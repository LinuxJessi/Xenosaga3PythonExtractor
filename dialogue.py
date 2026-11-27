#!/usr/bin/env python3
"""dialogue.py — Xenosaga III's dialogue in the order the scripts play it.

``text-export`` writes each scene's text pool as it is stored: every string, in
pool order, the developers' debug prints among them. This module reads the
script's CODE (``sbvm.py``) and keeps the strings that reach a native which
draws text, in the order the code calls it. On USA Disc 1, 550,358 native calls
in 715 scripts, all of whose argument lists are recovered; a string is a line
when it is the text argument of one of:

  =====================  =====================================================
  ``talk.EvtMsg``        an event line: (who, ?, voice id, text, ?, ?). The
                         handler (SLUS FUN_0026c1a8) reads arguments 3 and 4 as
                         text pool strings; the first is the voice clip's name
                         (``s000200_01vir``), the second the line. 4,766 calls.
  ``talk.Msg``           a field text box (text, ...); 2,403 calls
  ``extalk.Msg``         a line of a townsperson (who, text, ...); 2,214 calls
  ``talk.Sel``           a choice; the options are one string split by ``\\n``
  ``talk.Think``         a box without a speaker tag (28 calls, all in cf\\us\\1140)
  ``talk.Sys``           a system message ("You obtained a segment file.")
  ``bat.msgOpen``        a battle message (x, y, text)
  ``robo.msgOpen``       an E.S. battle message (x, y, text, ...)
  ``robo.dispSkillName`` an E.S. battle banner (unit, text)
  ``extalk.KeyWait``     NOT a line: the keyword a townsperson waits for. Its text
                         is the body of a ``<k...>`` tag of a line in the same
                         script in 576 of 576 calls (USA; 1,127 of 1,127 Japan),
                         so a translation must change both alike. Listed as
                         ``keyword``.
  =====================  =====================================================

Calls that name a resource are kept as markers, and the resource is looked up on
the disc (``RESOURCES``; every id below has its media file on USA Disc 1+2):

  ``talk.EvtMsg``      voice id -> ``snd\\adx\\mev\\<id>.adx``, ONE stream per line
                       (4,738 of 4,738 ids on the USA discs, 5,095 of 5,096 on Japan)
  ``runtime.mpeg2``    a movie -> ``mov\\<id>.sfd``, subtitles ``mov\\xx\\<id>.txt``
  ``runtime.event``    an event scene -> ``evt\\<id>.xep``, its audio
                       ``snd\\adx\\evt\\<id>.adx``, subtitles ``evt\\xx\\<id>.txt``
  ``bat.caption``      a voiced battle caption -> ``snd\\adx\\bat_voice\\<id>.adx``,
                       its text ``mov\\xx\\bat\\<id>.txt``
  ``bat.adxPlay``      a battle voice clip -> ``snd\\adx\\<id>.adx``
  ``sound.adxLoad``    a stream -> ``snd\\adx\\mev\\<id>.adx``

A movie's, event scene's or caption's subtitle file is listed under its marker,
cue by cue with the file's own time stamps, so a transcript reads through.

What a string is NOT, by the same evidence: ``deb.put`` (the developers' debug
print) takes 227,240 of the 245,984 text arguments on USA Disc 1. 3,797 pool
strings that ``sb.classify`` calls ``dialogue`` by their shape reach only
``deb.put`` and are never drawn.

Lines come out per routine (the script's named entries: ``main`` first, the
others in code order) and branches are kept, not flattened: ``if`` /
``else`` / ``loop`` / ``case N`` blocks as the compiler laid them out, the way
Xenosaga2PythonExtractor/dialogue.py does it. The conditions are flags and are
not named.

A few battle and field scripts hand a show native a string read from a
variable (a table of string numbers in the globals, or a message from another
thread). The call is listed as ``(text from a variable)`` and the script's
table strings (``sbvm.Program.table_strings``) are listed at its end: which
entry a given call picks is decided at run time.

Voice: ``--voice`` writes the stream of every voiced row (``talk.EvtMsg``,
``bat.caption``, ``bat.adxPlay``) as a WAV, decoded by ffmpeg. The clip is the
line's own file, so nothing is cut or aligned.

Not here: the timing of a line (``talk.EvtMsg``'s numeric arguments were not
identified) and the order in which the game runs the scripts.

Usage::

    python dialogue.py --iso DISC1.iso [--iso DISC2.iso] --out DIR [--only 8000] [--voice]
    python dialogue.py --self-test

Output (``DIR``)::

    scripts/cf/<scene>.txt, scripts/bat/<name>.txt   play-script transcript per script
    voice/<scene>/NNNN_<who>_<id>.wav                 one clip per voiced row (--voice)
    dialogue.csv     every row: source, scene, order, entry, branch, kind, speaker,
                     text, text_id, native, voice, voice_path, time, clip, pc, raw, path
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sb       # noqa: E402
import sbvm     # noqa: E402
import textcodec  # noqa: E402

# native -> (position of the text argument, kind)
DIALOGUE_NATIVES: Dict[str, Tuple[int, str]] = {
    "talk.EvtMsg": (3, "event"),
    "talk.Msg": (0, "box"),
    "extalk.Msg": (1, "npc"),
    "talk.Sel": (0, "choice"),
    "talk.Think": (0, "think"),
    "talk.Sys": (0, "system"),
    "bat.msgOpen": (2, "battle"),
    "robo.msgOpen": (2, "battle"),
    "robo.dispSkillName": (1, "banner"),
    "extalk.KeyWait": (0, "keyword"),
}
# natives whose text argument names a resource: (position, what it is)
MARKER_NATIVES: Dict[str, Tuple[int, str]] = {
    "runtime.mpeg2": (0, "movie"),
    "runtime.event": (0, "event scene"),
    "bat.adxPlay": (0, "battle voice"),
    "bat.caption": (0, "battle caption"),
    "sound.adxLoad": (0, "stream"),
}
# Where a native's id lives on the disc: (audio or video, subtitle file); {id} is the
# string, {lang} the build's language folder. Checked against the indexes of USA Disc
# 1+2 (2026-11-21): all 4,738 talk.EvtMsg voice ids, 192 sound.adxLoad, 60 bat.caption,
# 2 bat.adxPlay, 67 runtime.event and 36 runtime.mpeg2 ids have their media file; 53 of
# the 67 events and 29 of the 36 movies have a subtitle file.
RESOURCES: Dict[str, Tuple[str, Optional[str]]] = {
    "talk.EvtMsg": ("snd\\adx\\mev\\{id}.adx", None),
    "sound.adxLoad": ("snd\\adx\\mev\\{id}.adx", None),
    "bat.adxPlay": ("snd\\adx\\{id}.adx", None),
    "bat.caption": ("snd\\adx\\bat_voice\\{id}.adx", "mov\\{lang}\\bat\\{id}.txt"),
    "runtime.mpeg2": ("mov\\{id}.sfd", "mov\\{lang}\\{id}.txt"),
    "runtime.event": ("snd\\adx\\evt\\{id}.adx", "evt\\{lang}\\{id}.txt"),
}
SUBTITLE_KIND = {"runtime.mpeg2": "movie line", "runtime.event": "event scene line",
                 "bat.caption": "caption line"}
VOICED = ("talk.EvtMsg", "bat.caption", "bat.adxPlay")      # --voice writes these as WAV
EVTMSG_VOICE = 2                 # talk.EvtMsg: the voice id is the argument before the line
SHOWN_KINDS = frozenset(k for _p, k in DIALOGUE_NATIVES.values()) - {"keyword"}
_SUBRUBY_RE = re.compile(r"\[([^\[\]/]+)/[^\[\]]*\]")       # subtitle files: [base/reading]

_KEY_RE = re.compile(r"<k([^<>]*)>")
_TAG_RE = re.compile(r"<[A-Za-z][^<>]*>")
_RUBY_RE = re.compile(r"\$rubyb;(.*?)\$rubys;.*?\$rubye;", re.S)
_CODE_RE = re.compile(r"\$[a-z]+[-0-9A-Fa-f,]*;")
_SPEAKER_RE = re.compile(r"^\[([^\[\]]{1,40})\](.*)$", re.S)


def clean(text: str) -> str:
    """Markup out: a ``<k...>`` keyword keeps its words, ruby keeps its base text,
    other ``<...>`` tags and ``$...;`` codes go, the game's ``\\n`` becomes a space."""
    t = _RUBY_RE.sub(r"\1", text)
    t = _KEY_RE.sub(r"\1", t)
    t = _TAG_RE.sub("", t)
    t = _CODE_RE.sub("", t)
    t = t.replace("\\n", " ")
    return re.sub(r"[ \t　]+", " ", t).strip()


def split_speaker(text: str) -> Tuple[str, str]:
    m = _SPEAKER_RE.match(text)
    return (m.group(1).strip(), m.group(2)) if m else ("", text)


@dataclass
class Line:
    source: str                  # script | battle
    scene: str                   # cf/2940, bat/CIT_B01
    order: int = 0
    entry: str = ""
    branch: str = ""
    kind: str = ""               # event box npc choice think system battle banner keyword | a marker
    speaker: str = ""
    text: str = ""
    text_id: Optional[int] = None
    native: str = ""
    voice: str = ""              # the id a native was given (a voice clip, a movie, an event)
    voice_path: str = ""         # that id's file on the disc, when it is there
    time: str = ""               # subtitle rows: the cue's time as the file writes it
    clip: str = ""               # --voice: the WAV written for this row
    pc: int = -1
    raw: str = ""
    path: str = ""
    depth: int = 0
    headers: List[str] = field(default_factory=list)

    def row(self) -> dict:
        return {"source": self.source, "scene": self.scene, "order": self.order, "entry": self.entry,
                "branch": self.branch, "kind": self.kind, "speaker": self.speaker, "text": self.text,
                "text_id": "" if self.text_id is None else self.text_id, "native": self.native,
                "voice": self.voice, "voice_path": self.voice_path, "time": self.time, "clip": self.clip,
                "pc": f"{self.pc:04x}" if self.pc >= 0 else "", "raw": self.raw, "path": self.path}


CSV_FIELDS = ["source", "scene", "order", "entry", "branch", "kind", "speaker", "text", "text_id",
              "native", "voice", "voice_path", "time", "clip", "pc", "raw", "path"]


# ------------------------------------------------- routines and branch regions

def _structure(prog: sbvm.Program, insns: Sequence[sbvm.Insn]):
    """Routines (name, start pc, reachable pcs) and branch regions.

    A routine is a named entry (``call``, ``pushcode`` and ``start`` only ever
    name entries); its instructions are those reachable from its start without
    entering another entry. Regions follow the compiler's layout: a forward
    ``jz``/``jnz`` opens an ``if`` up to its target, a ``jmp`` over the target at
    the end of it an ``else``; a backward jump is a ``loop``; a ``switch`` opens
    one region per case."""
    by_pc = {i.pc: i for i in insns}
    nxt = {a.pc: b.pc for a, b in zip(insns, insns[1:])}
    prev = {b.pc: a.pc for a, b in zip(insns, insns[1:])}
    starts: Dict[int, str] = {}
    for name, pc in prog.entries:
        starts.setdefault(pc, name)
    owner: Dict[int, str] = {}
    routines = []
    for pc0 in sorted(starts):
        seen, todo = set(), [pc0]
        while todo:
            pc = todo.pop()
            if pc in seen or pc not in by_pc or (pc != pc0 and pc in starts):
                continue
            seen.add(pc)
            i = by_pc[pc]
            if i.op in (0x47, 0x48, 0x59):                 # ret, retv, end
                continue
            if i.op == 0x41:
                todo.append(i.operand)
                continue
            if i.op in (0x42, 0x43):
                todo.append(i.operand)
            if i.op == sbvm.SWITCH:
                todo += [i.default] + [t for _, t in i.table]
                continue
            if pc in nxt:
                todo.append(nxt[pc])
        for pc in seen:
            owner.setdefault(pc, starts[pc0])
        routines.append((starts[pc0], pc0, seen))

    regions: List[Tuple[int, int, str]] = []
    for i in insns:
        if i.op in sbvm.JUMPS:
            t = i.operand
            if t <= i.pc:
                regions.append((t, nxt.get(i.pc, i.pc + i.size), "loop"))
            elif i.op in (0x42, 0x43) and i.pc in nxt:
                body0 = nxt[i.pc]
                last = by_pc.get(prev.get(t, -1))
                if last is not None and last.op == 0x41 and last.operand > t and last.pc >= body0:
                    regions.append((body0, t, "if"))
                    regions.append((t, last.operand, "else"))
                else:
                    regions.append((body0, t, "if"))
        elif i.op == sbvm.SWITCH:
            cases = sorted({(t, f"case {v}") for v, t in i.table} | {(i.default, "default")})
            join = 0
            for t, _ in cases:
                p = by_pc.get(prev.get(t, -1))
                if p is not None and p.op == 0x41 and p.operand > join:
                    join = p.operand
            for k, (t, label) in enumerate(cases):
                end = cases[k + 1][0] if k + 1 < len(cases) else max(join, t + 1)
                if end > t:
                    regions.append((t, end, label))
    return routines, owner, regions


def _path(regions, pc: int) -> List[Tuple[int, int, str]]:
    return sorted((r for r in regions if r[0] <= pc < r[1]), key=lambda r: (r[0], -r[1]))


# ------------------------------------------------------------ script lines

def script_lines(data: bytes, scene: str, region=None, battle: bool = False, path: str = "",
                 find=None, read=None) -> List[Line]:
    """Every shown line, keyword and resource marker of one script, per routine in code
    order with its branch path; then the script's table strings (if a show native is
    fed from a variable).

    ``find(path) -> the disc's spelling or None`` and ``read(path) -> bytes`` give
    access to the disc: with them a row's ``voice_path`` is filled in and the subtitle
    file of a movie, event scene or battle caption is listed under its marker."""
    import region as _region
    lang = _region.as_region(region).lang or "us"
    prog = sbvm.parse(data)
    insns = sbvm.disassemble(prog.code)
    items = sb.parse(data, region).items
    routines, owner, regions = _structure(prog, insns)
    order_of = {name: (0 if name == "main" else 1, pc0) for name, pc0, _ in routines}
    src = "battle" if battle else "script"

    def text(idx) -> str:
        if not isinstance(idx, int) or not 0 <= idx < len(items):
            return ""
        return textcodec.codec_by_name(items[idx].codec).to_text(items[idx].raw)

    out: List[Line] = []
    indirect = False
    for pc, name, args in sbvm.native_calls(prog, insns):
        args = args or []
        if name in DIALOGUE_NATIVES:
            pos, kind = DIALOGUE_NATIVES[name]
        elif name in MARKER_NATIVES:
            pos, kind = MARKER_NATIVES[name]
        else:
            continue
        if pos >= len(args):
            continue
        akind, aval = args[pos]
        ln = Line(source=src, scene=scene, entry=owner.get(pc, ""), kind=kind, native=name, pc=pc, path=path)
        if akind == "text":
            ln.text_id = aval
            ln.raw = text(aval)
        elif akind.endswith(":text") or akind in ("expr", "result"):
            if name in MARKER_NATIVES:
                continue
            indirect = True
            ln.text = "(text from a variable)"
        else:
            continue                                   # an int or an omitted argument: nothing shown
        if name == "talk.EvtMsg" and args[EVTMSG_VOICE][0] == "text":
            ln.voice = text(args[EVTMSG_VOICE][1])
        if name in MARKER_NATIVES:
            ln.voice, ln.text = ln.raw, ""
        elif kind == "choice" and ln.raw:
            ln.speaker, ln.text = "CHOICE", " | ".join(clean(o) for o in ln.raw.split("\\n"))
        elif ln.raw:
            spk, body = split_speaker(ln.raw)
            ln.speaker, ln.text = spk, clean(body)
            if not ln.text and kind != "keyword":
                continue                               # an empty string clears the box
        bp = _path(regions, pc)
        ln.depth = len(bp)
        ln.branch = " > ".join(f"{lab}@{a:04x}" for a, _, lab in bp)
        out.append(ln)
        res = RESOURCES.get(name)
        if res is None or find is None or not ln.voice:
            continue
        ln.voice_path = find(res[0].format(id=ln.voice, lang=lang)) or ""
        sub = find(res[1].format(id=ln.voice, lang=lang)) if res[1] else None
        if sub and read is not None:
            import subtitle
            _codec, body = subtitle.to_text(sub, read(sub), region)
            for when, cue in subtitle.cues(body):
                shown = clean(_SUBRUBY_RE.sub(r"\1", cue))
                if shown:
                    out.append(Line(source=src, scene=scene, entry=ln.entry, kind=SUBTITLE_KIND[name],
                                    text=shown, native=name, voice=ln.voice, time=when, pc=pc, raw=cue,
                                    path=sub, depth=ln.depth + 1, branch=ln.branch))
    seq = {id(l): n for n, l in enumerate(out)}
    out.sort(key=lambda l: (order_of.get(l.entry, (2, 1 << 30)), l.pc, seq[id(l)]))
    if indirect:
        for slot, idx in prog.table_strings():
            raw = text(idx)
            spk, body = split_speaker(raw)
            out.append(Line(source=src, scene=scene, entry="(table)", kind="table", speaker=spk,
                            text=clean(body), text_id=idx, native=f"g{slot}", raw=raw, path=path))
    opened: List[Tuple[int, int, str]] = []
    cur_entry = None
    for n, ln in enumerate(out):
        ln.order = n
        if ln.entry != cur_entry:
            cur_entry, opened = ln.entry, []
        bp = _path(regions, ln.pc) if ln.pc >= 0 else []
        keep = 0
        while keep < min(len(opened), len(bp)) and opened[keep] == bp[keep]:
            keep += 1
        ln.headers = [("  " * d) + f"{lab}:" for d, (_, _, lab) in enumerate(bp) if d >= keep]
        opened = bp
    return out


_KIND_NOTE = {"think": "(think)", "system": "(system)", "battle": "(battle)", "banner": "(banner)",
              "npc": "", "box": "", "event": ""}


def transcript(scene: str, header: str, lines: List[Line]) -> str:
    """A play-script view of one script's lines."""
    out = [f"# {scene}  {header}".rstrip(), ""]
    cur = None
    for ln in lines:
        if ln.entry != cur:
            cur = ln.entry
            title = "strings read through a table, in slot order" if cur == "(table)" else cur
            out += ["", f"== {title} =="]
        out += ["  " + h for h in ln.headers]
        pad = "  " * (ln.depth + 1)
        ref = f"  [#{ln.text_id:04d}]" if ln.text_id is not None else ""
        if ln.time:
            out.append(f"{pad}[{ln.time}] {ln.text}")
        elif ln.native in MARKER_NATIVES:
            where = f" -> {ln.voice_path}" if ln.voice_path else ""
            out.append(f"{pad}~ {ln.kind} {ln.voice} ({ln.native}){where}")
        elif ln.kind == "keyword":
            out.append(f"{pad}(waits for the keyword: {ln.text}){ref}")
        elif ln.kind == "choice":
            out.append(f"{pad}CHOICE: {ln.text}{ref}")
        elif ln.kind == "table":
            who = f"{ln.speaker}: " if ln.speaker else ""
            out.append(f"{pad}{ln.native}  {who}{ln.text}{ref}")
        else:
            note = _KIND_NOTE.get(ln.kind, "")
            voice = f"  <{ln.voice}>" if ln.voice else ""
            if ln.speaker:
                out.append(f"{pad}{ln.speaker}{' ' + note if note else ''}: {ln.text}{ref}{voice}")
            else:
                out.append(f"{pad}{note or '(narration)'} {ln.text}{ref}{voice}")
    return "\n".join(out).replace("\n\n\n", "\n\n") + "\n"


def string_kinds(data: bytes) -> Dict[int, str]:
    """text pool index -> what the code does with the string: a kind of
    ``DIALOGUE_NATIVES`` (shown; ``keyword`` for extalk.KeyWait), ``table`` (read
    through a global table), ``debug`` (only ever handed to deb.put), ``resource``
    (handed to other natives: ids, file names) or ``unused``. A string used in
    several ways takes the first of: shown kind, keyword, table, resource, debug."""
    prog = sbvm.parse(data)
    uses = sbvm.text_uses(prog)
    table = {v for _s, v in prog.table_strings()}
    out: Dict[int, str] = {}
    for idx in range(prog.n_strings):
        kinds = [DIALOGUE_NATIVES[n][1] for n, pos in uses.get(idx, []) if n in DIALOGUE_NATIVES
                 and DIALOGUE_NATIVES[n][0] == pos]
        shown = [k for k in kinds if k != "keyword"]
        if shown:
            out[idx] = shown[0]
        elif kinds:
            out[idx] = "keyword"
        elif idx in table:
            out[idx] = "table"
        elif idx not in uses:
            out[idx] = "unused"
        elif {n for n, _ in uses[idx]} == {"deb.put"}:
            out[idx] = "debug"
        else:
            out[idx] = "resource"
    return out


# ------------------------------------------------------------------ the disc

def scene_of(path: str) -> Tuple[str, bool]:
    """('cf/2940', False) for ``cf\\us\\2940.sb``; ('bat/CIT_B01', True) for a battle script."""
    parts = path.replace("/", "\\").lstrip("\\").split("\\")
    top, stem = parts[0].lower(), parts[-1].rsplit(".", 1)[0]
    return f"{top}/{stem}", top == "bat"


class Discs:
    """The given images as one tree: a path is read from the first image that has it."""

    def __init__(self, isos: Sequence[str]):
        import region as _region
        from disc import Disc
        self.discs = [Disc(i) for i in isos]
        self.regions = [_region.detect(d) for d in self.discs]

    def close(self) -> None:
        for d in self.discs:
            d.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def find(self, path: str) -> Optional[str]:
        for d in self.discs:
            hit = d.lookup(path)
            if hit is not None:
                return hit[1].path.lstrip("\\")
        return None

    def read(self, path: str) -> bytes:
        for d in self.discs:
            if d.lookup(path) is not None:
                return d.read(path)
        raise FileNotFoundError(path)

    def scripts(self):
        """(region, path, data) of every .sb, each path once."""
        seen = set()
        for d, reg in zip(self.discs, self.regions):
            for _c, e in d.entries():
                p = e.path.lstrip("\\")
                if p.lower().endswith(".sb") and p.lower() not in seen:
                    seen.add(p.lower())
                    yield reg, p, d.read(e.path)


def _slug(text: str, n: int = 24) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_")[:n] or "line"


def write_voice(discs: "Discs", lines: Sequence[Line], out: Path, ffmpeg: str) -> Tuple[int, List[str]]:
    """One WAV per voiced row (``VOICED`` natives whose stream is on the disc), decoded
    by ffmpeg from the row's own ADX stream. Returns (clips written, errors)."""
    import subprocess
    import tempfile
    done: Dict[str, str] = {}
    errors: List[str] = []
    n = 0
    with tempfile.TemporaryDirectory(dir=out) as tmp:
        src = Path(tmp) / "clip.adx"
        for ln in lines:
            if ln.native not in VOICED or ln.time or not ln.voice_path.lower().endswith(".adx"):
                continue
            key = ln.voice_path.lower()
            if key not in done:
                stem = ln.voice_path.rsplit("\\", 1)[-1][:-4]
                who = _slug(ln.speaker) + "_" if ln.speaker else ""
                dest = out / "voice" / Path(*ln.scene.split("/")) / f"{ln.order:04d}_{who}{stem}.wav"
                dest.parent.mkdir(parents=True, exist_ok=True)
                src.write_bytes(discs.read(ln.voice_path))
                r = subprocess.run([ffmpeg, "-y", "-loglevel", "error", "-i", str(src), str(dest)],
                                   capture_output=True, text=True)
                if r.returncode != 0 or not dest.exists():
                    errors.append(f"{ln.voice_path}: {(r.stderr or 'ffmpeg failed').strip().splitlines()[-1]}")
                    done[key] = ""
                    continue
                done[key] = str(dest.relative_to(out)).replace(os.sep, "/")
                n += 1
            ln.clip = done[key]
    return n, errors


def run(isos: Sequence[str], out: Path, only: Optional[Sequence[str]] = None, voice: bool = False,
        ffmpeg: Optional[str] = None) -> int:
    out = Path(out)
    if voice:
        if not ffmpeg:
            from browse_bundle import detect_ffmpeg
            ffmpeg = detect_ffmpeg()
        if not ffmpeg:
            print("dialogue --voice needs ffmpeg to decode the ADX streams and none was found: install it "
                  "or pass --ffmpeg /path/to/ffmpeg. Nothing was written.", file=sys.stderr)
            return 2
    (out / "scripts").mkdir(parents=True, exist_ok=True)
    all_lines: List[Line] = []
    n_scripts = n_with = clips = 0
    errors: List[str] = []
    with Discs(isos) as discs:
        for reg, path, data in sorted(discs.scripts(), key=lambda t: scene_of(t[1])[0]):
            scene, battle = scene_of(path)
            if only and not any(o.lower() in scene.lower() for o in only):
                continue
            lines = script_lines(data, scene, reg, battle=battle, path=path, find=discs.find, read=discs.read)
            n_scripts += 1
            if not lines:
                continue
            n_with += 1
            status = sb.scene_status(path)
            head = f"{path} ({sbvm.parse(data).source})" + (f"  [{status}]" if status else "")
            dest = out / "scripts" / (scene + ".txt")
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(transcript(scene, head, lines), encoding="utf-8")
            all_lines += lines
        if voice:
            clips, errors = write_voice(discs, all_lines, out, ffmpeg)
    with open(out / "dialogue.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        w.writeheader()
        for ln in all_lines:
            w.writerow(ln.row())
    kinds: Dict[str, int] = {}
    for ln in all_lines:
        kinds[ln.kind] = kinds.get(ln.kind, 0) + 1
    voiced = sum(1 for l in all_lines if l.native == "talk.EvtMsg" and l.voice)
    found = sum(1 for l in all_lines if l.native == "talk.EvtMsg" and l.voice_path)
    print(f"dialogue: {n_scripts} scripts, {n_with} with lines; {len(all_lines)} rows: "
          + ", ".join(f"{k} {v}" for k, v in sorted(kinds.items(), key=lambda kv: -kv[1])))
    print(f"voice: {voiced} event lines name a voice clip, {found} of those streams are on these discs"
          + (f"; {clips} WAV written" if voice else ""))
    for e in errors[:20]:
        print("  voice error: " + e, file=sys.stderr)
    print(f"wrote {out / 'dialogue.csv'} and {n_with} transcripts under {out / 'scripts'}")
    return 1 if errors else 0


def survey(disc, region=None) -> dict:
    """What the docstring claims, counted on a disc.Disc."""
    import collections
    import region as _region
    reg = region or _region.detect(disc)
    r: collections.Counter = collections.Counter()
    for _c, e in disc.entries():
        if not e.path.lower().endswith(".sb"):
            continue
        data = disc.read(e.path)
        prog = sbvm.parse(data)
        items = sb.parse(data, reg).items
        uses = sbvm.text_uses(prog)
        tags = set()
        for it in items:
            tags.update(m.group(1) for m in re.finditer(rb"<k([^<>]*)>", it.raw))
        shown = set()
        for idx, where in uses.items():
            for name, pos in where:
                r["text arguments"] += 1
                r["to deb.put"] += name == "deb.put"
                hit = DIALOGUE_NATIVES.get(name)
                if hit and hit[0] == pos:
                    if hit[1] == "keyword":
                        r["keyword calls"] += 1
                        r["keyword is a <k> tag of the script"] += items[idx].raw in tags
                    else:
                        shown.add(idx)
        table = {v for _s, v in prog.table_strings()}
        r["strings"] += len(items)
        r["shown strings"] += len(shown)
        r["table strings"] += len(table)
        for idx, it in enumerate(items):
            if it.role in ("dialogue", "untranslated") and idx not in shown and idx not in table:
                r["dialogue-shaped, not shown"] += 1
                if {n for n, _ in uses.get(idx, [])} == {"deb.put"}:
                    r["dialogue-shaped, only deb.put"] += 1
            if idx in shown and it.role not in ("dialogue", "untranslated", "text"):
                r["shown, but not dialogue-shaped"] += 1
        scene, battle = scene_of(e.path)
        lines = script_lines(data, scene, reg, battle=battle)
        r["rows"] += len(lines)
        r["rows shown"] += sum(1 for l in lines if l.kind in SHOWN_KINDS)
        got = {l.text_id for l in lines if l.kind in SHOWN_KINDS and l.text_id is not None}
        r["shown strings missing from the rows"] += len({i for i in shown if items[i].raw} - got
                                                        - {i for i in shown if not clean(split_speaker(
                                                            textcodec.codec_by_name(items[i].codec).to_text(items[i].raw))[1])})
    return dict(r)


# ---------------------------------------------------------------- self-test

def self_test() -> int:
    ok = True

    def chk(cond, msg):
        nonlocal ok
        print(("ok    " if cond else "FAIL  ") + msg)
        ok &= bool(cond)

    chk(clean("[x]<l2>It seems you are <knot ready> yet.<w45>\\nOK<f>") == "[x]It seems you are not ready yet. OK"
        and clean("<col284680>Counter Boost<cole> on$col1;") == "Counter Boost on"
        and clean("$rubyb;漢字$rubys;かんじ$rubye;です") == "漢字です"
        and clean("$ay375;$xx0,24;$rubyy-4;$col707070;") == "", "clean: tags out, keywords and ruby bases kept")
    chk(split_speaker("[Shion]Hi") == ("Shion", "Hi") and split_speaker("Hi") == ("", "Hi"), "speaker tag")

    A = sbvm.assemble
    strs = [b"s000200_01vir", b"[Blue Testament]Looks like things are going\\nsmoothly.<f>",   # 0 1
            b"Yes\\nNo", b"[Shion]<l1>Fine.<w15>", b"start", b"s000300",                      # 2 3 4 5
            b"[Monkey]<l1>You are <knot ready> yet.", b"not ready", b"table line"]            # 6 7 8
    main = A([(0x26, 4), 0x18, (0x4A, 0),                                   # 00 deb.put("start")
              0x1A, (0x14, 9), (0x26, 0), (0x26, 1), 0x18, (0x14, 15), 0x1D, (0x4A, 1),   # 05 talk.EvtMsg(3, 9, voice, line, 1, 15)
              (0x26, 2), 0x18, (0x4A, 2), 0x4B,                             # 12 talk.Sel("Yes\nNo"); result
              (0x42, 3 + 6),                                                # 18 jz -> 21
              (0x26, 3), 0x18, 0x19, (0x4A, 3),                             # 1b talk.Msg("[Shion]..", 1)
              (0x26, 5), 0x18, (0x4A, 4),                                   # 21 runtime.mpeg2("s000300")
              0x47])                                                        # 26 ret
    sub = A([0x18, (0x26, 6), 0x19, (0x4A, 5), (0x26, 7), 0x18, (0x4A, 6),   # extalk.Msg(1, line); extalk.KeyWait("not ready")
             0x17, 0x18, (0x21, 0), 0x50, 0x1A, (0x4A, 7), 0x47])             # bat.msgOpen(0, 1, text read through g0)
    imports = [("deb", "put"), ("talk", "EvtMsg"), ("talk", "Sel"), ("talk", "Msg"), ("runtime", "mpeg2"),
               ("extalk", "Msg"), ("extalk", "KeyWait"), ("bat", "msgOpen")]
    data = sbvm.build_script(main + sub, imports, [("npc", len(main)), ("main", 0)], strs, [8])
    lines = script_lines(data, "cf/0000")
    kinds = [(l.entry, l.kind, l.text_id) for l in lines]
    chk(kinds == [("main", "event", 1), ("main", "choice", 2), ("main", "box", 3), ("main", "movie", 5),
                  ("npc", "npc", 6), ("npc", "keyword", 7), ("npc", "battle", None), ("(table)", "table", 8)],
        "lines per routine in code order, main first; debug prints left out; table strings listed")
    ev = lines[0]
    chk(ev.speaker == "Blue Testament" and ev.text == "Looks like things are going smoothly."
        and ev.voice == "s000200_01vir", "talk.EvtMsg: speaker, text, voice id")
    chk(lines[1].text == "Yes | No" and lines[2].branch.startswith("if@") and lines[2].depth == 1
        and lines[3].branch == "" and lines[4].text == "You are not ready yet." and lines[5].text == "not ready",
        "choice split, branch kept, keyword tied to its line")
    tr = transcript("cf/0000", "test", lines)
    chk("== main ==" in tr and "  if:" in tr and "CHOICE: Yes | No" in tr and "~ movie s000300 (runtime.mpeg2)" in tr
        and "<s000200_01vir>" in tr and "(waits for the keyword: not ready)" in tr and "g0  table line" in tr,
        "transcript")
    chk(string_kinds(data) == {0: "resource", 1: "event", 2: "choice", 3: "box", 4: "debug", 5: "resource",
                               6: "npc", 7: "keyword", 8: "table"}, "string_kinds: what the code does with each string")
    files = {"mov\\us\\s000300.txt": b"00:00:00\t$ay375;$rubyy-4;\r\n00:23:05\tMiyuki!\r\nend\r\n",
             "mov\\s000300.sfd": b"", "snd\\adx\\mev\\s000200_01vir.adx": b""}
    with_disc = script_lines(data, "cf/0000", find=lambda q: q if q in files else None, read=files.__getitem__)
    cue = [l for l in with_disc if l.time]
    chk(with_disc[0].voice_path == "snd\\adx\\mev\\s000200_01vir.adx" and len(cue) == 1
        and (cue[0].kind, cue[0].time, cue[0].text) == ("movie line", "00:23:05", "Miyuki!")
        and "[00:23:05] Miyuki!" in transcript("cf/0000", "t", with_disc)
        and "-> mov\\s000300.sfd" in transcript("cf/0000", "t", with_disc),
        "with a disc: voice ids resolve to their stream, a movie's subtitle cues follow its marker")
    chk(scene_of("cf\\us\\2940.sb") == ("cf/2940", False) and scene_of("\\bat\\jp\\mom1_b02.sb") == ("bat/mom1_b02", True),
        "scene names")

    isos = [(k, os.environ.get(k)) for k in ("XS3_D1", "XS3_JP1")]
    if not any(v for _, v in isos):
        print("SKIP  disc checks (set XS3_D1 / XS3_JP1)")
    from disc import Disc
    import region as _region
    for env, iso in isos:
        if not iso:
            continue
        with Disc(iso) as disc:
            r = survey(disc)
            chk(r["shown strings"] > 9000 and r.get("shown strings missing from the rows", 0) == 0,
                f"{env}: {r['strings']} pool strings; {r['shown strings']} reach a show native, each one is a "
                f"row; {r['table strings']} more through tables; {r['rows']} rows ({r['rows shown']} shown lines)")
            voiced = found = subs = 0
            for _c, e in disc.entries():
                if e.path.lower().endswith(".sb"):
                    scene, battle = scene_of(e.path)
                    for l in script_lines(disc.read(e.path), scene, _region.detect(disc), battle=battle,
                                          find=lambda q: q if disc.lookup(q) else None, read=disc.read):
                        voiced += l.native == "talk.EvtMsg" and bool(l.voice)
                        found += l.native == "talk.EvtMsg" and bool(l.voice_path)
                        subs += bool(l.time)
            chk(voiced > 4000 and found > 3000 and subs > 0,
                f"{env}: {found} of {voiced} talk.EvtMsg voice ids have their stream snd\\adx\\mev\\<id>.adx "
                f"on this one disc (the rest are on the other); {subs} subtitle cues listed under their markers")
            chk(r["keyword calls"] == r["keyword is a <k> tag of the script"] and r["keyword calls"] > 0,
                f"{env}: extalk.KeyWait names a <k...> tag of its script in {r['keyword is a <k> tag of the script']} "
                f"of {r['keyword calls']} calls")
            print(f"      {env}: deb.put takes {r['to deb.put']} of {r['text arguments']} text arguments; "
                  f"dialogue-shaped strings (sb.classify) not shown: {r.get('dialogue-shaped, not shown', 0)} "
                  f"({r.get('dialogue-shaped, only deb.put', 0)} reach only deb.put); shown but not "
                  f"dialogue-shaped: {r.get('shown, but not dialogue-shaped', 0)}")
    for a, b, miss in (("XS3_D1", "XS3_D2", 0), ("XS3_JP1", "XS3_JP2", 1)):
        if os.environ.get(a) and os.environ.get(b):
            with Discs([os.environ[a], os.environ[b]]) as discs:
                voiced = found = 0
                for reg, path, data in discs.scripts():
                    for l in script_lines(data, scene_of(path)[0], reg, find=discs.find, read=discs.read):
                        voiced += l.native == "talk.EvtMsg" and bool(l.voice)
                        found += l.native == "talk.EvtMsg" and bool(l.voice_path)
            chk(voiced - found == miss, f"{a}+{b}: {found} of {voiced} event-line voice ids have their own "
                                        f"stream on the pair")
    print("self-test", "passed" if ok else "FAILED")
    return 0 if ok else 1


def add_commands(subparsers) -> None:
    p = subparsers.add_parser("dialogue", help="every dialogue line in play order, read from the scripts' "
                              "code: transcripts per scene and dialogue.csv")
    p.add_argument("--iso", action="append", required=True,
                   help="a disc image (read only); give Disc 1 and Disc 2 for every scene")
    p.add_argument("--out", required=True, help="folder for scripts/ and dialogue.csv")
    p.add_argument("--only", action="append", help="only scenes whose name contains this (repeatable)")
    p.add_argument("--voice", action="store_true",
                   help="also write each voiced line's own stream as a WAV under voice/ (needs ffmpeg)")
    p.add_argument("--ffmpeg", help="path to ffmpeg (default: found on this computer)")
    p.set_defaults(func=lambda a: run(a.iso, Path(a.out), a.only, a.voice, a.ffmpeg))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--iso", action="append")
    ap.add_argument("--out")
    ap.add_argument("--only", action="append")
    ap.add_argument("--voice", action="store_true")
    ap.add_argument("--ffmpeg")
    a = ap.parse_args(argv)
    if a.self_test:
        return self_test()
    if not a.iso or not a.out:
        ap.error("give --iso and --out (or --self-test)")
    return run(a.iso, Path(a.out), a.only, a.voice, a.ffmpeg)


if __name__ == "__main__":
    sys.exit(main())
