# Result: session-only mode write succeeded, menu unchanged

> **Boot loop reported after this test: see [RECOVERY.md](RECOVERY.md) first.**
> Stop further writes and do not use `--persist`.

Date: 2026-11-04
Camera: ILME-FX30, firmware 6.01 (`31182_15.2025122501`)
Mode: service channel, BK4 write in RAM only (no `0x603/3` save)

## What was run

```bash
sudo -E ./venv/bin/python tools/fx30_pixel_shift.py --probe
sudo -E ./venv/bin/python tools/fx30_pixel_shift.py --apply --mode 4 --yes
```

Baseline `--probe`:

- MSC `054C:0E0E` → Senser auth → service `054C:0336` → HASP **88 B**.
- BK4 read: **2,253,564 B**, both bank checksums OK.
- `0x02cf02ca` = `00`, `0x02cf04d7` / `0x02cf04d9` = `00`,
  `0x02cf02d4` = `01` (electronic), `0x02cf0356` = `00` (flash off).
- Snapshot: `fx30_dump/pixel_shift_snapshot_20261104_153700.bin`.

Apply reported the single target byte `0x0916f2` `0x00 -> 0x01`, no `0x603/3`
save, and readback verification passed.

## What the camera showed

The Drive Mode menu still exposed only:

- single shooting
- self-timer
- the three bracketing modes

No Pixel Shift Multi Shoot entry appeared.

## Why this is the expected result

The BK4 property is the pixel-shift *value*, not the menu registration:

- `VAL_setting_menu_drive_mode_*` has 17 real values (plus `PRM_ALL`) and
  **none** is a pixel-shift value.
- The shared UI contains the label `Pixel Shift Multi Shoot.`
  (`string_english_f.uxc`) and guide/function strings such as
  `STRID_FUNC_PX_SHIFT_MULTI_SHOOT_SET_4_IMAGE` and
  `STRID_FUNC_PX_SHIFT_MULTI_SHOOT_GUIDE_*` (`area_check_data.dat`).
- No `STRID_MENU_*PIXEL*` / `STRID_MENU_*PX_SHIFT*` drive-mode item was found.

So the label/assets are present in the shared app, but the LAX product menu does
not register a drive-mode entry for it. Changing `0x02cf02ca` cannot add that
entry. This is consistent with the `PRM_FEATURE_MANAGER_menu_item` →
`TYPE_MENU_ITEM_LAX` product-class gating noted in the main README.

## Conclusion

- The non-persistent write mechanism works exactly as intended: one byte,
  checksum fixed, readback verified, no save.
- The blocker is **menu registration / product-class gating**, not the value
  property.
- Do **not** persist this byte. It has no visible effect on this build.

## Next viable paths

1. **Check the rest of the menu / Fn assignments** for a separate
   "Pixel Shift Multi Shoot" item (not Drive Mode). The UI has function labels,
   so it may be exposed elsewhere or not at all.
2. **Runtime test-shooting mode**
   (`PRM_pixel_shift_multi_shoot_test_shooting_mode`, values OFF/ON). This is a
   model/global test state, not a `BKID_APP_*` backup property. It needs a
   HAITA/PTP/remote invocation rather than `bk w`.
3. **Remote PTP path**: the app has
   `set_remote_px_shift_multi_shoot_mode/number/interval` and the corresponding
   remote events. A PC Remote PTP client could set the mode and request the
   sequence without the menu. This needs the vendor command/property codes.
4. Only if the runtime path is understood should a persistent BK4 edit be
   considered. A menu entry that is compiled out is not reachable by a setting
   byte.

The current RAM-only change should be rolled back with a cold boot:

1. Power off, disconnect USB.
2. Remove the battery for at least 30 s.
3. Reinsert, boot, reconnect, and run `--probe`; `0x02cf02ca` should be `00`.

A detailed design and build plan for the remote path — transports, firmware
hooks, unknown PTP codes to recover, phases, tool CLI, test matrix and stop
conditions — is in [REMOTE_TOOL_PLAN.md](REMOTE_TOOL_PLAN.md).
