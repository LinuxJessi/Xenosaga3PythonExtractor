# Depack / repack: the full mod loop for Xenosaga III

The kit's extraction pipeline (prep → scan → extract) is the **depack**
half: it mirrors every file on the disc into a `dump/` tree.
[`repack.py`](../repack.py) is the **repack** half: it writes files back
into an ISO, in place, for *any* file type on either disc — models, audio,
movies, event packages, textures, tables.

The character-texture tools ([MODDING-CHARACTERS.md](MODDING-CHARACTERS.md))
are a format-aware front end; this layer works on whole files and is
format-agnostic.

## The loop

```sh
# 0. depack once (or reuse your existing dump/) — see the README pipeline
# 1. start a mod tree containing ONLY the files you change,
#    mirroring the in-game paths:
mkdir -p mymod/mdl/chr/pc
cp dump/mdl/chr/pc/C3shion00.chr mymod/mdl/chr/pc/
#    ... edit mymod/mdl/chr/pc/C3shion00.chr with whatever tool ...

# 2. clone the ISO (instant on APFS) and repack the tree into it
cp -c "Xenosaga ... (Disc 1).iso" MOD.iso
python3 cli.py repack-tree --iso MOD.iso --mod mymod --dry-run   # preview
python3 cli.py repack-tree --iso MOD.iso --mod mymod             # do it
```

Every write is read back and verified. The GUI exposes this as card 14;
single files go through `repack-extract` / `repack-patch`, and
`repack-info` shows where any path lives:

```
$ python3 cli.py repack-info --iso MOD.iso --path '\mdl\chr\pc\C3kosmos00.chr'
\mdl\chr\pc\C3kosmos00.chr
  table   Lba0.txt   offset 0x0CCF6000   size 432384 (0x69900)
  lives in X3.01 -> ISO byte 0xD326800
  sector allocation 434176 bytes (1792 slack)
```

## Disc model (why this works, and its one hard limit)

Files hide inside the `X3.*` containers, indexed by three byte-addressed
tables: `Lba0` (shared system/model/audio data — **byte-identical on both
discs**, so one mod tree patches Disc 1 and Disc 2 copies with identical
commands), `Lba1` (Disc 1 story content, X3.11–13), `Lba2` (Disc 2 story
content, X3.21–23). `repack.py` reads the ISO's own root directory for the
container extents, so it works on any dump of either disc; it auto-detects
which tables apply and refuses paths from the wrong disc.

The engine's on-disc catalogs (`X3.00` / `X3.10` / `X3.20`) store the file
tree with **literal sizes but implicit offsets** — files pack back-to-back
at 2048-byte sector granularity, each starting on the sector after its
predecessor's last. Consequences:

* **Same-size replacement** — always safe. This is the default; anything
  else is rejected.
* **Different size within the sector allocation** (`--pad`): the file is
  zero-padded to its original allocation so nothing moves. The engine
  still *reads* the original byte count, so this is only correct for
  formats that carry their own internal sizes and ignore trailing bytes
  (Xc/`.chr`/`.sme` packages, `txy`, ADX). Opt-in for that reason.
  `repack-info`'s "slack" line tells you the headroom (0–2047 bytes,
  whatever the original left in its final sector).
* **Anything bigger** means every later file in that container shifts and
  the binary catalog's size chain must be rewritten — a full container
  rebuild. Nothing supports that yet; it is the known limit. (The catalog
  format is a front-coded name trie with LE32 sizes — decoded enough to
  know the layout, not enough to regenerate. Future work.)

## Practical notes

* Always patch a **copy** (`cp -c` on macOS is a free clone). Keep your
  originals pristine.
* Patched ISOs boot in PCSX2 and on real hardware — there are no
  checksums or anti-tamper anywhere in the read path.
* Testing in PCSX2: load from a memory-card save, not a savestate —
  savestates restore the *old* data from saved RAM/VRAM until the game
  re-streams it (any map change).
* Duplicate data: unlike Xenosaga I (which buries byte-copies of textures
  inside battle/scene bundles), XS3 keeps one file per asset. What *does*
  repeat is per-variant data — each costume/cutscene model is its own
  `.chr` with its own palettes — so "change X everywhere" means patching
  every variant file, which is what mirror trees and `chr-iso-sweep` are
  for.
* `--lba` points the resolver at a different directory of `Lba*.txt`
  tables if you're not using the kit's bundled ones.
