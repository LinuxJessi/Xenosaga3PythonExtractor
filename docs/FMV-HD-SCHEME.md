# Xenosaga III FMV (pre-rendered cutscenes): HD replacement scheme

How to take AI-upscaled versions of the `.sfd` cutscenes and repackage them so
the **actual PS2 engine loads and plays them**. Everything here is byte-verified
against the retail Disc 1 and cross-checked against the decompiled SLUS
(`decompiled/slus/functions/`); no code is built yet — this is the design +
the reverse-engineering that de-risks it.

Companion docs: [REPACK.md](REPACK.md) (general write-back), the HD trilogy
plan-of-record in the parent repo's `docs/HD-TRILOGY-PLAN.md` (Workstream B/E).

## What the cutscenes actually are (verified)

- **Standard MPEG-1 Program Stream**, not a proprietary opaque container:
  `mpeg1video` **512×320 @ 29.97 fps** + **CRI ADX** audio (`adpcm_adx`,
  48 kHz stereo, 432 kbps). Real bitrate ~6.9 Mbps (the stream's "104 Mbps" is
  the VBR sentinel `0x3FFFF·400`).
- **One 2048-byte MPEG pack per disc sector** (`00 00 01 BA` at every sector,
  incrementing SCR). Video = PES stream **0xE0**, ADX audio = PES stream
  **0xC0** (with PTS), padding **0xBE**.
- **Player = CRI‑MW Sofdec `mwPly`** (`MWSFD/PS2EE Ver.3.65`) over Sony
  **`sceMpeg`/IPU** for video and **ADXT** for ADX audio — all standard,
  documented PS2 middleware.
- 30 story movies on Disc 1 (`Lba1`, up to 353 MB) + 3 title movies (`Lba0`);
  21 story movies on Disc 2. Sector-tight (zero slack) in the bigfiles.

## The one hard constraint on the encode

ffmpeg **decodes** both streams but its `mpeg` muxer **refuses `adpcm_adx`**
(`Must be one of mp1, mp2, mp3, 16-bit pcm_dvd, pcm_s16be, ac3 or dts`). So a
full ffmpeg remux is impossible. The scheme therefore **splices a re-encoded
video elementary stream back into the original container while preserving the
original ADX audio PES packets verbatim** — the exact pattern Xenosaga I already
proved in `Xenosaga1PythonExtractor/subs.py:splice()` (adapted from XS1's 0xBD
SPU audio to XS3's 0xC0 ADX). Keeping the audio bytes gives perfect A/V sync
for free.

## How the game finds a movie (catalog — the key to growable replacement)

The engine does **not** read movies from the ISO9660 filesystem; it resolves
`\mov\…\*.sfd` through an internal binary catalog `X3.10` (Disc-1 `Lba1`),
inside the contiguous `X3.10→X3.13` region.

**Offsets are stored explicitly** (decompiled `FUN_00187e28`; confirmed on the
disc). Each catalog entry carries `[offset : 3 bytes LE, in 2048-byte sectors]
[size : 4 bytes LE, in bytes]`, read directly — no accumulation. Verified: for
all 15 Disc-1 movies the stored size matches exactly and the stored offset is a
constant **+26 sectors** above the `Lba1.txt` offset, and `X3.10` is exactly 26
sectors — i.e. offsets are relative to the catalog/mount base. (`Lba1.txt`'s
offsets only *looked* implicit because the legacy ripping tool regenerated them
by accumulation; the disc stores the real fields, which is what the game reads.)

The resolved `(offset, size)` is formatted `"%08x.%08x"` (`offset`,
`size>>11`) and handed to `mwPlyStartFname` (`FUN_0018b9f8`).

**Because offsets are stored, a single movie can be relocated and repointed
without touching its neighbours** — this is what makes HD (bigger) movies
possible without rebuilding the 2 GB container chain.

## Engine resolution ceiling (for true higher-res, not just cleaner 512×320)

The decode **maximum** is hard-coded 512×320, set by the immediates
**`FUN_0018bd40(0x200, 0x140)`** (called from the play routine `FUN_001b3858`),
propagated into the SofDec `MwsfdCrePrm` by `FUN_0018bcd0` and turned into the
work-buffer size by `mwPlyCalcWorkCprmSfd`. The IPU itself and the GS upload are
**stream-driven**: the IPU decodes whatever the MPEG sequence header declares,
and the GS uploader `FUN_0018b818` transfers the frame as 16×16 RGBA tiles using
dimensions taken live from the frame descriptor. So a larger MPEG will *try* to
decode at its own size and will display correctly **once the ceiling and the
derived buffers are raised** — otherwise it trips the guard `FUN_002fc8c8`
("Too small buffer size for %dx%d picture"). The practical ceiling is **4 MB GS
VRAM** (a 1024×640×32bpp frame ≈ 2.6 MB double-buffered is tight → ~2× realistic).

## The scheme, by ambition

**Remux core (needed by every tier)** — `sfd_splice.py`, cloning XS1
`subs.py:splice`: demux the `.sfd`, replace the 0xE0 video PES with a re-encoded
ES from the AI-processed frames, keep every 0xC0/pack/padding packet verbatim,
re-emit 2048-byte sector-aligned packs.

- **Tier 1 — cleaner 512×320, in place (works with today's tools).**
  AI-restore each frame → downscale back to native 512×320 → best-in-class
  MPEG-1 encode **within the original byte budget** → splice → `repack.py patch`
  (same-size-or-smaller, already built + read-back verified). No catalog, ISO,
  or ELF changes. Real quality gain from a modern encoder + AI denoise at equal
  bytes; resolution unchanged. **Recommended first target.**

- **Tier 2 — grow the files (higher bitrate / higher resolution).**
  *Disc side (cheap, because offsets are stored):* append the enlarged movies
  sector-aligned after `X3.13` (the ISO tail), rewrite each replaced movie's
  catalog `offset`+`size` in `X3.10`, and grow `X3.13`'s ISO9660 directory size
  + the PVD volume size. Same-size movies never move. *For higher **resolution**
  only:* also patch the SLUS ceiling (`FUN_0018bd40` `0x200,0x140` + the
  `MwsfdCrePrm` max fields + derived work/DMA/IPU-ring buffers). Gated on GS
  VRAM (~2×). Fits DVD-9 up to ~3× movie bitrate; PCSX2 loads any-size ISO.

- **Tier-alt — PINE-synced HD overlay (not in-engine).** Play a full-quality
  upscaled MP4 in a borderless always-on-top window, triggered by watching the
  movie-playback RAM flag over PINE (position-hunt method). Unlimited
  resolution/H.264, zero disc/engine work; the game renders underneath. Best
  quality-for-effort for personal use, though not literally "the game loading
  them."

## Build/validation ladder (each rung boots on PCSX2 before the next)

1. Demux→remux an **unmodified** `.sfd` → byte-identical file (proves the splice).
2. Same-size re-encode of one movie → `repack.py` in place → boots, plays,
   A/V sync holds (Tier 1).
3. Grow one movie → append + catalog repoint → boots, plays (Tier 2 disc side).
4. 2× one movie + patch the `FUN_0018bd40` ceiling & buffers → plays at higher
   res, or hits the `FUN_002fc8c8` guard (resolution spike).

## Legal note

Own-disc assets only; the upscaled/derived video never leaves the machine
(personal use). The scripts are content-free and shippable; the resulting
movies/patches are derivative and stay local.
