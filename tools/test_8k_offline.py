#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Offline tests for tools/fx30_8k.py.

No camera is touched. The tests patch a real LAX BK4 profile and check that the
8K selection changes only the file-format byte plus the bank checksum.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

import fx30_burst as burst  # noqa: E402
import fx30_8k as k  # noqa: E402

PROFILE = (ROOT / "extracted" / "firmware_tar" / "0110_backup" /
           "SYSIPSX-DSLR" / "LAX" / "CX96700_J1.bin")


def check(name: str, cond: bool, detail: str = "") -> None:
    print("%s %s%s" % ("PASS" if cond else "FAIL", name, (" - " + detail) if detail else ""))
    if not cond:
        raise SystemExit(1)


def main() -> int:
    if not PROFILE.exists():
        print("SKIP 8K offline test (extracted firmware not present)")
        return 0

    blob = PROFILE.read_bytes()
    check("profile checksum", burst.check(blob)[0])
    props = burst.parse_props(blob)
    fmt = props[k.FILE_FORMAT]
    check("file_format is 1 byte and currently XAVC S HD",
          fmt[1] == 1 and blob[fmt[2]] == 0x08)

    plan = k.default_plan(None)
    patched, edits, notes, changed, _ = k.build_patch(blob, plan, sync_mr=False)
    check("8K plan edits only file_format", [e.pid for e in edits] == [k.FILE_FORMAT])
    check("8K candidate checksum", burst.check(bytes(patched))[0])
    check("8K candidate value", patched[fmt[2]] == 5)

    diff = {i for i in range(len(blob)) if blob[i] != patched[i]}
    check("8K patch touches value + checksum only",
          fmt[2] in diff and diff <= {0x20, 0x21, 0x22, 0x23, fmt[2]},
          repr(sorted(diff)))

    plan_fr = k.default_plan("25p")
    patched2, edits2, notes2, changed2, _ = k.build_patch(blob, plan_fr, sync_mr=False)
    pids = [e.pid for e in edits2]
    check("25p plan edits file_format + frame_rate",
          pids == [k.FILE_FORMAT, k.FR_8K], repr(pids))
    check("25p frame-rate value", patched2[props[k.FR_8K][2]] == 3)
    check("25p checksum", burst.check(bytes(patched2))[0])

    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "candidate.bin"
        r = subprocess.run([sys.executable, str(HERE / "fx30_8k.py"),
                            "--offline", str(PROFILE), "--out", str(out)],
                           capture_output=True, text=True)
        check("8K offline CLI exit", r.returncode == 0,
              r.stdout[-300:] + r.stderr[-300:])
        check("8K offline CLI output", out.exists() and out.read_bytes() == bytes(patched))

        r = subprocess.run([sys.executable, str(HERE / "fx30_8k.py"),
                            "--persist", "--probe"],
                           capture_output=True, text=True)
        check("8K refuses --persist", r.returncode == 2 and "refused" in r.stdout,
              r.stdout[-200:] + r.stderr[-200:])

    print("\nAll 8K offline tests passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
