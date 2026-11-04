# Sony FX30 firmware 6.01 — unpacking & feature survey

Notes and tools for decrypting the official Sony FX30 (ILME-FX30) firmware update
`BODYDATA.DAT` and looking for dormant features (8K recording, open gate, 4:4:4, pixel shift).
Nothing here touches a camera; it is all offline analysis of the update file.

## Layout

```
BODYDATA.DAT                 original Sony update file (UFU container, encrypted)
tools/
  decrypt_fdat.py            UFU -> decrypted FDAT (UDTRFIRM) image
  fdat_to_tar.py             decrypted FDAT -> firmware.tar
  sgrep.py                   regex search over printable strings in a file or tree
  fx30_service_probe.py      USB service-mode read-only probe (MSC 0E0E -> service 0336 + HASP)
  fx30_burst.py              hidden burst-mode toggle/rollback helper for BK4 settings container
  fx30_pixel_shift.py        session-only pixel-shift BK4 probe (0x603/4, no save)
  fx30_8k.py                  XAVC HS 8K probe / forced RAM-only experiment
  test_pixel_shift_offline.py  synthetic + real-profile tests for the probe
  test_8k_offline.py         offline 8K file-format patch tests
  setup_service_deps.sh      fetch transport/pmca into deps/ and install pyusb
extracted/
  firmware_tar/              contents of firmware.tar
  nflasha15_usr/             /usr  (ext4) — lib/appFw.so is the main camera app
  nflasha7_root/             root filesystem (ext4)
notes/
  appFw_strings.txt          `strings -n 6` of appFw.so
  feature-manager-a7iv-602.json   per-product feature table decoded from the A7 IV 6.02
                             build by leogenot/sony-a7iv-feature-research (for comparison)
updates/
  pixel_shift_nonpersistent/ payload.json, README.md, TEST_PLAN.md, RESULT.md, REMOTE_TOOL_PLAN.md
  8k_video/                  findings, property map, probe/forced-write notes
```

`fdat.bin` and `firmware.tar` (about 860 MB each) are not kept. Regenerate them with the steps below.

## Reproducing from scratch

Requirements: Python 3, `pycryptodomex`, and `e2fsprogs` (for `debugfs`) on macOS.

```bash
python3 -m venv venv
```

```bash
./venv/bin/pip install pycryptodomex
```

```bash
brew install e2fsprogs
```

For the service-channel tools (`fx30_service_probe.py`, `fx30_burst.py`,
`fx30_pixel_shift.py`), run the dependency setup once:

```bash
./tools/setup_service_deps.sh
```

It sparse-clones the Sony runtime (`transport.py`, `core.py`, `vendor/pmca`)
into the gitignored `deps/` directory and installs `pyusb`/`libusb-package` into
`venv`. Without it the tools fail at `ModuleNotFoundError: No module named 'usb'`.
Use `./venv/bin/python` for those tools; bare `python3` may be a different
interpreter without the packages.

### 1. Decrypt the update

`BODYDATA.DAT` is a `\x89UFU\r\n\x1a\n` chunk container with `DATV`, `PROV`, `UDID`
(list of Sony USB product IDs the update accepts) and `FDAT` chunks. The `FDAT`
payload is encrypted with the 4th-gen "CXD90057_k8" scheme:

* data is split into 1024-byte blocks; the last 0x110 bytes of the chunk are a trailer,
  whose first 16 bytes are the CBC IV;
* the first 512 bytes of block 0 are AES-128-ECB with the common Sony key, everything
  after that is one continuous AES-256-CBC stream with the CXD90057_k8 key;
* each decrypted block starts with `u16 checksum, u16 size|0x8000(last)`, followed by the payload.

The keys and algorithm come from the `a7iv` branch of
[DavidBuchanan314/fwtool.py](https://github.com/DavidBuchanan314/fwtool.py)
(`fwtool/sony/fdat.py`, `constants.py`). `tools/decrypt_fdat.py` is a minimal
standalone reimplementation of that code.

```bash
./venv/bin/python tools/decrypt_fdat.py BODYDATA.DAT fdat.bin
```

Expected output: `header magic: b'UDTRFIRM'` … `ok, last-flag True bytes 903077376`.

### 2. Extract firmware.tar

```bash
python3 tools/fdat_to_tar.py fdat.bin firmware.tar
```

Expected output: `version 6.01  model 0x11030082`, tar at offset `0x132200`.

```bash
mkdir -p extracted/firmware_tar && tar xf firmware.tar -C extracted/firmware_tar
```

### 3. Dump the partition images

`extracted/firmware_tar/0700_part_image/dev/` contains:

| image | type | contents |
|---|---|---|
| `nflasha15` | ext4 | `/usr`: `lib/appFw.so`, `codec/`, `kmod/`, `share/` |
| `nflasha7`  | ext4 | root fs, `version.txt` = `31182_15.2025122501` |
| `nflasha3`, `nflasha8` | FAT | `/system`, `/cp` coprocessor files |
| `nflasha5`  | WBI2 | boot/kernel image |

```bash
D=extracted/firmware_tar/0700_part_image/dev
```

```bash
mkdir -p extracted/nflasha15_usr && /opt/homebrew/opt/e2fsprogs/sbin/debugfs -R "rdump / $PWD/extracted/nflasha15_usr" $D/nflasha15
```

```bash
mkdir -p extracted/nflasha7_root && /opt/homebrew/opt/e2fsprogs/sbin/debugfs -R "rdump / $PWD/extracted/nflasha7_root" $D/nflasha7
```

The "Operation not permitted while changing ownership" messages are harmless (they come from running as non-root).

### 4. Search

```bash
python3 tools/sgrep.py extracted/nflasha15_usr/lib/appFw.so 'pixel_shift' 'raw_output'
```

`LIMIT=200` raises the per-file hit limit. Note: on this machine `grep` is aliased to
ugrep, which parses `-i'…'` patterns differently. Use `sgrep.py` or `command grep`.

## Findings (firmware 6.01)

* **Product class:** the FX30 runs the shared Sony app as `PRODUCT_MODEL_LAX`
  (Cinema Line, IMX684, no mechanical shutter). The settings profiles are under
  `0110_backup/SYSIPSX-DSLR/LAX/`. This build defines 9 product classes:
  LS, YT, GL, LAX, ALCIN_UUD, SA, DZ, YS, GS.
* **Service channel:** `extracted/nflasha15_usr/bin/adjstctl.elf` implements the Jiritsu
  commands (`JIRITSU_SET_FILE`, `GET_FILE`, `FIRMUP`, …). The A7 IV and A7S III research
  uses this USB channel (via Sony-PMCA-RE service mode). It is untested on the FX30.

| Feature | Verdict | Evidence |
|---|---|---|
| Pixel shift | Implementation present; menu-gated | Full Pixel Shift Multi Shoot implementation present: `model::sequence_start_pixel_shift_multi_shoot`, `sequence_still_record::pixel_shift_multi_shoot_*`, remote setters (`set_remote_px_shift_multi_shoot_mode/number/interval`), and value enums for off/4-image/16-image modes. Gating clues in strings now include `PRM_setting_px_shift_multi_shoot`, `PRM_HAITA_setting_still_shutter_type_setting_px_shift_multi_shoot` (electronic still shutter requirement), per-product menu type `VAL_FEATURE_MANAGER_menu_item_TYPE_MENU_ITEM_LAX`, and a second exclusion path `PRM_HAITA_setting_wireless_flash_wireless_function_for_flash_signal_communications_external_flash_communication_type_setting_px_shift_multi_shoot`. Backup IDs (`BKID_APP_setting_px_shift_multi_shoot`, `BKID_APP_MR_setting_px_shift_multi_shoot`) plus 4/16-image BKIDs show a persisted setting path. On-camera result: the Drive Mode menu did not expose it; writing the 4-image value caused a still-image init boot loop (next row). |
| Pixel shift + autofocus | **Not possible / crash loop** | Attempting pixel shift on the FX30 led to a boot loop: photo mode → IBIS/sensor clunk → black screen → reboot, with a brief “Pixel Shift Multi Shoot is not available” modal. It reproduced without a lens, and the Drive Mode menu never showed a pixel-shift entry. Recovery: RAM-only snapshot restore followed by battery removal/cold boot; `--persist` was **not** needed. Do not enable pixel shift with AF on this body. |
| 8K video (XAVC HS 8K) | **Not viable on FX30** | Shared app has the full XAVC HS 8K format path and BKID properties (`0x02cf01f7` file_format=5, `0x02cf01f9` frame rate, `0x02cf0205/207` record settings, SQ variants `0x02cf0233/241/243`). All 11 LAX profiles contain them, but `file_format` defaults to `0x08` (XAVC S HD), and the 26.1 MP IMX684 cannot produce native 8K UHD (~33.2 MP). Probe with `tools/fx30_8k.py`; do not persist. See `updates/8k_video/README.md`. |

## Merged findings and tools from Lincan research (translated)

The following practical findings from
[Lincan19540/fx30-firmware-research](https://github.com/Lincan19540/fx30-firmware-research)
are now merged into this repository as local tools:

| Item | Summary | Local tool |
|---|---|---|
| Service-mode connection chain | Confirmed host-side flow from FX30 MSC identity (`054C:0E0E`) to Sony service identity (`054C:0336`), including Senser auth and HASP token read (expected length: 88 bytes). | `tools/fx30_service_probe.py` |
| Hidden burst mode toggle + rollback | Verified approach to write a paired two-byte BK4 setting change, recalculate bank checksum, validate readback, and rollback to single-shot mode. | `tools/fx30_burst.py` |

### Safety notes for the merged tools

* Both scripts are for research only and assume your own legal/risk review.
* `fx30_service_probe.py` is intended as read-only service-channel probing.
* `fx30_burst.py` performs writes to the settings container (BK4), **not** firmware partitions; follow the script safeguards and always keep snapshots for rollback.
* After any BK4 write test, do a full cold restart (disconnect USB and remove battery briefly) before evaluating camera behavior.

## Prepared non-persistent pixel-shift probe

`tools/fx30_pixel_shift.py` implements the session-only probe from next step 3.
It reads the live BK4 container, patches the 1-byte
`BKID_APP_setting_px_shift_multi_shoot` property (`0x02cf02ca`: `00` off,
`01` 4 images, `02` 16 images), recomputes the bank checksum, and writes with
`0x603/4`. It does **not** send `0x603/3` (`save`) by default, but that did
**not** prove non-persistence on this body: the camera later synced the dirty
container, and the value survived a power-off. A hard reboot can persist an
experimental value; restore the pre-write snapshot first and, if stable, save
the restored known-good state before rebooting. See
[RESULT.md](updates/pixel_shift_nonpersistent/RESULT.md) and
[RECOVERY.md](updates/pixel_shift_nonpersistent/RECOVERY.md).

Validated offline against all 11 `0110_backup/SYSIPSX-DSLR/LAX/*.bin` profiles:
the property is 1 byte, attr `0x60`, default `00`, and a `00`→`01` patch changes
only the property byte plus the checksum. The FX30 defaults are already
`still_shutter_type` = electronic (`0x02cf02d4` = `01`) and
`wireless_flash` = off (`0x02cf0356` = `00`), so the probe leaves both alone.
The `BKID_APP_MR_*` mirrors are 4-byte arrays, not single settings, and are also
left untouched. Run `python3 tools/test_pixel_shift_offline.py` for the
synthetic + real-profile regression tests.

Usage, evidence, limits and the camera checklist:
[updates/pixel_shift_nonpersistent/README.md](updates/pixel_shift_nonpersistent/README.md)
and [updates/pixel_shift_nonpersistent/TEST_PLAN.md](updates/pixel_shift_nonpersistent/TEST_PLAN.md).

First camera run (2026-11-04): the one-byte RAM write and readback succeeded, but
the Drive Mode menu did not change. The drive-mode enum has no pixel-shift value;
the property is the setting value, not the menu registration. The camera then
boot-looped in Photo mode after a power-off. A **RAM-only snapshot restore**
followed by **battery removal / cold boot** cleared the loop; `--persist` was
not used and was not necessary. The camera is usable in Movie mode (an OSS lens
widens the boot window). Verify `0x02cf02ca = 00` before switching to Photo; if
it is `01`, clear it with Setting Reset or a saved snapshot. See
[RECOVERY.md](updates/pixel_shift_nonpersistent/RECOVERY.md) and
[RESULT.md](updates/pixel_shift_nonpersistent/RESULT.md). The design and build
plan for the remote/PTP path is in
[REMOTE_TOOL_PLAN.md](updates/pixel_shift_nonpersistent/REMOTE_TOOL_PLAN.md).

### 8K video (XAVC HS 8K) — investigated, not viable

The shared app has the complete XAVC HS 8K format path and BKID properties:
`0x02cf01f7` (`file_format`, `5` = XAVC HS 8K), `0x02cf01f9` (8K frame rate),
`0x02cf0205`/`0x02cf0207` (8K record settings), plus SQ variants. All 11 LAX
profiles contain them, but `file_format` defaults to `0x08` (XAVC S HD). The
shared UI has the `STRID_FUNC_MOVIE_FORMAT_SET_XAVCHS_8K` Movie Format value
and its guide, but there is no separate top-level `STRID_MENU_*8K*` item; 8K is
a value of the Movie/File Format menu, not an independent mode. The FX30/LAX
menu does not expose it. The 26.1 MP IMX684 cannot produce native 8K UHD
(~33.2 MP); this is shared code for 8K-capable bodies. `tools/fx30_8k.py` is a
read-only probe with an explicit `--force-unsupported` RAM-only experiment; it
refuses `--persist`. Details:
[updates/8k_video/README.md](updates/8k_video/README.md).

## Next steps

1. Confirm the exact call chain in `appFw.so`: disassemble call sites of
   `PRM_FEATURE_MANAGER_menu_item` (getter `0x183ee0c`) and
   `PRM_HAITA_setting_still_shutter_type_setting_px_shift_multi_shoot` to identify
   where `TYPE_MENU_ITEM_LAX` suppresses pixel-shift menu exposure.
2. Trace both HAITA exclusion paths for pixel shift (`...still_shutter_type...` and
   `...wireless_flash...setting_px_shift_multi_shoot`) and map which menu state each one blocks.
3. ~~Implement a **non-persistent first** probe in service mode: test a session-only
   update path for pixel-shift-related settings and verify behavior reverts after a reboot.~~
   Implemented as `tools/fx30_pixel_shift.py` and run on the camera: the one-byte
   RAM write and readback succeeded, but the Drive Mode menu did not change. See
   [RESULT.md](updates/pixel_shift_nonpersistent/RESULT.md).
4. Do **not** persist `0x02cf02ca`: it is the pixel-shift value, not the menu
   registration. The drive-mode enum has no pixel-shift entry.
5. Build the remote/PTP tool described in
   [REMOTE_TOOL_PLAN.md](updates/pixel_shift_nonpersistent/REMOTE_TOOL_PLAN.md):
   read-only code/property enumeration first, then set mode / test mode, then
   start/cancel and event capture.
6. Only if the remote path is understood, consider persisted settings or other
   changes; back up first and expect warranty risk.

## References

* [leogenot/sony-a7iv-feature-research](https://github.com/leogenot/sony-a7iv-feature-research): method, product-class tables, open gate notes
* [DavidBuchanan314/fwtool.py `a7iv` branch](https://github.com/DavidBuchanan314/fwtool.py): FDAT keys and format
* [DavidBuchanan314/ILCE-7M4-RE](https://github.com/DavidBuchanan314/ILCE-7M4-RE)
* [ma1co/Sony-PMCA-RE](https://github.com/ma1co/Sony-PMCA-RE): USB service mode
* [Sony Alpha Rumors: A7S III Variable Shutter / BIG6 hack](https://www.sonyalpharumors.com/the-hacking-continues-variable-shutter-and-big6-added-on-the-sony-a7s-iii/)
