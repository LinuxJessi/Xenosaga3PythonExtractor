# Finds, leftovers, and what the discs say about how they were made

Things left on the Episode III discs that a player never sees. The first
part is the "Fun finds" list that used to close [disc-catalog.md](disc-catalog.md),
unchanged; the second part is what turned up later, when the kit learned to
read the Japanese discs and the May 2006 prototype. Each later item says how
it was checked. Dates, builds and people are in [HISTORY.md](HISTORY.md).

Paths are in-game paths; "the executable" is `SLUS_213.89` unless a line
says otherwise.

## Both disc executables are byte-identical

```
md5 SLUS_213.89 (disc1) == md5 SLUS_214.17 (disc2) == 0ef759d006731b465da05f475f24c233
```

Only the filename differs — the PS2 firmware uses the title ID to recognise
which disc is in the tray. Disc-switching logic is entirely data-driven; the
same 4.5 MB MIPS ELF runs both halves of the game.

## "KOS-MOS" is a literal C++ field

A string in the binary reads:

```c++
pKosmos->rsrc[XAct_Rsrc_XAP_Ext2]
```

So the main character isn't just an art asset — she has a dedicated pointer
in the engine's actor table. (Mildly funny because Jessi's parent workspace
directory is also named `KOS-MOS/`.)

## The engine is called "PsII"

Eight modules with the `PsII` prefix link into SLUS:
`PsIIlibcdvd · PsIIlibdma · PsIIlibgraph3000 · PsIIlibipu · PsIIlibkernl3000 ·
PsIIlibmc · PsIIlibpkt · PsIIlibsdr`. The `3000` suffix is the
PlayStation 2 SDK Series 3000 build; the rest are MonolithSoft wrappers.

## MatuzawaTest — a programmer's debug toggle

The string `?MatuzawaTest: NODEBUG` is preserved verbatim, along with
`CF Debug Flags` and `DEBUGPAUSE:`. Matsuzawa (松澤) was one of the
engineers on the team — they left a personal feature-flag in the shipped
build. (PS2-era games shipped with debug stubs all the time; it just wasn't
common to keep a name attached.)

## Test source filenames survived stripping

The shipped binary still names test sources that were never supposed to be
in a release build:

```
BlendTest.euc.c       CFLLightTest.euc.c    CullingTest.euc.c
ScisTest.euc.c        XstAnimTest.euc.c
```

The `.euc.c` extension is the MonolithSoft convention for **EUC-JP-encoded
C source** (so the comments can be in Japanese without needing UTF-8). The
test harness clearly lived in the same build target as the shipped game.

## CRI middleware was frozen 10 months before release

Build-date strings inside SLUS:

```
ADXRT  Ver.3020 Build:Sep 20 2005   ← CRI ADX audio runtime
SJ/PS2EE Ver.6.34 Build:Sep 20 2005 ← CRI Sofdec movie player
PL2ENC Ver.1.02 Build:Sep 20 2005   ← CRI's encoder helper
```

All three middleware libraries were built on the same Tuesday morning in
September 2005. The disc was mastered ten months later (`2006-07-12`).

## Languages that never shipped

The locale-code table reads `jpjpusendefriteszhko` — JP / JP / US / EN /
DE / FR / IT / ES / ZH / KO. The US disc only ships the `us/` subtrees
under `evt/`, `mov/`, `jpg/`, `mnu/`, `bat/`, `cf/`, `ef/`, but the engine
clearly had localization machinery for ten languages, including Korean and
Simplified Chinese. (No Korean or Chinese release of Xenosaga III actually
happened.)

## Subtitles ship as separate text files

Every `mov/*.sfd` cutscene has a `evt/us/{stem}.txt` companion with the
dialogue in tab-separated form — character timing on the left,
speaker-tagged line on the right. The first row sets visual style with
control codes like `$ay375;$xx0,24;$rubyy-4;$col707070;` — vertical
position, baseline-style, ruby (furigana) annotation, and color. So the
game's subtitle renderer supported ruby characters natively even though
the US release doesn't use any.

## The XAct resource enum

The pre-stripped enum names are still visible:

```
XAct_Rsrc_MDL    XAct_Rsrc_TEX    XAct_Rsrc_XAP    XAct_Rsrc_XAP_Ext2
XAct_Rsrc_XHR    XAct_Rsrc_XST
```

"XAct" is the engine's actor/asset system. `XAP_Ext2` exists as a slot for
secondary animation packs — implying actors can have layered animation
banks (probably for combos or scripted overrides).

## `credit.bin` is actually the boot logos

Turns out `mnu/credit.bin` isn't credits at all — and it's not obfuscated.
It's a tiny container holding **four concatenated JPEG images**: the
publisher (Bandai Namco Games) and developer (MonolithSoft) splash
screens that play at boot, plus two more. Each was extracted to
`browse/images/mnu/credit/credit_NN.jpg`. The "obfuscation" was just the
absence of ASCII strings because the payload is JPEG-compressed.

## Resource arithmetic in plain text

The binary contains live debug formatters:

```
%.2f/%.2f/%.2f/%.2f
ALL %2.2f / %2.2fMB
MAT %2.2f / %2.2fMB
XEP %2.2f / %2.2fMB
```

So the engine had a built-in memory-budget HUD broken down by resource
type (`ALL`, `MAT` = materials, `XEP` = event package, etc.). Probably
behind one of those Matuzawa debug flags.

## Dual-purpose mg1 minigame

The `mg1/` folder is treated as a separate game inside the game — it has
its own `Stage_NNNN.BMP` board art, its own `Message.Dat` text table, and
its own `Picture.xtx`. The format conventions don't match the rest of the
engine (BMPs instead of XTX), suggesting a different team built it.

---

# Found later

## Cheat codes in the mini-game overlay

`OV04.OVL` (the HaKox block-puzzle mini-game) answers pad sequences with
these messages, on every image: `FREE ALL STAGE!`, `NOW SOUND TEST!`,
`SECRET STAGE!`, `EDIT LIMITED/UNLIMITED!`, `STAGE RAPIDLOAD!` /
`STAGE ONMEMORY!` and `MASTER CODE ON!`, with `RETAIL MODE!` and
`DEBUG MODE!` beside them. The same overlay holds a Japanese stage-editor
debug display. The USA build adds `NORMAL MODE!` / `PHOTO MODE!`, which the
Japanese disc and the prototype lack.

*Checked 2026-11-21: the strings are in OV04 on USA Disc 1 and 2, Japan Disc
1 and the prototype. The pad sequences themselves were read from the overlay
on 2026-11-05 and have not been tried in the running game.*

## `x3` and `x3u`

The mini-game overlay still names the developers' own machine, and the path
differs by build: `host0:/home/xeno/vcd-f/x3/mg1/com/Stage/Stage_0000.BMP` on
the Japanese disc and the prototype, `.../vcd-f/x3u/...` on the USA discs. So
`x3` was the game's build tree and `x3u` the USA one, the same naming Episode
II used (`x2`, `x2u`). The prototype, a USA-language build, was still made
from `x3`.

*Checked 2026-11-21 on the four images.*

## Test files that shipped

`mnu\pse\test.jpg` and the map `mdl\map\cf\O_TST.map` are in the index of
every image; `mnu\pse\us\test.mes` is on the USA discs and the prototype.

*Checked 2026-11-21 through each disc's own index.*

## The table of contents still says "Episode.2"

The three index files pad themselves with the text
`MONOLITHSOFT Xenosaga Episode.2`. Episode III's indexes are Episode II's
format, written by the same tool, and nobody changed the filler.

*`toc_bin.py` rebuilds the indexes byte-identically, filler included.*

## Notes in three encodings

The scene scripts carry their writers' notes beside the dialogue. On the USA
discs most are Shift-JIS and some EUC-JP, in files whose displayed text uses
neither; on the Japanese discs everything is EUC-JP. Sixteen Japanese
placeholder lines shaped like real dialogue are still in the USA Disc 1
scripts.

*`sb.py` reads each string in the encoding that is exact for it and
`text-export` labels them `note` and `untranslated`.*

## The notes are debug prints, and they are still called

Those notes are not dead data. Each one is the argument of a call to
`deb.put`, the developers' debug print, which the retail scripts still make:
227,240 of the 245,984 strings the USA Disc 1 scripts hand to the engine go
to `deb.put`, among them every `--- main ---` and `--- Battle Start ---`. The
function is still registered in the retail executable, one of 327 the scripts
can call.

*`natives` counts the calls; `dialogue` leaves those strings out
([DIALOGUE.md](DIALOGUE.md)).*

## One voice file per line

Episode II cuts a scene's lines out of one long voice track by frame numbers.
Episode III gives each event line a file of its own: the script passes the
clip's name beside the text (`s000200_01vir`), and
`snd\adx\mev\` holds a stream by that name for all 4,738 voiced event lines of
the USA discs.

*`dialogue --voice` writes them as WAV, named by scene, order and speaker.*

## A table the engine reads past

The engine registers its script functions from tables that end with a zero.
The table of the `mm` class (party and menu functions) has no zero after its
22nd entry, `mm.OpenShop`, so the registration loop takes the next twelve
bytes of the executable as a 23rd function whose name pointer is `0x10204`.
No script asks for it. The same is true of the May 2006 prototype and the
Japanese build.

*`sbvm.read_vm_tables` reports the table as unterminated on all five images.*

## Scenes only the Japanese discs have

140 scene scripts under `cf\jp\` (2,287 lines of dialogue) and one battle
script have no counterpart on the USA discs. Whether the Japanese game ever
loads them is not known.

*Counted against the USA Disc 1 and 2 indexes; `browse` lists them in
`text/JP-ONLY.txt`.*

## Two menu strings the USA release dropped

`menutext.txd` has 909 strings on the Japanese discs and in the prototype,
907 on USA retail. Entries 0 to 906 are the same slots everywhere; 907 and
908 exist only in the first two.

## Kana grids in the English mini-game

The USA `Message.Dat` still holds the Japanese name-entry kana grids
(messages 587 and 589).

## What the May 2006 prototype has that retail does not

From the comparison made on 2026-11-05 (reports beside the prototype image);
the items marked *viewed* were looked at, the rest were measured:

* **A red "FOR PRESS ONLY" title** (`mnu\us\title1.png`, *viewed*).
* **Five announcement voice lines that were cut**
  (`snd\adx\mev\s020700g06ann_1..3`, `s020700g07ann_1..2`, 3.6 to 6.2
  seconds each), and one Shion line (`s050200_02_2shi.adx`) that is 18,148
  bytes in the prototype and **zero bytes** in retail: the retail index
  still lists the file, empty.
* **Blood in a synopsis picture** (`mnu\pse\EP1\001_000020_02.jpg`,
  *viewed*): a pool of blood under a fallen soldier, painted out in retail.
* **An alternate shot** in the movie `s072900.sfd`: frames 565 to 654 show a
  close-up of young Shion looking over the bed where retail shows another
  shot. Both movies have 5,152 frames.
* **Event audio at twice the sample rate**: 41 event tracks at 48 kHz where
  retail has 40 of them at 24 kHz.
* **Japanese where English would be**: some scene scripts still untranslated,
  and the mini-game's prize table in Japanese only.

The code barely differs: 8,599 of 8,626 functions of the main executable are
the same after relocation. There are no debug features that retail lacks and
no symbols.

## Artists' folders in the effect files

About 2,860 strings in the effect libraries (`ef\esd\*.esd` and others)
name the source picture of each particle emitter, for example
`x:\particle\sozai\watanabe\ashiato.clt`. The folders under `sozai\`
("materials") are people's: `watanabe`, `ikuko`, `sano`, `hasegawa`, `fujii`,
`tayzou`, `asakura`; and `ep2`, the largest, holds effects carried over from
Episode II (some strings still say `g:\xeno2\effects_data\`).

*Counted 2026-11-05 on the prototype and USA Disc 1, the same on both; not
recounted for this page. The names are as the folders spell them and
identify nobody beyond that.*
