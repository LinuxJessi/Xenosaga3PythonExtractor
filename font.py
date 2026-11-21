"""font.py — Episode III's bitmap fonts (``mnu\\us\\font0.bin`` / ``font1.bin``).

Borrowed from Xenosaga2PythonExtractor/font.py (2026-11-20). What changed:

* the FILE layer is new. Episode III's fonts have no 0x20 headers and no GS
  swizzle (the XS2 reader runs on them without error but returns noise), so
  ``decode_block`` / ``encode_block`` are replaced by a planar split, and the
  file also carries a 512-pair metric table and an 8x8 system font;
* the ADDRESSING is a fresh port from SLUS_213.89 (below), with Episode III's
  pair gate, the 0x1000 fixed-width flag, two extra-kanji lists and the
  ``right - left + 3`` / ``right + 2`` advance;
* the Measurer follows Episode III's width function (``$xx7``, ``$zoom``,
  control bytes 0x12/0x15/0x18/0x19, half-size mode) instead of XS2's;
* kept unchanged from XS2: the stdlib PNG reader/writer (``sheet_to_png``,
  ``png_to_gray``, ``quantize``), the sheet convention (4 sheets of 640x768,
  a 32x32 grid of 20x24 cells, 4 grey levels), the metrics CSV shape and the
  font-rebuild refusals;
* Episode I's addressing (fenced in the XS2 module) is not carried over, and
  neither is XS2's GS swizzle reader: the round-1 ``font-jp-kana`` helper that
  used an Episode II Japan font as a kana donor is gone. A Japanese donor
  must be the Episode III Japan disc (its font0 kanji are re-anti-aliased
  and its half-size kana block 768-959 is new), so ``font-donor`` copies cells
  and metrics between two Episode III fonts.

Regions (round 2). The FILE layer has no region branch: the Japanese fonts
(``mnu\\jp\\font0.bin`` / ``font1.bin`` on SLPS_256.40/41) have the same
layout. The ADDRESSING differs, and every difference is read from the
executable at the profile's VAs (``Addressing.from_executable``):

    field         read from                                   us / proto         jp
    gate          pair gate FUN_00181e48 (4 words at its VA)  whitelist          lead >= 0xA0 (EUC)
    prop_cells    the two prop-gate immediates                0x180 (384)        0xC0 (192)
                  (printer slti/sltiu, measurer slti)         0x1856e4/0x182dd4  0x185584/0x182c7c
    a9_row        code->cell jump table entry for lead A9     own case           = the AA..AC fallback
                  (US FUN_00184938 table 0x540080;            (Latin-1 singles)  (0x80-0x9F -> 0x7F)
                  JP 0x1847d8 table 0x53e8c0)
    half-size     FUN_00181db8, checked by sha1 of its bytes  same VA, identical code

So on Japan: every byte from 0xA0 up starts a two-byte code (trail not
tested), a lone 0x80-0x9F draws the fallback cell 0x7F (the single-byte path
goes through lead A9, which has no row), kana (cells 192-383) are never
proportional (advance 19), and the proportional tier is cells 0-191. The
half-size path (control 0x18) measures ``half_cell(cell)`` with the metric
pair of that cell and draws cell + 0x240: on Japan cells 768-959 hold the
half-size kana whose ink the metric pairs 192-383 describe (checked: 192/192
on font0), on USA they hold the proportional cp1252 images.

File layout (0x78C00 = 494,592 bytes, both files; Disc 1, Disc 2 and the
May 2006 prototype carry identical copies, and so do JP Disc 1 and Disc 2)::

    0x00000  1,024 cells x 480 bytes: 20x24 PSMT8, row-major, linear.
             Each byte packs four 2-bit planes: plane k = (byte >> 2k) & 3.
             Glyph cell n lives in byte cell (n & 0x3FF), plane (n >> 10),
             so the file holds 4 x 1,024 = 4,096 glyph cells.
    0x78000  512 (left, right) byte pairs, indexed by base cell
    0x78400  0x800 bytes: 1bpp 512x32 system font (8x8 glyphs, MSB first)

Sheet k (640x768) = plane k laid out as a 32x32 grid, so sheet k holds cells
1024k .. 1024k+1023, the same numbering as XS1/XS2 sheets.

How the engine draws (SLUS_213.89; the May 2006 prototype's code is the same
at the same function addresses, with its data shifted - see ``PROFILES``):

* ``FUN_00184188`` uploads one cell (``font + (cell & 0x3FF) * 0x1E0``) as a
  PSMT8 20x24 image (GIF packet at VA 0x4B3250) and sets TEX0 CBP =
  0x3FC0 + ((cell & 0xC00) >> 8): one CLUT per plane.
* The four CLUTs are uploaded from VA 0x4B1E90 (GIF packet at 0x4B1E40:
  BITBLTBUF DBP 0x3FC0, 32x32 PSMCT32). Checked here (``clut_check``): CLUT k
  maps index i to white with alpha (0, 0x2A, 0x55, 0x80)[(i >> 2k) & 3] for all
  256 entries of all four CLUTs (CSM1 order). So the 2-bit value is a linear
  coverage level, and the PNG grey levels 0/85/170/255 are exact.
* ``FUN_00181fa0`` expands the 8x8 font (nibble -> 4 bytes through the table
  at VA 0x4B3058, high nibble first, bit 3 = leftmost pixel) into a 512x32
  PSMT8H texture.

Addressing (``Addressing``, all tables read from the executable by VA):

* Code -> cell: ``xs3_cell`` = ``FUN_00184938``. Rows A1-AD by per-row rules
  (jump table at VA 0x540080), kanji rows B0-CF = lead*94 + trail - 0x3D41
  (B0A1 = cell 1024), lead D0 and up looked up by ``FUN_00181d40`` in an
  extra-kanji list (font0: VA 0x4B3020, font1: VA 0x4B2F50; chosen by the
  byte at 0x7E7E06), cell 0xF95 + index; anything else falls back to 0x7F.
  Codes A1B9, A1BC, A1F9-A1FE and the A2A0-A2AF group carry bit 0x1000: the
  proportional gate tests cell < 0x180 (Japan: 0xC0), so they are always fixed width. The
  draw call ignores bit 12 (``cell_index`` strips it).
* Pair gate: ``pair_gate`` = ``FUN_00181e48``. Lead A4 or A6 with any non-zero
  trail; A1 with BD DA DB DF EE F9 FA FB FC; A2 with A2-A6, AA-AD and F6; A3
  with B0-B9; AD with B5-B7 (whole function read, 0x181E48-0x181F94). Any other byte from 0x80 up is ONE character: lead A9, trail
  byte+0x80, so cell = byte + 0x80 (0xE9 'e acute' = cell 361). Japan: see
  "Regions" above (``pair_gate(..., gate="euc")``).
* ``$han1;``: ASCII 0x20-0x7F -> EUC code from the u16 table at VA 0x4B2E50
  (``FUN_00181d10``, table base + 2*byte). Without ``$han`` an ASCII byte is
  not a cell: it is drawn from the 8x8 font and is ``$zoom`` pixels wide.
* Width of one glyph: ``FUN_00185770`` reads u16 ``font+0x78000+2*cell``:
  ``right - left + 3`` when left != 0, ``right + 2`` when left == 0, ``$xx1 + 1``
  for cell 0, and ``2 * (xx3 >> 1)`` (10 when that is 0) while ``$xx3`` is
  non-zero. The image of a proportional glyph is cell + 0x240 (576).
* Control bytes 0x01-0x1F: operand lengths from the table at VA 0x4B3150
  (``FUN_00182290``); 0x08 and 0x15 are variable (0x08: a flag byte whose set
  bits add the bytes at VA 0x53FD40 = 2,2,3,2,2; 0x15: a length byte L and L
  more bytes).
* ``$``-commands: table at VA 0x4B31B0 (name, handler) pairs, 18 entries;
  ``FUN_00184090`` takes the FIRST name that is a prefix of the text after '$'.

Usage (wired into the kit CLI through ``add_commands``)::

    font-extract --iso DISC.iso --out DIR    # sheets, metrics, sys8x8, code table
    font-rebuild --ref font0.bin --sheets DIR [--metrics CSV] --out new.bin
    font-measure --iso DISC.iso --text '$prop1;$han1;Hello'
    font-donor --from JP.iso --to US.iso --cells 192-255 --out DIR   # cells + metrics
                     # (cells the --to disc's retail text draws are refused: on USA
                     # 256-383 are cp1252 0x80-0xFF, e.g. 361 é, 374 ö, 302 ®)
    python font.py --self-test
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import os
import struct
import sys
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Sequence, Tuple

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

FILE_SIZE = 0x78C00
CELL_BYTES = 480
CELL_W, CELL_H = 20, 24
SHEET_W, SHEET_H = 640, 768
CELLS_PER_ROW = 32
CELLS_PER_SHEET = 1024
SHEETS = 4
CELL_COUNT = CELLS_PER_SHEET * SHEETS          # 4096
METRICS_OFF = 0x78000
METRIC_PAIRS = 512
SYS_OFF = 0x78400
SYS_SIZE = 0x800
SYS_W, SYS_H = 512, 32

FALLBACK_CELL = 0x7F
FIXED_FLAG = 0x1000
EXTRA_KANJI_BASE = 0xF95                       # 3989, FUN_00181d40
PROP_LIMIT = 0x180                             # proportional if cell < 0x180 (slti 0x180)
PROP_CELL_SHIFT = 0x240                        # 576: image of a proportional glyph
FIXED_ADVANCE = 0x13                           # 19
CLUT_ALPHA = (0x00, 0x2A, 0x55, 0x80)
GREY = (0, 85, 170, 255)

FONT_PATHS = ("\\mnu\\us\\font0.bin", "\\mnu\\us\\font1.bin")     # the USA pair; see font_paths
JP_PROP_CELLS = 0xC0                           # 192: the Japanese prop-gate immediate


def font_paths(lang: str = "us") -> Tuple[str, str]:
    """``mnu\\<lang>\\font0.bin`` and ``font1.bin`` (the engine's ``mnu\\xx\\`` template)."""
    return (f"\\mnu\\{lang}\\font0.bin", f"\\mnu\\{lang}\\font1.bin")


class FontError(ValueError):
    pass


# --- build profiles: where the tables live in each executable ---------------
#
# Not to be confused with regions.py (the LBA-source -> X3.* container mapper).
# Keyed by SHA-1 of the boot executable. US Disc 1 SLUS_213.89 and Disc 2
# SLUS_214.17 are the same file. The prototype's VAs were found by searching
# its executable for the retail tables' bytes (each found exactly once) and
# checked against its code: the font functions are at the retail addresses and
# differ only in the lui/addiu/lw immediates that point at these tables.

@dataclass(frozen=True)
class Profile:
    name: str
    han_va: int
    extra_va: Tuple[int, int]                  # font0, font1
    ctl_va: int
    ctl08_va: int
    cmd_va: int
    clut_va: int
    font_dir: str = "us"
    # code addresses (round 2): the region rules are read from these. None
    # (synthetic test profiles only) = the USA rules, unread.
    gate_va: Optional[int] = None              # pair gate (FUN_00181e48 in every build)
    prop_imm_va: Tuple[int, ...] = ()          # prop gate: printer, measurer (slti/sltiu v0, rX, imm)
    cell_fn_va: Optional[int] = None           # code -> cell function
    jump_va: Optional[int] = None              # its 13-entry jump table (leads A1..AD)
    half_va: Optional[int] = None              # half-size map (FUN_00181db8 in every build)


PROFILES: Dict[str, Profile] = {
    "def4d42429001ca86111c6fa86dc84bdeb9a93c4": Profile(
        "us", han_va=0x4B2E50, extra_va=(0x4B3020, 0x4B2F50), ctl_va=0x4B3150,
        ctl08_va=0x53FD40, cmd_va=0x4B31B0, clut_va=0x4B1E90,
        gate_va=0x181E48, prop_imm_va=(0x1856E4, 0x182DD4), cell_fn_va=0x184938, jump_va=0x540080,
        half_va=0x181DB8),
    # the prototype's code is at the retail addresses; its data is shifted
    "e6c40f2f512586498a2d266cb45377f07ea1e62f": Profile(
        "proto-2006-05", han_va=0x4B2C10, extra_va=(0x4B2DE0, 0x4B2D10), ctl_va=0x4B2F10,
        ctl08_va=0x53FAE0, cmd_va=0x4B2F70, clut_va=0x4B1C50,
        gate_va=0x181E48, prop_imm_va=(0x1856E4, 0x182DD4), cell_fn_va=0x184938, jump_va=0x53FE20,
        half_va=0x181DB8),
    # SLPS_256.40 / SLPS_256.41 (one executable, sha256 b82b6744...). VAs from the
    # JP synthesis brief (S1, section 1); ctl08 (0x53E580) and CLUT (0x4B05E0) found
    # here by searching for the retail tables' bytes (one hit each, CLUT 4,096/4,096
    # bytes equal); the jump table VA is the one the cell function's lui/addiu loads.
    "e8125f743e0e7fda0ec392ea845dd0069470af3b": Profile(
        "jp", han_va=0x4B15A0, extra_va=(0x4B1770, 0x4B16A0), ctl_va=0x4B18A0,
        ctl08_va=0x53E580, cmd_va=0x4B1900, clut_va=0x4B05E0, font_dir="jp",
        gate_va=0x181E48, prop_imm_va=(0x185584, 0x182C7C), cell_fn_va=0x1847D8, jump_va=0x53E8C0,
        half_va=0x181DB8),
}

# the pair gate's first four words: the Japanese gate IS these four words
# (andi v0,a0,0xff; sltiu v0,v0,0xa0; jr ra; sltiu v0,v0,1 = "lead >= 0xA0");
# the USA whitelist gate starts andi a1,a1,0xff; andi a0,a0,0xff; beq a1,zero; ...
GATE_EUC_WORDS = bytes.fromhex("ff008230a000422c0800e0030100422c")
GATE_US_HEAD = bytes.fromhex("ff00a530ff0084305000a0102d100000")
# FUN_00181db8, the half-size map: these 0x90 bytes in us / proto / jp alike
HALF_FN_CODE = bytes.fromhex(
    "40ff8324c000632c1f0060142d108000ff0f85301b0002241900a210000000001c00a228"
    "080040503c0002241600a0102d100000050003241300a3107e0102240800e0037f010224"
    "0d00a210000000003c00a2280c0040147f0102248d00a228090040107f0102248000a228"
    "060040547f0102240800e00393008224000000000800e0037d0102240800e00300000000")


# the code words glyphs.py's optional unlocks rewrite in the USA / prototype
# executable: (VA, retail bytes, patched bytes). An executable that differs
# from a known one only at these sites gets that build's profile, and its rules
# are then read from the patched code (gate euc / prop cells 0xC0).
UNLOCK_SITES = (
    (0x181E48, GATE_US_HEAD, GATE_EUC_WORDS),                                  # pair gate -> JP's 4 words
    (0x1856E4, struct.pack("<I", 0x2E220180), struct.pack("<I", 0x2E2200C0)),  # printer prop gate
    (0x182DD4, struct.pack("<I", 0x28820180), struct.pack("<I", 0x288200C0)),  # measurer prop gate
)


def unpatched(exe: bytes) -> bytes:
    """``exe`` with every unlock site that holds its patched bytes put back."""
    out = bytearray(exe)
    for va, old, new in UNLOCK_SITES:
        try:
            o = va_to_offset(exe, va, len(new))
        except FontError:
            continue
        if out[o:o + len(new)] == new:
            out[o:o + len(new)] = old
    return bytes(out)


def profile_for(exe: bytes) -> Profile:
    h = hashlib.sha1(exe).hexdigest()
    p = PROFILES.get(h)
    if p is None and exe[:4] == b"\x7fELF":
        p = PROFILES.get(hashlib.sha1(unpatched(exe)).hexdigest())
    if p is None:
        raise FontError(f"unknown executable (sha1 {h}): no font table addresses are known for it")
    return p


def va_to_offset(exe: bytes, va: int, n: int = 1) -> int:
    """File offset of ``va`` through the ELF's PT_LOAD headers (US: data VA =
    file offset + 0x11F000; read from the headers, not assumed)."""
    if exe[:4] != b"\x7fELF":
        raise FontError("not an ELF file")
    phoff, = struct.unpack_from("<I", exe, 0x1C)
    phnum, = struct.unpack_from("<H", exe, 0x2C)
    for k in range(phnum):
        typ, off, vaddr, _pa, filesz = struct.unpack_from("<5I", exe, phoff + 32 * k)
        if typ == 1 and vaddr <= va and va + n <= vaddr + filesz:
            return off + va - vaddr
    raise FontError(f"VA {va:#x} is not in a loaded segment's file data")


def read_va(exe: bytes, va: int, n: int) -> bytes:
    o = va_to_offset(exe, va, n)
    return bytes(exe[o:o + n])


def _lui_refs(exe: bytes, fn_va: int, words: int = 64) -> List[int]:
    """Addresses built by ``lui rX, hi`` + ``addiu/lw ..., lo(rX)`` in the first
    ``words`` instructions of a function (a masked-signature check that a data VA
    belongs to that code)."""
    ws = struct.unpack(f"<{words}I", read_va(exe, fn_va, 4 * words))
    hi, out = {}, []
    for w in ws:
        op, rs, rt, imm = w >> 26, (w >> 21) & 31, (w >> 16) & 31, w & 0xFFFF
        if op == 0x0F:
            hi[rt] = imm << 16
        elif op in (0x09, 0x23) and rs in hi:
            out.append((hi[rs] + (imm - 0x10000 if imm & 0x8000 else imm)) & 0xFFFFFFFF)
    return out


# --- addressing ----------------------------------------------------------------

def pair_gate(lead: int, trail: int, gate: str = "whitelist") -> bool:
    """``FUN_00181e48``: does the print/width code read (lead, trail) as one code?
    ``gate`` "whitelist" = the USA/prototype function, "euc" = the Japanese
    four-word function (lead >= 0xA0, trail not tested)."""
    lead &= 0xFF
    trail &= 0xFF
    if gate == "euc":
        return lead >= 0xA0
    if trail == 0:
        return False
    if lead in (0xA4, 0xA6):
        return True
    if lead == 0xA1:
        return trail in (0xBD, 0xDA, 0xDB, 0xDF, 0xEE, 0xF9, 0xFA, 0xFB, 0xFC)
    if lead == 0xA2:
        return ((trail + 0x5E) & 0xFF) < 5 or trail in (0xAA, 0xAB, 0xAC, 0xAD, 0xF6)
    if lead == 0xA3:
        return 0xB0 <= trail <= 0xB9
    if lead == 0xAD:
        return 0xB5 <= trail <= 0xB7
    return False


def xs3_cell(lead: int, trail: int, extra: Sequence[Tuple[int, int]] = (), a9_row: bool = True) -> int:
    """``FUN_00184938`` (JP: 0x1847d8): the cell of a two-byte code, with bit
    0x1000 for the codes that are always fixed width. ``extra`` is the active
    extra-kanji list. ``a9_row`` False = the Japanese jump table, whose A9 entry
    is the AA..AC fallback (every other row is the same code in both builds)."""
    lead &= 0xFF
    trail &= 0xFF
    if lead < 0xB0:
        if lead == 0xA1:
            c = (trail - 0xA1) & 0xFFFF
            if trail in (0xB9, 0xBC) or trail >= 0xF9:
                c |= FIXED_FLAG
            return c
        if lead == 0xA2:
            base = {0xA0: 0x105D, 0xE0: 0x6C, 0xF0: 0x75}.get(trail & 0xF0)
            return FALLBACK_CELL if base is None else (trail & 0x0F) + base
        if lead == 0xA3:
            h = trail & 0xE0
            if h == 0xA0:
                return (trail & 0x0F) + 0x80
            if h == 0xC0:
                return (trail & 0x1F) + 0x89
            if h == 0xE0:
                return (trail & 0x1F) + 0xA3
            return FALLBACK_CELL
        if lead == 0xA4:
            return trail + 0x1F
        if lead == 0xA5:
            return trail + 0x7F
        if lead == 0xA6:
            return (trail & 0x1F) + (0x17F if trail < 0xC0 else 0x197)
        if lead == 0xA7:
            return trail + (0x10F if trail < 0xD0 else 0x100)
        if lead == 0xA8:
            return trail + 0x15F
        if lead == 0xA9:
            return trail + 0x100 if a9_row else FALLBACK_CELL
        if lead == 0xAD:
            return trail + 0x17F
        return FALLBACK_CELL
    if lead < 0xD0:
        return (lead * 94 + trail - 0x3D41) & 0xFFFF
    for i, pair in enumerate(extra):
        if tuple(pair) == (lead, trail):
            return EXTRA_KANJI_BASE + i
    return FALLBACK_CELL


def half_cell(cell: int) -> int:
    """``FUN_00181db8``: the cell measured in half-size mode (control byte 0x18)."""
    if 0xC0 <= cell < 0x180:
        return cell
    a = cell & 0xFFF
    if a == 0x1B or a == 0x3C:
        return 0x17D
    if a < 0x1C:
        return 0 if a == 0 else (0x17E if a == 5 else 0x17F)
    if a < 0x3C or a >= 0x8D or a < 0x80:
        return 0x17F
    return cell + 0x93


def cell_index(cell: int) -> int:
    """The glyph cell the draw call uses (bit 0x1000 is not part of it)."""
    return cell & 0xFFF


# the built-in fallback names, used only by synthetic tests; real names are read
CMD_NAMES = ("ax", "ay", "az", "rx", "ry", "init", "save", "load", "col", "bg", "shadow",
             "alpha", "zoom", "xx", "ruby", "prop", "han", "mark")


class Glyph(NamedTuple):
    length: int                 # bytes of text consumed
    kind: str                   # "cell" or "8x8"
    code: int                   # EUC code looked up (0 for "8x8")
    cell: Optional[int]         # with bit 0x1000 when fixed width


class Token(NamedTuple):
    kind: str                   # "cmd", "ctrl", "char", "8x8"
    start: int
    end: int
    name: str = ""              # cmd name
    args: Tuple[str, ...] = ()  # cmd arguments (text between name and ';', split at ',')
    cell: Optional[int] = None


@dataclass(frozen=True)
class Addressing:
    """Byte -> cell -> metric pair, with every table read from the executable."""
    profile: str
    han: Tuple[int, ...]                                   # EUC codes of bytes 0x20..0x7F
    extra: Tuple[Tuple[Tuple[int, int], ...], Tuple[Tuple[int, int], ...]]
    ctl: Tuple[int, ...]                                   # 32 operand lengths, 0xFF = variable
    ctl08: Tuple[int, ...]                                 # 8 byte counts per flag bit
    commands: Tuple[str, ...] = CMD_NAMES
    clut: Tuple[int, ...] = ()                             # 1024 RGBA words as uploaded
    gate: str = "whitelist"                                # "whitelist" (us/proto) or "euc" (jp)
    prop_cells: int = PROP_LIMIT                           # proportional iff cell < prop_cells
    a9_row: bool = True                                    # single bytes 0x80+ -> lead A9 row
    font_dir: str = "us"

    @property
    def latin1_singles(self) -> bool:
        """A lone byte 0x80+ draws its own cell (byte + 0x80). Japan: cell 0x7F."""
        return self.a9_row

    @staticmethod
    def read_rules(exe: bytes, prof: Profile) -> Dict[str, object]:
        """gate / prop_cells / a9_row read from the code at the profile's VAs, each
        checked against the instruction shape it must have (else FontError)."""
        if prof.gate_va is None:
            return {}
        head = read_va(exe, prof.gate_va, 16)
        if head == GATE_EUC_WORDS:
            gate = "euc"
        elif head == GATE_US_HEAD:
            gate = "whitelist"
        else:
            raise FontError(f"the pair gate at {prof.gate_va:#x} is neither the USA whitelist nor the "
                            f"Japanese lead >= 0xA0 function ({head.hex()}): wrong profile or a patched gate "
                            f"of another shape")
        imms = []
        for va in prof.prop_imm_va:
            w, = struct.unpack("<I", read_va(exe, va, 4))
            if (w >> 26) not in (0x0A, 0x0B) or (w >> 16) & 0x1F != 2:
                raise FontError(f"no slti/sltiu v0 at the prop gate {va:#x} ({w:08x})")
            imms.append(w & 0xFFFF)
        if not imms or len(set(imms)) != 1:
            raise FontError(f"the printer and measurer prop gates disagree: {[hex(x) for x in imms]}")
        jt = struct.unpack("<13I", read_va(exe, prof.jump_va, 52))
        if not (jt[9] == jt[10] == jt[11]) or len(_lui_refs(exe, prof.cell_fn_va)) == 0 \
                or prof.jump_va not in _lui_refs(exe, prof.cell_fn_va):
            raise FontError(f"the code->cell jump table at {prof.jump_va:#x} is not the one the function at "
                            f"{prof.cell_fn_va:#x} loads, or its AA..AC entries are not one fallback")
        if read_va(exe, prof.half_va, len(HALF_FN_CODE)) != HALF_FN_CODE:
            raise FontError(f"the half-size map at {prof.half_va:#x} is not FUN_00181db8's code")
        return {"gate": gate, "prop_cells": imms[0], "a9_row": jt[8] != jt[9]}

    @classmethod
    def from_executable(cls, exe: bytes, profile: Optional[Profile] = None) -> "Addressing":
        prof = profile or profile_for(exe)
        rules = cls.read_rules(exe, prof)
        try:
            han = struct.unpack("<96H", read_va(exe, prof.han_va + 0x40, 0xC0))
            lists = []
            for va in prof.extra_va:
                lst = []
                while True:
                    a, b = read_va(exe, va + 2 * len(lst), 2)
                    if a == 0:
                        break
                    lst.append((a, b))
                    if len(lst) > CELL_COUNT - EXTRA_KANJI_BASE:
                        raise FontError("the extra-kanji list does not end: wrong profile?")
                lists.append(tuple(lst))
            ctl = tuple(read_va(exe, prof.ctl_va, 32))
            ctl08 = tuple(read_va(exe, prof.ctl08_va, 8))
            names = []
            for k in range(64):
                p, _h = struct.unpack("<II", read_va(exe, prof.cmd_va + 8 * k, 8))
                if p == 0:
                    break
                o = va_to_offset(exe, p, 1)
                names.append(bytes(exe[o:o + 16]).split(b"\0")[0].decode("ascii"))
            clut = struct.unpack("<1024I", read_va(exe, prof.clut_va, 4096)) if prof.clut_va else ()
        except struct.error as e:
            raise FontError(f"cannot read the font tables: {e}")
        if han[0] != 0xA1A1 or han[ord("A") - 0x20] != 0xA3C1:
            raise FontError("the $han table is not at the profile's address: wrong executable?")
        if any(a < 0xD0 for lst in lists for a, _ in lst):
            raise FontError("an extra-kanji list holds a lead byte below 0xD0: wrong executable?")
        if ctl[0x08] != 0xFF or ctl[0x15] != 0xFF:
            raise FontError("the control-length table is not at the profile's address")
        if not names or any(not n.isalpha() for n in names):
            raise FontError("the $-command table is not at the profile's address")
        return cls(prof.name, tuple(han), (lists[0], lists[1]), ctl, ctl08, tuple(names), tuple(clut),
                   font_dir=prof.font_dir, **rules)

    @classmethod
    def from_iso(cls, iso_path) -> "Addressing":
        return cls.from_executable(read_boot_exe(iso_path))

    # -- code -> cell
    def pair(self, lead: int, trail: int) -> bool:
        return pair_gate(lead, trail, self.gate)

    def cell(self, lead: int, trail: int, font: int = 0) -> int:
        return xs3_cell(lead, trail, self.extra[1 if font else 0], self.a9_row)

    def han_code(self, b: int) -> int:
        """``FUN_00181d10``: EUC code of an ASCII byte under ``$han1;``."""
        return 0xA1A1 if b < 0x20 or b >= 0x80 else self.han[b - 0x20]

    def glyph(self, text: bytes, i: int = 0, han: bool = True, font: int = 0) -> Glyph:
        """The character at ``text[i]`` as the width/print code reads it.
        Control bytes and '$' codes are the caller's business."""
        b = text[i]
        if b < 0x20:
            raise FontError(f"control byte {b:#04x}: not a character")
        if b < 0x80:
            if not han:
                return Glyph(1, "8x8", 0, None)
            code = self.han_code(b)
            return Glyph(1, "cell", code, self.cell(code >> 8, code & 0xFF, font))
        nxt = text[i + 1] if i + 1 < len(text) else 0
        if self.pair(b, nxt):
            # the euc gate does not test the trail: at the very end of the text the
            # game would read the terminator as the trail; here the code stops there
            return Glyph(2 if i + 1 < len(text) else 1, "cell", b << 8 | nxt, self.cell(b, nxt, font))
        trail = (b + 0x80) & 0xFF
        return Glyph(1, "cell", 0xA900 | trail, self.cell(0xA9, trail, font))

    def control_length(self, data: bytes, i: int) -> int:
        """Total bytes of the control sequence at ``data[i]`` (< 0x20), as the
        width function's main loop steps over it (``FUN_00182290`` called with
        the sequence start; the ruby skip calls it one byte later - see
        ``Measurer``)."""
        return self._ctl_len(data, i, i)

    def _ctl_len(self, data: bytes, i: int, base: int) -> int:
        c = data[i]
        n = self.ctl[c]
        if n != 0xFF:
            return 1 + n
        arg = data[base + 1] if base + 1 < len(data) else 0
        if c == 0x08:
            return 2 + sum(self.ctl08[k] for k in range(8) if arg >> k & 1)
        if c == 0x15:
            return 2 + arg
        raise FontError(f"control byte {c:#04x}: variable length, no rule known")

    def command_at(self, text: bytes, i: int) -> Tuple[str, Tuple[str, ...], int]:
        """``FUN_00184090``: the '$' command at ``text[i]``: (name, args, end).
        ``end`` is just past the ';'. The first table name that prefixes the
        text wins, as in the game. Raises when there is no match or no ';'."""
        if text[i:i + 1] != b"$":
            raise FontError("not a '$' command")
        rest = text[i + 1:]
        for name in self.commands:
            if rest.startswith(name.encode()):
                e = text.find(b";", i)
                if e < 0:
                    raise FontError(f"${name} without its ';' (the game reads on past the text)")
                body = text[i + 1 + len(name):e].decode("latin-1")
                return name, tuple(body.split(",")) if body else (), e + 1
        raise FontError(f"unknown $-command at byte {i}: {text[i:i + 8]!r}")

    def tokens(self, text: bytes, han: bool = False, font: int = 0) -> List[Token]:
        """Split a string into $-commands, control sequences and characters.
        ``han`` is the starting ``$han`` state; ``$han`` and control byte 0x19
        update it as the game does."""
        out, i, n = [], 0, len(text)
        flags = 2 if han else 0
        while i < n and text[i] != 0:
            b = text[i]
            if b == 0x24:
                name, args, e = self.command_at(text, i)
                if name == "han":
                    flags = (flags & ~2) | ((text[i + 4] & 1) << 1 if i + 4 < n else 0)
                out.append(Token("cmd", i, e, name, args))
                i = e
            elif b < 0x20:
                L = self.control_length(text, i)
                if b == 0x19 and i + 1 < n:
                    flags = text[i + 1]
                out.append(Token("ctrl", i, i + L))
                i += L
            else:
                g = self.glyph(text, i, bool(flags & 2), font)
                out.append(Token("char" if g.kind == "cell" else "8x8", i, i + g.length, cell=g.cell))
                i += g.length
        return out

    # -- cell -> what is drawn
    def is_prop(self, cell: int, prop: bool = True) -> bool:
        return prop and 0 <= cell < self.prop_cells

    def drawn_cell(self, cell: int, prop: bool = True) -> int:
        """The cell whose image is drawn: cell + 0x240 for a proportional glyph."""
        return cell + PROP_CELL_SHIFT if self.is_prop(cell, prop) else cell_index(cell)

    @staticmethod
    def glyph_width(cell: int, metrics: Sequence[Tuple[int, int]], xx1: int = 4, xx3: int = 0) -> int:
        """``FUN_00185770``: pixels for one proportional glyph (zoom 16, no ``$xx7``)."""
        if xx3:
            a = (xx3 & 0xFF) >> 1
            return 2 * (a or 5)
        if cell == 0:
            return (xx1 & 0xFF) + 1
        left, right = metrics[cell]
        return right - left + 3 if left else right + 2

    def advance(self, cell: int, metrics, prop: bool = True, xx1: int = 4) -> int:
        """Advance at zoom 16: proportional width, or 19 when fixed."""
        return self.glyph_width(cell, metrics, xx1) if self.is_prop(cell, prop) else FIXED_ADVANCE

    def measurer(self, metrics, prop: bool = False, han: bool = False, xx1: int = 4,
                 font: int = 0) -> "Measurer":
        return Measurer(self, metrics, prop=prop, han=han, xx1=xx1, font=font)

    def table(self, metrics: Sequence[Tuple[int, int]] = (), prop: bool = True, font: int = 0) -> List[dict]:
        """code -> cell rows: single bytes 0x20-0xFF (with ``$han1;``; on Japan up
        to 0x9F, which all draw 0x7F) and every two-byte code the gate accepts
        (trails A1-FE)."""
        rows = []

        def row(src, length, code, cell):
            ci = cell_index(cell)
            r = {"bytes": src, "length": length, "code": f"{code:04X}", "cell": ci,
                 "fixed_flag": int(bool(cell & FIXED_FLAG)), "sheet": ci >> 10,
                 "prop": int(self.is_prop(cell, prop)), "drawn_cell": self.drawn_cell(cell, prop),
                 "left": "", "right": "", "advance": FIXED_ADVANCE}
            if self.is_prop(cell, prop) and cell < len(metrics):
                r.update(left=metrics[cell][0], right=metrics[cell][1],
                         advance="$xx1+1" if cell == 0 else self.glyph_width(cell, metrics))
            elif self.is_prop(cell, prop):
                r["advance"] = ""
            rows.append(r)

        for b in range(0x20, 0x100):
            if self.gate == "euc" and b >= 0xA0:
                continue                          # euc gate: every byte from 0xA0 up is a lead
            g = self.glyph(bytes((b, 0)), 0, True, font)
            row(f"{b:02X}", 1, g.code, g.cell)
        for lead in range(0xA1, 0xFF):
            for trail in range(0xA1, 0xFF):
                if self.pair(lead, trail):
                    row(f"{lead:02X}{trail:02X}", 2, lead << 8 | trail, self.cell(lead, trail, font))
        return rows

    def clut_check(self) -> Tuple[int, int]:
        """(entries matching, 1024): CLUT k index i = white, alpha level of plane k."""
        if len(self.clut) != 1024:
            return 0, 1024
        ok = 0
        for k in range(4):
            ox, oy = (k & 1) * 16, (k >> 1) * 16
            for i in range(256):
                ii = (i & 0xE7) | ((i & 8) << 1) | ((i & 16) >> 1)      # CSM1 order
                v = self.clut[(oy + ii // 16) * 32 + ox + ii % 16]
                lvl = (i >> (2 * k)) & 3
                ok += (v >> 24) == CLUT_ALPHA[lvl] and (lvl == 0 or v & 0xFFFFFF == 0xFFFFFF)
        return ok, 1024


def _number(s: bytes, i: int) -> int:
    """``FUN_00183260``: optional sign, then decimal or 0x hex; 0 when absent."""
    sign = 1
    if i < len(s) and s[i] in b"+-":
        sign = -1 if s[i] == 0x2D else 1
        i += 1
    if s[i:i + 2] == b"0x":
        j = i + 2
        while j < len(s) and chr(s[j]) in "0123456789abcdefABCDEF":
            j += 1
        return sign * int(s[i + 2:j] or b"0", 16)
    j = i
    while j < len(s) and 0x30 <= s[j] <= 0x39:
        j += 1
    return sign * int(s[i:j] or b"0")


def _s8(v: int) -> int:
    v &= 0xFF
    return v - 256 if v >= 128 else v


class Measurer:
    """The pixel width of a string, as ``FUN_001828a0`` computes it.

    State the game keeps in globals (and that therefore carries from one call to
    the next here too): ``$prop`` / ``$han`` (flag bits 0 and 1 at 0x7E7E11,
    also set wholesale by control byte 0x19), ``$xx1,N`` (default width of cell
    0), ``$xx3,N`` (fixed-pitch mode), ``$xx7,N`` (signed extra spacing added to
    every character). Per call: ``$zoom`` (default 16; control byte 0x12 sets it
    too) and half-size mode (control byte 0x18).

    Per character: ASCII without ``$han`` = zoom px. Otherwise the cell's width
    (``Addressing.glyph_width``) when ``$prop`` is on and the cell is below
    ``prop_cells`` (0x180 USA, 0xC0 Japan), else 19; in half-size mode the cell goes through ``half_cell`` and
    is always measured proportionally. Then ``w += ((width + xx7) * zoom) >> 4``.
    ``$rubys; ... $rubye;`` is skipped (control bytes inside it are stepped over
    with the ruby skip's one-byte-late operand read, as the game does). A '$'
    code that is not one of these has no width. Control bytes have no width.
    """

    def __init__(self, a: Addressing, metrics: Sequence[Tuple[int, int]], prop: bool = False,
                 han: bool = False, xx1: int = 4, xx3: int = 0, xx7: int = 0, font: int = 0):
        self.a, self.metrics, self.font = a, metrics, font
        self.flags = (1 if prop else 0) | (2 if han else 0)
        self.xx1, self.xx3, self.xx7 = xx1 & 0xFF, xx3 & 0xFF, _s8(xx7)

    @property
    def prop(self) -> bool:
        return bool(self.flags & 1)

    @property
    def han(self) -> bool:
        return bool(self.flags & 2)

    def width(self, s: bytes, stop_at_space: bool = False) -> int:
        w, zoom, half = 0, 16, 0
        i, n = 0, len(s)
        a = self.a
        while i < n and s[i] != 0:
            c = s[i]
            if c == 0x24:                                           # '$'
                t = s[i + 1:i + 8]
                if t.startswith(b"prop") and i + 5 < n:
                    self.flags = (self.flags & ~1) | (s[i + 5] & 1)
                elif t.startswith(b"han") and i + 4 < n:
                    self.flags = (self.flags & ~2) | ((s[i + 4] & 1) << 1)
                elif t.startswith(b"xx1,"):
                    self.xx1 = _number(s, i + 5) & 0xFF
                elif t.startswith(b"xx3,"):
                    self.xx3 = _number(s, i + 5) & 0xFF
                elif t.startswith(b"xx7,"):
                    self.xx7 = _s8(_number(s, i + 5))
                elif t.startswith(b"rubys;"):
                    j = i + 7
                    while j < n and s[j] != 0:
                        if s[j:j + 7] == b"$rubye;":
                            i = j
                            break
                        j += a._ctl_len(s, j, j + 1) if s[j] < 0x20 else 1
                elif t.startswith(b"zoom"):
                    zoom = _number(s, i + 5)
                e = s.find(b";", i)
                if e < 0:
                    raise FontError("a '$' code without its ';' (the game would read on past the text)")
                i = e + 1
            elif c < 0x20:
                if c == 0x15 and i + 3 < n:
                    if s[i + 2] == 2:
                        self.xx1 = s[i + 3]
                    elif s[i + 2] == 4:
                        self.xx3 = s[i + 3]
                elif c == 0x12 and i + 1 < n:
                    zoom = _s8(s[i + 1])
                elif c == 0x18 and i + 1 < n:
                    half = _s8(s[i + 1])
                elif c == 0x19 and i + 1 < n:
                    self.flags = s[i + 1]
                i += a.control_length(s, i)
            else:
                if c < 0x80 and not self.han:
                    w += (zoom * 16) >> 4
                    i += 1
                else:
                    g = a.glyph(s, i, True, self.font)
                    i += g.length
                    cell = g.cell
                    if half:
                        adv = a.glyph_width(half_cell(cell), self.metrics, self.xx1, self.xx3)
                    elif self.prop and cell < a.prop_cells:
                        adv = a.glyph_width(cell, self.metrics, self.xx1, self.xx3)
                    else:
                        adv = FIXED_ADVANCE
                    w += ((adv + self.xx7) * zoom) >> 4
            if stop_at_space and i < n and s[i] == 0x20:
                break
        return w


# --- the file --------------------------------------------------------------

def _planes_to_sheets(raw: bytes) -> List[bytearray]:
    d = np.frombuffer(raw, np.uint8, METRICS_OFF).reshape(CELLS_PER_SHEET, CELL_H, CELL_W)
    out = []
    for k in range(SHEETS):
        p = (d >> (2 * k)) & 3
        out.append(bytearray(p.reshape(32, 32, CELL_H, CELL_W).transpose(0, 2, 1, 3).tobytes()))
    return out


def _sheets_to_planes(sheets: Sequence[Sequence[int]]) -> bytes:
    acc = np.zeros((CELLS_PER_SHEET, CELL_H, CELL_W), np.uint8)
    for k, sh in enumerate(sheets):
        a = np.frombuffer(bytes(sh), np.uint8).reshape(32, CELL_H, 32, CELL_W).transpose(0, 2, 1, 3)
        acc |= ((a & 3) << (2 * k)).reshape(CELLS_PER_SHEET, CELL_H, CELL_W).astype(np.uint8)
    return acc.tobytes()


class Font:
    def __init__(self, sheets: List[bytearray], metrics: List[Tuple[int, int]],
                 sys8x8: bytes = bytes(SYS_SIZE), tail: bytes = b""):
        if len(sheets) != SHEETS or any(len(s) != SHEET_W * SHEET_H for s in sheets):
            raise FontError("a font is four 640x768 sheets")
        if len(metrics) != METRIC_PAIRS or len(sys8x8) != SYS_SIZE:
            raise FontError("a font has 512 metric pairs and a 2,048-byte system font")
        self.sheets = sheets          # four 640*768 bytearrays, values 0..3
        self.metrics = metrics        # 512 (left, right), indexed by base cell
        self.sys8x8 = bytes(sys8x8)   # 1bpp, 512x32, MSB first
        self.tail = tail              # bytes past 0x78C00 (none on the discs)

    @classmethod
    def blank(cls) -> "Font":
        return cls([bytearray(SHEET_W * SHEET_H) for _ in range(SHEETS)], [(0, 0)] * METRIC_PAIRS)

    @classmethod
    def from_bytes(cls, data: bytes) -> "Font":
        if len(data) < FILE_SIZE:
            raise FontError(f"font file is {len(data)} bytes; Episode III fonts are {FILE_SIZE}")
        data = bytes(data)
        m = data[METRICS_OFF:SYS_OFF]
        metrics = [(m[2 * i], m[2 * i + 1]) for i in range(METRIC_PAIRS)]
        return cls(_planes_to_sheets(data), metrics, data[SYS_OFF:SYS_OFF + SYS_SIZE], data[FILE_SIZE:])

    @classmethod
    def load(cls, path) -> "Font":
        return cls.from_bytes(Path(path).read_bytes())

    def to_bytes(self) -> bytes:
        out = bytearray(_sheets_to_planes(self.sheets))
        for left, right in self.metrics:
            out += bytes((left & 0xFF, right & 0xFF))
        out += self.sys8x8
        out += self.tail
        return bytes(out)

    # cells
    @staticmethod
    def _xy(index: int) -> Tuple[int, int, int]:
        if not 0 <= index < CELL_COUNT:
            raise FontError(f"cell {index}: cells are 0..4095 (strip bit 0x1000 with cell_index)")
        i = index % CELLS_PER_SHEET
        return index // CELLS_PER_SHEET, (i % CELLS_PER_ROW) * CELL_W, (i // CELLS_PER_ROW) * CELL_H

    def cell(self, index: int) -> List[List[int]]:
        """24 rows of 20 values (0..3)."""
        s, x0, y0 = self._xy(index)
        sh = self.sheets[s]
        return [list(sh[(y0 + r) * SHEET_W + x0:(y0 + r) * SHEET_W + x0 + CELL_W]) for r in range(CELL_H)]

    def set_cell(self, index: int, rows: Sequence[Sequence[int]]) -> None:
        if len(rows) != CELL_H or any(len(r) != CELL_W for r in rows):
            raise FontError("cell must be 24 rows of 20 values")
        s, x0, y0 = self._xy(index)
        sh = self.sheets[s]
        for r in range(CELL_H):
            sh[(y0 + r) * SHEET_W + x0:(y0 + r) * SHEET_W + x0 + CELL_W] = bytes(v & 3 for v in rows[r])

    def ink_bounds(self, index: int) -> Optional[Tuple[int, int]]:
        cols = [c for c in range(CELL_W) if any(row[c] for row in self.cell(index))]
        return (cols[0], cols[-1]) if cols else None

    def set_metrics(self, slot: int, left: int, right: int) -> None:
        if not 0 <= slot < METRIC_PAIRS:
            raise FontError(f"metric slot {slot}: the table has {METRIC_PAIRS} pairs and cannot grow")
        if not (0 <= left <= 255 and 0 <= right <= 255):
            raise FontError(f"metric slot {slot}: left and right are bytes")
        self.metrics[slot] = (left, right)

    def metrics_check(self) -> Tuple[int, int]:
        """(pairs whose ink of cell + 0x240 equals the pair, pairs with left != 0)."""
        total = ok = 0
        for c, (l, r) in enumerate(self.metrics):
            if l and c + PROP_CELL_SHIFT < CELL_COUNT:
                total += 1
                ok += self.ink_bounds(c + PROP_CELL_SHIFT) == (l, r)
        return ok, total

    # the 8x8 system font
    def sys8x8_image(self) -> bytearray:
        """512x32, one byte per pixel (0 or 1)."""
        bits = np.unpackbits(np.frombuffer(self.sys8x8, np.uint8))     # MSB first
        return bytearray(bits.tobytes())

    def set_sys8x8_image(self, pixels: Sequence[int]) -> None:
        if len(pixels) != SYS_W * SYS_H:
            raise FontError("the system font image is 512x32")
        self.sys8x8 = np.packbits(np.frombuffer(bytes(1 if p else 0 for p in pixels), np.uint8)).tobytes()


# --- donor: copy cells + metrics between two Episode III fonts -----------------

KANJI_CELLS = range(1024, 3989)                # B0A1..CFD3: drawn identically by every build


def font_cells(f: "Font") -> np.ndarray:
    """(4096, 24, 20) view of a font's glyph cells, values 0..3."""
    a = np.frombuffer(b"".join(bytes(s) for s in f.sheets), np.uint8)
    return a.reshape(SHEETS, 32, CELL_H, 32, CELL_W).transpose(0, 1, 3, 2, 4).reshape(CELL_COUNT, CELL_H, CELL_W)


def kanji_agreement(a: "Font", b: "Font") -> int:
    """How many of the 2,965 kanji cells of two fonts differ by at most one
    grey level per pixel. The same font of two builds scores 2,964-2,965 (the
    Japanese font0 is re-anti-aliased, +-1 level); font0 against font1 scores 0."""
    ca, cb = font_cells(a)[KANJI_CELLS.start:KANJI_CELLS.stop], font_cells(b)[KANJI_CELLS.start:KANJI_CELLS.stop]
    d = np.abs(ca.astype(np.int16) - cb).reshape(len(KANJI_CELLS), -1).max(1)
    return int((d <= 1).sum())


def parse_cells(spec: str) -> List[int]:
    """'192-383,851,3989-4088' -> sorted unique cell numbers (0..4095)."""
    out = set()
    for part in spec.replace(" ", "").split(","):
        if not part:
            continue
        lo, _, hi = part.partition("-")
        try:
            a, b = int(lo, 0), int(hi or lo, 0)
        except ValueError:
            raise FontError(f"--cells: {part!r} is not N or N-M")
        if not (0 <= a <= b < CELL_COUNT):
            raise FontError(f"--cells: {part!r} is outside 0..{CELL_COUNT - 1}")
        out.update(range(a, b + 1))
    if not out:
        raise FontError("--cells: no cells given")
    return sorted(out)


def donate(src: "Font", dst: "Font", cells: Sequence[int], metrics: bool = True,
           prop_images: bool = False, force: bool = False) -> Tuple["Font", Dict[str, object]]:
    """A copy of ``dst`` with ``cells`` (and their metric pairs, for cells below
    512) taken from ``src``. ``prop_images`` also copies cell + 0x240 for every
    given cell below 384 (the proportional image on USA, the half-size image on
    Japan; the metric pairs 192-383 describe those images in both builds).

    The two fonts must be the same font (font0 with font0): at least 2,900 of the
    2,965 kanji cells must agree within one grey level, else this refuses
    (``force`` skips the check)."""
    agree = kanji_agreement(src, dst)
    if agree < 2900 and not force:
        raise FontError(f"only {agree}/{len(KANJI_CELLS)} kanji cells agree: not the same font of two builds "
                        f"(give font0 with font0, font1 with font1), or pass --force")
    new = Font([bytearray(s) for s in dst.sheets], list(dst.metrics), dst.sys8x8, dst.tail)
    todo = set(cells)
    if prop_images:
        todo |= {c + PROP_CELL_SHIFT for c in cells if c < PROP_LIMIT}
    changed = 0
    for c in sorted(todo):
        rows = src.cell(c)
        changed += rows != new.cell(c)
        new.set_cell(c, rows)
    m_changed = 0
    m_slots = [c for c in cells if c < METRIC_PAIRS] if metrics else []
    for c in m_slots:
        m_changed += new.metrics[c] != src.metrics[c]
        new.set_metrics(c, *src.metrics[c])
    return new, {"kanji_agree": agree, "cells_copied": len(todo), "cells_changed": changed,
                 "metric_pairs_copied": len(m_slots), "metric_pairs_changed": m_changed}

# --- PNG (grayscale, stdlib only) — copied from the XS2 kit; png_to_gray now also
# reads 1/2/4-bit and 16-bit PNGs ---------------------------------------------------

def _png_chunk(tag: bytes, payload: bytes) -> bytes:
    return (struct.pack(">I", len(payload)) + tag + payload
            + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF))


def gray_png(gray: Sequence[int], width: int, height: int) -> bytes:
    raw = bytearray()
    g = bytes(gray)
    for y in range(height):
        raw.append(0)
        raw += g[y * width:(y + 1) * width]
    return (b"\x89PNG\r\n\x1a\n"
            + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0))
            + _png_chunk(b"IDAT", zlib.compress(bytes(raw), 6))
            + _png_chunk(b"IEND", b""))


def sheet_to_png(sheet: Sequence[int], width: int = SHEET_W, height: int = SHEET_H) -> bytes:
    return gray_png(bytes(sheet).translate(bytes(GREY[i & 3] for i in range(256))), width, height)


def png_to_gray(data: bytes) -> Tuple[int, int, bytearray]:
    """Decode a non-interlaced PNG (gray, gray+alpha, RGB, RGBA or palette;
    1/2/4/8-bit gray and palette, 8/16-bit otherwise; a 4-colour sheet saved
    at 2 bits by GIMP or Pillow included) to (width, height, gray bytes).
    16-bit samples are cut to their high byte. Transparency counts as
    background. Chunk lengths and CRCs are checked."""
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise FontError("not a PNG file")
    pos, idat, plte, trns = 8, bytearray(), b"", b""
    width = height = ctype = 0
    ended = False
    while pos < len(data):
        if pos + 12 > len(data):
            raise FontError("PNG cut off inside a chunk header")
        (ln,) = struct.unpack_from(">I", data, pos)
        tag = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + ln]
        if pos + 12 + ln > len(data):
            raise FontError(f"PNG chunk {tag!r} runs past the end of the file")
        if struct.unpack_from(">I", data, pos + 8 + ln)[0] != zlib.crc32(tag + body) & 0xFFFFFFFF:
            raise FontError(f"PNG chunk {tag!r} fails its CRC")
        if tag == b"tRNS":
            trns = body
        if tag == b"IHDR":
            width, height, depth, ctype, _, _, inter = struct.unpack(">IIBBBBB", body)
            if inter:
                raise FontError("PNG must be non-interlaced (save it without Adam7 interlacing)")
            if depth not in ({0: (1, 2, 4, 8, 16), 3: (1, 2, 4, 8)}.get(ctype, (8, 16))):
                raise FontError(f"PNG bit depth {depth} is not valid for colour type {ctype}")
        elif tag == b"PLTE":
            plte = body
        elif tag == b"IDAT":
            idat += body
        elif tag == b"IEND":
            ended = True
            break
        pos += 12 + ln
    if not ended or not width or ctype not in (0, 2, 3, 4, 6):
        raise FontError("PNG without IHDR/IEND or of an unsupported colour type")
    chans = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[ctype]
    bpp = max(1, chans * depth // 8)              # filter unit, in bytes
    try:
        raw = zlib.decompress(bytes(idat))
    except zlib.error as e:
        raise FontError(f"PNG image data does not decompress: {e}")
    stride = (width * chans * depth + 7) // 8
    if len(raw) != height * (stride + 1):
        raise FontError("PNG image data has the wrong length")
    prev = bytearray(stride)
    gray = bytearray(width * height)
    p = 0
    for y in range(height):
        f = raw[p]
        line = bytearray(raw[p + 1:p + 1 + stride])
        p += 1 + stride
        if f == 1:
            for i in range(bpp, stride):
                line[i] = (line[i] + line[i - bpp]) & 0xFF
        elif f == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif f == 3:
            for i in range(stride):
                a = line[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + ((a + prev[i]) >> 1)) & 0xFF
        elif f == 4:
            for i in range(stride):
                a = line[i - bpp] if i >= bpp else 0
                b = prev[i]
                c = prev[i - bpp] if i >= bpp else 0
                pa, pb, pc = abs(b - c), abs(a - c), abs(a + b - 2 * c)
                pred = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + pred) & 0xFF
        elif f != 0:
            raise FontError(f"bad PNG filter {f}")
        prev = line
        if depth < 8:                             # unpack to one sample per byte
            per, mask = 8 // depth, (1 << depth) - 1
            line = bytearray((line[x // per] >> (8 - depth * (x % per + 1))) & mask
                             for x in range(width))
            if ctype == 0:                        # scale gray to 0..255
                line = bytearray(v * 255 // mask for v in line)
        elif depth == 16:                         # keep the high byte of each sample
            line = line[0::2]
        row = y * width
        if ctype == 3:
            for x in range(width):
                i = line[x] * 3
                if i + 2 >= len(plte):
                    raise FontError("PNG palette index out of range")
                g = (plte[i] * 299 + plte[i + 1] * 587 + plte[i + 2] * 114) // 1000
                a = trns[line[x]] if line[x] < len(trns) else 255
                gray[row + x] = g * a // 255
        elif chans == 1:
            gray[row:row + width] = line
        else:
            for x in range(width):
                i = x * chans
                if chans == 2:
                    gray[row + x] = line[i] * line[i + 1] // 255
                else:
                    g = (line[i] * 299 + line[i + 1] * 587 + line[i + 2] * 114) // 1000
                    gray[row + x] = g * line[i + 3] // 255 if chans == 4 else g
    return width, height, gray


def quantize(gray: Sequence[int]) -> bytearray:
    """8-bit gray -> 4 levels (thresholds between the 0/85/170/255 steps)."""
    lut = bytes(0 if g <= 42 else 1 if g <= 127 else 2 if g <= 212 else 3 for g in range(256))
    return bytearray(bytes(gray).translate(lut))


# --- disc access -----------------------------------------------------------------

def _open_iso(iso_path):
    from iso9660 import IsoImage
    return IsoImage(iso_path)


def read_boot_exe(iso_path) -> bytes:
    """The boot executable named by SYSTEM.CNF (SLUS_213.89 / SLUS_214.17)."""
    with _open_iso(iso_path) as im:
        name = im.boot_elf_name()
        if not name:
            raise FontError(f"{iso_path}: no boot executable found")
        return bytes(im.read_file(name))


def read_disc_file(iso_path, discpath: str) -> bytes:
    """A file by in-game path, found through the disc's own index (``disc.Disc``:
    chain 0 first, then the disc's X3.10 / X3.20 chain), so it works on the
    prototype and on the Japanese discs too."""
    from disc import Disc, DiscError
    with Disc(iso_path) as d:
        try:
            return d.read(discpath)
        except (DiscError, FileNotFoundError, KeyError) as e:
            raise FontError(f"{discpath}: not on this disc ({e})")


def disc_lang(iso_path, exe: Optional[bytes] = None) -> str:
    """The font folder of the build on the disc (``us`` or ``jp``), from the
    executable's profile."""
    return profile_for(exe if exe is not None else read_boot_exe(iso_path)).font_dir


def read_fonts(iso_path, lang: Optional[str] = None) -> Tuple[bytes, bytes]:
    """``mnu\\<lang>\\font0.bin`` and ``font1.bin``; ``lang`` from the executable's
    profile when not given."""
    paths = font_paths(lang or disc_lang(iso_path))
    return read_disc_file(iso_path, paths[0]), read_disc_file(iso_path, paths[1])


# --- CLI -------------------------------------------------------------------

def write_table(path: Path, a: Addressing, font: Optional[Font], font_no: int = 0) -> int:
    fields = ["mode", "bytes", "length", "code", "cell", "fixed_flag", "sheet", "prop", "drawn_cell",
              "left", "right", "advance"]
    n = 0
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for prop in (True, False):
            for row in a.table(font.metrics if font else (), prop=prop, font=font_no):
                w.writerow(dict(row, mode="han1 prop1" if prop else "han1 prop0"))
                n += 1
    return n


def extract_font(data: bytes, stem: str, outp: Path) -> Font:
    font = Font.from_bytes(data)
    outp.mkdir(parents=True, exist_ok=True)
    (outp / f"{stem}.bin").write_bytes(data)
    for i, sheet in enumerate(font.sheets):
        (outp / f"{stem}_sheet{i}.png").write_bytes(sheet_to_png(sheet))
    with open(outp / f"{stem}_metrics.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["slot", "drawn_cell", "left", "right"])     # slot = base cell; image = cell + 576
        for slot, (l, r) in enumerate(font.metrics):
            w.writerow([slot, slot + PROP_CELL_SHIFT, l, r])
    (outp / f"{stem}_sys8x8.png").write_bytes(
        gray_png(bytes(font.sys8x8_image()).translate(bytes([0, 255] + [255] * 254)), SYS_W, SYS_H))
    return font


def cmd_extract(iso: str, out: str) -> int:
    outp = Path(out)
    exe = read_boot_exe(iso)
    a = Addressing.from_executable(exe)
    paths = font_paths(a.font_dir)
    for k, data in enumerate(read_fonts(iso, a.font_dir)):
        stem = f"font{k}"
        font = extract_font(data, stem, outp)
        rows = write_table(outp / f"{stem}_codes.csv", a, font, k)
        ok, tot = font.metrics_check()
        print(f"{paths[k]} ({a.profile}: gate {a.gate}, prop cells < {a.prop_cells}): 4 sheets, 512 metric pairs ({ok}/{tot} match the ink), sys8x8, "
              f"{rows} code rows -> {outp}")
    return 0


def cmd_rebuild(ref: str, sheets_dir: str, out: str, metrics_csv: Optional[str] = None,
                sys_png: Optional[str] = None, allow_unchanged: bool = False) -> int:
    """Rebuild from a reference .bin, the ``<stem>_sheetN.png`` found in
    ``sheets_dir``, an optional metrics CSV and an optional sys8x8 PNG."""
    if Path(out).resolve() == Path(ref).resolve():
        raise FontError(f"--out {out} is the reference file itself; give another name")
    data = Path(ref).read_bytes()
    font = Font.from_bytes(data)
    stem = Path(ref).stem
    names = [f"{stem}_sheet{i}.png" for i in range(SHEETS)]
    applied, changed = [], []
    for i, name in enumerate(names):
        p = Path(sheets_dir) / name
        if not p.exists():
            continue
        w, h, gray = png_to_gray(p.read_bytes())
        if (w, h) != (SHEET_W, SHEET_H):
            raise FontError(f"{p}: sheet must be {SHEET_W}x{SHEET_H}, got {w}x{h}")
        new = quantize(gray)
        if new != font.sheets[i]:
            changed.append(i)
        font.sheets[i] = new
        applied.append(i)
    n_rows = n_changed = 0
    if metrics_csv:
        seen = set()
        with open(metrics_csv, newline="") as fh:
            for row in csv.DictReader(fh):
                try:
                    slot, left, right = int(row["slot"]), int(row["left"]), int(row["right"])
                except (KeyError, TypeError, ValueError):
                    raise FontError(f"{metrics_csv}: a row without whole-number slot, left and right: {dict(row)}")
                if slot in seen:
                    raise FontError(f"{metrics_csv}: slot {slot} appears twice")
                seen.add(slot)
                n_rows += 1
                n_changed += 0 <= slot < METRIC_PAIRS and font.metrics[slot] != (left, right)
                font.set_metrics(slot, left, right)
    sys_applied = False
    if sys_png:
        w, h, gray = png_to_gray(Path(sys_png).read_bytes())
        if (w, h) != (SYS_W, SYS_H):
            raise FontError(f"{sys_png}: the system font image must be {SYS_W}x{SYS_H}, got {w}x{h}")
        font.set_sys8x8_image([g > 127 for g in gray])
        sys_applied = True
    if not applied and not n_rows and not sys_applied and not allow_unchanged:
        raise FontError(f"nothing to apply: none of {', '.join(names)} is in {sheets_dir} and no metrics or "
                        f"sys8x8 were given. Pass --allow-unchanged to write a plain copy of the reference")
    blob = font.to_bytes()
    if len(blob) != len(data):
        raise FontError(f"rebuilt font is {len(blob)} bytes, the original {len(data)}")
    Path(out).write_bytes(blob)
    print(f"applied: sheets {applied or 'none'} ({len(changed)} differ: {changed or 'none'}); "
          f"metrics rows {n_rows} ({n_changed} changed); sys8x8 {'yes' if sys_applied else 'no'}")
    print(f"wrote {out}" + (" (identical to the reference)" if blob == data else ""))
    return 0


def parse_text_arg(text: str) -> bytes:
    r"""cp1252 text with ``\xNN`` escapes for raw bytes (``$`` codes are literal)."""
    out, i = bytearray(), 0
    while i < len(text):
        if text.startswith("\\x", i) and i + 4 <= len(text):
            try:
                out.append(int(text[i + 2:i + 4], 16))
                i += 4
                continue
            except ValueError:
                pass
        try:
            out += text[i].encode("cp1252")
        except UnicodeEncodeError:
            raise FontError(f"{text[i]!r} has no cp1252 byte; give it as \\xNN")
        i += 1
    return bytes(out)


def cmd_measure(iso: str, text: str, prop: bool, han: bool, font_no: int) -> int:
    a = Addressing.from_iso(iso)
    font = Font.from_bytes(read_disc_file(iso, font_paths(a.font_dir)[font_no]))
    s = parse_text_arg(text)
    m = a.measurer(font.metrics, prop=prop, han=han, font=font_no)
    print(f"{m.width(s)} px  ({len(s)} bytes, {a.profile} profile, font{font_no}; "
          f"state after: prop={int(m.prop)} han={int(m.han)} xx1={m.xx1} xx3={m.xx3} xx7={m.xx7})")
    return 0


def _donor_font(iso: Optional[str], path: Optional[str], k: int, what: str) -> Tuple[Font, str]:
    if path:
        return Font.load(path), path
    if not iso:
        raise FontError(f"give --{what} ISO or --{what}-font{k} FILE")
    exe = read_boot_exe(iso)
    lang = profile_for(exe).font_dir
    p = font_paths(lang)[k]
    return Font.from_bytes(read_disc_file(iso, p)), f"{iso}:{p}"


def retail_cells(iso: str) -> Dict[int, int]:
    """{cell: hits} of every cell the retail text of ``iso`` draws under its own
    addressing (``glyphs.scan_retail``: .sb/.txd/mnu .bin strings, subtitles, .mes,
    batdat/Message.Dat runs, the boot ELF and overlays). A proportional image
    (cell + 0x240, cells 576-959) counts for its base cell too."""
    import glyphs
    from disc import Disc
    exe = read_boot_exe(iso)
    if glyphs.applied_unlock(exe) != "none":
        exe = unpatched(exe)                    # retail text is read under the retail rules
    a = Addressing.from_executable(exe)
    with Disc(iso) as d:
        scan = glyphs.scan_retail(d, a)
    out: Dict[int, int] = {}
    for c, n in scan.cells.items():
        out[c] = out.get(c, 0) + n
        if PROP_CELL_SHIFT <= c < PROP_CELL_SHIFT + PROP_LIMIT:
            out[c - PROP_CELL_SHIFT] = out.get(c - PROP_CELL_SHIFT, 0) + n
    return out


def cmd_donor(a) -> int:
    """Copy cells (+ metrics) from one Episode III font into another; writes
    ``fontK.bin`` and ``donor.json`` into --out (never onto a disc). Cells that
    the receiving disc's retail text draws are refused unless --allow-used (on
    USA, cells 256-383 are cp1252 0x80-0xFF: e.g. 361 = é in "Café", 374 = ö in
    "Möbius", 302 = ®; a Japanese kana there would replace them)."""
    import json
    cells = parse_cells(a.cells)
    if a.to_iso:
        used = retail_cells(a.to_iso)
        hit = [c for c in cells if c in used]
        if hit and not a.allow_used:
            ex = ", ".join(f"{c} ({used[c]}x)" for c in sorted(hit, key=lambda c: -used[c])[:8])
            raise FontError(f"{len(hit)} of the given cells are drawn by the retail text of {a.to_iso} "
                            f"(e.g. {ex}); donating them would change that text's glyphs and widths. "
                            f"Give only free cells (glyphs-slots lists them), or pass --allow-used")
        if hit:
            print(f"warning: --allow-used: {len(hit)} cells drawn by retail text are overwritten", file=sys.stderr)
    else:
        print("warning: no --to disc given, so whether retail text draws these cells is not checked",
              file=sys.stderr)
    if a.from_iso and a.to_iso and not a.force:
        src_p, dst_p = profile_for(read_boot_exe(a.from_iso)), profile_for(read_boot_exe(a.to_iso))
        if src_p.name == dst_p.name:
            raise FontError(f"--from and --to are both {src_p.name} builds; nothing to donate")
    outp = Path(a.out)
    outp.mkdir(parents=True, exist_ok=True)
    report = {"cells": a.cells, "metrics": not a.no_metrics, "prop_images": a.prop_images,
              "allow_used": bool(a.allow_used), "fonts": {}}
    for k in ((0, 1) if a.font == "both" else (int(a.font),)):
        src, src_name = _donor_font(a.from_iso, getattr(a, f"from_font{k}"), k, "from")
        dst, dst_name = _donor_font(a.to_iso, getattr(a, f"to_font{k}"), k, "to")
        new, rep = donate(src, dst, cells, metrics=not a.no_metrics, prop_images=a.prop_images, force=a.force)
        out = outp / f"font{k}.bin"
        blob = new.to_bytes()
        out.write_bytes(blob)
        rep.update(src=src_name, dst=dst_name, out=str(out), sha1=hashlib.sha1(blob).hexdigest())
        report["fonts"][f"font{k}"] = rep
        print(f"font{k}: kanji agree {rep['kanji_agree']}/{len(KANJI_CELLS)}; cells copied {rep['cells_copied']} "
              f"({rep['cells_changed']} changed); metric pairs {rep['metric_pairs_copied']} "
              f"({rep['metric_pairs_changed']} changed) -> {out}")
    (outp / "donor.json").write_text(json.dumps(report, indent=1))
    return 0


def _wrap(fn):
    def run(a):
        try:
            return fn(a)
        except FontError as e:
            print(f"refused: {e}", file=sys.stderr)
            return 1
    return run


def add_commands(subparsers) -> None:
    p = subparsers.add_parser("font-extract", help="font0/font1.bin -> sheet PNGs, metrics CSV, sys8x8 PNG, code table")
    p.add_argument("--iso", required=True)
    p.add_argument("--out", required=True)
    p.set_defaults(func=_wrap(lambda a: cmd_extract(a.iso, a.out)))

    p = subparsers.add_parser("font-rebuild", help="rebuild a font .bin from edited sheets / metrics / sys8x8")
    p.add_argument("--ref", required=True, help="the font .bin to start from (font-extract writes a copy)")
    p.add_argument("--sheets", required=True, help="directory with <ref stem>_sheet0..3.png")
    p.add_argument("--metrics", help="edited metrics CSV (slot,left,right)")
    p.add_argument("--sys8x8", help="edited 512x32 system font PNG")
    p.add_argument("--allow-unchanged", action="store_true", help="write a plain copy when nothing was found")
    p.add_argument("--out", required=True)
    p.set_defaults(func=_wrap(lambda a: cmd_rebuild(a.ref, a.sheets, a.out, a.metrics, a.sys8x8,
                                                    a.allow_unchanged)))

    p = subparsers.add_parser("font-measure", help="pixel width of a string as the game measures it")
    p.add_argument("--iso", required=True)
    p.add_argument("--text", required=True, help="cp1252 text; \\xNN for raw bytes; $codes literal")
    p.add_argument("--prop", action="store_true", help="start with $prop1 in effect")
    p.add_argument("--han", action="store_true", help="start with $han1 in effect")
    p.add_argument("--font", type=int, choices=(0, 1), default=0)
    p.set_defaults(func=_wrap(lambda a: cmd_measure(a.iso, a.text, a.prop, a.han, a.font)))

    p = subparsers.add_parser("font-donor", help="copy glyph cells (+ metrics) from one Episode III font into "
                                                 "another (e.g. Japan glyphs into free USA cells); cells the "
                                                 "receiving disc's retail text draws are refused")
    p.add_argument("--from", dest="from_iso", help="donor disc (e.g. the XS3 Japan disc)")
    p.add_argument("--to", dest="to_iso", help="receiving disc (e.g. the USA disc)")
    for k in (0, 1):
        p.add_argument(f"--from-font{k}", help=f"donor font{k}.bin instead of --from")
        p.add_argument(f"--to-font{k}", help=f"receiving font{k}.bin instead of --to")
    p.add_argument("--cells", required=True, help="cells to copy: N, N-M, comma-separated (e.g. 192-383)")
    p.add_argument("--font", choices=("0", "1", "both"), default="both")
    p.add_argument("--no-metrics", action="store_true", help="do not copy the metric pairs of cells < 512")
    p.add_argument("--prop-images", action="store_true",
                   help="also copy cell+576 for cells < 384 (USA proportional / Japan half-size images)")
    p.add_argument("--force", action="store_true", help="skip the same-font (kanji agreement) check")
    p.add_argument("--allow-used", action="store_true",
                   help="also overwrite cells the --to disc's retail text draws (on USA, 256-383 = cp1252 "
                        "accents and symbols such as é ö ®)")
    p.add_argument("--out", required=True, help="directory for font0.bin / font1.bin / donor.json")
    p.set_defaults(func=_wrap(cmd_donor))


# --- self-test -----------------------------------------------------------------

def _synthetic_elf(prof: Profile, extra0=(), extra1=(), gate: str = "whitelist", prop: int = PROP_LIMIT,
                   a9_row: bool = True) -> bytes:
    """A tiny ELF whose data segment holds synthetic tables at ``prof``'s VAs and,
    when the profile names code VAs, a text segment with the gate words, the two
    prop-gate immediates, a cell function that loads the jump table, and the
    half-size map."""
    vas = [prof.han_va, prof.extra_va[0], prof.extra_va[1], prof.ctl_va, prof.ctl08_va, prof.cmd_va]
    if prof.jump_va is not None:
        vas.append(prof.jump_va)
    seg_va = min(vas) & ~0xFFF
    seg = bytearray(max(vas) + 0x400 - seg_va)
    codes = [0xA300 | (c + 0x80) if chr(c).isalnum() else 0xA1A1 + (c - 0x20) % 94 for c in range(0x20, 0x80)]
    struct.pack_into("<96H", seg, prof.han_va + 0x40 - seg_va, *codes)
    for va, lst in ((prof.extra_va[0], extra0), (prof.extra_va[1], extra1)):
        for i, (x, y) in enumerate(lst):
            seg[va - seg_va + 2 * i:va - seg_va + 2 * i + 2] = bytes((x, y))
    ctl = [0, 1, 1, 1, 1, 1, 3, 0, 255, 0, 0, 0, 3, 1, 5, 3, 5, 6, 2, 2, 0, 255, 4, 7, 1, 1, 0, 1, 0, 0, 0, 0]
    seg[prof.ctl_va - seg_va:prof.ctl_va - seg_va + 32] = bytes(ctl)
    seg[prof.ctl08_va - seg_va:prof.ctl08_va - seg_va + 8] = bytes((2, 2, 3, 2, 2, 0, 0, 0))
    strs = prof.cmd_va + 8 * (len(CMD_NAMES) + 1)
    for k, nm in enumerate(CMD_NAMES):
        struct.pack_into("<II", seg, prof.cmd_va - seg_va + 8 * k, strs, 0x100000)
        seg[strs - seg_va:strs - seg_va + len(nm)] = nm.encode()
        strs += 8
    segs = [(seg_va, seg)]
    if prof.gate_va is not None:
        jt = [0x184000 + 0x40 * k for k in range(13)]
        jt[9] = jt[10] = jt[11] = 0x1849B4
        if not a9_row:
            jt[8] = jt[9]
        struct.pack_into("<13I", seg, prof.jump_va - seg_va, *jt)
        cvas = [prof.gate_va, prof.cell_fn_va, prof.half_va, *prof.prop_imm_va]
        t_va = min(cvas) & ~0xFFF
        text = bytearray(max(cvas) + 0x200 - t_va)
        text[prof.gate_va - t_va:prof.gate_va - t_va + 16] = GATE_EUC_WORDS if gate == "euc" else GATE_US_HEAD
        for va, op in zip(prof.prop_imm_va, (0x2E220000, 0x28820000)):
            struct.pack_into("<I", text, va - t_va, op | prop)
        hi, lo = (prof.jump_va + 0x8000) >> 16, prof.jump_va & 0xFFFF
        struct.pack_into("<3I", text, prof.cell_fn_va - t_va, 0x308400FF, 0x3C030000 | hi, 0x24630000 | lo)
        text[prof.half_va - t_va:prof.half_va - t_va + len(HALF_FN_CODE)] = HALF_FN_CODE
        segs.insert(0, (t_va, text))
    head = bytearray(0x34)
    head[:6] = b"\x7fELF\x01\x01"
    struct.pack_into("<I", head, 0x1C, 0x34)
    struct.pack_into("<HH", head, 0x2A, 32, len(segs))
    off, phs, body = 0x1000, b"", b""
    for va, data in segs:
        phs += struct.pack("<8I", 1, off + len(body), va, va, len(data), len(data), 6, 0x1000)
        body += bytes(data) + bytes(-len(data) % 0x1000)
    return bytes(head) + phs + bytes(off - 0x34 - len(phs)) + body


def self_test() -> int:
    import contextlib
    import io
    import tempfile
    ok = True

    def check(cond, msg):
        nonlocal ok
        print(("ok    " if cond else "FAIL  ") + msg)
        ok &= bool(cond)

    # code -> cell (FUN_00184938)
    check(xs3_cell(0xB0, 0xA1) == 1024 and xs3_cell(0xCF, 0xD3) == 3988, "kanji: B0A1 -> 1024, CFD3 -> 3988")
    check(xs3_cell(0xA3, 0xC1) == 138 and xs3_cell(0xA3, 0xB0) == 128 and xs3_cell(0xA3, 0xE1) == 164,
          "row A3: A -> 138, 0 -> 128, a -> 164")
    check(xs3_cell(0xA1, 0xA1) == 0 and xs3_cell(0xA1, 0xB9) == 0x1018 and xs3_cell(0xA1, 0xBC) == 0x101B
          and xs3_cell(0xA1, 0xF9) == 0x1058 and xs3_cell(0xA1, 0xF8) == 0x57, "row A1: 0x1000 on B9, BC, F9+")
    check(xs3_cell(0xA2, 0xA2) == 0x105F and xs3_cell(0xA2, 0xE0) == 0x6C and xs3_cell(0xA2, 0xF6) == 0x7B
          and xs3_cell(0xA2, 0xB0) == FALLBACK_CELL, "row A2: A0 group fixed-width (0x105D+), E0/F0, else 0x7F")
    check(xs3_cell(0xA4, 0xA1) == 192 and xs3_cell(0xA5, 0xA1) == 288 and xs3_cell(0xA9, 0x69) == 361
          and xs3_cell(0xAD, 0xB5) == 564 and xs3_cell(0xAA, 0xA1) == FALLBACK_CELL, "rows A4, A5, A9, AD; AA falls back")
    check(xs3_cell(0xA7, 0xCF) == 0x1DE and xs3_cell(0xA7, 0xD0) == 0x1D0 and xs3_cell(0xA6, 0xC1) == 0x198,
          "rows A6/A7")
    ex = ((0xD0, 0xBC), (0xD7, 0xFC))
    check(xs3_cell(0xD7, 0xFC, ex) == 3990 and xs3_cell(0xD7, 0xFD, ex) == FALLBACK_CELL, "extra kanji: 0xF95 + index")
    # gate
    check(pair_gate(0xA4, 0x01) and not pair_gate(0xA4, 0) and pair_gate(0xA6, 0xC0) and not pair_gate(0xA5, 0xA1)
          and not pair_gate(0xB0, 0xA1), "gate: A4/A6 any trail, A5 and kanji leads are not pairs")
    check([t for t in range(0xA1, 0xFF) if pair_gate(0xA1, t)] == [0xBD, 0xDA, 0xDB, 0xDF, 0xEE, 0xF9, 0xFA, 0xFB, 0xFC]
          and [t for t in range(0xA1, 0xFF) if pair_gate(0xA2, t)] == [0xA2, 0xA3, 0xA4, 0xA5, 0xA6, 0xAA, 0xAB, 0xAC, 0xAD, 0xF6]
          and [t for t in range(0x01, 0x100) if pair_gate(0xAD, t)] == [0xB5, 0xB6, 0xB7], "gate: A1, A2, AD sets")
    check(half_cell(0x100) == 0x100 and half_cell(0) == 0 and half_cell(5) == 0x17E and half_cell(0x1B) == 0x17D
          and half_cell(0x8A) == 0x11D and half_cell(0x400) == 0x17F, "half-size remap (FUN_00181db8)")

    # PNG reader: 2-bit palette (GIMP/Pillow 4-level save), 2-bit gray, 16-bit gray
    lv = [0, 85, 170, 255] * 5 + [255, 0, 170]          # 23 px, odd width
    def png(depth, ctype, rowbytes, plte=b""):
        return (b"\x89PNG\r\n\x1a\n" + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", 23, 1, depth, ctype, 0, 0, 0))
                + (_png_chunk(b"PLTE", plte) if plte else b"")
                + _png_chunk(b"IDAT", zlib.compress(b"\0" + rowbytes)) + _png_chunk(b"IEND", b""))
    idx = [lv.index(v) if v in lv[:4] else 0 for v in lv]
    two = bytes(sum(i << (6 - 2 * k) for k, i in enumerate(idx[j:j + 4] + [0] * (4 - len(idx[j:j + 4]))))
                for j in range(0, 23, 4))
    pal = b"".join(bytes((v, v, v)) for v in (0, 85, 170, 255))
    sixteen = b"".join(struct.pack(">H", v * 257) for v in lv)
    got = [png_to_gray(png(2, 3, two, pal))[2], png_to_gray(png(2, 0, two))[2], png_to_gray(png(16, 0, sixteen))[2]]
    check(all(bytes(quantize(g)) == bytes(quantize(lv)) for g in got),
          "PNG reader: 2-bit palette, 2-bit gray and 16-bit gray sheets read as 8-bit")

    # synthetic executable
    import dataclasses
    prof = dataclasses.replace(PROFILES["def4d42429001ca86111c6fa86dc84bdeb9a93c4"], clut_va=0)
    elf = _synthetic_elf(prof, ex, ex[:1])
    a = Addressing.from_executable(elf, prof)
    check(a.extra[0] == ex and a.extra[1] == ex[:1] and a.ctl[0x17] == 7 and a.commands == CMD_NAMES,
          "tables read from a synthetic ELF by VA through its program headers")
    try:
        profile_for(elf)
        check(False, "unknown executable refused")
    except FontError:
        check(True, "an unknown executable is refused by profile_for")
    check(a.glyph(b"A") == Glyph(1, "cell", 0xA3C1, 138) and a.glyph(b"A", han=False).kind == "8x8"
          and a.glyph(b"\xe9x") == Glyph(1, "cell", 0xA969, 361) and a.glyph(b"\xa4\xa2").length == 2
          and a.glyph(b"\xa4").length == 1, "glyph: han ASCII, 8x8, Latin byte, A4 pair, lone A4")
    check(a.control_length(b"\x06abc", 0) == 4 and a.control_length(b"\x08\x05\0\0\0\0\0\0", 0) == 2 + 2 + 3
          and a.control_length(b"\x15\x02\x02\x09", 0) == 4 and a.control_length(b"\x0d\x0a", 0) == 2,
          "control lengths: fixed, 08 flag bits, 15 length byte, CR LF")
    check(a.command_at(b"$zoom24,16;x", 0) == ("zoom", ("24", "16"), 11)
          and a.command_at(b"$rubys;", 0)[0] == "ruby", "$-commands: first prefix match, args split at ','")
    toks = a.tokens(b"$han1;A\x0d\x0a\xe9")
    check([t.kind for t in toks] == ["cmd", "char", "ctrl", "char"] and toks[1].cell == 138, "tokens")
    # metrics + measurer
    f = Font.blank()
    for c in range(METRIC_PAIRS):
        f.metrics[c] = (4, 4 + c % 12)
    f.metrics[0] = (0, 0)
    f.metrics[200] = (0, 9)
    wa = (4 + 138 % 12) - 4 + 3
    m = a.measurer(f.metrics, prop=True, han=True, xx1=8)
    check(m.width(b"AA") == 2 * wa and m.width(b"$col808080;A") == wa, "width: proportional, $-codes have none")
    check(m.width(b" ") == 9 if a.han_code(0x20) == 0xA1A1 else True, "width: cell 0 is $xx1 + 1")
    check(a.glyph_width(200, f.metrics) == 11, "width: left 0 -> right + 2")
    check(m.width(b"$zoom32;A") == 2 * wa and m.width(b"A") == wa, "width: $zoom is per call")
    check(m.width(b"$xx7,2;A") == wa + 2 and m.width(b"A") == wa + 2 and m.width(b"$xx7,0;A") == wa,
          "width: $xx7 is global extra spacing")
    check(m.width(b"$xx3,1;A") == 10 and m.width(b"$xx3,6;A") == 6 and m.width(b"$xx3,0;A") == wa,
          "width: $xx3 fixed pitch = 2*(N>>1) or 10")
    check(m.width(b"$prop0;A") == 19 and m.width(b"A") == 19 and m.width(b"$prop1;A") == wa, "width: $prop carries")
    check(m.width(b"\xa1\xf9") == 19 and a.glyph(b"\xa1\xb9").length == 1, "width: a 0x1000-flagged code (A1F9) is fixed width; A1B9 is not a pair")
    check(m.width(b"$han0;AB") == 32 and m.width(b"$han1;A") == wa, "width: ASCII without $han = zoom px")
    check(m.width(b"A$rubys;AAAA$rubye;A") == 2 * wa, "width: ruby reading skipped")
    check(m.width(b"\x12\x20\x00A") == 2 * wa and m.width(b"\x19\x00A") == 16 and m.width(b"\x19\x03A") == wa,
          "width: control 0x12 zoom, 0x19 flags")
    check(m.width(b"AB CD", stop_at_space=True) == m.width(b"AB"), "width: stop at space")
    try:
        m.width(b"$zoom13")
        check(False, "a $ code without ';' is refused")
    except FontError:
        check(True, "a $ code without ';' is refused")

    check((a.gate, a.prop_cells, a.a9_row) == ("whitelist", 0x180, True),
          "rules read from synthetic USA code: whitelist gate, prop < 0x180, A9 row")
    # the Japanese rules, from a synthetic executable laid out at the JP profile's VAs
    pj = dataclasses.replace(PROFILES["e8125f743e0e7fda0ec392ea845dd0069470af3b"], clut_va=0)
    aj = Addressing.from_executable(_synthetic_elf(pj, ex, ex[:1], gate="euc", prop=0xC0, a9_row=False), pj)
    check((aj.gate, aj.prop_cells, aj.a9_row, aj.latin1_singles, aj.font_dir) == ("euc", 0xC0, False, False, "jp"),
          "rules read from synthetic JP code: euc gate, prop < 0xC0, no A9 row, fonts mnu\\jp")
    check(aj.glyph(b"\xa5\xa2") == Glyph(2, "cell", 0xA5A2, 289) and aj.glyph(b"\xb0\xa1").cell == 1024
          and aj.glyph(b"\xa1\x41").length == 2 and aj.glyph(b"\x85A") == Glyph(1, "cell", 0xA905, FALLBACK_CELL)
          and aj.glyph(b"\xe9") .length == 1 and aj.glyph(b"\xd7\xfc").cell == 3990,
          "JP glyph: A5/B0 pairs, trail untested, lone 0x85 -> 0x7F, lone lead at the end, extra kanji")
    mj = aj.measurer(f.metrics, prop=True, han=True)
    check(mj.width(b"\xa4\xa2") == 19 and m.width(b"\xa4\xa2") == a.glyph_width(193, f.metrics)
          and mj.width(b"A") == wa and mj.width(b"\x18\x01\xa4\xa2") == aj.glyph_width(193, f.metrics),
          "JP width: kana (cell 193) fixed 19 under $prop1 (USA: proportional); half-size uses pair 193")
    try:
        bad = bytearray(_synthetic_elf(pj, gate="euc", prop=0xC0, a9_row=False))
        Addressing.from_executable(bytes(bad).replace(GATE_EUC_WORDS, b"\0" * 16), pj)
        check(False, "a gate of unknown shape is refused")
    except FontError:
        check(True, "a gate of unknown shape is refused")
    # donor on synthetic fonts
    s1, s2 = Font.blank(), Font.blank()
    for c in range(1024, 3989, 7):
        s1.set_cell(c, [[(c + y) % 4] * 20 for y in range(24)])
        s2.set_cell(c, [[(c + y) % 4] * 20 for y in range(24)])
    s1.set_cell(200, [[2] * 20] * 24)
    s1.set_cell(200 + PROP_CELL_SHIFT, [[1] * 20] * 24)
    s1.metrics[200] = (3, 9)
    nd, rp = donate(s1, s2, parse_cells("199-200"))
    check(nd.cell(200) == s1.cell(200) and nd.metrics[200] == (3, 9) and nd.cell(776) == s2.cell(776)
          and rp["cells_copied"] == 2 and rp["metric_pairs_changed"] == 1, "donate: cells + metrics, not cell+576")
    nd, rp = donate(s1, s2, [200], metrics=False, prop_images=True)
    check(nd.cell(776) == s1.cell(776) and nd.metrics[200] == (0, 0), "donate --prop-images --no-metrics")
    check(parse_cells("192-194, 3989") == [192, 193, 194, 3989], "parse_cells")

    # file layer on synthetic data
    rng = np.random.default_rng(3)
    blob = bytes(rng.integers(0, 256, FILE_SIZE, dtype=np.uint8))
    g = Font.from_bytes(blob)
    check(g.to_bytes() == blob, "random 0x78C00 bytes: from_bytes/to_bytes byte-exact")
    d = np.frombuffer(blob, np.uint8)
    n = 1024 + 37
    exp = ((d[37 * 480:38 * 480] >> 2) & 3).reshape(24, 20).tolist()
    check(g.cell(n) == exp, "cell n = byte cell n & 0x3FF, plane n >> 10")
    g.set_cell(4095, [[3] * 20] * 24)
    b2 = g.to_bytes()
    check(b2[1023 * 480:1024 * 480] == bytes(x | 0xC0 for x in blob[1023 * 480:1024 * 480])
          and b2[:1023 * 480] == blob[:1023 * 480], "set_cell touches only its plane")
    w_, h_, gray = png_to_gray(sheet_to_png(g.sheets[2]))
    check((w_, h_) == (SHEET_W, SHEET_H) and quantize(gray) == g.sheets[2], "sheet -> PNG -> sheet exact")
    img = g.sys8x8_image()
    g2 = Font.from_bytes(b2)
    g2.set_sys8x8_image(img)
    check(g2.to_bytes() == b2 and len(img) == SYS_W * SYS_H, "sys8x8 image round trip")
    try:
        g.set_metrics(512, 1, 1)
        check(False, "metrics cannot grow")
    except FontError:
        check(True, "metrics cannot grow")
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        with contextlib.redirect_stdout(io.StringIO()):
            extract_font(blob, "font0", td)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            cmd_rebuild(str(td / "font0.bin"), str(td), str(td / "out.bin"),
                        str(td / "font0_metrics.csv"), str(td / "font0_sys8x8.png"))
        check("identical" in buf.getvalue() and (td / "out.bin").read_bytes() == blob,
              "font-extract -> font-rebuild (sheets, metrics, sys8x8) is identical")
        (td / "copy.bin").write_bytes(blob)
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                cmd_rebuild(str(td / "copy.bin"), str(td), str(td / "o2.bin"))
            check(False, "rebuild with nothing to apply refused")
        except FontError:
            check(True, "rebuild with nothing to apply is refused")

    # disc checks
    discs = [(k, os.environ.get(k)) for k in ("XS3_D1", "XS3_D2", "XS3_PROTO", "XS3_JP1", "XS3_JP2")]
    if not any(p for _, p in discs):
        print("SKIP  disc checks (set XS3_D1 / XS3_D2 / XS3_PROTO / XS3_JP1 / XS3_JP2)")
    seen: Dict[Tuple[str, int], set] = {}
    fonts_by: Dict[Tuple[str, int], Font] = {}
    for key, path in discs:
        if not path:
            print(f"SKIP  {key} not set")
            continue
        exe = read_boot_exe(path)
        ad = Addressing.from_executable(exe)
        jp = ad.profile == "jp"
        check(ad.cell(*divmod(ad.han_code(ord("A")), 256)) == 138
              and ad.glyph(b"\xe9").cell == (FALLBACK_CELL if jp else 361)
              and len(ad.extra[0]) == 24 and len(ad.extra[1]) == 100 and len(ad.commands) == 18
              and ad.ctl[0x17] == 7 and tuple(ad.ctl08[:5]) == (2, 2, 3, 2, 2),
              f"{key} ({ad.profile}): han 'A' -> 138, lone 0xE9 -> {'0x7F' if jp else '361'}, extra lists 24/100, "
              f"18 commands, ctl tables")
        want = ("euc", JP_PROP_CELLS, False, "jp") if jp else ("whitelist", PROP_LIMIT, True, "us")
        check((ad.gate, ad.prop_cells, ad.a9_row, ad.font_dir) == want,
              f"{key}: rules read from the code: gate {ad.gate}, prop cells < {ad.prop_cells:#x}, "
              f"a9_row {ad.a9_row}, fonts mnu\\{ad.font_dir}")
        check(ad.clut_check() == (1024, 1024), f"{key}: the four CLUTs are white with alpha 0/2A/55/80 per plane")
        if jp:
            spots = {(0xB0, 0xA1): 1024, (0xA4, 0xA2): 193, (0xA5, 0xA2): 289, (0xA3, 0xC1): 138,
                     (0xA3, 0xB0): 128, (0xA6, 0xB8): 407}
            check(all(ad.cell(l, t) == c for (l, t), c in spots.items()),
                  f"{key}: M24 spots B0A1 1024, A4A2 193, A5A2 289, A3C1 138, A3B0 128, A6B8 407")
            g1, g2, g3 = ad.glyph(b"\xa5\xa2"), ad.glyph(b"\xb0\xa1"), ad.glyph(b"\x85x")
            check(g1.length == 2 and g2.length == 2 and (g3.length, g3.cell) == (1, FALLBACK_CELL)
                  and ad.glyph(b"\xa1\x41").length == 2,
                  f"{key}: euc gate: A5/B0 leads are pairs, any trail; lone 0x85 -> 0x7F")
        for k, data in enumerate(read_fonts(path, ad.font_dir)):
            fo = Font.from_bytes(data)
            mok, mtot = fo.metrics_check()
            want_m = (317, 317) if (jp and k == 0) else (320, 320) if jp else (378, 378)
            check(len(data) == FILE_SIZE and fo.to_bytes() == data and (mok, mtot) == want_m,
                  f"{key} font{k}: byte-exact rebuild, metrics = ink of cell+576 for {mok}/{mtot}")
            seen.setdefault((ad.font_dir, k), set()).add(hashlib.sha1(data).hexdigest())
            fonts_by[(ad.font_dir, k)] = fo
            if jp:
                m = ad.measurer(fo.metrics, prop=True, han=True, font=k)
                kana = m.width(b"\xa4\xa2\xa5\xa2")
                m2 = ad.measurer(fo.metrics, prop=True, han=True, font=k)
                half = m2.width(b"\x18\x01\xa4\xa2")
                check(kana == 2 * FIXED_ADVANCE and half == ad.glyph_width(193, fo.metrics),
                      f"{key} font{k}: kana are fixed width under $prop1 ({kana} px for 2); half-size A4A2 "
                      f"uses metric pair 193 ({half} px)")
    if seen:
        check(all(len(v) == 1 for v in seen.values()),
              "every disc of one region carries the same font0 / font1 (" +
              ", ".join(f"{d}/font{k} {next(iter(v))[:8]}" for (d, k), v in sorted(seen.items())) + ")")
    for k in (0, 1):
        if ("jp", k) in fonts_by and ("us", k) in fonts_by:
            jpf, usf = fonts_by[("jp", k)], fonts_by[("us", k)]
            new, rep = donate(jpf, usf, list(range(192, 384)), metrics=True)
            diff = [c for c in range(CELL_COUNT) if new.cell(c) != usf.cell(c)]
            check(rep["kanji_agree"] >= 2964 and set(diff) <= set(range(192, 384)) and len(diff) == 192
                  and new.metrics[192:384] == jpf.metrics[192:384] and new.metrics[:192] == usf.metrics[:192]
                  and new.cell(193) == jpf.cell(193),
                  f"donate() jp -> us font{k}: kanji agree {rep['kanji_agree']}/2965, 192 kana cells and metric "
                  f"pairs 192-383 copied, nothing else changed (the API; the command refuses used cells)")
            try:
                donate(jpf, fonts_by[("us", 1 - k)], [193])
                check(False, "donor between font0 and font1 refused")
            except FontError:
                check(True, f"font-donor refuses jp font{k} -> us font{1 - k} (kanji do not agree)")
        else:
            print(f"SKIP  font-donor font{k} (needs a us and a jp disc)")
    d1, j1 = os.environ.get("XS3_D1"), os.environ.get("XS3_JP1")
    if d1 and j1:
        used = retail_cells(d1)
        hit = {c for c in range(192, 384) if c in used}
        check(len(hit) >= 68 and {361, 374, 302} <= hit,
              f"USA D1 retail text draws {len(hit)} of cells 192-383 (361 é {used.get(361)}x, 374 ö "
              f"{used.get(374)}x, 302 ® {used.get(302)}x)")
        with tempfile.TemporaryDirectory() as td:
            ns = argparse.Namespace(cells="192-383", from_iso=j1, to_iso=d1, from_font0=None, from_font1=None,
                                    to_font0=None, to_font1=None, font="both", no_metrics=False,
                                    prop_images=False, force=False, allow_used=False, out=os.path.join(td, "o"))
            try:
                cmd_donor(ns)
                check(False, "font-donor --cells 192-383 into USA is refused (retail cells)")
            except FontError as e:
                check("drawn by the retail text" in str(e) and not os.path.exists(ns.out),
                      "font-donor --cells 192-383 into USA is refused (retail cells), nothing written")
            free = [c for c in range(192, 256) if c not in used][:4]
            ns.cells, ns.font = ",".join(map(str, free)), "0"
            with contextlib.redirect_stdout(io.StringIO()):
                rc = cmd_donor(ns)
            check(rc == 0 and os.path.exists(os.path.join(ns.out, "font0.bin")),
                  f"font-donor into free USA cells {ns.cells} is accepted")
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
