#!/usr/bin/env python3
"""chrtex.py — decode, edit, and re-import Xenosaga III character textures.

Works on the `txy` texture block embedded in `.chr` / `.wpn` / `.map`
MR packages (format spec: docs/chr-txy-format.md), and on the same
resource wherever else it appears (`.esd` / `.esp` effect libraries,
`.sme` bundles — see xcpack.iter_txy_records). Pixels are PSMT8 (fmt
0x13) or PSMT4 (fmt 0x14) indices swizzled into a PSMCT32 canvas, or raw
CT32 (fmt 0); palettes are CLUT tiles in that same canvas (16x16 for
PSMT8, 8x2 for PSMT4). Characters and weapons are stored uncompressed, so
every edit is a same-size in-place byte patch, both into the .chr and
into the ISO. Field maps are LZSS-compressed on disc (xcpack.py handles
that transparently for decoding; in-place edits of compressed packages
are refused because the result would not fit its disc slot).

Commands (see docs/MODDING-CHARACTERS.md for the walkthrough):

  decode <chr> <outdir>                 textures + canvas + palettes -> PNG
  export-palettes <chr> <outdir>        each CLUT tile -> editable 16x16 PNG
  import-palettes <chr> <dir> <out>     edited tile PNGs -> new .chr
  import-entry <chr> <name> <png> <out> repaint a texture (quantized, exp.)
  pink-kosmos <chr> <out> [hue]         worked example: blue-band recolor
  pink-shion <chr> <out> [hue]          worked example: warm-band + policy
  iso-extract <iso> <discpath> <out>    pull a file via the disc's own index
  iso-patch <iso> <discpath> <file>     write it back (size-checked+verified)
  iso-sweep <iso> kosmos|shion [hue]    recolor every matching .chr in an ISO

`<discpath>` is the in-game path as the disc's X3.00/X3.10/X3.20 index spells
it, e.g. `\\mdl\\chr\\pc\\C3kosmos00.chr` (quote it in the shell; / works,
case-insensitive). Works on USA, the May 2006 prototype and Japanese images.
Different-size writes and Disc 1 + Disc 2 pairs: `cli.py patch` (patch.py).
"""
import colorsys
import struct
import sys
import zlib
from pathlib import Path

import xcpack

# module dir normally; PyInstaller's unpack dir in frozen release builds
# (lba/ ships as bundled data there — see packaging/xenosaga-extractor.spec)
HERE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))


class ChrError(ValueError):
    """A package or texture block that cannot be parsed / edited as asked.
    The command-line entry points turn it into a clean exit message; batch
    callers (browse sweeps) catch it per file."""


# GS pixel-storage formats as they appear in the txy entry table
PSMCT32, PSMT8, PSMT4 = 0x00, 0x13, 0x14

# ---------------------------------------------------------------------------
# minimal PNG io (stdlib only; import accepts 8-bit RGB/RGBA, non-interlaced)
# ---------------------------------------------------------------------------

def _chunk(tag, payload):
    return (struct.pack(">I", len(payload)) + tag + payload
            + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF))


def write_png(path, w, h, rgba):
    raw = bytearray()
    for y in range(h):
        raw.append(0)
        raw += rgba[y * w * 4:(y + 1) * w * 4]
    Path(path).write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
        + _chunk(b"IDAT", zlib.compress(bytes(raw), 6))
        + _chunk(b"IEND", b""))


def read_png(path):
    """(w, h, rgba bytes). Accepts what image editors commonly save:
    8-bit truecolor with or without alpha, no interlacing, all filters."""
    d = Path(path).read_bytes()
    if d[:8] != b"\x89PNG\r\n\x1a\n":
        sys.exit(f"{path}: not a PNG")
    w, h = struct.unpack(">II", d[16:24])
    depth, ctype, _comp, _filt, interlace = d[24:29]
    if depth != 8 or ctype not in (2, 6) or interlace:
        sys.exit(f"{path}: save as 8-bit RGB/RGBA, non-interlaced "
                 f"(got depth={depth} colortype={ctype} interlace={interlace})")
    nch = 4 if ctype == 6 else 3
    idat, off = b"", 8
    while off < len(d):
        ln, = struct.unpack(">I", d[off:off + 4])
        tag = d[off + 4:off + 8]
        if tag == b"IDAT":
            idat += d[off + 8:off + 8 + ln]
        off += 12 + ln
    raw = zlib.decompress(idat)
    stride = w * nch
    out = bytearray(w * h * 4)
    prev = bytearray(stride)
    for y in range(h):
        f = raw[y * (stride + 1)]
        line = bytearray(raw[y * (stride + 1) + 1:(y + 1) * (stride + 1)])
        for x in range(stride):
            a = line[x - nch] if x >= nch else 0
            b = prev[x]
            c = prev[x - nch] if x >= nch else 0
            if f == 1:
                line[x] = (line[x] + a) & 0xFF
            elif f == 2:
                line[x] = (line[x] + b) & 0xFF
            elif f == 3:
                line[x] = (line[x] + (a + b) // 2) & 0xFF
            elif f == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pr = a if pa <= pb and pa <= pc else (b if pb <= pc else c)
                line[x] = (line[x] + pr) & 0xFF
        prev = line
        for x in range(w):
            px = line[x * nch:x * nch + nch]
            out[(y * w + x) * 4:(y * w + x) * 4 + 4] = (
                bytes(px) + b"\xff" if nch == 3 else bytes(px))
    return w, h, bytes(out)


# ---------------------------------------------------------------------------
# txy parsing (docs/chr-txy-format.md)
# ---------------------------------------------------------------------------

def parse_chr(data):
    """Sub-resource directory of a STORED MR package (``load`` normalizes
    compressed ones first). Raises ChrError when there is no txy block."""
    try:
        subs = xcpack.sub_resources(data)
    except xcpack.XcError as exc:
        raise ChrError(str(exc)) from None
    if "txy" not in subs:
        raise ChrError(f"no txy sub-resource (has: {sorted(subs)})")
    if subs["txy"][1] == 0:
        raise ChrError("empty txy slot (placeholder package)")
    return subs


def parse_txy(data, sub_off, _sub_size):
    """Parse a txy resource. Returns the primary texture bank's table
    (canvas width, strips, entries) plus ``banks``: the further bank
    tables of a multi-bank txy (field maps 2-8 banks, header word +0x04 =
    bank count, table offsets at +0x10[count]; layout as documented in
    Xenosaga2PythonExtractor/txy.py, the same engine). Every bank carries
    the same entry table and only the strips differ; each entry's +0x30
    word (``bank``) names the bank its pixels come from, and
    ``decode_entries`` decodes it against GS memory after banks 0..bank
    are uploaded in order (the XS2 txy.py rule)."""
    txy = sub_off + 0x40                       # 0x40-byte pre-header
    if data[txy:txy + 4] != b"txy\x00":
        raise ChrError("txy magic missing")
    tbl_off, = struct.unpack_from("<I", data, txy + 0x10)
    if tbl_off == 0 or txy + tbl_off + 0x40 > len(data):
        raise ChrError("empty txy (no strip table)")
    t = _parse_bank(data, txy, tbl_off)
    t["banks"] = []
    nbanks, = struct.unpack_from("<I", data, txy + 0x04)
    if not 1 <= nbanks <= 32:                  # older reading: 3 extra slots
        nbanks = 4
    for k in range(1, nbanks):                 # extra bank table pointers
        if txy + 0x10 + k * 4 + 4 > len(data):
            break
        extra, = struct.unpack_from("<I", data, txy + 0x10 + k * 4)
        if extra and txy + extra + 0x40 <= len(data):
            try:
                b = _parse_bank(data, txy, extra)
            except ChrError:
                b = None
        else:
            b = None
        # an unreadable bank stays as a None slot so entry bank numbers
        # keep pointing at the right table
        t["banks"].append(b)
    while t["banks"] and t["banks"][-1] is None:
        t["banks"].pop()
    return t


def _parse_bank(data, txy, tbl_off):
    r0 = struct.unpack_from("<8I", data, txy + tbl_off)
    canvas_w, n_strips, n_entries = r0[2], r0[5], r0[6]
    if canvas_w == 0 or canvas_w % 64 or canvas_w > 2048 or n_entries > 512 or n_strips > 64:
        raise ChrError(f"implausible txy table (canvas {canvas_w}, {n_entries} entries)")
    # r0[5] is the strip count. Characters (4 strips) also leave a zeroed
    # record after the last strip, but the 8-strip field maps (txy
    # version 2) run the entry table straight after strip 7 — reading
    # "until a zero record" there swallowed entry 0 as a bogus 64x64 strip
    # and stamped its bytes over the canvas corner.
    strips, p = [], txy + tbl_off + 0x20
    while p + 0x20 <= len(data) and (n_strips == 0 or len(strips) < n_strips):
        r = struct.unpack_from("<8I", data, p)
        if r[2] == 0 or r[3] == 0:
            break
        strips.append({"off": r[0], "gs_block": r[1], "w": r[2], "h": r[3]})
        p += 0x20
    if not strips or n_entries == 0:
        raise ChrError("txy carries no pixel strips / entries")
    entries = []
    base = strips[0]["off"] + txy - n_entries * 0x60
    if base < txy:
        raise ChrError("entry table runs before the txy header")
    for i in range(n_entries):
        b = base + i * 0x60
        gsaddr, fmt, w, h, x, y, cbp, flag, palx, paly = struct.unpack_from("<10I", data, b)
        bank, = struct.unpack_from("<i", data, b + 0x30)
        name = data[b + 0x40:b + 0x60].split(b"\x00")[0].decode("latin1")
        # gsaddr (+0x00) is what a .pxy material's TEX0.TBP0 - 0x3800 names;
        # bank (+0x30) the bank holding the pixels (-1 on some entries)
        entries.append({"i": i, "name": name, "fmt": fmt, "w": w, "h": h,
                        "x": x, "y": y, "cbp": cbp, "palx": palx, "paly": paly,
                        "gsaddr": gsaddr, "bank": bank})
    return {"txy": txy, "canvas_w": canvas_w, "strips": strips, "entries": entries}


def strip_origin(t, s):
    page = s["gs_block"] // 32
    return (page % (t["canvas_w"] // 64)) * 64, (page // (t["canvas_w"] // 64)) * 32


def _bank_list(t):
    """[primary, extra banks...] by bank number; a slot that could not be
    parsed, or whose canvas width differs from the primary's, is None."""
    W = t["canvas_w"]
    return [t] + [b if b is not None and b["canvas_w"] == W else None
                  for b in t.get("banks", [])]


def compose_canvas(data, t, upto=None):
    """GS local memory as a CT32 canvas after banks 0..``upto`` of this txy
    are uploaded in order (``upto=None``: every bank, the state after the
    whole file). A later bank's strips overwrite an earlier one's, so an
    entry has to be decoded against the canvas of its own bank
    (``decode_entries`` does that): against the all-banks overlay, 632
    E3_UMD07/O_TST/... entries of bank 0 on Disc 1 came out all zero."""
    W = t["canvas_w"]
    banks = _bank_list(t)
    H = max(strip_origin(b, s)[1] + s["h"] for b in banks if b for s in b["strips"])
    t["canvas_h"] = H
    canvas = bytearray(W * H * 4)
    for b in banks[:None if upto is None else upto + 1]:
        if b is None:
            continue
        for s in b["strips"]:
            x0, y0 = strip_origin(b, s)
            src = b["txy"] + s["off"] + 0x20
            for y in range(s["h"]):
                d = ((y0 + y) * W + x0) * 4
                canvas[d:d + s["w"] * 4] = data[src + y * s["w"] * 4:src + (y + 1) * s["w"] * 4]
    return canvas


def entry_bank(t, e):
    """Bank index an entry decodes from: its +0x30 word, or the last bank
    when that word is out of range (-1)."""
    n = len(_bank_list(t))
    b = e.get("bank", n - 1)
    return b if 0 <= b < n else n - 1


def canvas_file_offset(t, x, y):
    """File offset of canvas pixel (x,y), or None if no strip covers it."""
    for s in t["strips"]:
        x0, y0 = strip_origin(t, s)
        if x0 <= x < x0 + s["w"] and y0 <= y < y0 + s["h"]:
            return t["txy"] + s["off"] + 0x20 + ((y - y0) * s["w"] + (x - x0)) * 4
    return None


def unswizzle8(canvas, cw, ch):
    W, H, tw = cw * 2, ch * 2, cw * 2
    idx = bytearray(W * H)
    for y in range(H):
        block_row = (y & ~0xF) * tw
        swap = (((y + 2) >> 2) & 1) * 4
        col_row = ((((y & ~3) >> 1) + (y & 1)) & 7) * tw * 2
        byte_y = (y >> 1) & 1
        drow = y * W
        for x in range(W):
            idx[drow + x] = canvas[block_row + (x & ~0xF) * 2 + col_row
                                   + ((x + swap) & 7) * 4 + byte_y + ((x >> 2) & 2)]
    return idx


def swizzle8_offset(cw, x, y):
    """Canvas byte offset holding the PSMT8 index for 2x-space pixel (x,y)."""
    tw = cw * 2
    swap = (((y + 2) >> 2) & 1) * 4
    return ((y & ~0xF) * tw + (x & ~0xF) * 2
            + ((((y & ~3) >> 1) + (y & 1)) & 7) * tw * 2
            + ((x + swap) & 7) * 4 + ((y >> 1) & 1) + ((x >> 2) & 2))


# --- PSMT4 (fmt 0x14) -------------------------------------------------------
# The canvas is GS local memory viewed as PSMCT32 (page 64x32 = 32 blocks of
# 8x8, 4 columns of 8x2 words each). A PSMT4 image over the same memory has
# 128x128 pages of 32 blocks (32x16 each, in the order below), 4 columns of
# 32x4 nibbles per block; within a column the 16 words interleave rows 0-3
# as tabulated (odd-numbered columns swap the word halves — the same
# "swap selector" the PSMT8 routine applies). So PSMT4 space is 2x the
# canvas width and 4x its height. Verified on the battle backdrops of
# mdl/map/bat/BSP_B01.map (fmt-0x14 entries render clean line art).
_BLK32 = ((0, 1, 4, 5, 16, 17, 20, 21), (2, 3, 6, 7, 18, 19, 22, 23),
          (8, 9, 12, 13, 24, 25, 28, 29), (10, 11, 14, 15, 26, 27, 30, 31))
_BLK32_XY = {b: (c * 8, r * 8) for r, row in enumerate(_BLK32) for c, b in enumerate(row)}
_BLOCK4 = (0, 2, 8, 10, 1, 3, 9, 11, 4, 6, 12, 14, 5, 7, 13, 15,
           16, 18, 24, 26, 17, 19, 25, 27, 20, 22, 28, 30, 21, 23, 29, 31)
_CW4 = ([0, 1, 2, 3, 4, 5, 6, 7] * 4 + [8, 9, 10, 11, 12, 13, 14, 15] * 4
        + [4, 5, 6, 7, 0, 1, 2, 3] * 4 + [12, 13, 14, 15, 8, 9, 10, 11] * 4)
_CB4 = ([0] * 8 + [2] * 8 + [4] * 8 + [6] * 8) * 2 + ([1] * 8 + [3] * 8 + [5] * 8 + [7] * 8) * 2


def swizzle4_offset(cw, x, y):
    """(canvas byte offset, nibble shift) holding the PSMT4 index for
    4bpp-space pixel (x, y) — width 2*cw, height 4*canvas_h."""
    ppr = cw // 64
    page = (y // 128) * ppr + (x // 128)
    px, py = x % 128, y % 128
    block = _BLOCK4[(px // 32) + (py // 16) * 4]
    bx, by = px % 32, py % 16
    col = by // 4
    k = bx + (by % 4) * 32
    word = _CW4[k] ^ (4 if col & 1 else 0)
    nib = _CB4[k]
    # GS word address -> CT32 canvas coordinates
    bx32, by32 = _BLK32_XY[block]
    cx = (page % ppr) * 64 + bx32 + (word % 8)
    cy = (page // ppr) * 32 + by32 + col * 2 + (word // 8)
    return (cy * cw + cx) * 4 + nib // 2, (nib & 1) * 4


def read_psmt4_rect(canvas, cw, x0, y0, w, h):
    """Linear 4-bit indices (one byte each) of a w x h rect in PSMT4 space."""
    out = bytearray(w * h)
    n = len(canvas)
    for y in range(h):
        row = y * w
        for x in range(w):
            off, sh = swizzle4_offset(cw, x0 + x, y0 + y)
            if off < n:
                out[row + x] = (canvas[off] >> sh) & 0xF
    return out


def clut16_at(canvas, cw, palx, paly, scale_alpha=True):
    """16 (r,g,b,a) entries of the 8x2 CSM1 CLUT tile at (palx, paly)."""
    pal = []
    for ey in range(2):
        row = ((paly + ey) * cw + palx) * 4
        for ex in range(8):
            r, g, b, a = canvas[row + ex * 4:row + ex * 4 + 4]
            pal.append((r, g, b, min(a * 2, 255) if scale_alpha else a))
    return pal


CSM1_SWAP = [(g * 32 + 8 + j, g * 32 + 16 + j) for g in range(8) for j in range(8)]


def clut_at(canvas, cw, palx, paly, scale_alpha=True):
    """256 logical-order (r,g,b,a) entries of the CLUT tile at (palx,paly)."""
    pal = []
    for ey in range(16):
        row = ((paly + ey) * cw + palx) * 4
        for ex in range(16):
            r, g, b, a = canvas[row + ex * 4:row + ex * 4 + 4]
            pal.append((r, g, b, min(a * 2, 255) if scale_alpha else a))
    for k, m in CSM1_SWAP:
        pal[k], pal[m] = pal[m], pal[k]
    return pal


def tile_file_offsets(t, palx, paly):
    offs = []
    for ey in range(16):
        off = canvas_file_offset(t, palx, paly + ey)
        if off is None:
            raise ChrError(f"CLUT tile ({palx},{paly}) row {ey} outside all strips")
        offs.append(off)
    return offs


def write_clut(buf, t, palx, paly, pal_logical):
    """Write 256 logical-order (r,g,b,a) entries (a in 0..255) back.

    Alpha handling: some shipped CLUTs store alpha above 0x80 (which the
    export clamps to 255), so an exact inverse doesn't exist. If the PNG
    alpha still matches what the export produced, the original stored byte
    is kept untouched (lossless round-trip); an *edited* alpha is stored
    as its half, clamped to the GS-opaque 0x80."""
    pal = list(pal_logical)
    for k, m in CSM1_SWAP:                     # logical -> CSM1 storage
        pal[k], pal[m] = pal[m], pal[k]
    offs = tile_file_offsets(t, palx, paly)
    for ey in range(16):
        for ex in range(16):
            r, g, b, a = pal[ey * 16 + ex]
            o = offs[ey] + ex * 4
            orig_a = buf[o + 3]
            new_a = orig_a if min(orig_a * 2, 255) == a else min(0x80, (a + 1) // 2)
            buf[o:o + 4] = bytes((r, g, b, new_a))


def referenced_tiles(t):
    """16x16 CLUT tiles used by the PSMT8 entries -> set of entry names.
    (PSMT4 entries use 8x2 tiles and raw-CT32 entries none; the palette
    editing commands work on the 256-colour tiles only.)"""
    tiles = {}
    for e in t["entries"]:
        if e["fmt"] == PSMT8:
            tiles.setdefault((e["palx"], e["paly"]), set()).add(e["name"])
    return tiles


# ---------------------------------------------------------------------------
# decode / palette export / palette import / entry import
# ---------------------------------------------------------------------------

def load(path):
    """(stored-form package bytes, parsed txy). Compressed field maps are
    decompressed here, so decoding works on every package; the editing
    commands check ``xcpack.parse_header(raw).compressed`` before writing."""
    raw = Path(path).read_bytes()
    try:
        data = xcpack.normalize(raw)
    except xcpack.XcError as exc:
        raise ChrError(str(exc)) from None
    t = parse_txy(data, *parse_chr(data)["txy"])
    t["compressed"] = data is not raw
    return data, t


def _refuse_if_compressed(t, what):
    if t.get("compressed"):
        raise ChrError(f"{what}: this package is LZSS-compressed on disc; an edited "
                       "copy would have to be recompressed to fit its slot, which "
                       "nothing supports yet (characters and weapons are stored "
                       "uncompressed and edit fine)")


def _opaque_fraction(rgba):
    n = len(rgba) // 4
    return sum(1 for i in range(3, len(rgba), 4) if rgba[i]) / n if n else 0.0


def _decode_one(t, e, canvas, idx8):
    """rgba bytes of entry ``e`` against one canvas (``idx8``: its unswizzled
    8bpp atlas, needed for PSMT8 only)."""
    cw = t["canvas_w"]
    w, h, x0, y0 = e["w"], e["h"], e["x"], e["y"]
    rgba = bytearray(w * h * 4)
    if e["fmt"] == PSMT8:
        pal = [bytes(p) for p in clut_at(canvas, cw, e["palx"], e["paly"])]
        aw = cw * 2
        for y in range(h):
            irow = (y0 + y) * aw + x0
            if irow + w > len(idx8):
                break
            orow = y * w * 4
            for x in range(w):
                rgba[orow + x * 4:orow + x * 4 + 4] = pal[idx8[irow + x]]
    elif e["fmt"] == PSMT4:
        pal = [bytes(p) for p in clut16_at(canvas, cw, e["palx"], e["paly"])]
        nib = read_psmt4_rect(canvas, cw, x0, y0, w, h)
        for i, v in enumerate(nib):
            rgba[i * 4:i * 4 + 4] = pal[v]
    else:                                       # fmt 0: raw CT32 region
        for y in range(h):
            s = ((y0 + y) * cw + x0) * 4
            row = canvas[s:s + w * 4]
            orow = y * w * 4
            for x in range(min(w, len(row) // 4)):
                r, g, b, a = row[x * 4:x * 4 + 4]
                rgba[orow + x * 4:orow + x * 4 + 4] = bytes((r, g, b, min(a * 2, 255)))
    return bytes(rgba)


def decode_entries(data, t, canvas=None, idx8=None):
    """Yield ``(entry, w, h, rgba_bytes)`` for every entry of a parsed txy.

    fmt 0x13 (PSMT8): 256-colour CLUT tile at (palx, paly), indices from
    the unswizzled 8bpp atlas. fmt 0x14 (PSMT4): 16-colour 8x2 tile,
    indices read straight from the canvas per pixel. fmt 0: the entry
    rect is raw CT32 in canvas coordinates.

    Multi-bank txy: each entry is decoded against the canvas of its own
    bank (``entry_bank``: banks 0..bank uploaded in order). When that comes
    out all zero (no pixel, no alpha), the other bank states are tried in
    order and the first that gives pixels is used. Measured on Disc 1's
    265 multi-bank packages (34,980 entries): the bank word alone leaves
    140 entries of bank -1 (wave_plus.* in E3_ZDA01) and 22 of bank 0
    (sotowa3/4 in E3_UMD06) empty that bank 0 resp. bank 1 fill; the old
    all-banks overlay left 630 empty. ``canvas`` / ``idx8`` may be passed in
    to force one canvas for every entry instead."""
    cw = t["canvas_w"]
    forced = canvas is not None
    cache = {}
    nbanks = len(_bank_list(t))

    def state(b):
        if b not in cache:
            cache[b] = [compose_canvas(data, t, b), None]
        return cache[b]

    def run(st, e):
        if e["fmt"] == PSMT8 and st[1] is None:
            st[1] = unswizzle8(st[0], cw, t["canvas_h"])
        return _decode_one(t, e, st[0], st[1])

    forced_state = [canvas, idx8]
    if forced and canvas is not None and "canvas_h" not in t:
        compose_canvas(data, t, 0)              # sets canvas_h
    for e in t["entries"]:
        w, h = e["w"], e["h"]
        if w == 0 or h == 0 or w > 4096 or h > 4096:
            continue
        if forced:
            yield e, w, h, run(forced_state, e)
            continue
        own = entry_bank(t, e)
        rgba = run(state(own), e)
        if nbanks > 1 and not any(rgba):
            for b in range(nbanks):
                if b == own:
                    continue
                alt = run(state(b), e)
                if any(alt):
                    rgba = alt
                    break
        yield e, w, h, rgba


def cmd_decode(chrfile, outdir):
    data, t = load(chrfile)
    cw = t["canvas_w"]
    canvas = compose_canvas(data, t)
    idx = unswizzle8(canvas, cw, t["canvas_h"])
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    write_png(out / "_canvas_ct32.png", cw, t["canvas_h"], bytes(canvas))
    gray = b"".join(bytes((v, v, v, 255)) for v in idx)
    write_png(out / "_atlas_index.png", cw * 2, t["canvas_h"] * 2, gray)
    n = 0
    for e, w, h, rgba in decode_entries(data, t):         # per-entry bank
        write_png(out / f"{e['i']:02d}_{e['name']}.png", w, h, rgba)
        n += 1
    note = " (decompressed from LZSS)" if t.get("compressed") else ""
    print(f"{n} entries -> {out}{note}")


def cmd_export_palettes(chrfile, outdir):
    data, t = load(chrfile)
    _refuse_if_compressed(t, "export-palettes")
    canvas = compose_canvas(data, t)
    out = Path(outdir)
    out.mkdir(parents=True, exist_ok=True)
    for (px, py), names in sorted(referenced_tiles(t).items()):
        pal = clut_at(canvas, t["canvas_w"], px, py)
        rgba = b"".join(bytes(p) for p in pal)
        tag = sorted(names)[0][:24]
        write_png(out / f"pal_{px:03d}_{py:03d}__{tag}.png", 16, 16, rgba)
    print(f"{len(referenced_tiles(t))} palette tiles -> {out}")
    print("edit them (keep 16x16, 8-bit RGBA), then run import-palettes")


def cmd_import_palettes(chrfile, paldir, outfile):
    data, t = load(chrfile)
    _refuse_if_compressed(t, "import-palettes")
    buf = bytearray(data)
    n = 0
    for p in sorted(Path(paldir).glob("pal_*_*.png")):
        px, py = int(p.stem.split("_")[1]), int(p.stem.split("_")[2])
        w, h, rgba = read_png(p)
        if (w, h) != (16, 16):
            raise ChrError(f"{p.name}: must stay 16x16 (one pixel per palette entry)")
        pal = [tuple(rgba[i * 4:i * 4 + 4]) for i in range(256)]
        write_clut(buf, t, px, py, pal)
        n += 1
    Path(outfile).write_bytes(buf)
    print(f"{n} palette tiles imported -> {outfile}")


def cmd_import_entry(chrfile, name, pngfile, outfile):
    """EXPERIMENTAL: repaint a paletted texture. Pixels are quantized to the
    entry's existing 256-color palette (nearest color); palette unchanged."""
    data, t = load(chrfile)
    _refuse_if_compressed(t, "import-entry")
    matches = [e for e in t["entries"] if e["name"] == name and e["fmt"] == PSMT8]
    if not matches:
        raise ChrError(f"no 256-colour entry named {name!r}; run decode to list names")
    e = matches[0]
    w, h, rgba = read_png(pngfile)
    if (w, h) != (e["w"], e["h"]):
        raise ChrError(f"size mismatch: entry is {e['w']}x{e['h']}, png is {w}x{h}")
    canvas = compose_canvas(data, t)
    cw = t["canvas_w"]
    pal = clut_at(canvas, cw, e["palx"], e["paly"])
    buf = bytearray(data)
    cache = {}
    for y in range(h):
        for x in range(w):
            px = tuple(rgba[(y * w + x) * 4:(y * w + x) * 4 + 4])
            if px not in cache:
                cache[px] = min(range(256), key=lambda i: (
                    (pal[i][0] - px[0]) ** 2 + (pal[i][1] - px[1]) ** 2
                    + (pal[i][2] - px[2]) ** 2 + (pal[i][3] - px[3]) ** 2))
            coff = swizzle8_offset(cw, e["x"] + x, e["y"] + y)
            # coff is a byte offset in canvas space; word -> canvas (x,y),
            # low 2 bits pick the byte within the CT32 word
            foff = canvas_file_offset(t, (coff // 4) % cw, coff // (cw * 4))
            if foff is None:
                raise ChrError("pixel outside strips — corrupt entry rect?")
            buf[foff + (coff & 3)] = cache[px]
    others = [o["name"] for o in t["entries"]
              if o is not e and not (o["x"] + o["w"] <= e["x"] or e["x"] + e["w"] <= o["x"]
                                     or o["y"] + o["h"] <= e["y"] or e["y"] + e["h"] <= o["y"])]
    if others:
        print(f"note: region overlaps entries {sorted(set(others))} — they share pixels")
    Path(outfile).write_bytes(buf)
    print(f"repainted {name} -> {outfile}")


# ---------------------------------------------------------------------------
# worked recolors (the pink mods)
# ---------------------------------------------------------------------------

def _rot(r, g, b, hue, smin=0.0, sboost=1.1, lboost=1.0):
    _h, l, s = colorsys.rgb_to_hls(r / 255, g / 255, b / 255)
    nr, ng, nb = colorsys.hls_to_rgb(hue, min(1.0, l * lboost),
                                     min(1.0, max(s * sboost, smin)))
    return int(nr * 255), int(ng * 255), int(nb * 255)


def _is_blue(r, g, b):
    return (b > 140 and b > r + 40 and g > r) or (b > 90 and b > r + 30 and b >= g)


def _is_warm_dark(r, g, b):
    mx = max(r, g, b)
    return mx <= 165 and mx >= 25 and r > g and g >= b - 6 and r - b >= 15


def recolor(data, hue, mode):
    """mode 'blue': band-filter every referenced tile (KOS-MOS).
    mode 'warm': name policy — hair/matu-only tiles fully, face tiles by
    warm-dark band, everything else untouched (Shion)."""
    if xcpack.parse_header(data).compressed:
        raise ChrError("recolor: LZSS-compressed package (field map) — in-place "
                       "edits are only possible on stored packages")
    buf = bytearray(data)
    t = parse_txy(data, *parse_chr(data)["txy"])
    edits = 0
    for (px, py), names in sorted(referenced_tiles(t).items()):
        low = {n.lower() for n in names}
        if mode == "warm":
            hairish = all(("hair" in n or "matu" in n) for n in low)
            facey = any("face" in n for n in low)
            if not hairish and not facey:
                continue
        for off in tile_file_offsets(t, px, py):
            for i in range(off, off + 64, 4):
                r, g, b, a = buf[i:i + 4]
                if mode == "blue":
                    if _is_blue(r, g, b):
                        buf[i], buf[i + 1], buf[i + 2] = _rot(r, g, b, hue)
                        edits += 1
                elif hairish:
                    if (r, g, b, a) != (0, 0, 0, 0):
                        buf[i], buf[i + 1], buf[i + 2] = _rot(r, g, b, hue, 0.35, 1.5, 1.12)
                        edits += 1
                elif _is_warm_dark(r, g, b):
                    buf[i], buf[i + 1], buf[i + 2] = _rot(r, g, b, hue, 0.35, 1.5)
                    edits += 1
    return bytes(buf), edits


# ---------------------------------------------------------------------------
# ISO plumbing: every location comes from the disc's own X3.00/X3.10/X3.20
# index (disc.Disc), so these work on USA, the May 2006 prototype and Japan.
# lba/Lba0.txt is kept only as a test oracle (lba_rows, self_test).
# ---------------------------------------------------------------------------

def _lba_note(lba_dir):
    if lba_dir:
        print(f"note: --lba {lba_dir} is ignored: locations now come from the disc's own index "
              "(lba/ is kept only as a test oracle)", file=sys.stderr)


def _open(isopath, writable=False):
    from disc import Disc
    try:
        return Disc(isopath, writable=writable)
    except ValueError as e:
        sys.exit(f"{isopath}: {e}")


def lba_rows(lba_dir=None):
    """lower-case path -> (offset past X3.00, size, path) from a USA Lba0.txt; test oracle only."""
    rows = {}
    lba = Path(lba_dir) if lba_dir else HERE / "lba"
    for line in (lba / "Lba0.txt").read_text().splitlines():
        p = line.strip().split("|")
        if len(p) == 4:
            rows[p[3].lower()] = (int(p[0], 16), int(p[1], 16), p[3])
    return rows


def cmd_iso_extract(isopath, discpath, outfile, lba_dir=None):
    _lba_note(lba_dir)
    with _open(isopath) as d:
        hit = d.lookup(discpath)
        if hit is None:
            sys.exit(f"{discpath} is not in the index of {Path(isopath).name}")
        data = d.read_entry(hit[1])
    Path(outfile).write_bytes(data)
    print(f"{discpath} ({len(data)} bytes) -> {outfile}")


def cmd_iso_patch(isopath, discpath, infile, lba_dir=None):
    """Same-size write in place (verified). Different sizes, Disc 1 + Disc 2 pairs and
    copies go through cli.py patch (patch.py)."""
    from disc import DiscError
    _lba_note(lba_dir)
    new = Path(infile).read_bytes()
    with _open(isopath, writable=True) as d:
        hit = d.lookup(discpath)
        if hit is None:
            sys.exit(f"{discpath} is not in the index of {Path(isopath).name}")
        e = hit[1]
        if len(new) != e.size:
            sys.exit(f"size mismatch: slot is {e.size} bytes, file is {len(new)} — only same-size "
                     "edits here (cli.py patch handles other sizes, with --grow)")
        try:
            d.write_entry(e, new)
        except DiscError as ex:
            sys.exit(str(ex))
    print(f"patched {discpath} in {isopath} (verified)")


def cmd_iso_sweep(isopath, match, mode, hue, lba_dir=None):
    """Recolor every .chr whose path contains ``match``, in place, every chain of the image."""
    from disc import DiscError
    if mode not in ("blue", "warm"):
        sys.exit("mode must be 'blue' or 'warm'")
    _lba_note(lba_dir)
    total = files = 0
    with _open(isopath, writable=True) as d:
        todo = sorted({e.path: e for _, e in d.entries()
                       if match.lower() in e.path.lower() and e.path.lower().endswith(".chr")
                       and e.size > 0}.values(), key=lambda e: e.path.lower())
        for e in todo:
            data = d.read_entry(e)
            try:
                new, edits = recolor(data, hue, mode)
            except (ChrError, xcpack.XcError) as ex:
                print(f"  skip {e.path}: {ex}")
                continue
            if not edits:
                print(f"  {e.path}: nothing matched")
                continue
            try:
                d.write_entry(e, new)          # same size; reads back
            except DiscError as ex:
                print(f"  skip {e.path}: {ex}")
                continue
            print(f"  {e.path}: {edits} palette words")
            total += edits
            files += 1
    print(f"{files} files, {total} palette words recolored (verified)")


def add_commands(subparsers):
    """Nothing to register: cli.py registers chr-decode ... chr-iso-sweep itself."""


def self_test():
    """ISO plumbing on a synthetic image and, with XS3_D1 set, read-only on
    the real Disc 1 (index vs the lba/Lba0.txt oracle)."""
    import contextlib
    import io
    import os
    import tempfile
    import disc as disc_mod
    ok = True

    def check(cond, msg):
        nonlocal ok
        print(("ok    " if cond else "FAIL  ") + msg)
        ok &= bool(cond)

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        p = td / "syn.iso"
        disc_mod._synthetic_image(p)
        with contextlib.redirect_stdout(io.StringIO()):
            cmd_iso_extract(str(p), "\\mnu\\us\\font0.bin", str(td / "f.bin"))
        check((td / "f.bin").read_bytes() == bytes(range(256)) * 10, "iso-extract through the disc's index")
        (td / "g.bin").write_bytes(bytes(255 - (i % 256) for i in range(2560)))
        with contextlib.redirect_stdout(io.StringIO()):
            cmd_iso_patch(str(p), "mnu/us/font0.bin", str(td / "g.bin"))
        with disc_mod.Disc(p) as d:
            check(d.read("mnu\\us\\font0.bin") == (td / "g.bin").read_bytes(), "iso-patch same size, read back")
        (td / "h.bin").write_bytes(b"x")
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                cmd_iso_patch(str(p), "mnu/us/font0.bin", str(td / "h.bin"))
            check(False, "iso-patch refuses a different size")
        except SystemExit:
            check(True, "iso-patch refuses a different size")
    d1 = os.environ.get("XS3_D1")
    if d1:
        with disc_mod.Disc(d1) as d:
            x300 = d.readers[0].sizes[0]
            want = lba_rows()
            got = {e.path.lower() if e.path.startswith("\\") else "\\" + e.path.lower():
                   (e.byte_offset - x300, e.size) for _, e in d.entries(0)}
            same = sum(1 for k, (o, sz, _) in want.items() if got.get(k) == (o, sz))
            check(same == len(want), f"D1: index == lba/Lba0.txt oracle for {same}/{len(want)} rows")
            kos = [e for _, e in d.entries() if "c3kosmos00.chr" in e.path.lower()]
            check(len(kos) == 1 and recolor(d.read_entry(kos[0]), 0.92, "blue")[1] > 0,
                  "D1: C3kosmos00.chr found by index and recolors (sweep input)")
    else:
        print("SKIP  disc checks (set XS3_D1)")
    print("self-test", "passed" if ok else "FAILED")
    return 0 if ok else 1


# ---------------------------------------------------------------------------

def main():
    try:
        _main()
    except (ChrError, xcpack.XcError) as exc:
        sys.exit(f"chrtex: {exc}")


def _main():
    a = sys.argv[1:]
    if not a:
        sys.exit(__doc__)
    cmd = a[0]
    if cmd == "--self-test":
        sys.exit(self_test())
    if cmd == "decode":
        cmd_decode(a[1], a[2])
    elif cmd == "export-palettes":
        cmd_export_palettes(a[1], a[2])
    elif cmd == "import-palettes":
        cmd_import_palettes(a[1], a[2], a[3])
    elif cmd == "import-entry":
        cmd_import_entry(a[1], a[2], a[3], a[4])
    elif cmd in ("pink-kosmos", "pink-shion"):
        hue = float(a[3]) if len(a) > 3 else 0.92
        data = Path(a[1]).read_bytes()
        new, edits = recolor(data, hue, "blue" if cmd == "pink-kosmos" else "warm")
        Path(a[2]).write_bytes(new)
        print(f"{edits} palette words -> {a[2]}")
    elif cmd == "iso-extract":
        cmd_iso_extract(a[1], a[2], a[3])
    elif cmd == "iso-patch":
        cmd_iso_patch(a[1], a[2], a[3])
    elif cmd == "iso-sweep":
        preset = {"kosmos": ("kosmos", "blue"), "shion": ("shion", "warm")}.get(a[2])
        if not preset:
            sys.exit("sweep target must be 'kosmos' or 'shion' "
                     "(use cli.py chr-iso-sweep for arbitrary --match/--mode)")
        cmd_iso_sweep(a[1], preset[0], preset[1], float(a[3]) if len(a) > 3 else 0.92)
    else:
        sys.exit(f"unknown command {cmd}\n{__doc__}")


if __name__ == "__main__":
    main()
