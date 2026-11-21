"""chains.py — Episode III's three bigfile chains.

Borrowed from Xenosaga2PythonExtractor/chains.py (itself the XS1 module with
the table changed), 2026-11-20. What changed: the chain table (X3.* names,
four or three files per chain instead of five), ``chain_extents`` /
``contiguous`` to check the back-to-back layout, ``self_test`` and a no-op
``add_commands`` (the ``list`` / ``dump`` commands live in ``disc.py``).

An index's sector numbers address one virtual byte space formed by the index
file itself followed by its sibling bigfiles:

    chain 0:  X3.00 + X3.01 + X3.02            on both discs, byte-identical index
    chain 1:  X3.10 + X3.11 + X3.12 + X3.13    Disc 1 (and the May 2006 prototype)
    chain 2:  X3.20 + X3.21 + X3.22 + X3.23    Disc 2

Verified 2026-11-20 on the three images: every chain's files sit back to back
on the image (each starts at the previous one's LBA + sector count), X3.00 at
LBA 3114 on all three; chain 1 starts at LBA 807414 on Disc 1 and 807439 on
the prototype (whose X3.02 is 51,200 bytes larger), chain 2 at 807414 on
Disc 2. The engine reads by raw sector (LBA = index LBA + entry sector),
which is why ``read`` falls back to absolute addressing for an object
relocated past the chain's own extents (the XS1/XS2 grow rule; not yet
checked in-game for XS3).
"""
from __future__ import annotations

import sys
from typing import Iterator, List, Optional, Tuple

from iso9660 import IsoImage, SECTOR

CHAINS: dict[int, List[str]] = {
    0: ["X3.00", "X3.01", "X3.02"],
    1: ["X3.10", "X3.11", "X3.12", "X3.13"],
    2: ["X3.20", "X3.21", "X3.22", "X3.23"],
}

CHUNK = 8 * 1024 * 1024


def chain_files(iso: IsoImage, chain: int) -> Optional[List[str]]:
    """The ISO paths of CHAIN's bigfiles on this image: at the root, else in the one
    directory that holds all of them, else None."""
    names = CHAINS[chain]
    if all(n in iso.files for n in names):
        return list(names)
    dirs = sorted({p[:-len(names[0])] for p, f in iso.files.items()
                   if not f.is_dir and p.upper().endswith("\\" + names[0])})
    for d in dirs:
        if all(d + n in iso.files for n in names):
            return [d + n for n in names]
    return None


def available_chains(iso: IsoImage) -> List[int]:
    """Chains whose files all exist on this image: [0, 1] on Disc 1 and the prototype,
    [0, 2] on Disc 2."""
    return [c for c in CHAINS if chain_files(iso, c) is not None]


def disc_number(iso: IsoImage) -> int:
    """1 or 2, from which story chain the image carries (0 if neither)."""
    have = available_chains(iso)
    return 1 if 1 in have else 2 if 2 in have else 0


def chain_extents(iso: IsoImage, chain: int) -> List[Tuple[str, int, int]]:
    """(name, LBA, size) of each file of the chain, in chain order."""
    names = chain_files(iso, chain)
    if names is None:
        raise FileNotFoundError(f"{CHAINS[chain][0]} chain missing from ISO filesystem")
    return [(n, iso.files[n].lba, iso.files[n].size) for n in names]


def contiguous(iso: IsoImage, chain: int) -> bool:
    """True when every file of the chain starts where the previous one's sectors end
    and every file but the last is a whole number of sectors (the layout the
    engine's raw-sector reads assume)."""
    ext = chain_extents(iso, chain)
    for (_, lba, size), (_, nlba, _) in zip(ext, ext[1:]):
        if size % SECTOR or nlba != lba + size // SECTOR:
            return False
    return True


class ChainReader:
    def __init__(self, iso: IsoImage, chain: int):
        self.iso = iso
        self.chain = chain
        names = chain_files(iso, chain)
        if names is None:
            raise FileNotFoundError(f"{CHAINS[chain][0]} chain missing from ISO filesystem")
        self.names = names
        self.sizes = [iso.files[n].size for n in self.names]
        self.total = sum(self.sizes)
        self.toc_lba = iso.files[self.names[0]].lba

    def toc_bytes(self) -> bytes:
        return self.iso.read_file(self.names[0])

    def read_iter(self, offset: int, length: int) -> Iterator[bytes]:
        """Yield the byte range [offset, offset+length) of the chain in chunks,
        transparently spanning bigfile boundaries."""
        if offset + length > self.total:
            # relocated object: the engine addresses by absolute sector
            start = self.toc_lba * SECTOR + offset
            if start + length > self.iso.image_size:
                raise ValueError(f"read past image end: chain offset {offset}+{length}")
            yield self.iso.mm[start:start + length]
            return
        remaining = length
        for name, size in zip(self.names, self.sizes):
            if offset >= size:
                offset -= size
                continue
            take = min(remaining, size - offset)
            pos = 0
            while pos < take:
                n = min(CHUNK, take - pos)
                yield self.iso.read_file(name, offset + pos, n)
                pos += n
            remaining -= take
            offset = 0
            if remaining == 0:
                return

    def read(self, offset: int, length: int) -> bytes:
        return b"".join(self.read_iter(offset, length))

    def locate(self, offset: int) -> Tuple[str, int]:
        """Map a chain byte offset to (bigfile name, offset within it)."""
        for name, size in zip(self.names, self.sizes):
            if offset < size:
                return name, offset
            offset -= size
        raise ValueError(f"offset {offset} beyond chain end")


# ------------------------------------------------------------------ self-test

def self_test() -> int:
    import os
    import tempfile
    from pathlib import Path
    from iso9660 import make_test_image

    ok = True

    def check(cond, msg):
        nonlocal ok
        print(("ok    " if cond else "FAIL  ") + msg)
        ok &= bool(cond)

    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "t.iso"
        a = bytes([1]) + bytes(SECTOR - 1)
        b = bytes(range(256)) * 16          # 2 sectors
        c = b"tail-of-chain" * 10
        make_test_image(p, [("X3.00", a), ("X3.01", b), ("X3.02", c)], tail_sectors=4)
        with IsoImage(p) as iso:
            check(available_chains(iso) == [0] and disc_number(iso) == 0, "only chain 0 present")
            check(contiguous(iso, 0), "synthetic chain is back to back")
            r = ChainReader(iso, 0)
            check(r.total == len(a) + len(b) + len(c), "chain total = sum of file sizes")
            span = r.read(len(a) + len(b) - 5, 10)
            check(span == b[-5:] + c[:5], "a read spans a bigfile boundary")
            check(r.locate(len(a) + 3) == ("X3.01", 3), "locate maps offset to (file, offset)")
            far = r.read(r.total + 100, 4)          # past the chain: absolute-sector rule
            check(far == bytes(4), "a read past the chain end uses absolute sectors")

    discs = {k: os.environ[v] for k, v in (("D1", "XS3_D1"), ("D2", "XS3_D2"), ("PROTO", "XS3_PROTO"))
             if os.environ.get(v)}
    if not discs:
        print("SKIP  disc checks (set XS3_D1 / XS3_D2 / XS3_PROTO)")
    want = {"D1": ([0, 1], 807414), "D2": ([0, 2], 807414), "PROTO": ([0, 1], 807439)}
    for k, path in discs.items():
        with IsoImage(path) as iso:
            have = available_chains(iso)
            check(have == want[k][0], f"{k}: chains {have}")
            for ch in have:
                check(contiguous(iso, ch), f"{k}: chain {ch} ({', '.join(CHAINS[ch])}) back to back")
            story = have[1]
            check(iso.files[CHAINS[story][0]].lba == want[k][1],
                  f"{k}: {CHAINS[story][0]} at LBA {iso.files[CHAINS[story][0]].lba}")
            r = ChainReader(iso, 0)
            check(r.toc_bytes()[0] == 55, f"{k}: X3.00 byte 0 = 55 sectors")
    print("self-test", "passed" if ok else "FAILED")
    return 0 if ok else 1


def add_commands(subparsers) -> None:
    """No commands of its own: ``list`` and ``dump`` are registered by ``disc.py``."""
    return None


if __name__ == "__main__":
    if sys.argv[1:] == ["--self-test"]:
        sys.exit(self_test())
    print(__doc__)
