"""msgdat.py — the HaKox mini-game message table (``mg1\\xx\\Message.Dat``): parse and rebuild.

New for this kit (2026-11-20), from the Japanese brief (M16) and a fresh look
at the USA file. The two builds use different layouts; the build profile
(``region``) picks one and the parser checks the bytes fit it::

    JP  (mg1\\jp\\Message.Dat, 31,483 bytes = 0x7AFB, 871 messages)
        0x0000  u16 offsets[871], zero-filled to 0x800 (1,024 slots)
        0x0800  strings, NUL-terminated, contiguous in index order
                (offsets are relative to 0x800; u16 limits the string area to 64 KB)

    USA (mg1\\us\\Message.Dat, 44,133 bytes, 933 messages; the May 2006
        prototype has 922 and the same layout)
        0x0000  u32 offsets[933], zero-filled to 0x1000 (1,024 slots)
        0x1000  u16 a[1024]   per-message values: 0 on 750, 1 on 182, 2 on 1
        0x1800  u16 b[1024]   0xFC00 on 740, 0x01F0 on 183, 0x000A on 10
        0x2000  u16 c[1024]   0xFC00 on 767, 0x0064 on 165, 0x01BE on 1
        0x2800  strings, NUL-terminated, contiguous, offsets relative to 0x2800
        slots past the last message are 0 in all four arrays.

The meaning of a/b/c is NOT known. They are set on the stage hints, world
descriptions, menu help and option lines (they look like layout values, e.g.
b = 496 on most of them), and the prototype has a = 0 everywhere. They are
carried with each message (``Item.flags``) and written back unchanged; the
JP file has no such arrays.

Every string is game text in the build's print codec (USA ``us``: the button
glyphs ``<○> <×> <△> <□>`` are A1FB A1DF A2A4 A2A2 pairs; JP ``jp``). The USA
file still holds the name-entry kana grids (messages 587 and 589) as EUC A4
pairs, which the USA codec writes as ``⟦A4⟧⟦xx⟧`` escapes (the USA font has
Latin glyphs in the kana rows).

Per-container API::

    m = parse(data, region)        Message; m.items -> [textcodec.Item(key 'NNNN', raw, codec, 'message', flags)]
    rebuild(m, new) -> bytes        new: bytes or Items, same count; offsets recomputed,
                                    everything else in the header kept byte for byte

The loader's buffer for Message.Dat is NOT known: a grown file is unchecked
against the game.

    python msgdat.py --self-test
"""
from __future__ import annotations

import os
import struct
import sys
from dataclasses import dataclass, field
from typing import List, NamedTuple, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import region as _region                                           # noqa: E402
import textcodec                                                   # noqa: E402


class MsgError(ValueError):
    pass


class Layout(NamedTuple):
    width: int                  # offset size in bytes
    slots: int                  # offset slots in the table
    strings: int                # file offset of the string area
    attrs: Tuple[int, ...]      # file offsets of the u16[slots] arrays (USA a, b, c)


LAYOUTS = {
    "jp": Layout(2, 1024, 0x800, ()),
    "us": Layout(4, 1024, 0x2800, (0x1000, 0x1800, 0x2000)),
}


def layout_for(region) -> Layout:
    return LAYOUTS["jp" if _region.as_region(region).codec == "jp" else "us"]


@dataclass
class Message:
    data: bytes
    layout: Layout
    strings: List[bytes]
    attrs: List[Tuple[int, ...]] = field(default_factory=list)     # per message: (a, b, c) on USA
    region: object = None

    @property
    def items(self) -> List[textcodec.Item]:
        codec = textcodec.codec_name_for(self.region)
        out = []
        for i, s in enumerate(self.strings):
            flags = ("a=%d b=%#x c=%#x" % self.attrs[i],) if self.attrs else ()
            out.append(textcodec.Item(f"{i:04d}", s, codec, "message", flags))
        return out


def parse(data: bytes, region=None) -> Message:
    lay = layout_for(region)
    fmt = "<H" if lay.width == 2 else "<I"
    if len(data) < lay.strings:
        raise MsgError(f"{len(data)} bytes: shorter than the {lay.strings:#x}-byte header of this layout")
    offs = list(struct.unpack_from(f"<{lay.slots}{fmt[1]}", data, 0))
    if offs[0] != 0:
        raise MsgError("the first offset is not 0: not this build's Message.Dat layout")
    n = 1
    while n < lay.slots and offs[n] > offs[n - 1]:
        n += 1
    if any(offs[n:]):
        raise MsgError(f"nonzero offset slots after message {n}: not this build's Message.Dat layout")
    strings, pos = [], 0
    for i in range(n):
        if offs[i] != pos:
            raise MsgError(f"message {i} starts at {offs[i]:#x}, expected {pos:#x}: strings are not contiguous")
        start = lay.strings + offs[i]
        e = data.find(b"\0", start)
        if e < 0:
            raise MsgError(f"message {i} is not NUL-terminated")
        strings.append(data[start:e])
        pos += e - start + 1
    if lay.strings + pos != len(data):
        raise MsgError(f"{len(data) - lay.strings - pos} bytes after the last string")
    attrs: List[Tuple[int, ...]] = []
    if lay.attrs:
        arrays = [struct.unpack_from(f"<{lay.slots}H", data, a) for a in lay.attrs]
        if any(any(arr[n:]) for arr in arrays):
            raise MsgError("attribute slots past the last message are not zero")
        attrs = [tuple(arr[i] for arr in arrays) for i in range(n)]
    tbl_end = lay.width * lay.slots
    gap_end = lay.attrs[0] if lay.attrs else lay.strings
    if any(data[tbl_end:gap_end]) or any(data[lay.attrs[-1] + 2 * lay.slots:lay.strings] if lay.attrs else b""):
        raise MsgError("unexpected bytes in the header padding")
    return Message(data, lay, strings, attrs, _region.as_region(region))


def rebuild(msg: Message, strings) -> bytes:
    """The file with ``strings`` (same count) re-laid and the offsets recomputed."""
    strings = [textcodec.raw_of(x) for x in strings]
    if len(strings) != len(msg.strings):
        raise MsgError(f"{len(strings)} strings given, the file holds {len(msg.strings)}")
    lay = msg.layout
    offs, blob = [], bytearray()
    for i, s in enumerate(strings):
        if b"\0" in s:
            raise MsgError(f"message {i}: a NUL byte inside a string")
        offs.append(len(blob))
        blob += s + b"\0"
    limit = 1 << (8 * lay.width)
    if offs and offs[-1] >= limit:
        raise MsgError(f"the last message would start at {offs[-1]:#x}: this layout's u{8 * lay.width} "
                       f"offsets reach {limit:#x} at most")
    head = bytearray(msg.data[:lay.strings])
    struct.pack_into(f"<{len(offs)}{'H' if lay.width == 2 else 'I'}", head, 0, *offs)
    return bytes(head) + bytes(blob)


# ------------------------------------------------------------------ self-test

def _synthetic(region: str, strings: List[bytes], attrs=None) -> bytes:
    lay = layout_for(region)
    head = bytearray(lay.strings)
    blob, offs = bytearray(), []
    for s in strings:
        offs.append(len(blob))
        blob += s + b"\0"
    struct.pack_into(f"<{len(offs)}{'H' if lay.width == 2 else 'I'}", head, 0, *offs)
    for k, a in enumerate(lay.attrs):
        for i, v in enumerate(attrs or []):
            struct.pack_into("<H", head, a + 2 * i, v[k])
    return bytes(head) + bytes(blob)


def self_test() -> int:
    ok = True

    def check(cond, msg):
        nonlocal ok
        print(("ok    " if cond else "FAIL  ") + msg)
        ok &= bool(cond)

    def raises(fn, msg):
        try:
            fn()
            check(False, msg)
        except MsgError:
            check(True, msg)

    js = ["ゴールに到着するとキャラは\\n異次元に消え去ります。".encode("euc_jp"), b"", "ＯＫ".encode("euc_jp")]
    jd = _synthetic("jp", js)
    m = parse(jd, "jp")
    check(m.strings == js and rebuild(m, m.strings) == jd and [i.codec for i in m.items] == ["jp"] * 3,
          "JP synthetic: u16 offsets, strings at 0x800, empty message kept, byte-identical rebuild")
    grown = rebuild(m, [js[0] + "！".encode("euc_jp"), b"x", js[2]])
    check(parse(grown, "jp").strings[0].endswith("！".encode("euc_jp")), "JP: a grown message moves the others")
    raises(lambda: rebuild(m, [b"a" * 70000, b"", b""]), "JP: an offset past 0xFFFF is refused (u16)")
    us = [b"OFF", b"<\xa1\xfb> = Execute", b"Stage for editing."]
    ud = _synthetic("us", us, [(1, 0x1F0, 0x64), (0, 0xFC00, 0xFC00), (2, 0x1F0, 0x1BE)])
    mu = parse(ud, "us")
    check(mu.attrs[2] == (2, 0x1F0, 0x1BE) and rebuild(mu, mu.items) == ud and mu.items[0].flags == ("a=1 b=0x1f0 c=0x64",),
          "USA synthetic: u32 offsets, a/b/c arrays carried per message, rebuild from Items")
    raises(lambda: parse(jd, "us"), "a JP file under the USA layout is refused")
    raises(lambda: parse(ud, "jp"), "a USA file under the JP layout is refused")
    raises(lambda: rebuild(mu, us[:2]), "a different message count is refused")

    isos = [(k, os.environ.get(k)) for k in ("XS3_D1", "XS3_D2", "XS3_PROTO", "XS3_JP1", "XS3_JP2")]
    if not any(v for _, v in isos):
        print("SKIP  disc checks (set XS3_D1 / XS3_D2 / XS3_PROTO / XS3_JP1 / XS3_JP2)")
    from disc import Disc
    for env, iso in isos:
        if not iso:
            continue
        with Disc(iso) as disc:
            reg = _region.detect(disc)
            path = _region.resolve(disc, "mg1\\xx\\Message.Dat", reg)
            d = disc.read(path)
            mm = parse(d, reg)
            codec = textcodec.codec_by_name(mm.items[0].codec)
            exact = all(codec.from_text(codec.to_text(s)) == s for s in mm.strings)
            esc = sum(bool(textcodec.HIGH_ESC.search(codec.to_text(s))) for s in mm.strings)
            want = {"jp": (871, 0x7AFB), "us": (933, 44133), "proto_2006_05": (922, 43836)}[reg.name]
            # USA keeps the name-entry kana grids (messages 587, 589) as A4 pairs, which
            # the USA codec writes as escapes by design (its font has no kana there)
            check(rebuild(mm, mm.strings) == d and (len(mm.strings), len(d)) == want and exact
                  and (esc == 0 if reg.codec == "jp" else esc == 2),
                  f"{env}: {path} {len(d)} bytes, {len(mm.strings)} messages, rebuild byte-identical, "
                  f"codec {mm.items[0].codec} exact, {esc} with high-byte escapes")
    print("self-test", "passed" if ok else "FAILED")
    return 0 if ok else 1


def add_commands(subparsers) -> None:
    """``msgdat-strings FILE [--region us|jp]``: list a Message.Dat (local file)."""
    p = subparsers.add_parser("msgdat-strings", help="list the messages of an XS3 mg1 Message.Dat (local file)")
    p.add_argument("file")
    p.add_argument("--region", default="us", help="build profile: us (default), proto_2006_05 or jp")

    def run(a):
        m = parse(open(a.file, "rb").read(), a.region)
        for it in m.items:
            flags = f" [{','.join(it.flags)}]" if it.flags else ""
            print(f"{it.key}{flags} {textcodec.codec_by_name(it.codec).to_text(it.raw)}")
        return 0
    p.set_defaults(func=run)


if __name__ == "__main__":
    if sys.argv[1:] == ["--self-test"]:
        sys.exit(self_test())
    print(__doc__)
