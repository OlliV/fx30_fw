#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FX30 service-mode read-only probe (public v1)
============================================
Switch Sony FX30 from standard MSC identity (054C:0E0E) to service mode
(054C:0336), perform Senser authentication, and read the HASP service token
(88 bytes).

Important detail: MSC info query and Senser authentication must use different
USB handles.

Dependencies:
  - pyusb / libusb_package
  - Sony camera USB protocol wrappers (pmca / transport, third-party OSS)
Set protocol library path via FX30_DEPS, for example:
  sudo PYTHONPATH="$(FX30_DEPS):$(FX30_DEPS)/vendor" python3 fx30_service_probe.py

Research use only, at your own risk.
"""
import os, sys, time, subprocess, plistlib
from pathlib import Path

# Protocol library path: prefer FX30_DEPS, else try local deps/ directory.
_DEPS = os.environ.get("FX30_DEPS", "")
if _DEPS:
    sys.path.insert(0, _DEPS)
    sys.path.insert(0, str(Path(_DEPS) / "vendor"))
else:
    _cand = Path(__file__).resolve().parent.parent / "deps"
    if _cand.exists():
        sys.path.insert(0, str(_cand))
        sys.path.insert(0, str(_cand / "vendor"))

import usb.core, usb.util, usb.backend.libusb1
import libusb_package
backend = usb.backend.libusb1.get_backend(find_library=libusb_package.find_library)

import transport
from transport import Bounded, get_device
from pmca.usb.driver.generic import MscBbbDriver, GenericUsbDriver
from pmca.usb import MscDevice
from pmca.usb.sony import (SonyExtCmdCamera, SonyMscExtCmdDevice,
                           SonySenserAuthDevice, SonySenserDevice,
                           SonySenserCamera)

VID = 0x054C
PID_MSC = 0x0E0E


def step(m):
    print(f"\n=== {m} ===", flush=True)


def list_sony():
    return {d.idProduct: d for d in usb.core.find(find_all=True, idVendor=VID,
                                                  backend=backend)}


def mac_unmount(pid):
    """macOS: unmount camera storage volume (whole disk, not one partition)."""
    print(f"  Unmounting mounted volume for 054C:{pid:04X}...", flush=True)
    try:
        tree = plistlib.loads(subprocess.run(
            ["/usr/sbin/ioreg", "-p", "IOService", "-r", "-c",
             "IOUSBHostDevice", "-l", "-a"],
            capture_output=True, timeout=30).stdout)
    except Exception as e:
        print(f"  [warn] ioreg: {e}")
        return

    def walk(n):
        if isinstance(n, list):
            for x in n:
                yield from walk(x)
        elif isinstance(n, dict):
            yield n
            yield from walk(n.get("IORegistryEntryChildren", []))

    seen = set()
    for node in walk(tree):
        if node.get("idVendor") == VID and node.get("idProduct") == pid:
            for med in walk(node):
                if med.get("IOObjectClass") == "IOMedia" and med.get("BSD Name"):
                    d = med["BSD Name"]
                    if "s" in d[4:] or d in seen:
                        continue
                    seen.add(d)
                    r = subprocess.run(["/usr/sbin/diskutil", "unmountDisk",
                                        f"/dev/{d}"],
                                       capture_output=True, text=True,
                                       timeout=15)
                    print(f"    {d}: {'OK' if r.returncode == 0 else r.stderr.strip()}",
                          flush=True)


def claim_fresh(pid):
    """Re-find + detach + claim, returning a clean USB device handle."""
    dev = get_device(pid)
    if dev.is_kernel_driver_active(0):
        dev.detach_kernel_driver(0)
    usb.util.claim_interface(dev, 0)
    return dev


def main():
    step("0. Preconditions")
    if sys.platform == "darwin" and os.geteuid() != 0:
        print("  sudo is required")
        sys.exit(2)

    step("1. Scan Sony USB devices")
    before = list_sony()
    for pid, d in before.items():
        try:
            sn = usb.util.get_string(d, d.iSerialNumber)
            prod = usb.util.get_string(d, d.iProduct)
        except Exception:
            sn = prod = "?"
        print(f"  054C:{pid:04X}  {prod}  S/N={sn}", flush=True)
        usb.util.dispose_resources(d)
    if PID_MSC not in before:
        print(f"  [FAIL] Did not find 054C:{PID_MSC:04X}")
        sys.exit(1)

    if sys.platform == "darwin":
        step("2. Unmount MSC on macOS")
        mac_unmount(PID_MSC)
        time.sleep(1)

    # ---- Stage A: MSC info query (dedicated handle, dispose immediately) ----
    step("3. [Handle A] Read camera identity over MSC")
    try:
        dev_a = claim_fresh(PID_MSC)
        msc = MscBbbDriver(Bounded(dev_a, 15))
        info = MscDevice(msc).getDeviceInfo()
        print(f"  manufacturer: {info.manufacturer.strip()!r}", flush=True)
        ext = SonyExtCmdCamera(SonyMscExtCmdDevice(msc))
        ci = ext.getCameraInfo()
        print(f"  modelName: {ci.modelName!r}", flush=True)
        print(f"  serial:    {ci.serial!r}", flush=True)
    except Exception as e:
        print(f"  [warn] MSC query failed: {e}", flush=True)
    finally:
        usb.util.dispose_resources(dev_a)
        time.sleep(0.5)

    # ---- Stage B: Senser auth (fresh handle, no SCSI commands) ----
    step("4. [Handle B] Run Senser authentication (clean handle, no SCSI)")
    try:
        dev_b = claim_fresh(PID_MSC)
        print(f"  bus={dev_b.bus} addr={dev_b.address}", flush=True)
        auth = SonySenserAuthDevice(GenericUsbDriver(Bounded(dev_b, 20)))
        auth.start()
        auth.authenticate()
        print("  *** Authentication handshake complete ***", flush=True)
        auth.stop()
    except Exception as e:
        print(f"  [FAIL] Authentication failed: {e}", flush=True)
        try:
            auth.stop()
        except Exception:
            pass
        usb.util.dispose_resources(dev_b)
        sys.exit(1)
    finally:
        usb.util.dispose_resources(dev_b)

    # ---- Stage C: wait for new PID ----
    step("5. Wait for new Sony PID (25s)")
    deadline = time.monotonic() + 25
    new_pid = None
    new_dev = None
    while time.monotonic() < deadline:
        time.sleep(0.5)
        cur = list_sony()
        for pid, d in cur.items():
            if pid != PID_MSC:
                new_pid = pid
                new_dev = d
                break
        if new_dev:
            break
    if new_dev is None:
        print("  [FAIL] Camera did not switch identity", flush=True)
        sys.exit(1)
    print(f"  [OK] New identity 054C:{new_pid:04X}", flush=True)

    # ---- Stage D: authenticate on new PID + read HASP ----
    step(f"6. Authenticate on 054C:{new_pid:04X} and read HASP")
    time.sleep(2)
    try:
        new_dev.set_configuration()
    except Exception:
        pass
    try:
        sa = SonySenserAuthDevice(GenericUsbDriver(Bounded(new_dev, 60)))
        sa.start()
        sa.authenticate()
        ch = SonySenserDevice(sa.driver)
        cam = SonySenserCamera(ch)
        hasp = cam.readHasp()
        print(f"  HASP length: {len(hasp)}", flush=True)
        print(f"  HASP hex:  {hasp[:40].hex()}", flush=True)
        if len(hasp) == 88:
            print("  *** FX30 service channel available ***", flush=True)
        sa.stop()
    except Exception as e:
        print(f"  [FAIL] Second authentication failed: {e}", flush=True)
    finally:
        usb.util.dispose_resources(new_dev)
    step("Done")


if __name__ == "__main__":
    main()
