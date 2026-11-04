# Boot-loop recovery — FX30 after the pixel-shift RAM write

Status: recovered on 2026-11-04; recovery method documented below
Context: the BK4 write was verified in RAM and no `0x603/3` save was sent, but the
camera went into a boot loop.

## Resolution: OSS lens + Movie mode (2026-11-04)

The camera was recovered **without a settings reset** by using a lens with
optical image stabilization to slow the boot just enough to switch the camera
to **Movie mode** before the still-image initialization crashed it.

Likely mechanism: the boot loop is in the still-image/pixel-shift sensor
initialization. Movie mode does not run that still-image path, so the camera
stays up. The OSS lens lengthens lens/IBIS initialization enough to give you a
window to press **MODE** and switch to Movie.

**2026-11-04 detail:** the successful recovery used a **RAM-only** `--restore`
followed by **battery removal / cold boot**. `--persist` was **not used and was
not necessary**. The battery removal erased the RAM copy, so the exact mechanism
is not fully proven: the camera may have synced the restored `00` itself, or the
cold boot cleared a transient warm-boot state. Verify `0x02cf02ca = 00`; only if
it is still `01` after a cold boot should you use Setting Reset or a saved
snapshot.

### If this happens again

1. Attach a lens with **optical image stabilization** (OSS/SteadyShot).
2. Power on.
3. As soon as the UI appears, press **MODE** and switch to **Movie**.
4. Stay in Movie mode. Do **not** switch to Photo until the pixel-shift value is
   cleared.
5. Verify/clear the setting:
   - Run a read-only `--probe`; `0x02cf02ca = 00` is safe. If it is still `01`
     after a cold boot, use **MENU → Setup → Reset/Save Settings → Setting
     Reset → Camera Settings Reset** (or **Initialize** if needed).
6. **Cold boot** into Photo mode (battery out for at least 30 s), not a normal
   restart, and verify.

### Warm reboot vs cold boot (2026-11-04)

After the fix, a **warm reboot** brought the loop back; removing the battery
(**cold boot**) cleared it. The FX30 has a warm-boot image (`nflasha5`), so a
warm reboot can restore a pre-fix state.

After clearing the pixel-shift value, do a full **cold boot** (battery out for
at least 30 s), not a normal restart. If a warm reboot still loops while a
read-only `--probe` shows `0x02cf02ca = 00`, the warm-boot image likely needs a
service reflash; use cold boots until that is done.

### Caveats

- This is a **timing workaround**, not proof that the persisted value is gone.
  Movie mode ducks the still-image init; Photo mode can loop again if
  `0x02cf02ca` is still `01`.
- A **Setting Reset** is optional cleanup, needed only if `01` survives a cold
  boot or if Photo mode loops.
- In the observed recovery, `--persist` was **not** needed: a RAM-only restore
  followed by battery removal/cold boot was sufficient.
- Do not persist the experimental mode. If you need to write again, write the
  known-good pre-write snapshot (`00`), not mode `01`.
- The OSS lens is not a permanent fix; it only widens the boot window.

### How to verify the current state

Read-only, if service mode is reachable:

```bash
sudo -E ./venv/bin/python tools/fx30_pixel_shift.py --probe
```

- `0x02cf02ca = 00` → the live container is clean; Photo mode should be safe.
  In the observed recovery, no `--persist` was needed.
- `0x02cf02ca = 01` → do not switch to Photo until you clear it (Setting Reset
  or a saved snapshot restore).

This reads the live container. After the 2026-11-04 battery removal it reflects
the persisted state. In the observed recovery, a RAM-only restore plus the
battery removal/cold boot was sufficient; `--persist` was not used and was not
necessary. If `01` survives a cold boot, then use Setting Reset or a saved
snapshot.

## First: stop

- Do **not** run `--apply` again.
- Do **not** persist mode `01`.
- If the camera is stable in service mode, restore the **pre-write snapshot**,
  then **cold boot** (battery out for at least 30 s). In the observed recovery,
  `--persist` was not needed. Only if `01` survives the cold boot should you use
  Setting Reset or save the restored snapshot.
- Do not repeatedly power-cycle. A hard reboot can persist the experimental
  state; restore the snapshot before rebooting.
- Do not open the camera or edit `BODYDATA.DAT`.

## 0. If it reaches photo mode, IBIS moves, then reboots

Observed on 2026-11-04: the camera reaches photo mode, the IBIS/sensor makes a
clunk (also without a lens), the display goes black, and the camera reboots.
No error code and no beep. The menu can appear briefly, but the camera reboots
immediately.

This is consistent with the boot path initializing the sensor/IBIS with the
pixel-shift value still active. The camera is not dead — it gets far enough to
show the UI. The goal is to reach **Setting Reset** before the crash, or to boot
in a mode that skips the shooting/IBIS initialization.

Additional observation: trying to disable SteadyShot at startup briefly shows a
modal saying **“Pixel Shift Multi Shoot is not available.”** That is strong
evidence the persisted value is active and the app is trying to reconcile it at
boot. The modal is also a possible window to break the state.

Try these in order. Give the camera a rest between attempts.

### 0.1 Dismiss the modal and change Drive Mode

As soon as the camera boots:

1. When the **“Pixel Shift Multi Shoot is not available”** modal appears, press
   the **center button** (or touch **OK**) immediately.
2. If it dismisses, press **Fn** (or the Drive Mode button) and select
   **Drive Mode → Single Shooting**. The drive-mode list may not show a pixel
   shift entry, but selecting Single can overwrite the active drive state.
3. If the camera is still alive, go straight to
   **MENU → Setup → Reset/Save Settings → Setting Reset → Camera Settings
   Reset**.
4. If the modal returns, try again with faster timing; pressing the center
   button repeatedly as the camera boots may get past it.

If the modal has a **Cancel** option that cancels pixel shift, choose that
instead of OK. If it only has OK, press OK.

### 0.2 Boot into playback mode (primary attempt)

Two variants; try both:

1. With the camera **off**, press and hold the **Playback** button, then power
   on while still holding it. Keep holding until the playback screen appears.
2. Power on normally, and press **Playback** immediately when the image/menu
   first appears, before the IBIS clunk.

If it stays in playback:

1. Press **MENU**.
2. Go to **Setup → Reset/Save Settings → Setting Reset**.
3. Choose **Camera Settings Reset** first.
4. If the loop continues, repeat and choose **Initialize** (this resets all
   settings, network and privacy notice; recorded images are retained).
5. Keep the battery in until the reset completes.

Sony's procedure:
[Setting Reset](https://helpguide.sony.net/ilc/2220/v1/en/contents/TP1000844002.html).

### 0.3 Hold MENU through boot

With the camera off, hold **MENU** while powering on and keep holding it until
the menu appears. If the menu stays up, go to
**Setup → Reset/Save Settings → Setting Reset** and reset. This is a timing
attempt, not a documented recovery mode.

### 0.4 Boot without the lens and card

Remove the lens and both memory cards, then power on. The IBIS clunk still
happens without a lens, so this may not help, but it removes lens/card
initialization from the boot path. If it stays up long enough, reset settings.

### 0.5 Catch the USB/service window

Connect USB **before** powering on, then run this in a loop on the Mac:

```bash
while true; do
  sudo -E ./venv/bin/python tools/fx30_pixel_shift.py --scan
  sleep 1
done
```

If `054C:0E0E` appears and stays up long enough, run **read-only** `--probe`.
Only if that succeeds should you consider `--restore` (see section 3B). If the
camera reboots during the service handshake, it will not work; stop.

A full service handshake normally takes tens of seconds, so this only works if
the boot window is longer than usual. Do not blind-write during a reboot.

### 0.6 If the scan shows 054C:0D68 or 054C:096F

These are intermediate Sony USB identities seen during normal-side
re-authentication after service mode (`deps/transport.py:260`: 0D68 -> 096F ->
MSC again). They are **not** an update mode. The official updater PIDs are
`0x033a` / `0x03e2`; do not flash based on `0x0D68`.

A `0x0D68` scan usually shows a HID interface (class `03/00/00`, one interrupt
IN endpoint, 8-byte reports). That is consistent with the auth-transition HID,
not PTP/MSC and not the updater.

- Leave USB connected and wait 30–60 s without replugging; the camera may
  re-enumerate as `0x0E0E` (possibly via `0x096F`).
- Run `--scan` again. If `0x0E0E` appears, run read-only `--probe`.
- If it stays at `0x0D68`/`0x096F`, you can try the low-level `StopSenser`
  request, which is the same vendor request `SonySenserAuthDevice.stop()` uses.
  It does not authenticate, read/write BK4, or touch firmware:

  ```bash
  sudo -E ./venv/bin/python tools/fx30_usb_recover.py --stop-senser --retries 5 --delay 2
  ```

  A `Pipe error` can be transient while the camera is mid-boot or re-enumerating;
  the retry loop re-finds the device each attempt. If every attempt stalls, the
  HID interface does not accept `StopSenser`, and more retries will not help.
  Then try a USB port reset once:

  ```bash
  sudo -E ./venv/bin/python tools/fx30_usb_recover.py --reset
  ```

  Then `--scan` again. If `0x0E0E` appears, stop and run read-only `--probe`.
  If not, the service window is not available; use the official service route.
  Do not flash based on `0x0D68`.

### 0.6.1 USB recovery result (2026-11-04)

- The `0x0D68` HID device appears only intermittently: attempts 1–3 found no
  Sony device, attempts 4–5 found `0x0D68`, and the final scan found none. That
  is consistent with the camera rebooting through the USB stack each cycle.
- `StopSenser` returned `Pipe error` on every attempt (five retries, 2 s apart).
  The HID interface does not accept that request; this is not a transient
  one-off.
- Conclusion: the USB/auth path is exhausted. Do not keep retrying `StopSenser`
  or USB resets. The remaining failure is the app-level boot loop, and the
  practical recovery is a Sony service settings reset/reflash.

### 0.7 Official reflash / service

If none of the above reaches the reset menu, use Sony's official firmware
recovery/service route (section 3A/3C). A settings reset is preferable; a
reflash/service reset is the fallback.

Do **not** start a firmware update while the camera is rebooting unless Sony's
official recovery procedure explicitly supports it. An interrupted update is
worse than the current boot loop.

### 0.8 If playback is unreachable

If the camera cannot be held in playback or in the menu, the last safe DIY
attempt is a **read-only** service catch. Start the probe first, then power the
camera on so the script is already waiting when `054C:0E0E` appears:

```bash
sudo -E ./venv/bin/python tools/fx30_pixel_shift.py --probe
```

If it completes, stop and report the output; do not write yet. If it fails
because the camera reboots during the handshake, the service window is too
short. At that point, stop DIY attempts and contact Sony service. The camera
still boots to the UI, so a service settings reset/reflash is the appropriate
recovery level; do not attempt a firmware update while it is rebooting.

## 1. Basic clean boot

Try these in order, one change at a time:

1. Power the camera off (hold the power switch if it does not respond).
2. Disconnect USB.
3. Remove the SD card.
4. Remove the lens.
5. Remove the battery.
6. With the battery out, hold the power button for ~30 seconds to drain residual
   power.
7. Wait 5–10 minutes.
8. Insert a **known-good, charged** battery. Leave the card and lens out.
9. Power on and observe.

If it boots without the card/lens:

- Power off, insert a **different** known-good SD card, and try again.
- Try the lens only after the body boots.
- Do not reapply the pixel-shift setting. Back up the settings and report the
  result before any further experiment.

If it still loops, try a different charged battery and a different SD card.
A failing card or a low battery can produce a boot loop independently of the
BK4 write.

## 2. Read-only diagnosis (no writes)

While the camera is connected and attempting to boot, run this repeatedly:

```bash
sudo -E ./venv/bin/python tools/fx30_pixel_shift.py --scan
```

Record:

- Does any `054C:xxxx` device appear? Which PID?
- Does `054C:0E0E` appear, even briefly?
- Does `system_profiler SPUSBDataType` show an `ILME-FX30` / Sony device?
- Does the camera show the Sony logo repeatedly, an error code, or a blank
  screen? Any beeps?
- Did this start immediately after the `--apply`, after a normal power-off, or
  after removing the battery?

If `054C:0E0E` appears and stays up, run **read-only**:

```bash
sudo -E ./venv/bin/python tools/fx30_pixel_shift.py --probe
```

Save the output and the snapshot path. Do not write yet. The probe tells us
whether `0x02cf02ca` is still `01` in the live container or already back to `00`.

## 3. Recovery options

### A. Official firmware reflash (preferred)

Use Sony's official ILME-FX30 firmware update procedure for your region and the
**original** `BODYDATA.DAT` from Sony. Do not use a modified file.

- Use a charged battery and a stable USB connection (or the official SD-card
  procedure if that is what Sony specifies for your region).
- Do not interrupt power during the update.
- A reflash may replace the firmware and may or may not preserve settings; that
  is acceptable for recovery.

If the camera cannot reach the update screen or the updater cannot detect it,
stop and contact Sony service. Do not try random button combinations.

### B. Service-mode snapshot restore (only if the camera is stable)

If `--probe` succeeds and the camera stays in service mode long enough, the
pre-write snapshot can be written back:

```bash
sudo -E ./venv/bin/python tools/fx30_pixel_shift.py \
  --restore fx30_dump/pixel_shift_snapshot_20261104_153700.bin
```

Important:

- This writes the snapshot **in RAM only** (no `0x603/3` save).
- It may not fix a value that was already persisted, and it will not fix a boot
  loop that happens before the service handler starts.
- If the camera reboots during the write, stop. Do not retry blindly.
- After a successful restore, power-cycle and probe again. If the loop returns,
  use the official reflash/service route.

### C. Sony service

If the clean boot and official reflash do not recover it, contact Sony service
or the retailer. A boot loop after a settings write is a service-level recovery;
do not keep experimenting with the settings container.

## 4. What may have happened

The intended behavior was RAM-only: `0x603/4` without `0x603/3`. The apply
readback verified one byte and both bank checksums. However:

- the camera may save settings on shutdown or boot in some states;
- the write may have landed in a container the boot path uses;
- a boot loop can also be caused by the card, battery, lens, USB, or an
  unrelated firmware fault.

We cannot distinguish these without the read-only state (`--scan` / `--probe`)
or a successful official reflash. Do not assume the BK4 write is the only cause,
and do not assume it is harmless.

## 5. Information to collect for support

- Exact boot-loop behavior (logo cycle, error code, beeps, timing).
- Battery model/charge, SD card, lens, USB connection.
- Whether `--persist` was ever used (it should not have been).
- Whether `--restore` was run after the apply.
- `--scan` output, and `--probe` output if it connects.
- Snapshot path and SHA-256:
  `fx30_dump/pixel_shift_snapshot_20261104_153700.bin`
  (`sha256` prefix `704d1782730cbe7b`).

## 6. Do not

- Do not reapply mode 4.
- Do not send `--persist`.
- Do not write a modified firmware image.
- Do not open the body or remove the battery while a firmware update is running.
- Do not repeat service writes hoping one will “take”.
