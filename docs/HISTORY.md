# Historical context: what these discs record about Episode III

The extraction is also a record of how the game was built. Facts from the
discs are reproducible with this kit and say how they were read; the few
outside facts are linked to their source. The Episode I and II kits have the
same page.

## The game

*Xenosaga Episode III: Also sprach Zarathustra* was developed by Monolith
Soft and published by Namco Bandai Games: in Japan on July 6, 2006 and in
North America on August 29, 2006
([Wikipedia](https://en.wikipedia.org/wiki/Xenosaga_Episode_III)). It was not
released in Europe. It is the last of the three episodes, on two DVDs.

The kit reads five images of it: the USA discs (SLUS-21389 and SLUS-21417),
the Japanese discs (SLPS-25640 and SLPS-25641) and a single-disc USA
prototype marked "FOR PRESS ONLY".

## Dates on the discs

Read on 2026-11-21 from each image: the executable's `Compiled on` date and
time, and the creation time in the ISO 9660 volume descriptor.

| Build | Executable compiled | Volume created |
|---|---|---|
| Japan retail (SLPS_256.40 / .41, one executable) | Feb 21 2006, 15:45:12 | 2006-02-28, 15:34:50 (Disc 1) and 15:58:29 (Disc 2) |
| USA prototype (SLUS_213.89) | May 22 2006, 13:26:49 | 2006-03-01, 14:00:02 |
| USA retail (SLUS_213.89 / SLUS_214.17, one executable) | Jul 12 2006, 13:22:53 | 2006-07-12, 14:44:20 (Disc 1) and 15:16:46 (Disc 2) |

Two things to read with care:

* **The prototype's volume is older than its code.** Its volume says March 1
  and its executable May 22; the files inside are dated May 21 to 23. The
  disc project was set up in March and burned again later. Its first sectors
  still hold the mastering record: `SLUS-21389 / XENOSAGA3 /
  NAMCOBANDAIGAMES / 20060301 / PlayStation Master Disc 2`, written with
  Sony's CDVDGEN 2.00 on a Pioneer DVR-107D. The retail images have zeros
  there.
* **The Japanese dates are what the discs say, and nothing more.** February
  21 and 28 are more than four months before the Japanese release date. The
  discs do not say why, and this page does not guess. On USA retail the
  compile time and the volume time are 81 minutes apart on the same day.

Older dates inside the executable, the same on every build:

| Date | What |
|---|---|
| Aug 9 2005 and Sep 20 2005 | CRI's middleware builds (ADX, Sofdec and the rest; `Build:` strings) |
| Jan 31 2006, 14:48:23 | one more `Build:` stamp, later than CRI's |
| SDK 3.0 | Sony's libraries (`PsIIlibcdvd 3000`, `PsIIlibmc 3030` and others) |
| `GCC2096` | the compiler tag: Sony's ee-gcc 2.96 |

So the middleware was frozen about ten months before the USA master.

## Three builds, one program

| | Japan retail | USA prototype | USA retail |
|---|---|---|---|
| Executable | 4,505,232 bytes | 4,513,232 bytes | 4,513,232 bytes |
| Build tree, from the mini-game overlay's path | `x3` | `x3` | `x3u` |
| Language folder | `\jp\` | `\us\` | `\us\` |
| Text reading | EUC-JP pairs | USA pair list + Latin-1 | the same |
| Symbols | none | none | none |

Disc 1 and Disc 2 of a retail pair carry the same executable byte for byte;
only its file name differs, because the console tells the discs apart by it.
The prototype's code is USA retail's with small changes: 8,599 of the 8,626
functions of the main executable are identical after relocation, and the
rest differ in localisation text and glyph widths, the movie and disc-swap
flow, and small fixes (measured 2026-11-05). What the prototype's *data* has
that retail lost is in [FINDS.md](FINDS.md).

The executable's locale table reads `jp jp us en de fr it es zh ko`: ten
slots. Only `jp` and `us` trees were ever shipped on the discs the kit has
seen.

## From Episode I to Episode III

| | Episode I (2002) | Episode II (2004-05) | Episode III (2006) |
|---|---|---|---|
| Table of contents | binary, plain names | the same, with front-coded names | Episode II's format, by the same tool ("Episode.2" in its padding) |
| Compression | ARX | ARX (three files) | four LZSS flavours, in model packages |
| Scene scripts | Java classes (JDK 1.1) | Monolith's own stack machine, 16-bit words | `.sb` again, with another header: the same machine re-encoded as 99 one-byte opcodes, one voice stream per event line |
| Field music | sequenced (Procyon SMD/SWD) | sequenced (Standard MIDI on a KORG driver) | recorded: 120 ADX streams |
| Models | `.lex` + `.xtx` | loose `.pxy` + `.txy` + `.xhr` | the same three, inside `Xc` packages; `.xhr` 3.0 |
| Fonts | swizzled sheets with headers | the same | plain sheets, four 2-bit planes per byte |
| Movies | PSS (MPEG-2) | Sofdec, 512 x 448, ADX + AC3 5.1 | Sofdec, 512 x 320, ADX |
| Sony SDK | 2.4 | 2.7 | 3.0 |
| Symbols in the executable | yes | no | no |

Each episode carried its predecessor's tools forward and replaced one or two
parts. Episode III's effect files even still name Episode II's source
folders (`g:\xeno2\effects_data\`).

## Who

The discs name people in three places. All are as the files spell them, and
say nothing more about anyone:

* a debug switch in the executable, `?MatuzawaTest: NODEBUG`;
* the source folders of the particle effects: `watanabe`, `ikuko`, `sano`,
  `hasegawa`, `fujii`, `tayzou`, `asakura`;
* developers' work paths in the executable and overlays
  (`host0:/home/xeno/work/iwase/...`, `.../tetsuya/...`).

Unlike Episodes I and II, the data is not organized by person: the disc's
folders are by kind (`mdl`, `snd`, `mnu`, `cf`, `ef`, `mov`).

## How this kit came to read it

| Date | Step |
|---|---|
| 2026-05-15 | the first public beta: 7-Zip plus tables of sector addresses made by older Windows tools |
| 2026-07 | Sofdec movies: demux and same-size video splice |
| 2026-09-24 | the improvement run ported from the Episode I kit: LZSS field maps, textures inside packages, DTPK banks, swizzled UI sheets |
| 2026-11-05 | the prototype compared with retail; the disc's own index format read from the executable, so any build can be opened |
| 2026-11-20 | parity with the Episode I and II kits: Japanese discs, models, the text pipeline, fonts and new scripts, write-back to copies; the first discs written by the kit booted in PCSX2 |
| 2026-11-21 | motion clips as glTF animations; the soundtrack as its own output; the app bundle built and run by `build.py`; this page and its siblings |

[UPDATES.md](UPDATES.md) has each step in detail.
