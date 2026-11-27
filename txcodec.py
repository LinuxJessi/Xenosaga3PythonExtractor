"""txcodec.py — the translation editor's text form for Episode III, and its checks.

The Episode I editor's ``txcodec`` (accent block, #XX codes, font0/font1
swap) is specific to that game. This module keeps its NAMES and return
shapes, so ``txserver`` and the page run unchanged, and builds them on the
Episode III kit's own text rules:

    textcodec    the exact codecs: ``us`` (the USA print function's reading:
                 Latin-1 single bytes + a few symbol pairs), ``jp`` (EUC pairs),
                 ``cp932`` / ``euc_jp`` (developers' notes, never drawn)
    textpack.FontCheck   can the disc being translated draw a typed character
                 (the executable's code -> cell rules and the ink of
                 font0/font1 of that disc)
    font.Measurer        the width the game computes (FUN_001828a0)
    langpack.render_bytes  a line drawn from the disc's font cells

Display form (what the editor shows and the translator types)
-------------------------------------------------------------
``textcodec``'s text, with one change: the game's line break, which is the
two characters backslash + n in the data, is a real line break in the
editor. Everything else is as the text-export tree shows it: ``[Speaker]``
at the start of a dialogue line, ``<f>`` ``<w30>`` ``<l2>`` ``<kWORD>``
tags, ``$col...;`` commands, ``⟦XX⟧`` for a raw byte.

A catalog row's ``ctl`` names its codec (``us``, ``jp``, ``cp932``,
``euc_jp``); ``ctl`` ending in ``.f`` is a row cut from a whole text file
(a ``.mes`` message), where a line break is the file's own line end. A row's
``font`` is ``field`` when the game draws it (the font check applies) and
``note`` when it never does (developers' notes; the text only has to encode).

Because the font check depends on the disc, every check is for ONE disc: the
``ctx`` argument when it is given (the family modules pass theirs), else the
disc of the current scope. A scope is ``with disc(iso):`` (or ``use_disc(iso)``
for a single-threaded tool) and lives in a ``contextvars.ContextVar``: it is
per thread and per task, so two editor tabs on different builds, served by two
threads of one server, never see each other's disc. A thread that has entered
no scope has no disc (the USA codec rules, no ink check), never "the disc some
other request opened last". The permission to encode new-letter glyph codes
(``glyph_codes()``) is scoped the same way.

    python txcodec.py selftest [--iso DISC]
"""
from __future__ import annotations

import argparse
import contextvars
import re
import sys
import threading
import unicodedata
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import textcodec  # noqa: E402

FIELD, ASCII, BATTLE, NOTE = "field", "ascii", "battle", "note"
FONT0, FONT1 = "font0", "font1"
FILE_SUFFIX = ".f"


class TxEncodeError(ValueError):
    def __init__(self, problems: List[Tuple[int, str, str]]):
        self.problems = problems
        super().__init__("; ".join(f"pos {p}: {c!r}: {m}" for p, c, m in problems[:5])
                         + (f" (+{len(problems) - 5} more)" if len(problems) > 5 else ""))


class TxBuildError(RuntimeError):
    """Raised by the family modules when a build must not write anything."""


# -- tokens ------------------------------------------------------------------------
_TOKRUN_RE = re.compile("(?:⟦[0-9A-Fa-f]{2}⟧)+")
_CTLTOK_RE = re.compile("⟦[01][0-9A-Fa-f]⟧|⟦7[Ff]⟧")          # control bytes only
_TAG_RE = re.compile(r"<[^<>\n]{1,40}>")
_TAG_RAW_RE = re.compile(rb"<[^<>\n]{1,40}>")
_KWORD_RAW_RE = re.compile(rb"<k([^<>\n]*)>")
KEYWORD_PAD = 19                       # px the game adds to a keyword's own width (FUN_002730d0: + 0x13)
_LTAG_RE = re.compile(r"<l(\d+)>")
_CMD_RE = re.compile(r"\$[a-z]+[0-9A-Fa-f,+\-]*;")
_BS_RE = re.compile(r"\\(?:\d{1,3}|[A-Za-z])")
_PRINTF_RE = re.compile(r"%[-+0#]*\d*(?:\.\d+)?[lh]?[diouxXcsfegb]")
_SPEAKER_RE = re.compile(r"^\[[^\]\n/]{1,60}\]")
_SPEAKER_RAW_RE = re.compile(rb"^\[[^\]\0\n/]{1,60}\]")

# -- new-script glyph codes (the editor's per-row check only) ---------------------
# As on Episode I, a letter the build will draw into a font cell is carried as a
# private-use character, one per code, accepted only inside ``glyph_codes()``.
# Episode III builds never hand these to a family module (``langpack`` writes
# its codes as ``⟦XX⟧`` escapes in the encoded tree); the server's row check
# uses them to count bytes and to keep the font check off letters the build
# will draw.
GLYPH_BASE = 0xF0000
_GLYPH_CODES_ON = contextvars.ContextVar("xs3tx_glyph_codes", default=0)     # per thread / task


def glyph_char(code: int) -> str:
    if not (0 < code <= 0xFFFF):
        raise ValueError(f"glyph code {code:#x} out of range")
    return chr(GLYPH_BASE + code)


def glyph_code(ch: str) -> Optional[int]:
    o = ord(ch) - GLYPH_BASE
    return o if 0 < o <= 0xFFFF else None


class glyph_codes:
    """Context manager: accept glyph characters in from_display/check (nests)."""

    def __enter__(self):
        self._tok = _GLYPH_CODES_ON.set(_GLYPH_CODES_ON.get() + 1)
        return self

    def __exit__(self, *exc):
        _GLYPH_CODES_ON.reset(self._tok)
        return False


def escape_glyphs(text: str) -> str:
    """Inside ``glyph_codes()``: each glyph character as its two ``⟦XX⟧`` bytes
    (the form textcodec writes exactly); any other text unchanged."""
    if not _GLYPH_CODES_ON.get() or not any(glyph_code(c) is not None for c in text):
        return text
    return "".join(f"⟦{glyph_code(c) >> 8:02X}⟧⟦{glyph_code(c) & 0xFF:02X}⟧" if glyph_code(c) is not None else c
                   for c in text)


def char_name(ch: str) -> str:
    try:
        return unicodedata.name(ch).lower()
    except ValueError:
        return f"U+{ord(ch):04X}"


def _shown(ch: str) -> str:
    return f"{ch!r} ({char_name(ch)})" if ch else "''"


# -- disc context --------------------------------------------------------------------

class Context:
    """One disc set's text rules: build, display codec, font check, measurers."""

    def __init__(self, iso: str):
        import font as fontmod
        import region as regionmod
        import textpack
        from disc import Disc
        self.iso = iso
        with Disc(iso) as d:
            self.region = regionmod.require_known(d, "the translation editor")
            self.check = textpack.FontCheck.from_disc(d, self.region)
            self.addr = self.check.addr
            self.fonts = [fontmod.Font.from_bytes(d.read(regionmod.resolve(d, f"mnu\\xx\\font{k}.bin", self.region)))
                          for k in (0, 1)]
        self.display = self.region.codec
        self.faces = {f"font{k}": Face(self, k) for k in (0, 1)}

    def why_not(self, codec: str, ch: str) -> Optional[str]:
        return self.check.why_not(codec, ch)


class Face:
    """font0 or font1 of one disc: measures and draws game bytes in the
    ``$prop1;$han1;`` state the menus and dialogue use."""

    def __init__(self, ctx: Context, k: int):
        self.ctx, self.k, self.font = ctx, k, ctx.fonts[k]
        self.metrics = self.font.metrics

    def width_of_bytes(self, data: bytes) -> int:
        """Pixel width of one line. The speaker prefix and the control tags are
        not drawn in the line; a ``<kWORD>`` keyword is: the game leaves a gap of
        the word's width + 19 px for it (FUN_002730d0, USA) and draws the word
        there."""
        data = _SPEAKER_RAW_RE.sub(b"", data)
        n_kw = len(_KWORD_RAW_RE.findall(data))
        data = _TAG_RAW_RE.sub(b"", _KWORD_RAW_RE.sub(lambda m: m.group(1), data))
        try:
            return self.ctx.addr.measurer(self.metrics, prop=True, han=True, font=self.k).width(data) + KEYWORD_PAD * n_kw
        except Exception:                  # noqa: BLE001 - a string the measurer rejects (a '$' with no ';')
            return 0                       # has no width guide; it is never a reason to refuse text


_CTX: Dict[tuple, Context] = {}
_ACTIVE: "contextvars.ContextVar[Optional[Context]]" = contextvars.ContextVar("xs3tx_disc", default=None)
_CTX_LOCK = threading.Lock()


def context(iso: str) -> Context:
    import os
    p = str(Path(iso).expanduser().resolve())
    st = os.stat(p)
    key = (p, st.st_size, st.st_mtime_ns)
    with _CTX_LOCK:
        c = _CTX.get(key)
        if c is None:
            c = _CTX[key] = Context(p)
        return c


def use_disc(iso: Optional[str]) -> Optional[Context]:
    """Make ``iso`` the disc of THIS thread's scope from here on (a
    single-threaded tool: a build, a self-test). A server request uses
    ``with disc(iso):`` so the scope ends with the request."""
    ctx = context(iso) if iso else None
    _ACTIVE.set(ctx)
    return ctx


def set_active(ctx: Optional[Context]) -> None:
    """``use_disc`` for a Context already in hand."""
    _ACTIVE.set(ctx)


class disc:
    """``with disc(iso):`` the checks that are not told which disc they are for
    use ``iso`` inside the block, in this thread only; the scope before it comes
    back on exit, also after an exception. ``iso`` None = no disc (USA codec
    rules). Accepts a Context too."""

    def __init__(self, iso):
        self._iso = iso

    def __enter__(self) -> Optional[Context]:
        ctx = self._iso if isinstance(self._iso, Context) else (context(self._iso) if self._iso else None)
        self._tok = _ACTIVE.set(ctx)
        return ctx

    def __exit__(self, *exc):
        _ACTIVE.reset(self._tok)
        return False


def active() -> Optional[Context]:
    return _ACTIVE.get()


def load_fonts(iso: str) -> Dict[str, Face]:
    """{"font0": Face, "font1": Face} of the disc. A pure lookup: it does not
    change the scope's disc."""
    return context(iso).faces


# -- display form ----------------------------------------------------------------------

def split_ctl(ctl: str, ctx: Optional[Context] = None) -> Tuple[str, bool]:
    """(codec name, is a whole-file row) of a row's ``ctl``."""
    ctl = ctl or "us"
    if ctl.endswith(FILE_SUFFIX):
        return ctl[:-len(FILE_SUFFIX)], True
    if ctl == "c0":                    # the Episode I default: read as the build's codec
        c = ctx or active()
        return (c.display if c else "us"), False
    return ctl, False


def to_display(raw: bytes, ctl: str = "us", font: str = FIELD, face: str = FONT0) -> str:
    name, file = split_ctl(ctl)
    t = textcodec.codec_by_name(name).to_text(raw, file=file)
    if file:
        return t.replace("\r\n", "\n")
    return t.replace("\\n", "\n")


def _typed(text: str, file: bool) -> str:
    text = unicodedata.normalize("NFC", text).replace("\r\n", "\n").replace("\r", "\n")
    return text.replace("\n", "\r\n") if file else text.replace("\n", "\\n")


def from_display(text: str, font: str = FIELD, ctl: str = "us", face: str = FONT0,
                 keep: str = "", ctx: Optional[Context] = None) -> Tuple[bytes, List[str]]:
    """Display text -> (game bytes, warnings). Raises TxEncodeError listing every
    character that cannot be written, or (``font`` = field) that the disc's
    fonts cannot draw. ``keep`` = characters exempt from the font check (the
    ones the original string already held, as text-import does)."""
    ctx = ctx or active()
    name, file = split_ctl(ctl, ctx)
    codec = textcodec.codec_by_name(name)
    problems: List[Tuple[int, str, str]] = []
    warnings: List[str] = []
    out_text: List[str] = []
    typed = _typed(text, file)
    pos = 0
    for ch, rawb in textcodec.tokens(typed):
        if rawb is not None:
            out_text.append(f"⟦{rawb:02X}⟧")
            pos += 4
            continue
        if glyph_code(ch) is not None:
            code = glyph_code(ch)
            if not _GLYPH_CODES_ON.get():
                problems.append((pos, ch, "private-use character (new-letter codes exist only inside a build)"))
            elif code < 0x100:
                problems.append((pos, ch, "single-byte glyph code: Episode III font codes are two bytes"))
            else:
                out_text.append(f"⟦{code >> 8:02X}⟧⟦{code & 0xFF:02X}⟧")
            pos += 1
            continue
        if ord(ch) >= 0x80:
            try:
                codec.encode_char(ch)
            except textcodec.TextError as e:
                problems.append((pos, ch, str(e)))
                pos += 1
                continue
            if font == FIELD and ctx is not None and name == ctx.display and ch not in keep and ch != "\u3000":
                why = ctx.why_not(name, ch)
                if why:
                    problems.append((pos, ch, why))
        out_text.append(ch)
        pos += 1
    if problems:
        raise TxEncodeError(problems)
    try:
        data = codec.from_text("".join(out_text))
    except textcodec.TextError as e:
        raise TxEncodeError([(0, "", str(e))])
    if b"\x00" in data:
        raise TxEncodeError([(0, "", "a NUL byte (⟦00⟧) inside a string; the game would stop reading there")])
    return data, warnings


def draws_natively(ch: str, font: str = FIELD, face: str = FONT0, ctx: Optional[Context] = None) -> bool:
    """Can the active disc (or the USA rules when none is open) draw ``ch``
    without a new glyph?"""
    if ord(ch) < 0x80:
        return True
    ctx = ctx or active()
    if ctx is not None:
        return ctx.why_not(ctx.display, ch) is None
    try:
        textcodec.codec_by_name("us").encode_char(ch)
        return True
    except textcodec.TextError:
        return False


# -- protected tokens / checker ----------------------------------------------------

def _protected(text: str, ctl: str) -> List[Tuple[str, str]]:
    found: List[Tuple[int, str, str]] = []
    for m in _TOKRUN_RE.finditer(text):
        ctl_toks = "".join(_CTLTOK_RE.findall(m.group(0)))
        if ctl_toks:
            found.append((m.start(), "tok", ctl_toks))
    spans = []
    for m in _TAG_RE.finditer(text):
        tag = m.group(0)
        spans.append((m.start(), m.end()))
        if _LTAG_RE.fullmatch(tag):
            continue                    # the line count: the build keeps it right
        found.append((m.start(), "tag", tag))
    for m in _CMD_RE.finditer(text):
        found.append((m.start(), "cmd", m.group(0)))
    for m in _BS_RE.finditer(text):
        found.append((m.start(), "esc", m.group(0)))
    for m in _PRINTF_RE.finditer(text):
        if not any(a <= m.start() < b for a, b in spans):
            found.append((m.start(), "printf", m.group(0)))
    found.sort()
    return [(k, s) for _, k, s in found]


def protected_tokens(text: str, ctl: str = "us") -> List[str]:
    """Tokens a translation should keep: control-byte ``⟦XX⟧``, ``<...>`` tags,
    ``$name...;`` commands, backslash escapes, printf conversions, in order."""
    return [s for _, s in _protected(text, ctl)]


def _multiset_diff(a: List[str], b: List[str]) -> Tuple[List[str], List[str]]:
    from collections import Counter
    ca, cb = Counter(a), Counter(b)
    return sorted((ca - cb).elements()), sorted((cb - ca).elements())


def speaker_of(text: str) -> str:
    m = _SPEAKER_RE.match(text or "")
    return m.group(0)[1:-1] if m else ""


def fix_line_count(source: str, text: str) -> str:
    """``<lN>`` set to the translation's line count when the source's own
    ``<lN>`` matched its line count (as ``langpack`` does after a re-wrap)."""
    ms, mt = _LTAG_RE.search(source), _LTAG_RE.search(text)
    if not ms or not mt or int(ms.group(1)) != source.count("\n") + 1:
        return text
    n = text.count("\n") + 1
    if int(mt.group(1)) == n:
        return text
    return text[:mt.start()] + f"<l{n}>" + text[mt.end():]


_KIND_NAMES = {"tok": "control codes (⟦XX⟧)", "tag": "<...> tags", "cmd": "$...; commands",
               "esc": "backslash codes", "printf": "% placeholders"}


def control_errors(text: str, source: str, ctl: str = "us") -> List[str]:
    """The one token rule that is an ERROR: the control bytes (``⟦0D⟧``...) of
    the original are all there and no other is added. ``check`` reports it and
    so does a build (``txfam_core.text_errors``)."""
    missing, extra = _multiset_diff([s for k, s in _protected(source, ctl) if k == "tok"],
                                    [s for k, s in _protected(text, ctl) if k == "tok"])
    if not (missing or extra):
        return []
    return [f"{_KIND_NAMES['tok']} differ from the original:"
            + (f" missing {' '.join(missing)}" if missing else "") + (f" extra {' '.join(extra)}" if extra else "")]


def px_lines(measure: Face, row: dict, data: bytes) -> List[int]:
    """Width of each line of ``data`` (game bytes of one row)."""
    _name, file = split_ctl(row.get("ctl", "us"))
    lines = data.split(b"\r\n") if file else split_lines(data)
    return [measure.width_of_bytes(x) for x in lines]


def split_lines(data: bytes) -> List[bytes]:
    """Game bytes -> lines: the literal backslash-n and CR LF break."""
    out: List[bytes] = []
    for part in data.split(b"\\n"):
        out += part.split(b"\r\n")
    return out


def check(text: str, source: str, font: str = FIELD, ctl: str = "us",
          limit_bytes: Optional[int] = None, measure: Optional[Face] = None,
          width_px: Optional[int] = None, face: str = FONT0, ctx: Optional[Context] = None) -> dict:
    """Validate one translation against its source. ``ok`` is False when there
    is any error; warnings never block a build."""
    errors: List[str] = []
    warnings: List[str] = []
    data = b""
    ctx = ctx or active()
    name, file = split_ctl(ctl, ctx)
    keep = "".join(ch for ch, r in textcodec.tokens(source) if r is None)
    try:
        data, w = from_display(text, font, ctl, face, keep=keep, ctx=ctx)
        warnings += list(dict.fromkeys(w))
    except TxEncodeError as e:
        for pos, ch, msg in e.problems:
            errors.append(f"position {pos}: {_shown(ch)}: {msg}" if ch else msg)
    src = _protected(source, ctl)
    dst = _protected(text, ctl)
    errors += control_errors(text, source, ctl)
    for kind in ("tag", "cmd", "esc", "printf"):
        missing, extra = _multiset_diff([s for k, s in src if k == kind],
                                        [s for k, s in dst if k == kind])
        if kind == "tag":                  # a <kWORD> keyword is translated: only their NUMBER is compared
            n_src = sum(1 for k, t in src if k == "tag" and t.startswith("<k"))
            n_dst = sum(1 for k, t in dst if k == "tag" and t.startswith("<k"))
            missing = [t for t in missing if not t.startswith("<k")]
            extra = [t for t in extra if not t.startswith("<k")]
            if n_src != n_dst:
                warnings.append(f"{n_dst} <k...> keyword tag(s) where the original has {n_src}")
        if missing or extra:
            msg = (f"{_KIND_NAMES[kind]} differ from the original:"
                   + (f" missing {' '.join(missing)}" if missing else "")
                   + (f" extra {' '.join(extra)}" if extra else ""))
            (errors if kind == "tok" else warnings).append(msg)
    if font == FIELD and not file:
        s_spk, t_spk = bool(_SPEAKER_RE.match(source)), bool(_SPEAKER_RE.match(text))
        if s_spk and not t_spk:
            warnings.append("the original starts with a [Speaker] name and this does not: the line "
                            "would be shown without its name box")
        elif t_spk and not s_spk:
            warnings.append("this starts with [..], which the game reads as a speaker name; the "
                            "original has none")
        ms, mt = _LTAG_RE.search(source), _LTAG_RE.search(text)
        if ms and not mt:
            warnings.append(f"the original has {ms.group(0)} (its number of lines); without it the "
                            f"window may be sized wrong")
    nbytes = len(data)
    if limit_bytes is not None and nbytes > limit_bytes:
        errors.append(f"{nbytes} bytes, over the {limit_bytes}-byte limit")
    px = None
    pxl: Optional[List[int]] = None
    if data and font == FIELD and measure is not None:
        try:
            pxl = px_lines(measure, {"ctl": ctl}, data)
            px = max(pxl)
        except Exception:                                          # noqa: BLE001 - a guide, never a refusal
            px, pxl = None, None
    if px is not None and width_px is not None and px > width_px:
        warnings.append(f"a line is {px} px wide; past {width_px} px its window is wider than the screen "
                        f"(the game does not wrap): shorten it or break the line")
    return {"ok": not errors, "errors": errors, "warnings": warnings,
            "nbytes": nbytes, "px": px, "px_lines": pxl}


# -- drawing --------------------------------------------------------------------------

def render_line(face: Face, data: bytes, scale: int = 2) -> bytes:
    """PNG of one line of game bytes drawn from the disc's font cells
    (``langpack.render_bytes``: the printer's layout)."""
    import io
    import font as fontmod
    import langpack
    from PIL import Image
    data = _TAG_RAW_RE.sub(b"", _KWORD_RAW_RE.sub(lambda m: m.group(1), data))     # a keyword's word is drawn
    img, w = langpack.render_bytes(face.ctx.addr, face.font, data, True, True, face.k)
    W, H = max(len(img[0]), w, 1) + 8, fontmod.CELL_H + 8
    im = Image.new("L", (W, H), 24)
    px = im.load()
    for y in range(fontmod.CELL_H):
        for x, v in enumerate(img[y]):
            if v and 4 + x < W:
                px[4 + x, 4 + y] = fontmod.GREY[v]
    im = im.resize((W * scale, H * scale), Image.NEAREST)
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def preview_lines(data: bytes, ctl: str = "us") -> List[bytes]:
    """The lines a preview draws: the speaker name first (its own line), then
    each line of the text."""
    _name, file = split_ctl(ctl)
    m = None if file else _SPEAKER_RAW_RE.match(data)
    lines = data.split(b"\r\n") if file else split_lines(data[m.end():] if m else data)
    return ([m.group(0)[1:-1]] if m else []) + lines


# Episode I's build redraws a few capitals and gives three signs real metrics;
# Episode III's fonts need neither (kept so txserver's preview path is shared).
def missing_capital_accents(font, face: str) -> List[str]:
    return []


def fix_capital_accents(font, face: str = FONT0):
    return font


def needs_metric_fix(text: str, font, face: str) -> List[str]:
    return []


def fix_unmeasured(font, face: str, chars=None):
    return font


# -- selftest ---------------------------------------------------------------------------

def selftest(iso: Optional[str]) -> int:
    ok = True

    def check_(cond, what):
        nonlocal ok
        print(("ok   " if cond else "FAIL ") + what)
        ok = ok and bool(cond)

    use_disc(None)
    raw = b"[Shion]<l2>Disembark\\nthe E.S.?<f>"
    d = to_display(raw, "us")
    check_(d == "[Shion]<l2>Disembark\nthe E.S.?<f>" and from_display(d, FIELD, "us")[0] == raw,
           "the game's \\n is a line break in the editor, and back")
    check_(from_display("Möbius café ×", FIELD, "us")[0] == b"M\xf6bius caf\xe9 \xa1\xdf",
           "USA: Latin-1 letters and the × pair")
    try:
        from_display("Привет", FIELD, "us")
        check_(False, "Cyrillic refused by the USA codec")
    except TxEncodeError as e:
        check_(len(e.problems) == 6, "Cyrillic refused by the USA codec, one problem per letter")
    r = check("[Shion]Oui ?<f>", "[Shion]<l2>Yes?\nNo?<f>", FIELD, "us")
    check_(r["ok"] and any("<l2>" in w for w in r["warnings"]), "a dropped <lN> warns")
    r = check("Oui<f>", "[Shion]Yes<w30><f>", FIELD, "us")
    check_(r["ok"] and len(r["warnings"]) == 2, f"dropped <w30> and speaker warn, not refuse ({r['warnings']})")
    r = check("x", "⟦0D⟧⟦0A⟧y", FIELD, "us")
    check_(not r["ok"], "a dropped control byte is an error")
    check_(fix_line_count("<l2>a\nb<f>", "<l2>a\nb\nc<f>") == "<l3>a\nb\nc<f>"
           and fix_line_count("<l3>a\nb", "<l3>a\nb\nc") == "<l3>a\nb\nc", "<lN> follows the line count when it matched")
    check_(to_display(b"a\r\nb", "us.f") == "a\nb" and from_display("a\nb", NOTE, "us.f")[0] == b"a\r\nb",
           "a file row's line break is the file's line end")
    with glyph_codes():
        check_(from_display("a" + glyph_char(0xB0A1), FIELD, "us")[0] == b"a\xb0\xa1", "glyph code inside a build")
    try:
        from_display(glyph_char(0xB0A1), FIELD, "us")
        check_(False, "glyph code outside a build refused")
    except TxEncodeError:
        check_(True, "glyph code outside a build refused")
    check_(protected_tokens("$col707070;a<f>%d\\31⟦0D⟧⟦A4⟧") == ["$col707070;", "<f>", "%d", "\\31", "⟦0D⟧"],
           "protected tokens")
    if iso:
        ctx = use_disc(iso)
        f = load_fonts(iso)["font0"]
        w = f.width_of_bytes(b"[Shion]Hello<f>")
        check_(0 < w < 200 and w == f.width_of_bytes(b"Hello"), f"measure: 'Hello' is {w} px, tags and speaker not counted")
        png = render_line(f, b"Hello")
        check_(png[:8] == b"\x89PNG\r\n\x1a\n", f"render_line -> PNG ({len(png)} bytes)")
        if ctx.display == "us":
            check_(draws_natively("é") and not draws_natively("я") and not draws_natively("œ"),
                   "USA disc: é drawn, я and œ not")
            r = check("Ça va ? Привет", "x", FIELD, "us")
            check_(not r["ok"] and len(r["errors"]) == 6, "font check through check()")
        else:
            check_(draws_natively("あ") and draws_natively("я") and not draws_natively("é"),
                   "Japanese disc: kana and Cyrillic drawn, é not")
            r = check("縊", "x", FIELD, "jp")
            check_(not r["ok"], "JP: 縊 encodes but has no glyph: refused")
            check_(check("縊", "縊", FIELD, "jp")["ok"], "JP: a character the original already held is kept")
    print("selftest", "passed" if ok else "FAILED")
    return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("selftest")
    s.add_argument("--iso")
    a = ap.parse_args(argv)
    return selftest(a.iso)


if __name__ == "__main__":
    sys.exit(main())
