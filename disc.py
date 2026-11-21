"""disc.py — open an Episode III ISO and resolve any in-game path through the disc's OWN index.

New for this kit (2026-11-20); the write primitives are ported from
Xenosaga2PythonExtractor/repack.py (``patch_iso`` field patching, the grow =
append-at-image-end rule and ``_bump_volume``), reshaped into single steps a
later write path can compose. Nothing here needs 7-Zip or the bundled
lba/*.txt tables: every location comes from the X3.00 / X3.10 / X3.20 index on
the image itself (``toc_bin.py``), so the May 2006 prototype, whose layout
differs from retail in 364 X3.00 and 109 X3.10 entries, reads correctly.

    from disc import Disc
    with Disc("Disc 1.iso") as d:
        data = d.read("\\\\mnu\\\\us\\\\menutext.txd")     # case-insensitive, / or \\, leading \\ optional
        elf = d.read("SLUS_213.89")                  # ISO filesystem files resolve too

Path resolution order: the index entries of every chain on the image (chain 0
first, then the story chain), then the ISO9660 filesystem (root files such as
SYSTEM.CNF, the boot ELF, OV0x.OVL, and IOP\\*).

Write primitives (``Disc(path, writable=True)``; ALWAYS on a copy, never on
an original image; each step re-reads the image afterwards):

    fields_off(entry)          absolute image offset of the entry's u24 sector
                               field (u32 size at +3, u24 usize at +7 if compressed)
    patch_size(entry, n)       rewrite the size field in the index on the image
    relocate(entry, sector)    rewrite the u24 sector field (index-relative)
    write_entry(entry, data)   overwrite in place inside the entry's allocation
                               (clears the stale tail, patches the size); refused
                               for a zero-size entry that starts on another file's
                               sector (``sharers``; four such entries on D1)
    append(data)               append sector-aligned at the image end and grow the
                               PVD volume-space count; returns the new LBA. Refused
                               when the image has bytes past its volume end, and
                               when the image would pass ``ceiling`` (default: the
                               DVD-5 sector count for a single-layer image, DVD-9
                               for a dual-layer one; ``Disc(..., ceiling=0)`` lifts it)
    pad_to(sectors)            grow the image (sparse, zero) and the volume count to
                               ``sectors``; the Disc 1 + Disc 2 write path uses it so
                               a grown chain-0 object lands on the SAME LBA on both
                               discs and X3.00 stays byte-identical across the pair
    append_entry(entry, data)  append + relocate + patch_size: the XS1/XS2 grow
                               rule (engine reads LBA = index LBA + sector). Proven
                               in-game for XS1, NOT yet checked in PCSX2 for XS3.
    allocation(entry)          bytes the entry may occupy in place: to the next entry of
                               its chain; once relocated, to the next object of ANY
                               chain or ISO9660 file on the image
    fs_allocation(name)        bytes an ISO9660 file may occupy before the next extent
                               or appended index entry
    write_fs_file(name, data)  ISO9660 file in place (fits fs_allocation), directory
                               record length updated both-endian
    relocate_fs_file(name, d)  ISO9660 file appended at the image end, record repointed
                               (both ported from Xenosaga2PythonExtractor/repack.py)

UDF: every known XS3 image is an ISO9660 + UDF bridge disc (BEA01/NSR02/TEA01
at sectors 18-20, an anchor volume descriptor at sector 256 and in the last
sector: D1 1,915,919, JP1 1,984,399). These primitives keep ONLY the ISO9660
side consistent. After ``append``/``pad_to`` the old trailing UDF anchor sits
mid-image and the UDF partition still describes the old size; after
``write_fs_file``/``relocate_fs_file`` the UDF file entries still give the old
extent and length. The PS2 and PCSX2 read ISO9660 (not booted for XS3 yet);
tools that read or burn through UDF would see an inconsistent image.

The multi-file, copy-based write layer every importer uses is ``patch.py``
(``patch_copy``); these primitives are its single steps.

Commands (``add_commands``): ``list --iso [--chain N]`` and
``dump --iso ... --out OUT [--chain N] [--match S] [--fs [--bigfiles]]``
(OUT/dump/chainN/<path> + OUT/dump/manifest.csv: chain,path,sector,lba,size,sha1;
sector is chain-relative and blank for ISO files, lba is absolute for every row).
"""
from __future__ import annotations

import bisect
import csv
import hashlib
import os
import re
import struct
import sys
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple, Union

from chains import CHAINS, ChainReader, available_chains, chain_files
from iso9660 import IsoImage, SECTOR

# the X3.00-X3.13 / X3.20-X3.23 chain containers in the ISO root
BIGFILE_RE = re.compile(r"(?i)^x3\.\d\d(;1)?$")
from toc_bin import TocEntry, parse_toc

DVD9_SECTORS = 4_173_824          # single-sided dual-layer ceiling
DVD5_SECTORS = 2_295_104          # single layer

SOURCE_CHAIN = {names[0]: c for c, names in CHAINS.items()}


class DiscError(ValueError):
    pass


def norm(path: str) -> str:
    """Canonical lookup key: backslashes, no leading separator, no ';1', lower case."""
    return path.replace("/", "\\").lstrip("\\").split(";")[0].lower()


EntryRef = Union[TocEntry, str]


class Disc:
    def __init__(self, iso_path: str | Path, writable: bool = False,
                 ceiling: Optional[int] = None):
        self.path = Path(iso_path)
        self.writable = writable
        self._ceiling = ceiling              # None = auto (DVD-5 / DVD-9), 0 = no ceiling
        self._wfh = open(self.path, "r+b") if writable else None
        self.iso: Optional[IsoImage] = None
        self._load()

    # -- loading -------------------------------------------------------------

    def _load(self) -> None:
        if self.iso is not None:
            self.iso.close()
        self.iso = IsoImage(self.path)
        self.readers: Dict[int, ChainReader] = {}
        self.index_data: Dict[int, bytes] = {}
        self.entries_by_chain: Dict[int, List[TocEntry]] = {}
        self._index: Dict[str, Tuple[int, TocEntry]] = {}
        self._by_field: Dict[Tuple[int, int], TocEntry] = {}
        self._starts: Dict[int, List[int]] = {}               # chain -> sorted entry starts
        self._at: Dict[Tuple[int, int], List[TocEntry]] = {}  # (chain, start) -> sized entries
        for c in available_chains(self.iso):
            r = ChainReader(self.iso, c)
            data = bytes(r.toc_bytes())
            ents = parse_toc(data, CHAINS[c][0])
            self.readers[c], self.index_data[c], self.entries_by_chain[c] = r, data, ents
            for e in ents:
                self._index.setdefault(norm(e.path), (c, e))
                self._by_field[(c, e.fields_off)] = e
                if e.size > 0:
                    self._at.setdefault((c, e.byte_offset), []).append(e)
            self._starts[c] = sorted({e.byte_offset for e in ents})
        # every object's absolute start byte on the image: the entries of all chains
        # and the ISO9660 file extents. A relocated (appended) entry or ISO file may
        # only grow up to the NEXT of these, whatever chain or filesystem owns it.
        self._abs_starts: List[int] = sorted(
            {self.index_lba(c) * SECTOR + e.byte_offset for c, ents in self.entries_by_chain.items()
             for e in ents}
            | {f.lba * SECTOR for f in self.iso.files.values() if not f.is_dir and f.size > 0})

    def close(self) -> None:
        if self.iso is not None:
            self.iso.close()
            self.iso = None
        if self._wfh is not None:
            self._wfh.close()
            self._wfh = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # -- lookup / read ---------------------------------------------------------

    @property
    def chains(self) -> List[int]:
        return sorted(self.readers)

    def entries(self, chain: Optional[int] = None) -> Iterator[Tuple[int, TocEntry]]:
        for c in self.chains:
            if chain is None or c == chain:
                for e in self.entries_by_chain[c]:
                    yield c, e

    def lookup(self, path: str) -> Optional[Tuple[int, TocEntry]]:
        return self._index.get(norm(path))

    def exists(self, path: str) -> bool:
        return self.lookup(path) is not None or self.iso.find(path) is not None

    def _resolve(self, ref: EntryRef) -> Tuple[int, TocEntry]:
        if isinstance(ref, TocEntry):
            c = SOURCE_CHAIN.get(ref.source)
            if c is None or c not in self.readers:
                raise DiscError(f"entry {ref.path!r} is from {ref.source!r}, not a chain on this image")
            # the entry's fixed fields never move (only their values are patched), so
            # fields_off identifies it across reloads, even when another chain holds
            # the same path
            return c, self._by_field.get((c, ref.fields_off), ref)
        hit = self.lookup(ref)
        if hit is None:
            raise DiscError(f"no index entry for {ref!r}")
        return hit

    def read_entry(self, ref: EntryRef) -> bytes:
        c, e = self._resolve(ref)
        return self.readers[c].read(e.byte_offset, e.size)

    def read(self, path: str) -> bytes:
        """Bytes of an in-game path (index first) or an ISO filesystem file."""
        hit = self.lookup(path)
        if hit is not None:
            return self.read_entry(hit[1])
        f = self.iso.find(path)
        if f is not None and not f.is_dir:
            return bytes(self.iso.read_file(f.path))
        raise FileNotFoundError(f"{path!r} is neither in the disc's index nor in its ISO filesystem")

    def boot_elf_name(self) -> Optional[str]:
        return self.iso.boot_elf_name()

    # -- addresses ---------------------------------------------------------------

    def index_lba(self, chain: int) -> int:
        return self.readers[chain].toc_lba

    def fields_off(self, ref: EntryRef) -> int:
        """Absolute image byte offset of the entry's u24 sector field (u32 size at +3)."""
        c, e = self._resolve(ref)
        return self.index_lba(c) * SECTOR + e.fields_off

    def _next_abs_start(self, abs_start: int) -> int:
        """The first object start (any chain's entry, any ISO9660 extent) after
        ``abs_start``, or the image's volume end."""
        st = self._abs_starts
        i = bisect.bisect_right(st, abs_start)
        end = self._volume_end_sector() * SECTOR
        return min(st[i], end) if i < len(st) else end

    def allocation(self, ref: EntryRef) -> int:
        """Bytes the entry may occupy in place: up to the next entry's start (or the
        chain end); for an already relocated entry (past its chain's end), up to the
        next object on the whole image: an entry of ANY chain (D1 appends chain-1
        files, D2 chain-2 files, after the chain-0 ones), an ISO9660 file moved by
        relocate_fs_file, or the volume end."""
        c, e = self._resolve(ref)
        total = self.readers[c].total
        start = e.byte_offset
        if self.sharers(e):
            # a zero-size entry parked on another file's first sector (D1:
            # ef\esd\ee100\ee105_028.esd on ee106_001.esd, evt\us\s060600.txt
            # on s060720.txt): those bytes belong to the neighbour, so
            # nothing may be written in place
            return 0
        st = self._starts[c]
        i = bisect.bisect_right(st, start)
        end = st[i] if i < len(st) else total
        if start >= total:
            a = self.index_lba(c) * SECTOR + start
            return max(0, self._next_abs_start(a) - a)
        return end - start

    def sharers(self, ref: EntryRef) -> List[TocEntry]:
        """Other entries of the same chain that start on this entry's first byte
        and are not zero-sized placeholders, i.e. the files whose bytes an
        in-place write to ``ref`` would overwrite. Empty for a normal entry."""
        c, e = self._resolve(ref)
        return [x for x in self._at.get((c, e.byte_offset), [])
                if x.fields_off != e.fields_off and norm(x.path) != norm(e.path)]

    def absolute_offset(self, ref: EntryRef) -> int:
        """Absolute image byte offset of the entry's data (the engine's rule:
        index LBA * 2048 + sector * 2048; the chain files are back to back)."""
        c, e = self._resolve(ref)
        return self.index_lba(c) * SECTOR + e.byte_offset

    # -- write primitives -----------------------------------------------------------

    def _need_writable(self, what: str) -> None:
        if not self.writable or self._wfh is None:
            raise DiscError(f"{what}: this Disc was opened read-only (pass writable=True, on a copy)")

    def _pwrite(self, offset: int, data: bytes) -> None:
        self._wfh.seek(offset)
        self._wfh.write(data)
        self._wfh.flush()

    def patch_size(self, ref: EntryRef, new_size: int, usize: Optional[int] = None) -> None:
        """Rewrite the entry's u32 size (and u24 usize for a compressed entry)."""
        self._need_writable("patch_size")
        c, e = self._resolve(ref)
        if not 0 <= new_size < 1 << 32:
            raise DiscError(f"size {new_size} does not fit u32")
        f = self.fields_off(e)
        self._pwrite(f + 3, struct.pack("<I", new_size))
        if e.compressed:
            u = e.usize if usize is None else usize
            if not 0 <= u < 1 << 24:
                raise DiscError(f"usize {u} does not fit u24")
            self._pwrite(f + 7, struct.pack("<I", u)[:3])
        self._load()

    def relocate(self, ref: EntryRef, new_sector: int) -> None:
        """Rewrite the entry's u24 sector (relative to its index file's LBA)."""
        self._need_writable("relocate")
        c, e = self._resolve(ref)
        if not 0 <= new_sector < 1 << 24:
            raise DiscError(f"sector {new_sector} does not fit u24")
        self._pwrite(self.fields_off(e), struct.pack("<I", new_sector)[:3])
        self._load()

    def write_entry(self, ref: EntryRef, data: bytes) -> None:
        """Overwrite the entry in place (must fit its allocation), clear the old tail,
        patch the size field when it changes, read back."""
        self._need_writable("write_entry")
        c, e = self._resolve(ref)
        shared = self.sharers(e)
        if shared:
            raise DiscError(f"{e.path}: starts on the same sector as {shared[0].path} "
                            f"({len(shared)} file(s)); an in-place write would overwrite "
                            "it; use append_entry")
        alloc = self.allocation(e)
        if len(data) > alloc:
            raise DiscError(f"{e.path}: {len(data)} bytes exceed the allocation of {alloc}; use append_entry")
        if e.compressed:
            raise DiscError(f"{e.path}: compressed entries need the codec; not handled here")
        start = self.absolute_offset(e)
        if start + max(len(data), e.size) > self.iso.image_size:
            raise DiscError(f"{e.path}: write past the image end")
        self._pwrite(start, data)
        if len(data) < e.size:
            self._pwrite(start + len(data), bytes(e.size - len(data)))
        if len(data) != e.size:
            self.patch_size(e, len(data))
        else:
            self._load()
        if self.read_entry(e) != data:
            raise DiscError(f"{e.path}: read-back mismatch")

    def sector_ceiling(self) -> int:
        """The most sectors a write may grow the image to: the ``ceiling`` given to the
        constructor, else DVD-9 for a dual-layer image and DVD-5 for a single-layer one
        (every known XS3 image, USA, prototype and Japanese, is single-layer). 0 = none."""
        if self._ceiling is not None:
            return self._ceiling
        return DVD9_SECTORS if self.iso.layer2_pvd_sector is not None else DVD5_SECTORS

    def _volume_end_sector(self) -> int:
        if self.iso.layer2_pvd_sector is not None:
            return self.iso.layer2_base + self.iso.layer2_volume_sectors
        return self.iso.volume_sectors

    def _check_growable(self, what: str, new_total: int) -> None:
        size = self.iso.image_size
        if size % SECTOR:
            raise DiscError(f"{what}: image size is not a multiple of 2048")
        vol_end = self._volume_end_sector()
        if vol_end != size // SECTOR:
            # bytes past the volume end (padding, a trimmed or over-long dump):
            # appended data would land outside the ISO9660 volume (or the
            # volume count would no longer match), so refuse instead
            raise DiscError(f"{what}: the ISO9660 volume ends at sector {vol_end} but the "
                            f"image has {size // SECTOR} sectors; trim or pad the image to its "
                            "volume size first")
        cap = self.sector_ceiling()
        if cap and new_total > cap:
            raise DiscError(f"{what}: the image would grow to {new_total} sectors, past the "
                            f"{'DVD-9' if cap == DVD9_SECTORS else 'DVD-5' if cap == DVD5_SECTORS else 'given'} "
                            f"ceiling of {cap} ({new_total - cap} sectors over); pass a higher "
                            "ceiling (emulator-only images) or make the change smaller")

    def append(self, data: bytes) -> int:
        """Append ``data`` sector-aligned after the last sector of the image, grow the
        volume-space count of the volume that ends the image, return the new LBA."""
        self._need_writable("append")
        size = self.iso.image_size
        sectors = max(1, (len(data) + SECTOR - 1) // SECTOR)
        new_lba = size // SECTOR
        self._check_growable("append", new_lba + sectors)
        pvd_sector = self.iso.layer2_pvd_sector if self.iso.layer2_pvd_sector is not None else 16
        self._wfh.truncate(size + sectors * SECTOR)
        self._pwrite(new_lba * SECTOR, data)
        self._bump_volume(pvd_sector, sectors)
        self._load()
        if bytes(self.iso.mm[new_lba * SECTOR:new_lba * SECTOR + len(data)]) != data:
            raise DiscError("append: read-back mismatch")
        return new_lba

    def pad_to(self, sectors: int) -> int:
        """Grow the image to ``sectors`` sectors with zeros (a sparse extension; no
        bytes are written) and the volume-space count with it. Returns the number of
        sectors added (0 when the image is already that long). Never shrinks."""
        self._need_writable("pad_to")
        cur = self.iso.image_size // SECTOR
        if sectors < cur:
            raise DiscError(f"pad_to: image already has {cur} sectors (> {sectors})")
        if sectors == cur:
            return 0
        self._check_growable("pad_to", sectors)
        pvd_sector = self.iso.layer2_pvd_sector if self.iso.layer2_pvd_sector is not None else 16
        self._wfh.truncate(sectors * SECTOR)
        self._wfh.flush()
        self._bump_volume(pvd_sector, sectors - cur)
        self._load()
        return sectors - cur

    # -- ISO9660 files (boot ELF, OVLs, SYSTEM.CNF, IOP modules) ---------------------

    def _fs_file(self, name: str):
        f = self.iso.find(name)
        if f is None or f.is_dir:
            raise DiscError(f"{name!r} is not a file of the ISO9660 filesystem")
        if BIGFILE_RE.match(f.path.rsplit("\\", 1)[-1]):
            raise DiscError(f"{f.path}: an X3.nn chain container is written entry by entry, "
                            "never as a whole")
        return f

    def fs_allocation(self, name: str) -> int:
        """Bytes available to an ISO9660 file before the next extent of its layer starts
        (or its volume ends)."""
        f = self._fs_file(name)
        later = [g.lba for g in self.iso.files.values()
                 if g.layer == f.layer and g.lba > f.lba]
        end = min(later) * SECTOR if later else self._volume_end_sector() * SECTOR
        # an index entry appended after a relocated ISO file bounds it too
        end = min(end, self._next_abs_start(f.lba * SECTOR))
        return end - f.lba * SECTOR

    def _set_record(self, f, lba: Optional[int], size: int) -> None:
        r = f.record_off
        if lba is not None:
            rec_lba = lba - (self.iso.layer2_base if f.layer else 0)
            self._pwrite(r + 2, struct.pack("<I", rec_lba) + struct.pack(">I", rec_lba))
        self._pwrite(r + 10, struct.pack("<I", size) + struct.pack(">I", size))

    def write_fs_file(self, name: str, data: bytes) -> None:
        """Replace an ISO9660 file in place (must fit before the next extent), clear the
        stale tail, update the directory record's length; XS2 repack.patch_fs_file."""
        self._need_writable("write_fs_file")
        f = self._fs_file(name)
        alloc = self.fs_allocation(name)
        if len(data) > alloc:
            raise DiscError(f"{f.path}: {len(data)} bytes exceed the {alloc} bytes before the "
                            "next extent; use relocate_fs_file")
        start = f.lba * SECTOR
        self._pwrite(start, data)
        if len(data) < f.size:
            self._pwrite(start + len(data), bytes(f.size - len(data)))
        if len(data) != f.size:
            self._set_record(f, None, len(data))
        self._load()
        if bytes(self.iso.read_file(self._fs_file(name).path)) != data:
            raise DiscError(f"{f.path}: read-back mismatch")

    def relocate_fs_file(self, name: str, data: bytes) -> int:
        """Append an ISO9660 file's new content at the image end and repoint its
        directory record (extent + length); XS2 repack.relocate_fs_file. Returns the LBA."""
        self._need_writable("relocate_fs_file")
        f = self._fs_file(name)
        lba = self.append(data)
        f = self._fs_file(name)               # re-read after the append reloaded the image
        self._set_record(f, lba, len(data))
        self._load()
        if bytes(self.iso.read_file(self._fs_file(name).path)) != data:
            raise DiscError(f"{f.path}: read-back mismatch after relocation")
        return lba

    def _bump_volume(self, pvd_sector: int, sectors: int) -> None:
        """Grow the both-endian volume-space count (PVD bytes 80..88); XS2 repack._bump_volume."""
        base = pvd_sector * SECTOR
        old = struct.unpack_from("<I", self.iso.mm, base + 80)[0]
        new = old + sectors
        self._pwrite(base + 80, struct.pack("<I", new) + struct.pack(">I", new))

    def append_entry(self, ref: EntryRef, data: bytes) -> int:
        """Grow an entry: append its new bytes at the image end and repoint its index
        entry there (sector = new LBA - index LBA, size = len(data)). Returns the LBA."""
        self._need_writable("append_entry")
        c, e = self._resolve(ref)
        if e.compressed:
            raise DiscError(f"{e.path}: compressed entries need the codec; not handled here")
        lba = self.append(data)
        sector = lba - self.index_lba(c)
        self.relocate(e, sector)
        self.patch_size(e, len(data))
        if self.read_entry(e) != data:
            raise DiscError(f"{e.path}: read-back mismatch after relocation")
        return lba


# ------------------------------------------------------------------------ CLI

def _open_set(paths: List[str]) -> List[Disc]:
    discs = [Disc(p) for p in paths]
    if len(discs) > 1:
        try:
            from region import warn_mixed
            warn_mixed(discs)
        except ImportError:
            pass
    return discs


def _cmd_list(a) -> int:
    discs = _open_set(a.iso)
    seen = set()
    try:
        for d in discs:
            for c in d.chains:
                if (a.chain is not None and c != a.chain) or c in seen:
                    continue
                seen.add(c)
                for _, e in d.entries(c):
                    print(f"chain{c}\t{e.sector}\t{e.size}\t{e.path}")
        if a.chain is not None and a.chain not in seen:
            print(f"chain {a.chain} is not on the given image(s)", file=sys.stderr)
            return 1
    except BrokenPipeError:              # `list ... | head`
        sys.stdout = open(os.devnull, "w")
    finally:
        for d in discs:
            d.close()
    return 0


def _safe_rel(path: str) -> Path:
    parts = [p for p in path.replace("\\", "/").split("/") if p not in ("", ".", "..")]
    return Path(*parts)


def _cmd_dump(a) -> int:
    out = Path(a.out) / "dump"
    out.mkdir(parents=True, exist_ok=True)
    discs = _open_set(a.iso)
    seen = set()
    n = 0
    match = a.match.lower() if a.match else None
    try:
        with open(out / "manifest.csv", "w", newline="") as fh:
            w = csv.writer(fh)
            # sector: chain-relative (what the index stores; blank for ISO files);
            # lba: absolute image sector for every row
            w.writerow(["chain", "path", "sector", "lba", "size", "sha1"])
            iso_sha: Dict[str, str] = {}
            for k, d in enumerate(discs):
                if a.fs:
                    for f in sorted(d.iso.files.values(), key=lambda f: f.lba):
                        if f.is_dir or (match and match not in f.path.lower()):
                            continue
                        if BIGFILE_RE.match(re.split(r"[\\/]", f.path)[-1]) and not a.bigfiles:
                            continue          # the chains: dumped file by file below
                        data = bytes(d.iso.read_file(f.path))
                        sha = hashlib.sha1(data).hexdigest()
                        key = f.path.lower()
                        if key in iso_sha and iso_sha[key] == sha:
                            continue          # same file on an earlier disc
                        # a name already dumped with other bytes (Disc 2's
                        # SYSTEM.CNF boots SLUS_214.17) goes to iso-discN/
                        label = "iso" if key not in iso_sha else f"iso-disc{k + 1}"
                        iso_sha.setdefault(key, sha)
                        dst = out / label / _safe_rel(f.path)
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        dst.write_bytes(data)
                        w.writerow([label, f.path, "", f.lba, f.size, sha])
                        n += 1
                for c in d.chains:
                    if (a.chain is not None and c != a.chain) or c in seen:
                        continue
                    seen.add(c)
                    for _, e in d.entries(c):
                        if match and match not in e.path.lower():
                            continue
                        data = d.read_entry(e)
                        dst = out / f"chain{c}" / _safe_rel(e.path)
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        dst.write_bytes(data)
                        w.writerow([c, e.path, e.sector, d.index_lba(c) + e.sector, e.size,
                                    hashlib.sha1(data).hexdigest()])
                        n += 1
    finally:
        for d in discs:
            d.close()
    print(f"dumped {n} files to {out} (manifest.csv)")
    return 0


def add_commands(subparsers) -> None:
    """Register ``list`` and ``dump`` (both read the disc's own index; no 7-Zip)."""
    p = subparsers.add_parser("list", help="list the files in the disc's own X3.x0 indexes")
    p.add_argument("--iso", required=True, action="append", help="image (repeat for Disc 1 + Disc 2)")
    p.add_argument("--chain", type=int, choices=sorted(CHAINS), help="only this chain")
    p.set_defaults(func=_cmd_list)
    p = subparsers.add_parser("dump", help="dump every indexed file to OUT/dump/chainN/... with manifest.csv")
    p.add_argument("--iso", required=True, action="append", help="image (repeat for Disc 1 + Disc 2; "
                   "chain 0 is taken from the first)")
    p.add_argument("--out", required=True)
    p.add_argument("--chain", type=int, choices=sorted(CHAINS), help="only this chain")
    p.add_argument("--match", help="only paths containing this text (case-insensitive)")
    p.add_argument("--fs", action="store_true",
                   help="also dump the ISO9660 files (SYSTEM.CNF, boot ELF, OVLs, IOP modules) to "
                        "OUT/dump/iso/; a file whose bytes differ on a later --iso goes to "
                        "OUT/dump/iso-discN/. The X3.nn chain containers are skipped (their "
                        "contents are what the chainN/ folders hold) unless --bigfiles is given")
    p.add_argument("--bigfiles", action="store_true",
                   help="with --fs: also copy the raw X3.nn containers (about 4 GB per disc)")
    p.set_defaults(func=_cmd_dump)


# ------------------------------------------------------------------ self-test

def _synthetic_image(path: Path) -> None:
    """A chain-0 image: X3.00 index (1 sector) + X3.01 (3 sectors) + X3.02, packed
    back to back like retail, plus SYSTEM.CNF and a stand-in boot ELF."""
    from iso9660 import make_test_image
    from toc_bin import Event, serialize
    a = b"menu text one\x00" * 40                      # 560 bytes
    b = bytes(range(256)) * 10                         # 2560 bytes (2 sectors allocated)
    c = b"\x55" * 3000
    ev = [Event("dir", name=b"mnu"), Event("dir", name=b"us"),
          Event("file", name=b"menutext.txd", sector=1, size=len(a)),
          Event("file", name=b"font0.bin", sector=2, size=len(b)),
          Event("file", name=b"empty.bin", sector=2, size=0),   # parked on font0.bin
          Event("pop"), Event("pop"),
          Event("dir", name=b"cf"),
          Event("file", name=b"Big.SB", sector=4, size=len(c)),
          Event("pop")]
    idx = serialize(ev, 1)
    x301 = (a.ljust(SECTOR, b"\0") + b.ljust(2 * SECTOR, b"\0"))
    x302 = c
    make_test_image(path, [("SYSTEM.CNF", b"BOOT2 = cdrom0:\\SLUS_999.99;1\r\n"),
                           ("SLUS_999.99", b"\x7fELF-standin"),
                           ("X3.00", idx), ("X3.01", x301), ("X3.02", x302)])


def _sparse_copy(src: str, dst: Path, ranges: List[Tuple[int, int]]) -> None:
    """A copy of ``src`` with only the given (lba, sectors) ranges filled in and the
    rest left as holes: same length and layout, a few MB on disk. Read-only on src."""
    size = os.path.getsize(src)
    with open(src, "rb") as s, open(dst, "wb") as d:
        d.truncate(size)
        for lba, n in ranges:
            s.seek(lba * SECTOR)
            d.seek(lba * SECTOR)
            d.write(s.read(n * SECTOR))


def self_test() -> int:
    import tempfile
    from toc_bin import rebuild

    ok = True

    def check(cond, msg):
        nonlocal ok
        print(("ok    " if cond else "FAIL  ") + msg)
        ok &= bool(cond)

    def raises(fn, exc, msg):
        try:
            fn()
            check(False, msg)
        except exc:
            check(True, msg)

    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "syn.iso"
        _synthetic_image(p)
        with Disc(p) as d:
            check(d.chains == [0], "synthetic: chain 0 found")
            t = d.read("\\mnu\\us\\menutext.txd")
            check(t == b"menu text one\x00" * 40, "read by in-game path")
            check(d.read("MNU/US/MENUTEXT.TXD") == t and d.read("mnu\\US\\menutext.txd") == t,
                  "lookup is case-insensitive, / or \\, leading separator optional")
            check(d.read("cf\\big.sb") == b"\x55" * 3000, "read spans X3.01 -> X3.02")
            check(d.read("slus_999.99") == b"\x7fELF-standin", "ISO root files resolve too")
            raises(lambda: d.read("nope\\x.bin"), FileNotFoundError, "a missing path is FileNotFoundError")
            f = d.fields_off("mnu\\us\\font0.bin")
            mm = d.iso.mm
            check(int.from_bytes(mm[f:f + 3], "little") == 2 and int.from_bytes(mm[f + 3:f + 7], "little") == 2560,
                  "fields_off is the absolute offset of u24 sector / u32 size")
            check(d.allocation("mnu\\us\\menutext.txd") == SECTOR and d.allocation("mnu\\us\\font0.bin") == 2 * SECTOR,
                  "allocation = gap to the next entry")
            raises(lambda: d.patch_size("mnu\\us\\font0.bin", 1), DiscError, "read-only Disc refuses writes")
            check(d.allocation("mnu\\us\\empty.bin") == 0
                  and [norm(x.path) for x in d.sharers("mnu\\us\\empty.bin")] == ["mnu\\us\\font0.bin"]
                  and d.sharers("mnu\\us\\font0.bin") == [],
                  "a zero-size entry on font0.bin's sector: allocation 0, font0.bin is its sharer")
        before = p.read_bytes()
        with Disc(p, writable=True) as d:
            old_idx = d.index_data[0]
            d.patch_size("mnu\\us\\menutext.txd", 500)
            new_idx = d.index_data[0]
            diff = [i for i in range(len(old_idx)) if old_idx[i] != new_idx[i]]
            check(d.lookup("mnu\\us\\menutext.txd")[1].size == 500, "patch_size: re-parse sees the new size")
            check(len(diff) <= 4 and all(d.fields_off("mnu\\us\\menutext.txd") - d.index_lba(0) * SECTOR + 3 <= i
                                         < d.fields_off("mnu\\us\\menutext.txd") - d.index_lba(0) * SECTOR + 7
                                         for i in diff), "patch_size: only the 4 size bytes change")
            check(rebuild(new_idx) == new_idx, "patched index still rebuilds byte for byte")
            raises(lambda: d.write_entry("mnu\\us\\empty.bin", b"Z" * 1000), DiscError,
                   "write_entry refuses a zero-size entry that shares font0.bin's sector")
            check(d.read("mnu\\us\\font0.bin") == bytes(range(256)) * 10, "font0.bin untouched by that attempt")
            d.write_entry("mnu\\us\\menutext.txd", b"SHORTER")
            check(d.read("mnu\\us\\menutext.txd") == b"SHORTER", "write_entry in place, size patched")
            raises(lambda: d.write_entry("mnu\\us\\menutext.txd", bytes(SECTOR + 1)), DiscError,
                   "write_entry refuses data past the allocation")
            vol0, img0 = d.iso.volume_sectors, d.iso.image_size // SECTOR
            big = b"GROWN" * 1000                      # 5000 bytes, 3 sectors
            lba = d.append_entry("mnu\\us\\menutext.txd", big)
            check(lba == img0, "append_entry: data lands at the old image end")
            check(d.iso.image_size // SECTOR == img0 + 3 and d.iso.volume_sectors == vol0 + 3,
                  "append: image and PVD volume space grow by 3 sectors (both-endian field)")
            check(struct.unpack_from(">I", d.iso.mm, 16 * SECTOR + 84)[0] == vol0 + 3, "PVD big-endian copy bumped")
            e = d.lookup("mnu\\us\\menutext.txd")[1]
            check(e.sector == lba - d.index_lba(0) and e.size == 5000, "relocate: index points at the new LBA")
            check(d.read("mnu\\us\\menutext.txd") == big, "read follows the relocated entry past the chain")
            check(d.read("cf\\big.sb") == b"\x55" * 3000 and d.read("mnu\\us\\font0.bin") == bytes(range(256)) * 10,
                  "other entries unchanged")
            raises(lambda: d.relocate("cf\\big.sb", 1 << 24), DiscError, "relocate refuses a sector past u24")
        with IsoImage(p) as iso:
            check(iso.volume_sectors * SECTOR == iso.image_size, "grown image re-opens as ISO9660, volume = image")
        check(len(before) < p.stat().st_size, "the scratch image (not an original) is what grew")
        # an image with bytes past its volume end: append must refuse
        q = Path(td) / "padded.iso"
        _synthetic_image(q)
        with open(q, "ab") as fh:
            fh.write(bytes(5 * SECTOR))
        size0 = q.stat().st_size
        with Disc(q, writable=True) as d:
            raises(lambda: d.append_entry("cf\\big.sb", b"Q" * 5000), DiscError,
                   "append refuses an image with 5 sectors past its volume end")
        check(q.stat().st_size == size0, "refused append left the padded image unchanged")
        # sector ceiling, pad_to, ISO9660 file writes
        r = Path(td) / "ceil.iso"
        _synthetic_image(r)
        n0 = r.stat().st_size // SECTOR
        with Disc(r, writable=True, ceiling=n0 + 2) as d:
            check(d.sector_ceiling() == n0 + 2, "an explicit ceiling overrides the DVD-5/DVD-9 default")
            raises(lambda: d.append_entry("cf\\big.sb", b"Q" * 5000), DiscError,
                   "append refuses to grow the image past the ceiling (3 sectors > 2 left)")
            check(d.iso.image_size // SECTOR == n0 and d.read("cf\\big.sb") == b"\x55" * 3000,
                  "refused grow left image and index untouched")
            added = d.pad_to(n0 + 1)
            check(added == 1 and d.iso.image_size // SECTOR == n0 + 1 and d.iso.volume_sectors == n0 + 1,
                  "pad_to grows image and PVD volume count together")
            raises(lambda: d.pad_to(n0), DiscError, "pad_to never shrinks")
            raises(lambda: d.pad_to(n0 + 3), DiscError, "pad_to obeys the ceiling")
        with Disc(r) as d:
            check(d.sector_ceiling() == DVD5_SECTORS, "a single-layer image defaults to the DVD-5 ceiling")
        with Disc(r, writable=True) as d:
            alloc = d.fs_allocation("SYSTEM.CNF")
            check(alloc == SECTOR, "fs_allocation of SYSTEM.CNF = one sector (gap to the ELF)")
            cnf = b"BOOT2 = cdrom0:\\SLUS_999.99;1\r\nVER = 1.01\r\n"
            d.write_fs_file("SYSTEM.CNF", cnf)
            check(d.read("SYSTEM.CNF") == cnf and d.iso.find("SYSTEM.CNF").size == len(cnf),
                  "write_fs_file: new bytes, directory record length updated")
            raises(lambda: d.write_fs_file("SYSTEM.CNF", bytes(SECTOR + 1)), DiscError,
                   "write_fs_file refuses data past the next extent")
            raises(lambda: d.write_fs_file("X3.01", b"x"), DiscError, "X3.nn containers are refused as files")
            elf = b"\x7fELF-grown" * 500
            lba = d.relocate_fs_file("SLUS_999.99", elf)
            check(d.iso.find("SLUS_999.99").lba == lba and d.read("SLUS_999.99") == elf
                  and d.boot_elf_name() == "SLUS_999.99", "relocate_fs_file repoints the record past the end")
            check(d.read("mnu\\us\\menutext.txd") == b"menu text one\x00" * 40, "index entries unaffected")
        # dump --fs: X3.nn skipped by default, differing same-name files kept per disc
        import argparse
        q2 = Path(td) / "other.iso"
        from iso9660 import make_test_image
        make_test_image(q2, [("SYSTEM.CNF", b"BOOT2 = cdrom0:\\SLUS_888.88;1\r\n"),
                             ("SLUS_999.99", b"\x7fELF-standin")])
        ap = argparse.ArgumentParser()
        add_commands(ap.add_subparsers(dest="cmd"))
        outd = Path(td) / "dumped"
        ns = ap.parse_args(["dump", "--iso", str(q), "--iso", str(q2), "--out", str(outd), "--fs"])
        ns.func(ns)
        rows = list(csv.reader(open(outd / "dump" / "manifest.csv")))
        isorows = [r for r in rows[1:] if r[0].startswith("iso")]
        names = sorted((r[0], r[1].upper()) for r in isorows)
        check(rows[0] == ["chain", "path", "sector", "lba", "size", "sha1"]
              and not any("X3." in n for _, n in names),
              "dump --fs skips the X3.nn containers, manifest has sector + lba columns")
        check(sum(1 for lab, n in names if n.endswith("SYSTEM.CNF")) == 2
              and (outd / "dump" / "iso-disc2").exists()
              and sum(1 for lab, n in names if n.endswith("SLUS_999.99")) == 1,
              "dump --fs keeps Disc 2's differing SYSTEM.CNF (iso-disc2/), dedups identical files")
        crow = [r for r in rows[1:] if r[0] == "0" and r[1].lower().endswith("font0.bin")][0]
        with Disc(q) as d:
            check(int(crow[3]) * SECTOR == d.absolute_offset("mnu\\us\\font0.bin")
                  and int(crow[2]) == 2, "manifest chain row: chain-relative sector + absolute lba")

    discs = {k: os.environ[v] for k, v in (("D1", "XS3_D1"), ("D2", "XS3_D2"), ("PROTO", "XS3_PROTO"))
             if os.environ.get(v)}
    if not discs:
        print("SKIP  disc checks (set XS3_D1 / XS3_D2 / XS3_PROTO)")
    want_txd = {"D1": 15388, "D2": 15388, "PROTO": 15486}
    for k, path in discs.items():
        with Disc(path) as d:
            t = d.read("\\mnu\\us\\menutext.txd")
            check(len(t) == want_txd[k], f"{k}: \\mnu\\us\\menutext.txd = {len(t)} bytes")
            if k == "PROTO":
                check(t.endswith(b"uipment screen.\x00"), "PROTO: menutext.txd ends 'uipment screen.\\0' (real text, not padding)")
            boot = d.boot_elf_name()
            check(d.read(boot)[:4] == b"\x7fELF", f"{k}: boot ELF {boot} resolves through the ISO filesystem")
            c, e = d.lookup("mnu\\us\\font0.bin")
            f = d.fields_off(e)
            mm = d.iso.mm
            check(int.from_bytes(mm[f:f + 3], "little") == e.sector and int.from_bytes(mm[f + 3:f + 7], "little") == e.size == 494592,
                  f"{k}: fields_off reads back mnu\\us\\font0.bin's own sector/size from the image")
    if "D1" in discs:
        # a sparse copy of Disc 1 (real PVD, directories and both indexes; holes elsewhere)
        with tempfile.TemporaryDirectory() as td:
            src = discs["D1"]
            with IsoImage(src) as iso:
                x310 = iso.files["X3.10"]
                ranges = [(0, iso.files["X3.01"].lba), (x310.lba, x310.size // SECTOR)]
            cp = Path(td) / "d1-sparse.iso"
            _sparse_copy(src, cp, ranges)
            with Disc(cp, writable=True) as d:
                path = "mnu\\us\\menutext.txd"
                old = d.index_data[0]
                d.patch_size(path, 15388 - 100)
                new = d.index_data[0]
                check(sum(1 for x, y in zip(old, new) if x != y) <= 4 and rebuild(new) == new,
                      "D1 sparse copy: patch_size changes <= 4 index bytes, index still rebuilds")
                lba = d.append_entry(path, b"X" * 20000)
                e = d.lookup(path)[1]
                check(e.sector == lba - 3114 and d.read(path) == b"X" * 20000,
                      "D1 sparse copy: append_entry relocates past X3.13, reads back")
                check(len(list(d.entries(0))) == 9867 and len(list(d.entries(1))) == 3649,
                      "D1 sparse copy: entry counts unchanged")
                z = "ef\\esd\\ee100\\ee105_028.esd"
                check(d.allocation(z) == 0 and any(x.path.lower().endswith("ee106_001.esd")
                                                     for x in d.sharers(z)),
                      "D1: zero-size ee105_028.esd shares ee106_001.esd's sector, allocation 0")
                raises(lambda: d.write_entry(z, b"Z" * 1000), DiscError,
                       "D1: write_entry on ee105_028.esd is refused (would overwrite ee106_001.esd)")
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
