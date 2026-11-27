# The translation editor

*The command-line way (export a text tree, edit the files, import) is in
[TRANSLATING.md](TRANSLATING.md). This page is the editor's reference.*

One page in the app that lists every string of Xenosaga Episode III a
translator might want to change, sorted by what it is: voiced scene dialogue,
field boxes, what townspeople say, choices, system and battle messages, movie
and event subtitles, the Episode I and II recap, menus and the synopsis, the
database and menu tables, battle names and descriptions, and the HaKox
mini-game. Scene-script strings are sorted by what the script's **code** does
with them, so the developers' debug prints are not in the way. You type or paste
translations, the page checks each one as you go, and **Build** writes
patched copies of **both discs**. The retail images are only ever read.

It is the Episode I kit's editor (same page, same project file, same
backups, same language list), with Episode III's own readers and writers
under it: the kit's text pipeline (`textpack`, `textcodec`, `langpack`,
`patch`). What is the same and what differs is listed under
[Modules](#modules).

> **What has been seen in the game.** Builds from the editor were booted in
> PCSX2 on USA Disc 1 with Hindi, Traditional Chinese, Cherokee and Arabic
> (2026-11-21: a location caption over the real-time opening and the first
> dialogue box; the Chinese build again on 2026-11-27 after the glyph-size
> fix). On 2026-11-27, French on the Settings menu (heading, rows, values,
> help lines, button hints) and Spanish in the opening caption and the first
> scene's dialogue (¿, á, é, í, ú) followed. Everything else below comes from the kit's own tests on the real discs
> (USA Disc 1 + 2 and Japan Disc 1 + 2): rows read, builds written to clones,
> the clones read back. Not booted yet: battle text, Disc 2 and the Japanese
> discs. The page was walked
> through in Chrome on 2026-11-26/27. See [What was tested](#what-was-tested).
> Pictures: [LANGKIT.md](LANGKIT.md).

## Starting it

* **The editor's own download:** `Xenosaga3-Translation-Editor-<version>-win64.zip`
  on the releases page (or `Xenosaga-III-Translation-Editor.app` on macOS,
  made with `python build.py --editor`). Unzip it and double-click
  `Xenosaga-III-Translation-Editor`: the editor opens in your browser, with
  nothing else installed and no extractor cards (the extractor kit is a
  separate download). It carries everything a Build needs: the kit's text
  pipeline, the CLI it builds with, DejaVu Sans, HarfBuzz.
* **From a source checkout:** double-click `translate.bat` (Windows),
  `translate.command` (macOS) or `translate.sh` (Linux), or run
  `python gui.py --editor`. In the extractor's app bundle it is the second
  executable, `Xenosaga-III-Translation-Editor`.
* **From the extractor app:** click **Translation editor** in the header.
  The page opens in a new tab at `/editor`.
* **Headless:** `python gui.py --no-browser`, then open
  `http://127.0.0.1:21389/editor`. The GUI takes port 21389 (after
  SLUS-21389) whenever it is free, because the browser keeps what the page
  remembers (disc, project, switches) per address: a new port on every
  launch would look like a first start each time. `PORT=N` or `--port N`
  pins another one.
* **Terminal only:**
  `python cli.py tx-catalog --iso DISC1.iso --out catalog.json` writes the
  same list of strings as JSON;
  `python cli.py tx-build --project P.json --retail DISC1.iso --out OUT/`
  is what the Build button runs.

The first time a disc set is opened the editor reads every text object of
both discs and the code of every scene script (about half a minute; a minute
for the Japanese discs). After that the list comes from a cache (two
seconds); see [The cache](#the-cache) for where it is and how to clear it.

## Two discs, one project

Episode III is two discs. Almost all of its text is in the X3.00 family
(chain 0), which is the same bytes on both discs; each disc then has its own
movie subtitles (chain 1 on Disc 1, chain 2 on Disc 2).

You give the editor **one** image, either disc. It finds the other one by
itself (`txdiscs.py`): an image of the same build with the other disc number
in the same folder, in a folder next to it (`Game (Disc 1)/`, `Game (Disc
2)/`), or one level below either. The catalog then covers both discs, and a
build writes both: chain-0 files go to both discs at the same place, each
disc's subtitles to that disc.

* If the other disc is not found, the first note of the catalog says so. The
  project then covers that one disc: the other disc's movie subtitles are not
  listed, and a build writes one image. A project started that way has a
  different retail id from one started with both discs.
* On the command line, `--disc2 PATH` names the other disc when it is
  somewhere else. The `XS3_TX_DISC2` environment variable does the same for
  the app.
* Supported bases: the USA discs (SLUS_213.89 / SLUS_214.17), the Japanese
  discs (SLPS_256.40 / SLPS_256.41) and the May 2006 prototype (one disc).

## The workflow

The page shows four numbered steps across the top; the one to do next is lit.

1. **Disc.** *Choose disc…* and pick an untouched image, Disc 1 or Disc 2.
   The picker lists the Episode III images it finds nearby, the untouched
   ones first (marked ✓). Not a patched copy: every build starts again from
   retail, and the row ids are retail paths and keys.
2. **Language setup & project.** **New** opens the Language setup: search
   the 382 languages or choose *My language isn't listed* and paste a
   sample sentence. Each language says what it needs **on the disc you
   opened**:
   * *ready*: the disc's fonts already draw every letter. On the USA discs
     that is Spanish, Italian, Portuguese, Dutch, Swedish, Indonesian and
     about a hundred more (Latin-1). On the Japanese discs it is Japanese,
     and Russian (the font's JIS Cyrillic row).
   * *ready · a few letters added*: the disc lacks a few letters of this
     language and the build adds them by itself. French on the USA discs is
     here (Latin-1 has no `œ Œ Ÿ`); so are German („ “), Polish, Czech,
     Turkish, and every Latin language with accents on the Japanese discs:
     123 languages on the USA discs. The letters come from DejaVu Sans, which
     ships with the kit (`fonts/`), so the result is the same on every
     machine. Nothing to choose; the Language setup lists other fonts in case
     you want another look. See [The font for a few missing letters](#the-font-for-a-few-missing-letters).
   * *a few letters from a font*: the same case when the kit's font does not
     have one of the letters; you pick a font.
   * *new script · font*: Russian, Greek, Arabic, Hebrew, Hindi, Korean,
     Chinese, Japanese on the USA discs… Every letter is drawn from the
     font, so which font is your choice.
   When you choose a font, the installed fonts that draw every letter are
   listed and the best one is picked; *Try it* draws a sentence with the
   game's font as it will look after Build (about 2 seconds the first time
   for a new set of letters, 10 on the Japanese discs). *Next* asks where
   the project file goes. The project is a small JSON file holding only what
   you typed:
   `{"format": 1, "language": "es", "retail_id": "...", "translations": {id: {"text", "state"}}}`.
   It saves itself 1.5 s after each edit. One project, one language.
3. **Translate.** Three columns: where in the game (by type, by speaker, or
   by file), the original lines of the selected group, and the translation
   box for the highlighted line with its checks and a picture of the line in
   the game's font.
4. **Build.** Give an output **folder**; both patched images are written into
   it under their original names. **Check project** (next to Build) runs the
   build's own checks over the whole project without writing anything, and
   Build runs it first by itself. See [Build](#build).

Saving, backups (`<project> backups/`, automatic copies, checkpoints,
restore), the spreadsheet (TSV) export and import, *Copy group for
translation* / *Paste translations*, translation memory, search and filters
work as in the Episode I editor; its
[reference](https://github.com/LinuxJessi/Xenosaga1PythonExtractor/blob/main/docs/TRANSLATION-EDITOR.md)
describes them. What changed here (2026-11-26):

* **Saving** belongs to the project it started for: a reply that comes back
  after you opened another project does not touch that one, and Open, New,
  Restore, Export and Build wait for the save in flight and stop when it
  failed (your edits stay; *Backups → Save a copy* keeps them elsewhere). The
  server no longer replaces a project file from a save that names no
  version, recreates one that was deleted or moved since it was opened, or
  restores a backup over a file another tab changed; a failed automatic
  backup is said, not hidden. A save that failed on a disk or connection
  fault tries again by itself; a project file deleted or moved while open
  offers *Save it again here*; a project made while only one disc was found
  offers *Use both discs* once the other one is next to it.
* **TSV import** checks first: *Check* says how many lines are new, how many
  would replace a translation and what is skipped; *Import* applies exactly
  that, after a checkpoint ("before TSV import") when lines are replaced.
  A line whose text is already the same is left alone (its state too).
  Export refuses a project made for another disc set.
* **New → Next → Back → Cancel** puts the open project's language back.

## What is listed

Counts are for the USA Disc 1 + 2 set: 104,003 rows from 919 text objects,
20,913 offered, 544 locked and 82,547 hidden by default. (Japan Disc 1 + 2:
120,645 rows from 1,058 objects, 23,511 offered.)

| section (By type) | category | offered, USA | offered, Japan | what it is |
|---|---|---|---|---|
| Story | Dialogue — event lines (voiced) | 4,747 | 5,116 | `talk.EvtMsg`: a line of a real-time scene, with its voice clip |
| Story | Dialogue — field boxes | 2,169 | 2,808 | `talk.Msg`: the text boxes of the field |
| Story | Dialogue — townspeople | 2,138 | 4,127 | `extalk.Msg`: what a person says when spoken to |
| Story | Choices | 693 | 873 | `talk.Sel`: the options, one per line |
| Story | Narration boxes | 27 | 45 | `talk.Think` |
| Story | System messages | 9 | 17 | `talk.Sys` ("You obtained...") |
| Story | Battle messages | 156 | 156 | `bat.msgOpen`, `robo.msgOpen` |
| Story | Battle banners | 31 | 31 | `robo.dispSkillName` |
| Story | Scene text picked from a table | 45 | 62 | strings a script reads by number at run time |
| Story | Movie subtitles | 1,427 | 1,048 | `mov\us\*.txt`, one row per cue |
| Story | Event subtitles | 1,324 | 1,011 | `evt\us\*.txt` |
| Story | Battle voice subtitles | 139 | 139 | `mov\us\bat\*.txt` |
| Story | Story recap messages | 69 | 106 | `mnu\pse\us\EP1.mes`, `EP2.mes`, one row per `#MESSAGE` |
| Menus & system | Menu text | 699 | 721 | `mnu\us\menutext.txd`, `synopsis.txd`, `devchk.txd`, `discchg.txd` |
| Database, items & battle | Database & menu tables | 3,826 | 3,786 | `mnu\us\DBC.bin`, `DBC2.bin`, `MVtext.bin`, `SegmentFileData.bin`, `njBtlText.bin`, `njDBcommon.bin`, `njDataText.bin` |
| Database, items & battle | Battle names & descriptions | 2,484 | 2,595 | `bat\us\batdat.bin` (20 tables) |
| Mini-game | HaKox mini-game | 930 | 870 | `mg1\us\Message.Dat` |

### Scene scripts: sorted by what the code does

A script's strings all sit in one pool: lines, choices, voice ids, labels and
the developers' debug prints side by side, and on the Japanese discs nothing
in the bytes tells a note from a line. The editor therefore reads the
script's code (`sbvm.py`, `dialogue.string_kinds`; every argument list of
every native call is recovered, [DIALOGUE.md](DIALOGUE.md)): a string is
offered when a native that draws text receives it, or when the script reads
it through a table of string numbers.

| | before (by the look of the string) | now (by the code) |
|---|---|---|
| USA, script rows offered | 12,012 | 10,015, plus 534 keywords that follow their line |
| USA, debug prints among them | 3,797 | 0 (73,601 debug prints, all hidden) |
| Japan, script rows offered | 96,149 | 13,235, plus 1,054 keywords |
| Japan, "Scene text without a speaker" | 85,372 rows, mostly notes | gone: 86,561 debug prints hidden, the drawn rest in its own categories |

`text-export` says the same on each `### KEY` line of a script file
(`### 0012 dialogue use:debug`); the import reads the key alone, as before.
All 715 USA and 856 Japanese scripts are read this way. A script whose code
could not be read would fall back to the old rule and be named in the notes
above the list; none does.

Hidden by default (the *Show hidden lines* switch, Advanced):

* 73,601 debug prints (USA; 86,561 on Japan): strings the scripts only ever
  hand to `deb.put`. They can still be edited; they only have to fit their
  encoding, and no font check applies since nothing draws them.
* 6,401 script identifiers (labels, voice ids, file names: strings handed to
  other natives). Changing one prints a warning at build.
* 25 strings no code uses.
* empty strings, strings with no letters, the style line that opens each
  subtitle file, the recap movies' director scripts (`mnu\pse\*.txt`), and
  four `.mes` files left in Japanese on the USA discs.

Locked:

* **534 keywords** (1,054 on Japan). A townsperson can wait for a keyword
  (`extalk.KeyWait`); the keyword's bytes are the body of a `<kWORD>` tag in
  a line of the same script (569 tag occurrences on USA; every keyword has
  at least one). You translate the word **inside the tag** of the line, and
  the build writes the keyword from it. So the two cannot drift apart:
  * a line whose number of `<k…>` tags changed is refused;
  * a keyword that two or three lines hold (33 of the 534) must be written
    the same in each; while you type the first, the editor warns and names
    the others, and the build refuses until they agree;
  * the keyword's own row shows which line it follows and cannot be typed
    into (an imported spreadsheet may carry it, if it says what the tag says).
  After every build the copies are read again and each keyword's bytes are
  compared with its tags, for new-letter languages too.

**Japanese left on the USA discs.** 16 placeholder lines in the USA scripts
are still Japanese. They are shown in Japanese, and a translation typed for
one is written in the USA build's own encoding, since that is how the game
would read it.

**On the Japanese discs** the scripts' notes are EUC-JP like everything
else; they are told apart by the code as above, not by their bytes.

### Row ids

`<family>:<in-game path with />#<key>`, for example `sb:cf/us/1210.sb#0003`.
The key is the container's own string key, the same one `text-export` writes
after `###`. For a whole text file it is `L<line>` (a subtitle cue),
`M<n>` (a recap message) or `S<line>` (a director-script line). Families:
`sb` (scene scripts), `mnu` (.txd and the mnu .bin tables), `bat`
(batdat.bin, Message.Dat), `sub` (subtitles and pse files).

### How text is shown

The same form as the text-export tree, with one change: the game's line
break, which is the two characters `\n` in the data, is a real line break in
the box.

* `[Speaker]` at the start of a dialogue line is the name box. Translate the
  name, keep the brackets.
* `<f>` ends a page, `<w30>` waits, `<l2>` gives the number of lines.
  `<kWORD>` marks a keyword: translate the word, keep the tag (see *Locked*
  above). **`<lN>` is kept right for you:** when the original's
  `<lN>` matched its line count, the build writes the translation's line
  count.
* `$col707070;` and the other `$…;` commands, `\31` `\b` codes in the menu
  text and `%d` `%s` placeholders pass through as typed.
* `⟦XX⟧` is one raw byte.

### The checks

* **Errors (the build refuses the line):** a letter the encoding cannot write
  or the disc's fonts cannot draw (for a *ready* language; the font check
  reads the code-to-cell rules from the disc's executable and the ink of its
  `font0.bin` / `font1.bin`, as `text-import` does); a control byte
  (`⟦0D⟧`…) missing or added; a subtitle that breaks the cue grammar; a
  locked string; a broken keyword link; a choice with another number of
  options; a page past a proven byte limit. Letters the original line
  already held are not checked. The build refuses the same things, on both
  of its paths (a dropped control byte used to pass a build).
* **Warnings:** tags, `$` commands, backslash codes or `%` placeholders that
  differ from the original; a dialogue line that lost its `[Speaker]`; a
  missing `<lN>`; a line wider than its box (below).
* **Each check is for the disc of its own request.** The page sends the disc
  with every request and the server answers in a scope of that disc
  (`txcodec.disc`, a context variable: per thread). Two tabs on different
  builds do not affect each other, and a request that names no disc while two
  sets are open is refused, not answered from the other tab's disc.

### Limits: what is traced to the game's code

The numbers below are read from the USA executable (SLUS_213.89); the same
14 functions are in the May 2006 prototype and the Japanese executables with
the same instructions (only call targets and data addresses differ; the one
constant that differs is a vertical offset of the choice window, 20.0 against
5.0). Anything not in this table is **unknown**, and the editor says so.

| what | value | from |
|---|---|---|
| a message window's width | its widest line + 43 px | `FUN_00268938` measures each line (lines end only at the two characters `\n`, `FUN_00272fd8`) with the printer's own width function (`FUN_00268a28` → `FUN_00272680` → `FUN_001828a0`). `FUN_0026a878`: width = widest + 2 × 16 (the pad byte at window +0xA8), + 11 when flag 0x100 is set; `FUN_0026cc68` sets 0x108 for `talk.Msg`, `Think`, `Sys` and `EvtMsg` |
| wrapping by the game | none | the page is drawn as copied (`FUN_0026ae60` → `FUN_001826e0`); the window grows instead |
| the screen | 512 × 448 | `FUN_0026a370` skips a window outside 0…512 × 0…448; `FUN_0026e0f0` centres a window on x = 256 |
| **width guide**, event lines, field boxes, narration, system messages | **469 px** | 512 − 43: the widest line whose window is no wider than the screen |
| **width guide**, choices | **480 px** | `FUN_0026d0e8` → `FUN_0026ea28`: widest option + 32, centred on 256 |
| **width guide**, townspeople | **426 px** as the editor measures | `FUN_0026c788` sets flags 1 and 4, not 0x100: widest + 32. `FUN_00272680` gives a flag-1 window a prefix with zoom 18 where the others have 16, so the line may be 480 px at zoom 18, which is 480 × 16 / 18 = 426 at the zoom-16 width the editor shows |
| a window's height | lines × 27 + 12 (16, and + 25 for the name, in a balloon); 3 lines when a field box has no `<lN>` | `FUN_0026a878` |
| a `<kWORD>` keyword in a line | the word's width + 19 px | `FUN_002730d0` measures the word and leaves a gap of that width + 0x13 for it; the editor's width and picture of a line count the word the same way |
| **byte limit** of a script string that is drawn | **16,000 bytes** | `FUN_0026ae60` and `FUN_0026ade0` copy the page (window +0x50 to +0x54) with `FUN_00272680` to 0x70000000, the PS2's 16,384-byte scratchpad, behind a 59-byte style prefix, with no length check. The longest retail string is 1,045 bytes |
| battle messages and banners | unknown | the `bat` and `robo` natives are in OV02.OVL, not read |
| scene text picked from a table | unknown | which native gets the string is decided at run time |
| menus, database, battle names, HaKox, subtitles, recap | unknown | their window code is not traced |
| reading a file | no cap of its own | `FUN_00188618(path, buffer, flags, callback, offset, size)` reads the size the disc's index gives, rounded up to 2,048, into the buffer its caller passes, and checks nothing |
| `synopsis.txd` | at most 1,046,528 bytes | `FUN_001b50d8(0x1F00000)` reads it to 0x1F00000 and puts a table at +0xFFF00; the read is in whole 2,048-byte sectors, so the file may be 0xFF800 bytes (retail: 46,700) |
| every other text file's buffer | unknown | the callers were not traced: `discchg.txd` (`FUN_001b45b8`) gets a buffer from its caller; scripts, `menutext.txd`, the `mnu` tables, `batdat.bin`, `Message.Dat` and the subtitle files were not followed |

How the retail text sits against the guides (measured with the game's width
function on every drawn script string): on the USA discs 11 of 9,783 guided
strings are wider (one field box by 2 px, three narration boxes, seven
townspeople lines); on the Japanese discs 3 of 12,986.

What the editor does with them:

* a line wider than its guide is a **warning** with the pixels, never a
  refusal: the text is still drawn, part of the window is off the screen;
* ***Wrap to fit*** breaks such a line at spaces to the guide (a `<k two
  words>` tag is never split), and `<lN>` then follows the new line count.
  It works for a language that adds a few letters to the game font (French,
  German on the USA discs): those letters are measured as "m". A language
  in a new script has no widths to wrap with;
  **Not for a choice:** each line of a choice is one option the script acts
  on by its number, so a long option only warns, and a choice with another
  number of lines than the original is refused;
* a drawn script string over 16,000 bytes is **refused**, by the editor and by
  both build paths (checked on the bytes as written);
* rows of the families with no traced number show their width and their
  length against the original, and the older statistical warning (longer than
  the longest original text of the category); there is nothing to wrap to
  and the page says "no known width";
* growth of a file is refused only where a limit is proven (`synopsis.txd`,
  and the container rules that were always there: 64 KB tables, 1,024-byte
  battle captions on Japan). Every other grown file is allowed and listed.

## Build

**Check project** sends the saved project to `POST /tx/preflight`
(`txbuild.preflight`): the disc set, the target, ids this set does not
have, locked strings, keywords that follow their line's `<k…>` tag and,
for a language the game font draws, every family's rules with the touched
objects rebuilt in memory. Nothing is written. Each refused line joins the
*errors* filter and is a link in the list it shows. For a language with new
letters, fitting them into the font is left to the build. Build runs the
same check first and stops on a refusal, when the check could not run, or
when another project was opened meanwhile. Each check replaces the errors
the previous one added. The first check after opening the discs reads them
(about 25 s); later ones are quick.

**Build** runs `cli.py tx-build`. It:

1. finds the disc set and checks the project was made for it;
2. checks every translation again; any error stops the build before a byte
   is written, with the row ids (they are links in the log). The rules about
   the edits themselves (known ids, locked strings, keyword links) are the
   same for both kinds of build below;
3. for a *ready* language, rebuilds each changed object with the same
   functions `text-import` uses;
4. for a language that needs new letters, takes the project's font, or, for
   a language that lacks only a few letters and names none, the kit's own
   (the log says which letters and from which font); then runs the kit's
   new-script pipeline on the project: export the text tree, write the
   translations in (a keyword tag whose word has a new letter is written so
   that the encoder encodes the word; that works for text the encoder
   neither reorders nor wraps, and is refused with the reason for a
   right-to-left or wrapped target),
   `lang scan` (each new letter gets a font cell, shaped with HarfBuzz and
   drawn from your font into `font0.bin` and `font1.bin`), `lang encode`
   (shaping, right-to-left order by UAX #9, the new codes), `lang import`;
5. checks the objects it is about to write, on their bytes: no file past a
   proven buffer, no drawn script string past its byte limit, every edited
   row still there, every keyword still the `<k…>` word of its line; a
   failure here writes nothing;
6. writes everything into copies of both discs with `patch.patch_copy`
   (APFS clone or reflink where the file system has one, to a `.partial`
   name, each written byte verified, then renamed);
7. reads the copies again: every changed object must hold the planned
   bytes, every other text object and both fonts must still be the retail
   bytes, every keyword must be the `<k…>` word of its line, no drawn script
   string may pass its byte limit, and (ready languages) every translated
   row must read back as written. A copy that fails is deleted.

The output is a folder (`OUT/<each source image's name>`), or one `.iso`
when the set is a single disc. An output that exists is refused unless
*replace if it exists* is ticked.

**Growth.** Translations get longer. The loader itself has no cap (it reads
what the index says into its caller's buffer), and which buffer each text
file gets is traced for `synopsis.txd` only ([Limits](#limits-what-is-traced-to-the-games-code)).
The editor builds with growth allowed (`text-import --grow`): a file that
still fits its sectors is written in place, one that does not is appended at
the end of the image. The log lists every object that grew. Those are the
first screens to look at in an emulator.

### The font for a few missing letters

A language of the Latin script that lacks a few letters on the open disc
(kind `script-hybrid`) needs no font from you:

1. a font the project names (`target.font`, the Language setup) always wins;
   a named file that is missing is an error, never quietly replaced;
2. otherwise the kit's own **DejaVu Sans 2.37** (`fonts/DejaVuSans.ttf`, with
   its licence beside it) when it has every needed letter: the same glyphs on
   every machine;
3. otherwise the best installed face that has every one of them (plain, common
   sans families first, in a fixed order; the check is exact). The log then
   names the file and says another machine may pick another.

The needed letters are the ones the language lacks on this disc plus any
other letter of the project the disc cannot draw. Only those get a font
cell; every letter the disc already has is written and drawn exactly as a
*ready* build does it. The editor's checks and previews use the same font,
so a French line with `œ` checks OK and previews before any font is chosen.
A project that still says `"kind": "builtin"` for such a language (made
before this, or on another build) is treated as the language really is.

Languages of another script are not given a font this way.

## The cache

Reading every string of a disc set takes about half a minute (a minute on
the Japanese discs), because the scripts' code is disassembled; pairing the
Japanese text takes about as long. Both results are kept between runs by
`txcache.py`:

| | |
|---|---|
| where | the `xs3-txeditor` sub-folder of `$XS3_TX_CACHE` when that is set; else `~/Library/Caches/xs3-txeditor` (macOS), `%LOCALAPPDATA%\xs3-txeditor\Cache` (Windows), `$XDG_CACHE_HOME/xs3-txeditor` or `~/.cache/xs3-txeditor` (elsewhere). Never inside the kit's folder (such a setting is refused) and never in a folder that holds one of the disc images being read (nothing is then stored) |
| what | `catalog-<retail id>-<code stamp>.json.gz` per disc set (about 3 MB; it was 43 MB uncompressed), `source-<key>.json.gz` per pairing, `fonts-v1.json` (the installed-font index) |
| which disc | an entry is named by the retail id (a hash over each disc's boot executable and every index) and by a hash of the code that made it, and repeats both inside; a different disc set, a patched copy or another version of the kit never reads it. A truncated or foreign file is a miss and is removed |
| how much | pruned after every write: entries made by another version of the code, then anything unused for 60 days, then the least recently used, down to 6 disc sets, 6 pairings and 300 MB |
| what is deleted | only files with those names; other files in the folder are never touched, and no folder is removed unless empty |

The page shows the folder and its size under **Bulk ▾ → Clear the editor's
cache** (click twice to clear). `python cli.py tx-cache` prints the same and
`tx-cache --clear` deletes it. Projects and backups are never in the cache.
The first run also removes what earlier versions left in
`~/.cache/xs3-txeditor` (86 MB of uncompressed entries in an older format).

## Translating from Japanese

For a project on the USA discs, *Translate from: Japanese* (Language setup,
Advanced) shows the Japanese line above each English one. Pick either
Japanese disc; the other is found next to it. The rows stay keyed to the USA
discs. Pairing is `align-export`'s (`txsource.py`):

| family | method | offered rows with Japanese |
|---|---|---|
| scene scripts (`sb`) | same file name on both builds: index for index when the pools have the same number of strings (567 files), else aligned on identifiers and speakers (148 files; 651 USA strings left unpaired) | 11,440 of 12,012 |
| menus and tables (`mnu`) | `.txd`: index for index. `njBtlText.bin`, `SegmentFileData.bin`: key for key (the keys are the same on both builds). **Not paired:** `DBC.bin`, `DBC2.bin`, `MVtext.bin`, `njDataText.bin`, `njDBcommon.bin`, whose key lists differ between the builds (the database is sorted by name) | 831 of 4,535 |
| battle text (`bat`) | `batdat.bin`: key for key. **Not paired:** `Message.Dat` (933 strings against 871) | 2,429 of 3,414 |
| subtitles and recap (`sub`) | movie and event subtitles by time overlap (2,788 cues; a cue that shares its Japanese with another is marked); recap messages by number (69) | 2,848 of 2,959 |

The *By speaker* view shows a Japanese name under the English name the USA
discs give the same speaker (`txspeakers.json`: 268 names, generated by
`txspeakers.py` from the two disc sets, not typed in).

To translate **into** another language **on** the Japanese discs, open a
Japanese disc in step 1 instead: the original is then the Japanese text and
the build writes the Japanese discs. (The page's labels still say "English"
for the original in a few places.)

## Modules

Game-independent, taken from the Episode I kit:

| module | state |
|---|---|
| `txbackup.py`, `txlangs.py` | identical files |
| `txproject.py` | identical except `retail_id` (the disc set's executables and X3.x0 indexes, through `txdiscs`) |
| `txcatalog.py` | identical except the family list, the cache (through `txcache`), the `use` column and one note line |
| `txserver.py` | identical except: the sample catalog, the family names, disc detection through `txdiscs`, four hooks into `txcodec` (active disc, line splitting, drawing), messages, and the disc half of the self-test |
| `txeditor_page.py` | identical except 51 strings: the title, the sidebar sections, the highlighted codes, `ja-jp` for the Japanese source, the output folder, wording |
| `txtarget.py` | the language table, registry, `normalise_target`, `resolve_target`, `coverage` and the font index are the same code (10 small edits); the build half is new (`langpack`) |

Episode III's own:

| module | does |
|---|---|
| `txdiscs.py` | the disc set: the other disc, build, retail id |
| `txcache.py` | the cache on disk: where, how much, pruning, `tx-cache` |
| `txcodec.py` | display form and checks on `textcodec` / `textpack.FontCheck` / `font.Measurer`; same function names as Episode I's |
| `txfam_core.py` | rows (script strings by code use), keyword links, the traced guides and limits, validation and rebuild of all four families on `textpack.KINDS` |
| `txfam_sb.py`, `txfam_mnu.py`, `txfam_bat.py`, `txfam_sub.py` | the four families (thin) |
| `txsource.py` | the Japanese original, on `align.py` |
| `txspeakers.py`, `txspeakers.json` | Japanese speaker → USA speaker |
| `txbuild.py` | the build, `tx-build` / `tx-catalog` / `tx-selftest`, the self-tests |

A family returns its change set (`plan`) instead of patching an image
(`apply` on Episode I), because Episode III's objects are written in one
`patch_copy` over both discs.

**Changes to the shared modules since the port (2026-11-21), to fold back
into the Episode I and II editors.** None is specific to this game:

| module | change |
|---|---|
| `txcache.py` (new) | the whole cache: folder, keys, gzip, pruning, clear. Only the folder name and the environment variable are per game |
| `txcatalog.py` | caches through `txcache` under a content hash (`content_id`), not the retail id alone; `use_cache=False` neither reads nor writes; one more dictionary column (`use`) |
| `txsource.py` | caches through `txcache`; changes no ambient disc |
| `txserver.py` | every request runs in the scope of the disc it names, or of the only disc open (`_scope`, `_sole_iso`); `_current()` refuses when two catalogs are loaded, where it used to answer from the last one opened; the in-memory catalog is keyed by the whole set, so a second disc that appears is seen; `GET /tx/project` reads the project and its version under the lock a save holds; `check_one`, the length guides and *Wrap to fit* pass the row's own disc; `_family_rules` calls a family's `check_row` when it has one; *Wrap to fit* keeps a `<…>` tag whole; `GET /tx/cache`, `POST /tx/cache/clear`; `/tx/languages?iso=`; the automatic font in `_target_row_check`, `preview_png` and `target_preview` (each only when `txtarget` has `with_font`) |
| `txtarget.py`, shared half | the language table is computed without looking at any open disc; `native_predicate` keeps the disc it was made for; `auto_font`, `with_font`, `readiness`; `resolve_target` treats a stale `builtin` as the profile's `script-hybrid` and carries `lacking`; the preview pack is keyed by the font file's time and, for scripts whose letters change shape, by the text; the font index is written through `txcache` |
| `txeditor_page.py` | the language list is asked for the open disc and kept per disc; `iso` goes with the custom-language and font requests; the *ready · a few letters added* badge; the setup does not write a font path into the project when the kit's font does the job; the cache item of the Bulk menu; the wording of the limits |
| `txcodec.py` (per game, but the same shape in each) | the open disc and the glyph-code permission are context variables (`disc`, `use_disc`, `set_active`, `glyph_codes`), no longer module globals; `control_errors` (the control-byte rule as a function, so a build can apply it) |
| `txbuild.py` | the rules about the edits run on both build paths (`edit_errors`), the objects are checked before the write (`planned_errors`) and a missing row after it on both paths; two source images with one file name are refused, since the copies are named after them |
| `txdiscs.py` | a remembered pair is checked against both images' size and time; a lone disc is looked for again after ten seconds; a second disc named by hand that is missing, or is the first, is an error |

Not ported: `pseudoloc.py` (it respells Episode I executable-string files
for a pipeline test; Episode III has no such files), the battle-font target
(Episode III's battle HUD letters are pictures, `statfont`), the capital
accent font fix (not needed). Text that is not in the text-export tree is
not in the editor either: strings in the executable, `.xep` files, text
inside pictures (`image-export`), the battle HUD letters.

## What was tested

`python cli.py tx-selftest --iso DISC1.iso [--jp JPDISC.iso] [--scratch DIR]`
runs all of it on your own discs (builds go to clones in the scratch folder,
are read back and deleted). `python cli.py self-test` runs the part that
needs no disc, and the read-only disc checks when `XS3_D1` / `XS3_JP1` are
set; `build.py` runs that from the finished bundle.

Results on the real images, 2026-11-21 (after the five fixes of that day;
`tx-selftest` passes all 13 steps on the USA pair with `--jp`, 194 checks, and
all 11 on the Japan pair, 176 checks):

| check | USA Disc 1 + 2 | Japan Disc 1 + 2 |
|---|---|---|
| rows read, ids unique | 104,003 | 120,645 |
| every script's code read; only strings a show native draws are offered | 715 scripts; 10,015 offered, 73,601 debug prints hidden | 856 scripts; 13,235 offered, 86,561 hidden |
| every keyword's bytes are the `<k…>` word of its line (the retail set against its own links) | 534 keywords, 569 tags | 1,054 keywords, 1,113 tags |
| every offered original encodes back to its own bytes | yes (the 16 Japanese placeholder lines aside) | yes |
| unedited project (25 rows, every family) built | both copies byte-identical to retail, whole-image sha1 | both copies byte-identical |
| builtin-language build, rows of every family and both discs' own chains, one translated keyword tag | 26 of 26 rows read back; the keyword follows its tag; only the 14 planned objects differ, 907 others identical | same checks pass |
| refusals, nothing written: undrawable letter, unknown id, another disc set, a keyword row changed by hand, a removed `<k…>` tag (on both build paths) | all refused | all refused |
| new-letter build with a chosen font | Russian with Arial: text and both fonts written, read back, a line drawn from the patched disc's own font | French with Arial (é, à, ô drawn) |
| **a language that lacks a few letters, no font chosen** | French: `Œuvre, cœur, L'Haÿ, Ÿ` built with DejaVu Sans; the three letters took five new font cells (Œ and œ are two cells wide), each with ink and an advance, read from the patched disc's own font; a keyword `<kœuf>` and its KeyWait string hold the same bytes on the disc | Spanish (ñ ¿ é …) the same way |
| a page past the 16,000-byte limit; a line past its width guide; *Wrap to fit* | refused; warned; a 2,335 px line wrapped to 463 px (guide 469) | refused; warned; 2,575 px to 468 px |
| the app's own server, page → languages → check → wrap → preview → project → Build job → read-back → cache | French with no font, 9 rows of every family and a keyword | Japanese, 9 rows and a keyword |
| two disc sets in one server | 40 interleaved rounds of check / languages / preview per tab over HTTP, and 40 rounds of two threads inside different disc scopes at the same moment: every answer for its own disc; a request naming no disc is refused while two sets are open | (the other tab of the same test) |
| Japanese original paired | 16,024 of the 21,456 rows that are not hidden | — |
| the bundle (`build.py`, macOS) | built with `fonts/` inside; its own `xeno-cli self-test` and `gui --self-test` exit 0 | — |

2026-11-26, after the parity review (docs/panel/xs3-editor-parity-2026-11-26 in
the workspace): `txserver selftest` (fake and USA pair), `selftest-two` (USA +
Japan) and `gui --self-test` pass, with new checks for the project-save
refusals and the whole-project check; in Chrome, a French project created with
no font chosen, a line with œ wrapped, Check project, and a Build of both discs
(119 s; 3 objects changed and read back, 918 untouched). A cold disc read no
longer holds the server lock: a cached set answered in 0.13 s while another
set was being read, and two requests for the set being read shared one read.

The stand-alone package (`python build.py --editor`, macOS, 2026-11-26): an 81 MB
`Xenosaga-III-Translation-Editor.app`; its `xeno-cli self-test` and
`--self-test` exit 0; started through LaunchServices it serves the editor and
sends `/` there, with no extractor link; a French Build of both discs from
inside the app finished in 129 s and read back. First start takes about 16 s
before the page answers.

Also run once by hand: the May 2006 prototype opens and its four families
pass their read checks (101,902 rows; all 715 scripts read by their code,
10,002 script rows offered, 534 keywords; no build was made from it), and a
lone copy of USA Disc 1 in a folder of its own builds as a one-disc project
(11 objects, one image). `patch` warns on such a build that the other disc's
X3.00 no longer matches: translate with both discs present.

In the game (PCSX2 2.9.175, USA Disc 1, New Game): 2026-11-21, one project
each in Hindi, Traditional Chinese, Cherokee and Arabic, built by the editor;
the caption `evt/us/s000100.txt` (about 10 s in) and the first dialogue box
`cf/us/8000.sb#0114` (Blue Testament, about 2 min 25 s in) drawn in each, the
Arabic right to left. The Chinese line showed thin vertical lines between
characters: Han glyphs were drawn at the default px 20, which fills the 20 x 24
cell edge to edge (rows 0-18, columns 0-19), and the game's filtered draw
picked up the neighbouring cells. The Japanese retail font keeps its kanji in
rows 4-18 and columns 1-18. Han, kana and Hangul now default to px 17 on
baseline 17 (`txtarget.RENDER`); rebuilt and booted 2026-11-27, the lines are
gone.

Not tested: Disc 2 and the disc swap, the Japanese discs and the prototype in
an emulator; Windows and Linux (the shared modules are the Episode I ones,
which run there, but this port ran on macOS only).
