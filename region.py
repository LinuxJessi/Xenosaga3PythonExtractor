"""region.py — which Episode III build a disc carries, its language folder, its executable
tables, and how an engine path with the language token resolves on that disc.

Not to be confused with ``regions.py``, the older module that assigns legacy
Lba*.txt sources to X3.* containers (an LBA-to-container mapper). This one is
about game builds (USA retail, the May 2006 prototype, Japan retail).

Borrowed from Xenosaga2PythonExtractor/region.py (2026-11-20). Kept as is:
``require_known`` / ``require_executable`` / ``mixed_regions`` / ``warn_mixed``
/ ``elf_segments`` / ``va_to_offset`` / ``read_va``. What changed for XS3:

* profiles are keyed by SYSTEM.CNF serial AND boot-executable sha256, because
  the May 2006 prototype reuses the Disc 1 serial SLUS_213.89 with a different
  executable; ``region_of`` (alias ``detect``) hashes the executable;
* a profile carries every executable address the text, font and path code
  needs (``Region.vas``), the text rules (codec, pair gate, proportional cell
  count, Latin-1 singles, A9 row) and the folder layout; the table CONTENTS
  are read from the executable at run time, never copied into this file;
* every address is checked at run time by ``verify`` (below), so a profile
  entered wrongly fails loudly instead of reading the wrong bytes;
* ``lang_of`` finds the language folder from the disc's own index, ``lpath``
  substitutes it into engine-style paths (``mnu\\\\xx\\\\font0.bin``) and
  ``resolve`` finds the file the way the engine does (the language folder,
  then the folder without it: JP keeps ``jpg\\\\``, ``ef\\\\map\\\\`` and a few more
  at the root where the USA build has ``\\\\us\\\\``).

Builds (all three re-checked 2026-11-20 on the images)::

    build          serial(s)                  exe sha256 (boot ELF)
    us             SLUS_213.89 / SLUS_214.17  bec09b76fd56a146695954d55b05dec646ac606ed805c9b5287227c37746d99c
    proto_2006_05  SLUS_213.89                1c3d028a063ea086cc367252f2a0e784afd9890b0ae280f5b73c07ade3bd08dd
    jp             SLPS_256.40 / SLPS_256.41  b82b6744bac7b9557cce5cadde1c721b90fd2959d576828882b05feb03a54ec9

Both discs of a retail build carry the same executable and the same X3.00.

How an address is verified (``verify(region, elf)``; T4 of the JP brief)
-------------------------------------------------------------------------
Each name in ``SPECS`` has one rule; every VA of a verified profile must pass:

* ``func``  the first K instruction words, masked (j/jal targets, lui and
  I-type immediates except sp-relative ones are zeroed, as in the JP survey's
  fmatch.py), hash to the stored signature, and that masked run occurs
  exactly once in .text. For functions the two builds share, the USA and JP
  profiles store the SAME signature: the same masked code found at two
  different addresses in two different executables;
* ``xref``  a data address is computed (lui + addiu/load/store) by an
  instruction inside a named, verified function (the instruction VA is stored);
* ``content`` the bytes at the address hash to a stored value; tables that
  are equal in the two builds (ASCII->EUC ``$han`` table, extra-kanji lists,
  nibble/GIF tables, control lengths) store ONE hash for both;
* ``gate``  the pair gate FUN_00181e48: JP is the 4 words
  ``andi v0,a0,0xff; sltiu v0,v0,0xa0; jr ra; sltiu v0,v0,1`` (lead >= 0xA0,
  trail ignored); the USA build starts ``andi a1,a1,0xff; andi a0,a0,0xff``
  (two arguments: the whitelist of textcodec.us_pair);
* ``imm``   the proportional-cell gates in the printer and the measurer are
  sltiu/slti with immediate ``prop_cells`` (JP 0xC0, USA 0x180).

``$``-commands (``dollar_commands``): the table holds 18 (name, handler)
pairs, identical names in both builds: ax ay az rx ry init save load col bg
shadow alpha zoom xx ruby prop han mark.

Public API used by the other modules::

    detect(disc_or_iso) -> Region         region_of (serial + exe sha256)
    verify(region, elf) -> [Check]        every VA against its rule
    resolve(disc, 'cf\\\\xx\\\\1220.sb')   -> 'cf\\\\jp\\\\1220.sb' (or the root fallback)
    lpath(region, path) / disc_lang(disc) / mixed_regions(discs)
    region.codec  ('us' | 'jp')           textcodec.for_region picks the codec

    python region.py --self-test
"""
from __future__ import annotations

import dataclasses
import hashlib
import struct
import sys
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Mapping, NamedTuple, Optional, Tuple

import numpy as np

# the engine's locale table order (FUN_00181c18, "jpjpusendefriteszhko"), duplicates dropped
LOCALE_ORDER = ("jp", "us", "en", "de", "fr", "it", "es", "zh", "ko")
LOCALE_TABLE = b"jpjpusendefriteszhko"

# folders whose files sit under a language folder: the localized=1 types of the
# resource-type table (cf .t/.sb, bat, evt, mov, mnu, mg1; USA also ef\esp), the
# sprintf forms ef\map\%c%c (falls back to ef\map\) and ef\esd\%c%c, mnu/pse/xx,
# and jpg\ (localized=0 in the table but built as jpg\ + code by FUN_002dfd48)
LOCALIZED_PREFIXES = ("cf", "bat", "evt", "mov", "mnu", "mnu\\pse", "mg1",
                      "ef\\esp", "ef\\esd", "ef\\map", "jpg")

# ---------------------------------------------------------------- rules of an address

class Spec(NamedTuple):
    kind: str                 # func / data / bss / insn
    func: Optional[str]       # the function whose instruction computes it (data, bss, insn)
    note: str


SPECS: Dict[str, Spec] = {
    # functions (USA FUN_ names; the JP address is in the JP profile)
    "locale_lookup":   Spec("func", None, "FUN_00181c18: language byte -> locale code"),
    "han_lookup":      Spec("func", None, "FUN_00181d10: ASCII -> EUC ($han)"),
    "extra_lookup":    Spec("func", None, "FUN_00181d40: extra-kanji list of the current font"),
    "half_size":       Spec("func", None, "FUN_00181db8: half-size map, cell+0x240 at height 0xC0"),
    "pair_gate":       Spec("func", None, "FUN_00181e48: does (lead, trail) form one character"),
    "sys8x8_upload":   Spec("func", None, "FUN_00181fa0: sys8x8 upload"),
    "control_lengths": Spec("func", None, "FUN_00182290: control-code lengths"),
    "string_width":    Spec("func", None, "FUN_001828a0: string width (the measurer)"),
    "dollar_commands": Spec("func", None, "FUN_00184090: $-command dispatch"),
    "glyph_draw":      Spec("func", None, "FUN_00184188: glyph draw"),
    "ascii_draw":      Spec("func", None, "FUN_00184798: ASCII draw"),
    "code_to_cell":    Spec("func", None, "FUN_00184938: character code -> font cell"),
    "printer":         Spec("func", None, "FUN_00184b30: the print function"),
    "advance":         Spec("func", None, "FUN_00185770: glyph advance"),
    "font_load":       Spec("func", None, "FUN_00185cb0: font load / swap"),
    "file_read":       Spec("func", None, "FUN_00188148: file read (index LBA + sector)"),
    "ruby_packer":     Spec("func", None, "FUN_001b2520: subtitle ruby cue packer"),
    "subtitle_packer": Spec("func", None, "FUN_001b27b8: subtitle packer"),
    "txt_loader":      Spec("func", None, "FUN_001b2f60: subtitle .txt loader"),
    "restype_reader":  Spec("func", None, "FUN_001b6e18: resource-type table reader"),
    "path_suffix":     Spec("func", None, "FUN_001b7270: '%c%c\\' language path suffix"),
    "string_fetch":    Spec("func", None, "FUN_001d4238: .sb text-pool string fetch"),
    "ef_map_esd":      Spec("func", None, "FUN_0020fa70: ef\\map / ef\\esd path builder"),
    "lang_option_b":   Spec("func", None, "FUN_00225780: language option"),
    "lang_option_a":   Spec("func", None, "FUN_002257f0: language option (cycle)"),
    "tag_parser":      Spec("func", None, "FUN_002734b8: dialogue tag parser"),
    # data
    "locale_table":    Spec("data", "locale_lookup", "'jpjpusendefriteszhko'"),
    "lang_byte":       Spec("data", "locale_lookup", "language index byte (file value 0)"),
    "han_table":       Spec("data", "han_lookup", "u16 EUC code at VA + 2*byte"),
    "extra_kanji_font1": Spec("data", "extra_lookup", "100 u16 codes"),
    "extra_kanji_font0": Spec("data", "extra_lookup", "24 u16 codes"),
    "kanji_selector":  Spec("bss", "extra_lookup", "which extra list is live (printer state + 6)"),
    "printer_state":   Spec("bss", "sys8x8_upload", "printer state block"),
    "nibble_table":    Spec("data", "sys8x8_upload", "2-bit plane expansion"),
    "sys8x8_gif":      Spec("data", "sys8x8_upload", "sys8x8 GIF header"),
    "control_length_table": Spec("data", "control_lengths", "first 0x60 bytes (the pointers after differ)"),
    "dollar_table":    Spec("data", "dollar_commands", "18 (name, handler) pairs + (0, 0)"),
    "glyph_gif":       Spec("data", "glyph_draw", "glyph GIF header"),
    "cell_jump_table": Spec("data", "code_to_cell", "13 cases, leads A1..AD"),
    "restype_table":   Spec("data", "restype_reader", "38 x 20-byte resource types"),
    "path_format":     Spec("data", "path_suffix", "'%c%c\\'"),
    "ruby_tag":        Spec("data", "ruby_packer", "'$rubyb;'"),
    "lang_list":       Spec("data", "lang_option_b", "language option list (JP: 9 rodata bytes; USA: RAM)"),
    "font_path":       Spec("data", None, "'mnu\\xx\\font0.bin' (content only: no lui/addiu reference in JP)"),
    # instructions
    "prop_gate_printer":  Spec("insn", "printer", "sltiu imm = prop_cells"),
    "prop_gate_measurer": Spec("insn", "string_width", "slti imm = prop_cells"),
}

# content rules: name -> (length, sha1 prefix). One value for both builds where the
# tables are equal (filled from the executables; ``_derive`` prints them).
SHARED_CONTENT: Dict[str, Tuple[int, str]] = {
    "han_table": (0x100, "25bf7fbccb0a82bd"),
    "extra_kanji_font1": (200, "671a934d78f27cce"),
    "extra_kanji_font0": (48, "190a8ff246b4faf4"),
    "nibble_table": (0x40, "6947a646d2ae77a2"),
    "sys8x8_gif": (0x40, "76b4ae8f7f54aa40"),
    "control_length_table": (0x60, "3d8342fd8094905f"),
    "glyph_gif": (0x40, "495c985ed86be4f0"),
}
LITERALS: Dict[str, bytes] = {
    "locale_table": LOCALE_TABLE,
    "font_path": b"mnu\\xx\\font0.bin\0",
    "path_format": b"%c%c\\\0",
    "ruby_tag": b"$rubyb;\0",
}
DOLLAR_NAMES = ("ax", "ay", "az", "rx", "ry", "init", "save", "load", "col", "bg", "shadow",
                "alpha", "zoom", "xx", "ruby", "prop", "han", "mark")
JP_GATE = (0x308200FF, 0x2C4200A0, 0x03E00008, 0x2C420001)
US_GATE_HEAD = (0x30A500FF, 0x308400FF)

SIG_WORDS = 16


@dataclass(frozen=True)
class Region:
    name: str                              # "us", "proto_2006_05", "jp", "unknown"
    lang: Optional[str]                    # the build's language folder code
    serials: Tuple[str, ...] = ()
    exe_sha256: Optional[str] = None       # the executable every address below was read from
    locale_table_va: Optional[int] = None
    ascii_table_va: Optional[int] = None   # u16 EUC code at VA + 2 * byte (the $han table)
    restype_table_va: Optional[int] = None
    verified: bool = True
    note: str = ""
    fonts: Tuple[str, ...] = ("mnu\\xx\\font0.bin", "mnu\\xx\\font1.bin")
    text: str = "euc"                      # kept for older callers; see ``codec``
    serial: Optional[str] = None           # the serial seen, on an unknown/discovered profile
    # --- text rules (section 1 of the JP brief) ---
    codec: str = "us"                      # textcodec.for_region: 'us' (whitelist gate) | 'jp' (lead >= 0xA0)
    pair_gate: str = "whitelist"           # 'whitelist' (USA) | 'lead_a0' (JP)
    latin1_singles: bool = True            # lone 0xA0-0xFF draw Latin-1 cells (JP: 0x80-0x9F draw cell 0x7F)
    a9_row: bool = True                    # lead A9 -> cell trail+0x100
    prop_cells: int = 0x180                # cells below this are proportional (JP 0xC0)
    prop_pad: int = 3
    drawable_cells: int = 4096
    mono_subtitles: bool = True            # the subtitle loader has a 'mono' branch (JP: no)
    # --- folders ---
    localized_dirs: Tuple[str, ...] = ()
    dropped_dirs: Tuple[str, ...] = ()     # \us\ on USA, at the root on this build (resolve's fallback)
    # --- executable layout ---
    text_section: Tuple[int, int] = (0x120000, 0)
    vas: Mapping[str, int] = field(default_factory=dict, hash=False, compare=False)
    sizes: Mapping[str, int] = field(default_factory=dict, hash=False, compare=False)
    refs: Mapping[str, int] = field(default_factory=dict, hash=False, compare=False)
    sigs: Mapping[str, Tuple[int, str]] = field(default_factory=dict, hash=False, compare=False)

    def va(self, name: str) -> int:
        try:
            return self.vas[name]
        except KeyError:
            raise UnknownBuild(f"the {self.name} profile has no address for {name!r}")


_US_DIRS = ("bat\\us", "cf\\us", "ef\\esd\\us", "ef\\esp\\us", "ef\\map\\us", "evt\\us", "jpg\\us",
            "mov\\us", "mov\\us\\bat", "mnu\\us", "mnu\\pse\\us", "mg1\\us")
_JP_DIRS = ("bat\\jp", "cf\\jp", "ef\\esd\\jp", "evt\\jp", "mov\\jp", "mov\\jp\\bat", "mnu\\jp",
            "mnu\\pse\\jp", "mg1\\jp")
_JP_DROPPED = ("jpg", "ef\\map", "ef\\esp", "mnu\\pse")

# ---- profile tables (addresses found in the survey; verified by ``verify`` at run time)
_US_VAS = {
    "locale_lookup": 0x181C18, "han_lookup": 0x181D10, "extra_lookup": 0x181D40, "half_size": 0x181DB8,
    "pair_gate": 0x181E48, "sys8x8_upload": 0x181FA0, "control_lengths": 0x182290,
    "string_width": 0x1828A0, "dollar_commands": 0x184090, "glyph_draw": 0x184188,
    "ascii_draw": 0x184798, "code_to_cell": 0x184938, "printer": 0x184B30, "advance": 0x185770,
    "font_load": 0x185CB0, "file_read": 0x188148, "ruby_packer": 0x1B2520,
    "subtitle_packer": 0x1B27B8, "txt_loader": 0x1B2F60, "restype_reader": 0x1B6E18,
    "path_suffix": 0x1B7270, "string_fetch": 0x1D4238, "ef_map_esd": 0x20FA70,
    "lang_option_b": 0x225780, "lang_option_a": 0x2257F0, "tag_parser": 0x2734B8,
    "locale_table": 0x53FCC8, "lang_byte": 0x4B377E, "han_table": 0x4B2E50,
    "extra_kanji_font1": 0x4B2F50, "extra_kanji_font0": 0x4B3020, "kanji_selector": 0x7E7E06,
    "printer_state": 0x7E7E00, "nibble_table": 0x4B3058, "sys8x8_gif": 0x4B30A0,
    "control_length_table": 0x4B3150, "dollar_table": 0x4B31B0, "glyph_gif": 0x4B3250,
    "cell_jump_table": 0x540080, "restype_table": 0x3DFE78, "path_format": 0x530818,
    "ruby_tag": 0x53F588, "lang_list": 0x5A6BD0, "font_path": 0x540158,
    "prop_gate_printer": 0x1856E4, "prop_gate_measurer": 0x182DD4,
}
_JP_VAS = {
    "locale_lookup": 0x181C18, "han_lookup": 0x181D10, "extra_lookup": 0x181D40, "half_size": 0x181DB8,
    "pair_gate": 0x181E48, "sys8x8_upload": 0x181E58, "control_lengths": 0x182148,
    "string_width": 0x182758, "dollar_commands": 0x183F30, "glyph_draw": 0x184028,
    "ascii_draw": 0x184638, "code_to_cell": 0x1847D8, "printer": 0x1849C8, "advance": 0x185610,
    "font_load": 0x185B50, "file_read": 0x187FE8, "ruby_packer": 0x1B2188,
    "subtitle_packer": 0x1B2558, "txt_loader": 0x1B2658, "restype_reader": 0x1B5F80,
    "path_suffix": 0x1B63D8, "string_fetch": 0x1D3340, "ef_map_esd": 0x20EB78,
    "lang_option_b": 0x224350, "lang_option_a": 0x224398, "tag_parser": 0x271D58,
    "locale_table": 0x53E508, "lang_byte": 0x4B1EFE, "han_table": 0x4B15A0,
    "extra_kanji_font1": 0x4B16A0, "extra_kanji_font0": 0x4B1770, "kanji_selector": 0x7E6586,
    "printer_state": 0x7E6580, "nibble_table": 0x4B17A8, "sys8x8_gif": 0x4B17F0,
    "control_length_table": 0x4B18A0, "dollar_table": 0x4B1900, "glyph_gif": 0x4B19A0,
    "cell_jump_table": 0x53E8C0, "restype_table": 0x3DE8F8, "path_format": 0x52EF90,
    "ruby_tag": 0x53DDF8, "lang_list": 0x536F68, "font_path": 0x53E998,
    "prop_gate_printer": 0x185584, "prop_gate_measurer": 0x182C7C,
}
# function sizes in bytes (USA: the decomp symbol map, except code_to_cell whose
# jump-table cases run to 0x184b1c: 504 to the next function, not the map's 464;
# JP: distance to the next function start found by masked matching)
_US_SIZES: Dict[str, int] = {
    "locale_lookup": 116, "han_lookup": 44, "extra_lookup": 116, "half_size": 140, "pair_gate": 336,
    "sys8x8_upload": 216, "control_lengths": 172, "string_width": 1448, "dollar_commands": 216,
    "glyph_draw": 1536, "ascii_draw": 316, "code_to_cell": 504, "printer": 3064, "advance": 148,
    "font_load": 164, "file_read": 1052, "ruby_packer": 656, "subtitle_packer": 256, "txt_loader": 368,
    "restype_reader": 156, "path_suffix": 76, "string_fetch": 92, "ef_map_esd": 376, "lang_option_b": 112,
    "lang_option_a": 328, "tag_parser": 880,
}
_JP_SIZES: Dict[str, int] = {
    "locale_lookup": 116, "han_lookup": 44, "extra_lookup": 116, "half_size": 140, "pair_gate": 16,
    "sys8x8_upload": 216, "control_lengths": 172, "string_width": 1496, "dollar_commands": 216,
    "glyph_draw": 1536, "ascii_draw": 316, "code_to_cell": 496, "printer": 3144, "advance": 148,
    "font_load": 164, "file_read": 1052, "ruby_packer": 976, "subtitle_packer": 256, "txt_loader": 320,
    "restype_reader": 156, "path_suffix": 76, "string_fetch": 92, "ef_map_esd": 320, "lang_option_b": 72,
    "lang_option_a": 144, "tag_parser": 880,
}
# data/bss/insn name -> the instruction that computes the address (inside SPECS[name].func)
_US_REFS: Dict[str, int] = {
    "locale_table": 0x181c30, "lang_byte": 0x181c20, "han_table": 0x181d30, "extra_kanji_font1": 0x181d6c,
    "extra_kanji_font0": 0x181d5c, "kanji_selector": 0x181d48, "printer_state": 0x181fa8,
    "nibble_table": 0x181fd4, "sys8x8_gif": 0x18202c, "control_length_table": 0x1822a0,
    "dollar_table": 0x1840a4, "glyph_gif": 0x1842e4, "cell_jump_table": 0x18496c, "restype_table": 0x1b6e34,
    "path_format": 0x1b729c, "ruby_tag": 0x1b25c0, "lang_list": 0x2257b8, "prop_gate_printer": 0x1856e4,
    "prop_gate_measurer": 0x182dd4,
}
_JP_REFS: Dict[str, int] = {
    "locale_table": 0x181c30, "lang_byte": 0x181c20, "han_table": 0x181d30, "extra_kanji_font1": 0x181d6c,
    "extra_kanji_font0": 0x181d5c, "kanji_selector": 0x181d48, "printer_state": 0x181e60,
    "nibble_table": 0x181e8c, "sys8x8_gif": 0x181ee4, "control_length_table": 0x182158,
    "dollar_table": 0x183f44, "glyph_gif": 0x184184, "cell_jump_table": 0x18480c, "restype_table": 0x1b5f9c,
    "path_format": 0x1b6404, "ruby_tag": 0x1b236c, "lang_list": 0x224360, "prop_gate_printer": 0x185584,
    "prop_gate_measurer": 0x182c7c,
}
# function -> (K words, sha1 prefix of the masked words)
_US_SIGS: Dict[str, Tuple[int, str]] = {
    "locale_lookup": (16, "8737a4d5983a61e2"), "han_lookup": (11, "6b084e16545a8007"),
    "extra_lookup": (16, "25944b8ef1bc7741"), "half_size": (16, "32f4b70b583480dc"),
    "sys8x8_upload": (16, "94be64eeaa750c2d"), "control_lengths": (16, "b83a8e80771be056"),
    "string_width": (16, "a3d507c2a0a7831d"), "dollar_commands": (16, "4c88adae86be677a"),
    "glyph_draw": (16, "c6c2bff20b35ec79"), "ascii_draw": (16, "6046192ba7da1b76"),
    "code_to_cell": (16, "4d55b2a4cb8ea616"), "printer": (16, "65a481fd6eef1772"),
    "advance": (16, "f8fd335ad1b5c81c"), "font_load": (16, "16d7e86d31f80c69"),
    "file_read": (16, "50eb1b445f8d48d9"), "ruby_packer": (16, "576a437ad89ee983"),
    "subtitle_packer": (16, "41a1d5ef489c0eb3"), "txt_loader": (16, "1cfbf60816c4ebe6"),
    "restype_reader": (16, "3fa41cce6be2e67f"), "path_suffix": (16, "6958e3722eb3c75e"),
    "string_fetch": (16, "3c19ad48ef232f20"), "ef_map_esd": (16, "a2a3eb361551c509"),
    "lang_option_b": (16, "d20a998199669d95"), "lang_option_a": (16, "de865c576b63581c"),
    "tag_parser": (16, "c0ce0f15b040ffa0"),
}
_JP_SIGS: Dict[str, Tuple[int, str]] = {
    "locale_lookup": (16, "8737a4d5983a61e2"), "han_lookup": (11, "6b084e16545a8007"),
    "extra_lookup": (16, "25944b8ef1bc7741"), "half_size": (16, "32f4b70b583480dc"),
    "sys8x8_upload": (16, "94be64eeaa750c2d"), "control_lengths": (16, "b83a8e80771be056"),
    "string_width": (16, "96ed4bbecce281ad"), "dollar_commands": (16, "4c88adae86be677a"),
    "glyph_draw": (16, "c6c2bff20b35ec79"), "ascii_draw": (16, "6046192ba7da1b76"),
    "code_to_cell": (16, "ae14a95bd639e188"), "printer": (16, "ec4c9eb639a28390"),
    "advance": (16, "f8fd335ad1b5c81c"), "font_load": (16, "16d7e86d31f80c69"),
    "file_read": (16, "50eb1b445f8d48d9"), "ruby_packer": (16, "1b69277476249a24"),
    "subtitle_packer": (16, "63854eee5973484e"), "txt_loader": (16, "47e624060a9a6801"),
    "restype_reader": (16, "3fa41cce6be2e67f"), "path_suffix": (16, "6958e3722eb3c75e"),
    "string_fetch": (16, "3c19ad48ef232f20"), "ef_map_esd": (16, "8e5656453a556a66"),
    "lang_option_b": (16, "6ef78dbe1dca5bb7"), "lang_option_a": (16, "94785136d99d5657"),
    "tag_parser": (16, "c0ce0f15b040ffa0"),
}

US = Region("us", "us", ("SLUS_213.89", "SLUS_214.17"),
            exe_sha256="bec09b76fd56a146695954d55b05dec646ac606ed805c9b5287227c37746d99c",
            locale_table_va=0x53FCC8, ascii_table_va=0x4B2E50, restype_table_va=0x3DFE78,
            note="USA retail; Disc 1 and Disc 2 carry the same executable",
            localized_dirs=_US_DIRS, text_section=(0x120000, 0x1F72E8),
            vas=_US_VAS, sizes=_US_SIZES, refs=_US_REFS, sigs=_US_SIGS)
PROTO_2006_05 = Region("proto_2006_05", "us", ("SLUS_213.89",),
                       exe_sha256="1c3d028a063ea086cc367252f2a0e784afd9890b0ae280f5b73c07ade3bd08dd",
                       locale_table_va=0x53FA68, ascii_table_va=0x4B2C10, restype_table_va=0x3DFBF8,
                       note="May 22, 2006 press prototype; reuses the Disc 1 serial",
                       localized_dirs=_US_DIRS,
                       vas={"locale_table": 0x53FA68, "han_table": 0x4B2C10, "restype_table": 0x3DFBF8})
JP = Region("jp", "jp", ("SLPS_256.40", "SLPS_256.41"),
            exe_sha256="b82b6744bac7b9557cce5cadde1c721b90fd2959d576828882b05feb03a54ec9",
            locale_table_va=0x53E508, ascii_table_va=0x4B15A0, restype_table_va=0x3DE8F8,
            note="Japan retail (SLPS_256.40 / 256.41, SYSTEM.CNF VER 1.01); Disc 1 and Disc 2 "
                 "carry the same executable and the same X3.00",
            codec="jp", pair_gate="lead_a0", latin1_singles=False, a9_row=False, prop_cells=0xC0,
            mono_subtitles=False, localized_dirs=_JP_DIRS, dropped_dirs=_JP_DROPPED,
            text_section=(0x120000, 0x1F5D68),
            vas=_JP_VAS, sizes=_JP_SIZES, refs=_JP_REFS, sigs=_JP_SIGS)

PROFILES: Tuple[Region, ...] = (US, PROTO_2006_05, JP)   # verified, matched by serial + sha256
PLACEHOLDERS: Tuple[Region, ...] = ()                    # matched by serial only, then discovery


class UnknownBuild(ValueError):
    pass


# --------------------------------------------------------- executable access

def _iso(x):
    """An IsoImage from an IsoImage or a disc.Disc (anything with ``.iso``)."""
    return x.iso if hasattr(x, "iso") and not hasattr(x, "files") else x


def executable(x) -> Tuple[str, bytes]:
    """(name, bytes) of the boot executable named by SYSTEM.CNF."""
    iso = _iso(x)
    name = iso.boot_elf_name()
    if name is None:
        raise ElfError("no boot executable on this image")
    return name, bytes(iso.read_file(name))


_SHA_CACHE: Dict[Tuple[str, str], str] = {}


def exe_sha256(x) -> Optional[str]:
    iso = _iso(x)
    name = iso.boot_elf_name()
    if name is None:
        return None
    key = (str(getattr(iso, "path", id(iso))), name)
    if key not in _SHA_CACHE:
        _SHA_CACHE[key] = hashlib.sha256(executable(iso)[1]).hexdigest()
    return _SHA_CACHE[key]


def region_of(x) -> Region:
    """The profile of an image (IsoImage or Disc): serial and executable hash must both
    match a verified profile. Anything else is "unknown": it can be listed, dumped and
    browsed, but writers and table readers refuse."""
    iso = _iso(x)
    serial = iso.boot_elf_name()
    sha = exe_sha256(iso) if serial else None
    for p in PROFILES:
        if serial in p.serials and sha == p.exe_sha256:
            return p
    for p in PLACEHOLDERS:
        if serial in p.serials:
            try:
                found = discover(executable(iso)[1])
            except ElfError:
                found = {}
            return dataclasses.replace(p, serial=serial, **found)
    return Region("unknown", None, (), verified=False, fonts=(), text="unknown",
                  serial=serial or "(no boot executable)",
                  note=f"unknown build (exe sha256 {(sha or '?')[:16]}...)")


detect = region_of


def by_name(name: str) -> Region:
    for p in PROFILES:
        if p.name == name:
            return p
    raise UnknownBuild(f"no build profile named {name!r} (known: {', '.join(p.name for p in PROFILES)})")


def as_region(region) -> Region:
    """A Region from a Region, a profile name ('us', 'jp', ...) or None (= USA)."""
    if region is None:
        return US
    if isinstance(region, Region):
        return region
    return by_name(region)


def require_known(x, what: str) -> Region:
    """The image's profile, or UnknownBuild naming the serial seen."""
    prof = region_of(x)
    if prof.name == "unknown":
        known = sorted({s for p in PROFILES for s in p.serials})
        raise UnknownBuild(f"{what} is refused: this image's boot executable is {prof.serial} "
                           f"({prof.note}); known builds: {', '.join(known)} (matched by sha256 too). "
                           f"list, dump and browse still work")
    if not prof.verified:
        print(f"warning: {what}: {prof.name} profile is {prof.note}", file=sys.stderr)
    return prof


# sha256 of executables a self-test builds in code; never a real build
TEST_EXECUTABLES = set()


def require_executable(x, what: str) -> Region:
    """``require_known`` plus: a verified profile whose executable hash matches byte for byte."""
    prof = require_known(x, what)
    got = exe_sha256(x)
    if not prof.verified or (got != prof.exe_sha256 and got not in TEST_EXECUTABLES):
        raise UnknownBuild(f"{what} is refused: the {prof.name} profile is not verified against this "
                           f"executable (sha256 {(got or '?')[:16]}..., expected "
                           f"{(prof.exe_sha256 or 'none recorded')[:16]}...)")
    return prof


def _x300_sha(iso) -> Optional[str]:
    try:
        f = iso.find("X3.00")
        if f is None:
            return None
        return hashlib.sha1(bytes(iso.read_file(f.path))).hexdigest()
    except Exception:                                              # noqa: BLE001 - a probe only
        return None


def mixed_regions(discs: Iterable) -> Optional[str]:
    """A warning when the images are not all one build (told apart by profile AND
    executable hash, so the prototype next to a retail disc is flagged although both
    say SLUS_213.89; JP next to USA is flagged), or when discs of one build carry
    different X3.00 indexes (both discs of a retail build share it)."""
    discs = list(discs)
    seen: Dict[Tuple[str, str], List[str]] = {}
    x300: Dict[str, List[str]] = {}
    for d in discs:
        iso = _iso(d)
        key = (region_of(iso).name, (exe_sha256(iso) or "?")[:16])
        label = f"{getattr(iso, 'path', iso)} ({iso.boot_elf_name()})"
        seen.setdefault(key, []).append(label)
        x300.setdefault(_x300_sha(iso) or "?", []).append(label)
    if len(seen) >= 2:
        return ("warning: these discs are different builds of the game and should not be combined: "
                + "; ".join(f"{n} [exe sha256 {s}...]: {', '.join(v)}" for (n, s), v in sorted(seen.items()))
                + ". Chain 0 is taken from the first image; give Disc 1 and Disc 2 of one build.")
    if len(x300) >= 2:
        return ("warning: these discs run one executable but carry different X3.00 indexes "
                "(both discs of a retail build share it): "
                + "; ".join(f"X3.00 sha1 {k[:12]}: {', '.join(v)}" for k, v in sorted(x300.items())))
    return None


def warn_mixed(discs: Iterable) -> bool:
    """Print the mixed-build warning to stderr; True if there was one."""
    msg = mixed_regions(discs)
    if msg:
        print(msg, file=sys.stderr)
    return bool(msg)


# ------------------------------------------------------------ language folder

def lang_of(source) -> Optional[str]:
    """The first locale code (engine order jp, us, en, de, fr, it, es, zh, ko) for which
    ``mnu\\<code>\\menutext.txd`` exists. ``source`` is a disc.Disc (its index) or an
    iterable of in-game paths. Needs no executable."""
    if hasattr(source, "lookup"):
        have = lambda p: source.lookup(p) is not None
    else:
        paths = {p.replace("/", "\\").lstrip("\\").lower() for p in source}
        have = lambda p: p in paths
    for code in LOCALE_ORDER:
        if have(f"mnu\\{code}\\menutext.txd"):
            return code
    return None


def disc_lang(disc, region: Optional[Region] = None) -> Optional[str]:
    """``lang_of(disc)``, warning on stderr when it disagrees with the profile's code."""
    found = lang_of(disc)
    region = region or region_of(disc)
    if region.lang and found and found != region.lang:
        print(f"warning: the index says language folder {found!r}, the {region.name} profile says "
              f"{region.lang!r}; using {found!r}", file=sys.stderr)
    return found or region.lang


def lpath(region, path: str) -> str:
    """Substitute the language code into an engine-style path: a path component
    ``xx`` (the engine's own template token, e.g. mnu\\xx\\font0.bin) or ``{lang}``.
    ``region`` is a Region or a 2-letter code."""
    lang = region if isinstance(region, str) else region.lang
    if not lang:
        raise UnknownBuild(f"no language code to substitute into {path!r}")
    sep = "/" if "/" in path and "\\" not in path else "\\"
    return sep.join(lang if part in ("xx", "{lang}") else part for part in path.split(sep))


def candidates(lang: str, path: str) -> List[str]:
    """The paths ``resolve`` tries for an engine path, in order: the language token
    replaced by ``lang``, then the token dropped (M27: JP keeps jpg\\, ef\\map\\,
    ef\\esp\\{default,cfdef}.esp and mnu\\pse\\logo_*.tm2 at the root where the USA
    build has \\us\\; the engine's own ef\\map fallback works the same way). A path
    without the token is tried as given."""
    p = path.replace("/", "\\").lstrip("\\")
    parts = p.split("\\")
    idx = [i for i, part in enumerate(parts) if part.lower() in ("xx", "{lang}")]
    if not idx:
        return [p]
    i = idx[0]
    return ["\\".join(parts[:i] + [lang] + parts[i + 1:]), "\\".join(parts[:i] + parts[i + 1:])]


def resolve(disc, path: str, region: Optional[Region] = None) -> Optional[str]:
    """The disc path an engine path with the language token resolves to, or None:
    ``resolve(disc, 'jpg\\\\xx\\\\dtimg_0393.jpg')`` is ``jpg\\\\us\\\\dtimg_0393.jpg`` on
    the USA discs and ``jpg\\\\dtimg_0393.jpg`` on the JP discs. ``disc`` is a
    disc.Disc (or anything with ``lookup(path)`` or ``exists(path)``). The returned
    path is spelled as the disc's index spells it."""
    lang = disc_lang(disc, region) if region is None or region.lang is None else region.lang
    if not lang:
        raise UnknownBuild(f"no language folder known for this disc; cannot resolve {path!r}")
    for cand in candidates(lang, path):
        if hasattr(disc, "lookup"):
            hit = disc.lookup(cand)
            if hit is not None:
                ent = hit[1] if isinstance(hit, tuple) else hit
                return getattr(ent, "path", cand).lstrip("\\")
        elif disc.exists(cand):
            return cand
    return None


# ------------------------------------------------------ executable addresses

class ElfError(ValueError):
    pass


def elf_segments(elf: bytes) -> List[Tuple[int, int, int]]:
    """(virtual address, file offset, file size) of every PT_LOAD program header.
    The file must be a 32-bit little-endian ELF whose program-header table and
    every loaded segment lie inside the file; anything else is an ElfError."""
    if len(elf) < 0x34 or elf[:4] != b"\x7fELF":
        raise ElfError("not an ELF")
    if elf[4] != 1 or elf[5] != 1:
        raise ElfError(f"not a 32-bit little-endian ELF (class {elf[4]}, data {elf[5]})")
    phoff = struct.unpack_from("<I", elf, 0x1C)[0]
    phentsize, phnum = struct.unpack_from("<HH", elf, 0x2A)
    if phnum and phentsize < 32:
        raise ElfError(f"program-header entries of {phentsize} bytes")
    if phoff + phentsize * phnum > len(elf):
        raise ElfError("the program-header table runs past the end of the file")
    segs = []
    for i in range(phnum):
        p_type, p_offset, p_vaddr, _pa, p_filesz = struct.unpack_from("<5I", elf, phoff + phentsize * i)
        if p_type == 1:
            if p_offset + p_filesz > len(elf):
                raise ElfError(f"segment {i} ({p_filesz:#x} bytes at file offset {p_offset:#x}) runs past "
                               f"the end of the {len(elf)}-byte file")
            segs.append((p_vaddr, p_offset, p_filesz))
    return segs


def va_to_offset(elf: bytes, va: int, length: int = 1) -> int:
    """The file offset of ``length`` bytes at virtual address ``va``; ElfError when the
    range is not backed by file bytes of one loaded segment (.bss, unmapped)."""
    for vaddr, offset, filesz in elf_segments(elf):
        if vaddr <= va and va + length <= vaddr + filesz:
            return offset + (va - vaddr)
    raise ElfError(f"VA {va:#x}+{length} is not in the file image of any PT_LOAD segment")


def offset_to_va(elf: bytes, off: int) -> int:
    for vaddr, offset, filesz in elf_segments(elf):
        if offset <= off < offset + filesz:
            return vaddr + (off - offset)
    raise ElfError(f"file offset {off:#x} is not in any PT_LOAD segment")


def read_va(elf: bytes, va: int, length: int) -> bytes:
    """Exactly ``length`` bytes at ``va``, or ElfError: never a short slice."""
    if length < 0:
        raise ElfError("negative length")
    o = va_to_offset(elf, va, max(length, 1))
    out = bytes(elf[o:o + length])
    if len(out) != length:
        raise ElfError(f"short read at VA {va:#x}: {len(out)} of {length} bytes")
    return out


def elf_sections(elf: bytes) -> Dict[str, Tuple[int, int, int]]:
    """name -> (VA, file offset, size) from the section headers (empty if stripped of them)."""
    shoff = struct.unpack_from("<I", elf, 0x20)[0]
    shentsize, shnum, shstrndx = struct.unpack_from("<HHH", elf, 0x2E)
    if not shoff or not shnum or shoff + shentsize * shnum > len(elf) or shstrndx >= shnum:
        return {}
    sh = [struct.unpack_from("<10I", elf, shoff + shentsize * i) for i in range(shnum)]
    stro = sh[shstrndx][4]
    out = {}
    for s in sh:
        e = elf.find(b"\0", stro + s[0])
        out[elf[stro + s[0]:e].decode("latin1")] = (s[3], s[4], s[5])
    return out


# ---- masked code signatures
_IMM_OPS = np.zeros(64, dtype=bool)
_IMM_OPS[[8, 9, 0xA, 0xB, 0xC, 0xD, 0xE, 0x19, 0x1A, 0x1B, 0x1E, 0x1F, 0x20, 0x21, 0x22, 0x23, 0x24, 0x25,
          0x26, 0x27, 0x28, 0x29, 0x2A, 0x2B, 0x2C, 0x2D, 0x2E, 0x2F, 0x31, 0x35, 0x37, 0x39, 0x3D, 0x3F]] = True


def mask_words(words: np.ndarray) -> np.ndarray:
    """j/jal keep the opcode, lui keeps opcode+rt, I-type immediates are zeroed unless
    the base register is sp (stack offsets are part of a function's shape)."""
    w = words.astype(np.uint32)
    op = w >> 26
    rs = (w >> 21) & 31
    out = w.copy()
    jj = (op == 2) | (op == 3)
    out[jj] = w[jj] & np.uint32(0xFC000000)
    imm = ((op == 0xF) | (_IMM_OPS[op] & (rs != 29))) & ~jj
    out[imm] = w[imm] & np.uint32(0xFFFF0000)
    return out


def masked_at(elf: bytes, va: int, n: int) -> np.ndarray:
    return mask_words(np.frombuffer(read_va(elf, va, 4 * n), dtype="<u4"))


def signature(elf: bytes, va: int, k: int) -> str:
    return hashlib.sha1(masked_at(elf, va, k).astype("<u4").tobytes()).hexdigest()[:16]


_TEXT_CACHE: Dict[str, np.ndarray] = {}


def _masked_text(elf: bytes, text: Tuple[int, int]) -> np.ndarray:
    key = hashlib.sha1(elf[:4096] + struct.pack("<II", *text) + elf[-4096:]).hexdigest() + str(len(elf))
    if key not in _TEXT_CACHE:
        _TEXT_CACHE[key] = masked_at(elf, text[0], text[1] // 4)
    return _TEXT_CACHE[key]


def occurrences(elf: bytes, text: Tuple[int, int], va: int, k: int) -> int:
    """How many times the masked K words at ``va`` occur in .text."""
    t = _masked_text(elf, text)
    sig = masked_at(elf, va, k)
    hits = np.nonzero(t[:len(t) - k + 1] == sig[0])[0]
    return sum(1 for h in hits if np.array_equal(t[h:h + k], sig))


def address_of(elf: bytes, insn_va: int, back: int = 64) -> Optional[int]:
    """The address an addiu/load/store at ``insn_va`` computes from an earlier
    ``lui`` of its base register (searched up to ``back`` words), or None."""
    w = struct.unpack("<I", read_va(elf, insn_va, 4))[0]
    op, rs, imm = w >> 26, (w >> 21) & 31, w & 0xFFFF
    if not _IMM_OPS[op] or op in (0xA, 0xB, 0xC, 0xD, 0xE):
        return None
    for k in range(1, back + 1):
        p = struct.unpack("<I", read_va(elf, insn_va - 4 * k, 4))[0]
        if p >> 26 == 0xF and (p >> 16) & 31 == rs:
            return ((p & 0xFFFF) << 16) + (imm - 0x10000 if imm & 0x8000 else imm) & 0xFFFFFFFF
    return None


class Check(NamedTuple):
    name: str
    ok: bool
    detail: str


def _content_rule(region: Region, name: str, elf: bytes, va: int) -> Tuple[bool, str]:
    if name in LITERALS:
        want = LITERALS[name]
        got = read_va(elf, va, len(want))
        return got == want, repr(got)
    if name in SHARED_CONTENT:
        n, sha = SHARED_CONTENT[name]
        got = hashlib.sha1(read_va(elf, va, n)).hexdigest()[:16]
        return got == sha, f"{n} bytes sha1 {got} (shared value {sha})"
    if name == "lang_byte":
        v = read_va(elf, va, 1)[0]
        return v == 0, f"file value {v}"
    if name == "dollar_table":
        names = [n for n, _h in dollar_commands(region, elf)]
        return tuple(names) == DOLLAR_NAMES, " ".join(names)
    if name == "cell_jump_table":
        f, size = region.va("code_to_cell"), region.sizes.get("code_to_cell", 0)
        ents = struct.unpack("<13I", read_va(elf, va, 52))
        ok = all(f <= e < f + size for e in ents)
        # leads A1..AD; AA (index 9) is a default case in both builds, A9 (index 8)
        # has its own case only where the build draws an A9 row
        a9 = ents[8] != ents[9]
        ok &= a9 == region.a9_row
        return ok, f"13 cases inside code_to_cell {f:#x}+{size:#x}; lead A9 {'has its own case' if a9 else 'is the default case'}"
    if name == "restype_table":
        rows = restype_table(region, elf)
        ok = len(rows) == 38 and [r[0] for r in rows[:len(_RESTYPE_KEYS)]] == list(_RESTYPE_KEYS) \
            and rows[-1][0] == 0x7F000000
        loc = [f"{r[0] >> 16:04x}" for r in rows if r[4]]
        return ok, f"38 types, localized: {' '.join(loc)}"
    if name == "lang_list":
        if region.name == "jp":
            got = read_va(elf, va, 9)
            return got == bytes(range(9)), f"rodata {got.hex()}"
        return _in_section(elf, va, ".bss"), "RAM list (bss)"
    return True, "no content rule"


def _in_section(elf: bytes, va: int, name: str) -> bool:
    sec = elf_sections(elf).get(name)
    return bool(sec) and sec[0] <= va < sec[0] + sec[2]


def verify(region: Region, elf: bytes) -> List[Check]:
    """Every address of the profile against its rule (module docstring)."""
    out: List[Check] = []
    text = region.text_section
    for name, va in region.vas.items():
        spec = SPECS.get(name)
        if spec is None:
            out.append(Check(name, False, "no rule"))
            continue
        try:
            if spec.kind == "func":
                if name == "pair_gate":
                    words = struct.unpack("<4I", read_va(elf, va, 16))
                    if region.pair_gate == "lead_a0":
                        ok = words == JP_GATE
                        out.append(Check(name, ok, f"{va:#x} lead >= 0xA0 gate words {'ok' if ok else words}"))
                    else:
                        ok = words[:2] == US_GATE_HEAD
                        out.append(Check(name, ok, f"{va:#x} two-argument whitelist gate {'ok' if ok else words}"))
                    continue
                k, sha = region.sigs.get(name, (0, ""))
                if not k:
                    out.append(Check(name, False, "no signature recorded"))
                    continue
                got = signature(elf, va, k)
                n = occurrences(elf, text, va, k)
                shared = name in US.sigs and name in JP.sigs and US.sigs[name] == JP.sigs[name]
                ok = got == sha and n == 1
                out.append(Check(name, ok, f"{va:#x} masked {k} words {got} ({'shared by USA and JP' if shared else 'this build'})"
                                           f", {n} occurrence(s) in .text"))
                continue
            detail = []
            ok = True
            if spec.func and name in region.refs:
                ref = region.refs[name]
                f, size = region.va(spec.func), region.sizes.get(spec.func, 0)
                if spec.kind == "insn":
                    w = struct.unpack("<I", read_va(elf, va, 4))[0]
                    good = f <= va < f + size and w >> 26 in (0xA, 0xB) and (w & 0xFFFF) == region.prop_cells
                    ok &= good
                    detail.append(f"{va:#x} in {spec.func}: {'slti' if w >> 26 == 0xA else 'sltiu'} imm {w & 0xFFFF:#x}")
                else:
                    got = address_of(elf, ref)
                    good = f <= ref < f + size and got == va
                    ok &= good
                    detail.append(f"computed at {ref:#x} in {spec.func} ({'ok' if good else got})")
            elif spec.func and spec.kind != "insn" and region.refs:
                ok = False
                detail.append("no reference recorded")
            if spec.kind == "bss":
                good = _in_section(elf, va, ".bss")
                ok &= good
                detail.append("in .bss" if good else "NOT in .bss")
            elif spec.kind == "data":
                good, d = _content_rule(region, name, elf, va)
                ok &= good
                detail.append(d)
            out.append(Check(name, ok, f"{va:#x} " + "; ".join(detail)))
        except ElfError as e:
            out.append(Check(name, False, str(e)))
    return out


def dollar_commands(region: Region, elf: bytes) -> List[Tuple[str, int]]:
    """(name, handler VA) of each $-command, read from the executable."""
    va = region.va("dollar_table")
    out = []
    for i in range(32):
        s, h = struct.unpack("<II", read_va(elf, va + 8 * i, 8))
        if s == 0:
            break
        raw = read_va(elf, s, 16)
        out.append((raw.split(b"\0")[0].decode("ascii", "replace"), h))
    return out


def restype_table(region: Region, elf: bytes) -> List[Tuple[int, int, int, int, int]]:
    """(type key, name-list VA, extension VA, count, localized) of each resource type."""
    va = region.va("restype_table") if "restype_table" in region.vas else region.restype_table_va
    rows = []
    for i in range(64):
        r = struct.unpack("<5I", read_va(elf, va + 20 * i, 20))
        rows.append(r)
        if r[0] == 0x7F000000:
            break
    return rows


def table(region: Region, elf: bytes, name: str, length: int) -> bytes:
    """``length`` bytes of a profile table, read from the executable."""
    return read_va(elf, region.va(name), length)


# signatures (taken from the retail executable; identical in the prototype and JP)
# ASCII -> EUC: the u16 codes for ' ' .. '/' ('　！”＃＄％＆’（）＊＋，−．／')
_ASCII_SIG = bytes.fromhex("a1a1aaa1c9a1f4a1f0a1f3a1f5a1c7a1caa1cba1f6a1dca1a4a1dda1a5a1bfa1")
# resource-type table: the first six u32 type keys, 20-byte stride
_RESTYPE_KEYS = (0x01000000, 0x01010000, 0x01020000, 0x01030000, 0x01100000, 0x01110000)


def _unique(elf: bytes, sig: bytes) -> Optional[int]:
    i = elf.find(sig)
    if i < 0 or elf.find(sig, i + 1) >= 0:
        return None
    return i


def discover(elf: bytes) -> Dict[str, int]:
    """Find the three tables by signature: {locale_table_va, ascii_table_va,
    restype_table_va} for those found exactly once."""
    out: Dict[str, int] = {}
    i = _unique(elf, LOCALE_TABLE)
    if i is not None:
        out["locale_table_va"] = offset_to_va(elf, i)
    i = _unique(elf, _ASCII_SIG)
    if i is not None and i >= 0x40:
        out["ascii_table_va"] = offset_to_va(elf, i - 0x40)       # table starts at byte 0
    first = struct.pack("<I", _RESTYPE_KEYS[0])
    hits = []
    i = elf.find(first)
    while i >= 0:
        if i + 20 * len(_RESTYPE_KEYS) <= len(elf) and all(
                struct.unpack_from("<I", elf, i + 20 * k)[0] == key for k, key in enumerate(_RESTYPE_KEYS)):
            hits.append(i)
        i = elf.find(first, i + 1)
    if len(hits) == 1:
        out["restype_table_va"] = offset_to_va(elf, hits[0])
    return out


# ------------------------------------------------------------------------ CLI

def _cmd_region(a) -> int:
    from disc import Disc
    discs = [Disc(p) for p in a.iso]
    rc = 0
    try:
        for d in discs:
            prof = region_of(d)
            print(f"image   {d.path}")
            print(f"serial  {d.boot_elf_name()}")
            print(f"build   {prof.name}{'' if prof.verified else '  (UNVERIFIED)'}  {prof.note}")
            print(f"exe     sha256 {exe_sha256(d)}")
            print(f"lang    {disc_lang(d, prof)} (index: {lang_of(d)})  codec {prof.codec}  "
                  f"gate {prof.pair_gate}  prop cells {prof.prop_cells:#x}")
            try:
                elf = executable(d)[1]
                found = discover(elf)
                for k in ("locale_table_va", "ascii_table_va", "restype_table_va"):
                    pv, fv = getattr(prof, k), found.get(k)
                    agree = "" if pv is None or fv is None else ("  agrees" if pv == fv else "  DISAGREES")
                    print(f"{k:17} profile {pv and hex(pv)}  found {fv and hex(fv)}{agree}")
                if prof.name != "unknown":
                    checks = verify(prof, elf)
                    bad = [c for c in checks if not c.ok]
                    for c in (checks if a.verbose else bad):
                        print(f"  {'ok  ' if c.ok else 'FAIL'} {c.name:22} {c.detail}")
                    print(f"verify  {len(checks) - len(bad)}/{len(checks)} addresses pass")
                    rc |= bool(bad)
            except ElfError as e:
                print(f"exe     {e}")
            print()
        if warn_mixed(discs):
            rc |= 2                        # a mixed set: export/import/patch would refuse it
    finally:
        for d in discs:
            d.close()
    return int(rc)


def _cmd_resolve(a) -> int:
    from disc import Disc
    with Disc(a.iso) as d:
        for p in a.path:
            print(f"{p} -> {resolve(d, p)}")
    return 0


def add_commands(subparsers) -> None:
    """Register ``region`` (build, language folder, exe hash, address checks) and
    ``resolve`` (engine path with the xx token -> disc path)."""
    p = subparsers.add_parser("region", help="show the build profile, language folder and exe hash of an image")
    p.add_argument("--iso", required=True, action="append",
                   help="image (repeat to check a disc set; exit status: +2 if the set mixes builds, +1 if an address check fails)")
    p.add_argument("--verbose", "-v", action="store_true", help="print every address check, not only failures")
    p.set_defaults(func=_cmd_region)
    p = subparsers.add_parser("resolve", help="resolve engine paths like mnu\\xx\\font0.bin on an image")
    p.add_argument("--iso", required=True)
    p.add_argument("path", nargs="+")
    p.set_defaults(func=_cmd_resolve)


# ------------------------------------------------------------- profile derivation

def _derive(us_elf: bytes, jp_elf: bytes, us_sizes: Dict[str, int], jp_starts: List[int]) -> None:
    """Developer aid (not used at run time): print the sizes, reference instructions,
    signatures and shared content hashes the profiles above store."""
    def jp_size(name):
        va = _JP_VAS[name]
        nxt = min((s for s in jp_starts if s > va), default=va + us_sizes[name])
        return nxt - va
    sizes = {"us": dict(us_sizes), "jp": {n: jp_size(n) for n in us_sizes}}
    for n in us_sizes:
        k = min(SIG_WORDS, us_sizes[n] // 4)
        a, b = masked_at(us_elf, _US_VAS[n], k), masked_at(jp_elf, _JP_VAS[n], k)
        if np.array_equal(a, b):
            sizes["jp"][n] = min(sizes["jp"][n], us_sizes[n]) if sizes["jp"][n] >= us_sizes[n] else sizes["jp"][n]
    print("SIZES", sizes)
    for tag, elf, vas, sz in (("us", us_elf, _US_VAS, sizes["us"]), ("jp", jp_elf, _JP_VAS, sizes["jp"])):
        refs, sigs = {}, {}
        for n, spec in SPECS.items():
            if spec.kind == "func":
                k = min(SIG_WORDS, sz[n] // 4)
                sigs[n] = (k, signature(elf, vas[n], k))
            elif spec.func and spec.kind != "insn":
                f = vas[spec.func]
                for p in range(f, f + sz[spec.func], 4):
                    got = address_of(elf, p)
                    if got is not None and vas[n] <= got < vas[n] + 8:
                        refs[n] = p
                        break
            elif spec.kind == "insn":
                refs[n] = vas[n]
        print(tag.upper(), "REFS", {k: hex(v) for k, v in refs.items()})
        print(tag.upper(), "SIGS", sigs)
    for n, (ln, _s) in SHARED_CONTENT.items():
        a = hashlib.sha1(read_va(us_elf, _US_VAS[n], ln)).hexdigest()[:16]
        b = hashlib.sha1(read_va(jp_elf, _JP_VAS[n], ln)).hexdigest()[:16]
        print("CONTENT", n, ln, a, b, "equal" if a == b else "DIFFER")


# ------------------------------------------------------------------ self-test

def _test_elf() -> bytes:
    """A two-segment ELF holding the three table signatures at known VAs."""
    head = bytearray(0x34)
    head[:6] = b"\x7fELF\x01\x01"
    struct.pack_into("<I", head, 0x1C, 0x34)
    struct.pack_into("<HH", head, 0x2A, 32, 2)
    ph = struct.pack("<8I", 1, 0x1000, 0x120000, 0x120000, 0x200, 0x200, 5, 0x1000) \
        + struct.pack("<8I", 1, 0x1200, 0x300000, 0x300000, 0x400, 0x400, 6, 0x1000)
    body = bytearray(0x1600)
    body[:len(head)] = head
    body[0x34:0x34 + len(ph)] = ph
    body[0x1200 + 0x10:0x1200 + 0x10 + 20] = LOCALE_TABLE                    # VA 0x300010
    body[0x1200 + 0x100 + 0x40:0x1200 + 0x100 + 0x40 + len(_ASCII_SIG)] = _ASCII_SIG   # table VA 0x300100
    for k, key in enumerate(_RESTYPE_KEYS):                                   # VA 0x300300
        struct.pack_into("<I", body, 0x1200 + 0x300 + 20 * k, key)
    # code at 0x120000: lui v0,0x30; addiu v0,v0,0x10 (computes the locale table VA)
    struct.pack_into("<II", body, 0x1000, 0x3C020030, 0x24420010)
    return bytes(body)


def _env_discs():
    import os
    names = (("D1", "XS3_D1"), ("D2", "XS3_D2"), ("PROTO", "XS3_PROTO"), ("JP1", "XS3_JP1"), ("JP2", "XS3_JP2"))
    return {k: os.environ[v] for k, v in names if os.environ.get(v)}


def self_test() -> int:
    import tempfile
    from pathlib import Path

    ok = True

    def check(cond, msg):
        nonlocal ok
        print(("ok    " if cond else "FAIL  ") + msg)
        ok &= bool(cond)

    def raises(fn, exc, msg):
        try:
            fn()
            check(False, msg)
        except exc:
            check(True, msg)

    check(lpath(US, "mnu\\xx\\font0.bin") == "mnu\\us\\font0.bin", "lpath substitutes the engine's xx token")
    check(lpath("jp", "cf\\{lang}\\sc0100.sb") == "cf\\jp\\sc0100.sb", "lpath substitutes {lang}")
    check(lpath("us", "mnu/pse/xx/a.txt") == "mnu/pse/us/a.txt", "lpath keeps / separators")
    check(lpath("us", "ef\\xxx\\a") == "ef\\xxx\\a", "lpath leaves non-token components alone")
    check(candidates("jp", "\\jpg\\xx\\dtimg_0393.jpg") == ["jpg\\jp\\dtimg_0393.jpg", "jpg\\dtimg_0393.jpg"],
          "resolve candidates: language folder first, then the dropped-folder root")
    check(candidates("us", "SLUS_213.89") == ["SLUS_213.89"], "a path without the token is tried as given")
    check(lang_of(["\\mnu\\us\\menutext.txd", "cf\\us\\a.sb"]) == "us", "lang_of: us index")
    check(lang_of(["mnu\\jp\\menutext.txd", "mnu\\us\\menutext.txd"]) == "jp", "lang_of: engine order puts jp first")
    check(lang_of(["mnu\\us\\font0.bin"]) is None, "lang_of: no menutext.txd -> None")
    check(JP.verified and JP.exe_sha256.startswith("b82b6744") and "UNVERIFIED" not in JP.note,
          "JP profile is verified (sha256 b82b6744...), no UNVERIFIED note")
    check(JP.codec == "jp" and JP.pair_gate == "lead_a0" and JP.prop_cells == 0xC0 and not JP.latin1_singles
          and not JP.a9_row and not JP.mono_subtitles and US.codec == "us" and US.prop_cells == 0x180,
          "text rules: JP lead>=0xA0 gate, 192 proportional cells, no Latin-1 singles / A9 row / mono")
    check(set(_US_VAS) == set(_JP_VAS) == set(SPECS), "USA and JP profiles name every address of SPECS")
    check(set(US.sigs) == set(JP.sigs) == {n for n, s in SPECS.items() if s.kind == "func"} - {"pair_gate"},
          "every function but the gate has a masked signature in both profiles")
    shared = sorted(n for n in US.sigs if US.sigs[n] == JP.sigs[n])
    print(f"      {len(shared)} of {len(US.sigs)} function signatures are shared by the two builds")
    check(as_region("jp") is JP and as_region(None) is US, "as_region by name; None = USA")

    elf = _test_elf()
    found = discover(elf)
    check(found == {"locale_table_va": 0x300010, "ascii_table_va": 0x300100, "restype_table_va": 0x300300},
          "discover finds all three tables by signature")
    check(read_va(elf, 0x300010, 20) == LOCALE_TABLE, "read_va maps through PT_LOAD")
    check(address_of(elf, 0x120004) == 0x300010, "address_of follows lui + addiu")
    raises(lambda: read_va(elf, 0x3003FE, 4), ElfError, "a read across a segment end is an error")
    raises(lambda: elf_segments(elf[:0x40]), ElfError, "a truncated ELF is refused")
    m = mask_words(np.array([0x0C060706, 0x3C020030, 0x24420010, 0x27BDFFF0, 0x00851021], dtype=np.uint32))
    check(list(m) == [0x0C000000, 0x3C020000, 0x24420000, 0x27BDFFF0, 0x00851021],
          "mask: jal target, lui and addiu immediates zeroed; sp offsets and R-type kept")

    from iso9660 import IsoImage, make_test_image
    with tempfile.TemporaryDirectory() as td:
        def image(name, serial, exe):
            p = Path(td) / name
            make_test_image(p, [("SYSTEM.CNF", f"BOOT2 = cdrom0:\\{serial};1\r\n".encode()), (serial, exe)])
            return IsoImage(p)

        sha = hashlib.sha256(elf).hexdigest()
        fake = Region("testbuild", "us", ("SLUS_999.98",), exe_sha256=sha, **found)
        global PROFILES
        saved = PROFILES
        PROFILES = PROFILES + (fake,)
        try:
            a = image("a.iso", "SLUS_999.98", elf)
            b = image("b.iso", "SLUS_999.99", elf)                 # same exe, other serial
            c = image("c.iso", "SLUS_999.98", elf + b"patched")    # same serial, other exe
            j = image("j.iso", "SLPS_256.40", elf)                 # JP serial, wrong exe
            check(region_of(a) is fake and detect(a) is fake, "serial + sha256 select a profile")
            check(region_of(c).name == "unknown", "same serial, different executable -> unknown")
            check(region_of(b).name == "unknown", "same executable, unlisted serial -> unknown")
            check(region_of(j).name == "unknown", "the JP serial with another executable -> unknown")
            check(mixed_regions([a, a]) is None, "one build twice is not mixed")
            msg = mixed_regions([a, c])
            check(msg is not None and sha[:16] in msg, "same serial, different exe is flagged, naming the sha")
            raises(lambda: require_known(c, "text-import"), UnknownBuild, "require_known refuses an unknown build")
            check(require_known(a, "x") is fake, "require_known passes a known build")
            check(require_executable(a, "x") is fake, "require_executable passes the exact executable")
            for i in (a, b, c, j):
                i.close()
        finally:
            PROFILES = saved

    discs = _env_discs()
    if not discs:
        print("SKIP  disc checks (set XS3_D1 / XS3_D2 / XS3_PROTO / XS3_JP1 / XS3_JP2)")
    else:
        from disc import Disc
        opened = {k: Disc(p) for k, p in discs.items()}
        want = {"D1": US, "D2": US, "PROTO": PROTO_2006_05, "JP1": JP, "JP2": JP}
        elfs = {}
        for k, d in opened.items():
            prof = detect(d)
            check(prof is want[k], f"{k}: build {prof.name} (exe sha256 {exe_sha256(d)[:16]}...)")
            elf = elfs[k] = executable(d)[1]
            check(read_va(elf, prof.locale_table_va, 20) == LOCALE_TABLE, f"{k}: locale table at {prof.locale_table_va:#x}")
            check(read_va(elf, prof.ascii_table_va + 0x40, 2) == b"\xa1\xa1", f"{k}: ASCII->EUC table, ' ' -> 0xa1a1")
            check(discover(elf) == {"locale_table_va": prof.locale_table_va, "ascii_table_va": prof.ascii_table_va,
                                    "restype_table_va": prof.restype_table_va}, f"{k}: discover agrees with the profile")
            check(lang_of(d) == prof.lang, f"{k}: language folder from the index = {prof.lang}")
            check(require_executable(d, "self-test") is prof, f"{k}: require_executable passes")
            checks = verify(prof, elf)
            bad = [c for c in checks if not c.ok]
            for c in bad:
                print(f"      FAIL {c.name}: {c.detail}")
            check(not bad, f"{k}: {len(checks) - len(bad)}/{len(checks)} profile addresses pass their rule")
            if prof is JP:
                g = verify(prof, elf)
                byname = {c.name: c for c in g}
                check(byname["pair_gate"].ok and byname["prop_gate_printer"].ok and byname["prop_gate_measurer"].ok,
                      f"{k}: gate words at 0x181e48 = lead>=0xA0; prop gates imm 0xC0 at 0x185584 / 0x182c7c")
                check([n for n, _ in dollar_commands(prof, elf)] == list(DOLLAR_NAMES),
                      f"{k}: 18 $-commands: {' '.join(DOLLAR_NAMES)}")
                loc = sorted(r[0] >> 16 for r in restype_table(prof, elf) if r[4])
                check(loc == [0x0102, 0x0600, 0x0601, 0x0700, 0x0800, 0x0900, 0x1000],
                      f"{k}: localized resource types {' '.join(f'{x:04x}' for x in loc)} (esp is not)")
                check(resolve(d, "jpg\\xx\\dtimg_0393.jpg") == "jpg\\dtimg_0393.jpg"
                      and resolve(d, "mnu\\xx\\font0.bin").lower() == "mnu\\jp\\font0.bin"
                      and resolve(d, "cf\\xx\\1220.sb").lower() == "cf\\jp\\1220.sb",
                      f"{k}: resolve: jpg\\xx -> jpg\\ (dropped), mnu\\xx -> mnu\\jp, cf\\xx -> cf\\jp")
                f0 = d.read(resolve(d, "mnu\\xx\\font0.bin"))
                f1 = d.read(resolve(d, "mnu\\xx\\font1.bin"))
                n_paths = sum(1 for _ in d.entries())
                check(hashlib.sha1(f0).hexdigest().startswith("abc98640")
                      and hashlib.sha256(f0).hexdigest().startswith("3b789d9e")
                      and hashlib.sha1(f1).hexdigest().startswith("ffd061a5")
                      and len(d.read(resolve(d, "mnu\\xx\\menutext.txd"))) == 15574
                      and len(d.read(resolve(d, "mg1\\xx\\Message.Dat"))) == 0x7AFB
                      and n_paths == {"JP1": 14138, "JP2": 12183}[k],
                      f"{k}: T3 spot checks via resolve: font0 sha1 abc98640 / sha256 3b789d9e, font1 sha1 "
                      f"ffd061a5, menutext.txd 15,574 B, Message.Dat 0x7AFB; {n_paths} index paths")
            if prof is US:
                check(resolve(d, "jpg\\xx\\dtimg_0393.jpg").lower() == "jpg\\us\\dtimg_0393.jpg",
                      f"{k}: resolve: jpg\\xx -> jpg\\us")
        if "D1" in elfs and "JP1" in elfs:
            same = all(read_va(elfs["D1"], US.va(n), ln) == read_va(elfs["JP1"], JP.va(n), ln)
                       for n, (ln, _s) in SHARED_CONTENT.items())
            check(same, "USA and JP: $han table, extra-kanji lists, nibble/GIF/control tables equal byte for byte")
        pairs = [("D1", "D2", False), ("JP1", "JP2", False), ("D1", "PROTO", True), ("JP1", "D2", True),
                 ("D1", "JP2", True)]
        for x, y, mixed in pairs:
            if x in opened and y in opened:
                msg = mixed_regions([opened[x], opened[y]])
                check((msg is not None) == mixed, f"{x} + {y}: {'flagged as mixed' if mixed else 'one build'}"
                      + (f" ({msg[:60]}...)" if msg and mixed else ""))
        for d in opened.values():
            d.close()
    print("self-test", "passed" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    if sys.argv[1:] == ["--self-test"]:
        sys.exit(self_test())
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    add_commands(ap.add_subparsers(dest="cmd", required=True))
    a = ap.parse_args()
    sys.exit(a.func(a))
