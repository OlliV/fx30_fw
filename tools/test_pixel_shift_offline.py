#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline regression tests for tools/fx30_pixel_shift.py.

No camera and no Sony USB dependencies are needed.  The tests build a synthetic
BK4 container, and (when the extracted firmware is present) also patch a real
FX30 LAX regional profile and check that exactly the target property byte and
the bank checksum change.

Run:
    python3 tools/test_pixel_shift_offline.py
"""
from __future__ import annotations

import argparse
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

import fx30_burst as burst  # noqa: E402
import fx30_pixel_shift as ps  # noqa: E402

PROFILE = (ROOT / "extracted" / "firmware_tar" / "0110_backup" /
           "SYSIPSX-DSLR" / "LAX" / "CX96700_J1.bin")


def make_bank(values: dict[int, int], ns: int = 0x02CF + 1, np: int = 0x04DB) -> bytes:
    """Minimal BK4 bank with subsystem 0x02cf and one byte per property."""
    table = 0x100 + ns * 6
    data = (table + np * 6 + 0xF) & ~0xF
    bank = bytearray(data + np * 8)
    bank[12:16] = b"BK4\0"
    struct.pack_into("<4I", bank, 0x10, ns, np, data, len(bank) - data)
    struct.pack_into("<HI", bank, 0x100 + 0x02CF * 6, np, 0)

    for k in range(np):
        pid = 0x02CF0000 | k
        if pid in values:
            off = data + k * 8
            bank[off] = values[pid]
            struct.pack_into("<HI", bank, table + k * 6, 0x60, (1 << 24) | off)
        else:
            struct.pack_into("<HI", bank, table + k * 6, 0x00, 0xFFFFFFFF)

    struct.pack_into("<I", bank, 0x20, (sum(bank[:0x20]) + sum(bank[0x24:])) & 0xFFFFFFFF)
    return bytes(bank)


def check(name: str, cond: bool, detail: str = "") -> None:
    print("%s %s%s" % ("PASS" if cond else "FAIL", name, (" - " + detail) if detail else ""))
    if not cond:
        raise SystemExit(1)


class FakeSession:
    """Minimal stand-in for fx30_burst.Session; records writes and saves."""

    def __init__(self, blob: bytes, apply_writes: bool = True):
        self.blob = bytearray(blob)
        self.apply_writes = apply_writes
        self.writes: list[bytes] = []
        self.saves = 0

    def read_pdt(self):
        return bytearray(self.blob)

    def write_pdt(self, blob):
        self.writes.append(bytes(blob))
        if self.apply_writes:
            self.blob = bytearray(blob)
        return 0

    def save(self):
        self.saves += 1
        return 0


def test_mode_patch() -> None:
    blob = make_bank({ps.PX_MODE: 0, ps.PX_MODE_MR: 0})
    patched, edits, notes, changed, _ = ps.build_patch(blob, ps.default_plan(1, None))
    check("mode4 edits mode byte", [e.pid for e in edits] == [ps.PX_MODE])
    check("mode4 patched value", patched[edits[0].off] == 1)
    check("mode4 checksum", burst.check(bytes(patched))[0])
    check("mode4 MR untouched", patched[edits[0].off + 8] == 0)


def test_mode16_interval() -> None:
    blob = make_bank({ps.PX_MODE: 0, ps.PX_MODE_MR: 0,
                      ps.PX_INTERVAL_16: 0, ps.PX_INTERVAL_16_MR: 0})
    patched, edits, notes, changed, _ = ps.build_patch(blob, ps.default_plan(2, 8))
    pids = [e.pid for e in edits]
    check("mode16 edits mode + interval", pids == [ps.PX_MODE, ps.PX_INTERVAL_16], repr(pids))
    check("mode16 values", all(patched[e.off] == e.new for e in edits))
    check("mode16 checksum", burst.check(bytes(patched))[0])


def test_off_is_noop() -> None:
    blob = make_bank({ps.PX_MODE: 0, ps.PX_MODE_MR: 0})
    patched, edits, notes, changed, _ = ps.build_patch(blob, ps.default_plan(0, None))
    check("off is a no-op", edits == [] and bytes(patched) == blob)


def test_missing_required() -> None:
    blob = make_bank({ps.PX_MODE_MR: 0})  # no 0x02cf02ca
    try:
        ps.plan_bytes(blob, ps.default_plan(1, None))
    except RuntimeError as exc:
        check("missing required property is refused", "refusing to guess" in str(exc))
    else:
        check("missing required property is refused", False)


def test_real_profile() -> None:
    if not PROFILE.exists():
        print("SKIP real profile test (extracted firmware not present)")
        return
    blob = PROFILE.read_bytes()
    check("real profile checksum", burst.check(blob)[0])
    props = burst.parse_props(blob)
    attr, cap, off = props[ps.PX_MODE]
    check("real mode property is 1 byte", cap == 1 and blob[off] == 0)
    check("real MR property is 4 bytes", props[ps.PX_MODE_MR][1] == 4)

    patched, edits, notes, changed, _ = ps.build_patch(blob, ps.default_plan(1, None))
    check("real patch checksum", burst.check(bytes(patched))[0])
    check("real patch target", patched[off] == 1)

    diff = {i for i in range(len(blob)) if blob[i] != patched[i]}
    check("real patch touches only value + checksum",
          off in diff and diff <= {0x20, 0x21, 0x22, 0x23, off}, repr(sorted(diff)))
    check("real patch leaves MR untouched",
          patched[props[ps.PX_MODE_MR][2]:props[ps.PX_MODE_MR][2] + 4] ==
          blob[props[ps.PX_MODE_MR][2]:props[ps.PX_MODE_MR][2] + 4])

    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "patched.bin"
        r = subprocess.run([sys.executable, str(HERE / "fx30_pixel_shift.py"),
                            "--offline", str(PROFILE), "--out", str(out), "--mode", "4"],
                           capture_output=True, text=True)
        check("offline CLI exit", r.returncode == 0, r.stdout[-300:] + r.stderr[-300:])
        check("offline CLI output", out.exists() and out.read_bytes() == bytes(patched))


def test_camera_flow() -> None:
    """Exercise do_apply with a fake session: no save unless --persist."""
    blob = PROFILE.read_bytes() if PROFILE.exists() else make_bank(
        {ps.PX_MODE: 0, ps.PX_MODE_MR: 0, ps.PX_INTERVAL_4: 0, ps.PX_INTERVAL_4_MR: 0})
    off = burst.parse_props(blob)[ps.PX_MODE][2]
    plan = ps.default_plan(1, None)
    old_dump = burst.DUMP

    with tempfile.TemporaryDirectory() as td:
        burst.DUMP = Path(td)
        try:
            fake = FakeSession(blob)
            args = argparse.Namespace(persist=False, dry_run=False, yes=True, no_mr=False)
            rc = ps.do_apply(fake, args, plan)
            check("session-only flow rc", rc == 0, "rc=%d" % rc)
            check("session-only flow sent no save", fake.saves == 0, "saves=%d" % fake.saves)
            check("session-only flow wrote once", len(fake.writes) == 1)
            check("session-only flow value", fake.blob[off] == 1)

            fake = FakeSession(blob)
            args = argparse.Namespace(persist=True, dry_run=False, yes=True, no_mr=False)
            rc = ps.do_apply(fake, args, plan)
            check("persist flow rc", rc == 0, "rc=%d" % rc)
            check("persist flow sent save", fake.saves == 1, "saves=%d" % fake.saves)

            fake = FakeSession(blob)
            args = argparse.Namespace(persist=False, dry_run=True, yes=False, no_mr=False)
            rc = ps.do_apply(fake, args, plan)
            check("dry-run rc", rc == 0, "rc=%d" % rc)
            check("dry-run wrote nothing", not fake.writes and fake.saves == 0)

            fake = FakeSession(blob, apply_writes=False)
            args = argparse.Namespace(persist=False, dry_run=False, yes=True, no_mr=False)
            rc = ps.do_apply(fake, args, plan)
            check("failed readback rc", rc == 4, "rc=%d" % rc)
            check("failed readback auto-restored", len(fake.writes) == 2 and fake.writes[1] == blob)
        finally:
            burst.DUMP = old_dump


def main() -> int:
    test_mode_patch()
    test_mode16_interval()
    test_off_is_noop()
    test_missing_required()
    test_real_profile()
    test_camera_flow()
    print("\nAll offline pixel-shift tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
