"""textpack.py — Xenosaga III text as an editable UTF-8 tree, and back onto copies of the discs.

Structure borrowed from Xenosaga2PythonExtractor/textpack.py: ``### KEY``
block files, whole-file subtitles, a JSON manifest with per-object sha1,
"every block back, same keys, same order", refuse-on-any-error, and the
import that hands its result to a copy-then-patch writer. What changed for
XS3: the kinds are XS3's own container modules, the build profile
(``region.py``) picks the language folder and the codec, the disc is read
through its own X3.x0 indexes (``disc.Disc``), the font check reads the
font and the code->cell rules of the disc being patched (``font.Addressing``),
and the writer is ``patch.patch_copy`` (Disc 1 + Disc 2 together).

    kind      on the disc (xx = the build's folder: us or jp)       form in the tree
    sb        cf\\xx\\*.sb, bat\\xx\\*.sb  (text pool)                  ### NNNN <role> [codec] [flags]
    txd       mnu\\xx\\*.txd                                          ### NNNN
    nj        mnu\\xx\\DBC / DBC2 / MVtext / SegmentFileData /         ### BB.KKKK [fixed] [codec]
              njBtlText / njDBcommon / njDataText .bin
    msgdat    mg1\\xx\\Message.Dat                                    ### NNNN
    batdat    bat\\xx\\batdat.bin (20 text tables)                    ### TT.KKKK
    subtitle  mov\\xx\\**.txt, evt\\xx\\*.txt, mnu\\pse\\*.txt,           the file itself
              mnu\\pse\\xx\\*.mes

The tree is ``OUT/<in-game path>.txt`` plus ``OUT/xs3-text-export.json``.
Exporting Disc 1 and Disc 2 together gives ONE tree: the chain-0 objects
(X3.00 family, the same bytes on both discs) once, then each disc's story
chain (no path is in both story chains on either build).

**Block files.** The first line is a ``#`` header. Each ``### KEY`` line opens
one string; the text is the line after it. Words after the key (``dialogue``,
``note cp932``, ``fixed``) are information only: the codec of every string is
fixed by the manifest. Inside a block a line starting with ``#`` is a comment;
a string that starts with ``#`` is written ``⟦23⟧``. ``⟦XX⟧`` is a raw byte.
The game's line break is ``\\n`` typed as backslash + n; typing a real line
break joins the lines with ``\\n``.

**Whole files** (subtitles, pse) are the file's text in its codec, line ends
and tabs as on the disc (written and read with ``newline=""``). An editor that
rewrites every line end changes nothing: when the line count is kept, each
line gets its original end back. A UTF-8 BOM on any tree file is ignored.

**Import** (``text-import``, ``import_text``), the XS2 textpack rules:

* the manifest's build (profile name) must be the build of the discs, and the
  discs must be one build (``region.mixed_regions``; a known build,
  ``region.require_known``);
* every ``###`` block must come back: same keys, same order;
* an object whose disc bytes do not match the manifest sha1 is refused unless
  ``--rebase`` (then the tree is applied to the disc's current bytes, which
  must still have the same keys); a tree file that is byte-for-byte as
  exported is never applied, rebase or not;
* every TYPED character of a changed string must encode under the disc's
  codec AND, when the string is in the build's display codec (``us`` on the
  USA discs and the May 2006 prototype, ``jp`` on the Japanese discs), resolve
  through ``font.Addressing`` (gate, code->cell, extra-kanji lists, read from
  the disc's executable) to a cell with ink in font0 or font1 of that disc
  (the fixed-width image, or the proportional image cell+576 for a cell below
  the proportional limit). Characters the original string already held, cell 0
  (the full-width space A1A1) and ``⟦XX⟧`` escapes are not checked. Strings in
  another codec (the USA build's Shift-JIS developers' notes and untranslated
  EUC lines, the cp932 pse director scripts) are never drawn and only have to
  encode;
* subtitles also go through ``subtitle.encode`` (JP: no ``mono``, the 1K rule
  for ``mov\\jp\\bat``, ``[base/reading]`` ruby, time forms);
* GROWTH: no loader buffer size is known for ANY XS3 text object (not the .sb
  scripts, .txd tables, mnu .bin databases, Message.Dat, batdat.bin, subtitle
  or .mes files; the US survey lists them all as open), so an object whose new
  size is larger than the retail size is refused unless ``--grow``. With
  ``--grow`` it is written in place when it still fits its sector allocation,
  else appended at the image end (``patch_copy(grow=True)``). The one size rule
  that IS enforced always is the developers' 1K note for ``mov\\jp\\bat``;
* nothing is written unless every object passes. Then ``{path: bytes}`` goes
  to ``patch.patch_copy`` with every image given (chain-0 objects on both
  discs, chain-1 on Disc 1, chain-2 on Disc 2; complete verified copies or
  nothing). When no object changed, nothing is written at all.

The report lists, per changed object, the retail size, the new size, the
allocation (sector budget in place) and the action. Warnings (never errors):
an ``<lN>`` that no longer matches the line count, pass-through tags changed
(``sb.import_warnings``), and an edited identifier string.

Not covered: ``.xep`` (undecoded). Nothing here has been checked in game.

    python textpack.py --self-test
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import struct
import sys
import tempfile
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import batdat                                                      # noqa: E402
import msgdat                                                      # noqa: E402
import njbin                                                       # noqa: E402
import region as _region                                           # noqa: E402
import sb                                                          # noqa: E402
import subtitle                                                    # noqa: E402
import textcodec                                                   # noqa: E402
import txd                                                         # noqa: E402
from textcodec import Item, TextError                              # noqa: E402

MANIFEST = "xs3-text-export.json"
FORMAT = 2
SECTOR = 2048
Read = Callable[[str], bytes]


def _norm(path: str) -> str:
    return path.replace("/", "\\").lstrip("\\").lower()


def _clean(path: str) -> str:
    return path.replace("/", "\\").lstrip("\\")


def _sha1(b: bytes) -> str:
    return hashlib.sha1(b).hexdigest()


def guess_region(paths: List[str]):
    """The build a set of paths implies: ``region.lang_of`` (mnu\\xx\\menutext.txd), else
    any path in a ``\\jp\\`` folder means JP; USA otherwise."""
    lang = _region.lang_of(paths)
    if lang is None:
        lang = "jp" if any(region_of_path(p) is _region.JP for p in paths) else "us"
    return _region.JP if lang == "jp" else _region.US


def region_of_path(path: str):
    """The build a lone path implies (its language folder): JP for ``\\jp\\``, else USA."""
    p = _norm(path).split("\\")
    return _region.JP if "jp" in p[:3] else _region.US


# ------------------------------------------------------------------ disc

class DiscSource:
    """Read access to one image through ``disc.Disc`` (every chain's own index),
    with the build profile. ``paths()`` lists the index entries only."""

    def __init__(self, iso):
        from disc import Disc
        self.iso = Path(iso)
        self.disc = Disc(self.iso)
        self.region = _region.detect(self.disc)

    def close(self):
        self.disc.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def paths(self) -> List[str]:
        return [_clean(e.path) for _c, e in self.disc.entries()]

    def chained(self) -> List[Tuple[int, str]]:
        return [(c, _clean(e.path)) for c, e in self.disc.entries()]

    def chain_of(self, path: str) -> Optional[int]:
        hit = self.disc.lookup(path)
        return hit[0] if hit else None

    def has(self, path: str) -> bool:
        return self.disc.lookup(path) is not None

    def read(self, path: str) -> bytes:
        hit = self.disc.lookup(path)
        if hit is None:
            raise TextError(f"{path}: not in this disc's index")
        return self.disc.read_entry(hit[1])

    def alloc(self, path: str) -> int:
        return self.disc.allocation(path)

    def number(self) -> Optional[int]:
        from chains import disc_number
        try:
            return disc_number(self.disc.iso)
        except Exception:                                          # noqa: BLE001 - informative only
            return None

    def build(self) -> dict:
        x300 = self.disc.index_data.get(0)
        return {"region": self.region.name, "lang": self.region.lang, "codec": self.region.codec,
                "boot": self.disc.boot_elf_name(), "exe_sha256": _region.exe_sha256(self.disc),
                "x3_00_sha1": _sha1(x300) if x300 is not None else None,
                "chains": self.disc.chains}


IndexDisc = DiscSource          # the round-1 name (textcodec's exhaustive self-test uses it)


def open_disc(iso) -> DiscSource:
    return DiscSource(iso)


# ------------------------------------------------------------------ blocks

def parse_blocks(text: str, marker: str = "### ") -> List[Tuple[str, str]]:
    """(header after the marker, body) of every block (XS2 textpack.parse_blocks)."""
    out: List[Tuple[str, List[str]]] = []
    for line in text.split("\n"):
        line = line.rstrip("\r")
        if line.startswith(marker):
            out.append((line[len(marker):].strip(), []))
        elif line.startswith("#"):
            continue
        elif out:
            out[-1][1].append(line)
        elif line.strip():
            raise TextError(f"text before the first '{marker.strip()}' block: {line[:40]!r}")
    res = []
    for head, b in out:
        while len(b) > 1 and b[-1] == "":
            b.pop()
        res.append((head, "\\n".join(b)))
    return res


def keyed_bodies(text: str, expected: List[str]) -> List[str]:
    blocks = parse_blocks(text)
    keys = [h.split()[0] if h.split() else "" for h, _ in blocks]
    if keys != expected:
        seen, want = set(), set(expected)
        dup = sorted({k for k in keys if k in seen or seen.add(k)})
        missing = [k for k in expected if k not in set(keys)]
        unknown = sorted(k for k in set(keys) if k not in want)
        why = []
        if dup:
            why.append(f"{len(dup)} key(s) appear twice ({', '.join(dup[:3])})")
        if missing:
            why.append(f"{len(missing)} block(s) are missing ({', '.join(missing[:3])})")
        if unknown:
            why.append(f"{len(unknown)} key(s) are not in the export ({', '.join(unknown[:3])})")
        if not why:
            first = next(i for i, (a, b) in enumerate(zip(keys, expected)) if a != b)
            why.append(f"the blocks are out of order from '### {keys[first]}' (expected '### {expected[first]}')")
        raise TextError("; ".join(why) + ". Every '###' block of the export must be there once, in its order")
    return [b for _, b in blocks]


def _codec_map(codecs: List[str], default: str) -> Dict[str, List[int]]:
    out: Dict[str, List[int]] = {}
    for i, c in enumerate(codecs):
        if c != default:
            out.setdefault(c, []).append(i)
    return out


def _codec_list(cmap: Dict[str, List[int]], n: int, default: str) -> List[str]:
    out = [default] * n
    for c, idx in cmap.items():
        for i in idx:
            out[i] = c
    return out


# ------------------------------------------------------------------ font check

class FontCheck:
    """Can the disc draw a typed character? Reads the executable's code->cell rules
    (``font.Addressing``) and the ink of font0/font1 of the disc being patched."""

    def __init__(self, addr, inks, display: str, prop_shift: int = 0x240):
        self.addr, self.inks, self.display, self.shift = addr, inks, display, prop_shift
        self._cache: Dict[Tuple[str, str], Optional[str]] = {}

    @classmethod
    def from_disc(cls, disc, reg=None) -> "FontCheck":
        import font
        reg = reg or _region.detect(disc)
        addr = font.Addressing.from_executable(_region.executable(disc)[1])
        want = "euc" if reg.codec == "jp" else "whitelist"
        if addr.gate != want:
            raise TextError(f"the executable's pair gate reads as {addr.gate!r} but the {reg.name} profile's "
                            f"codec is {reg.codec!r}: a patched gate (glyphs-unlock) is not supported by "
                            "text-import")
        inks = []
        for k in (0, 1):
            p = _region.resolve(disc, f"mnu\\xx\\font{k}.bin", reg)
            if p is None:
                raise TextError(f"font{k}.bin not found on this disc")
            cells = font.font_cells(font.Font.from_bytes(disc.read(p)))
            inks.append(cells.reshape(len(cells), -1).any(axis=1))
        return cls(addr, inks, reg.codec)

    def why_not(self, codec_name: str, ch: str) -> Optional[str]:
        """None if ``ch`` (typed in a ``codec_name`` string) is drawable, else the reason."""
        key = (codec_name, ch)
        if key in self._cache:
            return self._cache[key]
        try:
            b = textcodec.codec_by_name(codec_name).encode_char(ch)
        except TextError as e:
            r = str(e)
        else:
            r = None
            if codec_name == self.display and b and b[0] >= 0x80:
                g = self.addr.glyph(b, 0, True, 0)
                if g.length != len(b):
                    r = f"{b.hex().upper()} is not read as one character"
                else:
                    ok = False
                    for f in (0, 1):
                        c = self.addr.cell(b[0], b[1], f) if len(b) == 2 else (g.cell or 0)
                        c &= 0xFFF
                        if c == 0:
                            ok = True
                        elif c != 0x7F and (self.inks[f][c] or
                                            (c < self.addr.prop_cells and self.inks[f][c + self.shift])):
                            ok = True
                    if not ok:
                        r = (f"{b.hex().upper()} has no glyph in this disc's fonts (cell {c:#x} is blank "
                             "or the fallback 0x7F)")
        self._cache[key] = r
        return r

    def check(self, codec_name: str, old_text: str, new_text: str, where: str) -> None:
        old = {ch for ch, raw in textcodec.tokens(old_text) if raw is None}
        bad = []
        for ch, raw in textcodec.tokens(new_text):
            if raw is not None or ord(ch) < 0x80 or ch in old or ch == "　":
                continue
            r = self.why_not(codec_name, ch)
            if r and (ch, r) not in bad:
                bad.append((ch, r))
        if bad:
            raise TextError(f"{where}: cannot be drawn: " + "; ".join(f"{ch!r} ({r})" for ch, r in bad[:5]))


def _encode(key: str, codec_name: str, old: bytes, body: str, force: bool,
            check: Optional[FontCheck] = None) -> bytes:
    codec = textcodec.codec_by_name(codec_name)
    old_text = codec.to_text(old)
    if not force and old_text == body:
        return old
    try:
        new = codec.from_text(body)
    except TextError as e:
        raise TextError(f"### {key}: {e}")
    if b"\x00" in new:
        raise TextError(f"### {key}: a NUL byte (⟦00⟧) inside a string; the game would stop reading there")
    if check is not None and new != old:
        check.check(codec_name, old_text, body, f"### {key}")
    return new


# ------------------------------------------------------------------ kinds

class Kind:
    name = ""
    whole_file = False
    show_role = False

    def match(self, path: str, reg) -> bool:
        raise NotImplementedError

    def strings(self, path: str, data: bytes, region=None) -> List[Tuple[str, bytes, str]]:
        """(key, bytes, codec name) of every exported string; key '*' = whole file."""
        reg = _region.as_region(region) if region is not None else region_of_path(path)
        return [(it.key, it.raw, it.codec) for it in self.items(path, data, reg)]

    def items(self, path: str, data: bytes, reg) -> List[Item]:
        raise NotImplementedError


class BlockKind(Kind):
    """A container with keyed strings, through a module's parse(data, region).items."""
    module = None
    rebuild_name = "rebuild"

    def parse(self, data, reg):
        return self.module.parse(data, reg)

    def exported(self, obj) -> List[Item]:
        return list(obj.items)

    def items(self, path, data, reg):
        return self.exported(self.parse(data, reg))

    def header(self, path, data, obj, items) -> List[str]:
        return [f"# {path}  {len(items)} strings  file {len(data)} bytes"]

    def build(self, obj, new: Dict[str, bytes], force: bool) -> bytes:
        raise NotImplementedError

    def export(self, path, data, reg):
        obj = self.parse(data, reg)
        items = self.exported(obj)
        lines = self.header(path, data, obj, items)
        for it in items:
            words = ([it.role] if self.show_role and it.role else []) + \
                    ([it.codec] if it.codec != reg.codec else []) + \
                    ["fixed" if f == "mid-string" else f for f in it.flags]
            lines.append(f"### {it.key}" + (" " + " ".join(words) if words else ""))
            lines.append(textcodec.codec_by_name(it.codec).to_text(it.raw))
        meta = {"count": len(items)}
        cm = _codec_map([it.codec for it in items], reg.codec)
        if cm:
            meta["codecs"] = cm
        return "\n".join(lines) + "\n", meta

    def rebuild(self, path, data, text, meta, reg, force=False, check=None, warn=None):
        obj = self.parse(data, reg)
        items = self.exported(obj)
        keys = [it.key for it in items]
        codecs = _codec_list(meta.get("codecs", {}), len(keys), reg.codec)
        bodies = keyed_bodies(text, keys)
        new: Dict[str, bytes] = {}
        errors = []
        for it, cn, body in zip(items, codecs, bodies):
            try:
                raw = _encode(it.key, cn, it.raw, body, force, check)
            except TextError as e:
                errors.append(str(e))
                continue
            if raw != it.raw:
                self.warnings(it, raw, reg, warn)
            new[it.key] = raw
        if errors:
            raise TextError(f"{len(errors)} string(s) refused: " + " | ".join(errors[:5]))
        if not force and all(new[it.key] == it.raw for it in items):
            return data
        out = self.build(obj, new, force)
        back = {it.key: it.raw for it in self.items(path, out, reg)}
        if any(back.get(k) != v for k, v in new.items()):
            raise TextError("the rebuilt object does not read back as written")
        return out

    def warnings(self, it: Item, raw: bytes, reg, warn) -> None:
        pass


class SbKind(BlockKind):
    name = "sb"
    module = sb
    show_role = True

    def match(self, path, reg):
        low = _norm(path)
        return low.endswith(".sb") and (low.startswith(f"cf\\{reg.lang}\\") or low.startswith(f"bat\\{reg.lang}\\"))

    def header(self, path, data, obj, items):
        h = [f"# {path}  {len(items)} strings  text pool at 0x{obj.pool:X} "
             f"({obj.pool_end - obj.pool} bytes)  file {len(data)} bytes"]
        st = sb.scene_status(path)
        if st:
            h.append(f"# {st}: no USA counterpart; whether the game loads this scene is not known")
        return h

    def build(self, obj, new, force):
        return sb.rebuild(obj, [new.get(f"{i:04d}", s) for i, s in enumerate(obj.strings)])

    def warnings(self, it, raw, reg, warn):
        if warn is None:
            return
        for w in sb.import_warnings(it.raw, raw, reg):
            warn(f"### {it.key}: {w}")
        if it.role == "identifier":
            warn(f"### {it.key}: an identifier (label / voice id) was changed; the script refers to it by name")


class TxdKind(BlockKind):
    name = "txd"
    module = txd

    def match(self, path, reg):
        low = _norm(path)
        return low.startswith(f"mnu\\{reg.lang}\\") and low.endswith(".txd")

    def header(self, path, data, obj, items):
        return [f"# {path}  {len(items)} strings  {'count-prefixed ' if obj.counted else ''}file {len(data)} bytes"]

    def build(self, obj, new, force):
        return txd.rebuild(obj, [new.get(f"{i:04d}", s) for i, s in enumerate(obj.strings)])


class NjKind(BlockKind):
    name = "nj"
    module = njbin
    _names = {n.lower() for n in njbin.NAMES}

    def match(self, path, reg):
        low = _norm(path)
        return low.startswith(f"mnu\\{reg.lang}\\") and low.count("\\") == 2 and low.rsplit("\\", 1)[-1] in self._names

    def exported(self, obj):
        return [it for it in obj.items if it.raw or "unreferenced" not in it.flags]

    def header(self, path, data, obj, items):
        h = [f"# {path}  {len(obj.blobs)} blobs  {len(items)} strings  file {len(data)} bytes",
             "# a block marked 'fixed' holds a value pointing inside it (meaning unknown): it cannot change"]
        n_jp = sum(1 for it in items if it.codec not in ("us", "jp"))
        if n_jp:
            h.append(f"# {n_jp} strings marked euc_jp (or euc_jis_2004) are untranslated Japanese (EUC-JP) and "
                     "shown as such; the USA print function would draw those bytes as Latin-1 cells, so "
                     "replace them with English")
        return h

    def build(self, obj, new, force):
        strings = [list(b.strings) for b in obj.blobs]
        for key, raw in new.items():
            i, k = (int(x) for x in key.split("."))
            strings[i][k] = raw
        if force:
            return njbin.build_outer([njbin.build_blob(b, s) for b, s in zip(obj.blobs, strings)])
        return njbin.rebuild(obj, strings)


class MsgdatKind(BlockKind):
    name = "msgdat"
    module = msgdat

    def match(self, path, reg):
        return _norm(path) == f"mg1\\{reg.lang}\\message.dat"

    def header(self, path, data, obj, items):
        h = [f"# {path}  {len(items)} messages  file {len(data)} bytes  u{8 * obj.layout.width} offsets, strings at {obj.layout.strings:#x}"]
        if obj.attrs:
            h.append("# the a/b/c words after each key are per-message values of unknown meaning, kept unchanged")
        return h

    def build(self, obj, new, force):
        return msgdat.rebuild(obj, [new.get(f"{i:04d}", s) for i, s in enumerate(obj.strings)])


class BatdatKind(BlockKind):
    name = "batdat"
    module = batdat

    def match(self, path, reg):
        return _norm(path) == f"bat\\{reg.lang}\\batdat.bin"

    def exported(self, obj):
        return [it for it in obj.items if it.raw or "unreferenced" not in it.flags]

    def header(self, path, data, obj, items):
        return [f"# {path}  {len(obj.tables)} tables  {len(items)} strings  file {len(data)} bytes",
                "# keys are table.string; the string fields were derived from the file's structure "
                "(not confirmed from the battle code). A table with u16 offsets cannot pass 64 KB"]

    def build(self, obj, new, force):
        return batdat.rebuild(obj, list(new.items()), force)


class SubtitleKind(Kind):
    name = "subtitle"
    whole_file = True

    def match(self, path, reg):
        return subtitle.role(path, reg) is not None

    def items(self, path, data, reg):
        return subtitle.items(path, data, reg)

    def export(self, path, data, reg):
        name, t = subtitle.to_text(path, data, reg)
        return t, {"codec": name, "role": subtitle.role(path)}

    def rebuild(self, path, data, text, meta, reg, force=False, check=None, warn=None):
        name = meta["codec"]
        orig = textcodec.codec_by_name(name).to_text(data, file=True)
        if not force and orig == text:
            return data
        text = _keep_line_ends(orig, text)
        if not force and orig == text:
            return data
        new = subtitle.encode(path, text, name, reg)
        if check is not None and new != data:
            shown = "\n".join(ln for ln in text.replace("\r", "\n").split("\n") if not ln.startswith(";"))
            check.check(name, orig, shown, path)
        return new


def _keep_line_ends(orig: str, text: str) -> str:
    """The subtitle files mix CR LF and LF (s060400.txt). An editor that
    normalises every line end changes no text; give each line its original end
    back when the edit kept the line count, so only real edits change bytes."""
    o_lines = orig.splitlines(keepends=True)
    n_lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    o_bodies = [ln.rstrip("\r\n") for ln in o_lines]
    ends = [ln[len(b):] for ln, b in zip(o_lines, o_bodies)]
    if orig.endswith(("\n", "\r")):
        o_bodies.append("")
        ends.append("")
    else:
        ends[-1:] = [""] if ends else []
    if len(n_lines) != len(o_bodies):
        return text
    return "".join(b + e for b, e in zip(n_lines, ends))


KINDS: Dict[str, Kind] = {k.name: k for k in (SbKind(), TxdKind(), NjKind(), MsgdatKind(), BatdatKind(),
                                              SubtitleKind())}
UNFINISHED = {"*.xep": "undecoded"}


def collect(paths: Iterable[str], region=None) -> List[Tuple[str, str]]:
    """(path, kind) of every text object among ``paths``, sorted by path. Without a
    region, the language folder the paths hold decides (``region.lang_of``)."""
    paths = list(paths)
    if region is None:
        reg = guess_region(paths)
    else:
        reg = _region.as_region(region)
    out = []
    for p in paths:
        for k in KINDS.values():
            if k.match(p, reg):
                out.append((p, k.name))
                break
    return sorted(out, key=lambda x: x[0].lower())


def tree_path(root: Path, path: str) -> Path:
    parts = path.replace("/", "\\").strip("\\").split("\\")
    if any(p in ("", ".", "..") or ":" in p for p in parts):
        raise TextError(f"object path {path!r} cannot be a file path")
    return Path(root, *parts[:-1], parts[-1] + ".txt")


# ------------------------------------------------------------------ export / rebuild

def export(read: Read, paths: Iterable[str], out_dir, build: Optional[dict] = None,
           alloc: Optional[Callable[[str], int]] = None, log=print, region=None,
           info: Optional[Callable[[str], dict]] = None) -> dict:
    """Write the tree and its manifest for every text object among ``paths``.
    ``region`` (a Region or name; default: from ``build['region']``, else the
    language folder of the paths) picks the folders and codecs."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    build = dict(build or {})
    if region is None and build.get("region") in {p.name for p in _region.PROFILES}:
        region = build["region"]
    paths = list(paths)
    reg = _region.as_region(region) if region is not None else guess_region(paths)
    build.setdefault("region", reg.name)
    objs, counts = {}, {}
    for path, kind in collect(paths, reg):
        data = read(path)
        k = KINDS[kind]
        try:
            text, meta = k.export(path, data, reg)
        except (ValueError, struct.error) as e:
            log(f"skip {path}: {e}")
            continue
        dest = tree_path(out, path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        raw = text.encode("utf-8")
        dest.write_bytes(raw)
        o = dict(kind=kind, sha1=_sha1(data), size=len(data),
                 budget=alloc(path) if alloc else -(-len(data) // SECTOR) * SECTOR,
                 tree=str(dest.relative_to(out)).replace(os.sep, "/"), tree_sha1=_sha1(raw))
        if info:
            o.update(info(path))
        o.update(meta)
        objs[_clean(path)] = o
        counts[kind] = counts.get(kind, 0) + 1
    manifest = {"format": FORMAT, "tool": "xs3 textpack", "build": build, "objects": objs,
                "unfinished": UNFINISHED}
    (out / MANIFEST).write_text(json.dumps(manifest, indent=1, ensure_ascii=False), encoding="utf-8")
    log(f"exported {sum(counts.values())} objects {counts} to {out}")
    return manifest


def export_discs(isos: List[str], out_dir, log=print) -> dict:
    """One tree from one image or Disc 1 + Disc 2 of one build (mixed sets refused)."""
    srcs = [DiscSource(i) for i in isos]
    try:
        for s in srcs:
            if s.region.name == "unknown":
                raise TextError(f"{s.iso.name}: unknown build ({s.region.note}); text-export needs a known build")
        msg = _region.mixed_regions([s.disc for s in srcs])
        if msg:
            raise TextError("refused: " + msg.replace("warning: ", "", 1))
        owner: Dict[str, Tuple[DiscSource, int, str]] = {}
        for s in srcs:
            for c, p in s.chained():
                owner.setdefault(_norm(p), (s, c, p))
        build = srcs[0].build()
        build["isos"] = [s.iso.name for s in srcs]
        build["discs"] = [s.number() for s in srcs]
        build["chains"] = sorted({c for s in srcs for c in s.disc.chains})
        mismatch = []

        def info(path):
            s, c, _p = owner[_norm(path)]
            d = {"chain": c}
            if c == 0 and len(srcs) == 2:
                other = srcs[1] if s is srcs[0] else srcs[0]
                if other.has(path) and other.read(path) != s.read(path):
                    mismatch.append(path)
            return d

        m = export(lambda p: owner[_norm(p)][0].read(p), [v[2] for v in owner.values()], out_dir, build,
                   lambda p: owner[_norm(p)][0].alloc(p), log, srcs[0].region, info)
        if mismatch:
            log(f"warning: {len(mismatch)} chain-0 object(s) differ between the two discs, e.g. {mismatch[0]}")
        return m
    finally:
        for s in srcs:
            s.close()


def load_manifest(tree) -> dict:
    p = Path(tree) / MANIFEST
    if not p.exists():
        raise TextError(f"{p} is missing: not a text-export tree")
    m = json.loads(p.read_text(encoding="utf-8"))
    if m.get("format") != FORMAT:
        raise TextError(f"manifest format {m.get('format')} (this kit reads {FORMAT}); export the text again")
    return m


def _tree_text(tree: Path, o: dict) -> Tuple[bytes, str]:
    raw = (tree / o["tree"]).read_bytes()
    # utf-8-sig: a BOM that Windows Notepad adds is dropped, not read as text
    return raw, raw.decode("utf-8-sig")


def rebuild(manifest: dict, tree, read: Read, force: bool = False, changed_only: bool = True,
            rebase: bool = False, check: Optional[FontCheck] = None, warn=None,
            skip_untouched: bool = False, region=None) -> Dict[str, bytes]:
    """{path: new bytes} for every object of the tree (only the changed ones unless
    ``changed_only`` is False), in memory. ``read`` supplies the original bytes; an
    object whose bytes do not match the manifest sha1 is refused unless ``rebase``.
    ``force`` re-encodes every string and re-lays every container (no shortcut for
    unchanged text), which is how the round trip proves the rebuilders.
    ``skip_untouched`` skips a tree file that is byte-for-byte as exported without
    reading the disc. Nothing is returned unless every object passes."""
    tree = Path(tree)
    reg = _region.as_region(region or manifest.get("build", {}).get("region") or None)
    out, errors = {}, []
    for path, o in manifest["objects"].items():
        try:
            raw, text = _tree_text(tree, o)
            if skip_untouched and not force and o.get("tree_sha1") == _sha1(raw):
                continue
            data = read(path)
            if _sha1(data) != o["sha1"] and not rebase:
                raise TextError("the disc object is not the one this tree was exported from (sha1 differs); "
                                "--rebase applies the tree to it anyway")
            ws: List[str] = []
            new = KINDS[o["kind"]].rebuild(path, data, text, o, reg, force, check, ws.append)
            if warn is not None:
                for w in ws:
                    warn(f"{path}: {w}")
            if not changed_only or new != data:
                out[path] = new
        except (TextError, ValueError, OSError, struct.error) as e:
            errors.append(f"{path}: {e}")
    if errors:
        raise TextError(f"{len(errors)} object(s) refused:\n  " + "\n  ".join(errors[:20]))
    return out


# ------------------------------------------------------------------ import

def plan_import(isos: List[str], tree, grow: bool = False, rebase: bool = False,
                log=print) -> Tuple[Dict[str, bytes], List[dict], List[str]]:
    """Check a tree against the images and build the change set (writes nothing).
    Returns ({path: bytes}, report rows, warnings); raises TextError on any refusal."""
    tree = Path(tree)
    m = load_manifest(tree)
    srcs = [DiscSource(i) for i in isos]
    try:
        if not 1 <= len(srcs) <= 2:
            raise TextError(f"give one image or a Disc 1 + Disc 2 pair, not {len(srcs)}")
        for s in srcs:
            try:
                _region.require_known(s.disc, "text-import")
            except _region.UnknownBuild as e:
                raise TextError(str(e))
        msg = _region.mixed_regions([s.disc for s in srcs])
        if msg:
            raise TextError("refused: " + msg.replace("warning: ", "", 1))
        reg = srcs[0].region
        want = m.get("build", {}).get("region")
        if want != reg.name:
            raise TextError(f"the tree was exported from the {want!r} build; these discs are {reg.name!r}")
        check = FontCheck.from_disc(srcs[0].disc, reg)
        owner: Dict[str, DiscSource] = {}
        for s in srcs:
            for p in s.paths():
                owner.setdefault(_norm(p), s)
        warnings: List[str] = []
        changes: Dict[str, bytes] = {}
        rows: List[dict] = []
        errors: List[str] = []
        for path, o in m["objects"].items():
            try:
                raw, text = _tree_text(tree, o)
            except OSError as e:
                errors.append(f"{path}: {e}")
                continue
            if o.get("tree_sha1") == _sha1(raw):
                continue                                  # untouched since the export
            s = owner.get(_norm(path))
            if s is None:
                errors.append(f"{path}: edited, but it is on none of the images given "
                              f"(chain {o.get('chain')}; give the disc that holds it)")
                continue
            try:
                data = s.read(path)
                if _sha1(data) != o["sha1"] and not rebase:
                    raise TextError("the disc object is not the one this tree was exported from (sha1 "
                                    "differs: an already patched image or another revision); --rebase "
                                    "applies the tree to it anyway")
                ws: List[str] = []
                new = KINDS[o["kind"]].rebuild(path, data, text, o, reg, False, check, ws.append)
                warnings += [f"{path}: {w}" for w in ws]
            except (TextError, ValueError, struct.error) as e:
                errors.append(f"{path}: {e}")
                continue
            if new == data:
                continue
            chain = s.chain_of(path)
            if chain == 0:
                for t in srcs:
                    if t is not s and t.has(path) and t.read(path) != data:
                        errors.append(f"{path}: a chain-0 object whose bytes differ between the two discs")
            alloc = s.alloc(path)
            row = {"path": _clean(path), "kind": o["kind"], "chain": chain, "old_size": len(data),
                   "new_size": len(new), "allocation": alloc,
                   "action": "in-place" if len(new) <= alloc else "grow (append at image end)"}
            if len(new) > len(data) and not grow:
                errors.append(f"{path}: grows from {len(data)} to {len(new)} bytes; the loader's buffer for "
                              f"{o['kind']} objects is not known, so growth needs --grow")
            rows.append(row)
            changes[_clean(path)] = new
        if errors:
            raise TextError(f"{len(errors)} problem(s); nothing written:\n  " + "\n  ".join(errors[:30]))
        return changes, rows, warnings
    finally:
        for s in srcs:
            s.close()


def import_text(isos: List[str], tree, out, grow: bool = False, rebase: bool = False,
                dry_run: bool = False, ceiling=None, log=print, overwrite: bool = False) -> dict:
    """text-import: check the tree, then write every changed object into copies of
    ``isos`` (``patch.patch_copy``). Returns {'changes', 'rows', 'warnings', 'written',
    'patch'}; nothing is written when no object changed or on any refusal."""
    changes, rows, warnings = plan_import(isos, tree, grow, rebase, log)
    for w in warnings:
        log("warning: " + w)
    for r in rows:
        log(f"  {r['path']}: {r['kind']} chain {r['chain']}: {r['old_size']} -> {r['new_size']} bytes "
            f"(allocation {r['allocation']}): {r['action']}")
    res = {"changes": sorted(changes), "rows": rows, "warnings": warnings, "written": [], "patch": []}
    if not changes:
        log("no object changed: nothing written")
        return res
    import patch
    try:
        res["patch"] = patch.patch_copy(list(isos), out, changes, grow=grow, ceiling=ceiling,
                                        verbose=True, dry_run=dry_run, overwrite=overwrite)
    except patch.PatchError as e:
        raise TextError(str(e))
    if not dry_run:
        res["written"] = sorted({r["disc"] for r in res["patch"] if r["action"] != "unchanged"})
    return res


# ------------------------------------------------------------------ CLI

def cmd_export(a) -> int:
    export_discs(a.iso, a.out)
    return 0


def cmd_import(a) -> int:
    try:
        res = import_text(a.iso, a.text, a.out, grow=a.grow, rebase=a.rebase, dry_run=a.dry_run,
                          ceiling=a.ceiling, overwrite=a.overwrite)
    except TextError as e:
        print(f"text-import refused: {e}", file=sys.stderr)
        return 1
    if a.report:
        Path(a.report).write_text(json.dumps(res, indent=1, ensure_ascii=False), encoding="utf-8")
    return 0


def roundtrip(iso: str, work=None, log=print) -> Tuple[int, List[str]]:
    """Export, then rebuild every object unchanged with ``force`` (full re-encode and
    re-lay); return (objects checked, paths that differ)."""
    with DiscSource(iso) as d:
        with tempfile.TemporaryDirectory(dir=work) as tmp:
            m = export(d.read, d.paths(), tmp, d.build(), d.alloc, log=lambda *x: None, region=d.region)
            got = rebuild(load_manifest(tmp), tmp, d.read, force=True, changed_only=False)
            bad = [p for p, b in got.items() if b != d.read(p)]
            kinds = {}
            for p, o in m["objects"].items():
                kinds[o["kind"]] = kinds.get(o["kind"], 0) + 1
            log(f"{Path(iso).name}: {len(got)} objects {kinds} rebuilt, {len(bad)} differ")
            return len(got), bad


def cmd_roundtrip(a) -> int:
    rc = 0
    for iso in a.iso:
        n, bad = roundtrip(iso)
        for p in bad[:20]:
            print("  DIFF", p)
        if bad or not n:
            rc = 1
    print("text-roundtrip", "OK: every object byte-identical" if rc == 0 else "FAILED")
    return rc


def add_commands(subparsers) -> None:
    p = subparsers.add_parser("text-export", help="export XS3 text (.sb/.txd/mnu .bin/Message.Dat/batdat/"
                                                  "subtitles/pse) to a UTF-8 tree + manifest (USA, prototype or JP)")
    p.add_argument("--iso", action="append", required=True, help="disc image (repeat for Disc 1 and Disc 2: one tree)")
    p.add_argument("--out", required=True)
    p.set_defaults(func=cmd_export)
    p = subparsers.add_parser("text-import", help="check an edited text tree and write it into COPIES of the "
                                                  "disc(s) (Disc 1 + Disc 2 together); nothing written on any error")
    p.add_argument("--iso", action="append", required=True, help="source image, never written (repeat for Disc 2)")
    p.add_argument("--text", required=True, help="the tree text-export wrote (edited)")
    p.add_argument("--out", required=True, help="output folder (OUT/<source name>) or one .iso path")
    p.add_argument("--grow", action="store_true",
                   help="allow objects to get larger (loader buffers are unknown) and to be appended at the image end")
    p.add_argument("--rebase", action="store_true", help="apply the tree although a disc object's sha1 differs")
    p.add_argument("--dry-run", action="store_true", help="check and report only; write nothing")
    p.add_argument("--ceiling", default=None, help="sector ceiling: auto (default), dvd5, dvd9 (dual-layer images only), "
                        "or none / N for emulator-only images")
    p.add_argument("--report", help="write the report as JSON")
    p.add_argument("--overwrite", action="store_true",
                   help="replace output images that already exist (an earlier output; never an original)")
    p.set_defaults(func=cmd_import)
    p = subparsers.add_parser("text-roundtrip", help="export then rebuild every text object unchanged; assert byte-identical")
    p.add_argument("--iso", action="append", required=True)
    p.set_defaults(func=cmd_roundtrip)
    # align-export lives in align.py; registered from here so the CLI has it even
    # before cli.py lists align (skipped when cli.py already registered it)
    if "align-export" not in getattr(subparsers, "choices", {}):
        import align
        align.add_commands(subparsers)


# ------------------------------------------------------------------ self-test

def _synthetic_sb(strings: List[bytes], name: bytes = b"us\\0001") -> bytes:
    code = struct.pack("<II", 12, 0)
    pool = sb.build_pool(strings)
    rest = [struct.pack("<II", 8, 0)] * 2 + [struct.pack("<II", 1, 8) + name + b"\0"]
    parts = [code, struct.pack("<II", 8, 0), pool] + rest
    offs, cur = [], 0x40
    for p_ in parts:
        offs.append(cur)
        cur += len(p_)
    return sb.MAGIC + struct.pack("<HH", 1, 1) + struct.pack("<6I", *offs) + b"\0" * 0x20 + b"".join(parts)


class _FakeAddr:
    """A stand-in Addressing for the synthetic font check: ``drawable`` codes have ink."""
    prop_cells = 0x180

    def __init__(self, drawable):
        import font
        self._f = font
        self.drawable = drawable

    def glyph(self, b, i, han, f):
        import font
        if len(b) == 2 and font.pair_gate(b[0], b[1]):
            return font.Glyph(2, "cell", b[0] << 8 | b[1], 0x500)
        return font.Glyph(1, "cell", 0xA900 | ((b[0] + 0x80) & 0xFF), b[0] + 0x80)

    def cell(self, lead, trail, f):
        return 0x500 if (lead << 8 | trail) in self.drawable else 0x7F


def self_test() -> int:
    import numpy as np
    ok = True

    def check(cond, msg):
        nonlocal ok
        print(("ok    " if cond else "FAIL  ") + msg)
        ok &= bool(cond)

    def raises(fn, msg, contains=""):
        try:
            fn()
            check(False, msg)
        except TextError as e:
            check(contains in str(e), msg + ("" if contains in str(e) else f" (got: {e})"))

    # a synthetic USA disc: one .txd, one subtitle, one sb
    t = txd.build(txd.Table(True, [b"Yes", b"M\xf6bius Hotel", b"<\xa1\xdf> Cancel"]))
    s = b"00:00:00\t$ay375;\r\n00:01:00\tHello.\nend\r\n"
    sbd = _synthetic_sb([b"[Shion]<l1>Hi.<f>", "＊メモ＊".encode("cp932"), b"seg_now"])
    files = {"mnu\\us\\menutext.txd": t, "mov\\us\\s000300.txt": s, "cf\\us\\0001.sb": sbd}
    ink = np.zeros(4096, bool)
    ink[[0x500, 0x176, 0x169]] = True                      # ×-pair cell, ö (F6), é (E9)
    fc = FontCheck(_FakeAddr({0xA1DF}), [ink, ink], "us")
    with tempfile.TemporaryDirectory() as tmp:
        m = export(files.__getitem__, files, tmp, {"boot": "synthetic"}, log=lambda *x: None)
        check(set(m["objects"]) == set(files) and m["build"]["region"] == "us",
              "synthetic: every object exported, build us")
        got = rebuild(load_manifest(tmp), tmp, files.__getitem__, force=True, changed_only=False)
        check(all(got[p] == files[p] for p in files), "synthetic: forced rebuild of the untouched tree is byte-identical")
        check(rebuild(load_manifest(tmp), tmp, files.__getitem__, skip_untouched=True) == {},
              "synthetic: an untouched tree yields no change")
        tp = Path(tmp) / "mnu/us/menutext.txd.txt"
        body = tp.read_text(encoding="utf-8")
        check("Möbius Hotel" in body and "<×> Cancel" in body, "synthetic: Möbius and <×> readable in the tree")
        tp.write_text(body.replace("Möbius Hotel", "Möbius Hotel Lobby"), encoding="utf-8")
        got = rebuild(load_manifest(tmp), tmp, files.__getitem__, check=fc)
        check(list(got) == ["mnu\\us\\menutext.txd"] and txd.parse(got["mnu\\us\\menutext.txd"]).strings[1]
              == b"M\xf6bius Hotel Lobby", "synthetic: an edited string comes back encoded, only that object returned")
        tp.write_text(body.replace("Möbius Hotel", "Hôtel Möbius é"), encoding="utf-8")
        raises(lambda: rebuild(load_manifest(tmp), tmp, files.__getitem__, check=fc),
               "synthetic: a typed character with no glyph (ô) is refused by the font check", "cannot be drawn")
        tp.write_text(body.replace("Möbius Hotel", "Möbius ⟦F4⟧ é"), encoding="utf-8")
        got = rebuild(load_manifest(tmp), tmp, files.__getitem__, check=fc)
        check(txd.parse(got["mnu\\us\\menutext.txd"]).strings[1] == b"M\xf6bius \xf4 \xe9",
              "synthetic: an escape is never font-checked; é (inked) passes")
        tp.write_text(body.replace("Möbius Hotel", "Möbius ｱ"), encoding="utf-8")
        raises(lambda: rebuild(load_manifest(tmp), tmp, files.__getitem__, check=fc),
               "synthetic: a character the USA codec cannot encode is refused")
        # editor habits: a UTF-8 BOM, and every line end normalised to CR LF
        tp.write_text(body, encoding="utf-8-sig")
        sub = Path(tmp) / "mov/us/s000300.txt.txt"
        stext = sub.read_bytes().decode("utf-8")
        sub.write_bytes(("﻿" + stext.replace("\r\n", "\n").replace("\n", "\r\n")).encode("utf-8"))
        got = rebuild(load_manifest(tmp), tmp, files.__getitem__)
        check(got == {}, "synthetic: a BOM and CR LF-normalised line ends alone change nothing")
        sub.write_bytes(stext.replace("Hello.", "Hello there.").replace("\r\n", "\n").replace("\n", "\r\n")
                        .encode("utf-8"))
        got = rebuild(load_manifest(tmp), tmp, files.__getitem__, check=fc)
        check(got.get("mov\\us\\s000300.txt") == s.replace(b"Hello.", b"Hello there."),
              "synthetic: an edited subtitle keeps each line's original CR LF / LF")
        sub.write_bytes(stext.encode("utf-8"))
        sp = Path(tmp) / "cf/us/0001.sb.txt"
        st = sp.read_text(encoding="utf-8")
        check("＊メモ＊" in st and "note cp932" in st, "synthetic: the sb note reads as Shift-JIS")
        ws: List[str] = []
        sp.write_text(st.replace("<l1>Hi.", "<l1>Hi.\\nAgain."), encoding="utf-8")
        rebuild(load_manifest(tmp), tmp, files.__getitem__, check=fc, warn=ws.append)
        check(any("<l1>" in w for w in ws), f"synthetic: a broken <lN> count is a warning ({ws[:1]})")
        sp.write_text(st.replace("### 0002", "### 0003"), encoding="utf-8")
        raises(lambda: rebuild(load_manifest(tmp), tmp, files.__getitem__), "synthetic: a renamed key is refused")
        sp.write_text(st, encoding="utf-8")
        f2 = dict(files)
        f2["cf\\us\\0001.sb"] = _synthetic_sb([b"[Shion]<l1>Ho.<f>", "＊メモ＊".encode("cp932"), b"seg_now"])
        sp.write_text(st.replace("Hi.", "Hey."), encoding="utf-8")
        raises(lambda: rebuild(load_manifest(tmp), tmp, f2.__getitem__), "synthetic: a sha1 mismatch is refused",
               "sha1 differs")
        got = rebuild(load_manifest(tmp), tmp, f2.__getitem__, rebase=True)
        check(sb.parse(got["cf\\us\\0001.sb"]).strings[0] == b"[Shion]<l1>Hey.<f>", "synthetic: --rebase applies it")
    # a synthetic JP sb: role/codec by region, kana under the jp codec
    jsb = _synthetic_sb(["[シオン]こんにちは".encode("euc_jp"), b"seg_now"], b"jp\\0001")
    jf = {"cf\\jp\\0001.sb": jsb}
    with tempfile.TemporaryDirectory() as tmp:
        m = export(jf.__getitem__, jf, tmp, {}, log=lambda *x: None)
        txt = (Path(tmp) / "cf/jp/0001.sb.txt").read_text(encoding="utf-8")
        check(m["build"]["region"] == "jp" and "### 0000 dialogue" in txt and "こんにちは" in txt
              and "codecs" not in m["objects"]["cf\\jp\\0001.sb"], "synthetic JP: region jp, dialogue, EUC readable")
        (Path(tmp) / "cf/jp/0001.sb.txt").write_text(txt.replace("こんにちは", "Ｈｅｌｌｏ"), encoding="utf-8")
        got = rebuild(load_manifest(tmp), tmp, jf.__getitem__)
        check(sb.parse(got["cf\\jp\\0001.sb"]).strings[0] == "[シオン]Ｈｅｌｌｏ".encode("euc_jp"),
              "synthetic JP: an edit encodes as EUC")
        (Path(tmp) / "cf/jp/0001.sb.txt").write_text(txt.replace("こんにちは", "ﾊﾛｰ"), encoding="utf-8")
        raises(lambda: rebuild(load_manifest(tmp), tmp, jf.__getitem__), "synthetic JP: half-width kana refused")

    envs = [(k, os.environ.get(k)) for k in ("XS3_D1", "XS3_D2", "XS3_PROTO", "XS3_JP1", "XS3_JP2")]
    if not any(v for _, v in envs):
        print("SKIP  disc checks (set XS3_D1 / XS3_D2 / XS3_PROTO / XS3_JP1 / XS3_JP2)")
    for env, iso in envs:
        if not iso:
            continue
        with DiscSource(iso) as d:
            if d.region.lang == "us":
                dbc2 = "mnu\\us\\DBC2.bin"
                text, meta = KINDS["nj"].export(dbc2, d.read(dbc2), d.region)
                esc = sum(1 for ln in text.splitlines() if "⟦A4⟧" in ln)
                if env == "XS3_PROTO":
                    check("ヴォークリンデⅡ" in text and esc == 0 and sum(map(len, meta.get("codecs", {}).values())) > 1400,
                          f"{env}: DBC2.bin (untranslated EUC-JP) reads as Japanese: "
                          f"{ {c: len(v) for c, v in meta.get('codecs', {}).items()} }, {esc} lines with ⟦A4⟧")
                else:
                    check(not meta.get("codecs") and "Woglinde" in text, f"{env}: DBC2.bin is all USA text")
            else:
                kinds = {}
                for p, k in collect(d.paths(), d.region):
                    kinds[k] = kinds.get(k, 0) + 1
                check(kinds.get("msgdat") == 1 and kinds.get("batdat") == 1 and kinds.get("txd") == 4
                      and kinds.get("nj") == 7 and kinds.get("sb", 0) > 400,
                      f"{env}: JP objects collected by region {kinds}")
            fc = FontCheck.from_disc(d.disc, d.region)
            if d.region.codec == "jp":
                check(fc.why_not("jp", "ア") is None and fc.why_not("jp", "縊") is not None,
                      f"{env}: font check: ア drawable, 縊 (E5D0, no glyph in either font) refused")
            else:
                check(fc.why_not("us", "é") is None and fc.why_not("us", "×") is None,
                      f"{env}: font check: é and × drawable")
        n, bad = roundtrip(iso, log=lambda *x: print("      " + " ".join(map(str, x))))
        check(n > 0 and not bad, f"{env}: text-roundtrip of {n} objects byte-identical {bad[:3] or ''}")
        if env in ("XS3_D1", "XS3_JP1"):
            # import planning on the real disc (writes nothing; the copy writes are exit tests)
            with tempfile.TemporaryDirectory() as tmp:
                export_discs([iso], tmp, log=lambda *x: None)
                ch, rows, _w = plan_import([iso], tmp)
                check(ch == {} and rows == [], f"{env}: the unchanged tree plans no change")
                if env == "XS3_JP1":
                    sp = Path(tmp) / "cf/jp/1220.sb.txt"
                    st = sp.read_text(encoding="utf-8")
                    old = "[ミズーリ]再搭乗の手続き申請は\\n現在受け付けておりません。<w45>"
                    sp.write_text(st.replace(old, "[ミズーリ]本日の受付は終了しました。<w45>"), encoding="utf-8")
                    ch, rows, _w = plan_import([iso], tmp)
                    check(list(ch) == ["cf\\jp\\1220.sb"] and rows[0]["action"] == "in-place"
                          and sb.parse(ch["cf\\jp\\1220.sb"], "jp").strings[116]
                          == "[ミズーリ]本日の受付は終了しました。<w45>".encode("euc_jp"),
                          f"{env}: an edit of cf\\jp\\1220.sb #116 plans in place ({rows[0]['old_size']} -> "
                          f"{rows[0]['new_size']} B)")
                    sp.write_text(st.replace(old, "[ミズーリ]縊<w45>"), encoding="utf-8")
                    raises(lambda: plan_import([iso], tmp), f"{env}: 縊 (no glyph) refused", "cannot be drawn")
                else:
                    tp = Path(tmp) / "mnu/us/menutext.txd.txt"
                    body = tp.read_text(encoding="utf-8")
                    tp.write_text(body.replace("### 0005\nFormation\n", "### 0005\nFormation Setup\n"), encoding="utf-8")
                    raises(lambda: plan_import([iso], tmp), f"{env}: a longer menutext without grow is refused", "--grow")
                    ch, rows, _w = plan_import([iso], tmp, grow=True)
                    check(list(ch) == ["mnu\\us\\menutext.txd"] and rows[0]["new_size"] == rows[0]["old_size"] + 6,
                          f"{env}: with grow it plans {rows[0]['old_size']} -> {rows[0]['new_size']} B, {rows[0]['action']}")
    print("self-test", "passed" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    if sys.argv[1:] == ["--self-test"]:
        sys.exit(self_test())
    ap = argparse.ArgumentParser(description="XS3 text export / import / round trip")
    add_commands(ap.add_subparsers(dest="cmd", required=True))
    a = ap.parse_args()
    sys.exit(a.func(a))
