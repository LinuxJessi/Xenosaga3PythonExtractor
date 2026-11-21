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
    0x20  u32 offset of the GS upload packet (0x30 throughout the discs)
    0x24  …  reserved (zeros)
    0x30  32-byte GS upload packet (DMA → VIF → GIF), validated before use:
          0x30-0x3B  zero (DMA tag)
          0x3C  u32  VIF DIRECT = 0x50 << 24 | (W*H*4/16 + 1) qwords
          0x40  u64  GIF tag: IMAGE mode (FLG 2), EOP, NLOOP = W*H*4/16
          0x48  u64  0 (REGS)
    0x50  payload: width × height × 4 bytes for BOTH formats; the file ends
          exactly there (size = 0x50 + W*H*4, all 1,875 XTX on the five
          discs — USA 1/2, Japan 1/2, May 2006 prototype).

Pixels start AFTER the packet: ``pixel_offset = header[0x20] + 0x20`` when
the packet's tag words check out. A file without that packet (none known)
falls back to reading pixels at ``header[0x20]`` itself. Until 2026-11-20
this module read pixels at 0x30, which shifted every picture 8 words right
with row wrap (16 px for fmt 0x08, 8 px for fmt 0x04) and dragged the
packet in as the first 8 words; the 8 px were invisible on portraits but
put every parked CLUT tile 8 words off its 16×16 block grid.

Format 0x04 (367 files per disc — kao/ portraits, most UI): the payload is
straight rows of R, G, B, A.

Format 0x08 (8 files per disc — mnu/ and mg1/ sheets): the payload is a GS
local-memory dump — a CT32 "canvas" of width × height words that actually
holds a PSMT8 8-bit-indexed image of (2·width) × (2·height) pixels, exactly
like Xenosaga I's XTX. The indices are recovered with the standard PS2
"unswizzle8" routine. The 256-colour CSM1 palettes are parked inside the
same canvas as 16×16 CT32 tiles (SLUS addresses them by GS block pointer,
which the file itself does not record). Palette selection (``plan_palettes``)
is the ranked plan of steps 1-5 below with the ENGINE's own bindings laid on
top (step 6): wherever a draw found in the game code reaches, its CLUT wins.

1. Candidates: 16×16 tiles whose 256 entries all have raw alpha ≤ 0x80, ≥ 64
   distinct colours and ≥ 26 entries at exactly 0x80. The opaque-entry test
   is new (2026-11-20) and removes the look-alikes made of index bytes
   (window0: 24 real tiles vs 185 look-alikes; itemcap 15 vs 247). The real
   tiles sit on the 16-word grid at the bottom of every canvas (window
   sheets rows 96/112, itemcap row 240, segcap/picture/ctrl row 112).
2. BASE palette: the candidate whose whole-image render is most spatially
   coherent (adjacent-pixel colour distance ÷ distance-16 colour distance)
   with a stiff penalty for transparency.
3. Picture grid: column and row seams of the index map (lines where the
   index jump is a local spike; a run of seams along a frame or gutter
   stands for its middle one) cut the sheet into cells. When the cells with
   a hue signal number exactly the parked palettes (itemcap 15 icons / 15
   palettes, segcap 15 thumbnails / 15), each picture takes a different
   palette by minimum total chroma score (step 4's score, Hungarian
   assignment) and step 4 is skipped. Pictures are 125x140 (itemcap) and
   75x65 (segcap), so the 64-px blocks of step 4 straddled two pictures and
   split them between palettes (the gold ring half silver, seams through
   most thumbnails); the grid follows the real borders (124/256/380/512 x
   140/280; 75/150/225/256/331/406 x 65/130/195) and every icon and
   thumbnail is in one palette, its own (column-major on itemcap, row-major
   on segcap — checked in self_test on all five discs).
4. Otherwise per 64-px block, chroma coherence: many sheets park one luminance-sorted
   256-colour palette per picture (itemcap: one per item icon, column-major;
   segcap: one per location thumbnail; window sheets: one per portrait
   pair). Under any of them an index map renders as a smooth luminance
   picture, which is why step 2 alone settled on a sepia ramp. Hue tells
   them apart: under the right palette chroma (RGB minus its mean) is
   smooth, under a wrong one it jumps pixel to pixel. A block takes the
   candidate with the best chroma score when it is clearly better than the
   base and the runner-up, keeps the block opaque, does not flatten it, and
   keeps a dominant background index the base's colour; undecided blocks
   between agreeing decided neighbours inherit their palette.
5. The CLUT tiles the plan uses are blanked from the output.
6. Engine bindings (``engine_palettes``, new 2026-11-20 fifth pass): the
   draw rectangles and CLUT pointers (CBP = sheet page * 32 + K, K a block
   inside the sheet's own canvas) read from SLUS_213.89's sprite tables and
   draw functions, OV01.OVL (title menu) and OV04.OVL (minigame), applied
   largest first so a smaller draw wins where two overlap.

Colour status (2026-11-20, fifth pass): exact from the engine — itemcap and
segcap (the executable's tables agree with step 3 pixel for pixel, so their
PNGs did not change), titleobj (its three CLUTs are its own tiles (0,112)
(16,112) (32,112): one colour each with an alpha ramp, which step 1 cannot
see; before this pass it rendered as grayscale indices), the minigame sheet
(OV04's table; the ranked plan had painted it in one wrong palette) and
every drawn part of window0-2: about 78 % of their non-zero art pixels
(the HUD letters/digits, words, icons, gauges, tabs, frames, the portrait
faces). The rest of window0-2 (portrait cells outside the 26 x 45 face
sprites, a few small portraits, some frame pieces) is reached by no draw
found so far and keeps the ranked palette; where a portrait's face is bound
the ranked palette of its cell is the same one. ctrl has one palette. The
``*_index.png`` written alongside is exact for every sheet.


PS2 alpha is 7-bit with 128 = fully opaque. To produce a PNG the rest of the
world reads as normal, alpha bytes are scaled ``min(a * 2, 255)``.

There are no trailing bytes: the "32-byte footer" earlier notes described
was the last 8 words of pixels, misread because of the 0x30 start.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple


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
    data_offset: int       # header field +0x20: where the GS packet starts
    pixel_offset: int      # first pixel byte (data_offset + 0x20 after a valid packet)


PACKET_SIZE = 0x20


def has_gs_packet(data: bytes, at: int, width: int, height: int) -> bool:
    """True when ``data[at:at+0x20]`` is the GS image-upload packet for a
    width × height CT32 payload (zero DMA tag, VIF DIRECT qwords+1, GIF IMAGE
    tag with NLOOP = qwords and EOP, zero REGS)."""
    if at + PACKET_SIZE > len(data):
        return False
    q = width * height * 4 // 16
    vif = struct.unpack_from("<I", data, at + 0x0C)[0]
    gif, regs = struct.unpack_from("<QQ", data, at + 0x10)
    return (data[at:at + 0x0C] == bytes(12) and vif == (0x50 << 24 | (q + 1))
            and gif & 0x7FFF == q and gif >> 15 & 1 == 1 and gif >> 58 & 3 == 2
            and regs == 0)


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
    pixel_offset = data_offset
    if has_gs_packet(data, data_offset, width, height):
        pixel_offset = data_offset + PACKET_SIZE
    if pixel_offset + width * height * 4 > len(data):
        raise XTXError(
            f"truncated pixel block: need {pixel_offset + width*height*4} bytes, have {len(data)}"
        )
    return XTXHeader(total_size, sub_count, header_size, width, fmt, height, data_offset,
                     pixel_offset)


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


CLUT_OPAQUE_MIN = 26   # a parked CLUT has >= ~10% entries at raw alpha 0x80


def _clut_tile_like(canvas: bytes, canvas_w: int, px: int, py: int) -> bool:
    """Does the 16×16 tile at (px, py) look like CLUT data? Every raw alpha
    ≤ 0x80 (GS 7-bit), ≥ 64 distinct colours, and at least CLUT_OPAQUE_MIN
    entries at exactly 0x80 (fully opaque). The last test is what separates a
    palette from PSMT8 index bytes that happen to stay ≤ 0x80 in the alpha
    lane: on the five discs every real CLUT tile has ≥ 16% opaque entries and
    every look-alike made of index data has 0% (window0: 24 real tiles, 185
    look-alikes; itemcap: 15 real, 247 look-alikes)."""
    distinct = set()
    opaque = 0
    for ey in range(16):
        row = ((py + ey) * canvas_w + px) * 4
        for ex in range(16):
            r, g, b, a = canvas[row + ex * 4 : row + ex * 4 + 4]
            if a > 0x80:
                return False
            opaque += a == 0x80
            distinct.add((r, g, b))
    return len(distinct) >= 64 and opaque >= CLUT_OPAQUE_MIN


def _scan_for_clut(canvas: bytes, canvas_w: int, canvas_h: int
                   ) -> Iterable[Tuple[List[bytes], Tuple[int, int]]]:
    """Yield ``(palette, (tile_x, tile_y))`` for every block-aligned 16×16
    tile that looks like a CLUT, bottom-right first (the parking
    convention), then the finer 8-px grid (CBPs address 8×8-word blocks) for
    tiles that do not overlap one already found."""
    found: List[Tuple[int, int]] = []
    def grid(n: int, step: int) -> range:      # multiples of step, high to low
        return range((n - 16) // step * step, -1, -step)
    spots = [(x, y) for y in grid(canvas_h, 16) for x in grid(canvas_w, 16)]
    spots += [(x, y) for y in grid(canvas_h, 8) for x in grid(canvas_w, 8) if x % 16 or y % 16]
    for px, py in spots:
        if any(abs(px - fx) < 16 and abs(py - fy) < 16 for fx, fy in found):
            continue
        if _clut_tile_like(canvas, canvas_w, px, py):
            found.append((px, py))
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
    """(base palette or None, all candidate palettes, [base tile]).
    See the module docstring for the ranking."""
    uniq = _unique_cluts(canvas, canvas_w, canvas_h)
    if not uniq:
        return None, [], []
    best, base, base_xy = float("inf"), None, None
    for pal, xy in uniq:
        s = _candidate_score(idx, out_w, out_h, pal)
        if s < best:
            best, base, base_xy = s, pal, xy
    # every candidate is a verified parked CLUT (opaque-entry test), so the
    # best one is used even when its score is poor (flat-colour sheets such
    # as mg1 picture score > 1.2 under every palette, the true one included)
    if base is None:
        return None, [p for p, _ in uniq], []
    return base, [p for p, _ in uniq], [base_xy]


def _unique_cluts(canvas: bytes, canvas_w: int, canvas_h: int
                  ) -> List[Tuple[List[bytes], Tuple[int, int]]]:
    """CLUT tiles with identical palettes collapsed (first tile kept)."""
    uniq: List[Tuple[List[bytes], Tuple[int, int]]] = []
    for pal, xy in _scan_for_clut(canvas, canvas_w, canvas_h):
        if all(pal != p for p, _ in uniq):
            uniq.append((pal, xy))
    return uniq


# per-block palette assignment (chroma coherence), see plan_palettes
PLAN_BLOCK = 64       # px of the PSMT8 picture
PLAN_MARGIN = 0.87    # a block's winner must beat the base palette by 13%
PLAN_CONFIDENT = 0.9  # ... and the runner-up by 10%
PLAN_OPAQUE = 0.97    # a rescue palette must leave the block opaque


def _chroma_score(rgba, far_d: int = 16) -> float:
    """Chroma coherence of a rendered block (numpy (h, w, 4) float):
    (adjacent chroma distance + 4) / (chroma distance ``far_d`` px apart + 4).
    Chroma = RGB minus its mean, so luminance-sorted palettes (portraits,
    icons: 256 colours ordered dark to light) — which all render any index
    map as a smooth luminance picture — are told apart by hue: under the
    right palette hue varies smoothly, under another one it jumps from pixel
    to pixel. Flat chroma (a grey palette) scores 1, never a win. inf when
    the block is not almost fully opaque under this palette."""
    import numpy as np
    rgb = rgba[..., :3]
    ch = rgb - rgb.mean(-1, keepdims=True)
    op = rgba[..., 3] > 0
    if op.mean() < PLAN_OPAQUE:
        return float("inf")
    m = op[:, 1:] & op[:, :-1]
    m2 = op[:, far_d:] & op[:, :-far_d]
    if m.sum() < 40 or m2.sum() < 20:
        return float("inf")
    adj = np.abs(ch[:, 1:] - ch[:, :-1]).sum(-1)[m].mean()
    far = np.abs(ch[:, far_d:] - ch[:, :-far_d]).sum(-1)[m2].mean()
    return float((adj + 4) / (far + 4))


# picture-grid assignment (sheets that park one palette per picture), see
# plan_palettes step 3
SEAM_RATIO = 3.0      # a seam's index jump vs the median jump of its neighbours
SEAM_MIN_GAP = 24     # px between kept seams (the stronger one wins)
SEAM_EDGE = 12        # px: seams this close to the sheet edge are ignored
SEAM_RUN = 8          # px: seams chained this close form one run
PICTURE_MIN = 40      # px: smaller grid cells are gutters, not pictures
PICTURE_SIGNAL = 0.85  # a picture's best chroma score (flat = 1.0)


def _seams(im, axis: int) -> List[int]:
    """Picture seams of an index map along one axis (0 = between columns):
    positions where the mean index jump across the line is a local maximum
    above SEAM_RATIO × the median jump of the 10 lines around it. Seams
    closer than SEAM_MIN_GAP keep the stronger one; a run of seams chained
    at most SEAM_RUN apart stands for its middle member."""
    import numpy as np
    a = (im if axis == 0 else im.T).astype(np.int32)
    D = np.abs(np.diff(a, axis=1)).mean(0)
    n = len(D)
    cand = []
    for x in range(n):
        w = np.r_[D[max(0, x - 6):max(0, x - 1)], D[x + 2:x + 7]]
        if len(w) and D[x] > SEAM_RATIO * np.median(w) + 2 and D[x] >= D[max(0, x - 1):x + 2].max():
            cand.append((D[x] / (np.median(w) + 2), x + 1))
    keep: List[int] = []
    for _s, x in sorted(cand, reverse=True):
        # framed pictures give a run of seams (itemcap: A's 2-px frame, B's
        # 2-px frame, sometimes an 8-px gutter of index 0 between them):
        # the middle seam of the run is the border between the two pictures
        pos = sorted(c for _t, c in cand)
        i = j = pos.index(x)
        while i > 0 and pos[i] - pos[i - 1] <= SEAM_RUN:
            i -= 1
        while j + 1 < len(pos) and pos[j + 1] - pos[j] <= SEAM_RUN:
            j += 1
        x = pos[(i + j + 1) // 2]
        if SEAM_EDGE <= x <= n + 1 - SEAM_EDGE and all(abs(x - k) >= SEAM_MIN_GAP for k in keep):
            keep.append(x)
    return sorted(keep)


def _assign_min_cost(cost) -> List[int]:
    """One-to-one assignment minimising total cost (Hungarian method, square
    numpy matrix): ``result[row] = column``."""
    import numpy as np
    c = np.asarray(cost, np.float64)
    n = c.shape[0]
    u, v = np.zeros(n + 1), np.zeros(n + 1)
    p, way = np.zeros(n + 1, int), np.zeros(n + 1, int)
    for i in range(1, n + 1):
        p[0], j0 = i, 0
        minv, used = np.full(n + 1, np.inf), np.zeros(n + 1, bool)
        while True:
            used[j0] = True
            i0, delta, j1 = p[j0], np.inf, 0
            for j in range(1, n + 1):
                if not used[j]:
                    cur = c[i0 - 1, j - 1] - u[i0] - v[j]
                    if cur < minv[j]:
                        minv[j], way[j] = cur, j0
                    if minv[j] < delta:
                        delta, j1 = minv[j], j
            for j in range(n + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while True:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
            if j0 == 0:
                break
    out = [0] * n
    for j in range(1, n + 1):
        out[p[j] - 1] = j - 1
    return out


def _picture_grid(im, luts) -> List[Tuple[int, int, int, int, int]] | None:
    """``[(u0, v0, u1, v1, palette #)]`` when the sheet is a grid of pictures
    with one parked palette each, else None. The grid is the product of the
    column and row seams; a picture is a cell at least PICTURE_MIN px each
    way whose best chroma score is under PICTURE_SIGNAL. When there are
    exactly as many pictures as palettes, every picture takes a different
    palette by minimum total chroma score."""
    import numpy as np
    H, W = im.shape
    xs = [0] + _seams(im, 0) + [W]
    ys = [0] + _seams(im, 1) + [H]
    cells, scores = [], []
    for j in range(len(ys) - 1):
        for i in range(len(xs) - 1):
            u0, u1, v0, v1 = xs[i], xs[i + 1], ys[j], ys[j + 1]
            if u1 - u0 < PICTURE_MIN or v1 - v0 < PICTURE_MIN:
                continue
            sub = im[v0:v1, u0:u1]
            s = np.array([_chroma_score(lut[sub]) for lut in luts])
            if s.min() < PICTURE_SIGNAL:
                cells.append((u0, v0, u1, v1))
                scores.append(np.where(np.isfinite(s), s, 10.0))
    if len(cells) < 2 or len(cells) != len(luts):
        return None
    pick = _assign_min_cost(np.array(scores))
    return [c + (pick[n],) for n, c in enumerate(cells)]


def plan_palettes(canvas: bytes, canvas_w: int, canvas_h: int, idx: bytes,
                  out_w: int, out_h: int, name: str = ""
                  ) -> Tuple[Tuple[int, int] | None, List[Tuple[int, int, int, int, Tuple[int, int]]],
                             Dict[Tuple[int, int], List[bytes]]]:
    """Palette plan of a PSMT8 sheet: ``(base_tile, rects, palettes)``.

    The ranked plan below (``_ranked_plan``), then the ENGINE's own bindings
    on top (``engine_palettes.engine_rects``: draw rectangles and CLUT
    pointers read from the executable and its overlays), so every pixel a
    known draw reaches takes the palette the game uses and only the rest
    keeps the ranked guess. ``name`` (a file name or disc path, optional)
    tells the US and JP minigame sheets apart when their CLUTs were edited.
    A sheet with no detectable CLUT but known draws (titleobj) takes the
    largest draw's tile as its base."""
    import engine_palettes
    base, rects, pals = _ranked_plan(canvas, canvas_w, canvas_h, idx, out_w, out_h)
    eng = engine_palettes.engine_rects(canvas_w, canvas_h, canvas, name)
    if not eng:
        return base, rects, pals
    for *_r, xy in eng:
        if xy not in pals:
            pals[xy] = _clut_at(canvas, canvas_w, *xy)
    if base is None:
        base = eng[0][4]
    return base, list(rects) + eng, pals


def _ranked_plan(canvas: bytes, canvas_w: int, canvas_h: int, idx: bytes,
                 out_w: int, out_h: int
                 ) -> Tuple[Tuple[int, int] | None, List[Tuple[int, int, int, int, Tuple[int, int]]],
                            Dict[Tuple[int, int], List[bytes]]]:
    """The ranked (heuristic) palette plan: ``(base_tile, rects, palettes)``.

    ``base_tile`` is the BASE palette's canvas tile (None = no parked CLUT
    ranks; grayscale identity), ``rects`` are ``(u0, v0, u1, v1, tile)``
    picture rectangles that use another tile, ``palettes`` maps tile -> the
    256 display colours. Steps: the coherence-ranked base (``select_palettes``);
    then, when the sheet is a seam grid of exactly as many pictures as
    palettes (``_picture_grid``: itemcap, segcap), one palette per picture by
    minimum-cost assignment and nothing else; otherwise every PLAN_BLOCK block is scored under every candidate with
    ``_chroma_score``; a candidate takes the block when it beats the base by
    PLAN_MARGIN and the runner-up by PLAN_CONFIDENT, does not flatten the
    block (luminance spread ≥ half the base's) and, when one index fills half
    the block (a background), colours that index like the base does (L1 ≤ 48);
    an undecided block between
    ≥ 3 decided neighbours (3×3) that agree takes their palette when that
    keeps it as opaque as the base does. plan_palettes adds the engine
    bindings on top; xtx_encode.auto_plan uses that plan verbatim, so its
    export render equals this module's RGBA."""
    import numpy as np
    W, H = out_w, out_h
    uniq = _unique_cluts(canvas, canvas_w, canvas_h)
    base_pal, _pals, used = select_palettes(canvas, canvas_w, canvas_h, idx, W, H)
    pals = {xy: pal for pal, xy in uniq}
    if base_pal is None:
        return None, [], pals
    base_xy = used[0]
    keys = [xy for _, xy in uniq]
    kb = keys.index(base_xy)
    luts = [np.frombuffer(b"".join(pal), np.uint8).reshape(256, 4).astype(np.float64)
            for pal, _ in uniq]
    im = np.frombuffer(idx, np.uint8).reshape(H, W)
    grid = _picture_grid(im, luts)
    if grid is not None:
        return base_xy, [(u0, v0, u1, v1, keys[k]) for u0, v0, u1, v1, k in grid if k != kb], pals
    B = PLAN_BLOCK
    ny, nx = (H + B - 1) // B, (W + B - 1) // B
    decided = np.full((ny, nx), -1)
    for by in range(ny):
        for bx in range(nx):
            sub = im[by * B:(by + 1) * B, bx * B:(bx + 1) * B]
            renders = [lut[sub] for lut in luts]
            spread = [r[..., :3].mean(-1).std() for r in renders]
            vals, counts = np.unique(sub, return_counts=True)
            dom = int(vals[counts.argmax()]) if counts.max() * 2 >= sub.size else None
            s = np.array([_chroma_score(r)
                          if spread[k] >= 0.5 * spread[kb] and (
                              dom is None or np.abs(luts[k][dom] - luts[kb][dom]).sum() <= 48)
                          else np.inf
                          for k, r in enumerate(renders)])
            order = np.argsort(s)
            k = int(order[0])
            second = s[order[1]] if len(order) > 1 else np.inf
            if (k != kb and np.isfinite(s[k]) and s[k] < s[kb] * PLAN_MARGIN
                    and s[k] < second * PLAN_CONFIDENT):
                decided[by, bx] = k
    choice = np.where(decided >= 0, decided, kb)
    for by in range(ny):
        for bx in range(nx):
            if decided[by, bx] >= 0:
                continue
            win = decided[max(0, by - 1):by + 2, max(0, bx - 1):bx + 2].ravel()
            win = win[win >= 0]
            if len(win) < 3:
                continue
            vals, counts = np.unique(win, return_counts=True)
            if counts.max() < 3:
                continue
            k = int(vals[counts.argmax()])
            sub = im[by * B:(by + 1) * B, bx * B:(bx + 1) * B]
            if (luts[k][sub][..., 3] > 0).mean() >= (luts[kb][sub][..., 3] > 0).mean() - 0.03:
                choice[by, bx] = k
    rects = [(bx * B, by * B, min(W, (bx + 1) * B), min(H, (by + 1) * B), keys[int(choice[by, bx])])
             for by in range(ny) for bx in range(nx) if choice[by, bx] != kb]
    return base_xy, rects, pals


def tile_pixel_mask(canvas_w: int, canvas_h: int, tiles: Sequence[Tuple[int, int]]):
    """(H, W) bool numpy mask of the PSMT8 pixels whose canvas bytes lie in the
    given 16×16 CT32 tiles (exact, through the unswizzle8 mapping)."""
    import numpy as np
    tw = canvas_w * 2
    y = np.arange(2 * canvas_h, dtype=np.int64)[:, None]
    x = np.arange(2 * canvas_w, dtype=np.int64)[None, :]
    off = ((y & ~0xF) * tw + (x & ~0xF) * 2
           + ((((y & ~3) >> 1) + (y & 1)) & 7) * tw * 2
           + ((x + (((y + 2) >> 2) & 1) * 4) & 7) * 4 + ((y >> 1) & 1) + ((x >> 2) & 2))
    cmask = np.zeros((canvas_h, canvas_w), bool)
    for tx, ty in tiles:
        cmask[ty:ty + 16, tx:tx + 16] = True
    bytemask = np.repeat(cmask.ravel(), 4)
    return bytemask[np.minimum(off, bytemask.size - 1)] & (off < bytemask.size)


def decode_indexed(data: bytes, name: str = "") -> Tuple[XTXHeader, int, int, bytes, bytes]:
    """Decode a fmt=0x08 file. Returns ``(header, out_w, out_h, indices,
    rgba)`` where ``indices`` is the raw PSMT8 index map (ground truth) and
    ``rgba`` is the render under ``plan_palettes`` (grayscale identity when
    no palette tile ranks and no engine draw is known), with the CLUT tiles
    the plan uses blanked. ``name``: see plan_palettes."""
    import numpy as np
    hdr = parse_header(data)
    canvas = data[hdr.pixel_offset : hdr.pixel_offset + hdr.width * hdr.height * 4]
    out_w, out_h = hdr.width * 2, hdr.height * 2
    idx = _unswizzle8(canvas, hdr.width, out_w, out_h)
    base, rects, pals = plan_palettes(canvas, hdr.width, hdr.height, idx, out_w, out_h, name)
    im = np.frombuffer(idx, np.uint8).reshape(out_h, out_w)
    if base is None:
        lut = np.stack([np.arange(256)] * 3 + [np.full(256, 255)], -1).astype(np.uint8)
        rgba = lut[im]
        return hdr, out_w, out_h, idx, rgba.tobytes()

    def lut_of(xy):
        return np.frombuffer(b"".join(pals[xy]), np.uint8).reshape(256, 4)

    rgba = lut_of(base)[im]
    used = [base]
    for u0, v0, u1, v1, xy in rects:
        rgba[v0:v1, u0:u1] = lut_of(xy)[im[v0:v1, u0:u1]]
        if xy not in used:
            used.append(xy)
    # CLUT tiles are palette data, not art: blank the tiles the plan uses
    rgba[tile_pixel_mask(hdr.width, hdr.height, used)] = 0
    return hdr, out_w, out_h, idx, rgba.tobytes()


def decode(data: bytes) -> Tuple[XTXHeader, bytes]:
    """Return ``(header, rgba_pixels)`` for a linear (fmt=0x04) file.
    ``rgba_pixels`` is alpha-scaled and ready to feed into
    ``PIL.Image.frombytes('RGBA', (w, h), ...)``."""
    hdr = parse_header(data)
    raw = data[hdr.pixel_offset : hdr.pixel_offset + hdr.width * hdr.height * 4]
    return hdr, _scale_alpha(raw)


def decode_to_png(data: bytes, out_path: Path, name: str | None = None) -> XTXHeader:
    """Decode and write a PNG (plus a ``*_index.png`` ground-truth map for
    swizzled files). Imports PIL only here so the parser stays import-clean
    for callers that just want headers."""
    from PIL import Image

    hdr = parse_header(data)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if hdr.fmt == 0x08:
        hdr, out_w, out_h, idx, rgba = decode_indexed(data, str(out_path) if name is None else name)
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

# ---------------------------------------------------------------- self-test

def _synthetic(width: int = 8, height: int = 4, fmt: int = 0x04, packet: bool = True) -> bytes:
    n = width * height * 4
    hdr = bytearray(0x30)
    struct.pack_into("<4sIII", hdr, 0, b"XTX\x00", 0x50 + n, 1, 0x10)
    struct.pack_into("<HHI", hdr, 0x10, width, fmt, height)
    struct.pack_into("<II", hdr, 0x1C, (n >> 12) << 8 | 2, 0x30)
    q = n // 16
    pk = (bytes(12) + struct.pack("<I", 0x50 << 24 | (q + 1))
          + struct.pack("<QQ", q | 1 << 15 | 2 << 58, 0)) if packet else bytes(0x20)
    pixels = bytes((i * 7) & 0x7F for i in range(n))
    return bytes(hdr) + pk + pixels


def self_test() -> int:
    import os
    import numpy as np
    bad = 0

    def check(c, msg):
        nonlocal bad
        print(("ok   " if c else "FAIL ") + msg)
        bad += 0 if c else 1

    d = _synthetic()
    h = parse_header(d)
    check(h.data_offset == 0x30 and h.pixel_offset == 0x50,
          "GS packet at 0x30 recognised: pixels read from 0x50")
    check(decode(d)[1][:4] == bytes((0, 7, 14, min(21 * 2, 255))),
          "first pixel is the first byte after the packet (no 8-word shift)")
    d2 = _synthetic(packet=False)
    check(parse_header(d2).pixel_offset == 0x30,
          "no packet (zeroed tag words): falls back to the header offset")
    bad_pk = bytearray(d)
    struct.pack_into("<I", bad_pk, 0x3C, 0x50 << 24 | 3)
    check(parse_header(bytes(bad_pk)).pixel_offset == 0x30, "wrong VIF qword count: not taken as a packet")

    # CLUT filter: index bytes in the alpha lane (all <= 0x80, none 0x80) are rejected
    cw = 16
    tile = bytearray()
    for i in range(256):
        tile += bytes((i, (i * 3) & 255, (i * 5) & 255, 0x40))
    check(not _clut_tile_like(bytes(tile), cw, 0, 0), "CLUT look-alike with no opaque entry rejected")
    for i in range(0, 256 * 4, 4 * 8):
        tile[i + 3] = 0x80
    check(_clut_tile_like(bytes(tile), cw, 0, 0), "tile with 32 opaque entries accepted as a CLUT")

    # chroma score: same luminance ramp, smooth hue vs per-entry random hue
    rng = np.random.default_rng(1)
    lum = np.arange(256, dtype=np.float64)
    smooth = np.stack([lum, lum * 0.8, lum * 0.5, np.full(256, 255.0)], -1)
    jitter = rng.integers(-40, 41, (256, 3)).astype(np.float64)
    noisy = smooth.copy()
    noisy[:, :3] = np.clip(smooth[:, :3] + jitter - jitter.mean(1, keepdims=True), 0, 255)
    yy, xx = np.mgrid[0:64, 0:64]
    img = ((xx * 3 + yy) % 256).astype(np.uint8)
    check(_chroma_score(smooth[img]) < _chroma_score(noisy[img]) * PLAN_MARGIN,
          "chroma score prefers the palette whose hue varies smoothly")

    iso = os.environ.get("XS3_D1")
    if not iso or not Path(iso).exists():
        print("SKIP XS3_D1 not set")
        return 1 if bad else 0
    from disc import Disc
    with Disc(iso) as disc:
        names = [e.path for _c, e in disc.entries()
                 if getattr(e, "path", "") and e.path.lower().endswith(".xtx")]
        offs = set()
        for nm in names:
            b = disc.read(nm)
            hh = parse_header(b)
            offs.add((hh.pixel_offset, len(b) == hh.pixel_offset + hh.width * hh.height * 4))
        check(len(names) == 375 and offs == {(0x50, True)},
              f"Disc 1: all {len(names)} XTX carry the packet, pixels at 0x50, file = 0x50 + W*H*4")

        def plan(nm):
            b = disc.read(nm)
            hh = parse_header(b)
            cv = b[hh.pixel_offset:hh.pixel_offset + hh.width * hh.height * 4]
            W, H = hh.width * 2, hh.height * 2
            base, rects, pals = plan_palettes(cv, hh.width, hh.height,
                                              _unswizzle8(cv, hh.width, W, H), W, H)
            return base, {(r[0], r[1]): r[4] for r in rects}, pals

        def tiles_in(nm, cells):
            """The set of palette tiles the plan gives each cell (shrunk 3 px)."""
            b = disc.read(nm)
            hh = parse_header(b)
            cv = b[hh.pixel_offset:hh.pixel_offset + hh.width * hh.height * 4]
            W, H = hh.width * 2, hh.height * 2
            base, rects, _p = plan_palettes(cv, hh.width, hh.height,
                                            _unswizzle8(cv, hh.width, W, H), W, H)
            m = np.zeros((H, W), np.int32)
            m[:] = base[0] << 16 | base[1]
            for u0, v0, u1, v1, t in rects:
                m[v0:v1, u0:u1] = t[0] << 16 | t[1]
            return [{(int(v) >> 16, int(v) & 0xFFFF) for v in np.unique(m[y0 + 3:y1 - 3, x0 + 3:x1 - 3])}
                    for x0, y0, x1, y1 in cells]

        # itemcap: 5 x 3 framed icons (borders 124/256/380/512, 140/280),
        # palettes on row 240 column-major: icon (c, r) -> tile #(3c + r)
        cols = [(0, 124), (124, 256), (256, 380), (380, 512), (512, 640)]
        tiles = [(x, 240) for x in (0, 16, 32, 48, 64, 80, 128, 144, 160, 176, 192, 208, 256, 272, 288)]
        got = tiles_in("mnu\\itemcap.xtx", [(x0, 140 * r, x1, 140 * r + 140)
                                             for x0, x1 in cols for r in range(3)])
        check(got == [{t} for t in tiles],
              "itemcap: each of the 15 icons is in one palette, its own (column-major on row 240; "
              "the gold ring is gold top to bottom)")
        # segcap: two groups of 75 x 65 thumbnails (3+3+2 at x 0, 3+3+1 at x 256),
        # palettes on row 112 row-major: thumbnail #k -> tile (16k, 112)
        cells = [(g + 75 * c, 65 * r, g + 75 * c + 75, 65 * r + 65)
                 for g, rows in ((0, (3, 3, 2)), (256, (3, 3, 1))) for r, n in enumerate(rows) for c in range(n)]
        got = tiles_in("mnu\\segcap.xtx", cells)
        check(got == [{(16 * k, 112)} for k in range(15)],
              "segcap: each of the 15 thumbnails is in one palette, its own (row-major on row 112)")
        base, rects, pals = plan("mnu\\us\\window0.xtx")
        got = [rects.get((u, 0), base) for u in (256, 320, 384, 448)] + \
              [rects.get((u, 64), base) for u in (256, 320, 384, 448)]
        b0 = disc.read("mnu\\us\\window0.xtx")
        nclut = len(_unique_cluts(b0[0x50:], 512, 128))
        check(nclut == 24 and got == [(x, 112) for x in range(128, 256, 16)],
              "window0: 24 parked CLUTs; the 8 portrait blocks take the 8 sorted palettes "
              "(128..240, 112) in order")
        base, rects, pals = plan("mnu\\us\\titleobj.xtx")
        check(base == (0, 112) and list(rects.values()) == [(0, 112), (16, 112), (32, 112)],
              "titleobj: the three OV01 title-menu CLUTs (0x308/0x30c/0x318 = its own tiles "
              "(0,112) grey, (16,112) cyan, (32,112) white)")
        _engine_disc_checks(disc, "us", check)
    iso = os.environ.get("XS3_JP1")
    if iso and Path(iso).exists():
        with Disc(iso) as disc:
            _engine_disc_checks(disc, "jp", check)
    else:
        print("SKIP XS3_JP1 not set")
    return 1 if bad else 0


def _engine_disc_checks(disc, region: str, check) -> None:
    """engine_palettes against one disc: its tables re-read from the boot
    executable and the overlays, and the decoder drawing each bound rect with
    the bound CLUT (itemcap/segcap: no pixel changes against the ranked plan)."""
    import numpy as np
    import engine_palettes as E
    elf = disc.read(disc.boot_elf_name())
    ov01, ov04 = disc.read("OV01.OVL"), disc.read("OV04.OVL")
    win = list(E.WINDOW_SPRITES) if region == "us" else \
        [e for k, e in enumerate(E.WINDOW_SPRITES) if not 89 <= k <= 114]
    off = E.find_table(elf, E.WINDOW_SPRITES)
    check(off is not None and E.read_table(elf, off, len(win)) == win,
          f"{region}: window sprite table re-read from {disc.boot_elf_name()} "
          f"({len(win)} entries{'' if region == 'us' else ', no lowercase block'})")
    for nm, tab in (("itemcap", E.ITEMCAP_SPRITES), ("segcap", E.SEGCAP_SPRITES)):
        off = E.find_table(elf, tab)
        check(off is not None and E.read_table(elf, off, len(tab)) == list(tab),
              f"{region}: {nm} sprite table re-read from the executable")
    mg = E.MINIGAME_SPRITES_US if region == "us" else E.MINIGAME_SPRITES_JP
    off = E.find_table(ov04, mg, first=10)
    check(off is not None and E.read_table(ov04, off, len(mg)) == list(mg),
          f"{region}: minigame sprite table re-read from OV04.OVL")
    check(E.title_cbps(ov01) == [0x318, 0x30C, 0x308], f"{region}: OV01 title menu CBPs 0x318/0x30c/0x308")
    pic = disc.read(f"mg1\\{region}\\Picture.xtx")
    check(E.sheet_kind(256, 128, pic[0x50:]) == f"minigame-{region}"
          and E.sheet_kind(256, 128, b"", f"mg1/{region}/Picture.png") == f"minigame-{region}",
          f"{region}: minigame sheet recognised by its CLUT block and by its path")
    lang = region
    for path in (f"mnu\\{lang}\\window0.xtx", f"mnu\\{lang}\\titleobj.xtx", f"mg1\\{lang}\\Picture.xtx"):
        b = disc.read(path)
        hh = parse_header(b)
        cv = b[hh.pixel_offset:hh.pixel_offset + hh.width * hh.height * 4]
        W, H = hh.width * 2, hh.height * 2
        _h, _w, _hh, idx, rgba = decode_indexed(b)        # no name: retail CLUT fingerprint
        im = np.frombuffer(idx, np.uint8).reshape(H, W)
        out = np.frombuffer(rgba, np.uint8).reshape(H, W, 4)
        eng = E.engine_rects(hh.width, hh.height, cv)
        owner = np.full((H, W), -1)
        for n, (u0, v0, u1, v1, _t) in enumerate(eng):
            owner[v0:v1, u0:u1] = n
        blank = tile_pixel_mask(hh.width, hh.height, sorted({r[4] for r in eng}))
        ok = bool(eng)
        for n, (*_r, t) in enumerate(eng):
            lut = np.frombuffer(b"".join(_clut_at(cv, hh.width, *t)), np.uint8).reshape(256, 4)
            sel = (owner == n) & ~blank
            ok = ok and np.array_equal(out[sel], lut[im[sel]])
        check(ok, f"{region}: {path} — every pixel of the {len(eng)} engine rects drawn with its "
                  f"CLUT ({100 * E.coverage(hh.width, hh.height, idx, cv):.0f}% of the non-zero "
                  "indices covered)")
    for path in ("mnu\\itemcap.xtx", "mnu\\segcap.xtx"):
        b = disc.read(path)
        hh = parse_header(b)
        cv = b[hh.pixel_offset:hh.pixel_offset + hh.width * hh.height * 4]
        W, H = hh.width * 2, hh.height * 2
        idx = _unswizzle8(cv, hh.width, W, H)
        base, rects, pals = _ranked_plan(cv, hh.width, hh.height, idx, W, H)
        m = np.zeros((H, W), np.int64)
        m[:] = base[0] << 16 | base[1]
        for u0, v0, u1, v1, t in rects:
            m[v0:v1, u0:u1] = t[0] << 16 | t[1]
        ok = True
        for u0, v0, u1, v1, t in E.engine_rects(hh.width, hh.height, cv):
            ok = ok and bool((m[v0:v1, u0:u1] == (t[0] << 16 | t[1])).all())
        check(ok, f"{region}: {path} — the executable's sprite table agrees with the ranked "
                  "picture-grid plan pixel for pixel")


__all__ = [
    "XTXError",
    "XTXHeader",
    "parse_header",
    "decode",
    "decode_indexed",
    "decode_to_png",
    "convert_tree",
    "BatchStats",
    "plan_palettes",
    "self_test",
]


if __name__ == "__main__":
    import sys
    sys.exit(self_test())
