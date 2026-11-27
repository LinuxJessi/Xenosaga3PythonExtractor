"""txfam_core.py — the translation editor's readers and writers for Episode III.

The Episode I editor has one module per text family, each with its own
container code. Episode III's containers are already read and rebuilt,
byte-exact, by the kit's text pipeline (``textpack.KINDS``: sb, txd, nj,
msgdat, batdat, subtitle), so the four family modules here are thin: each
names the kinds it owns, and this module does the work once.

    family      kinds            what
    txfam_sb    sb               scene scripts: dialogue with [Speaker], notes
    txfam_mnu   txd, nj          menus, synopsis, the database and menu tables
    txfam_bat   batdat, msgdat   battle names and descriptions, the HaKox mini-game
    txfam_sub   subtitle         movie / event / battle-voice subtitles, the
                                 Episode I-II recap messages, director scripts

Rows (the catalog schema of ``txcatalog``)::

    id       "<fam>:<in-game path with />#<key>"   e.g. sb:cf/us/1210.sb#0003
             key = the container's own string key (text-export's ``### KEY``);
             for a whole text file: L<line> (a subtitle cue), M<n> (a .mes
             message), S<line> (a director-script line)
    src      the original in display form (``txcodec.to_display``)
    ctl      the codec the translation is written in (``us`` / ``jp``; a
             developers' note keeps its own ``cp932`` / ``euc_jp``); ``.f`` = a
             row cut from a text file
    font     ``field`` = drawn by the game (font check), ``note`` = never drawn
    ctx      the speaker of a dialogue line, or what the string is
    lock     why a string cannot change (an nj ``fixed`` block; a keyword that
             follows its ``<k...>`` tag)
    hide     why a string is not offered by default (identifier, debug print,
             note, style line)
    use      scene scripts: what the script's CODE does with the string
             (``dialogue.string_kinds``): event box npc choice think system
             battle banner table keyword debug resource unused; "" when the
             code could not be read and the shape rule was used
    px, lim  width guide and byte limit, where one is traced to the game's
             code (``GUIDES``); None = not known

Scene scripts are classified by their code, not by the look of the string
(2026-11-21): a string is offered when a native that draws text receives it
(or the script reads it through a table). The developers' debug prints
(``deb.put``; 84,526 strings on Japan Disc 1, 73,601 on USA Disc 1) are hidden
and never font-checked, whatever they look like. The keyword a townsperson
waits for (``extalk.KeyWait``) is the body of a ``<kWORD>`` tag of a line in
the same script: its row is LOCKED and a build writes it from the translated
tag (``effective``), so the two cannot drift apart.

A string the USA build holds in Japanese but would draw (16 placeholder
lines in the scripts, untranslated database entries) is shown in Japanese and
its translation is written in the build's own codec, since that is how the
print function will read it.

One disc set = one catalog: ``txdiscs.pair(iso)`` gives Disc 1 + Disc 2; the
chain-0 objects are listed once (the same bytes on both discs), each disc's
movie subtitles under their own paths.

Writing: ``plan(edits, iso)`` returns ``{in-game path: new bytes}`` for the
objects whose bytes change, built by the same ``Kind.build`` functions
text-import uses and read back before they are returned. ``txbuild`` hands
the union to ``patch.patch_copy`` (verified copies of both discs; the source
images are never written). Nothing here writes a file.

    python txfam_core.py selftest --iso DISC
"""
from __future__ import annotations

import os
import re
import sys
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import textcodec  # noqa: E402
import txcodec as tc  # noqa: E402
import txdiscs  # noqa: E402

FAM_KINDS = {"sb": ("sb",), "mnu": ("txd", "nj"), "bat": ("batdat", "msgdat"), "sub": ("subtitle",)}
KIND_FAM = {k: f for f, ks in FAM_KINDS.items() for k in ks}
FACE = "font0"

HIDE_ID = "identifier (a label or voice id the scripts look up by name)"
HIDE_DEBUG = "debug print (the script only hands it to deb.put; never drawn)"
HIDE_UNUSED = "not used by the script's code"
LOCK_KEYWORD = ("a keyword a townsperson waits for: it follows the <k...> word of its line, "
                "translate it there")
HIDE_NOTE = "developers' note (never shown in the game)"
HIDE_EMPTY = "empty"
HIDE_NOLETTERS = "no letters (a separator or placeholder)"
HIDE_STYLE = "style line (position and colour codes, no text)"
HIDE_SCRIPT = "director script of the recap movies (commands, not shown text)"
HIDE_JAFILE = "a Japanese file left on this disc (not known to be shown)"
JA_LEFT = "left in Japanese on this disc"
LOCK_FIXED = "holds a value pointing into its middle (meaning unknown): it cannot change"

TXD_NAMES = {"menutext.txd": "Menus", "synopsis.txd": "Synopsis", "devchk.txd": "Memory card messages",
             "discchg.txd": "Disc change"}

_CUE = re.compile(r"^(\s*\+?(?:\d+:\d+:\d+|\d+)[ \t]+)(.*\S.*)$")
_STYLE_ONLY = re.compile(r"^(?:\$[a-z]+[^;\n$ ]{0,30};\s*)+$")
_MES_HEAD = re.compile(r"^#MESSAGE\b.*$")
_EOL = re.compile(r"(\r\n|\n|\r)")
_LETTER = re.compile(r"[^\W\d_]", re.UNICODE)
_KTAG = re.compile(r"<k([^<>]*)>")
_KTAG_RAW = re.compile(rb"<k([^<>]*)>")

# scene-script categories by what the code does with the string
SB_CAT = {"event": "Dialogue — event lines (voiced)", "box": "Dialogue — field boxes",
          "npc": "Dialogue — townspeople", "choice": "Choices", "think": "Narration boxes",
          "system": "System messages", "battle": "Battle messages", "banner": "Battle banners",
          "table": "Scene text picked from a table", "keyword": "Keywords townspeople wait for",
          "debug": "Debug prints", "resource": "Script identifiers", "unused": "Unused strings"}
SB_SHOWN = ("event", "box", "npc", "choice", "think", "system", "battle", "banner", "table")

# Width guides and byte limits traced to the game's code (USA SLUS_213.89; the
# functions are at other addresses in the other builds, same code). See
# docs/TRANSLATION-EDITOR.md "Limits" for each citation.
#
# px: the message window is as wide as its widest line (FUN_00268938 measures
# every backslash-n line with the printer's own width function; FUN_0026a878:
# width = widest + 2 x 16, + 11 when flag 0x100 is set, which FUN_0026cc68 sets
# for talk.Msg / Think / Sys / Sel / EvtMsg). The engine never wraps. The screen
# is 512 px wide (FUN_0026a370 culls at 512 x 448; FUN_0026e0f0 centres on 256).
# So the widest line whose window is no wider than the screen is 512 - 43 = 469.
# A townsperson's balloon (extalk.Msg, FUN_0026c788: flag 1, no 0x100) is drawn
# at zoom 18/16 (FUN_00272680's second prefix) with 2 x 16 of padding: 480 px
# at that zoom = 426 px as this editor measures (zoom 16).
# lim: FUN_0026ae60 copies the page being drawn into the 16 KB scratchpad at
# 0x70000000 behind a 59-byte style prefix, with no bounds check.
SCREEN_W = 512
# A file whose buffer is traced: FUN_001b50d8(0x1F00000) reads synopsis.txd to
# 0x1F00000 and puts a table at +0xFFF00 (the loader, FUN_00188618, reads the
# index size rounded up to 2,048 into the buffer its caller passes, unchecked).
# The read is rounded up, so the file itself may be 0xFF800 bytes at most.
OBJ_LIMITS = {"synopsis.txd": (0xFF800, "it is read to 0x1F00000 in 2,048-byte sectors and a table follows at +0xFFF00 (FUN_001b50d8)")}
# A choice list (talk.Sel, FUN_0026d0e8 -> FUN_0026ea28) is widest option + 32,
# centred on 256: 480. Battle messages and banners (bat / robo natives, in
# OV02.OVL) and table strings are NOT traced: no guide.
GUIDES = {"event": 469, "box": 469, "think": 469, "system": 469, "choice": 480, "npc": 426}
SB_SCRATCH_LIM = 16000


@dataclass
class Obj:
    path: str                 # in-game path as the index spells it
    kind: str
    chain: int
    disc: int                 # index into State.isos of the image it is read from
    data: bytes
    alloc: int
    codec: str = ""           # whole-file kinds: the file's codec
    role: str = ""            # whole-file kinds: movie / event / pse-mes / pse-script
    lines: List[Tuple[str, str]] = field(default_factory=list)   # whole-file: (body, line end)


@dataclass
class Slot:
    obj: Obj
    key: str                  # container key, or L<n> / M<n> / S<n>
    raw: bytes                # the original bytes of this string (b"" for file rows)
    a: int = 0                # file rows: first line
    b: int = 0                # file rows: one past the last line
    prefix: str = ""          # cue rows: the time and the separator
    ja: bool = False          # a drawn string held in a Japanese codec (its translation goes into the build's)


@dataclass
class State:
    isos: List[str]
    region: object
    ctx: object
    objs: Dict[str, Obj]
    rows: Dict[str, List[dict]]
    by_id: Dict[str, dict]
    slots: Dict[str, Slot]
    japanese: set = field(default_factory=set)      # ids of drawn strings this disc holds in a Japanese codec
    links: Dict[str, List[Tuple[str, List[int]]]] = field(default_factory=dict)
    #        keyword row id -> [(line row id, positions of its <k...> tags that hold the keyword)]
    linked: Dict[str, List[str]] = field(default_factory=dict)     # line row id -> its keyword row ids
    notes: List[str] = field(default_factory=list)                  # for the catalog (scripts read by shape...)


_STATES: Dict[tuple, State] = {}
_LOCK = threading.Lock()


def _fwd(path: str) -> str:
    return path.replace("\\", "/").strip("/")


def row_id(fam: str, path: str, key: str) -> str:
    return f"{fam}:{_fwd(path)}#{key}"


def _split_lines(text: str) -> List[Tuple[str, str]]:
    parts = _EOL.split(text)
    out = [(parts[i], parts[i + 1]) for i in range(0, len(parts) - 1, 2)]
    if parts[-1] != "":
        out.append((parts[-1], ""))
    return out


def _join_lines(lines: List[Tuple[str, str]]) -> str:
    return "".join(b + e for b, e in lines)


# ---------------------------------------------------------------------------
# reading
# ---------------------------------------------------------------------------

def _stem(path: str) -> str:
    return path.replace("/", "\\").rsplit("\\", 1)[-1]


def _hide_text(src: str) -> Optional[str]:
    if not src:
        return HIDE_EMPTY
    if not _LETTER.search(tc._CMD_RE.sub("", tc._TAG_RE.sub("", src))):
        return HIDE_NOLETTERS
    return None


def _base(fam, obj, key, src, cat, grp, ordn, ctl, font, ctx="", lock=None, hide=None,
          use="", px=None, lim=None) -> dict:
    return {"id": row_id(fam, obj.path, key), "fam": fam, "cat": cat, "grp": grp, "ord": ordn, "src": src,
            "ctx": ctx, "font": font, "ctl": ctl, "measure": FACE if font == tc.FIELD else None,
            "face": FACE if font == tc.FIELD else None, "px": px, "lim": lim, "lock": lock, "hide": hide,
            "use": use}


def sb_uses(data: bytes) -> Tuple[Dict[int, str], set]:
    """({pool index: kind}, {pool indexes extalk.KeyWait receives}) of one
    script, from its code (``dialogue.string_kinds`` + ``sbvm.text_uses``)."""
    import dialogue
    import sbvm
    kinds = dialogue.string_kinds(data)
    uses = sbvm.text_uses(sbvm.parse(data))
    kw = {i for i, us in uses.items() if any(n == "extalk.KeyWait" and pos == 0 for n, pos in us)}
    return kinds, kw


def _block_rows(st_reg, obj: Obj, kind, out_rows: List[dict], slots: Dict[str, Slot],
                links: Optional[dict] = None, notes: Optional[List[str]] = None) -> None:
    reg = st_reg
    display = reg.codec
    fam = KIND_FAM[obj.kind]
    parts = obj.path.replace("/", "\\").split("\\")
    name = parts[-1]
    items = kind.items(obj.path, obj.data, reg)
    uses: Optional[Dict[int, str]] = None
    kw: set = set()
    if obj.kind == "sb":
        try:
            uses, kw = sb_uses(obj.data)
            if any(not it.key.isdigit() or int(it.key) not in uses for it in items):
                raise ValueError("the pool has strings the code analysis does not list")
        except Exception as exc:                                   # noqa: BLE001 - one odd script falls back to the shape rule
            uses, kw = None, set()
            if notes is not None:
                notes.append(f"{obj.path}: the script's code could not be read ({type(exc).__name__}: {exc}); "
                             f"its strings are sorted by their look, as before")
    rows_here: List[dict] = []
    slots_here: Dict[str, Slot] = {}
    for n, it in enumerate(items):
        role = it.role or ""
        if role == "note":
            ctl, font = it.codec, tc.NOTE
        else:
            ctl, font = display, tc.FIELD      # an undrawn-codec string that IS shown: translate into the build's codec
        src = tc.to_display(it.raw, it.codec)
        ctx, lock, hide = "", None, None
        use, px, lim = "", None, None
        if obj.kind == "sb" and uses is not None:
            use = uses[int(it.key)]
            cat, grp = SB_CAT[use], name.rsplit(".", 1)[0]
            if use in SB_SHOWN or use == "keyword":
                ctl, font = display, tc.FIELD                      # drawn: the build's codec, the font check
                spk = tc.speaker_of(src)
                ctx = spk
                if it.codec != display and not spk:
                    ctx = JA_LEFT
                hide = _hide_text(src)
                if use == "keyword":
                    lock = LOCK_KEYWORD
                else:
                    px = GUIDES.get(use)
                    lim = SB_SCRATCH_LIM if use in GUIDES else None
            else:                                                  # never drawn: it only has to encode, as it is stored
                ctl, font = it.codec, tc.NOTE
                hide = {"debug": HIDE_DEBUG, "resource": HIDE_ID, "unused": HIDE_UNUSED}[use]
        elif obj.kind == "sb":
            scene = name.rsplit(".", 1)[0]
            if role == "identifier":
                cat, hide = "Script identifiers", HIDE_ID
            elif role == "note":
                cat, hide = "Developers' notes", HIDE_NOTE
            else:
                where = "battle scenes" if parts[0].lower() == "bat" else "scenes"
                spk = tc.speaker_of(src)
                if not spk:      # choices, system lines, the scripts' own prints; on Japan also the notes
                    cat = f"Scene text without a speaker — {where}"
                else:
                    cat = f"Dialogue — {where}"
                ctx = spk
                if (role == "untranslated" or it.codec != display) and not spk:
                    ctx = JA_LEFT
                hide = _hide_text(src)
            grp = scene
        elif obj.kind == "txd":
            cat, grp = "Menu text", TXD_NAMES.get(name.lower(), name)
            hide = _hide_text(src)
        elif obj.kind == "nj":
            blob = it.key.split(".")[0]
            cat, grp = "Database & menu tables", f"{name.rsplit('.', 1)[0]} / {blob}"
            if any(f in ("mid-string", "fixed") for f in it.flags):
                lock = LOCK_FIXED
            if it.codec != display:
                ctx = JA_LEFT
            hide = _hide_text(src)
        elif obj.kind == "batdat":
            cat, grp = "Battle names & descriptions", "table " + it.key.split(".")[0]
            hide = _hide_text(src)
        else:                                  # msgdat
            cat, grp = "HaKox mini-game", name
            hide = _hide_text(src)
        r = _base(fam, obj, it.key, src, cat, grp, n, ctl, font, ctx, lock, hide, use, px, lim)
        rows_here.append(r)
        slots_here[r["id"]] = Slot(obj, it.key, it.raw, ja=(font == tc.FIELD and it.codec != display))
    if uses is not None and links is not None and kw:
        # keyword -> the <k...> tags that hold it, by exact bytes (the game's own match)
        by_key = {it.key: it for it in items}
        for k in sorted(kw):
            kit = by_key[f"{k:04d}"]
            if uses[k] != "keyword":
                continue                                           # also a shown line: left editable
            krid = row_id(fam, obj.path, kit.key)
            found: List[Tuple[str, List[int]]] = []
            for it in items:
                if it.key == kit.key or uses[int(it.key)] not in SB_SHOWN:
                    continue                                       # only a line the game draws carries a keyword
                pos = [i for i, b in enumerate(_KTAG_RAW.findall(it.raw)) if b == kit.raw]
                if pos:
                    found.append((row_id(fam, obj.path, it.key), pos))
            by = {r["id"]: r for r in rows_here}
            if found:
                links[krid] = found
                by[krid]["ctx"] = "keyword of line " + ", ".join(l.rsplit("#", 1)[1] for l, _p in found)
            else:                                                  # no tag holds it: nothing to follow, so not locked
                by[krid]["lock"] = None
                by[krid]["ctx"] = "keyword (no <k...> tag of this script holds it)"
    out_rows.extend(rows_here)
    slots.update(slots_here)


def _file_rows(reg, obj: Obj, out_rows: List[dict], slots: Dict[str, Slot]) -> None:
    import subtitle
    display = reg.codec
    fam = "sub"
    parts = obj.path.replace("/", "\\").split("\\")
    name = parts[-1]
    obj.role = subtitle.role(obj.path, reg) or ""
    obj.codec = subtitle.codec_name(obj.path, obj.data, reg)
    text = textcodec.codec_by_name(obj.codec).to_text(obj.data, file=True)
    obj.lines = _split_lines(text)
    stem = name.rsplit(".", 1)[0]
    if obj.role in ("movie", "event"):
        battle = len(parts) == 4 and parts[2].lower() == "bat"
        cat = "Event subtitles" if obj.role == "event" else \
            ("Battle voice subtitles" if battle else "Movie subtitles")
        in_comment = False
        n = 0
        for i, (body, _e) in enumerate(obj.lines):
            if in_comment:
                in_comment = "*/" not in body
                continue
            if body.lstrip().startswith("/*"):
                in_comment = "*/" not in body.lstrip()[2:]
                continue
            if body.startswith(";"):
                continue
            m = _CUE.match(body)
            if not m:
                continue
            src = m.group(2).replace("\\n", "\n")
            hide = HIDE_STYLE if _STYLE_ONLY.match(m.group(2)) else _hide_text(src)
            font = tc.FIELD if obj.codec == display else tc.NOTE
            r = _base(fam, obj, f"L{i}", src, cat, stem, n, obj.codec, font, m.group(1).strip(), None, hide)
            out_rows.append(r)
            slots[r["id"]] = Slot(obj, f"L{i}", b"", i, i + 1, m.group(1))
            n += 1
    elif obj.role == "pse-mes":
        cat = "Story recap messages"
        heads = [i for i, (b, _e) in enumerate(obj.lines) if _MES_HEAD.match(b)]
        for n, h in enumerate(heads):
            end = heads[n + 1] if n + 1 < len(heads) else len(obj.lines)
            a, b = h + 1, end
            while b > a and not obj.lines[b - 1][0].strip():
                b -= 1
            if b <= a:
                continue
            src = "\n".join(x for x, _e in obj.lines[a:b])
            shown = obj.codec == display
            r = _base(fam, obj, f"M{n}", src, cat, stem, n, obj.codec + tc.FILE_SUFFIX,
                      tc.FIELD if shown else tc.NOTE, obj.lines[h][0].strip(), None,
                      None if shown else HIDE_JAFILE)
            out_rows.append(r)
            slots[r["id"]] = Slot(obj, f"M{n}", b"", a, b)
    else:                                      # pse-script: commands and comments
        cat = "Recap director scripts"
        n = 0
        for i, (body, _e) in enumerate(obj.lines):
            if not body.strip():
                continue
            r = _base(fam, obj, f"S{i}", body, cat, stem, n, obj.codec + tc.FILE_SUFFIX, tc.NOTE, "",
                      None, HIDE_SCRIPT)
            out_rows.append(r)
            slots[r["id"]] = Slot(obj, f"S{i}", b"", i, i + 1)
            n += 1


def _set_key(isos: List[str]) -> tuple:
    out = []
    for p in isos:
        st = os.stat(p)
        out.append((p, st.st_size, st.st_mtime_ns))
    return tuple(out)


def load_set(isos: List[str], cache: bool = True) -> State:
    """Read every text object of one disc set (one image or Disc 1 + Disc 2)."""
    import textpack
    key = _set_key(isos)
    with _LOCK:
        if cache and key in _STATES:
            return _STATES[key]
        srcs = [textpack.DiscSource(p) for p in isos]
        try:
            reg = srcs[0].region
            owner: Dict[str, Tuple[int, int, str]] = {}
            for di, s in enumerate(srcs):
                for c, p in s.chained():
                    owner.setdefault(textpack._norm(p), (di, c, p))
            objs: Dict[str, Obj] = {}
            rows: Dict[str, List[dict]] = {f: [] for f in FAM_KINDS}
            slots: Dict[str, Slot] = {}
            links: Dict[str, List[Tuple[str, List[int]]]] = {}
            notes: List[str] = []
            for path, kind in textpack.collect([v[2] for v in owner.values()], reg):
                di, c, p = owner[textpack._norm(path)]
                data = srcs[di].read(p)
                obj = Obj(textpack._clean(p), kind, c, di, data, srcs[di].alloc(p))
                k = textpack.KINDS[kind]
                try:
                    if k.whole_file:
                        _file_rows(reg, obj, rows["sub"], slots)
                    else:
                        _block_rows(reg, obj, k, rows[KIND_FAM[kind]], slots, links, notes)
                except Exception as exc:                           # noqa: BLE001 - one odd file must not hide the rest
                    print(f"[txfam] skip {path}: {type(exc).__name__}: {exc}", file=sys.stderr)
                    continue
                objs[textpack._norm(p)] = obj
        finally:
            for s in srcs:
                s.close()
        by_id = {r["id"]: r for fam in rows.values() for r in fam}
        linked: Dict[str, List[str]] = {}
        for krid, found in links.items():
            for lrid, _pos in found:
                linked.setdefault(lrid, []).append(krid)
        if len(notes) > 12:
            notes = notes[:12] + [f"... and {len(notes) - 12} more scripts read by shape"]
        st = State(list(isos), reg, tc.context(isos[0]), objs, rows, by_id, slots,
                   {rid for rid, s in slots.items() if s.ja}, links, linked, notes)
        if cache:
            _STATES[key] = st
        return st


def load(iso: str) -> State:
    """The set ``iso`` belongs to. A pure lookup: every check below is handed
    this set's own ``State.ctx``; nothing ambient is changed (two sets can be
    open in one process, each request in its own ``txcodec.disc`` scope)."""
    return load_set(txdiscs.pair(iso))


def rows(iso: str, fam: str) -> List[dict]:
    return [dict(r) for r in load(iso).rows[fam]]


# ---------------------------------------------------------------------------
# encoding one row
# ---------------------------------------------------------------------------

def _keep(src: str) -> str:
    return "".join(ch for ch, r in textcodec.tokens(src) if r is None)


def encode(st: State, row: dict, text: str) -> bytes:
    """The bytes of one translated row (raises txcodec.TxEncodeError)."""
    slot = st.slots[row["id"]]
    if slot.obj.kind == "sb":
        text = tc.fix_line_count(row["src"], text)
    return tc.from_display(text, row["font"], row["ctl"], FACE, keep=_keep(row["src"]), ctx=st.ctx)[0]


def _file_text(st: State, obj: Obj, edits: Dict[str, str], check: bool = True) -> str:
    """The whole text of a file object with the edited rows put in (``check``
    off: no codec / font check, for the tree a new-script build encodes later)."""
    lines = list(obj.lines)
    repl = []
    for rid, text in edits.items():
        slot = st.slots[rid]
        row = st.by_id[rid]
        if check:
            tc.from_display(text, row["font"], row["ctl"], FACE, keep=_keep(row["src"]), ctx=st.ctx)
        typed = tc.escape_glyphs(text.replace("\r\n", "\n").replace("\r", "\n"))
        if slot.key.startswith("L"):
            new = [(slot.prefix + typed.replace("\n", "\\n"), lines[slot.a][1])]
        else:
            eol = lines[slot.a][1] or "\r\n"
            body = typed.split("\n")
            new = [(b, eol) for b in body[:-1]] + [(body[-1], lines[slot.b - 1][1])]
        repl.append((slot.a, slot.b, new))
    for a, b, new in sorted(repl, reverse=True):
        lines[a:b] = new
    return _join_lines(lines)


def _build_obj(st: State, obj: Obj, edits: Dict[str, str]) -> bytes:
    """New bytes of one object with ``edits`` ({row id: text}) applied (the
    kit's own builders; read back before it is returned). A file with a proven
    buffer size (``OBJ_LIMITS``) may not pass it."""
    out = _build_obj_bytes(st, obj, edits)
    lim = OBJ_LIMITS.get(_stem(obj.path).lower())
    if lim and len(out) > lim[0]:
        raise tc.TxBuildError(f"{obj.path}: {len(out):,} bytes, over the {lim[0]:,} the game has room for ({lim[1]})")
    return out


def _build_obj_bytes(st: State, obj: Obj, edits: Dict[str, str]) -> bytes:
    import subtitle
    import textpack
    reg = st.region
    kind = textpack.KINDS[obj.kind]
    if kind.whole_file:
        text = _file_text(st, obj, edits)
        orig = _join_lines(obj.lines)
        if text == orig:
            return obj.data
        if obj.role in ("movie", "event"):
            return subtitle.encode(obj.path, text, obj.codec, reg)
        return subtitle.from_text(text, obj.codec)
    parsed = kind.parse(obj.data, reg)
    items = kind.exported(parsed)
    new = {it.key: it.raw for it in items}
    changed = False
    for rid, text in edits.items():
        slot = st.slots[rid]
        raw = encode(st, st.by_id[rid], text)
        if raw != new[slot.key]:
            new[slot.key] = raw
            changed = True
    if not changed:
        return obj.data
    out = kind.build(parsed, new, False)
    back = {it.key: it.raw for it in kind.items(obj.path, out, reg)}
    if any(back.get(k) != v for k, v in new.items()):
        raise tc.TxBuildError(f"{obj.path}: the rebuilt object does not read back as written")
    return out


def _short(rid: str) -> str:
    return rid.split(":", 1)[1] if ":" in rid else rid


def _nfc(text: str) -> str:
    import unicodedata
    return unicodedata.normalize("NFC", text)


def effective(st: State, edits: Dict[str, str], partial: bool = False
              ) -> Tuple[Dict[str, str], Dict[str, List[str]], Dict[str, List[str]], set]:
    """The edits a build writes: ``edits`` plus every keyword row that follows
    a translated ``<k...>`` tag. -> (edits, errors, warnings, derived ids).

    A townsperson's ``extalk.KeyWait`` waits for a keyword whose bytes are the
    body of a ``<kWORD>`` tag in a line of the same script (the link is by the
    retail bytes, per tag occurrence: ``State.links``). The keyword row is
    locked; when a linked line is translated, the keyword becomes the body of
    the tag in the same position. Refused: a linked line whose number of
    ``<k...>`` tags changed, one keyword written differently in two of its
    lines, a keyword row edited by hand to something else.

    ``partial`` (the editor checking ONE row, without the project's other
    edits): a keyword that other, untranslated lines also hold is a warning
    naming those lines, not an error."""
    out = dict(edits)
    errs: Dict[str, List[str]] = {}
    warns: Dict[str, List[str]] = {}
    derived: set = set()
    touched = {k for rid in edits for k in st.linked.get(rid, ())} | {r for r in edits if r in st.links}
    for krid in sorted(touched):
        krow = st.by_id[krid]
        bodies: List[Tuple[str, str]] = []          # (line row id, body of the tag that holds this keyword)
        broken = False
        for lrid, positions in st.links[krid]:
            lrow = st.by_id[lrid]
            text = edits.get(lrid)
            if text is None:
                bodies += [(lrid, krow["src"])] * len(positions)
                continue
            n_src, tags = len(_KTAG.findall(lrow["src"])), _KTAG.findall(_nfc(text))
            if len(tags) != n_src:
                errs.setdefault(lrid, []).append(
                    f"{len(tags)} <k...> keyword tag(s) where the original has {n_src}: a townsperson "
                    f"waits for each keyword, so keep every tag and translate the word inside it")
                broken = True
                continue
            bodies += [(lrid, tags[p]) for p in positions]
        if broken:
            continue
        mine = [b for l, b in bodies if l in edits]
        want = mine[0] if mine else krow["src"]
        differ = sorted({l for l, b in bodies if b != want})
        if differ:
            others = ", ".join(_short(l) for l in differ[:4])
            msg = (f"the keyword <k{krow['src']}> is also in {others}; a townsperson waits for ONE word "
                   f"(here <k{want}>), so write the same word in every one of these lines")
            for l in {l for l, _b in bodies if l in edits}:
                if partial and all(d not in edits for d in differ):
                    warns.setdefault(l, []).append(msg + " (the build refuses until they agree)")
                else:
                    errs.setdefault(l, []).append(msg)
            if not partial or any(d in edits for d in differ):
                continue
        if krid in edits and _nfc(edits[krid]) != want:
            errs.setdefault(krid, []).append(
                f"locked: {LOCK_KEYWORD} ({', '.join(_short(l) for l, _p in st.links[krid][:4])}); "
                f"the tag there says <k{want}>")
            continue
        if want != krow["src"] or krid in edits:
            out[krid] = want
            if krid not in edits:
                derived.add(krid)
    return out, errs, warns, derived


def check_links(retail: State, built: State) -> List[str]:
    """Problems in a built set: a keyword whose bytes are no longer the body
    of each ``<k...>`` tag it follows (compared as written on the disc, so a
    new-script build's glyph codes are checked too)."""
    out = []
    for krid, found in retail.links.items():
        ks = built.slots.get(krid)
        if ks is None:
            out.append(f"{krid}: the keyword is gone from the copy")
            continue
        for lrid, positions in found:
            ls = built.slots.get(lrid)
            tags = _KTAG_RAW.findall(ls.raw) if ls is not None else []
            for p in positions:
                if p >= len(tags) or tags[p] != ks.raw:
                    out.append(f"{krid}: the keyword's bytes are not the <k...> word of {_short(lrid)} "
                               f"(a townsperson would wait for a word the line no longer has)")
                    break
    return out


def _group(st: State, edits: Dict[str, str], fam: Optional[str], derived=()) -> Tuple[Dict[str, Dict[str, str]], Dict[str, List[str]]]:
    per: Dict[str, Dict[str, str]] = {}
    errs: Dict[str, List[str]] = {}
    for rid, text in edits.items():
        row = st.by_id.get(rid)
        if row is None or (fam and row["fam"] != fam):
            errs[rid] = ["unknown id (not a string of this disc set)"]
            continue
        if row.get("lock") and not (row["lock"] == LOCK_KEYWORD and (rid in derived or rid in st.links)):
            errs[rid] = [f"locked: {row['lock']}"]
            continue
        import textpack
        per.setdefault(textpack._norm(st.slots[rid].obj.path), {})[rid] = text
    return per, errs


def text_errors(row: dict, text: str) -> List[str]:
    """Rules about one row's TEXT that hold whatever writes it (retail letters
    or new glyphs): the control bytes of the original are kept (the editor's
    own error, ``txcodec.control_errors``), and a choice keeps its number of
    options (``talk.Sel`` splits the string at each line break and the script
    acts on the option's number)."""
    out = list(tc.control_errors(text, row["src"], row["ctl"]))
    if row.get("use") == "choice":
        a, b = row["src"].count("\n") + 1, text.replace("\r\n", "\n").count("\n") + 1
        if a != b:
            out.append(f"{b} line(s) where the original has {a}: every line of a choice is one option the "
                       f"script acts on by its number, so keep one line per option (shorten a long option; "
                       f"do not break it)")
    return out


def _row_errors(st: State, row: dict, text: str) -> List[str]:
    try:
        raw = encode(st, row, text)
    except tc.TxEncodeError as e:
        return [f"position {p}: {c!r} ({tc.char_name(c)}): {m}" if c else m for p, c, m in e.problems]
    return text_errors(row, text) + limit_errors(row, raw)


def limit_errors(row: dict, raw: bytes) -> List[str]:
    """A proven byte limit of the row, checked on the bytes as written (both
    build paths call this; the editor's ``txcodec.check`` says the same)."""
    lim = row.get("lim")
    if lim is not None and len(raw) > lim:
        return [f"{len(raw)} bytes, over the {lim}-byte limit (the game copies the page into a 16 KB "
                f"work area without checking its length)"]
    return []


def edit_errors(st: State, edits: Dict[str, str], fam: Optional[str] = None, partial: bool = False
                ) -> Tuple[Dict[str, str], Dict[str, List[str]], Dict[str, List[str]], set]:
    """The rules about the edits themselves, the same for every build path
    (retail letters or new glyphs): known ids, locks, keyword links.
    -> (effective edits, errors, warnings, derived keyword ids)."""
    eff, errs, warns, derived = effective(st, edits, partial)
    for rid in eff:
        row = st.by_id.get(rid)
        if row is None or (fam and row["fam"] != fam):
            errs.setdefault(rid, []).append("unknown id (not a string of this disc set)")
        elif row.get("lock") and not (row["lock"] == LOCK_KEYWORD and (rid in derived or rid in st.links)):
            errs.setdefault(rid, []).append(f"locked: {row['lock']}")
        elif rid not in derived:
            e = text_errors(row, eff[rid])
            if e:
                errs.setdefault(rid, []).extend(e)
    return eff, errs, warns, derived


def planned_errors(st: State, changes: Dict[str, bytes], edits: Dict[str, str]) -> List[str]:
    """What must hold of the objects a build is ABOUT to write (``changes`` =
    {in-game path: new bytes}, from either build path), checked on the bytes:
    no file past its proven buffer, no drawn script string past its byte limit,
    every edited block row still there, every keyword still the ``<k...>`` word
    of its line. Empty = good; nothing has been written yet."""
    import textpack
    out: List[str] = []
    raws: Dict[str, bytes] = {}
    seen_obj = set()
    for path, data in changes.items():
        if not isinstance(path, str):
            continue
        key = textpack._norm(path)
        obj = st.objs.get(key)
        if obj is None:
            continue                                               # a font
        seen_obj.add(key)
        lim = OBJ_LIMITS.get(_stem(obj.path).lower())
        if lim and len(data) > lim[0]:
            out.append(f"{obj.path}: {len(data):,} bytes, over the {lim[0]:,} the game has room for ({lim[1]})")
        kind = textpack.KINDS[obj.kind]
        if kind.whole_file:
            continue
        try:
            for it in kind.items(obj.path, data, st.region):
                raws[row_id(KIND_FAM[obj.kind], obj.path, it.key)] = it.raw
        except Exception as exc:                                   # noqa: BLE001
            out.append(f"{obj.path}: the rebuilt object cannot be read ({type(exc).__name__}: {exc})")
    for rid in edits:
        slot = st.slots.get(rid)
        if slot is None or textpack._norm(slot.obj.path) not in seen_obj or textpack.KINDS[slot.obj.kind].whole_file:
            continue
        if rid not in raws:
            out.append(f"{rid}: the row is gone from the rebuilt object")
        else:
            out += [f"{rid}: {m}" for m in limit_errors(st.by_id[rid], raws[rid])]
    for krid, found in st.links.items():
        if krid not in raws and all(l not in raws for l, _p in found):
            continue
        kraw = raws.get(krid, st.slots[krid].raw)
        for lrid, positions in found:
            tags = _KTAG_RAW.findall(raws.get(lrid, st.slots[lrid].raw))
            if any(p >= len(tags) or tags[p] != kraw for p in positions):
                out.append(f"{krid}: the keyword's bytes would not be the <k...> word of {_short(lrid)}")
                break
    return out


def validate(edits: Dict[str, str], iso: Optional[str], fam: Optional[str] = None,
             partial: bool = False) -> Dict[str, List[str]]:
    """{row id: [errors]} for the edits that a build would refuse (rows that
    pass are absent). The edit rules first (ids, locks, keyword links), then
    the row rules (codec, font, proven byte limit), then each touched object
    is built in memory so the container's own rules answer too (subtitle
    grammar, 64 KB tables). An error of a keyword the build derives is
    reported on the line whose tag it follows."""
    if not iso:
        return {}
    st = load(iso)
    if not edits:
        return {}
    edits, kerrs, _kw, derived = effective(st, edits, partial)
    per, errs = _group(st, edits, fam, derived)
    for rid, e in kerrs.items():
        errs.setdefault(rid, [])[:0] = e
    errs = _validate_objects(st, per, errs)
    for krid in [r for r in errs if r in derived]:               # a derived keyword: say it on its line
        msgs = errs.pop(krid)
        for lrid, _p in st.links[krid]:
            if lrid in edits:
                errs.setdefault(lrid, []).extend(f"its keyword <k...>: {m}" for m in msgs)
    return errs


def check_row(rid: str, text: str, iso: str) -> Tuple[List[str], List[str]]:
    """(errors, warnings) of ONE row checked on its own, as the editor does
    while the translator types: ``validate`` with ``partial`` (a keyword other
    lines still hold in the original is a warning, since the editor cannot see
    the project's other rows from here)."""
    st = load(iso)
    errs = validate({rid: text}, iso, None, partial=True).get(rid, [])
    _e, _k, warns, _d = effective(st, {rid: text}, partial=True)
    return list(errs), list(warns.get(rid, []))


def _validate_objects(st: State, per: Dict[str, Dict[str, str]], errs: Dict[str, List[str]]) -> Dict[str, List[str]]:
    for opath, group in per.items():
        obj = st.objs[opath]
        good = {}
        for rid, text in group.items():
            e = _row_errors(st, st.by_id[rid], text)
            if e:
                errs.setdefault(rid, []).extend(e)
            elif rid not in errs:
                good[rid] = text
        if not good:
            continue
        try:
            _build_obj(st, obj, good)
        except (textcodec.TextError, tc.TxBuildError, tc.TxEncodeError, ValueError) as exc:
            # which row broke the object? try each alone; a rule that only the
            # whole set breaks is reported on every edited row of the object
            alone = {}
            for rid, text in good.items():
                try:
                    _build_obj(st, obj, {rid: text})
                except (textcodec.TextError, tc.TxBuildError, tc.TxEncodeError, ValueError) as e1:
                    alone[rid] = str(e1)
            for rid in (alone or good):
                errs.setdefault(rid, []).append(alone.get(rid, str(exc)))
    return errs


def warnings(edits: Dict[str, str], iso: Optional[str], fam: Optional[str] = None) -> Dict[str, List[str]]:
    """{row id: [warnings]}: the kit's own import warnings for script strings."""
    import sb
    if not iso or not edits:
        return {}
    st = load(iso)
    out: Dict[str, List[str]] = {}
    for rid, text in edits.items():
        row = st.by_id.get(rid)
        if row is None or (fam and row["fam"] != fam) or st.slots[rid].obj.kind != "sb":
            continue
        try:
            raw = encode(st, row, text)
        except tc.TxEncodeError:
            continue
        ws = list(sb.import_warnings(st.slots[rid].raw, raw, st.region))
        if row.get("hide") == HIDE_ID and raw != st.slots[rid].raw:
            ws.append("an identifier (label / voice id) was changed; the script refers to it by name")
        if ws:
            out[rid] = ws
    return out


def plan(edits: Dict[str, str], iso: str, fam: Optional[str] = None) -> Tuple[Dict[str, bytes], List[dict]]:
    """({in-game path: new bytes}, report rows) for every object ``edits``
    changes. Raises txcodec.TxBuildError when any row is refused."""
    st = load(iso)
    bad = validate(edits, iso, fam)
    if bad:
        lines = [f"{rid}: {'; '.join(e)}" for rid, e in list(bad.items())[:20]]
        raise tc.TxBuildError(f"{len(bad)} row(s) refused:\n  " + "\n  ".join(lines))
    edits, _ke, _kw, derived = effective(st, edits)
    per, _errs = _group(st, edits, fam, derived)
    changes: Dict[str, bytes] = {}
    report: List[dict] = []
    for opath, group in per.items():
        obj = st.objs[opath]
        new = _build_obj(st, obj, group)
        if new == obj.data:
            continue
        changes[obj.path] = new
        report.append({"path": obj.path, "kind": obj.kind, "chain": obj.chain, "disc": obj.disc,
                       "old_size": len(obj.data), "new_size": len(new), "allocation": obj.alloc,
                       "rows": len(group),
                       "action": "in-place" if len(new) <= obj.alloc else "grow (append at image end)"})
    return changes, report


def read_back(out_isos: List[str], ids: List[str]) -> Dict[str, Optional[str]]:
    """{row id: the display text the written images now hold} (None = the row
    is gone). The images are read afresh, never from the cache."""
    st = load_set([str(Path(p).resolve()) for p in out_isos], cache=False)
    return {rid: (st.by_id[rid]["src"] if rid in st.by_id else None) for rid in ids}


def object_bytes(isos: List[str]) -> Dict[str, bytes]:
    """{normalised path: bytes} of every text object of a set (for comparisons)."""
    st = load_set([str(Path(p).resolve()) for p in isos], cache=False)
    return {k: o.data for k, o in st.objs.items()}


# ---------------------------------------------------------------------------

def selftest_roles() -> int:
    """No disc: a script assembled here, sorted by what its code does with each
    string, and the keyword rule on it."""
    import region as regionmod
    import sbvm
    import textpack
    ok = True

    def check(cond, what):
        nonlocal ok
        print(("ok   " if cond else "FAIL ") + what)
        ok = ok and bool(cond)

    A = sbvm.assemble
    strs = [b"s000200_01vir", b"[Blue Testament]Looks like things are going\\nsmoothly.<f>",       # 0 1
            b"Yes\\nNo", b"[Shion]<l1>Fine.<w15>", b"[Shion]This looks like a line.<f>", b"s000300",  # 2 3 4 5
            b"[Monkey]<l1>You are <knot ready> yet, <kGnosis>.", b"not ready", b"table line",       # 6 7 8
            b"[Monkey]<l1>Still <knot ready>?", b"Gnosis", b"never used", b"lonely"]                # 9 10 11 12
    main = A([(0x26, 4), 0x18, (0x4A, 0),                                   # deb.put(a string shaped like dialogue)
              0x1A, (0x14, 9), (0x26, 0), (0x26, 1), 0x18, (0x14, 15), 0x1D, (0x4A, 1),   # talk.EvtMsg
              (0x26, 2), 0x18, (0x4A, 2), 0x4B,                             # talk.Sel
              (0x42, 3 + 6),
              (0x26, 3), 0x18, 0x19, (0x4A, 3),                             # talk.Msg
              (0x26, 5), 0x18, (0x4A, 4),                                   # runtime.mpeg2
              0x47])
    sub = A([0x18, (0x26, 6), 0x19, (0x4A, 5), (0x26, 7), 0x18, (0x4A, 6),   # extalk.Msg(line 6); KeyWait("not ready")
             0x18, (0x26, 9), 0x19, (0x4A, 5), (0x26, 10), 0x18, (0x4A, 6),  # extalk.Msg(line 9); KeyWait("Gnosis")
             (0x26, 12), 0x18, (0x4A, 6),                                    # KeyWait("lonely"): no tag holds it
             0x17, 0x18, (0x21, 0), 0x50, 0x1A, (0x4A, 7), 0x47])            # bat.msgOpen(text through g0)
    imports = [("deb", "put"), ("talk", "EvtMsg"), ("talk", "Sel"), ("talk", "Msg"), ("runtime", "mpeg2"),
               ("extalk", "Msg"), ("extalk", "KeyWait"), ("bat", "msgOpen")]
    data = sbvm.build_script(main + sub, imports, [("npc", len(main)), ("main", 0)], strs, [8])
    reg = regionmod.by_name("us")
    obj = Obj("cf\\us\\0001.sb", "sb", 0, 0, data, len(data))
    rows: List[dict] = []
    slots: Dict[str, Slot] = {}
    links: Dict[str, List[Tuple[str, List[int]]]] = {}
    notes: List[str] = []
    _block_rows(reg, obj, textpack.KINDS["sb"], rows, slots, links, notes)
    rid = lambda n: f"sb:cf/us/0001.sb#{n:04d}"                    # noqa: E731
    by = {r["id"]: r for r in rows}
    uses = [by[rid(n)]["use"] for n in range(13)]
    check(uses == ["resource", "event", "choice", "box", "debug", "resource", "npc", "keyword", "table", "npc",
                   "keyword", "unused", "keyword"] and not notes, f"every string sorted by what the code does with it")
    check(by[rid(4)]["hide"] == HIDE_DEBUG and by[rid(4)]["font"] == tc.NOTE and not by[rid(1)]["hide"]
          and by[rid(1)]["font"] == tc.FIELD and by[rid(1)]["ctx"] == "Blue Testament",
          "a debug print shaped like a line is hidden and never font-checked; a drawn line is offered")
    check(by[rid(0)]["hide"] == HIDE_ID and by[rid(11)]["hide"] == HIDE_UNUSED, "ids and unused strings are hidden")
    check((by[rid(1)]["px"], by[rid(3)]["px"], by[rid(2)]["px"], by[rid(6)]["px"], by[rid(8)]["px"]) == (469, 469, 480, 426, None)
          and by[rid(1)]["lim"] == SB_SCRATCH_LIM and by[rid(8)]["lim"] is None,
          "width guides and the byte limit only where the window code is traced")
    check(links == {rid(7): [(rid(6), [0]), (rid(9), [0])], rid(10): [(rid(6), [1])]}
          and by[rid(7)]["lock"] == LOCK_KEYWORD and by[rid(12)]["lock"] is None,
          "keyword -> the <k...> tags that hold its bytes, per occurrence; a keyword no tag holds is not locked")
    linked: Dict[str, List[str]] = {}
    for k, found in links.items():
        for l, _p in found:
            linked.setdefault(l, []).append(k)
    st = State([], reg, None, {}, {"sb": rows}, by, slots, set(), links, linked, notes)
    L6, L9 = by[rid(6)]["src"], by[rid(9)]["src"]
    eff, errs, _w, der = effective(st, {rid(6): L6.replace("Gnosis", "Gnose")})
    check(not errs and der == {rid(10)} and eff[rid(10)] == "Gnose", "a translated tag carries its keyword along")
    eff, errs, _w, der = effective(st, {rid(6): L6.replace("not ready", "pas prêt"), rid(9): L9.replace("not ready", "pas prêt")})
    check(not errs and eff[rid(7)] == "pas prêt" and der == {rid(7)}, "a keyword of two lines follows both")
    eff, errs, warns, der = effective(st, {rid(6): L6.replace("not ready", "pas prêt")})
    check(rid(6) in errs and "0009" in errs[rid(6)][0], "translated in one of its two lines only: refused, the other line named")
    eff, errs, warns, der = effective(st, {rid(6): L6.replace("not ready", "pas prêt")}, partial=True)
    check(not errs and rid(6) in warns, "the same while typing one row (the editor cannot see the other): a warning")
    eff, errs, _w, der = effective(st, {rid(6): L6.replace("not ready", "pas prêt"), rid(9): L9.replace("not ready", "pas pret")})
    check(rid(6) in errs and rid(9) in errs, "one keyword written two ways: both lines refused")
    eff, errs, _w, der = effective(st, {rid(6): L6.replace("<kGnosis>", "Gnosis")})
    check(rid(6) in errs and "keyword tag" in errs[rid(6)][0], "a removed <k...> tag is refused")
    _e, errs, _w, _d = edit_errors(st, {rid(7): "x"})
    check(rid(7) in errs and "locked" in errs[rid(7)][0], "a keyword row edited by hand is refused (it is locked)")
    _e, errs, _w, _d = edit_errors(st, {rid(10): "Gnose", rid(6): L6.replace("Gnosis", "Gnose")})
    check(not errs, "a hand edit that says what the tag says is accepted (an imported spreadsheet)")
    _e, errs, _w, _d = edit_errors(st, {rid(12): "seul", "sb:nope#0": "x"})
    check(list(errs) == ["sb:nope#0"], "an unlinked keyword is an ordinary row; an unknown id is refused")
    _e, errs, _w, _d = edit_errors(st, {rid(2): "Oui\nNon\nPeut-être"})
    check(rid(2) in errs and "option" in errs[rid(2)][0] and not edit_errors(st, {rid(2): "Oui\nNon"})[1],
          "a choice keeps one line per option (a third line is refused)")
    eff, errs, _w, der = effective(st, {rid(6): L6.replace("Gnosis", "Gnose\u0301")})
    check(not errs and eff[rid(10)] == "Gnos\u00e9", "a keyword is compared as it is written (composed), not as it was typed")
    check(tc.control_errors("a", "a⟦0D⟧⟦0A⟧b") and not tc.control_errors("x⟦0D⟧⟦0A⟧y", "a⟦0D⟧⟦0A⟧b")
          and text_errors({"src": "a⟦0D⟧⟦0A⟧b", "ctl": "us", "use": ""}, "ab"),
          "a dropped control byte is an error of the build too, not of the editor alone")
    exp, _meta = textpack.KINDS["sb"].export(obj.path, data, reg)
    check("### 0004 dialogue use:debug" in exp and "### 0007 dialogue use:keyword" in exp
          and textpack.keyed_bodies(exp, [f"{n:04d}" for n in range(13)])[7] == "not ready",
          "text-export says each string's use on its ### line; import still reads the key alone")
    bad = Obj("cf\\us\\0002.sb", "sb", 0, 0, data[:0x40] + b"\xff" * 8 + data[0x48:], len(data))
    rows2: List[dict] = []
    notes2: List[str] = []
    try:
        _block_rows(reg, bad, textpack.KINDS["sb"], rows2, {}, {}, notes2)
        check(len(notes2) == 1 and all(r["use"] == "" for r in rows2) and len(rows2) == 13,
              "a script whose code cannot be read falls back to the shape rule, with a note")
    except Exception as exc:                                       # noqa: BLE001
        check(False, f"a script whose code cannot be read falls back to the shape rule ({type(exc).__name__}: {exc})")
    print("selftest", "passed" if ok else "FAILED")
    return 0 if ok else 1


def selftest(iso: str, fam: Optional[str] = None) -> int:
    import time
    ok = True

    def check(cond, what):
        nonlocal ok
        print(("ok   " if cond else "FAIL ") + what)
        ok = ok and bool(cond)

    t = time.time()
    st = load(iso)
    fams = [fam] if fam else list(FAM_KINDS)
    n = sum(len(st.rows[f]) for f in fams)
    print(f"     {len(st.isos)} image(s), build {st.region.name}: {len(st.objs)} objects, "
          f"{n} rows in {time.time() - t:.1f} s")
    check(n > 0, "rows read")
    for f in fams:
        rs = st.rows[f]
        vis = [r for r in rs if not r["hide"] and not r["lock"]]
        check(len({r["id"] for r in rs}) == len(rs), f"{f}: {len(rs)} rows ({len(vis)} offered), ids unique")
        # every offered row's original encodes back to its own bytes (block kinds:
        # the string; file kinds: the file)
        bad = 0
        for r in rs:
            slot = st.slots[r["id"]]
            if slot.raw and r["font"] == tc.FIELD and r["ctl"] == st.region.codec:
                try:
                    if tc.from_display(r["src"], r["font"], r["ctl"], FACE, keep=_keep(r["src"]), ctx=st.ctx)[0] != slot.raw:
                        bad += 1
                except tc.TxEncodeError:
                    bad += 1
        untr = sum(1 for r in rs if r["id"] in st.japanese)
        check(bad <= untr, f"{f}: originals encode back to their bytes ({bad} differ; {untr} are Japanese "
                           f"strings whose translation is written in the build's codec)")
        if not vis:
            continue
        # unchanged edits change nothing; a real edit changes exactly its object
        same = {r["id"]: r["src"] for r in vis[:200] if r["id"] not in st.japanese}
        ch, _rep = plan(same, iso, f)
        check(not ch, f"{f}: {len(same)} rows 'translated' to their own text change no object")
        pick = next(r for r in vis if _LETTER.search(r["src"]) and r["id"] not in st.japanese)
        new_text = pick["src"] + " X"
        ch, rep = plan({pick["id"]: new_text}, iso, f)
        check(len(ch) == 1 and rep[0]["rows"] == 1, f"{f}: one edit changes one object ({rep[0]['path'] if rep else ''})")
        v = validate({pick["id"]: "Ж"}, iso, f) if st.region.codec == "us" else \
            validate({pick["id"]: "é"}, iso, f)
        check(pick["id"] in v, f"{f}: a letter the build cannot draw is refused ({(v.get(pick['id']) or [''])[0][:60]})")
    locked = next((r for r in st.by_id.values() if r["lock"]), None)
    if locked and (not fam or locked["fam"] == fam):
        check(locked["id"] in validate({locked["id"]: "x"}, iso), "a locked row is refused")
    if not fam or fam == "sb":
        import collections
        sbrows = st.rows["sb"]
        use = collections.Counter(r["use"] for r in sbrows)
        offered = [r for r in sbrows if not r["hide"] and not r["lock"]]
        check(not st.notes and "" not in use, f"every script's code was read: {dict(sorted(use.items()))}")
        check(all(r["use"] in SB_SHOWN for r in offered) and all(r["font"] == tc.NOTE for r in sbrows
              if r["use"] in ("debug", "resource", "unused")),
              f"only strings a show native draws are offered ({len(offered)}); debug prints "
              f"({use['debug']}), ids and unused strings are hidden and never font-checked")
        kws = [r for r in sbrows if r["use"] == "keyword"]
        check(kws and all(r["id"] in st.links and r["lock"] == LOCK_KEYWORD for r in kws)
              and not check_links(st, st),
              f"{len(kws)} keywords, each locked to the <k...> tag(s) holding its bytes "
              f"({sum(len(v) for v in st.links.values())} links); the retail set satisfies its own links")
        k2 = next((k for k, v in sorted(st.links.items()) if len(v) == 1 and len(v[0][1]) == 1), None)
        if k2:
            line = st.links[k2][0][0]
            new = st.by_id[line]["src"].replace(f"<k{st.by_id[k2]['src']}>", "<kX Y>")
            ch, rep_ = plan({line: new}, iso, "sb")
            check(len(ch) == 1 and not validate({line: new}, iso) and k2 in validate({k2: "nope"}, iso)
                  and line in validate({line: st.by_id[line]["src"].replace(f"<k{st.by_id[k2]['src']}>", "X")}, iso),
                  "a translated <k...> tag builds (its keyword follows); the keyword alone, or a removed tag, is refused")
        over = next((r for r in offered if r["lim"]), None)
        if over:
            v = validate({over["id"]: over["src"] + "x" * (over["lim"] + 1)}, iso)
            check(over["id"] in v and "limit" in v[over["id"]][0], f"a page past the {over['lim']}-byte work area is refused")
    print("selftest", "passed" if ok else "FAILED")
    return 0 if ok else 1


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("selftest")
    s.add_argument("--iso", required=True)
    s.add_argument("--fam", choices=sorted(FAM_KINDS))
    sub.add_parser("selftest-roles")
    a = ap.parse_args(argv)
    if a.cmd == "selftest-roles":
        return selftest_roles()
    return selftest(a.iso, a.fam)


if __name__ == "__main__":
    sys.exit(main())
