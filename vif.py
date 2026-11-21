#!/usr/bin/env python3
"""PS2 VIF command stream walker (strict).

Borrowed from the Xenosaga Episode II kit, Xenosaga2PythonExtractor/vif.py
(same author, MIT), 2026-11-20.  Changed: nothing in the walker (it walks
every Episode III `.pxy` stream unchanged); `self_test()` returns 0 and
`add_commands()` was added for the kit's CLI convention (this module is a
library and registers no subcommand).  Episode III uses the same `.pxy`
VIF framing as Episode II; the signed V4-16 unpacks of its quantized
meshes are decoded by the walker already (USN is reported, not judged).

The Episode II `.pxy` meshes carry their geometry as a raw VIF1 command
stream (no DMA tags inside the file; the engine wraps each draw-list
entry in a DMA `ref` tag at run time).  This module walks such a stream
command by command.  It never skips a byte it does not understand: an
unknown command, a truncated payload or a non-zero pad raises `VifError`.

    python vif.py --self-test
    python vif.py FILE --start 0x3bf0 --end 0x3c9e0     # list the commands

Command encoding (Sony EE User's Manual, VIF chapter): one 32-bit word
`CMD:8 NUM:8 IMMEDIATE:16`, CMD bit 7 = interrupt.  UNPACK is
`011 m vn:2 vl:2`; its NUM is a count of *written* vectors with 0
meaning 256; IMMEDIATE = `FLG:1 USN:1 0000 ADDR:10` (FLG adds VIF1_TOPS
to the address, USN = zero-extend).  The data length depends on the
current STCYCL (CL, WL): with WL <= CL every written vector is read
from the stream; with WL > CL only CL of every WL are.
"""
import struct
import sys

__all__ = ["VifError", "Cmd", "walk", "unpack_data", "histogram", "self_test"]


class VifError(ValueError):
    pass


NAMES = {
    0x00: "NOP", 0x01: "STCYCL", 0x02: "OFFSET", 0x03: "BASE", 0x04: "ITOP",
    0x05: "STMOD", 0x06: "MSKPATH3", 0x07: "MARK", 0x10: "FLUSHE",
    0x11: "FLUSH", 0x13: "FLUSHA", 0x14: "MSCAL", 0x15: "MSCALF",
    0x17: "MSCNT", 0x20: "STMASK", 0x30: "STROW", 0x31: "STCOL",
    0x4A: "MPG", 0x50: "DIRECT", 0x51: "DIRECTHL",
}
_EXTRA_WORDS = {0x20: 1, 0x30: 4, 0x31: 4}
VN = ("S", "V2", "V3", "V4")
VL = ("32", "16", "8", "5")


class Cmd(object):
    """One decoded VIF command."""
    __slots__ = ("off", "cmd", "num", "imm", "irq", "name", "data_off",
                 "data_len", "cl", "wl", "vn", "vl", "mask", "usn", "flg",
                 "addr", "count", "mode")

    def __init__(self, **kw):
        for k in self.__slots__:
            setattr(self, k, kw.get(k))

    @property
    def is_unpack(self):
        return self.vn is not None

    @property
    def fmt(self):
        return "%s-%s" % (VN[self.vn], VL[self.vl]) if self.is_unpack else None

    def __repr__(self):
        if self.is_unpack:
            return ("<%06x UNPACK %s n=%d addr=%d%s%s%s cl=%d wl=%d>" % (
                self.off, self.fmt, self.count, self.addr,
                " TOPS" if self.flg else "", " USN" if self.usn else "",
                " MASK" if self.mask else "", self.cl, self.wl))
        return "<%06x %s num=%d imm=0x%04x>" % (self.off, self.name,
                                                self.num, self.imm)


def unpack_words(vn, vl, count, cl, wl):
    """Bytes of stream data an UNPACK of `count` written vectors reads."""
    if vl == 3:
        if vn != 3:
            raise VifError("UNPACK vl=5 only exists as V4-5")
        elem_bits = 16
    else:
        elem_bits = (32 >> vl) * (vn + 1)
    if wl <= cl:
        n_read = count
    else:
        if wl == 0:
            raise VifError("UNPACK with WL=0")
        n_read = cl * (count // wl) + min(count % wl, cl)
    nbytes = (n_read * elem_bits + 7) // 8
    return nbytes, (nbytes + 3) & ~3


def walk(buf, start=0, end=None, cl=1, wl=1, mode=0):
    """Yield a `Cmd` for every VIF command in buf[start:end].

    Raises VifError on the first thing that is not a well-formed VIF
    command.  The stream must end exactly at `end`.
    """
    if end is None:
        end = len(buf)
    if (start | end) & 3:
        raise VifError("VIF stream bounds not word aligned")
    p = start
    while p < end:
        w, = struct.unpack_from("<I", buf, p)
        cmd = (w >> 24) & 0x7F
        irq = w >> 31
        num = (w >> 16) & 0xFF
        imm = w & 0xFFFF
        c = Cmd(off=p, cmd=cmd, num=num, imm=imm, irq=irq, cl=cl, wl=wl,
                mode=mode, data_off=p + 4, data_len=0)
        if cmd >= 0x60:
            vn = (cmd >> 2) & 3
            vl = cmd & 3
            count = num or 256
            nbytes, padded = unpack_words(vn, vl, count, cl, wl)
            if p + 4 + padded > end:
                raise VifError("UNPACK at 0x%x runs past the stream end" % p)
            pad = buf[p + 4 + nbytes:p + 4 + padded]
            if any(bytearray(pad)):
                raise VifError("UNPACK at 0x%x has non-zero padding" % p)
            if imm & 0x3C00:
                raise VifError("UNPACK at 0x%x: reserved address bits set "
                               "(imm 0x%04x)" % (p, imm))
            c.name = "UNPACK"
            c.vn, c.vl, c.mask = vn, vl, (cmd >> 4) & 1
            c.flg, c.usn, c.addr = imm >> 15, (imm >> 14) & 1, imm & 0x3FF
            c.count = count
            c.data_len = nbytes
            p += 4 + padded
        elif cmd in NAMES:
            c.name = NAMES[cmd]
            extra = 0
            if cmd in _EXTRA_WORDS:
                extra = 4 * _EXTRA_WORDS[cmd]
            elif cmd == 0x4A:
                extra = 8 * (num or 256)
                if p & 4 == 0:
                    raise VifError("MPG at 0x%x: data not 8-byte aligned" % p)
            elif cmd in (0x50, 0x51):
                extra = 16 * (imm or 65536)
                if (p + 4) & 15:
                    raise VifError("DIRECT at 0x%x: data not qword aligned"
                                   % p)
            elif cmd == 0x01:
                cl, wl = imm & 0xFF, imm >> 8
                c.cl, c.wl = cl, wl
            elif cmd == 0x05:
                mode = imm & 3
                c.mode = mode
            if p + 4 + extra > end:
                raise VifError("%s at 0x%x runs past the stream end"
                               % (c.name, p))
            c.data_len = extra
            p += 4 + extra
        else:
            raise VifError("unknown VIF command 0x%02x (word 0x%08x) at 0x%x"
                           % (cmd, w, p))
        yield c
    if p != end:
        raise VifError("VIF stream overran its end")


def unpack_data(buf, c):
    """The rows of an UNPACK as a list of tuples (raw stream values;
    no row/mask/mode processing).  Only WL <= CL streams."""
    if c.wl > c.cl:
        raise VifError("unpack_data: fill-write (WL > CL) not supported")
    n = c.vn + 1
    if c.vl == 3:
        vals = struct.unpack_from("<%dH" % c.count, buf, c.data_off)
        return [(v & 31, (v >> 5) & 31, (v >> 10) & 31, v >> 15) for v in vals]
    ch = ("I", "H", "B")[c.vl] if c.usn else ("i", "h", "b")[c.vl]
    vals = struct.unpack_from("<%d%s" % (c.count * n, ch), buf, c.data_off)
    return [vals[i:i + n] for i in range(0, len(vals), n)]


def histogram(buf, start, end, hist=None):
    """Add this stream's commands to a dict keyed by a signature tuple."""
    if hist is None:
        hist = {}
    for c in walk(buf, start, end):
        if c.is_unpack:
            key = ("UNPACK", c.fmt, "mask" if c.mask else "", "USN" if c.usn
                   else "", "TOPS" if c.flg else "", "cl%d/wl%d" % (c.cl, c.wl),
                   "mode%d" % c.mode)
        elif c.cmd == 0x01:
            key = ("STCYCL", "cl%d/wl%d" % (c.cl, c.wl))
        elif c.cmd in (0x14, 0x15, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07):
            key = (c.name, "imm=0x%x" % c.imm)
        else:
            key = (c.name,)
        if c.irq:
            key = key + ("IRQ",)
        hist[key] = hist.get(key, 0) + 1
    return hist


def self_test():
    w = lambda cmd, num, imm: struct.pack("<I", cmd << 24 | num << 16 | imm)
    s = b""
    s += w(0x01, 0, 0x0101)                               # STCYCL 1/1
    s += w(0x6C, 2, 0xC005) + struct.pack("<8f", *range(8))   # V4-32 x2
    s += w(0x64, 3, 0x8010) + struct.pack("<6f", *range(6))   # V2-32 x3
    s += w(0x6E, 3, 0x4020) + bytes(bytearray(range(12)))     # V4-8 x3 USN
    s += w(0x6A, 1, 0x0030) + b"\x01\xff\x03\x00"             # V3-8 + pad
    s += w(0x20, 0, 0) + b"\x55" * 4                      # STMASK
    s += w(0x30, 0, 0) + b"\0" * 16                       # STROW
    s += w(0x17, 0, 0)                                    # MSCNT
    s += w(0x14, 0, 8)                                    # MSCAL 8
    s += w(0x01, 0, 0x0401)                               # STCYCL cl1 wl4
    s += w(0x6C, 8, 0) + b"\0" * 32                       # fill: 2 read
    cs = list(walk(s))
    assert [c.name for c in cs] == ["STCYCL", "UNPACK", "UNPACK", "UNPACK",
                                    "UNPACK", "STMASK", "STROW", "MSCNT",
                                    "MSCAL", "STCYCL", "UNPACK"], cs
    assert cs[1].fmt == "V4-32" and cs[1].flg == 1 and cs[1].usn == 1
    assert cs[1].addr == 5 and cs[1].count == 2
    assert unpack_data(s, cs[1])[1] == struct.unpack(
        "<4I", struct.pack("<4f", 4.0, 5.0, 6.0, 7.0))   # raw words
    assert unpack_data(s, cs[3]) == [(0, 1, 2, 3), (4, 5, 6, 7),
                                     (8, 9, 10, 11)]
    assert unpack_data(s, cs[4]) == [(1, -1, 3)]
    assert cs[10].data_len == 32
    # zero means 256
    z = w(0x6E, 0, 0) + b"\0" * 1024
    assert next(walk(z)).count == 256
    # hard failures
    for bad in (w(0x7F & 0x44, 0, 0), s[:-4], w(0x6A, 1, 0) + b"\1\2\3\4",
                w(0x6C, 1, 0x1000) + b"\0" * 16):
        try:
            list(walk(bad))
        except VifError:
            pass
        else:
            raise AssertionError("walker accepted a bad stream")
    h = histogram(s, 0, len(s))
    assert h[("MSCNT",)] == 1 and h[("MSCAL", "imm=0x8")] == 1
    print("vif self-test ok")
    return 0


def add_commands(subparsers):
    """Library module: registers no CLI subcommand (kit convention)."""
    return None


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="strict VIF stream walker")
    ap.add_argument("file", nargs="?")
    ap.add_argument("--start", type=lambda s: int(s, 0), default=0)
    ap.add_argument("--end", type=lambda s: int(s, 0))
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test or not a.file:
        return self_test()
    with open(a.file, "rb") as f:
        buf = f.read()
    for c in walk(buf, a.start, a.end):
        print(repr(c))


if __name__ == "__main__":
    sys.exit(main())
