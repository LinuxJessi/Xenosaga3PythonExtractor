# Modding Xenosaga III character textures — the human guide

How to recolor or repaint any character on the XS3 discs yourself, from
"three commands" to "hex editor and a calculator." This is the process that
produced pink KOS-MOS and pink Shion; everything here was verified against
the real discs and confirmed rendering in PCSX2.

Byte-level format reference: [chr-txy-format.md](chr-txy-format.md).
Tool: [`chrtex.py`](../chrtex.py) (stdlib-only Python 3, no installs).

Everything here is also wired into the kit proper: `cli.py` exposes the
same operations as `chr-*` subcommands with `--flag` arguments (see the
README table), and the GUI has cards 10–13 for the common path (decode →
export palettes → edit → import → ISO sweep). The examples below use
`chrtex.py` directly because it is the shortest to type; swap in
`python3 cli.py chr-decode --chr file.chr --out dir/` etc. if you prefer
the kit-style interface or are using the Windows release build
(`xeno-cli.exe chr-decode ...`).

---

## 0. Quick start: pink Shion in three commands

```sh
cp -c "Xenosaga ... (Disc 1).iso" PINK.iso        # instant APFS clone
python3 chrtex.py iso-sweep PINK.iso shion         # recolor all 23 Shion .chr
# boot PINK.iso in PCSX2, load your save — pink hair
```

`iso-sweep <iso> kosmos|shion [hue]` recolors every matching character file
in place and verifies each write by reading it back. Hue is 0..1 around the
color wheel: `0.92` rose pink (default), `0.0` red, `0.33` green, `0.66`
blue, `0.83` purple.

**Always work on a copy of the ISO.** `cp -c` on macOS clones instantly
(copy-on-write) — you keep a pristine original for free.

---

## 1. The mental model (read this once)

- Each disc hides its files inside big containers (`X3.01`, `X3.02`…)
  indexed by the `Lba0/1/2.txt` tables (`offset|size|id|path` per file).
  `X3.01`+`X3.02` sit back-to-back in the ISO, so for any file in Lba0:
  **ISO byte = 0x630800 + Lba0 offset**. Same on both discs — Disc 2
  carries identical copies at the identical location, so any Lba0 patch
  applies to both discs verbatim.
- A character is a `.chr` file (e.g. `\mdl\chr\pc\C3shion00.chr`). Inside,
  the `txy` block holds all its textures: an image atlas of 8-bit
  *indexed* pixels plus 16×16-pixel *palettes* (CLUTs), one per material.
  A texture's color scheme is entirely in its 256-entry palette.
- Because of that, **recoloring never touches pixels** — you edit a few
  hundred palette bytes and the whole hairdo follows. And because nothing
  on the disc is compressed, edits drop straight back in at the same size.
- Each character has many `.chr` variants (costumes `00..NN`, high-res
  cutscene models `H00..`, a low-LOD `L00`) and each variant has its *own*
  palettes (lighting is baked in — they are similar, not identical). A
  complete mod re-runs the same recolor on every variant; that's what
  `iso-sweep` automates. KOS-MOS = 27 files, Shion = 23.
- Textures are *named* on disc (`hair_longL02`, `shion_face00`,
  `kosmos_hada00` = skin, `mayuge` = brows, `kutu` = shoes…), which is how
  scripts and humans decide what to touch.

## 2. Get a file out and look at it

```sh
python3 chrtex.py iso-extract GAME.iso '\mdl\chr\pc\C3shion00.chr' shion.chr
python3 chrtex.py decode shion.chr out/
```

`out/` now has one PNG per texture (numbered, named), plus
`_canvas_ct32.png` (the raw atlas — you can literally see the palette
tiles parked in it) and `_atlas_index.png` (the indexed image). Browse the
PNGs to find what you want to change and note its name.

## 3. Pick your editing path

### A. Scripted recolor (what the pink mods use)

`pink-kosmos` / `pink-shion` are worked examples on a single `.chr`;
`iso-sweep` applies them disc-wide. Two selection strategies, worth
knowing if you write your own:

- **Color-band filter** (KOS-MOS): her hair is the only blue thing, so a
  "is this blue?" test over every palette entry is safe. One-liner rules,
  no name knowledge needed.
- **Tile policy by name** (Shion): chestnut hair lives in the same warm
  range as skin, so color rules alone would bleed. Instead: palettes used
  *only* by hair textures get recolored wholesale; palettes shared with a
  `face` texture get a dark-warm band filter (light skin spared by a
  brightness ceiling); palettes touching skin/brow/eye names are left
  alone. Copy `recolor()` in `chrtex.py` and adjust the rules — it's ~30
  lines.

### B. Image editor (GIMP / Photoshop / Krita / Aseprite)

The palettes themselves are editable as images:

```sh
python3 chrtex.py export-palettes shion.chr pal/
#   pal/pal_224_112__shion_hair00.png   <- 16x16, one pixel per color
open -a GIMP pal/pal_224_112__shion_hair00.png
python3 chrtex.py import-palettes shion.chr pal/ shion_edited.chr
```

Each PNG is a 16×16 swatch grid: **one pixel = one palette entry**, in
logical ramp order, alpha already un-scaled for you. Zoom to 1600%, use
Hue-Saturation / Curves / hand-painting — anything, as long as you:

- keep it exactly 16×16,
- export as 8-bit RGB or RGBA, non-interlaced (every editor's default),
- keep the filename (`pal_<x>_<y>__<name>.png` — the coordinates say
  which tile it goes back into; the name suffix is just a hint).

Only files present in the directory get imported, so delete the swatches
you didn't touch. Gradient-mapping a hair ramp in an editor gives far more
artistic control than a scripted hue rotation — ombre fades, two-tone,
whatever you can paint into 256 pixels.

To preview: `decode` the edited `.chr` again and look at the PNGs before
ever booting the game.

### C. Repainting pixels (experimental)

```sh
python3 chrtex.py import-entry shion.chr shion_hair00 painted.png shion_edited.chr
```

Takes a PNG the same size as the texture and writes it into the atlas,
quantizing every pixel to the texture's *existing* 256-color palette
(nearest color; the palette itself is unchanged — combine with a palette
edit if you need new colors). Good for drawn-on details in the texture's
own color range: strand highlights, patterns, insignia. Limits: palette
quantization can band smooth gradients, and overlapping atlas entries
share pixels (the tool warns). Round-trip verified: reimporting a decoded
PNG reproduces the original bytes' output exactly.

Faces on high-res `H` models are raw truecolor (`fmt 0` in the decode
listing) — `import-entry` doesn't handle those yet; everything else,
including all hair, is paletted.

## 4. Put it back

Single file:

```sh
python3 chrtex.py iso-patch PINK.iso '\mdl\chr\pc\C3shion00.chr' shion_edited.chr
```

Size-checked, read-back verified. Repeat for each variant you edited
(`C3shion03`, `C3shionH00`, … — the field model your save uses is the
plain `00`, so for a quick test that one file is enough; cutscenes use the
`H` models).

Both discs: run the same commands against a Disc 2 copy — identical
offsets, identical bytes.

For batches (or non-texture files), the general layer is
[`repack.py`](../repack.py): keep your edited files in a directory that
mirrors the game tree and `repack-tree` patches them all at once — see
[REPACK.md](REPACK.md).

The patched ISO also works on real hardware (burn / USB-load) — it's a
plain same-size byte edit, no filesystem changes.

## 5. See it in-game

Boot the patched ISO in PCSX2. Two gotchas:

- **Savestates carry stale textures.** A state made on the original ISO
  restores the old VRAM, so hair stays brown until the game re-streams the
  model (any map transition). Loading a *memory-card save* from the title
  screen always streams fresh from disc.
- PCSX2's auto-resume state counts as a savestate for this purpose.

No checksums, no anti-tamper — the game reads whatever the LBA tables
point at.

## 6. No tools at all: the hex-editor path

Everything above is arithmetic on the format spec; a hex editor (or
`xxd`/`dd`) can do it. Worked example — KOS-MOS's main hair palette in
`C3kosmos00.chr`:

```
txy block starts at file offset 0x3A980 (Xc header table -> txy entry + 0x40)
hair_longL02's palette tile sits at canvas (304, 32)
canvas row 32 lives in strip 2 (record table: data at txy+0xD790, 384 wide)
  -> tile row 0 = 0x3A980 + 0xD790 + 0x20 + (0*384 + 304)*4 = file 0x485F0
  -> 16 rows of 64 bytes, one canvas row (0x600 bytes) apart:
     0x485F0, 0x48BF0, 0x491F0, ... 0x4DFF0
in the Disc ISO the file starts at 0x630800 + 0x0CCF6000, so row 0 is at
     ISO offset 0xD36EDF0    (bytes there: 45 50 85 00 44 4F 83 00 ...)
```

Each 4-byte group is one R,G,B,A palette entry (alpha 0x00–0x80; the GS
doubles it). `45 50 85` is a dusty blue — overwrite R/G/B, leave A, and
that hair color is yours. The 16 rows are stored in CSM1 order (rows 8/16
of each 32-entry group swapped) — irrelevant for "recolor everything
blue-ish," only matters if you care which exact ramp position an entry is.
The spec doc has the full record/entry layouts if you want to find these
offsets for any other file: the entry table gives every texture's palette
position in plain little-endian, with its name right next to it.

## 7. What's still script-only or open

- 2D art (menu portraits in `kao/`, battle faces) is a different, simpler
  format (linear XTX) — decoded by the browse pipeline, no importer yet,
  so a hair mod currently leaves portraits in the original color.
- `fmt 0` truecolor regions (H-model faces): decoded, not importable.
- Length-changing edits (bigger textures) would need LBA/container
  rebuilding — nothing supports that yet; stay same-size.
