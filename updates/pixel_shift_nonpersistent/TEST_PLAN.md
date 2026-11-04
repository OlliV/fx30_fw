# Camera test plan — FX30 Pixel Shift Multi Shoot (session-only)

One change per session. Record everything; a negative result is still a result.
The write is **not** saved, so a cold boot must bring the original value back.

## Preconditions

- [ ] FX30 on firmware **6.01** (`version.txt` = `31182_15.2025122501`).
- [ ] Battery at least 50 %, card formatted, clock set.
- [ ] Still-image mode (not Movie / S&Q).
- [ ] Drive mode = Single before the test.
- [ ] Electronic shutter (FX30 default; no mechanical shutter on this body).
- [ ] No flash attached / flash disabled (FX30 has no flash support).
- [ ] Tripod, static high-detail scene, steady light.
- [ ] Steady-shot / IBIS off if the camera allows it for the test.
- [ ] USB connection mode = **MSC**; camera not mounted by another app.
- [ ] `fx30_dump/` exists and has room for 2.25 MB snapshots.

## 0. Baseline (read-only)

```bash
sudo -E PYTHONPATH="$FX30_DEPS:$FX30_DEPS/vendor" \
  python3 tools/fx30_pixel_shift.py --probe
```

- [ ] `0x02cf02ca` = `0x00` (off).
- [ ] `0x02cf04d7` / `0x02cf04d9` values recorded.
- [ ] Snapshot file name and sha256 recorded.
- [ ] MENU → Shooting → Drive Mode options photographed/recorded **before** any
      write. This is the baseline for “did the menu change?”.

## 1. Apply 4-image mode (RAM only)

```bash
sudo -E PYTHONPATH="$FX30_DEPS:$FX30_DEPS/vendor" \
  python3 tools/fx30_pixel_shift.py --apply --mode 4 --yes
```

- [ ] Readback verification passed (`all 1 target byte(s) verified`).
- [ ] No `0x603/3` save line in the output.
- [ ] Camera did not disconnect or reboot during the write.

## 2. Observe without rebooting

Do not power-cycle yet. Check, in this order:

1. [ ] MENU → Shooting → Drive Mode: does **Pixel Shift Multi Shoot** appear?
2. [ ] If it appears, select **4 images**. Does the camera show the pixel-shift
       guide / “compose the shot” message?
3. [ ] Press the shutter once. Does the camera take four exposures?
4. [ ] Do the four files appear as one grouped pixel-shift set (same group id)?
5. [ ] If the menu does **not** appear, try the Drive Mode button/dial and the
       Fn menu. Record exactly where it is still hidden.
6. [ ] Try a normal single shot to confirm the camera still behaves normally.

Record:

| Observation | Result |
|---|---|
| Drive Mode menu entry visible? | yes / no |
| 4-shot sequence triggered? | yes / no / error |
| Files produced (count, names) | |
| Grouped as pixel-shift set? | yes / no |
| Any error message / beep / freeze | |
| Camera temperature / unusual behaviour | |

## 3. Cold-boot revert

1. [ ] Power off, disconnect USB.
2. [ ] Remove the battery for at least 30 s.
3. [ ] Reinsert, power on, reconnect USB in MSC.
4. [ ] Run `--probe` again.

- [ ] `0x02cf02ca` is back to `0x00`.
- [ ] The Drive Mode menu no longer shows Pixel Shift Multi Shoot.
- [ ] A normal single shot still works.

If the value or the behaviour survives the cold boot, **stop**. That means the
write was not session-only on this firmware; record it and do not repeat until
the persistence path is understood.

## 4. Optional 16-image run

Only after the 4-image run has been reverted and the camera is confirmed normal:

```bash
sudo -E PYTHONPATH="$FX30_DEPS:$FX30_DEPS/vendor" \
  python3 tools/fx30_pixel_shift.py --apply --mode 16 --interval shortest --yes
```

Repeat sections 2–3. A 16-image run takes longer and produces 16 frames; watch
battery and heat.

## 5. Rollback / cleanup

- Normal rollback: cold boot (section 3).
- Immediate rollback without a reboot:

```bash
sudo -E PYTHONPATH="$FX30_DEPS:$FX30_DEPS/vendor" \
  python3 tools/fx30_pixel_shift.py --restore fx30_dump/pixel_shift_snapshot_XXXX.bin
```

- Persistent rollback (only if you deliberately used `--persist`):
  add `--persist --yes` to the restore command, then cold-boot and verify.

## Abort criteria

Stop immediately and cold-boot if any of these happen:

- write rejected (`res=129`) or readback mismatch;
- camera freezes, reboots, or drops USB during/after the write;
- menu or settings look corrupted;
- unexpected heat, noise, or repeated actuator movement;
- the changed value survives a cold boot (persistence surprise).

Do not “try one more byte” in the same session. Revert, cold-boot, and reassess.

## Session log

| Field | Value |
|---|---|
| Date / time | |
| Firmware | 6.01 (`31182_15.2025122501`) |
| Body / serial (optional) | |
| Snapshot file + sha256 | |
| `0x02cf02ca` before / after | `00` / `01` |
| Menu entry visible | |
| 4-shot sequence | |
| Files / grouping | |
| Cold-boot value | `00` (expected) |
| Cold-boot menu | hidden (expected) |
| Notes | |
