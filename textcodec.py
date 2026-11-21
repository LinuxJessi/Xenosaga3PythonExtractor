"""textcodec.py — bytes of Xenosaga III game text <-> editable text, and back, exactly.

Borrowed from Xenosaga2PythonExtractor/textcodec.py (UsCodec / EucCodec /
SjisCodec, the ``⟦XX⟧`` escape grammar, the block/file forms). What changed:

* the USA pair table is XS3's own, read from SLUS_213.89 FUN_00181e48 (the
  "pair gate" called from the print function FUN_00184b30, and from
  FUN_001828a0 / FUN_00182e90). XS2's list (``font.us_two_byte``) is not used;
* ``NoteCodec`` is new: the scene banks (.sb) also hold developers' notes that
  are never drawn, mostly Shift-JIS (cp932) with some EUC-JP; each string gets
  the reading that is exact for it, and the choice is recorded with the string;
* ``check_typed`` (the font check) is not ported here: the XS3 font module is
  another lane's work;
* ``JpCodec`` is the Japanese retail build's reading (SLPS_256.40/41, gate
  verified by region.verify), see below; ``for_region`` picks the codec from the
  build profile and nothing here guesses per string on JP (M8: an
  EUC-everywhere codec garbles USA text, a Latin fallback garbles JP text).

USA reading (FUN_00181e48 + FUN_00184b30 default case)
------------------------------------------------------
A byte from 0x80 up starts a two-byte character only when the gate accepts
the pair:

    lead A4 or A6       any nonzero trail
    lead A1             trail BD DA DB DF EE F9 FA FB FC
    lead A2             trail A2-A6, AA-AD, F6
    lead A3             trail B0-B9
    lead AD             trail B5-B7

Every other high byte is ONE character, drawn from the font's Latin-1 cell
(code 0xA9xx, trail byte+0x80): 0xF6 is ``ö``, 0xE2 ``â``, 0xAE ``®``.

``UsCodec.to_text`` writes:

* a lone byte 0xA0-0xFF as its Latin-1 character (``Möbius``, ``Château``);
* a gate pair with lead A1, A2, A3 or A6 that is valid EUC-JP as that EUC
  character (``× △ □ ★ ○ ― 【 】 → ♪ ０ Σ``);
* a gate pair with lead A4 as two escapes ``⟦A4⟧⟦A2⟧``: in the USA font
  the kana rows were overwritten with Latin glyphs (fonts lane), so an EUC
  label would mislead;
* AD B5-B7 as ``Ⅰ Ⅱ Ⅲ`` (euc_jis_2004; Python's euc_jp lacks them);
* ``×`` always as its pair A1DF (the retail text uses it in ``<×>``); the lone
  byte 0xD7 is written ``⟦D7⟧`` (the known trap: Latin-1 0xD7 is also ×);
* bytes below 0x20 (except tab/CR/LF in a whole-file text), 0x7F and
  0x80-0x9F as ``⟦XX⟧``.

The game's own tags (``<l2>``, ``<w45>``, ``<f>``, ``<kWORD>``, ``$col..;``,
literal ``\\n``) are plain ASCII and pass through unchanged.

JP reading (SLPS_256.40 0x181e48 + printer 0x1849c8)
------------------------------------------------------
The JP gate is ``lead >= 0xA0`` with the trail unchecked (4 words, pure EUC):
any byte from 0xA0 up consumes the next byte too. 0x80-0x9F are single bytes
drawn as cell 0x7F (a circle); there is no SS2/SS3 (0x8E/0x8F) and no Latin-1.
``JpCodec.to_text`` writes:

* a pair that is exact EUC-JP as that character (``Ａ ０ あ ア 亜 ○ × △ □``:
  A1FB is ○, A1DF ×, A2A4 △, A2A2 □);
* a pair of the NEC row 13 (lead AD: ``① Ⅰ Ⅱ Ⅲ ㈱ №``, 18 Ⅰ/Ⅱ/Ⅲ pairs on the
  discs) through cp932, when the character has no JIS row 1-12 pair of its own;
* any other pair as TWO escapes ``⟦L⟧⟦T⟧`` (the gate took both bytes, so the
  reading never resyncs one byte later: the old resync garbled ``Ⅱ・ヴ`` into
  ``⟦AD⟧供Ε凜Д``);
* lone 0x80-0x9F, control bytes, 0x7F and a lead with no trail as one ``⟦XX⟧``.

``JpCodec.from_text`` refuses what the JP build cannot draw: half-width kana
(``ｱ``: EUC 8E xx; type the full-width ``ア``), JIS X 0212 (EUC 8F xx xx,
e.g. ``é``), Latin-1 letters, and typed pieces that would fuse into one pair
(a raw lead escape followed by a typed character). It accepts the cp932
spellings of row 1-2 symbols (``－ ～ ∥ ￢``, U+FF0D etc.) for the EUC
characters Python names ``− 〜 ‖ ¬``: those type ``ＫＯＳ－ＭＯＳ``.

Every codec here is exact: ``from_text(to_text(b)) == b`` for any bytes.
``UsCodec.from_text`` also refuses typed text whose bytes the game would read
differently (two typed pieces fusing into one gate pair, e.g. ``£°`` = A3 B0 = ``０``).

    python textcodec.py --self-test
"""
from __future__ import annotations

import os
import re
import sys
from typing import Dict, List, NamedTuple, Optional, Tuple

_ESC = re.compile(r"⟦([0-9A-Fa-f]{2})⟧")
HIGH_ESC = re.compile(r"⟦[89A-Fa-f][0-9A-Fa-f]⟧")       # an escaped byte from 0x80 up (not a control code)
_KEEP_IN_FILES = (9, 10, 13)
_SJIS_LEAD = set(range(0x81, 0xA0)) | set(range(0xE0, 0xFD))
EUC = "euc_jp"


class TextError(ValueError):
    pass


class Item(NamedTuple):
    """One editable string of a container, as the per-container APIs return it
    (sb.items, txd.items, njbin.items, msgdat.items, batdat.items, subtitle.items):
    ``key`` is stable within the file, ``raw`` the exact bytes, ``codec`` the
    codec_by_name name that reads them, ``role`` what the string is, ``flags``
    notes such as 'read-only' or 'mid-string pointer'."""
    key: str
    raw: bytes
    codec: str
    role: str = ""
    flags: Tuple[str, ...] = ()


def raw_of(x) -> bytes:
    """bytes from bytes or an Item (rebuild functions accept either)."""
    return x.raw if isinstance(x, Item) else bytes(x)


def _esc(b: int) -> str:
    return f"⟦{b:02X}⟧"


def us_pair(lead: int, trail: int) -> bool:
    """SLUS_213.89 FUN_00181e48: does the USA print function read (lead, trail) as one
    two-byte character?"""
    if trail == 0:
        return False
    if lead in (0xA4, 0xA6):
        return True
    if lead == 0xA1:
        return trail in (0xBD, 0xDA, 0xDB, 0xDF, 0xEE, 0xF9, 0xFA, 0xFB, 0xFC)
    if lead == 0xA2:
        return 0xA2 <= trail <= 0xA6 or trail in (0xAA, 0xAB, 0xAC, 0xAD, 0xF6)
    if lead == 0xA3:
        return 0xB0 <= trail <= 0xB9
    if lead == 0xAD:
        return 0xB5 <= trail <= 0xB7
    return False


def tokens(text: str) -> List[Tuple[str, Optional[int]]]:
    """The text as (character, None) and ("", raw byte) items, in order."""
    out, pos = [], 0
    for m in _ESC.finditer(text):
        out += [(ch, None) for ch in text[pos:m.start()]]
        out.append(("", int(m.group(1), 16)))
        pos = m.end()
    out += [(ch, None) for ch in text[pos:]]
    return out


class Codec:
    """One reading of text bytes. ``file=True`` is for a whole text file: tabs and
    line ends stay as they are; without it they are escapes and a leading ``#`` is
    written ``⟦23⟧`` (in a block file a line starting with ``#`` is a comment)."""
    name = ""

    def _decode(self, s: bytes, file: bool) -> str:
        raise NotImplementedError

    def encode_char(self, ch: str) -> bytes:
        raise NotImplementedError

    def to_text(self, s: bytes, file: bool = False) -> str:
        t = self._decode(s, file)
        if not file and t.startswith("#"):
            t = "⟦23⟧" + t[1:]
        return t

    def from_text(self, text: str) -> bytes:
        out = bytearray()
        for ch, raw in tokens(text):
            if raw is not None:
                out.append(raw)
            elif ord(ch) < 0x80:
                out.append(ord(ch))
            else:
                out += self.encode_char(ch)
        return bytes(out)


def _ascii(b: int, file: bool) -> str:
    keep = (0x20 <= b < 0x7F) or (file and b in _KEEP_IN_FILES)
    return chr(b) if keep else _esc(b)


class MbCodec(Codec):
    """A plain multibyte codec (EUC-JP or Shift-JIS) where any piece that does not
    decode exactly becomes byte escapes."""

    def __init__(self, codec: str, name: str):
        self.codec, self.name = codec, name

    def _size(self, s: bytes, i: int) -> int:
        if self.codec.startswith("euc"):
            return 3 if s[i] == 0x8F else 2
        return 2 if s[i] in _SJIS_LEAD else 1

    def _decode(self, s: bytes, file: bool) -> str:
        out, i, n = [], 0, len(s)
        while i < n:
            b = s[i]
            if b < 0x80:
                out.append(_ascii(b, file))
                i += 1
                continue
            size = self._size(s, i)
            piece = s[i:i + size]
            try:
                ch = piece.decode(self.codec)
                if len(ch) == 1 and ch.encode(self.codec) == piece and ch not in "⟦⟧":
                    out.append(ch)
                    i += size
                    continue
            except UnicodeError:
                pass
            out.append(_esc(b))
            i += 1
        return "".join(out)

    def encode_char(self, ch: str) -> bytes:
        try:
            return ch.encode(self.codec)
        except UnicodeEncodeError:
            raise TextError(f"{ch!r} (U+{ord(ch):04X}) cannot be written in {self.codec}")


def EucCodec() -> MbCodec:
    return MbCodec(EUC, "euc_jp")


def SjisCodec() -> MbCodec:
    return MbCodec("cp932", "cp932")


def _us_pairs() -> Dict[bytes, str]:
    out = {}
    cands = [(0xA1, t) for t in range(0x100)] + [(0xA2, t) for t in range(0x100)]
    cands += [(0xA3, t) for t in range(0x100)] + [(0xA6, t) for t in range(0x100)]
    for a, b in cands:
        if not us_pair(a, b):
            continue
        piece = bytes((a, b))
        try:
            ch = piece.decode(EUC)
        except UnicodeDecodeError:
            continue
        if len(ch) == 1 and ch.encode(EUC) == piece:
            out[piece] = ch
    # AD B5-B7: the Roman numerals of the NEC row, outside Python's euc_jp but in
    # euc_jis_2004 (retail: 'EPISODE Ⅱ Summary 01', 'Woglinde Ⅱ' in DBC.bin)
    for t in (0xB5, 0xB6, 0xB7):
        piece = bytes((0xAD, t))
        out[piece] = piece.decode("euc_jis_2004")
    return out


class UsCodec(Codec):
    """The USA print function's reading (module docstring)."""
    name = "us"
    PAIRS = _us_pairs()
    CHARS = {ch: piece for piece, ch in PAIRS.items()}

    @staticmethod
    def read(s: bytes, i: int) -> int:
        """How many bytes the print function takes as one character at s[i]."""
        if s[i] >= 0x80 and i + 1 < len(s) and us_pair(s[i], s[i + 1]):
            return 2
        return 1

    def _decode(self, s: bytes, file: bool) -> str:
        out, i, n = [], 0, len(s)
        while i < n:
            b = s[i]
            if b < 0x80:
                out.append(_ascii(b, file))
                i += 1
            elif self.read(s, i) == 2:
                ch = self.PAIRS.get(s[i:i + 2])
                out.append(ch if ch else _esc(b) + _esc(s[i + 1]))
                i += 2
            else:
                ch = chr(b)
                out.append(ch if b >= 0xA0 and ch not in self.CHARS else _esc(b))
                i += 1
        return "".join(out)

    def encode_char(self, ch: str) -> bytes:
        if ch in self.CHARS:
            return self.CHARS[ch]
        if 0xA0 <= ord(ch) <= 0xFF:
            return bytes((ord(ch),))
        raise TextError(f"{ch!r} (U+{ord(ch):04X}) cannot be written on the USA build: its print function "
                        f"reads Latin-1 bytes and a few symbol pairs (FUN_00181e48), not Japanese text")

    def from_text(self, text: str) -> bytes:
        """Encode, then check the bytes are read back the way they were typed: two
        typed pieces must not fuse into one gate pair (``£°`` is A3 B0, which the
        game draws as ``０``; ``¦é`` is A6 E9, one A6-row character). Two raw
        escapes may form a pair (that is how the export writes ``⟦A4⟧⟦A2⟧``)."""
        out = bytearray()
        owner: List[int] = []                  # token index of every output byte
        escaped: List[bool] = []
        for ti, (ch, raw) in enumerate(tokens(text)):
            if raw is not None:
                piece = bytes((raw,))
            elif ord(ch) < 0x80:
                piece = bytes((ord(ch),))
            else:
                piece = self.encode_char(ch)
            out += piece
            owner += [ti] * len(piece)
            escaped.append(raw is not None)
        i, n = 0, len(out)
        while i < n:
            if self.read(out, i) == 2:
                a, b = owner[i], owner[i + 1]
                if a != b and not (escaped[a] and escaped[b]):
                    typed = self._decode(bytes(out[i:i + 2]), False)
                    pieces = "".join(ch or _esc(raw) for k, (ch, raw) in enumerate(tokens(text))
                                     if k in (a, b))
                    raise TextError(f"{pieces!r} would be drawn as ONE character {typed!r} (bytes "
                                    f"{out[i]:02X} {out[i + 1]:02X} form a pair the USA print function "
                                    f"reads together, FUN_00181e48); put a space between them, or write "
                                    f"the two bytes as escapes if the pair is meant")
                i += 2
            else:
                i += 1
        return bytes(out)


# ------------------------------------------------------------------ Japan

def _sjis_of_jis(j1: int, j2: int) -> bytes:
    s1 = (j1 + 1) // 2 + (0x70 if j1 <= 0x5E else 0xB0)
    s2 = j2 + (0x1F if j1 % 2 else 0x7E)
    if j1 % 2 and s2 >= 0x7F:
        s2 += 1
    return bytes((s1, s2))


def _jp_tables() -> Tuple[Dict[bytes, str], Dict[str, bytes]]:
    """(pair -> character for decoding, character -> pair for encoding). Decoding:
    exact euc_jp, then NEC row 13 (lead AD) through cp932 for characters that have
    no euc_jp pair. Encoding adds the cp932 spellings of rows 1-8 symbols."""
    dec: Dict[bytes, str] = {}
    enc: Dict[str, bytes] = {}
    for lead in range(0xA1, 0xFF):
        for trail in range(0xA1, 0xFF):
            piece = bytes((lead, trail))
            try:
                ch = piece.decode(EUC)
            except UnicodeDecodeError:
                continue
            if len(ch) == 1 and ch.encode(EUC) == piece and ch not in "⟦⟧":
                dec[piece] = ch
                enc.setdefault(ch, piece)
    for lead in list(range(0xA1, 0xA9)) + [0xAD]:
        for trail in range(0xA1, 0xFF):
            piece = bytes((lead, trail))
            sj = _sjis_of_jis(lead - 0x80, trail - 0x80)
            try:
                ch = sj.decode("cp932")
            except UnicodeDecodeError:
                continue
            if len(ch) != 1 or ch.encode("cp932") != sj or ch in "⟦⟧" or ord(ch) < 0x80:
                continue
            if ch not in enc:
                enc[ch] = piece
                if lead == 0xAD and piece not in dec:
                    dec[piece] = ch
    return dec, enc


class JpCodec(Codec):
    """The Japanese retail print function's reading (module docstring)."""
    name = "jp"
    DEC, ENC = _jp_tables()

    @staticmethod
    def read(s: bytes, i: int) -> int:
        """SLPS_256.40 0x181e48: a byte from 0xA0 up takes the next byte with it."""
        return 2 if s[i] >= 0xA0 and i + 1 < len(s) else 1

    def _decode(self, s: bytes, file: bool) -> str:
        out, i, n = [], 0, len(s)
        while i < n:
            b = s[i]
            if b < 0x80:
                out.append(_ascii(b, file))
                i += 1
            elif self.read(s, i) == 2:
                ch = self.DEC.get(s[i:i + 2])
                out.append(ch if ch else _esc(b) + _esc(s[i + 1]))
                i += 2
            else:
                out.append(_esc(b))
                i += 1
        return "".join(out)

    def encode_char(self, ch: str) -> bytes:
        piece = self.ENC.get(ch)
        if piece is not None:
            return piece
        if 0xFF61 <= ord(ch) <= 0xFF9F:
            import unicodedata
            raise TextError(f"{ch!r} (U+{ord(ch):04X}) is a half-width kana (EUC 8E xx): the Japanese build "
                            f"draws no 8E/8F codes; type the full-width {unicodedata.normalize('NFKC', ch)!r}")
        try:
            raw = ch.encode(EUC)
        except UnicodeEncodeError:
            raw = b""
        if raw[:1] == b"\x8f":
            raise TextError(f"{ch!r} (U+{ord(ch):04X}) is JIS X 0212 (EUC 8F xx xx): the Japanese build "
                            f"draws no 8E/8F codes")
        if 0x80 <= ord(ch) <= 0xFF:
            raise TextError(f"{ch!r} (U+{ord(ch):04X}) cannot be written on the Japanese build: it has no "
                            f"Latin-1 cells (0x80-0x9F draw cell 0x7F, 0xA0 up leads a pair)")
        raise TextError(f"{ch!r} (U+{ord(ch):04X}) has no EUC-JP (JIS X 0208 / NEC row 13) code")

    def from_text(self, text: str) -> bytes:
        """Encode, then check the bytes read back as typed: a raw lead escape
        followed by a typed character would fuse into one pair (two escapes may)."""
        out = bytearray()
        owner: List[int] = []
        escaped: List[bool] = []
        toks = tokens(text)
        for ti, (ch, raw) in enumerate(toks):
            if raw is not None:
                piece = bytes((raw,))
            elif ord(ch) < 0x80:
                piece = bytes((ord(ch),))
            else:
                piece = self.encode_char(ch)
            out += piece
            owner += [ti] * len(piece)
            escaped.append(raw is not None)
        i, n = 0, len(out)
        while i < n:
            if self.read(out, i) == 2:
                a, b = owner[i], owner[i + 1]
                if a != b and not (escaped[a] and escaped[b]):
                    shown = self._decode(bytes(out[i:i + 2]), False)
                    pieces = "".join(ch or _esc(raw) for k, (ch, raw) in enumerate(toks) if k in (a, b))
                    raise TextError(f"{pieces!r} would be read as ONE character {shown!r} (bytes {out[i]:02X} "
                                    f"{out[i + 1]:02X}: the Japanese gate takes the byte after any lead from "
                                    f"0xA0 up); write both bytes as escapes if the pair is meant")
                i += 2
            else:
                i += 1
        return bytes(out)


# ------------------------------------------------------------------ dev notes

def _sjis_signature(s: bytes) -> bool:
    """A Shift-JIS-only byte pattern: a lead 0x81-0x9F, or a lead 0xE0-0xEF with a
    trail below 0xA1 (impossible in EUC-JP)."""
    for i, b in enumerate(s):
        if 0x81 <= b <= 0x9F:
            return True
        if 0xE0 <= b <= 0xEF and i + 1 < len(s) and 0x40 <= s[i + 1] < 0xA1:
            return True
    return False


def _exact(s: bytes, codec: str) -> bool:
    try:
        return s.decode(codec).encode(codec) == s
    except UnicodeError:
        return False


def _japanese_euc(s: bytes) -> bool:
    """Exact EUC-JP with at least one kana or kanji pair (lead A4, A5 or B0 up)."""
    if not _exact(s, EUC):
        return False
    i = 0
    while i < len(s):
        b = s[i]
        if b < 0x80:
            i += 1
            continue
        if b in (0xA4, 0xA5) or b >= 0xB0:
            return True
        i += 3 if b == 0x8F else 2
    return False


class NoteCodec:
    """Developers' strings that are never drawn (.sb scene notes, pse scripts, the
    untranslated EUC-JP .mes files). The reading is chosen per string and stored
    with it; the encoding is its exact inverse.

    ``pick(s)`` -> codec name: ``cp932`` when the bytes carry a Shift-JIS-only
    pattern, decode exactly and read as Japanese; ``euc_jp`` when they are exact
    EUC-JP holding kana or kanji and read as Japanese; else ``us`` (the USA print
    reading). Shift-JIS is tried first only on a Shift-JIS-only byte pattern: the
    EUC-JP notes are mostly also valid cp932 (as half-width katakana soup). Every choice is exact, so
    a wrong guess costs readability, never bytes."""

    CODECS = {"cp932": SjisCodec(), "euc_jp": EucCodec(), "us": UsCodec(),
              # EUC-JP plus the NEC row (Ⅰ Ⅱ Ⅲ at AD B5-B7) Python's euc_jp lacks
              "euc_jis_2004": MbCodec("euc_jis_2004", "euc_jis_2004")}

    @staticmethod
    def japanese(text: str) -> bool:
        """Does a decoded reading look like Japanese rather than English with a few
        Latin-1 letters misread as double-byte (``Ch\xe2teau`` is a valid cp932
        pair E2 74)? At least two CJK/kana/full-width characters (or one and no
        ASCII letters), and no more than three ASCII letters per such character."""
        cjk = sum(1 for ch in text if ord(ch) >= 0x3000)
        letters = sum(1 for ch in text if ch.isascii() and ch.isalpha())
        return (cjk >= 2 or (cjk == 1 and letters == 0)) and cjk * 3 >= letters

    @classmethod
    def pick(cls, s: bytes) -> str:
        if _sjis_signature(s) and _exact(s, "cp932") and cls.japanese(s.decode("cp932")):
            return "cp932"
        if _japanese_euc(s) and cls.japanese(s.decode(EUC)):
            return "euc_jp"
        return "us"

    @classmethod
    def pick_euc(cls, s: bytes) -> Optional[str]:
        """``euc_jp`` or ``euc_jis_2004`` when ``s`` is untranslated EUC Japanese
        (exact in that codec, with kana or kanji, reading as Japanese), else None."""
        if _japanese_euc(s) and cls.japanese(s.decode(EUC)):
            return "euc_jp"
        if _exact(s, "euc_jis_2004") and any(b in (0xA4, 0xA5) or b >= 0xB0 for b in s if b >= 0x80) \
                and cls.japanese(s.decode("euc_jis_2004")):
            return "euc_jis_2004"
        return None

    @classmethod
    def codec(cls, name: str) -> Codec:
        try:
            return cls.CODECS[name]
        except KeyError:
            raise TextError(f"unknown text codec {name!r}")

    @classmethod
    def to_text(cls, s: bytes, file: bool = False, name: Optional[str] = None) -> Tuple[str, str]:
        name = name or cls.pick(s)
        return name, cls.codec(name).to_text(s, file)

    @classmethod
    def from_text(cls, text: str, name: str) -> bytes:
        return cls.codec(name).from_text(text)


_JP = JpCodec()


def codec_by_name(name: str) -> Codec:
    if name == "jp":
        return _JP
    return NoteCodec.codec(name)


def for_region(region) -> Codec:
    """The display codec of a build profile (region.Region, a profile name, or None
    for USA): ``region.codec`` is 'us' (SLUS_213.89/214.17 and the May 2006
    prototype: the whitelist gate) or 'jp' (SLPS_256.40/41: lead >= 0xA0)."""
    import region as _region
    return codec_by_name(_region.as_region(region).codec)


def codec_name_for(region) -> str:
    import region as _region
    return _region.as_region(region).codec


def for_build(build: str) -> Codec:
    """Older spelling of ``for_region`` (a build name)."""
    return _JP if build == "jp" else UsCodec()


# ------------------------------------------------------------------ font coverage (JP brief T7)

def jp_font_coverage(disc):
    """(pairs per container, missing pair -> (count, first container)) for every
    two-byte character the JP gate reads in the parsed JP strings (.sb, .txd,
    mnu .bin, Message.Dat, batdat.bin, subtitle/.mes lines that are not ``;``
    comments), resolved through the code->cell map (font.Addressing, read from the
    disc's executable) to an inked cell of font0 (with its extra list) or font1
    (with its list). Retail result: everything resolves except A1A1 (the
    full-width space, a blank cell) and E5D0 縊 in bat\\jp\\RAV_B02.sb #0017, which
    neither font draws (cell 0x7F)."""
    import collections
    import font as _font
    import region as _region
    import sb as _sb, txd as _txd, njbin as _nj, msgdat as _mg, batdat as _bd, subtitle as _sub
    reg = _region.detect(disc)
    lang = reg.lang
    addr = _font.Addressing.from_executable(_region.executable(disc)[1])
    inks = []
    for k in (0, 1):
        cells = _font.font_cells(_font.Font.from_bytes(disc.read(_region.resolve(disc, f"mnu\\xx\\font{k}.bin", reg))))
        inks.append(cells.reshape(len(cells), -1).any(axis=1))
    total: Dict[str, int] = collections.Counter()
    missing: Dict[bytes, list] = {}
    nj_names = {n.lower() for n in _nj.NAMES}

    def scan(kind: str, raw: bytes):
        i = 0
        while i < len(raw):
            k = _JP.read(raw, i)
            if k == 2:
                total[kind] += 1
                good = False
                for f in (0, 1):
                    c = addr.cell(raw[i], raw[i + 1], f) & 0xFFF
                    good |= c != 0x7F and bool(inks[f][c])
                if not good:
                    m = missing.setdefault(bytes(raw[i:i + 2]), [0, kind])
                    m[0] += 1
            i += k

    for _c, e in disc.entries():
        p = e.path.lower().lstrip("\\")
        if p.endswith(".sb"):
            for x in _sb.parse(disc.read_entry(e), reg).strings:
                scan("sb", x)
        elif p.endswith(".txd"):
            for x in _txd.parse(disc.read_entry(e), reg).strings:
                scan("txd", x)
        elif p.startswith(f"mnu\\{lang}\\") and p.rsplit("\\", 1)[-1] in nj_names:
            for it in _nj.parse(disc.read_entry(e), reg).items:
                scan("bin", it.raw)
        elif p == f"mg1\\{lang}\\message.dat":
            for x in _mg.parse(disc.read_entry(e), reg).strings:
                scan("mg1", x)
        elif p == f"bat\\{lang}\\batdat.bin":
            for it in _bd.parse(disc.read_entry(e), reg).items:
                scan("batdat", it.raw)
        elif _sub.role(e.path, reg) in ("movie", "event", "pse-mes"):
            for ln in disc.read_entry(e).split(b"\n"):
                if not ln.startswith(b";"):
                    scan("subtitle", ln)
    return total, {k: tuple(v) for k, v in missing.items()}


# ------------------------------------------------------------------ self-test

def _disc_strings(iso: str):
    """Every string textpack would export from one disc (for the exhaustive check)."""
    import textpack
    disc = textpack.IndexDisc(iso)
    for path, kind in textpack.collect(disc.paths()):
        data = disc.read(path)
        for key, s, codec in textpack.KINDS[kind].strings(path, data):
            yield path, key, s, codec


def self_test() -> int:
    ok = True

    def check(cond, msg):
        nonlocal ok
        print(("ok    " if cond else "FAIL  ") + msg)
        ok &= bool(cond)

    us, euc, sj = UsCodec(), EucCodec(), SjisCodec()
    every = bytes(range(256)) * 2 + bytes(range(255, -1, -1)) + b"\xa4\xa2\xa1\xdf\xa1\xa1\xa2\xf6\xad\xb5\xd7"
    check(all(c.from_text(c.to_text(every)) == every and c.from_text(c.to_text(every, file=True)) == every
              for c in (us, euc, sj, JpCodec())), "every codec is exact on arbitrary bytes, block and file form")
    for name in ("cp932", "euc_jp", "us"):
        check(NoteCodec.from_text(NoteCodec.to_text(every, name=name)[1], name) == every,
              f"NoteCodec[{name}] is exact on arbitrary bytes")
    check(us.to_text(b"M\xf6bius Hotel") == "Möbius Hotel" and us.from_text("Möbius Hotel") == b"M\xf6bius Hotel",
          "USA: Möbius (lone 0xF6 = ö)")
    check(us.to_text(b"Rennes-le-Ch\xe2teau") == "Rennes-le-Château", "USA: Château (lone 0xE2 = â)")
    check(us.to_text(b"Xenosaga\xae") == "Xenosaga®", "USA: ® (lone 0xAE)")
    check(us.to_text(b"<\xa2\xa4> button") == "<△> button" and us.from_text("<△> button") == b"<\xa2\xa4> button",
          "USA: <△> is the pair A2A4")
    check(us.to_text(b"<\xa1\xdf>") == "<×>" and us.from_text("<×>") == b"<\xa1\xdf>",
          "USA: × is the pair A1DF (the trap)")
    check(us.to_text(b"5\xd7") == "5⟦D7⟧" and us.from_text("5⟦D7⟧") == b"5\xd7", "USA: a lone 0xD7 is ⟦D7⟧")
    check(us.to_text(b"Erde Kaiser \xa6\xb2") == "Erde Kaiser Σ", "USA: Σ is the A6 pair A6B2")
    check(us.to_text(b"\xa4\xa2") == "⟦A4⟧⟦A2⟧", "USA: A4 pairs are escapes")
    check(us.to_text(b"EPISODE\xad\xb6Summary") == "EPISODEⅡSummary" and us.from_text("Ⅰ Ⅱ Ⅲ") == b"\xad\xb5 \xad\xb6 \xad\xb7",
          "USA: AD B5-B7 read and type as Ⅰ Ⅱ Ⅲ")
    for typed, shown in (("£°", "０"), ("¡½", "―"), ("¦é", "⟦A6⟧⟦E9⟧"), ("¤a", "⟦A4⟧⟦61⟧"), ("£⟦B0⟧", "０")):
        try:
            us.from_text("x" + typed + "y")
            check(False, f"USA: typed {typed!r} (would be drawn as {shown!r}) is refused")
        except TextError:
            check(True, f"USA: typed {typed!r} (would be drawn as {shown!r}) is refused")
    check(us.from_text("⟦A4⟧⟦A2⟧") == b"\xa4\xa2" and us.from_text("£ °") == b"\xa3 \xb0",
          "USA: a pair written as two escapes is kept; a space keeps £ and ° apart")
    check(us.to_text(b"\xa3\xb5\xa2\xaa\xa1\xee") == "５→℃", "USA: A3B0-B9, A2AA-AD, A1EE are accepted pairs")
    check(us.to_text(b"\xa1\xa2") == "¡¢", "USA: A1A2 is not a gate pair: two Latin-1 characters")
    check(us.to_text(b"\x85\x01\x7f") == "⟦85⟧⟦01⟧⟦7F⟧", "USA: 0x80-0x9F, control bytes and 0x7F are escapes")
    check(us.to_text(b"#1") == "⟦23⟧1" and us.to_text(b"#1", file=True) == "#1", "leading # is ⟦23⟧ in block form")
    check(us.to_text(b"a\r\nb", file=True) == "a\r\nb" and us.to_text(b"a\r\nb") == "a⟦0D⟧⟦0A⟧b",
          "file form keeps line ends; block form escapes them")
    try:
        us.from_text("あ")
        check(False, "USA: kana cannot be typed")
    except TextError:
        check(True, "USA: kana cannot be typed")
    note = "＊BGM設定＊".encode("cp932")
    check(NoteCodec.to_text(note) == ("cp932", "＊BGM設定＊"), "notes: a Shift-JIS note reads as cp932")
    enote = "ここでテスト".encode(EUC)
    check(NoteCodec.to_text(enote) == ("euc_jp", "ここでテスト"), "notes: an EUC-JP note reads as euc_jp")
    check(NoteCodec.pick(b"Erde Kaiser \xa6\xb2") == "us", "notes: English with a Greek pair stays us")
    check(NoteCodec.pick(b"[Canaan]this object is called Rennes-le-\\nCh\xe2teau.<f>") == "us",
          "notes: English whose Latin-1 letter is also a cp932 pair (E2 74) stays us")
    check(NoteCodec.pick("（遺跡）".encode(EUC)) == "euc_jp", "notes: an EUC note that is also valid cp932 reads as EUC")

    jp = JpCodec()
    check(jp.from_text("Ⅱ") == b"\xad\xb6" and jp.to_text(b"\xad\xb6") == "Ⅱ", "JP: Ⅱ = AD B6 (NEC row 13)")
    check(jp.to_text(b"\xad\xb6\xa1\xa6\xa5\xf4") == "Ⅱ・ヴ", "JP: Ⅱ・ヴ decodes (no resync after the AD lead)")
    check(jp.from_text("ＫＯＳ－ＭＯＳ") == b"\xa3\xcb\xa3\xcf\xa3\xd3\xa1\xdd\xa3\xcd\xa3\xcf\xa3\xd3",
          "JP: ＫＯＳ－ＭＯＳ types (cp932 － = A1DD)")
    check(jp.from_text("￢") == b"\xa2\xcc" and jp.from_text("～∥￠￡") == b"\xa1\xc1\xa1\xc2\xa1\xf1\xa1\xf2",
          "JP: cp932 spellings ￢ (even row: A2CC, not A2CD ⇒) and ～∥￠￡ type to their JIS pairs")
    agree = n = 0
    for j1 in range(0x21, 0x75):
        for j2 in range(0x21, 0x7F):
            try:
                want = bytes((j1 | 0x80, j2 | 0x80)).decode(EUC).encode("shift_jis")
            except UnicodeError:
                continue
            n += 1
            agree += _sjis_of_jis(j1, j2) == want
    check(n > 6000 and agree == n, f"JP: _sjis_of_jis agrees with Python's shift_jis on all {n} JIS X 0208 pairs")
    check([jp.to_text(bytes.fromhex(h)) for h in ("a1fb", "a1df", "a2a4", "a2a2")] == ["○", "×", "△", "□"],
          "JP: A1FB ○, A1DF ×, A2A4 △, A2A2 □")
    check(jp.to_text(b"\xa4\x41") == "⟦A4⟧⟦41⟧" and jp.from_text("⟦A4⟧⟦41⟧") == b"\xa4\x41",
          "JP: a lead with a low trail is still one pair: two escapes")
    check(jp.to_text(b"\x85\xa0\xa1x") == "⟦85⟧⟦A0⟧⟦A1⟧x" and jp.to_text(b"a\xb0") == "a⟦B0⟧",
          "JP: lone 0x80-0x9F one escape; A0 lead pair two escapes; a lead at the end one escape")
    check(jp.to_text(b"\x8e\xb1") == "⟦8E⟧⟦B1⟧", "JP: 8E is not an SS2 prefix")
    for typed, why in (("ｱ", "half-width kana"), ("é", "JIS X 0212 / Latin-1 accent"), ("ö", "Latin-1"),
                       ("⟦A4⟧A", "a raw lead fusing with a typed byte")):
        try:
            jp.from_text(typed)
            check(False, f"JP: {typed!r} is refused ({why})")
        except TextError:
            check(True, f"JP: {typed!r} is refused ({why})")
    check(not any(p[0] in (0x8E, 0x8F) for p in JpCodec.ENC.values()), "JP: the encoder never emits 8E/8F")
    import region as _region
    check(isinstance(for_region(_region.JP), JpCodec) and isinstance(for_region("us"), UsCodec)
          and isinstance(for_region(_region.PROTO_2006_05), UsCodec), "for_region: JP -> JpCodec, USA/proto -> UsCodec")

    for env in ("XS3_JP1", "XS3_JP2"):
        iso = os.environ.get(env)
        if not iso:
            continue
        import sb as _sb
        from disc import Disc
        n = bad = esc = nec = raw_nec = 0
        with Disc(iso) as d:
            for _c, e in d.entries():
                if not e.path.lower().endswith(".sb"):
                    continue
                for x in _sb.parse(d.read_entry(e)).strings:
                    t = jp.to_text(x)
                    n += 1
                    bad += jp.from_text(t) != x
                    esc += "⟦" in t
                    nec += sum(t.count(c) for c in "ⅠⅡⅢ")
                    i = 0
                    while i < len(x):
                        k = jp.read(x, i)
                        raw_nec += k == 2 and x[i] == 0xAD and 0xB5 <= x[i + 1] <= 0xB7
                        i += k
        check(n > 0 and bad == 0 and esc == 0 and nec == raw_nec > 0,
              f"{env}: JpCodec exact on all {n} .sb strings, {esc} with escapes, "
              f"{nec} Ⅰ/Ⅱ/Ⅲ decoded of {raw_nec} AD B5-B7 pairs")
        with Disc(iso) as d:
            total, missing = jp_font_coverage(d)
        check(set(missing) == {b"\xa1\xa1", b"\xe5\xd0"},
              f"{env}: T7 font coverage: {sum(total.values())} pairs ({dict(total)}) resolve to inked JP font "
              f"cells except " + ", ".join(f"{k.hex().upper()} x{v[0]} ({v[1]})" for k, v in sorted(missing.items())))

    disc_vars = [(k, os.environ.get(k)) for k in ("XS3_D1", "XS3_D2", "XS3_PROTO")]
    if not any(v for _, v in disc_vars):
        print("SKIP  disc checks (set XS3_D1 / XS3_D2 / XS3_PROTO)")
    for env, iso in disc_vars:
        if not iso:
            continue
        n = bad = 0
        found = {}
        for path, key, s, cname in _disc_strings(iso):
            c = codec_by_name(cname)
            file = key == "*"
            n += 1
            t = c.to_text(s, file)
            if c.from_text(t) != s:
                bad += 1
                if bad < 4:
                    print("      mismatch", path, key, s[:40])
            for w in ("Möbius", "Château", "®", "<△>", "<×>"):
                if w in t:
                    found.setdefault(w, (path, key))
        check(n > 0 and bad == 0, f"{env}: decode/encode exact on all {n} strings ({bad} mismatches)")
        if env != "XS3_PROTO" or found:
            check(all(w in found for w in ("Möbius", "Château", "®", "<△>", "<×>")),
                  f"{env}: Möbius/Château/®/<△>/<×> decode readably: "
                  + ", ".join(f"{w}@{p}" for w, (p, _) in sorted(found.items())))
    print("self-test", "passed" if ok else "FAILED")
    return 0 if ok else 1


def add_commands(subparsers) -> None:
    """textcodec has no disc command of its own; ``text-decode`` shows how the USA
    codec reads a hex byte string (a debugging aid)."""
    p = subparsers.add_parser("text-decode", help="show how the XS3 codecs read a hex byte string")
    p.add_argument("hex")
    p.add_argument("--codec", default="us", choices=["us", "cp932", "euc_jp", "jp", "note"],
                   help="us = USA/prototype print reading, jp = Japanese retail print reading")

    def run(a):
        b = bytes.fromhex(a.hex)
        if a.codec == "note":
            name, t = NoteCodec.to_text(b)
            print(f"{name}: {t}")
        else:
            print(codec_by_name(a.codec).to_text(b))
        return 0
    p.set_defaults(func=run)


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    if sys.argv[1:] == ["--self-test"]:
        sys.exit(self_test())
    print(__doc__)
