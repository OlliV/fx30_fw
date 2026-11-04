# Result: session-only mode write succeeded, menu unchanged

> **Recovered on 2026-11-04 without a settings reset:** attaching an OSS lens
> slowed the boot enough to switch to Movie mode, which does not run the
> still-image/pixel-shift path. See [RECOVERY.md](RECOVERY.md) for the method
> and the caveat that the persisted value still needs verification.

Date: 2026-11-04
Camera: ILME-FX30, firmware 6.01 (`31182_15.2025122501`)
Mode: service channel, BK4 write in RAM only (no `0x603/3` save)

## Recovery

The camera boot-looped in Photo mode after the write and a normal power-off.
Attempts to reset via the menu failed because the camera rebooted immediately.
A RAM-only `--restore` was written; **`--persist` was not used**. A later
battery removal / cold boot cleared the loop. The camera was then usable by:

1. Attaching a lens with optical image stabilization (OSS).
2. Powering on; the OSS lens lengthened the boot window.
3. Switching to **Movie** mode before the still-image initialization crashed.
4. Movie mode stayed up; no settings reset was needed for the camera to work.

No `--persist` was needed for this recovery. The exact mechanism is not fully
proven: the camera may have synced the restored `00` itself, or the cold boot
cleared the warm-boot state. Verify with a read-only `--probe`; if
`0x02cf02ca` is still `01`, clear it before switching back to Photo mode.

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

## Why it persisted (important)

Although the tool did not send `0x603/3`, the mode `01` value survived a normal
power-off and battery removal. The camera most likely flushed the dirty BK4
container on shutdown/reboot, or the write landed in the live store rather than
a purely volatile buffer.

Therefore:

- “No save command” is **not** proof of “RAM-only.”
- A hard reboot can **persist** the experimental value instead of discarding it.
- The safe rollback order is: restore the pre-write snapshot, then **cold boot**
  (battery out). In the observed recovery, `--persist` was **not** needed; save
  the restored state only if `01` survives the cold boot.

This is why the recovery path starts with a snapshot restore, not “just
power-cycle it.” A cold boot after the restore cleared the loop; a cold boot on
the experimental value did not.

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

- The one-byte write and readback worked, but the **persistence assumption
  failed**: the camera synced the dirty container even without `0x603/3`.
- The menu blocker is **menu registration / product-class gating**, not the
  value property.
- **Pixel shift with autofocus is not usable on this body**: attempting it
  triggers the still-image init boot loop. Do not enable it with AF.
- Do **not** persist mode `01`. In the observed recovery, no `--persist` was
  needed: a RAM-only snapshot restore followed by battery removal/cold boot was
  sufficient. If `01` survives a cold boot, use Setting Reset or save the
  restored snapshot.

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

To roll back, restore the pre-write snapshot, then **cold boot** (battery out
for at least 30 s). In the observed recovery, `--persist` was not needed. If
`01` survives the cold boot, use **Setting Reset → Camera Settings Reset** or
save the restored snapshot, then cold boot again. A hard reboot on the
experimental value can persist it instead of clearing it.

A detailed design and build plan for the remote path — transports, firmware
hooks, unknown PTP codes to recover, phases, tool CLI, test matrix and stop
conditions — is in [REMOTE_TOOL_PLAN.md](REMOTE_TOOL_PLAN.md).
