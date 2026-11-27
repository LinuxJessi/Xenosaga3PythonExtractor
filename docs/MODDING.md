# Modding Episode III

Everything the kit can change on a disc, in one place: which command does
it, which page explains it, and how far each has been checked. The Episode I
and II kits have a page of the same name; here the detail lives in the pages
this one links to.

**Always give the kit your original images and let it write copies.** `patch`
and the importers never open an original for writing. On macOS a copy is an
APFS clone, so it costs no disk space until bytes change.

## What you can change

| You want to change | Commands | Guide | Checked how far |
|---|---|---|---|
| any file, any size | `patch` (`--set`, `--tree`, `--grow`, `--dry-run`) | [REPACK.md](REPACK.md) | in place and appended, single disc and Disc 1 + Disc 2 pair, every write read back; a grown text file was booted (below) |
| dialogue, menus, subtitles, battle and database text | `text-export`, `text-import` | [TRANSLATING.md](TRANSLATING.md) | every container rebuilds byte-identically on all five images; a same-size English menu edit and a grown synopsis were **booted in PCSX2** |
| the language itself: a new script or alphabet | `lang scan`, `lang encode`, `lang import`, `lang preview` | [SCRIPTS.md](SCRIPTS.md) | Arabic (new glyphs, right-to-left, scene dialogue) and Japanese on the USA disc (`--unlock jp`) were **booted in PCSX2** |
| the fonts | `font-extract`, `font-rebuild`, `font-donor`, `glyphs-*` | [FONT.md](FONT.md) | byte-exact out and back in; new glyphs seen in game through the `lang` builds |
| the HUD's small letters | `statfont-export`, `statfont-import` | `statfont.py`'s docstring, [FORMATS.md](FORMATS.md#13-fonts) | on disc copies only; not booted |
| pictures that carry text (JPEG pages, PNG, UI sheets, logos, effect textures) | `image-export`, `image-import`, `xtx-export`, `xtx-encode` | `imagetext.py`'s docstring, [FORMATS.md](FORMATS.md#3-xtx-pictures) | on disc copies only (same size, or within the file's sector allocation); not booted |
| a character's colours or texture pixels | `chr-decode`, `chr-palettes`, `chr-import-palettes`, `chr-import-entry`, `chr-recolor`, `chr-iso-sweep` | [MODDING-CHARACTERS.md](MODDING-CHARACTERS.md) | the pink KOS-MOS and pink Shion recolours were seen rendering in PCSX2 |
| a cutscene's video | `fmv_sfd.py` (same-size video splice) | [FMV-HD-SCHEME.md](FMV-HD-SCHEME.md) | the splice round-trips byte-identically; a replaced movie has not been booted |

What was booted, with the commands and captures, is the 2026-11-20 seventh
pass in [UPDATES.md](UPDATES.md). Discs written from the Japanese images or
the prototype, and Disc 2 of any pair, have not been booted.

## The loop

```sh
# look: where is the file, how much room does it have
python cli.py repack-info --iso D1.iso --path '\mnu\us\menutext.txd'

# take it out, change it
python cli.py repack-extract --iso D1.iso --path '\mnu\us\menutext.txd' --out mymod/mnu/us/menutext.txd

# plan, then write copies of both discs
python cli.py patch --iso D1.iso --iso D2.iso --out modded/ --tree mymod --dry-run
python cli.py patch --iso D1.iso --iso D2.iso --out modded/ --tree mymod --grow
```

For text, pictures and fonts you do not handle files yourself: the export
commands write an editable tree, and the import commands check it and call
the same patcher.

## Rules the writers keep

* **Chain 0 is on both discs.** A file in `X3.00`'s chain exists on Disc 1 and
  Disc 2, and the two copies of the index must stay identical. Give both
  images; a pair patched one disc at a time is refused later.
* **Same build only.** A USA image with a Japanese or prototype image is
  refused, and so is an executable the kit does not know.
* **In place when it fits, appended when it does not.** A changed file that
  fits its sector allocation is written where it was. With `--grow` a larger
  one is appended at the end of the image and its index entry is moved; the
  plan shows the sector budget first.
* **Read back.** Every written file is read again through the patched index
  and compared before the copy gets its final name. A refusal or a failed
  check leaves no output.
* **A tree knows its disc.** A text or picture tree records the disc it was
  exported from, and the importers refuse another disc or an already patched
  one unless told to rebase.

## What cannot be changed yet

* **Models.** They come out as glTF ([MODELS.md](MODELS.md)); there is no
  importer for an edited mesh. Texture edits are the route.
* **Motion.** The clips come out as glTF animations ([MOTION.md](MOTION.md));
  there is no importer for an edited one.
* **Scripts' logic, events, effects.** Not decoded
  ([FORMATS.md](FORMATS.md#17-not-decoded)). A script's *text* can be any
  length; its code is carried untouched.
* **Movies larger than the original.** The splice keeps the byte budget; a
  longer or higher-bitrate movie needs a muxer the kit does not have.
* **Compressed packages.** The field maps are LZSS-packed; the kit reads them
  and has no compressor for them.
* **Sound.** No ADX or DTPK writer.

## Seeing it in the game

Boot the patched copy in PCSX2 and load a **memory-card save** or start a new
game. A savestate made on the original image restores the old video memory,
so a recolour seems not to have worked until the game loads the model again.
The game has no checksums: it reads whatever the index points at.
