# XS3 character textures: the embedded `txy` format (and how to recolor them)

> **2026-09-24 additions** (from the improvement run, see UPDATES.md): the
> same `txy` block is what field maps (`.map`, LZSS-compressed on disc —
> see the "Package compression" section) and weapons carry, and it appears
> free-standing inside `.esd`/`.esp`/`.sme` effect files. Entries come in
> three formats now (`0x13` PSMT8, `0x14` PSMT4, `0x00` raw CT32); the
> strip count lives in the table header; version-2 blocks carry a second
> upload bank. Sections marked **[2026-09]** below are the corrections.

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
  +0x00  "txy\0", u32 version (1 = characters/weapons/battle maps, 2 = field maps)
  +0x08  u32 total size of the txy block
  +0x10  u32 record-table offset (0x90 in all observed files)
  +0x14  u32 second-bank table offset   [2026-09] version 2 only (0 otherwise);
         +0x18/+0x1C reserved for further banks (always 0 on Disc 1)

record table (0x20-byte records):
  record 0 — canvas descriptor:
    u32 ?, u32 ?, u32 canvas_width(512), u32 canvas_height, u32 0,
    u32 strip_count, u32 entry_count, u32 0
    NOTE: canvas_height says 128 even when 9-strip H models stack pages to
    256 rows — compute the real height from the strips, not this field.
    [2026-09] word 5 is the STRIP COUNT (4 for characters, 8 for field
    maps). Read exactly that many records: the 8-strip maps have no zero
    terminator — the entry table starts right after strip 7, and reading
    "until a zero record" swallowed entry 0 as a bogus 64×64 strip.
  records 1..n — CT32 strip uploads:
    u32 data_off (txy-relative), u32 gs_block, u32 width_px, u32 height_px(32),
    u32 0, u32 size_qwords (includes the 0x20 sub-header), u32 ?, u32 4
    page = gs_block/32; strip lands at canvas x=(page%(cw/64))*64,
    y=(page/(cw/64))*32. Pixel bytes start at data_off+0x20.

entry table — first_strip.data_off − entry_count*0x60, one 0x60 entry each:
  +0x00  u32 gs texture base (blocks)
  +0x04  u32 fmt        GS PSM code: 0x13 = PSMT8 (256-colour), 0x14 = PSMT4
                        (16-colour) [2026-09], 0x00 = raw PSMCT32
  +0x08  u32 width      (PSMT8 space = 2× canvas px for 0x13; PSMT4 space =
  +0x0C  u32 height      2× wide / 4× tall for 0x14; CT32 px for fmt 0)
  +0x10  u32 x          position in that format's pixel space
  +0x14  u32 y
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

### PSMT4 entries (fmt 0x14) **[2026-09]**

About a quarter of all package entries (small decals on characters —
weapon lettering, glasses — and most field-map tiles) are 4-bit. The GS
lays a PSMT4 image over the same memory as 128×128-pixel pages of 32
blocks (32×16 px each) in the order

```
 0  2  8 10 | 1  3  9 11 | 4  6 12 14 | 5  7 13 15
16 18 24 26 | 17 19 25 27 | 20 22 28 30 | 21 23 29 31   (4 across, 8 down)
```

Each block is 4 columns of 32×4 nibbles = 16 words. Within a column,
pixel (cx, cy) sits in word `CW4[cx + 32*cy]` at nibble `CB4[...]`:

```
CW4 rows 0..3:  0-7 ×4 | 8-15 ×4 | 4,5,6,7,0,1,2,3 ×4 | 12..15,8..11 ×4
CB4 rows 0..3:  (0×8,2×8,4×8,6×8) | same | (1×8,3×8,5×8,7×8) | same
odd-numbered columns XOR the word index with 4 (the PSMT8 "swap selector")
```

The word address maps back to the CT32 canvas through the usual PSMCT32
page/block/column layout (`chrtex.swizzle4_offset`). The 16-colour CLUT is
the 8×2 CT32 tile at (pal_x, pal_y) in CSM1 order (no swap). Verified
against the proven PSMT8 path (a table-driven reader reproduces
`unswizzle8` byte for byte) and visually on `mdl/map/bat/BSP_B01.map`.

### Two upload banks (txy version 2) **[2026-09]**

Field maps store a second strip table at header +0x14 with its own
canvas descriptor and strips but the **same entry table**. The engine
uploads bank 1, then bank 2 over it; bank 2's lower pages are narrower
(256 px), so bank-1 pixels survive to the right of them. Decoding against
bank 1 alone left 118 of E3_CIT01's 315 entries fully transparent (their
CLUT or pixels live in bank 2); `compose_canvas` now overlays the banks
in order and every entry renders. Residual: ~20 entries per big map
(glass-reflection sheets, flags, holo panels) still read as noise — their
palette is runtime state (the bank-2 upload overwrites it) and would need
a live-VRAM capture.

### Package compression **[2026-09]**

Characters and weapons are stored, but every field map (`E3_*.map`, 98 on
Disc 1) is an LZSS-compressed MR package (version word `0x0401`). The
loader dispatch and all four decoder flavours are ported in
[`xcpack.py`](../xcpack.py); `chrtex.load` / the browse sweep decompress
transparently and the CLI's `xc-unpack` writes the stored form. In-place
editing of a compressed package is refused (no recompressor yet).

### Free-standing txy records **[2026-09]**

`.esd` / `.esp` effect libraries and the `esp` member of `.sme` bundles
carry textures as records of `{u32 total_size, u32 payload_size, u16, u16,
u32 ×2, char name[] ("hamon02.txy")}` (0x40 bytes) followed by the same
`txy` block. `xcpack.iter_txy_records` finds them (a texture *reference*
string also ends in `.txy\0`; the size-consistency test rejects those);
stub records (`tbl_off = 0`, 0x90 bytes) carry no pixels.

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
  Cleaner than XS1's 12 buried duplicates. **[2026-09] re-confirmed by the
  full package sweep**: `browse/package_textures.csv` lists every texture
  on the disc by pixel hash, and the KOS-MOS hair sheets match nothing
  outside `mdl/chr/pc/` (the `.sme` duplicates are all effect sprites).
* **CLUTs differ per file** (8 distinct hair palettes across the 27 — baked
  lighting/costume grading), so the XS1 byte-signature sweep does NOT work.
  The mod must parse each file structurally and recolor per-tile. The
  hue-band selector + rose-pink rotation from XS1 `pinkhair.py`
  (`_is_hair_blue` / hue 0.92) transfer unchanged; 27 files, ~34,400 palette
  words total, face/eye/skin untouched.
* **Write-back is trivial** — no compression on the character path
  (field maps are compressed, see above):
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
