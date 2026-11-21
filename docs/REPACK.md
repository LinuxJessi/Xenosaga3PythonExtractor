# Depack / repack: the full mod loop for Xenosaga III

The kit's extraction side (`dump`, `browse`, the format tools) is the
**depack** half. The **repack** half writes files back into a disc image, for
*any* file type on either disc — models, audio, movies, event packages,
textures, text tables, the boot ELF.

Since 2026-11-20 every write finds its file through the disc's **own**
`X3.00` / `X3.10` / `X3.20` index (`disc.py`), not the bundled `lba/*.txt`
tables, so the same commands work on the USA discs, the May 2006 prototype and
the Japanese discs. `lba/` is kept only as a test oracle (the self-tests check
that the USA index matches it row for row: 9,867 / 3,649 / 1,709).

There are two front ends:

| command | module | writes | sizes | discs |
|---|---|---|---|---|
| `patch` | `patch.py` (`patch_copy`) | **copies** of the images | any (with `--grow`) | one image or a Disc 1 + Disc 2 pair |
| `repack-patch` / `repack-tree` | `repack.py` | the image you give, in place | same size, or fits the allocation (`--pad`) | one image |
| `chr-iso-patch` / `chr-iso-sweep` | `chrtex.py` | the image you give, in place | same size | one image |

Importers (text, fonts, textures, subtitles) call `patch.patch_copy`.

## The loop

```sh
# 1. a mod tree holding ONLY the files you change, mirroring in-game paths
mkdir -p mymod/mnu/us
python3 cli.py repack-extract --iso D1.iso --path '\mnu\us\menutext.txd' --out mymod/mnu/us/menutext.txd
#    ... edit it ...

# 2. write it into copies of BOTH discs (the source images are never written)
python3 cli.py patch --iso D1.iso --iso D2.iso --out modded/ --tree mymod --dry-run   # plan + budget
python3 cli.py patch --iso D1.iso --iso D2.iso --out modded/ --tree mymod --grow
#    single files: --set 'mnu\us\menutext.txd=edited.txd'  (repeatable; prefix chainN: to force a chain)
```

`patch` clones each source with APFS `clonefile` on macOS (no 4 GB copy, no
disk space until bytes change), a reflink on Linux, or a hole-preserving
stream copy elsewhere; patches the clone as `<name>.partial`; verifies; and
only then renames it to `OUT/<source name>`. A refusal or a failed check
leaves no output behind.

`repack-info` shows where a path lives and how much room it has:

```
$ python3 cli.py repack-info --iso D1.iso --path '\mnu\us\menutext.txd'
\mnu\us\menutext.txd
  index   X3.00 (chain 0)   sector 4001   size 15388 (0x3C1C)
  lives in X3.01 +0x7B5000 -> LBA 7115, ISO byte 0xDE5800
  allocation 16384 bytes (996 slack)
  chain 0: the same file is on Disc 1 and Disc 2 (patch both: cli.py patch --iso D1 --iso D2)
```

## Disc model

Files live in three chains of `X3.*` containers; each chain starts with its
index file, and an entry's data sits at **index LBA + entry sector** (the
engine's raw-sector rule, `FUN_00187e28` / `FUN_00188148`). Every index entry
stores an explicit u24 sector and u32 size, so a file can be resized or moved
by rewriting only its own fields; nothing else moves.

| chain | files | on | notes |
|---|---|---|---|
| 0 | `X3.00`–`X3.02` | both discs | index byte-identical on Disc 1 and Disc 2 |
| 1 | `X3.10`–`X3.13` | Disc 1 (and the prototype) | |
| 2 | `X3.20`–`X3.23` | Disc 2 | |

Do not assume index sizes: USA `X3.00` is 55 sectors at LBA 3114; Japanese
`X3.00` is 58 sectors at LBA 3110, `X3.10` 26 and `X3.20` 13. Every chain is
packed to the sector except the Japanese `X3.02`, whose last file
(`mnu\jp\font0.bin`, 494,592 bytes) has 1,024 bytes of tail slack (its
allocation is 495,616).

## What `patch_copy` does with each changed file

1. **Where.** A chain-0 path is written on **every** image given; a chain-1
   path only on Disc 1; a chain-2 path only on Disc 2. A path no index holds is
   looked up in the ISO9660 filesystem (`SYSTEM.CNF`, the boot ELF,
   `OV0x.OVL`, `IOP\*`) and written on every image that has it. The `X3.nn`
   containers themselves are never written whole.
2. **In place** when the new bytes fit the entry's allocation (gap to the next
   entry's sector): overwrite, clear the stale tail, rewrite the index's u32
   size field (`Disc.write_entry`). ISO9660 files: in place when they fit
   before the next extent, the directory record's length rewritten
   both-endian.
3. **Grown** (`--grow` only) when they do not fit, or when the entry starts on
   another file's sector (four zero-size entries on Disc 1, e.g.
   `ef\esd\ee100\ee105_028.esd` on `ee106_001.esd`; an in-place write would
   destroy the neighbour): appended after the last sector of the image, the
   index entry's sector and size rewritten, the PVD volume size bumped
   (`Disc.append_entry`). ISO9660 files: appended and their directory record
   repointed.
4. **Pairs keep X3.00 identical.** On a Disc 1 + Disc 2 pair, every grown
   chain-0 file lands on the **same LBA on both discs**: the shorter image is
   first padded with zeros (sparse) to the longer one's end. This keeps `X3.00`
   byte-identical across the pair, which is safe whether or not the engine
   re-reads the index after a disc swap (not established). Cost: USA Disc 1
   grows from 1,915,920 to Disc 2's 2,205,056 sectors on its first chain-0
   grow (Japanese: 1,984,400 → 2,259,440). Patching chain-0 files on one disc
   alone prints a warning, because the other disc's copy then differs.
5. **Budget, checked before anything is copied.** The grown image must stay
   within the DVD-5 sector count (2,295,104; every known XS3 image is
   single-layer) or DVD-9 (4,173,824) for a dual-layer image. Room for
   chain-0 growth on a pair: USA 90,048 sectors (≈184 MB), Japan 35,664
   (≈73 MB). `--ceiling none|N` raises it for emulator-only images (one
   volume past DVD-5, no layer break: not burnable, PCSX2 untested; the kit
   warns). `--ceiling dvd9` is refused on a single-layer image.

Refused outright: mixed builds (USA + Japanese, or the prototype next to a
retail disc; told apart by executable sha256 since the prototype reuses
`SLUS_213.89`), unknown builds, two images of the same disc number, `X3.00`
differing between the pair, compressed entries (none exist on any known XS3
image), growth without `--grow`, the ceiling, `--ceiling dvd9` on a
single-layer image (the result would be one volume past DVD-5, not a DVD-9;
use `none` or a number for emulator-only images), and an output path that
already exists (it could be an original; `--overwrite` replaces an earlier
output of the kit). A chain-0 change on ONE image of a pair only warns, but
that image's `X3.00` then differs from the other disc's for good, so the two
can no longer be patched together for chain-0 objects.

A pair's boot executables (`SLUS_213.89` / `SLUS_214.17`, `SLPS_256.40` /
`SLPS_256.41`) are byte-identical: a change to one of them on a pair is
written to the other too (refused if they differ), so statfont and unlock
edits made from Disc 1 reach Disc 2.

Re-patching an output works on the same rules. An entry already moved past
its chain's end may grow in place only up to the next object on the image,
whatever chain or ISO9660 file owns it (`Disc.allocation`).

Only the ISO9660 side of these ISO9660 + UDF bridge images is kept
consistent: after a grow the UDF anchor and partition still describe the old
size, and a rewritten ISO9660 file's UDF record keeps the old extent.

**Verification** re-opens every output: no two files overlap on the image
that did not already overlap in the source (every sized entry of every chain
and every ISO9660 file, by absolute byte range); each changed path reads back equal to
the new bytes; every index parses and re-serializes byte for byte with the
same entry count; every untouched entry keeps its sector and size; `X3.00` is
still identical across a pair; the ISO9660 volume size equals the image size;
and an evenly spread sample of untouched entries plus the boot ELF keeps the
source's sha1.

## Tested (2026-11-20, on clonefile copies; originals never written)

* USA Disc 1: same-size `menutext.txd` in place; 100 bytes shorter → the u32
  size field on the image reads 15,288.
* USA Disc 1 + Disc 2: `menutext.txd` grown to 23,388 bytes lands at LBA
  2,205,056 on both discs, `X3.00` identical; `mov\us\s073600.txt` (chain 1)
  appended past `X3.13` on Disc 1 only; `mov\us\s100900.txt` (chain 2) past
  `X3.23` on Disc 2 only; `font1.bin` same-size on both. Both outputs parse,
  every index rebuilds.
* Japanese Disc 1: same-size `mnu\jp\menutext.txd`, an edit of string #116
  in `cf\jp\1220.sb` (in place, 40,324 → 40,328 bytes, re-extracted equal) and
  `mnu\jp\font1.bin` grown; Japanese pair: a chain-0 grow at LBA 2,259,440 on
  both, `X3.00` identical.
* Prototype: same-size patch through its own index.
* Refusals: USA + Japanese, USA + prototype, growth without `--grow`, a
  200 MB pair grow (DVD-5), a Japanese pair grow one sector past DVD-5, the
  shared-sector entry in place.

**Booted in PCSX2 (2026-11-20), USA Disc 1 only.** A chain-0
`mnu\us\synopsis.txd` grown from 46,700 to 47,195 bytes (allocation 47,104)
was appended past the old end of the image on a D1 + D2 pair (Disc 1 padded
from 1,915,920 to 2,205,080 sectors); the game loaded it from there and showed
the new text, and the field loaded after it. So the grow rule (index LBA +
sector past the last container) and the Disc 1 padding hold in PCSX2. Same-size
in-place text, in-place rewrites within the allocation (398 `.sb` scenes and
`menutext.txd`) and the fonts plus the patched boot executable also booted
(UPDATES.md). Not booted: Disc 2, a disc swap, chain-1/chain-2 appends,
ISO9660-file appends, a real PS2.

## `repack.py` / `chrtex.py` in place

`repack-patch` writes one file into the image you give: same size by default;
`--pad` allows any size up to the allocation and **rewrites the size field**
(before 2026-11-20 `--pad` zero-padded and left the old size in the index, so
the engine kept reading the old length — fixed). Anything larger needs
`patch --grow`. `chr-iso-patch` is same-size only; `chr-iso-sweep` recolors
every matching `.chr` in every chain of the image. `--lba` is accepted and
ignored with a note.

## Practical notes

* Always work on copies; `patch` does this for you. For the in-place commands,
  `cp -c` on macOS is a free clone.
* There are no checksums or anti-tamper in the read path.
* Testing in PCSX2: load from a memory-card save, not a savestate — savestates
  restore the *old* data from saved RAM/VRAM until the game re-streams it.
* Region-variant files share paths only within a build: never mix Japanese and
  USA files, or prototype and retail files, in one image (`patch` refuses mixed
  image sets; it cannot tell where a file *you* supply came from).
* XS3 keeps one file per asset, but per-variant data repeats (each costume or
  cutscene model is its own `.chr`), so "change X everywhere" means patching
  every variant — what mirror trees and `chr-iso-sweep` are for.
