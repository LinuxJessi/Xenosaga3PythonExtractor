# Xenosaga III Python Extractor

By Jessi Ray Godsibb. Originally bootstrapped with ChatGPT; rebuilt around the
corrected disc model.

Unpack, browse, edit and translate **Xenosaga Episode III — Also sprach
Zarathustra** (PS2) with Python. Point it at your own disc images and you get
the game in forms your computer opens: **every model as a glTF file Blender
opens, textured, rigged and animated with the game's own motion clips**, every
texture as PNG in its real colours, voices and music as WAV, cutscenes as MP4,
and all of the game's text as UTF-8. It reads the USA discs (SLUS_213.89 /
SLUS_214.17), **the Japanese discs (SLPS_256.40 / 256.41)** and the May 2006
press prototype. Then change it: rewrite a line, recolour a character, or
translate into an alphabet the game never had, and the kit writes a patched
copy of the disc and checks every byte it wrote.

<table>
<tr>
<td align="center"><img src="docs/images/front/motion-kosmos-shion-walk.gif" height="260" alt="KOS-MOS and Shion walking: the kit's .glb files, animated with clip 1 of each character's field motion, rendered in Blender"></td>
<td align="center"><img src="docs/images/xs3-ingame-hindi-movie-subtitle.png" height="260" alt="A Hindi subtitle over the opening movie, drawn by the game in PCSX2 from a font the kit rebuilt"></td>
<td align="center"><img src="docs/images/xs3-ingame-arabic-dialogue.png" height="260" alt="Arabic in a scene dialogue box, joined and right to left, PCSX2 capture"></td>
</tr>
<tr>
<td align="center"><sub>KOS-MOS and Shion, exported with their motion<br>and rendered in Blender</sub></td>
<td align="center"><sub>Hindi subtitles over the opening movie<br>(PCSX2, a disc the kit rebuilt)</sub></td>
<td align="center"><sub>Arabic in the dialogue box, right to left<br>(PCSX2, the same kind of disc)</sub></td>
</tr>
</table>

**Bring your own discs:** the kit works from your copy of the game. Every
picture and sound on this page was made by the kit from the retail discs, or
captured exactly as it appeared in PCSX2, running a disc the kit patched.

This is the Episode III sibling of the
[Episode I extractor](https://github.com/LinuxJessi/Xenosaga1PythonExtractor)
and the [Episode II extractor](https://github.com/LinuxJessi/Xenosaga2PythonExtractor),
built the same way, with code borrowed from both where the formats are shared
(each borrowed module says so at the top).

> **Beta — feedback wanted.** Please open issues at
> <https://github.com/LinuxJessi/Xenosaga3PythonExtractor/issues>.
> Reading is tested on all five images. Discs written by the kit have been
> booted in PCSX2 with English edits, Arabic, Hindi, Amharic, Georgian,
> Japanese on the USA disc, a grown file and a character recolour (Disc 1,
> 2026-11-20/21), and translation-editor builds in French, Spanish, Hindi,
> Chinese, Cherokee and Arabic (2026-11-21/27; [docs/UPDATES.md](docs/UPDATES.md) says exactly what). Not
> yet booted: Disc 2 and the disc swap, the Japanese discs, the prototype,
> imported pictures and the battle HUD letters.

**Contents:** [Translation editor](#the-translation-editor-langkit) ·
[Models](#models) · [Animation](#animation) ·
[Translating](#translating-into-another-alphabet) ·
[Changing textures](#changing-textures) · [Textures in their real colours](#textures-in-their-real-colours) ·
[Audio samples](#audio-samples) · [Movies, fonts and menus](#movies-fonts-and-menus) ·
[The window](#the-window) · [What you get](#what-you-get) · [Regions](#regions) ·
[Commands](#commands) · [Quick start](#quick-start--gui-recommended)


## The translation editor (langkit)

Play Episode III in your own language. Open the translation editor, pick
your discs and a language, and type. Press **Build** and you get patched
copies of Disc 1 and Disc 2 that boot like the originals. The editor knows
382 languages and adds the few letters French or German need. It can also
draw whole new alphabets (Arabic, Devanagari, Cherokee, Chinese, Korean…)
into the game's own font. For large alphabets it opens the font's kanji
rows, which hold thousands of letters. Translators can download it on its own.
**[See the langkit tour: docs/LANGKIT.md](docs/LANGKIT.md)**

<table>
<tr>
<td align="center"><img src="docs/images/editor/xs3-ingame-editor-french-settings.jpg" width="400" alt="The Settings menu in French, drawn by the game in PCSX2 from a disc the editor built"></td>
<td align="center"><img src="docs/images/editor/xs3-ingame-editor-spanish-dialogue-2.jpg" width="400" alt="A Spanish line in the first cutscene's dialogue box, PCSX2 capture"></td>
</tr>
<tr>
<td align="center"><sub>French menus, in the game</sub></td>
<td align="center"><sub>A Spanish cutscene, in the game</sub></td>
</tr>
<tr>
<td colspan="2" align="center"><img src="docs/images/editor/editor-translate-french.jpg" width="820" alt="The translation editor: the opening scene being translated into French, with a preview of the original and the translation drawn with the game's own font"></td>
</tr>
<tr>
<td colspan="2" align="center"><sub>The editor: every line of both discs grouped the way you meet them, checked as you type, and previewed in the game's own font</sub></td>
</tr>
<tr>
<td align="center"><img src="docs/images/editor/editor-language-setup-arabic.jpg" width="400" alt="Language setup: Arabic, fonts that have every letter, and a test line drawn right to left"></td>
<td align="center"><img src="docs/images/editor/xs3-ingame-editor-chinese-dialogue.jpg" width="400" alt="Traditional Chinese in the first dialogue box, PCSX2 capture of a disc the editor built"></td>
</tr>
<tr>
<td align="center"><sub>Language setup for a new alphabet</sub></td>
<td align="center"><sub>Traditional Chinese, in the game</sub></td>
</tr>
</table>

Get it as `Xenosaga3-Translation-Editor-<version>-win64.zip` from the releases
page, or build a macOS app with `python build.py --editor`. From a checkout,
double-click `translate.command`, `translate.bat` or `translate.sh`. The
full reference is [docs/TRANSLATION-EDITOR.md](docs/TRANSLATION-EDITOR.md).

## Models

Every model on every disc converts: 1,609 per disc (`.chr` characters, `.wpn`
weapons, `.map` fields and the standalone `.pxy`), 1,589 with geometry and
20 whose mesh slot is empty in the game's own data. Skinned models come out
with their skeleton; maps keep their animated parts (ships, rubble,
crystals). `blend` writes a ready `.blend`: textures packed, Material Preview
on, the view framed. Each picture below is one command and a Blender render,
nothing touched up ([docs/gallery/](docs/gallery/) has the scripts).

### Playable characters

| <img src="docs/images/gallery/kosmos00.jpg" width="140" alt="KOS-MOS"> | <img src="docs/images/gallery/shion00.jpg" width="140" alt="Shion"> | <img src="docs/images/gallery/jr00.jpg" width="140" alt="Jr."> | <img src="docs/images/gallery/momo00.jpg" width="140" alt="MOMO"> | <img src="docs/images/gallery/chaos00.jpg" width="140" alt="chaos"> |
|:-:|:-:|:-:|:-:|:-:|
| KOS-MOS | Shion | Jr. | MOMO | chaos |
| <img src="docs/images/gallery/ziggy00.jpg" width="140" alt="Ziggy"> | <img src="docs/images/gallery/jin00.jpg" width="140" alt="Jin"> | <img src="docs/images/gallery/allen00.jpg" width="140" alt="Allen"> | <img src="docs/images/gallery/canan00.jpg" width="140" alt="Canaan"> | <img src="docs/images/gallery/miyuki00.jpg" width="140" alt="Miyuki"> |
| Ziggy | Jin | Allen | Canaan | Miyuki |

*Field models `mdl\chr\pc\C3<name>00.chr`, USA Disc 1.*

### Notable NPCs

| <img src="docs/images/gallery/virhelm00.jpg" width="140" alt="virhelm00"> | <img src="docs/images/gallery/telos00.jpg" width="140" alt="telos00"> | <img src="docs/images/gallery/mary00.jpg" width="140" alt="mary00"> | <img src="docs/images/gallery/shelley00.jpg" width="140" alt="shelley00"> | <img src="docs/images/gallery/marglis00.jpg" width="140" alt="marglis00"> |
|:-:|:-:|:-:|:-:|:-:|
| `virhelm00` | `telos00` | `mary00` | `shelley00` | `marglis00` |
| <img src="docs/images/gallery/pelegri00.jpg" width="140" alt="pelegri00"> | <img src="docs/images/gallery/nephilim00.jpg" width="140" alt="nephilim00"> | <img src="docs/images/gallery/sergius00.jpg" width="140" alt="sergius00"> | <img src="docs/images/gallery/yuriev00.jpg" width="140" alt="yuriev00"> | <img src="docs/images/gallery/albelt00.jpg" width="140" alt="albelt00"> |
| `pelegri00` | `nephilim00` | `sergius00` | `yuriev00` | `albelt00` |

*`mdl\chr\npc`, captioned with the disc's own file names.*

### E.S.

| <img src="docs/images/gallery/M3asher01.jpg" width="180" alt="M3asher01"> | <img src="docs/images/gallery/M3zebulun01.jpg" width="180" alt="M3zebulun01"> | <img src="docs/images/gallery/M3reuben01.jpg" width="180" alt="M3reuben01"> |
|:-:|:-:|:-:|
| `M3asher01` | `M3zebulun01` | `M3reuben01` |

### Environments

| | |
|---|---|
| <img src="docs/images/gallery/E3_CIT01.jpg" width="440" alt="E3_CIT01"><br>`E3_CIT01` | <img src="docs/images/gallery/E3_SYU01.jpg" width="440" alt="E3_SYU01"><br>`E3_SYU01` |
| <img src="docs/images/gallery/E3_KYM02.jpg" width="440" alt="E3_KYM02"><br>`E3_KYM02` | <img src="docs/images/gallery/E3_ELS05.jpg" width="440" alt="E3_ELS05"><br>`E3_ELS05` |
| <img src="docs/images/gallery/E3_KYO06.jpg" width="440" alt="E3_KYO06"><br>`E3_KYO06` | <img src="docs/images/gallery/E3_HOS01.jpg" width="440" alt="E3_HOS01"><br>`E3_HOS01` |

Maps are shown from a raised three-quarter view with their sky shells hidden
and back faces culled, so the outer walls do not hide the rooms.

```sh
python cli.py browse --out out/ --kinds models        # all of them, with their motion
python cli.py model --iso "Disc 1.iso" --path 'mdl\chr\pc\C3kosmos00.chr' --out kosmos.glb
python cli.py blend --glb kosmos.glb --render kosmos.png
```

More in [docs/MODELS.md](docs/MODELS.md) and [docs/BLENDER.md](docs/BLENDER.md).

## Animation

<img src="docs/images/front/motion-kosmos-battle-attack.gif" width="360" align="right" alt="KOS-MOS playing battle clip 21: a leap, a crouching slash, a lunge and the recovery">

The motion files are decoded. Every body clip on every disc (5,039 per disc:
XAC 1.4, 1.6 and 1.7, plus the FAC face clips) becomes a glTF animation on
the model's armature, read the way the executable reads it, at 30 keys per
second. Field clips live in `pac\cf\*.sme`, battle clips in `pac\bat\*.sme`,
and `model` attaches a character's same-named clips by default.

```sh
python cli.py model --iso "Disc 1.iso" --path 'mdl\chr\pc\C3kosmos00.chr' \
       --out kosmos.glb --motion 'pac\bat\C3kosmos00.sme#0,21'
python cli.py motion --iso "Disc 1.iso" --sweep     # decode every clip on the disc
```

On the right, KOS-MOS plays battle clip 21 (`pac/bat/C3kosmos00#21`): a leap,
a crouching slash, a lunge and the recovery. At the top of the page, KOS-MOS
and Shion play field clip 1, a walk-like cycle that loops exactly. Below,
KOS-MOS turns once while playing battle clip 0.

<img src="docs/images/front/kosmos-turntable.gif" height="300" alt="KOS-MOS turning once while playing battle clip 0, a stance-like loop">

The kit reads its own files back (every sampled joint within 2.4e-6 of the
engine formula), the glTF validator reports no problems, and Blender imports
every action at its clip's frame range. The game's own names for the clips
are not on the disc, so "walk-like", "attack" and "stance" describe what the
renders look like. None of this has been compared with the running game yet,
and hair and coats do not swing, because the game simulates them and the kit
does not. More in [docs/MOTION.md](docs/MOTION.md).

<br clear="right">

## Translating into another alphabet

The kit exports every line the game shows (scenes, menus, the database,
battle messages, movie and event subtitles) as one UTF-8 tree, and imports an
edited tree into copies of both discs. `lang` goes further: it draws a new
alphabet from a TrueType font into the game's free font cells, shapes and
wraps the text (right to left where needed), and encodes it. Several scripts
can share one disc with `--extend`. These are all **PCSX2 captures** from
disc copies the kit wrote:

| | |
|---|---|
| ![Hindi (Devanagari, conjuncts and vowel signs) in a scene dialogue box](docs/images/xs3-ingame-hindi-dialogue.png) | ![Arabic: the "story so far" screen, right to left](docs/images/xs3-ingame-arabic-synopsis.png) |
| *Hindi in a scene's dialogue box* | *Arabic on the "story so far" screen* |
| ![Amharic: the save screen's title, the overwrite prompt and Yes/No](docs/images/xs3-ingame-amharic-save.png) | ![Georgian: the "story so far" screen](docs/images/xs3-ingame-georgian-synopsis.png) |
| *Amharic on the save screen* | *Georgian on the "story so far" screen* |
| ![Japanese on the USA disc with --unlock jp: the field menu's first entry and help line](docs/images/xs3-ingame-japanese-unlock-menu.png) | ![A location caption in Hindi over the real-time opening](docs/images/xs3-ingame-hindi-event-subtitle.png) |
| *Japanese on the USA disc (`--unlock jp`, kana and kanji from the Japanese font)* | *A Hindi location caption over the real-time opening* |

Hindi, Amharic and Georgian were built onto one disc (three `lang scan`
passes chained with `--extend`, 87 new glyphs) and boot together. Arabic and
Hebrew are right to left, with the bidi algorithm checked against ICU.
Guides: [docs/TRANSLATING.md](docs/TRANSLATING.md) ·
[docs/SCRIPTS.md](docs/SCRIPTS.md) · [docs/FONT.md](docs/FONT.md).

**The translation editor** (new 2026-11-21, ported from the Episode I kit)
does all of this from one page. **Translators can download it on its own**
(`Xenosaga3-Translation-Editor-<version>-win64.zip` on the releases page, or
`python build.py --editor` for a macOS app): double-click
`Xenosaga-III-Translation-Editor` and the editor opens, without the
extractor kit. From a checkout: `translate.command` / `translate.bat` /
`translate.sh`, or the **Translation editor** button of the app. It lists
every string of both discs by type and by speaker, checks each translation
against the disc's fonts as you type, and builds patched copies of Disc 1
and Disc 2 with one button, in any of 382 languages. Scene-script strings
are sorted by what the script's code does with them, so the 73,601 debug
prints of the USA discs are out of the way and a townsperson's keyword stays
equal to the word in its line. French works with nothing to set up: the
three letters the USA font lacks (`œ Œ Ÿ`) are added from a font that ships
with the kit. Dialogue has a width guide read from the game's window code
(the game never wraps; 469 px keeps a window on the 512 px screen), and
*Wrap to fit* breaks lines to it. Its builds have been played in PCSX2 in
French, Spanish, Korean, Hindi, Chinese, Cherokee and Arabic
([docs/LANGKIT.md](docs/LANGKIT.md)).
[docs/TRANSLATION-EDITOR.md](docs/TRANSLATION-EDITOR.md).

The Japanese release is read too: its own codec, font rules and `Message.Dat`
layout, the 140 scenes that exist only in Japanese listed, and `align-export`
lines the Japanese script up with the English one (TSV, JSON or a
dual-language SRT).

## Changing textures

<img src="docs/images/xs3-ingame-shion-recolor-zoom.jpg" width="360" align="right" alt="Shion in the Vector S-Line hall, retail (left) and with her hair recoloured by chr-iso-sweep (right), PCSX2 captures">

`chr-decode` turns every texture in a model into PNG; `chr-palettes` and
`chr-import-palettes` round-trip its colours through an editable swatch;
`chr-iso-sweep` recolours every copy of a character on a disc. On the right,
Shion in the Vector S-Line hall, retail and after
`chr-iso-sweep --match shion --mode warm`, both PCSX2 captures from the same
memory-card save.

Below, KOS-MOS from the retail disc and from a copy swept with
`--mode blue`, rendered in Blender after re-extracting the copy. The blue
filter changes her blue armour trim as well as her hair, so check the result
before you sweep. Guide: [docs/MODDING-CHARACTERS.md](docs/MODDING-CHARACTERS.md).

<br clear="right">

![KOS-MOS from the retail disc (left) and from the recoloured copy (right), rendered in Blender](docs/images/xs3-kosmos-recolor-blender.png)

## Textures in their real colours

![UI sheets before and after the XTX fix: the top half is the old sepia ramp read 16 pixels off, the bottom half the corrected decode with per-picture palettes](docs/screenshots/xtx-palettes-2026-11-20.jpg)

*Top: what every earlier version produced. Bottom: pixels read from the
right offset and each icon, thumbnail and portrait given its own palette.*

![Window sheets, titleobj and the minigame sheet before and after binding palettes from the game's own draw code](docs/screenshots/ui-palettes-engine-2026-11-20.jpg)

*Then the game's own sprite tables and draw calls (SLUS, OV01, OV04) pick
each sprite's palette: HUD words, gauges, the title menu and the minigame
sheet now draw the way the game draws them.*

| | |
|---|---|
| ![Field map textures](docs/screenshots/improve-field-map.png) | ![Effect textures](docs/screenshots/improve-effects.png) |
| *LZSS-packed field maps decoded* | *Effect-file textures* |

## Audio samples

Short previews decoded by the kit (25-second BGM excerpts; voice lines cut
from the movies' own audio at the timing in each movie's subtitle file, so
music and effects are mixed in). Click to play or download.

| | Source | Sample |
|---|---|---|
| Voice | movie `s030100`: "Do it anytime, KOS-MOS!" / "Acknowledged." | [voice_s030100_do_it_anytime.mp3](docs/samples/voice_s030100_do_it_anytime.mp3) |
| Voice | movie `s031300`: "I am order!" / "Not you, KOS-MOS!" | [voice_s031300_i_am_order.mp3](docs/samples/voice_s031300_i_am_order.mp3) |
| Voice | movie `s083110` (Disc 2): "Fear drives evolution." | [voice_s083110_fear_drives_evolution.mp3](docs/samples/voice_s083110_fear_drives_evolution.mp3) |
| Voice | movie `s093500` (Disc 2): "When Mary fulfills her duty, Zarathustra shall speak!" | [voice_s093500_zarathustra_shall_speak.mp3](docs/samples/voice_s093500_zarathustra_shall_speak.mp3) |
| Voice | movie `s094820` (Disc 2): "I am not Mary. I am... KOS-MOS!" | [voice_s094820_i_am_not_mary.mp3](docs/samples/voice_s094820_i_am_not_mary.mp3) |
| BGM | `snd/adx/M01.adx` (81 s) | [bgm_m01.mp3](docs/samples/bgm_m01.mp3) |
| BGM | `snd/adx/M11.adx` (82 s) | [bgm_m11.mp3](docs/samples/bgm_m11.mp3) |
| BGM | `snd/adx/M56.adx` (132 s) | [bgm_m56.mp3](docs/samples/bgm_m56.mp3) |
| BGM | `snd/adx/M78.adx` (94 s) | [bgm_m78.mp3](docs/samples/bgm_m78.mp3) |
| BGM | `snd/adx/A01.adx` (131 s) | [bgm_a01.mp3](docs/samples/bgm_a01.mp3) |
| BGM | `snd/adx/B01.adx` (90 s) | [bgm_b01.mp3](docs/samples/bgm_b01.mp3) |
| Battle callout | `snd/adx/bat_voice/allen_bst1.adx` | [voice_bat_voice_allen_bst1.mp3](docs/samples/voice_bat_voice_allen_bst1.mp3) |
| Event voice | `snd/adx/mev/bat_eld33.adx` | [voice_mev_bat_eld33.mp3](docs/samples/voice_mev_bat_eld33.mp3) |
| System jingle | `snd/adx/sys/system01.adx` | [voice_sys_system01.mp3](docs/samples/voice_sys_system01.mp3) |
| Field SE | `snd/dat/CIT.dap` cue 3 | [sfx_CIT_c03.mp3](docs/samples/sfx_CIT_c03.mp3) |
| Battle SE | bank inside `pac/cf/C3kosmos00.sme`, cue 0 | [sfx_kosmos_bank_c00.mp3](docs/samples/sfx_kosmos_bank_c00.mp3) |

The full set (10 BGM streams, 289 battle callouts, 77 movie voice lines,
607 sound banks, every movie's audio) comes out of
`browse --kinds audio,soundbanks,movies` on your own disc.

## Movies, fonts and menus

| | |
|---|---|
| <img src="docs/images/tour/movie_s000300.jpg" width="400" alt="A frame of the opening movie s000300: young Shion in a cockpit"> | <img src="docs/images/xs3-ingame-field-retail.png" width="400" alt="Vector S-Line Division gate hall, retail, PCSX2 capture"> |
| A frame of `s000300.sfd`, the opening (`browse --kinds movies`) | The Vector S-Line hall in the retail game (PCSX2), for comparison |
| <img src="docs/images/tour/ui_sheets.jpg" width="400" alt="A menu background, item icons and the controller sheet"> | <img src="docs/images/tour/ui_portraits.jpg" width="400" alt="Party portraits from the battle window sheet window0.xtx"> |
| UI sheets: a menu background (`mnu\pse\haikei`), item icons (`itemcap.xtx`), the controller (`ctrl.xtx`) | Party portraits from the window sheet `mnu\us\window0.xtx` |
| <img src="docs/images/tour/font_sheet.png" width="300" alt="font0 glyph sheet 0"> | <img src="docs/images/tour/synopsis_pictures.jpg" width="400" alt="Four of the pictures behind the story-so-far screen"> |
| Sheet 0 of `font0` (`font-extract`) | Four of the 71 pictures behind the "story so far" screen (`mnu\syno\*.jpg`) |
| <img src="docs/images/tour/textures_kosmos.png" width="400" alt="KOS-MOS's texture pages from C3kosmos00.chr"> | <img src="docs/screenshots/extracted-mosaic.png" width="400" alt="Extracted memory-card save illustrations"> |
| KOS-MOS's texture pages (`chr-decode`) | Some of the 348 memory-card save scenes (`--kinds images`) |

## The window

![The kit's window: a card per command, grouped by section, the environment panel on the right](docs/images/tour/gui-window.png)

`python gui.py` (or a launcher) opens a local page with one card per
command, grouped by section, built from the command line's own parser. It
finds your discs and tells USA, Japan and prototype images apart. The discs
in this screenshot are empty stand-ins with the usual file names.

## What you get

| | |
|---|---|
| Models | all 1,609 models per disc (`.chr` / `.wpn` / `.map` packages and the standalone `.pxy`) as `.glb`: mesh, UVs, textures inside the file, skin weights and a skeleton for the skinned ones (1,014 on each Japanese disc). `blend` turns one into a `.blend` that opens textured, framed and without "bone balls". [docs/BLENDER.md](docs/BLENDER.md), [docs/MODELS.md](docs/MODELS.md) |
| Japanese discs | detected by the boot executable's hash; 46 executable addresses checked against the code at run time; every Japanese text container reads and rebuilds byte-identically; 140 scenes that exist only in Japanese are listed; `align-export` puts the Japanese and English script side by side (TSV, JSON, dual SRT) |
| Text | the scene scripts (`.sb`), menu tables (`.txd`), menu databases (`mnu\xx\*.bin`), `Message.Dat`, `batdat.bin`, movie/event subtitles and `.mes` files as one UTF-8 tree. `text-import` checks an edited tree (codec, font ink, sizes) and writes it into copies of Disc 1 + Disc 2. [docs/TRANSLATING.md](docs/TRANSLATING.md) |
| Dialogue and scene scripts | `dialogue` writes every line the scene and battle scripts show, in the order their code shows it, with speakers, choices, branches and each event line's own voice stream (`--voice`: 4,699 WAV on the USA discs); the subtitles of movies and event scenes appear where the script starts them. `sb` disassembles a script (a 99-opcode byte machine read from the executable) and `natives` lists the 327 engine functions the scripts call. [docs/DIALOGUE.md](docs/DIALOGUE.md) |
| New scripts | `lang scan / encode / import / preview` draws Arabic, Hebrew, Devanagari or any HarfBuzz-shaped script from a TrueType font into the game's free font cells (123 proportional + 51 wide on USA Disc 1) and encodes the text shaped, wrapped and right-to-left where needed. Japanese on the USA build, with kana and kanji donated from the Japanese font. [docs/SCRIPTS.md](docs/SCRIPTS.md) |
| Fonts | `font0` / `font1` sheets, metrics and the 8x8 system font out and back in byte-exactly; the rules (pair gate, proportional range) read from each disc's own executable; `font-donor` copies cells between builds; `glyphs-*` finds free slots and renders TTF glyphs. [docs/FONT.md](docs/FONT.md) |
| Battle HUD letters | `statfont-export / -import`: the HUD's bitmap letters in the window sheets plus their byte and width tables in the executable |
| Pictures | `image-export / -import`: 1,131 localized pictures on USA Disc 1 (JPEG illustrations, PNG, UI `.xtx` sheets, logo `.tm2`, effect `txy`) to PNG and back at the same size or within the file's sector allocation |
| Writing back | `patch` writes any set of files into **copies** of one disc or a Disc 1 + Disc 2 pair: in place when a file fits, appended at the image end with `--grow`, with a sector budget, refusals for mixed builds, and a full read-back check. [docs/REPACK.md](docs/REPACK.md) |
| Music | the soundtrack is 120 recorded ADX streams (3.31 hours, 114 with loop points); `browse --kinds music` writes them as WAV with a table of rates, lengths and loop points, and `music-list` prints that table straight from a disc. Episode III has no sequenced music, so there is no MIDI to export. [docs/MUSIC.md](docs/MUSIC.md) |
| Browse tree | `browse` builds a folder of things you can open: textures and package textures as PNG, audio and sound banks as WAV, movies as MP4, text as UTF-8 (Japanese read with the Japanese codec), models as `.glb` |
| Code | the executable and overlays disassembled with string cross-references (`disasm`) |

## Regions

The kit reads the build from the disc's boot executable (`region.py`; `python
cli.py region --iso X.iso -v` shows the profile and checks every address):

| | USA retail | May 2006 prototype | Japan retail |
|---|---|---|---|
| Boot executable | SLUS_213.89 (Disc 1), SLUS_214.17 (Disc 2), same code | SLUS_213.89, different code (sha256 1c3d028a…) | SLPS_256.40 (Disc 1), SLPS_256.41 (Disc 2), same code |
| Language folder | `\us\` (`cf\us`, `mnu\us`, `mov\us`, `jpg\us` …) | `\us\` | `\jp\`; `jpg\`, `ef\map\`, `ef\esp\` and `mnu\pse\` files sit at the folder root (`resolve` handles both) |
| Text codec | the executable's whitelist of two-byte pairs; lone `é`, `ö` … are Latin-1 cells | same as USA | EUC-JP: any byte from 0xA0 pairs with the next; no half-width kana, no Latin-1 |
| Proportional cells | 0x180 (Latin and symbols) | 0x180 | 0xC0 (kana are fixed width) |
| `Message.Dat` | 933 messages, u32 offsets, strings from 0x2800 | same layout | 871 messages, u16 offsets, strings from 0x800 |
| Subtitles | `mono` allowed | as USA | no `mono`; `mov\jp\bat` files kept within 1 KiB (the developers' own note) |
| Scenes | 715 `.sb` per disc | 886 text objects, as many as USA Disc 1 | 856 (140 of them JP-only, load status unknown) |
| Write tests on copies | `text-import`, `lang import`, `patch` (in place and grown, pair and single); **booted in PCSX2**: same-size, Arabic, `--unlock jp`, grown (Disc 1) | `patch` same size | `text-import`, `patch` (in place and grown); not booted |

Give Disc 1 and Disc 2 of the same build. The writers refuse a mixed pair
(USA + Japan, USA + prototype) and an unknown executable.

## Commands

`python cli.py <command> --help` gives the options; the GUI (`python gui.py`,
or a launcher) has a card for every command, grouped by section.

| Section | Commands |
|---|---|
| Disc | `region`, `resolve`, `list`, `dump`, `iso-ls`, `toc-check` |
| Models | `model`, `models`, `blend`, `glb-info` |
| Dialogue and scripts | `dialogue` (`--voice`), `sb`, `natives` (`--table`) |
| Text | `text-export`, `text-import`, `text-roundtrip`, `align-export`; one file at a time: `text-decode`, `sb-strings`, `txd-strings`, `nj-strings`, `subtitle-text`, `msgdat-strings`, `batdat-strings` |
| Translation editor | `gui --editor` (the page), `tx-build`, `tx-catalog`, `tx-selftest`, `tx-cache` |
| New scripts and fonts | `lang scan` / `encode` / `import` / `preview`, `font-extract`, `font-rebuild`, `font-measure`, `font-donor`, `glyphs-slots`, `glyphs-coverage`, `glyphs-render`, `glyphs-apply`, `glyphs-unlock`, `statfont-export`, `statfont-import` |
| Pictures | `image-export`, `image-import`, `xtx-export`, `xtx-encode`, `chr-decode`, `chr-palettes`, `chr-import-palettes`, `chr-import-entry`, `chr-recolor`, `xc-unpack` |
| Writing to discs | `patch` (copies, pairs, `--grow`); older in-place single-ISO tools: `repack-info`, `repack-extract`, `repack-patch`, `repack-tree`, `chr-iso-extract`, `chr-iso-patch`, `chr-iso-sweep` |
| Browse, music and code | `browse`, `music-list`, `code-extract`, `disasm` |
| 7-Zip pipeline (USA discs) | `prep`, `lba-from-iso`, `container-map`, `map-regions`, `toc`, `scan`, `extract`, `verify`, `doctor` |
| Kit | `self-test`, `gui`; `python build.py` builds the app bundle and runs its self-tests |

`python cli.py self-test` runs every module's self-test. Set `XS3_D1`,
`XS3_D2`, `XS3_PROTO`, `XS3_JP1` and `XS3_JP2` to your ISO paths to include
the disc checks.

## What's new — 2026-11-26 (lessons from a sibling kit)

Two fixes taken from Anzinono's
[xenosaga3-translation-kit](https://github.com/Anzinono/xenosaga3-translation-kit),
a German translation kit for the USA discs (see [Credits](#credits)):

* **UDF stays in step when a disc grows.** `patch` used to fix only the
  ISO9660 side of these ISO9660 + UDF discs. Now the UDF end anchor, the
  partition size, the integrity table and the file entry of every moved
  ISO9660 file are rewritten too (`udf.py`), so tools that mount or burn
  through UDF see the same files. A grown image is one sector longer for the
  moved anchor. Checked on all four known images and with pycdlib's UDF
  reader ([docs/REPACK.md](docs/REPACK.md)).
* **Database ids are no longer rewritten.** 14 values in `DBC2.bin` and
  `njDataText.bin` that happen to land inside a string are numbers (DBF fields
  7/8 hold ids), not pointers. The kit used to move them along with their string,
  which changed the ids after any earlier edit, and it refused to let those
  strings change. Now the numbers stay as they are and the strings can be
  edited ([docs/FORMATS.md](docs/FORMATS.md), section nj).

## What's new — 2026-11-21 (the scene scripts as programs)

The scripts' code is read, not only their text
([docs/UPDATES.md](docs/UPDATES.md), [docs/DIALOGUE.md](docs/DIALOGUE.md)):

* **`dialogue`**: every line in play order, one transcript per scene, read
  from what the code does. A string is a line when it reaches a function that
  draws text; the developers' debug prints (most of every text pool) are left
  out.
* **A voice clip per line.** Each event line names its own stream
  (`snd\adx\mev\<id>.adx`); `dialogue --voice` writes them as WAV.
* **`sb`** and **`natives`**: a disassembler for the 99-opcode script machine
  and the list of the 327 functions it calls, both read from the executable
  and checked on all five disc images (every script disassembles end to end).

## What's new — 2026-11-21 (parity pass)

A parity pass against the Xenosaga I and II kits
([docs/UPDATES.md](docs/UPDATES.md) has the details and what was checked):

* **The soundtrack on its own.** `browse --kinds music` and `music-list`: the
  120 music streams with their loop points ([docs/MUSIC.md](docs/MUSIC.md)).
* **`build.py`**, as in the other two kits: one command builds the app
  bundle (now also a macOS `.app`) and runs the bundle's own self-tests.
  Running it found that the bundled `xeno-cli` refused every command; fixed.
* **The same set of documents as the other kits:**
  [BROWSING](docs/BROWSING.md), [MODDING](docs/MODDING.md),
  [MUSIC](docs/MUSIC.md), [FORMATS](docs/FORMATS.md),
  [CODEBASE](docs/CODEBASE.md), [FINDS](docs/FINDS.md) and
  [HISTORY](docs/HISTORY.md).

## What's new — 2026-11-20/21

Seven passes brought the kit level with the Xenosaga I and II kits. Full
change log: [docs/UPDATES.md](docs/UPDATES.md); every document:
[docs/README.md](docs/README.md).

* **Japanese discs.** The Japan retail pair is read like the USA discs: its
  own language folder, its own text codec (taken from the executable's pair
  gate), its own font rules, and `Message.Dat`'s shorter layout.
  `align-export` lines up the Japanese and English script.
* **Models in Blender in one step.** `blend` writes a `.blend` that opens
  textured and framed, with the armature as sticks instead of the importer's
  bone spheres.
* **Text goes back in.** `text-import` writes an edited tree into copies of
  both discs at once, refusing anything the disc's codec or font cannot show.
  `Message.Dat` and `batdat.bin` are now part of the tree.
* **New scripts.** `lang` ports the Xenosaga I pipeline: HarfBuzz shaping,
  right-to-left, wrapping, `--extend` for a second script, and Japanese on the
  USA build.
* **Pictures and HUD letters** export and import (`image-*`, `xtx-*`,
  `statfont-*`).
* **XTX pixels start at 0x50** (after a 32-byte GS upload packet), not 0x30:
  every decoded `.xtx` was 8 words off. With the fix, the swizzled UI sheets'
  item icons, location thumbnails and portraits come out in their real
  colours instead of sepia/grey. Re-run `browse --kinds textures_png`, and
  re-export before importing anything made from old `*_index.png` files.
* **A new write layer.** `patch` writes into copies, keeps the two discs'
  shared index identical, and checks every file afterwards. `repack-*` and
  `chr-iso-*` now find files through the disc's own index on any build.
* **A new GUI**, built from the command line itself, grouped by section, that
  finds your discs and tells USA, Japan and prototype images apart.
* **Motion.** All 5,039 clips per disc decode (`xap.py`, ported from the
  Episode II kit with XS3's new clip versions) and attach to the models.
* **Every model converts.** Maps carry a second model at header +0xD0 (their
  animated parts); the three "unexplained" maps were that case.
* **Palettes from the game code.** The executable's sprite tables and draw
  calls bind the UI sheets' palettes (`engine_palettes.py`).
* **Booted in PCSX2.** English, Arabic, Hindi, Amharic, Georgian, Japanese on
  the USA disc, a grown file and a recolour, all on Disc 1 copies.

Still open: nothing booted from Disc 2, the Japanese discs or the prototype;
no battle screen captured yet; the loader buffer sizes for text objects are
unknown (so growth needs `--grow`); the `batdat.bin` string fields are
structural, not traced in code; motion is not yet compared with the running
game and the map `PAM ` block is undecoded; the `.xep` codec is not decoded;
about a fifth of the art on the window0-2 sheets still has a ranked, not
engine-bound, palette.

### Earlier: the 2026-09-24 improvement run

Package textures (~20,900 PNGs inside `.chr`/`.wpn`/`.map` and effect
files), the LZSS field maps (`xcpack.py`), 4-bit textures, the text kind and
the `.sme` sound banks. Details and before/after panels in
[docs/UPDATES.md](docs/UPDATES.md).

*1,300+ event illustrations, 348 memory-card save scenes, every
character face texture, every cutscene as MP4, every voiced line as WAV.
Real extraction; nothing reconstructed or upscaled.*

> **For curious testers:** [`docs/disc-catalog.md`](docs/disc-catalog.md)
> is the full data dictionary — every file extension across both discs,
> what it actually is, where the engine reads it from, plus a "Fun finds"
> section at the bottom.

## Dialogue sample

From `cf/us/2940.sb`, a Miltia field scene, exactly as the `text` kind
writes it (`<lN>` = portrait/line slot, `<wNN>` = wait in frames):

```
[Barth]<l2>Realians of the same model as me\nare displaying strange behaviors.<w45>
[Barth]<l3>I can't exactly explain it, but they\nseem to take actions completely\nunrelated to their own will.<w45>
[Corel]<l2>And?<w15> Are you showing\nsigns of that?<w45>
[Barth]<l2>Well,<w15> I start to hear\nsomeone singing.<w45>
[Corel]<l2>Singing?<w15> That's odd.<w15>\nI wonder what the cause is.<w45>
[Owusu]<l3>There's this girl who's always\ngrowing flowers at that hospital\nup ahead!<w45>
[Emil]<l2>She's weird.<w15> She spends\nall her time at a hospital!<w45>
```

`dialogue` writes a scene as a play script, in the order its code shows the
lines. The opening (`cf/8000`), each line with its voice clip:

```
== evt01 ==
  Blue Testament: Looks like things are going smoothly.  [#0114]  <s000200_01vir>
  Blue Testament: Tch. You're as friendly as ever.  [#0116]  <s000200_02vir>
  Red Testament: We must correct the errors.  [#0124]  <s000200_04_2kev>
```

The same file carries the writers' Japanese scene index
(`≪レンヌ・ル・シャトー、KOS-MOSと墓標≫` — "Rennes-le-Château, KOS-MOS and
the grave marker"), and `mnu/us/DBC.bin` yields the encyclopedia:

```
Aizen Magus
An elderly resident of\nthe Dabrye Mine.
An elderly resident of the <Dabrye Mine> on Miltia. Originally\na labor
immigrant from another star system after Miltia\nbecame a republic …
```

## Quick start — GUI (recommended)

Most people will want this path. **It opens in your browser; nothing is
exposed to the internet — the server only listens on `127.0.0.1`.**

### Windows — pre-built (easiest, available since v0.2.3)

Skip the entire "install Python, install 7-Zip, install ffmpeg" dance.
The Windows release zip contains everything — just download, extract,
double-click.

1. Download
   **[the latest Windows release zip](https://github.com/LinuxJessi/Xenosaga3PythonExtractor/releases/latest)**
   (look for `Xenosaga3-Extractor-X.Y.Z-win64.zip` under *Assets*, ~95 MB).
2. Right-click → **Extract All…** anywhere you have space. **Extracting
   matters** — double-clicking `gui.exe` from inside the zip preview will
   *not* work.
3. Double-click **`gui.exe`**. The first time, Windows will warn
   "Windows protected your PC." Click **More info → Run anyway**. See
   *["Why Windows warns the first time"](#why-windows-warns-the-first-time)*
   below.

That's it. Your browser opens to the GUI; the Environment panel should
show the five required Python packages (numpy, Pillow, capstone, fonttools,
uharfbuzz) and ffmpeg / 7-Zip in green (all bundled). The Python and
`pip install` steps in the manual section below are **not** needed for the
pre-built.

#### Why Windows warns the first time

The download isn't (yet) signed with a Microsoft-trusted code-signing
certificate, so SmartScreen flags it as "unrecognized." This is a
reputation system, not a malware verdict — the file is exactly the one
GitHub Actions built from the source in this repo (build log:
`https://github.com/LinuxJessi/Xenosaga3PythonExtractor/actions`).

What we do to keep the warning small:

* **No installer** — just a zip you extract. Installers trigger heavier
  SmartScreen heuristics than plain zips.
* **No UPX packing** of the executables (UPX is the single strongest
  "this is malware" signal in most AV engines' weights).
* **Full Windows version-info resource** on both `.exe` files, so
  Properties → Details shows a real company name and description.
* **One-folder layout** — no unpacking to `%TEMP%` at startup, which is
  the most-flagged behaviour of one-file bundles.
* **Build is fully reproducible from GitHub Actions** — feel free to
  diff your downloaded zip against the workflow's published artefact.

What's still on the roadmap: applying for the free
[SignPath.io OSS programme](https://signpath.org/) or paying for
[Azure Trusted Signing](https://learn.microsoft.com/en-us/azure/trusted-signing/)
(~$10/month). Either eliminates the warning entirely.

If you'd rather not click through, use the manual-install path below or
run from source.

### Windows — manual install

1. Install **Python 3.9 or newer** from <https://www.python.org/downloads/>.
   **Tick "Add Python to PATH"** on the first installer screen — this is the
   single most common cause of "it won't launch" reports.
2. **Double-click `launch.bat`.** The first run checks for the kit's five
   required Python packages (numpy, Pillow, capstone, fonttools, uharfbuzz);
   if your Python lacks any of them it makes a private environment in
   `.venv\` beside the launcher and installs `requirements.txt` there.
   Later runs reuse `.venv\`. Then it prints the URL it bound to and opens
   your browser. Leave the console window open while you use the GUI —
   closing it shuts the server down.
3. *(For `browse` audio and movies)* install **ffmpeg**. Easiest:
   <https://www.gyan.dev/ffmpeg/builds/> → "release essentials" zip, unpacked
   so the binary lives at `C:\ffmpeg\bin\ffmpeg.exe`, or `winget install
   Gyan.FFmpeg` (both auto-detected).
4. *(For the older `prep` pipeline only)* install **7-Zip** from
   <https://www.7-zip.org/>. The direct-from-ISO commands (`list`, `dump`,
   `model`, `text-export`, ...) do not need it.
5. *(Optional, for models)* install **Blender** from <https://www.blender.org/>;
   the GUI finds it in its default location. The `.glb` files open in any
   glTF viewer without it (see `docs/BLENDER.md`).

### macOS

1. Install **Python 3** if you don't have it (`brew install python` or from
   python.org).
2. Optionally `brew install ffmpeg` (browse audio/movies), `brew install
   p7zip` (`prep` only) and Blender (`brew install --cask blender`).
3. **First-time setup**: open Terminal in the extractor folder and run
   `chmod +x launch.command` (one-time — Finder won't let you double-click
   it otherwise).
4. **Double-click `launch.command`.** Like `launch.bat`, the first run
   installs the five required packages into `.venv/` if the Python it finds
   lacks any of them, then Terminal prints the URL and your browser opens.

### Linux

1. `sudo apt install python3 python3-venv ffmpeg p7zip-full` (or your
   distro's equivalent; `python3-venv` lets the launcher create `.venv/`).
2. **First-time setup**: `chmod +x launch.sh` in a terminal.
3. **Double-click `launch.sh`** in your file manager (set to "Run" if it
   asks), or run `./launch.sh` in a terminal. The first run installs the
   requirements into `.venv/` when needed, as on the other systems.

### What you see in the GUI

A right-side **Environment** panel shows Python, the CLI, the five required
packages with their versions (red = missing: run the launcher again, or
`python -m pip install -r requirements.txt`), ffmpeg, Blender and 7-Zip, and
every Episode III disc it found near the kit, grouped by build: the USA pair,
the Japanese pair and the May 2006 prototype (each confirmed from the image's
own serial and executable hash, see `region.py`). When more than one build is
found, **Fill disc fields with** picks which one pre-fills the disc fields.
Commands that rewrite an image in place never get a detected original
pre-filled — give them a copy.

The main area is one **card per CLI command**, grouped into sections: Disc,
Browse, Models, Text & translation, Fonts & scripts, Modding, Diagnostics
(and Other for anything new the map does not name). The cards are generated
from `cli.py`'s own argument parser when the GUI starts, so every option of
every command is there, and a command added to the kit later appears with no
GUI change. Click a card header to expand it. Every card has a **"Show
command"** button that previews the exact `cli.py` command line without
running it; output of a real run streams live into the Output panel.

A good first run: **region** (which build each disc is), then **dump** or
**list**, then **browse** / **models** / **text-export**.

### Stopping the GUI

Close the terminal/console window the launcher opened, or hit Ctrl+C in it.

## What the disc actually looks like

The Lybac toolchain treats each disc as a small set of **catalog** files plus
ordered **bigfile** chains:

| Disc | Catalog (small) | Bigfile chain | LBA file |
|------|------------------|---------------------------|--------------|
| 1, 2 | `X3.00` (~110 KB) | `X3.01` + `X3.02`           | `Lba0.txt` |
| 1    | `X3.10` (~52 KB)  | `X3.11` + `X3.12` + `X3.13` | `Lba1.txt` |
| 2    | `X3.20` (~26 KB)  | `X3.21` + `X3.22` + `X3.23` | `Lba2.txt` |

The catalogs are the game's own directory index (sector + size per path,
front-coded names). `x3index.py` reads them directly, so the `Lba*.txt`
tables can be regenerated from any disc with `lba-from-iso`.

The 3.0x chain is **identical on both discs** (system/UI/models). 3.1x lives
on Disc 1 only, 3.2x on Disc 2 only.

Each LBA file is its own byte address space starting at `0`. Offsets and sizes
inside the LBA text are **bytes**, not sectors. Bigfile chains are walked as
one concatenated region — a single LBA row can span two bigfiles where the
file straddles a boundary (only a handful do in practice).

### Why v0.1 corrupted files

The first cut treated **all** X3.* parts as a single flat address space, so
every row from Lba1 and Lba2 was read from the start of the X3.* chain rather
than from its own region. Lba0 rows were already at offset 0 of the chain and
happened to land correctly, which is why "80% looked fine" while everything
under `\evt`, `\mov` and `\snd` came out as garbage.

## Requirements

- **Python** 3.9+ (Windows / macOS / Linux / WSL)
- **Python packages — all required** (`requirements.txt`): numpy, Pillow,
  capstone, fonttools, uharfbuzz. The launchers install them into `.venv/`
  on first run when your Python lacks any of them; from a terminal:

  ```bash
  python -m pip install -r requirements.txt
  ```

  No command falls back to a worse path when one is missing:
  `python cli.py self-test` fails, and `cli.py` refuses to run other commands
  while a module cannot be imported.
- **ffmpeg** — `browse` audio (`.adx`) and movies (`.sfd`). Static builds
  work fine; pass `--ffmpeg /path/to/ffmpeg` if it isn't on `PATH`.
- **7-Zip** — only the older `prep` / `code-extract` pipeline. On Windows
  install 7-Zip; on macOS/Linux `p7zip`. Pass `--sevenzip /path/to/7z` if it
  isn't on `PATH`.
- **Blender** (optional) — for opening the `.glb` models; see
  `docs/BLENDER.md`.

## GUI (double-click to launch)

| OS | File | Notes |
|---|---|---|
| Windows | `launch.bat` | Uses the `py` launcher or `python` on PATH; creates `.venv\` on first run if needed. |
| macOS | `launch.command` | First run: `chmod +x launch.command`. Opens in Terminal; creates `.venv/` if needed. |
| Linux | `launch.sh` | First run: `chmod +x launch.sh`. Creates `.venv/` if needed. |

The launcher makes sure the requirements are installed, starts a local web
server on a free port and opens your browser. Plain HTTP, bound only to
`127.0.0.1`, and requests from other web sites are refused — nothing reaches
the network.

You can also run it directly (with the requirements installed):

```bash
python gui.py              # opens default browser
python gui.py --no-browser # just print the URL
PORT=8080 python gui.py    # pin the port
python gui.py --self-test  # check the cards, the disc detection and the deps
```

## Workflow (command line)

Per-disc, in a clean directory.

```bash
# 0. Sanity check
python cli.py doctor --work .

# 1. List the ISO and extract the X3.* parts. Writes container_map.json.
python cli.py prep --iso "...Disc 1).iso" --work .  # or pass --sevenzip path

# 2. Assign LBA sources to bigfile chains. Auto works for clean discs;
#    manual gives you explicit control.
python cli.py map-regions --work . \
    --assign "Lba0.txt=X3.01,X3.02" \
    --assign "Lba1.txt=X3.11,X3.12,X3.13" \
    --ignore X3.00 --ignore X3.10

# 3. (Optional) human summary of the LBA tables.
python cli.py toc --work .

# 4. Build the extraction manifest (one row per LBA entry, resolved to a
#    container + local offset). Sniff-magics in the log help spot anomalies.
python cli.py scan --work . --sniff

# 5. Dry-run to see what would be written.
python cli.py extract --work . --out ./dump --dry-run

# 6. Real extract. --hash records SHA-1s under dump/_reports/hashes.sha1.
python cli.py extract --work . --out ./dump --hash

# 7. Spot-check sizes (and optionally re-verify the SHA-1s).
python cli.py verify --work . --out ./dump --limit 500 --hash

# 8. (Optional) extract non-X3 files from the ISO (SLUS, OVL, IRX,
#    SYSTEM.CNF). Mirrors the ISO's filesystem under --out.
python cli.py code-extract --iso "...Disc 1).iso" --out ./browse/code

# 9. (Optional) build a sibling browse/ tree of viewable / playable files.
#    Needs ffmpeg on PATH (for audio/movies); Pillow and numpy come with
#    the requirements. Also works on a `dump` folder of any build (the
#    text readers follow the build; --region overrides). --stage is a fast scratch dir; --out is the final
#    destination (omit to keep outputs in --stage). `--kinds` filters
#    which categories to produce; default is all.
python cli.py browse \
    --dump ./dump \
    --stage /fast/disk/stage \
    --out ./browse \
    --jobs 6 \
    --kinds images,text,textures,textures_png,audio,movies,carved

# 10. (Optional) MIPS R5900 disassembly + lui/addiu string xrefs for SLUS
#     and the three OVL overlays (capstone, in the requirements).
python cli.py disasm --code-dir ./browse/code
```

Disc 2 is the same flow with a fresh `--work` directory, using `Lba0.txt` +
`Lba2.txt` against `X3.01/02` and `X3.21/22/23`.

## Outputs

- `container_map.json` — v2 schema: `containers` (name+size) and `regions`
  (LBA filename → ordered chain of container names).
- `disc_7z_list.txt` — raw 7-Zip listing.
- `toc/toc_headers.json` — by-source / by-top / by-ext summary.
- `out/manifest_merged.csv` — every LBA row plus the resolved container, the
  local offset, the comma-separated chain it touches, and a `map_status`.
- `dump/<in-game path>` — extracted files.
- `dump/_reports/extract.log` — per-row log line (`OK`, `SKIP`, `ERR`).
- `dump/_reports/hashes.sha1` — SHA-1 of every written file (when `--hash`).

## Subcommands (the 7-Zip pipeline and the older tools)

The direct-from-ISO commands are listed under [Commands](#commands) above.

| Command         | What it does |
|-----------------|--------------|
| `doctor`        | Prints `container_map.json`, on-disk X3.\*, LBA max-ends. |
| `prep`          | 7-Zip listing + X3.\* extraction + v2 `container_map.json` (no regions). |
| `lba-from-iso`  | Build `Lba*.txt` from the disc's own `X3.00/X3.10/X3.20` index (format in `x3index.py`). Matches the vendored tables exactly on US discs and also handles other builds such as the May 2006 prototype. `prep` runs it automatically when `<work>/lba/` is empty. |
| `container-map` | Rebuild `container_map.json` from a saved 7-Zip listing (no re-extract). |
| `map-regions`   | Assign each `Lba*.txt` to a container chain (`--assign` or auto). |
| `toc`           | Human-readable summary of the merged LBA tables. |
| `scan`          | Walks every LBA row, resolves to `(container, local_offset)`, writes manifest. |
| `extract`       | Slice bytes per the manifest into a mirrored tree. |
| `verify`        | Cross-check extracted file sizes (and optionally SHA-1) against the manifest. |
| `browse`        | Build a sibling `browse/` tree. Categories (`--kinds`): `images` (JPG copy), `text` (TXT/MES/T copy plus a UTF-8 `*.utf8.txt` reading of subtitles and `.mes`, `.txd` menu-text tables decoded, `.sb` scene scripts, `mnu\xx\*.bin` databases, `Message.Dat` and `batdat.bin` parsed to `*.strings.txt` with the build's codec; on a Japanese dump the JP-only scenes are listed in `text/JP-ONLY.txt`), `textures` (XTX/TM2/TXY/BMP/PNG raw copy), `textures_png` (XTX/TM2 → PNG decode, Pillow needed), `package_textures` (every texture inside `.chr`/`.wpn`/`.map` packages and `.esd`/`.esp`/`.sme` effect files → PNG + `package_textures.csv`, pure Python), `audio` (ADX → WAV, ffmpeg), `music` (the 120 soundtrack streams → `music/*.wav` + `music.csv` with loop points; with it on, they are not written under `audio/` as well), `soundbanks` (DAP → per-cue WAV, incl. the banks inside `.sme`), `movies` (SFD → H.264 MP4, ffmpeg), `carved` (JPGs carved from `credit.bin`-style containers), `models` (every model as `.glb` + `models.csv`). `--region auto\|us\|proto_2006_05\|jp` picks the text readers (auto: the dump's boot executable, else its language folder). |
| `code-extract`  | Run 7-Zip over the ISO to pull the non-X3 files (SLUS, OVL, IRX, SYSTEM.CNF) into a directory. |
| `disasm`        | MIPS R5900 disassembly + `lui`/`addiu` string xrefs for SLUS / OVL ELFs. Needs `capstone`. |

### Depack / repack (any file, any build, one ISO in place)

These write a single ISO in place. For copies, Disc 1 + Disc 2 pairs and files
that grow, use `patch`.

| Command          | What it does |
|------------------|--------------|
| `repack-info`    | Resolve an in-game path through the disc's own index: chain, container, absolute ISO offset, sector-allocation slack, files sharing its sectors. |
| `repack-extract` | Pull any one file out of an ISO (all three chains, any build). |
| `repack-patch`   | Write a file back into an ISO in place, read-back verified. Same-size by default; `--pad` allows resizes up to the slot's sector allocation and updates the index size. |
| `repack-tree`    | Patch an entire mod directory that mirrors the game tree (`mymod/mdl/chr/...` → `\mdl\chr\...`). `--dry-run` previews. |
| `xc-unpack`      | Inspect an `Xc` MR package (`.chr`/`.map`/`.wpn`/`.sme`): version, sub-resources; `--out` writes it decompressed (the field maps are LZSS-packed on disc — see `xcpack.py`). |

Full loop and the disc model's rules: [docs/REPACK.md](docs/REPACK.md).
Underlying module works standalone too: [`repack.py`](repack.py).

### Character-texture modding

| Command         | What it does |
|-----------------|--------------|
| `chr-decode`    | Decode every texture inside a `.chr` (or `.wpn`/`.map`, compressed maps included) to PNG — 8-bit, 4-bit and raw-CT32 entries — plus the raw atlas + index map. |
| `chr-palettes`  | Export each texture's 256-color CLUT as an editable 16×16 PNG swatch (one pixel = one color). |
| `chr-import-palettes` | Write edited swatch PNGs back into a `.chr` (lossless round-trip for untouched entries). |
| `chr-import-entry` | Repaint a texture from a same-size PNG, quantized to its existing palette (experimental). |
| `chr-recolor`   | Hair recolor of one `.chr` — `--mode blue` (KOS-MOS-style color filter) or `--mode warm` (Shion-style name policy), `--hue 0..1`. |
| `chr-iso-extract` | Pull one file out of an ISO by its disc path (the disc's own index). |
| `chr-iso-patch` | Write a same-size file back into an ISO, read-back verified. |
| `chr-iso-sweep` | Recolor every matching `.chr` in an ISO in place (work on a copy!), across all chains. |

The GUI has cards for the common path (decode → export palettes → import →
sweep). Guide with the full workflow incl. image-editor palette editing:
[docs/MODDING-CHARACTERS.md](docs/MODDING-CHARACTERS.md); byte-level spec:
[docs/chr-txy-format.md](docs/chr-txy-format.md). The underlying module
also works standalone with positional args: [`chrtex.py`](chrtex.py).

## Common issues

**`Missing container_map.json`** — run `prep` or `container-map` first.

**`{path} has no `regions` mapping`** — `prep` only writes container sizes;
you still need `map-regions` before `scan`.

**Auto-assign refuses with `Leftover containers`** — the heuristic sees
catalog files it doesn't recognise. Re-run with explicit `--ignore X3.00
--ignore X3.10` (Disc 1) or `--ignore X3.00 --ignore X3.20` (Disc 2). Or skip
auto entirely and pass `--assign` strings.

**`unmapped` rows in the manifest** — an LBA entry's offset falls outside
its region's container chain. Usually means the assignment is wrong; check
the `doctor` output and verify the LBA's max byte-end against the chain
size.

**WSL + Windows 7-Zip** — the bundled `iso_ops.py` calls a `7z` binary on
the `PATH`. From WSL you can either install `p7zip-full`, or wrap the
Windows-side `7z.exe`:

```bash
# Optional WSL wrapper
mkdir -p ~/.local/bin
cat > ~/.local/bin/7z <<'SH'
#!/bin/bash
"/mnt/c/Program Files/7-Zip/7z.exe" "$@"
SH
chmod +x ~/.local/bin/7z
```

`7z.exe` reaches WSL paths via `\\wsl.localhost\<distro>\...` if you ever
need to pass them manually.

## Credits

* **Anzinono**: [xenosaga3-translation-kit](https://github.com/Anzinono/xenosaga3-translation-kit)
  (MIT). `udf.py` ports its UDF descriptor handling (CRC-CCITT, tag fix-up,
  partition/integrity/anchor offsets) from `tools/x3rebuild.py`. Its database
  notes (`docs/formats/datenbank.md`, DBF string fields 3, 5 and 9-14) confirmed
  that the 14 mid-string values in `DBC2.bin` / `njDataText.bin` are numbers.
  That kit's `xtx.py` is in turn based on this kit's `xtx_decode.py`.
* **Lybac**: the original Xenosaga III unpack/repack tools, whose LBA lists
  (`lba/`) this kit started from.

## FAQ

**Does this modify the ISOs?** Reading never does. `patch` writes into
copies; only the older `repack-*` / `chr-iso-*` commands edit an image in
place, so give them a copy.

**Can I run scan/extract again after editing the manifest?** Yes —
`scan` is idempotent. `extract` overwrites destination files.

**Is the data fair use?** Jessi owns physical copies of both discs; the
extraction here is for personal archival/study.
