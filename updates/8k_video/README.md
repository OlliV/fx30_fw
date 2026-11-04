# 8K video (XAVC HS 8K) — investigation

Status: **not viable on the FX30**; shared app code only.
Date: 2026-11-04

## What was found

The FX30 6.01 `appFw.so` contains the complete XAVC HS 8K file-format path and
8K BKID properties, because the app is shared with 8K-capable bodies:

| Property | BKID | Value |
|---|---|---|
| `0x02cf01f7` | `BKID_APP_setting_file_format` | `5` = `FILE_FORMAT_XAVC_HS_8K` |
| `0x02cf01f9` | `BKID_APP_setting_movie_rec_frame_rate_xavc_hs_8k` | `2` 30p, `3` 25p, `4` 24p |
| `0x02cf0205` | `..._movie_record_setting_xavc_hs_8k_30p_25p` | `9` = 200M 420 10-bit |
| `0x02cf0207` | `..._movie_record_setting_xavc_hs_8k_24p` | `9` |
| `0x02cf0233` | `..._sq_rec_frame_rate_xavc_hs_8k` | SQ variant |
| `0x02cf0241` | `..._sq_record_setting_xavc_hs_8k_30p_25p` | SQ variant |
| `0x02cf0243` | `..._sq_record_setting_xavc_hs_8k_24p` | SQ variant |

`VAL_setting_file_format_*` lists `FILE_FORMAT_XAVC_HS_8K` as enum value `5`.
The 8K frame-rate enum has 60p/50p/30p/25p/24p/120p/100p/24.00p.

The shared UI also contains the menu-side strings for it:

- `STRID_FUNC_MOVIE_FORMAT_SET_XAVCHS_8K` — the Movie Format set label
- `STRID_FUNC_MOVIE_FORMAT_GUIDE_XAVCHS_8K` — the guide/help
- `STRID_CMN_XAVC_HS_8K_I` — the value label

There is **no separate `STRID_MENU_*8K*` top-level menu item** in the UI data:
8K is a *value* of the Movie/File Format menu, not an independent mode.
`VAL_HAITA_setting_menu_shooting_mode_setting_file_format_MODE_MOVIE_8K`
is the derived shooting-mode value used when that format is active.

The FX30/LAX menu does not expose the XAVC HS 8K value. The strings and
properties are shared with 8K-capable bodies; adding a menu entry would require
changing the product/menu data, not just writing a BK4 value.

All 11 `0110_backup/SYSIPSX-DSLR/LAX/*.bin` profiles contain these properties
with `attr=0x60`, `cap=1`, and defaults:

- `file_format = 0x08` → **XAVC S HD** (not 8K)
- `movie_rec_frame_rate_xavc_hs_8k = 0x02` → 30p
- `movie_record_setting_xavc_hs_8k_30p_25p = 0x09` → 200M 420 10-bit
- `..._24p = 0x09`

## Why it cannot be a real 8K mode on the FX30

The FX30 uses the 26.1 MP IMX684 APS-C sensor. 8K UHD is 7680×4320, about
**33.2 MP**. The sensor cannot capture a native 8K frame; the 8K code and
properties are shared with 8K-capable bodies (e.g. the 50 MP A1). Selecting the
8K file format on a 26 MP body is expected to be rejected, ignored, or to fail.

The FX30 menu does not expose the 8K file format in normal use. The properties
being present in the BK4 container does **not** mean the sensor or image
pipeline supports the mode.

## Tool

`tools/fx30_8k.py` is a probe-first tool:

```bash
# read-only: list the properties and the assessment
sudo -E ./venv/bin/python tools/fx30_8k.py --probe

# offline: patch a saved BK4 file, never touch a camera
python3 tools/fx30_8k.py \
  --offline extracted/firmware_tar/0110_backup/SYSIPSX-DSLR/LAX/CX96700_J1.bin \
  --out /tmp/CX96700_J1.8k_candidate.bin

# forced RAM-only experiment; requires the explicit unsupported-hardware flag
sudo -E ./venv/bin/python tools/fx30_8k.py \
  --apply --force-unsupported --yes
```

The offline patch changes only `file_format` (`0x08 → 0x05`) and the bank
checksum. Run `python3 tools/test_8k_offline.py` for the regression check.

`--frame-rate 30p|25p|24p` also sets the 8K frame-rate/record-setting
properties, which are already at 8K defaults in the LAX profiles.

The script **refuses `--persist`**. If `--apply` is used, it writes with
`0x603/4` only, verifies the readback, and restores the pre-write snapshot in
RAM if the target does not stick. Use `--dry-run` to build the candidate without
a camera write.

## Safety and recovery

- Prefer `--probe`/`--offline`; do not run the forced write on a camera you need.
- If forced and the camera becomes unstable: restore the pre-write snapshot,
  then **cold boot** (battery out ≥30 s). Do not persist the 8K value.
- The pixel-shift incident showed that a hard reboot can persist an experimental
  value even without `0x603/3`; the same caution applies here. Restore first.
- The FX30 sensor cannot produce native 8K, so a successful byte write would not
  give real 8K footage.

## Code reuse

`fx30_8k.py` imports the BK4 plan/patch/checksum/snapshot/scan helpers from
`fx30_pixel_shift.py` instead of duplicating them. A future cleanup can move
those helpers into a dedicated common module; the 8K tool does not copy the BK4
parser or session code.
