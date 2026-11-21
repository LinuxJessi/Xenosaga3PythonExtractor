"""njbin.py — Xenosaga III menu databases (``mnu\\xx\\DBC.bin``, ``DBC2.bin``,
``MVtext.bin``, ``SegmentFileData.bin``, ``njBtlText.bin``, ``njDBcommon.bin``,
``njDataText.bin``): parse and rebuild the string pools.

New for XS3 (no XS2 analogue). Grounded in the survey's scratch njrt.py /
ptrscan.py, which rebuilt all seven files byte-identically on D1 and the May
2006 prototype.

Outer container::

    u32 count, count x {u32 offset, u32 size}, 0x90 padding to 16;
    each blob starts on a 16-byte boundary, 0x90 between blobs.

Inner blobs: tagged record tables (``DBF`` encyclopedia records of 0xD0 bytes,
``TOP``/``CHA``/``EVE``, ``MVD``, ``SEG``) or plain offset tables, followed by
a string area. Every string reference is a blob-relative u32 that sits before
the string area. ``pointer_map`` finds them from the ORIGINAL bytes: the
string area starts at the lowest u32 value that follows a NUL and is followed
only by text bytes; a pointer is any u32 field before that start whose value
lands inside the area. The map is a pure function of the original bytes, so
it is frozen by the object's sha1 (textpack refuses another revision).

Strings are re-laid in their original order from the original start; each
pointer gets ``new start of its string + its byte offset``.

**Mid-string values.** 7 fields in DBC2.bin and 7 in njDataText.bin (D1) land
inside a string ('View s|ummary of ...', '<Federation| Police>'). They are
kept as (string, byte offset). Their meaning is NOT known: they may be page
breaks or plain numbers that happen to fall in range (in CHA records they sit
in a column of their own). So a rebuild refuses to change a string that holds
one; when only other strings change they move with their string.

Japanese build (``mnu\\jp\\``): the same container and the same pointer-scan
rebuild (7/7 byte-identical). Strings use the JP codec. Per build the blob
layout differs: DBC2.bin has 12 blobs on JP vs 27 on USA and no mid-string
values (USA 7); njDataText.bin has 7 mid-string values on JP too; njDBcommon.bin
holds 58 strings vs 48; DBC.bin is 420,140 bytes vs 510,999. The pointer map is
derived from each file's own bytes, so no per-build table is needed.

Per-container API::

    c = parse(data, region)       Container; c.items -> [textcodec.Item(key 'BB.KKKK', raw, codec, role, flags)]
                                  flags: 'mid-string' (read-only), 'unreferenced'
    rebuild(c, [[bytes]*n]*blobs) or rebuild_items(c, items) -> bytes
                                  (items: Items or (key, bytes); keys left out keep their bytes)

    python njbin.py --self-test
"""
from __future__ import annotations

import os
import struct
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import region as _region                                           # noqa: E402
import textcodec                                                   # noqa: E402

PAD = b"\x90"
ALIGN = 16
NAMES = ("DBC.bin", "DBC2.bin", "MVtext.bin", "SegmentFileData.bin",
         "njBtlText.bin", "njDBcommon.bin", "njDataText.bin")


class NjError(ValueError):
    pass


# ------------------------------------------------------------------ outer

def parse_outer(data: bytes) -> List[bytes]:
    if len(data) < 4:
        raise NjError("too short")
    n = struct.unpack_from("<I", data)[0]
    if not 0 < n < 4096 or 4 + 8 * n > len(data):
        raise NjError("not an nj container (bad count)")
    out = []
    for i in range(n):
        o, s = struct.unpack_from("<II", data, 4 + 8 * i)
        if o + s > len(data):
            raise NjError(f"blob {i} runs past the file")
        out.append(data[o:o + s])
    return out


def build_outer(blobs: List[bytes]) -> bytes:
    n = len(blobs)
    first = -(-(4 + 8 * n) // ALIGN) * ALIGN
    offs, body, cur = [], bytearray(), first
    for i, b in enumerate(blobs):
        offs.append(cur)
        body += b
        cur += len(b)
        if i < n - 1:
            p = (-cur) % ALIGN
            body += PAD * p
            cur += p
    head = struct.pack("<I", n) + b"".join(struct.pack("<II", o, len(b)) for o, b in zip(offs, blobs))
    return head + PAD * (first - len(head)) + bytes(body)


# ------------------------------------------------------------------ inner

def _texty(b: bytes) -> bool:
    return all(x >= 0x20 or x in (0, 9, 10, 13) for x in b)


@dataclass
class Blob:
    data: bytes
    start: Optional[int]                     # string area start, None = no strings
    segs: List[Tuple[int, bytes]] = field(default_factory=list)       # (offset, bytes)
    ptrs: List[Tuple[int, int, int]] = field(default_factory=list)    # (field, seg index, byte offset)
    terminated: bool = True

    @property
    def strings(self) -> List[bytes]:
        return [s for _, s in self.segs]

    def referenced(self) -> Dict[int, List[int]]:
        out: Dict[int, List[int]] = {}
        for _f, k, j in self.ptrs:
            out.setdefault(k, []).append(j)
        return out

    def mid(self) -> Dict[int, List[int]]:
        return {k: [j for j in js if j] for k, js in self.referenced().items() if any(js)}


def pointer_map(b: bytes) -> Blob:
    n = len(b) // 4
    vals = [(p * 4, struct.unpack_from("<I", b, p * 4)[0]) for p in range(n)]
    cands = sorted({v for p, v in vals if p < v < len(b) and b[v - 1] == 0})
    start = next((v for v in cands if _texty(b[v:])), None)
    if start is None:
        return Blob(b, None)
    segs, i = [], start
    while i < len(b):
        e = b.find(b"\0", i)
        if e < 0:
            e = len(b)
        segs.append((i, b[i:e]))
        i = e + 1
    where = {}
    for k, (st, s) in enumerate(segs):
        for j in range(len(s) + 1):
            where.setdefault(st + j, (k, j))
    ptrs = []
    for p, v in vals:
        if p + 4 <= start and start <= v < len(b) and v in where:
            k, j = where[v]
            ptrs.append((p, k, j))
    return Blob(b, start, segs, ptrs, b.endswith(b"\0"))


def build_blob(blob: Blob, strings: List[bytes]) -> bytes:
    if blob.start is None:
        if strings:
            raise NjError("this blob holds no strings")
        return blob.data
    if len(strings) != len(blob.segs):
        raise NjError(f"{len(strings)} strings given, the blob holds {len(blob.segs)}")
    for k, js in blob.mid().items():
        if strings[k] != blob.segs[k][1]:
            raise NjError(f"string {k} holds a value that points inside it (byte offset(s) "
                          f"{', '.join(map(str, js))}) whose meaning is unknown; it cannot be changed")
    out, new = bytearray(blob.data[:blob.start]), []
    for s in strings:
        if b"\0" in s:
            raise NjError("a NUL byte inside a string")
        new.append(len(out))
        out += s + b"\0"
    if not blob.terminated:
        out = out[:-1]
    for p, k, j in blob.ptrs:
        struct.pack_into("<I", out, p, new[k] + j)
    return bytes(out)


@dataclass
class Container:
    data: bytes
    blobs: List[Blob]
    region: object = None

    def codec(self, s: bytes) -> str:
        if _region.as_region(self.region).codec == "jp":
            return "jp"
        # USA: the May 2006 prototype's DBC2.bin is untranslated EUC-JP; such a
        # string keeps its exact Japanese reading
        return textcodec.NoteCodec.pick_euc(s) or "us"

    @property
    def items(self) -> List[textcodec.Item]:
        out = []
        for i, b in enumerate(self.blobs):
            mid, refd = b.mid(), b.referenced()
            for k, s in enumerate(b.strings):
                flags = (("mid-string",) if k in mid else ()) + (() if k in refd else ("unreferenced",))
                out.append(textcodec.Item(f"{i:02d}.{k:04d}", s, self.codec(s), "menu-db", flags))
        return out


def parse(data: bytes, region=None) -> Container:
    return Container(data, [pointer_map(b) for b in parse_outer(data)], _region.as_region(region))


def rebuild_items(c: Container, items) -> bytes:
    """Rebuild from a flat list of Items or (key, bytes) pairs ('BB.KKKK' keys)."""
    new = [list(b.strings) for b in c.blobs]
    for it in items:
        key, raw = (it.key, it.raw) if isinstance(it, textcodec.Item) else (it[0], bytes(it[1]))
        i, k = (int(x) for x in key.split("."))
        if not (0 <= i < len(new) and 0 <= k < len(new[i])):
            raise NjError(f"no string {key} in this container")
        new[i][k] = raw
    return rebuild(c, new)


def rebuild(c: Container, strings: List[List[bytes]]) -> bytes:
    """``strings[i]`` = the new strings of blob i (same counts)."""
    if len(strings) != len(c.blobs):
        raise NjError("blob count differs")
    if all(s == b.strings for s, b in zip(strings, c.blobs)):
        return c.data
    return build_outer([build_blob(b, s) for b, s in zip(c.blobs, strings)])


def self_test() -> int:
    ok = True

    def check(cond, msg):
        nonlocal ok
        print(("ok    " if cond else "FAIL  ") + msg)
        ok &= bool(cond)

    # synthetic: two records pointing at strings, one mid-string value
    strs = [b"Alpha", b"Beta gamma", b"Delta"]
    start = 0x20
    offs, cur = [], start
    for s in strs:
        offs.append(cur)
        cur += len(s) + 1
    head = b"DBF\0" + struct.pack("<5I", offs[0], offs[1], offs[1] + 5, offs[2], 0xFFFFFFFF)
    head += b"\0" * (start - len(head))
    blob = head + b"".join(s + b"\0" for s in strs)
    data = build_outer([blob, b"\x01\x02\x03"])
    c = parse(data)
    check(build_outer([b.data for b in c.blobs]) == data, "synthetic: outer container rebuilds byte-identically")
    check(c.blobs[0].strings == strs and len(c.blobs[0].ptrs) == 4 and c.blobs[0].mid() == {1: [5]},
          "synthetic: pointer map finds 4 pointers, one mid-string")
    check(rebuild(c, [b.strings for b in c.blobs]) == data, "synthetic: unchanged rebuild is identical")
    new = rebuild(c, [[b"Alpha longer", strs[1], b"D"], []])
    c2 = parse(new)
    check(c2.blobs[0].strings == [b"Alpha longer", strs[1], b"D"] and c2.blobs[0].mid() == {1: [5]},
          "synthetic: an edit moves later strings and the mid-string value with its string")
    try:
        rebuild(c, [[strs[0], b"Beta delta", strs[2]], []])
        check(False, "synthetic: editing a string with a mid-string value is refused")
    except NjError:
        check(True, "synthetic: editing a string with a mid-string value is refused")

    cj = parse(data, "jp")
    check([i.codec for i in cj.items][:3] == ["jp"] * 3 and [i.flags for i in cj.items][1] == ("mid-string",)
          and rebuild_items(cj, [("00.0000", b"Alpha")]) == data, "items API: JP codec, mid-string flag, keyed rebuild")

    isos = [(k, os.environ.get(k)) for k in ("XS3_D1", "XS3_D2", "XS3_PROTO", "XS3_JP1", "XS3_JP2")]
    if not any(v for _, v in isos):
        print("SKIP  disc checks (set XS3_D1 / XS3_D2 / XS3_PROTO / XS3_JP1 / XS3_JP2)")
    from disc import Disc
    for env, iso in isos:
        if not iso:
            continue
        with Disc(iso) as disc:
            reg = _region.detect(disc)
            paths = [e.path for _c, e in disc.entries() if e.path.lower().startswith(f"mnu\\{reg.lang}\\")
                     and e.path.rsplit("\\", 1)[-1].lower() in {n.lower() for n in NAMES}]
            res, esc = [], 0
            for p in paths:
                d = disc.read(p)
                c = parse(d, reg)
                full = build_outer([build_blob(b, b.strings) if b.start is not None else b.data for b in c.blobs])
                n = sum(len(b.strings) for b in c.blobs)
                if reg.codec == "jp":
                    esc += sum(bool(textcodec.HIGH_ESC.search(textcodec.codec_by_name(it.codec).to_text(it.raw)))
                               for it in c.items)
                res.append((p.rsplit("\\", 1)[-1], full == d, len(c.blobs), n,
                            sum(len(v) for b in c.blobs for v in b.mid().values())))
            good = all(r[1] for r in res)
            check(len(paths) == 7 and good and esc == 0,
                  f"{env}: {len(paths)} nj bins re-laid byte-identically: "
                  + ", ".join(f"{n} blobs={nb} strings={ns} mid={m}{'' if g else ' DIFF'}" for n, g, nb, ns, m in res)
                  + (f"; {esc} JP strings with high-byte escapes" if reg.codec == "jp" else ""))
    print("self-test", "passed" if ok else "FAILED")
    return 0 if ok else 1


def add_commands(subparsers) -> None:
    p = subparsers.add_parser("nj-strings", help="list the strings of an XS3 mnu/xx nj*/DBC .bin (local file)")
    p.add_argument("file")
    p.add_argument("--region", default="us", help="build profile: us (default), proto_2006_05 or jp")

    def run(a):
        c = parse(open(a.file, "rb").read(), a.region)
        for it in c.items:
            flag = f" [{','.join(it.flags)}]" if it.flags else ""
            print(f"{it.key}{flag} {textcodec.codec_by_name(it.codec).to_text(it.raw)}")
        return 0
    p.set_defaults(func=run)


if __name__ == "__main__":
    if sys.argv[1:] == ["--self-test"]:
        sys.exit(self_test())
    print(__doc__)
