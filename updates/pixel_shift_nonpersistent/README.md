# Pixel Shift Multi Shoot — non-persistent probe (FX30 6.01)

> **Boot loop reported after the first camera run: see [RECOVERY.md](RECOVERY.md)
> before doing anything else. Stop writes; do not use `--persist`.**

This package prepares a **session-only** test of the FX30 Pixel Shift Multi
Shoot path. It writes one BK4 setting byte in RAM and deliberately does not
persist it. A cold boot is the rollback.

It is an experiment, not a feature unlock. The shared Sony app still contains
the product-class (`TYPE_MENU_ITEM_LAX`) gating that can hide the menu entry, so
the first question is whether changing the live setting has any visible effect
at all.

**First camera result (2026-11-04):** the non-persistent write worked and
readback verified, but the Drive Mode menu did **not** change. The drive-mode
enum has no pixel-shift value, so this byte is the setting value, not the menu
registration. See [RESULT.md](RESULT.md) before running another test; do not
persist the byte.

## What changes

Exactly one 1-byte BK4 property, plus the bank checksum:

| Property | Name | Value | Meaning |
|---|---|---|---|
| `0x02cf02ca` | `BKID_APP_setting_px_shift_multi_shoot` | `01` | 4-image Pixel Shift Multi Shoot |

`02` selects 16 images; `00` is off. The property is 1 byte, attr `0x60`, in
bank 0 of all 11 `0110_backup/SYSIPSX-DSLR/LAX/*.bin` profiles. Its default
is `00`.

The tool can optionally set the interval option as well:

| Property | Name | Values |
|---|---|---|
| `0x02cf04d7` | `..._px_shift_multi_shoot_4_images_shooting` | `00` shortest, `01` 1 s, … `08` 30 s |
| `0x02cf04d9` | `..._px_shift_multi_shoot_16_images_shooting` | same enum |

## What does not change

* **No flash setting.** The FX30 has no flash support. `BKID_APP_setting_wireless_flash`
  (`0x02cf0356`) is already `00` (off) in every LAX profile.
* **No mechanical-shutter setting.** The FX30 has no mechanical shutter.
  `BKID_APP_setting_still_shutter_type` (`0x02cf02d4`) is already `01`
  (electronic) in every LAX profile. The generic `PRM_HAITA_...still_shutter_type...`
  and `...wireless_flash...` exclusions are shared-app gates, not FX30 levers.
* **No MR mirrors.** `BKID_APP_MR_setting_px_shift_multi_shoot` (`0x02cf02cb`)
  and the interval MR mirrors are 4-byte arrays, not single settings. They are
  left untouched.
* **No firmware partitions.** Only the BK4 settings container is written.
* **Nothing persistent by default.** The service call `0x603/4` changes the
  in-memory container; `0x603/3` (`bk s` / `save`) is what writes it to storage.
  This tool never sends `0x603/3` unless you explicitly pass `--persist`.

## Why this is the right first probe

The firmware evidence is:

* Generated name records in `appFw.so` resolve
  `BKID_APP_setting_px_shift_multi_shoot` to internal id `0x02ca`, i.e. property
  `0x02cf02ca`.
* All 11 LAX regional profiles contain that property as a 1-byte `0x60` setting
  with value `00`; the four interval/MR variants are present too.
* The full runtime path exists (`sequence_start_pixel_shift_multi_shoot`,
  `sequence_still_record::pixel_shift_multi_shoot_*`, remote setters), but the
  menu exposure is a separate shared-app decision.

The non-persistent write isolates the question “does the live setting change
behaviour?” from “does a persistent edit survive and alter the menu?”.

## Files

| File | Purpose |
|---|---|
| `tools/setup_service_deps.sh` | fetch `transport`/`pmca` into `deps/`, install pyusb |
| `tools/fx30_pixel_shift.py` | probe / apply / restore / offline patcher |
| `tools/test_pixel_shift_offline.py` | synthetic + real-profile regression tests |
| `updates/pixel_shift_nonpersistent/payload.json` | explicit 4-image payload |
| `updates/pixel_shift_nonpersistent/TEST_PLAN.md` | camera session checklist |

## Prerequisites

* FX30 on firmware **6.01**, USB connection set to **MSC** (`054C:0E0E`).
* Run the dependency setup once from the repo root:

  ```bash
  ./tools/setup_service_deps.sh
  ```

  It installs `pyusb`/`libusb-package` into `./venv` and sparse-clones the Sony
  runtime (`transport.py`, `core.py`, `compat.py`, `macos_host.py`,
  `vendor/pmca`) into the gitignored `deps/` directory, which `fx30_burst.py`
  searches by default. If you keep the runtime elsewhere, set `FX30_DEPS` to
  the directory containing `transport.py` and `vendor/pmca`.
* Use `./venv/bin/python`. Bare `python3` is often a different interpreter
  without the packages and fails with `ModuleNotFoundError: No module named 'usb'`.
* macOS needs `sudo` for USB access.
* A free `fx30_dump/` directory for snapshots (created automatically).

The service session takes about 30–60 s: MSC identity → Senser auth → service
identity `054C:0336` → HASP read.

The underlying operation is the same as PMCA `serviceshell`'s
`bk w 0x02cf02ca 01`: it writes the in-memory backup property. The tool adds the
snapshot, checksum recalculation, readback verification and automatic RAM
restore. If you use the shell directly, do **not** issue `bk s`.

## Run

### 1. Read and snapshot (no write)

```bash
sudo -E ./venv/bin/python tools/fx30_pixel_shift.py --probe
```

Record the printed values and keep the `fx30_dump/pixel_shift_snapshot_*.bin`
file. Confirm `0x02cf02ca` is `0x00` before the test.

### 2. Apply 4-image mode in RAM only

```bash
sudo -E ./venv/bin/python tools/fx30_pixel_shift.py --apply --mode 4 --yes
```

The tool reads the live BK4, snapshots it, patches `0x02cf02ca` to `01`,
recomputes the bank checksum, writes with `0x603/4`, and re-reads. Success looks
like:

```
--- write (0x603/4, no save) ---
  (no 0x603/3 save sent; this is the non-persistent path)
--- readback verification ---
  all 1 target byte(s) verified
  BK4 checksums: OK
Session-only write complete.
```

If the write is rejected (`res=129`) or the readback does not stick, stop. The
tool writes the pre-write snapshot back in RAM automatically on a failed
readback.

### 3. Test on the camera

Follow [TEST_PLAN.md](TEST_PLAN.md). The key checks are whether the Drive Mode
menu exposes Pixel Shift Multi Shoot, whether the camera accepts a 4-shot
sequence, and whether the resulting files are grouped as a pixel-shift set.

### 4. Cold-boot revert

Power off, disconnect USB, remove the battery for at least 30 s, reinsert, and
run `--probe` again. `0x02cf02ca` should be back to `00`. If the behaviour
persists after a cold boot, the write was not session-only on this firmware —
stop and record that result before doing anything else.

### 16-image variant

```bash
sudo -E ./venv/bin/python tools/fx30_pixel_shift.py --apply --mode 16 --interval shortest --yes
```

### Restore a snapshot in RAM

```bash
sudo -E ./venv/bin/python tools/fx30_pixel_shift.py --restore fx30_dump/pixel_shift_snapshot_XXXX.bin
```

This writes the snapshot back without saving. A cold boot is still the final
rollback.

### Offline validation (no camera)

```bash
python3 tools/fx30_pixel_shift.py \
  --offline extracted/firmware_tar/0110_backup/SYSIPSX-DSLR/LAX/CX96700_J1.bin \
  --out /tmp/CX96700_J1.pixel_shift_4img.bin --mode 4

python3 tools/test_pixel_shift_offline.py
```

The real-profile test checks that the patch changes only the property byte and
the bank checksum (two bytes total for a `00`→`01` edit) and leaves the MR and
interval bytes alone.

## Limits and next steps

* The menu may stay hidden because `PRM_FEATURE_MANAGER_menu_item` returns
  `TYPE_MENU_ITEM_LAX` for the product class. That is compile-time gating and
  cannot be changed by a BK4 byte.
* If nothing changes until a reboot, the running model did not pick up the
  in-memory container write. A cold boot will then discard it, so that variant
  cannot be tested session-only. Record that result and move to the runtime
  test-shooting/remote path rather than saving the byte.
* `PRM_pixel_shift_multi_shoot_test_shooting_mode` is a runtime-only property
  with no `BKID_APP_*` record and no identified BK4 slot. The tool does not guess
  at it. `--list` prints the nearby BK4 range if you have independent evidence
  for an ID; `--extra ID=VAL --allow-unknown` can test that ID explicitly.
* If the setting alone produces no visible change, the next experiment is the
  runtime test-shooting/remote path (PTP or the HAITA-style command interface),
  not a persistent BK4 edit. The design and build steps for that remote tool are
  in [REMOTE_TOOL_PLAN.md](REMOTE_TOOL_PLAN.md).

## Safety

* Research use only; warranty and bricking risk.
* Back up the settings and keep the snapshots.
* Do not pass `--persist` for the first test. It sends `0x603/3` and survives a
  cold boot.
* Do not interrupt USB power during a write.
* If the camera behaves abnormally, power off, disconnect USB, remove the
  battery for at least 30 s, and restore the snapshot in RAM before retrying.
