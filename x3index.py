"""
x3index.py — Read the disc's own X3.00 / X3.10 / X3.20 file indexes.

The legacy Lba*.txt tables were produced by old Windows tools. The game
itself finds files through three small index files at the ISO root:

    X3.00  → the shared X3.01/X3.02 bigfiles   (both discs)
    X3.10  → Disc 1 story bigfiles X3.11..13
    X3.20  → Disc 2 story bigfiles X3.21..23

This module parses them directly. The format was reversed from SLUS_213.89
(FUN_00187e28 lookup, FUN_00187bd8 directory walk, FUN_00187b18 name decode)
and reproduces the shipped Lba0/1/2.txt byte-for-byte on the US discs; it
also reads the May 2006 prototype's indexes.

Format
------
byte 0          size of the index file itself, in 2048-byte sectors (N).
                Every sector number below counts from the first sector of the
                index file, and the bigfiles follow it contiguously on the
                ISO, so the byte offset into the concatenated bigfiles is
                (sector - N) * 2048.
then records until a 0x00 byte:
  directory     h & 0x80: h & 0x3f = record length, next byte = levels to pop,
                then an encoded name.
  file          h & 0x80 == 0: h & 0x3f = offset from the record start to the
                7-byte tail; encoded name at +1; tail = u24 sector, u32 size;
                if h & 0x40 a further u24 follows (purpose unknown).
encoded name    first byte c: c == 0 → plain NUL-terminated name follows;
                else overwrite (c & 0xf) bytes starting (c >> 4) + 1 bytes
                before the end of the previous name at the same level.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

SECTOR = 2048

# Which Lba table each index corresponds to (matches the kit's lba/ names).
INDEX_TO_LBA = {"X3.00": "Lba0.txt", "X3.10": "Lba1.txt", "X3.20": "Lba2.txt"}


@dataclass(frozen=True)
class IndexEntry:
    path: str            # in-game path, e.g. \evt\s000100.xep
    sector: int          # sector relative to the start of the index file
    size: int            # byte length
    extra: Optional[int]  # optional trailing u24 (h & 0x40), else None
    tail: int            # byte offset of the sector/size tail inside the index file


def _decode_name(buf: bytearray, pos: int, data: bytes, i: int) -> Tuple[int, int]:
    """Emulate FUN_00187b18. Writes the decoded name into ``buf`` starting at
    ``pos`` (on top of the previous name there). Returns (index of the
    terminating NUL in buf, read position after the name)."""
    c = data[i]
    i += 1
    if c == 0:
        while True:
            buf[pos] = data[i]
            i += 1
            if buf[pos] == 0:
                return pos, i
            pos += 1
    n = c & 0xF
    e = pos
    while buf[e] != 0:
        e += 1
    e -= (c >> 4) + 1
    for _ in range(n):
        buf[e] = data[i]
        e += 1
        i += 1
    e -= 1
    while buf[e] != 0:
        e += 1
    return e, i


def _cstr(buf: bytearray, pos: int) -> str:
    return bytes(buf[pos:buf.index(0, pos)]).decode("latin1")


def parse_index(data: bytes) -> List[IndexEntry]:
    """Parse one X3.x0 index file."""
    out: List[IndexEntry] = []
    path = bytearray(1024)
    fbuf = bytearray(512)
    starts = [0]  # buffer offset of each path component; level = len-1
    p = 1
    while p < len(data) and data[p] != 0:
        h = data[p]
        ln = h & 0x3F
        if h & 0x80:
            pop = data[p + 1]
            level = len(starts) - 1
            if pop:
                level -= pop
                path[starts[level + 1] - 1] = 0
                starts = starts[: level + 1]
            end, _ = _decode_name(path, starts[level], data, p + 2)
            path[end] = 0x5C  # backslash
            path[end + 1] = 0
            starts = starts[: level + 1] + [end + 1]
            p += ln
        else:
            _decode_name(fbuf, 0, data, p + 1)
            q = p + ln
            sector = data[q] | data[q + 1] << 8 | data[q + 2] << 16
            size = int.from_bytes(data[q + 3:q + 7], "little")
            extra = None
            nxt = q + 7
            if h & 0x40:
                extra = data[q + 7] | data[q + 8] << 8 | data[q + 9] << 16
                nxt = q + 10
            out.append(IndexEntry("\\" + _cstr(path, 0) + _cstr(fbuf, 0),
                                  sector, size, extra, q))
            p = nxt
    return out


def header_sectors(data: bytes) -> int:
    return data[0]


def to_lba_lines(data: bytes) -> List[str]:
    """Render an index in the legacy Lba*.txt format
    (OFFSET|LENGTH|INDEX|path, 8 hex digits each).

    OFFSET = (sector - N) * 2048. INDEX is the byte offset of the entry's
    sector/size tail inside the index file (what the legacy tool printed)."""
    base = header_sectors(data)
    return [f"{(e.sector - base) * SECTOR:08X}|{e.size:08X}|{e.tail:08X}|{e.path}"
            for e in parse_index(data)]


def read_iso_file(iso: Path, name: str) -> Optional[bytes]:
    """Read a root-directory file from a PS2 ISO9660 image (no 7-Zip needed)."""
    with open(iso, "rb") as f:
        f.seek(16 * SECTOR)
        pvd = f.read(SECTOR)
        if pvd[1:6] != b"CD001":
            raise ValueError(f"{iso}: not an ISO9660 image")
        root = pvd[156:156 + 34]
        lba = int.from_bytes(root[2:6], "little")
        size = int.from_bytes(root[10:14], "little")
        f.seek(lba * SECTOR)
        d = f.read(size)
        i = 0
        want = name.upper()
        while i < len(d):
            rl = d[i]
            if rl == 0:
                i = (i // SECTOR + 1) * SECTOR
                continue
            nl = d[i + 32]
            nm = d[i + 33:i + 33 + nl].decode("latin1").split(";")[0].upper()
            if nm == want:
                flba = int.from_bytes(d[i + 2:i + 6], "little")
                fsz = int.from_bytes(d[i + 10:i + 14], "little")
                f.seek(flba * SECTOR)
                return f.read(fsz)
            i += rl
    return None


def write_lba_from_iso(iso: Path, out_dir: Path) -> List[Path]:
    """Regenerate Lba*.txt for every X3.x0 index present on ``iso``."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for idx, lba_name in INDEX_TO_LBA.items():
        data = read_iso_file(iso, idx)
        if data is None:
            continue
        dest = out_dir / lba_name
        dest.write_text("\n".join(to_lba_lines(data)) + "\n")
        written.append(dest)
    return written


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("source", help="an ISO, or a raw X3.00/X3.10/X3.20 file")
    ap.add_argument("--out", help="write Lba*.txt into this dir (ISO input only)")
    a = ap.parse_args(argv)
    src = Path(a.source)
    if src.suffix.lower() == ".iso":
        out = Path(a.out or "lba")
        for p in write_lba_from_iso(src, out):
            print(f"wrote {p} ({sum(1 for _ in p.open())} entries)")
    else:
        print("\n".join(to_lba_lines(src.read_bytes())))


if __name__ == "__main__":
    main()
