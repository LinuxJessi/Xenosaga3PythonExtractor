# Browsing the extracted game

What `browse` writes, which folders are worth opening first, and how long
each part takes. For what each file type *is*, see
[disc-catalog.md](disc-catalog.md); for byte layouts, [FORMATS.md](FORMATS.md).

## Two commands

```sh
# 1. unpack the disc images (both discs give all three chains)
python cli.py dump --iso "Disc 1.iso" --iso "Disc 2.iso" --out out/

# 2. convert the dump into files your computer opens
python cli.py browse --dump out/dump --stage out/browse
```

`dump` writes `out/dump/chain0/` (shared by both discs), `chain1/` (Disc 1)
and `chain2/` (Disc 2) with a `manifest.csv`; `--fs` adds the executables and
IOP modules under `dump/iso/`, and `--match TEXT` takes only the paths that
contain a text. It works on the USA discs, the Japanese discs and the May
2006 prototype. The older 7-Zip pipeline (`prep`, `scan`, `extract`) writes
the same kind of tree and `browse` accepts either.

`browse` needs ffmpeg for sound and movies (bundled in the Windows app,
otherwise on PATH); everything else is Python. `--kinds` picks what to make;
with none, every kind runs.

## What you get

| Kind | Folder under the browse tree | What is in it |
|---|---|---|
| `models` | `models/` | every model as `.glb` (mesh, UVs, textures inside the file, skin and skeleton for the skinned ones, and the same-named motion clips as animations) and `models/models.csv`; 1,609 per USA disc ([MOTION.md](MOTION.md)) |
| `textures_png` | `textures_png/` | the `.xtx` and `.tm2` pictures as PNG: character portraits, the UI sheets, episode logos; each swizzled sheet also gets a `*_index.png` of its raw indices |
| `package_textures` | `textures_png/_packages/<carrier>/` | every texture stored inside another file: character, weapon and map packages, effect libraries, combatant bundles. About 20,900 different PNGs per disc, duplicates recorded in `package_textures.csv` and not written twice |
| `music` | `music/` | the soundtrack: 120 recorded streams as WAV, and `music.csv` with each one's rate, length and loop points ([MUSIC.md](MUSIC.md)) |
| `audio` | `audio/` | every other ADX stream as WAV: scene voice, battle voice, whole-scene mixes, system sounds |
| `soundbanks` | `soundbanks/` | the DTPK banks, one WAV per sample, including the bank inside each combatant bundle |
| `movies` | `movies/` | the Sofdec cutscenes as MP4 (18 on Disc 1, 24 on Disc 2) |
| `images` | `images/` | the JPEG pictures as they are: database illustrations, synopsis pages, wallpapers |
| `carved` | `images/mnu/credit/` | the four boot logos inside `credit.bin` |
| `text` | `text/` | subtitles and message files (with a UTF-8 `*.utf8.txt` reading beside each), menu tables as `*.txd.txt`, and the strings of scene scripts, menu databases and data files as `*.strings.txt` |
| `textures` | `textures/` | the picture files copied unconverted, for other tools |

Text is read the way the build reads it: the USA discs and the prototype
with the USA reading (a lone `é` is one Latin-1 byte), the Japanese discs
with the Japanese one. A byte no reading can show is written as a `⟦XX⟧`
escape, so the text files are an exact account of the bytes. On a Japanese
dump the 140 scenes that exist only there are listed in `text/JP-ONLY.txt`.

## Where to look first

Inside each kind's folder the game's own paths follow, under the `chain0/`,
`chain1/` or `chain2/` folder the file was dumped into (`music/` is flat).

* **`models/chain0/mdl/chr/pc/`**: the party. Open a `.glb` in Blender, or run
  `python cli.py blend` for a `.blend` that opens textured and framed
  ([BLENDER.md](BLENDER.md)).
* **`textures_png/chain0/kao/`**: the 367 dialogue portraits.
* **`textures_png/_packages/`**: sorted by the file each texture came from, so
  a character's folder holds all of that character's texture pages.
* **`music/`**: sort `music.csv` by `seconds` to find the long pieces.
* **`movies/`** with the `evt/us/` folder under **`text/`**: each cutscene's
  subtitles have the cutscene's name (`mov/s000700.mp4`, `evt/us/s000700.txt`).
* **the `cf/us/*.strings.txt` files under `text/`**: scene dialogue, with the
  developers' Japanese notes left in the scripts.

## How long it takes

| Kind | Time |
|---|---|
| `textures_png` | seconds: the 367 portraits in 2 s (measured 2026-11-21, Apple-silicon laptop) |
| `music` | 20 of the 120 streams in 9 s on the same machine, so about a minute for all |
| `package_textures` | several minutes per disc (pure Python, several processes) |
| `models` | not timed for this page; one process per core less one |
| `audio`, `movies` | the long ones: about 3,900 more streams on Disc 1, and every movie is re-encoded |

So a first look is quicker with a short list, for example
`--kinds models,textures_png,music,text`.

## Not converted

The scripts' code, event packages and effect parameters have no
converter; [FORMATS.md](FORMATS.md#17-not-decoded) says what is known about
each. One ADX entry on Disc 1 (`snd\adx\mev\s050200_02_2shi.adx`) is zero
bytes long in the disc's own index and is skipped.
