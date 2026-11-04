# Disabled menu entries — deep dive

Status: survey complete for the obvious hardware-plausible features; no new
safe BK4-only unlock found.
Date: 2026-11-04

## Why “disabled menu entry” is not a BK4 problem

The FX30 runs a shared Sony app and a compiled UI. Menu visibility has three
layers:

1. **Product menu type** — `PRM_FEATURE_MANAGER_menu_item` returns
   `TYPE_MENU_ITEM_LAX` (value `1`) for the FX30. The UI uses that to select a
   compiled layout (`master_camera.uxc`, `LayoutMaster_Menu.uxc`,
   `LayoutMaster_Other.uxc`).
2. **Derived availability** — 771 `PRM_HAITA_*` properties and 6,859
   `VAL_HAITA_*` labels encode “is this item available in this product/state?”
   They are computed, not stored as BK4 settings.
3. **BK4 values** — the settings themselves. Writing one changes the value, not
   whether the menu layout contains the item.

The pixel-shift test proved this: the BK4 value was accepted, but the Drive
Mode menu did not change; the still-image path then caused a boot loop. A BK4
write cannot add a menu entry.

## What was enumerated

- `area_check_data.dat`: **7,337 unique `STRID_FUNC_*`** UI labels, plus `CMN`
  and `VAL` strings. Most belong to other bodies sharing the app.
- `appFw.so`: **771 unique `PRM_HAITA_*`** derived properties and **6,859
  `VAL_HAITA_*`** values, i.e. the availability/gating vocabulary.
- `master_camera.uxc` / `LayoutMaster_Menu.uxc`: compiled `uxc\x07` binaries.
  No public parser was found, so the per-product item layout cannot be
  enumerated reliably offline without reverse-engineering UXC.

## Candidate findings

| Candidate | Menu/UI evidence | Settable BK4? | FX30 manual | Verdict |
|---|---|---|---|---|
| 8K XAVC HS | `STRID_FUNC_MOVIE_FORMAT_SET_XAVCHS_8K` | `0x02cf01f7` = 5 | no | not viable (26 MP) |
| Pixel shift | PX shift labels/guides | `0x02cf02ca` | no | menu-gated; crash loop |
| Cinematic Mode | `STRID_FUNC_CINEMATIC_MODE*` (Look/Mood) | no BKID; only remote events | no | UI/remote-only; not settable |
| Embedded LUT | `sequence_set_embedded_lut` | no BKID found | no | model/sequence code, not exposed |
| Tally | `sequence_set_tally_status` | no BKID | no | status output, no user menu |
| CLC / variable ND | `STRID_FUNC_CLC_FILTER` | no appFw property | no | hardware absent |
| Open gate | no strings | no | no | not present |
| 4:4:4 | no strings | no | no | not present |
| ND / mechanical shutter / flash | — | — | no | hardware absent |
| Shutter angle | manual + UI | already exposed | yes (5.00+) | already available |
| Breathing comp. | manual + UI | already exposed | yes | already available |
| De-squeeze 1.3/1.5/1.6/2.0 | manual + UI | already exposed | yes (6.00+) | already available |
| RAW output | manual + UI | already exposed | yes | already available |
| 240 fps S&Q | manual + UI | already exposed | yes | already available |

Conclusion: **no additional hardware-supported feature with a proper FX30 menu
entry and a settable BK4 value was found**. The remaining “exciting” UI strings
are shared with other bodies (8K, Cinematic Mode, CLC/ND), are UI/remote-only
(Embedded LUT, Tally), or are hardware-impossible.

## How to go deeper

1. **Reverse-engineer UXC** — the files start with `uxc\x07` and contain
   resource/offset tables. A parser would let us diff the LAX layout against
   the LS/ALCIN_UUD layouts and list every hidden item. No parser is present in
   this repo or in the local Sony-PMCA-RE tree.
2. **Compare product layouts** — if separate layout resources exist per
   `TYPE_MENU_ITEM_*`, extract them from the firmware and diff item IDs.
3. **Instrument the UI/app on a camera** — log menu item IDs as the menu is
   built; this needs a test body and is read-only.
4. **For one specific candidate** — find its `STRID_FUNC_*`, `PRM_HAITA_*` and
   BKID property, then test the value in RAM with the pixel-shift-style tool.
   Expect the menu not to change unless the layout/HAITA layer is patched.

## Safety

- Do not write BK4 values just to “see if a menu appears”; pixel shift showed
  that the value can be accepted and still crash the still-image path.
- Menu/layout patches are a different risk class from BK4 writes; they are not
  covered by the existing tools.
- The existing probe/offline pattern (snapshot, checksum, readback, restore,
  no persist) is the minimum bar for any further experiment.
