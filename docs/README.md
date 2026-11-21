# Documents

Every document in this folder, grouped by what you want to do. The kit's
front page is [../README.md](../README.md); what changed and what to re-run is
in [UPDATES.md](UPDATES.md).

**Write-side caveat.** The pages about writing to discs (translating, new
scripts, fonts, repacking) describe work tested on disc copies and in previews
only. No disc built by the kit has been booted in PCSX2 yet; each page says
what is and is not verified.

## Look at the game

| Document | What it covers |
|---|---|
| [BLENDER.md](BLENDER.md) | Opening the kit's models in Blender: the one-step `blend` command, navigation, Material Preview, the "balls everywhere" fix, Japanese-disc models |
| [MODELS.md](MODELS.md) | How the `.chr` / `.wpn` / `.map` packages and `.pxy` meshes become glTF: VIF batches, skins, skeletons, the sweep and its numbers |
| [disc-catalog.md](disc-catalog.md) | The data dictionary: every file extension on the discs, what it is, where the engine reads it, plus "Fun finds" |
| [chr-txy-format.md](chr-txy-format.md) | The embedded `txy` texture format inside packages and effect files |

## Translate and add scripts

| Document | What it covers |
|---|---|
| [TRANSLATING.md](TRANSLATING.md) | `text-export` / `text-import`: the text tree, the USA and Japanese codecs, escapes, the font check, sizes and `--grow`, refusals, `align-export` |
| [SCRIPTS.md](SCRIPTS.md) | `lang scan / encode / import / preview`: Arabic, Devanagari and other scripts drawn into the game fonts; Japanese on the USA build (`--donor`, `--unlock`) |
| [FONT.md](FONT.md) | `font0` / `font1`: cell layout, metrics, the rules read from each build's executable, `font-donor`, glyph slots and the `glyphs-*` commands |

## Mod and write back

| Document | What it covers |
|---|---|
| [REPACK.md](REPACK.md) | `patch` (copies, Disc 1 + Disc 2 pairs, `--grow`, the sector budget, refusals) and the older in-place `repack-*` commands |
| [MODDING-CHARACTERS.md](MODDING-CHARACTERS.md) | Recolouring and repainting character textures, from three commands to a hex editor |

## Cutscenes

| Document | What it covers |
|---|---|
| [FMV-HD-SCHEME.md](FMV-HD-SCHEME.md) | Repackaging upscaled `.sfd` cutscenes so the PS2 engine plays them |
| [FMV-RELOADER.md](FMV-RELOADER.md) | Design of an external HD cutscene player for PCSX2 (scaffold; blocked on the FMV-active signal) |

## Kit

| Document | What it covers |
|---|---|
| [UPDATES.md](UPDATES.md) | Change log, newest first, with what to re-run |
| [security.md](security.md) | Why Windows SmartScreen warns about the pre-built `gui.exe`, and how to check it |
