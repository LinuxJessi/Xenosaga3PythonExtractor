# XS3 character textures: the embedded `txy` format (and how to recolor them)

Reverse-engineered 2026-07-19 using KOS-MOS (`mdl/chr/pc/C3kosmos*.chr`) as
the test case ("pink KOS-MOS"). Everything below was verified end-to-end: all
30 KOS-MOS `.chr` files decode with this layout, a hair recolor was applied
byte-in-place, and the patched Disc 1 ISO boots and streams normally in
PCSX2. Implementation: [`chrtex.py`](../chrtex.py); human walkthrough:
[MODDING-CHARACTERS.md](MODDING-CHARACTERS.md).

## Where character pixels live

A `.chr` MR Package (`Xc\x01`, see disc-catalog.md) contains sub-resources
`pxy` (mesh), `txy` (textures), `xhr` (skeleton), `epf`. The `txy`
sub-resource — *unlike* the standalone index-only `.txy` files — carries the
actual pixels. Its architecture is Xenosaga I's XTX all over again: raw GS
uploads composing a PSMCT32 canvas that holds a PSMT8 image at 2× dimensions
plus 16×16 CLUT tiles, CSM1 palette order, stored alpha 0..0x80 (double on
decode).

## Layout

Sub-resource start = offset from the Xc header table. First 0x40 bytes are a
float/pointer pre-header; `txy\0` magic at +0x40. All offsets below are
relative to the `txy` magic ("txy base").

```
txy base:
  +0x00  "txy\0", u32 version(1)
  +0x08  u32 total size of the txy block
  +0x10  u32 record-table offset (0x90 in all observed files)

record table (0x20-byte records):
  record 0 — canvas descriptor:
    u32 ?, u32 ?, u32 canvas_width(512), u32 canvas_height, u32 0,
    u32 4, u32 entry_count, u32 0
    NOTE: canvas_height says 128 even when 9-strip H models stack pages to
    256 rows — compute the real height from the strips, not this field.
  records 1..n — CT32 strip uploads (until a zero record):
    u32 data_off (txy-relative), u32 gs_block, u32 width_px, u32 height_px(32),
    u32 0, u32 size_qwords (includes the 0x20 sub-header), u32 ?, u32 4
    page = gs_block/32; strip lands at canvas x=(page%(cw/64))*64,
    y=(page/(cw/64))*32. Pixel bytes start at data_off+0x20.

entry table — first_strip.data_off − entry_count*0x60, one 0x60 entry each:
  +0x00  u32 gs texture base (blocks)
  +0x04  u32 fmt        0x13 = PSMT8 (paletted), 0x00 = raw PSMCT32
  +0x08  u32 width      (PSMT8-space px for fmt 0x13; CT32 px for fmt 0)
  +0x0C  u32 height
  +0x10  u32 x          position in the 2×-dims PSMT8 index space
  +0x14  u32 y          (1× CT32 space for fmt 0)
  +0x18  u32 CBP        CLUT base pointer, GS blocks
  +0x1C  u32 flags?
  +0x20  u32 pal_x      CLUT tile position in CT32 canvas coords —
  +0x24  u32 pal_y      redundant with CBP (verified via blockTable32 math)
  +0x28  u32 0, +0x2C u32 0x400, +0x30..0x40 zero
  +0x40  char[32] texture name, NUL-padded  ("hair_longL02", "kosmos_hada00"…)
```

Decode: compose canvas → `unswizzle8` (the standard PS2 routine, as in XS1
`browse.py`) → per entry, look up its 16×16 CLUT tile at (pal_x, pal_y) with
the XS1 CSM1 de-swizzle, index the (x,y,w,h) region. fmt 0 entries (H-model
faces) are read straight from the canvas as RGBA.

This solves, for character models, what disc-catalog.md lists as the open
"swizzled-sheet palette↔region binding" thread — the binding is explicit in
the entry table. (The menu-overlay binding for the 8 standalone swizzled UI
XTX sheets remains open.)

## The pink-KOS-MOS result (what a modder pipeline needs)

* **Recolor = CLUT edit only.** XS3 hair is fully paletted — no true-color
  trap like XS1's long-hair atlas region. Editing 16×16 CLUT tiles in place
  (same-size, RGB words only) changes nothing structural.
* **Carriers.** A whole-disc sweep for the hair texture names found them in
  exactly 25 files, all `mdl/chr/pc/C3kosmos*.chr` / `C3kosmosH*.chr` — plus
  `C3kosmosH09.chr` (different hairstyle entry names) and `C3kosmosL00.chr`
  (2-entry low-LOD sheet). No copies hide in maps, events, battle bundles or
  story containers: `pac/bat|cf/*.sme` txy blocks are effect textures only,
  `kao/*.xtx` portraits are the separate (already-cracked) linear 2D format.
  Cleaner than XS1's 12 buried duplicates.
* **CLUTs differ per file** (8 distinct hair palettes across the 27 — baked
  lighting/costume grading), so the XS1 byte-signature sweep does NOT work.
  The mod must parse each file structurally and recolor per-tile. The
  hue-band selector + rose-pink rotation from XS1 `pinkhair.py`
  (`_is_hair_blue` / hue 0.92) transfer unchanged; 27 files, ~34,400 palette
  words total, face/eye/skin untouched.
* **Write-back is trivial** — no compression anywhere in the path:
  `ISO byte = 0x630800 + Lba0_offset` (X3.01 and X3.02 are contiguous in the
  ISO; formula covers the whole Lba0 chain). Same-size in-place write +
  read-back verify. **Disc 2 is identical**: same X3.01/X3.02 content at the
  same extent 0x630800, so the same patch bytes apply verbatim.
* **Engine check.** A patched Disc 1 ISO boots in PCSX2, loads a
  mid-Chapter-2 save, and **renders the recolor on screen** — confirmed
  visually with a companion pink-Shion patch (all 23 `C3shion*.chr`; her
  chestnut hair needs a dark-warm band filter on face-shared tiles instead
  of the blue detector, tiles classified by entry names: hair/matu-exclusive
  → full recolor, face-sharing → band, skin/brow/eye tiles untouched).
  KOS-MOS's own render awaits a Chapter-3+ save (she joins the party there).

## Open threads

* `pxy` mesh→texture-entry assignment (which mesh uses which entry) — not
  needed for recolors, needed for glTF export.
* `C3kosmosH09.chr` hair entry names (recolor works via the blue-band filter
  anyway); `kao/` portrait recolor for menu-consistency of a hair mod.
* Whether battle models reference `C3kosmos00.chr` or a `pac/bat` copy of
  geometry — textures for the field/battle model come from the .chr either
  way (no hair textures exist anywhere else).
