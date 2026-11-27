# File formats

The byte layout of every format the kit reads or writes, and how each was
proven. This page is the map: one section per format, short enough to read in
one go, each ending with the module that implements it (its docstring is the
full specification) and the page that goes deeper. What each file extension
*is* and where the engine uses it is in [disc-catalog.md](disc-catalog.md).

All numbers are little-endian unless a section says otherwise. "The five
images" are USA Disc 1 and 2 (SLUS_213.89 / SLUS_214.17), Japan Disc 1 and 2
(SLPS_256.40 / 256.41) and the May 2006 prototype.

| Format | Read | Written back | Section |
|---|---|---|---|
| disc indexes X3.00 / X3.10 / X3.20 | yes | yes, byte-identical rebuild | [1](#1-the-disc-three-chains-and-their-indexes) |
| `Xc` packages (`.chr .wpn .map .sme`) | yes, four LZSS flavours | stored form only | [2](#2-xc-packages) |
| `.xtx` UI pictures | yes | yes, same size | [3](#3-xtx-pictures) |
| `txy` texture blocks | yes | palettes and repaints | [4](#4-txy-texture-blocks) |
| `.tm2` logos | yes | yes | [5](#5-tim2-logos) |
| `.pxy` meshes, `.xhr` skeletons | yes, to glTF | no | [6](#6-models-pxy-and-xhr) |
| `.xap` body clips, `.fap` face clips | yes, to glTF animations | no | [6](#6-models-pxy-and-xhr), [MOTION.md](MOTION.md) |
| `.sb` scene scripts | text pool only | text pool, any length | [7](#7-sb-scene-scripts) |
| `.txd` menu tables | yes | yes | [8](#8-txd-menu-text) |
| `mnu\xx\*.bin` menu databases | string pools | string pools | [9](#9-menu-databases) |
| `Message.Dat` | yes | yes | [10](#10-messagedat) |
| `batdat.bin` | 28 tables, string fields | string fields | [11](#11-batdatbin) |
| subtitles, `.mes`, pse scripts | yes | yes | [12](#12-subtitles-and-whole-file-text) |
| `font0.bin` / `font1.bin` | yes | yes, byte-exact | [13](#13-fonts) |
| `.adx` streams | header here, audio through ffmpeg | no | [14](#14-adx-streams) |
| `.dap` sound banks | samples to WAV | no | [15](#15-dtpk-sound-banks) |
| `.sfd` movies | demux; video through ffmpeg | same-size video splice | [16](#16-sofdec-movies) |
| `.xep` / `.xev` events, `.esd` / `.esp` effect parameters, the `.sb` code section | no | no | [17](#17-not-decoded) |

## 1. The disc: three chains and their indexes

The ISO 9660 file system holds only the executables, the IOP modules and a
handful of big files. All game data is in three **chains**, each an index
file followed back to back by its bigfiles:

    chain 0   X3.00 + X3.01 + X3.02            on both discs, identical index
    chain 1   X3.10 + X3.11 + X3.12 + X3.13    Disc 1 (and the prototype)
    chain 2   X3.20 + X3.21 + X3.22 + X3.23    Disc 2

An index is Episode II's front-coded table of contents; even its filler still
reads `MONOLITHSOFT Xenosaga Episode.2`:

    toc    = [u8 own size in sectors] item* [0x00]* filler
    file   = [b]      [code] [literal: b-2 bytes]   [u24 sector] [u32 size]
    cfile  = [b|0x40] [code] [literal: (b&0x3f)-2]  [u24 sector] [u32 csize] [u24 usize]
    dir    = [0x80|n] [u8 pops] [code] [literal: n-3 bytes]
    pop    = [0x00]                     closes one directory level
    code   = 0: the literal is the whole name
             else H = code >> 4, L = code & 15: replace L bytes of the previous
             name starting H + 1 bytes before its end

Sectors count from the first sector of the index file, so an entry's absolute
LBA is the index's LBA plus its sector. No `cfile` (compressed) entry exists on
any Episode III image.

**Proof.** `serialize(parse(file)) == file` for all six index files of the USA
discs and the prototype (X3.00 9,867 entries; X3.10 3,649; X3.20 1,709; the
prototype's X3.10 3,654), and the retail entries equal the bundled
`lba/Lba0/1/2.txt` line for line. `x3index.py` is a second reader written from
the executable (lookup `FUN_00187e28`, directory walk `FUN_00187bd8`, name
decode `FUN_00187b18`) and agrees.

Modules: `toc_bin.py`, `x3index.py`, `chains.py`, `disc.py`. Writing:
[REPACK.md](REPACK.md).

## 2. Xc packages

Every `.chr`, `.map`, `.wpn` and `.sme` is an MR package:

    0x00  "Xc"
    0x02  u16 version   0x0001 stored; 0x0101 / 0x0201 / 0x0301 / 0x0401 compressed
    0x04  u32 payload size, decompressed
    0x08  u32 payload size as stored
    0x0C  u16 sub-resource count      0x0E  "Xp"
    0x10  count x 4-byte type tags ("pxy", "txy", "xhr", "epf", "dap", ...)
    0x40  count x {u32 offset, u32 size}, offsets valid for the decompressed image

The loader (`FUN_001b7330`) picks a decoder by the version word:

* **0x0101 / 0x0201, LZSS-A.** Flag byte, bits from the top; 1 = literal, 0 =
  back-reference `b0 b1`: length `(b0 >> 4) + 3`, distance
  `((b0 & 0xF) << 8) | b1`, distance 0 ends the stream.
* **0x0301, LZSS-B.** Back-reference `b0 lo hi`: `b0 == 0` ends, else length
  `b0 + 1`, distance `u16 + 1`.
* **0x0401, LZSS-C.** A 0 flag bit is followed by a second flag bit: 1 = the
  short form (as A, distance + 1), 0 = the long form (as B).

On Disc 1, 98 of the 168 `mdl\map` packages are 0x0401 (the field maps);
battle maps, characters and weapons are stored. `xcpack.normalize` turns any
package into its stored form, so every parser works on the same offsets. The
kit does not write the compressed forms.

`.xep` event packages begin `Xc\x01\x03` but are not MR packages (no `Xp`,
another header) and do not decode with these schemes.

Module: `xcpack.py`.

## 3. XTX pictures

    0x00  "XTX\0"          0x04  u32 file size      0x08  u32 sub-image count (1)
    0x0C  u32 header size (0x10)
    0x10  u16 width        0x12  u16 format         0x14  u32 height
    0x1C  u32 flags        0x20  u32 offset of the GS upload packet (0x30)
    0x30  32-byte GS upload packet (DMA tag, VIF DIRECT, GIF IMAGE tag)
    0x50  payload: width x height x 4 bytes; the file ends there

True for all 1,875 `.xtx` on the five images. **Pixels start after the
packet**, at 0x50; until 2026-11-20 the kit read them at 0x30 and every
picture came out shifted.

* **Format 0x04** (367 per disc: portraits, most UI): rows of R, G, B, A.
* **Format 0x08** (8 per disc: the `mnu` and `mg1` sheets): the payload is a GS
  memory dump, a 32-bit canvas that really holds an 8-bit indexed picture of
  twice the width and height (Episode I's layout). The 256-colour palettes are
  parked in the same canvas as 16 x 16 tiles. Which palette a sprite uses is
  not in the file: the game addresses them by GS block pointer.
  `engine_palettes.py` carries the bindings read from the draw code (main
  executable, OV01, OV04); where no draw is known, `xtx_decode.plan_palettes`
  ranks the parked tiles. About 22% of the three window sheets is still drawn
  with a ranked palette.

Modules: `xtx_decode.py`, `engine_palettes.py`, `xtx_encode.py` (PNG to
`.xtx`, same size, byte-exact when nothing changed).

## 4. txy texture blocks

The textures of models and effects are `txy` blocks: inside packages, as
free-standing records in `.esd` / `.esp` effect libraries and `.sme` bundles,
and as 82 standalone `.txy` files. A block is a set of 32-bit strip uploads
that compose a GS canvas, and a named entry table of 8-bit, 4-bit and raw
32-bit rectangles with their palette positions; field maps carry two upload
banks. The full specification, with the proofs, is
[chr-txy-format.md](chr-txy-format.md).

Module: `chrtex.py` (decode, palette export and import, repaint, recolour).

## 5. TIM2 logos

Sony's standard TIM2 (`.tm2`), four per disc under `mnu\pse\`. Nothing
Monolith-specific. Module: `tm2_decode.py`; written back by `imagetext.py`.

## 6. Models: pxy and xhr

`.pxy` (version 0.15, the same as Episode II's) is the render mesh: a header,
materials, and VIF command streams that unpack vertex batches for VU1. Episode
III uses three batch layouts: Episode II's float layout, a quantized one
(16-bit positions and normals with a float scale; 35 or more character and
enemy models, KOS-MOS among them) and an unlit one for field maps (baked vertex colours, no
normals). A second complete pxy can sit inside the first, at the offset in
header word +0xD0 (310 maps; the engine draws both). A material finds its
texture by GS address: `TEX0.TBP0 - 0x3800` equals the txy entry's address.

`.xhr` (version 3.0) is the skeleton: six runs of transform records (0x40 /
0x60 / 0x60 / 0x70 / variable / 0x40 bytes). Joint matrix *j* of the mesh
binds to transform *j* + 2, and the rest pose reproduces the mesh.

Motion is in `xap` blocks (body clips, in the `.sme` bundles under `pac\cf\`
and `pac\bat\` and in weapons) and `.fap` files (face clips): curves of
keys per transform, which `xap.py` (the Episode II kit's module, changed for
Episode III's clip versions 1.6 and 1.7) turns into glTF animations. All
5,039 clips of a disc decode. [MOTION.md](MOTION.md) has the layout, the
proofs and what is not yet compared with the running game.

Counts, proofs and what is still unverified are in [MODELS.md](MODELS.md).
Modules: `vif.py`, `pxy.py`, `xhr.py`, `xap.py`, `gltf.py`, `models_sweep.py`.

## 7. SB scene scripts

`cf\xx\*.sb` and `bat\xx\*.sb` (715 files on each USA disc, 856 on Japan
Disc 1):

    +0x00  "SB  "  u16 1  u16 1
    +0x08  u32 offset of the code section (0x40)
    +0x0C  u32 globals      +0x10  u32 TEXT POOL    +0x14  u32 entries
    +0x18  u32 imports ("runtime", "seg", "objx", ...)
    +0x1C  u32 chunk list {u32 id, u32 size, data}; id 1 = source name ("us\2940")

    code     = u32 12, u32 pc of "main", u32 code size, the code bytes
    globals  = u32 8, u32 slots, u32 values[slots]     (the initial values)
    entries  = u32 8, u32 n, n x {u32 name offset, u32 pc}, the names
    imports  = u32 8, u32 n, n x u32 (class name offset << 16 | function name
               offset), the names; both offsets count from the end of the table

    text pool = u32 8, u32 count, u32 offsets[count] (from the end of the
                table), then the strings, NUL-terminated, in offset order,
                padded to 4 bytes

The engine fetches a string by index (`FUN_001d4238`), so the pool can be
rebuilt at any length as long as the header offsets above it move with it.
Everything outside the pool is kept byte for byte: 715 / 715 USA and 856 / 856
Japanese files rebuild identically. The pool also holds identifiers, voice
ids and the developers' notes (Shift-JIS on the USA discs, EUC-JP on Japan).

### The code

A stack machine, the same design as Episode II's (operators, typed arguments,
threads, natives registered by class) re-encoded as **bytes** with short and
long operand forms. Read from the boot executable on 2026-11-21 (USA Disc 1
addresses):

| What | Where |
|---|---|
| interpreter step: fetch the byte at pc, call `handler[op](thread, op)` for `op < 99` | `FUN_001d2738` |
| 99 handler pointers (39 distinct functions, `FUN_001d27e0` .. `FUN_001d3eb0`) | table at `0x407b70` |
| 99 instruction lengths; `switch` is `8n + 6` instead | table at `0x407b08`, read by `FUN_001d2700` |
| operand reader, **big-endian**, a byte at a time | `FUN_001d2498` |
| push / pop (a value stack and a parallel stack of one type byte per slot) | `FUN_001d2630`, `FUN_001d26b0` |
| start a thread at a pc (32 threads of 0x48 bytes at `0x60e140`) | `FUN_001d1cc8` |
| register a native class `(name, table)`; resolve an import to `class << 16 \| index` | `FUN_001d1868`; `FUN_001d1a50`, `FUN_001d1b60` |
| a native reads argument n, its type, "omitted?" | `FUN_001d3fd8`, `FUN_001d4088`, `FUN_001d4108` |
| text pool string by index | `FUN_001d4238` |

A pc counts bytes from the start of the code; a jump is relative to its own
opcode (signed 16 bits, `switch` signed 32). Every push carries a type: 0 none
(an omitted argument), 1 int, 2 text (a pool index), 4 code (an entry's pc),
5 table (a global holding the slot number of a block of globals: on the discs
always the message buffer of `send`/`recv`). Type 3 has push opcodes but no
script uses it.

    00 nop     01 neg     02-12 add sub mul div mod or and shr shl eq gt lt ge le ne lor land
    13 push i32   14 push i8   15 push i16   16 push -1   17-1f push 0..8
    20/21 pushaddr u16/u8      22/23 pushcode (entry index)    24 pushnone
    25/26 pushtext u16/u8      27/28 push, type 3 (unused)
    29-2d ldg u16 (types 1..5)   2e-32 ldg u8      33-37 ldl u16   38-3c ldl u8
    3d stg   3e stl   3f stg.keep   40 stl.keep
    41 jmp   42 jz   43 jnz   (s16)        44 enter   45/46 call u16/u8   47 ret   48 retv
    49/4a native u16/u8 (import index)     4b result (push the native's result)
    4c start   4d stop  (a thread, by the pc it was started at)     4e drop
    4f-53 ldg.ind (types 1..5)   54-58 ldl.ind
    59 end   5a yield   5b sleep   5c send   5d recv
    5e incg  5f incl  60 decg  61 decl
    62 switch: u8 n, s32 default, n x {s32 value, s32 offset}, values sorted

The mnemonics are the kit's (the Episode II kit's where a handler does the
same thing); the executable has no names for opcodes. A native call is: the
arguments in order, then their count, then `native k`.

**Natives.** 22 classes, 327 functions: `runtime` (52), `bat` (60), `robo`
(31), `cam` (26), `objx` (24), `mm` (22), `sound` (16), `cfmap` (14), `enepc`
(12), `talk` (11), `bcam` (11), `id` (10), `extalk`, `effcam`, `filter` (7
each), `fade` (5), `math` (4), `seg` (3), `database` (2), `deb`, `inv`,
`modelviewer` (1 each). The tables are `{char *name, handler, int min_args}`
records; `bat` and `robo` are in OV02.OVL. The names are the game's own
strings (`sbnatives.py` has the list, `natives --table --iso DISC.iso` reads
it from a disc). The `mm` table has no closing zero in the executable, so the
engine registers one junk record after `mm.OpenShop`.

**Every build.** The two tables and the registration call are found by
content, not by address (`sbvm.read_vm_tables`): the 99 lengths are
byte-identical and the 327 natives have the same names and minimum argument
counts on USA Disc 1 and 2, the May 2006 prototype (lengths at `0x4078c8`,
registration `0x1d17e0`) and Japan Disc 1 and 2 (`0x406378`, `0x1d0970`).

**Measured** (`python sbvm.py --self-test` with the disc variables set):

| | USA Disc 1 | Prototype | Japan Disc 1 |
|---|---|---|---|
| scripts disassembled end to end, no unknown byte | 715 / 715 | 715 / 715 | 856 / 856 |
| instructions | 3,225,706 | 3,225,626 | 3,951,242 |
| jumps, switch arms, entries, `main` off an instruction | 0 | 0 | 0 |
| opcodes that occur | 65 of 99 | 65 of 99 | 65 of 99 |
| native calls, argument lists recovered | 550,358, all | 550,348, all | 669,272, all |
| imports not in the native tables | 0 | 0 | 0 |
| pool strings = named by `pushtext` + by a global table | 90,580 = 90,535 + 45 | 90,557 = 90,512 + 45 | 108,040 = 107,975 + 65 |

USA Disc 2 equals Disc 1 and Japan Disc 2 equals Japan Disc 1. The 34
opcodes no script uses: 00 0a 22 27 28 2a 2b 2c 30 31 33-37 39-3c 3f 40 43 45
49 51-58 5f 61.

**Which strings are shown** follows from the code: a string is a line when it
is the text argument of a native that draws text. `deb.put`, the developers'
debug print, takes 227,240 of the 245,984 text arguments on USA Disc 1.
[DIALOGUE.md](DIALOGUE.md) has the natives, the counts and the play-order
export.

**Not known:** what most natives do (only the text-showing ones were read),
the meaning of `talk.EvtMsg`'s numeric arguments, the loader's buffer size
for a grown `.sb`, and the `.t` file beside each scene.

Modules: `sb.py` (text pool), `sbvm.py` (code), `sbnatives.py`, `dialogue.py`.
Editing: [TRANSLATING.md](TRANSLATING.md).

## 8. TXD menu text

`mnu\xx\menutext.txd` is `u32 count, u32 offsets[count]`, then the strings;
`synopsis`, `discchg` and `devchk` have no count (it is the first offset
divided by 4). Offsets are absolute; strings are NUL-terminated and
contiguous. Japan and USA: menutext 909 / 907 strings, synopsis 166, discchg
13, devchk 20. All files rebuild byte-identically. Module: `txd.py`.

## 9. Menu databases

`mnu\xx\DBC.bin`, `DBC2.bin`, `MVtext.bin`, `SegmentFileData.bin`,
`njBtlText.bin`, `njDBcommon.bin`, `njDataText.bin`:

    u32 count, count x {u32 offset, u32 size}, 0x90 padding to 16;
    each blob starts on a 16-byte boundary

A blob is a table of tagged records (`DBF` encyclopedia records of 0xD0 bytes,
`TOP` / `CHA` / `EVE`, `MVD`, `SEG`) or a plain offset table, then a string
area. Every string reference is a blob-relative u32 before the string area;
the kit finds them from the original bytes and re-lays the strings in their
original order. All seven files rebuild byte-identically on USA Disc 1, the
prototype and Japan.

Fourteen values (seven in `DBC2.bin`, seven in `njDataText.bin`, USA Disc 1)
land inside a string. They are numbers, not pointers: in `DBC2.bin` they sit
in `DBF` fields 7 and 8 (ids; the same columns in `DBC.bin` hold the same kind
of id or `FFFFFFFF` and never touch text), in `njDataText.bin` in `CHA` field
2 (a rising count) and `TOP` field 4. A `DBF` record's strings are exactly
fields 3, 5 and 9-14, which Anzinono's
[xenosaga3-translation-kit](https://github.com/Anzinono/xenosaga3-translation-kit)
found independently across all 906 records. A rebuild keeps these numbers
as they are and lets the strings they land in change. Until 2026-11-26 the kit
moved them along with their string (rewriting the ids after any earlier edit)
and refused to change those strings.

Module: `njbin.py`.

## 10. Message.Dat

The HaKox mini-game's messages, with a different layout per build:

    Japan (871 messages)   u16 offsets[871] zero-filled to 0x800, strings from 0x800
    USA (933; prototype 922)
                           u32 offsets zero-filled to 0x1000,
                           three u16 arrays at 0x1000 / 0x1800 / 0x2000,
                           strings from 0x2800

The three USA arrays hold per-message values whose meaning is not known (they
are set on hints, descriptions and option lines); they are carried with each
message and written back unchanged. Module: `msgdat.py`.

## 11. batdat.bin

`bat\xx\batdat.bin` (USA 125,764 bytes; Japan 127,836; prototype 123,724):

    u32 count (28)   u32 file size   u32 offset[28]

A table that holds text is fixed-size records followed by a string area, with
table-relative u16 or u32 string fields. The record size and the string
fields of each table are derived from the table's own bytes, and come out the
same on USA, the prototype and Japan although every string area differs. The
file is loaded through the resource-type table, so the executable holds no
reference to its name. Module: `batdat.py` (the docstring lists every table).

## 12. Subtitles and whole-file text

`mov\xx\*.txt`, `mov\xx\bat\*.txt` and `evt\xx\*.txt` are plain text:

    ; comment
    mm:ss:ff<TAB>text      a cue (or a frame count; a leading + is relative)
    \n                     a line break inside a cue
    [漢字/かんじ]          ruby
    end

The cue at time 0 carries the style line
(`$ay375;$xx0,24;$rubyy-4;$col707070;`). A first line `mono` selects a branch
that only the USA loader has. The pse director scripts (`mnu\pse\*.txt`) are
Shift-JIS and identical on both builds; `mnu\pse\xx\*.mes` are message files.
The whole file is the unit: comments, empty cues and each file's own line
ends are kept byte for byte.

Module: `subtitle.py`. The codecs (the USA build's whitelist of two-byte
pairs with Latin-1 for every other high byte; Japan's "any byte from 0xA0
starts a pair") are in `textcodec.py` and [TRANSLATING.md](TRANSLATING.md).

## 13. Fonts

`mnu\xx\font0.bin` and `font1.bin`, 494,592 bytes each:

    0x00000  1,024 cells x 480 bytes: 20 x 24 pixels, 8-bit, row-major, linear.
             Each byte packs four 2-bit planes, so the file holds 4,096 glyphs.
    0x78000  512 (left, right) metric pairs
    0x78400  0x800 bytes: a 1-bit 512 x 32 system font (8 x 8 glyphs)

No header and no swizzle, unlike Episode I and II. Which bytes of text select
which cell, and which cells are proportional, differ per build and are read
from each executable. [FONT.md](FONT.md) has the addressing, the proofs and
the `glyphs-*` commands. Modules: `font.py`, `glyphs.py`.

The battle and menu HUD's small letters are not in these files: they are
16-pixel cells in the window sheets `mnu\xx\window0/1/2.xtx`, chosen by a
byte-to-cell function and a width table in the executable. Module:
`statfont.py`.

## 14. ADX streams

CRI ADX, big-endian header:

    0x00  u16 0x8000        0x02  u16 offset of the audio minus 4
    0x04  u8 encoding (3)   0x05  u8 block size (18)   0x06  u8 bits (4)   0x07  u8 channels
    0x08  u32 sample rate   0x0C  u32 samples per channel
    0x12  u8 version (3 or 4)
    loop block at 0x14 (version 3) or 0x20 (version 4):
      +0x04 u32 loop flag   +0x08 u32 loop start sample   +0x10 u32 loop end sample

The kit reads the header and leaves decoding to ffmpeg. The loop fields were
checked on the 120 soundtrack streams of all five images: every looped
stream has start < end <= samples, and the start byte stored beside the start
sample agrees with it (18-byte blocks of 32 samples per channel).
[MUSIC.md](MUSIC.md) says which streams are what. Module: `adx.py`.

## 15. DTPK sound banks

`.dap` (607 per disc): a 0x40-byte preamble, then a chain of segments:

    +0x00  "ps2_DTPK"   +0x08 u32 version (0x4C02)   +0x0C u32 segment size
    +0x60  "ps2_TBLD"   driver tables: programs, tones, sequences
    +0xB8  u32 sample-table pointer (0 = the segment has no samples)

    sample table: u32 count - 1, then 16-byte records
                  {u32 offset, u32 pad, u16 flags, u16 rate, u32 length}

Samples are PS2 SPU ADPCM in the segment's `ps2_VAGD` chunk; flag bit 2 marks
a looped cue. The kit writes one WAV per sample. The driver tables (how the
samples are sequenced into cues) are not decoded. Module: `dap_decode.py`.

## 16. Sofdec movies

`.sfd`: a sector-aligned MPEG-1 program stream, one 2,048-byte pack per
sector. Video is stream 0xE0 (MPEG-1, 512 x 320), audio is ADX in stream
0xC0, padding 0xBE. `fmv_sfd.demux` records the byte span of every video
payload; `splice` puts a new video stream of the same length into those
spans and leaves every other byte alone (`splice(data, demux(data)[0]) ==
data`). Growing a movie needs a repacketizing muxer; see
[FMV-HD-SCHEME.md](FMV-HD-SCHEME.md). Module: `fmv_sfd.py`.

## 17. Not decoded

File counts are USA Disc 1's.

| What | Where | Known so far |
|---|---|---|
| event packages | 43 `.xep`, 42 `.xev` | `Xc\x01\x03` header, not an MR package, not LZSS-B |
| effect parameters | `.esd`, `.esp` | only their embedded `txy` textures are read |
| DTPK driver tables | `.dap` | only the samples are read |
| `.shp`, `.t`, `.chp` | 25, 647, 1 | `.t` files are copied as text by `browse`; the others are untouched |
| UI palette bindings | about 22% of `window0/1/2.xtx` | no draw call found that reaches them |
