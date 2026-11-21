"""toc_bin.py — Parse (and rebuild) Episode III's binary file indexes X3.00 / X3.10 / X3.20.

Borrowed from Xenosaga2PythonExtractor/toc.py (2026-11-20). Renamed because
this kit already has an unrelated ``toc.py`` (a summary of the legacy
lba/*.txt tables). What changed: the grammar code is untouched; imports point
at this kit's ``chains.py``; ``rebuild`` / ``index_sectors`` wrap the
serialize API trap (below); ``lba_lines`` renders the legacy Lba*.txt form so
the bundled tables serve as test oracles; disc checks, ``self_test`` and
``add_commands`` (``toc-check``) follow the kit convention.

Episode III's indexes use exactly Episode II's front-coded grammar (the filler
even still says "Episode.2"). Verified 2026-11-20 on all six index files of
the three known images (USA Disc 1: X3.00 9,867 entries, X3.10 3,649; Disc 2:
X3.00 9,867, X3.20 1,709; May 2006 prototype: X3.00 9,867, X3.10 3,654):
``serialize(parse) == file`` byte for byte, no compressed (cfile) entries, and
the retail entries equal lba/Lba0/1/2.txt line for line. ``x3index.py`` is an
independent reader of the same files (its "purpose unknown" h&0x40 u24 is the
cfile ``usize`` here).

API TRAP: ``serialize(events, size_sectors)`` wants byte 0 of the index file
(its own size in sectors, 55 / 26 / 13 on retail). The second value
``parse_events`` returns is the filler offset, NOT that; passing it builds a
227 MB file. Use ``rebuild(data, events)`` or ``index_sectors(data)``.

Grammar (reverse-engineered for Episode II, 2026-11-05)::

    toc    = [u8 own size in sectors] item* [0x00]* filler
    item   = file | cfile | dir | pop
    file   = [b]      [code] [literal: b-2 bytes]    [u24le sector] [u32le size]
    cfile  = [b|0x40] [code] [literal: (b&0x3f)-2]   [u24le sector] [u32le csize] [u24le usize]
    dir    = [0x80|n] [u8 pops] [code] [literal: n-3 bytes]
    pop    = [0x00]                          (closes one directory level)
    filler = "MONOLITHSOFT Xenosaga Episode.2\\0" repeated, phase-locked to
             (absolute file offset % 32)

Front coding (``code``)::

    code == 0 : the literal is the whole name plus its NUL
    else      : H = code >> 4, L = code & 15 == len(literal)
                p = len(prev) - H - 1
                name = prev[:p] + literal + prev[p + L:]   then cut at the first NUL

Entry sectors are relative to the first sector of the index file itself: the
bigfiles follow it back to back on the image (``chains.py``), so the byte
offset into the concatenated bigfiles is ``(sector - byte0) * 2048`` and the
absolute LBA is ``index LBA + sector``. ``fields_off`` is the index-file byte
offset of an entry's u24 sector; its u32 size follows at ``fields_off + 3``
(the legacy Lba*.txt third column).

Usage::

    python toc_bin.py --self-test
    python toc_bin.py toc-check --iso DISC.iso
"""
from __future__ import annotations

import argparse
import struct
import sys
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

SECTOR = 2048
FILLER = b"MONOLITHSOFT Xenosaga Episode.2\x00"


@dataclass(frozen=True)
class TocEntry:
    source: str          # TOC filename the entry came from
    path: str            # in-game path, backslash-separated
    sector: int          # sector offset relative to the TOC file (chain start)
    size: int            # stored byte length (compressed length for cfiles)
    usize: Optional[int]  # uncompressed length for cfiles, else None
    compressed: bool
    fields_off: int = -1  # TOC byte offset of u24 sector, u32 size[, u24 usize]

    @property
    def byte_offset(self) -> int:
        return self.sector * SECTOR

    @property
    def ext(self) -> str:
        name = self.path.rsplit("\\", 1)[-1]
        return name.rsplit(".", 1)[-1].lower() if "." in name else ""


class TocError(ValueError):
    pass


# --------------------------------------------------------------- front coding

def decode_name(prev: bytes, code: int, literal: bytes) -> bytes:
    """Apply one front-coded edit to ``prev``."""
    if code == 0:
        name = literal
    else:
        h, n = code >> 4, code & 15
        if n != len(literal):
            raise TocError(f"code {code:#04x} says {n} literal bytes, have {len(literal)}")
        p = len(prev) - h - 1
        if p < 0:
            raise TocError(f"code {code:#04x} edits before the start of {prev!r}")
        name = prev[:p] + literal + prev[p + n:]
    cut = name.find(b"\x00")
    return name if cut < 0 else name[:cut]


def encode_name(prev: bytes, name: bytes) -> Tuple[int, bytes]:
    """The (code, literal) Monolith's tool writes for ``name`` after ``prev``."""
    if prev:
        p = 0
        lim = min(len(prev), len(name))
        while p < lim and prev[p] == name[p]:
            p += 1
        if len(name) == len(prev):
            s = 0
            while s < len(name) - p and prev[-1 - s] == name[-1 - s]:
                s += 1
            lit = name[p:len(name) - s]
        else:
            lit = name[p:] + b"\x00"
        h = len(prev) - p - 1
        if lit and 0 <= h <= 15 and len(lit) <= 15:
            return (h << 4) | len(lit), lit
    return 0, name + b"\x00"


# ---------------------------------------------------------------------- parse

@dataclass
class Event:
    """One TOC item, as needed to rebuild the file byte-identically."""
    kind: str                    # "file" | "dir" | "pop"
    name: bytes = b""
    pops: int = 0
    sector: int = 0
    size: int = 0
    usize: Optional[int] = None
    compressed: bool = False
    fields_off: int = -1


def _is_filler(data: bytes, pos: int) -> bool:
    rest = data[pos:]
    if not rest:
        return True
    phase = pos % len(FILLER)
    want = (FILLER * (len(rest) // len(FILLER) + 2))[phase:phase + len(rest)]
    return rest == want


def parse_events(data: bytes, source: str = "") -> Tuple[List[Event], int]:
    """The item stream and the offset where the filler starts."""
    if not data:
        raise TocError(f"{source}: empty")
    if data[0] != len(data) // SECTOR:
        raise TocError(f"{source}: header byte {data[0]} != file sector count {len(data) // SECTOR}")
    pos, events = 1, []
    file_prev = b""
    dir_prev: dict[int, bytes] = {}
    depth = 0
    while pos < len(data):
        if _is_filler(data, pos):
            return events, pos
        b = data[pos]
        if b == 0:
            events.append(Event("pop"))
            depth = max(0, depth - 1)
            pos += 1
            continue
        if b & 0x80:
            n = b & 0x7F
            pops, code = data[pos + 1], data[pos + 2]
            literal = data[pos + 3:pos + n]
            depth = max(0, depth - pops)
            name = decode_name(dir_prev.get(depth, b""), code, literal)
            if not name or not all(32 <= c < 127 for c in name):
                raise TocError(f"{source}: bad dir name {name!r} at {pos:#x}")
            dir_prev[depth] = name
            for k in [k for k in dir_prev if k > depth]:
                del dir_prev[k]
            events.append(Event("dir", name=name, pops=pops))
            depth += 1
            file_prev = b""
            pos += n
            continue
        comp = bool(b & 0x40)
        n = b & 0x3F
        code = data[pos + 1]
        literal = data[pos + 2:pos + n]
        name = decode_name(file_prev, code, literal)
        if not name or not all(32 <= c < 127 for c in name):
            raise TocError(f"{source}: bad file name {name!r} at {pos:#x}")
        off = pos + n
        sector = int.from_bytes(data[off:off + 3], "little")
        size = int.from_bytes(data[off + 3:off + 7], "little")
        usize = int.from_bytes(data[off + 7:off + 10], "little") if comp else None
        events.append(Event("file", name=name, sector=sector, size=size, usize=usize,
                            compressed=comp, fields_off=off))
        file_prev = name
        pos = off + (10 if comp else 7)
    return events, pos


def parse_toc(data: bytes, source: str = "") -> List[TocEntry]:
    """Parse a whole TOC file. Raises TocError on any grammar violation."""
    events, _ = parse_events(data, source)
    stack: List[str] = []
    out: List[TocEntry] = []
    for ev in events:
        if ev.kind == "pop":
            if stack:
                stack.pop()
        elif ev.kind == "dir":
            for _ in range(ev.pops):
                if stack:
                    stack.pop()
            stack.append(ev.name.decode("ascii"))
        else:
            out.append(TocEntry(source, "\\".join(stack + [ev.name.decode("ascii")]),
                                ev.sector, ev.size, ev.usize, ev.compressed, ev.fields_off))
    return out


def serialize(events: List[Event], size_sectors: int, filler: bytes = FILLER) -> bytes:
    """Rebuild a TOC from its item stream: the inverse of ``parse_events``.
    Names are front-coded with ``encode_name``; the file is padded with the
    phase-locked filler to ``size_sectors``."""
    out = bytearray([size_sectors & 0xFF])
    file_prev = b""
    dir_prev: dict[int, bytes] = {}
    depth = 0
    for ev in events:
        if ev.kind == "pop":
            out.append(0)
            depth = max(0, depth - 1)
        elif ev.kind == "dir":
            depth = max(0, depth - ev.pops)
            code, lit = encode_name(dir_prev.get(depth, b""), ev.name)
            n = 3 + len(lit)
            if n > 0x7F:
                raise TocError(f"dir name too long: {ev.name!r}")
            out += bytes([0x80 | n, ev.pops, code]) + lit
            dir_prev[depth] = ev.name
            for k in [k for k in dir_prev if k > depth]:
                del dir_prev[k]
            depth += 1
            file_prev = b""
        else:
            code, lit = encode_name(file_prev, ev.name)
            n = 2 + len(lit)
            if n > 0x3F:
                raise TocError(f"file name too long: {ev.name!r}")
            out += bytes([n | (0x40 if ev.compressed else 0), code]) + lit
            out += ev.sector.to_bytes(3, "little") + ev.size.to_bytes(4, "little")
            if ev.compressed:
                out += (ev.usize or 0).to_bytes(3, "little")
            file_prev = ev.name
    total = size_sectors * SECTOR
    if len(out) > total:
        raise TocError(f"TOC needs {len(out)} bytes, {total} available")
    start = len(out)
    rep = filler * (total // len(filler) + 2)
    phase = start % len(filler)
    out += rep[phase:phase + total - start]
    return bytes(out)


# ------------------------------------------------------------------ self-test

def _synthetic() -> Tuple[List[Event], List[str]]:
    ev = [
        Event("file", name=b"font0.us", sector=53, size=492352),
        Event("file", name=b"font1.us", sector=294, size=492352),
        Event("file", name=b"credit.bin", sector=576, size=53248),
        Event("file", name=b"title.bin", sector=602, size=1234, usize=917504, compressed=True),
        Event("dir", name=b"sound"),
        Event("dir", name=b"vsf"),
        Event("file", name=b"SYS_SE.prj", sector=700, size=976),
        Event("file", name=b"SYS_SE.vsf", sector=701, size=80528),
        Event("file", name=b"CFS_SE.prj", sector=741, size=1360),
        Event("file", name=b"CF_DYU.prj", sector=742, size=1360),
        Event("dir", name=b"smf", pops=1),
        Event("file", name=b"020300_marglis.xap", sector=800, size=51920),
        Event("file", name=b"020300_mobj200.xap", sector=826, size=6304),
        Event("file", name=b"020300_mobj201.xap", sector=830, size=5196),
        Event("file", name=b"020300_oruguia.xap", sector=833, size=87568),
        Event("dir", name=b"yajima", pops=2),
        Event("file", name=b"a_very_long_file_name_beyond_fifteen.bin", sector=900, size=1),
        Event("pop"),
    ]
    paths = ["font0.us", "font1.us", "credit.bin", "title.bin",
             "sound\\vsf\\SYS_SE.prj", "sound\\vsf\\SYS_SE.vsf", "sound\\vsf\\CFS_SE.prj",
             "sound\\vsf\\CF_DYU.prj", "sound\\smf\\020300_marglis.xap",
             "sound\\smf\\020300_mobj200.xap", "sound\\smf\\020300_mobj201.xap",
             "sound\\smf\\020300_oruguia.xap", "yajima\\a_very_long_file_name_beyond_fifteen.bin"]
    return ev, paths


def index_sectors(data: bytes) -> int:
    """The ``size_sectors`` argument ``serialize`` wants: byte 0 of the index file."""
    return data[0]


def rebuild(data: bytes, events: Optional[List[Event]] = None) -> bytes:
    """Serialize ``events`` (default: the file's own) at the file's own size. Avoids
    the trap of passing parse_events' filler offset as ``size_sectors``."""
    if events is None:
        events = parse_events(data)[0]
    return serialize(events, index_sectors(data))


def lba_lines(data: bytes, source: str = "") -> List[str]:
    """The legacy lba/Lba*.txt rendering: OFFSET|LENGTH|INDEX|\\path, 8 hex digits,
    OFFSET = (sector - byte0) * 2048, INDEX = fields_off."""
    base = index_sectors(data)
    return [f"{(e.sector - base) * SECTOR:08X}|{e.size:08X}|{e.fields_off:08X}|\\{e.path}"
            for e in parse_toc(data, source)]


def load_lba_txt(path) -> List[str]:
    """Lines of a bundled Lba*.txt, without the stray NUL line the shipped files end with."""
    from pathlib import Path
    lines = Path(path).read_text("latin-1").splitlines()
    return [ln for ln in lines if ln.strip("\x00").strip()]


def self_test() -> int:
    ok = True

    def check(cond, msg):
        nonlocal ok
        print(("ok    " if cond else "FAIL  ") + msg)
        ok &= bool(cond)

    # codes observed on the Episode II retail disc, re-derived by the encoder
    check(encode_name(b"font0.us", b"font1.us") == (0x31, b"1"), "font0.us -> font1.us is code 0x31 '1'")
    check(encode_name(b"SYS_SE.prj", b"SYS_SE.vsf") == (0x23, b"vsf"), "same-length suffix edit 0x23")
    check(encode_name(b"font1.us", b"credit.bin") == (0x7B, b"credit.bin\x00"), "longer name carries its NUL")
    check(encode_name(b"020300_marglis.xap", b"020300_mobj200.xap") == (0x96, b"obj200"),
          "middle edit keeps the suffix (0x96)")
    check(decode_name(b"020300_mobj200.xap", 0x41, b"1") == b"020300_mobj201.xap", "decode 0x41")
    check(decode_name(b"abc", 0, b"xyz\x00") == b"xyz", "code 0 is the whole name")
    ev, paths = _synthetic()
    blob = serialize(ev, 2)
    got = parse_toc(blob, "synthetic")
    check([e.path for e in got] == paths, "synthetic tree parses back to its paths")
    check(serialize(parse_events(blob)[0], 2) == blob, "serialize(parse(x)) == x")
    check(rebuild(blob) == blob, "rebuild uses byte 0, not the filler offset")
    check(parse_events(blob)[1] != index_sectors(blob), "(the trap: parse_events' 2nd value is not byte 0)")
    check(next(e for e in got if e.path == "title.bin").usize == 917504, "cfile usize survives")
    e0 = got[0]
    check(int.from_bytes(blob[e0.fields_off:e0.fields_off + 3], "little") == e0.sector
          and int.from_bytes(blob[e0.fields_off + 3:e0.fields_off + 7], "little") == e0.size,
          "fields_off points at u24 sector + u32 size")
    check(_is_filler(blob, len(blob) - 40), "filler is phase-locked")
    try:
        parse_toc(b"\x05" + bytes(100), "bad")
        check(False, "a wrong header byte is refused")
    except TocError:
        check(True, "a wrong header byte is refused")

    # disc checks: six index files round-trip, retail equals the bundled oracles
    import os
    from pathlib import Path
    discs = {k: os.environ[v] for k, v in (("D1", "XS3_D1"), ("D2", "XS3_D2"), ("PROTO", "XS3_PROTO"))
             if os.environ.get(v)}
    if not discs:
        print("SKIP  disc checks (set XS3_D1 / XS3_D2 / XS3_PROTO)")
    else:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from iso9660 import IsoImage
        lba_dir = Path(__file__).resolve().parent / "lba"
        counts = {("D1", "X3.00"): 9867, ("D1", "X3.10"): 3649, ("D2", "X3.00"): 9867,
                  ("D2", "X3.20"): 1709, ("PROTO", "X3.00"): 9867, ("PROTO", "X3.10"): 3654}
        oracle = {"X3.00": "Lba0.txt", "X3.10": "Lba1.txt", "X3.20": "Lba2.txt"}
        for k, path in discs.items():
            with IsoImage(path) as iso:
                for idx in ("X3.00", "X3.10", "X3.20"):
                    if idx not in iso.files:
                        continue
                    data = bytes(iso.read_file(idx))
                    ents = parse_toc(data, idx)
                    check(rebuild(data) == data, f"{k} {idx}: {len(ents)} entries, rebuild byte-identical")
                    check(len(ents) == counts.get((k, idx), -1), f"{k} {idx}: entry count as surveyed")
                    if k != "PROTO" and (lba_dir / oracle[idx]).exists():
                        same = lba_lines(data, idx) == load_lba_txt(lba_dir / oracle[idx])
                        check(same, f"{k} {idx}: equals lba/{oracle[idx]} line for line")
    print("self-test", "passed" if ok else "FAILED")
    return 0 if ok else 1


def _report(iso_path: str) -> int:
    sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
    from chains import CHAINS, ChainReader, available_chains
    from iso9660 import IsoImage

    iso = IsoImage(iso_path)
    rc = 0
    for chain in available_chains(iso):
        reader = ChainReader(iso, chain)
        data = bytes(reader.toc_bytes())
        events, end = parse_events(data, CHAINS[chain][0])
        ents = parse_toc(data, CHAINS[chain][0])
        same = rebuild(data, events) == data
        moved = [e for e in ents if e.byte_offset >= reader.total]      # relocated (grown) objects
        tiles = sorted((e for e in ents if e.byte_offset < reader.total), key=lambda e: e.sector)
        gaps = overlaps = 0
        for a, b in zip(tiles, tiles[1:]):
            end_a = a.sector + (a.size + SECTOR - 1) // SECTOR
            gaps += b.sector > end_a
            overlaps += b.sector < end_a
        last = max(e.byte_offset + e.size for e in tiles)
        print(f"chain{chain} {CHAINS[chain][0]}: {len(ents)} entries, "
              f"{sum(e.compressed for e in ents)} compressed, filler at {end:#x}, "
              f"rebuild byte-identical: {same}, gaps {gaps}, overlaps {overlaps}, "
              f"data ends {reader.total - last} bytes before the chain end"
              + (f", {len(moved)} relocated past it" if moved else ""))
        rc |= (not same) or bool(overlaps)
    iso.close()
    return 1 if rc else 0


def add_commands(subparsers) -> None:
    """Register ``toc-check`` (parse + rebuild every index on an image, report)."""
    p = subparsers.add_parser("toc-check", help="parse every X3.x0 index on an image and check it rebuilds byte for byte")
    p.add_argument("--iso", required=True)
    p.set_defaults(func=lambda a: _report(a.iso))


def main() -> int:
    if sys.argv[1:] == ["--self-test"]:
        return self_test()
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    add_commands(ap.add_subparsers(dest="cmd", required=True))
    a = ap.parse_args()
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
