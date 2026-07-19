#!/usr/bin/env python3
"""chrtex.py — decode, edit, and re-import Xenosaga III character textures.

Works on the `txy` texture block embedded in `.chr` / `.wpn` / `.sme`
MR packages (format spec: docs/chr-txy-format.md). Pixels are PSMT8
indices swizzled into a PSMCT32 canvas; palettes are 16x16 CLUT tiles in
that same canvas. Because nothing is compressed, every edit is a
same-size in-place byte patch, both into the .chr and into the ISO.

Commands (see docs/MODDING-CHARACTERS.md for the walkthrough):

  decode <chr> <outdir>                 textures + canvas + palettes -> PNG
  export-palettes <chr> <outdir>        each CLUT tile -> editable 16x16 PNG
  import-palettes <chr> <dir> <out>     edited tile PNGs -> new .chr
  import-entry <chr> <name> <png> <out> repaint a texture (quantized, exp.)
  pink-kosmos <chr> <out> [hue]         worked example: blue-band recolor
  pink-shion <chr> <out> [hue]          worked example: warm-band + policy
  iso-extract <iso> <discpath> <out>    pull a file via the Lba tables
  iso-patch <iso> <discpath> <file>     write it back (size-checked+verified)
  iso-sweep <iso> kosmos|shion [hue]    recolor every matching .chr in an ISO

`<discpath>` is the in-game path as it appears in lba/Lba0.txt, e.g.
`\\mdl\\chr\\pc\\C3kosmos00.chr` (quote it in the shell).
"""
import colorsys
import struct
import sys
import zlib
from pathlib import Path

# module dir normally; PyInstaller's unpack dir in frozen release builds
# (lba/ ships as bundled data there — see packaging/xenosaga-extractor.spec)
HERE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))

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
    if data[:2] != b"Xc":
        sys.exit("not an Xc MR package")
    cnt = struct.unpack_from("<H", data, 0xC)[0]
    subs = {}
    for i in range(cnt):
        typ = data[0x10 + i * 4:0x14 + i * 4].rstrip(b"\x00").decode("latin1")
        off, sz = struct.unpack_from("<II", data, 0x40 + i * 8)
        subs[typ] = (off, sz)
    if "txy" not in subs:
        sys.exit(f"no txy sub-resource (has: {sorted(subs)})")
    return subs


def parse_txy(data, sub_off, _sub_size):
    txy = sub_off + 0x40                       # 0x40-byte pre-header
    if data[txy:txy + 4] != b"txy\x00":
        sys.exit("txy magic missing")
    tbl_off, = struct.unpack_from("<I", data, txy + 0x10)
    r0 = struct.unpack_from("<8I", data, txy + tbl_off)
    canvas_w, n_entries = r0[2], r0[6]
    strips, p = [], txy + tbl_off + 0x20
    while True:
        r = struct.unpack_from("<8I", data, p)
        if r[2] == 0 or r[3] == 0:
            break
        strips.append({"off": r[0], "gs_block": r[1], "w": r[2], "h": r[3]})
        p += 0x20
    entries = []
    base = strips[0]["off"] + txy - n_entries * 0x60
    for i in range(n_entries):
        b = base + i * 0x60
        gsaddr, fmt, w, h, x, y, cbp, flag, palx, paly = struct.unpack_from("<10I", data, b)
        name = data[b + 0x40:b + 0x60].split(b"\x00")[0].decode("latin1")
        entries.append({"i": i, "name": name, "fmt": fmt, "w": w, "h": h,
                        "x": x, "y": y, "cbp": cbp, "palx": palx, "paly": paly})
    return {"txy": txy, "canvas_w": canvas_w, "strips": strips, "entries": entries}


def strip_origin(t, s):
    page = s["gs_block"] // 32
    return (page % (t["canvas_w"] // 64)) * 64, (page // (t["canvas_w"] // 64)) * 32


def compose_canvas(data, t):
    W = t["canvas_w"]
    H = max(strip_origin(t, s)[1] + s["h"] for s in t["strips"])
    t["canvas_h"] = H
    canvas = bytearray(W * H * 4)
    for s in t["strips"]:
        x0, y0 = strip_origin(t, s)
        src = t["txy"] + s["off"] + 0x20
        for y in range(s["h"]):
            d = ((y0 + y) * W + x0) * 4
            canvas[d:d + s["w"] * 4] = data[src + y * s["w"] * 4:src + (y + 1) * s["w"] * 4]
    return canvas


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
            sys.exit(f"CLUT tile ({palx},{paly}) row {ey} outside all strips")
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
    tiles = {}
    for e in t["entries"]:
        tiles.setdefault((e["palx"], e["paly"]), set()).add(e["name"])
    return tiles


# ---------------------------------------------------------------------------
# decode / palette export / palette import / entry import
# ---------------------------------------------------------------------------

def load(path):
    data = Path(path).read_bytes()
    t = parse_txy(data, *parse_chr(data)["txy"])
    return data, t


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
    for e in t["entries"]:
        w, h, x0, y0 = e["w"], e["h"], e["x"], e["y"]
        rgba = bytearray(w * h * 4)
        if e["fmt"] == 0x13:
            pal = clut_at(canvas, cw, e["palx"], e["paly"])
            for y in range(h):
                irow = (y0 + y) * cw * 2 + x0
                for x in range(w):
                    rgba[(y * w + x) * 4:(y * w + x) * 4 + 4] = bytes(pal[idx[irow + x]])
        else:                                   # fmt 0: raw CT32 region
            for y in range(h):
                s = ((y0 + y) * cw + x0) * 4
                row = canvas[s:s + w * 4]
                for x in range(w):
                    r, g, b, a = row[x * 4:x * 4 + 4]
                    rgba[(y * w + x) * 4:(y * w + x) * 4 + 4] = bytes((r, g, b, min(a * 2, 255)))
        write_png(out / f"{e['i']:02d}_{e['name']}.png", w, h, bytes(rgba))
    print(f"{len(t['entries'])} entries -> {out}")


def cmd_export_palettes(chrfile, outdir):
    data, t = load(chrfile)
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
    buf = bytearray(data)
    n = 0
    for p in sorted(Path(paldir).glob("pal_*_*.png")):
        px, py = int(p.stem.split("_")[1]), int(p.stem.split("_")[2])
        w, h, rgba = read_png(p)
        if (w, h) != (16, 16):
            sys.exit(f"{p.name}: must stay 16x16 (one pixel per palette entry)")
        pal = [tuple(rgba[i * 4:i * 4 + 4]) for i in range(256)]
        write_clut(buf, t, px, py, pal)
        n += 1
    Path(outfile).write_bytes(buf)
    print(f"{n} palette tiles imported -> {outfile}")


def cmd_import_entry(chrfile, name, pngfile, outfile):
    """EXPERIMENTAL: repaint a paletted texture. Pixels are quantized to the
    entry's existing 256-color palette (nearest color); palette unchanged."""
    data, t = load(chrfile)
    matches = [e for e in t["entries"] if e["name"] == name and e["fmt"] == 0x13]
    if not matches:
        sys.exit(f"no paletted entry named {name!r}; run decode to list names")
    e = matches[0]
    w, h, rgba = read_png(pngfile)
    if (w, h) != (e["w"], e["h"]):
        sys.exit(f"size mismatch: entry is {e['w']}x{e['h']}, png is {w}x{h}")
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
                sys.exit("pixel outside strips — corrupt entry rect?")
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
# ISO plumbing (X3.01+X3.02 are contiguous: ISO byte = extent + Lba0 offset)
# ---------------------------------------------------------------------------

def _iso_x301_base(iso):
    iso.seek(16 * 2048)
    pvd = iso.read(2048)
    if pvd[1:6] != b"CD001":
        sys.exit("not an ISO9660 image")
    rext, = struct.unpack("<I", pvd[156 + 2:156 + 6])
    rsz, = struct.unpack("<I", pvd[156 + 10:156 + 14])
    iso.seek(rext * 2048)
    d = iso.read(rsz)
    off = 0
    while off < rsz:
        ln = d[off]
        if ln == 0:
            off = (off // 2048 + 1) * 2048
            continue
        nl = d[off + 32]
        if d[off + 33:off + 33 + nl].split(b";")[0] == b"X3.01":
            ext, = struct.unpack("<I", d[off + 2:off + 6])
            return ext * 2048
        off += ln
    sys.exit("X3.01 not found in ISO root")


def lba_rows(lba_dir=None):
    rows = {}
    lba = Path(lba_dir) if lba_dir else HERE / "lba"
    for line in (lba / "Lba0.txt").read_text().splitlines():
        p = line.strip().split("|")
        if len(p) == 4:
            rows[p[3].lower()] = (int(p[0], 16), int(p[1], 16), p[3])
    return rows


def cmd_iso_extract(isopath, discpath, outfile, lba_dir=None):
    row = lba_rows(lba_dir).get(discpath.lower())
    if not row:
        sys.exit(f"{discpath} not in Lba0.txt (only Lba0/X3.0x files supported)")
    off, sz, _ = row
    with open(isopath, "rb") as iso:
        base = _iso_x301_base(iso)
        iso.seek(base + off)
        Path(outfile).write_bytes(iso.read(sz))
    print(f"{discpath} ({sz} bytes) -> {outfile}")


def cmd_iso_patch(isopath, discpath, infile, lba_dir=None):
    row = lba_rows(lba_dir).get(discpath.lower())
    if not row:
        sys.exit(f"{discpath} not in Lba0.txt")
    off, sz, _ = row
    new = Path(infile).read_bytes()
    if len(new) != sz:
        sys.exit(f"size mismatch: slot is {sz} bytes, file is {len(new)} — "
                 "only same-size edits are supported")
    with open(isopath, "r+b") as iso:
        base = _iso_x301_base(iso)
        iso.seek(base + off)
        iso.write(new)
        iso.seek(base + off)
        if iso.read(sz) != new:
            sys.exit("read-back verification FAILED")
    print(f"patched {discpath} in {isopath} (verified)")


def cmd_iso_sweep(isopath, match, mode, hue, lba_dir=None):
    if mode not in ("blue", "warm"):
        sys.exit("mode must be 'blue' or 'warm'")
    total = files = 0
    with open(isopath, "r+b") as iso:
        base = _iso_x301_base(iso)
        for key, (off, sz, path) in sorted(lba_rows(lba_dir).items()):
            if match.lower() not in key or not key.endswith(".chr"):
                continue
            iso.seek(base + off)
            data = iso.read(sz)
            try:
                new, edits = recolor(data, hue, mode)
            except SystemExit as ex:
                print(f"  skip {path}: {ex}")
                continue
            if not edits:
                print(f"  {path}: nothing matched")
                continue
            iso.seek(base + off)
            iso.write(new)
            iso.seek(base + off)
            assert iso.read(sz) == new, f"read-back failed: {path}"
            print(f"  {path}: {edits} palette words")
            total += edits
            files += 1
    print(f"{files} files, {total} palette words recolored (verified)")


# ---------------------------------------------------------------------------

def main():
    a = sys.argv[1:]
    if not a:
        sys.exit(__doc__)
    cmd = a[0]
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
