# Music and sound

Where Episode III keeps its music, what the kit does with it, and why this
page is so much shorter than the other two kits' `MUSIC.md`.

## The soundtrack is recorded, not sequenced

Episode I's field music is sequenced (Procyon SMD/SWD files), and so is
Episode II's (Standard MIDI files on a KORG driver). Those kits rebuild the
PS2's synthesizer to turn them into MIDI, SoundFonts and WAV. Episode III has
nothing of the kind to render: its music is **120 recorded stereo ADX
streams** sitting directly in `snd\adx\`, beside the folders of voice and
event audio. So there is no MIDI and no SoundFont to export, and the audio
you get is the game's own recording, not a model of it.

```sh
python cli.py music-list --iso "Disc 1.iso" --csv soundtrack.csv   # the table, straight from the disc
python cli.py browse --dump out/dump --stage out/browse --kinds music
```

`browse --kinds music` writes `music/<name>.wav` for each stream and
`music/music.csv`. When `audio` runs in the same `browse`, the soundtrack is
written under `music/` only, not a second time under `audio/`; with `audio`
alone it stays under `audio/` as before.

## What is on the discs

Read from the stream headers of all five images on 2026-11-21 (USA Disc 1 and
2, Japan Disc 1 and 2, the May 2006 prototype). The 120 streams have the same
rates, lengths and loop points on every one of them:

| Names | Streams | Length | Sample rate | Looped |
|---|---|---|---|---|
| `A01` | 1 | 2.2 min | 48 kHz | yes |
| `B01` .. `B19` | 17 | 35.2 min | 48 kHz (one at 24 kHz) | all |
| `C01` .. `C24` | 33 | 51.0 min | 20 at 24 kHz, 13 at 48 kHz | all |
| `E03` .. `E49B` | 53 | 94.7 min | 39 at 24 kHz, 14 at 48 kHz | all |
| `M01` .. `M78` | 10 | 13.8 min | 24 kHz | all |
| `S01` .. `S05C` | 6 | 1.7 min | 24 kHz | none: they play once |
| **all** | **120** | **3.31 hours** | 44 at 48 kHz, 76 at 24 kHz | 114 |

The longest is `E45` (4 min 16 s); the shortest are the `S` streams (7 to 32
seconds). A name with a letter suffix (`C01B`, `E25B`, `S05A/B/C`) is a
variant of the same number. What each letter stands for is not written
anywhere the kit has read, and this page does not guess: no stream has been
matched to a scene, a track title or the soundtrack album.

### Loop points

A looped stream's header gives the sample where the loop starts and the
sample where it ends. For example `B01`: 89.7 s long, loop from 10.283 s to
89.141 s, so it plays an introduction once and then repeats the rest. ffmpeg
decodes a stream once through, so the WAV holds one pass and the loop points
are in `music.csv` (in samples and in seconds) for anyone who wants to cut a
seamless loop or an extended version. `adx.py` checks each header before
trusting it: start before end, end within the stream.

### The other ADX folders are not music

| Folder | USA Disc 1 / Disc 2 | What |
|---|---|---|
| `snd\adx\mev\` | 3,534 / 1,645 | scene voice lines |
| `snd\adx\bat_voice\` | 289 / 289 | battle voice |
| `snd\adx\evt\` | 41 / 29 | the audio tracks of event scenes (`s000100.adx` and so on) |
| `snd\adx\sys\` | 12 / 12 | short system sounds |
| `snd\adx\arasuji\` | Japanese discs only, 70 | not listened to; *arasuji* is Japanese for "synopsis" |

The Japanese discs also carry more `mev` and `bat_voice` streams (3,571 and
311 on Disc 1). The movies' music is mixed into each movie's own ADX track.

## Sound banks

Sound effects are in 607 DTPK banks (`.dap`): 606 in `snd\dat\` and one under
the mini-game's `mg1\com\Sound\`. `browse --kinds soundbanks` writes one WAV per sample
with `dap_decode.py`: 6,268 samples from 599 banks on USA Disc 1 (8 banks
hold no samples).

| Bank names | Banks | Samples |
|---|---|---|
| `me_*` | 247 | 2,254 |
| `fs_*` | 139 | 1,765 |
| seventeen three-letter prefixes (`HOS`, `MIK`, `ZDA`, `RAV`, `HAK`, `REN`, `SYU`, `CIT`, `DYU`, `ELS`, `MOR`, `UMD`, `MER`, `DOU`, `KYO`, `MUJ`, `KYM`) and `MINI` | 220 | 2,194 |
| `Master.dap` | 1 | 55 |

Each combatant bundle (`.sme`) carries a bank of its own, which `browse`
writes too. A bank also holds driver tables (programs, tones, sequences) that
say how the samples are pitched and combined into the cues the game plays;
those are **not decoded**, so you get the raw samples at their recorded rate,
once through, not the cues as heard in game.

## Still open

* Which stream plays where (the scripts' code is not decoded, so the calls
  that start a stream have not been read).
* The DTPK driver tables.
* No WAV is written with the loop applied; the table gives the points.
* The streams were decoded with ffmpeg and checked by length against their
  headers (`C01`: 40.085 s both ways). They have not been compared with a
  capture of the running game.
