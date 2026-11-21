# Motion: `.xap` body clips and `.fap` face clips

What the kit knows about Episode III's motion, how each fact was established,
how the exporter turns it into glTF animations, and what is still open. Code:
`xap.py` (decoder, engine pose, glTF tracks), the animation helpers in
`gltf.py`, and the `model` / `models` / browse hooks in `models_sweep.py`.
`xap.py` is the Episode II kit's module with changes for Episode III; its
docstring lists each one. Episode II's `docs/MOTION.md` has the parts both
games share in full: the key walk, the cubic, the matrix order, the visibility
walk. This page covers what Episode III changes, plus the numbers from the
Episode III discs.

Evidence, as in [MODELS.md](MODELS.md):

* **code**: read from SLUS_213.89, routines named by address only
  (`FUN_<addr>`), from the Ghidra output in `xenosaga3-decompiled/` and, where
  it was unclear, the disassembly (gp = 0x5571f0, read from the entry code at
  0x1201c0);
* **number**: a sweep over a disc's files (`python cli.py motion --iso D1.iso
  --sweep`);
* **image**: Blender renders of KOS-MOS and Shion.

**Nothing on this page has been compared with the running game.** The poses
come from the executable's formulas and look right in Blender. Whether the
game shows the same thing frame for frame, and at what speed, has not been
checked. A PCSX2 side-by-side would settle it (see "Unverified").

## Reproducing

```sh
python xap.py --self-test
python cli.py motion --iso "Disc 1.iso" --sweep                        # every clip on the disc
python cli.py motion --iso "Disc 1.iso" --path 'pac\cf\C3kosmos00.sme'  # one file's clip table
python cli.py motion --iso "Disc 1.iso" --path 'pac\cf\C3kosmos00.sme#1' \
       --xhr 'mdl\chr\pc\C3kosmos00.chr' --frame 10                     # one pose, per transform
python cli.py model --iso "Disc 1.iso" --path 'mdl\chr\pc\C3kosmos00.chr' --out kosmos.glb
python cli.py model --iso "Disc 1.iso" --path 'mdl\chr\pc\C3kosmos00.chr' --out kosmos.glb \
       --motion 'pac\cf\C3kosmos00.sme#1,2' --motion 'pac\bat\C3kosmos00.sme#0,21'
python tools/demo/motion_check.py "Disc 1.iso" out/motion-check          # read-back report
blender -b --factory-startup --python tools/demo/motion_blender_check.py -- out/motion-check/*.glb
```

The front-page GIFs: `docs/gallery/render_motion.py` (Blender, EEVEE) renders
the frames and `docs/gallery/make_gif.py` joins them. The commands are under
"Front-page pictures" below.

## Where motion lives

| where | count (Disc 1) | holds |
|---|---:|---|
| `pac\cf\*.sme` | 363 | field motion: MR package, slots `xap` (motion), `esp`, `dap` |
| `pac\bat\*.sme` | 200 | battle motion: `xap`, `esp`, `dat` |
| `mg1\com\Motion\MG*.sme` | 20 | minigame motion: `xap` only |
| `mdl\wpn\*.wpn` | 82 of 134 | a weapon's own clips in its `xap` slot (`shion_sp01a.wpn` holds only that) |
| `jpg\mv_*.xap`, `mnu\obj288.xap` | 29 | standalone `.xap` files |
| `mot\face_all.fap`, `jpg\C3_*.fap` | 21 | face clips |

(**number**) 715 motion files: 8,530 slots, 3,491 empty stubs and 5,039 clips.
Every clip decodes. The two USA discs, both Japan discs and the May 2006
prototype give identical counts (all five swept).

## What Episode III changes

Read from SLUS_213.89 (**code**), then checked by walking every clip on the
discs (**number**).

* **Clip versions.** XAC 1.4 (260 clips), 1.6 (2,231), 1.7 (2,514) and FAC 1.4
  (34) occur. `FUN_00299350` runs the body player `FUN_00299e98` for any
  XAC version >= 1.4 and the face player `FUN_0029ad70` for FAC >= 1.4 (the
  constants at gp-0x7130 / gp-0x712c are 1.4). Nothing below 1.4 is on the
  discs and Episode III has no player for it, so the parser refuses those.
* **Header.** The header is 0x50 bytes with eight count / offset pairs.
  Counts sit at +0x10..+0x2C and offsets (relative to the clip) at
  +0x30..+0x4C:

  | count | offset | stream |
  |---|---|---|
  | +0x10 | +0x30 | run A; the first block is the root (`FUN_002a3760`, read without a count check) |
  | +0x14 | +0x34 | run B |
  | +0x18 | +0x38 | run D, face joints (FAC clips only) |
  | +0x1C | +0x3C | run E, chains; 8-byte block header (mask, flags, f32) |
  | +0x20 | +0x40 | visibility list (`FUN_0029bd98` / `FUN_002a4918`, the Episode II walk) |
  | +0x24 | +0x44 | run C |
  | +0x28 | +0x48 | **new** "P": two entries, each a u32 the engine skips plus two curves |
  | +0x2C | +0x4C | **new** "Q": one pair list per set bit of the count word |

  The streams tile every clip exactly, in this order (**number**: 5,039 of
  5,039, no gap, no tail).
* **P (+0x28).** `FUN_00299e98` reads it only when the count is exactly 2 and
  the skeleton's word +0x60 is not 0. For each entry, `FUN_002a48b0` skips 4
  bytes and evaluates two curves. The first value goes to actor +0x114. Actor
  +0x11C gets a skeleton value (record at skeleton +0x64, +0x3C) minus the
  second value. What these drive is not traced. 2,431 clips have P entries.
  In 1.4 clips a count other than 0 or 2 is Maya junk (48 clips), as in
  Episode II.
* **Q (+0x2C).** No reader was found. In 1.6 and 1.7 clips the bytes are one
  list (i32 n, n x (f32 frame, u32 value)) per set bit of the count word, and
  that reading tiles all 503 clips that have lists. Treating the word as a
  plain count would not fit. In KOS-MOS's field clips 1 and 2 the word is 6:
  two lists, each with value 1 at one frame (8 and 27 of 38; 9 and 21 of 24),
  two per cycle like footfalls. That is a guess from the shape, not a traced
  meaning. 1.4 clips hold junk there (260).
* **One root.** XHR 3.0 starts run A with one 0x40-byte record
  ([MODELS.md](MODELS.md)). The first run-A block drives it unconditionally,
  so a body clip needs at least one run-A block (Episode II needed two).
  Block i >= 1 drives transform i while i is below the clip's run-A count.
  Every other block rule is Episode II's: past a run's count, transforms stay
  at their `.xhr` rest values, and extra blocks are ignored.
* **Key type 6** (new; 8 bytes): an s16 angle at +4 (in = out) and an s16
  value at +6, both fixed point divided by 4096 (`FUN_002a2dd0`,
  `FUN_002a2c08`, `FUN_002a2cf0`). There is a quirk: when a type-6 key ends
  the curve and is reached first, `FUN_002a2eb0` returns the raw s16 as a
  float, not divided (disassembly at 0x2a3090: `lh`, `cvt.s.w`). The decoder
  reproduces that. **No type-6 key occurs on any disc**, so the quirk is
  covered by the self-test only.
* **Scale thresholds.** For the root, runs A, B, C and the face run D, the
  scale is left out of the matrix when all three values are in [0.999,
  1.001) (gp-0x70d8 / -0x70d4). Run E skips it only at exactly (1, 1, 1). The
  current-scale slot keeps the keyed value either way, and that slot is what
  a compensated child divides by.
* **Parent-scale compensation** (block flags bit 0) applies to the root and
  runs A, B and C, and to run D in a face clip. It never applies to run E:
  `FUN_00299e98` stores the bit for run E but looks up no parent scale. The
  slot lookup `FUN_00299d10` treats the first two transforms as 0x40-byte
  records unless skeleton word +0x5C has bit 3 set, and no USA skeleton has
  it set. So a child of transform 1 reads transform 1's **rest** scale
  (record +0x28), not its current one. A child of a run-D transform reads
  record +0x3C. The decoder does both.
* **Face** (`FUN_0029ad70`, run D, own clock): as in Episode II, the keyed
  translation is applied only when the rest T is not zero. Unlike Episode
  II, the scale follows the threshold rule above rather than "only when the
  rest S is not 1".
* Everything else matches Episode II: the container (`"XAP "`/`"FAP "`, f32
  1.2, offset table), empty stubs (start > end, `FUN_00298910`), the
  block layout (u16 mask, u16 flags, one curve per set bit, T/R/S x/y/z), key
  types 0-3 and 5, the 0x8000 linear rule, the cubic on x = frame / 30
  (`FUN_002a4b78`, `FUN_002a4c90`; gp-0x704c = 1/30), linear segments
  (`FUN_002a4cd8`), and the matrix order (identity, T, invPS, JO z/y/x,
  R z/y/x, S, built by `FUN_00299e98` with the `FUN_002a1358`..`FUN_002a14d0`
  helpers):

      L = S * Rx(R.x) Ry(R.y) Rz(R.z) * Rx(JO.x) Ry(JO.y) Rz(JO.z) * invPS * T

## From clip to glTF

As in Episode II (`xap.add_to_glb`): one glTF animation per selected clip on
the `.glb` that `pxy.to_glb` wrote with the skeleton (nodes `t00`..`tNN`).
Every transform is keyed with T, R and S (rest values as a single key where
the clip does not drive it). The scale is the one the matrix uses, after the
threshold. There is no matrix decomposition. Frames run int(start)..int(end)
at 30 fps, and every transform is made a skin joint so Blender gives each one
a bone.

* **Names** are the disc path without the extension, then the slot:
  `pac/cf/C3kosmos00#01`, `pac/bat/C3kosmos00#21`, `mdl/wpn/kosmos_lc01#00`.
  The game's own names for the slots are not on the disc, so nothing is called
  "walk" or "idle" in the file. Captions on this page describe what a clip
  looks like.
* A clip whose block counts differ from the skeleton's carries them in its
  name and extras, clip/xhr: `pac/cf/C3kosmos00#05 [counts A5/30 B0/16
  E0/18]`. `model --matched-only` leaves such clips out.
* **Extras** per animation: the Episode II set (source, slots, version,
  start, end, fps, kind, counts, xhr_counts, max_shear_residual,
  visibility, e_extra, run_counts_differ, compensation), plus `p_28` (per
  entry: the skipped u32 and both curves sampled per frame) and `q_2c_mask` /
  `q_2c_lists`.

## Pairing a model with its motion

`model` without `--motion`, and `models` / browse kind `models`, add every
same-stem motion. A model takes its clips from `pac\cf\<stem>.sme` (field),
`pac\bat\<stem>.sme` (battle), any `<stem>.xap`, and a `.wpn`'s own `xap`
slot. Pairing is by file name only. Which motion the game binds to which
model is not traced beyond that, and names that differ (`MGkosmos00`,
`mv_E3obj002`, `C3_kosmos.sme`) are not guessed. `model --motion` takes any of
them by path. On Disc 1, 163 `.chr` models have a same-stem motion and 82
weapons carry their own; a clip is attached only when the mesh is skinned and
written with its skeleton. `models.csv` lists the clips per model in
`motion`, with the clips whose counts differ in `motion_counts_differ`.

(**number**, every disc) 3,447 clips pair with a skeleton by stem. 3,335 of
them have the skeleton's block count in every run they drive; 112 do not (run
A 37, run B 97, run E 25). Example: field slots 5 and 6 of `C3kosmos00` and
`C3shion00` have 5 or 7 run-A blocks and nothing else. They are probably for
a prop, but that is not known. Rest check, as in Episode II: the first
translation key of run-A joints 1 and up equals the `.xhr` rest translation
in 124,089 of 131,886 channels (0.941) when the counts match, and in 1,366 of
2,046 (0.668) when they differ.

## Checked

* **Self-test** (`xap.py`, part of `cli.py self-test`): hand-computed curves
  for every key type, including the type-6 raw last key; the vectorised
  evaluator against the literal transcription on random curves; 1.4, 1.6 and
  1.7 layouts with P and Q; damaged and refused input; poses against an
  independent column-vector composition; every scale and compensation rule
  above; the face rules; a synthetic skinned `.glb` read back and sampled the
  glTF way against `xap.pose` at every frame (1e-5); package motion slots,
  spec parsing and same-stem pairing. With `XS3_D1` etc. set, each disc's
  `pac\cf\C3kosmos00.sme` decodes, 12 of its 14 clips match the skeleton's
  counts, and clip 1 loops exactly.
* **Read-back** (`tools/demo/motion_check.py`, **number**): `C3kosmos00` (40
  animations) and `C3shion00` (43) as `model` writes them. Every frame of
  every animation was sampled from the `.glb` and compared with `xap.pose`.
  The worst node world-matrix difference is 2.4e-6 (1.4e-6 of the skeleton
  height), the gap between float64 and the file's float32. `gltf.validate`
  reports nothing.
* **Loops** (**number**): field slots 0-4 and 10-13 of KOS-MOS, and 0-4, 8,
  10 and 12 of Shion, end exactly on their first pose (gap 0). That includes
  clips 1 and 2, the walk- and run-like cycles. Disc-wide, 2,016 of the
  3,447 paired clips close within 1e-3. The rest are one-shots: attacks,
  turns, gestures.
* **Blender 5.4** (`tools/demo/motion_blender_check.py`, **image**): both
  files import; every animation becomes an action with the clip's frame
  range (40 of 40, 43 of 43); the armature has one bone per skin joint (82,
  74). The renders below came from those imports.

## Front-page pictures

| file | what it shows |
|---|---|
| `docs/images/front/motion-kosmos-shion-walk.gif` | KOS-MOS and Shion side by side, each playing field clip 1 (`pac/cf/C3kosmos00#01`, `pac/cf/C3shion00#01`, 38 frames, walk-like, in place), all 38 frames at 30 fps |
| `docs/images/front/motion-kosmos-battle-attack.gif` | KOS-MOS, battle clip 21 (`pac/bat/C3kosmos00#21`, 57 frames): a leap forward, a crouching slash, a lunge and the recovery; the clip carries her 2.7 m forward (root translation as keyed); every second frame, 15 fps |
| `docs/images/front/kosmos-turntable.gif` | KOS-MOS turning once, playing battle clip 0 (`pac/bat/C3kosmos00#00`, 90 frames, a stance-like loop); 60 frames |

```sh
python cli.py model --iso "Disc 1.iso" --path 'mdl\chr\pc\C3kosmos00.chr' --out C3kosmos00.glb
python cli.py model --iso "Disc 1.iso" --path 'mdl\chr\pc\C3shion00.chr'  --out C3shion00.glb
R=docs/gallery/render_motion.py
blender -b --factory-startup --python $R -- f_walk 38 "C3kosmos00.glb=pac/cf/C3kosmos00#01" \
    "C3shion00.glb=pac/cf/C3shion00#01" --size 440 460 --cam 25 6 --spacing 0.75
blender -b --factory-startup --python $R -- f_attack 29 "C3kosmos00.glb=pac/bat/C3kosmos00#21" \
    --size 600 420 --cam 40 6 --fit-all
blender -b --factory-startup --python $R -- f_turn 60 "C3kosmos00.glb=pac/bat/C3kosmos00#00" \
    --size 360 460 --cam 0 6 --turntable
python docs/gallery/make_gif.py f_walk   docs/images/front/motion-kosmos-shion-walk.gif --height 420 --ms 33
python docs/gallery/make_gif.py f_attack docs/images/front/motion-kosmos-battle-attack.gif --height 380 --ms 67
python docs/gallery/make_gif.py f_turn   docs/images/front/kosmos-turntable.gif --height 440 --ms 50
```

## Not reproduced

* **Chain simulation.** Hair and coat chains in run E are simulated after the
  pose in the game. The exporter writes their keyed or rest values, so
  KOS-MOS's hair hangs stiff.
* **Visibility lists, P and Q.** These are stored in the extras and not
  applied.
* **`FUN_0029c9a8`**, the player taken when actor word +0xE0 is set
  (probably a blend of two motions).
* **The run-time factor** actor +0xB0..+0xB8 on the root's local translation
  (1.0 unless something sets it).
* **Real-time rate.** Curves are 30 keys per second and the glTF is 30 fps;
  how fast the game advances a clip is unverified.

## Unverified

* **Anything against the running game.** No pose, speed or pairing has been
  compared with PCSX2. A PINE capture of the actor's local matrices
  (`pMRPack->pLocalMat`) while KOS-MOS walks would check the decoder
  frame by frame.
* What P and Q drive. That the Q word is a bit mask rests only on the lists
  tiling the clips.
* What the clips are. Captions such as "walk-like" and "attack" describe the
  renders; the game's names for the slots are not known.
* Which clips the game plays on which skeleton, including the 112 same-stem
  clips whose counts differ and the motion files whose names differ from
  every model's.
* The type-6 raw-last-key behaviour. It is read from the disassembly, but no
  disc file uses type 6.
* The map motion in `"PAM "` blocks ([MODELS.md](MODELS.md)) is a separate
  format and is not decoded.

## In Blender

Set the scene to 30 fps (Output Properties ▸ Frame Rate), then File ▸ Import
▸ glTF 2.0. Each clip is an action on the armature: in the Dope Sheet, switch
to the Action Editor and pick one (`pac/cf/C3kosmos00#01`). Bones are
`t00`..`tNN`; `t00` is the root that battle clips move.
