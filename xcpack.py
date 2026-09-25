"""
xcpack.py — MonolithSoft "Xc" MR Package layer: header, sub-resource
directory, and the engine's in-place compression.

Every ``.chr`` / ``.map`` / ``.wpn`` / ``.sme`` file on the disc is an
MR Package::

    0x00  "Xc"
    0x02  u16 version   0x0001 stored  |  0x0101 / 0x0201 / 0x0301 / 0x0401
                        = compressed with one of four LZSS flavours
    0x04  u32 payload size, decompressed
    0x08  u32 payload size as stored (== 0x04 when version is 0x0001)
    0x0C  u16 sub-resource count
    0x0E  "Xp"
    0x10  count x 4-byte type tags ("pxy", "txy", "xhr", "epf", "dap", ...)
    0x40  count x {u32 offset, u32 size}  — offsets from file start,
          valid for the DECOMPRESSED image
    0x40  (when count == 0 the header is only 0x10 bytes long)
    ...   payload

The loader (SLUS ``FUN_001b7330``) switches on the version word and runs
one of five decoders on the payload, all writing to a buffer of the
decompressed size; the sub-resource offsets then index that buffer with
the 0x40-byte header in front. Reversed from the decompile
(``FUN_001b7438`` / ``_7480`` / ``_7540`` / ``_7558`` / ``_7620``):

* **0x0001** — memcpy.
* **0x0101 / 0x0201** — LZSS-A. Flag byte, bits MSB-first, 1 = literal
  byte, 0 = back-reference ``b0 b1``: length ``(b0 >> 4) + 3``, distance
  ``((b0 & 0xF) << 8) | b1``; distance 0 = end of stream.
* **0x0301** — LZSS-B. Same flag scheme; back-reference ``b0 lo hi``:
  ``b0 == 0`` = end, else length ``b0 + 1``, distance ``u16 + 1``.
* **0x0401** — LZSS-C, the one the retail maps use. A 0 flag bit is
  followed by a SECOND flag bit choosing the form: 1 = short
  (``b0 b1``: length ``(b0 >> 4) + 3``, distance ``((b0 & 0xF) << 8 | b1)
  + 1``), 0 = long (``b0 lo hi``: ``b0 == 0`` = end, else length
  ``b0 + 1``, distance ``u16 + 1``). Both flag bits come from the same
  flag byte; a group never straddles a flag byte.

On Disc 1, 98 of the 168 ``mdl/map`` packages are 0x0401 (the field maps
— every ``E3_*`` town/dungeon); battle maps, characters and weapons are
stored. ``normalize`` turns any package into its stored (0x0001) form, so
every existing parser keeps working on the same offsets.

Not covered: ``.xep`` event packages start with ``Xc\\x01\\x03`` but are
NOT MR packages (no "Xp" tag, different header); their payload does not
decode with LZSS-B either — the event loader has its own scheme.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Dict, Iterable, List, Tuple


class XcError(ValueError):
    """Not an Xc package, or one this module cannot decode."""


VERSION_STORED = 0x0001
COMPRESSED_VERSIONS = (0x0101, 0x0201, 0x0301, 0x0401)


@dataclass(frozen=True)
class XcHeader:
    version: int
    size_decompressed: int
    size_stored: int
    count: int
    tags: Tuple[str, ...]
    dir_offset: int      # 0x40 (count > 0) or 0x10 (count == 0)

    @property
    def compressed(self) -> bool:
        return self.version != VERSION_STORED


def is_xc(data: bytes) -> bool:
    return len(data) >= 0x10 and data[:2] == b"Xc" and data[0xE:0x10] == b"Xp"


def parse_header(data: bytes) -> XcHeader:
    if len(data) < 0x10 or data[:2] != b"Xc":
        raise XcError("not an Xc package (magic)")
    if data[0xE:0x10] != b"Xp":
        raise XcError("not an MR package (no Xp tag — e.g. an .xep event file)")
    version = struct.unpack_from("<H", data, 2)[0]
    dsize, ssize = struct.unpack_from("<II", data, 4)
    count = struct.unpack_from("<H", data, 0xC)[0]
    if version != VERSION_STORED and version not in COMPRESSED_VERSIONS:
        raise XcError(f"unknown Xc version {version:#06x}")
    if count > 12:
        raise XcError(f"implausible sub-resource count {count}")
    tags = tuple(data[0x10 + i * 4:0x14 + i * 4].rstrip(b"\x00").decode("latin1")
                 for i in range(count))
    dir_offset = 0x40 if count else 0x10
    return XcHeader(version, dsize, ssize, count, tags, dir_offset)


# ---------------------------------------------------------------------------
# decoders (straight ports of the SLUS routines; see module docstring)
# ---------------------------------------------------------------------------

def _lzss_a(src: bytes, dsize: int) -> bytes:
    out = bytearray()
    p, n = 0, len(src)
    while len(out) < dsize and p < n:
        flags = src[p]
        p += 1
        for _ in range(8):
            if len(out) >= dsize or p >= n:
                break
            if flags & 0x80:
                out.append(src[p])
                p += 1
            else:
                b0, b1 = src[p], src[p + 1]
                p += 2
                dist = ((b0 & 0xF) << 8) | b1
                if dist == 0:
                    return bytes(out)
                length = (b0 >> 4) + 3
                s = len(out) - dist
                for i in range(length):
                    out.append(out[s + i])
            flags = (flags << 1) & 0xFF
    return bytes(out)


def _lzss_b(src: bytes, dsize: int) -> bytes:
    out = bytearray()
    p, n = 0, len(src)
    while len(out) < dsize and p < n:
        flags = src[p]
        p += 1
        for _ in range(8):
            if len(out) >= dsize or p >= n:
                break
            if flags & 0x80:
                out.append(src[p])
                p += 1
            else:
                b0 = src[p]
                if b0 == 0:
                    return bytes(out)
                dist = struct.unpack_from("<H", src, p + 1)[0] + 1
                p += 3
                s = len(out) - dist
                for i in range(b0 + 1):
                    out.append(out[s + i])
            flags = (flags << 1) & 0xFF
    return bytes(out)


def _lzss_c(src: bytes, dsize: int) -> bytes:
    out = bytearray()
    p, n = 0, len(src)
    while len(out) < dsize and p < n:
        flags = src[p]
        p += 1
        k = 7
        while k != -1:
            if len(out) >= dsize or p >= n:
                break
            if flags & 0x80:
                out.append(src[p])
                p += 1
            else:
                flags = (flags << 1) & 0xFF   # second flag bit: form select
                k -= 1
                if flags & 0x80:
                    b0 = src[p]
                    length = (b0 >> 4) + 3
                    dist = (((b0 & 0xF) << 8) | src[p + 1]) + 1
                    p += 2
                else:
                    b0 = src[p]
                    if b0 == 0:
                        return bytes(out)
                    length = b0 + 1
                    dist = struct.unpack_from("<H", src, p + 1)[0] + 1
                    p += 3
                s = len(out) - dist
                for i in range(length):
                    out.append(out[s + i])
            k -= 1
            flags = (flags << 1) & 0xFF
    return bytes(out)


_DECODERS = {
    0x0101: _lzss_a,
    0x0201: _lzss_a,
    0x0301: _lzss_b,
    0x0401: _lzss_c,
}


def normalize(data: bytes) -> bytes:
    """Return the package in stored (version 0x0001) form.

    A stored package comes back unchanged (same object). A compressed one
    is decoded; the returned header has version 0x0001 and the stored-size
    field rewritten, so ``parse_header`` / ``sub_resources`` / every
    existing txy parser read it exactly like a disc-stored file."""
    hdr = parse_header(data)
    if not hdr.compressed:
        return data
    payload = _DECODERS[hdr.version](data[hdr.dir_offset:], hdr.size_decompressed)
    if len(payload) != hdr.size_decompressed:
        raise XcError(f"decompressed {len(payload)} bytes, header says "
                      f"{hdr.size_decompressed} (version {hdr.version:#06x})")
    head = bytearray(data[:hdr.dir_offset])
    head[2:4] = struct.pack("<H", VERSION_STORED)
    head[8:12] = struct.pack("<I", hdr.size_decompressed)
    return bytes(head) + payload


def sub_resources(data: bytes) -> Dict[str, Tuple[int, int]]:
    """``tag -> (offset, size)`` of a STORED package (see ``normalize``).
    Offsets are from file start; a size-0 entry is an empty slot."""
    hdr = parse_header(data)
    if hdr.compressed:
        raise XcError("compressed package — call normalize() first")
    if hdr.dir_offset + hdr.count * 8 > len(data):
        raise XcError("truncated sub-resource directory")
    subs: Dict[str, Tuple[int, int]] = {}
    for i, tag in enumerate(hdr.tags):
        off, size = struct.unpack_from("<II", data, 0x40 + i * 8)
        subs[tag] = (off, size)
    return subs


# ---------------------------------------------------------------------------
# embedded txy records (effect libraries, pac bundles)
# ---------------------------------------------------------------------------

TXY_MAGIC = b"txy\x00"


def iter_txy_records(data: bytes) -> Iterable[Tuple[int, int, str]]:
    """Yield ``(record_offset, record_size, name)`` for every texture
    resource embedded in a blob that is not itself an MR package.

    ``.esd`` / ``.esp`` effect libraries and the ``esp`` member of ``.sme``
    bundles carry textures as free-standing records: a 0x40-byte
    pre-header ``{u32 total_size, u32 payload_size, u16, u16, u32 x2,
    char name[..]}`` ("hamon02.txy") followed by the same ``txy`` resource
    a ``.chr`` holds. ``record_offset`` is the pre-header, so
    ``chrtex.parse_txy(data, record_offset, record_size)`` reads it.

    The name string of a texture *reference* also ends in ``.txy\\0``; the
    size-consistency test below rejects those (and any other stray hit)."""
    n = len(data)
    i = data.find(TXY_MAGIC)
    while i >= 0:
        if i >= 0x40:
            total, payload = struct.unpack_from("<II", data, i - 0x40)
            if (0x20 < payload <= total <= n - (i - 0x40)
                    and total - payload <= 0x100):
                name = data[i - 0x2C:i].split(b"\x00")[0].decode("latin1", "replace")
                yield i - 0x40, total, name
                i = data.find(TXY_MAGIC, i - 0x40 + total)
                continue
        i = data.find(TXY_MAGIC, i + 4)


__all__ = [
    "XcError", "XcHeader", "VERSION_STORED", "COMPRESSED_VERSIONS",
    "is_xc", "parse_header", "normalize", "sub_resources",
    "iter_txy_records", "TXY_MAGIC",
]


def main() -> None:
    import argparse
    from pathlib import Path

    ap = argparse.ArgumentParser(
        description="Inspect or decompress a MonolithSoft Xc MR package (.chr/.map/.wpn/.sme)")
    ap.add_argument("package")
    ap.add_argument("-o", "--out", help="write the stored (decompressed) package here")
    a = ap.parse_args()
    data = Path(a.package).read_bytes()
    hdr = parse_header(data)
    print(f"version {hdr.version:#06x} ({'compressed' if hdr.compressed else 'stored'}) "
          f"payload {hdr.size_stored} -> {hdr.size_decompressed} bytes, "
          f"{hdr.count} sub-resources: {', '.join(hdr.tags) or '-'}")
    flat = normalize(data)
    for tag, (off, size) in sub_resources(flat).items():
        print(f"  {tag:4s} @ {off:#010x}  {size:>10d} bytes")
    if a.out:
        Path(a.out).write_bytes(flat)
        print(f"-> {a.out} ({len(flat)} bytes)")


if __name__ == "__main__":
    main()
