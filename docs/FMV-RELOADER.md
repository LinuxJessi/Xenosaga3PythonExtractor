# FMV Reloader — external HD cutscene playback for Xenosaga (PCSX2)

Status: **design + scaffold**. Blocking unknown: the FMV-active RAM signal
(see §4). Everything else is built or reused.

## 1. Why external, not in-place

The in-place splice path (`fmv_sfd.py` + `repack.py`) is byte-exact and proven,
but it is **hard-capped at the original resolution** — XS3 movies are
`mpeg1video 512x320`, and the module's own docstring says growing past the
byte budget "needs a repacketizing muxer + disc-side append/repoint … out of
scope." Even if we grew the stream, the PS2 **IPU + the game's decode buffers**
top out near DVD resolution (~480p). Upscaling to 4K only to re-encode down to
480p defeats the remaster.

The reloader routes around the emulated video path entirely: when the game
starts a cutscene, PCSX2 keeps running but we **lay a real HD video player over
its window**, decoding our locally-generated 1080p/4K file with a modern codec.
No IPU ceiling, no ISO growth, no PCSX2 fork. This is
[PCSX2 issue #8545](https://github.com/PCSX2/pcsx2/issues/8545) implemented
*outside* the emulator, driven by the existing PINE stack.

## 2. Distribution model (Bleem-framework)

The **splash is a generator, not an asset pack.** We ship tools; the user's
copyrighted bytes never leave their machine.

Shipped:  portable PCSX2 (GPLv3), the extract toolchain (`repack.py`,
`fmv_sfd.py`), the upscaler (Video2X + APISR/Real-CUGAN, bundled or fetched),
and the reloader daemon.
**Never shipped:** PS2 BIOS, the game ISO, or any upscaled FMV. The user points
the splash at their own dump; extraction → upscale → playback all happen locally.

First-run flow the splash orchestrates:

```
user's clean ISO
   └─ repack.py / fmv_sfd.py  →  extract every .sfd video ES   (their disc)
        └─ Video2X + APISR     →  upscale to HD AV files         (their GPU)
             └─ fmv_reloader     →  play them over PCSX2 at runtime
```

## 3. Runtime architecture

```
        PCSX2 (portable, unmodified)
          │  PINE unix socket ($TMPDIR/pcsx2.sock)
   ┌──────┴───────┐
   │ fmv_reloader │  polls FMV-active @ ~60 Hz  (pine.py, reused as-is)
   └──────┬───────┘
   rising edge → identify which .sfd → resolve HD file → HANDOFF
```

**Handoff strategy (default: `turbo-underlay`).** On the rising edge:
1. **Mute** PCSX2 and engage **turbo/fast-forward** (hotkeys via `pynput`) so
   the in-engine FMV blazes through in seconds and the game reaches the
   post-cutscene state — clock desync becomes irrelevant.
2. Simultaneously launch a **borderless, always-on-top** player (`ffplay`/mpv)
   playing the HD file at normal speed over the PCSX2 window.
3. **Teardown** on overlay-end *or* user-skip: kill the player, release turbo,
   unmute. (FMV-active falling early just confirms the game already finished.)

Alternative `pause-and-resume` strategy (config flag) holds the VM at FMV start
and plays a self-contained HD **A/V** file, then resumes + skips the game past
its own FMV. Kept as fallback for any movie turbo mishandles.

The **which-file mapping is free**: `repack.Disc` already enumerates every
`.sfd` by name (`fmv_sfd.py selftest`), so the daemon maps
`{sfd basename → HD file}` at startup from the disc catalog.

## 4. The one blocking unknown — the FMV-active signal

We need two runtime reads, both found by `fmv_state_hunt.py` against a live game:

- **FMV-active byte** — 0 during gameplay, non-zero during *every* FMV, back to
  0 after (incl. on skip). Found by differential snapshot diff (the `poshunt`
  method): sample during play vs during several FMVs, keep bytes matching the
  on/off pattern, two-spot confirm.
- **Which FMV** — on the rising edge, scan a RAM window for a known `.sfd`
  basename (the Sofdec/mwPly library keeps the filename string live). Gives us
  the identifier without needing a stable index address.

This is the only step that needs a person at the emulator. Recipe in §6.

## 5. Known hard parts (validate in prototype)

- **Handoff latency** — the overlay must appear within ~1–2 frames of the rising
  edge or the SD original flashes. Mitigation: fast poll + a 1-frame black cover.
- **Skip handling** — user skip clears FMV-active; teardown keys off overlay-end
  OR that falling edge, whichever first.
- **Turbo side-effects** — some games gate logic/audio on real-time FMV
  playback; if XS3 misbehaves under turbo, fall back to `pause-and-resume`.
- **Save-states / alt-tab / window focus** — pynput hotkeys need PCSX2 focused;
  daemon should re-assert focus before sending keys.

## 6. Build phases

| Phase | Deliverable | Needs live game |
|-------|-------------|-----------------|
| 0 | this doc + `fmv_state_hunt.py` + `fmv_reloader.py` scaffold | no |
| 1 | run the hunt → fill `fmv_reloader.json` (addresses + name map) | **yes** |
| 2 | single-FMV proof: one cutscene, turbo-underlay handoff | yes |
| 3 | full-disc sweep + the extract→upscale generator wiring | — |
| 4 | XS1 port (same `pine.py`; XS1 FMV format TBD), splash packaging | — |

### Phase 1 hunt recipe

```
# with XS3 booted in PCSX2, standing in normal gameplay (not an FMV):
python3 flag-hunt/fmv_state_hunt.py snap gameplay
# now trigger a cutscene, and while it plays:
python3 flag-hunt/fmv_state_hunt.py snap fmv1
# after it ends, back in gameplay, trigger a different cutscene, during it:
python3 flag-hunt/fmv_state_hunt.py snap fmv2
python3 flag-hunt/fmv_state_hunt.py solve      # -> candidate FMV-active bytes
python3 flag-hunt/fmv_state_hunt.py findname <iso>   # during an FMV: locate the .sfd name string
# write the winners into fmv_reloader.json
```
