#!/usr/bin/env python3
"""repack.py — depack/repack any file on the Xenosaga III discs, in place.

The general write-back layer for the kit (chrtex.py is the texture-aware
front end; this works on whole files of any type). Resolves in-game paths
through the Lba tables and the ISO9660 root to absolute ISO offsets and
patches ISOs directly — no container rebuild, no re-mastering.

Disc model (docs/disc-catalog.md): files live inside X3.* "bigfile"
containers; each Lba*.txt table is a byte-addressed space over a chain of
containers. Offsets in the engine's own binary catalogs (X3.00/X3.10/
X3.20) are implicit — files pack back-to-back at 2048-byte sector
granularity — so files cannot move or change sector count without
rebuilding a whole container. What CAN be done, and what this tool does:

  * replace a file with one of the same size (always safe), or
  * a smaller/slightly larger one that still fits the file's sector
    allocation (``--pad``): the written file is zero-padded to the
    original allocation. The engine still reads the *original* byte
    length, so this is only correct for formats that self-describe their
    size (Xc packages, ADX, txy, …) — hence opt-in.

Every write is verified by reading it back.

Commands:
  info    <iso> <discpath>            resolution, slack, duplicate copies
  extract <iso> <discpath> <out>      pull one file
  patch   <iso> <discpath> <file>     write one file back  [--pad]
  tree    <iso> <moddir>              patch every file in a mirror tree
                                      (moddir/mdl/chr/... = \\mdl\\chr\\...)
                                      [--pad] [--dry-run]

<discpath> is the in-game path as in the Lba tables, e.g.
\\mdl\\chr\\pc\\C3kosmos00.chr (quote it in the shell). Forward slashes
are accepted. Work on a COPY of your ISO (macOS: ``cp -c`` is instant).
"""
from __future__ import annotations

import struct
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

HERE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
SECTOR = 2048

# Which containers make up each Lba address space, in chain order.
# Lba0 (shared system/UI/model data) is identical on both discs; Lba1 is
# Disc 1's story content, Lba2 is Disc 2's. See docs/disc-catalog.md.
CHAINS = {
    "Lba0.txt": ["X3.01", "X3.02"],
    "Lba1.txt": ["X3.11", "X3.12", "X3.13"],
    "Lba2.txt": ["X3.21", "X3.22", "X3.23"],
}


@dataclass(frozen=True)
class Row:
    source: str        # Lba table filename
    offset: int        # byte offset in the table's address space
    size: int          # byte length
    alloc: int         # sector allocation (gap to the next entry)
    path: str          # in-game path as written in the table


class Disc:
    """One ISO: its root directory extents plus the applicable Lba tables."""

    def __init__(self, iso_path: str, lba_dir: Optional[str] = None):
        self.iso_path = Path(iso_path)
        self.extents = self._read_root(self.iso_path)
        lba = Path(lba_dir) if lba_dir else HERE / "lba"
        self.rows: Dict[str, Row] = {}
        self.sources: List[str] = []
        for source, chain in CHAINS.items():
            if not (lba / source).exists():
                continue
            if not all(c in self.extents for c in chain):
                continue                      # e.g. Lba1 chain absent on Disc 2
            self.sources.append(source)
            self._load_table(lba / source, source, chain)

    @staticmethod
    def _read_root(iso_path: Path) -> Dict[str, Tuple[int, int]]:
        """name -> (byte offset in ISO, size) for every ISO root file."""
        with open(iso_path, "rb") as f:
            f.seek(16 * SECTOR)
            pvd = f.read(SECTOR)
            if pvd[1:6] != b"CD001":
                sys.exit(f"{iso_path}: not an ISO9660 image")
            rext, = struct.unpack("<I", pvd[156 + 2:156 + 6])
            rsz, = struct.unpack("<I", pvd[156 + 10:156 + 14])
            f.seek(rext * SECTOR)
            d = f.read(rsz)
        out, off = {}, 0
        while off < rsz:
            ln = d[off]
            if ln == 0:
                off = (off // SECTOR + 1) * SECTOR
                continue
            ext, = struct.unpack("<I", d[off + 2:off + 6])
            sz, = struct.unpack("<I", d[off + 10:off + 14])
            nl = d[off + 32]
            name = d[off + 33:off + 33 + nl].split(b";")[0].decode("latin1")
            if name not in ("\x00", "\x01"):
                out[name] = (ext * SECTOR, sz)
            off += ln
        return out

    def _load_table(self, path: Path, source: str, chain: List[str]) -> None:
        entries = []
        for line in path.read_text().splitlines():
            p = line.strip().split("|")
            if len(p) != 4:
                continue
            entries.append((int(p[0], 16), int(p[1], 16), p[3]))
        entries.sort()
        chain_end = sum(self.extents[c][1] for c in chain)
        for i, (off, size, gpath) in enumerate(entries):
            nxt = entries[i + 1][0] if i + 1 < len(entries) else chain_end
            self.rows[gpath.lower()] = Row(source, off, size, nxt - off, gpath)

    # -- resolution ---------------------------------------------------------

    def row(self, discpath: str) -> Row:
        key = discpath.strip().replace("/", "\\").lower()
        if not key.startswith("\\"):
            key = "\\" + key
        r = self.rows.get(key)
        if not r:
            sys.exit(f"{discpath}: not found in {'/'.join(self.sources)} "
                     f"(is this the right disc?)")
        return r

    def iso_offset(self, r: Row) -> int:
        cum = 0
        for name in CHAINS[r.source]:
            base, size = self.extents[name]
            if r.offset < cum + size:
                return base + (r.offset - cum)
            cum += size
        sys.exit(f"{r.path}: offset 0x{r.offset:X} beyond {r.source} chain")

    # -- operations ---------------------------------------------------------

    def read(self, r: Row) -> bytes:
        with open(self.iso_path, "rb") as f:
            f.seek(self.iso_offset(r))
            return f.read(r.size)

    def write(self, r: Row, data: bytes, pad: bool) -> None:
        if len(data) != r.size:
            if not pad:
                sys.exit(f"{r.path}: size mismatch (slot {r.size}, file "
                         f"{len(data)}). Same-size only unless --pad.")
            if len(data) > r.alloc:
                sys.exit(f"{r.path}: {len(data)} bytes exceeds the sector "
                         f"allocation ({r.alloc}); this needs a container "
                         "rebuild, which nothing supports yet.")
            data = data + b"\x00" * (r.alloc - len(data))
        off = self.iso_offset(r)
        with open(self.iso_path, "r+b") as f:
            f.seek(off)
            f.write(data)
            f.seek(off)
            if f.read(len(data)) != data:
                sys.exit(f"{r.path}: read-back verification FAILED")


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------

def cmd_info(iso: str, discpath: str, lba_dir=None) -> None:
    d = Disc(iso, lba_dir)
    r = d.row(discpath)
    off = d.iso_offset(r)
    cum = 0
    holder = "?"
    for name in CHAINS[r.source]:
        base, size = d.extents[name]
        if r.offset < cum + size:
            holder = name
            break
        cum += size
    print(f"{r.path}")
    print(f"  table   {r.source}   offset 0x{r.offset:08X}   size {r.size} "
          f"(0x{r.size:X})")
    print(f"  lives in {holder} -> ISO byte 0x{off:X}")
    print(f"  sector allocation {r.alloc} bytes ({r.alloc - r.size} slack)")


def cmd_extract(iso: str, discpath: str, out: str, lba_dir=None) -> None:
    d = Disc(iso, lba_dir)
    r = d.row(discpath)
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_bytes(d.read(r))
    print(f"{r.path} ({r.size} bytes) -> {out}")


def cmd_patch(iso: str, discpath: str, infile: str, pad=False, lba_dir=None) -> None:
    d = Disc(iso, lba_dir)
    r = d.row(discpath)
    d.write(r, Path(infile).read_bytes(), pad)
    print(f"patched {r.path} in {iso} (verified)")


def cmd_tree(iso: str, moddir: str, pad=False, dry_run=False, lba_dir=None) -> None:
    d = Disc(iso, lba_dir)
    root = Path(moddir)
    if not root.is_dir():
        sys.exit(f"{moddir}: not a directory")
    files = sorted(p for p in root.rglob("*") if p.is_file()
                   and not p.name.startswith("."))
    if not files:
        sys.exit(f"{moddir}: no files found")
    patched = skipped = 0
    for p in files:
        discpath = "\\" + str(p.relative_to(root)).replace("/", "\\")
        key = discpath.lower()
        if key not in d.rows:
            print(f"  skip (not on disc): {discpath}")
            skipped += 1
            continue
        r = d.rows[key]
        data = p.read_bytes()
        if dry_run:
            fit = ("same-size" if len(data) == r.size
                   else f"pad {len(data)}/{r.alloc}" if pad and len(data) <= r.alloc
                   else "WOULD FAIL")
            print(f"  would patch {discpath} [{fit}]")
            continue
        d.write(r, data, pad)
        print(f"  patched {discpath} ({len(data)} bytes)")
        patched += 1
    if not dry_run:
        print(f"{patched} patched, {skipped} skipped, all writes verified")


def main() -> None:
    a = sys.argv[1:]
    pad = "--pad" in a
    dry = "--dry-run" in a
    a = [x for x in a if x not in ("--pad", "--dry-run")]
    if len(a) >= 3 and a[0] == "info":
        cmd_info(a[1], a[2])
    elif len(a) >= 4 and a[0] == "extract":
        cmd_extract(a[1], a[2], a[3])
    elif len(a) >= 4 and a[0] == "patch":
        cmd_patch(a[1], a[2], a[3], pad)
    elif len(a) >= 3 and a[0] == "tree":
        cmd_tree(a[1], a[2], pad, dry)
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
