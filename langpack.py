"""langpack.py — translate Episode III into scripts its font never had (Arabic,
Hebrew, Devanagari, Georgian, Japanese on the USA build, ...): shape, wrap,
order and encode text for the game's font.

Borrowed from Xenosaga1PythonExtractor/langpack.py (2026-11-20). Kept: the
pipeline (scan -> encode -> preview), ``arabic_forms`` and ``SimpleShaper`` (for
the hand-drawn ``--cells`` sheet only), ``HBShaper`` (HarfBuzz clusters as glyph
keys), the bidi pass (rewritten 2026-11-20 as UAX #9 proper: ``bidi_levels`` = rules
W1-W7, N0 paired brackets, N1-N2, I1-I2 on the whole paragraph before the wrap;
``reorder`` = L2 per wrapped line; L4 mirroring; checked against ICU 78), the
greedy pixel wrap, mixed-script words split into runs so their Latin halves stay Latin, ``--extend`` (a
second script into the same font pair), ``--prop-only`` / ``--wide-only``. What
changed for Episode III:

* uharfbuzz + fonttools are REQUIRED; there is no "no HarfBuzz" path for a
  TrueType font (``SimpleShaper`` serves only ``--cells``, where there is no
  font to shape with);
* slots come from ``glyphs.SlotModel`` (the build's addressing read from its
  executable, the cells retail text draws reserved, optional USA executable
  unlocks), not a fixed 256-slot block. A proportional glyph is drawn at
  cell + 0x240 with its metric pair, as ``glyphs.GlyphSet.apply`` does;
* widths are measured with ``font.Measurer`` (FUN_001828a0) on the bytes the
  game will see, in the ``$prop1;$han1;`` state the menus and dialogue use
  (``--state`` changes it);
* the tree is the XS3 ``text-export`` tree (``textpack``: ``### KEY`` block files
  and whole subtitle / .mes files, manifest FORMAT 2). Only strings in the
  build's DISPLAY codec are touched (``us`` on USA / the May 2006 prototype,
  ``jp`` on Japan); identifiers, developers' notes (cp932 / euc_jp), the cp932
  pse director scripts and ``fixed`` nj blocks are copied unchanged;
* a character is TARGET SCRIPT when the build cannot already draw it: the
  display codec refuses it, or its cell has no ink in either font (e.g. Arabic,
  Cyrillic, kana on USA; Arabic, Devanagari on Japan; Cyrillic and Greek ARE
  drawn by the Japanese font's JIS rows and stay as typed). A paragraph without
  a target character is copied byte for byte, so ``encode`` on an unmodified
  tree is the identity (exit test);
* control codes pass through in place and are never shaped, mirrored or
  wrapped across: ``$name...;`` commands (the executable's 18 names),
  ``$rubys; ... $rubye;`` spans, ``<...>`` script tags (``<f> <wNN> <lN> <colX>
  <kWORD> <○>``), escaped control bytes 0x01-0x1F WITH their operands (operand
  lengths from the executable's table, 0x08 / 0x15 variable), the game's line
  breaks (``\\n`` typed as backslash-n, and CR LF = ``⟦0D⟧⟦0A⟧``), the speaker
  prefix ``[Name]`` of a dialogue string (encoded on its own, kept first) and
  the Japanese subtitle ruby ``[base/reading]``. Tags before the first word of
  a paragraph stay first, tags after the last word stay last, tags between
  words travel with the following word;
* ``<lN>`` is updated to the new line count when the wrap changes it and it
  matched before (``sb.line_count``);
* Japanese (and any wide script) may break between any two characters;
* glyph codes are written as ``⟦XX⟧`` escapes, which ``textcodec`` turns into the
  exact bytes and ``textpack.FontCheck`` does not refuse;
* ``--donor`` takes glyph images from another Episode III font (the Japanese
  disc's) instead of a TrueType font: Japanese on the USA build in the game's
  own kana and kanji;
* ``--unlock`` (USA / prototype only, ``glyphs.UNLOCKS``) builds the slot model of
  the patched executable: ``jp-gate`` opens the 2,965 kanji cells (which the USA
  font still holds) and A5 katakana codes, ``jp-prop`` makes cells 192-383 fixed
  width. Under ``jp-gate`` every Latin-1 byte becomes a pair lead, so ``encode``
  re-encodes EVERY display string of the tree (each retail character gets its
  cell's new code, ``SlotModel.code_for``), and ``lang import`` writes the patched
  boot executable of each disc (both discs' executables) together with the text
  and the fonts. Text that is not in the tree (executable / overlay strings,
  ``.xep``) is not re-encoded: Latin-1 there draws wrong under ``jp-gate``;
* ``--reclaim-latin`` frees the Latin-1 cells retail text draws (the 0xA0-0xFF
  singles: accented letters, ``®``, ``°``...; the ``$han`` ASCII cells always stay).
  Only for a tree that no longer uses them: ``encode`` refuses any display
  string that still draws a reclaimed cell.

Pipeline::

    text-export --iso D1 --iso D2 --out tr/en          -> logical UTF-8 tree (translate it)
    lang scan   --iso D1 --text tr/ar --font F.ttf ... --out tr/pack
    lang encode --text tr/ar --pack tr/pack --out tr/ar-enc [--width 440 --align right]
    lang import --iso D1 --iso D2 --text tr/ar-enc --pack tr/pack --out OUT/ [--grow]
                (= text-import + font0/font1.bin + the patched executables, one verified copy)
    lang preview --pack tr/pack --text "..." --out line.png
    lang preview --iso OUT/D1.iso --path 'cf\\us\\1010.sb' --key 0001 --out back.png

``lang preview`` draws through the build's own code -> cell rules and the
rebuilt font file (fixed cells at 19 px, proportional images at cell + 0x240,
advance ``right - left + 3``), so a code that lands on the wrong cell shows.

Nothing produced here has been booted in PCSX2.

    python langpack.py --self-test
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import os
import re
import shutil
import sys
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import font as fontmod                                             # noqa: E402
import glyphs as glyphmod                                          # noqa: E402
import region as regionmod                                         # noqa: E402
import textcodec                                                   # noqa: E402
from font import FIXED_ADVANCE, Addressing, Font, FontError        # noqa: E402
from glyphs import Glyph, GlyphError, GlyphSet, SlotModel          # noqa: E402

# Bidi_Paired_Bracket pairs (UAX #9 BD14-BD16, BidiBrackets.txt) for the characters
# this kit can meet, and Bidi_Mirroring_Glyph (rule L4) for those plus the angle
# quotes and less/greater-than (mirrored, but not paired brackets).
# U+2329/U+232A are canonically equivalent to U+3008/U+3009 and BD16 pairs
# canonical equivalents. ICU does it by pushing an angle opener twice: the
# equivalent closer first, then its own (``_BRACKET_ALT``), so a closer that
# matches the top entry leaves the other one on the stack — ICU 78 output,
# kept as is.
_BRACKETS = "()[]{}（）［］｛｝〈〉《》「」『』【】〔〕〖〗〘〙〚〛｟｠｢｣⁅⁆⁽⁾₍₎\u2329\u232a"
_OPEN = {_BRACKETS[i]: _BRACKETS[i + 1] for i in range(0, len(_BRACKETS), 2)}
_CLOSE = {v: k for k, v in _OPEN.items()}
_BRACKET_ALT = {"\u232a": "\u3009", "\u3009": "\u232a"}
MIRROR = dict(_OPEN, **_CLOSE)
MIRROR.update({"<": ">", ">": "<", "«": "»", "»": "«", "‹": "›", "›": "‹", "≤": "≥", "≥": "≤"})
PACK_CFG = "langpack.json"
STATES = {"prop1han1": (True, True), "prop0han1": (False, True), "prop1han0": (True, False),
          "prop0han0": (False, False)}
_ESC1 = re.compile(r"⟦([0-9A-Fa-f]{2})⟧")
_TAG = re.compile(r"<[^<>\n⟦⟧]{1,40}>")
_PREFIX = re.compile(r"\[[^\[\]/\n]{1,40}\]")
_RUBY = re.compile(r"\[[^\[\]/\n]{1,40}/[^\[\]\n]{1,40}\]")
_LTAG = re.compile(r"<l(\d+)>")
# script tags that only steer the printer (page end, wait, line count, position,
# speed, colour); every other <...> tag (button marks <○> <×> <△> <□>, keywords
# <Shion> <kGnosis> <variant URTV>) draws something and is placed by the bidi pass
# as an inline object
_CTRL_TAG = re.compile(r"<(?:f|[wlxs]\d+|col[0-9A-Za-z]*)>")


def _visible_tag(t: str) -> bool:
    return bool(_TAG.fullmatch(t)) and not _CTRL_TAG.fullmatch(t)
BLOCK_KINDS = ("sb", "txd", "nj", "msgdat", "batdat")
STRIP = 17                     # px per strip of a cluster wider than a proportional cell


class LangError(ValueError):
    pass


# --- Arabic presentation forms (for hand-drawn --cells sheets only) -------------------

# letter -> (isolated, final, initial, medial); two entries = right-joining only
_ARABIC = {
    0x0621: (0xFE80,), 0x0622: (0xFE81, 0xFE82), 0x0623: (0xFE83, 0xFE84),
    0x0624: (0xFE85, 0xFE86), 0x0625: (0xFE87, 0xFE88),
    0x0626: (0xFE89, 0xFE8A, 0xFE8B, 0xFE8C), 0x0627: (0xFE8D, 0xFE8E),
    0x0628: (0xFE8F, 0xFE90, 0xFE91, 0xFE92), 0x0629: (0xFE93, 0xFE94),
    0x062A: (0xFE95, 0xFE96, 0xFE97, 0xFE98), 0x062B: (0xFE99, 0xFE9A, 0xFE9B, 0xFE9C),
    0x062C: (0xFE9D, 0xFE9E, 0xFE9F, 0xFEA0), 0x062D: (0xFEA1, 0xFEA2, 0xFEA3, 0xFEA4),
    0x062E: (0xFEA5, 0xFEA6, 0xFEA7, 0xFEA8), 0x062F: (0xFEA9, 0xFEAA),
    0x0630: (0xFEAB, 0xFEAC), 0x0631: (0xFEAD, 0xFEAE), 0x0632: (0xFEAF, 0xFEB0),
    0x0633: (0xFEB1, 0xFEB2, 0xFEB3, 0xFEB4), 0x0634: (0xFEB5, 0xFEB6, 0xFEB7, 0xFEB8),
    0x0635: (0xFEB9, 0xFEBA, 0xFEBB, 0xFEBC), 0x0636: (0xFEBD, 0xFEBE, 0xFEBF, 0xFEC0),
    0x0637: (0xFEC1, 0xFEC2, 0xFEC3, 0xFEC4), 0x0638: (0xFEC5, 0xFEC6, 0xFEC7, 0xFEC8),
    0x0639: (0xFEC9, 0xFECA, 0xFECB, 0xFECC), 0x063A: (0xFECD, 0xFECE, 0xFECF, 0xFED0),
    0x0640: (0x0640, 0x0640, 0x0640, 0x0640),
    0x0641: (0xFED1, 0xFED2, 0xFED3, 0xFED4), 0x0642: (0xFED5, 0xFED6, 0xFED7, 0xFED8),
    0x0643: (0xFED9, 0xFEDA, 0xFEDB, 0xFEDC), 0x0644: (0xFEDD, 0xFEDE, 0xFEDF, 0xFEE0),
    0x0645: (0xFEE1, 0xFEE2, 0xFEE3, 0xFEE4), 0x0646: (0xFEE5, 0xFEE6, 0xFEE7, 0xFEE8),
    0x0647: (0xFEE9, 0xFEEA, 0xFEEB, 0xFEEC), 0x0648: (0xFEED, 0xFEEE),
    0x0649: (0xFEEF, 0xFEF0), 0x064A: (0xFEF1, 0xFEF2, 0xFEF3, 0xFEF4),
}
_LAM_ALEF = {0x0622: (0xFEF5, 0xFEF6), 0x0623: (0xFEF7, 0xFEF8),
             0x0625: (0xFEF9, 0xFEFA), 0x0627: (0xFEFB, 0xFEFC)}


def arabic_forms(word: str) -> List[str]:
    """Contextual presentation forms for one word, logical order; marks
    (harakat) are dropped. Lam-alef becomes one ligature form."""
    letters = [c for c in word if not (0x064B <= ord(c) <= 0x0652 or ord(c) == 0x0670)]
    out: List[str] = []
    i = 0
    prev_joins = False
    while i < len(letters):
        c = letters[i]
        o = ord(c)
        forms = _ARABIC.get(o)
        if forms is None:
            out.append(c)
            prev_joins = False
            i += 1
            continue
        nxt = ord(letters[i + 1]) if i + 1 < len(letters) else None
        if o == 0x0644 and nxt in _LAM_ALEF:
            iso, fin = _LAM_ALEF[nxt]
            out.append(chr(fin if prev_joins else iso))
            prev_joins = False
            i += 2
            continue
        dual = len(forms) == 4
        next_joins = nxt in _ARABIC
        if prev_joins and dual and next_joins:
            f = forms[3]
        elif prev_joins:
            f = forms[1] if len(forms) > 1 else forms[0]
        elif dual and next_joins:
            f = forms[2]
        else:
            f = forms[0]
        out.append(chr(f))
        prev_joins = dual and next_joins
        i += 1
    return out


# --- shaping back-ends ----------------------------------------------------------------

class SimpleShaper:
    """Hand-drawn ``--cells`` sheets: one key per character (Arabic through the
    presentation-form table). Not a fallback for a TrueType font."""
    name = "cells"

    def __init__(self, rtl: bool):
        self.rtl = rtl
        self.notdef: set = set()

    def keys(self, word: str, rtl: bool) -> List[str]:
        if any(0x0600 <= ord(c) <= 0x06FF for c in word):
            seq = [f"u:{f}" for f in arabic_forms(word)]
        else:
            seq = [f"u:{c}" for c in word if unicodedata.category(c) != "Mn"]
        return seq[::-1] if rtl else seq      # visual order, like HarfBuzz

    def glyph(self, key: str):
        return None


class HBShaper:
    """HarfBuzz shaping through glyphs.TTFRenderer; keys name glyph ids, or a
    cluster of glyphs (base + marks, a conjunct) drawn into one cell."""
    name = "harfbuzz"

    def __init__(self, renderer, script: Optional[str], language: Optional[str],
                 max_cluster_px: int = 18):
        self.r = renderer
        self.script = script
        self.language = language
        self.max_cluster = max_cluster_px
        self._parts: Dict[str, list] = {}
        self._adv: Dict[str, float] = {}
        self.notdef: set = set()

    def keys(self, word: str, rtl: bool) -> List[str]:
        r = self.r
        glyphs = r.shape(word, "rtl" if rtl else "ltr", self.script, self.language)
        if any(g[0] == 0 for g in glyphs):
            self.notdef.add(word)
        groups: List[list] = []
        for g in glyphs:
            if groups and groups[-1][0][1] == g[1]:
                groups[-1].append(g)
            else:
                groups.append([g])
        out = []
        for grp in groups:
            pen = 0.0
            parts = []
            for gid, _, adv, xo, yo in grp:
                parts.append((gid, (pen + xo) * r.scale, yo * r.scale))
                pen += adv
            pen_px = pen * r.scale
            lo, hi = self._extent(parts)
            # one cell when the advance AND the ink fit a proportional image (origin at
            # column 1: ink from column 0 to 19)
            fits = pen_px <= self.max_cluster and lo >= -1.0 and hi <= 19.0
            if fits and len(grp) == 1:
                out.append(f"g:{r.name}:{grp[0][0]}")
                continue
            spec = ";".join(f"{gid}@{dx:.1f},{dy:.1f}" for gid, dx, dy in parts)
            if fits:
                key = f"c:{r.name}:{spec}"
                self._parts[key] = parts
                self._adv[key] = pen_px
                out.append(key)
            else:
                # wider than a proportional cell (a long conjunct, a ligature, a mark
                # hanging past the advance): cut the composed cluster into STRIP-px
                # strips, each its own glyph whose advance is the strip width, so the
                # pieces abut exactly
                n = max(1, -(-int(round(pen_px)) // STRIP))
                for i in range(n):
                    key = f"s:{r.name}:{spec}#{i}/{n}"
                    self._parts[key] = parts
                    self._adv[key] = STRIP if i < n - 1 else max(1, round(pen_px) - STRIP * (n - 1))
                    out.append(key)
        return out

    def _extent(self, parts) -> Tuple[float, float]:
        """Ink extent in px from the pen origin (outline bounds, so no raster needed)."""
        if not hasattr(self, "_bounds"):
            self._bounds: Dict[int, Optional[Tuple[float, float]]] = {}
        lo, hi = 0.0, 0.0
        for gid, dx, _dy in parts:
            if gid not in self._bounds:
                xs = [x for c in self.r.contours(gid) for x, _y in c]
                self._bounds[gid] = (min(xs), max(xs)) if xs else None
            bd = self._bounds[gid]
            if bd:
                lo = min(lo, dx + bd[0] * self.r.scale)
                hi = max(hi, dx + bd[1] * self.r.scale)
        return lo, hi

    @staticmethod
    def _parse_parts(spec: str) -> list:
        parts = []
        for p in spec.split(";"):
            gid, _, off = p.partition("@")
            dx, dy = off.split(",")
            parts.append((int(gid), float(dx), float(dy)))
        return parts

    def covers(self, word: str) -> bool:
        """Does the font have every character of ``word`` (marks and joiners too)?"""
        if not hasattr(self, "_cmap"):
            self._cmap = set(self.r.tt.getBestCmap() or {})
        return all(ord(c) in self._cmap or c in "\u200c\u200d" for c in word)

    def glyph(self, key: str) -> Glyph:
        kind, _, rest = key.partition(":")
        if kind == "g":
            return self.r.render_gid(int(rest.split(":")[1]))
        if kind == "s":
            body, _, frac = rest.rpartition("#")
            i, n = (int(x) for x in frac.split("/"))
            parts = self._parts.get(key) or self._parse_parts(body.split(":", 1)[1])
            bm = self.r.raster(parts, x_origin=1.0 - STRIP * i)
            for row in bm:
                for x in range(fontmod.CELL_W):
                    if (x < 1 and i > 0) or (x >= 1 + STRIP and i < n - 1):
                        row[x] = 0
            adv = self._adv.get(key) or (STRIP if i < n - 1 else None)
            return Glyph(key, bm, adv)
        if kind == "c":
            parts = self._parts.get(key)
            if parts is None:
                parts = []
                for p in rest.split(":", 1)[1].split(";"):
                    gid, _, off = p.partition("@")
                    dx, dy = off.split(",")
                    parts.append((int(gid), float(dx), float(dy)))
            g = self.r.render_cluster(parts, key)
            if key in self._adv:
                g.advance_hint = round(self._adv[key])
            return g
        return self.r.render_text(rest, key)


class Donor:
    """Glyph images from another Episode III font (``font-donor``'s source): a
    character the donor build draws (its codec + addressing) becomes key
    ``u:<ch>`` with the donor cell's image. For Japanese on the USA build the
    donor is the Japanese disc: its own kana and kanji, as the game drew them."""

    def __init__(self, addr: Addressing, font: Font, codec, label: str = ""):
        self.addr, self.font, self.codec, self.label = addr, font, codec, label
        self._cache: Dict[str, Optional[Glyph]] = {}

    @classmethod
    def from_iso(cls, iso) -> "Donor":
        from disc import Disc
        a = Addressing.from_iso(iso)
        with Disc(iso) as d:
            reg = regionmod.region_of(d)
            f = Font.from_bytes(d.read(fontmod.font_paths(a.font_dir)[0]))
        return cls(a, f, textcodec.for_region(reg), Path(iso).name)

    def glyph_for(self, ch: str) -> Optional[Glyph]:
        if ch in self._cache:
            return self._cache[ch]
        g = None
        try:
            b = self.codec.encode_char(ch)
        except textcodec.TextError:
            b = b""
        if len(b) == 2 and b[0] >= 0xA1:
            gl = self.addr.glyph(b, 0, True, 0)
            cell = fontmod.cell_index(gl.cell or 0)
            if gl.length == 2 and cell not in (0, fontmod.FALLBACK_CELL):
                bm = self.font.cell(cell)
                if any(any(r) for r in bm):
                    g = Glyph(f"u:{ch}", [list(r) for r in bm])
        self._cache[ch] = g
        return g


# --- the pack: model, addressing, fonts, config --------------------------------------

def _addr_to_json(a: Addressing) -> dict:
    return dataclasses.asdict(a)


def _addr_from_json(d: dict) -> Addressing:
    d = dict(d)
    d["han"] = tuple(d["han"])
    d["extra"] = tuple(tuple(tuple(p) for p in lst) for lst in d["extra"])
    for k in ("ctl", "ctl08", "commands", "clut"):
        d[k] = tuple(d[k])
    return Addressing(**d)


def _model_to_json(m: SlotModel) -> dict:
    return {"build": m.build, "unlock": m.unlock, "gate": m.gate, "prop_cells": m.prop_cells,
            "a9_row": m.a9_row, "exe_sha1": m.exe_sha1,
            "codes": {str(c): v.hex().upper() for c, v in sorted(m.codes.items())},
            "reserved": sorted(m.reserved), "prop": m.prop, "wide": m.wide}


def _model_from_json(d: dict) -> SlotModel:
    return SlotModel(d["build"], d["unlock"], d["gate"], d["prop_cells"], d["a9_row"],
                     {int(c): bytes.fromhex(v) for c, v in d["codes"].items()}, set(d["reserved"]),
                     list(d["prop"]), list(d["wide"]), d.get("exe_sha1", ""))


class Pack:
    """What ``scan`` writes and ``encode`` / ``preview`` / ``import`` read:
    glyphset.json, font0.bin, font1.bin, langpack.json (options, region, the
    retail addressing, the slot model)."""

    def __init__(self, cfg: dict, gs: GlyphSet, fonts: List[Font]):
        self.cfg, self.gs, self.fonts = cfg, gs, fonts
        self.retail = _addr_from_json(cfg["addressing"])
        self.model = _model_from_json(cfg["model"])
        self.unlock = cfg.get("unlock", "none")
        self.addr = glyphmod.unlocked_addressing(self.retail, self.unlock) if self.unlock != "none" \
            else self.retail
        self.region = regionmod.by_name(cfg["region"])
        self.codec = textcodec.codec_by_name(self.region.codec)
        self.reclaimed = set(cfg.get("reclaimed", []))

    @classmethod
    def load(cls, d) -> "Pack":
        d = Path(d)
        if not (d / PACK_CFG).exists():
            raise LangError(f"{d / PACK_CFG} is missing: give the folder 'lang scan --out' wrote")
        cfg = json.loads((d / PACK_CFG).read_text(encoding="utf-8"))
        gs = GlyphSet.load(d / "glyphset.json")
        fonts = [Font.load(d / "font0.bin"), Font.load(d / "font1.bin")]
        pk = cls(cfg, gs, fonts)
        pk.dir = d
        return pk

    def shaper(self):
        return make_shaper(self.cfg)

    def donor(self) -> Optional[Donor]:
        return self.donor_from_cfg(self.cfg.get("donor"), getattr(self, "dir", None))

    @staticmethod
    def donor_from_cfg(dn, base=None) -> Optional[Donor]:
        """The donor a pack names: its addressing (json) and its font0 (donor_font0.bin)."""
        if not dn or base is None:
            return None
        a = _addr_from_json(dn["addressing"])
        f = Font.load(Path(base) / dn["font_file"])
        return Donor(a, f, textcodec.codec_by_name(dn["codec"]), dn.get("label", ""))


class MultiShaper:
    """Several TrueType fonts in one pack (``scan --extend``): a run goes to the
    first font that has all its characters; ``keys`` returns None when none has
    (scan leaves such runs to a later --extend scan; encode writes '?')."""
    name = "multi"

    def __init__(self, shapers: List[HBShaper]):
        self.shapers = shapers
        self.notdef: set = set()

    def keys(self, word: str, rtl: bool) -> Optional[List[str]]:
        for sh in self.shapers:
            if sh.covers(word):
                k = sh.keys(word, rtl)
                self.notdef |= sh.notdef
                return k
        return None

    def glyph(self, key: str) -> Glyph:
        name = key.split(":")[1] if key.count(":") >= 2 else ""
        for sh in self.shapers:
            if sh.r.name == name:
                return sh.glyph(key)
        raise LangError(f"no font of this pack made glyph key {key!r}")


def shaper_specs(cfg: dict) -> List[dict]:
    if cfg.get("shapers"):
        return list(cfg["shapers"])
    if cfg.get("ttf"):
        return [{k: cfg.get(k) for k in ("ttf", "px", "baseline", "face", "script", "language")}]
    return []


def make_shaper(cfg: dict):
    specs = shaper_specs(cfg)
    if specs:
        shs = []
        for sp in specs:
            r = glyphmod.TTFRenderer(sp["ttf"], sp.get("px") or 20.0, sp.get("baseline") or 17, sp.get("face") or 0)
            shs.append(HBShaper(r, sp.get("script"), sp.get("language")))
        return MultiShaper(shs)
    return SimpleShaper(bool(cfg.get("rtl")))


# --- what the build draws ---------------------------------------------------------------

class Drawable:
    """Can the build (after the pack's unlock) draw a character as it is, and with
    which bytes? ``bytes_for`` returns (bytes, typed) - typed = the character may
    stay typed in the tree (no unlock: the display codec writes those bytes) - or
    None for a target-script character."""

    def __init__(self, pack: "Pack", fonts: Optional[List[Font]] = None, fill_blank: bool = False):
        self.p = pack
        self.fill_blank = fill_blank
        self.blank: Counter = Counter()           # encodable characters whose cell has no ink
        fonts = fonts or pack.fonts
        cells = [fontmod.font_cells(f) for f in fonts]
        self.ink = [c.reshape(len(c), -1).any(axis=1) for c in cells]
        self.slot_cells = {s["cell"] for s in pack.gs.slots.values()}
        self._jp = textcodec.codec_by_name("jp")
        self._cache: Dict[str, Optional[Tuple[bytes, bool]]] = {}

    def inked(self, a: Addressing, b: bytes) -> Optional[int]:
        """The cell ``b`` draws under ``a`` if it is one character with ink (or the
        full-width space, cell 0), else None."""
        g = a.glyph(b + b"\0", 0, True, 0)
        if g.length != len(b):
            return None
        for f in (0, 1):
            c = a.cell(b[0], b[1], f) if len(b) == 2 else (g.cell or 0)
            ci = fontmod.cell_index(c)
            if ci == 0:
                return 0
            if ci != fontmod.FALLBACK_CELL and (self.ink[f][ci] or
                                                (a.is_prop(c) and self.ink[f][ci + fontmod.PROP_CELL_SHIFT])):
                return ci
        return None

    def bytes_for(self, ch: str) -> Optional[Tuple[bytes, bool]]:
        if ch in self._cache:
            return self._cache[ch]
        r = None
        p = self.p
        try:
            b = p.codec.encode_char(ch)
        except textcodec.TextError:
            b = b""
        if b:
            cell = self.inked(p.retail, b)
            if cell is None and not self.fill_blank:
                # the build reads it but draws nothing (or the fallback): keep it typed, so
                # an untouched retail string never changes (JP 縊 E5D0); textpack's font
                # check refuses it if a translator types it anew
                self.blank[ch] += 1
                g = p.retail.glyph(b + b"\0", 0, True, 0)
                cell = fontmod.cell_index(g.cell or 0) if g.length == len(b) else None
            if cell is not None:              # reclaimed cells stay typed: encode's reclaim check lists them
                if p.unlock == "none":
                    r = (b, True)
                elif cell in p.model.codes or len(b) == 2:
                    r = (reencode_char(p, b, cell), False)
        if r is None and p.unlock != "none" and p.addr.gate == "euc":
            # under jp-gate: a kanji the USA font still holds, by its own EUC code
            try:
                b = self._jp.encode_char(ch)
            except textcodec.TextError:
                b = b""
            if len(b) == 2 and b == b"\xa1\xa1":
                r = (b, False)                # the full-width space (A1A1, cell 0): no ink to check
            elif len(b) == 2 and 0xB0 <= b[0] <= 0xCF:
                cell = self.inked(p.addr, b)
                if cell is not None and cell >= 1024 and cell not in self.slot_cells \
                        and cell not in p.model.reserved:
                    r = (b, False)
        self._cache[ch] = r
        return r


def reencode_char(pack: "Pack", b: bytes, cell: int) -> bytes:
    """The code of a retail character after the unlock: unchanged if the unlocked
    addressing still reads it as one character on the same cell, else the
    model's code for that cell."""
    g = pack.addr.glyph(b + b"\0", 0, True, 0)
    if g.length == len(b) and fontmod.cell_index(g.cell or 0) == cell:
        return b
    return pack.model.code_for(cell)


def reencode_bytes(pack: "Pack", data: bytes) -> bytes:
    """Every character of a retail string re-coded for the unlocked executable
    ('$' commands and control sequences with their operands are left alone)."""
    a = pack.retail
    out = bytearray()
    i, n = 0, len(data)
    while i < n:
        c = data[i]
        if c == 0x24:
            try:
                e = a.command_at(data, i)[2]
            except FontError:
                e = i + 1
            out += data[i:e]
            i = e
        elif c < 0x20:
            try:
                L = max(1, a.control_length(data, i))
            except (FontError, IndexError):
                L = 1
            out += data[i:i + L]
            i += L
        elif c < 0x80:
            out.append(c)
            i += 1
        else:
            g = a.glyph(data, i, True, 0)
            piece = data[i:i + g.length]
            out += reencode_char(pack, piece, fontmod.cell_index(g.cell or 0))
            i += g.length
    return bytes(out)


def bytes_to_text(data: bytes) -> str:
    """Bytes as tree text that encodes back to exactly them under any codec:
    printable ASCII typed, everything else (control bytes, 0x7F, high bytes) as
    ``⟦XX⟧``, and an ASCII byte right after a high byte escaped too (``guard``)."""
    return guard("".join(chr(b) if 0x20 <= b < 0x7F else f"⟦{b:02X}⟧" for b in data))


_HIGH_THEN_TYPED = re.compile(r"(⟦[89A-Fa-f][0-9A-Fa-f]⟧)([\x20-\x7e])")


def guard(text: str) -> str:
    """Escape a typed ASCII character that directly follows an escaped high byte.
    The bytes do not change; ``textcodec`` refuses a typed piece that the RETAIL
    gate would fuse with an escaped lead (``⟦A6⟧]`` = A6 5D, one USA pair), which
    is wrong for text meant for an unlocked executable, and two escapes may pair."""
    return _HIGH_THEN_TYPED.sub(lambda m: m.group(1) + f"⟦{ord(m.group(2)):02X}⟧", text)


def cells_of(addr: Addressing, data: bytes) -> List[int]:
    out = []
    i, n = 0, len(data)
    while i < n:
        c = data[i]
        if c == 0x24:
            try:
                i = addr.command_at(data, i)[2]
                continue
            except FontError:
                i += 1
                continue
        if c < 0x20:
            try:
                i += max(1, addr.control_length(data, i))
            except (FontError, IndexError):
                i += 1
            continue
        if c < 0x80:
            i += 1
            continue
        g = addr.glyph(data, i, True, 0)
        out.append(fontmod.cell_index(g.cell or 0))
        i += g.length
    return out


# --- text atoms ----------------------------------------------------------------------------

# '$' always starts a command for the game. FUN_00184090 (the printer) logs
# "[*error*:....]" for a name it does not know and then draws the '$' as a
# character, but FUN_001828a0 (the width function every centred, right-aligned
# or wrapped box uses) skips from any '$' to the next ';' — past the end of the
# string when there is none. So a typed '$' (currency, "$5") is drawn but the
# line is measured wrong. Write the amount without it ("5 dollars", "5 USD").
DOLLAR_WARNING = ("a literal '$' is not text for the game: it is drawn, but the width function "
                  "skips from it to the next ';' (wrong centring/wrapping); write the amount without '$'")


class Atom:
    __slots__ = ("kind", "text", "byte")

    def __init__(self, kind: str, text: str, byte: int = -1):
        self.kind, self.text, self.byte = kind, text, byte

    def __repr__(self):
        return f"{self.kind}:{self.text!r}"


def atoms(text: str, addr: Addressing, prefix: bool = False, ruby: bool = False) -> List[Atom]:
    """Split tree text into atoms: ctrl (``$cmd;``, ``<tag>``, escaped control bytes
    with their operands), ruby (``$rubys;...$rubye;``, ``[base/reading]``), break
    (``\\n``, ``⟦0D⟧⟦0A⟧``), prefix (a leading ``[Name]`` when ``prefix``), space,
    esc (an escaped byte from 0x80 up) and char."""
    out: List[Atom] = []
    i, n = 0, len(text)
    names = sorted(addr.commands, key=len, reverse=True)

    def unit(j: int) -> Tuple[int, int]:
        """(byte value, end) of one operand unit at text[j]: an escape or a char."""
        m = _ESC1.match(text, j)
        if m:
            return int(m.group(1), 16), m.end()
        if j < n:
            return (ord(text[j]) if ord(text[j]) < 0x100 else 0x3F), j + 1
        return 0, j

    if prefix:
        m = _PREFIX.match(text)
        if m:
            out.append(Atom("prefix", m.group(0)))
            i = m.end()
    while i < n:
        ch = text[i]
        m = _ESC1.match(text, i)
        if m:
            b = int(m.group(1), 16)
            if b < 0x20:
                j = m.end()
                if b == 0x0D:
                    v, e = unit(j)
                    if v == 0x0A and e > j:
                        out.append(Atom("break", text[i:e]))
                        i = e
                        continue
                L = addr.ctl[b]
                if L == 0xFF:
                    v, e = unit(j)
                    if b == 0x08:
                        L = 1 + sum(addr.ctl08[k] for k in range(8) if v >> k & 1)
                    else:
                        L = 1 + v
                for _ in range(L):
                    _v, j = unit(j)
                out.append(Atom("ctrl", text[i:j], b))
                i = j
                continue
            if b >= 0x80:
                j = m.end()
                while True:
                    m2 = _ESC1.match(text, j)
                    if not m2 or int(m2.group(1), 16) < 0x80:
                        break
                    j = m2.end()
                out.append(Atom("esc", text[i:j], b))
                i = j
                continue
            out.append(Atom("ctrl", m.group(0), b))           # 0x7F
            i = m.end()
            continue
        if ch == "\\" and text.startswith("\\n", i):
            out.append(Atom("break", "\\n"))
            i += 2
            continue
        if ch == "$":
            if text.startswith("$rubys;", i):
                e = text.find("$rubye;", i)
                if e >= 0:
                    out.append(Atom("ruby", text[i:e + 7]))
                    i = e + 7
                    continue
            name = next((nm for nm in names if text.startswith(nm, i + 1)), None)
            e = text.find(";", i)
            if name and e > 0 and "\\n" not in text[i:e]:
                out.append(Atom("ctrl", text[i:e + 1]))
                i = e + 1
                continue
        if ch == "<":
            m = _TAG.match(text, i)
            if m:
                out.append(Atom("ctrl", m.group(0)))
                i = m.end()
                continue
        if ch == "[" and ruby:
            m = _RUBY.match(text, i)
            if m:
                out.append(Atom("ruby", m.group(0)))
                i = m.end()
                continue
        if ch in " 　":
            out.append(Atom("space", ch))
            i += 1
            continue
        if ch in "\r\n\t":
            out.append(Atom("ctrl", ch))
            i += 1
            continue
        out.append(Atom("char", ch))
        i += 1
    return out


# --- the encoder ---------------------------------------------------------------------------

def _direction(word: str) -> str:
    """R (right-to-left strong), L (left-to-right strong), E (numbers), N."""
    classes = {unicodedata.bidirectional(c) for c in word}
    if classes & {"R", "AL"}:
        return "R"
    if "L" in classes:
        return "L"
    if classes & {"EN", "AN"}:
        return "E"
    return "N"


def _strong(t: str) -> Optional[str]:
    """Strong direction for N0-N2: L, or R (EN and AN count as R)."""
    return "L" if t == "L" else ("R" if t in ("R", "AL", "EN", "AN") else None)


def bidi_levels(chars: Sequence[str], base: int, classes: Optional[Sequence[str]] = None) -> List[int]:
    """Embedding levels of one paragraph (UAX #9 rules W1-W7, N0-N2, I1-I2) with no
    explicit embeddings or isolates: game text has none, so the paragraph is one
    isolating run sequence with sos = eos = the paragraph direction. ``chars`` are
    the paragraph's characters in logical order (an item that stands for an
    escape or a control may be given as "" with its class in ``classes``).
    Boundary neutrals (BN: joiners, format characters) are removed (X9) and take
    the level of the character after them (the paragraph level at the end), as
    ICU 78 places them. Rule L1 (trailing white space) is a
    per-line rule: see ``Encoder._emit``."""
    n = len(chars)
    cls = list(classes) if classes is not None else [unicodedata.bidirectional(c) or "L" for c in chars]
    keep = [i for i in range(n) if cls[i] not in ("BN", "LRE", "RLE", "LRO", "RLO", "PDF")]
    t = [("ON" if cls[i] in ("LRI", "RLI", "FSI", "PDI") else cls[i]) for i in keep]
    orig = list(t)
    e = "R" if base & 1 else "L"
    m = len(t)
    # W1: NSM takes the type of the character before it (sos at the start)
    for i in range(m):
        if t[i] == "NSM":
            t[i] = t[i - 1] if i else e
    # W2: EN after AL (last strong) is AN; W3: AL is R
    last = e
    for i in range(m):
        if t[i] in ("L", "R", "AL"):
            last = t[i]
        elif t[i] == "EN" and last == "AL":
            t[i] = "AN"
    t = ["R" if x == "AL" else x for x in t]
    # W4: one ES between ENs, one CS between two numbers of the same type
    for i in range(1, m - 1):
        if t[i] == "ES" and t[i - 1] == "EN" and t[i + 1] == "EN":
            t[i] = "EN"
        elif t[i] == "CS" and t[i - 1] == t[i + 1] and t[i - 1] in ("EN", "AN"):
            t[i] = t[i - 1]
    # W5: a sequence of ETs next to an EN becomes EN
    i = 0
    while i < m:
        if t[i] != "ET":
            i += 1
            continue
        j = i
        while j < m and t[j] == "ET":
            j += 1
        if (i and t[i - 1] == "EN") or (j < m and t[j] == "EN"):
            t[i:j] = ["EN"] * (j - i)
        i = j
    # W6: remaining separators and terminators are ON; W7: EN after L is L
    t = ["ON" if x in ("ES", "ET", "CS") else x for x in t]
    last = e
    for i in range(m):
        if t[i] in ("L", "R"):
            last = t[i]
        elif t[i] == "EN" and last == "L":
            t[i] = "L"
    # N0: paired brackets (BD16: a stack of 63, mismatches skipped)
    ch = [chars[i] for i in keep]
    pairs, stack = [], []
    for i in range(m):
        if t[i] != "ON":
            continue
        c = ch[i]
        if c in _OPEN:
            if len(stack) == 63:
                break
            if _OPEN[c] in _BRACKET_ALT:
                stack.append((i, _BRACKET_ALT[_OPEN[c]]))
            stack.append((i, _OPEN[c]))
        elif c in _CLOSE:
            for k in range(len(stack) - 1, -1, -1):
                if stack[k][1] == c:
                    o = stack[k][0]
                    pairs.append((o, i))
                    if any(_strong(x) for x in t[o + 1:i]):
                        while k and stack[k - 1][0] == o:     # ICU: a resolved pair drops
                            k -= 1                            # the opener's synonym too,
                    del stack[k:]                             # an N0d pair keeps it
                    break
    for o, c in sorted(pairs):
        inside = {_strong(x) for x in t[o + 1:c]} - {None}
        if e in inside:
            new = e
        elif inside:
            new = next((_strong(t[k]) for k in range(o - 1, -1, -1) if _strong(t[k])), e)   # N0 c
        else:
            continue
        # UAX #9 also gives marks right after a resolved bracket the bracket's
        # type; ICU 78 does not (the mark stays the neutral W1 made it), and the
        # kit follows ICU
        for b in (o, c):
            t[b] = new
    # N1 / N2: neutrals take the direction around them, else the embedding's
    i = 0
    while i < m:
        if t[i] not in ("B", "S", "WS", "ON"):
            i += 1
            continue
        j = i
        while j < m and t[j] in ("B", "S", "WS", "ON"):
            j += 1
        left = _strong(t[i - 1]) if i else e
        right = _strong(t[j]) if j < m else e
        t[i:j] = [left if left == right else e] * (j - i)
        i = j
    # I1 / I2
    lv = []
    for x in t:
        if base & 1:
            lv.append(base + 1 if x in ("L", "EN", "AN") else base)
        else:
            lv.append(base + (1 if x == "R" else 2 if x in ("EN", "AN") else 0))
    out = [base] * n
    nxt = base
    pos = {k: j for j, k in enumerate(keep)}
    for i in range(n - 1, -1, -1):
        if i in pos:
            nxt = out[i] = lv[pos[i]]
        else:
            out[i] = nxt
    return out


def reorder(levels: Sequence[int]) -> List[int]:
    """Rule L2: the visual order (indices) of one line from its levels."""
    order = list(range(len(levels)))
    if not order:
        return order
    hi = max(levels)
    lo = min(lv for lv in levels if lv & 1) if any(lv & 1 for lv in levels) else hi + 1
    for lvl in range(hi, lo - 1, -1):
        i = 0
        while i < len(order):
            if levels[order[i]] >= lvl:
                j = i
                while j < len(order) and levels[order[j]] >= lvl:
                    j += 1
                order[i:j] = order[i:j][::-1]
                i = j
            else:
                i += 1
    return order


def _wide(ch: str) -> bool:
    return unicodedata.east_asian_width(ch) in ("W", "F")


class Item:
    """One placeable piece of a paragraph: kind space / native / ascii / keys /
    ctrl(trailing). ``brk`` = a line may break before it. ``text`` = its logical
    characters (what the bidi pass classifies; "" for an opaque escape / ruby
    piece, which counts as one strong L), ``level`` = its resolved embedding
    level (``bidi_levels``)."""
    __slots__ = ("kind", "payload", "dir", "width", "ctrl", "brk", "native", "text", "level")

    def __init__(self, kind, payload, d, width, ctrl, brk=False, native=None, text=None):
        self.kind, self.payload, self.dir, self.width, self.ctrl, self.brk, self.native = \
            kind, payload, d, width, ctrl, brk, native
        self.text = payload if text is None else text
        self.level = 0


class Encoder:
    """Logical tree text -> the same text with target-script runs as glyph codes,
    wrapped and in visual order. ``collect`` (scan) gathers glyph keys only."""

    def __init__(self, pack: Pack, shaper, rtl: Optional[bool], width: int = 0, align: str = "left",
                 state: str = "prop1han1", collect: bool = False, donor: Optional[Donor] = None,
                 fonts: Optional[List[Font]] = None, fill_blank: bool = False):
        self.p = pack
        self.gs = pack.gs
        self.shaper = shaper
        self.rtl = rtl
        self.width = width
        self.align = align
        self.prop, self.han = STATES[state]
        self.collect = collect
        self.donor = donor
        self.fonts = fonts or pack.fonts
        self.draw = Drawable(pack, self.fonts, fill_blank)
        self.counts: Counter = Counter()
        self.missing: Counter = Counter()
        self.donor_glyphs: Dict[str, Glyph] = {}
        self.uncovered: Counter = Counter()        # target runs no font of the pack has
        self.escape_natives = False
        self.space_px = self.measure(b" ") or 5
        self.warnings: List[str] = []

    # measuring --------------------------------------------------------------------
    def measure(self, b: bytes) -> int:
        try:
            return fontmod.Measurer(self.p.addr, self.fonts[0].metrics, prop=self.prop, han=self.han).width(b)
        except (FontError, IndexError):
            return FIXED_ADVANCE * len(b)

    def key_width(self, key: str) -> int:
        if key in self.gs.slots:
            return self.gs.width(key)
        return FIXED_ADVANCE

    # classification -----------------------------------------------------------------
    def is_target(self, ch: str) -> bool:
        if ord(ch) < 0x80:
            return False
        if unicodedata.category(ch) in ("Mn", "Me", "Cf") and ord(ch) >= 0x300:
            return True                      # marks / joiners belong to the run they shape
        return self.draw.bytes_for(ch) is None

    def has_target(self, ats: Sequence[Atom]) -> bool:
        for a in ats:
            if a.kind == "char" and self.is_target(a.text):
                return True
            if a.kind == "prefix" and any(self.is_target(c) for c in a.text[1:-1]):
                return True
        return False

    # native text ----------------------------------------------------------------------
    def native_text(self, s: str) -> str:
        """Typed retail characters / escapes as the output writes them: unchanged
        without an unlock; re-coded escapes under one."""
        if self.p.unlock == "none" and not self.escape_natives:
            return s
        return bytes_to_text(self.native_bytes(s))

    def native_bytes(self, s: str) -> bytes:
        """The bytes the game gets for native text: the display codec's (escapes
        included), re-coded for the unlocked executable when there is one. A kanji
        that only the unlocked gate reaches is not a retail character: its EUC code
        is written as it is, never re-coded."""
        try:
            b = self.p.codec.from_text(s)
            return reencode_bytes(self.p, b) if self.p.unlock != "none" else b
        except textcodec.TextError:
            pass
        out = bytearray()
        run: List[str] = []

        def flush():
            if run:
                piece = self.p.codec.from_text("".join(run))
                out.extend(reencode_bytes(self.p, piece) if self.p.unlock != "none" else piece)
                run.clear()

        for ch, raw in textcodec.tokens(s):
            if raw is not None:
                run.append(f"⟦{raw:02X}⟧")
                continue
            try:
                self.p.codec.encode_char(ch) if ord(ch) >= 0x80 else None
                run.append(ch)
            except textcodec.TextError:
                r = self.draw.bytes_for(ch)
                if r is None:
                    raise
                flush()
                out.extend(r[0])
        flush()
        return bytes(out)

    # one paragraph -----------------------------------------------------------------------
    def _runs(self, tok: List[Atom]) -> List[Tuple[str, str]]:
        """(class, text) runs of a word: a ASCII letters/digits, p ASCII punctuation,
        n native (the build draws it), x an escape or ruby piece (opaque), and
        target script split by bidi class so one shaped run never straddles two
        levels: sR right-to-left letters, sL left-to-right letters, sD digits
        (Arabic-Indic: AN / EN), sN a neutral (one character per run). Marks and
        joiners stay with the run before them."""
        out: List[Tuple[str, str]] = []
        for at in tok:
            if at.kind in ("esc", "ruby"):
                k = "x"
            else:
                c = at.text
                o = ord(c)
                if o < 0x80:
                    k = "a" if c.isalnum() else "p"
                elif self.is_target(c):
                    bd = unicodedata.bidirectional(c)
                    if bd in ("NSM", "BN", "") and out and out[-1][0].startswith("s"):
                        k = out[-1][0]
                    elif bd in ("R", "AL"):
                        k = "sR"
                    elif bd == "L":
                        k = "sL"
                    elif bd in ("EN", "AN"):
                        k = "sD"
                    elif bd in ("NSM", "BN", ""):
                        k = "sL"
                    else:
                        k = "sN"
                else:
                    k = "n"
            if out and out[-1][0] == k and (k != "sN" or unicodedata.bidirectional(at.text) in ("NSM", "BN")):
                out[-1] = (k, out[-1][1] + at.text)
            else:
                out.append((k, at.text))
        return out

    def _items_of_run(self, k: str, s: str, ctrl: str, brk: bool) -> List[Item]:
        if k in ("a", "p"):
            return [Item("ascii", s, _direction(s), self.measure(s.encode("ascii")), ctrl, brk)]
        if k == "x":
            return [Item("native", s, "L", self.measure(self.native_bytes(s)), ctrl, brk, text="")]
        if k == "n":
            if not s.startswith("⟦") and not s.startswith("$") and len(s) > 0 and all(_wide(c) for c in s):
                items = []
                for i, c in enumerate(s):
                    items.append(Item("native", c, "L", self.measure(self.native_bytes(c)),
                                      ctrl if i == 0 else "", brk or i > 0))
                return items
            d = "L" if s.startswith(("⟦", "$", "[")) else _direction(s)
            return [Item("native", s, d, self.measure(self.native_bytes(s)), ctrl, brk)]
        d = _direction(s)
        rtl = d == "R"
        if self.donor is not None and all(self.donor.glyph_for(c) for c in s):
            keys = []
            for c in s:
                g = self.donor.glyph_for(c)
                self.donor_glyphs[g.key] = g
                keys.append(g.key)
            if rtl:
                keys.reverse()
        else:
            keys = self.shaper.keys(s, rtl)
            if keys is None:
                self.uncovered[s] += 1
                keys = [f"?:{c}" for c in s]
                if self.collect:
                    return []
        if self.collect:
            self.counts.update(keys)
        if all(_wide(c) for c in s if unicodedata.category(c)[0] != "M") and len(keys) == len(s) and not rtl:
            # one cell per character: a line may break between any two of them
            return [Item("keys", [kk], d, self.key_width(kk), ctrl if i == 0 else "", brk or i > 0, text=s[i])
                    for i, kk in enumerate(keys)]
        for kk in keys:
            if kk not in self.gs.slots:
                self.missing[kk] += 1
        return [Item("keys", keys, d, sum(self.key_width(kk) for kk in keys), ctrl, brk, text=s)]

    def _tag_item(self, tag: str, ctrl: str, brk: bool) -> Item:
        """A drawn script tag as an inline object: classified by the bidi pass by
        what it shows (a keyword reads as its letters, a button mark is a neutral),
        never shaped, mirrored or split; width estimated from its text."""
        inner = tag[1:-1]
        try:
            w = self.measure(self.native_bytes(inner))
        except textcodec.TextError:
            w = FIXED_ADVANCE * len(inner)
        return Item("tag", tag, _direction(inner), w, ctrl, brk, text=inner)

    def _encode_inline(self, inner: str) -> str:
        """Encode a short piece (a speaker name) on its own, one line, no wrap."""
        w, self.width = self.width, 0
        try:
            ats = atoms(inner, self.p.addr)
            if not self.has_target(ats):
                return self.native_text(inner) if self.p.unlock != "none" else inner
            lines = self.paragraph(ats)
            return lines[0] if lines else inner
        finally:
            self.width = w

    def paragraph(self, ats: List[Atom]) -> List[str]:
        """Atoms of one paragraph (no breaks) -> encoded lines."""
        lead, k = [], 0
        while k < len(ats) and ats[k].kind in ("ctrl", "prefix") and not _visible_tag(ats[k].text):
            a = ats[k]
            lead.append(("[" + self._encode_inline(a.text[1:-1]) + "]") if a.kind == "prefix" else a.text)
            k += 1
        end = len(ats)
        while end > k and ats[end - 1].kind in ("ctrl", "space") and not _visible_tag(ats[end - 1].text):
            end -= 1
        trail = "".join(a.text for a in ats[end:])
        body = ats[k:end]
        items: List[Item] = []
        pending, brk, word = "", False, []

        def flush():
            nonlocal pending, brk, word
            if not word:
                return
            first = True
            cur: List[Atom] = []
            for at in word + [None]:
                if at is not None and at.kind != "ctrl":
                    cur.append(at)
                    continue
                if cur:
                    for kk, s in self._runs(cur):
                        its = self._items_of_run(kk, s, pending, brk if first else False)
                        items.extend(its)
                        pending, first = "", False
                    cur = []
                if at is not None and _visible_tag(at.text):
                    items.append(self._tag_item(at.text, pending, brk if first else False))
                    pending, first = "", False
                elif at is not None:
                    pending += at.text
            word = []
            brk = False

        for at in body:
            if at.kind == "space":
                flush()
                items.append(Item("space", at.text, "N", self.space_px if at.text == " " else
                                  self.measure(self.native_bytes(at.text)), pending))
                pending = ""
                brk = True
            else:
                word.append(at)
        flush()
        if pending:
            trail = pending + trail
        if self.collect:
            return []
        has_r = any(it.dir == "R" for it in items)
        base_rtl = has_r if self.rtl is None or self.rtl else False
        items = self._resolve(items, 1 if base_rtl else 0)    # levels on the whole paragraph
        lines = self._wrap(items) if self.width else [items]  # wrap in logical order
        out = [self._emit(line, base_rtl) for line in lines]  # then reorder each line
        out[0] = "".join(lead) + out[0]
        out[-1] = out[-1] + trail
        return out

    def _wrap(self, items: List[Item]) -> List[List[Item]]:
        """Greedy fill, breaking at spaces and before ``brk`` items (between wide
        characters), so a word and the tags glued to it always travel together."""
        groups: List[List[Item]] = []
        for it in items:
            if it.kind == "space" or it.brk or not groups or groups[-1][0].kind == "space":
                groups.append([it])
            else:
                groups[-1].append(it)
        lines: List[List[Item]] = []
        cur: List[Item] = []
        cur_w = 0
        for g in groups:
            w = sum(it.width for it in g)
            if g[0].kind == "space":
                if cur:
                    cur += g
                    cur_w += w
                continue
            if cur and cur_w + w > self.width:
                while cur and cur[-1].kind == "space":
                    cur.pop()
                lines.append(cur)
                cur, cur_w = [], 0
            cur += g
            cur_w += w
        while cur and cur[-1].kind == "space":
            cur.pop()
        if cur or not lines:
            lines.append(cur)
        return lines

    def _resolve(self, items: List[Item], base: int) -> List[Item]:
        """Resolve the paragraph's embedding levels (``bidi_levels``) over all its
        items at once, before the wrap: brackets pair and numbers bind across what
        will become a line break, as UAX #9 resolves a paragraph before line
        breaking. An ASCII or native item whose characters land on different levels
        is split there (each piece re-measured); a shaped target run is one level
        by construction (``_runs``)."""
        chars: List[str] = []
        classes: List[str] = []
        owner: List[int] = []
        for n, it in enumerate(items):
            if it.kind == "space":
                units = [(it.payload, "WS")]
            elif it.text == "":
                units = [("", "L")]                         # an opaque escape / ruby piece
            else:
                units = [(c, unicodedata.bidirectional(c) or "L") for c in it.text]
            for c, k in units:
                chars.append(c)
                classes.append(k)
                owner.append(n)
        lv = bidi_levels(chars, base, classes)
        per: List[List[int]] = [[] for _ in items]
        strong: List[List[int]] = [[] for _ in items]
        for n, v, k in zip(owner, lv, classes):
            per[n].append(v)
            if k != "BN":
                strong[n].append(v)
        out: List[Item] = []
        for it, levels, own in zip(items, per, strong):
            if it.kind in ("ascii", "native") and it.text and len(set(levels)) > 1:
                i = 0
                first = True
                while i < len(levels):
                    j = i
                    while j < len(levels) and levels[j] == levels[i]:
                        j += 1
                    sub = it.payload[i:j]
                    w = self.measure(sub.encode("ascii")) if it.kind == "ascii" else \
                        self.measure(self.native_bytes(sub))
                    piece = Item(it.kind, sub, _direction(sub), w, it.ctrl if first else "",
                                 it.brk if first else False)
                    piece.level = levels[i]
                    out.append(piece)
                    first = False
                    i = j
                continue
            # a joiner (BN) sits on the next character's level (ICU), but it was
            # shaped into this run, so the run's own characters decide its level
            it.level = max(own or levels) if levels else base
            out.append(it)
        return out

    def _emit(self, items: List[Item], base_rtl: bool) -> str:
        base = 1 if base_rtl else 0
        levels = [it.level for it in items]
        k = len(items)                                      # L1: trailing white space
        while k and (items[k - 1].kind == "space" or (     # (and joiners among it)
                items[k - 1].kind == "keys" and items[k - 1].text
                and all(unicodedata.bidirectional(c) == "BN" for c in items[k - 1].text))):
            k -= 1
            levels[k] = base
        order = reorder(levels)                             # L2
        out: List[str] = []
        line_w = 0
        for idx in order:
            it = items[idx]
            out.append(it.ctrl)
            line_w += it.width
            odd = levels[idx] & 1
            if it.kind == "space":
                out.append(it.payload if self.p.unlock == "none" or it.payload == " "
                           else self.native_text(it.payload))
            elif it.kind == "ascii":
                s = it.payload
                if odd:                                     # L2 inside the piece, L4 mirroring
                    s = "".join(MIRROR.get(c, c) for c in s[::-1])
                out.append(s)
            elif it.kind == "tag":
                out.append(it.payload)
            elif it.kind == "native":
                s = it.payload
                if odd and it.text:
                    s = "".join(MIRROR.get(c, c) for c in s[::-1])
                out.append(self.native_text(s))
            else:
                out.append("".join(self._code_text(k) for k in it.payload))
        text = "".join(out)
        if self.width and self.align == "right" and base_rtl and line_w < self.width:
            text = " " * ((self.width - line_w) // max(1, self.space_px)) + text
        return text

    def _code_text(self, key: str) -> str:
        if key not in self.gs.slots:
            return "?"                   # visible: the key has no slot (run scan again)
        return "".join(f"⟦{b:02X}⟧" for b in self.gs.code_bytes(key))

    # whole strings ------------------------------------------------------------------------
    def string(self, text: str, prefix: bool = False, ruby: bool = False) -> str:
        """A logical string (one tree body; may hold breaks) -> encoded string.
        Paragraphs without a target-script character come back unchanged (under an
        unlock: re-coded byte for byte)."""
        if not text:
            return text
        ats = atoms(text, self.p.addr, prefix=prefix, ruby=ruby)
        if any(a.kind == "char" and a.text == "$" for a in ats):
            self.warnings.append(DOLLAR_WARNING + f": {text[:60]!r}")
        if not self.has_target(ats):
            if self.p.unlock != "none" and not self.collect:
                return self._reencode_plain(text)
            return text
        self.escape_natives = False
        try:
            out = self._string(ats)
            if not self.collect:
                self.p.codec.from_text(out)
        except textcodec.TextError:
            self.escape_natives = True
            out = self._string(ats)
        finally:
            self.escape_natives = False
        if self.collect:
            return text
        if self.p.unlock != "none" or self.escape_natives:
            out = guard(out)
        return self._fix_lines(text, out)

    def _string(self, ats: List[Atom]) -> str:
        parts: List[str] = []
        para: List[Atom] = []
        for a in ats + [None]:
            if a is not None and a.kind != "break":
                para.append(a)
                continue
            if para and self.has_target(para):
                lines = self.paragraph(para)
                brk = a.text if a is not None else self._default_break(ats)
                parts.append(brk.join(lines) if lines else "")
            else:
                s = "".join(x.text for x in para)
                parts.append(self._reencode_plain(s) if self.p.unlock != "none" else s)
            if a is not None:
                parts.append(a.text)
            para = []
        return "".join(parts)

    @staticmethod
    def _default_break(ats: List[Atom]) -> str:
        for a in ats:
            if a.kind == "break":
                return a.text
        return "\\n"

    def _reencode_plain(self, text: str) -> str:
        try:
            b = self.p.codec.from_text(text)
        except textcodec.TextError:
            b = None
        try:
            nb = self.native_bytes(text)
        except textcodec.TextError:
            return text
        return text if nb == b else bytes_to_text(nb)

    @staticmethod
    def _fix_lines(old: str, new: str) -> str:
        """Keep ``<lN>`` equal to the line count when it was before."""
        m = _LTAG.search(new)
        if not m:
            return new
        n_old = old.count("\\n") + 1
        mo = _LTAG.search(old)
        if not mo or int(mo.group(1)) != n_old:
            return new
        n_new = new.count("\\n") + 1
        return new[:m.start()] + f"<l{n_new}>" + new[m.end():]


# --- trees -------------------------------------------------------------------------------------

def _load_manifest(tree: Path) -> dict:
    import textpack
    return textpack.load_manifest(tree)


def _block_codecs(o: dict, default: str) -> List[str]:
    import textpack
    return textpack._codec_list(o.get("codecs", {}), o.get("count", 0), default)


def transform_block_file(text: str, codecs: List[str], display: str, fn) -> str:
    """Apply ``fn(body, header_words)`` to every display-codec block body of a
    ``### KEY`` file; untouched blocks keep their lines byte for byte."""
    lines = text.split("\n")
    blocks: List[Tuple[int, List[str], List[int]]] = []        # (header line, words, body line idx)
    for i, ln in enumerate(lines):
        s = ln.rstrip("\r")
        if s.startswith("### "):
            blocks.append((i, s[4:].split(), []))
        elif s.startswith("#"):
            continue
        elif blocks:
            blocks[-1][2].append(i)
    repl: Dict[int, Optional[str]] = {}
    for bi, (_h, words, idx) in enumerate(blocks):
        if bi >= len(codecs) or codecs[bi] != display:
            continue
        flags = set(words[1:])
        if flags & {"identifier", "fixed", "note", "untranslated"}:
            continue
        body_lines = [lines[i].rstrip("\r") for i in idx]
        while len(body_lines) > 1 and body_lines[-1] == "":
            body_lines.pop()
            idx = idx[:len(body_lines)]
        body = "\\n".join(body_lines)
        new = fn(body, words)
        if new != body and idx:
            cr = "\r" if lines[idx[0]].endswith("\r") else ""
            repl[idx[0]] = new + cr
            for j in idx[1:]:
                repl[j] = None
    if not repl:
        return text
    out = []
    for i, ln in enumerate(lines):
        if i in repl:
            if repl[i] is not None:
                out.append(repl[i])
        else:
            out.append(ln)
    return "\n".join(out)


def transform_whole_file(text: str, role: str, fn) -> str:
    """Subtitles (``time<TAB>text``) and .mes files (lines; ``#`` headers kept)."""
    out = []
    for ln in text.splitlines(keepends=True):
        body = ln.rstrip("\r\n")
        end = ln[len(body):]
        if role == "pse-mes":
            if body and not body.startswith(("#", "//")):
                body = fn(body)
        elif not body.startswith(";") and "\t" in body:
            head, _, rest = body.partition("\t")
            if rest:
                body = head + "\t" + fn(rest)
        out.append(body + end)
    return "".join(out)


def iter_tree(tree: Path, reg) -> Iterable[Tuple[str, dict, Path]]:
    m = _load_manifest(tree)
    for path, o in m["objects"].items():
        yield path, o, tree / o["tree"]


LAYOUT_KINDS = ("sb", "subtitle", "msgdat")


def transform_tree(src: Path, enc: Encoder, dst: Optional[Path] = None,
                   layout_kinds: Sequence[str] = LAYOUT_KINDS) -> Tuple[int, int]:
    """Run ``enc`` over every display string of the tree (writing ``dst`` when
    given). ``--width`` / ``--align`` apply to the kinds in ``layout_kinds`` only
    (dialogue, subtitles, help messages); menu labels (txd, nj, batdat) are
    encoded on one line, never padded. Returns (files read, files changed)."""
    m = _load_manifest(src)
    reg = regionmod.as_region(m.get("build", {}).get("region"))
    if reg.name != enc.p.region.name:
        raise LangError(f"the tree was exported from the {reg.name!r} build; the pack is for {enc.p.region.name!r}")
    display = reg.codec
    n = changed = 0
    for path, o in m["objects"].items():
        p = src / o["tree"]
        if not p.exists():
            continue
        raw = p.read_bytes()
        text = raw.decode("utf-8-sig")
        n += 1
        kind = o["kind"]
        width, align = enc.width, enc.align
        if kind not in layout_kinds:
            enc.width, enc.align = 0, "left"
        if kind in BLOCK_KINDS:
            codecs = _block_codecs(o, display)
            sb_dialogue = kind == "sb"
            new = transform_block_file(text, codecs, display,
                                       lambda body, words: enc.string(body, prefix=sb_dialogue and
                                                                      "dialogue" in words))
        elif kind == "subtitle" and o.get("codec") == display:
            ruby = reg.name == "jp"
            new = transform_whole_file(text, o.get("role", ""), lambda body: enc.string(body, ruby=ruby))
        else:
            new = text
        enc.width, enc.align = width, align
        if dst is not None:
            out = dst / o["tree"]
            out.parent.mkdir(parents=True, exist_ok=True)
            if new == text:
                out.write_bytes(raw)
            else:
                changed += 1
                with open(out, "w", encoding="utf-8", newline="") as fh:
                    fh.write(new)
    if dst is not None:
        for p in src.rglob("*"):
            if p.is_file():
                d = dst / p.relative_to(src)
                if not d.exists():
                    d.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(p, d)
    return n, changed


def display_bodies(tree: Path, pack: Pack) -> Dict[str, List[str]]:
    """path -> every display-codec string (block bodies, subtitle text fields) of a tree."""
    out: Dict[str, List[str]] = {}
    m = _load_manifest(tree)
    disp = pack.region.codec
    for path, o in m["objects"].items():
        text = (tree / o["tree"]).read_text(encoding="utf-8-sig")
        bodies: List[str] = []
        if o["kind"] in BLOCK_KINDS:
            transform_block_file(text, _block_codecs(o, disp), disp, lambda b, w: bodies.append(b) or b)
        elif o["kind"] == "subtitle" and o.get("codec") == disp:
            transform_whole_file(text, o.get("role", ""), lambda b: bodies.append(b) or b)
        out[path] = bodies
    return out


def verify_reencode(old_tree: Path, new_tree: Path, pack: Pack) -> Tuple[int, int, List[str]]:
    """Unlock re-encode check: every display string of ``new_tree`` must draw, under
    the unlocked addressing, exactly the cells the ``old_tree`` string draws under
    the retail one. Returns (strings compared, strings re-coded, problems)."""
    a_old = pack.retail
    a_new = pack.addr
    old, new = display_bodies(old_tree, pack), display_bodies(new_tree, pack)
    n = recoded = 0
    bad: List[str] = []
    for path, ob in old.items():
        nb = new.get(path, [])
        if len(ob) != len(nb):
            bad.append(f"{path}: {len(ob)} strings before, {len(nb)} after")
            continue
        for x, y in zip(ob, nb):
            n += 1
            bx, by = pack.codec.from_text(x), pack.codec.from_text(y)
            recoded += bx != by
            if cells_of(a_old, bx) != cells_of(a_new, by):
                bad.append(f"{path}: {x[:40]!r} draws other cells after the re-encode")
    return n, recoded, bad


def reclaim_check(tree: Path, pack: Pack) -> List[str]:
    """Display strings of an (encoded) tree that still draw a reclaimed cell."""
    if not pack.reclaimed:
        return []
    bad = []
    enc_codec = pack.codec
    m = _load_manifest(tree)
    for path, o in m["objects"].items():
        p = tree / o["tree"]
        text = p.read_text(encoding="utf-8-sig")
        bodies: List[str] = []
        if o["kind"] in BLOCK_KINDS:
            codecs = _block_codecs(o, pack.region.codec)
            transform_block_file(text, codecs, pack.region.codec, lambda b, w: bodies.append(b) or b)
        elif o["kind"] == "subtitle" and o.get("codec") == pack.region.codec:
            transform_whole_file(text, o.get("role", ""), lambda b: bodies.append(b) or b)
        for b in bodies:
            try:
                raw = enc_codec.from_text(b)
            except textcodec.TextError:
                continue
            hit = set(cells_of(pack.retail, raw)) & pack.reclaimed
            if hit:
                bad.append(f"{path}: {b[:50]!r} draws reclaimed cell(s) {sorted(hit)[:4]}")
    return bad


# --- scan / encode / import / preview ---------------------------------------------------------------

def _disc_fonts(d, a: Addressing) -> List[Font]:
    return [Font.from_bytes(d.read(p)) for p in fontmod.font_paths(a.font_dir)]


def scan(iso, tree, out, ttf: Optional[str] = None, px: float = 20.0, baseline: int = 17, face: int = 0,
         script: Optional[str] = None, language: Optional[str] = None, rtl: bool = False,
         unlock: str = "none", extend: Optional[str] = None, cells: Optional[str] = None,
         keys_file: Optional[str] = None, donor_iso: Optional[str] = None, reclaim_latin: bool = False,
         prop_only: bool = False, wide_only: bool = False, font0: Optional[str] = None,
         font1: Optional[str] = None, state: str = "prop1han1", spacing: str = "font", log=print) -> Pack:
    """Collect the glyphs a translated tree needs, give each a slot of the disc's
    model and draw them into both fonts; write the pack to ``out``."""
    from disc import Disc
    exe = fontmod.read_boot_exe(iso)
    with Disc(iso) as d:
        reg = regionmod.require_known(d, "lang scan")
        boot = regionmod.executable(d)[0]
    if glyphmod.applied_unlock(exe) != "none":
        raise LangError(f"{iso}: its executable already carries a glyphs unlock; scan the retail disc "
                        "and pass --unlock")
    a = Addressing.from_executable(exe)
    if unlock != "none" and a.gate != "whitelist":
        raise LangError(f"--unlock is for the USA / prototype executable; {reg.name} needs none")
    with Disc(iso) as d:
        retail_fonts = _disc_fonts(d, a)
        scan_r = glyphmod.scan_retail(d, a)
    reserved = set(scan_r.reserved())
    reclaimed: set = set()
    if reclaim_latin:
        if a.gate != "whitelist":
            raise LangError("--reclaim-latin is for the USA / prototype build (Japan has no Latin-1 cells)")
        han_cells = {fontmod.cell_index(a.cell(a.han_code(b) >> 8, a.han_code(b) & 0xFF, 0))
                     for b in range(0x20, 0x80)}
        reclaimed = {c for c in reserved if 256 <= c < 384 and c not in han_cells}
        reserved -= reclaimed
    import hashlib
    model = glyphmod.build_model(a, reserved, retail_fonts[0], unlock, None, hashlib.sha1(exe).hexdigest())
    fonts = [Font.load(font0) if font0 else retail_fonts[0], Font.load(font1) if font1 else retail_fonts[1]]
    cfg = {"tool": "xs3 langpack", "region": reg.name, "unlock": unlock, "rtl": bool(rtl),
           "ttf": str(Path(ttf).resolve()) if ttf else None, "px": px, "baseline": baseline, "face": face,
           "script": script, "language": language, "cells": cells, "state": state,
           "reclaimed": sorted(reclaimed), "addressing": _addr_to_json(a), "model": _model_to_json(model),
           "boot": boot}
    donor = None
    if donor_iso:
        donor = Donor.from_iso(donor_iso)
        cfg["donor"] = {"label": donor.label, "codec": donor.codec.name,
                        "addressing": _addr_to_json(donor.addr), "font_file": "donor_font0.bin"}
    if ttf:
        cfg["shapers"] = [{"ttf": cfg["ttf"], "px": px, "baseline": baseline, "face": face, "script": script,
                           "language": language}]
    if extend:
        gs = GlyphSet.load(extend)
        old = Path(extend).with_name(PACK_CFG)
        if old.exists():
            ocfg = json.loads(old.read_text(encoding="utf-8"))
            cfg["shapers"] = shaper_specs(ocfg) + cfg.get("shapers", [])
            cfg["rtl"] = bool(rtl or ocfg.get("rtl"))
            if ocfg.get("donor") and not donor_iso:
                cfg["donor"] = ocfg["donor"]
                donor = Pack.donor_from_cfg(ocfg["donor"], old.parent)
            if (ocfg.get("region"), ocfg.get("unlock", "none")) != (reg.name, unlock):
                raise LangError(f"--extend: that pack is for {ocfg.get('region')}/{ocfg.get('unlock')}, "
                                f"not {reg.name}/{unlock}")
            if sorted(ocfg.get("reclaimed", [])) != sorted(reclaimed):
                raise LangError("--extend: pass the same --reclaim-latin as the first scan")
            cfg["extends"] = ocfg.get("extends", []) + [{k: ocfg.get(k) for k in
                                                         ("ttf", "script", "language", "rtl", "px", "face")}]
        gs.source += f" + {ttf or cells or donor_iso}"
    else:
        gs = GlyphSet(ttf or cells or donor_iso or "")
    shaper = make_shaper(cfg) if not cells else SimpleShaper(rtl)
    if cells:
        if not keys_file:
            raise LangError("--cells needs --keys")
        ks = [k for k in Path(keys_file).read_text(encoding="utf-8").split("\n") if k]
        ks = [k if k.startswith(("u:", "g:", "c:")) else f"u:{k}" for k in ks]
        for g in glyphmod.from_png(cells, ks, cells).glyphs.values():
            gs.add(g)
    elif not ttf and not donor_iso:
        raise LangError("give --font TTF, --donor ISO or --cells PNG --keys TXT")
    pack = Pack(cfg, gs, fonts)
    enc = Encoder(pack, shaper, rtl, collect=True, donor=donor, state=state)
    n, _ = transform_tree(Path(tree), enc)
    order = [k for k, _ in enc.counts.most_common()]
    for k, g in enc.donor_glyphs.items():
        if k not in gs.glyphs:
            gs.add(g)
    missing = [k for k in order if k not in gs.glyphs]
    if missing and cells:
        raise LangError(f"{len(missing)} keys have no cell in {cells}: {missing[:8]}")
    if missing and not isinstance(shaper, MultiShaper):
        raise LangError(f"{len(missing)} characters the donor does not draw and no --font given: {missing[:8]}")
    for k in missing:
        gs.add(shaper.glyph(k))
    before = set(gs.slots)
    # font spacing draws the raw raster (origin at column 1, ink anywhere in the 20
    # columns), so a glyph whose advance fits is proportional even with 19-20 columns
    # of ink (GlyphSet.allocate's tier rule looks at ink width only)
    widened = {}
    if spacing == "font":
        for k in order:
            g = gs.glyphs.get(k)
            if g is not None and k not in gs.slots and g.bounds and g.ink_width > 18 \
                    and g.advance_hint and g.advance_hint <= 20:
                widened[k] = g.bounds
                g.bounds = (g.bounds[0], g.bounds[0] + 17)
    gs.allocate(order, model, prop_only=prop_only, wide_only=wide_only)
    for k, b in widened.items():
        gs.glyphs[k].bounds = b
    if spacing == "font":
        set_font_spacing(gs, [k for k in gs.slots if k not in before])
    probs = gs.check(pack.addr, model)
    if probs:
        raise LangError("glyph set check failed: " + "; ".join(probs[:5]))
    outp = Path(out)
    outp.mkdir(parents=True, exist_ok=True)
    for f, name in ((fonts[0], "font0.bin"), (fonts[1], "font1.bin")):
        gs.apply(f)
        apply_spacing(gs, f)
        (outp / name).write_bytes(f.to_bytes())
    gs.save(outp / "glyphset.json")
    if donor is not None:
        (outp / "donor_font0.bin").write_bytes(donor.font.to_bytes())
    placed = [gs.glyphs[k] for k in gs.slots]
    if placed:
        (outp / "glyphs.png").write_bytes(glyphmod.to_png(placed))
    (outp / PACK_CFG).write_text(json.dumps(cfg, indent=1), encoding="utf-8")
    if enc.uncovered:
        log(f"note: {sum(enc.uncovered.values())} run(s) of characters no font of this pack has were left "
            f"for a later 'scan --extend' (or the donor): {list(enc.uncovered)[:6]}")
    if getattr(shaper, "notdef", None):
        log(f"warning: {len(shaper.notdef)} word(s) use characters this font lacks (drawn as the "
            f"font's .notdef): {sorted(shaper.notdef)[:6]}")
    tiers = Counter(v["tier"] for v in gs.slots.values())
    new = [k for k in order]
    log(f"scanned {n} files: {sum(enc.counts.values())} glyph uses, {len(new)} distinct glyphs; "
        f"glyph set now {tiers.get('prop', 0)} proportional + {tiers.get('wide', 0)} wide slots "
        f"({model.summary()})")
    log(f"wrote {outp}/glyphset.json, font0.bin, font1.bin, glyphs.png, {PACK_CFG}")
    pk = Pack(cfg, gs, fonts)
    pk.dir = outp
    return pk


def set_font_spacing(gs: GlyphSet, keys: Iterable[str]) -> int:
    """Give proportional glyphs their TrueType font's own spacing instead of ink + 2
    px, so joining scripts (Arabic, the Devanagari headline) touch. The printer's
    advance is ``right - left + 3`` (FUN_00185770); the image at cell + 0x240 is
    assumed drawn at ``pen + 1 - left`` (the layout ``preview`` uses; not traced in
    the draw code). With left = 1 and the raster kept unshifted (glyph origin at
    column 1), every glyph's origin lands at pen + 1 and the advance is the font's
    (``right = advance - 2``). Marks the slots ``spacing: font`` for ``apply_spacing``."""
    n = 0
    for k in keys:
        s = gs.slots[k]
        g = gs.glyphs.get(k)
        if s["tier"] != "prop" or g is None or not g.advance_hint or g.bounds is None:
            continue
        s["left"], s["right"], s["spacing"] = 1, max(1, min(19, int(g.advance_hint) - 2)), "font"
        n += 1
    return n


def apply_spacing(gs: GlyphSet, f: Font) -> None:
    """After ``GlyphSet.apply``: the unshifted raster of every ``spacing: font`` slot
    at cell + 0x240, with its metric pair."""
    for k, s in gs.slots.items():
        if s.get("spacing") == "font":
            f.set_cell(s["cell"] + fontmod.PROP_CELL_SHIFT, gs.glyphs[k].bitmap)
            f.set_metrics(s["cell"], s["left"], s["right"])


def encode(tree, pack_dir, out, width: int = 0, align: str = "left", rtl: Optional[bool] = None,
           state: Optional[str] = None, layout_kinds: Sequence[str] = LAYOUT_KINDS,
           log=print) -> Tuple[int, int, Counter]:
    pack = Pack.load(pack_dir)
    r = pack.cfg.get("rtl") if rtl is None else rtl
    enc = Encoder(pack, pack.shaper(), r, width=width, align=align, state=state or pack.cfg.get("state", "prop1han1"),
                  donor=pack.donor())
    n, changed = transform_tree(Path(tree), enc, Path(out), layout_kinds)
    log(f"encoded {n} files ({changed} changed) -> {out}")
    if enc.warnings:
        log(f"warning: {len(enc.warnings)} string(s): " + "; ".join(enc.warnings[:5]))
    if enc.draw.blank:
        log(f"note: {len(enc.draw.blank)} character(s) the build reads but draws blank were kept as typed "
            f"(text-import refuses them in edited strings): {''.join(list(enc.draw.blank)[:10])}")
    bad = reclaim_check(Path(out), pack)
    if bad:
        raise LangError(f"{len(bad)} string(s) still draw Latin-1 cells that --reclaim-latin gave away:\n  "
                        + "\n  ".join(bad[:10]))
    return n, changed, enc.missing


def unlock_changes(isos: Sequence[str], mode: str) -> Dict[str, bytes]:
    """{boot executable name: patched bytes} for every image (both discs)."""
    out: Dict[str, bytes] = {}
    if mode == "none":
        return out
    from iso9660 import IsoImage
    for iso in isos:
        with IsoImage(iso) as im:
            name = im.boot_elf_name()
            exe = bytes(im.read_file(name))
        new, _rep = glyphmod.apply_patches(exe, glyphmod.unlock_patches(mode))
        if name in out and out[name] != new:
            raise LangError(f"{name} differs between the images")
        out[name] = new
    return out


def import_pack(isos: List[str], tree, pack_dir, out, grow: bool = False, rebase: bool = False,
                dry_run: bool = False, ceiling=None, log=print, overwrite: bool = False) -> dict:
    """text-import of the encoded tree + the pack's fonts (+ the unlocked boot
    executables) into one verified copy of the disc(s)."""
    import patch
    import textpack
    pack = Pack.load(pack_dir)
    changes, rows, warnings = textpack.plan_import(list(isos), tree, grow, rebase, log)
    from disc import Disc
    with Disc(isos[0]) as d:
        reg = regionmod.region_of(d)
        if reg.name != pack.region.name:
            raise LangError(f"the pack is for {pack.region.name}, the disc is {reg.name}")
        exe = fontmod.read_boot_exe(isos[0])
        import hashlib
        if hashlib.sha1(exe).hexdigest() != pack.model.exe_sha1:
            raise LangError("the pack was scanned from another executable (sha1 differs)")
        for k in (0, 1):
            p = regionmod.resolve(d, f"mnu\\xx\\font{k}.bin", reg)
            new = pack.fonts[k].to_bytes()
            if d.read(p) != new:
                changes[p] = new
    changes.update(unlock_changes(isos, pack.unlock))
    for w in warnings:
        log("warning: " + w)
    if not changes:
        log("nothing to write")
        return {"changes": [], "patch": []}
    res = patch.patch_copy(list(isos), out, changes, grow=grow, ceiling=ceiling, dry_run=dry_run,
                           overwrite=overwrite)
    return {"changes": sorted(changes), "rows": rows, "patch": res}


# --- preview ---------------------------------------------------------------------------------------

def render_bytes(addr: Addressing, fnt: Font, data: bytes, prop: bool = True, han: bool = True,
                 font_no: int = 0) -> Tuple[List[List[int]], int]:
    """Draw one line of game bytes the way the printer lays it out: a fixed cell at
    the pen, 19 px; a proportional glyph's image (cell + 0x240) placed so its ink
    starts one pixel after the pen, advance ``right - left + 3`` (FUN_00185770).
    ASCII without ``$han`` advances 16 px blank. Returns (24 rows, width)."""
    flags = (1 if prop else 0) | (2 if han else 0)
    pen = 0
    draws: List[Tuple[int, int]] = []
    i, n = 0, len(data)
    while i < n and data[i] != 0:
        c = data[i]
        # '$' + no command name: the printer logs an error and draws the '$'
        if c == 0x24 and any(data.startswith(nm.encode(), i + 1) for nm in addr.commands):
            try:
                name, args, e = addr.command_at(data, i)
            except FontError:
                e = i + 1
                name = ""
            if name == "prop" and i + 5 < n:
                flags = (flags & ~1) | (data[i + 5] & 1)
            elif name == "han" and i + 4 < n:
                flags = (flags & ~2) | ((data[i + 4] & 1) << 1)
            if name == "ruby" and data[i:i + 7] == b"$rubys;":
                j = data.find(b"$rubyb;", i)
                k = data.find(b"$rubye;", i)
                if j > 0 and k > j:
                    sub, w = render_bytes(addr, fnt, data[i + 7:j], bool(flags & 1), bool(flags & 2), font_no)
                    draws.append((-1, pen, sub))                                    # type: ignore
                    pen += w
                    i = k + 7
                    continue
            i = e
            continue
        if c < 0x20:
            try:
                L = max(1, addr.control_length(data, i))
            except (FontError, IndexError):
                L = 1
            if c == 0x19 and i + 1 < n:
                flags = data[i + 1]
            i += L
            continue
        if c < 0x80 and not flags & 2:
            pen += 16
            i += 1
            continue
        g = addr.glyph(data, i, True, font_no)
        i += g.length
        cell = g.cell or 0
        ci = fontmod.cell_index(cell)
        if addr.is_prop(cell, bool(flags & 1)):
            left, right = fnt.metrics[ci]
            if ci == 0:
                pen += addr.glyph_width(0, fnt.metrics)
                continue
            draws.append((ci + fontmod.PROP_CELL_SHIFT, pen + 1 - left if left else pen))
            pen += addr.glyph_width(ci, fnt.metrics)
        else:
            draws.append((ci, pen))
            pen += FIXED_ADVANCE
    W = max([pen + 2] + [d[1] + fontmod.CELL_W for d in draws if d[0] != -1]
            + [d[1] + len(d[2][0]) for d in draws if d[0] == -1])
    img = [[0] * W for _ in range(fontmod.CELL_H)]
    for d in draws:
        if d[0] == -1:
            sub, x0 = d[2], d[1]                                                    # type: ignore
            for y in range(fontmod.CELL_H):
                for x, v in enumerate(sub[y]):
                    if v and 0 <= x0 + x < W:
                        img[y][x0 + x] = max(img[y][x0 + x], v)
            continue
        cell, x0 = d
        bm = fnt.cell(cell)
        for y in range(fontmod.CELL_H):
            for x in range(fontmod.CELL_W):
                if bm[y][x] and 0 <= x0 + x < W:
                    img[y][x0 + x] = max(img[y][x0 + x], bm[y][x])
    return img, pen


_STRIP_TAGS = re.compile(rb"<[^<>\n]{1,40}>")


def split_lines(data: bytes) -> List[bytes]:
    """Game bytes -> lines: literal ``\\n`` and CR LF break; script tags dropped."""
    data = _STRIP_TAGS.sub(b"", data)
    out = []
    for part in data.split(b"\\n"):
        out += part.split(b"\r\n")
    return out


def preview_png(addr: Addressing, fnt: Font, data: bytes, out, scale: int = 2, width: int = 0,
                prop: bool = True, han: bool = True, align_right: bool = False) -> List[int]:
    """Render game bytes (several lines) to a PNG; returns each line's width."""
    from PIL import Image
    m = re.match(rb"\[[^\[\]/\n]{1,60}\]", data)
    lines = split_lines(data[m.end():] if m else data)
    rows = [render_bytes(addr, fnt, ln, prop, han) for ln in lines]
    rows = [(img, w, len(img[0])) for img, w in rows]
    if m:                                  # the speaker name: drawn above, not part of the box width
        img, w = render_bytes(addr, fnt, m.group(0)[1:-1], prop, han)
        rows.insert(0, ([[v // 2 + (v > 0) for v in r] for r in img], w, len(img[0])))
    W = max([max(w, iw) for _, w, iw in rows] + [width, 1]) + 8
    H = len(rows) * 26 + 8
    im = Image.new("L", (W, H), 24)
    px = im.load()
    for li, (img, w, _iw) in enumerate(rows):
        x0 = 4 + (max(width, w) - w if align_right else 0)
        y0 = 4 + li * 26
        for y in range(fontmod.CELL_H):
            for x, v in enumerate(img[y]):
                if v and x0 + x < W:
                    px[x0 + x, y0 + y] = fontmod.GREY[v]
    if width:
        for y in range(H):
            px[4 + width, y] = 90
    im = im.resize((W * scale, H * scale), Image.NEAREST)
    im.save(out)
    return [w for _, w, _iw in rows]


def read_back(iso, path: str, key: str) -> Tuple[bytes, Addressing, List[Font]]:
    """The bytes of one string (``key``; '*' = the whole file) as the disc holds
    them, with the disc's own addressing and fonts."""
    import textpack
    from disc import Disc
    a = Addressing.from_iso(iso)
    unlocked = glyphmod.applied_unlock(fontmod.read_boot_exe(iso)) != "none"
    with Disc(iso) as d:
        reg = None if unlocked else regionmod.region_of(d)
        data = d.read(path)
        fonts = _disc_fonts(d, a)
        if reg is None:
            reg = regionmod.by_name("us" if a.font_dir == "us" else "jp")
        kinds = textpack.collect([path], reg)
        if not kinds:
            raise LangError(f"{path} is not a text object of this build")
        k = textpack.KINDS[kinds[0][1]]
        for it in k.items(path, data, reg):
            if it.key == key:
                return it.raw, a, fonts
    raise LangError(f"{path} has no string {key!r}")


# --- CLI -----------------------------------------------------------------------------------------------

def _wrap(fn):
    def run(a):
        try:
            return fn(a)
        except (LangError, GlyphError, FontError, textcodec.TextError) as e:
            print(f"refused: {e}", file=sys.stderr)
            return 1
    return run


def cmd_scan(a) -> int:
    scan(a.iso, a.text, a.out, ttf=a.font, px=a.px, baseline=a.baseline, face=a.face, script=a.script,
         language=a.language, rtl=a.rtl, unlock=a.unlock, extend=a.extend, cells=a.cells, keys_file=a.keys,
         donor_iso=a.donor, reclaim_latin=a.reclaim_latin, prop_only=a.prop_only, wide_only=a.wide_only,
         font0=a.font0, font1=a.font1, state=a.state, spacing=a.spacing)
    return 0


def cmd_encode(a) -> int:
    _n, _c, missing = encode(a.text, a.pack, a.out, a.width, a.align, a.rtl, a.state,
                             tuple(k for k in a.layout_kinds.split(",") if k))
    if missing:
        print(f"warning: {sum(missing.values())} glyph uses had no slot (written as '?'; re-run scan): "
              f"{list(missing)[:6]}", file=sys.stderr)
        return 1
    return 0


def cmd_import(a) -> int:
    res = import_pack(a.iso, a.text, a.pack, a.out, a.grow, a.rebase, a.dry_run, a.ceiling,
                      overwrite=getattr(a, "overwrite", False))
    if a.report:
        Path(a.report).write_text(json.dumps(res, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    print("NOT tested in game: boot the copy in PCSX2 before relying on it")
    return 0


def cmd_preview(a) -> int:
    if a.iso:
        if not (a.path and a.key):
            raise LangError("--iso needs --path and --key")
        data, addr, fonts = read_back(a.iso, a.path, a.key)
        fnt = fonts[a.font_no]
        enc_text = bytes_to_text(data)
    else:
        if not (a.pack and a.text is not None):
            raise LangError("give --pack and --text, or --iso --path --key")
        pack = Pack.load(a.pack)
        r = pack.cfg.get("rtl") if a.rtl is None else a.rtl
        enc = Encoder(pack, pack.shaper(), r, width=a.width, align=a.align,
                      state=a.state or pack.cfg.get("state", "prop1han1"), donor=pack.donor())
        enc_text = enc.string(a.text, prefix=a.text.startswith("["))
        data = pack.codec.from_text(enc_text)
        addr, fnt = pack.addr, pack.fonts[a.font_no]
        if enc.missing:
            print(f"warning: no slot for {list(enc.missing)[:6]} (run scan with this text in the tree)",
                  file=sys.stderr)
        for w in enc.warnings:
            print("warning: " + w, file=sys.stderr)
    prop, han = STATES[a.state or "prop1han1"]
    print(enc_text)
    widths = preview_png(addr, fnt, data, a.out, a.scale, a.width, prop, han, a.align == "right")
    print(f"preview -> {a.out} ({len(widths)} line(s), {widths} px)")
    return 0


def add_commands(subparsers) -> None:
    p = subparsers.add_parser("lang", help="new scripts: scan a translated tree into the fonts, encode it, "
                                           "import it, preview it (Arabic, Devanagari, Japanese on USA, ...)")
    sub = p.add_subparsers(dest="lang_cmd", required=True)

    ps = sub.add_parser("scan", help="collect the glyphs a translated tree needs and draw them into font0/1.bin")
    ps.add_argument("--iso", required=True, help="the retail disc (executable, fonts, retail text scan)")
    ps.add_argument("--text", required=True, help="translated text-export tree (logical order)")
    ps.add_argument("--font", help="TrueType/OpenType font to shape and rasterise from")
    ps.add_argument("--face", type=int, default=0, help="face index inside a .ttc")
    ps.add_argument("--px", type=float, default=20.0, help="em size in pixels (cell is 20x24)")
    ps.add_argument("--baseline", type=int, default=17, help="baseline row in the 24 px cell")
    ps.add_argument("--script", help="HarfBuzz script tag: Arab, Hebr, Deva, Geor, Cyrl, ...")
    ps.add_argument("--language", help="BCP-47 language for shaping (ar, he, hi, ka, ...)")
    ps.add_argument("--rtl", action="store_true", help="right-to-left paragraphs")
    ps.add_argument("--donor", help="take glyph images from this Episode III disc's font0 (e.g. the Japanese "
                                    "disc: kana and kanji for Japanese on the USA build)")
    ps.add_argument("--cells", help="PNG sheet of hand-drawn 20x24 cells instead of --font")
    ps.add_argument("--keys", help="text file, one key per line, matching --cells order")
    ps.add_argument("--unlock", choices=tuple(glyphmod.UNLOCK_MODES), default="none",
                    help="USA/prototype: slot model of the patched executable (glyphs-unlock; untested in game)")
    ps.add_argument("--reclaim-latin", action="store_true",
                    help="USA: free the Latin-1 cells retail text draws (the tree must not use them any more)")
    ps.add_argument("--extend", help="glyphset.json of an earlier scan (another script) to add to")
    ps.add_argument("--font0", help="start from this font0.bin instead of the disc's")
    ps.add_argument("--font1", help="start from this font1.bin instead of the disc's")
    ps.add_argument("--prop-only", action="store_true")
    ps.add_argument("--wide-only", action="store_true")
    ps.add_argument("--state", choices=tuple(STATES), default="prop1han1", help="measuring state")
    ps.add_argument("--spacing", choices=("font", "ink"), default="font",
                    help="proportional advance: the TrueType font's own (joins touch; default) or ink + 2 px")
    ps.add_argument("--out", required=True)
    ps.set_defaults(func=_wrap(cmd_scan))

    pe = sub.add_parser("encode", help="the tree with target-script runs as glyph codes (wrapped, visual order)")
    pe.add_argument("--text", required=True)
    pe.add_argument("--pack", required=True, help="the folder 'lang scan --out' wrote")
    pe.add_argument("--out", required=True)
    pe.add_argument("--width", type=int, default=0, help="wrap width in pixels (0 = only your own breaks)")
    pe.add_argument("--align", choices=("left", "right"), default="left")
    pe.add_argument("--layout-kinds", default=",".join(LAYOUT_KINDS),
                    help="object kinds --width/--align apply to (default sb,subtitle,msgdat; menus stay one line)")
    pe.add_argument("--state", choices=tuple(STATES), default=None)
    pe.add_argument("--rtl", dest="rtl", action="store_true", default=None)
    pe.add_argument("--ltr", dest="rtl", action="store_false")
    pe.set_defaults(func=_wrap(cmd_encode))

    pi = sub.add_parser("import", help="text-import of an encoded tree + the pack's fonts (+ unlocked executables) "
                                       "into COPIES of the disc(s)")
    pi.add_argument("--iso", action="append", required=True, help="source image, never written (repeat for Disc 2)")
    pi.add_argument("--text", required=True, help="the tree 'lang encode' wrote")
    pi.add_argument("--pack", required=True)
    pi.add_argument("--out", required=True, help="output folder (OUT/<source name>) or one .iso path")
    pi.add_argument("--grow", action="store_true")
    pi.add_argument("--rebase", action="store_true")
    pi.add_argument("--dry-run", action="store_true")
    pi.add_argument("--ceiling", default=None)
    pi.add_argument("--overwrite", action="store_true",
                    help="replace output images that already exist (an earlier output; never an original)")
    pi.add_argument("--report")
    pi.set_defaults(func=_wrap(cmd_import))

    pp = sub.add_parser("preview", help="render an encoded line (or a string read back from a disc) to PNG")
    pp.add_argument("--pack", help="a scan folder (with --text)")
    pp.add_argument("--text", help="logical text to encode and draw")
    pp.add_argument("--iso", help="read the string back from this (patched) disc instead")
    pp.add_argument("--path", help="with --iso: the in-game path, e.g. 'cf\\us\\1010.sb'")
    pp.add_argument("--key", help="with --iso: the string key, e.g. 0001 ('*' for a whole subtitle file)")
    pp.add_argument("--out", required=True)
    pp.add_argument("--width", type=int, default=0)
    pp.add_argument("--align", choices=("left", "right"), default="left")
    pp.add_argument("--scale", type=int, default=2)
    pp.add_argument("--font-no", type=int, choices=(0, 1), default=0)
    pp.add_argument("--state", choices=tuple(STATES), default=None)
    pp.add_argument("--rtl", dest="rtl", action="store_true", default=None)
    pp.add_argument("--ltr", dest="rtl", action="store_false")
    pp.set_defaults(func=_wrap(cmd_preview))


# --- self-test -------------------------------------------------------------------------------------------

def _synthetic_pack(rtl: bool = True) -> Tuple[Pack, Addressing]:
    us_prof = dataclasses.replace(fontmod.PROFILES["def4d42429001ca86111c6fa86dc84bdeb9a93c4"], clut_va=0)
    a = Addressing.from_executable(fontmod._synthetic_elf(us_prof), us_prof)
    f = Font.blank()
    for c in range(128, 192):                     # inked han cells (ASCII) and Latin-1 cells
        f.set_cell(c + fontmod.PROP_CELL_SHIFT, [[2 if 2 <= x < 8 else 0 for x in range(20)] for _ in range(24)])
        f.set_metrics(c, 2, 7)
    for c in range(256, 384):
        f.set_cell(c + fontmod.PROP_CELL_SHIFT, [[2 if 2 <= x < 8 else 0 for x in range(20)] for _ in range(24)])
        f.set_metrics(c, 2, 7)
    model = glyphmod.build_model(a, {361}, f)
    cfg = {"region": "us", "unlock": "none", "rtl": rtl, "addressing": _addr_to_json(a),
           "model": _model_to_json(model), "reclaimed": []}
    gs = GlyphSet("synthetic")
    pack = Pack(cfg, gs, [f, Font.from_bytes(f.to_bytes())])
    return pack, a


class _FakeShaper:
    """One key per character, visual order for RTL, every glyph 6 px of ink."""
    name = "fake"
    notdef: set = set()

    def keys(self, word, rtl):
        seq = [f"u:{c}" for c in word]
        return seq[::-1] if rtl else seq

    def glyph(self, key):
        return Glyph(key, [[3 if 2 <= x < 8 and 4 <= y < 18 else 0 for x in range(20)] for y in range(24)])


class _EchoEncoder(Encoder):
    """The encoder with each glyph code written as the character it draws (every
    glyph 6 px): the output reads as a visual-order string, comparable with a
    reference bidi implementation's display string."""

    def _code_text(self, key: str) -> str:
        return key[2:] if key.startswith("u:") else key

    def key_width(self, key: str) -> int:
        return 6


# (logical, visual left-to-right) in a right-to-left paragraph. The visual strings
# are ICU 78 ubidi_writeReordered(UBIDI_DO_MIRRORING) output, checked by hand.
_BIDI_CASES = [
    ("سلام (abc def) ghi", "ghi (abc def) مالس"),        # N0: Latin in brackets, context R
    ("[a(b]c) سلام", "مالس (c[a(b]"),                    # BD16: only [ ] pair; ( ) are plain neutrals
    ("(سلام)", "(مالس)"),                                  # L4: both brackets mirrored
    ("سلام «abc» عليكم", "مكيلع «abc» مالس"),             # mirrored angle quotes
    ("سلام 1,000.5 عليكم", "مكيلع 1,000.5 مالس"),         # W4: separators inside a number
    ("سلام 50% عليكم", "مكيلع %50 مالس"),                  # W2: digits after Arabic are AN, % stays out
    ("שלום 50% עולם", "םלוע 50% םולש"),                    # Hebrew: digits stay EN, W5 takes the %
    ("$5 سلام", "مالس $5"),                                # W5 (bidi only: a typed '$' warns, DOLLAR_WARNING)
    ("1+2=3 سلام", "مالس 3=1+2"),                          # W4 + N1 around = (EN EN only)
    ("رقم ٤٢ هنا", "انه ٤٢ مقر"),                          # Arabic-Indic digits read left to right
    ("HP و EP بالكامل", "لماكلاب EP و HP"),               # Latin words inside Arabic
    ("שלום 12:30 PM", "PM 12:30 םולש"),                    # Hebrew with a time and Latin
]


def self_test() -> int:
    import tempfile
    ok = True

    def check(cond, msg):
        nonlocal ok
        print(("ok    " if cond else "FAIL  ") + msg)
        ok &= bool(cond)

    # Arabic forms (cells path)
    f = arabic_forms("بيت")
    check(f == ["\ufe91", "\ufef4", "\ufe96"], f"arabic_forms('بيت') joins: {[hex(ord(c)) for c in f]}")
    check(arabic_forms("لا") == ["\ufefb"], "lam-alef ligature")
    check(SimpleShaper(True).keys("بيت", True) == ["u:\ufe96", "u:\ufef4", "u:\ufe91"],
          "--cells shaper: presentation-form keys in visual (right-to-left) order")

    # atoms: control escapes keep their operands, commands, tags, breaks, prefix
    pack, a = _synthetic_pack()
    ats = atoms("[Hong]<l2>$col707070;Hi⟦19⟧⟦03⟧ x\\ny⟦0D⟧⟦0A⟧z⟦15⟧⟦02⟧⟦04⟧⟦07⟧!$rubys;A$rubyb;b$rubye;",
                a, prefix=True)
    kinds = [x.kind for x in ats]
    check(kinds[:3] == ["prefix", "ctrl", "ctrl"] and ats[5].text == "⟦19⟧⟦03⟧" and "break" in kinds
          and any(x.text == "⟦0D⟧⟦0A⟧" and x.kind == "break" for x in ats)
          and any(x.text == "⟦15⟧⟦02⟧⟦04⟧⟦07⟧" for x in ats) and kinds[-1] == "ruby",
          f"atoms: prefix, <lN>, $col, ⟦19⟧+operand, \\n, CR LF, ⟦15⟧ variable length, ruby ({len(ats)} atoms)")

    # encoder on a synthetic USA build
    shaper = _FakeShaper()
    for k in "سلامعليكم":
        pack.gs.add(shaper.glyph(f"u:{k}"))
    order = [f"u:{k}" for k in "سلامعليكم"]
    pack.gs.allocate(order, pack.model)
    for fnt in pack.fonts:
        pack.gs.apply(fnt)
    enc = Encoder(pack, shaper, True)
    eng = "[Shion]<l2>Hello, Möbius.\\nSee <kGnosis> now.<w45><f>"
    check(enc.string(eng, prefix=True) == eng, "no target character: the string comes back unchanged")
    s = enc.string("سلام KOS-MOS 42.<f>")
    codes = {k: "".join(f"⟦{b:02X}⟧" for b in pack.gs.code_bytes(k)) for k in order}
    want = ".KOS-MOS 42 " + "".join(codes[f"u:{c}"] for c in "سلام"[::-1]) + "<f>"
    check(s == want, f"RTL: Latin and digits stay forward, the Arabic run is reversed, <f> stays last: {s[:60]!r}")
    enc_w = Encoder(pack, shaper, True, width=60)
    s3 = enc_w.string("<l1>عليكم سلام عليكم سلام")
    check(s3.count("\\n") >= 1 and s3.startswith("<l") and f"<l{s3.count(chr(92) + 'n') + 1}>" in s3,
          f"wrap at 60 px adds line breaks and <lN> follows the line count: {s3[:24]!r}...")
    b = pack.codec.from_text(s)
    han = {fontmod.cell_index(a.cell(a.han_code(x) >> 8, a.han_code(x) & 0xFF, 0)) for x in range(0x20, 0x80)}
    slot_cells = [pack.gs.slots[f"u:{c}"]["cell"] for c in "سلام"[::-1]]
    got = cells_of(a, b)
    check(got[-4:] == slot_cells and all(c in han for c in got[:-4]),
          f"every glyph code reads back through the addressing as its slot's cell ({slot_cells})")
    check(enc.string("(سلام)") == "(" + "".join(codes[f"u:{c}"] for c in "سلام"[::-1]) + ")",
          "brackets around an RTL word stay balanced (mirrored as a neutral run)")
    echo = _EchoEncoder(pack, shaper, True)
    unesc = lambda t: _ESC1.sub(lambda m: chr(int(m.group(1), 16)), t)     # « » come back as escapes
    bad = [(lg, unesc(echo.string(lg)), vis) for lg, vis in _BIDI_CASES if unesc(echo.string(lg)) != vis]
    check(not bad, f"UAX #9 on {len(_BIDI_CASES)} reference lines (paired brackets N0, mirroring L4, numbers "
                   f"W2/W4/W5, Arabic-Indic digits, Latin inside Arabic, Hebrew) equal ICU's display order {bad[:2]}")
    dlg = "إلى أين يذهب؟ انتظر، ربما إلى الحديقة (رقم 42)؟"
    got_l = _EchoEncoder(pack, shaper, True, width=250).string(dlg).split("\\n")
    check(got_l == ["مقر) ةقيدحلا ىلإ امبر ،رظتنا ؟بهذي نيأ ىلإ", "؟(42"],
          f"a bracket pair split by the wrap: resolved on the paragraph, then each line reordered "
          f"(ICU ubidi_setLine) {got_l}")
    tg = [echo.string("اضغط على <○>."), echo.string("قال <Joachim Mizrahi>: لا<w15> نعم<f>")]
    check(tg == [".<○> ىلع طغضا", "معن<w15> ال :<Joachim Mizrahi> لاق<f>"],
          f"a drawn tag (button mark, keyword) is an inline object placed by the bidi pass (the full stop "
          f"after <○> lands on its left); printer tags stay glued / last {tg}")
    check(bidi_levels("abc سلام 12", 0) == [0, 0, 0, 0, 1, 1, 1, 1, 1, 2, 2]
          and bidi_levels("abc سلام 12", 1) == [2, 2, 2, 1, 1, 1, 1, 1, 1, 2, 2],
          "bidi_levels: left-to-right and right-to-left paragraph levels (EN after AL is AN)")
    # ICU 78 ubidi_getLevels reference values (U+0628 beh, U+0651 shadda, U+200D ZWJ)
    icu = [("ب (ب)ّ c", 0, [1, 1, 1, 1, 1, 0, 0, 0]),                  # a mark after an N0 bracket stays neutral
           ("\u0639\u2329\u0643\u232a\u3009", 0, [1, 1, 1, 1, 0]),      # resolved pair drops the U+3009 synonym
           ("\u3008\u3009K\u232a9", 1, [1, 1, 2, 1, 2]),                # N0d pair keeps it: U+232A pairs with U+3008
           ("a\u200dب", 0, [0, 1, 1]), ("ب\u200d", 0, [1, 0])]          # a joiner takes the next level
    bad = [(x, b, bidi_levels(list(x), b), w) for x, b, w in icu if bidi_levels(list(x), b) != w]
    check(not bad and MIRROR["\u2329"] == "\u232a",
          f"bidi_levels equals ICU 78 on angle-bracket synonyms (U+2329/U+3008), a mark after a bracket and "
          f"joiners {bad}")
    plain = ["Hello (world) 50% $5 1,000.5 [a(b]c) <x> «q»", "[Shion]<l2>KOS-MOS: 12:30 PM?\\nOK.<f>",
             "Möbius - 3+4=7 (ok)"]
    check(all(echo.string(x, prefix=True) == x for x in plain),
          "no target character: English with brackets, numbers and Latin-1 comes back byte for byte")
    # a typed '$' is not text for the game: warned about, and drawn by the preview as the printer does
    wn = Encoder(pack, shaper, True)
    wn.string("$5 سلام")
    wn.string("$col1;سلام$col0;")
    d_lit, d_cmd = render_bytes(a, pack.fonts[0], b"$5")[1], render_bytes(a, pack.fonts[0], b"$col1;5")[1]
    check(len(wn.warnings) == 1 and "'$5" in wn.warnings[0] and d_lit > d_cmd > 0,
          f"a literal '$' (no command name after it) is warned about once, a $col1; command is not; "
          f"the preview draws the literal '$' like FUN_00184090 ({d_lit} px vs {d_cmd} px for '$col1;5')")
    ctrl = "⟦19⟧⟦03⟧سلام"
    check(enc.string(ctrl).startswith("⟦19⟧⟦03⟧"), "a control byte with its operand stays in front, untouched")
    # collect mode returns the text and counts keys
    col = Encoder(pack, shaper, True, collect=True)
    col.string("سلام سلام")
    check(sum(col.counts.values()) == 8 and set(col.counts) == {f"u:{c}" for c in "سلام"}, "scan counts glyph keys")
    # preview renders through the addressing
    with tempfile.TemporaryDirectory() as td:
        widths = preview_png(a, pack.fonts[0], b, Path(td) / "p.png")
        check(len(widths) == 1 and widths[0] > 50 and (Path(td) / "p.png").stat().st_size > 100,
              f"preview renders the line ({widths[0]} px)")
        # tree transform: block file + subtitle, untouched blocks byte for byte
        blk = "# header\n### 0000 identifier\nseg_now\n### 0001 dialogue\n[Shion]سلام<f>\n### 0002 note cp932\nメモ\n"
        out = transform_block_file(blk, ["us", "us", "cp932"], "us",
                                   lambda body, w: enc.string(body, prefix="dialogue" in w))
        check(out.split("\n")[:3] == blk.split("\n")[:3] and "seg_now" in out and out.split("\n")[-2] == "メモ"
              and "[Shion]⟦" in out, "block file: identifier and note untouched, dialogue encoded, prefix kept first")
        sub = "00:00:00\t$ay375;$xx0,24;\r\n00:23:05\tسلام\r\n00:24:08\r\n"
        out2 = transform_whole_file(sub, "movie", enc.string)
        check(out2.startswith("00:00:00\t$ay375;$xx0,24;\r\n00:23:05\t⟦") and out2.endswith("\r\n00:24:08\r\n"),
              "subtitle: time codes, init line and CR LF kept, text after the tab encoded")
    # unlock re-encode (synthetic USA exe)
    us_prof = dataclasses.replace(fontmod.PROFILES["def4d42429001ca86111c6fa86dc84bdeb9a93c4"], clut_va=0)
    mu = glyphmod.build_model(a, {361, 193}, pack.fonts[0], "jp")
    cfg = dict(pack.cfg, unlock="jp", model=_model_to_json(mu))
    pu = Pack(cfg, GlyphSet("u"), pack.fonts)
    nb = reencode_bytes(pu, b"M\xe9x $col1; \x19\x03\xa4\xa2")
    ua = glyphmod.unlocked_addressing(a, "jp")
    check(cells_of(ua, nb) == [361, 193] and nb.startswith(b"M\xa5\xeax") and b"\x19\x03" in nb,
          f"unlock jp: retail é (E9, cell 361) -> {nb[1:3].hex().upper()} on the same cell; A4A2 kept; "
          "control operand untouched")
    enc_u = Encoder(pu, shaper, False)
    check(pu.codec.from_text(enc_u.string("Möbius")) == b"M" + mu.code_for(374) + b"bius"
          and enc_u.string("plain") == "plain",
          "unlock: an untouched string with Latin-1 is re-coded as escapes; pure ASCII unchanged")

    # discs: the byte-exact no-op on unmodified trees
    for key in ("XS3_D1", "XS3_JP1"):
        iso = os.environ.get(key)
        if not iso:
            print(f"SKIP  {key} not set")
            continue
        import textpack
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            textpack.export_discs([iso], td / "tree", log=lambda *x: None)
            pk = scan(iso, td / "tree", td / "pack", ttf=None, donor_iso=iso, log=lambda *x: None)
            check(not pk.gs.slots, f"{key}: scanning the unmodified tree finds no target-script glyph")
            n, changed, missing = encode(td / "tree", td / "pack", td / "enc", log=lambda *x: None)
            same = all((td / "enc" / p.relative_to(td / "tree")).read_bytes() == p.read_bytes()
                       for p in (td / "tree").rglob("*") if p.is_file())
            check(n > 800 and changed == 0 and same,
                  f"{key}: lang encode of the unmodified tree is byte-identical ({n} files, {changed} changed)")
            if key == "XS3_D1":
                mu_pack = Pack.load(td / "pack")
                cfg = dict(mu_pack.cfg, unlock="jp")
                exe = fontmod.read_boot_exe(iso)
                ad = Addressing.from_executable(exe)
                from disc import Disc
                with Disc(iso) as d:
                    rs = glyphmod.scan_retail(d, ad)
                    f0 = _disc_fonts(d, ad)[0]
                m2 = glyphmod.build_model(ad, rs.reserved(), f0, "jp")
                cfg["model"] = _model_to_json(m2)
                (td / "pack" / PACK_CFG).write_text(json.dumps(cfg), encoding="utf-8")
                n2, ch2, _m = encode(td / "tree", td / "pack", td / "enc_u", log=lambda *x: None)
                pu2 = Pack.load(td / "pack")
                ns, nre, bad = verify_reencode(td / "tree", td / "enc_u", pu2)
                check(ch2 > 0 and nre > 0 and not bad,
                      f"{key}: under --unlock jp every display string draws the same cells through the patched "
                      f"gate ({ns} strings, {nre} re-coded, {ch2} files changed, {len(bad)} problems "
                      f"{bad[:2]})")
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
