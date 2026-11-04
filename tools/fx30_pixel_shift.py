#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fx30_pixel_shift.py - session-only pixel-shift probe for the FX30 (ILME-FX30).

What this does
--------------
Reads the live BK4 settings container over the Sony service channel (0x603/5),
patches only the pixel-shift backup property in memory (0x603/4), and verifies
the readback.  It does **not** send 0x603/3 ("save") by default, but that is
**not** a guarantee the camera will not persist the change: the FX30 can sync
the dirty BK4 container on shutdown/reboot (observed 2026-11-04).  To roll back,
restore the pre-write snapshot, then cold boot (battery out).  In the observed
recovery, `--persist` was not needed; save the restored state only if `01`
survives the cold boot.  Do not cold-boot the experimental value.

Confirmed property IDs from the generated BKID name records in appFw.so
(record layout: u32 id, u32 len, char* name):

    0x02cf02ca  BKID_APP_setting_px_shift_multi_shoot      0=off 1=4 images 2=16 images
    0x02cf02cb  BKID_APP_MR_setting_px_shift_multi_shoot   MR mirror
    0x02cf04d7  BKID_APP_setting_px_shift_multi_shoot_4_images_shooting   interval 0..8
    0x02cf04d9  BKID_APP_setting_px_shift_multi_shoot_16_images_shooting  interval 0..8

The FX30 has no mechanical shutter and no flash support, so the generic
still-shutter-type / wireless-flash HAITA exclusions are not part of the default
plan.  They can be forced with research-only flags if you are deliberately
testing those shared-app gates, but they are not expected to be the blocker on
this body.

The runtime-only property PRM_pixel_shift_multi_shoot_test_shooting_mode has no
BKID record and no BK4 slot that can be identified from the firmware alone, so
this tool does not guess at it.  Use --list / --extra only if you have
independent evidence for an ID.

Usage
-----
    # Read current values and take a snapshot (no write)
    sudo -E ./venv/bin/python tools/fx30_pixel_shift.py --probe

    # Session-only 4-image mode (the intended test)
    sudo -E ./venv/bin/python tools/fx30_pixel_shift.py --apply --mode 4 --yes

    # Session-only 16-image mode, shortest interval
    sudo -E ./venv/bin/python tools/fx30_pixel_shift.py --apply --mode 16 --interval shortest --yes

    # Offline: patch a saved BK4 snapshot, never touch the camera
    python3 tools/fx30_pixel_shift.py --offline fx30_dump/bk4_snapshot.bin

    # Restore a previous snapshot in RAM
    sudo -E ./venv/bin/python tools/fx30_pixel_shift.py --restore fx30_dump/pixel_shift_snapshot_xxx.bin

Safety model
------------
* No 0x603/3 save is sent unless --persist is given.  That is **not** a
  guarantee of non-persistence: the camera may sync the dirty BK4 container on
  shutdown/reboot.  Roll back by restoring the snapshot, then cold boot; do not
  cold-boot the experimental value.  Persist only if 01 survives.
* Snapshot is written before any camera write and is checksum-validated.
* Only BK4 settings are touched; firmware partitions are never written.
* Readback is verified; on mismatch the pre-write image is written back in RAM.
* --persist requires --yes and prints an explicit warning.

Research use only.  Keep a backup, follow the test plan, and expect warranty and
bricking risk.  A hard reboot can persist the experimental state.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import fx30_burst as burst  # noqa: E402  (shared BK4 parser + service session)

# ---------------------------------------------------------------------------
# Confirmed property IDs (BKID records in FX30 6.01 appFw.so)
# ---------------------------------------------------------------------------
PX_MODE = 0x02CF02CA
PX_MODE_MR = 0x02CF02CB
PX_INTERVAL_4 = 0x02CF04D7
PX_INTERVAL_4_MR = 0x02CF04D8
PX_INTERVAL_16 = 0x02CF04D9
PX_INTERVAL_16_MR = 0x02CF04DA
# Present in the shared app, but not applicable to the FX30 body.  Read-only
# by default; only used by the --force-* research flags.
SHUTTER_TYPE = 0x02CF02D4
SHUTTER_TYPE_MR = 0x02CF02D5
WIRELESS_FLASH = 0x02CF0356
WIRELESS_FLASH_MR = 0x02CF0357

NAMES = {
    PX_MODE: "BKID_APP_setting_px_shift_multi_shoot",
    PX_MODE_MR: "BKID_APP_MR_setting_px_shift_multi_shoot",
    SHUTTER_TYPE: "BKID_APP_setting_still_shutter_type",
    SHUTTER_TYPE_MR: "BKID_APP_MR_setting_still_shutter_type",
    WIRELESS_FLASH: "BKID_APP_setting_wireless_flash",
    WIRELESS_FLASH_MR: "BKID_APP_MR_setting_wireless_flash",
    PX_INTERVAL_4: "BKID_APP_setting_px_shift_multi_shoot_4_images_shooting",
    PX_INTERVAL_4_MR: "BKID_APP_MR_setting_px_shift_multi_shoot_4_images_shooting",
    PX_INTERVAL_16: "BKID_APP_setting_px_shift_multi_shoot_16_images_shooting",
    PX_INTERVAL_16_MR: "BKID_APP_MR_setting_px_shift_multi_shoot_16_images_shooting",
}

MODE_VALUES = {
    "off": 0,
    "4": 1, "4-images": 1, "4_images": 1,
    "16": 2, "16-images": 2, "16_images": 2,
}
MODE_LABELS = {0: "off", 1: "4 images", 2: "16 images"}
SHUTTER_LABELS = {0: "mechanical", 1: "electronic", 2: "invalid"}
FLASH_LABELS = {0: "off", 1: "on"}
INTERVAL_VALUES = {
    "shortest": 0, "1s": 1, "2s": 2, "3s": 3, "4s": 4,
    "5s": 5, "10s": 6, "15s": 7, "30s": 8,
}
INTERVAL_LABELS = {v: k for k, v in INTERVAL_VALUES.items()}


@dataclass
class Edit:
    pid: int
    value: int
    required: bool
    mr_twin: bool
    role: str = ""

    @property
    def name(self) -> str:
        return NAMES.get(self.pid, "unknown")


@dataclass
class PlannedByte:
    pid: int
    name: str
    off: int
    old: int
    new: int
    role: str
    twin: bool = False


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------
def default_plan(mode: int, interval: int | None) -> list[Edit]:
    """The FX30-appropriate plan: the live 1-byte setting + optional interval.

    The BKID_APP_MR_* mirrors are 4-byte arrays, not single settings, so they are
    intentionally not synced here.  The FX30's shutter/flash gates are already
    satisfied by hardware/defaults and are also not touched.
    """
    plan = [Edit(PX_MODE, mode, True, False, "mode")]
    if mode != 0 and interval is not None:
        pid = PX_INTERVAL_4 if mode == 1 else PX_INTERVAL_16
        plan.append(Edit(pid, interval, False, False, "interval"))
    return plan


def load_payload(path: Path) -> list[Edit]:
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data.get("properties")
    if not isinstance(rows, list) or not rows:
        raise ValueError("%s: no 'properties' list" % path)
    plan = []
    for n, row in enumerate(rows):
        try:
            pid = int(str(row["id"]), 0)
            val = int(str(row["value"]), 0)
        except (KeyError, ValueError) as exc:
            raise ValueError("%s: bad property row %d: %r" % (path, n, row)) from exc
        if not 0 <= val <= 0xFF:
            raise ValueError("%s: value out of byte range in row %d" % (path, n))
        plan.append(Edit(
            pid=pid,
            value=val,
            required=bool(row.get("required", False)),
            mr_twin=bool(row.get("mr_twin", True)),
            role=str(row.get("role", "")),
        ))
    return plan


def _props(blob: bytes):
    return burst.parse_props(bytes(blob))


def plan_bytes(blob: bytes, plan: list[Edit], sync_mr: bool = True) -> tuple[list[PlannedByte], list[str]]:
    """Resolve property IDs to byte edits without changing blob."""
    props = _props(blob)
    out: list[PlannedByte] = []
    notes: list[str] = []

    for e in plan:
        info = props.get(e.pid)
        if info is None:
            if e.required:
                raise RuntimeError(
                    "required property %#010x (%s) is missing from the BK4 container; "
                    "refusing to guess" % (e.pid, e.name)
                )
            notes.append("property %#010x (%s) is not present; skipped" % (e.pid, e.name))
            continue
        attr, cap, off = info
        if cap != 1:
            if e.required:
                raise RuntimeError(
                    "required property %#010x (%s) has capacity %d, expected 1" % (e.pid, e.name, cap)
                )
            notes.append("property %#010x (%s) has capacity %d; skipped" % (e.pid, e.name, cap))
            continue

        old = blob[off]
        if old != e.value:
            out.append(PlannedByte(e.pid, e.name, off, old, e.value, e.role))

        if sync_mr and e.mr_twin:
            twin = e.pid + 1
            tinfo = props.get(twin)
            if tinfo is None:
                notes.append("MR twin %#010x is not present; base only" % twin)
            elif tinfo[0] != 0xC0:
                notes.append("MR twin %#010x has attr %#06x (not 0xC0); base only" % (twin, tinfo[0]))
            elif tinfo[1] != 1:
                notes.append("MR twin %#010x has capacity %d; base only" % (twin, tinfo[1]))
            else:
                toff = tinfo[2]
                told = blob[toff]
                if told != e.value:
                    out.append(PlannedByte(twin, NAMES.get(twin, "?"), toff, told, e.value, e.role, True))

    # De-duplicate by offset, keeping the first (base before twin).
    seen = set()
    uniq = []
    for b in out:
        if b.off in seen:
            continue
        seen.add(b.off)
        uniq.append(b)
    return uniq, notes


def build_patch(blob: bytes, plan: list[Edit], sync_mr: bool = True):
    edits, notes = plan_bytes(blob, plan, sync_mr)
    patched = bytearray(blob)
    pairs = [(e.off, e.new) for e in edits]
    changed, touched = burst.apply_edits(patched, pairs)
    ok, _ = burst.check(bytes(patched), "patched")
    if not ok:
        raise RuntimeError("patched image has inconsistent BK4 checksums; aborting")
    return patched, edits, notes, changed, touched


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------
def describe(pid: int, value: int) -> str:
    if pid in (PX_MODE, PX_MODE_MR):
        return MODE_LABELS.get(value, "?")
    if pid in (SHUTTER_TYPE, SHUTTER_TYPE_MR):
        return SHUTTER_LABELS.get(value, "?")
    if pid in (WIRELESS_FLASH, WIRELESS_FLASH_MR):
        return FLASH_LABELS.get(value, "?")
    if pid in (PX_INTERVAL_4, PX_INTERVAL_4_MR, PX_INTERVAL_16, PX_INTERVAL_16_MR):
        return INTERVAL_LABELS.get(value, "?")
    return ""


def current_values(blob: bytes) -> None:
    props = _props(blob)
    print("\nCurrent pixel-shift-related properties:")
    for pid in (PX_MODE, PX_MODE_MR,
                PX_INTERVAL_4, PX_INTERVAL_4_MR, PX_INTERVAL_16, PX_INTERVAL_16_MR,
                SHUTTER_TYPE, WIRELESS_FLASH):
        info = props.get(pid)
        if info is None:
            print("  %#010x  %-68s  <not in container>" % (pid, NAMES.get(pid, "?")))
            continue
        attr, cap, off = info
        raw = bytes(blob[off:off + cap])
        val = raw[0] if cap == 1 else None
        print("  %#010x  %-68s  attr=%#06x cap=%d off=%#08x value=%s %s"
              % (pid, NAMES.get(pid, "?"), attr, cap, off,
                 ("0x%02x" % val) if val is not None else raw.hex(),
                 describe(pid, val) if val is not None else ""))
    print("  (still-shutter-type and wireless-flash are read-only here: the FX30 has")
    print("   no mechanical shutter and no flash support.)")


def list_props(blob: bytes, lo: int, hi: int) -> None:
    props = _props(blob)
    print("\nBK4 properties in %#010x .. %#010x:" % (lo, hi))
    for pid, (attr, cap, off) in sorted(props.items()):
        if not (lo <= pid <= hi):
            continue
        raw = bytes(blob[off:off + cap])
        val = raw[0] if cap == 1 else None
        print("  %#010x attr=%#06x cap=%-3d off=%#08x value=%-8s %s"
              % (pid, attr, cap, off,
                 ("0x%02x" % val) if val is not None else raw.hex()[:16],
                 describe(pid, val) if val is not None else ""))


def print_plan(edits: list[PlannedByte], notes: list[str]) -> None:
    if not edits:
        print("\nNo byte changes needed: the container already holds the requested values.")
    else:
        print("\nPlanned in-memory changes (%d byte%s):" % (len(edits), "" if len(edits) == 1 else "s"))
        for e in edits:
            print("  %#08x  %#010x  %-60s  %#04x -> %#04x%s"
                  % (e.off, e.pid, e.name, e.old, e.new, "  [MR twin]" if e.twin else ""))
    for n in notes:
        print("  note: %s" % n)


def snapshot_blob(blob: bytes, tag: str) -> Path:
    stamp = time.strftime("%Y%m%d_%H%M%S")
    path = burst.DUMP / ("pixel_shift_%s_%s.bin" % (tag, stamp))
    path.write_bytes(blob)
    print("  snapshot: %s (%d B, sha256=%s)"
          % (path, len(blob), hashlib.sha256(blob).hexdigest()[:16]))
    return path


# ---------------------------------------------------------------------------
# Camera flows
# ---------------------------------------------------------------------------
def do_probe(s, args) -> int:
    print("\n--- read BK4 ---")
    blob = s.read_pdt()
    ok, _ = burst.check(blob, "readback")
    if not ok:
        print("  [ABORT] readback checksum is not consistent; not touching anything")
        return 1
    snapshot_blob(blob, "snapshot")
    current_values(blob)
    if args.list:
        list_props(blob, 0x02CF02C0, 0x02CF0360)
        list_props(blob, 0x02CF04D0, 0x02CF04E0)
    return 0


def do_offline(args, plan: list[Edit]) -> int:
    path = Path(args.offline)
    blob = path.read_bytes()
    ok, _ = burst.check(blob, "offline input")
    if not ok:
        print("[ABORT] input BK4 checksum is not consistent")
        return 1
    print("Loaded %s (%d B, sha256=%s)"
          % (path, len(blob), hashlib.sha256(blob).hexdigest()[:16]))
    current_values(blob)
    patched, edits, notes, changed, _ = build_patch(blob, plan, sync_mr=not args.no_mr)
    print_plan(edits, notes)
    out = Path(args.out) if args.out else burst.DUMP / (path.stem + ".pixel_shift.bin")
    out.write_bytes(patched)
    print("\nWrote candidate: %s (%d B, sha256=%s)"
          % (out, len(patched), hashlib.sha256(patched).hexdigest()[:16]))
    print("This is an offline file. It has NOT been sent to a camera.")
    return 0


def do_apply(s, args, plan: list[Edit]) -> int:
    print("\n--- read BK4 + snapshot ---")
    blob = s.read_pdt()
    ok, _ = burst.check(blob, "readback")
    if not ok:
        print("  [ABORT] readback checksum is not consistent; not writing")
        return 1
    snap = snapshot_blob(blob, "snapshot")
    current_values(blob)

    patched, edits, notes, changed, touched = build_patch(blob, plan, sync_mr=not args.no_mr)
    print_plan(edits, notes)

    if not edits:
        print("\nNothing to write. No save was sent.")
        return 0

    print("\n  Write target : BK4 settings container")
    print("  Persistence  : %s" % ("PERSISTENT (0x603/3 save WILL be sent!)" if args.persist
                                   else "NO SAVE SENT (camera may still sync on shutdown)"))
    print("  Rollback     : %s" % snap.name)
    if args.dry_run:
        out = burst.DUMP / ("pixel_shift_dryrun_%s.bin" % time.strftime("%Y%m%d_%H%M%S"))
        out.write_bytes(patched)
        print("\n  [DRY-RUN] no camera write; candidate -> %s" % out)
        return 0
    if not args.yes:
        print("\n  [SAFETY] --yes not given; no write performed.")
        return 0
    if args.persist:
        print("\n  *** WARNING: --persist will call 0x603/3 and survive a cold boot. ***")
        print("  *** This is no longer a session-only test.                      ***")

    print("\n--- write (0x603/4, no save) ---")
    res = s.write_pdt(patched)
    if res != 0:
        print("  [FAIL] write rejected res=%s" % res)
        print("  res=129 usually means the firmware rejected the image/checksum.")
        return 3

    if args.persist:
        print("\n--- save (0x603/3) ---")
        s.save()
    else:
        print("  (no 0x603/3 save sent; the camera may still sync on shutdown)")
    time.sleep(1.0)

    print("\n--- readback verification ---")
    after = s.read_pdt()
    snapshot_blob(after, "after")
    ok, _ = burst.check(after, "after")
    missing = [e for e in edits if after[e.off] != e.new]
    if not ok or missing:
        if not ok:
            print("  [FAIL] readback BK4 checksum is inconsistent")
        if missing:
            print("  [FAIL] %d target byte(s) did not stick:" % len(missing))
            for e in missing:
                print("    %#08x %#010x: expected %#04x, read %#04x" % (e.off, e.pid, e.new, after[e.off]))
        print("\n  [AUTO-RESTORE] writing the pre-write snapshot back in RAM ...")
        try:
            if burst.check(blob, "snapshot")[0] and s.write_pdt(blob) == 0:
                if args.persist:
                    s.save()
                    print("  restore write accepted and saved (persistent)")
                else:
                    print("  restore write accepted; no save sent")
                back = s.read_pdt()
                d = [i for i in range(min(len(back), len(blob))) if back[i] != blob[i]]
                print("  readback diff vs snapshot: %d byte(s) %s"
                      % (len(d), ", ".join("%#x" % i for i in d[:12])))
            else:
                print("  restore failed; stop and seek service recovery")
        except Exception as exc:
            print("  restore failed: %r; stop and seek service recovery" % (exc,))
        return 4

    print("  all %d target byte(s) verified" % len(edits))
    print("  BK4 checksums: OK")
    if args.persist:
        print("\nPersistent write complete. Cold boot will keep these values.")
    else:
        print("\nWrite complete without 0x603/3.")
        print("Do NOT cold-boot the experimental value: the camera may sync the")
        print("dirty container on shutdown/reboot. Run --restore <snapshot>, then")
        print("cold boot. In the observed recovery, --persist was not needed; save")
        print("the restored state only if 01 survives.")
    return 0


def do_restore(s, args) -> int:
    path = Path(args.restore)
    blob = path.read_bytes()
    ok, _ = burst.check(blob, "restore image")
    if not ok:
        print("[ABORT] restore image checksum is not consistent")
        return 2
    print("Restoring %s (%d B) in %s mode"
          % (path, len(blob), "PERSISTENT" if args.persist else "RAM only"))
    res = s.write_pdt(blob)
    if res != 0:
        print("[FAIL] write rejected res=%s" % res)
        return 3
    if args.persist:
        s.save()
    time.sleep(1.0)
    after = s.read_pdt()
    d = [i for i in range(min(len(after), len(blob))) if after[i] != blob[i]]
    if d:
        print("Readback differs in %d byte(s): %s"
              % (len(d), ", ".join("%#x" % i for i in d[:20])))
        print("Differences in counter/timestamp areas are normal; target bytes should match.")
    else:
        print("Readback matches the restore image byte-for-byte.")
    if not args.persist:
        print("This restore was RAM-only. In the observed recovery, a RAM")
        print("restore followed by battery removal/cold boot was sufficient;")
        print("--persist was not used. If 01 survives, use Setting Reset or")
        print("re-run with --persist --yes.")
    return 0


def _plan_from_args(args) -> list[Edit]:
    if args.payload:
        plan = load_payload(Path(args.payload))
        print("Using payload: %s" % args.payload)
        return plan
    interval = INTERVAL_VALUES[args.interval] if args.interval is not None else None
    return default_plan(MODE_VALUES[args.mode], interval)


def check_host_deps() -> bool:
    """Fail early with an actionable message instead of a USB traceback."""
    missing = []
    try:
        import usb.core  # noqa: F401
        import usb.backend.libusb1  # noqa: F401
    except ModuleNotFoundError:
        missing.append("pyusb")
    try:
        import libusb_package  # noqa: F401
    except ModuleNotFoundError:
        missing.append("libusb-package")
    try:
        import transport  # noqa: F401
    except ModuleNotFoundError:
        missing.append("transport")
    try:
        from pmca.usb.driver.generic import GenericUsbDriver, MscBbbDriver  # noqa: F401
        from pmca.usb.sony import SonySenserAuthDevice, SonySenserDevice  # noqa: F401
    except ModuleNotFoundError:
        missing.append("pmca")

    if not missing:
        if sys.platform == "darwin" and hasattr(os, "geteuid") and os.geteuid() != 0:
            print("note: macOS USB access usually requires sudo. Re-run with:")
            print("  sudo -E %s %s --probe" % (sys.executable, sys.argv[0]))
        return True

    print("Missing host dependencies: %s" % ", ".join(missing))
    print("Easiest fix from the repo root:")
    print("  ./tools/setup_service_deps.sh")
    print("That installs pyusb/libusb-package into ./venv and fetches transport/pmca")
    print("into ./deps (the default search path used by fx30_burst.py).")
    print("")
    print("Manual alternative: install the USB packages into the interpreter that")
    print("runs this script:")
    print("  %s -m pip install pyusb libusb-package" % sys.executable)
    print("and point FX30_DEPS at the Sony protocol wrappers (the directory that")
    print("contains transport.py and vendor/pmca), for example:")
    print("  export FX30_DEPS=/path/to/a7c2-fl23-research/src/camera_runtime")
    print("  sudo -E PYTHONPATH=\"$FX30_DEPS:$FX30_DEPS/vendor\" \\")
    print("    %s tools/fx30_pixel_shift.py --probe" % sys.executable)
    print("--offline does not need any of these USB dependencies.")
    return False


# ---------------------------------------------------------------------------
# USB diagnostics
# ---------------------------------------------------------------------------
def _usb_string(dev, index) -> str:
    if not index:
        return ""
    try:
        import usb.util
        return usb.util.get_string(dev, index) or ""
    except Exception:
        return ""


def do_scan() -> int:
    """List what pyusb and macOS see, without touching the camera."""
    print("=== pyusb / libusb ===")
    devs = []
    try:
        import usb.core
        import usb.backend.libusb1
        import libusb_package
        backend = usb.backend.libusb1.get_backend(
            find_library=libusb_package.find_library)
        devs = list(usb.core.find(find_all=True, backend=backend) or [])
    except Exception as exc:
        print("  pyusb failed: %r" % (exc,))

    print("  %d USB device(s) visible" % len(devs))
    sony = []
    for d in devs:
        man = _usb_string(d, d.iManufacturer)
        prod = _usb_string(d, d.iProduct)
        ser = _usb_string(d, d.iSerialNumber)
        print("  %04x:%04x  %-22s %-30s %s"
              % (d.idVendor, d.idProduct, man[:22], prod[:30], ser[:20]))
        if d.idVendor == 0x054C:
            sony.append(d)
            try:
                for cfg in d:
                    for itf in cfg:
                        print("      cfg %d if %d alt %d class=%02x/%02x/%02x eps=%d"
                              % (cfg.bConfigurationValue, itf.bInterfaceNumber,
                                 itf.bAlternateSetting, itf.bInterfaceClass,
                                 itf.bInterfaceSubClass, itf.bInterfaceProtocol,
                                 itf.bNumEndpoints))
            except Exception as exc:
                print("      descriptors: %r" % (exc,))

    if any(d.idProduct == 0x0E0E for d in sony):
        print("\n  054C:0E0E (MSC) is present.")
        print("  If the tool still fails, close Photos/Image Capture/Imaging Edge,")
        print("  unmount any FX30 volume, and retry.")
    elif any(d.idProduct in (0x0D68, 0x096F) for d in sony):
        print("\n  054C:0D68 / 054C:096F are intermediate Sony identities seen")
        print("  during normal-side re-authentication after service mode, not an")
        print("  update mode. Do not flash based on this PID.")
        print("  Leave USB connected and wait 30-60 s without replugging; the")
        print("  camera may re-enumerate as 054C:0E0E. Then retry --scan/--probe.")
    elif sony:
        print("\n  Sony device(s) found, but none is 054C:0E0E (MSC).")
        print("  The camera is in another USB mode (PC Remote / Streaming / Auto).")
    else:
        print("\n  No Sony 054C device found.")

    if sys.platform == "darwin":
        print("\n=== macOS system_profiler (USB) ===")
        try:
            out = subprocess.run(["system_profiler", "SPUSBDataType"],
                                 capture_output=True, text=True, timeout=30).stdout
            lines = out.splitlines()
            hits = set()
            for i, line in enumerate(lines):
                if re.search(r"054c|sony|ilme|fx30", line, re.I):
                    for j in range(max(0, i - 4), min(len(lines), i + 8)):
                        hits.add(j)
            if not hits:
                print("  no Sony/054c entry")
            else:
                for j in sorted(hits):
                    print("  " + lines[j].strip())
        except Exception as exc:
            print("  system_profiler failed: %r" % (exc,))

    print("\nCamera checklist:")
    print("  1. Camera is ON and awake (not sleeping / not in a menus timeout).")
    print("  2. Use the camera's USB-C data port and a data cable; try another")
    print("     cable/port, direct to the Mac (no hub or dock).")
    print("  3. MENU -> Setup (or Network) -> USB -> USB Connection Mode =")
    print("     Mass Storage (MSC). Not PC Remote, not Streaming, not Auto.")
    print("     Chinese menu: 设置/网络 -> USB -> USB连接模式 -> 海量存储.")
    print("  4. After changing the mode, unplug and replug the cable.")
    print("  5. Close Photos, Image Capture, Imaging Edge, and any app that may")
    print("     claim the camera; unmount any FX30 volume.")
    print("  6. Run with sudo on macOS.")
    print("  7. If a 054C device appears with a PID other than 0x0e0e, the camera")
    print("     is in another USB mode; change it to Mass Storage.")
    print("\nNo camera data was read or written by this scan.")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(
        description="FX30 session-only pixel-shift probe (BK4 in RAM, no save by default)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("Usage\n-----", 1)[-1],
    )
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--probe", action="store_true", help="read + snapshot only (default)")
    g.add_argument("--apply", action="store_true", help="write the plan in RAM (no save unless --persist)")
    g.add_argument("--restore", metavar="FILE", help="write a saved BK4 snapshot back")
    g.add_argument("--offline", metavar="FILE", help="patch a saved BK4 file locally; no camera")
    g.add_argument("--scan", action="store_true", help="list USB devices and camera-mode checklist; no write")

    ap.add_argument("--mode", choices=sorted(MODE_VALUES), default="4",
                    help="pixel-shift mode (default: 4)")
    ap.add_argument("--interval", choices=sorted(INTERVAL_VALUES),
                    help="interval option for the selected mode; default: leave unchanged")
    ap.add_argument("--no-mr", action="store_true", help="do not sync the MR twin property")
    ap.add_argument("--payload", metavar="JSON", help="use an explicit property payload instead of the built-in plan")
    ap.add_argument("--list", action="store_true", help="with --probe, dump the nearby BK4 property range")
    ap.add_argument("--out", metavar="FILE", help="output file for --offline")

    # Research-only shared-app gates.  Not applicable to the FX30 body.
    ap.add_argument("--force-shutter-type", action="store_true",
                    help="RESEARCH ONLY: also force still shutter type = electronic (FX30 has no mechanical shutter)")
    ap.add_argument("--force-flash-off", action="store_true",
                    help="RESEARCH ONLY: also force wireless flash = off (FX30 has no flash support)")

    ap.add_argument("--persist", action="store_true", help="ALSO send 0x603/3 (persistent; requires --yes)")
    ap.add_argument("--dry-run", action="store_true", help="build the image but do not write to the camera")
    ap.add_argument("--yes", action="store_true", help="confirm the camera write")
    ap.add_argument("--extra", action="append", default=[], metavar="ID=VAL",
                    help="extra 1-byte property edit; requires --allow-unknown")
    ap.add_argument("--allow-unknown", action="store_true",
                    help="allow --extra IDs that are not in the known pixel-shift set")
    args = ap.parse_args()

    if args.scan:
        return do_scan()

    if args.persist and not args.yes:
        print("--persist requires --yes (and is not the intended test path).")
        return 2
    if args.persist and not (args.apply or args.restore):
        print("--persist only makes sense with --apply or --restore.")
        return 2
    if args.extra and not args.allow_unknown:
        print("--extra requires --allow-unknown; refusing to write unidentified properties.")
        return 2
    if args.extra and args.payload:
        print("--extra cannot be combined with --payload")
        return 2

    plan = _plan_from_args(args)
    if args.payload and (args.mode != "4" or args.interval is not None):
        print("note: --payload supplies the values; --mode/--interval are ignored")
    if args.force_shutter_type:
        plan.append(Edit(SHUTTER_TYPE, 1, False, True, "shutter"))
        print("RESEARCH FLAG: forcing still shutter type = electronic (not expected to matter on FX30)")
    if args.force_flash_off:
        plan.append(Edit(WIRELESS_FLASH, 0, False, True, "flash"))
        print("RESEARCH FLAG: forcing wireless flash = off (not expected to matter on FX30)")
    for item in args.extra:
        k, v = item.split("=", 1)
        plan.append(Edit(int(k, 0), int(v, 0) & 0xFF, False, False, "extra"))

    if args.offline:
        return do_offline(args, plan)

    try:
        with burst.Session() as s:
            if args.restore:
                return do_restore(s, args)
            if not args.apply:
                return do_probe(s, args)
            return do_apply(s, args, plan)
    except RuntimeError as exc:
        if "0E0E" in str(exc):
            print("[!] Camera not found at 054C:0E0E.")
            print("    Run: sudo -E %s %s --scan" % (sys.executable, sys.argv[0]))
            print("    Then check the USB cable/port and set")
            print("    USB Connection Mode = Mass Storage (MSC), not PC Remote/Streaming.")
            return 1
        import traceback
        print("[!] %r" % (exc,))
        traceback.print_exc()
        return 1
    except Exception as exc:
        import traceback
        print("[!] %r" % (exc,))
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main() or 0)
