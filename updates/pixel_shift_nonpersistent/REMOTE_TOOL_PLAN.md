# Remote pixel-shift tool — why it is needed and how to build it

Status: design / work plan, 2026-11-04
Context: [RESULT.md](RESULT.md) — the non-persistent BK4 write succeeded, but the
Drive Mode menu did not change.

## 1. Why a remote tool is needed

The first camera run established that `0x02cf02ca` is the pixel-shift **value**,
not the menu registration:

- `VAL_setting_menu_drive_mode_*` has 17 real values and none is pixel shift.
- The UI has `Pixel Shift Multi Shoot.` and the `STRID_FUNC_PX_SHIFT_...` labels
  and guides, but no `STRID_MENU_*PIXEL*` drive-mode item.
- The Drive Mode list is a compiled, per-product menu; a BK4 byte cannot add
  an item to it.

The remaining non-persistent route is to drive the app's **remote/model API**
from the host, without going through the menu:

- the app has `set_remote_px_shift_multi_shoot_mode`,
  `set_remote_px_shift_multi_shoot_number`,
  `set_remote_px_shift_multi_shoot_interval`;
- it has matching remote events (`EVENT_REMOTE_PIXEL_SHIFT_SHOOTING_MODE`,
  `..._NUMBER`, `..._INTERVAL`, `EVENT_REMOTE_CANCEL_PIXEL_SHIFT_SHOOTING_ON/OFF`);
- it has a runtime-only `PRM_pixel_shift_multi_shoot_test_shooting_mode`
  (OFF/ON) that is not a `BKID_APP_*` backup property and cannot be set with
  `bk w`.

A host-side remote client is therefore the only plausible way to set the mode
and request the sequence without a menu entry or a firmware patch.

This is a **new tool**, not an extension of the BK4 probe. It does not write the
BK4 container and does not persist anything.

Decision tree:

```text
Is there a Pixel Shift item anywhere in the camera menu / Fn menu?
  yes -> use it; no remote tool needed
  no
   v
PTP read-only probe: are pixel-shift commands/properties advertised?
  no  -> stop; try a service HAITA command only with new evidence
  yes
   v
set mode (4/16) -> read back -> arm/start -> capture events -> cancel
   v
restore known-good state -> reboot -> confirm off
```

## 2. What the firmware already gives us

Addresses are virtual addresses in FX30 6.01 `appFw.so`; use the existing
`pyelftools`/`capstone` helpers (or `appfw_elf.py`) to re-check them.

| Hook | Evidence |
|---|---|
| `model::model_api::detail::set_remote_px_shift_multi_shoot_mode(...)` | pretty string `0x37a4950`; code ref `0x28350dc` |
| `...set_remote_px_shift_multi_shoot_number(...)` | pretty string `0x37a5120`; code ref `0x2835388` |
| `...set_remote_px_shift_multi_shoot_interval(...)` | pretty string `0x37a55c8`; code ref `0x279b0b8` |
| `infra_wrapper_remote::detail::to_remote_event_pixel_shift_shooting_mode(...)` | pretty string `0x39a0f48`; converter ref `0x2ea99b8` |
| `...to_remote_event_pixel_shift_shooting_number(...)` | `0x39a1190`; `0x2e9e6c0` |
| `...to_remote_event_pixel_shift_shooting_interval(...)` | `0x39a1648`; `0x2e9e780` |
| `set_px_shift_multi_shoot_test_shooting_mode` | name `0x3c0ace1`; name pointer in BSS at `0x4b2e548` |
| `PRM_pixel_shift_multi_shoot_test_shooting_mode` | name `0x39b0f1d`; name-table slot `0x411c740` |
| `EVENT_REMOTE_PIXEL_SHIFT_SHOOTING_MODE/NUMBER/INTERVAL` | strings `0x3c3d8b5` / `0x3c3d8dc` / `0x3c3d905` |
| `EVENT_REMOTE_CANCEL_PIXEL_SHIFT_SHOOTING_ON/OFF` | strings `0x3c3e1fe` / `0x3c3e22a` |

The event converters compare the notify payload value and write internal
`ds_remote_event` codes such as `0x2a61`, `0x2a62`, `0x2a64`, `0x2a1d`,
`0x2a65`, `0x2a66`, `0x2a68`. Those are **internal** event codes, not the PTP
notify codes; the dispatcher that calls the converters still has to be mapped.

### Still unknown (the actual reverse-engineering work)

1. PTP vendor **command code** for each setter (set mode / number / interval /
   test mode) and the **property code** if it is a property write.
2. PTP **notify code** that dispatches to each event converter (the converter
   receives an already-decoded `ptp::ds_notify_command<u16>`).
3. Payload layout: scalar `u16`, enum, or array; endianness and length.
4. Whether the FX30's PC Remote interface advertises these codes at all.
5. Whether `test_shooting_mode` is reachable over PTP, or only through an
   internal HAITA/service command.
6. Whether the sequence needs an explicit "start" command or a normal remote
   shutter release after the mode is armed.

## 3. Transport choice

### A. PTP over USB in PC Remote mode (recommended)

- Camera USB mode: **PC Remote**, not Mass Storage/MSC.
- Reuse the Sony PTP client shape from the A7 IV research
  (`a7iv_ptp_log_probe.py` / `a7iv_ptp_snapshot.py`): `pmca` USB drivers,
  `MtpDevice`, `device.driver.sendReadCommand`, `_checkResponse`.
- Read-only enumeration uses Sony's PC Remote operations:
  - `0x9201` SDIO_CONNECT
  - `0x9202` GET_EXT_DEVICE_INFO
  - `0x9203` GET_DEVICE_PROP_DESC
  - `0x9209` GET_ALL_EXT_DEVICE_PROP_INFO
- Pros: documented shape, read-only enumeration, event stream, can trigger a
  remote shutter; no service-mode adjustment writes.
- Cons: requires switching the camera out of MSC; the FX30 may not advertise
  the pixel-shift codes.

### B. Service-mode HAITA/model command (fallback)

- Stay in MSC/service mode and invoke the model function by name/ID over the
  existing service channel.
- Pros: no USB mode change; reuses the working service session.
- Cons: the command format is undocumented; `adjstctl.elf` is a black box; a
  wrong adjustment command is riskier than a PTP property write; no known event
  or trigger path.
- Only pursue if A is unavailable and the Phase 0 map identifies a safe
  read-back command.

**Recommendation:** build A first. It is read-only until Phase 2 and has a
well-defined stop condition (codes not advertised).

## 4. Tool design

Two scripts, sharing one module:

```text
tools/fx30_ptp.py                 # PTP USB session, Sony 0x9201/0x9202/0x9203/0x9209
tools/fx30_remote_probe.py        # read-only: enumerate codes/descriptors -> JSON
tools/fx30_pixel_shift_remote.py  # status/set/start/cancel/watch
notes/remote-pixel-shift-map.json # recovered codes/payloads + evidence addresses
updates/pixel_shift_nonpersistent/REMOTE_TEST_PLAN.md
```

CLI shape:

```bash
# read-only; no writes
python3 tools/fx30_remote_probe.py --json notes/fx30-ptp-snapshot.json

# state
python3 tools/fx30_pixel_shift_remote.py --status

# set mode only (no start); --yes is required for any write
python3 tools/fx30_pixel_shift_remote.py --set-mode 4 --interval shortest --yes

# explicit arm/start (separate step, like --yes in the BK4 tool)
python3 tools/fx30_pixel_shift_remote.py --start --count 4 --yes

# cancel / cleanup
python3 tools/fx30_pixel_shift_remote.py --cancel
python3 tools/fx30_pixel_shift_remote.py --watch
```

Safety requirements:

- `--status` and `--watch` are read-only.
- `--set-mode` and `--start` are separate; no combined "do everything" flag.
- Every camera-affecting write (including `--set-mode`) requires `--yes`;
  `--status`, `--watch` and `--dry-run` do not.
- A `--dry-run` prints the PTP command/ payload without sending.
- No BK4 container read/write, no `0x603` calls, no firmware writes, no save.
  But “no save” is **not** a guarantee of non-persistence on this body; the
  FX30 may sync a dirty state on shutdown/reboot. Restore the known-good state
  and verify it before rebooting (see [RECOVERY.md](RECOVERY.md)).
- Log every command/response and every event to `fx30_dump/`.
- On timeout/exception, send `--cancel` / set mode OFF if possible, then stop.

## 5. Build steps

### Phase 0 — offline map (no camera)

1. Re-resolve the strings/addresses in section 2 with `appfw_elf.py` and
   capstone; record the actual function starts.
2. Disassemble `set_remote_px_shift_multi_shoot_mode/number/interval` and follow
   the calls into the remote wrapper. Identify:
   - the operation/command constant passed to the PTP layer;
   - the payload construction (register writes, `strh`, arrays);
   - the return/error convention.
3. Disassemble the three `to_remote_event_*` converters and their **caller
   dispatcher**. Identify the PTP notify code compared before the call, and the
   payload offset used for the value (`[x21,#0xc]` in the current dump).
4. Map internal `ds_remote_event` codes (`0x2a61`, `0x2a62`, `0x2a64`,
   `0x2a1d`, `0x2a65`, `0x2a66`, `0x2a68`) to names using the enum strings and
   the surrounding jump table.
5. Search `pmca` / Sony-PMCA-RE for an existing Sony vendor command table and
   for the same codes on other models (A7 IV, A7S III). Reuse definitions where
   they match.
6. Produce `notes/remote-pixel-shift-map.json` with, per operation:
   `ptp_code`, `direction` (set/get/notify), `payload` (type/len), `evidence`
   (function VA, instruction VA), `confidence`.

Deliverable: a code map with confidence flags. No camera interaction.

### Phase 1 — read-only PTP probe

1. Set the camera to **PC Remote** (`MENU → Setup/Network → USB → USB
   Connection Mode → PC Remote`), replug the cable.
2. Record the USB identity (`tools/fx30_pixel_shift.py --scan`) — the PID may
   differ from MSC's `0x0E0E`.
3. Open a PTP session and run `SDIO_CONNECT` 1/2/3 and
   `GET_EXT_DEVICE_INFO` (protocol `0x012C`).
4. Dump `GET_ALL_EXT_DEVICE_PROP_INFO` (`0x9209`) and all advertised property
   and control codes.
5. For each candidate code from Phase 0, fetch its `0x9203` descriptor
   (current, factory, writable, enum/range).
6. Save the snapshot JSON. **No writes.**

Stop condition: if neither the mode/number/interval codes nor any plausible
pixel-shift property appears, the FX30 PC Remote surface does not expose the
feature. Record that and stop; do not fall back to blind writes.

### Phase 2 — set mode, no sequence

1. Send the set-mode operation for 4 images using the Phase 0/1 code map.
2. Read it back with the matching get/descriptor; confirm the value.
3. Set the interval and number if exposed; read back.
4. Try `test_shooting_mode = ON` only if its code is identified; read back.
5. Subscribe to events and log everything. Do not trigger the shutter yet.

Success: values change and read back, no error, no unexpected mode change.

### Phase 3 — start / cancel

1. Send the start/capture operation, or a normal remote shutter release if the
   mode is armed and the sequence is started by the shutter.
2. Capture and decode `EVENT_REMOTE_PIXEL_SHIFT_SHOOTING_*` and the cancel
   events; record payloads.
3. Verify 4 (or 16) frames, grouping, and the interval.
4. Send `--cancel`; verify the state returns to idle/off.

If no start path exists, record that the sequence can only be started from a
physical control and stop.

### Phase 4 — non-persistence / cleanup

1. Cancel, set mode OFF.
2. Disconnect, power off, remove the battery for ≥30 s.
3. Reconnect, run `--status`; confirm mode OFF.
4. Keep the JSON/event logs as the experiment record.

## 6. Test matrix

| Test | Precondition | Expected | Stop if |
|---|---|---|---|
| Probe | PC Remote | camera info + codes, no writes | session/commands unsupported |
| Status | mode off | mode 0, interval enum, test mode off | values unreadable |
| Set 4 | probe ok | readback = 4, no events/errors | rejected or value normalizes |
| Set 16 | probe ok | readback = 16 | same |
| Set interval | probe ok | readback = chosen enum | same |
| Test mode on | code known | readback = 1 | rejected |
| Start | mode 4 armed | 4 frames / events | no frames or camera error |
| Cancel | sequence/armed | idle, mode unchanged | stuck busy |
| Reboot | after restoring known-good state | mode 0 | value survives as 1 |

## 7. Risks and decision points

- **No advertised codes**: the remote route is unavailable on this body. The
  only remaining options are a service HAITA command (if one exists) or a
  firmware/menu patch, both outside the non-persistent scope.
- **PTP writes rejected**: same conclusion; do not escalate to persistent BK4
  edits.
- **Set succeeds but no start**: record it; the menu is still the gate for the
  trigger, and the sequence is not usable without a physical control.
- **Sensor movement**: use a tripod, static scene, electronic shutter; avoid
  repeated 16-image runs; watch battery/heat.
- **Model/firmware differences**: codes are per-model; do not reuse A7 IV
  codes without matching evidence in the FX30 binary.
- **Warranty/bricking**: PC Remote property writes are lower risk than service
  adjustment writes but still experimental. No firmware patches.
- **“No save” is not non-persistence**: the FX30 may sync a dirty state on
  shutdown/reboot. Restore the known-good state and verify before rebooting.

## 8. Immediate next actions

1. Quick sweep: check the **Fn menu** and the **Shooting menu** (not just Drive
   Mode) for a separate Pixel Shift item. If it exists, the remote tool may be
   unnecessary.
2. Restore the known-good state first, then reboot and confirm `0x02cf02ca = 00`.
3. If no menu item, do Phase 0 (offline code map); it needs no camera.
4. Then Phase 1 (read-only PTP probe). Decide from the advertised codes, not
   from guesses.

## 9. References

- A7 IV PTP read-only snapshot:
  [a7iv_ptp_snapshot.py](https://github.com/leogenot/sony-a7iv-feature-research/blob/main/scripts/a7iv_ptp_snapshot.py)
- A7 IV PTP log/descriptor probe:
  [a7iv_ptp_log_probe.py](https://github.com/leogenot/sony-a7iv-feature-research/blob/main/scripts/a7iv_ptp_log_probe.py)
- Sony-PMCA-RE USB/PTP drivers:
  [ma1co/Sony-PMCA-RE](https://github.com/ma1co/Sony-PMCA-RE)
- Local evidence: `notes/appFw_strings.txt`, `extracted/nflasha15_usr/lib/appFw.so`,
  and the addresses in section 2.

## Appendix A — minimal read-only PTP session skeleton

This is the shape to start from; it is deliberately read-only. It mirrors the
A7 IV scripts above and uses Sony's PC Remote operation codes.

```python
# tools/fx30_ptp.py (sketch)
import sys
from pathlib import Path

sys.path.insert(0, str(Path.home() / "Documents/Sony-PMCA-RE"))
from pmca.commands.usb import importDriver
from pmca.usb import MtpDevice
from pmca.usb.driver import USB_CLASS_PTP

# from a7iv_ptp_log_probe import find_sony_ptp_device  # copy/adapt helper

SONY_VENDOR_ID = 0x054C
SONY_SDIO_CONNECT = 0x9201
SONY_SDIO_GET_EXT_DEVICE_INFO = 0x9202
SONY_GET_ALL_EXT_DEVICE_PROP_INFO = 0x9209
SONY_PROTOCOL_3_00 = 0x012C


def read_command(device, operation, params):
    response, data = device.driver.sendReadCommand(operation, params)
    device._checkResponse(response)
    return data


def open_sony_ptp(drivers):
    # Find the PTP-interface Sony device.  Reuse find_sony_ptp_device()
    # from a7iv_ptp_log_probe.py; it filters 054C and USB_CLASS_PTP.
    return find_sony_ptp_device(drivers, MtpDevice, USB_CLASS_PTP)


def probe(device):
    read_command(device, SONY_SDIO_CONNECT, [1, 0, 0])
    read_command(device, SONY_SDIO_CONNECT, [2, 0, 0])
    ext = read_command(device, SONY_SDIO_GET_EXT_DEVICE_INFO,
                       [SONY_PROTOCOL_3_00, 1])
    # parse: u16 version, u32 count + u16 properties, u32 count + u16 controls
    # then optionally 0x9209 aggregate descriptors and 0x9203 per-property.
    read_command(device, SONY_SDIO_CONNECT, [3, 0, 0])
    return ext


def main():
    # Keep the driver context open for the whole session; returning a device
    # out of this block closes the USB driver.
    with importDriver() as drivers:
        device, info = open_sony_ptp(drivers)
        ext = probe(device)
        print("camera:", info.manufacturer, info.model)
        print("extended info bytes:", len(ext))


if __name__ == "__main__":
    main()
```

The next functions to add are:

1. `parse_extended_device_info(ext)` — copy the A7 IV parser, including the
   property-code and control-code arrays.
2. `get_descriptor(code)` — `0x9203` request + the A7 IV `parse_descriptor()`
   for current/enum/range/writable.
3. `find_pixel_shift_codes(properties)` — intersect the advertised codes with
   the Phase 0 map; if empty, stop.
4. `set_property(code, value)` / `send_vendor_command(code, payload)` — only
   after Phase 2 approval; log raw request/response.
5. `event_loop()` — subscribe to PTP events, decode notify codes with the
   Phase 0 map, print payloads, and never auto-rearm.

Do not add a `--force` or "send everything" mode. Each camera-affecting step
should require its own explicit flag, exactly like the BK4 tool's `--yes`.
