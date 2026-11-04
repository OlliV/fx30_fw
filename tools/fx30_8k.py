#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fx30_8k.py - probe / optional RAM-only XAVC HS 8K setting for the FX30.

The shared Sony app contains XAVC HS 8K file-format code and 8K BK4 properties.
The FX30 (IMX684, 26.1 MP) cannot produce native 8K UHD (~33.2 MP required);
those paths are for 8K-capable bodies in the same app. This tool therefore:

  * defaults to a read-only probe (no write);
  * shows exactly which BK4 bytes would change for 8K;
  * refuses to write without --force-unsupported --yes;
  * never sends 0x603/3 (save) and never offers --persist;
  * snapshots before any write and restores the snapshot in RAM on failure.

Do not use --apply expecting real 8K. It is an experiment to see whether the
firmware rejects, ignores, or accepts the 8K file-format value on this body.

Confirmed BKID properties (FX30 6.01 appFw.so):

    0x02cf01f7  BKID_APP_setting_file_format                     5 = XAVC HS 8K
    0x02cf01f9  BKID_APP_setting_movie_rec_frame_rate_xavc_hs_8k 2=30p 3=25p 4=24p
    0x02cf0205  ..._movie_record_setting_xavc_hs_8k_30p_25p
    0x02cf0207  ..._movie_record_setting_xavc_hs_8k_24p
    0x02cf0233  ..._sq_rec_frame_rate_xavc_hs_8k
    0x02cf0241  ..._sq_record_setting_xavc_hs_8k_30p_25p
    0x02cf0243  ..._sq_record_setting_xavc_hs_8k_24p

LAX profiles default file_format = 0x08 (XAVC S HD), not 8K.

Usage:
    sudo -E ./venv/bin/python tools/fx30_8k.py --probe
    python3 tools/fx30_8k.py --offline fx30_dump/bk4_snapshot.bin --dry-run
    sudo -E ./venv/bin/python tools/fx30_8k.py --apply --force-unsupported --yes

Recovery: restore the pre-write snapshot, then cold boot (battery out). Do not
persist the 8K value. See the pixel-shift recovery notes for the same rules.
"""
from __future__ import annotations

import argparse
import hashlib
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import fx30_burst as burst  # noqa: E402
from fx30_pixel_shift import (  # noqa: E402  reuse the existing BK4 helpers
    Edit,
    NAMES,
    build_patch,
    check_host_deps,
    do_scan,
    plan_bytes,
    print_plan,
    snapshot_blob,
)

# ---------------------------------------------------------------------------
# Confirmed 8K BKID properties
# ---------------------------------------------------------------------------
FILE_FORMAT = 0x02CF01F7
FILE_FORMAT_MR = 0x02CF01F8
FR_8K = 0x02CF01F9
REC_8K_30P25P = 0x02CF0205
REC_8K_24P = 0x02CF0207
SQ_FR_8K = 0x02CF0233
SQ_REC_8K_30P25P = 0x02CF0241
SQ_REC_8K_24P = 0x02CF0243
FILE_FORMAT_CURRENT = 0x02CF14A5
EXTERN_MENU_MOV_FORMAT = 0x02CF012B

NAMES.update({
    FILE_FORMAT: "BKID_APP_setting_file_format",
    FILE_FORMAT_MR: "BKID_APP_MR_setting_file_format",
    FR_8K: "BKID_APP_setting_movie_rec_frame_rate_xavc_hs_8k",
    REC_8K_30P25P: "BKID_APP_setting_movie_record_setting_xavc_hs_8k_30p_25p",
    REC_8K_24P: "BKID_APP_setting_movie_record_setting_xavc_hs_8k_24p",
    SQ_FR_8K: "BKID_APP_setting_sq_rec_frame_rate_xavc_hs_8k",
    SQ_REC_8K_30P25P: "BKID_APP_setting_sq_record_setting_xavc_hs_8k_30p_25p",
    SQ_REC_8K_24P: "BKID_APP_setting_sq_record_setting_xavc_hs_8k_24p",
    FILE_FORMAT_CURRENT: "BKID_APP_setting_file_format_current_value",
    EXTERN_MENU_MOV_FORMAT: "BKID_APP_extern_menu_mov_file_format",
})

FILE_FORMAT_LABELS = {
    0: "XAVC S 4K (NG)",
    1: "XAVC S HD (NG)",
    2: "XAVC S",
    3: "AVCHD",
    4: "MP4",
    5: "XAVC HS 8K",
    6: "XAVC HS 4K",
    7: "XAVC S 4K",
    8: "XAVC S HD",
    9: "XAVC SI 4K",
    10: "XAVC SI HD",
    11: "XAVC SI DCI 4K",
    12: "invalid",
}
FR_8K_LABELS = {
    0: "60p", 1: "50p", 2: "30p", 3: "25p", 4: "24p",
    5: "120p", 6: "100p", 7: "24.00p", 8: "invalid",
}
REC_8K_LABELS = {
    0: "600M 422 10-bit", 1: "500M 422 10-bit", 2: "400M 420 10-bit",
    3: "300M 422 10-bit", 4: "280M 422 10-bit", 5: "250M 422 10-bit",
    6: "240M 422 10-bit", 7: "222M 422 10-bit", 8: "200M 422 10-bit",
    9: "200M 420 10-bit", 10: "200M 420 8-bit",
}

FRAME_RATE_VALUES = {"30p": 2, "25p": 3, "24p": 4}


def describe(pid: int, value: int) -> str:
    if pid in (FILE_FORMAT, FILE_FORMAT_CURRENT):
        return FILE_FORMAT_LABELS.get(value, "?")
    if pid in (FR_8K, SQ_FR_8K):
        return FR_8K_LABELS.get(value, "?")
    if pid in (REC_8K_30P25P, REC_8K_24P, SQ_REC_8K_30P25P, SQ_REC_8K_24P):
        return REC_8K_LABELS.get(value, "?")
    return ""


def default_plan(frame_rate: str | None) -> list[Edit]:
    """The minimal 8K selection: file-format byte, optional frame-rate bytes."""
    plan = [Edit(FILE_FORMAT, 5, True, False, "file_format")]
    if frame_rate:
        val = FRAME_RATE_VALUES[frame_rate]
        plan.append(Edit(FR_8K, val, False, False, "frame_rate"))
        rec_pid = REC_8K_24P if frame_rate == "24p" else REC_8K_30P25P
        plan.append(Edit(rec_pid, 9, False, False, "record_setting"))
    return plan


def current_values(blob: bytes) -> None:
    props = burst.parse_props(bytes(blob))
    print("\n8K-related BK4 properties:")
    for pid in (FILE_FORMAT, FILE_FORMAT_CURRENT, EXTERN_MENU_MOV_FORMAT,
                FR_8K, REC_8K_30P25P, REC_8K_24P,
                SQ_FR_8K, SQ_REC_8K_30P25P, SQ_REC_8K_24P):
        info = props.get(pid)
        if info is None:
            print("  %#010x  %-64s  <not in container>" % (pid, NAMES.get(pid, "?")))
            continue
        attr, cap, off = info
        raw = bytes(blob[off:off + cap])
        val = raw[0] if cap == 1 else None
        print("  %#010x  %-64s  attr=%#06x cap=%d off=%#08x value=%s %s"
              % (pid, NAMES.get(pid, "?"), attr, cap, off,
                 ("0x%02x" % val) if val is not None else raw.hex(),
                 describe(pid, val) if val is not None else ""))
    print("\nAssessment:")
    print("  FX30 / IMX684 is a 26.1 MP sensor. 8K UHD (7680x4320) is ~33.2 MP.")
    print("  The shared app contains 8K code for 8K-capable bodies; LAX defaults")
    print("  file_format to 0x08 (XAVC S HD). Selecting 8K on this body is expected")
    print("  to be rejected or to fail. Do not persist it.")


def do_probe(s, args) -> int:
    print("\n--- read BK4 ---")
    blob = s.read_pdt()
    ok, _ = burst.check(blob, "readback")
    if not ok:
        print("  [ABORT] readback checksum is not consistent")
        return 1
    snapshot_blob(blob, "8k_snapshot")
    current_values(blob)
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
    patched, edits, notes, changed, _ = build_patch(blob, plan, sync_mr=False)
    print_plan(edits, notes)
    out = Path(args.out) if args.out else burst.DUMP / (path.stem + ".8k_candidate.bin")
    out.write_bytes(patched)
    print("\nWrote candidate: %s (%d B, sha256=%s)"
          % (out, len(patched), hashlib.sha256(patched).hexdigest()[:16]))
    print("Offline file only; it has NOT been sent to a camera.")
    return 0


def do_apply(s, args, plan: list[Edit]) -> int:
    print("\n--- read BK4 + snapshot ---")
    blob = s.read_pdt()
    ok, _ = burst.check(blob, "readback")
    if not ok:
        print("  [ABORT] readback checksum is not consistent; not writing")
        return 1
    snap = snapshot_blob(blob, "8k_snapshot")
    current_values(blob)

    patched, edits, notes, changed, _ = build_patch(blob, plan, sync_mr=False)
    print_plan(edits, notes)
    if not edits:
        print("\nNothing to write.")
        return 0

    print("\n  Write target : BK4 settings container (RAM only)")
    print("  Persistence  : NO SAVE; 8K must not be persisted")
    print("  Hardware     : FX30 26.1 MP cannot produce native 8K UHD")
    print("  Rollback     : %s" % snap.name)
    if not args.force_unsupported:
        print("\n  [REFUSED] 8K is not supported by this sensor. Re-run with")
        print("            --force-unsupported if you accept the crash risk.")
        return 0
    if args.dry_run:
        out = burst.DUMP / ("8k_dryrun_%s.bin" % time.strftime("%Y%m%d_%H%M%S"))
        out.write_bytes(patched)
        print("\n  [DRY-RUN] no camera write; candidate -> %s" % out)
        return 0
    if not args.yes:
        print("\n  [SAFETY] --yes not given; no write performed.")
        return 0

    print("\n--- write (0x603/4, no save) ---")
    res = s.write_pdt(patched)
    if res != 0:
        print("  [FAIL] write rejected res=%s" % res)
        return 3
    print("  (no 0x603/3 save sent; do not persist 8K)")
    time.sleep(1.0)

    print("\n--- readback verification ---")
    after = s.read_pdt()
    snapshot_blob(after, "8k_after")
    ok, _ = burst.check(after, "after")
    missing = [e for e in edits if after[e.off] != e.new]
    if not ok or missing:
        if not ok:
            print("  [FAIL] readback checksum is inconsistent")
        for e in missing:
            print("  [FAIL] %#08x %#010x: expected %#04x read %#04x"
                  % (e.off, e.pid, e.new, after[e.off]))
        print("\n  [AUTO-RESTORE] writing the pre-write snapshot back in RAM ...")
        try:
            if burst.check(blob, "snapshot")[0] and s.write_pdt(blob) == 0:
                print("  restore write accepted; no save sent")
                back = s.read_pdt()
                d = [i for i in range(min(len(back), len(blob))) if back[i] != blob[i]]
                print("  readback diff vs snapshot: %d byte(s)" % len(d))
            else:
                print("  restore failed; stop and seek service recovery")
        except Exception as exc:
            print("  restore failed: %r; stop and seek service recovery" % (exc,))
        return 4

    print("  all %d target byte(s) verified" % len(edits))
    print("  BK4 checksums: OK")
    print("\nRAM-only 8K experiment complete (no save).")
    print("Do not persist. Restore the snapshot, then cold boot (battery out).")
    return 0


def do_restore_safe(s, args) -> int:
    path = Path(args.restore)
    blob = path.read_bytes()
    ok, _ = burst.check(blob, "restore image")
    if not ok:
        print("[ABORT] restore image checksum is not consistent")
        return 2
    print("Restoring %s in RAM only (no persist for 8K)" % path)
    res = s.write_pdt(blob)
    if res != 0:
        print("[FAIL] write rejected res=%s" % res)
        return 3
    after = s.read_pdt()
    d = [i for i in range(min(len(after), len(blob))) if after[i] != blob[i]]
    print("Readback differs in %d byte(s)%s"
          % (len(d), "" if not d else ": " + ", ".join("%#x" % i for i in d[:12])))
    print("Now cold boot (battery out >=30 s) and verify; do not persist 8K.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description="FX30 XAVC HS 8K probe / forced RAM-only experiment",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("Usage\n-----", 1)[-1],
    )
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--probe", action="store_true", help="read-only probe (default)")
    g.add_argument("--offline", metavar="FILE", help="patch a saved BK4 file; no camera")
    g.add_argument("--apply", action="store_true", help="forced RAM-only 8K write")
    g.add_argument("--restore", metavar="FILE", help="restore a snapshot in RAM")
    g.add_argument("--scan", action="store_true", help="list USB devices; no write")

    ap.add_argument("--frame-rate", choices=sorted(FRAME_RATE_VALUES),
                    help="also set the 8K frame-rate property (default: leave)")
    ap.add_argument("--out", metavar="FILE", help="output file for --offline")
    ap.add_argument("--force-unsupported", action="store_true",
                    help="allow the RAM-only write despite the 26 MP sensor")
    ap.add_argument("--dry-run", action="store_true", help="build but do not write")
    ap.add_argument("--yes", action="store_true", help="confirm the camera write")
    ap.add_argument("--persist", action="store_true",
                    help="refused: 8K must not be persisted")
    args = ap.parse_args()

    if args.persist:
        print("--persist is refused for the 8K experiment; do not persist it.")
        return 2

    plan = default_plan(args.frame_rate)
    if args.scan:
        return do_scan()
    if args.offline:
        return do_offline(args, plan)

    if not check_host_deps():
        return 1
    try:
        with burst.Session() as s:
            if args.restore:
                return do_restore_safe(s, args)
            if not args.apply:
                return do_probe(s, args)
            return do_apply(s, args, plan)
    except Exception as exc:
        import traceback
        print("[!] %r" % (exc,))
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main() or 0)
