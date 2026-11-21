"""xtx_encode.py — PNG -> ``.xtx``: the inverse of xtx_decode.py, same size, byte-exact on a no-op.

New for this kit (2026-11-20). xtx_decode.py (read only here) documents the
container; this module writes it back for the two formats on the discs:

* fmt 0x08 — every localized sheet (mnu\\xx\\window0/1/2.xtx, mnu\\xx\\titleobj.xtx,
  mg1\\xx\\picture.xtx) and mnu\\ctrl/itemcap.xtx: a CT32 canvas of W x H words that
  holds a PSMT8 image of 2W x 2H indices ("unswizzle8") plus the 256-colour CSM1
  CLUT tiles parked in the same canvas as 16x16 CT32 tiles;
* fmt 0x04 — linear RGBA (kao\\ portraits), alpha 0..128 on disc.

GS PACKET (found here, 2026-11-20): the "data offset" 0x30 points at a 32-byte
GS upload packet, not at pixels. Bytes 0x30-0x3B are zero (DMA tag), 0x3C is a VIF
DIRECT code (0x50 << 24 | qword count = W*H*4/16 + 1) and 0x40-0x4F a GIF tag in
IMAGE mode (NLOOP = W*H*4/16, EOP); the pixels start at 0x50 and the file is exactly
0x50 + W*H*4 bytes. Checked on all 375 XTX files of Disc 1 (367 fmt 4, 8 fmt 8).
xtx_decode.py read its canvas from 0x30 (8 words early) until it was fixed the
same day; it now validates the packet and reads from 0x50 too, so both modules
see the same canvas and statfont's texel coordinates and CLUT pointers land
exactly on the sheet. ``*_index.png`` files written by the old decoder are
shifted 16 px right with row wrap and must be re-exported before import.

The model (``Sheet``) keeps the 0x30-byte header, the packet, the canvas and any
trailing bytes verbatim, so ``Sheet.parse(b).to_bytes() == b`` and re-encoding the
unmodified index map gives the original file byte for byte. The PSMT8 <-> CT32
mapping is the decoder's own unswizzle8 formula, which is a bijection over the
whole canvas for every fmt-0x08 sheet on the discs (512x128, 384x128, 128x128,
320x256, 72x128 words checked; mnu\\segcap.xtx, 246 words wide, is not, and is
refused).

Import modes (``import_png``):

* an 8-bit index PNG (mode "L" like the decoder's ``*_index.png``, or mode "P"
  as ``xtx-export`` writes it): the pixel values ARE the indices;
* an RGBA PNG plus the export sidecar (``<name>.json``, written by
  ``export_sheet``): pixels that still equal the exported render keep their
  original index (palettes repeat colours, so this is the only exact inverse);
  changed pixels are quantized to the nearest entry of the palette the sidecar
  binds to that pixel ("existing" palette, the default), or, with
  ``palette="rebuild"`` and a sheet whose editable pixels all use ONE palette
  tile, that tile is rebuilt from the edited image (median-cut, <= 256
  colours) and every pixel is re-indexed against it.

Pixels whose canvas bytes belong to a protected CLUT tile (the tiles the plan
uses plus any engine-bound tiles passed in ``bindings``) are never taken from
the PNG; edits that land there are counted and reported.

Palette plan: which CLUT colours a pixel. The file does not record it (the
engine sets CBP per draw). The plan is xtx_decode.plan_palettes verbatim (the
ranked plan, then the engine's own draw rectangles and CBPs from
engine_palettes: the executable's sprite tables and draw functions, OV01, OV04;
so the export render equals xtx_decode's RGBA) followed by ``bindings``
(statfont.BINDINGS: the HUD letter and digit cells, CBP 0x308 / 0x3c8 / 0x30c,
which the engine rectangles already contain). ``cbp_xy`` turns a GS CBP into
canvas coordinates (TBW 8, CT32 block order). Outside the engine rectangles the
plan is a heuristic (see xtx_decode, "Colour status"); the index map is exact
either way.

Commands (``add_commands``):

    xtx-export --in F.xtx --out DIR [--bind statfont]
        DIR/F.png (render), DIR/F_index.png (mode P, render palette), DIR/F.json
    xtx-encode --in F.xtx --png EDIT.png --out NEW.xtx [--json F.json] [--palette existing|rebuild]
"""
from __future__ import annotations

import hashlib
import json
import struct
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
from PIL import Image

import xtx_decode as X

HEADER = 0x30          # XTX header; the GS packet follows
PIXELS = 0x50          # first pixel byte (after the 32-byte DMA/VIF/GIF packet)
FMT_LINEAR, FMT_PSMT8 = 0x04, 0x08

# CT32 block order inside a 64x32-word page (GS manual, PSMCT32)
_BLK32 = ((0, 1, 4, 5, 16, 17, 20, 21), (2, 3, 6, 7, 18, 19, 22, 23),
          (8, 9, 12, 13, 24, 25, 28, 29), (10, 11, 14, 15, 26, 27, 30, 31))
_BLK32_XY = {b: (c * 8, r * 8) for r, row in enumerate(_BLK32) for c, b in enumerate(row)}
_CSM1_SWAP = [(g * 32 + 8 + j, g * 32 + 16 + j) for g in range(8) for j in range(8)]


class XTXEncodeError(ValueError):
    pass


def cbp_xy(cbp: int, tbw: int = 8) -> Tuple[int, int]:
    """Canvas word coordinates of a GS block pointer, relative to the sheet's base
    page, for a buffer ``tbw`` pages (64 words) wide. The window sheets sit in a
    TBW-8 buffer on both US (512 words) and JP (384 words) builds: the CLUT tiles
    at CBP 0x30c / 0x328 / 0x330 are byte-identical at the same (x, y) on both."""
    page, blk = divmod(cbp, 32)
    py, px = divmod(page, tbw)
    bx, by = _BLK32_XY[blk]
    return px * 64 + bx, py * 32 + by


def check_packet(data: bytes, w: int, h: int) -> None:
    """The 32-byte upload packet at 0x30: zero DMA tag, VIF DIRECT of W*H*4/16 + 1
    qwords, GIF tag IMAGE with NLOOP W*H*4/16 and EOP."""
    q = w * h * 4 // 16
    vif = struct.unpack_from("<I", data, 0x3C)[0]
    gif = struct.unpack_from("<Q", data, 0x40)[0]
    if (data[0x30:0x3C] != bytes(12) or vif != (0x50 << 24 | (q + 1))
            or gif & 0x7FFF != q or not gif >> 15 & 1 or gif >> 58 & 3 != 2):
        raise XTXEncodeError(f"unexpected GS packet at 0x30 ({data[0x30:0x50].hex()})")


def make_packet(w: int, h: int) -> bytes:
    q = w * h * 4 // 16
    return bytes(12) + struct.pack("<I", 0x50 << 24 | (q + 1)) + struct.pack("<QQ", q | 1 << 15 | 2 << 58, 0)


_OFFS_CACHE: Dict[Tuple[int, int], np.ndarray] = {}


def swizzle_offsets(cw: int, ch: int) -> np.ndarray:
    """(2*ch, 2*cw) array: canvas byte offset of each PSMT8 index (xtx_decode._unswizzle8)."""
    key = (cw, ch)
    if key not in _OFFS_CACHE:
        tw = cw * 2
        y = np.arange(2 * ch, dtype=np.int64)[:, None]
        x = np.arange(2 * cw, dtype=np.int64)[None, :]
        off = ((y & ~0xF) * tw + (x & ~0xF) * 2
               + ((((y & ~3) >> 1) + (y & 1)) & 7) * tw * 2
               + ((x + (((y + 2) >> 2) & 1) * 4) & 7) * 4 + ((y >> 1) & 1) + ((x >> 2) & 2))
        _OFFS_CACHE[key] = off
    return _OFFS_CACHE[key]


def is_bijective(cw: int, ch: int) -> bool:
    off = swizzle_offsets(cw, ch)
    n = cw * ch * 4
    return int(off.max()) < n and np.unique(off).size == n


@dataclass
class Sheet:
    """One XTX file, editable. ``canvas`` is the payload (W*H*4 bytes)."""
    header: bytes
    fmt: int
    cw: int
    ch: int
    canvas: bytearray
    trailer: bytes
    packet: bytes = b""

    @classmethod
    def parse(cls, data: bytes) -> "Sheet":
        if len(data) < PIXELS or data[:4] != b"XTX\x00":
            raise XTXEncodeError("not an XTX file")
        w = struct.unpack_from("<H", data, 0x10)[0]
        fmt = struct.unpack_from("<H", data, 0x12)[0]
        h = struct.unpack_from("<I", data, 0x14)[0]
        if fmt not in (FMT_LINEAR, FMT_PSMT8):
            raise XTXEncodeError(f"fmt {fmt:#x} is not one this encoder writes")
        if struct.unpack_from("<I", data, 0x20)[0] != HEADER:
            raise XTXEncodeError("data offset != 0x30")
        n = w * h * 4
        check_packet(data, w, h)
        if len(data) < PIXELS + n:
            raise XTXEncodeError(f"truncated: {len(data)} < {PIXELS + n}")
        return cls(bytes(data[:HEADER]), fmt, w, h, bytearray(data[PIXELS:PIXELS + n]),
                   bytes(data[PIXELS + n:]), bytes(data[HEADER:PIXELS]))

    def to_bytes(self) -> bytes:
        return self.header + self.packet + bytes(self.canvas) + self.trailer

    # ---- PSMT8 view
    @property
    def size(self) -> Tuple[int, int]:
        """(width, height) of the picture: indices for fmt 8, pixels for fmt 4."""
        return (self.cw * 2, self.ch * 2) if self.fmt == FMT_PSMT8 else (self.cw, self.ch)

    def _need8(self):
        if self.fmt != FMT_PSMT8:
            raise XTXEncodeError("not a PSMT8 (fmt 0x08) sheet")
        if not is_bijective(self.cw, self.ch):
            raise XTXEncodeError(f"{self.cw}x{self.ch}-word canvas: the PSMT8 view does not "
                                 "cover the canvas one to one; not encodable")

    def indices(self) -> np.ndarray:
        self._need8()
        return np.frombuffer(bytes(self.canvas), np.uint8)[swizzle_offsets(self.cw, self.ch)]

    def set_indices(self, idx: np.ndarray, mask: Optional[np.ndarray] = None) -> None:
        """Write an index map (H, W) back; ``mask`` limits the write to True pixels."""
        self._need8()
        off = swizzle_offsets(self.cw, self.ch)
        if idx.shape != off.shape:
            raise XTXEncodeError(f"index map {idx.shape[::-1]} != sheet {off.shape[::-1]}")
        buf = np.frombuffer(self.canvas, np.uint8)
        if mask is None:
            buf[off.ravel()] = idx.ravel().astype(np.uint8)
        else:
            buf[off[mask]] = idx[mask].astype(np.uint8)

    # ---- CLUT tiles (raw GS alpha 0..0x80, logical order)
    def clut_raw(self, x: int, y: int) -> List[Tuple[int, int, int, int]]:
        if x < 0 or y < 0 or x + 16 > self.cw or y + 16 > self.ch:
            raise XTXEncodeError(f"CLUT tile ({x},{y}) outside the {self.cw}x{self.ch} canvas")
        pal = []
        for ey in range(16):
            row = ((y + ey) * self.cw + x) * 4
            for ex in range(16):
                pal.append(tuple(self.canvas[row + ex * 4:row + ex * 4 + 4]))
        for k, m in _CSM1_SWAP:
            pal[k], pal[m] = pal[m], pal[k]
        return pal

    def clut(self, x: int, y: int) -> List[bytes]:
        """Display palette (alpha scaled like xtx_decode._clut_at)."""
        return [bytes((r, g, b, min(a * 2, 255))) for r, g, b, a in self.clut_raw(x, y)]

    def put_clut_raw(self, x: int, y: int, pal: Sequence[Tuple[int, int, int, int]]) -> None:
        pal = list(pal)
        if len(pal) != 256:
            raise XTXEncodeError("a CSM1 CLUT has 256 entries")
        for k, m in _CSM1_SWAP:
            pal[k], pal[m] = pal[m], pal[k]
        for ey in range(16):
            row = ((y + ey) * self.cw + x) * 4
            for ex in range(16):
                self.canvas[row + ex * 4:row + ex * 4 + 4] = bytes(pal[ey * 16 + ex])

    def tile_pixel_mask(self, tiles: Sequence[Tuple[int, int]]) -> np.ndarray:
        """Index-map pixels whose canvas bytes lie in the given 16x16 tiles."""
        cmask = np.zeros((self.ch, self.cw), bool)
        for x, y in tiles:
            cmask[y:y + 16, x:x + 16] = True
        bytemask = np.repeat(cmask.ravel(), 4)
        return bytemask[swizzle_offsets(self.cw, self.ch)]

    # ---- linear RGBA (fmt 4)
    def rgba_linear(self) -> np.ndarray:
        a = np.frombuffer(bytes(self.canvas), np.uint8).reshape(self.ch, self.cw, 4).copy()
        a[..., 3] = np.minimum(a[..., 3].astype(np.int32) * 2, 255)
        return a

    def set_rgba_linear(self, rgba: np.ndarray) -> None:
        """Inverse of rgba_linear for every byte the decoder can produce (raw alpha
        0..0x80; a raw alpha above 0x80 would decode to 255 and come back as 0x80)."""
        if rgba.shape != (self.ch, self.cw, 4):
            raise XTXEncodeError(f"image {rgba.shape[1]}x{rgba.shape[0]} != sheet {self.cw}x{self.ch}")
        old = np.frombuffer(bytes(self.canvas), np.uint8).reshape(self.ch, self.cw, 4)
        out = rgba.astype(np.uint8).copy()
        a = rgba[..., 3].astype(np.int32)
        raw = np.where(a >= 255, 0x80, (a + 1) // 2)
        same = np.minimum(old[..., 3].astype(np.int32) * 2, 255) == a
        out[..., 3] = np.where(same, old[..., 3], raw).astype(np.uint8)
        self.canvas[:] = out.tobytes()


# --------------------------------------------------------------- palette plan

@dataclass
class Plan:
    """Which palette tile renders which pixel. ``base`` covers everything, then
    each rect (x0, y0, x1, y1, (tx, ty)) overrides it, in order. ``protect`` are
    CLUT tiles whose canvas bytes must not be repainted. ``base=None``: grayscale."""
    base: Optional[Tuple[int, int]] = None
    rects: List[Tuple[int, int, int, int, Tuple[int, int]]] = field(default_factory=list)
    protect: List[Tuple[int, int]] = field(default_factory=list)

    def to_json(self) -> dict:
        return {"base": list(self.base) if self.base else None,
                "rects": [[x0, y0, x1, y1, t[0], t[1]] for x0, y0, x1, y1, t in self.rects],
                "protect": [list(t) for t in self.protect]}

    @classmethod
    def from_json(cls, j: dict) -> "Plan":
        return cls(tuple(j["base"]) if j.get("base") else None,
                   [(r[0], r[1], r[2], r[3], (r[4], r[5])) for r in j.get("rects", [])],
                   [tuple(t) for t in j.get("protect", [])])

    def tiles(self) -> List[Tuple[int, int]]:
        out = [self.base] if self.base else []
        for *_r, t in self.rects:
            if t not in out:
                out.append(t)
        return out

    def tile_map(self, w: int, h: int) -> Tuple[np.ndarray, List[Tuple[int, int]]]:
        """(H, W) int map of indexes into ``tiles()`` (-1 = grayscale identity)."""
        tiles = self.tiles()
        m = np.full((h, w), tiles.index(self.base) if self.base else -1, np.int32)
        for x0, y0, x1, y1, t in self.rects:
            m[y0:y1, x0:x1] = tiles.index(t)
        return m, tiles


def auto_plan(sheet: Sheet, bindings: Sequence[Tuple[int, int, int, int, Tuple[int, int]]] = (),
              name: str = "") -> Plan:
    """xtx_decode.plan_palettes (ranked plan, then the engine's own draw bindings
    from engine_palettes), then ``bindings``. ``name``: the file name or disc path
    (tells the US and JP minigame sheets apart when their CLUTs were edited)."""
    sheet._need8()
    cv, cw, ch = bytes(sheet.canvas), sheet.cw, sheet.ch
    W, H = cw * 2, ch * 2
    base, rects, _pals = X.plan_palettes(cv, cw, ch, sheet.indices().tobytes(), W, H, name)
    plan = Plan(base=tuple(base) if base else None,
                rects=[(u0, v0, u1, v1, tuple(t)) for u0, v0, u1, v1, t in rects])
    for x0, y0, x1, y1, t in bindings:
        if x1 <= W and y1 <= H and t[0] + 16 <= cw and t[1] + 16 <= ch:
            plan.rects.append((x0, y0, x1, y1, tuple(t)))
    plan.protect = plan.tiles()
    return plan


def render(sheet: Sheet, plan: Plan, blank_tiles: bool = True) -> np.ndarray:
    """(H, W, 4) RGBA of a PSMT8 sheet under a plan (blank_tiles: the plan's
    CLUT tiles drawn transparent, as xtx_decode does for the tiles it used)."""
    idx = sheet.indices()
    h, w = idx.shape
    m, tiles = plan.tile_map(w, h)
    out = np.zeros((h, w, 4), np.uint8)
    gray = m < 0
    out[gray] = np.stack([idx[gray]] * 3 + [np.full(idx[gray].shape, 255, np.uint8)], -1)
    for k, t in enumerate(tiles):
        lut = np.frombuffer(b"".join(sheet.clut(*t)), np.uint8).reshape(256, 4)
        sel = m == k
        out[sel] = lut[idx[sel]]
    if blank_tiles and plan.protect:
        out[sheet.tile_pixel_mask(plan.protect)] = 0
    return out


# ------------------------------------------------------------------- export

def export_sheet(data: bytes, out_dir: Path, stem: str,
                 bindings: Sequence = (), source: str = "") -> dict:
    """Write ``stem.png`` (render), ``stem_index.png`` (mode P: indices with the
    base palette) and ``stem.json`` (plan + sha1). Returns the sidecar dict."""
    out_dir.mkdir(parents=True, exist_ok=True)
    sheet = Sheet.parse(data)
    side = {"source": source, "sha1": hashlib.sha1(data).hexdigest(), "fmt": sheet.fmt,
            "size": list(sheet.size)}
    if sheet.fmt == FMT_LINEAR:
        Image.fromarray(sheet.rgba_linear(), "RGBA").save(out_dir / f"{stem}.png")
    else:
        plan = auto_plan(sheet, bindings, source or stem)
        Image.fromarray(render(sheet, plan), "RGBA").save(out_dir / f"{stem}.png")
        p = Image.fromarray(sheet.indices(), "P")
        lut = sheet.clut(*plan.base) if plan.base else [bytes((i, i, i, 255)) for i in range(256)]
        p.putpalette(b"".join(c[:3] for c in lut), "RGB")
        p.save(out_dir / f"{stem}_index.png")
        side["plan"] = plan.to_json()
    (out_dir / f"{stem}.json").write_text(json.dumps(side, indent=1))
    return side


# ------------------------------------------------------------------- import

@dataclass
class ImportReport:
    changed: int = 0             # pixels that differ from the original
    quantized: int = 0           # pixels re-indexed by nearest colour
    ignored_protected: int = 0   # edits inside protected CLUT tiles (dropped)
    max_error: float = 0.0       # worst RGBA distance of a quantized pixel
    mode: str = ""

    def line(self) -> str:
        return (f"{self.mode}: {self.changed} px changed, {self.quantized} quantized "
                f"(worst RGBA distance {self.max_error:.1f}), "
                f"{self.ignored_protected} edits inside CLUT tiles ignored")


def _nearest(lut: np.ndarray, px: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """Nearest LUT entry (RGBA euclidean; fully transparent pixels prefer alpha-0 entries)."""
    d = ((px[:, None, :].astype(np.int32) - lut[None, :, :].astype(np.int32)) ** 2).sum(-1)
    k = d.argmin(1)
    return k, np.sqrt(d[np.arange(len(k)), k])


def _load_png(png) -> Image.Image:
    return png if isinstance(png, Image.Image) else Image.open(png)


def import_png(data: bytes, png, sidecar: Optional[dict] = None,
               palette: str = "existing") -> Tuple[bytes, ImportReport]:
    """Re-encode ``data`` (an .xtx) with the picture in ``png`` (path or PIL image).
    Same size always; see the module docstring for the modes."""
    sheet = Sheet.parse(data)
    im = _load_png(png)
    rep = ImportReport()
    w, h = sheet.size
    if im.size != (w, h):
        raise XTXEncodeError(f"picture is {im.size[0]}x{im.size[1]}, the sheet is {w}x{h}")
    if sheet.fmt == FMT_LINEAR:
        new = np.array(im.convert("RGBA"))
        old = sheet.rgba_linear()
        rep.changed = int((new != old).any(-1).sum())
        rep.mode = "linear"
        sheet.set_rgba_linear(new)
        return sheet.to_bytes(), rep

    plan = Plan.from_json(sidecar["plan"]) if sidecar and "plan" in sidecar else None
    old_idx = sheet.indices()
    if im.mode in ("L", "P"):
        new_idx = np.array(im, np.uint8)
        prot = sheet.tile_pixel_mask(plan.protect) if plan else np.zeros_like(new_idx, bool)
        diff = new_idx != old_idx
        rep.ignored_protected = int((diff & prot).sum())
        rep.changed = int((diff & ~prot).sum())
        rep.mode = "index"
        sheet.set_indices(new_idx, ~prot)
        return sheet.to_bytes(), rep

    if plan is None:
        raise XTXEncodeError("an RGBA picture of a PSMT8 sheet needs the export sidecar "
                             "(.json) to know which palette each pixel uses; or import "
                             "the index PNG instead")
    if sidecar.get("sha1") and sidecar["sha1"] != hashlib.sha1(data).hexdigest():
        raise XTXEncodeError("the sidecar was exported from a different file (sha1 mismatch)")
    new = np.array(im.convert("RGBA"))
    ref = render(sheet, plan)
    prot = sheet.tile_pixel_mask(plan.protect)
    diff = (new != ref).any(-1)
    rep.ignored_protected = int((diff & prot).sum())
    edit = diff & ~prot
    rep.changed = int(edit.sum())
    m, tiles = plan.tile_map(w, h)
    new_idx = old_idx.copy()

    if palette == "rebuild":
        rep.mode = "rebuild"
        free = ~prot
        used = set(np.unique(m[free]).tolist())
        if len(used) != 1 or -1 in used:
            raise XTXEncodeError(f"--palette rebuild needs one palette tile under every "
                                 f"editable pixel; this plan uses {len(used)} "
                                 f"({[tiles[k] if k >= 0 else 'gray' for k in sorted(used)]})")
        tile = tiles[used.pop()]
        px = new[free]
        q = Image.fromarray(px.reshape(1, -1, 4), "RGBA").quantize(256, Image.Quantize.FASTOCTREE)
        qpal = np.array(q.getpalette("RGBA")[:256 * 4] + [0] * max(0, 1024 - len(q.getpalette("RGBA"))),
                        np.uint8).reshape(256, 4)
        raw = [(int(r), int(g), int(b), 0x80 if a >= 255 else (int(a) + 1) // 2) for r, g, b, a in qpal]
        sheet.put_clut_raw(*tile, raw)
        lut = np.frombuffer(b"".join(sheet.clut(*tile)), np.uint8).reshape(256, 4)
        k, err = _nearest(lut, px) if len(px) < 2_000_000 else (np.array(q).ravel(), np.zeros(1))
        new_idx[free] = k
        rep.quantized = int(free.sum())
        rep.max_error = float(err.max()) if err.size else 0.0
        sheet.set_indices(new_idx, free)
        return sheet.to_bytes(), rep

    if palette != "existing":
        raise XTXEncodeError(f"palette mode {palette!r}: use 'existing' or 'rebuild'")
    rep.mode = "existing"
    for k in np.unique(m[edit]).tolist():
        sel = edit & (m == k)
        px = new[sel]
        if k < 0:                                   # grayscale identity: index = value
            new_idx[sel] = px[:, 0]
            continue
        lut = np.frombuffer(b"".join(sheet.clut(*tiles[k])), np.uint8).reshape(256, 4)
        uniq, inv = np.unique(px.reshape(-1, 4), axis=0, return_inverse=True)
        kk, err = _nearest(lut, uniq)
        new_idx[sel] = kk[inv.ravel()]
        rep.max_error = max(rep.max_error, float(err.max()))
        rep.quantized += int(sel.sum())
    sheet.set_indices(new_idx, edit)
    return sheet.to_bytes(), rep


# ---------------------------------------------------------------------- CLI

def _bindings_for(name: Optional[str]):
    if not name:
        return ()
    if name == "statfont":
        import statfont
        return statfont.BINDINGS
    raise XTXEncodeError(f"unknown binding set {name!r} (known: statfont)")


def _cmd_export(a) -> int:
    src = Path(a.inp)
    side = export_sheet(src.read_bytes(), Path(a.out), src.stem, _bindings_for(a.bind), str(src))
    plan = side.get("plan")
    print(f"{src.name}: {side['size'][0]}x{side['size'][1]} fmt {side['fmt']:#x}"
          + (f", base palette {plan['base']}, {len(plan['rects'])} plan rects" if plan else "")
          + f" -> {a.out}")
    return 0


def _cmd_encode(a) -> int:
    src = Path(a.inp)
    side = None
    jp = Path(a.json) if a.json else Path(a.png).with_name(src.stem + ".json")
    if jp.exists():
        side = json.loads(jp.read_text())
    out, rep = import_png(src.read_bytes(), a.png, side, a.palette)
    Path(a.out).write_bytes(out)
    print(rep.line())
    print(f"{a.out}: {len(out)} bytes (same size as {src.name}: {len(out) == src.stat().st_size})")
    return 0


def add_commands(subparsers) -> None:
    p = subparsers.add_parser("xtx-export", help="XTX -> PNG render + index PNG + palette-plan sidecar")
    p.add_argument("--in", dest="inp", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--bind", help="known palette bindings to apply ('statfont' for the window sheets)")
    p.set_defaults(func=_cmd_export)
    p = subparsers.add_parser("xtx-encode", help="PNG -> XTX, same size (index PNG, or RGBA + sidecar)")
    p.add_argument("--in", dest="inp", required=True, help="the original .xtx")
    p.add_argument("--png", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--json", help="export sidecar (default: <png dir>/<xtx stem>.json)")
    p.add_argument("--palette", choices=("existing", "rebuild"), default="existing")
    p.set_defaults(func=_cmd_encode)


# ---------------------------------------------------------------- self-test

def _synthetic(cw: int = 64, ch: int = 32) -> bytes:
    """A small fmt-8 sheet: a gradient index image with one CLUT tile at (0, 16)."""
    rng = np.random.default_rng(3)
    hdr = bytearray(HEADER)
    struct.pack_into("<4sIII", hdr, 0, b"XTX\x00", PIXELS + cw * ch * 4, 1, 0x10)
    struct.pack_into("<HHI", hdr, 0x10, cw, FMT_PSMT8, ch)
    struct.pack_into("<II", hdr, 0x1C, ((cw * ch * 4) >> 12) << 8 | 2, HEADER)
    s = Sheet(bytes(hdr), FMT_PSMT8, cw, ch, bytearray(cw * ch * 4), b"", make_packet(cw, ch))
    yy, xx = np.mgrid[0:ch * 2, 0:cw * 2]
    s.set_indices(((xx + yy) % 200).astype(np.uint8))
    pal = [(i, 255 - i, (i * 7) & 255, 0x80) for i in range(256)]
    pal[0] = (0, 0, 0, 0)
    s.put_clut_raw(0, 16, pal)
    s.canvas[:4] = rng.integers(0, 255, 4, dtype=np.uint8).tobytes()
    return s.to_bytes()


def _disc_samples(env: str, paths: Sequence[str]):
    import os
    iso = os.environ.get(env)
    if not iso or not Path(iso).exists():
        return None
    from disc import Disc
    out = {}
    with Disc(iso) as d:
        for p in paths:
            if d.exists(p):
                out[p] = d.read(p)
    return out


def self_test() -> int:
    import io
    import tempfile
    bad = 0

    def check(c, msg):
        nonlocal bad
        print(("ok   " if c else "FAIL ") + msg)
        bad += 0 if c else 1

    # mapping
    check(cbp_xy(0x308) == (0, 112) and cbp_xy(0x3c8) == (384, 112) and cbp_xy(0x30c) == (16, 112),
          "cbp_xy: 0x308 -> (0,112), 0x3c8 -> (384,112), 0x30c -> (16,112) at TBW 8")
    for cw, ch in ((512, 128), (384, 128), (72, 128), (128, 128), (320, 256)):
        check(is_bijective(cw, ch), f"unswizzle8 is a bijection on a {cw}x{ch} canvas")
    check(not is_bijective(246, 128), "246-word canvas (segcap) is refused")

    # synthetic round trips
    data = _synthetic()
    s = Sheet.parse(data)
    check(s.to_bytes() == data, "synthetic: parse/to_bytes identity")
    s.set_indices(s.indices())
    check(s.to_bytes() == data, "synthetic: set_indices(indices()) identity")
    check(s.clut_raw(0, 16)[5] == (5, 250, 35, 0x80), "synthetic: CSM1 CLUT read back in logical order")
    with tempfile.TemporaryDirectory() as td:
        side = export_sheet(data, Path(td), "syn", bindings=[(0, 0, 128, 64, (0, 16))])
        out, rep = import_png(data, Path(td) / "syn.png", side)
        check(out == data and rep.changed == 0, "synthetic: unmodified RGBA export re-encodes byte-identical")
        out, rep = import_png(data, Path(td) / "syn_index.png", side)
        check(out == data, "synthetic: unmodified index PNG re-encodes byte-identical")
        im = np.array(Image.open(Path(td) / "syn.png"))
        im[2:6, 2:6] = (10, 245, 70, 255)            # palette entry 10
        out, rep = import_png(data, Image.fromarray(im, "RGBA"), side)
        idx = Sheet.parse(out).indices()
        check(len(out) == len(data) and (idx[2:6, 2:6] == 10).all() and rep.quantized == 15,   # (5,5) was index 10 already
              f"synthetic: an edit quantizes to the bound palette ({rep.line()})")

    # discs: every fmt-8 sheet decodes and re-encodes byte-identical
    for env, paths in (("XS3_D1", ("mnu\\us\\window0.xtx", "mnu\\us\\titleobj.xtx",
                                   "mg1\\us\\picture.xtx", "mnu\\itemcap.xtx", "kao\\abel01_nol.xtx")),
                       ("XS3_JP1", ("mnu\\jp\\window0.xtx", "mnu\\jp\\titleobj.xtx",
                                    "mg1\\jp\\picture.xtx"))):
        got = _disc_samples(env, paths)
        if got is None:
            print(f"SKIP {env} not set")
            continue
        for p, b in got.items():
            sh = Sheet.parse(b)
            ok = sh.packet == make_packet(sh.cw, sh.ch) and sh.trailer == b""
            if sh.fmt == FMT_PSMT8:
                sh.set_indices(sh.indices())
                ok = ok and sh.to_bytes() == b
                ref = X._unswizzle8(b[PIXELS:], sh.cw, sh.cw * 2, sh.ch * 2)
                ok = ok and sh.indices().tobytes() == ref
            else:
                sh.set_rgba_linear(sh.rgba_linear())
                ok = sh.to_bytes() == b
            check(ok, f"{env} {p}: GS packet as expected, index/RGBA re-encode byte-identical ({len(b)} B)")
        p = paths[0]                # window0: a sheet with a real multi-palette plan
        if p in got:
            with tempfile.TemporaryDirectory() as td:
                side = export_sheet(got[p], Path(td), "t")
                _h, dw, dh, dec, drgba = X.decode_indexed(got[p])
                sh = Sheet.parse(got[p])
                check(dec == sh.indices().tobytes()
                      and np.array_equal(np.array(Image.open(Path(td) / "t.png")),
                                         np.frombuffer(drgba, np.uint8).reshape(dh, dw, 4)),
                      f"{env} {p}: xtx_decode reads the same canvas (0x50) and renders the same "
                      "picture as the export")
                out, rep = import_png(got[p], Path(td) / "t.png", side)
                check(out == got[p], f"{env} {p}: unmodified RGBA PNG -> XTX byte-identical")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(self_test())
