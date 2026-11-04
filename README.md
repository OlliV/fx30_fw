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
extracted/
  firmware_tar/              contents of firmware.tar
  nflasha15_usr/             /usr  (ext4) — lib/appFw.so is the main camera app
  nflasha7_root/             root filesystem (ext4)
notes/
  appFw_strings.txt          `strings -n 6` of appFw.so
  feature-manager-a7iv-602.json   per-product feature table decoded from the A7 IV 6.02
                             build by leogenot/sony-a7iv-feature-research (for comparison)
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
| Pixel shift | Possible | Full Pixel Shift Multi Shoot implementation present: `model::sequence_start_pixel_shift_multi_shoot`, `sequence_still_record::pixel_shift_multi_shoot_*`, remote setters (`set_remote_px_shift_multi_shoot_mode/number/interval`), and value enums for off/4-image/16-image modes. Gating clues in strings now include `PRM_setting_px_shift_multi_shoot`, `PRM_HAITA_setting_still_shutter_type_setting_px_shift_multi_shoot` (electronic still shutter requirement), per-product menu type `VAL_FEATURE_MANAGER_menu_item_TYPE_MENU_ITEM_LAX`, and a second exclusion path `PRM_HAITA_setting_wireless_flash_wireless_function_for_flash_signal_communications_external_flash_communication_type_setting_px_shift_multi_shoot`. Backup IDs (`BKID_APP_setting_px_shift_multi_shoot`, `BKID_APP_MR_setting_px_shift_multi_shoot`) plus 4/16-image BKIDs show a persisted setting path. |

## Next steps

1. Confirm the exact call chain in `appFw.so`: disassemble call sites of
   `PRM_FEATURE_MANAGER_menu_item` (getter `0x183ee0c`) and
   `PRM_HAITA_setting_still_shutter_type_setting_px_shift_multi_shoot` to identify
   where `TYPE_MENU_ITEM_LAX` suppresses pixel-shift menu exposure.
2. Trace both HAITA exclusion paths for pixel shift (`...still_shutter_type...` and
   `...wireless_flash...setting_px_shift_multi_shoot`) and map which menu state each one blocks.
3. Implement a **non-persistent first** probe in service mode: test a session-only
   update path for pixel-shift-related settings and verify behavior reverts after a reboot.
4. Only if the non-persistent path is understood, evaluate the persisted backup
   property route (`BKID_APP_setting_px_shift_multi_shoot`,
   `BKID_APP_setting_px_shift_multi_shoot_4_images_shooting`,
   `BKID_APP_setting_px_shift_multi_shoot_16_images_shooting`), following
   `leogenot/sony-a7iv-feature-research` docs `SERVICE_MODE.md` / `SHUTTER_ANGLE.md`.
5. Only then, on a real camera: back up the settings first, test read-only, and expect warranty risk.

## References

* [leogenot/sony-a7iv-feature-research](https://github.com/leogenot/sony-a7iv-feature-research): method, product-class tables, open gate notes
* [DavidBuchanan314/fwtool.py `a7iv` branch](https://github.com/DavidBuchanan314/fwtool.py): FDAT keys and format
* [DavidBuchanan314/ILCE-7M4-RE](https://github.com/DavidBuchanan314/ILCE-7M4-RE)
* [ma1co/Sony-PMCA-RE](https://github.com/ma1co/Sony-PMCA-RE): USB service mode
* [Sony Alpha Rumors: A7S III Variable Shutter / BIG6 hack](https://www.sonyalpharumors.com/the-hacking-continues-variable-shutter-and-big6-added-on-the-sony-a7s-iii/)
