# How the code is organized

A tour for someone who has never seen the kit: what each module does, how
they stack, and where to start when you want to change something. Byte
layouts are in [FORMATS.md](FORMATS.md); what `browse` writes is in
[BROWSING.md](BROWSING.md); writing to discs is in [MODDING.md](MODDING.md).
This page is about the code. (The Episode I and II kits have the same page,
so the three can be read side by side.)

## The design rules

1. **Python 3.9 or newer and five required packages.** `requirements.txt`
   lists numpy, Pillow, capstone, fonttools and uharfbuzz. All five are
   required: the launchers install them into `.venv/` when the Python they
   find lacks any, `build.py` refuses to build without them, and
   `python cli.py self-test` fails (it does not skip) when a module cannot
   import. No command falls back to a worse path. ffmpeg (audio, movies),
   Blender (`blend`) and 7-Zip (`prep`) are programs, found on PATH or under
   `tools/` in the Windows bundle.
2. **Every module stands alone and registers its own commands.** A module
   that has commands defines `add_commands(subparsers)`; `cli.py` imports the
   modules named in `COMMAND_MODULES` and calls it. Adding a command means
   adding it to its module, not to `cli.py`.
3. **Every claim has a self-test.** A module that decodes or rebuilds
   something has `self_test()` with made-up data, and disc checks that run
   when `XS3_D1`, `XS3_D2`, `XS3_JP1`, `XS3_JP2` or `XS3_PROTO` name an image.
   `cli.py self-test` runs all of them (`SELF_TESTS`, 34 modules), and
   `build.py` runs them again from inside the finished bundle.
4. **Writers write copies.** `patch`, `text-import`, `lang import` and
   `image-import` never open an original image for writing; the older
   single-file `repack-patch` and `chr-iso-patch` commands write in place and
   say so (their `--iso` is never pre-filled by the GUI).
5. **The build decides, not the user.** `region.py` reads the boot
   executable's serial and sha256 and picks the language folder, codec and
   the executable addresses; a mixed Disc 1 + Disc 2 pair or an unknown
   executable is refused by the writers.

## The stack

```
   gui.py ───────────────► cli.py ◄──────────── you, at a terminal
 (cards built from           │
  cli.py's parser)           ├─ region / resolve ─► region.py            (which build, engine paths)
                             ├─ list / dump / iso-ls / toc-check ─► disc.py ─► toc_bin.py, chains.py, iso9660.py
                             ├─ browse ─► browse_bundle.py ─► xtx_decode.py tm2_decode.py engine_palettes.py   pictures
                             │                               chrtex.py xcpack.py                              package textures
                             │                               adx.py dap_decode.py                             music, sound banks
                             │                               sb.py txd.py njbin.py msgdat.py batdat.py subtitle.py   text
                             │                               models_sweep.py                                  models
                             ├─ model / models / blend ─► models_sweep.py ─► pxy.py, xhr.py, xap.py, vif.py, gltf.py ─► blend.py
                             ├─ motion ─► xap.py                            (clip tables, poses, the disc sweep)
                             ├─ text-export / text-import / text-roundtrip ─► textpack.py ─► the six text modules, textcodec.py
                             ├─ align-export ─► align.py                    (Japanese beside English)
                             ├─ sb / natives ─► sbvm.py ─► sb.py, sbnatives.py   (the scripts' code, the engine's natives)
                             ├─ dialogue ─► dialogue.py ─► sbvm.py, sb.py, subtitle.py   (lines in play order, voice clips)
                             ├─ lang scan / encode / import / preview ─► langpack.py ─► glyphs.py, font.py
                             ├─ tx-build / tx-catalog / tx-selftest ─► txbuild.py ─► txfam_core.py ─► textpack.py, patch.py
                             │      (gui.py serves /editor and /tx/* itself, through txserver.py)   the translation editor
                             ├─ font-* / glyphs-* / statfont-* ─► font.py, glyphs.py, statfont.py
                             ├─ image-export / image-import / xtx-* ─► imagetext.py, xtx_encode.py
                             ├─ music-list ─► adx.py
                             ├─ patch ─► patch.py ─► disc.py                (copies, pairs, --grow)
                             ├─ repack-* / chr-* ─► repack.py, chrtex.py    (older, one ISO, in place)
                             ├─ disasm ─► disasm_code.py                    (capstone)
                             └─ prep / map-regions / toc / scan / extract / verify   the 7-Zip pipeline (below)
```

There are two ways into a disc, and both are kept:

* **Direct from the image** (`disc.py`, 2026-11-20): the disc's own
  X3.00 / X3.10 / X3.20 indexes are parsed (`toc_bin.py`) and any in-game path
  is read by sector. This is what every newer command uses, and the only way
  that reads the Japanese discs and the prototype.
* **The 7-Zip pipeline** (`prep` → `map-regions` → `scan` → `extract` →
  `verify`; `iso_ops.py`, `lba.py`, `regions.py`, `containers.py`,
  `resolver.py`, `manifest.py`, `scooper.py`, `verify_cmd.py`): the original
  route, which extracts the X3.* files with 7-Zip and slices them by the
  bundled `lba/Lba*.txt` tables. `lba-from-iso` (`x3index.py`) rebuilds those
  tables from any image.

## The modules

Line counts are from 2026-11-21.

### Reading a disc

| Module | Lines | Role |
|---|---|---|
| `iso9660.py` | 301 | minimal ISO 9660 reader, no 7-Zip; `iso-ls` |
| `chains.py` | 199 | the three bigfile chains (X3.00+01+02, X3.10..13, X3.20..23) as one byte space each |
| `toc_bin.py` | 442 | parse and rebuild the binary indexes X3.00 / X3.10 / X3.20 (Episode II's front-coded grammar); `toc-check` |
| `x3index.py` | 199 | an independent reader of the same indexes, reversed from the executable; feeds `lba-from-iso` |
| `disc.py` | 838 | open an image, resolve any in-game path through the disc's own index, read, and (on a writable copy) write, relocate and append; `list`, `dump` |
| `region.py` | 1173 | which build an image carries (USA, Japan, May 2006 prototype), its language folder, its executable tables with every address checked against the code; `region`, `resolve` |
| `xcpack.py` | 298 | the "Xc" MR package layer of `.chr` / `.map` / `.wpn` / `.sme`: header, sub-resource directory, the four LZSS flavours |

### The 7-Zip pipeline

| Module | Lines | Role |
|---|---|---|
| `iso_ops.py` | 303 | 7-Zip helpers and the container map |
| `lba.py`, `toc.py` | 128, 114 | parse the legacy `Lba*.txt` tables; a readable summary of them |
| `regions.py`, `containers.py`, `resolver.py` | 205, 316, 166 | assign each table to its X3.* containers and turn a row into (container, offset) |
| `manifest.py`, `scooper.py`, `verify_cmd.py` | 102, 129, 130 | the extraction manifest, the byte-slice extractor, the size/SHA-1 check |
| `code_extract.py` | 83 | pull SLUS, OVL, IRX and SYSTEM.CNF out of the ISO |
| `disasm_code.py` | 243 | MIPS R5900 disassembly with string cross-references |

### Pictures

| Module | Lines | Role |
|---|---|---|
| `xtx_decode.py` | 923 | `.xtx` to PNG: linear 32-bit files, and the swizzled 8-bit sheets with their parked palettes |
| `engine_palettes.py` | 347 | which palette the game itself binds to each part of an 8-bit sheet, read from the draw code |
| `xtx_encode.py` | 632 | PNG back to `.xtx`, same size, byte-exact on a no-op; `xtx-export`, `xtx-encode` |
| `tm2_decode.py` | 127 | Sony TIM2 logos to PNG |
| `chrtex.py` | 875 | the `txy` texture block inside packages: decode, palettes out and in, repaint, recolour, ISO sweep; the `chr-*` commands |
| `imagetext.py` | 647 | the localized pictures (JPEG, PNG, `.xtx`, `.tm2`, effect `txy`) out as PNG and back; `image-export`, `image-import` |
| `carve_jpeg.py` | 79 | JPEGs concatenated inside `credit.bin` |

### Models

| Module | Lines | Role |
|---|---|---|
| `vif.py` | 269 | strict PS2 VIF command-stream walker |
| `pxy.py` | 1545 | `.pxy` meshes to glTF: batches, UVs, colours, skin weights, materials, the second mesh at header +0xD0 |
| `xhr.py` | 399 | `.xhr` skeletons: hierarchy and bind pose |
| `xap.py` | 2019 | `.xap` body clips and `.fap` face clips: the decoder, the engine's pose formula, glTF animation tracks; `motion` ([MOTION.md](MOTION.md)) |
| `gltf.py` | 850 | format-neutral `.glb` writer and reader, with the animation helpers; `glb-info` |
| `models_sweep.py` | 953 | one model to `.glb` with its same-named clips, and the sweep of every model on a disc; `model`, `models` |
| `blend.py` | 672 | a `.glb` to a ready-to-open `.blend` through Blender in the background; `blend` |

### Sound and movies

| Module | Lines | Role |
|---|---|---|
| `adx.py` | 224 | ADX stream headers and which streams are the soundtrack; `music-list` |
| `dap_decode.py` | 175 | DTPK sound banks (`.dap`) to one WAV per cue |
| `fmv_sfd.py` | 225 | Sofdec `.sfd` demux and same-size video splice |

### Text

| Module | Lines | Role |
|---|---|---|
| `textcodec.py` | 827 | bytes of game text to editable text and back, exactly: the USA pair gate, the Japanese reading, developers' notes; `text-decode` |
| `sb.py` | 395 | scene scripts: parse the text pool and rebuild it; `sb-strings` |
| `sbvm.py` | 1,013 | scene scripts as programs: the 99-opcode byte machine, disassembler, native-call walk, the reader of the tables in an executable; `sb`, `natives` |
| `sbnatives.py` | 186 | data: the 22 native classes and 327 functions the engine registers (names, minimum arguments, USA handler addresses) |
| `dialogue.py` | 768 | dialogue in play order from the scripts' code, voice ids resolved to their streams, movie and event subtitles in place; `dialogue` |
| `txd.py` | 158 | menu text tables; `txd-strings` |
| `njbin.py` | 317 | the seven menu databases; `nj-strings` |
| `msgdat.py` | 247 | the HaKox mini-game's `Message.Dat`; `msgdat-strings` |
| `batdat.py` | 380 | the battle data container's 28 tables; `batdat-strings` |
| `subtitle.py` | 331 | movie and event subtitles, the pse director scripts and `.mes` files; `subtitle-text` |
| `textpack.py` | 1148 | all of the above as one UTF-8 tree and back onto copies of the discs; `text-export`, `text-import`, `text-roundtrip` |
| `align.py` | 477 | Japanese and English side by side (TSV, JSON, dual SRT); `align-export` |

### Fonts and new scripts

| Module | Lines | Role |
|---|---|---|
| `font.py` | 1755 | `font0` / `font1`: sheets, metrics, the 8x8 system font, the addressing rules read from each build's executable; `font-extract`, `font-rebuild`, `font-measure`, `font-donor` |
| `glyphs.py` | 1378 | free glyph slots, TrueType rendering, the executable unlock; the `glyphs-*` commands |
| `langpack.py` | 2437 | shape, wrap, order (UAX #9) and encode a translation for the game's font; `lang scan / encode / import / preview` |
| `statfont.py` | 660 | the HUD's letter sprites in the window sheets and their tables in the executable; `statfont-export`, `statfont-import` |

### The translation editor

Ported from the Episode I kit on 2026-11-21; [TRANSLATION-EDITOR.md](TRANSLATION-EDITOR.md)
has the reference and the list of what differs from the Episode I files.

| Module | Lines | Role |
|---|---|---|
| `txeditor_page.py` | 3107 | the page served at `/editor` (one string: HTML, CSS, JS); Episode I's with 51 strings changed, plus the per-disc language list, the readiness badge and the cache control |
| `txserver.py` | 2079 | the page's routes (`/tx/*`): catalog, per-row check, preview, project, languages, fonts, cache; every request runs in the scope of its own disc (`txcodec.disc`) |
| `txproject.py`, `txbackup.py`, `txlangs.py` | 398, 295, 580 | the project file, its backups, the language registry (the last two are Episode I's files unchanged) |
| `txcatalog.py` | 381 | the four families as one cached list of rows |
| `txcache.py` | 432 | the cache on disk: platform folder or `$XS3_TX_CACHE`, entries keyed by disc set and code, gzip, pruning; `tx-cache` |
| `txdiscs.py` | 287 | the disc set: finds the other disc, the build, the retail id |
| `txcodec.py` | 619 | the editor's text form and checks, on `textcodec`, `textpack.FontCheck`, `font.Measurer`; the per-thread disc scope |
| `txfam_core.py` | 1119 | rows (script strings sorted by what the code does with them, on `dialogue.string_kinds`), keyword links, the traced width guides and byte limits, validation and rebuild for every family, on `textpack.KINDS` |
| `txfam_sb.py`, `txfam_mnu.py`, `txfam_bat.py`, `txfam_sub.py` | 69-70 each | the four families: scene scripts; menus and tables; battle text and the mini-game; subtitles and recap files |
| `txtarget.py` | 1443 | what a language needs on the open disc; the font for a few missing letters (`fonts/DejaVuSans.ttf`); the new-letter build and preview through `langpack` |
| `txsource.py` | 431 | the Japanese original beside each USA row, on `align.py` |
| `txspeakers.py` | 84 | generates `txspeakers.json` (Japanese speaker to USA speaker) from the discs |
| `txbuild.py` | 914 | the build and its read-back; `tx-build`, `tx-catalog`, `tx-selftest`, `tx-cache`; the editor's self-tests |

### Writing back

| Module | Lines | Role |
|---|---|---|
| `patch.py` | 958 | a set of changed files into copies of one disc or a Disc 1 + Disc 2 pair: in place, or appended with `--grow`, read back afterwards; `patch` |
| `repack.py` | 368 | the older single-file, in-place commands (`repack-info`, `-extract`, `-patch`, `-tree`) |

### The front ends

| Module | Lines | Role |
|---|---|---|
| `cli.py` | 814 | the parser, the 7-Zip pipeline commands, `browse`, `doctor`, `disasm`, `self-test` |
| `browse_bundle.py` | 1091 | the `browse` tree: one conversion per kind (see below) |
| `gui.py` | 2032 | the local web page, built from `cli.py`'s parser |
| `build.py` | 135 | builds the app bundle and runs its self-tests |

## The GUI reads the CLI

`gui.py` does not list the commands itself. When it starts it asks `cli.py`
for its parser and makes one card per subcommand (one per leaf for `lang scan`
and the like): a flag becomes a checkbox, `--iso` a disc-image picker, `--out`
a folder picker, `--kinds` one checkbox per browse kind. So adding a command
adds a card. Two optional tables make a card nicer: `COMMAND_HELP` (friendlier
text) and `SECTION_OF` / `SECTION_PREFIXES` (which section it sits in).
`python gui.py --self-test` fails when a command of the real CLI falls into
the "Other" section, so a new command needs a section.

## Adding a browse kind

In `browse_bundle.py`: add the name to `ALL_KINDS` and its extensions to
`_EXTS`; convert one file in `_convert_one` (it returns the kind name, an
error or None, and a count), count it in `BundleStats` and in the loop in
`bundle`; a step that needs the whole dump at once (a table, a de-duplicating
sweep) is a function called after the pool, like `_music_table` or
`_package_textures`. Add a check to `self_test`. The `music` kind
(2026-11-21) is the smallest worked example.

## Where to start reading, by goal

| You want to | Start in |
|---|---|
| read one file off a disc | `disc.py` (`Disc.read`), then `toc_bin.py` |
| support another build | `region.py` (a profile and its address checks) |
| decode a new texture case | `xtx_decode.py` for UI sheets, `chrtex.py` for package textures |
| fix a model | `pxy.py` (mesh), `xhr.py` (skeleton), `xap.py` (motion), `models_sweep.py` (pairing and numbers) |
| add a text container | a module with `parse` / `rebuild` / `self_test`, then a kind in `textpack.py` |
| change how text is written back | `textpack.py`, `patch.py` |
| add a script or alphabet | `langpack.py`, `glyphs.py`; [SCRIPTS.md](SCRIPTS.md) |
| change what the translation editor lists or checks | `txfam_core.py` (rows, categories, hide and lock reasons, `GUIDES` / `OBJ_LIMITS`), `txcodec.py` (the checks) |
| change the editor's page or routes | `txeditor_page.py`, `txserver.py`: change them in the Episode I kit first, they are shared |

## Packaging

`python build.py` renders the Windows version resources
(`packaging/render_version_info.py`), makes the placeholder icon when none is
committed (`packaging/build_icon.py`), runs PyInstaller on
`packaging/xenosaga-extractor.spec` and then runs `xeno-cli self-test` and
`gui --self-test` from the finished bundle. The spec bundles every module of
the kit (found by listing the folder) and the five packages, puts `gui` and
`xeno-cli` side by side in `dist/Xenosaga3-Extractor/`, and on macOS also wraps
them in `Xenosaga-III-Extractor.app`. The release workflow
(`.github/workflows/release.yml`) runs `build.py` on GitHub's Windows machine,
adds portable ffmpeg and 7-Zip under `tools/`, and attaches the zip to a draft
release when a `v*` tag is pushed.

Running the bundle is what found, on 2026-11-21, that a `xeno-cli` built from
the spec as it stood refused every command (`gui.py` was not bundled into it,
and `cli.py` refuses to run while a command module cannot import). The macOS
bundle is checked by `build.py` on this machine; the Windows one is checked by
the workflow and has not been run by hand.
