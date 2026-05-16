"""
tm2_decode.py — Decode Sony PS2 TIM2 (``.tm2``) textures to PNG.

The four TIM2 files in Xenosaga III are all 32-bpp RGBA with no palette
(chapter-select background + three episode logos). This decoder only
supports that subset; other bpp codes raise :class:`TM2Error`.

Format (little-endian):

    0x00  4   magic "TIM2"
    0x04  u8  version
    0x05  u8  format code
    0x06  u16 picture count
    0x08  …   reserved/zeros up to 0x10
    0x10  picture header
        +0x00  u32 total size
        +0x04  u32 palette size
        +0x08  u32 image (pixel) size
        +0x0C  u16 header size (usually 0x30)
        +0x0E  u16 colour count (0 when no palette)
        +0x10  u8  picture format
        +0x11  u8  mip count
        +0x12  u8  CLUT format
        +0x13  u8  bpp code (1=16bpp, 2=24bpp, 3=32bpp, 4=4bpp idx, 5=8bpp idx)
        +0x14  u16 width
        +0x16  u16 height
        ...
    0x10 + header_size: pixel data
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path
from typing import List


class TM2Error(Exception):
    """Raised when a TM2 file does not match the supported layout."""


@dataclass(frozen=True)
class TM2Header:
    width: int
    height: int
    bpp_code: int
    header_size: int
    image_size: int


def parse_header(data: bytes) -> TM2Header:
    if len(data) < 0x30 or data[:4] != b"TIM2":
        raise TM2Error("not a TIM2 file (missing magic)")
    ph = 0x10
    image_size = struct.unpack_from("<I", data, ph + 8)[0]
    header_size = struct.unpack_from("<H", data, ph + 12)[0]
    bpp_code = data[ph + 19]
    width = struct.unpack_from("<H", data, ph + 20)[0]
    height = struct.unpack_from("<H", data, ph + 22)[0]
    if bpp_code != 3:
        raise TM2Error(
            f"bpp_code {bpp_code} not supported by this decoder (expected 3=32bpp RGBA)"
        )
    if width <= 0 or height <= 0:
        raise TM2Error(f"bad dimensions {width}x{height}")
    return TM2Header(width, height, bpp_code, header_size, image_size)


def _scale_alpha(pixels: bytes) -> bytes:
    """PS2 alpha is 7-bit; 128 = fully opaque. Scale to PC convention."""
    out = bytearray(pixels)
    for i in range(3, len(out), 4):
        out[i] = min(out[i] * 2, 255)
    return bytes(out)


def decode(data: bytes):
    hdr = parse_header(data)
    data_off = 0x10 + hdr.header_size
    raw = data[data_off : data_off + hdr.width * hdr.height * 4]
    if len(raw) != hdr.width * hdr.height * 4:
        raise TM2Error(
            f"truncated pixel block: need {hdr.width*hdr.height*4} bytes, have {len(raw)}"
        )
    return hdr, _scale_alpha(raw)


def decode_to_png(data: bytes, out_path: Path) -> TM2Header:
    from PIL import Image

    hdr, rgba = decode(data)
    img = Image.frombytes("RGBA", (hdr.width, hdr.height), rgba)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)
    return hdr


@dataclass
class BatchStats:
    ok: int = 0
    err: int = 0
    errors: List[str] = None

    def add_error(self, msg: str) -> None:
        if self.errors is None:
            self.errors = []
        self.errors.append(msg)


def convert_tree(dump_root: Path, out_root: Path, pattern: str = "*.tm2") -> BatchStats:
    """Walk ``dump_root`` for TIM2 files and mirror them under ``out_root`` as PNGs."""
    stats = BatchStats()
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
    return stats


__all__ = ["TM2Error", "TM2Header", "parse_header", "decode", "decode_to_png", "convert_tree", "BatchStats"]
