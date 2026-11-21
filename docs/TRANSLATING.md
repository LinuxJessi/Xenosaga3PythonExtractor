# Translating Xenosaga Episode III

This kit exports the game's text to plain UTF-8 files. You edit them in any
text editor, then write them back into **copies** of your discs. The original
images are never written.

Works on the USA retail discs (SLUS_213.89 / SLUS_214.17), the May 2006
prototype, and the Japanese retail discs (SLPS_256.40 / SLPS_256.41).

> **Partly checked in the game (2026-11-20).** USA Disc 1 copies written by
> `text-import` booted in PCSX2 2.9.175 and showed the edits: a same-size
> `menutext.txd` edit, and a `synopsis.txd` grown past its allocation and
> appended with `--grow` (captures and the table in [UPDATES.md](UPDATES.md)).
> Everything else below comes from the kit's own tests (round trips, read-back
> of the patched copies, refusals): Disc 2, the Japanese discs, subtitles,
> `batdat.bin`, the mnu databases and grown `.sb` files have not been booted.

## The workflow

```sh
# 1. export Disc 1 and Disc 2 together into ONE tree
python cli.py text-export --iso "Disc 1.iso" --iso "Disc 2.iso" --out text/

# 2. edit the .txt files under text/ (keep text/xs3-text-export.json)

# 3. check and write into copies (both discs at once)
python cli.py text-import --iso "Disc 1.iso" --iso "Disc 2.iso" --text text/ --out patched/ [--grow]
```

You can add `--dry-run` to step 3: it runs every check and prints the plan,
but writes nothing. `--report r.json` saves the report as JSON.

The tree mirrors the in-game paths, for example
`text/cf/us/1210.sb.txt`, `text/mnu/us/menutext.txd.txt` and
`text/mov/us/s000300.txt.txt`.

Files in chain 0 (the X3.00 family) are the same on both discs, so they
appear in the tree once. On import they are written to **both** discs, at the
same place, so X3.00 stays identical on the pair. Files in a story chain go
only to the disc that holds them: chain 1 to Disc 1, chain 2 to Disc 2. If you
import with only one disc, edited files that live on the other disc are
refused.

When no file has changed, `text-import` writes nothing and says
`no object changed: nothing written`.

## What is in the tree

| kind | on the disc (xx = `us` or `jp`) | form |
|---|---|---|
| sb | `cf\xx\*.sb`, `bat\xx\*.sb` (scene scripts) | `### NNNN role [codec]` blocks |
| txd | `mnu\xx\*.txd` (menus, synopsis, disc change) | `### NNNN` blocks |
| nj | `mnu\xx\DBC.bin`, `DBC2.bin`, `MVtext.bin`, `SegmentFileData.bin`, `njBtlText.bin`, `njDBcommon.bin`, `njDataText.bin` | `### BB.KKKK` blocks |
| msgdat | `mg1\xx\Message.Dat` (HaKox mini-game) | `### NNNN` blocks |
| batdat | `bat\xx\batdat.bin` (battle names and descriptions) | `### TT.KKKK` blocks |
| subtitle | `mov\xx\*.txt`, `mov\xx\bat\*.txt`, `evt\xx\*.txt`, `mnu\pse\*.txt`, `mnu\pse\xx\*.mes` | the whole file |

Counts per disc:

| build | objects |
|---|---|
| USA Disc 1 | 886 |
| USA Disc 2 | 869 |
| USA Disc 1+2 tree | 919 |
| prototype | 886 |
| JP Disc 1 | 1,025 |
| JP Disc 2 | 1,010 |

`.xep` files are not covered: their format is not decoded.

### Block files

```
# cf\us\1210.sb  147 strings  text pool at 0x2AE4 (3664 bytes)  file 16080 bytes
### 0003 dialogue
Disembark the E.S.?<f>
### 0004 identifier
ce100_045
### 0005 dialogue
***************************************************
### 0006 note cp932
＊BGM設定＊
```

(an excerpt of the real export of USA Disc 1)

- Each `### KEY` line starts one string. The line after it is the text.
- Every block must come back: the same keys, in the same order, none
  missing and none added.
- The words after the key (`dialogue`, `identifier`, `note cp932`, `fixed`)
  are for information only. Each string's codec comes from the manifest.
- Inside a block, a line that starts with `#` is a comment. A string that
  really starts with `#` is written `⟦23⟧`.
- `⟦XX⟧` is one raw byte. It is written as given and never checked against
  the font.
- The game's line break is `\n`, typed as a backslash and an `n`. If you type
  a real line break inside a block, the lines are joined with `\n`.
- Keep the game's own codes as they are:
  - `[Speaker]`, `<lN>` (number of lines), `<wN>` (wait), `<f>` (end of page)
  - `$col…;`, `$ay…;`, `$ruby…;` and the other `$` commands
  - the `<kWORD>` tags
- `identifier` strings are labels and voice ids that the script looks up by
  name. Changing one prints a warning.

### Whole files (subtitles, pse)

A whole file is the disc file's text, comment lines (`;`) included.

- Line ends (LF, CR LF, mixed) are kept. If your editor rewrites every line
  end but the number of lines stays the same, each line gets its original
  line end back.
- A UTF-8 BOM is ignored.
- A cue is `mm:ss:ff<TAB>text`, a plain frame count, or either of those with
  a leading `+` (relative to the previous cue).
- A time with no text clears the subtitle. `end` closes the file.

## Region rules

The build profile (`region.py`) decides the language folder and how bytes
become characters. Nothing is guessed per string on the Japanese build.

### USA discs and the prototype (`us` codec)

The USA print function reads:

- **Latin-1 single bytes**, so `é`, `ö`, `â`, `®` and `Möbius` work as typed;
- **a short whitelist of symbol pairs**: `× △ □ ○ ★ ― 【 】 → ♪ ０-９ Ⅰ Ⅱ Ⅲ`
  and the Greek row (`Σ Ω α β`…; lead bytes A1, A2, A3, A6, AD; see
  `textcodec.py`). The font check passes all of them on USA Disc 1.

Japanese kana and kanji cannot be typed into the USA build, and neither can
Cyrillic, `œ` or `€`. The A4 kana row is exported as `⟦A4⟧⟦xx⟧` escapes,
because the USA font holds Latin glyphs in those cells. Text in another script needs the font and
langpack tools (`docs/FONT.md`, glyphs).

The USA scripts also hold developers' notes, which are never shown. They
export in their exact Shift-JIS (`note cp932`) or EUC (`note euc_jp`)
reading. 16 Japanese placeholder lines on Disc 1 export as `untranslated`.

### Japanese discs (`jp` codec)

Every byte from 0xA0 up starts a two-byte EUC-JP character. Type normal
Japanese, or full-width Latin such as `ＫＯＳ－ＭＯＳ`.

The JP codec refuses:

- half-width kana (`ｱ`): type the full-width `ア`;
- JIS X 0212 and Latin-1 accents (`é`);
- typed pieces that would fuse into one pair.

Plain ASCII letters are drawn from the 8×8 system font unless `$han1;` is on.

Other JP rules:

- **Dialogue.** Lines with a `[Speaker]` prefix are tagged `dialogue`. On JP,
  `<lN>` is optional. All other strings, the notes included, are tagged
  `text` and use the JP codec.
- **Ruby.** Ruby in subtitles is written `[漢字/かんじ]`. In `mov\jp\bat\`
  files the reading must be hiragana or katakana only.
- **No `mono` subtitles.** The JP subtitle loader has no mono branch, so a
  `mono` first line is refused.
- **JP-only scenes.** 140 `cf\jp` scenes and `bat\jp\mom1_b02.sb` have no
  USA counterpart. Their header says "JP-only, load status unknown":
  nobody knows yet whether the game loads them.

### The font check

Every character you type into a changed string must:

1. encode under the disc's codec, and
2. when the string uses the build's display codec (`us` or `jp`), have a
   glyph with ink in font0 or font1 **of the disc being patched**. The kit
   finds the glyph by following the game's own code-to-cell rules: the pair
   gate, the row rules, the extra-kanji lists and the proportional limit,
   all read from the disc's executable.

Some characters are not checked:

- characters the original string already held;
- the full-width space;
- `⟦XX⟧` escapes.

Strings that are never drawn (USA notes, the cp932 pse director scripts) only
have to encode.

Example: on JP, `縊` (E5D0) encodes but has no glyph in either font, so it
is refused. One retail line already uses it, in `bat\jp\RAV_B02.sb` #0017.
That line is left alone because it is unchanged.

A disc whose executable gate was patched (`glyphs-unlock`) no longer matches
any known build, so text-import refuses it.

## Budgets and growth

**No loader buffer size is known for any XS3 text file.** That covers the
.sb scripts, .txd tables, mnu .bin databases, Message.Dat, batdat.bin,
subtitles and .mes files. The US survey lists all of them as open.

So `text-import` refuses any file that would get **larger** than its retail
size unless you pass `--grow`. With `--grow`:

- a file that still fits its sector allocation (the gap to the next file) is
  written in place, and its size field in the index is updated;
- a file that does not fit is appended at the end of the image and its index
  entry is repointed. On a pair, a grown chain-0 file goes to the same LBA on
  both discs. To make that possible, the shorter image is first padded to the
  longer one's end. For example, USA Disc 1 grows from 1,915,920 to about
  2,205,067 sectors. See `docs/REPACK.md`.

Shorter and same-length edits never need `--grow`.

The images must stay under the DVD-5 sector count. `--ceiling none|N`
changes that limit for images used only in an emulator: past DVD-5 a
single-layer image is one volume with no layer break, so it cannot be burned,
and whether PCSX2 accepts it is untested (the kit warns). `--ceiling dvd9`
is refused on these single-layer images, since the result would not be a DVD-9.

The report lists each changed file: chain, retail size, new size, allocation
and action (`in-place`, or `grow (append at image end)`).

These limits are always enforced, `--grow` or not:

- `mov\jp\bat\*.txt`: at most 1,024 bytes. This is the developers' own note
  in each file ("ファイルサイズ制限あり 1K以内に納めること"), not a measured
  buffer size.
- `batdat.bin` tables with u16 offsets cannot pass 64 KB, and
  `Message.Dat` on JP (u16 offsets) cannot either.
- Strings in `DBC2.bin` and `njDataText.bin` marked `fixed` hold a pointer of
  unknown meaning into their middle, so they cannot change.

## Refusals

Nothing is written unless every file passes. These are refused:

- a disc of an unknown build;
- discs of two different builds (USA + JP, retail + prototype);
- two images with the same disc number;
- a tree exported from another build;
- a file whose disc bytes differ from the export's sha1, for example an
  image you already patched. `--rebase` applies the tree to the current bytes
  anyway; the keys must still match;
- missing, renamed or reordered blocks;
- characters that do not encode, or that have no glyph;
- growth without `--grow`;
- a JP subtitle rule broken (`mono`, the 1K note, malformed ruby, a bad time);
- an edited file that lives on a disc you did not give;
- anything `patch.py` refuses (the sector ceiling, shared-sector entries
  without `--grow`, and so on).

A tree file that is byte for byte as exported is skipped, so `--rebase` never
re-applies untouched files.

## Japanese ↔ English side by side

```sh
python cli.py align-export --jp JP1.iso --jp JP2.iso --us D1.iso --us D2.iso --out align/
```

This writes three outputs:

- `align/align.tsv`: one row per pair, with kind, file, keys, method, roles,
  speakers and both texts;
- `align/align.json`: the same rows, plus per-file counts and the learned
  speaker map;
- `align/srt/**.{jp,en,dual}.srt` for every subtitle file.

How each kind is paired:

| kind | method | result |
|---|---|---|
| .sb, same string count | index for index | 567 files |
| .sb, different count | aligned on identifiers and speakers (`difflib`) | 148 files: 22,380 pairs; 1,290 JP and 651 USA strings left unpaired and listed |
| .txd | index for index | `menutext` 907–908 exist only on JP |
| subtitles | time overlap | 177 files, 2,186 JP cues paired, 14 JP and 25 USA cues unpaired |

- Speaker agreement is 94.8% over all paired dialogue, and 91.2% inside the
  aligned files.
- The two builds' subtitles were timed independently, which is why they are
  paired by time overlap rather than by line.
- Not paired: the mnu .bin databases, Message.Dat and batdat.bin.

## What has been tested

All of these tests ran on APFS clones of the real images, and every clone was
deleted afterwards.

**Round trips.** Exporting, then rebuilding every file unchanged with a full
re-encode, gives byte-identical files:

| disc | files |
|---|---|
| USA D1 | 886 |
| USA D2 | 869 |
| prototype | 886 |
| JP1 | 1,025 |
| JP2 | 1,010 |

**Import:**

- **Unchanged tree on D1+D2.** No change; nothing is written.
- **Same-length edit.** A menutext line edited on a D1+D2 pair is written in
  place on both discs. It reads back through `disc.Disc` and `txd`, and X3.00
  stays identical on the pair.
- **Longer edit.** The same line made longer is refused without `--grow`.
  With `--grow` it is written in place (15,388 → 15,411 bytes) and the index
  size updates on both discs.
- **Edits past the allocation.** A menutext line, a chain-1 subtitle and a
  chain-2 subtitle, all grown past their allocation, are appended:
  - the menutext lands on the same LBA (2,205,056) on both discs;
  - each subtitle lands only on its own disc.
- **JP1 `cf\jp\1220.sb` #116.** The edited line is written to a JP1 copy
  and re-extracts as edited.
- **Refusals.** Each of these was refused:
  - a sha1 mismatch on an already patched pair;
  - Cyrillic typed into the USA build;
  - USA D1 + JP D2;
  - a USA tree imported into a JP disc;
  - `縊` (no glyph) on JP;
  - half-width kana on JP;
  - a `mono` JP subtitle.

**Not tested in the game:**

- any edited line;
- the grown or relocated files;
- the Disc 1 padding rule;
- growth of a .sb pool beyond its retail size;
- the subtitle packer's size rule (not ported);
- the batdat string fields, which come from the file structure and have not
  been confirmed from the battle code.
