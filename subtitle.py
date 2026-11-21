"""subtitle.py — Xenosaga III whole-file text: timed subtitles (``mov\\xx\\*.txt``,
``mov\\xx\\bat\\*.txt``, ``evt\\xx\\*.txt``) and the pse files (``mnu\\pse\\*.txt``
director scripts, ``mnu\\pse\\xx\\*.mes`` message files); xx = us or jp.

Idea borrowed from Xenosaga2PythonExtractor/textpack.py (kinds ``subtitle``
and ``quest``: the file itself is the export) and textcodec.UsSubtitleCodec.
What changed: the whole file is one exact text (``;`` comment lines, empty
clear cues and the files' LF / CR LF / mixed line ends kept byte for byte;
the tree file is written with ``newline=""``), and the codec is chosen per
file by its role and the build (``region``, or the language folder of the
path when no region is given):

    role         path                       USA codec                JP codec
    movie        mov\\xx\\..., mov\\xx\\bat\\...  us (print reading)       jp
    event        evt\\xx\\...                 us                       jp
    pse-script   mnu\\pse\\*.txt              cp932 (shared, byte-identical on both builds)
    pse-mes      mnu\\pse\\xx\\*.mes           euc_jp if Japanese        jp
                                            (AC, PP, opening, test ship
                                            untranslated), else us

Subtitle grammar (survey, packer SLUS FUN_001b27b8 / cue packer FUN_001b2520 /
loader FUN_001b2f60; JP 0x1b2558 / 0x1b2188 / 0x1b2658, region.py; and the
developers' own header comment in every JP file): ``;`` starts a comment line;
a cue is ``mm:ss:ff<TAB>text``, a plain frame count, or either with a leading
``+`` (relative); literal ``\\n`` breaks a line; ``[漢字/かんじ]`` is ruby
(the packer turns it into $ruby tags); time 0 carries the style line
(``$ay375;$xx0,24;$rubyy-4;$col707070;``); ``end`` closes the file; a first line
``mono`` selects the USA loader's mono branch.

JP rules (``check_edit``; M17-M19), on top of the exact codec:

* no ``mono``: the JP loader (0x1b2658, 320 bytes vs USA 368) has no mono branch;
* ``mov\\jp\\bat\\*.txt``: the developers' note in each file says
  "ファイルサイズ制限あり 1K以内に納めること" (size limit, keep within 1K) and
  "ルビはひらがなカタカナのみ" (ruby in hiragana/katakana only): a file over 1,024
  bytes or with non-kana ruby is refused. That 1K is the documented rule, NOT an
  instruction-checked buffer size (largest retail file 558 bytes);
* ruby must be ``[base/reading]``: one ``/``, no nesting, closed on its line;
* ruby needs a non-empty base and reading; a ``]`` outside a ruby is refused;
* every line outside a ``/* ... */`` block (retail has such blocks after the last
  cue; they are left to the loader) is blank, a ``;`` comment, ``end``, ``mono``
  or a cue, and a cue carries one of the three time forms above. A text line with
  no time is refused, since nothing shows how the loader treats one. The time and
  text are split by a tab, once by spaces in retail (s061400), which is accepted.

The packed-size rule of FUN_001b27b8 (USA) / 0x1b2558 (JP) is NOT ported.

Per-container API::

    items(path, data, region) -> [textcodec.Item('*', data, codec, role)]
    to_text(path, data, region) -> (codec, text)        from_text(text, codec) -> bytes
    encode(path, text, codec, region) -> bytes          from_text + check_edit, raises TextError

    python subtitle.py --self-test
"""
from __future__ import annotations

import os
import re
import sys
from typing import List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import region as _region                                           # noqa: E402
import textcodec                                                   # noqa: E402


def _parts(path: str) -> List[str]:
    return path.replace("/", "\\").lstrip("\\").lower().split("\\")


def path_lang(path: str) -> Optional[str]:
    """The language folder of a subtitle/pse path (mov\\jp\\x.txt -> 'jp'), or None."""
    p = _parts(path)
    if len(p) >= 3 and p[0] in ("mov", "evt") and p[1] in _region.LOCALE_ORDER:
        return p[1]
    if len(p) == 4 and p[:2] == ["mnu", "pse"] and p[2] in _region.LOCALE_ORDER:
        return p[2]
    return None


def role(path: str, region=None) -> Optional[str]:
    """movie / event / pse-mes / pse-script, or None. With a region, the language
    folder must be that build's."""
    p = _parts(path)
    lang = path_lang(path)
    if region is not None and lang is not None and lang != _region.as_region(region).lang:
        return None
    if lang and p[0] == "mov" and p[-1].endswith(".txt"):
        return "movie"
    if lang and p[0] == "evt" and p[-1].endswith(".txt"):
        return "event"
    if lang and p[:2] == ["mnu", "pse"] and p[-1].endswith(".mes"):
        return "pse-mes"
    if len(p) == 3 and p[:2] == ["mnu", "pse"] and p[-1].endswith(".txt"):
        return "pse-script"
    return None


def _region_for(path: str, region):
    if region is not None:
        return _region.as_region(region)
    return _region.JP if path_lang(path) == "jp" else _region.US


def codec_name(path: str, data: bytes, region=None) -> str:
    r = role(path)
    if r == "pse-script":
        return "cp932" if textcodec._exact(data, "cp932") else "us"
    reg = _region_for(path, region)
    if reg.codec == "jp":
        return "jp"
    if r == "pse-mes":
        return "euc_jp" if textcodec._japanese_euc(data) else "us"
    return "us"


def to_text(path: str, data: bytes, region=None) -> Tuple[str, str]:
    name = codec_name(path, data, region)
    return name, textcodec.codec_by_name(name).to_text(data, file=True)


def from_text(text: str, name: str) -> bytes:
    return textcodec.codec_by_name(name).from_text(text)


def items(path: str, data: bytes, region=None) -> List[textcodec.Item]:
    return [textcodec.Item("*", data, codec_name(path, data, region), role(path) or "")]


BAT_LIMIT = 1024
_TIME = re.compile(r"^\+?(\d+:\d+:\d+|\d+)$")
_KANA = re.compile(r"^[\u3041-\u309f\u30a0-\u30ff]+$")


def check_edit(path: str, data: bytes, region=None, codec: Optional[str] = None) -> List[str]:
    """Problems that would make the game misread a subtitle file (module docstring);
    an empty list means it passes. Only the movie/event roles are checked."""
    r = role(path)
    if r not in ("movie", "event"):
        return []
    reg = _region_for(path, region)
    codec = codec or codec_name(path, data, reg)
    text = textcodec.codec_by_name(codec).to_text(data, file=True)
    out = []
    lines = text.replace("\r\n", "\n").split("\n")
    first = next((ln.strip() for ln in lines if ln.strip()), "")
    battle = len(_parts(path)) == 4 and _parts(path)[2] == "bat"
    if first == "mono" and not reg.mono_subtitles:
        out.append("'mono' is not supported: the Japanese subtitle loader has no mono branch")
    if reg.codec == "jp" and battle and len(data) > BAT_LIMIT:
        out.append(f"{len(data)} bytes: the developers' rule for battle subtitles is 1K "
                   f"(ファイルサイズ制限あり 1K以内に納めること), at most {BAT_LIMIT} bytes")
    in_comment = False
    for no, ln in enumerate(lines, 1):
        if in_comment:
            in_comment = "*/" not in ln
            continue
        if ln.lstrip().startswith("/*"):   # retail has /* ... */ blocks after the last cue: left to the loader
            in_comment = "*/" not in ln.lstrip()[2:]
            continue
        if not ln.strip() or ln.startswith(";") or ln.strip() in ("end", "mono"):
            continue
        if ln.lstrip()[:1] not in "+0123456789":
            out.append(f"line {no}: not a cue: a cue line starts with its time (mm:ss:ff, a frame count, "
                       f"or either with '+'), comments start with ';' or sit in /* ... */: {ln[:24]!r}")
            continue
        ln = ln.lstrip()                   # the May 2006 prototype has one cue indented by a space (s025300)
        m = re.match(r"^(\S+)[ \t]*(.*)$", ln)
        t, body = m.group(1), m.group(2)      # retail separates with a tab, once with spaces (s061400)
        if not body:
            if not _TIME.match(t):
                out.append(f"line {no}: time {t!r} is not mm:ss:ff, a frame count, or either with '+'")
            continue                       # a time alone: an empty (clearing) cue
        if not _TIME.match(t.strip()):
            out.append(f"line {no}: time {t!r} is not mm:ss:ff, a frame count, or either with '+'")
        if reg.codec != "jp":
            continue
        pos = 0
        while True:
            i = body.find("[", pos)
            if i < 0:
                break
            j = body.find("]", i)
            inner = body[i + 1:j] if j >= 0 else ""
            if j < 0 or "[" in inner or inner.count("/") != 1:
                out.append(f"line {no}: ruby must be [base/reading]: {body[i:i + 24]!r}")
                break
            base, reading = inner.split("/", 1)
            if not base.strip() or not reading.strip():
                out.append(f"line {no}: ruby needs both a base and a reading: {body[i:j + 1]!r}")
                break
            if battle and not _KANA.match(reading):
                out.append(f"line {no}: battle ruby must be hiragana/katakana only "
                           f"(ルビはひらがなカタカナのみ): {reading!r}")
            pos = j + 1
        if "]" in re.sub(r"\[[^\[\]]*\]", "", body):
            out.append(f"line {no}: ']' outside a [base/reading] ruby: {body[:24]!r}")
    return out


def encode(path: str, text: str, codec: str, region=None) -> bytes:
    """``from_text`` plus ``check_edit``: TextError on any problem."""
    data = from_text(text, codec)
    probs = check_edit(path, data, region, codec)
    if probs:
        raise textcodec.TextError(f"{path}: " + "; ".join(probs))
    return data


_CUE = re.compile(r"^(\+?\d+:\d+:\d+|\d+)\t(.*)$")


def cues(text: str) -> List[Tuple[str, str]]:
    """(time, text) of each cue line of a subtitle file (for listing only)."""
    out = []
    for ln in text.replace("\r\n", "\n").split("\n"):
        m = _CUE.match(ln)
        if m:
            out.append((m.group(1), m.group(2)))
    return out


def self_test() -> int:
    ok = True

    def check(cond, msg):
        nonlocal ok
        print(("ok    " if cond else "FAIL  ") + msg)
        ok &= bool(cond)

    sub = b"00:00:00\t$ay375;$xx0,24;\r\n00:14:20\tHere it is.\\nI\x92m sure.\n00:20:00\tend\r\n"
    name, t = to_text("\\mov\\us\\s000300.txt", sub)
    check(name == "us" and from_text(t, name) == sub and "\r\n" in t and "⟦92⟧" in t,
          "movie subtitle: us codec, mixed line ends kept, 0x92 is ⟦92⟧")
    check(len(cues(t)) == 3, "cue lines parsed")
    scr = "//\tあらすじ\r\n#MAXCUT 3\r\n".encode("cp932")
    check(to_text("\\mnu\\pse\\episode1.txt", scr) == ("cp932", "//\tあらすじ\r\n#MAXCUT 3\r\n"), "pse script: cp932")
    mes = "#MESSAGE 0\r\nテスト\r\n".encode("euc_jp")
    check(to_text("\\mnu\\pse\\us\\AC.mes", mes)[0] == "euc_jp", "Japanese .mes: euc_jp")
    check(to_text("\\mnu\\pse\\us\\EP1.mes", b"#MESSAGE 0\r\n20XX A.D.\r\n")[0] == "us", "English .mes: us")
    check(role("\\mov\\us\\bat\\CHRV_EVE0001.txt") == "movie" and role("\\evt\\us\\s000700.txt") == "event"
          and role("\\mnu\\pse\\us\\x.txt") is None, "roles by path")

    jsub = ";字幕\r\n00:00:00\t$ay365;\r\n00:00:01\t[永遠の連環/ツァラトゥストラ]を紡ぐ者よ\n\nend\n"
    jb = from_text(jsub, "jp")
    check(to_text("\\evt\\jp\\s000100.txt", jb) == ("jp", jsub) and check_edit("evt\\jp\\s000100.txt", jb) == [],
          "JP event subtitle: jp codec, ';' comments, mixed line ends and an empty cue kept; ruby ok")
    check(role("mov\\jp\\bat\\CHRV_EVE0000.txt") == "movie" and role("mnu\\pse\\jp\\EP1.mes") == "pse-mes"
          and codec_name("mnu\\pse\\jp\\AC.mes", mes) == "jp" and role("mov\\us\\x.txt", "jp") is None,
          "JP roles by path; .mes on JP uses the jp codec; a region filters other folders")
    mono = from_text("mono\r\n\r\n00:05:00\t30,30,30,00:10:00,60,text\n", "jp")
    check(check_edit("mov\\jp\\s020000.txt", mono) != [] and check_edit("mov\\us\\s020000.txt", mono, "us") == [],
          "'mono' is refused on JP, allowed on USA")
    big = from_text("00:00:00\t$ay390;\n00:00:02\t" + "あ" * 600 + "\nend\n", "jp")
    check(check_edit("mov\\jp\\bat\\X.txt", big) != [] and check_edit("mov\\jp\\X.txt", big) == [],
          "JP battle subtitles over 1,024 bytes are refused (the developers' 1K rule)")
    for bad, why in (("00:00:02\t[漢字かんじ]\n", "ruby without '/'"), ("00:00:02\t[漢字/かん\n", "unclosed ruby"),
                     ("0:0\tx\n", "a malformed time"), ("テスト行\n", "a text line with no time"),
                     ("30\t[/かんじ]x\n", "an empty ruby base"), ("30\tabc]def\n", "a stray ']'")):
        check(check_edit("evt\\jp\\a.txt", from_text(bad, "jp")) != [], f"JP: {why} is refused")
    check(check_edit("evt\\jp\\a.txt", from_text("00:00:01\tx\nend\n/* メモ\nテスト行 */\n/* 一行 */\n", "jp")) == []
          and check_edit("evt\\jp\\a.txt", from_text("30 テスト\n", "jp")) == [],
          "JP: /* ... */ blocks (one or many lines) and a space separator (retail s061400) pass")
    check(check_edit("mov\\jp\\bat\\a.txt", from_text("00:00:02\t[漢字/漢字]\n", "jp")) != [],
          "JP battle ruby must be kana")
    try:
        encode("mov\\jp\\s020000.txt", "mono\n00:00:01\tx\n", "jp")
        check(False, "encode raises on a refused edit")
    except textcodec.TextError:
        check(True, "encode raises on a refused edit")

    isos = [(k, os.environ.get(k)) for k in ("XS3_D1", "XS3_D2", "XS3_PROTO", "XS3_JP1", "XS3_JP2")]
    if not any(v for _, v in isos):
        print("SKIP  disc checks (set XS3_D1 / XS3_D2 / XS3_PROTO / XS3_JP1 / XS3_JP2)")
    from disc import Disc
    sets = {}
    for env, iso in isos:
        if not iso:
            continue
        with Disc(iso) as disc:
            reg = _region.detect(disc)
            n, bad, kinds, probs, esc, comments = 0, [], {}, [], 0, 0
            files = {}
            for _c, e in disc.entries():
                p = e.path
                if role(p, reg) is None:
                    continue
                d = disc.read_entry(e)
                files[p.lower()] = d
                name, t = to_text(p, d, reg)
                kinds[f"{role(p)}/{name}"] = kinds.get(f"{role(p)}/{name}", 0) + 1
                n += 1
                if from_text(t, name) != d:
                    bad.append(p)
                pr = check_edit(p, d, reg)
                if pr:
                    probs.append((p, pr[0]))
                if reg.codec == "jp" and role(p) != "pse-script":
                    esc += "⟦" in t
                    comments += sum(1 for ln in t.split("\n") if ln.startswith(";"))
            sets[env] = files
            check(n > 0 and not bad, f"{env}: {n} subtitle/pse files exact {kinds} {bad[:3] or ''}")
            check(not probs, f"{env}: check_edit passes every retail file {probs[:2] or ''}")
            if reg.codec == "jp":
                check(esc == 0, f"{env}: 0 JP files need escapes; {comments} ';' comment lines kept")
    if "XS3_JP1" in sets and "XS3_JP2" in sets:
        a, b = sets["XS3_JP1"], sets["XS3_JP2"]
        diff = sum(1 for k in set(a) | set(b) if a.get(k) != b.get(k))
        print(f"      JP1 vs JP2: {len(a)} / {len(b)} files, {diff} differ or exist on one disc only")
    print("self-test", "passed" if ok else "FAILED")
    return 0 if ok else 1


def add_commands(subparsers) -> None:
    p = subparsers.add_parser("subtitle-text", help="show an XS3 subtitle/pse file as text (local file + its disc path)")
    p.add_argument("file")
    p.add_argument("discpath", help="its in-game path, e.g. \\mov\\us\\s000300.txt (sets the codec)")
    p.add_argument("--region", default=None, help="build profile (default: from the path's language folder)")

    def run(a):
        name, t = to_text(a.discpath, open(a.file, "rb").read(), a.region)
        sys.stdout.write(f"# codec {name}\n{t}")
        return 0
    p.set_defaults(func=run)


if __name__ == "__main__":
    if sys.argv[1:] == ["--self-test"]:
        sys.exit(self_test())
    print(__doc__)
