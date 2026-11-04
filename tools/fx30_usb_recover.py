#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fx30_usb_recover.py - low-level USB recovery for a stuck Sony auth identity.

The camera can sit at 054C:0D68 (HID, one 8-byte interrupt IN endpoint) during
the normal-side authentication transition after service mode. This tool offers
two small, non-flashing operations:

  --stop-senser   send Sony's StopSenser vendor request (the same request
                  SonySenserAuthDevice.stop() uses). It does not authenticate.
  --reset         request a USB port reset for the device.

It never reads/writes BK4, never authenticates, and never touches firmware.
Use it only after the camera has failed to return to 054C:0E0E on its own.

Usage:
    sudo -E ./venv/bin/python tools/fx30_usb_recover.py --stop-senser
    sudo -E ./venv/bin/python tools/fx30_usb_recover.py --reset

Run --scan afterwards. If the PID becomes 0x0e0e, stop and use the read-only
`fx30_pixel_shift.py --probe` before any further action.
"""
from __future__ import annotations

import argparse
import sys
import time

try:
    import usb.core
    import usb.util
    import usb.backend.libusb1
    import libusb_package
except ModuleNotFoundError as exc:
    print("Missing USB dependency: %r" % (exc,))
    print("Run ./tools/setup_service_deps.sh first.")
    sys.exit(2)

SONY_VID = 0x054C
AUTH_PIDS = (0x0D68, 0x096F)
# SonySenserAuthDevice.SONY_VendorRequest_StopSenser
STOP_SENSER = (1, 0xC800, 0x2855)
# vendor, OUT, recipient=other
BM_REQUEST_TYPE = 0x43


def backend():
    return usb.backend.libusb1.get_backend(find_library=libusb_package.find_library)


def find_auth_device(pid: int | None):
    be = backend()
    if pid is not None:
        return usb.core.find(idVendor=SONY_VID, idProduct=pid, backend=be)
    for candidate in AUTH_PIDS:
        dev = usb.core.find(idVendor=SONY_VID, idProduct=candidate, backend=be)
        if dev is not None:
            return dev
    return None


def sony_pids() -> list[str]:
    be = backend()
    out = []
    for dev in usb.core.find(find_all=True, idVendor=SONY_VID, backend=be) or []:
        out.append("%04x" % dev.idProduct)
    return out


def claim(dev) -> bool:
    try:
        if dev.is_kernel_driver_active(0):
            dev.detach_kernel_driver(0)
            print("  detached kernel driver on interface 0")
    except NotImplementedError:
        pass
    except Exception as exc:
        print("  detach: %r" % (exc,))
    try:
        usb.util.claim_interface(dev, 0)
        print("  claimed interface 0")
        return True
    except Exception as exc:
        print("  claim interface failed (continuing): %r" % (exc,))
        return False


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--stop-senser", action="store_true",
                   help="send Sony StopSenser vendor request (no authentication)")
    g.add_argument("--reset", action="store_true",
                   help="request a USB port reset for the device")
    g.add_argument("--scan", action="store_true",
                   help="only list Sony PIDs (no operation)")
    ap.add_argument("--pid", type=lambda x: int(x, 0),
                    help="target PID (default: 0x0d68 or 0x096f)")
    ap.add_argument("--retries", type=int, default=1,
                    help="attempts for the operation (default: 1; try 5 for a transient stall)")
    ap.add_argument("--delay", type=float, default=2.0,
                    help="seconds between attempts (default: 2.0)")
    args = ap.parse_args()

    if args.scan:
        print("Sony PIDs:", " ".join(sony_pids()) or "none")
        return 0

    attempts = max(1, args.retries)
    last_pids = []
    for attempt in range(1, attempts + 1):
        dev = find_auth_device(args.pid)
        if dev is None:
            print("Attempt %d/%d: no Sony auth device (0x0d68/0x096f)."
                  % (attempt, attempts))
            last_pids = sony_pids()
            print("  Sony PIDs:", " ".join(last_pids) or "none")
            if "0e0e" in last_pids:
                print("  0e0e appeared; stop here and run --probe read-only.")
                break
            if attempt < attempts:
                time.sleep(args.delay)
            continue

        print("Attempt %d/%d target: %04x:%04x bus=%s address=%s"
              % (attempt, attempts, dev.idVendor, dev.idProduct, dev.bus, dev.address))
        claimed = claim(dev)
        try:
            if args.stop_senser:
                print("  sending StopSenser vendor request ...")
                try:
                    dev.ctrl_transfer(BM_REQUEST_TYPE, STOP_SENSER[0],
                                      STOP_SENSER[1], STOP_SENSER[2], b"", timeout=2000)
                    print("  StopSenser sent")
                except Exception as exc:
                    print("  StopSenser failed: %r" % (exc,))
            elif args.reset:
                print("  requesting USB port reset ...")
                try:
                    dev.reset()
                    print("  reset requested")
                except Exception as exc:
                    print("  reset failed: %r" % (exc,))
        finally:
            if claimed:
                try:
                    usb.util.release_interface(dev, 0)
                except Exception:
                    pass
            try:
                usb.util.dispose_resources(dev)
            except Exception:
                pass

        time.sleep(max(1.0, args.delay))
        last_pids = sony_pids()
        print("  Sony PIDs after attempt: %s" % (" ".join(last_pids) or "none"))
        if "0e0e" in last_pids:
            print("  0e0e appeared; stop here and run --probe read-only.")
            break
        if attempt < attempts:
            print("  retrying ...")

    print("Final Sony PIDs:", " ".join(last_pids) or "none")
    if "0e0e" not in last_pids:
        print("If only 0d68/096f remains: do not flash; use Sony service.")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
