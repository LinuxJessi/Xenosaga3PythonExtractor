# Xenosaga III — disc catalog

What's actually on both Xenosaga III (USA) discs, what each file type is,
where it comes from, and how the extractor handles it. Written from a real
end-to-end unpack of Jessi's physical copies; numbers and counts are exact.

If you're just looking for *how to run the tool*, see the
[main README](../README.md). This document is the data dictionary.

The "Fun finds" section at the bottom collects everything notable the team
left in the shipped binaries (developer names, untranslated locale tables,
KOS-MOS as a literal C struct field, etc.).

After running the full pipeline against both discs, the resulting
`xenosagaextract/` directory has this shape:

```
disc1/
  X3.00 … X3.13                     raw "bigfile" containers from the disc
  lba/Lba0.txt, Lba1.txt            byte-offset tables that index the bigfiles
  container_map.json                LBA→container chain assignment (v2 schema)
  disc_7z_list.txt                  saved 7z listing of the ISO
  toc/toc_headers.json              by-source/by-top/by-ext summary
  out/manifest_merged.csv           every LBA row + resolved container + local offset
  out/dry_run_summary.json          map_status counts
  dump/                             extracted bytes mirrored to the in-game tree
    bat/  cf/  ef/  evt/  jpg/  kao/  mdl/  mg1/  mnu/  mot/  mov/  pac/  snd/
  browse/                           viewable / playable conversions
    code/      ISO-root executables and IOP modules
    images/    JPGs (browseable directly)
    textures/  XTX/TXD/TXY/TM2/BMP/PNG (XTX/TXD need a viewer)
    text/      TXT subtitle / dialogue / config scripts
    movies/    SFD → H.264+AAC MP4
    audio/     ADX → 16-bit PCM WAV
disc2/        (same shape; Lba2.txt instead of Lba1.txt; X3.20/21/22/23)
```

Disc 1 totals: 13,516 files / 3.7 GB raw + 2.6 GB conversions.  
Disc 2 totals: 11,576 files / 4.2 GB raw + 2.4 GB conversions.

> The X3.0x family (`X3.01` + `X3.02`, indexed by `Lba0.txt`) is byte-identical
> on both discs — it holds shared system/UI/model data. Lba1.txt covers
> Disc 1's story content (X3.11/12/13), Lba2.txt covers Disc 2's
> (X3.21/22/23).

## Top-level directory roles

Each row of dump/ corresponds to an in-game path the engine reads from. The
top folders are:

| Folder | Purpose | Approx counts (Disc 1) |
|--------|---------|------------------------|
| `bat/` | Battle definitions, battle-face portraits, battle-sound banks | 91 |
| `cf/`  | Cutscene/Cinematic Fragment configs (the `.t`/`.sb` pairs that drive the engine for a scene) | 1294 |
| `ef/`  | Effects — particle systems and their parameter tables (`.esd`/`.esp`) | 3009 |
| `evt/` | Event scripts and their subtitles for cutscenes (`.xep`/`.xev`/`.txt`) | 121 |
| `jpg/` | UI artwork: still images (real JPGs) + their animation payloads (`.fap`/`.xap`) | 1076 |
| `kao/` | Character face portraits (`.xtx` textures — `kao` = 顔 = "face" in Japanese) | 367 |
| `mdl/` | All 3D models: maps, objects, characters, enemies, weapons, robots | 1576 |
| `mg1/` | A minigame's assets — its own `Stage_NNNN.BMP` boards and `Picture.xtx` | 255 |
| `mnu/` | Menus and UI: pause screen, save, shop, synopsis, UMN browser | 316 |
| `mot/` | Shared motion / face-animation data | 1 |
| `mov/` | Full-motion video cutscenes (`.sfd`) + their subtitle scripts (`.txt`) | 129 |
| `pac/` | "Packed" combatant resource bundles (one `.sme` per character per state) | 679 |
| `snd/` | All audio: streamed voice clips (`.adx`) and sound banks (`.dap`) | 4602 |

The 10-character locale enumeration baked into the SLUS executable —
`jpjpusendefriteszhko` — implies a JP/JP/US/EN/DE/FR/IT/ES/ZH/KO matrix
existed in development; the US release only ships the `us/` subtrees.

---

## File-type catalog

### Standard formats (decode with off-the-shelf tools)

| Ext      | Count (D1/D2) | Lives in           | What it is |
|----------|---------------|--------------------|------------|
| `.adx`   | 3996 / 2095   | `snd/adx/...`      | CRI ADX 4-bit ADPCM voice / SFX, 24–48 kHz mono or stereo. ffmpeg decodes natively. |
| `.sfd`   | 18 / 24       | `mov/` and `mov/us/`| CRI Sofdec — MPEG-1 video (512×320 @ ~24 fps) muxed with ADX audio (48 kHz stereo) in an MPEG-PS wrapper. ffmpeg or VLC plays them straight. |
| `.jpg`   | 1286 / 1286   | `jpg/us/`, `mnu/`, `bat/us/` | Real baseline JFIF JPEGs. UI/event still images. |
| `.bmp`   | 100 / 100     | `mg1/com/Stage/`   | Real BMP (`BM` magic). The mg1 minigame's stage tiles. |
| `.png`   | 4 / 3         | `mov/us/`, `mnu/`  | Real PNG. `libpng 1.2.7` is statically linked into SLUS for these. |
| `.tm2`   | 4 / 4         | `mnu/`             | Sony **TIM2** texture — official PS2 SDK image format. Tools like *PVMEdit*, *Rainbow*, or `tm2-utils` decode them. |
| `.txt`   | 152 / 135     | `evt/us/`, `mov/us/`, `mnu/pse/` | Subtitle / dialogue / config scripts. Tab-separated, CRLF, UTF-8. Cutscene `.txt` lines start with control codes like `$ay375;$xx0,24;$rubyy-4;$col707070;` (positioning, ruby annotation, color). |

### Proprietary "Xc" package family (MonolithSoft PsII engine)

Most of the engine's 3D and animation data lives in a generic container the
engine calls an **MR Package** (Multi-Resource Package). Layout:

```
0x00: "Xc" + u16 version           (\x01\x00 = the common case)
0x04: u32 total size
0x08: u32 total size (repeated — checksum?)
0x0c: u16 sub-resource count
0x0e: "Xp" tag
0x10: array of 4-byte type identifiers ("pxy","txy","xhr","epf","xap"…)
0x40: array of (u32 offset, u32 size) per sub-resource
...: the sub-resources themselves, each starting with its own magic
       ("XHR ","XAP ","XAC ","XST ","XTX "…)
```

Wrapped types and their roles in the engine (from SLUS assertion strings):

| Outer ext | Magic    | Where     | What it bundles | Engine name |
|-----------|----------|-----------|-----------------|-------------|
| `.chr`    | `Xc\x01` | `mdl/chr/{pc,npc,cit,cfn}/` | A complete character: pxy + txy + xhr (hierarchy/skeleton) + epf (effects?) + textures. KOS-MOS is `pc/C3kosmos00.chr`. | XAct character |
| `.map`    | `Xc\x01` | `mdl/map/` | Map geometry packages: a battle background, a town hub, etc. | XAct map |
| `.wpn`    | `Xc\x01` | `mdl/wpn/` | Weapon model packages (`allen_bow01.wpn` is Allen's bow). | XAct weapon |
| `.sme`    | `Xc\x01` | `pac/cf/`, `pac/bat/` | "State for ME" — combatant resource bundles for a given character/state. Contains XAP animation packs and many XAC curves. | XAct combatant |
| `.xep`    | `Xc\x01\x03` | `evt/`, `evt/us/` | Event/scripted-scene file (cutscene logic data). | event package |
| `.xev`    | `XEV ` magic | `evt/`     | Event vector data — paired with `.xep` per scene. | event vector |
| `.chp`    | (custom)  | `mdl/pac/` | "Character package" combining many character entries. | — |

Sub-resource types (the 4-byte tags inside the package's Xp directory):

| Tag    | Stands for | Engine role |
|--------|------------|-------------|
| `xhr`  | XHR — heirarchy | Skeleton / bone hierarchy. `CURRENT_XHR_VERSION` asserts versions. |
| `xap`  | XAP — animation package | Animation clip bundle. `XacKeyType_Hermite` curves inside. |
| `xac`  | XAC — animation curves | Individual curve resources inside an XAP. `CURRENT_XAC_VERSION`. |
| `pxy`  | "proxy" geometry | Lightweight collision / proxy mesh. |
| `txy`  | texture proxy | Texture index/manifest for the package. |
| `xst`  | XST — static? | Static state tables. |
| `epf`  | effect/face? | Bound to face animation in characters. |

### Proprietary face animation

| Ext   | Magic   | Header notes | Role |
|-------|---------|--------------|------|
| `.fap` | `FAP ` + float + counts | Followed by `FAC ` blocks at offsets named by an `Xp` directory | Face Animation Package — lip-sync / expression curves. `mot/face_all.fap` is the shared library; `jpg/C3_*.fap` are per-character expression sets. |
| `.xap` (in `jpg/`) | `XAP ` + float + counts | Followed by `XAC ` blocks | Same family, different content. Drives animated UI/event sprites. |

The `&& "illegal fac version"` assertion in SLUS proves `.fap` is internally
the "FAC" version of XAP.

### Textures

| Ext   | Magic   | Notes |
|-------|---------|-------|
| `.xtx`| `XTX\0` + u32 size + u32 count + u32 hdr-size + u16 width + u16 fmt + u32 height … | MonolithSoft texture format. 750 across both discs (375 each, mostly the same UI textures). Used for character portraits in `kao/`, UI windows (`window0/1/2.xtx`, `ctrl.xtx`), menu icons. **Decoded to PNG under `browse/textures_png/`** for the 367 linear (fmt=0x04) per disc — the 8 swizzled (fmt=0x08) ones are still raw bytes because the MonolithSoft swizzle pattern doesn't match standard PS2 PSMCT32. |
| `.txd`| 8 / 8   | Probably **TXD** — RenderWare-style texture dictionary or a Monolith variant; not yet decoded. |
| `.txy`| `txy\0` + u32 version | Texture index/manifest (pairs with `.pxy` of same stem). Pure index data, not pixels. |
| `.tm2`| `TIM2` magic | Sony's PS2 SDK image format. **Decoded to PNG**; in this game they are all 32bpp RGBA with no palette — chapter-select background (`haikei.tm2`) and episode logos (`logo_ep1`, `logo_ep2`, `logo_pp`). |

### Effects (particle systems)

| Ext   | Count (D1/D2) | Structure |
|-------|---------------|-----------|
| `.esd` | 2083 / 2083 | "Effect Stream/Script Data". First u32 = file size, then the file's own embedded name at ~0x14. Stored under `ef/esd/{group}/{name}.esd` with US versions in `ef/esd/us/`. |
| `.esp` | 926 / 926   | "Effect Script Parameters"? — paired by directory, not 1:1 by stem (2083 vs 926). |

### Scene config

| Ext  | Count | Pairs with | What it is |
|------|-------|------------|------------|
| `.t` | 647 / 647 | `cf/{id}.t` | Tab-separated text manifest for cutscene/encounter `{id}`. Lists `map`, `ene` (enemy), `mdl` entries by name. CRLF, UTF-8. |
| `.sb`| 715 / 715 | `cf/us/{id}.sb` | "Sound Bank" — `SB  ` magic + version + count + offset table. Localized voice/SFX bank for that scene. |

### Localized message data

| Ext  | Count | Where | Notes |
|------|-------|-------|-------|
| `.mes` | 6 / 6 | `mnu/`, `bat/` | Message tables — localized strings. |
| `.bin` | 17 / 17 | `mnu/`, `bat/` | Generic binary. **`mnu/credit.bin` turns out to be a tiny container holding 4 JPGs** — the boot-up publisher / developer logos (Bandai Namco, MonolithSoft). Each JPG is **extracted under `browse/images/mnu/credit/`**. Header: u32 count(?)+4 u32 file-offsets, then the JPGs concatenated. |
| `.dat` | 23 / 23 | `mg1/`, `mnu/` | Generic data (e.g. `mg1/us/Message.Dat` is the minigame's English message table). |
| `.shp` | 25 / 25 | `mnu/shop/` | Shop inventory tables (`07.shp` = shop 07's stock). Small (~500B) binary lookup. |
| `.pxy` | 82 / 82 | `mnu/`, `mg1/` | Standalone proxy/index file (same `pxy` tag used inside `.chr` packages). |

### Audio

| Ext   | Count | Role |
|-------|-------|------|
| `.adx` | 3996 / 2095 | CRI ADX streamed audio. Convention used in `snd/adx/`: `mev/` = movie voice, `bat_voice/` = battle voice, plus SFX trees. |
| `.dap` | 607 / 607 | **CRI DTPK sound bank**. At offset 0x40 the magic `ps2_DTPK` appears; followed at a fixed offset by a `ps2_VAGD` chunk holding PS2 SPU2 ADPCM (VAG) audio. Each file is a 2 KiB header + N × 2 KiB pages of bank entries. Decode with **vgmstream** or **VGMToolbox** (CRI ACB/DTPK support); a full Python decoder is out of scope here. |

---

## Conversions produced under `browse/`

The `browse/` tree is what to scroll through in a file manager. Everything
here is in a format your OS can open without help.

| Folder            | Source ext(s)       | Output ext | Tool          | Notes |
|-------------------|---------------------|------------|---------------|-------|
| `browse/images/`  | `.jpg`              | `.jpg`     | copy          | 1542 (D1) / 1524 (D2) files, 30 MB each disc |
| `browse/textures/`| `.xtx .txd .txy .tm2 .bmp .png` | unchanged | copy | 569 / 568 files; BMP/PNG/TM2 are already viewable; XTX/TXD/TXY need a format converter |
| `browse/text/`    | `.txt .mes`         | unchanged  | copy          | 158 / 141 files; cutscene subtitles + menu strings. Subtitles pair 1:1 with `browse/movies/` |
| `browse/movies/`  | `.sfd`              | `.mp4`     | ffmpeg (x264 CRF 23 + AAC 160 kbps) | 18 / 24 files. Plays in any modern player. |
| `browse/audio/`   | `.adx`              | `.wav`     | ffmpeg (`pcm_s16le`) | 3995 / 2095 files. Voice clips, SFX, music loops. |
| `browse/code/`    | ISO root            | unchanged  | 7-Zip extract | 15 files per disc: SLUS executable + 3 OVL overlays + 10 IOP modules + SYSTEM.CNF. |
| `browse/textures_png/` | `.xtx`, `.tm2`  | `.png`     | xtx_decode.py + tm2 helper | 371 / 371 files (367 linear XTX + 4 TM2 + the swizzled ones written but unreadable). Includes the character portraits, episode logos, chapter-select background. |
| `browse/images/mnu/credit/` | `credit.bin` JPGs | `.jpg` | regex SOI/EOI carve | 4 boot logos per disc. |

Subtitle pairing example:
```
browse/movies/mov/s000700.mp4    ← Miyuki & Shion cutscene
browse/text/evt/us/s000700.txt   ← the dialogue, with timecodes
```

One ADX (`snd/adx/mev/s050200_02_2shi.adx` on Disc 1) is a **0-byte entry in
the original LBA** — it's faithfully extracted as an empty file. The browse
step skips empties.

---

## Code / disassembly

`browse/code/` now also contains:

- `SLUS_{213.89,214.17}.disasm.txt` — full MIPS R5900 disassembly of the
  main game executable (~22 MB, 517,646 instructions). Decoded with
  Capstone in MIPS64-LE mode with `skipdata=True`; PS2 EE MMI / VU0-macro
  instructions appear as `.byte` runs (Capstone doesn't decode those).
- `SLUS_{213.89,214.17}.strings_xrefs.txt` — for every code site that
  loads the address of a printable string with a `lui`/`addiu` pair, one
  line of `<load_va>  ->  <string_va>  <string>` (1,153 unique strings).
  Far more readable than the raw asm; this is where you find things like
  `mwPlyCreateSofdec: can't skghn.` next to the file address that calls it.
- `OV{01,02,04}.OVL.disasm.txt` — same treatment for the three overlays.

The disasm is identical between discs (the binaries themselves are
identical — see Fun finds).

## What's still raw / not converted

These keep their original bytes under `dump/` but no `browse/` conversion
yet — they need format-specific work beyond the scope of this pipeline:

- **3D models** (`.chr .map .wpn .sme`) — would need an XHR/XAP parser to
  reconstruct meshes + skeletons + bound textures into glTF/FBX. The
  container layout is documented (the "Xc" package family above), but
  decoding the actual mesh streams is a separate project.
- **Swizzled XTX textures** (16 files, mostly UI overlays in `mnu/`) —
  the MonolithSoft swizzle pattern doesn't match standard PS2 PSMCT32.
  Bytes are written linearly anyway, just visually scrambled.
- **Effect data** (`.esd .esp`) — parameter tables for the particle
  system; unlikely to be viewable on their own, but interesting for
  modders.
- **Event scripts** (`.xep .xev`) — opcode streams for the cutscene VM.
  Without a disassembler for that VM you only see the `Xc\x01\x03` header.
- **CRI DTPK sound banks** (`.dap`) — wrapped CRI bank format
  (`ps2_DTPK` + `ps2_VAGD` chunks containing PS2 SPU2 VAG ADPCM). Use
  vgmstream or VGMToolbox to extract individual cues.
- **Scene sound banks** (`.sb`) — `SB  ` magic + offset table. Same idea
  as DAP but Xenosaga-specific.

---

## Fun finds

### Both disc executables are byte-identical

```
md5 SLUS_213.89 (disc1) == md5 SLUS_214.17 (disc2) == 0ef759d006731b465da05f475f24c233
```

Only the filename differs — the PS2 firmware uses the title ID to recognise
which disc is in the tray. Disc-switching logic is entirely data-driven; the
same 4.5 MB MIPS ELF runs both halves of the game.

### "KOS-MOS" is a literal C++ field

A string in the binary reads:

```c++
pKosmos->rsrc[XAct_Rsrc_XAP_Ext2]
```

So the main character isn't just an art asset — she has a dedicated pointer
in the engine's actor table. (Mildly funny because Jessi's parent workspace
directory is also named `KOS-MOS/`.)

### The engine is called "PsII"

Eight modules with the `PsII` prefix link into SLUS:
`PsIIlibcdvd · PsIIlibdma · PsIIlibgraph3000 · PsIIlibipu · PsIIlibkernl3000 ·
PsIIlibmc · PsIIlibpkt · PsIIlibsdr`. The `3000` suffix is the
PlayStation 2 SDK Series 3000 build; the rest are MonolithSoft wrappers.

### MatuzawaTest — a programmer's debug toggle

The string `?MatuzawaTest: NODEBUG` is preserved verbatim, along with
`CF Debug Flags` and `DEBUGPAUSE:`. Matsuzawa (松澤) was one of the
engineers on the team — they left a personal feature-flag in the shipped
build. (PS2-era games shipped with debug stubs all the time; it just wasn't
common to keep a name attached.)

### Test source filenames survived stripping

The shipped binary still names test sources that were never supposed to be
in a release build:

```
BlendTest.euc.c       CFLLightTest.euc.c    CullingTest.euc.c
ScisTest.euc.c        XstAnimTest.euc.c
```

The `.euc.c` extension is the MonolithSoft convention for **EUC-JP-encoded
C source** (so the comments can be in Japanese without needing UTF-8). The
test harness clearly lived in the same build target as the shipped game.

### CRI middleware was frozen 10 months before release

Build-date strings inside SLUS:

```
ADXRT  Ver.3020 Build:Sep 20 2005   ← CRI ADX audio runtime
SJ/PS2EE Ver.6.34 Build:Sep 20 2005 ← CRI Sofdec movie player
PL2ENC Ver.1.02 Build:Sep 20 2005   ← CRI's encoder helper
```

All three middleware libraries were built on the same Tuesday morning in
September 2005. The disc was mastered ten months later (`2006-07-12`).

### Languages that never shipped

The locale-code table reads `jpjpusendefriteszhko` — JP / JP / US / EN /
DE / FR / IT / ES / ZH / KO. The US disc only ships the `us/` subtrees
under `evt/`, `mov/`, `jpg/`, `mnu/`, `bat/`, `cf/`, `ef/`, but the engine
clearly had localization machinery for ten languages, including Korean and
Simplified Chinese. (No Korean or Chinese release of Xenosaga III actually
happened.)

### Subtitles ship as separate text files

Every `mov/*.sfd` cutscene has a `evt/us/{stem}.txt` companion with the
dialogue in tab-separated form — character timing on the left,
speaker-tagged line on the right. The first row sets visual style with
control codes like `$ay375;$xx0,24;$rubyy-4;$col707070;` — vertical
position, baseline-style, ruby (furigana) annotation, and color. So the
game's subtitle renderer supported ruby characters natively even though
the US release doesn't use any.

### The XAct resource enum

The pre-stripped enum names are still visible:

```
XAct_Rsrc_MDL    XAct_Rsrc_TEX    XAct_Rsrc_XAP    XAct_Rsrc_XAP_Ext2
XAct_Rsrc_XHR    XAct_Rsrc_XST
```

"XAct" is the engine's actor/asset system. `XAP_Ext2` exists as a slot for
secondary animation packs — implying actors can have layered animation
banks (probably for combos or scripted overrides).

### `credit.bin` is actually the boot logos

Turns out `mnu/credit.bin` isn't credits at all — and it's not obfuscated.
It's a tiny container holding **four concatenated JPEG images**: the
publisher (Bandai Namco Games) and developer (MonolithSoft) splash
screens that play at boot, plus two more. Each was extracted to
`browse/images/mnu/credit/credit_NN.jpg`. The "obfuscation" was just the
absence of ASCII strings because the payload is JPEG-compressed.

### Resource arithmetic in plain text

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

### Dual-purpose mg1 minigame

The `mg1/` folder is treated as a separate game inside the game — it has
its own `Stage_NNNN.BMP` board art, its own `Message.Dat` text table, and
its own `Picture.xtx`. The format conventions don't match the rest of the
engine (BMPs instead of XTX), suggesting a different team built it.

---

## How to reproduce everything in this catalog

Either point your browser at the GUI launcher (see the
[main README](../README.md)) and walk top-to-bottom through the ten cards,
or run the same commands from the command line:

```bash
cd ~/work-disc1                                              # one dir per disc
cp -r /path/to/Xenosaga3PythonExtractor/lba ./               # vendored Lba0/1/2.txt
pip install -r /path/to/Xenosaga3PythonExtractor/requirements.txt   # optional deps
python /path/to/Xenosaga3PythonExtractor/cli.py prep         --iso  Disc1.iso --work .
python /path/to/Xenosaga3PythonExtractor/cli.py map-regions  --work . \
    --assign "Lba0.txt=X3.01,X3.02" --assign "Lba1.txt=X3.11,X3.12,X3.13" \
    --ignore X3.00 --ignore X3.10
python /path/to/Xenosaga3PythonExtractor/cli.py scan         --work . --sniff
python /path/to/Xenosaga3PythonExtractor/cli.py extract      --work . --out ./dump --hash
python /path/to/Xenosaga3PythonExtractor/cli.py verify       --work . --out ./dump --hash
python /path/to/Xenosaga3PythonExtractor/cli.py code-extract --iso Disc1.iso  --out ./browse/code
python /path/to/Xenosaga3PythonExtractor/cli.py browse       --dump ./dump --stage ~/stage --out ./browse --jobs 6
python /path/to/Xenosaga3PythonExtractor/cli.py disasm       --code-dir ./browse/code
```

Disc 2 is the same workflow with `Lba2.txt` against `X3.21/22/23` and
`--ignore X3.00 --ignore X3.20`.

A separate one-shot Ghidra-headless pipeline (Ghidra 12.1 + JDK 21) was
used to produce the C-pseudocode decompilation that backs many of the
"Fun finds" below. It's not part of this extractor's CLI — the steps live
in a sibling project directory.

## Provenance

- Source ISOs: Jessi's personally-owned PS2 disc rips. Use your own.
- Extraction tool: this repo. Fixes the v0.1 ChatGPT prototype's
  cross-bigfile address bug that was silently corrupting every row from
  Lba1/Lba2 (= every event script, voice line, and cutscene audio entry).
- LBA tables originally generated by Lybac's *Xeno23Lbae* (2006). Ours
  are vendored under [`lba/`](../lba/) so the extractor works
  out-of-the-box without chasing down the original Windows .exes.
