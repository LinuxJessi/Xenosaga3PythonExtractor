# Documents

Every document in this folder, grouped by what you want to do. The kit's
front page is [../README.md](../README.md); what changed and what to re-run is
in [UPDATES.md](UPDATES.md).

**Write-side caveat.** Four kinds of disc written by the kit have been booted
in PCSX2 (2026-11-20: a same-size text edit, Arabic, Japanese on the USA disc,
a grown file). Everything else on the write side is tested on disc copies and
in previews only. [MODDING.md](MODDING.md) has the table; each page says what
is and is not verified.

## Look at the game

| Document | What it covers |
|---|---|
| [BROWSING.md](BROWSING.md) | What `dump` and `browse` write, which folders to open first, how long each kind takes |
| [BLENDER.md](BLENDER.md) | Opening the kit's models in Blender: the one-step `blend` command, navigation, Material Preview, the "balls everywhere" fix, Japanese-disc models |
| [MODELS.md](MODELS.md) | How the `.chr` / `.wpn` / `.map` packages and `.pxy` meshes become glTF: VIF batches, skins, skeletons, the sweep and its numbers |
| [disc-catalog.md](disc-catalog.md) | The data dictionary: every file extension on the discs, what it is, where the engine reads it, plus "Fun finds" |
| [chr-txy-format.md](chr-txy-format.md) | The embedded `txy` texture format inside packages and effect files |
| [MOTION.md](MOTION.md) | The `.xap` body clips and `.fap` face clips as glTF animations: layout, proofs, what is unverified |
| [MUSIC.md](MUSIC.md) | The soundtrack (120 recorded ADX streams, their loop points), the other audio folders, the DTPK sound banks |
| [FORMATS.md](FORMATS.md) | The byte layout of every format the kit reads or writes, how each was proven, and what is not decoded |
| [DIALOGUE.md](DIALOGUE.md) | Every line in the order the scripts play it: which strings are shown and which are debug prints, voice clips per line, movie and event subtitles in place |

## Translate and add scripts

| Document | What it covers |
|---|---|
| [LANGKIT.md](LANGKIT.md) | the langkit tour: the translation editor in pictures, the four steps, editor builds in the game, what is and is not checked |
| [TRANSLATION-EDITOR.md](TRANSLATION-EDITOR.md) | the translation editor (`gui --editor`): one project for both discs, what is listed, the checks, the build, translating from Japanese, the modules, what was tested |
| [TRANSLATING.md](TRANSLATING.md) | `text-export` / `text-import`: the text tree, the USA and Japanese codecs, escapes, the font check, sizes and `--grow`, refusals, `align-export` |
| [SCRIPTS.md](SCRIPTS.md) | `lang scan / encode / import / preview`: Arabic, Devanagari and other scripts drawn into the game fonts; Japanese on the USA build (`--donor`, `--unlock`) |
| [FONT.md](FONT.md) | `font0` / `font1`: cell layout, metrics, the rules read from each build's executable, `font-donor`, glyph slots and the `glyphs-*` commands |

## Mod and write back

| Document | What it covers |
|---|---|
| [MODDING.md](MODDING.md) | Start here: everything the kit can change, the command and guide for each, and how far each has been checked in the game |
| [REPACK.md](REPACK.md) | `patch` (copies, Disc 1 + Disc 2 pairs, `--grow`, the sector budget, refusals) and the older in-place `repack-*` commands |
| [MODDING-CHARACTERS.md](MODDING-CHARACTERS.md) | Recolouring and repainting character textures, from three commands to a hex editor |

## Cutscenes

| Document | What it covers |
|---|---|
| [FMV-HD-SCHEME.md](FMV-HD-SCHEME.md) | Repackaging upscaled `.sfd` cutscenes so the PS2 engine plays them |
| [FMV-RELOADER.md](FMV-RELOADER.md) | Design of an external HD cutscene player for PCSX2 (scaffold; blocked on the FMV-active signal) |

## The discs' story

| Document | What it covers |
|---|---|
| [FINDS.md](FINDS.md) | Leftovers on the discs: debug switches, cheat codes in the mini-game, test files, what the prototype has that retail lost |
| [HISTORY.md](HISTORY.md) | Build and mastering dates read from each image, the three builds, what changed from Episode I to III |

## Kit

| Document | What it covers |
|---|---|
| [CODEBASE.md](CODEBASE.md) | How the code is organized: design rules, the module stack, where to start reading, packaging |
| [UPDATES.md](UPDATES.md) | Change log, newest first, with what to re-run |
| [security.md](security.md) | Why Windows SmartScreen warns about the pre-built `gui.exe`, and how to check it |
