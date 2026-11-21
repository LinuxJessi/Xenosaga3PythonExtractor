"""txd.py — Xenosaga III menu text tables (``mnu\\xx\\*.txd``, xx = us or jp): parse and rebuild.

New for XS3 (the XS2 kit's menu kind reads XS2's ``yosikawa\\*.txd``, a
different layout). Layout, from the four files on D1, D2 and the May 2006
prototype (the prototype's .txd differ from retail, an independent check)::

    menutext.txd                     synopsis / discchg / devchk .txd
    u32 count                        u32 offsets[n]   (n = first offset / 4)
    u32 offsets[count]
    strings, NUL-terminated, contiguous, no trailing pad; offsets are absolute

Strings use the build's print codec (``textcodec.for_region``: USA
``UsCodec``, JP ``JpCodec``) with ``$`` codes,
literal ``\\n`` (synopsis/devchk) or real CR LF (menutext), and backslash
escapes like ``\\31\\3`` (devchk). Regional path template in SLUS:
``mnu\\xx\\{discchg,synopsis,devchk}.txd`` ('xx' from the locale table at
0x420cc8).

Japanese build: the same two layouts (4/4 files rebuild byte-identically).
String counts JP / USA: menutext 909 / 907, synopsis 166, discchg 13, devchk 20.
menutext indices 0-906 hold the same entries on both builds; 907-908 exist on
JP (and in the May 2006 prototype), not on USA retail (``JP_ONLY_MENUTEXT``).

Per-container API::

    t = parse(data, region)    Table; t.items -> [textcodec.Item(key 'NNNN', raw, codec, role 'menu')]
    build(Table(t.counted, new)) or rebuild(t, new) -> bytes    (new: bytes or Items, any count)

    python txd.py --self-test
"""
from __future__ import annotations

import os
import struct
import sys
from dataclasses import dataclass, field
from typing import List

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import region as _region                                           # noqa: E402
import textcodec                                                   # noqa: E402


class TxdError(ValueError):
    pass


JP_ONLY_MENUTEXT = (907, 908)


@dataclass
class Table:
    counted: bool
    strings: List[bytes]
    region: object = field(default=None, compare=False)

    @property
    def items(self) -> List[textcodec.Item]:
        codec = textcodec.codec_name_for(self.region)
        return [textcodec.Item(f"{i:04d}", s, codec, "menu") for i, s in enumerate(self.strings)]


def parse(data: bytes, region=None) -> Table:
    if len(data) < 8:
        raise TxdError("too short for a .txd")
    a, b = struct.unpack_from("<II", data)
    if 0 < a < 65536 and 4 + 4 * a == b:
        counted, n, hdr = True, a, 4
    elif a % 4 == 0 and 4 <= a <= len(data):
        counted, n, hdr = False, a // 4, 0
    else:
        raise TxdError("not a .txd offset table")
    offs = struct.unpack_from(f"<{n}I", data, hdr)
    out = []
    for o in offs:
        if o > len(data):
            raise TxdError("offset beyond the file")
        e = data.find(b"\0", o)
        out.append(data[o:e if e >= 0 else len(data)])
    return Table(counted, out, _region.as_region(region))


def build(table: Table) -> bytes:
    n = len(table.strings)
    hdr = (4 if table.counted else 0) + 4 * n
    offs, blob = [], bytearray()
    for s in map(textcodec.raw_of, table.strings):
        if b"\0" in s:
            raise TxdError("a NUL byte inside a string")
        offs.append(hdr + len(blob))
        blob += s + b"\0"
    return (struct.pack("<I", n) if table.counted else b"") + struct.pack(f"<{n}I", *offs) + bytes(blob)


def rebuild(table: Table, strings) -> bytes:
    return build(Table(table.counted, [textcodec.raw_of(x) for x in strings]))


def self_test() -> int:
    ok = True

    def check(cond, msg):
        nonlocal ok
        print(("ok    " if cond else "FAIL  ") + msg)
        ok &= bool(cond)

    for counted in (True, False):
        t = Table(counted, [b"Yes", b"M\xf6bius", b"", b"<\xa2\xa4> button"])
        d = build(t)
        check(parse(d) == t and build(parse(d)) == d, f"synthetic {'counted' if counted else 'plain'} table round-trips")
    t = parse(build(Table(True, ["メニュー".encode("euc_jp"), b"OK"])), "jp")
    check([i.codec for i in t.items] == ["jp", "jp"] and rebuild(t, t.items) == build(t),
          "JP table: items read with the jp codec; rebuild accepts Items")
    isos = [(k, os.environ.get(k)) for k in ("XS3_D1", "XS3_D2", "XS3_PROTO", "XS3_JP1", "XS3_JP2")]
    if not any(v for _, v in isos):
        print("SKIP  disc checks (set XS3_D1 / XS3_D2 / XS3_PROTO / XS3_JP1 / XS3_JP2)")
    from disc import Disc
    for env, iso in isos:
        if not iso:
            continue
        with Disc(iso) as disc:
            reg = _region.detect(disc)
            paths = [e.path for _c, e in disc.entries() if e.path.lower().endswith(".txd")]
            bad, counts, esc = [], {}, 0
            for p in paths:
                d = disc.read(p)
                tb = parse(d, reg)
                if build(tb) != d:
                    bad.append(p)
                counts[p.rsplit("\\", 1)[-1].lower()] = len(tb.strings)
                for it in tb.items:
                    esc += bool(textcodec.HIGH_ESC.search(textcodec.codec_by_name(it.codec).to_text(it.raw))) \
                        and reg.codec == "jp"
            want = {"jp": 909, "us": 907, "proto_2006_05": 909}[reg.name]
            check(len(paths) == 4 and not bad and esc == 0 and counts.get("menutext.txd") == want,
                  f"{env}: {len(paths)} .txd rebuild byte-identically {bad or ''}; counts {counts}"
                  + (f"; {esc} JP strings with escapes of high bytes" if reg.codec == "jp" else ""))
    print("self-test", "passed" if ok else "FAILED")
    return 0 if ok else 1


def add_commands(subparsers) -> None:
    p = subparsers.add_parser("txd-strings", help="list the strings of an XS3 .txd file (local file)")
    p.add_argument("file")
    p.add_argument("--region", default="us", help="build profile: us (default), proto_2006_05 or jp")

    def run(a):
        t = parse(open(a.file, "rb").read(), a.region)
        for it in t.items:
            print(f"{it.key} {textcodec.codec_by_name(it.codec).to_text(it.raw)}")
        return 0
    p.set_defaults(func=run)


if __name__ == "__main__":
    if sys.argv[1:] == ["--self-test"]:
        sys.exit(self_test())
    print(__doc__)
