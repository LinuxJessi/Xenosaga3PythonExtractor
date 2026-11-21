"""sb.py — Xenosaga III scene scripts (``cf\\xx\\*.sb``, ``bat\\xx\\*.sb``; xx = us or jp):
parse the text pool and rebuild it.

New for XS3. The XS2 kit's sb.py does NOT read these files (it raises
``SbError: section offsets out of order`` on cf/us/2940.sb): XS3 keeps its
strings inside the script as one section, and has no .sbl bank.

Layout (all 715 files on D1, D2 and the May 2006 prototype)::

    +0x00  'SB  '  u16 1  u16 1
    +0x08  u32 offset of the code section       (always 0x40)
    +0x0C  u32 offset of the globals section
    +0x10  u32 offset of the TEXT POOL
    +0x14  u32 offset of the entries section
    +0x18  u32 offset of the imports section    ('runtime', 'seg', 'objx', ...)
    +0x1C  u32 offset of the source name        (e.g. 'us\\2940')
    +0x20  zero to 0x40

    section  = u32 8 (its header size), u32 count, ...   (the name section: u32 1)
    text pool = u32 8, u32 count, u32 offsets[count] (relative to the end of the
                table), the strings NUL-terminated and contiguous in offset
                order, zero-padded to 4 bytes.

The engine fetches a string by index: SLUS FUN_001d4238 returns
``pool + 8 + count*4 + offs[i]`` (the section accessors
FUN_001d1328/1340/1358/1370/1388 are ``base + *(base+off)``). So the pool can
be rebuilt with any lengths as long as every header offset above it is moved
by the size change. Everything outside the pool is kept byte for byte.

Each string is classified (``classify``) for the export:

* ``dialogue``   ``[Speaker]<lN>...`` and other displayed text (USA codec)
* ``identifier`` labels and voice ids (``seg_now``, ``ce100_045``, ``runtime``): one ASCII
                 word, lower case or holding ``_``, a digit, ``:`` or ``/``
* ``untranslated`` Japanese placeholder lines shaped like dialogue (``[Speaker]``
                 and a ``<wN>``/``<f>``/``<lN>`` tag; 16 on D1): exported in their
                 exact Japanese codec for readability. If the scene runs them, the
                 USA build draws those bytes through its Latin-1 gate.
* ``note``       developers' comments, never drawn: Shift-JIS (most) or EUC-JP

A dialogue byte pair that is not a gate pair is drawn as two Latin-1 cells and
exported that way: the EUC ``？？`` (A1A9 A1A9) left in 15 D1 dialogue lines
reads ``¡©¡©``, which is what the USA build puts on screen.

Japanese build (region.JP; M9-M12)
----------------------------------
The pool layout is the same (856/856 files on JP1 rebuild byte-identically,
108,040 strings). Roles on JP (``classify(s, region)``):

* ``identifier`` as on USA;
* ``dialogue``   a ``[Speaker]`` prefix (10,133 strings on JP1). ``<lN>`` is
                 optional on JP (6,988 dialogue strings have none); when present,
                 N is the number of literal ``\\n``-separated lines in 3,132 of 3,145;
* ``text``       every other string: displayed text without a speaker and the
                 developers' notes, which JP stores in EUC like everything else.

Every string on JP is read with the JP codec (``codec_for`` -> ``jp``): the USA
notes are Shift-JIS, the JP ones are not, and NoteCodec's per-string guess
picked cp932 for 323 EUC strings. ``import_warnings`` flags an edit that
breaks an ``<lN>`` count or touches the pass-through tags the engine treats as
literal text: ``$rubyb;...$rubys;...$rubye;`` (ruby), and the no-op typo tags
``<ｗN>``, ``<ｆ>`` and ``<WN>`` (full-width / upper-case spellings of
``<wN>``/``<f>``; kept byte for byte).

140 ``cf\\jp\\*.sb`` scenes (2,287 dialogue strings) and ``bat\\jp\\mom1_b02.sb``
have no USA counterpart (measured against the USA Disc 1+2 indexes; names in
``JP_ONLY_SB``), with 118 ``cf\\*.t`` companions. Whether the game ever loads
them is NOT known: ``scene_status`` reports "JP-only, load status unknown" and
``jp_only_scenes(disc)`` lists them with their .t files.

Per-container API (for textpack and the import lane)::

    sc = parse(data, region)         Script; sc.items -> [textcodec.Item(key 'NNNN', raw, codec, role)]
    rebuild(sc, new) -> bytes         new = list of bytes or Items, same count and order

The loader's buffer size for .sb is NOT known (survey: not found), so a grown
.sb may overrun; the write path must keep a budget rule.

    python sb.py --self-test
"""
from __future__ import annotations

import os
import re
import struct
import sys
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import region as _region                                           # noqa: E402
import textcodec                                                   # noqa: E402

MAGIC = b"SB  "
HDR = 0x08               # first of the six section offsets
POOL_SLOT = 0x10         # header field holding the pool offset


class SbError(ValueError):
    pass


@dataclass
class Script:
    data: bytes
    secs: List[int]                      # the six offsets at +0x08..+0x1C
    pool: int                            # offset of the pool section
    pool_end: int                        # offset of the next section
    strings: List[bytes] = field(default_factory=list)
    region: object = None                # region.Region the roles/codecs are for

    @property
    def items(self) -> List[textcodec.Item]:
        out = []
        for i, s in enumerate(self.strings):
            role = classify(s, self.region)
            out.append(textcodec.Item(f"{i:04d}", s, codec_for(s, role, self.region), role,
                                      tuple(tag_flags(s))))
        return out


def parse(data: bytes, region=None) -> Script:
    if data[:4] != MAGIC or len(data) < 0x40:
        raise SbError("not an XS3 'SB  ' script")
    secs = list(struct.unpack_from("<6I", data, HDR))
    pool = secs[2]
    after = sorted(x for x in secs if x > pool)
    if not after:
        raise SbError("no section after the text pool")
    pool_end = after[0]
    kind, count = struct.unpack_from("<II", data, pool)
    if kind != 8:
        raise SbError(f"text pool header size {kind}, expected 8")
    base = pool + 8 + 4 * count
    if base > pool_end:
        raise SbError("text pool table runs past the next section")
    offs = struct.unpack_from(f"<{count}I", data, pool + 8)
    strings = []
    for o in offs:
        e = data.find(b"\0", base + o, pool_end)
        if e < 0:
            raise SbError("unterminated string in the text pool")
        strings.append(data[base + o:e])
    return Script(data, secs, pool, pool_end, strings, _region.as_region(region))


def build_pool(strings: List[bytes]) -> bytes:
    offs, blob = [], bytearray()
    for s in strings:
        if b"\0" in s:
            raise SbError("a NUL byte inside a string")
        offs.append(len(blob))
        blob += s + b"\0"
    out = struct.pack("<II", 8, len(strings)) + struct.pack(f"<{len(strings)}I", *offs) + bytes(blob)
    return out + b"\0" * ((-len(out)) % 4)


def rebuild(script: Script, strings: List[bytes]) -> bytes:
    """The script with its pool replaced by ``strings`` (same count) and every header
    offset above the pool moved by the size change."""
    strings = [textcodec.raw_of(x) for x in strings]
    if len(strings) != len(script.strings):
        raise SbError(f"{len(strings)} strings given, the pool holds {len(script.strings)}")
    d = script.data
    pool = build_pool(strings)
    delta = len(pool) - (script.pool_end - script.pool)
    secs = [x + delta if x > script.pool else x for x in script.secs]
    out = d[:HDR] + struct.pack("<6I", *secs) + d[HDR + 24:script.pool] + pool + d[script.pool_end:]
    return out


_ID = re.compile(rb"^[A-Za-z0-9_/:\-]+$")
# the shape of a displayed line: a [Speaker] tag and one of the game's own tags
_SHOWN = re.compile(rb"^\[[^\]]+\].*<(w\d+|f|l\d+)>", re.S)


_SPEAKER = re.compile(rb"^\[[^\]\0]+\]")
_LTAG = re.compile(rb"<l(\d+)>")
# pass-through tags (M11): ruby markup and the no-op typo spellings of <wN>/<f>
# (EUC full-width ｗ = A3F7, ｆ = A3E6)
_PASS = (("ruby", re.compile(rb"\$rubyb;")), ("fullwidth-w", re.compile(rb"<\xa3\xf7(?:[0-9]|\xa3[\xb0-\xb9])+>")),
         ("fullwidth-f", re.compile(rb"<\xa3\xe6>")), ("upper-W", re.compile(rb"<W\d+>")))


def _is_identifier(s: bytes) -> bool:
    return bool(s) and bool(_ID.match(s)) and (s.islower() or any(c in s for c in b"_0123456789/:"))


def classify(s: bytes, region=None) -> str:
    """USA: dialogue / identifier / untranslated / note; JP: identifier / dialogue /
    text (module docstring). ``region`` is a region.Region or name; None = USA."""
    if _is_identifier(s):
        return "identifier"
    if _region.as_region(region).codec == "jp":
        return "dialogue" if _SPEAKER.match(s) else "text"
    if textcodec.NoteCodec.pick(s) != "us":
        # Japanese bytes shaped like a shown line ('[ファルリン]シチュエーション３
        # （仮）<w30>', cf\us\1250.sb #125): placeholder dialogue left
        # untranslated, not a comment
        return "untranslated" if _SHOWN.match(s) else "note"
    return "dialogue"


def codec_for(s: bytes, role: str, region=None) -> str:
    """The export codec. JP: always the JP print reading (notes included). USA: the
    Japanese reading that is exact for a note or an untranslated line (the USA build
    itself would draw those bytes as Latin-1 cells), the USA print reading otherwise."""
    if _region.as_region(region).codec == "jp":
        return "jp"
    return textcodec.NoteCodec.pick(s) if role in ("note", "untranslated") else "us"


def line_count(s: bytes) -> int:
    """Lines of a dialogue string: literal backslash-n separators + 1."""
    return s.count(b"\\n") + 1


def tag_flags(s: bytes) -> List[str]:
    """The pass-through tags a string carries, plus 'lN-mismatch' when its <lN>
    disagrees with its line count (13 retail JP lines already do)."""
    out = [name for name, rx in _PASS if rx.search(s)]
    m = _LTAG.search(s)
    if m and int(m.group(1)) != line_count(s):
        out.append("lN-mismatch")
    return out


def import_warnings(old: bytes, new: bytes, region=None) -> List[str]:
    """Warnings for replacing ``old`` with ``new`` (never errors): an <lN> that no
    longer matches the line count (only when it matched before), and pass-through
    tags added, removed or changed."""
    out = []
    m = _LTAG.search(new)
    if m and int(m.group(1)) != line_count(new) and "lN-mismatch" not in tag_flags(old):
        out.append(f"<l{m.group(1).decode()}> but the text has {line_count(new)} line(s)")
    for name, rx in _PASS:
        if rx.findall(old) != rx.findall(new):
            out.append(f"{name} tag(s) changed: the engine passes them through as written")
    return out


# 140 cf\jp scenes and one bat\jp scene with no USA counterpart, measured from the
# JP Disc 1+2 and USA Disc 1+2 indexes (2026-11-20); x8-numbered mostly, not all
JP_ONLY_SB = frozenset("""
1118 1148 1218 1228 1238 1248 1258 1268 1278 1288 1298 1308 1318 1328 1348 1418 1428 1438 1448
1458 1468 1478 1488 1498 1638 1648 1658 1668 1728 1738 1748 1758 1768 1858 1888 1898 1908 1918
1948 1978 1988 2318 2328 2418 2628 2638 2648 2718 2728 2738 2748 2758 2768 2778 2788 2918 2928
2938 2948 2958 2968 2978 2988 2998 3118 3128 3138 3148 3150 3168 3178 3188 3198 3208 3218 3228
3238 3248 3258 3268 3278 3288 3298 3308 3318 3328 3338 3348 3358 3428 3438 3448 3468 3488 3528
3598 3758 3810 3828 3838 3848 3858 3868 3878 4048 4078 4118 4158 4198 4328 4418 7045 7115 7120
7125 7155 7160 7250 7265 7280 7320 7325 7375 7455 7490 7495 7500 7505 7525 7530 7540 7555 8180
8260 8265 8570 8715 8772 8865 8937
""".split())
JP_ONLY_BAT_SB = frozenset({"mom1_b02"})
# 118 cf\*.t scene files with no USA counterpart: 117 belong to a JP-only .sb, plus
# 3930.t whose 3930.sb exists on USA too
JP_ONLY_T = JP_ONLY_SB | {"3930"}
JP_ONLY_STATUS = "JP-only, load status unknown"


def scene_status(path: str) -> Optional[str]:
    """``JP_ONLY_STATUS`` for a JP .sb (or its cf\\*.t) that has no USA counterpart."""
    low = path.replace("/", "\\").lstrip("\\").lower()
    name = low.rsplit("\\", 1)[-1].rsplit(".", 1)[0]
    if low.startswith("cf\\jp\\") and low.endswith(".sb") and name in JP_ONLY_SB:
        return JP_ONLY_STATUS
    if low.startswith("bat\\jp\\") and low.endswith(".sb") and name in JP_ONLY_BAT_SB:
        return JP_ONLY_STATUS
    if low.count("\\") == 1 and low.startswith("cf\\") and low.endswith(".t") and name in JP_ONLY_T:
        return JP_ONLY_STATUS
    return None


def jp_only_scenes(disc) -> List[Tuple[str, Optional[str]]]:
    """(sb path, cf .t path or None) of each JP-only scene on a disc.Disc."""
    out = []
    for _c, e in disc.entries():
        p = e.path.lstrip("\\")
        if p.lower().endswith(".sb") and scene_status(p):
            name = p.rsplit("\\", 1)[-1][:-3]
            t = f"cf\\{name}.t"
            hit = disc.lookup(t) if p.lower().startswith("cf\\") else None
            out.append((p, hit[1].path.lstrip("\\") if hit else None))
    return sorted(set(out))


def self_test() -> int:
    ok = True

    def check(cond, msg):
        nonlocal ok
        print(("ok    " if cond else "FAIL  ") + msg)
        ok &= bool(cond)

    # synthetic script: code, globals, pool, entries, imports, name
    def sec(n, body):
        return struct.pack("<II", 8, n) + body
    code = struct.pack("<II", 12, 1) + b"\x01\x02\x03\x04"
    glob_ = sec(0, b"")
    strs = [b"[Shion]<l1>Hello.<w15>", "＊BGM＊".encode("cp932"), b"seg_now"]
    pool = build_pool(strs)
    ents, imps, name = sec(1, b"abcd"), sec(1, b"runtime\0"), struct.pack("<II", 1, 8) + b"us\\0000\0"
    parts = [code, glob_, pool, ents, imps, name]
    offs, cur = [], 0x40
    for p in parts:
        offs.append(cur)
        cur += len(p)
    data = MAGIC + struct.pack("<HH", 1, 1) + struct.pack("<6I", *offs) + b"\0" * 0x20 + b"".join(parts)
    s = parse(data)
    check(s.strings == strs, "synthetic: pool strings read back")
    check(rebuild(s, s.strings) == data, "synthetic: unchanged rebuild is byte-identical")
    new = rebuild(s, [b"[Shion]<l1>Hello there, this line grew.<w15>", strs[1], strs[2]])
    s2 = parse(new)
    check(s2.strings[0].endswith(b"grew.<w15>") and new[s2.secs[3]:] == data[s.secs[3]:],
          "synthetic: a grown string moves the later sections, bytes after the pool unchanged")
    check([classify(x) for x in strs] == ["dialogue", "note", "identifier"], "classify dialogue/note/identifier")
    ph = "[アビー]…　！…<w45>".encode("cp932")
    check(classify(ph) == "untranslated" and codec_for(ph, "untranslated") == "cp932",
          "a Japanese line shaped like dialogue is 'untranslated', exported as cp932")

    jp = _region.JP
    jl = "[シオン]<l1>テスト。<w15>".encode("euc_jp")
    check([classify(x, jp) for x in (jl, "＊メモ＊".encode("euc_jp"), b"seg_now", "[ア]あ".encode("euc_jp"))]
          == ["dialogue", "text", "identifier", "dialogue"], "JP: classify dialogue ([Speaker], <lN> optional) / text / identifier")
    check(all(codec_for(x, classify(x, jp), jp) == "jp" for x in (jl, "＊メモ＊".encode("euc_jp"), b"seg_now")),
          "JP: every string uses the JP codec, notes included")
    check(codec_for("＊BGM設定＊".encode("cp932"), "note") == "cp932", "USA notes keep their per-string reading")
    s2 = parse(data, "jp")
    check([i.codec for i in s2.items] == ["jp"] * 3 and [i.key for i in s2.items] == ["0000", "0001", "0002"]
          and rebuild(s2, s2.items) == data, "items API: keys, JP codecs; rebuild accepts Items")
    two = "[ア]<l2>一行目\\n二行目".encode("euc_jp")
    check(line_count(two) == 2 and "lN-mismatch" not in tag_flags(two), "<lN> = literal \\n lines + 1")
    check(import_warnings(two, "[ア]<l2>一行".encode("euc_jp"), jp) != [], "an edit breaking <lN> warns")
    ruby = "[ア]$rubyb;漢字$rubys;かんじ$rubye;<ｗ15>".encode("euc_jp")
    check(set(tag_flags(ruby)) == {"ruby", "fullwidth-w"} and import_warnings(ruby, ruby.replace(b"$rubyb;", b""), jp),
          "ruby and <ｗN> are flagged as pass-through; removing one warns")
    check(scene_status("cf\\jp\\1218.sb") == JP_ONLY_STATUS and scene_status("\\cf\\1218.t") == JP_ONLY_STATUS
          and scene_status("cf\\jp\\1220.sb") is None and scene_status("bat\\jp\\mom1_b02.sb") == JP_ONLY_STATUS
          and scene_status("cf\\3930.t") == JP_ONLY_STATUS and len(JP_ONLY_SB) == 140, "JP-only scenes: 140 cf names + bat mom1_b02, flagged 'load status unknown'")

    isos = [(k, os.environ.get(k)) for k in ("XS3_D1", "XS3_D2", "XS3_PROTO", "XS3_JP1", "XS3_JP2")]
    if not any(v for _, v in isos):
        print("SKIP  disc checks (set XS3_D1 / XS3_D2 / XS3_PROTO / XS3_JP1 / XS3_JP2)")
    from disc import Disc
    for env, iso in isos:
        if not iso:
            continue
        with Disc(iso) as disc:
            reg = _region.detect(disc)
            paths = [e.path for _c, e in disc.entries() if e.path.lower().endswith(".sb")]
            bad, roles, n, lbad, ltot, esc, jponly = 0, {}, 0, 0, 0, 0, 0
            for p in paths:
                sc = parse(disc.read(p), reg)
                if rebuild(sc, sc.strings) != sc.data or build_pool(sc.strings) != sc.data[sc.pool:sc.pool_end]:
                    bad += 1
                jponly += scene_status(p) is not None
                for it in sc.items:
                    n += 1
                    roles[it.role] = roles.get(it.role, 0) + 1
                    t = textcodec.codec_by_name(it.codec).to_text(it.raw)
                    esc += "⟦" in t and reg.codec == "jp"
                    if it.role == "dialogue" and _LTAG.search(it.raw):
                        ltot += 1
                        lbad += "lN-mismatch" in it.flags
            check(len(paths) > 0 and bad == 0,
                  f"{env}: {len(paths)} .sb rebuild byte-identical ({bad} differ), {n} strings; roles {roles}")
            if reg.codec == "jp":
                t_only = [e.path for _c, e in disc.entries() if e.path.lower().endswith(".t")
                          and scene_status(e.path)]
                check(esc == 0 and jponly > 0,
                      f"{env}: 0 JP strings need escapes ({esc}); <lN> agrees in {ltot - lbad}/{ltot}; "
                      f"{jponly} JP-only .sb {len(t_only)} JP-only cf .t")
    print("self-test", "passed" if ok else "FAILED")
    return 0 if ok else 1


def add_commands(subparsers) -> None:
    p = subparsers.add_parser("sb-strings", help="list the text pool of an XS3 .sb file (local file)")
    p.add_argument("file")
    p.add_argument("--region", default="us", help="build profile: us (default), proto_2006_05 or jp")

    def run(a):
        sc = parse(open(a.file, "rb").read(), a.region)
        for it in sc.items:
            t = textcodec.codec_by_name(it.codec).to_text(it.raw)
            flags = f" [{','.join(it.flags)}]" if it.flags else ""
            print(f"{it.key} {it.role:10s} {it.codec:6s} {t}{flags}")
        return 0
    p.set_defaults(func=run)


if __name__ == "__main__":
    if sys.argv[1:] == ["--self-test"]:
        sys.exit(self_test())
    print(__doc__)
