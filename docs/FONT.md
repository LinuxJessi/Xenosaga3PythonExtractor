# Episode III fonts (`font.py`)

Episode III has two bitmap fonts, `\mnu\xx\font0.bin` and `\mnu\xx\font1.bin`,
where `xx` is `us` on the USA discs and the May 2006 prototype and `jp` on the
Japanese discs (SLPS_256.40/41). They live in the shared X3.01/X3.02 space and
are 0x78C00 bytes each. USA Disc 1, Disc 2 and the prototype carry
byte-identical copies; so do Japan Disc 1 and Disc 2 (font0 sha1 abc98640…,
font1 ffd061a5…), which differ from the USA pair. The game takes `xx` from the
table `jp jp us en de fr it es zh ko` (SLUS VA 0x53FCC8, SLPS 0x53E508),
picked by the byte at 0x4B377E (SLPS 0x4B1EFE); `FUN_00181c18` maps 0 to `us`
on USA and to `jp` on Japan.

New glyphs for a translation (other scripts, accents, Japanese in the USA
build) go in through `glyphs.py`, described at the end.

`font.py` started as a copy of the XS2 kit's `font.py`. The file layer and the
addressing were rewritten for Episode III. The PNG code and the sheet convention
were kept. The file layer has no region branch (the round trip is byte-exact
on all four fonts); the addressing is region-parameterised, with every rule
read from the executable (see "Regions").

## File layout

| offset  | size     | contents |
|---------|----------|----------|
| 0x00000 | 0x78000  | 1,024 cells of 480 bytes. Each cell is a 20x24 PSMT8 image, row-major, not swizzled. Each byte packs four 2-bit planes: plane k = `(byte >> 2k) & 3`. |
| 0x78000 | 0x400    | 512 `(left, right)` byte pairs, indexed by base cell |
| 0x78400 | 0x800    | 1bpp 512x32 system font (8x8 glyphs, MSB first) |

Glyph cell `n` (0..4095) is plane `n >> 10` of byte cell `n & 0x3FF`.
`font-extract` writes each plane as one sheet. Each sheet is 640x768: a 32x32
grid of 20x24 cells, so sheet k holds cells 1024k to 1024k+1023. This is the
same numbering as XS1/XS2, so glyph tooling built for those kits carries over.

Grey levels are 0/85/170/255 for the values 0..3. They are exact because the
engine draws each plane through its own CLUT. TEX0 CBP = 0x3FC0 + ((cell &
0xC00) >> 8), and the four CLUTs are uploaded from SLUS VA 0x4B1E90 (GIF packet
at 0x4B1E40, 32x32 PSMCT32 at DBP 0x3FC0). In CLUT k, index i is white with
alpha (0, 0x2A, 0x55, 0x80)[(i >> 2k) & 3]. The self-test checks this for all
1024 entries on all three images (`Addressing.clut_check`).

Plane 0 holds the JIS rows A1 to AD, remapped. USA fonts:
- cells 0-191: symbols, full-width digits and letters
- cells 192-255: `ä é ê Ä ®` and blanks (the A4 row)
- cells 256-383: cp1252 0x80-0xFF
- Greek, Cyrillic, box drawing and circled numbers after that
- cells 576-959: proportional copies of cells 0-383 (cell + 0x240)

Japanese fonts (checked cell by cell against the USA pair):
- cells 0-191: the same symbols in a different typeface (1 cell identical)
- cells 192-383: the full hiragana (192-275) and katakana (288-383) the USA
  fonts overwrote with cp1252
- cells 576-767: proportional copies of 0-191; cells 768-959: HALF-SIZE kana,
  drawn by the half-size path (control 0x18) as cell + 0x240. Cells 851-859
  (= 275-283 + 576, codes A4F4-A4FC) hold half-size "3 K O S — M 俺 達 子",
  purpose unknown.
- cells 3989+: 24 (font0) / 100 (font1) extra kanji that match the exe's
  lists; the USA fonts carry 87 XS2-era extras that do not.

Planes 1-3 hold the kanji from B0A1 (cell 1024) up, plus the extra kanji from
cell 3989. The 2,965 kanji cells agree between the two regions to within one
grey level (font0 2,965/2,965 with 16 byte-identical: the Japanese font0 is
re-anti-aliased; font1 2,964/2,965 with 2,063 identical).

The metrics pairs match the ink exactly. For every pair with left != 0, the
inked columns of cell + 576 are `[left, right]`: 378/378 in both USA fonts on
all three USA images, 317/317 (font0) and 320/320 (font1) on Japan. Pairs
192-383 describe the cell + 576 images in both regions, so on Japan they are
the metrics of the half-size kana (192/192). Pairs 384-447 are non-zero, but
the code only reads pairs below the prop limit (and the half-size cells).

The 8x8 system font is expanded by `FUN_00181fa0` (high nibble first, bit 3 =
leftmost pixel, through the table at 0x4B3058) into a 512x32 PSMT8H texture.
The exported PNG is that texture. It holds ASCII and half-width katakana.
Which glyph sits at which position (the UV layout) has not been worked out.
That does not affect the round trip.

## Addressing

All tables are read from the boot executable by VA through its program headers.
The data segment maps VA = file offset + 0x11F000 in every build. `PROFILES` is
keyed by the executable's SHA-1 (an executable that differs from a known one
only at the `glyphs.py` unlock sites gets that build's profile). It is not the
same thing as `regions.py`, which assigns LBA tables to X3 containers, nor
`region.py`, which detects the build from SYSTEM.CNF + sha256.

| table | US (SLUS_213.89 = SLUS_214.17) | May 2006 prototype | Japan (SLPS_256.40 = .41) |
|---|---|---|---|
| `$han` ASCII → EUC (u16, base + 2*byte) | 0x4B2E50 | 0x4B2C10 | 0x4B15A0 |
| extra kanji, font0 / font1 | 0x4B3020 / 0x4B2F50 (24 / 100 codes) | 0x4B2DE0 / 0x4B2D10 | 0x4B1770 / 0x4B16A0 |
| control operand lengths | 0x4B3150 | 0x4B2F10 | 0x4B18A0 |
| 0x08 flag-bit lengths | 0x53FD40 (2,2,3,2,2) | 0x53FAE0 | 0x53E580 |
| `$`-command table | 0x4B31B0 (18 entries) | 0x4B2F70 | 0x4B1900 |
| CLUT image | 0x4B1E90 | 0x4B1C50 | 0x4B05E0 |
| pair gate (code) | 0x181E48 | 0x181E48 | 0x181E48 |
| prop gate immediates: printer / measurer | 0x1856E4 / 0x182DD4 | same | 0x185584 / 0x182C7C |
| code → cell function / its jump table | 0x184938 / 0x540080 | 0x184938 / 0x53FE20 | 0x1847D8 / 0x53E8C0 |
| half-size map | 0x181DB8 | same | same (identical code) |

The Japanese table VAs are from the JP synthesis brief; ctl08 and the CLUT were
found here by searching for the retail tables' bytes (one hit each, CLUT 4,096
bytes equal). Each jump-table VA is the one its cell function builds with
`lui`/`addiu` (checked at load: `_lui_refs`).

To find the prototype addresses, each retail table's bytes were searched for in
the prototype's executable, and each was found exactly once. The prototype's
font functions sit at the retail addresses. Disassembled side by side, they
differ only in the immediates that point at these tables.

The functions behind each rule, with SLUS_213.89 addresses:

- **Code → cell**: `FUN_00184938` is ported as `xs3_cell`.
  - Rows A1-AD follow per-row rules (jump table at 0x540080).
  - Rows B0-CF: `lead*94 + trail - 0x3D41`.
  - Lead bytes D0 and up go to `FUN_00181d40`: a lookup in the extra list
    (font0 or font1, chosen by the byte at 0x7E7E06), giving cell 0xF95 +
    index.
  - Anything else falls back to cell 0x7F.
  - Codes A1B9, A1BC, A1F9-A1FE and A2A0-A2AF also get bit 0x1000. The
    proportional test is `cell < 0x180`, so these codes are always fixed width.
    The draw call ignores the bit (`cell_index`).
- **Pair gate**: `FUN_00181e48` (`pair_gate`). The whole function was read.
  - A4 or A6 with any non-zero trail
  - A1 with BD DA DB DF EE F9 FA FB FC
  - A2 with A2-A6, AA-AD, F6
  - A3 with B0-B9
  - AD with B5-B7

  Any other byte from 0x80 up is one character with cell = byte + 0x80 (lead
  A9). (`textcodec.py` carries its own copy, `us_pair`.)
- **Glyph width**: `FUN_00185770` (`Addressing.glyph_width`).
  - `right - left + 3`, or `right + 2` when left == 0
  - cell 0: `$xx1 + 1` (default 4 + 1)
  - while `$xx3` is non-zero: `2*(xx3>>1)`, or 10 when that is 0
  - A fixed-width glyph advances 19. The image of a proportional glyph is
    cell + 0x240.
- **String width**: `FUN_001828a0` is ported as `Measurer.width`.
  - `$prop` and `$han` are flag bits 0 and 1 at 0x7E7E11. Control byte 0x19
    also sets that byte. These are globals, so they carry from call to call.
    `$xx1` / `$xx3` / `$xx7` carry the same way.
  - `$zoom`, control 0x12 (zoom) and 0x18 (half-size mode) last only for the
    current call.
  - Control 0x15 with sub-code 2 or 4 sets xx1 or xx3.
  - ASCII without `$han` is `zoom` pixels wide.
  - Half-size mode measures `half_cell(cell)` (`FUN_00181db8`) proportionally.
  - Per character: `w += ((width + xx7) * zoom) >> 4`.
  - `$rubys; … $rubye;` is skipped.
  - A `$` code without its `;` is refused; the game would read past the end
    of the string.
- **Control bytes**: `FUN_00182290` (`control_length`). Operand lengths come
  from the table above. Two are variable:
  - 0x08: a flag byte whose set bits add 2,2,3,2,2 bytes
  - 0x15: a length byte L and L more bytes

  The main loop passes the start of the sequence. The ruby skip passes one byte
  later, and the Measurer copies that.
- **`$`-commands**: `FUN_00184090`. Names: `ax ay az rx ry init save load col
  bg shadow alpha zoom xx ruby prop han mark`. The first name that is a prefix
  of the text wins. `Addressing.tokens()` splits a string into commands,
  control sequences and characters.

## Regions

`Addressing.from_executable` reads four rules from the code at the profile's
VAs, each checked against the instruction shape it must have (a profile at the
wrong executable is refused, not silently misread):

| rule | read from | USA / prototype | Japan |
|---|---|---|---|
| `gate` | the first 4 words at 0x181E48 | `whitelist` (the function above) | `euc`: `andi v0,a0,0xff; sltiu v0,v0,0xa0; jr ra; sltiu v0,v0,1` = lead >= 0xA0, trail not tested |
| `prop_cells` | both prop-gate `slti`/`sltiu v0` immediates (must agree) | 0x180 (384) | 0xC0 (192) |
| `a9_row` | jump-table entry 8 (lead A9) vs entries 9-11 (AA-AC, the fallback) | own case: `trail + 0x100` | = fallback |
| half-size | 0x90 bytes at 0x181DB8 equal `HALF_FN_CODE` | identical | identical |

What follows on Japan:
- every byte from 0xA0 up starts a two-byte code, whatever follows (`glyph`
  gives length 2; a lead at the very end of the text stops there);
- a lone byte 0x80-0x9F goes down the single-byte path as lead A9, which has no
  row, so it draws cell 0x7F (◯). There are no Latin-1 singles and no SS2/SS3;
- kana (cells 192-383) are never proportional: advance 19 under `$prop1;`;
- the proportional tier is cells 0-191 (images 576-767, metric pairs 0-191);
- half-size mode (control 0x18) measures `half_cell(cell)`, which keeps cells
  0xC0-0x17F, with the metric pair of that cell, and draws cell + 0x240: the
  half-size kana block. Self-test: 2 kana = 38 px under `$prop1;`, a half-size
  あ = pair 193 = 11 px.

Spot values (self-test, both Japanese discs): 亜 B0A1 → 1024, あ A4A2 → 193,
ア A5A2 → 289, Ａ A3C1 → 138, ０ A3B0 → 128, Ω A6B8 → 407.

Coverage (exit test T7, `glyphs-coverage`, parse-only): every two-byte code in
the parsed Japanese .sb (98,836 strings), .txd (1,108), mnu .bin (3,815) and
subtitle/.mes files (150) — 2,151 distinct codes, 1,362,742 uses — resolves to
an inked cell, except A1A1 (the full-width space) and one retail gap: E5D0 縊,
used once in `bat\jp\RAV_B02.sb` ("少々見縊っていたようね"). Lead E5 goes
through the extra-kanji lists and E5D0 is in neither, so the game would draw
cell 0x7F there (not checked in game). 74 codes resolve in only one font; all
are extra-list kanji (lead >= 0xD0), which are per font by design.

## Commands

```
font-extract --iso DISC.iso --out DIR
    font{0,1}.bin (reference copy), _sheet0..3.png, _metrics.csv (slot = base cell,
    drawn_cell = slot + 576), _sys8x8.png, _codes.csv (every single byte 0x20-0xFF
    and every gate-accepted pair: code, cell, 0x1000 flag, sheet, prop, drawn cell,
    pair, advance; for han1 prop1 and han1 prop0)
font-rebuild --ref DIR/font0.bin --sheets DIR [--metrics CSV] [--sys8x8 PNG] --out new.bin
    refuses when nothing is found to apply (unless --allow-unchanged) and refuses to
    overwrite its reference; the size never changes, so repack.py can patch in place
font-measure --iso DISC.iso --text '$prop1;$han1;Text' [--prop] [--han] [--font 0|1]
    cp1252 text, \xNN for raw bytes; the disc's own rules (Japan: euc gate, prop < 192)
font-donor (--from ISO | --from-font0/1 FILE) (--to ISO | --to-font0/1 FILE) --cells N,N-M
           [--font 0|1|both] [--no-metrics] [--prop-images] [--force] [--allow-used] --out DIR
    copy cells (and the metric pairs of cells < 512) from one Episode III font into
    another; writes DIR/font0.bin, font1.bin and donor.json, never a disc. With --to
    ISO, cells that disc's retail text draws are refused unless --allow-used
```

All of them read the font folder (`us` / `jp`) from the executable's profile.

## Japanese glyph donor (`font-donor`)

The round-1 `font-jp-kana` helper copied kana from the Episode II Japan font.
It is gone: the donor must be the Episode III Japan disc, because its font0
kanji are re-anti-aliased and its half-size kana block (768-959) is new.
`donate(src, dst, cells, metrics=True, prop_images=False)` copies the given
cells, the metric pairs of those below 512, and with `prop_images` also cell +
0x240 of those below 384. It first checks that the two files are the same font
of two builds: at least 2,900 of the 2,965 kanji cells must agree within one
grey level (font0↔font0 2,965, font1↔font1 2,964, font0↔font1 0), else it
refuses (`--force` skips this).

The command also refuses cells that the receiving disc's retail text draws
(`retail_cells`, from `glyphs.scan_retail`; a proportional image cell + 0x240
counts for its base cell), unless `--allow-used`. This matters for the kana
block: on USA, cells 256-383 are cp1252 0x80-0xFF and 192-255 hold `ä é ê Ä
®`, so a Japanese kana donated there replaces glyphs that retail English
draws. USA D1 draws 70 of the cells 192-383, for example 361 = é ("Café",
198 hits), 374 = ö ("Möbius", 54), 302 = ® (106), 195 and 203. An unlock does
not help: `SlotModel.code_for(361)` re-codes é to A5EA, which is still cell 361. So
`--cells 192-383` into the USA fonts is refused; give only free cells
(`glyphs-slots` lists them). Without `--to ISO` (font files only) the check
cannot run, and the command warns.

Self-test (USA D1 + Japan D1): the `donate()` API with cells 192-383 changes
exactly the 192 kana cells and metric pairs 192-383 in each font, nothing
else; the command refuses `--cells 192-383` into USA D1 (70 used cells) and
writes nothing; it accepts four free cells; a font0→font1 donation is refused.

Using donated kana in the USA build (cross-region item X2 of the JP brief;
untested in game). The whole block cannot be donated without losing the
accented letters above (`--allow-used` does it anyway, for a build whose
English text no longer needs them):
- the metric pairs 192-383 describe the half-size images, so donate with
  `--prop-images` (cells 768-959) to keep pairs and images consistent;
- USA draws cells below 0x180 proportionally from cell + 0x240, which after
  `--prop-images` is the HALF-SIZE kana. Either apply the `jp-prop` unlock
  (`glyphs-unlock`, prop gate 0x180 → 0xC0: kana fixed width from the base
  cells, as on Japan) or write kana text under `$prop0;`;
- the USA gate reaches A4xx but not A5xx (katakana) or kanji: the `jp-gate`
  unlock gives both, at the cost of re-encoding all English (below);
- extras: `--cells 3989-4088` copies the Japanese extra-kanji cells, which
  match the exe's lists (the USA ones do not).

## Measurer check (retail menutext.txd, Disc 1, font0)

These numbers come from 20 strings, every 17th string longer than 6 bytes, each
measured from a fresh state. Lines are split at CR LF; in the font's control
table 0x0D takes one operand, so CR LF counts as one control sequence.

- Measured from the default state ($prop0, $han0), most lines come out at 16
  px per character. "The three at the top are the attackers in battle." would
  be 784 px, wider than the 640 px screen. So the menus must already have
  `$prop1;$han1;` in effect.
- With `$prop1;$han1;` in effect:
  - "Next Character" = 133 px, "View status." = 104, "Settings" = 71,
    "Please select location." = 189
  - the 2-line help "Learn various single and / range break tech attacks." =
    208 / 222
  - the 4-line memory-card message = 435 / 427 / 431 / 136
- The near-equal first lines (427-435 px) fit a hand-wrapped box about 440 px
  wide, which is plausible. All 907 strings together have 964 lines: 957 are
  under 550 px, one is 550-599 px, and six are wider (next point).
- Six help-bar lines ("View … (switch information with left and right
  directional buttons)") measure 700-763 px. They must be drawn with a smaller
  `$zoom` or scrolled. This was not checked in game.

## New glyphs (`glyphs.py`)

Borrowed from `Xenosaga1PythonExtractor/glyphs.py`: `Glyph`, `GlyphSet` (json,
`from_png`), the `TTFRenderer` (uharfbuzz shaping, fonttools outlines, the
kit's scanline rasteriser) and the glyph keys `langpack` uses. fonttools and
uharfbuzz are required. New: the slot model, the retail scan, the unlocks.

### Slot model (`SlotModel`, `build_model`, `model_from_disc`)

A slot is a cell a code can reach that nothing retail draws. Reachable cells
come from the build's addressing (`reachable`: every single byte the gate
leaves alone, every gate-accepted pair with an EUC trail A1-FE, leads below
0xD0; 0x1000-flagged and fallback results are not slots). Reserved:
- cell 0, cell 0x7F, the 96 cells of the `$han` table;
- every cell the retail text draws, and its `half_cell` twin;
- cells 576-959 (the images of cells 0-383) and 3989-4095 (extras);
- with a font: a fixed-width cell below 384 whose half-size image has ink
  (on Japan the whole kana block 192-383, including A4F4-A4FC, whose half-size
  images are the "3 K O S …" glyphs; the JP brief's suggestion to use them is
  not taken).

Tier = proportional when the cell is below `prop_cells`, else wide (19 px).
A proportional glyph is drawn ink-aligned at cell + 0x240 with its metric pair
at the cell (advance `right - left + 3`), and centred at the cell for
`$prop0;`. A wide glyph is centred at the cell.

The retail scan (`scan_retail`, parse-only) walks .sb strings (identifiers
skipped; USA developer notes, which are never drawn, skipped), .txd, the
seven mnu .bin databases, mov/evt subtitles and pse .mes files, plausible text
runs of batdat.bin and Message.Dat, and of the boot executable and OV01/02/04.
Parsed strings are walked twice (the printer's walk with operand lengths, and a
plain byte walk) and the union kept, so a misread can only over-reserve. On the
USA gate, Japanese left in the build (16 .sb placeholder lines, AC/PP/opening/
test .mes, the prototype's EUC DBC2, and the hiragana table of the abolished
HaKox password input in Message.Dat, #0587/#0589, prototype #0586/#0588, which
the plausible-run filter misses and the parsed Message.Dat items add) is
counted apart as "untranslated" and is
not reserved unless `--include-untranslated` (those lines draw Latin-1 /
hiragana soup either way).

Numbers (`glyphs-slots`, self-test):

| build | retail cells | free proportional | free wide |
|---|---|---|---|
| USA D1 | 91 (+190 untranslated) | 123 | 51 (A6 384-438, AD B5-B7) |
| USA D1 `--include-untranslated` | 91 + 190 untranslated | 10 | 47 |
| prototype | 88 | 127 | 51 |
| USA D1, unlock `jp` | 91 | 72 | 3,149 (2,965 kanji) |
| Japan D1 | 2,227 | 51 | 1,302 |
| Japan D1 `--require-blank` | 2,227 | 0 | 0 |

No reachable cell of the Japanese fonts is blank, so on Japan (JP brief M22)
the free code space is the reachable cells retail text never draws: unused
symbols and JIS kanji, overwritten. A Japanese-language mod that needs those
kanji must reserve them itself. Latin-1, 8E/8F and 0x80-0x9F are not code
space on Japan.

`GlyphSet.allocate(order, model)` is deterministic: free proportional cells in
ascending order for glyphs up to 18 px of ink, then wide cells; keys already
placed keep their codes; a set made for another build/unlock is refused.
`GlyphSet.check(addressing, model)` verifies that no slot is reserved and that
every code draws its cell. Codes are 1 or 2 bytes, saved as hex in the json.

### Unlocks (`UNLOCKS`, `apply_patches`, `glyphs-unlock`) — NOT tested in game

Patch descriptors (VA, old bytes, new bytes) for the USA / prototype
executable (the words also live in `font.UNLOCK_SITES`). Every old word is
checked before anything is written; a site that already holds its new bytes is
reported, not rewritten; any other content refuses the set.

| mode | sites | effect |
|---|---|---|
| `jp-gate` | 0x181E48: the gate's first 4 words → the Japanese 4 words | every lead ≥ 0xA0 is a pair: kanji rows B0-CF reach cells 1024-3988 (2,965 wide cells), A5 reaches 288-383. USA Latin-1 singles 0xA0-0xFF become leads, so ALL English must be re-encoded: `SlotModel.code_for(cell)` gives each retail cell its new code (é, cell 361: E9 → A5EA; cells 382/383 only through a non-EUC trail, e.g. A76F / A640) |
| `jp-prop` | 0x1856E4 `sltiu v0,s1,0x180` and 0x182DD4 `slti v0,a0,0x180` → 0xC0 | cells 192-383 become fixed width, as on Japan |
| `jp` | both | |

Checked: on the real D1 and prototype executables the old words match and the
patched code reads back as gate `euc`, prop cells 0xC0; `glyphs-unlock`
(then `--patch-iso`, an in-place writer since replaced by `--out`) on an APFS clone of D1 changed 15 bytes and the patched disc
keeps its `us` profile (`profile_for` undoes known unlock sites for the hash);
`model_from_disc` on it reads the retail text under the retail rules and
reports unlock `jp`. The PCSX2 boot test has not been run.

### Commands

```
glyphs-slots    --iso DISC.iso [--unlock MODE] [--require-blank] [--include-untranslated]
                [--font 0|1] [--json slots.json]
glyphs-coverage --iso JP.iso                      # T7; exit 2 on a gap beyond E5D0
glyphs-render   --iso DISC.iso --ttf F.ttf --text "абв" --out gs.json [--png prev.png]
                [--px 20] [--baseline 17] [--direction rtl] [--prop-only|--wide-only] [--keep]
glyphs-apply    --glyphset gs.json --font font0.bin --out new.bin
glyphs-unlock   --mode jp|jp-gate|jp-prop --iso US.iso [--iso US2.iso]
                (--out-exe FILE | --out OUT [--overwrite] [--dry-run])
```

`--out` writes patched copies through `patch.patch_copy` (the sources are never
written, an existing output is refused unless `--overwrite`, and on a pair
both boot executables, SLUS_213.89 and SLUS_214.17, are patched). `--out-exe`
writes one executable file; `patch --iso D1 --iso D2 --set SLUS_213.89=FILE`
then puts it on both discs (a pair's boot executables are byte-identical, so
patch writes the change to Disc 2's own copy too).

## Open

- The glyph order inside the 8x8 system font is not known.
- Half-size mode was ported from the width function only. Ruby layout is not
  modelled.
- The printer (`FUN_00184b30`, JP 0x1849c8) was read by the survey, not
  re-read here. It draws a proportional glyph from cell + 0x240, and the
  Measurer follows the width function.
- Nobody has checked whether the battle/system text paths use the same gate.
- The unlocks, the donated kana and every allocated glyph are untested in
  PCSX2.
- Text inside the overlays is only scanned as plausible runs; overlay strings
  that use rare cells could be missed (they would then be overwritten).
- What A4F4-A4FC (half-size 851-859) are for on Japan.
