"""glyphs.py — put a new script's glyphs into Episode III's fonts.

Borrowed from Xenosaga1PythonExtractor/glyphs.py (2026-11-20). Kept as is:
``Glyph``, the bitmap helpers, ``GlyphSet`` (keys, json, ``from_png``), the
``TTFRenderer`` (HarfBuzz shaping through uharfbuzz, outlines through
fonttools, the kit's own even-odd scanline rasteriser at 4x supersampling,
averaged to the font's four levels) and the glyph-key scheme ``langpack``
uses (``u:<text>``, ``g:<font>:<gid>``, ``c:<font>:<gid>@dx,dy;...``). What
changed for Episode III:

* fonttools and uharfbuzz are REQUIRED (requirements.txt), not optional;
* the SLOT MODEL is new (``SlotModel``): Episode I had a fixed 256-slot
  proportional block and the kanji rows; Episode III's room depends on the
  build's addressing (``font.Addressing``: gate, prop_cells, A9 row), on the
  cells retail text draws (scanned from the disc, parse-only), and on the
  optional executable unlocks below;
* a proportional glyph is drawn twice: its ink-aligned image at cell + 0x240
  (what ``$prop1;`` draws, FUN_00185770 measures it with the metric pair of
  the base cell) and a centred copy at the base cell (what ``$prop0;`` draws);
* codes are byte strings of 1 or 2 bytes (USA single bytes 0x80-0xFF are
  characters of their own).

Slot model, per build (all addressing read from the executable by font.py):

USA / May 2006 prototype (whitelist gate, prop cells < 384, A9 row):
    proportional tier  cells 0..383 reachable through gate-accepted codes:
                       A4A1-A4FE -> 192-285; single bytes 0x80-0xFF -> byte + 0x80
                       = 256-383 (except the bytes that can start a pair: A1 A2 A3
                       A4 A6 AD); A1/A2/A3 codes below 192 (A1BD/DA/DB/DF/EE,
                       A2F6, A3B0-B9). Codes flagged 0x1000 (always fixed width:
                       A1B9, A1BC, A1F9-FC, the A2A0 group) are not slots.
    wide tier          A6 pairs -> 384..438 (one EUC trail per cell), AD B5-B7 -> 564-566
    reserved           cell 0 (space), 0x7F (the fallback), the 96 cells of the
                       ``$han`` table, every cell retail text draws (and its
                       half-size twin, FUN_00181db8), cells 576..959 (the images of
                       cells 0..383), and the extra-kanji cells 3989+.
Japan (euc gate, prop cells < 192, no A9 row; M22 of the JP brief):
    any pair with lead A1..CF and trail A1..FE whose cell the Japanese font
    leaves BLANK and retail text does not draw; tier by cell (< 192 prop).
    Latin-1, SS2/SS3 (8E/8F) and 0x80-0x9F are not code space on Japan.

Optional unlocks of the USA executable (``UNLOCKS``; data the langpack can
request, NOT tested in game). Each is a list of patch descriptors
(VA, old bytes, new bytes); ``apply_patches`` checks every old word before it
writes anything, and refuses a mismatch:

    jp-gate   the pair gate FUN_00181e48's first four words become the Japanese
              gate (lead >= 0xA0, trail untested). Kanji rows B0-CF reach cells
              1024..3988 (2,965 wide cells, ~3,000) and A5 reaches 288-383. Cost:
              USA Latin-1 singles 0xA0-0xFF become leads, so all English text
              must be re-encoded (``SlotModel.code_for`` gives the new code of
              every cell: e.g. e-acute (cell 361) = A5EA instead of E9; cells 382/383
              only through a non-EUC trail, e.g. A76F / A640).
    jp-prop   the two prop-gate immediates 0x180 -> 0xC0 (printer 0x1856e4,
              measurer 0x182dd4), as on Japan: cells 192-383 become fixed width
              and their metric pairs serve the half-size path only.
    jp        both.

Usage (``add_commands``)::

    glyphs-slots    --iso DISC.iso [--unlock jp] [--json slots.json]
    glyphs-coverage --iso JP.iso                         # T7: every EUC pair inked
    glyphs-render   --iso DISC.iso --ttf F.ttf --text "абв" --out gs.json [--png prev.png]
    glyphs-apply    --glyphset gs.json --font font0.bin --out new.bin
    glyphs-unlock   --iso US.iso [--iso US2.iso] --mode jp (--out-exe FILE | --out OUT)
    python glyphs.py --self-test

XS1KOR (https://github.com/poketony/XS1KOR), poketony's Korean localisation
of the Japanese Episode I, is the proof the approach works: 2,048 Hangul cells
rendered from a TTF into the kanji area.
"""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import math
import os
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import font as fontmod                                             # noqa: E402
import patch                                                       # noqa: E402
from font import (CELL_H, CELL_W, CELL_COUNT, EXTRA_KANJI_BASE, FALLBACK_CELL, FIXED_ADVANCE,  # noqa: E402
                  FIXED_FLAG, PROP_CELL_SHIFT, PROP_LIMIT, Addressing, Font, FontError, half_cell)


class GlyphError(ValueError):
    pass


# --- bitmaps (unchanged from XS1) ----------------------------------------------

Bitmap = List[List[int]]        # CELL_H rows of CELL_W values 0..3


def blank() -> Bitmap:
    return [[0] * CELL_W for _ in range(CELL_H)]


def ink_bounds(bm: Bitmap) -> Optional[Tuple[int, int]]:
    cols = [x for x in range(CELL_W) if any(row[x] for row in bm)]
    return (cols[0], cols[-1]) if cols else None


def shift_x(bm: Bitmap, dx: int) -> Bitmap:
    out = blank()
    for y in range(CELL_H):
        for x in range(CELL_W):
            if 0 <= x - dx < CELL_W:
                out[y][x] = bm[y][x - dx]
    return out


class Glyph:
    def __init__(self, key: str, bitmap: Bitmap, advance_hint: Optional[int] = None):
        self.key = key
        self.bitmap = bitmap
        self.bounds = ink_bounds(bitmap)
        self.advance_hint = advance_hint    # for blank glyphs (spaces)

    @property
    def ink_width(self) -> int:
        return self.bounds[1] - self.bounds[0] + 1 if self.bounds else 0


# --- executable unlocks ------------------------------------------------------------

@dataclass(frozen=True)
class Patch:
    va: int
    old: bytes
    new: bytes
    what: str


_SITES = {va: (old, new) for va, old, new in fontmod.UNLOCK_SITES}     # font.py holds the words
UNLOCKS: Dict[str, Tuple[Patch, ...]] = {
    "jp-gate": (Patch(0x181E48, *_SITES[0x181E48],
                      "pair gate FUN_00181e48 -> the Japanese four words (lead >= 0xA0)"),),
    "jp-prop": (Patch(0x1856E4, *_SITES[0x1856E4], "printer prop gate sltiu v0,s1,0x180 -> 0xC0"),
                Patch(0x182DD4, *_SITES[0x182DD4], "measurer prop gate slti v0,a0,0x180 -> 0xC0")),
}
UNLOCK_MODES: Dict[str, Tuple[str, ...]] = {"none": (), "jp-gate": ("jp-gate",), "jp-prop": ("jp-prop",),
                                            "jp": ("jp-gate", "jp-prop")}
# the builds whose code these VAs were read from (the prototype's code sits at the
# retail addresses; checked word for word by apply_patches either way)
UNLOCK_BUILDS = ("us", "proto-2006-05")


def unlock_patches(mode: str) -> List[Patch]:
    if mode not in UNLOCK_MODES:
        raise GlyphError(f"unknown unlock mode {mode!r}; one of {', '.join(UNLOCK_MODES)}")
    return [p for name in UNLOCK_MODES[mode] for p in UNLOCKS[name]]


def apply_patches(exe: bytes, patches: Sequence[Patch]) -> Tuple[bytes, List[str]]:
    """``exe`` with every patch applied. Each site must hold its old bytes (or
    already its new bytes: reported, not rewritten); any other content refuses
    the whole set before anything is written."""
    out = bytearray(exe)
    report, todo = [], []
    for p in patches:
        cur = fontmod.read_va(exe, p.va, len(p.old))
        if cur == p.new:
            report.append(f"{p.va:#x} already patched ({p.what})")
        elif cur == p.old:
            todo.append(p)
        else:
            raise GlyphError(f"{p.va:#x}: expected {p.old.hex()} ({p.what}), found {cur.hex()}: "
                             f"not a build these patches were made for")
    for p in todo:
        o = fontmod.va_to_offset(exe, p.va, len(p.new))
        out[o:o + len(p.new)] = p.new
        report.append(f"{p.va:#x} {p.old.hex()} -> {p.new.hex()} ({p.what})")
    return bytes(out), report


def unlocked_addressing(a: Addressing, mode: str) -> Addressing:
    """The addressing the USA executable has after ``mode`` (no executable needed)."""
    names = UNLOCK_MODES.get(mode)
    if names is None:
        raise GlyphError(f"unknown unlock mode {mode!r}")
    if names and a.gate != "whitelist":
        raise GlyphError(f"unlock {mode!r} is for the USA/prototype executable; this one has the {a.gate} gate")
    rep = {}
    if "jp-gate" in names:
        rep["gate"] = "euc"
    if "jp-prop" in names:
        rep["prop_cells"] = fontmod.JP_PROP_CELLS
    return dataclasses.replace(a, **rep)


def patch_iso(iso_path, mode: str) -> List[str]:
    """Patch the boot executable of an ISO in place (a COPY: this writes; the CLI
    does not use it any more, ``glyphs-unlock --out`` goes through
    ``patch.patch_copy``, which never writes a source image). The
    executable's file extent is found through ISO9660; every patch site is
    checked first. Returns the report lines."""
    from iso9660 import IsoImage
    with IsoImage(iso_path) as im:
        name = im.boot_elf_name()
        f = im.find(name) if name else None
        if f is None or f.layer:
            raise GlyphError(f"{iso_path}: no first-layer boot executable")
        exe = bytes(im.read_file(f.path))
        start = f.lba * 2048
    try:
        prof = fontmod.profile_for(exe)
    except FontError:
        prof = None
    if prof is not None and prof.name not in UNLOCK_BUILDS:
        raise GlyphError(f"{iso_path}: the {prof.name} executable needs no unlock (or has other VAs)")
    new, report = apply_patches(exe, unlock_patches(mode))
    if new != exe:
        with open(iso_path, "r+b") as fh:
            for i in range(0, len(exe), 4):
                if new[i:i + 4] != exe[i:i + 4]:
                    fh.seek(start + i)
                    fh.write(new[i:i + 4])
        with IsoImage(iso_path) as im:
            if bytes(im.read_file(f.path)) != new:
                raise GlyphError(f"{iso_path}: re-read of the patched executable differs")
    return report


# --- retail text scan (parse-only) ---------------------------------------------------

def _walk_game(a: Addressing, s: bytes, cells: Counter, font_nos=(0, 1)) -> None:
    """The printer's walk: '$' commands and control sequences (with their operand
    lengths) are stepped over; characters from 0x80 up give cells."""
    i, n = 0, len(s)
    while i < n:
        b = s[i]
        if b == 0x24:
            try:
                i = a.command_at(s, i)[2]
                continue
            except FontError:
                i += 1
                continue
        if b < 0x20:
            try:
                i += max(1, a.control_length(s, i))
            except (FontError, IndexError):
                i += 1
            continue
        if b < 0x80:
            i += 1
            continue
        g = None
        for k in font_nos:
            g = a.glyph(s, i, True, k)
            cells[fontmod.cell_index(g.cell)] += 1
        i += g.length


def _walk_plain(a: Addressing, s: bytes, cells: Counter, font_nos=(0, 1)) -> None:
    """Every byte below 0x80 is one byte (no operand skipping): for whole text
    files, and as a second, desync-proof pass over parsed strings."""
    i, n = 0, len(s)
    while i < n:
        if s[i] < 0x80:
            i += 1
            continue
        g = None
        for k in font_nos:
            g = a.glyph(s, i, True, k)
            cells[fontmod.cell_index(g.cell)] += 1
        i += g.length


def _text_runs(data: bytes, min_len: int = 2) -> Iterable[bytes]:
    for run in data.split(b"\0"):
        if len(run) >= min_len and all(c >= 0x20 or c in (9, 10, 13) for c in run):
            yield run


_LETTERS = re.compile(rb"[A-Za-z]{2}")


def plausible(run: bytes, gate: str) -> bool:
    """Is a NUL-delimited run from a binary file (batdat.bin, Message.Dat, the
    executable, the overlays) text? USA: 4+ bytes, 75% printable ASCII, two
    letters in a row (keeps 'Ω Universitas', 'Press <○>' and drops code bytes).
    Japan: a strict EUC-JP (+NEC row 13) reading with 2+ kana/kanji."""
    if gate == "euc":
        if len(run) < 4 or not any(c >= 0xA1 for c in run):
            return False
        try:
            t = run.decode("euc_jis_2004")
        except UnicodeDecodeError:
            return False
        return sum(0x3040 <= ord(ch) <= 0x9FFF or 0xFF00 <= ord(ch) <= 0xFFEF for ch in t) >= 2
    pr = sum(0x20 <= c < 0x7F for c in run)
    return len(run) >= 4 and pr >= 0.75 * len(run) and bool(_LETTERS.search(run))


def _disc_paths(d) -> List[str]:
    return [e.path for _c, e in d.entries()]


def text_sources(paths: Iterable[str], lang: str) -> List[Tuple[str, str]]:
    """(path, kind) of every text file the scan reads: kinds sb, txd, nj, file
    (whole-file subtitles / pse messages), raw (batdat.bin, Message.Dat: text
    runs). The executable and overlays (kind exe) are added by ``scan_retail``."""
    import njbin
    nj = {n.lower() for n in njbin.NAMES}
    out = []
    for p in paths:
        low = p.replace("/", "\\").lstrip("\\").lower()
        parts = low.split("\\")
        if low.endswith(".sb") and len(parts) == 3 and parts[0] in ("cf", "bat") and parts[1] == lang:
            out.append((p, "sb"))
        elif parts[:2] == ["mnu", lang] and len(parts) == 3 and low.endswith(".txd"):
            out.append((p, "txd"))
        elif parts[:2] == ["mnu", lang] and len(parts) == 3 and parts[2] in nj:
            out.append((p, "nj"))
        elif parts[0] in ("mov", "evt") and len(parts) >= 3 and parts[1] == lang and low.endswith(".txt"):
            out.append((p, "file"))
        elif parts[:3] == ["mnu", "pse", lang] and low.endswith(".mes"):
            out.append((p, "file"))
        elif low in (f"bat\\{lang}\\batdat.bin", f"mg1\\{lang}\\message.dat"):
            out.append((p, "raw"))
    return sorted(out, key=lambda x: x[0].lower())


def scan_strings(read, sources: Sequence[Tuple[str, str]], gate: str,
                 region=None) -> Iterable[Tuple[str, str, bytes, str]]:
    """(path, kind, string, category) for every string of ``sources`` that the
    game may draw. category "text", or on the USA gate "untranslated": Japanese
    left in the USA build (.sb placeholder lines, the euc_jp .mes files AC / PP /
    opening / test, the prototype's EUC DBC2) that the USA printer would draw as
    Latin-1/hiragana soup. USA .sb developer notes (never drawn) and identifiers
    are skipped; on Japan every non-identifier string is text."""
    import njbin
    import sb
    import subtitle
    import textcodec
    us = gate == "whitelist"
    for p, kind in sources:
        data = read(p)
        if kind == "sb":
            for s in sb.parse(data).strings:
                role = sb.classify(s)
                if role == "identifier" or (us and role == "note"):
                    continue
                yield p, kind, s, "untranslated" if us and role == "untranslated" else "text"
        elif kind == "txd":
            import txd
            for s in txd.parse(data).strings:
                yield p, kind, s, "text"
        elif kind == "nj":
            for b in njbin.parse(data).blobs:
                for s in b.strings:
                    yield p, kind, s, "untranslated" if us and textcodec.NoteCodec.pick_euc(s) else "text"
        elif kind == "file":
            jp_mes = us and subtitle.codec_name("\\" + p.lstrip("\\"), data) not in ("us",)
            yield p, kind, data, "untranslated" if jp_mes else "text"
        else:
            for s in _text_runs(data):
                if plausible(s, gate):
                    yield p, kind, s, "text"
            # plus every item the text pipeline (msgdat / batdat parse, textpack,
            # langpack) treats as display text. The plausible-run filter alone
            # misses USA Message.Dat #0587 / #0589 (prototype #0586 / #0588): the
            # hiragana table of the HaKox password input ("The password function
            # was abolished", #0588). Those are EUC Japanese that the USA printer
            # draws as A4-row soup, so on the USA gate they count as
            # "untranslated" like the mnu .bin EUC strings (reserved only with
            # include_untranslated), not silently as free cells.
            if region is not None:
                import batdat
                import msgdat
                mod = msgdat if p.lower().endswith("message.dat") else batdat
                for it in mod.parse(data, region).items:
                    if it.codec in ("us", "jp") and it.role not in ("note", "identifier", "untranslated"):
                        jp_left = us and textcodec.NoteCodec.pick_euc(it.raw)
                        yield p, kind, it.raw, "untranslated" if jp_left else "text"


@dataclass
class RetailScan:
    cells: Counter                                   # cell -> hits, category "text"
    untranslated: Counter                            # cell -> hits, category "untranslated" (USA only)
    files: Counter                                   # kind -> files read
    strings: Counter                                 # kind -> strings walked
    lang: str = "us"

    def reserved(self, include_untranslated: bool = False) -> Set[int]:
        return set(self.cells) | (set(self.untranslated) if include_untranslated else set())

    def to_json(self) -> dict:
        return {"lang": self.lang, "files": dict(self.files), "strings": dict(self.strings),
                "cells": {str(k): v for k, v in sorted(self.cells.items())},
                "untranslated_cells": {str(k): v for k, v in sorted(self.untranslated.items())}}


def scan_retail(d, a: Addressing, lang: Optional[str] = None, exe: bool = True) -> RetailScan:
    """Every cell the retail text of disc ``d`` (a ``disc.Disc``) draws under the
    build's own addressing ``a``: .sb / .txd / mnu .bin strings (parsed), the
    subtitle and .mes files, plausible text runs of batdat.bin and Message.Dat,
    and (``exe``) of the boot executable and the root overlays OV*.OVL. Parsed
    strings are walked twice (the printer's walk and a plain byte walk) and the
    union kept, so a misread operand can only over-reserve."""
    lang = lang or a.font_dir
    sources = text_sources(_disc_paths(d), lang)
    cells, untr, files, strings = Counter(), Counter(), Counter(), Counter()
    for p, kind in sources:
        files[kind] += 1
    import region as _region
    items = list(scan_strings(d.read, sources, a.gate, _region.detect(d)))
    if exe:
        iso = d.iso
        names = [n for n, f in iso.files.items() if "\\" not in n and not f.is_dir
                 and (n == iso.boot_elf_name() or re.match(r"(?i)^OV\d\d\.OVL$", n))]
        for n in sorted(names):
            files["exe"] += 1
            data = bytes(iso.read_file(n))
            items += [(n, "exe", s, "text") for s in _text_runs(data) if plausible(s, a.gate)]
    for p, kind, s, cat in items:
        strings[kind] += 1
        tgt = cells if cat == "text" else untr
        if kind in ("file", "raw", "exe"):
            _walk_plain(a, s, tgt)
        else:
            _walk_game(a, s, tgt)
            _walk_plain(a, s, tgt)
    return RetailScan(cells, untr, files, strings, lang)


# --- slot model ---------------------------------------------------------------------

PROP_IMAGES = range(PROP_CELL_SHIFT, PROP_CELL_SHIFT + PROP_LIMIT)       # 576..959


def reachable(a: Addressing, font_no: int = 0, flagged: bool = False) -> Dict[int, bytes]:
    """cell -> the shortest (then lowest) code that draws it under ``a``. Pairs use
    EUC trails A1..FE only; leads from 0xD0 (the extra-kanji lists) and fallback
    results are left out. 0x1000-flagged codes (always fixed width) are left out
    unless ``flagged``, and then only fill cells no other code reaches, as do
    pairs with a printable non-EUC trail (the euc gate does not test the trail);
    ``flagged`` is the re-encoding table, never the slot list."""
    out: Dict[int, bytes] = {}
    late: Dict[int, bytes] = {}
    if a.a9_row:
        for b in range(0x80, 0x100):
            if any(a.pair(b, t) for t in range(1, 0x100)):
                continue                          # may start a pair: not a safe single
            c = a.glyph(bytes((b,)), 0, True, font_no).cell
            if c != FALLBACK_CELL:
                (late if c & FIXED_FLAG else out).setdefault(fontmod.cell_index(c), bytes((b,)))
    for lead in range(0xA1, 0xD0):
        for trail in range(0xA1, 0xFF):
            if not a.pair(lead, trail):
                continue
            c = a.cell(lead, trail, font_no)
            if c == FALLBACK_CELL:
                continue
            (late if c & FIXED_FLAG else out).setdefault(fontmod.cell_index(c), bytes((lead, trail)))
    if flagged:
        for c, code in late.items():
            out.setdefault(c, code)
        # last resort for re-encoding only: printable non-EUC trails (not '$', '\\')
        for lead in range(0xA1, 0xD0):
            for trail in range(0x21, 0xA1):
                if trail in (0x24, 0x5C) or not a.pair(lead, trail):
                    continue
                c = a.cell(lead, trail, font_no)
                if c != FALLBACK_CELL:
                    out.setdefault(fontmod.cell_index(c), bytes((lead, trail)))
    return out


@dataclass
class SlotModel:
    build: str                                       # addressing profile (us / proto-2006-05 / jp)
    unlock: str                                      # none / jp-gate / jp-prop / jp
    gate: str
    prop_cells: int
    a9_row: bool
    codes: Dict[int, bytes]                          # every reachable cell -> code
    reserved: Set[int]
    prop: List[int] = field(default_factory=list)    # free proportional cells, ascending
    wide: List[int] = field(default_factory=list)    # free fixed-width cells, ascending
    exe_sha1: str = ""

    def code_for(self, cell: int) -> bytes:
        try:
            return self.codes[cell]
        except KeyError:
            raise GlyphError(f"cell {cell} is not reachable by any code under this model")

    def summary(self) -> str:
        return (f"{self.build} (unlock {self.unlock}): gate {self.gate}, prop cells < {self.prop_cells}; "
                f"{len(self.codes)} cells have a code, {len(self.reserved & set(self.codes))} of them reserved; "
                f"free: {len(self.prop)} proportional, {len(self.wide)} wide")

    def to_json(self) -> dict:
        return {"build": self.build, "unlock": self.unlock, "gate": self.gate, "prop_cells": self.prop_cells,
                "a9_row": self.a9_row, "exe_sha1": self.exe_sha1,
                "prop": [[c, self.codes[c].hex().upper()] for c in self.prop],
                "wide": [[c, self.codes[c].hex().upper()] for c in self.wide],
                "reserved": sorted(self.reserved)}


def build_model(a: Addressing, retail: Iterable[int], font: Optional[Font] = None, unlock: str = "none",
                require_blank: Optional[bool] = None, exe_sha1: str = "") -> SlotModel:
    """Free slots of a build. ``retail`` = cells retail text draws (``scan_retail``,
    taken under the ORIGINAL addressing: they stay reserved under an unlock, and
    ``code_for`` gives their new codes). ``require_blank`` also refuses cells the
    font has ink in (on the Japanese disc no reachable cell is blank, so the
    default is off everywhere: a free cell is one no retail text draws).

    With ``font`` given, a fixed-width cell below 384 whose half-size image
    (cell + 0x240, drawn under control 0x18) has ink is reserved too: on Japan
    that is the whole kana block 192-383, including A4F4-A4FC whose half-size
    images 851-859 are the unexplained '3 K O S - M ...' glyphs."""
    if unlock != "none":
        a = unlocked_addressing(a, unlock)
    require_blank = bool(require_blank)
    if require_blank and font is None:
        raise GlyphError("require_blank needs the font")
    slots_ok = set(reachable(a, 0))
    codes = reachable(a, 0, flagged=True)
    reserved: Set[int] = {0, FALLBACK_CELL}
    for b in range(0x20, 0x80):                                     # the $han table
        code = a.han_code(b)
        reserved.add(fontmod.cell_index(a.cell(code >> 8, code & 0xFF, 0)))
    for c in retail:
        c = fontmod.cell_index(c)
        reserved.add(c)
        reserved.add(fontmod.cell_index(half_cell(c)))
    reserved.update(PROP_IMAGES)
    reserved.update(range(EXTRA_KANJI_BASE, CELL_COUNT))
    if font is not None:
        reserved.update(c for c in range(a.prop_cells, PROP_LIMIT)
                        if any(any(r) for r in font.cell(c + PROP_CELL_SHIFT)))
    prop, wide = [], []
    for c in sorted(slots_ok):
        if c in reserved:
            continue
        if require_blank and (any(any(r) for r in font.cell(c))
                              or (c < a.prop_cells and any(any(r) for r in font.cell(c + PROP_CELL_SHIFT)))):
            continue
        (prop if c < a.prop_cells else wide).append(c)
    return SlotModel(a.profile, unlock, a.gate, a.prop_cells, a.a9_row, codes, reserved, prop, wide, exe_sha1)


def model_from_disc(iso_path, unlock: str = "none", require_blank: Optional[bool] = None,
                    font_no: int = 0, include_untranslated: bool = False) -> Tuple[SlotModel, Addressing, RetailScan]:
    """The slot model of a disc: its executable's addressing, its retail text
    scanned, and its font (for the half-size rule and ``require_blank``).
    ``include_untranslated`` also reserves what the Japanese left in the USA
    build would draw (off by default: those lines show as soup either way)."""
    from disc import Disc
    exe = fontmod.read_boot_exe(iso_path)
    applied = applied_unlock(exe)
    if applied != "none":
        if unlock not in ("none", applied):
            raise GlyphError(f"this disc's executable already carries unlock {applied!r}, not {unlock!r}")
        unlock = applied
        exe = fontmod.unpatched(exe)            # retail text is read under the retail rules
    a = Addressing.from_executable(exe)
    with Disc(iso_path) as d:
        scan = scan_retail(d, a)
        f = Font.from_bytes(d.read(fontmod.font_paths(a.font_dir)[font_no]))
    m = build_model(a, scan.reserved(include_untranslated), f, unlock, require_blank,
                    hashlib.sha1(exe).hexdigest())
    return m, a, scan


def applied_unlock(exe: bytes) -> str:
    """Which unlock mode a USA / prototype executable carries ("none" for a retail
    one, and for any other build: the Japanese gate is native there)."""
    if fontmod.profile_for(exe).name not in UNLOCK_BUILDS:
        return "none"
    on = set()
    for name, patches in UNLOCKS.items():
        state = [fontmod.read_va(exe, p.va, len(p.new)) == p.new for p in patches]
        if all(state):
            on.add(name)
        elif any(state):
            raise GlyphError(f"unlock {name!r} is only partly applied to this executable")
    for mode, names in UNLOCK_MODES.items():
        if set(names) == on:
            return mode
    raise GlyphError(f"unlock state {sorted(on)} matches no mode")


# --- allocation -----------------------------------------------------------------------

class GlyphSet:
    def __init__(self, source: str = ""):
        self.source = source
        self.glyphs: Dict[str, Glyph] = {}
        self.slots: Dict[str, dict] = {}     # key -> {tier, cell, code (bytes), left, right}
        self.model: dict = {}                # build / unlock / exe_sha1 the slots were made for

    def add(self, g: Glyph) -> None:
        self.glyphs[g.key] = g

    def allocate(self, order: Sequence[str], model: SlotModel, prop_only: bool = False,
                 wide_only: bool = False) -> None:
        """Give every key in ``order`` (most frequent first) a slot: free
        proportional cells first (ink up to 18 px wide), then wide cells. Keys
        already placed keep their place; the result depends only on ``order``,
        the model and the bitmaps."""
        if self.model and (self.model.get("build"), self.model.get("unlock")) != (model.build, model.unlock):
            raise GlyphError(f"this glyph set was made for {self.model.get('build')}/{self.model.get('unlock')}, "
                             f"not {model.build}/{model.unlock}")
        self.model = {"build": model.build, "unlock": model.unlock, "exe_sha1": model.exe_sha1,
                      "prop_cells": model.prop_cells}
        used = {v["cell"] for v in self.slots.values()}
        clash = used & model.reserved
        if clash:
            raise GlyphError(f"placed glyphs sit on cells the model reserves: {sorted(clash)[:10]}")
        free_prop = [c for c in model.prop if c not in used]
        free_wide = [c for c in model.wide if c not in used]
        for key in order:
            if key in self.slots:
                continue
            g = self.glyphs.get(key)
            if g is None:
                raise GlyphError(f"no bitmap for key {key!r}")
            if not wide_only and free_prop and (g.ink_width <= 18 or prop_only):
                c = free_prop.pop(0)
                left, right = self._prop_metrics(g)
                self.slots[key] = {"tier": "prop", "cell": c, "code": model.code_for(c), "left": left, "right": right}
            elif not prop_only and free_wide:
                c = free_wide.pop(0)
                self.slots[key] = {"tier": "wide", "cell": c, "code": model.code_for(c), "left": 0, "right": 19}
            else:
                raise GlyphError(f"out of font cells at key {key!r} ({len(self.slots)} placed)")

    @staticmethod
    def _prop_metrics(g: Glyph) -> Tuple[int, int]:
        """(left, right) for a proportional slot. Ink starts at column 1 at the
        earliest (``apply`` shifts the bitmap to match), so the advance is always
        FUN_00185770's ``right - left + 3``."""
        if g.bounds is None:
            w = max(2, min(18, (g.advance_hint or 6) - 2))
            return 1, w                       # blank slot with a usable advance
        left, right = g.bounds
        shift = 1 - left if left < 1 else 0
        return 1 if shift else left, min(19, right + shift)

    def width(self, key: str) -> int:
        s = self.slots[key]
        return s["right"] - s["left"] + 3 if s["tier"] == "prop" else FIXED_ADVANCE

    # applying
    def apply(self, font: Font) -> None:
        """Draw every placed glyph into ``font``: proportional = ink-aligned image
        at cell + 0x240 plus metrics at the cell, and a centred copy at the cell;
        wide = centred at the cell."""
        for key, s in self.slots.items():
            g = self.glyphs[key]
            bm = g.bitmap
            centred = shift_x(bm, (CELL_W - g.ink_width) // 2 - g.bounds[0]) if g.bounds else bm
            if s["tier"] == "prop":
                aligned = shift_x(bm, s["left"] - g.bounds[0]) if g.bounds and g.bounds[0] != s["left"] else bm
                font.set_cell(s["cell"] + PROP_CELL_SHIFT, aligned)
                font.set_metrics(s["cell"], s["left"], s["right"])
            font.set_cell(s["cell"], centred)

    # persistence
    def to_json(self) -> str:
        return json.dumps({
            "source": self.source,
            "model": self.model,
            "slots": {k: dict(v, code=v["code"].hex().upper()) for k, v in self.slots.items()},
            "bitmaps": {k: ["".join(str(v) for v in row) for row in g.bitmap]
                        for k, g in self.glyphs.items()},
        }, ensure_ascii=False, indent=0)

    @classmethod
    def from_json(cls, text: str) -> "GlyphSet":
        d = json.loads(text)
        gs = cls(d.get("source", ""))
        gs.model = d.get("model", {})
        for k, rows in d.get("bitmaps", {}).items():
            gs.add(Glyph(k, [[int(ch) for ch in row] for row in rows]))
        for k, v in d.get("slots", {}).items():
            gs.slots[k] = dict(v, code=bytes.fromhex(v["code"]))
        return gs

    def save(self, path) -> None:
        Path(path).write_text(self.to_json(), encoding="utf-8")

    @classmethod
    def load(cls, path) -> "GlyphSet":
        return cls.from_json(Path(path).read_text(encoding="utf-8"))

    def code_bytes(self, key: str) -> bytes:
        return self.slots[key]["code"]

    def check(self, a: Addressing, model: SlotModel) -> List[str]:
        """Problems: a slot on a reserved cell, two keys on one cell, or a code
        that the addressing does not draw as the slot's cell."""
        out, seen = [], {}
        for k, s in self.slots.items():
            c = s["cell"]
            if c in model.reserved:
                out.append(f"{k}: cell {c} is reserved")
            if c in seen:
                out.append(f"{k}: cell {c} also holds {seen[c]}")
            seen[c] = k
            g = a.glyph(s["code"] + b"\0", 0, True, 0)
            if g.length != len(s["code"]) or fontmod.cell_index(g.cell) != c:
                out.append(f"{k}: code {s['code'].hex()} draws cell {g.cell}, not {c}")
            if s["tier"] == "prop" and not a.is_prop(c):
                out.append(f"{k}: cell {c} is not proportional under this addressing")
        return out


# --- PNG cells -------------------------------------------------------------------------

def from_png(png_path, keys: Iterable[str], source: str = "") -> GlyphSet:
    """Cells read left-to-right, top-to-bottom from a 20x24-grid PNG."""
    w, h, gray = fontmod.png_to_gray(Path(png_path).read_bytes())
    if w % CELL_W or h % CELL_H:
        raise GlyphError(f"sheet {w}x{h} is not a multiple of {CELL_W}x{CELL_H}")
    q = fontmod.quantize(gray)
    per_row = w // CELL_W
    gs = GlyphSet(source or str(png_path))
    for i, key in enumerate(keys):
        cx, cy = (i % per_row) * CELL_W, (i // per_row) * CELL_H
        if cy + CELL_H > h:
            raise GlyphError("more keys than cells in the sheet")
        bm = [list(q[(cy + r) * w + cx:(cy + r) * w + cx + CELL_W]) for r in range(CELL_H)]
        gs.add(Glyph(key, bm))
    return gs


def to_png(glyphs: Sequence[Glyph], per_row: int = 16) -> bytes:
    """A preview / editing sheet of 20x24 cells (the layout ``from_png`` reads)."""
    rows = max(1, -(-len(glyphs) // per_row))
    w, h = per_row * CELL_W, rows * CELL_H
    px = bytearray(w * h)
    for i, g in enumerate(glyphs):
        cx, cy = (i % per_row) * CELL_W, (i // per_row) * CELL_H
        for y in range(CELL_H):
            for x in range(CELL_W):
                px[(cy + y) * w + cx + x] = fontmod.GREY[g.bitmap[y][x] & 3]
    return fontmod.gray_png(px, w, h)


# --- TrueType rendering (fonttools + uharfbuzz, required) -------------------------------

class TTFRenderer:
    """Shape text with HarfBuzz and rasterise glyph outlines into cells.

    ``px`` is the em size in pixels (20 fits most scripts in a 24 px cell;
    Devanagari with stacked marks may want 16-18), ``baseline`` the cell
    row the baseline sits on (default 17: six rows for descenders).
    """

    def __init__(self, path, px: float = 20.0, baseline: int = 17,
                 face_index: int = 0, features: Optional[dict] = None,
                 supersample: int = 4):
        from fontTools.ttLib import TTFont, TTCollection
        import uharfbuzz as hb
        self.hb = hb
        p = Path(path)
        data = p.read_bytes()
        if p.suffix.lower() == ".ttc":
            self.tt = TTCollection(str(p)).fonts[face_index]
        else:
            self.tt = TTFont(str(p))
        self.upem = self.tt["head"].unitsPerEm
        self.glyph_set = self.tt.getGlyphSet()
        self.glyph_order = self.tt.getGlyphOrder()
        face = hb.Face(data, face_index)
        self.hbfont = hb.Font(face)
        self.hbfont.scale = (self.upem, self.upem)
        self.px = px
        self.baseline = baseline
        # one cell per glyph: keep required ligatures (lam-alef, conjuncts)
        # but not the optional wide ones a 20 px cell cannot hold
        self.features = {"liga": False, "dlig": False, "calt": False} if features is None else features
        self.ss = supersample
        self.name = p.stem
        self.scale = px / self.upem

    # shaping
    def shape(self, text: str, direction: str = "ltr", script: Optional[str] = None,
              language: Optional[str] = None):
        """-> list of (gid, cluster, x_advance, x_offset, y_offset) in font units."""
        hb = self.hb
        buf = hb.Buffer()
        buf.add_str(text)
        buf.guess_segment_properties()
        buf.direction = direction
        if script:
            buf.script = script
        if language:
            buf.language = language
        hb.shape(self.hbfont, buf, self.features)
        return [(i.codepoint, i.cluster, p.x_advance, p.x_offset, p.y_offset)
                for i, p in zip(buf.glyph_infos, buf.glyph_positions)]

    def gid_name(self, gid: int) -> str:
        return self.glyph_order[gid]

    def advance_px(self, gid: int) -> float:
        return self.hbfont.get_glyph_h_advance(gid) * self.scale

    # outlines
    def contours(self, gid: int) -> List[List[Tuple[float, float]]]:
        """Flattened closed contours in font units."""
        from fontTools.pens.recordingPen import DecomposingRecordingPen
        pen = DecomposingRecordingPen(self.glyph_set)   # flattens TrueType components
        self.glyph_set[self.gid_name(gid)].draw(pen)
        out: List[List[Tuple[float, float]]] = []
        cur: List[Tuple[float, float]] = []
        last = (0.0, 0.0)
        for op, args in pen.value:
            if op == "moveTo":
                if cur:
                    out.append(cur)
                cur = [args[0]]
                last = args[0]
            elif op == "lineTo":
                cur.append(args[0])
                last = args[0]
            elif op == "qCurveTo":
                pts = list(args)
                if pts[-1] is None:          # TrueType implied on-curve start
                    pts = pts[:-1]
                ctrls = pts[:-1]
                end = pts[-1]
                p0 = last
                for i, c in enumerate(ctrls):
                    nxt = ctrls[i + 1] if i + 1 < len(ctrls) else end
                    p2 = nxt if i + 1 == len(ctrls) else ((c[0] + nxt[0]) / 2, (c[1] + nxt[1]) / 2)
                    for t in range(1, 9):
                        u = t / 8
                        x = (1 - u) ** 2 * p0[0] + 2 * (1 - u) * u * c[0] + u * u * p2[0]
                        y = (1 - u) ** 2 * p0[1] + 2 * (1 - u) * u * c[1] + u * u * p2[1]
                        cur.append((x, y))
                    p0 = p2
                last = end
            elif op == "curveTo":
                c1, c2, end = args[-3], args[-2], args[-1]
                p0 = last
                for t in range(1, 9):
                    u = t / 8
                    x = ((1 - u) ** 3 * p0[0] + 3 * (1 - u) ** 2 * u * c1[0]
                         + 3 * (1 - u) * u * u * c2[0] + u ** 3 * end[0])
                    y = ((1 - u) ** 3 * p0[1] + 3 * (1 - u) ** 2 * u * c1[1]
                         + 3 * (1 - u) * u * u * c2[1] + u ** 3 * end[1])
                    cur.append((x, y))
                last = end
            elif op in ("closePath", "endPath"):
                if cur:
                    out.append(cur)
                cur = []
        if cur:
            out.append(cur)
        return out

    # rasterising
    def raster(self, placements: Sequence[Tuple[int, float, float]],
               x_origin: float = 1.0) -> Bitmap:
        """Draw glyphs (gid, x_px, y_px offsets from the pen) into one cell.
        Even-odd scanline fill at ``supersample`` x resolution, then averaged
        to the four levels the font supports."""
        ss = self.ss
        W, H = CELL_W * ss, CELL_H * ss
        cov = [[0] * W for _ in range(H)]
        edges = []
        for gid, dx, dy in placements:
            for contour in self.contours(gid):
                pts = [((x_origin + dx + x * self.scale) * ss,
                        (self.baseline - dy - y * self.scale) * ss) for x, y in contour]
                for i in range(len(pts)):
                    x0, y0 = pts[i]
                    x1, y1 = pts[(i + 1) % len(pts)]
                    if y0 != y1:
                        edges.append((x0, y0, x1, y1))
        for sy in range(H):
            yc = sy + 0.5
            xs = []
            for x0, y0, x1, y1 in edges:
                if (y0 <= yc < y1) or (y1 <= yc < y0):
                    xs.append(x0 + (yc - y0) * (x1 - x0) / (y1 - y0))
            xs.sort()
            for i in range(0, len(xs) - 1, 2):
                a, b = int(math.floor(xs[i] + 0.5)), int(math.floor(xs[i + 1] + 0.5))
                for sx in range(max(a, 0), min(b, W)):
                    cov[sy][sx] = 1
        bm = blank()
        n = ss * ss
        for y in range(CELL_H):
            for x in range(CELL_W):
                s = sum(cov[y * ss + j][x * ss + i] for j in range(ss) for i in range(ss))
                bm[y][x] = min(3, (s * 4 + n // 2) // n) if s else 0
        return bm

    def render_gid(self, gid: int) -> Glyph:
        bm = self.raster([(gid, 0.0, 0.0)])
        return Glyph(f"g:{self.name}:{gid}", bm, round(self.advance_px(gid)))

    def render_cluster(self, parts: Sequence[Tuple[int, float, float]], key: str) -> Glyph:
        return Glyph(key, self.raster(parts))

    def render_text(self, text: str, key: str, direction: str = "ltr",
                    script: Optional[str] = None) -> Glyph:
        """Shape ``text`` as one unit and draw it into one cell (left-aligned)."""
        pen = 0.0
        parts = []
        for gid, _, adv, xo, yo in self.shape(text, direction, script):
            parts.append((gid, (pen + xo) * self.scale, yo * self.scale))
            pen += adv
        return Glyph(key, self.raster(parts), round(pen * self.scale))


# --- T7: font coverage of retail text -------------------------------------------------

# Codes the Japanese retail text uses that no font cell answers: E5D0 '縊' (once,
# bat\jp\RAV_B02.sb, in '少々見縊っていたようね'). Lead E5 >= 0xD0 goes through the
# extra-kanji lists, and E5D0 is in neither, so the game would draw cell 0x7F
# there (not checked in game).
T7_KNOWN_GAPS = ("E5D0",)

def coverage(d, a: Addressing, fonts: Sequence[Font]) -> dict:
    """Every two-byte code (lead >= 0xA0) in the parsed retail strings, resolved
    through ``a`` in each font. A code passes when it is A1A1 (the full-width
    space, blank by design) or resolves in at least one font to an inked cell
    other than the fallback; codes whose lead is 0xD0 or above resolve only
    through that font's extra-kanji list, so they are judged per font."""
    sources = text_sources(_disc_paths(d), a.font_dir)
    pairs: Counter = Counter()
    kinds: Counter = Counter()
    for _p, kind, s, _cat in scan_strings(d.read, sources, "euc" if a.gate == "euc" else a.gate):
        if kind == "raw":
            continue
        kinds[kind] += 1
        i = 0
        while i < len(s):
            if a.pair(s[i], s[i + 1] if i + 1 < len(s) else 0) and i + 1 < len(s) and s[i] >= 0xA0:
                pairs[(s[i], s[i + 1])] += 1
                i += 2
            else:
                i += 1
    ink = [[any(any(r) for r in f.cell(c)) for c in range(CELL_COUNT)] for f in fonts]
    bad, per_font_only = Counter(), Counter()
    for (l, t), n in pairs.items():
        if (l, t) == (0xA1, 0xA1):
            continue
        ok = []
        for k in range(len(fonts)):
            c = fontmod.cell_index(a.cell(l, t, k))
            ok.append(c != FALLBACK_CELL and ink[k][c])
        if not any(ok):
            bad[(l, t)] += n
        elif not all(ok):
            per_font_only[(l, t)] += n
    return {"strings": dict(kinds), "codes": len(pairs), "uses": sum(pairs.values()),
            "unresolved": {f"{l:02X}{t:02X}": n for (l, t), n in sorted(bad.items())},
            "one_font_only": len(per_font_only),
            "one_font_only_all_extra": all(l >= 0xD0 for l, _ in per_font_only)}


# --- CLI ------------------------------------------------------------------------------

def _wrap(fn):
    def run(a):
        try:
            return fn(a)
        except (GlyphError, FontError) as e:
            print(f"refused: {e}", file=sys.stderr)
            return 1
    return run


def cmd_slots(a) -> int:
    m, ad, scan = model_from_disc(a.iso, a.unlock, a.require_blank, a.font, a.include_untranslated)
    print(m.summary())
    print(f"retail scan: {dict(scan.files)} files, {sum(scan.strings.values())} strings, "
          f"{len(scan.cells)} distinct cells drawn by text, {len(scan.untranslated)} by untranslated Japanese"
          f"{' (reserved)' if a.include_untranslated else ' (not reserved)'}")
    if a.json:
        Path(a.json).write_text(json.dumps(dict(m.to_json(), retail=scan.to_json()), indent=0))
        print(f"wrote {a.json}")
    return 0


def cmd_coverage(a) -> int:
    from disc import Disc
    ad = Addressing.from_iso(a.iso)
    with Disc(a.iso) as d:
        fonts = [Font.from_bytes(d.read(p)) for p in fontmod.font_paths(ad.font_dir)]
        rep = coverage(d, ad, fonts)
    print(json.dumps(rep, indent=1))
    new = set(rep["unresolved"]) - set(T7_KNOWN_GAPS)
    if new:
        print(f"codes no cell answers (beyond the known {', '.join(T7_KNOWN_GAPS)}): {sorted(new)}", file=sys.stderr)
    return 2 if new else 0


def cmd_render(a) -> int:
    m, ad, _scan = model_from_disc(a.iso, a.unlock, a.require_blank, 0, a.include_untranslated)
    r = TTFRenderer(a.ttf, px=a.px, baseline=a.baseline)
    gs = GlyphSet.load(a.out) if a.keep and Path(a.out).exists() else GlyphSet(a.ttf)
    order = []
    for ch in a.text:
        key = f"u:{ch}"
        if key not in gs.glyphs:
            gs.add(r.render_text(ch, key, direction=a.direction))
        if key not in order:
            order.append(key)
    gs.allocate(order, m, prop_only=a.prop_only, wide_only=a.wide_only)
    probs = gs.check(unlocked_addressing(ad, a.unlock), m)
    if probs:
        raise GlyphError("; ".join(probs[:5]))
    gs.save(a.out)
    if a.png:
        Path(a.png).write_bytes(to_png([gs.glyphs[k] for k in order]))
    tiers = Counter(gs.slots[k]["tier"] for k in order)
    print(f"{len(order)} glyphs placed ({dict(tiers)}); {m.summary()} -> {a.out}")
    return 0


def cmd_apply(a) -> int:
    if Path(a.out).resolve() == Path(a.font).resolve():
        raise GlyphError("--out is the input font; give another name")
    gs = GlyphSet.load(a.glyphset)
    f = Font.load(a.font)
    gs.apply(f)
    Path(a.out).write_bytes(f.to_bytes())
    print(f"{len(gs.slots)} glyphs drawn into {a.font} -> {a.out}")
    return 0


def unlock_exe(iso, mode: str) -> Tuple[str, bytes, List[str]]:
    """(boot executable name, patched bytes, report lines) of one image; refuses
    builds the patches were not made for."""
    from iso9660 import IsoImage
    with IsoImage(iso) as im:
        name = im.boot_elf_name()
        if not name:
            raise GlyphError(f"{iso}: no boot executable")
        exe = bytes(im.read_file(name))
    prof = fontmod.profile_for(exe)
    if prof.name not in UNLOCK_BUILDS:
        raise GlyphError(f"the {prof.name} executable is not a build these patches were made for")
    new, rep = apply_patches(exe, unlock_patches(mode))
    return name, new, rep


def cmd_unlock(a) -> int:
    """--out-exe FILE writes the patched executable of one --iso; --out OUT writes
    patched COPIES of the image(s) through patch.patch_copy (both discs' boot
    executables, verified; an existing output is refused unless --overwrite).
    Nothing here writes into an image it was given."""
    if bool(a.out_exe) == bool(a.out):
        raise GlyphError("give exactly one of --out-exe FILE or --out OUT (patched copies of the --iso images)")
    if a.out_exe:
        if len(a.iso) != 1:
            raise GlyphError("--out-exe takes one --iso (each disc boots its own copy; 'patch --iso D1 "
                             "--iso D2 --set NAME=FILE' then writes it to both)")
        if any(patch.same_file(i, a.out_exe) for i in a.iso):
            raise GlyphError("--out-exe is the --iso image itself")
        name, new, rep = unlock_exe(a.iso[0], a.mode)
        Path(a.out_exe).write_bytes(new)
        rep = rep + [f"{name} -> {a.out_exe}"]
    else:
        changes = {}
        rep = []
        for iso in a.iso:
            name, new, r = unlock_exe(iso, a.mode)
            changes[name] = new
            rep += [f"{Path(iso).name}: {name}: {x}" for x in r]
        try:
            patch.patch_copy(list(a.iso), a.out, changes, overwrite=a.overwrite, dry_run=a.dry_run)
        except patch.PatchError as e:
            raise GlyphError(str(e))
    for ln in rep:
        print(ln)
    print("NOT tested in game: boot the patched image in PCSX2 before relying on it")
    return 0


def add_commands(subparsers) -> None:
    def common(p, iso=True):
        if iso:
            p.add_argument("--iso", required=True)
        p.add_argument("--unlock", choices=tuple(UNLOCK_MODES), default="none",
                       help="slot model of the USA executable after this exe patch (glyphs-unlock)")
        p.add_argument("--require-blank", action="store_true",
                       help="only cells the font leaves blank (none are, on the Japanese disc)")
        p.add_argument("--include-untranslated", action="store_true",
                       help="USA: also reserve the cells the Japanese left in the USA build would draw")

    p = subparsers.add_parser("glyphs-slots", help="free font cells for new glyphs (per build, retail text scanned)")
    common(p)
    p.add_argument("--font", type=int, choices=(0, 1), default=0, help="font whose ink --require-blank checks")
    p.add_argument("--json")
    p.set_defaults(func=_wrap(cmd_slots))

    p = subparsers.add_parser("glyphs-coverage", help="every EUC pair in the retail text resolves to an inked cell")
    p.add_argument("--iso", required=True)
    p.set_defaults(func=_wrap(cmd_coverage))

    p = subparsers.add_parser("glyphs-render", help="render characters from a TTF/OTF into a glyph set (json)")
    common(p)
    p.add_argument("--ttf", required=True)
    p.add_argument("--text", required=True, help="the characters to place, one cell each")
    p.add_argument("--px", type=float, default=20.0)
    p.add_argument("--baseline", type=int, default=17)
    p.add_argument("--direction", default="ltr", choices=("ltr", "rtl"))
    p.add_argument("--prop-only", action="store_true")
    p.add_argument("--wide-only", action="store_true")
    p.add_argument("--keep", action="store_true", help="extend an existing --out glyph set (codes kept)")
    p.add_argument("--out", required=True)
    p.add_argument("--png", help="preview sheet of the glyphs")
    p.set_defaults(func=_wrap(cmd_render))

    p = subparsers.add_parser("glyphs-apply", help="draw a glyph set into a font .bin")
    p.add_argument("--glyphset", required=True)
    p.add_argument("--font", required=True)
    p.add_argument("--out", required=True)
    p.set_defaults(func=_wrap(cmd_apply))

    p = subparsers.add_parser("glyphs-unlock", help="patch the USA executable's gate / prop gate (untested in game)")
    p.add_argument("--iso", required=True, action="append",
                   help="source image, never written (repeat for Disc 1 + Disc 2 with --out)")
    p.add_argument("--mode", required=True, choices=tuple(m for m in UNLOCK_MODES if m != "none"))
    p.add_argument("--out-exe", help="write the patched executable of the one --iso here")
    p.add_argument("--out", help="write patched COPIES of the --iso images here (folder, or one .iso path)")
    p.add_argument("--overwrite", action="store_true", help="with --out: replace earlier outputs of this kit")
    p.add_argument("--dry-run", action="store_true", help="with --out: show the plan only")
    p.set_defaults(func=_wrap(cmd_unlock))


# --- self-test --------------------------------------------------------------------------

def _test_ttf(path: Path) -> None:
    """A two-glyph TrueType font built in code: 'A' = a 500x700 box with a 300x500
    hole, 'L' = an L shape (upem 1000)."""
    from fontTools.fontBuilder import FontBuilder
    from fontTools.pens.ttGlyphPen import TTGlyphPen

    def box(pen, x0, y0, x1, y1, cw=True):
        pts = [(x0, y0), (x0, y1), (x1, y1), (x1, y0)]
        if not cw:
            pts.reverse()
        pen.moveTo(pts[0])
        for p in pts[1:]:
            pen.lineTo(p)
        pen.closePath()

    fb = FontBuilder(1000, isTTF=True)
    fb.setupGlyphOrder([".notdef", "A", "L"])
    fb.setupCharacterMap({0x41: "A", 0x4C: "L"})
    glyphs = {}
    pen = TTGlyphPen(None)
    glyphs[".notdef"] = pen.glyph()
    pen = TTGlyphPen(None)
    box(pen, 0, 0, 500, 700)
    box(pen, 100, 100, 400, 600, cw=False)
    glyphs["A"] = pen.glyph()
    pen = TTGlyphPen(None)
    pen.moveTo((0, 0)); pen.lineTo((0, 700)); pen.lineTo((150, 700)); pen.lineTo((150, 150))
    pen.lineTo((450, 150)); pen.lineTo((450, 0)); pen.closePath()
    glyphs["L"] = pen.glyph()
    fb.setupGlyf(glyphs)
    fb.setupHorizontalMetrics({".notdef": (500, 0), "A": (600, 0), "L": (550, 0)})
    fb.setupHorizontalHeader(ascent=800, descent=-200)
    fb.setupNameTable({"familyName": "XS3Test", "styleName": "Regular"})
    fb.setupOS2()
    fb.setupPost()
    fb.save(str(path))


def self_test() -> int:
    import tempfile
    ok = True

    def check(cond, msg):
        nonlocal ok
        print(("ok    " if cond else "FAIL  ") + msg)
        ok &= bool(cond)

    # synthetic addressing (font.py's synthetic executable, USA and JP layouts)
    us_prof = dataclasses.replace(fontmod.PROFILES["def4d42429001ca86111c6fa86dc84bdeb9a93c4"], clut_va=0)
    jp_prof = dataclasses.replace(fontmod.PROFILES["e8125f743e0e7fda0ec392ea845dd0069470af3b"], clut_va=0)
    us_elf = fontmod._synthetic_elf(us_prof)
    a = Addressing.from_executable(us_elf, us_prof)
    aj = Addressing.from_executable(fontmod._synthetic_elf(jp_prof, gate="euc", prop=0xC0, a9_row=False), jp_prof)

    codes = reachable(a)
    check(codes[193] == b"\xa4\xa2" and codes[361] == b"\xe9" and codes[256] == b"\x80"
          and 292 not in codes and 0x7B in codes and codes[384] == b"\xa6\xa1" and codes[438] == b"\xa6\xdf"
          and codes[565] == b"\xad\xb6" and not any(c >= 1024 for c in codes),
          "USA reachable: A4A2 -> 193, E9 -> 361, 80 -> 256, A4 not a single, A2F6, A6 384-438, ADB6; no kanji")
    check(len([c for c in codes if c < 384]) == len({c for c in codes if c < 384}) and
          all(not (c & FIXED_FLAG) for c in codes), "USA reachable: no 0x1000-flagged cells")
    retail = {193, 361, 384, 300}
    m = build_model(a, retail)
    check(not (set(m.prop) | set(m.wide)) & m.reserved and 193 not in m.prop and 384 not in m.wide
          and all(c < 384 for c in m.prop) and all(384 <= c < 576 for c in m.wide)
          and not set(m.prop) & set(range(128, 138)),
          f"USA model: free {len(m.prop)} prop / {len(m.wide)} wide, none reserved (retail, han digits)")
    mj = build_model(aj, set(), font=Font.blank())
    check(any(c >= 1024 for c in mj.wide) and all(c >= 192 for c in mj.wide) and all(c < 192 for c in mj.prop)
          and not set(mj.wide) & set(PROP_IMAGES) and not set(mj.wide) & set(range(EXTRA_KANJI_BASE, CELL_COUNT)),
          f"JP model (blank font): kanji wide tier, prop < 192, images 576-959 and extras never slots "
          f"({len(mj.prop)} prop / {len(mj.wide)} wide)")
    inked = Font.blank()
    inked.set_cell(1024, [[1] * 20] * 24)
    mj2 = build_model(aj, set(), font=inked, require_blank=True)
    check(1024 in mj.wide and 1024 not in mj2.wide, "JP model: a cell the font has ink in is not free")
    mu = build_model(a, retail, unlock="jp")
    check(mu.gate == "euc" and mu.prop_cells == 0xC0 and len([c for c in mu.wide if 1024 <= c < 3989]) == 2965
          and mu.code_for(361) == b"\xa5\xea" and unlocked_addressing(a, "jp").glyph(b"\xa5\xea").cell == 361
          and 361 in mu.reserved and mu.code_for(383)[1] < 0xA1
          and unlocked_addressing(a, "jp").glyph(mu.code_for(383)).cell == 383,
          "unlock jp: 2,965 kanji cells wide, prop < 192, retail e-acute (361) kept reserved with new code A5EA; "
          f"cell 383 only through a non-EUC trail ({mu.code_for(383).hex().upper()})")

    # glyph sets: determinism and no collision with reserved cells
    def make_set():
        gs = GlyphSet("test")
        for k in range(300):
            w = 4 + k % 17
            gs.add(Glyph(f"u:{k}", [[3 if 2 <= x < 2 + w and 4 <= y < 18 else 0 for x in range(20)]
                                    for y in range(24)]))
        return gs
    order = [f"u:{k}" for k in range(300)]
    g1, g2 = make_set(), make_set()
    g1.allocate(order[:120], mj)
    g1.allocate(order, mj)
    g2.allocate(order, mj)
    check(g1.to_json() == g2.to_json(), "allocation is deterministic (incremental == one pass)")
    g3 = make_set()
    g3.allocate(order[:40], mj)
    before = {k: dict(v) for k, v in g3.slots.items()}
    g3.allocate(order[40:80] + order[:40], mj)
    check(all(g3.slots[k] == v for k, v in before.items()), "keys already placed keep their codes")
    gu = make_set()
    try:
        gu.allocate(order, m)
        check(False, "USA synthetic model runs out")
    except GlyphError:
        n_placed = len(gu.slots)
        check(n_placed == len(m.prop) + len(m.wide), f"USA model fills exactly its {n_placed} free cells, then refuses")
    check(not gu.check(a, m) and not g1.check(aj, mj), "no slot on a reserved cell; every code draws its cell")
    rt = GlyphSet.from_json(g1.to_json())
    check(rt.to_json() == g1.to_json() and rt.code_bytes(order[0]) == g1.code_bytes(order[0]), "json round trip")
    try:
        g1.allocate(order, m)
        check(False, "a glyph set made for another model refused")
    except GlyphError:
        check(True, "a glyph set made for another build/unlock is refused")

    # patches
    new, rep = apply_patches(us_elf, unlock_patches("jp"))
    ap = Addressing.read_rules(new, us_prof)
    check(ap == {"gate": "euc", "prop_cells": 0xC0, "a9_row": True} and len(rep) == 3,
          "unlock jp on a synthetic USA exe: euc gate, prop < 0xC0 (read back from the code)")
    new2, rep2 = apply_patches(new, unlock_patches("jp"))
    check(new2 == new and all("already" in r for r in rep2), "patching twice is a no-op")
    bad = bytearray(us_elf)
    o = fontmod.va_to_offset(us_elf, 0x182DD4)
    bad[o:o + 4] = b"\0\0\0\0"
    try:
        apply_patches(bytes(bad), unlock_patches("jp"))
        check(False, "old-byte mismatch refused")
    except GlyphError:
        check(True, "an old-byte mismatch refuses the whole patch set")
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        import iso9660
        cnf = b"BOOT2 = cdrom0:\\SLUS_213.89;1\r\nVER = 1.00\r\n"
        iso9660.make_test_image(td / "t.iso", [("SYSTEM.CNF", cnf), ("SLUS_213.89", us_elf)])
        rep3 = patch_iso(td / "t.iso", "jp-gate")
        with iso9660.IsoImage(td / "t.iso") as im:
            got = bytes(im.read_file("SLUS_213.89"))
        check(Addressing.read_rules(got, us_prof)["gate"] == "euc" and len(rep3) == 1
              and sum(x != y for x, y in zip(got, us_elf)) <= 16, "patch_iso on a synthetic image: gate only")

        # TTF -> 20x24 2bpp cell -> font file -> back
        ttf = td / "t.ttf"
        _test_ttf(ttf)
        r = TTFRenderer(ttf, px=20)
        gA = r.render_text("A", "u:A")
        gL = r.render_text("L", "u:L")
        cols = gA.bounds
        check(cols is not None and cols[0] == 1 and 10 <= cols[1] <= 11 and gA.bitmap[17 - 7][3] == 0
              and gA.bitmap[17 - 1][2] == 3 and gA.bitmap[2][5] == 0 and gA.bitmap[3][5] == 3
              and gA.advance_hint == 12
              and set(v for row in gA.bitmap for v in row) <= {0, 1, 2, 3},
              f"TTF 'A' (box with hole) rasterised into a 20x24 cell: ink columns {cols}, hole empty, 4 levels")
        fnt = Font.blank()
        gs = GlyphSet(str(ttf))
        gs.add(gA)
        gs.add(gL)
        gs.allocate(["u:A", "u:L"], mj)
        gs.apply(fnt)
        back = Font.from_bytes(fnt.to_bytes())
        sA = gs.slots["u:A"]
        cen = shift_x(gA.bitmap, (20 - gA.ink_width) // 2 - gA.bounds[0])
        check(back.cell(sA["cell"]) == cen and (sA["tier"] != "prop" or (
              back.cell(sA["cell"] + PROP_CELL_SHIFT) == gA.bitmap and back.metrics[sA["cell"]] == (1, cols[1]))),
              f"glyph written to cell {sA['cell']} ({sA['tier']}) survives to_bytes/from_bytes "
              f"(image, cell+576 and metrics)")
        (td / "s.png").write_bytes(to_png([gA, gL]))
        gp = from_png(td / "s.png", ["u:A", "u:L"])
        check(gp.glyphs["u:A"].bitmap == gA.bitmap and gp.glyphs["u:L"].bitmap == gL.bitmap,
              "to_png -> from_png round trip")

    # discs
    import disc as discmod
    for key in ("XS3_D1", "XS3_PROTO", "XS3_JP1"):
        iso = os.environ.get(key)
        if not iso:
            print(f"SKIP  {key} not set")
            continue
        model, ad, scan = model_from_disc(iso)
        bad_hits = (set(model.prop) | set(model.wide)) & set(scan.cells)
        check(not bad_hits and scan.files.get("sb", 0) > 700 and scan.files.get("txd") == 4
              and scan.files.get("nj") == 7,
              f"{key}: {model.summary()}; retail cells {len(scan.cells)} (files {dict(scan.files)}); "
              f"no free cell is one retail text draws")
        gsd = make_set()
        try:
            gsd.allocate(order, model)
        except GlyphError:
            pass
        probs = gsd.check(ad, model)
        check(not probs and len(gsd.slots) == min(300, len(model.prop) + len(model.wide)),
              f"{key}: {len(gsd.slots)} glyphs allocated, none on a reserved cell, every code draws its cell")
        if ad.gate == "whitelist":
            mu = build_model(ad, scan.cells, unlock="jp")
            exe = fontmod.read_boot_exe(iso)
            new, _r = apply_patches(exe, unlock_patches("jp"))
            rules = Addressing.read_rules(new, fontmod.profile_for(exe))
            kanji = len([c for c in mu.wide if 1024 <= c < 3989])
            check(rules == {"gate": "euc", "prop_cells": 0xC0, "a9_row": True} and kanji == 2965
                  and all(c in mu.codes for c in scan.cells if c not in (FALLBACK_CELL,)),
                  f"{key}: unlock jp verifies against the real exe (old words matched); {kanji} kanji cells wide; "
                  f"every retail cell still has a code")
        else:
            with discmod.Disc(iso) as d:
                fonts = [Font.from_bytes(d.read(p)) for p in fontmod.font_paths(ad.font_dir)]
                rep = coverage(d, ad, fonts)
            check(set(rep["unresolved"]) <= set(T7_KNOWN_GAPS) and rep["one_font_only_all_extra"]
                  and rep["strings"].get("sb", 0) > 90000,
                  f"{key} T7: {rep['codes']} distinct EUC codes ({rep['uses']} uses in {rep['strings']}) resolve "
                  f"to an inked cell (A1A1 excepted) except the known retail gap(s) {rep['unresolved']}; "
                  f"{rep['one_font_only']} only in one font, all extra-list kanji")
    print("self-test", "passed" if ok else "FAILED")
    return 0 if ok else 1


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["--self-test"]:
        return self_test()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    add_commands(sub)
    a = ap.parse_args(argv)
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
