# Models: `.pxy` meshes, `.xhr` skeletons, texture link

What the kit knows about Episode III's model files, how each fact was
established, and what is still open. Using the output in Blender:
[BLENDER.md](BLENDER.md).

Code: `vif.py` (strict VIF walker), `pxy.py` (mesh decoder, invariants,
GLB export), `xhr.py` (skeleton), `gltf.py` (GLB writer/reader),
`models_sweep.py` (`model` / `models` commands, sweep, browse hook). The
first four are vendored from the Episode II kit
(`Xenosaga2PythonExtractor/`, same engine); each module's docstring says
what changed. Episode II's `docs/MODELS.md` holds the VU1-microcode
evidence for the parts both games share (batch layout F, strip rule,
skinning, palette slots, material batch); this page covers what Episode
III adds and the numbers from Episode III discs.

Evidence kinds, as in the Episode II page:

* **code**: read from SLUS_213.89 (functions named `FUN_<addr>`);
* **number**: a sweep over a disc's files, with the count;
* **image**: looked right in a software render or a Blender import.

## Reproducing

```sh
python cli.py models --iso "Disc 1.iso" --iso "Disc 2.iso" --iso "proto.iso" --out out/models
python cli.py model --iso "Disc 1.iso" --path 'mdl\chr\pc\C3kosmos00.chr' --out kosmos.glb
python pxy.py some.chr --glb some.glb        # summary + every counter of check()
XS3_D1="Disc 1.iso" python models_sweep.py --self-test
```

The sweep reads files through the disc's own X3.00 / X3.10 / X3.20
indexes (`x3index.py`): a file's ISO offset is (index extent + sector) x
2048. That works unchanged on the May 2006 prototype, whose layout
differs from the retail `lba/` tables.

## Where models live

A disc has 1,609 models (all in X3.00, so both USA discs and the
prototype carry the same set):

| | count | holds |
|---|---:|---|
| `mdl/**.chr` | 919 | MR package: `pxy`, `txy`, `xhr`, `epf` |
| `mdl/**.wpn` | 134 | MR package: `pxy`, `txy`, `xhr`, `epf`, `xap` |
| `mdl/map/**.map` | 474 | MR package: `pxy`, `txy`, `id`; field maps (`E3_*`) are LZSS-compressed (`xcpack.py`) |
| standalone `.pxy` | 82 | 55 under `mg1/`, 23 under `mdl/` (mostly `map/ev/`), 4 under `mnu/`; the `.txy` (and in two cases `.xhr`) of the same name sits beside each |

Package sub-resource data starts at 0x40 + the directory offset (the
directory itself is at 0x40); `pxy` in `C3kosmos00.chr` is at file 0x80
and its own size field equals the directory size (**number**: all 1,589
non-empty packages parse with that rule). 20 packages have an empty
(size 0) `pxy` slot: 19 field maps and `shion_sp01a.wpn`.

The `.pxy` is the full render mesh, not a proxy or collision mesh (the
decoded meshes are the textured characters and rooms; **image**).

## `.pxy` version 0.15

Header, tables, draw list and draw items are the Episode II layout
unchanged (`pxy.parse`; **number**: 1,588 files version 0.15 and one 0.14
on Disc 1, every table in range, the draws tile the VIF region exactly).
The VIF stream is the same `STCYCL 1,1; UNPACK...; MSCNT` batches. What
is new is two mesh-batch layouts. Each batch identifies its own layout
from its first two UNPACKs, so a file may mix them.

**Layout F** (Episode II's): V4-32 x (2n+1) = header, n x (x, y, z, S),
n x (nx, ny, nz, T) with bit 0 of T = strip restart; colours V4-8 at
2n+1, face normals at 3n+1, weights at 4n+1, palette bytes at 5n+1. Disc
1: 191,579 batches in 1,308 files.

**Layout Q** (quantized). Disc 1: 43,133 batches in 61 files, among them
KOS-MOS 00/01/04/05/07/17, Shion 00/04/06/07/13/99/H06, Momo 01, T-elos,
`E3eru01`-`04`, many `E3obj069*`/`070*`, enemies `mac*`, `mon*`, `rob*`,
`top*`, and three weapons.

    +0      V4-32 x 1: x = n | 0x8000, y = kind, z = f32 position scale,
            w = flags (bit 0 colours, bits 1-4 skin mode)
    +1      ONE signed (USN = 0) UNPACK V4-16 of 2n rows:
            n x (x, y, z, S) then n x (nx, ny, nz, T), all i16
            pos = i16 * scale / 4096     nrm = i16 / 4096
            S = i16 / 4096, T = (i16 & ~1) / 4096
    +2n+1 / +4n+1 / +5n+1   colours / weights / palette, as in layout F

Evidence (**number**): the largest |y| integer in each KOS-MOS draw is
exactly 28672 (7.0 in 1/4096), and pos = i16 * scale / 4096 puts every
vertex of every Q file inside its draw item's box and sphere (0 outside);
normals come out unit length (0 of 3,833,907 normals on Disc 1 off by
more than 0.2 %); u = S / SW lands in [0, 1] for every vertex under a
REGION_CLAMP material. There is **no restart bit**: treating the batch as
one strip gives n - 2 triangles per batch and the header's triangle count
in all 61 files (KOS-MOS: sum(n - 2) = 5049 - 2 x 911 = 3227). Skin modes
2 / 4 / 8 occur (31,847 / 8,071 / 3,215 batches). Not found in code: the
VU program that applies the scale (a guess is ITOF12 then a multiply).

**Layout U** (unlit field maps). Disc 1: 567,965 batches in 428 files.

    +0      V4-32 x (n+1): header, then n x (x, y, z, S) as floats
    +n+1    S-32 x n: T (float) with bit 0 = strip restart, as in F
    +2n+1   V4-8 colours (baked lighting, 128 = 1.0)
    +3n+1   optional V4-32 face normals (188,511 batches)

No vertex normals and never a skin mode (**number**: 0 of 567,965).
Header y (kind) is 0 or 3 here as in the other layouts. The face-normal
block points opposite to the strip-parity geometric normal for 1,397,509
of 1,512,584 triangles (92.4 %), the same relation Episode II's
static-file face normals have (93.5 %).

Export of layout U: COLOR_0, no NORMAL, a `KHR_materials_unlit`
material, and the strip-parity winding as stored (the facing turn and
the "strips face one way" check need vertex normals and are skipped).
Whether the strip winding of maps is right in a culling viewer is not
proven: materials are double-sided.

**Batch limits** (**number**): n <= 30 in all three layouts (the Episode
II limit); kinds 0 and 3 in all three.

**Material batches** are the Episode II layout unchanged (shader id, SW
and TW, TEX0, CLAMP, ALPHA); 230,642 textured material batches on Disc 1.

## Texture link

Every textured material batch names its texture by GS address:

    TEX0.TBP0 - 0x3800 == txy entry word +0x00 (the entry's GS address)
    TEX0.CBP  - 0x3800 == entry CBP
    SW * TEX0 width == entry width,  TW * TEX0 height == entry height

(**number**: 0 unlinked and 0 size mismatches over 230,642 textured
material batches on Disc 1, and the same on Disc 2 and the prototype.)
This is the Episode II rule unchanged; it closes the "pxy mesh ->
texture entry" thread of `chr-txy-format.md`. The kit's `chrtex.py` now
keeps that word as `gsaddr` in each parsed entry.

Textures are decoded by `chrtex.py` for package txy blocks and for
standalone `.txy` files alike (a standalone `.txy` is the same format
without the 0x40-byte package pre-header; it does carry pixels). For
two-bank field-map txy the chrtex bank overlay is used: Episode II's
`txy.py` gives different pixels for 95 of 152 entries of `E3_ELS01`, and
chrtex's overlay was tuned on Episode III. About twenty entries per map
take their palette from run-time state and look noisy.

## Skeleton (`.xhr` 3.0)

Every Episode III skeleton is version 3.0 (1,017 on Disc 1; the loader
`FUN_00299350` asserts `fileVersion >= CURRENT_XHR_VERSION`). Header and
run counts are the 2.x ones; the records are wider:

| run | Episode II (2.3/2.4) | Episode III (3.0) |
|---|---|---|
| A | two 0x40 records, then 0x50 | one 0x40 record, then 0x60 |
| B, C | 0x50 | 0x60 |
| D | 0x70 | 0x70 |
| E | 0xB0 + 0x10 x sum(three i32 at +0x1C) | 0xD0 + 0x10 x sum |
| F | 0x40 | 0x40 |

Field offsets inside each record are the Episode II ones (parent i32 at
0, T at 4, JO at 0x10, R at 0x1C, S at 0x28; run D T at 0xC; run E T at
0x30). Evidence (**number**): on all 1,017 skeletons of each disc run A
ends exactly where run B starts, B/C/D tile, and run E ends at or before
run F; joint matrix j of the `.pxy` binds to transform j + 2 as in
Episode II; the GLB rest pose reproduces the stored mesh within 2.2e-6
(model units) over 1,014 skinned models per disc (KOS-MOS: 4.9e-8). The
tables after run F are not decoded (not needed for the bind pose).

As in Episode II, some inverse bind matrices no vertex uses do not match
the transform at their index (106 models on Disc 1; the `.xhr` value is
kept, the `.glb` says so in `extras.warnings`), and in 21 models the
skeleton's rest values differ from the mesh's bind pose on joints that
vertices use (party models such as `C3chaos00`, `C3momo00`,
`C3kosmos04`, several NPCs, `top001`, `top024`): the bind pose is used,
so the mesh is exact, but those bones' rest transforms come from the
mesh, not the `.xhr`. Not resolved.

**Palette slot past the list.** Files with more than 64 joint matrices
upload, per node, the matrices named by the node's zero-terminated
1-based list. In `mdl\obj\E3obj287.chr` and `mdl\rob\npr\M3_npcr15.chr`
(the same mesh) node `combine` lists 63 joints, filling its 0x40-byte
field up to the terminator, yet 125 vertices use slot 63. Their centroid
sits 0.079 from joint 24, one of the five joints missing from the list,
and the list ends with the run 16, 17, ... 24 (1-based), which would
continue with 25 = joint 24, but which matrix the engine has in slot 63 was not traced. The
exporter leaves those vertices on the skeleton root and reports them
(`palette_overrun` in `check()`, a warning in the `.glb`). Any other
slot past a list still raises.

## Sweep

`python cli.py models --iso D1 --iso D2 --iso PROTO --out ...` (about
100 s per disc on 8 cores), each disc:

* 1,609 models: 1,586 decode, pass every check, write a `.glb` and read
  it back; 20 have an empty pxy slot; 3 are "unexplained": a non-empty
  pxy that decodes to 0 draws and 0 triangles, so no `.glb` is written
  (`map\cf\E3_HAK01_EV03.map`, `map\cf\E3_HAK16.map`,
  `map\ev\E3_HAK01_EV03.pxy`); 0 decode failures, 0 check failures
  (re-run 2026-11-20 on USA Disc 1 and Japan Disc 1).
* Decoded triangle count == header triangle count in all 1,586, and the
  read-back `.glb` has the same count.
* Files per layout: F 1,308, Q 61, U 428 (Japan Disc 1: F 1,307, Q 62,
  U 428).
* Triangles: 8,005,633 (USA Disc 1 and Disc 2), 8,005,679 (prototype:
  `map\bat\KYO_B02.map` and `map\cf\E3_KYO06.map` differ, every other
  model decodes to the same counts).
* Textured material batches unlinked: 0. Vertices outside their item
  box or sphere: 0. Weight rows not summing to 1: 0.
* Skinned: 1,014; skinned rest-pose error at most 2.2e-6.
* Facing (layouts F/Q): 2,459,461 of 2,491,810 non-degenerate triangles
  agree with their vertex normals; 531,122 of 533,251 strips face one
  way.

A model passes only if it decodes without any structural surprise
(unknown layout, VIF command, UNPACK flag, address, skin mode, palette
byte) *and* passes: triangle count = header; every vertex inside its
item's box and sphere; weight rows sum to 1; normals unit length;
strips face one way (layouts F/Q); every textured material batch finds
a txy entry at its address with its size; the `.glb` reads back with
the header's triangle count and, when skinned, a rest pose within 1e-5.

Blender (**image**): headless imports into Blender 5.4 of KOS-MOS
(28 meshes + armature of 76 joints, 53 images), `kosmos_lc01.wpn`,
`E3_ELS01.map` (14,921 triangles, 67 images, unlit), `mnu\umn.pxy` and
`E3obj287` finish without error with the expected triangle counts.
Software renders of KOS-MOS, Allen and `E3_ELS01` looked right.

## Open

* Motion (`.xap` in `.wpn` packages and elsewhere), the `epf` slot, the
  `.xhr` tables after run F.
* What the position scale of layout Q is applied by (VU code), and why
  some models are quantized.
* Strip winding of layout U against a culling renderer; the face-normal
  block is not exported.
* The 21 skeletons whose rest pose differs from the bind pose; the
  slot-63 joint of `E3obj287` / `M3_npcr15`.
* Colour scale (128 = 1.0, clipped above), alpha modes (the Episode II
  group rule), handedness: not checked against the running game.
* Japan Disc 1 was swept (2026-11-20): 1,586 ok, 20 empty, the same 3
  unexplained, 8,007,064 triangles (USA 8,005,633), header == decoded in
  every model, 1,014 skinned. Which models differ from USA was not
  broken down; Japan Disc 2 was not swept.
