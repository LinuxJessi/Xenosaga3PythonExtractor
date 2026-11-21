"""statfont.py — the HUD letter sprites of the window sheets: export, repaint, re-map.

New for this kit (2026-11-20). Episode III's battle/menu HUD labels that are not
drawn with font0/font1 come from a letter printer in the main executable that
picks 16-px cells out of the window sheets ``mnu\\xx\\window0/1/2.xtx`` (the three
sheets differ only in x 272-335, a portrait column; the letter cells are in all
three, so every edit is written to all three). Found in the USA executable
SLUS_213.89 (decompile: xenosaga3-decompiled/decompiled/slus):

    FUN_0023c588 / FUN_0023c620 / FUN_0023c688   string printers -> FUN_0023c2c0 per byte
    FUN_0023c2c0   one byte: '0'-'9' -> FUN_0023c6f8 (digit cells); else cell =
                   FUN_0023c168(byte), width = FUN_0023c210(byte); cell 0x40 = not drawn
    FUN_0023c168   byte -> cell:  'A'-'Z' -> 0-25 except 'W' -> 30;  'a'-'z' -> 32-57
                   (byte - 0x41);  0x21-0x3a through a 26-entry jump table at
                   VA 0x538d50 ('!' 31, '*' 22, '-' 27, '.' 29, '/' 26, ':' 28, rest 0x40);
                   everything else 0x40
    FUN_0023c210   width = s8 table at VA 0x538db8 [cell] (64 cells; 58-63 are 0)
    cell < 32      u = (cell & 15) * 16 (cell 31: u = 244), v = (cell >> 4) * 16,
                   palette TEX2 CBP = base*32 + 0x308
    cell >= 32     i = cell & 31: u = 768 + (i & 15) * 16, v = (i >> 4) * 16, CBP + 0x3c8
    FUN_0023c6f8   digit d: u = ((d + 9) % 10) * 13, v = 32, 13 x 17, CBP + 0x30c
    sprite         [u, u + width) x [v, v + 16) of the sheet's PSMT8 picture

``base`` is the VRAM page variable DAT_004c83a2 (0x1c0 / 0xc0). Read relative to the
sheet's base page in a 512-word (TBW 8) buffer (xtx_encode.cbp_xy), the three
palettes are the canvas tiles (0,112), (384,112) and (16,112) of the sheet as
xtx_encode and xtx_decode read it (pixels from 0x50, after the GS packet). The sheet
upload is FUN_001997d0 (2026-11-20, fifth pass): the XTX header is its descriptor, the
"format" field at +0x12 is the destination buffer width (8 = TBW 8) and the image goes
to page DAT_004c83a2, so the CBPs index the sheet's own canvas (engine_palettes.py has
every other window-sheet draw). The reading was first checked by the result: under those tiles every letter cell renders as a white glyph with a
dark outline exactly inside its [u, u+16) x [v, v+16) rect, the digits likewise,
and the gauge bar of FUN_0023cfc8 (CBP 0x328, uv 180,54-226,65) as a clean bar;
the tiles are byte-identical on the 384-word JP sheets.

What a translation can change (all same-size; nothing is relocated):

* the pixels of every cell (52 letters, 6 symbols, 10 digits) in all three sheets;
* the width byte of each cell (data at VA 0x538db8): proportional spacing;
* which of the seven existing case bodies a byte 0x21-0x3a (not the digits)
  jumps to (data at VA 0x538d50), i.e. a punctuation byte can be pointed at
  cell 22 / 26 / 27 / 28 / 29 / 31 or made invisible (0x40).

Bytes can NOT be pointed at new cells: the cell numbers are immediates in code, so
cells 58-63 stay unreachable and a new alphabet reuses existing letter cells (paint
a new letter into, say, the 'Q' cell and write that letter in the HUD strings as
byte 'Q'). ``statfont-import --letters`` takes that assignment and writes the
char -> byte map a text encoder needs (``charmap`` in its output JSON).

The Japanese executable (SLPS_256.40) has its own variant (FUN_0023aba8 classifier,
FUN_0023ac38 width, FUN_0023ace8 draw; same cell geometry and CBP 0x308): capitals
only, 'A'-'Z' but 'W' direct, 'W' and every byte 0x21-0x57 through a 55-entry jump
table at VA 0x537530, widths at VA 0x537610, cell 0x20 = not drawn, cells >= 0x20 are
never drawn (the JP sheets are 768 px wide, so the lowercase block at x >= 768 does not
exist). Both variants are found by signature (``discover``); the May 2006 prototype
carries the US variant 0xc8 lower.

    python cli.py statfont-export --iso D1.iso --out tr/statfont
    python cli.py statfont-import --iso D1.iso --dir tr/statfont --out tr/statfont-out \\
        [--letters tr/letters.json] [--font Some.ttf --px 15]

``statfont-import`` writes OUT/files/<disc path> for the three sheets and the boot
executable, plus OUT/statfont-out.json (``files`` sha1 list and ``charmap``); the
same {path: bytes} comes from ``build()`` for patch.py. Put them on the discs with

    python cli.py patch --iso D1.iso --iso D2.iso --tree tr/statfont-out/files --out OUT/

The window sheets are chain-0 objects (written on both discs). The executable
file is the boot executable of the --iso given (SLUS_213.89 for USA Disc 1);
Disc 2 boots its own byte-identical SLUS_214.17, and ``patch`` writes the same
change there too when both discs are given (refused if the two differ).
"""
from __future__ import annotations

import hashlib
import json
import struct
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
from PIL import Image, ImageDraw, ImageFont

import xtx_encode as XE

SHEETS = ("mnu\\xx\\window0.xtx", "mnu\\xx\\window1.xtx", "mnu\\xx\\window2.xtx")
CELLS = 64
CBP_UPPER, CBP_LOWER, CBP_DIGIT = 0x308, 0x3C8, 0x30C
TILE_UPPER, TILE_LOWER, TILE_DIGIT = XE.cbp_xy(CBP_UPPER), XE.cbp_xy(CBP_LOWER), XE.cbp_xy(CBP_DIGIT)
DIGIT_W, DIGIT_H, DIGIT_V = 13, 17, 32

# USA retail addresses (verified against the decompile); discover() finds them anywhere
US_ADDR = {"classify": 0x23C168, "width_fn": 0x23C210, "draw": 0x23C2C0, "digit": 0x23C6F8,
           "jump_table": 0x538D50, "width_table": 0x538DB8}
# first 5 instructions of the classifier (position independent), per printer variant:
# "us" = FUN_0023c168 (SLUS_213.89; also the May 2006 prototype), "jp" = FUN_0023aba8
# (SLPS_256.40: capitals only, 'W' and 0x21-0x57 through a 55-entry jump table at
# VA 0x537530, widths at VA 0x537610, cell 0x20 = not drawn)
CLASSIFY_SIGS = {"us": bytes.fromhex("0026040003260400bfff8324ff0062301a00422c"),
                 "jp": bytes.fromhex("0026040003260400bfff83241a00622c04004050")}
NONE_CELLS = {"us": 0x40, "jp": 0x20}
JUMP_FIRST = 0x21


def cell_rect(cell: int) -> Tuple[int, int]:
    """(u, v) of a letter cell in the sheet's PSMT8 picture."""
    if cell < 32:
        u = (cell & 15) * 16 + (4 if cell == 31 else 0)
        return u, (cell >> 4) * 16
    i = cell & 31
    return 768 + (i & 15) * 16, (i >> 4) * 16


def cell_tile(cell: int) -> Tuple[int, int]:
    return TILE_UPPER if cell < 32 else TILE_LOWER


def digit_rect(d: int) -> Tuple[int, int]:
    return ((d + 9) % 10) * DIGIT_W, DIGIT_V


# palette bindings for xtx_encode (index-space rects -> CLUT tile); rects are
# whole 16x16 cells (cell 31 shares row 1's last column, u 244..256)
BINDINGS: List[Tuple[int, int, int, int, Tuple[int, int]]] = (
    [(cell_rect(c)[0], cell_rect(c)[1], min(cell_rect(c)[0] + 16, 256 if c < 32 else 1024),
      cell_rect(c)[1] + 16, cell_tile(c)) for c in range(CELLS)]
    + [(0, DIGIT_V, 10 * DIGIT_W, DIGIT_V + DIGIT_H, TILE_DIGIT)])


class StatfontError(ValueError):
    pass


# ------------------------------------------------------------- executable

def _elf_tools():
    from region import read_va, va_to_offset, offset_to_va
    return read_va, va_to_offset, offset_to_va


def discover(elf: bytes) -> Optional[Dict[str, int]]:
    """Addresses of the printer in any executable, by the classifier's signature and
    the immediates of the instructions around it; None when the build has no printer.
    ``variant`` 0 = "us", 1 = "jp" (see CLASSIFY_SIGS)."""
    import capstone
    read_va, va_to_offset, offset_to_va = _elf_tools()
    for vi, (variant, sig) in enumerate(CLASSIFY_SIGS.items()):
        i = elf.find(sig)
        if i >= 0 and elf.find(sig, i + 1) < 0:
            break
    else:
        return None
    cls = offset_to_va(elf, i)
    md = capstone.Cs(capstone.CS_ARCH_MIPS, capstone.CS_MODE_MIPS64 | capstone.CS_MODE_LITTLE_ENDIAN)
    ins = list(md.disasm(read_va(elf, cls, 0x200), cls))
    hi: Dict[str, int] = {}
    jt = wt = wfn = count = None
    seen_sub = False
    for k, x in enumerate(ins):
        ops = [o.strip() for o in x.op_str.split(",")]
        if x.mnemonic == "lui":
            hi[ops[0]] = int(ops[1], 0) << 16
        elif x.mnemonic == "addiu" and len(ops) == 3 and ops[2] == "-0x21":
            seen_sub = True
        elif x.mnemonic == "sltiu" and seen_sub and count is None:
            count = int(ops[2], 0)
        elif x.mnemonic == "lw" and jt is None and "(" in ops[1]:
            base = ops[1].split("(")[1].rstrip(")")
            if base in hi:
                jt = hi[base] + int(ops[1].split("(")[0], 0)
        elif x.mnemonic == "jal" and int(ops[0], 0) == cls and wt is None:
            # width function: lui $s0, hi ... jal classify; addiu $s0, $s0, lo (delay slot)
            for y in ins[k - 4:k + 3]:
                yo = [o.strip() for o in y.op_str.split(",")]
                if y.mnemonic == "addiu" and len(yo) == 3 and yo[0] == yo[1] and yo[0] in hi:
                    wt = hi[yo[0]] + int(yo[2], 0)
            for y in reversed(ins[:k]):
                if y.mnemonic == "addiu" and y.op_str.startswith("$sp, $sp, -"):
                    wfn = y.address
                    break
    if jt is None or wt is None or not count:
        return None
    return {"classify": cls, "width_fn": wfn, "jump_table": jt, "jump_count": count,
            "width_table": wt, "variant": vi}


def case_constant(elf: bytes, target: int) -> int:
    """The cell a jump-table target sets: ``b; addiu $r,$zero,K`` or ``addiu $r,$zero,K``."""
    import capstone
    read_va, *_ = _elf_tools()
    md = capstone.Cs(capstone.CS_ARCH_MIPS, capstone.CS_MODE_MIPS64 | capstone.CS_MODE_LITTLE_ENDIAN)
    a, b = list(md.disasm(read_va(elf, target, 8), target))[:2]
    x = b if a.mnemonic == "b" else a
    if x.mnemonic != "addiu" or ", $zero, " not in x.op_str:
        raise StatfontError(f"jump target {target:#x} is not a case body ({a.mnemonic} {a.op_str})")
    return int(x.op_str.split(",")[2], 0)


class Printer:
    """The printer's tables as read from one executable."""

    def __init__(self, elf: bytes, addr: Dict[str, int]):
        read_va, va_to_offset, _ = _elf_tools()
        self.elf, self.addr = elf, addr
        self.variant = list(CLASSIFY_SIGS)[addr.get("variant", 0)]
        self.none = NONE_CELLS[self.variant]
        self.ncells = CELLS if self.variant == "us" else 32
        self.count = addr["jump_count"]
        self.jump = list(struct.unpack(f"<{self.count}I", read_va(elf, addr["jump_table"], 4 * self.count)))
        self.widths = [b - 256 if b > 127 else b for b in read_va(elf, addr["width_table"], self.ncells)]
        self.case_targets: Dict[int, int] = {}
        self._case: Dict[int, int] = {}
        for t in sorted(set(self.jump)):
            k = case_constant(elf, t)
            self._case[t] = k
            self.case_targets.setdefault(k, t)

    def cell_of(self, byte: int) -> int:
        """The classifier with this executable's jump table."""
        c = byte - 0x41
        if self.variant == "us":
            if 0 <= c < 26:
                return 30 if byte == 0x57 else c
            if 0 <= byte - 0x61 < 26:
                return c
        elif 0 <= c < 26 and byte != 0x57:
            return c
        k = byte - JUMP_FIRST
        if 0 <= k < self.count:
            return self._case[self.jump[k]]
        return self.none

    def byte_map(self) -> Dict[int, int]:
        """byte -> cell for every byte that draws a letter cell (digits excluded)."""
        return {b: self.cell_of(b) for b in range(0x20, 0x80)
                if not 0x30 <= b <= 0x39 and self.cell_of(b) != self.none}

    def patched(self, widths: Optional[Dict[int, int]] = None,
                remap: Optional[Dict[int, int]] = None) -> bytes:
        read_va, va_to_offset, _ = _elf_tools()
        out = bytearray(self.elf)
        for cell, w in (widths or {}).items():
            if not 0 <= cell < self.ncells or not 0 <= w <= 32:
                raise StatfontError(f"width {w} for cell {cell}: cells 0-{self.ncells - 1}, widths 0-32")
            out[va_to_offset(self.elf, self.addr["width_table"] + cell)] = w
        for byte, cell in (remap or {}).items():
            k = byte - JUMP_FIRST
            if not 0 <= k < self.count or 0x30 <= byte <= 0x39 or (
                    self.variant == "jp" and 0x41 <= byte <= 0x5A and byte != 0x57):
                raise StatfontError(f"byte {byte:#04x}: only 0x21-{JUMP_FIRST + self.count - 1:#04x} "
                                    "outside the digits (and, on JP, outside A-Z but W) go "
                                    "through the jump table")
            if cell not in self.case_targets:
                raise StatfontError(f"cell {cell:#x}: a jump-table byte can only reach "
                                    f"{sorted(hex(c) for c in self.case_targets)}")
            struct.pack_into("<I", out, va_to_offset(self.elf, self.addr["jump_table"] + 4 * k),
                             self.case_targets[cell])
        return bytes(out)


def printer_for(elf: bytes) -> Optional[Printer]:
    addr = discover(elf)
    return Printer(elf, addr) if addr else None


# ------------------------------------------------------------------ cells

def _sheet_paths(disc, lang: str) -> List[str]:
    from region import lpath
    return [lpath(lang, p) for p in SHEETS]


def cell_image(sheet: XE.Sheet, cell: int) -> Tuple[np.ndarray, np.ndarray]:
    """(16x16 indices, 16x16 RGBA) of one cell under its engine palette."""
    u, v = cell_rect(cell)
    idx = sheet.indices()[v:v + 16, u:u + 16]
    lut = np.frombuffer(b"".join(sheet.clut(*cell_tile(cell))), np.uint8).reshape(256, 4)
    return idx, lut[idx]


def digit_image(sheet: XE.Sheet, d: int) -> Tuple[np.ndarray, np.ndarray]:
    u, v = digit_rect(d)
    idx = sheet.indices()[v:v + DIGIT_H, u:u + DIGIT_W]
    lut = np.frombuffer(b"".join(sheet.clut(*TILE_DIGIT)), np.uint8).reshape(256, 4)
    return idx, lut[idx]


def _label(byte_map: Dict[int, int], cell: int) -> str:
    return "".join(chr(b) for b, c in sorted(byte_map.items()) if c == cell)


def grid_png(sheet: XE.Sheet, byte_map: Dict[int, int], widths: Sequence[int], path: Path,
             lower: bool, scale: int = 3) -> None:
    """Overview: each cell on a dark backdrop (glyphs are alpha coverage), width
    marked in red, the bytes that reach it underneath."""
    cols = 16
    cells = list(range(32)) + (list(range(32, CELLS)) if lower else [])
    rows = (len(cells) + cols - 1) // cols + 1
    cw, chh = 16 * scale + 6, 16 * scale + 18
    img = Image.new("RGBA", (cols * cw, rows * chh), (40, 40, 48, 255))
    dr = ImageDraw.Draw(img)
    for n, c in enumerate(cells):
        x, y = (n % cols) * cw + 3, (n // cols) * chh + 3
        _, rgba = cell_image(sheet, c)
        tile = Image.new("RGBA", (16, 16), (90, 110, 160, 255))
        tile.alpha_composite(Image.fromarray(rgba, "RGBA"))
        img.paste(tile.resize((16 * scale, 16 * scale), Image.NEAREST), (x, y))
        if widths[c]:
            dr.line([(x + widths[c] * scale, y), (x + widths[c] * scale, y + 16 * scale - 1)],
                    fill=(255, 60, 60, 255))
        dr.text((x, y + 16 * scale + 2), f"{c} {_label(byte_map, c)}", fill=(255, 255, 255, 255))
    y = (rows - 1) * chh + 3
    for d in range(10):
        _, rgba = digit_image(sheet, d)
        tile = Image.new("RGBA", (DIGIT_W, DIGIT_H), (90, 110, 160, 255))
        tile.alpha_composite(Image.fromarray(rgba, "RGBA"))
        img.paste(tile.resize((DIGIT_W * scale, DIGIT_H * scale), Image.NEAREST), (3 + d * cw, y))
    img.save(path)


# ---------------------------------------------------------------- export

def export(disc, out: Path) -> dict:
    from region import disc_lang
    lang = disc_lang(disc)
    out.mkdir(parents=True, exist_ok=True)
    elf_name = disc.boot_elf_name()
    elf = disc.read(elf_name)
    pr = printer_for(elf)
    paths = _sheet_paths(disc, lang)
    sheet = XE.Sheet.parse(disc.read(paths[0]))
    lower = sheet.size[0] >= 1024
    info = {"exe": elf_name, "exe_sha1": hashlib.sha1(elf).hexdigest(), "lang": lang,
            "sheets": paths, "sheet_size": list(sheet.size),
            "printer": None, "cells": [], "digits": []}
    (out / "cells").mkdir(exist_ok=True)
    byte_map = pr.byte_map() if pr else {}
    widths = (pr.widths + [0] * CELLS)[:CELLS] if pr else [0] * CELLS
    for c in range(CELLS if lower else 32):
        idx, rgba = cell_image(sheet, c)
        Image.fromarray(rgba, "RGBA").save(out / "cells" / f"cell_{c:02d}.png")
        u, v = cell_rect(c)
        info["cells"].append({"cell": c, "u": u, "v": v, "width": widths[c],
                              "tile": list(cell_tile(c)), "bytes": _label(byte_map, c)})
    for d in range(10):
        _, rgba = digit_image(sheet, d)
        Image.fromarray(rgba, "RGBA").save(out / "cells" / f"digit_{d}.png")
        info["digits"].append({"digit": d, "u": digit_rect(d)[0], "v": DIGIT_V,
                               "w": DIGIT_W, "h": DIGIT_H})
    if pr:
        info["printer"] = {k: hex(v) for k, v in pr.addr.items() if v is not None and k != "variant"}
        info["printer"]["variant"] = pr.variant
        info["printer"]["reachable_by_jump_table"] = sorted(pr.case_targets)
        info["byte_map"] = {f"{b:#04x}": c for b, c in sorted(byte_map.items())}
        info["edit"] = {"widths": {}, "remap": {}}
    grid_png(sheet, byte_map, widths, out / "grid.png", lower)
    for p in paths:
        b = disc.read(p)
        XE.export_sheet(b, out / "sheets", Path(p.replace("\\", "/")).stem, BINDINGS, p)
    (out / "statfont.json").write_text(json.dumps(info, indent=1, ensure_ascii=False))
    return info


# ---------------------------------------------------------------- import

class CellPainter:
    """Glyphs -> indices of one palette. The retail cells are a light fill with a
    dark 1-px outline; a rendered coverage map is drawn the same way (fill colour =
    the most used light colour of the sample cells, outline = the most used dark
    one, outline = coverage dilated by one pixel) and quantized to the palette."""

    def __init__(self, sheet: XE.Sheet, tile: Tuple[int, int], sample_cells: Sequence[int]):
        self.lut = np.frombuffer(b"".join(sheet.clut(*tile)), np.uint8).reshape(256, 4)
        used = np.concatenate([cell_image(sheet, c)[0].ravel() for c in sample_cells]) \
            if len(sample_cells) else np.zeros(0, np.uint8)
        used = used[self.lut[used, 3] >= 200]
        lum = self.lut[:, :3].astype(np.int32).sum(1)
        light = used[lum[used] >= 384]
        dark = used[lum[used] < 384]

        def mode(v, default):
            if not len(v):
                return np.array(default, np.float32)
            vals, cnt = np.unique(v, return_counts=True)
            return self.lut[vals[cnt.argmax()], :3].astype(np.float32)
        self.fill = mode(light, (255, 255, 255))
        self.edge = mode(dark, (0, 0, 0))

    def from_rgba(self, rgba: np.ndarray) -> np.ndarray:
        k, _ = XE._nearest(self.lut, rgba.reshape(-1, 4))
        return k.reshape(rgba.shape[:2]).astype(np.uint8)

    def target(self, cov: np.ndarray) -> np.ndarray:
        """RGBA picture of a glyph: fill over a one-pixel dark outline."""
        pad = np.pad(cov, 1)
        out_cov = np.max([pad[1 + dy:pad.shape[0] - 1 + dy, 1 + dx:pad.shape[1] - 1 + dx]
                          for dy in (-1, 0, 1) for dx in (-1, 0, 1)], axis=0)
        c = cov[..., None]
        rgb = self.fill * c + self.edge * (1 - c)
        alpha = np.maximum(out_cov, cov)
        return np.concatenate([rgb, alpha[..., None] * 255], -1).round().astype(np.uint8)

    def from_coverage(self, cov: np.ndarray) -> np.ndarray:
        t = self.target(cov)
        t[t[..., 3] < 16] = 0
        return self.from_rgba(t)


def render_letter(ch: str, font: str, px: float, baseline: int) -> Tuple[np.ndarray, int]:
    """(16x16 coverage, advance) of one character, left-aligned at x=1."""
    f = ImageFont.truetype(font, size=int(round(px)))
    im = Image.new("L", (16, 16), 0)
    ImageDraw.Draw(im).text((1, baseline), ch, fill=255, font=f, anchor="ls")
    adv = int(round(f.getlength(ch))) + 2
    return np.array(im, np.float32) / 255.0, min(16, max(1, adv))


def build(disc, edit_dir: Path, letters: Optional[Dict[str, str]] = None,
          font: Optional[str] = None, px: float = 15.0, baseline: int = 13,
          base: Optional[Dict[str, bytes]] = None) -> Tuple[Dict[str, bytes], dict]:
    """Apply an edited export (cells/*.png, statfont.json ``edit``) and an optional
    letter assignment {new char: existing byte char} rendered from ``font``.
    ``base`` ({disc path: bytes}, e.g. imagetext.import_dir's result) is used instead
    of the disc's copy for any sheet / executable it holds, so edits chain.
    Returns ({disc path: bytes} for every changed file, report)."""
    from region import disc_lang
    info = json.loads((edit_dir / "statfont.json").read_text())
    lang = disc_lang(disc)
    paths = _sheet_paths(disc, lang)
    base = base or {}
    elf_name = disc.boot_elf_name()
    elf = disc.read(elf_name)
    if info.get("exe_sha1") and info["exe_sha1"] != hashlib.sha1(elf).hexdigest():
        raise StatfontError("statfont.json was exported from a different executable")
    elf = base.get(elf_name, elf)
    pr = printer_for(elf)
    sheets = {p: base.get(p) or disc.read(p) for p in paths}
    first = XE.Sheet.parse(sheets[paths[0]])
    lower = first.size[0] >= 1024
    ncell = CELLS if lower else 32
    painters = {TILE_UPPER: CellPainter(first, TILE_UPPER, range(26)),
                TILE_LOWER: CellPainter(first, TILE_LOWER, range(32, 58)) if lower else None}
    new_cells: Dict[int, np.ndarray] = {}
    new_digits: Dict[int, np.ndarray] = {}
    for c in range(ncell):
        f = edit_dir / "cells" / f"cell_{c:02d}.png"
        if f.exists():
            rgba = np.array(Image.open(f).convert("RGBA"))
            if rgba.shape[:2] != (16, 16):
                raise StatfontError(f"{f.name}: must stay 16x16")
            idx0, ref = cell_image(first, c)
            if not (rgba == ref).all():
                new_cells[c] = painters[cell_tile(c)].from_rgba(rgba)
    for d in range(10):
        f = edit_dir / "cells" / f"digit_{d}.png"
        if f.exists():
            rgba = np.array(Image.open(f).convert("RGBA"))
            _, ref = digit_image(first, d)
            if rgba.shape[:2] != (DIGIT_H, DIGIT_W):
                raise StatfontError(f"{f.name}: must stay {DIGIT_W}x{DIGIT_H}")
            if not (rgba == ref).all():
                lut = np.frombuffer(b"".join(first.clut(*TILE_DIGIT)), np.uint8).reshape(256, 4)
                new_digits[d] = XE._nearest(lut, rgba.reshape(-1, 4))[0].reshape(DIGIT_H, DIGIT_W).astype(np.uint8)
    edit = info.get("edit", {})
    widths = {int(k): int(v) for k, v in edit.get("widths", {}).items()}
    remap = {int(k, 0): int(v, 0) if isinstance(v, str) else int(v) for k, v in edit.get("remap", {}).items()}
    charmap: Dict[str, str] = {}
    if letters:
        if pr is None:
            raise StatfontError("this executable has no HUD letter printer (JP build?)")
        if not font:
            raise StatfontError("--letters needs --font to draw the new letters")
        for newch, slot in letters.items():
            if len(slot) != 1 or ord(slot) not in pr.byte_map():
                raise StatfontError(f"{newch!r} -> {slot!r}: the slot must be one byte that "
                                    "already draws a cell (A-Z, a-z, ! * - . / :)")
            cell = pr.cell_of(ord(slot))
            if cell >= ncell:
                raise StatfontError(f"cell {cell} is not on this sheet")
            cov, adv = render_letter(newch, font, px, baseline)
            new_cells[cell] = painters[cell_tile(cell)].from_coverage(cov)
            widths.setdefault(cell, adv)
            charmap[newch] = slot
    out: Dict[str, bytes] = {}
    for p, b in sheets.items():
        sh = XE.Sheet.parse(b)
        idx = sh.indices()
        mask = np.zeros_like(idx, bool)
        for c, cidx in new_cells.items():
            u, v = cell_rect(c)
            w = min(16, (256 if c < 32 else 1024) - u)
            idx[v:v + 16, u:u + w] = cidx[:, :w]
            mask[v:v + 16, u:u + w] = True
        for d, didx in new_digits.items():
            u, v = digit_rect(d)
            idx[v:v + DIGIT_H, u:u + DIGIT_W] = didx
            mask[v:v + DIGIT_H, u:u + DIGIT_W] = True
        if mask.any():
            sh.set_indices(idx, mask)
            nb = sh.to_bytes()
            if nb != disc.read(p):
                out[p] = nb
    if widths or remap:
        if pr is None:
            raise StatfontError("width / byte edits need the HUD letter printer (absent here)")
        nelf = pr.patched(widths, remap)
        if nelf != elf:
            out[elf_name] = nelf
    rep = {"cells": sorted(new_cells), "digits": sorted(new_digits), "widths": widths,
           "remap": {f"{k:#04x}": v for k, v in remap.items()}, "charmap": charmap,
           "files": {p: hashlib.sha1(b).hexdigest() for p, b in out.items()}}
    return out, rep


# ------------------------------------------------------------------- CLI

def _cmd_export(a) -> int:
    from disc import Disc
    with Disc(a.iso) as d:
        info = export(d, Path(a.out))
    pr = info["printer"]
    print(f"{info['exe']} ({info['lang']}): sheet {info['sheet_size'][0]}x{info['sheet_size'][1]}, "
          f"{len(info['cells'])} cells, 10 digits -> {a.out}")
    print(f"  printer: {pr if pr else 'ABSENT in this executable (sheets and cells exported only)'}")
    return 0


def _cmd_import(a) -> int:
    from disc import Disc
    letters = json.loads(Path(a.letters).read_text(encoding="utf-8")) if a.letters else None
    with Disc(a.iso) as d:
        files, rep = build(d, Path(a.dir), letters, a.font, a.px, a.baseline)
    out = Path(a.out)
    for p, b in files.items():
        dst = out / "files" / Path(*p.replace("\\", "/").split("/"))
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(b)
    out.mkdir(parents=True, exist_ok=True)
    (out / "statfont-out.json").write_text(json.dumps(rep, indent=1, ensure_ascii=False))
    print(f"{len(rep['cells'])} cells, {len(rep['digits'])} digits, {len(rep['widths'])} widths, "
          f"{len(rep['remap'])} byte remaps -> {len(files)} files under {out / 'files'}")
    if rep["charmap"]:
        print("  charmap (write these letters as these bytes in HUD strings): "
              + " ".join(f"{k}={v}" for k, v in rep["charmap"].items()))
    return 0


def add_commands(subparsers) -> None:
    p = subparsers.add_parser("statfont-export", help="HUD letter cells of the window sheets + "
                              "byte/width tables from the executable")
    p.add_argument("--iso", required=True, help="disc image to read the window sheets and executable from")
    p.add_argument("--out", required=True, help="folder for the cell PNGs and the width/byte tables")
    p.set_defaults(func=_cmd_export)
    p = subparsers.add_parser("statfont-import", help="edited cells / widths / letters -> "
                              "window sheets + executable (same size); then 'patch --tree OUT/files'")
    p.add_argument("--iso", required=True, help="the disc the export came from (read only)")
    p.add_argument("--dir", required=True, help="a statfont-export directory, edited")
    p.add_argument("--out", required=True, help="writes OUT/files/<disc path> and OUT/statfont-out.json "
                   "(feed OUT/files to 'patch --iso D1 --iso D2 --tree')")
    p.add_argument("--letters", help="JSON {new letter: existing byte char}, drawn with --font")
    p.add_argument("--font", help="TrueType/OpenType font for --letters")
    p.add_argument("--px", type=float, default=15.0, help="--font pixel size for --letters (default 15)")
    p.add_argument("--baseline", type=int, default=13,
                   help="baseline row inside the HUD letter cell for --letters (default 13)")
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

    check(cell_rect(0) == (0, 0) and cell_rect(30) == (224, 16) and cell_rect(31) == (244, 16)
          and cell_rect(32) == (768, 0) and cell_rect(57) == (768 + 9 * 16, 16),
          "cell rects: A (0,0), W->30 (224,16), ! (244,16), a (768,0), z (912,16)")
    check(digit_rect(1) == (0, 32) and digit_rect(0) == (117, 32), "digit rects: '1' u 0, '0' u 117")
    check(TILE_UPPER == (0, 112) and TILE_LOWER == (384, 112) and TILE_DIGIT == (16, 112),
          "palette tiles from CBP 0x308 / 0x3c8 / 0x30c")
    iso = os.environ.get("XS3_D1")
    if not iso or not Path(iso).exists():
        print("SKIP XS3_D1 not set")
        return 1 if bad else 0
    from disc import Disc
    with Disc(iso) as d:
        elf = d.read(d.boot_elf_name())
        pr = printer_for(elf)
        check(pr is not None and {k: pr.addr[k] for k in ("classify", "jump_table", "width_table")}
              == {k: US_ADDR[k] for k in ("classify", "jump_table", "width_table")},
              f"US printer found by signature at {pr and {k: hex(v) for k, v in pr.addr.items()}}")
        bm = pr.byte_map()
        check(bm[ord("A")] == 0 and bm[ord("W")] == 30 and bm[ord("a")] == 32 and bm[ord("*")] == 22
              and bm[ord("!")] == 31 and bm[ord(":")] == 28 and ord("#") not in bm,
              f"byte map: {len(bm)} drawing bytes, A0 W30 a32 *22 !31 :28, # not drawn")
        check(pr.widths[:3] == [15, 13, 13] and pr.widths[30] == 17 and pr.widths[58:] == [0] * 6,
              "width table: A15 B13 C13, W(30)=17, cells 58-63 empty")
        check(sorted(pr.case_targets) == [0x16, 0x1a, 0x1b, 0x1c, 0x1d, 0x1f, 0x40],
              "jump table reaches cells 0x16 0x1a 0x1b 0x1c 0x1d 0x1f 0x40")
        np_ = pr.patched({0: 12}, {0x23: 0x1d})
        pr2 = Printer(np_, pr.addr)
        check(len(np_) == len(elf) and pr2.widths[0] == 12 and pr2.cell_of(0x23) == 0x1d
              and pr2.cell_of(0x2e) == 0x1d, "patched exe: width A=12, '#' -> cell 0x1d ('.')")
        with tempfile.TemporaryDirectory() as td:
            info = export(d, Path(td))
            check(len(info["cells"]) == 64 and (Path(td) / "grid.png").exists(),
                  "export: 64 cells + grid + 3 sheet renders")
            files, rep = build(d, Path(td))
            check(files == {}, "unmodified export imports to no changed file")
            im = np.array(Image.open(Path(td) / "cells" / "cell_16.png"))
            im[:] = 0
            Image.fromarray(im, "RGBA").save(Path(td) / "cells" / "cell_16.png")
            files, rep = build(d, Path(td))
            ok = len(files) == 3 and all(len(files[p]) == len(d.read(p)) for p in files)
            sh = XE.Sheet.parse(files["mnu\\us\\window0.xtx"]) if ok else None
            check(ok and (cell_image(sh, 16)[1][..., 3] == 0).all(),
                  f"blanking cell 16 ('Q') rewrites the 3 sheets, same size")
            if ok:
                o = XE.Sheet.parse(d.read("mnu\\us\\window0.xtx")).indices()
                n = sh.indices()
                diff = np.argwhere(o != n)
                check(diff[:, 0].min() >= 16 and diff[:, 0].max() < 32 and diff[:, 1].min() >= 0
                      and diff[:, 1].max() < 16, "only the 'Q' cell's pixels changed")
        font = os.environ.get("XS3_TEST_FONT", "/System/Library/Fonts/Supplemental/Arial Bold.ttf")
        if Path(font).exists():
            with tempfile.TemporaryDirectory() as td:
                export(d, Path(td))
                files, rep = build(d, Path(td), {"\u0416": "Q", "\u0434": "q"}, font, 14, 13)
                sh = XE.Sheet.parse(files["mnu\\us\\window0.xtx"])
                npr = printer_for(files[d.boot_elf_name()])
                a = cell_image(sh, 16)[1][..., 3]
                check(rep["charmap"] == {"\u0416": "Q", "\u0434": "q"} and rep["cells"] == [16, 48]
                      and (a > 0).sum() > 40 and npr.widths[16] == rep["widths"][16]
                      and len(files) == 4,
                      f"--letters: Zhe -> 'Q' cell, de -> 'q' cell drawn from {Path(font).name}, "
                      f"widths {rep['widths']}, 3 sheets + exe")
        else:
            print(f"SKIP --letters test: no font at {font} (set XS3_TEST_FONT)")
    jp = os.environ.get("XS3_JP1")
    if jp and Path(jp).exists():
        with Disc(jp) as d:
            jpp = printer_for(d.read(d.boot_elf_name()))
            ok = jpp is not None and jpp.variant == "jp"
            bm = jpp.byte_map() if ok else {}
            check(ok and jpp.addr["classify"] == 0x23ABA8 and jpp.addr["jump_table"] == 0x537530
                  and jpp.count == 55 and jpp.addr["width_table"] == 0x537610
                  and bm.get(ord("A")) == 0 and bm.get(ord("W")) == 30 and ord("a") not in bm,
                  f"JP printer variant: classify 0x23aba8, 55-entry jump table 0x537530, widths "
                  f"0x537610; A0 W{bm.get(ord('W'))}, no lowercase; {len(bm)} drawing bytes")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(self_test())
