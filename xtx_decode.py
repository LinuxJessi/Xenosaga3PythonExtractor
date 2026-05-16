"""
xtx_decode.py — Decode MonolithSoft PsII ``.xtx`` textures into PNG.

Format (all little-endian):

    0x00  4   magic "XTX\\0"
    0x04  u32 total file size (in bytes)
    0x08  u32 sub-image count (always 1 in the Xenosaga III set)
    0x0C  u32 header size (always 0x10)
    0x10  u16 width
    0x12  u16 format / mip code (0x04 in kao/, 0x08 elsewhere; both decode as 32bpp RGBA)
    0x14  u32 height
    0x18  u32 reserved (0)
    0x1C  u32 flags
    0x20  u32 offset to pixel data (0x30 throughout the disc)
    0x24  …  reserved (zeros)
    0x30  pixels: width × height × 4 bytes, channel order R, G, B, A

PS2 alpha is 7-bit with 128 = fully opaque. To produce a PNG the rest of the
world reads as normal, alpha bytes are scaled ``min(a * 2, 255)``.

Trailing bytes after the pixel data (typically 32 bytes) are ignored — they
look like padding to a 16-byte boundary plus a small footer.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Tuple


class XTXError(Exception):
    """Raised when an XTX file does not match the expected layout."""


@dataclass(frozen=True)
class XTXHeader:
    total_size: int
    sub_count: int
    header_size: int
    width: int
    fmt: int
    height: int
    data_offset: int


def parse_header(data: bytes) -> XTXHeader:
    if len(data) < 0x30 or data[:4] != b"XTX\x00":
        raise XTXError("not an XTX file (missing magic)")
    total_size, sub_count, header_size = struct.unpack_from("<III", data, 4)
    width = struct.unpack_from("<H", data, 16)[0]
    fmt = struct.unpack_from("<H", data, 18)[0]
    height = struct.unpack_from("<I", data, 20)[0]
    data_offset = struct.unpack_from("<I", data, 32)[0]
    if data_offset < 0x30:
        raise XTXError(f"unexpected data_offset {data_offset:#x}")
    if width <= 0 or height <= 0:
        raise XTXError(f"bad dimensions {width}x{height}")
    if data_offset + width * height * 4 > len(data):
        raise XTXError(
            f"truncated pixel block: need {data_offset + width*height*4} bytes, have {len(data)}"
        )
    return XTXHeader(total_size, sub_count, header_size, width, fmt, height, data_offset)


def _scale_alpha(pixels: bytes) -> bytes:
    """Map 0-128 alpha into 0-255 — PS2 GS treats 128 as fully opaque."""
    out = bytearray(pixels)
    for i in range(3, len(out), 4):
        out[i] = min(out[i] * 2, 255)
    return bytes(out)


def decode(data: bytes) -> Tuple[XTXHeader, bytes]:
    """Return ``(header, rgba_pixels)``. ``rgba_pixels`` is alpha-scaled and
    ready to feed into ``PIL.Image.frombytes('RGBA', (w, h), ...)``."""
    hdr = parse_header(data)
    raw = data[hdr.data_offset : hdr.data_offset + hdr.width * hdr.height * 4]
    return hdr, _scale_alpha(raw)


def decode_to_png(data: bytes, out_path: Path) -> XTXHeader:
    """Decode and write a PNG. Imports PIL only here so the parser stays
    import-clean for callers that just want headers."""
    from PIL import Image

    hdr, pixels = decode(data)
    img = Image.frombytes("RGBA", (hdr.width, hdr.height), pixels)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)
    return hdr


@dataclass
class BatchStats:
    ok: int = 0
    err: int = 0
    errors: List[str] = None  # populated lazily

    def add_error(self, msg: str) -> None:
        if self.errors is None:
            self.errors = []
        self.errors.append(msg)


def convert_tree(
    dump_root: Path,
    out_root: Path,
    *,
    pattern: str = "*.xtx",
    progress_every: int = 100,
) -> BatchStats:
    """Walk ``dump_root`` for XTX files and mirror them under ``out_root`` as PNGs."""
    stats = BatchStats()
    done = 0
    for src in dump_root.rglob(pattern):
        if not src.is_file() or "_reports" in src.parts:
            continue
        rel = src.relative_to(dump_root).with_suffix(".png")
        dst = out_root / rel
        try:
            decode_to_png(src.read_bytes(), dst)
            stats.ok += 1
        except Exception as exc:
            stats.err += 1
            stats.add_error(f"{rel}: {exc}")
        done += 1
        if progress_every and done % progress_every == 0:
            print(f"[xtx] {done} files  ok={stats.ok} err={stats.err}", flush=True)
    return stats


__all__ = ["XTXError", "XTXHeader", "parse_header", "decode", "decode_to_png", "convert_tree", "BatchStats"]
