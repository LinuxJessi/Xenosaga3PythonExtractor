"""patch.py — write a set of changed files into copies of an Episode III disc (or a Disc 1 + Disc 2 pair).

New for this kit (2026-11-20). ``patch_copy`` is the one write layer every
importer (text, fonts, textures, subtitles, models) calls; the single steps
underneath are the ``disc.Disc`` write primitives, which find every file through
the disc's OWN X3.00 / X3.10 / X3.20 index, so the same code patches the USA
discs, the May 2006 prototype and the Japanese discs. The copy-then-patch shape
and the ISO9660 file steps follow Xenosaga2PythonExtractor/repack.py
(``patch_copy`` / ``patch_fs_file`` / ``relocate_fs_file``); the pair handling
and the sector budget are new.

    from patch import patch_copy
    patch_copy([d1, d2], "out/", {"mnu\\\\us\\\\menutext.txd": new_txd,      # chain 0: both discs
                                  "cf\\\\us\\\\2940.sb": new_sb},             # chain 1: Disc 1 only
               grow=True)

What happens, per changed path:

* where it lives: looked up in each image's index. A chain-0 object (X3.00
  family, byte-identical on both discs) is written on EVERY image given; a
  chain-1 object only on Disc 1, a chain-2 object only on Disc 2. A path no
  index holds is looked up in the ISO9660 filesystem (SYSTEM.CNF, the boot
  ELF, OV0x.OVL, IOP modules) and written on every image that has it. The
  X3.nn containers themselves are never written whole. A key may also be a
  ``(chain, path)`` tuple to name the chain explicitly. Each disc boots its
  own executable (SLUS_213.89 / SLUS_214.17, SLPS_256.40 / SLPS_256.41,
  byte-identical within a pair): a change to one image's boot executable on a
  pair is written to the other's too (refused if the two differ), so a
  statfont/glyph-unlock edit made on Disc 1 reaches Disc 2.
* in place when the bytes fit the entry's allocation (the gap to the next
  entry's sector; chain end for the last entry, which on the Japanese X3.02
  includes its 1,024 bytes of slack): ``Disc.write_entry`` overwrites, clears
  the stale tail and rewrites the u32 size field in the index.
* grown (``grow=True`` only) when they do not fit, or when the entry starts
  on another file's sector (``Disc.sharers``; an in-place write would destroy
  the neighbour, so it is refused without ``grow``): the bytes are appended
  after the last sector of the image and the index entry repointed
  (``Disc.append_entry``; engine rule LBA = index LBA + sector, proven for XS1
  in game, NOT booted in PCSX2 for XS3). On a pair, every grown chain-0 object
  lands on the SAME LBA on both discs: the shorter image is first padded
  (sparse zeros) to the longer one's end, so X3.00 stays byte-identical
  across the pair whether or not the engine re-reads it after a disc swap.
* the sector budget is checked before anything is copied: the grown image
  must stay within the DVD-5 sector count (single-layer image; every known
  XS3 image is single-layer) or DVD-9 (dual-layer), unless ``ceiling`` says
  otherwise (``0`` = none, for emulator-only images).

Refusals (``PatchError``, raised before any output exists): mixed builds or
regions (``region.mixed_regions``: the prototype next to a retail disc, USA
next to Japanese), an unknown build (``region.require_known``), two images of
the same disc number, X3.00 differing between the two images while a chain-0
object is changed (which is what a chain-0 change made on ONE image of a pair
leads to for good: such a single-image write only warns, but the two images
can no longer be patched together for chain-0 objects; patch the pair from the
originals instead), compressed entries (none exist on any known XS3 image),
growth without ``grow``, the sector ceiling.

Only the ISO9660 side of the ISO9660 + UDF bridge images is kept consistent
(``disc.py`` docstring, "UDF"): a grown image's UDF anchor and partition, and
the UDF records of a rewritten ISO9660 file, are left as they were.

Output: each source image is cloned (APFS ``clonefile`` on macOS, a reflink
on Linux, else a hole-preserving stream copy) to ``<out>.partial``, patched,
verified and only then moved over ``<out>``. Verification re-opens every output
with ``disc.Disc``: no two files overlap on the image that did not already in
the source (every sized entry of every chain and every ISO9660 file, by
absolute byte range), each changed path reads back equal to the new bytes, every
index still parses and re-serializes byte for byte (``toc_bin.rebuild``) with
the same entry count, every untouched entry keeps its sector and size, X3.00 is
still identical across a pair, the ISO9660 volume size equals the image size,
and an evenly spread sample of untouched entries (and the boot ELF) has the
source's sha1. Sources are opened read-only and never written.

CLI::

    patch --iso D1.iso [--iso D2.iso] --out OUTDIR --set 'path=file' ... [--tree MODDIR]
          [--grow] [--ceiling auto|dvd5|dvd9|none|N] [--dry-run]

``--set`` takes an in-game path (``mnu\\us\\menutext.txd``, ``/`` or ``\\``,
case-insensitive; prefix ``chainN:`` to force a chain) or an ISO9660 file name.
``--tree`` adds every file of a mirror tree (MODDIR/mnu/us/menutext.txd =
``mnu\\us\\menutext.txd``). Outputs are OUTDIR/<source file name>.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import hashlib
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple, Union

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from chains import disc_number                                     # noqa: E402
from disc import (DVD5_SECTORS, DVD9_SECTORS, Disc, DiscError,     # noqa: E402
                  norm, BIGFILE_RE)
from iso9660 import SECTOR                                         # noqa: E402
from toc_bin import rebuild                                        # noqa: E402

Key = Union[str, Tuple[int, str]]


class PatchError(ValueError):
    pass


@dataclass
class Target:
    disc: int                 # index into the source list
    kind: str                 # "entry" or "fs"
    chain: Optional[int]      # None for an ISO9660 file
    path: str                 # as the disc spells it
    data: bytes
    old_size: int = 0
    alloc: int = 0
    action: str = ""          # "in-place", "grow", "unchanged"
    reason: str = ""
    lba: Optional[int] = None  # absolute sector after the write
    entry: object = None      # the TocEntry (kind "entry")

    def report(self, names: Sequence[str]) -> dict:
        return {"disc": names[self.disc], "chain": self.chain, "path": self.path,
                "action": self.action, "old_size": self.old_size, "new_size": len(self.data),
                "allocation": self.alloc, "lba": self.lba, "reason": self.reason}


def _sectors(n: int) -> int:
    return max(1, (n + SECTOR - 1) // SECTOR)


# ------------------------------------------------------------------ copying

def clone_file(src: Path, dst: Path) -> str:
    """Copy ``src`` to ``dst`` as cheaply as the filesystem allows. Returns the method:
    "clonefile" (APFS, macOS; no data copied), "reflink" (Linux cp --reflink), or
    "copy" (a stream copy that leaves all-zero 1 MB runs as holes)."""
    src, dst = Path(src), Path(dst)
    if dst.exists() or dst.is_symlink():
        dst.unlink()
    if sys.platform == "darwin":
        try:
            libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
            fn = libc.clonefile
            fn.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint32]
            fn.restype = ctypes.c_int
            if fn(os.fsencode(str(src)), os.fsencode(str(dst)), 0) == 0:
                return "clonefile"
        except (OSError, AttributeError):
            pass
    elif sys.platform.startswith("linux"):
        r = subprocess.run(["cp", "--reflink=always", str(src), str(dst)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if r.returncode == 0:
            return "reflink"
        if dst.exists():
            dst.unlink()
    chunk = 1 << 20
    zero = bytes(chunk)
    size = src.stat().st_size
    with open(src, "rb") as s, open(dst, "wb") as d:
        while True:
            b = s.read(chunk)
            if not b:
                break
            if b == zero[:len(b)]:
                d.seek(len(b), 1)
            else:
                d.write(b)
        d.truncate(size)
    return "copy"


def same_file(a, b) -> bool:
    """True when two paths name one file (same path after resolving links, or hard links)."""
    a, b = Path(a), Path(b)
    try:
        if a.resolve() == b.resolve():
            return True
        return a.exists() and b.exists() and os.path.samefile(a, b)
    except OSError:
        return False


def parse_ceiling(v) -> Optional[int]:
    """None (auto), "auto", "dvd5", "dvd9", "none"/0, or a sector count."""
    if v is None or v == "auto":
        return None
    if isinstance(v, int):
        return v
    v = str(v).lower()
    if v == "dvd5":
        return DVD5_SECTORS
    if v == "dvd9":
        return DVD9_SECTORS
    if v in ("none", "0", "off"):
        return 0
    try:
        return int(v)
    except ValueError:
        raise PatchError(f"--ceiling {v!r}: use auto, dvd5, dvd9, none or a sector count")


# ------------------------------------------------------------------ planning

def _check_set(discs: List[Disc], allow_unknown: bool) -> List[int]:
    import region
    if not 1 <= len(discs) <= 2:
        raise PatchError(f"give one image or a Disc 1 + Disc 2 pair, not {len(discs)}")
    if not allow_unknown:
        for d in discs:
            try:
                region.require_known(d, "patching")
            except region.UnknownBuild as e:
                raise PatchError(str(e))
    msg = region.mixed_regions(discs)
    if msg:
        raise PatchError("refused: " + msg.replace("warning: ", "", 1))
    nums = [disc_number(d.iso) for d in discs]
    if len(discs) == 2 and sorted(nums) != [1, 2]:
        raise PatchError(f"the two images must be Disc 1 and Disc 2 of one build; they carry story "
                         f"chains for disc {nums[0]} and disc {nums[1]}")
    return nums


def _resolve(discs: List[Disc], changes: Dict[Key, bytes]) -> List[Target]:
    targets: List[Target] = []
    seen: Dict[Tuple[int, str, Optional[int]], Key] = {}
    for key, data in changes.items():
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise PatchError(f"{key!r}: the new content must be bytes")
        data = bytes(data)
        want_chain = None
        path = key
        if isinstance(key, tuple):
            want_chain, path = key
        hits = []
        for i, d in enumerate(discs):
            if want_chain is None:
                h = d.lookup(path)            # chain 0 first, then the story chain
            else:
                e = next((x for x in d.entries_by_chain.get(want_chain, [])
                          if norm(x.path) == norm(path)), None)
                h = (want_chain, e) if e is not None else None
            if h is not None:
                hits.append(Target(i, "entry", h[0], h[1].path, data, entry=h[1]))
        if not hits and want_chain is None:
            for i, d in enumerate(discs):
                f = d.iso.find(path)
                if f is not None and not f.is_dir:
                    if BIGFILE_RE.match(f.path.rsplit("\\", 1)[-1]):
                        raise PatchError(f"{path}: an X3.nn chain container; change the files inside "
                                         "it (by their in-game paths) instead")
                    hits.append(Target(i, "fs", None, f.path, data))
        if not hits:
            where = f"chain {want_chain} of " if want_chain is not None else ""
            raise PatchError(f"{path!r} is in neither the index nor the ISO filesystem of "
                             f"{where}{', '.join(str(d.path.name) for d in discs)}")
        if any(t.chain == 0 for t in hits):
            missing = [discs[i].path.name for i in range(len(discs))
                       if not any(t.disc == i and t.chain == 0 for t in hits)]
            if missing:
                raise PatchError(f"{path}: a chain-0 object, but not in X3.00 of {', '.join(missing)}")
            hits = [t for t in hits if t.chain == 0]
        for t in hits:
            k = (t.disc, norm(t.path), t.chain)
            if k in seen:
                raise PatchError(f"{key!r} and {seen[k]!r} name the same file")
            seen[k] = key
        targets.extend(hits)
    return targets


def _classify(discs: List[Disc], targets: List[Target], grow: bool) -> List[str]:
    errors = []
    for t in targets:
        d = discs[t.disc]
        if t.kind == "entry":
            e = t.entry
            t.old_size = e.size
            if e.compressed:
                errors.append(f"{t.path}: compressed entry (none exist on any known XS3 image); "
                              "not supported")
                continue
            t.alloc = d.allocation(e)
            if d.read_entry(e) == t.data:
                t.action = "unchanged"
                continue
            shared = d.sharers(e)
            if shared:
                t.reason = f"starts on the sector of {shared[0].path}"
            elif len(t.data) > t.alloc:
                t.reason = f"{len(t.data)} bytes > allocation {t.alloc}"
            else:
                t.action = "in-place"
                continue
        else:
            f = d.iso.find(t.path)
            t.old_size, t.alloc = f.size, d.fs_allocation(t.path)
            if bytes(d.iso.read_file(f.path)) == t.data:
                t.action = "unchanged"
                continue
            if len(t.data) <= t.alloc:
                t.action = "in-place"
                continue
            t.reason = f"{len(t.data)} bytes > {t.alloc} before the next extent"
        if grow:
            t.action = "grow"
        else:
            errors.append(f"{d.path.name}: {t.path}: {t.reason}; pass grow=True (--grow) to "
                          "append it at the image end")
    return errors


def _boot_pair(discs: List[Disc], targets: List[Target]) -> List[str]:
    """Each disc boots its OWN executable (USA SLUS_213.89 / SLUS_214.17, Japan
    SLPS_256.40 / SLPS_256.41), byte-identical within a retail pair. A change to
    one image's boot executable on a pair is written to the other's too (like a
    chain-0 object), so Disc 2 does not keep retail code; when the two differ the
    change is refused. On one image alone it warns. Returns the warnings."""
    notes: List[str] = []
    boots = [d.boot_elf_name() for d in discs]
    for t in list(targets):
        if t.kind != "fs" or not boots[t.disc] or norm(t.path) != norm(boots[t.disc]):
            continue
        if len(discs) == 1:
            notes.append(f"{t.path}: the boot executable of {discs[0].path.name} only; the other disc "
                         "boots its own copy, which stays as it was: give --iso for both discs")
            continue
        j = 1 - t.disc
        if not boots[j] or any(u.disc == j and u.kind == "fs" and norm(u.path) == norm(boots[j])
                               for u in targets):
            continue
        if discs[0].read(boots[0]) != discs[1].read(boots[1]):
            raise PatchError(f"{t.path} is changed, but {discs[j].path.name} boots {boots[j]}, whose bytes "
                             f"differ from it; give the new bytes for {boots[j]} too")
        f = discs[j].iso.find(boots[j])
        targets.append(Target(j, "fs", None, f.path, t.data))
        notes.append(f"{discs[j].path.name} boots {f.path}, byte-identical to {t.path}: the same new "
                     "executable is written there too")
    return notes


@dataclass
class Plan:
    targets: List[Target]
    base: List[int]                  # sector each image's appends start at (after padding)
    final: List[int]                 # image sectors after all appends
    chain0_grows: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


def plan_changes(discs: List[Disc], changes: Dict[Key, bytes], grow: bool = False,
                 allow_unknown: bool = False) -> Plan:
    """Resolve, classify and budget a change set against open (read-only) images.
    Raises PatchError for anything ``patch_copy`` would refuse; writes nothing."""
    _check_set(discs, allow_unknown)
    targets = _resolve(discs, changes)
    warnings = _boot_pair(discs, targets)
    errors = _classify(discs, targets, grow)
    if any(t.chain == 0 and t.action != "unchanged" for t in targets):
        if len(discs) == 2 and discs[0].index_data[0] != discs[1].index_data[0]:
            errors.append("X3.00 differs between the two images (one was patched alone before?); "
                          "chain-0 objects can only be patched on a pair whose X3.00 is identical")
        if len(discs) == 1:
            warnings.append(f"chain-0 objects patched on {discs[0].path.name} only: the other disc's "
                            "X3.00 copy is unchanged, so from now on this output and the other disc "
                            "form a pair whose X3.00 differs, and every later pair patch of them that "
                            "changes a chain-0 object is refused (start again from the originals); give "
                            "--iso for both discs to keep them identical")
    if errors:
        raise PatchError("refused:\n  " + "\n  ".join(errors))
    ends = [d.iso.image_size // SECTOR for d in discs]
    c0 = []
    for t in targets:
        if t.action == "grow" and t.chain == 0 and t.path not in c0:
            c0.append(t.path)
    s0 = sum(_sectors(len(next(t.data for t in targets if t.path == p and t.chain == 0))) for p in c0)
    base = [max(ends) if (s0 and len(discs) == 2) else e for e in ends]
    final = []
    for i, d in enumerate(discs):
        own = sum(_sectors(len(t.data)) for t in targets
                  if t.disc == i and t.action == "grow" and t.chain != 0)
        n = base[i] + s0 + own
        final.append(n)
        if n > DVD5_SECTORS and d.iso.layer2_pvd_sector is None:
            warnings.append(f"{d.path.name}: grows to {n} sectors, past DVD-5 ({DVD5_SECTORS}), as ONE "
                            "ISO9660 volume with no layer break: not burnable to a DVD-5 or a DVD-9, for "
                            "emulators only, and whether PCSX2 accepts it is untested")
        if n != ends[i]:
            vol_end = d._volume_end_sector()
            if vol_end != ends[i]:
                errors.append(f"{d.path.name}: the ISO9660 volume ends at sector {vol_end} but the "
                              f"image has {ends[i]} sectors; growing it is refused")
            cap = d.sector_ceiling()
            if cap and n > cap:
                pad = f" (incl. {base[i] - ends[i]} sectors of padding to keep chain-0 LBAs equal " \
                      "on both discs)" if base[i] > ends[i] else ""
                errors.append(f"{d.path.name}: would grow from {ends[i]} to {n} sectors{pad}, "
                              f"{n - cap} past the ceiling of {cap}; pass a higher ceiling "
                              "(emulator-only images) or make the change smaller")
    if errors:
        raise PatchError("refused:\n  " + "\n  ".join(errors))
    return Plan(targets, base, final, c0, warnings)


# ------------------------------------------------------------------ writing

def _apply(disc: Disc, i: int, plan: Plan) -> None:
    mine = [t for t in plan.targets if t.disc == i]
    for t in mine:                                         # 1. in place
        if t.action != "in-place":
            continue
        if t.kind == "entry":
            disc.write_entry(t.entry, t.data)
            t.lba = disc.absolute_offset(t.entry) // SECTOR
        else:
            disc.write_fs_file(t.path, t.data)
            t.lba = disc.iso.find(t.path).lba
    if plan.chain0_grows:                                  # 2. chain-0 grows, same LBA on a pair
        disc.pad_to(plan.base[i])
        for p in plan.chain0_grows:
            t = next(t for t in mine if t.chain == 0 and t.path == p)
            t.lba = disc.append_entry(t.entry, t.data)
    for t in mine:                                         # 3. this disc's own grows
        if t.action != "grow" or t.chain == 0:
            continue
        if t.kind == "entry":
            t.lba = disc.append_entry(t.entry, t.data)
        else:
            t.lba = disc.relocate_fs_file(t.path, t.data)


def _spot_entries(src: Disc, chain: int, skip: set, n: int):
    ents = [e for e in src.entries_by_chain[chain] if e.size > 0 and norm(e.path) not in skip]
    if not ents or n <= 0:
        return []
    step = max(1, len(ents) // n)
    return ents[::step][:n]


def _overlaps(d: Disc) -> set:
    """Pairs of objects whose bytes overlap on the image: every sized index entry of
    every chain (at its absolute offset) and every ISO9660 file except the X3.nn
    containers (which hold the entries by design)."""
    ext = []
    for c, ents in d.entries_by_chain.items():
        base = d.index_lba(c) * SECTOR
        for e in ents:
            if e.size > 0:
                ext.append((base + e.byte_offset, base + e.byte_offset + e.size, f"chain{c}:{norm(e.path)}"))
    for f in d.iso.files.values():
        if not f.is_dir and f.size > 0 and not BIGFILE_RE.match(f.path.rsplit("\\", 1)[-1]):
            ext.append((f.lba * SECTOR, f.lba * SECTOR + f.size, f"iso:{norm(f.path)}"))
    ext.sort()
    pairs = set()
    for i, (a0, a1, la) in enumerate(ext):
        j = i + 1
        while j < len(ext) and ext[j][0] < a1:
            if la != ext[j][2]:
                pairs.add(tuple(sorted((la, ext[j][2]))))
            j += 1
    return pairs


def verify(srcs: List[Disc], outs: List[Disc], plan: Plan, spot: int = 24) -> List[str]:
    """Problems found re-reading the outputs (empty = good)."""
    bad = []
    for i, (s, o) in enumerate(zip(srcs, outs)):
        name = o.path.name
        # no file may land on another one's bytes (an in-place write over an
        # appended file of another chain, a relocated ISO file, ...): any overlap
        # the source did not already have is an error
        new_ov = sorted(_overlaps(o) - _overlaps(s))
        if new_ov:
            bad.append(f"{name}: {len(new_ov)} pair(s) of files now overlap on the image, e.g. "
                       f"{new_ov[0][0]} and {new_ov[0][1]}")
        mine = [t for t in plan.targets if t.disc == i]
        vol_end = o._volume_end_sector()
        if vol_end * SECTOR != o.iso.image_size:
            bad.append(f"{name}: ISO9660 volume {vol_end} sectors != image {o.iso.image_size // SECTOR}")
        if o.chains != s.chains:
            bad.append(f"{name}: chains {o.chains} != source {s.chains}")
        for t in mine:
            got = o.read_entry(t.entry) if t.kind == "entry" else o.read(t.path)
            if got != t.data:
                bad.append(f"{name}: {t.path} does not read back as the new bytes")
        for c in s.chains:
            idx = o.index_data[c]
            if rebuild(idx) != idx:
                bad.append(f"{name}: chain {c} index no longer re-serializes byte for byte")
            se, oe = s.entries_by_chain[c], o.entries_by_chain[c]
            if len(se) != len(oe):
                bad.append(f"{name}: chain {c} has {len(oe)} entries, source {len(se)}")
                continue
            touched = {norm(t.path) for t in mine if t.chain == c}
            moved = [a.path for a, b in zip(se, oe)
                     if norm(a.path) not in touched and (a.path, a.sector, a.size) != (b.path, b.sector, b.size)]
            if moved:
                bad.append(f"{name}: chain {c}: {len(moved)} untouched entries changed, e.g. {moved[0]}")
            # spot-check bytes of untouched entries (skip any sharing a changed entry's sector)
            starts = {t.entry.byte_offset for t in mine if t.chain == c}
            skip = touched | {norm(e.path) for e in se if e.byte_offset in starts}
            for e in _spot_entries(s, c, skip, spot):
                if hashlib.sha1(s.read_entry(e)).digest() != hashlib.sha1(o.read_entry(e)).digest():
                    bad.append(f"{name}: untouched {e.path} changed")
        boot = s.boot_elf_name()
        if boot and not any(t.kind == "fs" and norm(t.path) == norm(boot) for t in mine):
            if hashlib.sha1(s.read(boot)).digest() != hashlib.sha1(o.read(boot)).digest():
                bad.append(f"{name}: boot ELF {boot} changed")
    if len(srcs) == 2 and srcs[0].index_data[0] == srcs[1].index_data[0] \
            and outs[0].index_data[0] != outs[1].index_data[0]:
        bad.append("X3.00 is no longer identical on the two outputs")
    return bad


def _out_paths(src_isos: List[Path], out_isos, overwrite: bool = False) -> List[Path]:
    """The output image paths. An output that already exists as a file is refused
    unless ``overwrite`` (an ``--out`` naming another original, e.g. the Disc 2 ISO
    while patching Disc 1, would otherwise be replaced); a source is refused always."""
    if isinstance(out_isos, (str, Path)):
        od = Path(out_isos)
        if od.exists() and not od.is_dir():
            if len(src_isos) != 1:
                raise PatchError(f"{od} is a file; give a folder for {len(src_isos)} images")
            outs = [od]                              # checked below like any output
        elif not od.exists() and od.suffix.lower() == ".iso" and len(src_isos) == 1:
            outs = [od]
        else:
            outs = [od / s.name for s in src_isos]   # the folder is made by patch_copy
    else:
        outs = [Path(p) for p in out_isos]
    if len(outs) != len(src_isos):
        raise PatchError(f"{len(src_isos)} source image(s) but {len(outs)} output path(s)")
    if len({str(p.resolve()) for p in outs}) != len(outs):
        raise PatchError("two outputs have the same path")
    for o in outs:
        if o.is_dir():
            raise PatchError(f"output {o} is a folder")
        for s in src_isos:
            if same_file(s, o) or same_file(s, o.with_name(o.name + ".partial")):
                raise PatchError(f"output {o} is the source image {s} itself; the kit never patches "
                                 "its source")
    existing = [o for o in outs if o.exists() or o.is_symlink()]
    if existing and not overwrite:
        raise PatchError(f"output {existing[0]} already exists; the kit never replaces a file it "
                         "did not just write (it may be an original image): give a new --out, delete "
                         "it yourself, or pass --overwrite if it is an earlier output of this kit")
    return outs


def patch_copy(src_isos, out_isos, changes: Dict[Key, bytes], grow: bool = False, *,
               ceiling=None, verbose: bool = True, spot: int = 24, dry_run: bool = False,
               overwrite: bool = False,
               _allow_unknown: bool = False, _fail_after_copy=None) -> List[dict]:
    """Patch ``changes`` ({in-game path or ISO file name or (chain, path): new bytes})
    into copies of ``src_isos`` (one image, or Disc 1 + Disc 2 of one build) written
    to ``out_isos`` (a list of paths, or one folder: OUT/<source name>; an output that
    already exists is refused unless ``overwrite``). Returns one
    report dict per (image, file). See the module docstring for the rules."""
    srcs_p = [Path(p) for p in ([src_isos] if isinstance(src_isos, (str, Path)) else src_isos)]
    cap = parse_ceiling(ceiling)
    srcs = [Disc(p, ceiling=cap) for p in srcs_p]
    outs: List[Disc] = []
    tmps: List[Path] = []
    try:
        if str(ceiling).lower() == "dvd9" and any(s.iso.layer2_pvd_sector is None for s in srcs):
            raise PatchError("--ceiling dvd9: these are single-layer images; the output would be one "
                             "ISO9660 volume past DVD-5 with no layer break and no second volume, which is "
                             "not a DVD-9. For emulator-only images say so with --ceiling none or a "
                             "sector count")
        plan = plan_changes(srcs, changes, grow, allow_unknown=_allow_unknown)
        names = [p.name for p in srcs_p]
        for w in plan.warnings:
            print("warning: " + w, file=sys.stderr)
        if verbose:
            for t in plan.targets:
                print(f"  {names[t.disc]}: {('chain%d' % t.chain) if t.chain is not None else 'iso'} "
                      f"{t.path}: {t.action} ({t.old_size} -> {len(t.data)} bytes, allocation {t.alloc}"
                      f"{'; ' + t.reason if t.reason and t.action == 'grow' else ''})")
            for i, n in enumerate(names):
                end = srcs[i].iso.image_size // SECTOR
                if plan.final[i] != end:
                    print(f"  {n}: {end} -> {plan.final[i]} sectors (ceiling "
                          f"{srcs[i].sector_ceiling() or 'none'})")
        dsts = _out_paths(srcs_p, out_isos, overwrite)      # refusals first, also on a dry run
        if dry_run:
            return [t.report(names) for t in plan.targets]
        for d in dsts:
            d.parent.mkdir(parents=True, exist_ok=True)
        if all(t.action == "unchanged" for t in plan.targets) and verbose:
            print("note: every file already has these bytes; the outputs are plain copies")
        for s, d in zip(srcs_p, dsts):
            tmp = d.with_name(d.name + ".partial")
            tmps.append(tmp)
            how = clone_file(s, tmp)
            if verbose:
                print(f"{how}: {s} -> {tmp}")
        if _fail_after_copy is not None:
            _fail_after_copy(tmps)
        for i, tmp in enumerate(tmps):
            with Disc(tmp, writable=True, ceiling=cap) as w:
                _apply(w, i, plan)
        if len(srcs) == 2 and plan.chain0_grows:
            for p in plan.chain0_grows:
                lbas = {t.lba for t in plan.targets if t.chain == 0 and t.path == p}
                if len(lbas) != 1:
                    raise PatchError(f"{p}: grown to different LBAs on the two discs {sorted(lbas)}")
        outs = [Disc(t) for t in tmps]
        bad = verify(srcs, outs, plan, spot)
        if bad:
            raise PatchError("verification failed:\n  " + "\n  ".join(bad))
        for o in outs:
            o.close()
        outs = []
        for tmp, d in zip(tmps, dsts):
            os.replace(tmp, d)
        if verbose:
            n = sum(1 for t in plan.targets if t.action != "unchanged")
            print(f"patched {n} file write(s) into {', '.join(str(d) for d in dsts)} (verified)")
        return [t.report(names) for t in plan.targets]
    except BaseException:
        for o in outs:
            o.close()
        for tmp in tmps:
            try:
                if tmp.exists():
                    tmp.unlink()
            except OSError:
                pass
        raise
    finally:
        for s in srcs:
            s.close()


# ------------------------------------------------------------------ CLI

def _parse_set(spec: str) -> Tuple[Key, Path]:
    if "=" not in spec:
        raise PatchError(f"--set {spec!r}: expected 'in-game path=local file'")
    path, f = spec.split("=", 1)
    key: Key = path
    low = path.lower()
    if low.startswith("chain") and ":" in path[:8] and path[5:path.index(":")].isdigit():
        key = (int(path[5:path.index(":")]), path[path.index(":") + 1:])
    return key, Path(f)


def _cmd_patch(a) -> int:
    changes: Dict[Key, bytes] = {}
    try:
        for spec in a.set or []:
            key, f = _parse_set(spec)
            changes[key] = f.read_bytes()
        if a.tree:
            root = Path(a.tree)
            if not root.is_dir():
                raise PatchError(f"--tree {root}: not a folder")
            for p in sorted(root.rglob("*")):
                if p.is_file() and not any(part.startswith(".") for part in p.relative_to(root).parts):
                    changes["\\".join(p.relative_to(root).parts)] = p.read_bytes()
        if not changes:
            raise PatchError("nothing to patch: give --set 'path=file' and/or --tree DIR")
        patch_copy(a.iso, a.out, changes, grow=a.grow, ceiling=a.ceiling, dry_run=a.dry_run,
                   overwrite=a.overwrite)
    except (PatchError, DiscError, OSError) as e:
        print(f"patch: {e}", file=sys.stderr)
        return 1
    return 0


def add_commands(subparsers) -> None:
    """Register ``patch`` (copy-based, multi-file, Disc 1 + Disc 2 aware)."""
    p = subparsers.add_parser("patch", help="write changed files into COPIES of one disc or a Disc 1 + "
                              "Disc 2 pair (in place when they fit, appended with --grow); verified")
    p.add_argument("--iso", required=True, action="append",
                   help="source image (repeat for Disc 1 + Disc 2 of one build); never written")
    p.add_argument("--out", required=True, help="output folder (OUT/<source name>), or an .iso path "
                   "for a single image")
    p.add_argument("--set", action="append", metavar="PATH=FILE",
                   help=r"in-game path (or ISO file name) = local file; prefix chainN: to force a chain")
    p.add_argument("--tree", help="mirror tree: every file under it, by its relative path")
    p.add_argument("--grow", action="store_true",
                   help="append files that outgrow their allocation at the image end and repoint "
                        "the index (not yet booted in PCSX2 for XS3)")
    p.add_argument("--ceiling", default="auto",
                   help="most sectors an image may grow to: auto (DVD-5 single-layer / DVD-9 "
                        "dual-layer), dvd5, dvd9 (dual-layer images only), or none / a number for "
                        "emulator-only images (past DVD-5 a single-layer image is not burnable)")
    p.add_argument("--dry-run", action="store_true", help="show the plan and budget; write nothing")
    p.add_argument("--overwrite", action="store_true",
                   help="replace output images that already exist (only ever an earlier output of "
                        "this kit; never point --out at an original)")
    p.set_defaults(func=_cmd_patch)


# ------------------------------------------------------------------ self-test

def _syn_pair(dirp: Path, elf2: bytes = b"\x7fELF-standin") -> Tuple[Path, Path]:
    """Two synthetic images shaped like Disc 1 / Disc 2: identical chain 0 (X3.00-02),
    chain 1 (X3.10-11) on one, chain 2 (X3.20-21) on the other, different lengths."""
    from iso9660 import make_test_image
    from toc_bin import Event, serialize
    a = b"menu text one\x00" * 40
    b = bytes(range(256)) * 10
    c = b"\x55" * 3000
    idx0 = serialize([Event("dir", name=b"mnu"), Event("dir", name=b"us"),
                      Event("file", name=b"menutext.txd", sector=1, size=len(a)),
                      Event("file", name=b"font0.bin", sector=2, size=len(b)),
                      Event("file", name=b"empty.bin", sector=2, size=0),
                      Event("pop"), Event("pop"),
                      Event("file", name=b"last.bin", sector=4, size=len(c)),
                      ], 1)
    x301 = a.ljust(SECTOR, b"\0") + b.ljust(2 * SECTOR, b"\0")
    x302 = c
    s1 = b"scene one" * 300                                   # 2700 bytes
    idx1 = serialize([Event("dir", name=b"cf"), Event("dir", name=b"us"),
                      Event("file", name=b"1010.sb", sector=1, size=len(s1)),
                      Event("pop"), Event("pop")], 1)
    s2 = b"scene two" * 500                                   # 4500 bytes
    idx2 = serialize([Event("dir", name=b"cf"), Event("dir", name=b"us"),
                      Event("file", name=b"5010.sb", sector=1, size=len(s2)),
                      Event("pop"), Event("pop")], 1)
    p1, p2 = dirp / "syn1.iso", dirp / "syn2.iso"
    common = [("X3.00", idx0), ("X3.01", x301), ("X3.02", x302)]
    make_test_image(p1, [("SYSTEM.CNF", b"BOOT2 = cdrom0:\\SLUS_999.99;1\r\n"),
                         ("SLUS_999.99", b"\x7fELF-standin")] + common
                    + [("X3.10", idx1), ("X3.11", s1.ljust(2 * SECTOR, b"\0")),
                       ("X3.12", bytes(SECTOR)), ("X3.13", bytes(SECTOR))])
    make_test_image(p2, [("SYSTEM.CNF", b"BOOT2 = cdrom0:\\SLUS_999.99;1\r\n"),
                         ("SLUS_999.99", elf2)] + common
                    + [("X3.20", idx2), ("X3.21", s2.ljust(9 * SECTOR, b"\0")),
                       ("X3.22", bytes(SECTOR)), ("X3.23", bytes(SECTOR))])
    return p1, p2


def _sha(p: Path) -> str:
    h = hashlib.sha1()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def _disc_sparse(src: str, dst: Path) -> None:
    """Sparse copy of a real image: system area, root files and X3.00 (everything up to
    X3.01) plus the story chain's index; holes elsewhere."""
    from disc import _sparse_copy
    from iso9660 import IsoImage
    with IsoImage(src) as iso:
        ranges = [(0, iso.files["X3.01"].lba)]
        for n in ("X3.10", "X3.20"):
            if n in iso.files:
                ranges.append((iso.files[n].lba, iso.files[n].size // SECTOR))
    _sparse_copy(src, dst, ranges)


def self_test() -> int:
    import tempfile
    ok = True

    def check(cond, msg):
        nonlocal ok
        print(("ok    " if cond else "FAIL  ") + msg)
        ok &= bool(cond)

    def raises(fn, exc, msg, contains=""):
        try:
            fn()
            check(False, msg)
        except exc as e:
            check(contains in str(e), msg + ("" if contains in str(e) else f" (got: {e})"))

    q = dict(verbose=False, _allow_unknown=True)
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        p1, p2 = _syn_pair(td)
        h1, h2 = _sha(p1), _sha(p2)
        out = td / "out"
        a = b"menu text one\x00" * 40
        # 1. same size, one image
        new = a.replace(b"one", b"ONE")
        r = patch_copy([p1], out, {"mnu/us/menutext.txd": new}, **q)
        # an output that already exists is never replaced without overwrite=True
        # (verifier repro: --out naming another original was os.replace'd)
        victim = td / "victim.iso"
        victim.write_bytes(b"V" * 800)
        h_out = _sha(out / p1.name)
        raises(lambda: patch_copy([p1], victim, {"mnu/us/menutext.txd": new}, **q), PatchError,
               "an existing file given as --out is refused", "already exists")
        raises(lambda: patch_copy([p1], out, {"mnu/us/menutext.txd": new}, **q), PatchError,
               "an existing OUT/<name> is refused without overwrite", "already exists")
        raises(lambda: patch_copy([p1], victim, {"mnu/us/menutext.txd": new}, dry_run=True, **q), PatchError,
               "the refusal also holds on a dry run", "already exists")
        check(victim.read_bytes() == b"V" * 800 and _sha(out / p1.name) == h_out,
              "the existing files are untouched by the refusals")
        victim.unlink()
        q["overwrite"] = True              # the rest of the synthetic runs reuse OUT on purpose
        with Disc(out / p1.name) as d:
            check(d.read("mnu\\us\\menutext.txd") == new and d.lookup("mnu\\us\\menutext.txd")[1].size == len(a)
                  and r[0]["action"] == "in-place", "same-size patch in place, size unchanged")
        # 2. smaller on the pair: chain 0 written on both, size field updated
        r = patch_copy([p1, p2], out, {"mnu\\us\\menutext.txd": b"SHORT"}, **q)
        check(len(r) == 2 and {x["disc"] for x in r} == {p1.name, p2.name},
              "chain-0 change applies to Disc 1 AND Disc 2")
        with Disc(out / p1.name) as d1, Disc(out / p2.name) as d2:
            check(all(d.read("mnu\\us\\menutext.txd") == b"SHORT" and d.lookup("mnu\\us\\menutext.txd")[1].size == 5
                      for d in (d1, d2)), "smaller patch: index size field = 5 on both discs")
            check(d1.index_data[0] == d2.index_data[0], "X3.00 still identical on both outputs")
        # 3. grow on the pair: chain 0 + chain 1 + chain 2
        big0 = b"GROWN0" * 1000
        r = patch_copy([p1, p2], out, {"mnu\\us\\font0.bin": big0, "cf\\us\\1010.sb": b"S1" * 6000,
                                       "cf\\us\\5010.sb": b"S2" * 4000}, grow=True, **q)
        with Disc(p1) as s1, Disc(p2) as s2, Disc(out / p1.name) as d1, Disc(out / p2.name) as d2:
            end1, end2 = s1.iso.image_size // SECTOR, s2.iso.image_size // SECTOR
            l0 = [x["lba"] for x in r if x["chain"] == 0]
            check(len(l0) == 2 and l0[0] == l0[1] == max(end1, end2),
                  f"grown chain-0 object lands on the same LBA on both discs ({l0}, ends {end1}/{end2})")
            check(d1.index_data[0] == d2.index_data[0], "X3.00 identical on both outputs after the grow")
            check(d1.read("mnu\\us\\font0.bin") == big0 == d2.read("mnu\\us\\font0.bin"), "grown chain-0 reads back on both")
            c1 = [x for x in r if x["chain"] == 1]
            c2 = [x for x in r if x["chain"] == 2]
            check(len(c1) == 1 and c1[0]["disc"] == p1.name and c1[0]["lba"] > l0[0]
                  and d1.read("cf\\us\\1010.sb") == b"S1" * 6000, "chain-1 object grown on Disc 1 only, past chain 0's")
            check(len(c2) == 1 and c2[0]["disc"] == p2.name and d2.read("cf\\us\\5010.sb") == b"S2" * 4000,
                  "chain-2 object grown on Disc 2 only")
            check(d1.iso.volume_sectors * SECTOR == d1.iso.image_size and d2.iso.volume_sectors * SECTOR == d2.iso.image_size,
                  "both grown outputs: volume = image size")
        # 4. refusals leave nothing behind
        out4 = td / "out4"
        raises(lambda: patch_copy([p1, p2], out4, {"mnu\\us\\font0.bin": big0}, **q), PatchError,
               "growth without grow=True is refused", "grow")
        raises(lambda: patch_copy([p1], out4, {"mnu\\us\\empty.bin": b"x" * 10}, **q), PatchError,
               "a zero-size entry on another file's sector is refused in place", "starts on the sector")
        r = patch_copy([p1], out4, {"mnu\\us\\empty.bin": b"x" * 10}, grow=True, **q)
        with Disc(out4 / p1.name) as d:
            check(r[0]["action"] == "grow" and d.read("mnu\\us\\empty.bin") == b"x" * 10
                  and d.read("mnu\\us\\font0.bin") == bytes(range(256)) * 10,
                  "with grow the shared-sector entry is relocated, its neighbour untouched")
        (out4 / p1.name).unlink()
        raises(lambda: patch_copy([p1, p2], out4, {"mnu\\us\\font0.bin": big0}, grow=True, ceiling=20, **q),
               PatchError, "the sector ceiling is checked before copying", "ceiling")
        raises(lambda: patch_copy([p1, p1], out4, {"mnu\\us\\font0.bin": b"z"}, **q), PatchError,
               "two images of the same disc number are refused", "Disc 1 and Disc 2")
        raises(lambda: patch_copy([p1], [p1], {"mnu\\us\\font0.bin": b"z"}, **q), PatchError,
               "writing over the source is refused", "source")
        raises(lambda: patch_copy([p1], out4, {"nope\\x.bin": b"z"}, **q), PatchError,
               "an unknown path is refused", "neither")
        raises(lambda: patch_copy([p1], out4, {"X3.01": b"z"}, **q), PatchError,
               "a whole X3.nn container is refused", "container")

        def boom(tmps):
            raise RuntimeError("injected")
        raises(lambda: patch_copy([p1, p2], out4, {"mnu\\us\\font0.bin": b"q"}, _fail_after_copy=boom, **q),
               RuntimeError, "an error after copying propagates")
        check(not any(out4.glob("*")), "refusals and the failed run left no output or .partial behind")
        (td / "mixed").mkdir()
        m1, m2 = _syn_pair(td / "mixed", elf2=b"\x7fELF-other")
        raises(lambda: patch_copy([m1, m2], out4, {"mnu\\us\\font0.bin": b"q"}, **q), PatchError,
               "two different builds (executables differ) are refused", "different builds")
        raises(lambda: patch_copy([p1], out4, {"mnu\\us\\font0.bin": b"q"}, verbose=False), PatchError,
               "an unknown build is refused (require_known)", "refused")
        # 5. ISO9660 file on both discs, (chain, path) keys, the CLI
        cnf = b"BOOT2 = cdrom0:\\SLUS_999.99;1\r\nVER = 1.01\r\n"
        r = patch_copy([p1, p2], out, {"system.cnf": cnf, (1, "cf/us/1010.sb"): b"tuple key"}, **q)
        with Disc(out / p1.name) as d1, Disc(out / p2.name) as d2:
            check(d1.read("SYSTEM.CNF") == cnf == d2.read("SYSTEM.CNF") and d1.read("cf\\us\\1010.sb") == b"tuple key",
                  "ISO9660 file written on both images; (chain, path) key")
        check(_sha(p1) == h1 and _sha(p2) == h2, "sources unchanged (sha1) after every run")
        check(_parse_set("chain2:cf\\us\\5010.sb=x.bin") == ((2, "cf\\us\\5010.sb"), Path("x.bin"))
              and _parse_set("mnu/us/a.txd=b=c.bin") == ("mnu/us/a.txd", Path("b=c.bin")),
              "--set parsing: chainN: prefix, first '=' splits")

    # real images: sparse copies (system area + indexes; holes elsewhere), a few MB each
    env = {k: os.environ.get(v) for k, v in (("D1", "XS3_D1"), ("D2", "XS3_D2"), ("JP1", "XS3_JP1"))}
    if env["D1"] and env["D2"]:
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            s1, s2 = td / "d1.iso", td / "d2.iso"
            _disc_sparse(env["D1"], s1)
            _disc_sparse(env["D2"], s2)
            with Disc(s1) as d:
                c1 = next(e.path for e in d.entries_by_chain[1] if e.size > 0)
            with Disc(s2) as d:
                c2 = next(e.path for e in d.entries_by_chain[2] if e.size > 0)
            r = patch_copy([s1, s2], td / "o", {"mnu\\us\\menutext.txd": b"T" * 20000, c1: b"A" * 9000,
                                                 c2: b"B" * 7000}, grow=True, verbose=False)
            l0 = [x["lba"] for x in r if x["chain"] == 0]
            check(l0[0] == l0[1] == 2205056, f"US pair (sparse): grown menutext.txd at LBA {l0[0]} on both "
                  "(Disc 1 padded to Disc 2's 2,205,056 sectors)")
            with Disc(td / "o" / s1.name) as d1, Disc(td / "o" / s2.name) as d2:
                check(d1.index_data[0] == d2.index_data[0] and len(d1.entries_by_chain[0]) == 9867,
                      "US pair (sparse): X3.00 identical, 9,867 entries")
                check(d1.read(c1) == b"A" * 9000 and d2.read(c2) == b"B" * 7000 and d1.lookup(c2) is None,
                      "US pair (sparse): chain-1 grow on D1, chain-2 grow on D2 only")
            # re-patching an already grown pair: appended objects of chain 0 and of the
            # story chain interleave (menutext, c1/c2, then batle_bg); menutext's room
            # must end at c1/c2, not at the next chain-0 start (verifier repro scen3)
            o1, o2 = td / "o" / s1.name, td / "o" / s2.name
            patch_copy([o1, o2], td / "o2", {"bat\\us\\batle_bg.sb": b"Z" * 3000}, grow=True, verbose=False)
            with Disc(td / "o2" / s1.name) as d:
                a = d.allocation(d.lookup("mnu\\us\\menutext.txd")[1])
            check(a == 10 * SECTOR, f"re-patch: a relocated entry's room ends at the next object of any "
                  f"chain ({a} bytes = its 10 sectors, c1 follows)")
            r = patch_copy([td / "o2" / s1.name, td / "o2" / s2.name], td / "o3",
                           {"mnu\\us\\menutext.txd": b"M" * 21000}, grow=True, verbose=False)
            with Disc(td / "o3" / s1.name) as d1, Disc(td / "o3" / s2.name) as d2:
                check(all(x["action"] == "grow" for x in r) and d1.read(c1) == b"A" * 9000
                      and d2.read(c2) == b"B" * 7000 and d1.read("mnu\\us\\menutext.txd") == b"M" * 21000,
                      "re-patch: 21,000 B menutext is grown, not written over the chain-1/chain-2 file")
            for k in ("o", "o2", "o3"):
                shutil.rmtree(td / k, ignore_errors=True)
            with Disc(s1) as d:
                exe = bytearray(d.read("SLUS_213.89"))
            exe[0x1000] ^= 0xFF
            r = patch_copy([s1, s2], td / "o4", {"SLUS_213.89": bytes(exe)}, dry_run=True, verbose=False)
            check(sorted((x["disc"], x["path"].split(";")[0]) for x in r)
                  == sorted([(s1.name, "SLUS_213.89"), (s2.name, "SLUS_214.17")]),
                  "a Disc 1 boot-executable change on the pair is written to Disc 2's SLUS_214.17 too")
    else:
        print("SKIP  US pair checks (set XS3_D1 and XS3_D2)")
    if env["JP1"]:
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            s = td / "jp1.iso"
            _disc_sparse(env["JP1"], s)
            with Disc(s) as d:
                old = d.read("mnu\\jp\\menutext.txd")
                last = max(d.entries_by_chain[0], key=lambda e: e.byte_offset)
                lalloc = d.allocation(last)
            check(norm(last.path) == "mnu\\jp\\font0.bin" and lalloc - last.size == 1024,
                  f"JP1: last chain-0 entry {last.path} gets the X3.02 tail slack: allocation {lalloc} "
                  f"= size {last.size} + 1,024 (SYNTHESIS M2)")
            new = bytes(x ^ 0x5A for x in old)          # same size; the sparse copy holds zeros here
            r = patch_copy([s], td / "o", {"mnu\\jp\\menutext.txd": new,
                                          "mnu\\jp\\font0.bin": b"F" * 600000}, grow=True, verbose=False)
            with Disc(td / "o" / s.name) as d:
                check(d.read("mnu\\jp\\menutext.txd") == new and d.read("mnu\\jp\\font0.bin") == b"F" * 600000
                      and [x["action"] for x in r] == ["in-place", "grow"],
                      "JP1 (sparse): same-size in place + grow, both read back")
    else:
        print("SKIP  JP checks (set XS3_JP1)")
    print("self-test", "passed" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    if sys.argv[1:] == ["--self-test"]:
        sys.exit(self_test())
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    add_commands(ap.add_subparsers(dest="cmd", required=True))
    a = ap.parse_args()
    sys.exit(a.func(a))
