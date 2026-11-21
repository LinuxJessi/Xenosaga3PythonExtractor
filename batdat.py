"""batdat.py — the battle data container (``bat\\xx\\batdat.bin``): its 28 tables, their
string fields, export and byte-identical rebuild.

New for this kit (2026-11-20; JP brief M15). The file is loaded through the
resource-type table (type 0x0601 "bat", localized; region.restype_table), so
SLUS holds no direct reference to the name "batdat.bin".

Container (USA 125,764 bytes, JP 127,836, May 2006 prototype 123,724)::

    u32 count (28)   u32 file size   u32 offset[28]     (header 0x78 bytes)
    table i = file[offset[i] : offset[i+1] or file size], every table 4-aligned

A table that holds text is ``count`` fixed-size records followed by a string
area: NUL-terminated strings, records point at them with a table-relative
u16 or u32 field (the first string starts right after the last record). The
layout of each table is DERIVED from the table's own bytes (``derive``):

    for each field width w (2, 4), record size R and first field f0:
      S = the value at f0 in record 0, N = S / R records (S a multiple of R);
      the bytes from S on must be text (NUL or >= 0x20), every record's field f
      must land on a string start, and S must be the lowest such value;
    the candidate covering the most (record, field) pointers wins, the
    smaller R on a tie, then the wider field (a u32 whose high half is 0 in
    every record also reads as a u16; the u32 reading keeps the high half).

Derived layouts (identical on USA retail, the prototype and JP although every
string area differs in size; ``self_test`` checks this):

    table  w  R    N    string fields   table  w  R    N    string fields
     0     2  56   17   +22              12    2  20  120   +0 +2
     1     2  56  177   +22              13    2  20  128   +0 +2
     4     4  32   98   +0               14    2  28  174   +0 +2
     5     4  32  612   +0               15    2  24   80   +0 +2
     6     2  32   88   +0 +2            16    2  20   32   +0 +2
     7     2  40   88   +0 +2            17    2  20   16   +0 +2
     8     2  40   54   +0 +2            18    2  20   16   +0 +2
     9     2  40   64   +0 +2            19    2  24   46   +0 +2
    10     2   8   16   +0 +2            23    2   2  110   +0 (an offset array)
    11     2   8   32   +0 +2            27    2   8   59   +0 +2

(+0 +2 is a name and a description: 'Medica S' / 'Recover small amount of HP.',
'Break' / 'Icon is erased and unable to move next turn.'.)

Tables 2, 3, 20, 21, 22, 24, 25 and 26 have no string area and are byte for
byte the same in all three builds: they are kept verbatim and exported as
read-only (no items).

What is NOT done: the string fields were derived structurally and confirmed
only by the three builds agreeing, not from the SLUS battle code that reads
them; no record field other than the string pointers is named.

Rebuild: an unchanged table is copied as is. A changed table keeps its record
bytes, re-lays its strings in their original order from S, rewrites every
pointer field, and pads with NULs to 4 bytes (the original NUL tail, grown to
the next multiple of 4); u16 tables refuse to grow past 0xFFFF. The header
offsets and the file size are recomputed.

Per-container API::

    b = parse(data, region)       BatDat; b.items -> [textcodec.Item(key 'TT.KKKK', raw, codec, 'battle', flags)]
                                  flags: 'unreferenced' for a string no record points at
    rebuild(b, items) -> bytes    items: Items or (key, bytes); keys left out keep their bytes

    python batdat.py --self-test
"""
from __future__ import annotations

import os
import struct
import sys
from dataclasses import dataclass, field
from typing import Dict, List, NamedTuple, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import region as _region                                           # noqa: E402
import textcodec                                                   # noqa: E402

TABLES = 28
NO_TEXT = (2, 3, 20, 21, 22, 24, 25, 26)


class BatError(ValueError):
    pass


class Layout(NamedTuple):
    width: int            # pointer field size
    stride: int           # record size
    count: int            # records
    start: int            # string area offset (= count * stride)
    fields: Tuple[int, ...]


def _texty(b: bytes) -> bool:
    return all(x >= 0x20 or x in (0, 9, 10, 13) for x in b)


def derive(t: bytes) -> Optional[Layout]:
    """The record/string layout of one table, or None (module docstring)."""
    n = len(t)
    best = None
    texty_cache: Dict[int, bool] = {}
    starts_cache: Dict[int, set] = {}
    for w in (2, 4):
        fmt = "<H" if w == 2 else "<I"
        for R in range(w, 257, w):
            for f0 in range(0, min(R, 64), w):
                if f0 + w > n:
                    break
                S = struct.unpack_from(fmt, t, f0)[0]
                if S == 0 or S >= n or S % R or S < 2 * R:
                    continue
                N = S // R
                if S not in texty_cache:
                    texty_cache[S] = _texty(t[S:])
                if not texty_cache[S]:
                    continue
                if S not in starts_cache:
                    starts_cache[S] = {S} | {i + 1 for i in range(S, n - 1) if t[i] == 0}
                starts = starts_cache[S]
                fields, low = [], n
                for f in range(0, R - w + 1, w):
                    col = [struct.unpack_from(fmt, t, k * R + f)[0] for k in range(N)]
                    if all(v in starts for v in col):
                        fields.append(f)
                        low = min(low, min(col))
                if f0 not in fields or low != S:
                    continue
                cand = (len(fields) * N, -R, w, Layout(w, R, N, S, tuple(fields)))
                if best is None or cand[:3] > best[:3]:
                    best = cand
    return best[3] if best else None


@dataclass
class Table:
    index: int
    data: bytes
    layout: Optional[Layout]
    segs: List[Tuple[int, bytes]] = field(default_factory=list)    # (offset, bytes) of every string
    tail: int = 0                                                  # NULs after the last kept string
    ptrs: List[Tuple[int, int]] = field(default_factory=list)      # (field offset, segment index)

    @property
    def strings(self) -> List[bytes]:
        return [s for _, s in self.segs]

    def referenced(self) -> set:
        return {k for _p, k in self.ptrs}


def _table(index: int, t: bytes) -> Table:
    lay = derive(t)
    if lay is None:
        return Table(index, t, None)
    segs, i = [], lay.start
    while i < len(t):
        e = t.find(b"\0", i)
        if e < 0:
            raise BatError(f"table {index}: the string area does not end with a NUL")
        segs.append((i, t[i:e]))
        i = e + 1
    where = {off: k for k, (off, _s) in enumerate(segs)}
    fmt = "<H" if lay.width == 2 else "<I"
    ptrs = []
    for r in range(lay.count):
        for f in lay.fields:
            p = r * lay.stride + f
            ptrs.append((p, where[struct.unpack_from(fmt, t, p)[0]]))
    refd = {k for _p, k in ptrs}
    keep = len(segs)
    while keep > 0 and segs[keep - 1][1] == b"" and keep - 1 not in refd:
        keep -= 1
    tail = len(segs) - keep              # each dropped empty segment is one NUL
    return Table(index, t, lay, segs[:keep], tail, ptrs)


def build_table(tb: Table, strings: List[bytes]) -> bytes:
    if tb.layout is None:
        if strings:
            raise BatError(f"table {tb.index} holds no strings")
        return tb.data
    if len(strings) != len(tb.segs):
        raise BatError(f"table {tb.index}: {len(strings)} strings given, it holds {len(tb.segs)}")
    lay = tb.layout
    out = bytearray(tb.data[:lay.start])
    new = []
    for k, s in enumerate(strings):
        if b"\0" in s:
            raise BatError(f"table {tb.index} string {k}: a NUL byte inside a string")
        new.append(len(out))
        out += s + b"\0"
    pad = tb.tail
    while (len(out) + pad) % 4:
        pad += 1
    out += b"\0" * pad
    if lay.width == 2 and new and max(new) > 0xFFFF:
        raise BatError(f"table {tb.index}: a string would start at {max(new):#x}; its u16 pointers reach 0xFFFF")
    fmt = "<H" if lay.width == 2 else "<I"
    for p, k in tb.ptrs:
        struct.pack_into(fmt, out, p, new[k])
    return bytes(out)


@dataclass
class BatDat:
    data: bytes
    tables: List[Table]
    region: object = None

    @property
    def items(self) -> List[textcodec.Item]:
        codec = textcodec.codec_name_for(self.region)
        out = []
        for tb in self.tables:
            refd = tb.referenced()
            for k, s in enumerate(tb.strings):
                out.append(textcodec.Item(f"{tb.index:02d}.{k:04d}", s, codec, "battle",
                                          () if k in refd else ("unreferenced",)))
        return out


def parse(data: bytes, region=None) -> BatDat:
    if len(data) < 8:
        raise BatError("too short for batdat.bin")
    n, total = struct.unpack_from("<II", data)
    if n != TABLES or total != len(data) or 8 + 4 * n > len(data):
        raise BatError(f"not a batdat.bin (count {n}, size field {total}, file {len(data)})")
    offs = list(struct.unpack_from(f"<{n}I", data, 8)) + [total]
    if offs[0] != 8 + 4 * n or any(b < a for a, b in zip(offs, offs[1:])) or any(o % 4 for o in offs[:-1]):
        raise BatError("table offsets out of order or unaligned")
    return BatDat(data, [_table(i, data[offs[i]:offs[i + 1]]) for i in range(n)], _region.as_region(region))


def rebuild(bd: BatDat, items=None, force: bool = False) -> bytes:
    """The file with the given strings (Items or (key, bytes); others unchanged).
    ``force`` re-lays every text table even when unchanged (the self-test's
    proof that the layouts reproduce the retail bytes)."""
    new = [list(tb.strings) for tb in bd.tables]
    for it in items or []:
        key, raw = (it.key, it.raw) if isinstance(it, textcodec.Item) else (it[0], bytes(it[1]))
        i, k = (int(x) for x in key.split("."))
        if not (0 <= i < len(new) and 0 <= k < len(new[i])):
            raise BatError(f"no string {key} in batdat.bin")
        new[i][k] = raw
    bodies = []
    for tb, strings in zip(bd.tables, new):
        if not force and strings == tb.strings:
            bodies.append(tb.data)
        else:
            bodies.append(build_table(tb, strings))
    head = 8 + 4 * len(bodies)
    offs, cur = [], head
    for b in bodies:
        offs.append(cur)
        cur += len(b)
    return struct.pack("<II", len(bodies), cur) + struct.pack(f"<{len(offs)}I", *offs) + b"".join(bodies)


# ------------------------------------------------------------------ self-test

def _synthetic() -> bytes:
    names = [(b"Medica S", b"Recover small amount of HP."), (b"Medica M", b"Recover medium amount\\nof HP.")]
    R = 8
    recs = bytearray(R * len(names))
    area = bytearray()
    for k, (a, b) in enumerate(names):
        struct.pack_into("<HH", recs, k * R, len(recs) + len(area), 0)
        area += a + b"\0"
        struct.pack_into("<H", recs, k * R + 2, len(recs) + len(area))
        area += b + b"\0"
        struct.pack_into("<HH", recs, k * R + 4, 0x64 + k, 0x0100)
    t0 = bytes(recs + area)
    t0 += b"\0" * ((-len(t0)) % 4)
    other = bytes(range(16))
    tables = [t0] + [other] * (TABLES - 1)
    head = 8 + 4 * TABLES
    offs, cur = [], head
    for t in tables:
        offs.append(cur)
        cur += len(t)
    return struct.pack("<II", TABLES, cur) + struct.pack(f"<{TABLES}I", *offs) + b"".join(tables)


def self_test() -> int:
    ok = True

    def check(cond, msg):
        nonlocal ok
        print(("ok    " if cond else "FAIL  ") + msg)
        ok &= bool(cond)

    syn = _synthetic()
    b = parse(syn)
    lay = b.tables[0].layout
    check(lay == Layout(2, 8, 2, 16, (0, 2)) and b.tables[1].layout is None,
          f"synthetic: table 0 derived as w2 R8 N2 fields +0 +2 ({lay}); a binary table has none")
    check(rebuild(b, force=True) == syn and rebuild(b) == syn, "synthetic: forced and plain rebuild byte-identical")
    grown = rebuild(b, [("00.0000", b"Medica Small")])
    b2 = parse(grown)
    check(b2.tables[0].strings[:2] == [b"Medica Small", b"Recover small amount of HP."]
          and b2.tables[0].layout == lay and len(b2.tables[0].data) % 4 == 0
          and b2.tables[1].data == b.tables[1].data, "synthetic: an edit re-lays the strings, keeps 4-alignment")
    try:
        rebuild(b, [("00.0000", b"x" * 70000)])
        check(False, "synthetic: a u16 table past 0xFFFF is refused")
    except BatError:
        check(True, "synthetic: a u16 table past 0xFFFF is refused")

    isos = [(k, os.environ.get(k)) for k in ("XS3_D1", "XS3_D2", "XS3_PROTO", "XS3_JP1", "XS3_JP2")]
    if not any(v for _, v in isos):
        print("SKIP  disc checks (set XS3_D1 / XS3_D2 / XS3_PROTO / XS3_JP1 / XS3_JP2)")
    from disc import Disc
    layouts, notext = {}, {}
    for env, iso in isos:
        if not iso:
            continue
        with Disc(iso) as disc:
            reg = _region.detect(disc)
            path = _region.resolve(disc, "bat\\xx\\batdat.bin", reg)
            d = disc.read(path)
            bd = parse(d, reg)
            items = bd.items
            codec = textcodec.codec_by_name(textcodec.codec_name_for(reg))
            exact = all(codec.from_text(codec.to_text(it.raw)) == it.raw for it in items)
            esc = sum(bool(textcodec.HIGH_ESC.search(codec.to_text(it.raw))) for it in items)
            unref = sum(1 for it in items if it.flags and it.raw)
            text_tables = [tb.index for tb in bd.tables if tb.layout]
            layouts[env] = {tb.index: tb.layout[:3] + tb.layout[4:] for tb in bd.tables if tb.layout}
            pick = [it for it in items if it.key.startswith("07.")][0]
            grow = codec.from_text(codec.to_text(pick.raw) + ("（改）" if reg.codec == "jp" else " (edited)"))
            ed = parse(rebuild(bd, [(pick.key, grow)]), reg)
            after = {it.key: it.raw for it in ed.items}
            check(after[pick.key] == grow and all(after[it.key] == it.raw for it in items if it.key != pick.key)
                  and [tb.layout and tb.layout[:3] + tb.layout[4:] for tb in ed.tables]
                  == [tb.layout and tb.layout[:3] + tb.layout[4:] for tb in bd.tables],
                  f"{env}: editing {pick.key} grows table 7, re-derives the same layouts, every other string unchanged")
            notext[env] = {tb.index: tb.data for tb in bd.tables if not tb.layout}
            check(rebuild(bd, force=True) == d and rebuild(bd) == d and exact
                  and sorted(set(range(TABLES)) - set(text_tables)) == list(NO_TEXT),
                  f"{env}: {path} {len(d)} bytes, {len(text_tables)} text tables / {len(NO_TEXT)} without text, "
                  f"{len(items)} strings, forced re-lay byte-identical, codec exact, {esc} with high-byte escapes, "
                  f"{unref} non-empty unreferenced")
    envs = list(layouts)
    if len(envs) > 1:
        same = all(layouts[e] == layouts[envs[0]] for e in envs)
        check(same, f"derived layouts identical on {', '.join(envs)}")
        check(all(notext[e] == notext[envs[0]] for e in envs),
              f"tables {', '.join(map(str, NO_TEXT))} byte-identical on {', '.join(envs)}")
    print("self-test", "passed" if ok else "FAILED")
    return 0 if ok else 1


def add_commands(subparsers) -> None:
    """``batdat-strings FILE [--region us|jp] [--layouts]``: list batdat.bin strings (local file)."""
    p = subparsers.add_parser("batdat-strings", help="list the tables and strings of an XS3 batdat.bin (local file)")
    p.add_argument("file")
    p.add_argument("--region", default="us", help="build profile: us (default), proto_2006_05 or jp")
    p.add_argument("--layouts", action="store_true", help="only print each table's derived layout")

    def run(a):
        bd = parse(open(a.file, "rb").read(), a.region)
        if a.layouts:
            for tb in bd.tables:
                lay = tb.layout
                print(f"table {tb.index:2d} {len(tb.data):6d} bytes  " + (
                    f"u{8 * lay.width} R{lay.stride} N{lay.count} strings@{lay.start:#x} fields "
                    f"{' '.join(f'+{f}' for f in lay.fields)} ({len(tb.segs)} strings)" if lay else "no strings (read-only)"))
            return 0
        for it in bd.items:
            flags = f" [{','.join(it.flags)}]" if it.flags else ""
            print(f"{it.key}{flags} {textcodec.codec_by_name(it.codec).to_text(it.raw)}")
        return 0
    p.set_defaults(func=run)


if __name__ == "__main__":
    if sys.argv[1:] == ["--self-test"]:
        sys.exit(self_test())
    print(__doc__)
