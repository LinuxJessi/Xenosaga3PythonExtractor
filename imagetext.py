"""imagetext.py — export / import the localized images (pictures with text burned in).

New for this kit (2026-11-20). A full language pack also has to translate the
pictures that carry text. This module finds them on a disc through the disc's own
index (disc.Disc), exports each as an editable PNG with a manifest, and re-encodes
the edited PNGs into same-format bytes, returned as {disc path: bytes} for the
patch step (patch.py, another module, writes them; nothing here writes an ISO).

What counts as localized (``collect``; ``lang`` = the disc's language folder,
region.disc_lang):

    kind  where
    jpg   jpg\\<lang>\\*.jpg (680 dtimg_* database pictures on US); on a build whose
          jpg\\ has no language folder (JP), the same family sits at the root:
          jpg\\dtimg_*.jpg
    jpg   mnu\\<lang>\\*.jpg (gameov1, wall); mnu\\syno\\*.jpg and mnu\\intm\\*.jpg
          (text burned in, 0/71 and 0/10 identical US vs JP); mnu\\pse\\ep1\\
          001_000020_02.jpg and jpg\\mcimg_7255/7270/8745/8755/8840 (differ by
          region, SYNTHESIS M28)
    png   mnu\\<lang>\\*.png (title1, syno), mov\\<lang>\\*.png (w09)
    xtx   mnu\\<lang>\\*.xtx (window0/1/2, titleobj), mg1\\<lang>\\*.xtx (picture)
          through xtx_encode (window sheets get statfont.BINDINGS)
    tm2   mnu\\pse\\<lang>\\logo_*.tm2, or mnu\\pse\\logo_*.tm2 without the folder (JP)
    txy   the textures embedded in ef\\esp\\<lang>\\*.esp, ef\\esd\\<lang>\\*.esd,
          ef\\map\\<lang>\\*.esp; on JP ef\\esp\\default|cfdef.esp, ef\\esd\\jp\\*.esd
          and the 40 ef\\map\\*.esp whose US copies sit in ef\\map\\us\\ (EF_MAP_US).
          Each PSMT8 / PSMT4 entry of each txy record (xcpack.iter_txy_records,
          chrtex.parse_txy / decode_entries, read only) is one PNG.

Export (``image-export --iso D.iso --out DIR``): DIR/manifest.json plus one PNG per
item under DIR/<disc path>.png (txy entries: DIR/<disc path>/<record>/<i>_<name>.png;
xtx also the index PNG and the palette-plan sidecar). Each manifest row:
{path, kind, format, dims, sha1 (of the disc file), png, png_sha1, [record, entry]}.

Import (``image-import --iso D.iso --dir DIR [--out OUT]``): every PNG whose sha1
still equals png_sha1 is skipped; the others are re-encoded:

* jpg: same dimensions, the original's chroma subsampling, baseline, optimized
  Huffman tables, JFIF only (the retail files mix standard and optimized tables,
  4:4:4 and 4:2:0); the quality is the highest 1-100 whose output fits the budget
  (``--budget allocation`` = the bytes the entry may occupy in place,
  Disc.allocation, the default; ``size`` = the original file size). If even
  quality 1 does not fit, the item is reported as unfit and not returned;
* png: RGBA 8-bit like the retail files, IDAT split in 8192-byte chunks as they are,
  zlib level 9 with per-row adaptive filters; same budget rule;
* xtx: xtx_encode.import_png with the sidecar (same size);
* tm2: 32-bit TIM2, alpha back to 0..0x80 (same size; an unchanged alpha keeps its
  stored byte);
* txy: pixels that changed are quantized to the entry's own CLUT (PSMT8 256 or PSMT4
  16 colours) and written into the record in place (same size); unchanged pixels
  keep their index.

patch.py integration: ``files, report = imagetext.import_dir(disc, Path(DIR),
budget="allocation")`` gives {disc path: bytes}; the keys are the disc's own index
paths (as Disc.read takes them), the bytes fit Disc.allocation(path) for
jpg/png and equal the original size for xtx/tm2/txy, so Disc.write_entry(path,
data) applies each in place. ``report["unfit"]`` lists items that would need
Disc.append_entry instead (not done here). ``--out OUT`` writes the same set to
OUT/files/<path> plus OUT/image-import.json; ``patch --iso D1 --iso D2 --tree
OUT/files --out DIR`` then writes them into copies of the discs.

NOT verified in PCSX2: no re-encoded JPEG/PNG/XTX has been booted; the engine's
JPEG and PNG decoders are only known to accept what the retail discs contain.
"""
from __future__ import annotations

import hashlib
import io
import json
import struct
import sys
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import numpy as np
import PIL
from PIL import Image, JpegImagePlugin

import xtx_encode as XE

# the 40 ef\map effect files the US build keeps under ef\map\us\ (Disc 1 + Disc 2);
# a build without the language folder (JP) has them at ef\map\ (SYNTHESIS: dropped dirs)
EF_MAP_US = tuple(f"ef{n}.esp" for n in (
    1010, 1150, 1210, 1218, 1220, 1240, 1248, 1410, 1430, 1438, 1440, 1630, 2110, 2200,
    2310, 2318, 2320, 2328, 2410, 2418, 2610, 2710, 2718, 2770, 2778, 2780, 2788, 2910,
    2918, 3110, 3278, 3410, 3710, 3830, 3838, 4010, 4310, 4340, 4370, 4450))
EF_ESP_US = ("default.esp", "cfdef.esp")
REGION_VARIANT = ("mnu\\pse\\ep1\\001_000020_02.jpg",) + tuple(
    f"jpg\\mcimg_{n}.jpg" for n in (7255, 7270, 8745, 8755, 8840))
PNG_CHUNK = 8192


class ImageTextError(ValueError):
    pass


@dataclass
class Item:
    path: str            # the disc index path (lower case, backslashes, no leading \)
    kind: str            # jpg png xtx tm2 txy
    record: Optional[int] = None     # txy: record offset inside the file
    entry: Optional[int] = None      # txy: entry index
    name: str = ""                   # txy: record/entry label


def _paths(disc) -> List[str]:
    return [e.path.replace("/", "\\").lstrip("\\").lower() for _c, e in disc.entries()]


def collect(disc, lang: Optional[str] = None) -> List[Item]:
    """Every localized picture of this disc (see the module docstring)."""
    from region import disc_lang
    lang = lang or disc_lang(disc)
    allp = sorted(set(_paths(disc)))
    have = set(allp)
    L = f"\\{lang}\\"
    files: List[Tuple[str, str]] = []

    def add(p, kind):
        if p in have and (p, kind) not in files:
            files.append((p, kind))

    jpg_lang = [p for p in allp if p.startswith(f"jpg{L}") and p.endswith(".jpg")]
    for p in jpg_lang or [p for p in allp if p.startswith("jpg\\dtimg_") and p.endswith(".jpg")]:
        add(p, "jpg")
    for p in allp:
        ext = p.rsplit(".", 1)[-1]
        if p.startswith(f"mnu{L}") and ext in ("jpg", "png", "xtx"):
            add(p, ext)
        elif p.startswith(("mnu\\syno\\", "mnu\\intm\\")) and ext == "jpg":
            add(p, "jpg")
        elif p.startswith(f"mov{L}") and ext == "png":
            add(p, "png")
        elif p.startswith(f"mg1{L}") and ext == "xtx":
            add(p, "xtx")
        elif p.startswith("mnu\\pse\\") and ext == "tm2" and "logo_" in p:
            if p.startswith(f"mnu\\pse{L}") or "\\" not in p[len("mnu\\pse\\"):]:
                add(p, "tm2")
    for p in REGION_VARIANT:
        add(p, "jpg")
    ef = [p for p in allp if p.startswith((f"ef\\esp{L}", f"ef\\esd{L}", f"ef\\map{L}"))]
    if not any(p.startswith(f"ef\\map{L}") for p in allp):
        ef += [f"ef\\map\\{n}" for n in EF_MAP_US if f"ef\\map\\{n}" in have]
    if not any(p.startswith(f"ef\\esp{L}") for p in allp):
        ef += [f"ef\\esp\\{n}" for n in EF_ESP_US if f"ef\\esp\\{n}" in have]
    items = [Item(p, k) for p, k in files]
    for p in ef:
        items += _txy_items(p, disc.read(p))
    return items


def _txy_items(path: str, data: bytes) -> List[Item]:
    import chrtex
    import xcpack
    out = []
    for off, size, name in xcpack.iter_txy_records(data):
        try:
            t = chrtex.parse_txy(data, off, size)
        except chrtex.ChrError:
            continue
        for e in t["entries"]:
            if e["fmt"] in (chrtex.PSMT8, chrtex.PSMT4) and 0 < e["w"] <= 4096 and 0 < e["h"] <= 4096:
                out.append(Item(path, "txy", off, e["i"], f"{name}/{e['i']:02d}_{e['name']}"))
    return out


def _safe(name: str) -> str:
    return "".join(c if c.isalnum() or c in "._-" else "_" for c in name)


def _png_rel(it: Item) -> str:
    base = it.path.replace("\\", "/")
    if it.kind == "txy":
        rec, ent = it.name.split("/", 1)
        return f"{base}/{it.record:06x}_{_safe(rec)}/{_safe(ent)}.png"
    return base + ".png"


def _sha1(b: bytes) -> str:
    return hashlib.sha1(b).hexdigest()


# --------------------------------------------------------------------- txy

def _txy(data: bytes, off: int):
    import chrtex
    import xcpack
    for o, size, _n in xcpack.iter_txy_records(data):
        if o == off:
            return chrtex.parse_txy(data, o, size)
    raise ImageTextError(f"no txy record at {off:#x}")


def _txy_entry(data: bytes, off: int, i: int):
    import chrtex
    t = _txy(data, off)
    for e, w, h, rgba in chrtex.decode_entries(data, t):
        if e["i"] == i:
            return t, e, np.frombuffer(rgba, np.uint8).reshape(h, w, 4)
    raise ImageTextError(f"no entry {i} in the txy record at {off:#x}")


def _txy_import(buf: bytearray, off: int, i: int, new: np.ndarray) -> int:
    """Quantize changed pixels to the entry's CLUT and write them in place."""
    import chrtex
    t, e, ref = _txy_entry(bytes(buf), off, i)
    if t["banks"]:
        raise ImageTextError("multi-bank txy records are not written by this importer")
    if new.shape != ref.shape:
        raise ImageTextError(f"picture {new.shape[1]}x{new.shape[0]} != entry {e['w']}x{e['h']}")
    canvas = chrtex.compose_canvas(bytes(buf), t)
    cw = t["canvas_w"]
    if e["fmt"] == chrtex.PSMT8:
        pal = np.array(chrtex.clut_at(canvas, cw, e["palx"], e["paly"]), np.uint8)
    else:
        pal = np.array(chrtex.clut16_at(canvas, cw, e["palx"], e["paly"]), np.uint8)
    changed = np.argwhere((new != ref).any(-1))
    if not len(changed):
        return 0
    px = new[changed[:, 0], changed[:, 1]]
    k, _ = XE._nearest(pal, px)
    for (y, x), v in zip(changed.tolist(), k.tolist()):
        X, Y = e["x"] + x, e["y"] + y
        if e["fmt"] == chrtex.PSMT8:
            coff = chrtex.swizzle8_offset(cw, X, Y)
            foff = chrtex.canvas_file_offset(t, (coff // 4) % cw, coff // (cw * 4))
            if foff is None:
                raise ImageTextError("pixel outside the record's strips")
            buf[foff + (coff & 3)] = v
        else:
            coff, sh = chrtex.swizzle4_offset(cw, X, Y)
            foff = chrtex.canvas_file_offset(t, (coff // 4) % cw, coff // (cw * 4))
            if foff is None:
                raise ImageTextError("pixel outside the record's strips")
            b = foff + (coff & 3)
            buf[b] = (buf[b] & (0xF0 >> sh)) | (v << sh)
    return len(changed)


# ------------------------------------------------------------- tm2 / png

def _tm2_rgba(data: bytes) -> np.ndarray:
    import tm2_decode
    hdr, rgba = tm2_decode.decode(data)
    return np.frombuffer(rgba, np.uint8).reshape(hdr.height, hdr.width, 4)


def _tm2_encode(data: bytes, new: np.ndarray) -> bytes:
    import tm2_decode
    hdr = tm2_decode.parse_header(data)
    off = 0x10 + hdr.header_size
    n = hdr.width * hdr.height * 4
    if new.shape != (hdr.height, hdr.width, 4):
        raise ImageTextError(f"picture {new.shape[1]}x{new.shape[0]} != tm2 {hdr.width}x{hdr.height}")
    old = np.frombuffer(data[off:off + n], np.uint8).reshape(new.shape)
    out = new.astype(np.uint8).copy()
    a = new[..., 3].astype(np.int32)
    keep = np.minimum(old[..., 3].astype(np.int32) * 2, 255) == a
    out[..., 3] = np.where(keep, old[..., 3], np.where(a >= 255, 0x80, (a + 1) // 2)).astype(np.uint8)
    return data[:off] + out.tobytes() + data[off + n:]


def png_encode(rgba: np.ndarray, level: int = 9) -> bytes:
    """RGBA 8-bit PNG, adaptive per-row filter, IDAT in 8192-byte chunks."""
    h, w, _ = rgba.shape
    a = rgba.astype(np.int16)
    raw = bytearray()
    prev = np.zeros((w * 4,), np.int16)
    for y in range(h):
        row = a[y].reshape(-1)
        left = np.concatenate([np.zeros(4, np.int16), row[:-4]])
        upleft = np.concatenate([np.zeros(4, np.int16), prev[:-4]])
        p = left + prev - upleft
        pa, pb, pc = np.abs(p - left), np.abs(p - prev), np.abs(p - upleft)
        paeth = np.where((pa <= pb) & (pa <= pc), left, np.where(pb <= pc, prev, upleft))
        cands = [row, row - left, row - prev, row - ((left + prev) >> 1), row - paeth]
        enc = [(c & 0xFF).astype(np.uint8) for c in cands]
        cost = [np.abs(e.astype(np.int8).astype(np.int32)).sum() for e in enc]
        f = int(np.argmin(cost))
        raw.append(f)
        raw += enc[f].tobytes()
        prev = row
    z = zlib.compress(bytes(raw), level)

    def chunk(tag, payload):
        return struct.pack(">I", len(payload)) + tag + payload + struct.pack(">I", zlib.crc32(tag + payload))
    out = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
    for i in range(0, len(z), PNG_CHUNK):
        out += chunk(b"IDAT", z[i:i + PNG_CHUNK])
    return out + chunk(b"IEND", b"")


def restart_interval(jpeg: bytes) -> int:
    """The DRI restart interval (MCUs between RSTn markers) of a JPEG, 0 if none.
    Only the header segments before the first SOS are read."""
    i = 2
    while i + 4 <= len(jpeg) and jpeg[i] == 0xFF:
        m = jpeg[i + 1]
        if m == 0xFF:
            i += 1
            continue
        n = struct.unpack_from(">H", jpeg, i + 2)[0]
        if m == 0xDD and n == 4 and i + 6 <= len(jpeg):
            return struct.unpack_from(">H", jpeg, i + 4)[0]
        if m == 0xDA:
            break
        i += 2 + n
    return 0


def jpeg_fit(rgb: Image.Image, original: bytes, budget: int) -> Tuple[Optional[bytes], int]:
    """(jpeg bytes, quality) of the highest quality that fits ``budget``; (None, 0)
    when quality 1 does not fit. The original's restart interval (DRI + RSTn
    markers; 13 of the 769 USA JPEGs, 12 on JP, have one) is kept: whether the
    engine's decoder needs them is unknown, so the output keeps the same shape."""
    sub = JpegImagePlugin.get_sampling(Image.open(io.BytesIO(original)))
    sub = sub if sub in (0, 1, 2) else 2
    ri = restart_interval(original)
    extra = {"restart_marker_blocks": ri} if ri else {}

    def enc(q):
        b = io.BytesIO()
        rgb.save(b, "JPEG", quality=q, subsampling=sub, optimize=True, progressive=False, **extra)
        out = b.getvalue()
        if restart_interval(out) != ri:
            raise ImageTextError(f"the JPEG encoder did not keep the restart interval {ri} "
                                 f"(Pillow {PIL.__version__}; restart_marker_blocks needs Pillow 10.0 or newer)")
        return out
    lo, hi, best = 1, 100, None
    first = enc(1)
    if len(first) > budget:
        return None, 0
    best = (first, 1)
    while lo <= hi:
        q = (lo + hi) // 2
        b = enc(q)
        if len(b) <= budget:
            best, lo = (b, q), q + 1
        else:
            hi = q - 1
    return best


# ----------------------------------------------------------------- export

def _decode(it: Item, data: bytes) -> np.ndarray:
    if it.kind == "jpg":
        return np.array(Image.open(io.BytesIO(data)).convert("RGB"))
    if it.kind == "png":
        return np.array(Image.open(io.BytesIO(data)).convert("RGBA"))
    if it.kind == "tm2":
        return _tm2_rgba(data)
    if it.kind == "txy":
        return _txy_entry(data, it.record, it.entry)[2]
    raise ImageTextError(it.kind)


def _bindings(path: str):
    if "\\window" in path:
        import statfont
        return statfont.BINDINGS
    return ()


def export(disc, out: Path, kinds: Optional[Iterable[str]] = None,
           progress: bool = False) -> dict:
    from region import disc_lang
    lang = disc_lang(disc)
    out.mkdir(parents=True, exist_ok=True)
    items = [it for it in collect(disc, lang) if not kinds or it.kind in kinds]
    rows = []
    cache: Dict[str, bytes] = {}
    for n, it in enumerate(items):
        data = cache.get(it.path) or disc.read(it.path)
        cache = {it.path: data}
        rel = _png_rel(it)
        dst = out / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        row = {"path": it.path, "kind": it.kind, "sha1": _sha1(data), "size": len(data), "png": rel}
        if it.kind == "xtx":
            stem = Path(it.path.replace("\\", "/")).name.rsplit(".", 1)[0]
            side = XE.export_sheet(data, dst.parent, stem, _bindings(it.path), it.path)
            row["png"] = str(Path(rel).parent / f"{stem}.png")
            row["index_png"] = str(Path(rel).parent / f"{stem}_index.png")
            row["sidecar"] = str(Path(rel).parent / f"{stem}.json")
            row["format"] = f"xtx fmt {side['fmt']:#x}"
            row["dims"] = side["size"]
            row["png_sha1"] = _sha1((out / row["png"]).read_bytes())
            row["index_sha1"] = _sha1((out / row["index_png"]).read_bytes())
        else:
            pix = _decode(it, data)
            if it.kind == "png":
                dst.write_bytes(data)                         # already a PNG: verbatim
            else:
                Image.fromarray(pix, "RGB" if pix.shape[2] == 3 else "RGBA").save(dst)
            row["format"] = {"jpg": "jpeg", "png": "png rgba8", "tm2": "tim2 32bpp",
                             "txy": "txy"}[it.kind]
            row["dims"] = [int(pix.shape[1]), int(pix.shape[0])]
            row["png_sha1"] = _sha1(dst.read_bytes())
            if it.kind == "jpg":
                im = Image.open(io.BytesIO(data))
                row["subsampling"] = JpegImagePlugin.get_sampling(im)
            if it.kind == "txy":
                row.update(record=it.record, entry=it.entry, name=it.name)
        rows.append(row)
        if progress and (n + 1) % 200 == 0:
            print(f"[image-export] {n + 1}/{len(items)}", flush=True)
    man = {"disc": str(getattr(disc, "path", "")), "lang": lang, "items": rows}
    (out / "manifest.json").write_text(json.dumps(man, indent=1))
    return man


# ----------------------------------------------------------------- import

@dataclass
class ImportResult:
    files: Dict[str, bytes] = field(default_factory=dict)
    changed: List[dict] = field(default_factory=list)
    unfit: List[dict] = field(default_factory=list)


def import_dir(disc, edit_dir: Path, budget: str = "allocation") -> Tuple[Dict[str, bytes], dict]:
    """Re-encode every edited PNG of an export directory. Returns ({disc path: bytes}, report)."""
    man = json.loads((edit_dir / "manifest.json").read_text())
    res = ImportResult()
    work: Dict[str, bytearray] = {}
    for row in man["items"]:
        path, kind = row["path"], row["kind"]
        png = edit_dir / row["png"]
        edited = png.exists() and _sha1(png.read_bytes()) != row["png_sha1"]
        if kind == "xtx" and not edited:
            ip = edit_dir / row["index_png"]
            edited = ip.exists() and _sha1(ip.read_bytes()) != row["index_sha1"]
            png = ip if edited else png
        if not edited:
            continue
        orig = disc.read(path)
        if _sha1(orig) != row["sha1"]:
            raise ImageTextError(f"{path}: the disc's file is not the one exported (sha1)")
        cur = work.setdefault(path, bytearray(orig))
        room = disc.allocation(path) if budget == "allocation" else len(orig)
        note = {"path": path, "kind": kind, "png": row["png"]}
        if kind == "jpg":
            im = Image.open(png).convert("RGB")
            if list(im.size) != row["dims"]:
                raise ImageTextError(f"{png}: {im.size} != {tuple(row['dims'])} (keep the size)")
            b, q = jpeg_fit(im, orig, room)
            if b is None:
                res.unfit.append({**note, "budget": room, "why": "quality 1 does not fit"})
                work.pop(path)
                continue
            work[path] = bytearray(b)
            note.update(quality=q, bytes=len(b), budget=room)
        elif kind == "png":
            rgba = np.array(Image.open(png).convert("RGBA"))
            if [rgba.shape[1], rgba.shape[0]] != row["dims"]:
                raise ImageTextError(f"{png}: size changed")
            b = png_encode(rgba)
            if len(b) > room:
                res.unfit.append({**note, "budget": room, "bytes": len(b)})
                work.pop(path)
                continue
            work[path] = bytearray(b)
            note.update(bytes=len(b), budget=room)
        elif kind == "xtx":
            side = json.loads((edit_dir / row["sidecar"]).read_text())
            b, rep = XE.import_png(bytes(cur), png, side)
            work[path] = bytearray(b)
            note.update(report=rep.line())
        elif kind == "tm2":
            rgba = np.array(Image.open(png).convert("RGBA"))
            work[path] = bytearray(_tm2_encode(bytes(cur), rgba))
        elif kind == "txy":
            rgba = np.array(Image.open(png).convert("RGBA"))
            n = _txy_import(cur, row["record"], row["entry"], rgba)
            note.update(entry=row["name"], pixels=n)
        res.changed.append(note)
    for path, b in work.items():
        b = bytes(b)
        if b != disc.read(path):
            res.files[path] = b
    report = {"changed": res.changed, "unfit": res.unfit,
              "files": {p: {"bytes": len(b), "sha1": _sha1(b)} for p, b in res.files.items()}}
    return res.files, report


# --------------------------------------------------------------------- CLI

def _cmd_export(a) -> int:
    from disc import Disc
    with Disc(a.iso) as d:
        man = export(d, Path(a.out), a.kind, progress=True)
    from collections import Counter
    c = Counter(r["kind"] for r in man["items"])
    print(f"lang {man['lang']}: {len(man['items'])} pictures ({dict(c)}) -> {a.out}")
    return 0


def _cmd_import(a) -> int:
    from disc import Disc
    with Disc(a.iso) as d:
        files, rep = import_dir(d, Path(a.dir), a.budget)
    for n in rep["changed"]:
        extra = (f" q{n['quality']} {n['bytes']}/{n['budget']} B" if "quality" in n
                 else f" {n['bytes']}/{n['budget']} B" if "bytes" in n else
                 f" {n.get('report', '')}{n.get('entry', '')}")
        print(f"  {n['kind']:4} {n['path']}{extra}")
    for n in rep["unfit"]:
        print(f"  UNFIT {n['path']}: {n}")
    if a.out:
        out = Path(a.out)
        for p, b in files.items():
            dst = out / "files" / Path(*p.split("\\"))
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(b)
        out.mkdir(parents=True, exist_ok=True)
        (out / "image-import.json").write_text(json.dumps(rep, indent=1))
    print(f"{len(files)} files re-encoded, {len(rep['unfit'])} unfit"
          + (f" -> {a.out}" if a.out else " (dry run; pass --out to write them)"))
    return 1 if rep["unfit"] else 0


def add_commands(subparsers) -> None:
    p = subparsers.add_parser("image-export", help="localized pictures (jpg/png/xtx/tm2/effect txy) "
                              "-> PNG + manifest")
    p.add_argument("--iso", required=True, help="disc image (read only)")
    p.add_argument("--out", required=True, help="folder for manifest.json and the PNGs")
    p.add_argument("--kind", action="append", choices=("jpg", "png", "xtx", "tm2", "txy"),
                   help="limit to these kinds (repeatable)")
    p.set_defaults(func=_cmd_export)
    p = subparsers.add_parser("image-import", help="edited PNGs -> re-encoded disc files "
                              "({path: bytes} for the patch step)")
    p.add_argument("--iso", required=True, help="the disc the export came from (read only)")
    p.add_argument("--dir", required=True, help="an image-export folder with edited PNGs")
    p.add_argument("--out", help="write OUT/files/<path> and OUT/image-import.json "
                   "(then 'patch --iso D1 --iso D2 --tree OUT/files --out ...')")
    p.add_argument("--budget", choices=("allocation", "size"), default="allocation",
                   help="jpg/png size limit: allocation (room before the next file, default) or the "
                        "original size")
    p.set_defaults(func=_cmd_import)


# --------------------------------------------------------------- self-test

def self_test() -> int:
    import os
    import tempfile
    bad = 0

    def check(c, msg):
        nonlocal bad
        print(("ok   " if c else "FAIL ") + msg)
        bad += 0 if c else 1

    rng = np.random.default_rng(1)
    img = rng.integers(0, 255, (37, 53, 4), dtype=np.uint8)
    b = png_encode(img)
    check((np.array(Image.open(io.BytesIO(b))) == img).all(), "png_encode round-trips RGBA")
    big = png_encode(np.zeros((300, 300, 4), np.uint8) + rng.integers(0, 255, (300, 300, 4), dtype=np.uint8))
    sizes = []
    i = 8
    while i < len(big):
        L = struct.unpack(">I", big[i:i + 4])[0]
        if big[i + 4:i + 8] == b"IDAT":
            sizes.append(L)
        i += 12 + L
    check(len(sizes) > 1 and all(s == PNG_CHUNK for s in sizes[:-1]), "png IDAT split at 8192 bytes")
    src = Image.fromarray(img[..., :3].copy())
    for ri in (0, 27):
        o = io.BytesIO()
        src.save(o, "JPEG", quality=90, **({"restart_marker_blocks": ri} if ri else {}))
        fit, q = jpeg_fit(src, o.getvalue(), 1 << 20)
        check(restart_interval(o.getvalue()) == ri and restart_interval(fit) == ri
              and (b"\xff\xdd" in fit) == bool(ri),
              f"jpeg_fit keeps the restart interval ({ri or 'none'}) of the original")

    for env in ("XS3_D1", "XS3_JP1"):
        iso = os.environ.get(env)
        if not iso or not Path(iso).exists():
            print(f"SKIP {env} not set")
            continue
        from disc import Disc
        from collections import Counter
        with Disc(iso) as d, tempfile.TemporaryDirectory() as td:
            td = Path(td)
            items = collect(d)
            c = Counter(it.kind for it in items)
            print(f"     {env}: {dict(c)}")
            if env == "XS3_D1":
                check(c["jpg"] == 680 + 2 + 71 + 10 + 6 and c["png"] == 3 and c["xtx"] == 5
                      and c["tm2"] == 3 and c["txy"] > 300,
                      "US D1 collect: 769 jpg, 3 png, 5 xtx, 3 tm2, >300 effect entries")
            else:
                check(c["jpg"] == 680 + 2 + 71 + 10 + 6 and c["png"] == 1 and c["xtx"] == 5
                      and c["tm2"] == 3, "JP D1 collect: 769 jpg (dtimg at the root), "
                      "1 png, 5 xtx, 3 tm2 (logos at the mnu\\pse root)")
            # a reduced export: everything but the 680 dtimg pictures (two kept)
            keep = [it for it in items if "dtimg_" not in it.path] + \
                   [it for it in items if "dtimg_" in it.path][:2]
            import imagetext as me
            orig_collect = me.collect
            me.collect = lambda disc, lang=None: keep
            try:
                man = export(d, td)
            finally:
                me.collect = orig_collect
            files, rep = import_dir(d, td)
            check(files == {} and not rep["unfit"], f"{env}: unmodified export ({len(man['items'])} "
                  "pictures) imports to no changed file")
            rows = {r["kind"]: r for r in man["items"]}
            for kind in ("jpg", "png", "xtx", "tm2", "txy"):
                r = rows.get(kind)
                if not r:
                    continue
                p = td / r["png"]
                im = Image.open(p)
                a = np.array(im.convert("RGBA" if kind != "jpg" else "RGB"))
                h, w = a.shape[:2]
                a[h // 4:h // 4 + max(1, h // 8), w // 4:w // 4 + max(1, w // 3)] = \
                    (255, 255, 255, 255)[:a.shape[2]]
                Image.fromarray(a).save(p)
            files, rep = import_dir(d, td)
            kinds = {n["kind"] for n in rep["changed"]}
            same = all(len(files[p]) == d.allocation(p) or len(files[p]) <= d.allocation(p) for p in files)
            fixed = all(len(files[n["path"]]) == len(d.read(n["path"]))
                        for n in rep["changed"] if n["kind"] in ("xtx", "tm2", "txy") and n["path"] in files)
            check(kinds == set(rows) and same and fixed and not rep["unfit"],
                  f"{env}: one edit per kind {sorted(kinds)} re-encodes; xtx/tm2/txy same size, "
                  "jpg/png within the allocation")
            for n in rep["changed"]:
                if n["kind"] == "jpg":
                    back = np.array(Image.open(io.BytesIO(files[n["path"]])).convert("RGB")).astype(float)
                    ed = np.array(Image.open(td / n["png"]).convert("RGB")).astype(float)
                    psnr = 10 * np.log10(255 ** 2 / max(1e-9, ((back - ed) ** 2).mean()))
                    check(psnr > 28, f"{env}: jpg {n['path']} q{n['quality']} "
                          f"{n['bytes']}/{n['budget']} B, PSNR {psnr:.1f} dB vs the edit")
                if n["kind"] == "png":
                    back = np.array(Image.open(io.BytesIO(files[n["path"]])).convert("RGBA"))
                    check((back == np.array(Image.open(td / n["png"]).convert("RGBA"))).all(),
                          f"{env}: png {n['path']} lossless ({n['bytes']}/{n['budget']} B)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(self_test())
