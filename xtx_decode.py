"""
xtx_decode.py — Decode MonolithSoft PsII ``.xtx`` textures into PNG.

Format (all little-endian):

    0x00  4   magic "XTX\\0"
    0x04  u32 total file size (in bytes)
    0x08  u32 sub-image count (always 1 in the Xenosaga III set)
    0x0C  u32 header size (always 0x10)
    0x10  u16 width
    0x12  u16 format (0x04 = linear 32bpp RGBA; 0x08 = swizzled 8bpp, see below)
    0x14  u32 height
    0x18  u32 reserved (0)
    0x1C  u32 flags ((payload_size >> 12) << 8 | 2 across the disc)
    0x20  u32 offset to pixel data (0x30 throughout the disc)
    0x24  …  reserved (zeros)
    0x30  payload: width × height × 4 bytes for BOTH formats

Format 0x04 (367 files per disc — kao/ portraits, most UI): the payload is
straight rows of R, G, B, A.

Format 0x08 (8 files per disc — mnu/ and mg1/ sheets): the payload is a GS
local-memory dump — a CT32 "canvas" of width × height words that actually
holds a PSMT8 8-bit-indexed image of (2·width) × (2·height) pixels, exactly
like Xenosaga I's XTX. The indices are recovered with the standard PS2
"unswizzle8" routine. The 256-colour CSM1 palettes are parked inside the
same canvas as 16×16 CT32 tiles (SLUS addresses them by GS block pointer,
which the file itself does not record). Palette selection is the scheme
that fixed the same problem in the Xenosaga I kit: every CLUT-looking tile
is a candidate; the BASE palette is the one whose whole-image render is
most spatially coherent (adjacent-pixel colour distance ÷ distance-16
colour distance — real art is smooth up close and varied at range, a wrong
palette renders dither noise, ≈1) with a stiff penalty for transparency
(a wrong palette must not win by hiding pixels behind alpha 0); then each
64-px block that still reads as noise under the base is repainted with the
candidate that renders it clearly smoother; the chosen CLUT tiles are
blanked from the output.

KNOWN LIMITATION (2026-09): the geometry is right but the COLOURS ARE NOT —
window0-2 render sepia, itemcap's icons grey. The ranking cannot separate
a monotone ramp palette from the true one (under a ramp every index map
looks smooth), so it settles on whichever ramp is parked in the canvas.
Treat the RGBA output of these 8 files as a preview; the grayscale
``*_index.png`` emitted alongside is the ground truth. A fix needs the
engine's own region→palette binding (planned: capture TEX0 CBP/CSA from
EE RAM with the menu open and ship it as a per-sheet table).

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


# ---------------------------------------------------------------------------
# fmt=0x08: PSMT8-in-CT32 canvas (GS memory dump), ported from the Xenosaga I
# extractor where the identical layout was cracked first.
# ---------------------------------------------------------------------------

def _unswizzle8(canvas: bytes, canvas_w: int, out_w: int, out_h: int) -> bytes:
    """Recover linear PSMT8 indices from a CT32-arranged canvas.

    ``canvas_w`` is the canvas width in CT32 words; the PSMT8 image is twice
    the canvas size in each axis. This is the widely shared PS2 "unswizzle8"
    routine (same block/column tables as the GS spec).
    """
    tw = canvas_w * 2
    idx = bytearray(out_w * out_h)
    for y in range(out_h):
        block_row = (y & ~0xF) * tw
        swap_selector = (((y + 2) >> 2) & 1) * 4
        col_row = ((((y & ~3) >> 1) + (y & 1)) & 7) * tw * 2
        byte_y = (y >> 1) & 1
        drow = y * out_w
        for x in range(out_w):
            src = (block_row + (x & ~0xF) * 2 + col_row
                   + ((x + swap_selector) & 7) * 4 + byte_y + ((x >> 2) & 2))
            if src < len(canvas):
                idx[drow + x] = canvas[src]
    return bytes(idx)


def _clut_at(canvas: bytes, canvas_w: int, palx: int, paly: int) -> List[bytes]:
    """Read a 256-entry CSM1 palette from a 16×16 CT32 tile at (palx, paly)."""
    pal = []
    for ey in range(16):
        row = ((paly + ey) * canvas_w + palx) * 4
        for ex in range(16):
            p = canvas[row + ex * 4 : row + ex * 4 + 4]
            pal.append(bytes((p[0], p[1], p[2], min(p[3] * 2, 255))))
    for g in range(8):  # CSM1 storage order -> logical order
        for j in range(8):
            k, m = g * 32 + 8 + j, g * 32 + 16 + j
            pal[k], pal[m] = pal[m], pal[k]
    return pal


def _clut_tile_like(canvas: bytes, canvas_w: int, px: int, py: int) -> bool:
    """Does the 16×16 tile at (px, py) look like CLUT data? (every raw alpha
    ≤ 0x80 — GS 7-bit — and a rich colour count)."""
    distinct = set()
    for ey in range(16):
        row = ((py + ey) * canvas_w + px) * 4
        for ex in range(16):
            r, g, b, a = canvas[row + ex * 4 : row + ex * 4 + 4]
            if a > 0x80:
                return False
            distinct.add((r, g, b))
    return len(distinct) >= 64


def _scan_for_clut(canvas: bytes, canvas_w: int, canvas_h: int
                   ) -> Iterable[Tuple[List[bytes], Tuple[int, int]]]:
    """Yield ``(palette, (tile_x, tile_y))`` for every block-aligned 16×16
    tile that looks like a CLUT, bottom-right first (the parking
    convention), then the finer 8-px grid (CBPs address half blocks)."""
    seen = set()
    spots = [(x, y) for y in range(canvas_h - 16, -1, -16)
             for x in range(canvas_w - 16, -1, -16)]
    spots += [(x, y) for y in range(canvas_h - 16, -1, -8)
              for x in range(canvas_w - 16, -1, -8) if x % 16 or y % 16]
    for px, py in spots:
        if (px, py) in seen:
            continue
        seen.add((px, py))
        if _clut_tile_like(canvas, canvas_w, px, py):
            yield _clut_at(canvas, canvas_w, px, py), (px, py)


def _region_noise(idx: bytes, W: int, pal: List[bytes],
                  u0: int, u1: int, v0: int, v1: int) -> Tuple[float, float]:
    """(coherence ratio, opaque fraction) of a region rendered under a
    palette — mean L1 RGB distance of horizontally adjacent opaque pixels
    divided by the same for pixels 16 apart (rows sampled). ≪1 = real art,
    ≈1 = dither noise (wrong palette), inf = hidden or flat."""
    adj = adjn = far = farn = opaque = count = 0
    for v in range(v0, v1, 2):
        irow = v * W
        row = [pal[idx[irow + u]] for u in range(u0, u1)]
        n = len(row)
        for i, p in enumerate(row):
            count += 1
            if not p[3]:
                continue
            opaque += 1
            if i + 1 < n and row[i + 1][3]:
                q = row[i + 1]
                adj += abs(p[0] - q[0]) + abs(p[1] - q[1]) + abs(p[2] - q[2])
                adjn += 1
            if i + 16 < n and row[i + 16][3]:
                q = row[i + 16]
                far += abs(p[0] - q[0]) + abs(p[1] - q[1]) + abs(p[2] - q[2])
                farn += 1
    opq = opaque / count if count else 0.0
    if not count or opq < 0.3 or not adjn or not farn:
        return float("inf"), opq
    fbar = far / farn
    if fbar < 2.0:
        return float("inf"), opq
    return (adj / adjn) / fbar, opq


def _candidate_score(idx: bytes, W: int, H: int, pal: List[bytes]) -> float:
    """Whole-image score of a BASE-palette candidate: coherence ratio plus
    a stiff transparency penalty. Lower is better."""
    ratio, opq = _region_noise(idx, W, pal, 0, W, 0, H)
    return ratio + max(0.0, 0.95 - opq) * 2.0


def select_palettes(canvas: bytes, canvas_w: int, canvas_h: int,
                    idx: bytes, out_w: int, out_h: int
                    ) -> Tuple[List[bytes] | None, List[List[bytes]], List[Tuple[int, int]]]:
    """(base palette or None, all candidate palettes, tiles chosen).
    See the module docstring for the ranking."""
    cands = [(pal, xy) for pal, xy in _scan_for_clut(canvas, canvas_w, canvas_h)]
    # de-duplicate identical palettes (colour-variant strips repeat entries)
    uniq: List[Tuple[List[bytes], Tuple[int, int]]] = []
    for pal, xy in cands:
        if all(pal != p for p, _ in uniq):
            uniq.append((pal, xy))
    if not uniq:
        return None, [], []
    best, base, base_xy = float("inf"), None, None
    for pal, xy in uniq[:40]:
        s = _candidate_score(idx, out_w, out_h, pal)
        if s < best:
            best, base, base_xy = s, pal, xy
    if base is None or best > 1.2:
        return None, [p for p, _ in uniq], []
    return base, [p for p, _ in uniq], [base_xy]


def decode_indexed(data: bytes) -> Tuple[XTXHeader, int, int, bytes, bytes]:
    """Decode a fmt=0x08 file. Returns ``(header, out_w, out_h, indices,
    rgba)`` where ``indices`` is the raw PSMT8 index map (ground truth) and
    ``rgba`` is the coherence-ranked palette render (grayscale identity when
    no palette tile is found)."""
    hdr = parse_header(data)
    canvas = data[hdr.data_offset : hdr.data_offset + hdr.width * hdr.height * 4]
    out_w, out_h = hdr.width * 2, hdr.height * 2
    W, H = out_w, out_h
    idx = _unswizzle8(canvas, hdr.width, out_w, out_h)
    base, pals, used = select_palettes(canvas, hdr.width, hdr.height, idx, W, H)
    lut = base if base else [bytes((i, i, i, 255)) for i in range(256)]
    rgba = bytearray(out_w * out_h * 4)
    for i, ib in enumerate(idx):
        rgba[i * 4 : i * 4 + 4] = lut[ib]

    def paint(pal, u0, u1, v0, v1):
        for v in range(v0, v1):
            drow = v * W * 4
            irow = v * W
            for u in range(u0, u1):
                rgba[drow + u * 4 : drow + u * 4 + 4] = pal[idx[irow + u]]

    # per-64px-block rescue: where the base palette renders dither noise,
    # another parked CLUT that renders the block clearly smoother wins
    if base is not None and len(pals) > 1:
        pal_xy = {}
        for pal, xy in _scan_for_clut(canvas, hdr.width, hdr.height):
            key = bytes(b"".join(pal))
            pal_xy.setdefault(key, xy)
        for v0 in range(0, H, 64):
            v1 = min(H, v0 + 64)
            for u0 in range(0, W, 64):
                u1 = min(W, u0 + 64)
                bn, _ = _region_noise(idx, W, base, u0, u1, v0, v1)
                if bn == float("inf") or bn < 0.75:
                    continue
                best_pal, best_n = None, bn
                for pal in pals[:40]:
                    if pal == base:
                        continue
                    n, _ = _region_noise(idx, W, pal, u0, u1, v0, v1)
                    if n < best_n:
                        best_pal, best_n = pal, n
                if best_pal is not None and best_n < bn * 0.5:
                    paint(best_pal, u0, u1, v0, v1)
                    xy = pal_xy.get(bytes(b"".join(best_pal)))
                    if xy and xy not in used:
                        used.append(xy)

    # CLUT tiles are palette data, not art: blank the tiles actually used
    for tx, ty in used:
        px0, py0 = tx * 2, ty * 2
        for y in range(max(0, py0), min(H, py0 + 32)):
            drow = y * W * 4
            for x in range(max(0, px0), min(W, px0 + 32)):
                rgba[drow + x * 4 : drow + x * 4 + 4] = b"\x00\x00\x00\x00"
    return hdr, out_w, out_h, idx, bytes(rgba)


def decode(data: bytes) -> Tuple[XTXHeader, bytes]:
    """Return ``(header, rgba_pixels)`` for a linear (fmt=0x04) file.
    ``rgba_pixels`` is alpha-scaled and ready to feed into
    ``PIL.Image.frombytes('RGBA', (w, h), ...)``."""
    hdr = parse_header(data)
    raw = data[hdr.data_offset : hdr.data_offset + hdr.width * hdr.height * 4]
    return hdr, _scale_alpha(raw)


def decode_to_png(data: bytes, out_path: Path) -> XTXHeader:
    """Decode and write a PNG (plus a ``*_index.png`` ground-truth map for
    swizzled files). Imports PIL only here so the parser stays import-clean
    for callers that just want headers."""
    from PIL import Image

    hdr = parse_header(data)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if hdr.fmt == 0x08:
        hdr, out_w, out_h, idx, rgba = decode_indexed(data)
        Image.frombytes("RGBA", (out_w, out_h), rgba).save(out_path)
        index_path = out_path.with_name(out_path.stem + "_index.png")
        Image.frombytes("L", (out_w, out_h), idx).save(index_path)
        return hdr
    hdr, pixels = decode(data)
    Image.frombytes("RGBA", (hdr.width, hdr.height), pixels).save(out_path)
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


__all__ = [
    "XTXError",
    "XTXHeader",
    "parse_header",
    "decode",
    "decode_indexed",
    "decode_to_png",
    "convert_tree",
    "BatchStats",
]
