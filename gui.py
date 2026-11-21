"""gui.py — Local web GUI for the Xenosaga III Python Extractor.

Run me directly:
    python gui.py                 # opens your browser on a free localhost port
    python gui.py --no-browser    # just print the URL
    PORT=8080 python gui.py       # pin the port
    python gui.py --self-test
or double-click one of the launchers (launch.bat / launch.command / launch.sh),
which first make sure numpy, Pillow, capstone, fonttools and uharfbuzz are
installed (into .venv/ when the Python they find lacks any of them).

Stdlib only. A small HTTP server on 127.0.0.1 (never any other interface), a
page with one card per command, and every command run as a ``cli.py``
subprocess whose output streams back live (Server-Sent Events).

Schema-driven architecture borrowed from Xenosaga2PythonExtractor/gui.py
(2026-11-20): ``cli_parser`` / ``command_schema`` / ``build_argv``, the Job
runner, the picker and the page script. The cards are not written by hand:
they are built from ``cli.build_parser()`` when the GUI starts, so a command
added to cli.py (or to any module's ``add_commands``) shows up here with no
change to this file. What changed for XS3:

* cards are grouped into sections (Disc, Browse, Models, Text & translation,
  Fonts & scripts, Modding, Diagnostics) by ``SECTION_OF`` / ``SECTION_PREFIXES``,
  with an "Other" section for any command neither names;
* a command with its own sub-commands (``lang scan`` / ``lang encode`` / ...)
  becomes one card per leaf, run as ``cli.py lang scan ...``;
* ``detect_isos`` / ``xs3_builds`` find the USA pair, the Japanese pair and the
  May 2006 prototype, confirmed by ``region.region_of`` (serial + exe hash), and
  the page lets you pick which build fills the disc fields;
* an ``--iso`` whose help says "COPY" (commands that write the image in place)
  is never pre-filled with a detected original;
* ``detect_deps`` reports the five required Python packages, the CLI's own
  import errors, ffmpeg, Blender and 7-Zip;
* the stylesheet is the earlier XS3 GUI's, plus section headers.
"""
from __future__ import annotations

import argparse
import glob
import http.server
import json
import os
import queue
import re
import shlex
import shutil
import socket
import socketserver
import string
import subprocess
import sys
import threading
import time
import uuid
import webbrowser
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import parse_qs, unquote, urlparse

ROOT = Path(__file__).resolve().parent
CLI = ROOT / "cli.py"
PY = sys.executable or "python3"
sys.path.insert(0, str(ROOT))      # the kit's modules, also under `python -I`

# When frozen by PyInstaller, sys.executable is gui.exe — it can't run cli.py.
# We ship a sibling CLI binary built from the same spec; invoke it directly.
FROZEN = bool(getattr(sys, "frozen", False))
if FROZEN:
    _cli_name = "xeno-cli.exe" if os.name == "nt" else "xeno-cli"
    _cli_exe = Path(sys.executable).resolve().parent / _cli_name
    CLI_ARGV: List[str] = [str(_cli_exe)]
    CLI_TARGET = _cli_exe
    RUNTIME_DIR = Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
else:
    CLI_ARGV = [PY, str(CLI)]
    CLI_TARGET = CLI
    RUNTIME_DIR = ROOT

TITLE = "Xenosaga III Extractor"
HOST = "127.0.0.1"                 # loopback only; never bind anything else


def _fatal(title: str, body: str) -> None:
    """Surface a startup error the user can actually see (windowed builds have
    no console: a MessageBox on Windows, a dialog on a macOS app bundle)."""
    msg = f"{title}\n\n{body}"
    print(f"[gui] FATAL: {msg}", file=sys.stderr)
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, body, f"{TITLE} — {title}", 0x10)
        except Exception:
            pass
    elif sys.platform == "darwin" and FROZEN:
        try:
            esc = body.replace("\\", "\\\\").replace('"', '\\"')
            subprocess.run(
                ["osascript", "-e",
                 f'display dialog "{esc}" with title "{TITLE} — {title}" '
                 'buttons {"OK"} default button 1 with icon stop'],
                timeout=120, check=False,
            )
        except Exception:
            pass
    sys.exit(2)


# ---------------------------------------------------------------------------
# The command list, read from cli.py's own parser
# ---------------------------------------------------------------------------

def cli_parser(module=None) -> argparse.ArgumentParser:
    """cli.py's top-level parser, without running a command."""
    if module is None:
        import cli as module  # noqa: F401  (also tells PyInstaller to bundle it)
    return module.build_parser()


def cli_import_errors(module=None) -> Dict[str, str]:
    """Modules cli.py could not import while building its parser (name -> error).
    cli.py refuses every command but ``self-test`` while this is non-empty."""
    if module is None:
        import cli as module
    return dict(getattr(module, "IMPORT_ERRORS", {}) or {})


# Commands that are not cards (the GUI itself).
HIDDEN = {"gui"}

SECTIONS = ("Disc", "Browse", "Models", "Text & translation", "Fonts & scripts",
            "Modding", "Diagnostics", "Other")

# Exact names first; a command not listed falls to the first matching prefix
# in SECTION_PREFIXES, then to "Other". A sub-command card ("lang scan") is
# looked up by its full name, then by its parent ("lang").
SECTION_OF = {
    # Disc: read the image, its index and chains; the 7-Zip pipeline
    "region": "Disc", "iso-ls": "Disc", "toc-check": "Disc", "list": "Disc",
    "dump": "Disc", "prep": "Disc", "lba-from-iso": "Disc", "container-map": "Disc",
    "map-regions": "Disc", "toc": "Disc", "scan": "Disc", "extract": "Disc",
    "verify": "Disc", "code-extract": "Disc", "xc-unpack": "Disc", "resolve": "Disc",
    # Browse: viewable / playable files
    "browse": "Browse", "chr-decode": "Browse", "chr-palettes": "Browse",
    # Models
    "model": "Models", "models": "Models", "glb-info": "Models", "blend": "Models",
    # Text & translation
    "text-export": "Text & translation", "text-import": "Text & translation",
    "text-roundtrip": "Text & translation", "text-decode": "Text & translation",
    "sb-strings": "Text & translation", "txd-strings": "Text & translation",
    "nj-strings": "Text & translation", "subtitle-text": "Text & translation",
    "align-export": "Text & translation", "lang": "Text & translation",
    "evt-import": "Text & translation", "ovl-import": "Text & translation",
    "subs": "Text & translation", "msgdat-strings": "Text & translation",
    "batdat-strings": "Text & translation",
    # Fonts & scripts
    "statfont": "Fonts & scripts", "statfont-export": "Fonts & scripts",
    "statfont-import": "Fonts & scripts",
    # Modding: anything that writes a disc image
    "patch": "Modding", "chr-import-palettes": "Modding", "chr-import-entry": "Modding",
    "chr-recolor": "Modding", "chr-iso-extract": "Modding", "chr-iso-patch": "Modding",
    "chr-iso-sweep": "Modding",
    # Diagnostics
    "self-test": "Diagnostics", "doctor": "Diagnostics", "disasm": "Diagnostics",
}
SECTION_PREFIXES: Tuple[Tuple[str, str], ...] = (
    ("font", "Fonts & scripts"), ("glyph", "Fonts & scripts"), ("statfont", "Fonts & scripts"),
    ("text", "Text & translation"), ("lang", "Text & translation"),
    ("align", "Text & translation"), ("subs", "Text & translation"),
    ("evt", "Text & translation"), ("ovl", "Text & translation"),
    ("model", "Models"), ("glb", "Models"), ("blend", "Models"),
    ("image", "Browse"), ("img", "Browse"), ("tex", "Browse"), ("xtx", "Browse"),
    ("txy", "Browse"), ("png", "Browse"),
    ("repack", "Modding"), ("chr-iso", "Modding"), ("patch", "Modding"),
    ("iso", "Disc"), ("toc", "Disc"), ("chain", "Disc"),
)


def section_of(name: str) -> str:
    """The section a card goes in (see SECTION_OF / SECTION_PREFIXES)."""
    for key in (name, name.split(" ")[0]):
        if key in SECTION_OF:
            return SECTION_OF[key]
    for key in (name, name.split(" ")[0]):
        for prefix, sec in SECTION_PREFIXES:
            if key.startswith(prefix):
                return sec
    return "Other"


# Friendlier text for some commands. A command without an entry here gets
# its argparse help line, so new commands still read fine.
COMMAND_HELP = {
    "region": "Which build each image is (USA retail, Japanese retail or the May 2006 "
              "prototype), its language folder and the executable's hash. Harmless: reads only.",
    "list": "Print every entry of the disc's own index: chain, sector, size and in-game path. "
            "Chain 0 (X3.0x) is shared by both discs, chain 1 (X3.1x) is Disc 1 only, "
            "chain 2 (X3.2x) Disc 2 only.",
    "dump": "Unpack the disc images straight from their index into <code>OUT/</code>, "
            "no 7-Zip needed. Give both discs to get all three chains.",
    "browse": "Convert a dump into files your computer opens: textures as PNG, audio and "
              "movies through ffmpeg, text as UTF-8. Untick the kinds you do not want.",
    "model": "One model straight from the disc to a <code>.glb</code> Blender opens.",
    "models": "Every model at once, as <code>.glb</code> files (see docs/BLENDER.md).",
    "text-export": "Write the dialogue, menu and subtitle banks to an editable UTF-8 tree.",
    "self-test": "Run every module's built-in checks. Disc checks read the XS3_D1 / XS3_D2 / "
                 "XS3_PROTO environment variables and are skipped without them.",
    "prep": "The older 7-Zip pipeline, step 1: list the ISO and extract the X3.* parts. "
            "The direct-from-ISO commands above do not need it.",
}

# Field hints keyed by option dest: label, picker, placeholder.
FIELD_HINTS = {
    "iso": {"label": "Disc image", "pick": "file", "filter": "iso"},
    "out": {"label": "Output", "pick": "dir"},
    "work": {"label": "Work folder", "pick": "dir"},
    "stage": {"label": "Stage folder", "pick": "dir"},
    "dump": {"label": "Dump folder", "pick": "dir"},
    "text": {"label": "Text folder", "pick": "dir"},
    "code_dir": {"label": "Code folder", "pick": "dir"},
    "mod": {"label": "Mod folder", "pick": "dir"},
    "chr": {"label": ".chr file", "pick": "any"},
    "png": {"label": "PNG", "pick": "any"},
    "file": {"label": "File", "pick": "any"},
    "elf": {"label": "Executable", "pick": "any"},
    "ffmpeg": {"label": "ffmpeg", "pick": "any"},
    "sevenzip": {"label": "7-Zip", "pick": "any"},
    "path": {"label": "In-game path", "placeholder": "e.g. mnu\\us\\font0.bin"},
    "set": {"label": "Replacements", "placeholder": "chain0:mnu\\us\\font0.bin=/path/to/new.bin"},
    "limit": {"label": "At most", "placeholder": "N objects (optional, for a quick sample)"},
    "chain": {"label": "Chain", "choices": [["", "All chains"], ["0", "Chain 0 (X3.0x, both discs)"],
                                            ["1", "Chain 1 (X3.1x, Disc 1)"],
                                            ["2", "Chain 2 (X3.2x, Disc 2)"]]},
}

# Commands whose --out is a disc image they write, not a folder.
_WRITES_ISO = re.compile(r"\b(copy of the disc|disc copy|modded|\.iso|output (disc|image))\b", re.I)
_WRITES_ISO_NAMES = {"patch", "text-import", "evt-import", "ovl-import"}
# An --iso the command writes in place: never pre-filled with an original.
_IN_PLACE = re.compile(r"\bcopy\b", re.I)
_IN_PLACE_NAMES = {"chr-iso-patch", "chr-iso-sweep", "repack-patch", "repack-tree"}


def _help_of(sub_action, name) -> str:
    for ca in getattr(sub_action, "_choices_actions", []):
        if ca.dest == name or getattr(ca, "metavar", None) == name:
            return ca.help or ""
    return ""


def _kinds_choices() -> Optional[List[str]]:
    try:
        from browse_bundle import ALL_KINDS
        return list(ALL_KINDS)
    except Exception:
        return None


def _subparsers_of(p: argparse.ArgumentParser):
    return next((a for a in p._actions if isinstance(a, argparse._SubParsersAction)), None)


def _fields(name: str, p: argparse.ArgumentParser, short: str) -> List[dict]:
    writes_iso = bool(_WRITES_ISO.search(short)) or name in _WRITES_ISO_NAMES
    fields = []
    for a in p._actions:
        if isinstance(a, (argparse._HelpAction, argparse._SubParsersAction, argparse._VersionAction)):
            continue
        if a.help == argparse.SUPPRESS:
            continue
        flag = next((s for s in a.option_strings if s.startswith("--")),
                    a.option_strings[0] if a.option_strings else None)
        if isinstance(a, argparse._StoreTrueAction):
            kind = "flag"
        elif isinstance(a, argparse._StoreFalseAction):
            kind = "flag-off"
        elif isinstance(a, argparse._AppendAction) or a.nargs in ("+", "*"):
            kind = "multi"
        elif isinstance(a, argparse._StoreConstAction) or a.nargs == 0:
            kind = "flag"
        else:
            kind = "value"
        hint = dict(FIELD_HINTS.get(a.dest, {}))
        help_ = a.help or ""
        default = a.default
        if default in (None, False, argparse.SUPPRESS) or isinstance(default, (list, tuple)) and not default:
            default = None
        elif isinstance(default, (list, tuple)):
            default = "\n".join(str(x) for x in default)
        elif not isinstance(default, (str, int, float)):
            default = str(default)
        f = {
            "dest": a.dest,
            "flag": flag,
            "positional": not a.option_strings,
            "kind": kind,
            "required": bool(a.required) if a.option_strings else (a.nargs not in ("?", "*")),
            "help": help_,
            "default": default,
            "type": getattr(a.type, "__name__", None) if a.type else None,
            "choices": [str(c) for c in a.choices] if a.choices else None,
            "label": hint.get("label") or a.dest.replace("_", " ").capitalize(),
            "placeholder": hint.get("placeholder", help_),
            "nargs_many": bool(a.option_strings) and a.nargs in ("+", "*"),
        }
        if a.dest == "kinds" and name == "browse":
            f["kind"] = "kinds"
            f["choices"] = _kinds_choices()
            if not f["choices"]:
                f["kind"] = "value"
        elif hint.get("choices") and not f["choices"]:
            f["select"] = hint["choices"]
        pick = hint.get("pick")
        if a.dest == "iso" and (_IN_PLACE.search(help_) or name in _IN_PLACE_NAMES):
            f["in_place"] = True
            f["label"] = "Disc image (a COPY)"
            f["placeholder"] = "a COPY of your disc image: this command writes it in place"
        if a.dest == "out" and (writes_iso or re.search(r"\.iso\b|disc image", help_, re.I)):
            pick = "save"
            f["label"] = "Output disc"
            f["suggest"] = "modded.iso"
        if pick:
            f["pick"] = pick
            if hint.get("filter"):
                f["filter"] = hint["filter"]
        elif kind in ("value", "multi") and not f.get("select") and not f["choices"] and \
                re.search(r"\b(file|png|wav|sf2|json|csv|tsv|ttf|otf|glb|folder|dir|directory)\b",
                          help_, re.I):
            f["pick"] = "any"
        fields.append(f)
    return fields


def command_schema(parser: Optional[argparse.ArgumentParser] = None) -> List[dict]:
    """One dict per card: name, argv path, section, help, aliases and fields.

    A sub-command with sub-commands of its own (``lang scan``) gives one card
    per leaf; its ``path`` is the words to put after the CLI (["lang", "scan"])."""
    parser = parser or cli_parser()
    sub = _subparsers_of(parser)
    commands: List[dict] = []
    by_signature: Dict[tuple, dict] = {}

    def walk(sub_action, prefix: List[str]):
        for name, p in sub_action.choices.items():
            if not prefix and name in HIDDEN:
                continue
            path = prefix + [name]
            full = " ".join(path)
            short = _help_of(sub_action, name)
            inner = _subparsers_of(p)
            if inner is not None:
                walk(inner, path)
                continue
            fields = _fields(full, p, short)
            signature = (tuple(prefix), short, tuple((f["dest"], f["kind"]) for f in fields))
            if short and signature in by_signature:      # aliases: one card, two names
                by_signature[signature]["aliases"].append(full)
                continue
            cmd = {"name": full, "path": path, "short": short, "help": COMMAND_HELP.get(full, ""),
                   "section": section_of(full), "aliases": [], "fields": fields}
            by_signature[signature] = cmd
            commands.append(cmd)

    if sub is not None:
        walk(sub, [])
    order = {s: i for i, s in enumerate(SECTIONS)}
    commands.sort(key=lambda c: order.get(c["section"], len(SECTIONS)))   # stable: argparse order kept
    return commands


def build_argv(cmd: dict, form: dict) -> List[str]:
    """Turn a submitted card into the argv the CLI gets. Raises ValueError
    with a readable message when something required is missing."""
    def val(key):
        v = form.get(key)
        if isinstance(v, list):
            v = v[0] if v else ""
        return (v or "").strip()

    on = ("1", "on", "true", "yes")
    argv = [*CLI_ARGV, *cmd.get("path", [cmd["name"]])]
    positional: List[str] = []
    for f in cmd["fields"]:
        key = f["dest"]
        if f["kind"] == "flag":
            if val(key).lower() in on:
                argv.append(f["flag"])
            continue
        if f["kind"] == "flag-off":
            if val(key).lower() not in on:
                argv.append(f["flag"])
            continue
        if f["kind"] == "kinds":
            picked = [k for k in f["choices"] if val(f"{key}.{k}").lower() in on]
            if not picked:
                raise ValueError("Pick at least one kind to convert")
            if len(picked) < len(f["choices"]):
                argv += [f["flag"], ",".join(picked)]
            continue
        if f["kind"] == "multi":
            items = [s.strip() for s in re.split(r"[\n;]", val(key)) if s.strip()]
            if f["required"] and not items:
                raise ValueError(f"{f['label']} is required")
            if f["positional"]:
                positional += items
            elif f.get("nargs_many"):
                if items:
                    argv += [f["flag"], *items]
            else:
                for it in items:
                    argv += [f["flag"], it]
            continue
        v = val(key)
        if not v:
            if f["required"]:
                raise ValueError(f"{f['label']} is required")
            continue
        if f["type"] == "int":
            try:
                int(v, 0)
            except ValueError:
                raise ValueError(f"{f['label']} must be a whole number") from None
        if f["type"] == "float":
            try:
                float(v)
            except ValueError:
                raise ValueError(f"{f['label']} must be a number") from None
        if f["choices"] and v not in f["choices"]:
            raise ValueError(f"{f['label']} must be one of {', '.join(f['choices'])}")
        if f["positional"]:
            positional.append(v)
        else:
            argv += [f["flag"], v]
    # positionals go right after the command words, so an option taking many
    # values (nargs '+') cannot swallow them
    base = len(CLI_ARGV) + len(cmd.get("path", [cmd["name"]]))
    return argv[:base] + positional + argv[base:]


_SCHEMA_CACHE: Optional[List[dict]] = None
_SCHEMA_LOCK = threading.Lock()


def schema() -> List[dict]:
    global _SCHEMA_CACHE
    with _SCHEMA_LOCK:
        if _SCHEMA_CACHE is None:
            _SCHEMA_CACHE = command_schema()
        return _SCHEMA_CACHE


def find_command(name: str) -> Optional[dict]:
    for c in schema():
        if c["name"] == name or name in c["aliases"]:
            return c
    return None


# ---------------------------------------------------------------------------
# Job runner: one subprocess per launched command, lines streamed to clients
# ---------------------------------------------------------------------------

class Job:
    def __init__(self, cmd: List[str], cwd: Optional[Path]):
        self.id = uuid.uuid4().hex[:12]
        self.cmd = cmd
        self.cwd = str(cwd or ROOT)
        self.started_at = time.time()
        self.ended_at: Optional[float] = None
        self.exit_code: Optional[int] = None
        self.lines: List[str] = []
        self.subscribers: List["queue.Queue[Optional[str]]"] = []
        self._lock = threading.Lock()
        self._proc = subprocess.Popen(
            cmd, cwd=self.cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
            env={**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"},
        )
        self.lines.append(f"$ {' '.join(shlex.quote(c) for c in cmd)}")
        threading.Thread(target=self._pump, daemon=True).start()

    def _broadcast(self, line: Optional[str]) -> None:
        with self._lock:
            subs = list(self.subscribers)
        for q in subs:
            try:
                q.put_nowait(line)
            except queue.Full:
                pass

    def _pump(self) -> None:
        assert self._proc.stdout is not None
        for line in self._proc.stdout:
            line = line.rstrip("\r\n")
            with self._lock:
                self.lines.append(line)
            self._broadcast(line)
        rc = self._proc.wait()
        summary = f"[exit {rc}]"
        with self._lock:
            self.exit_code = rc
            self.ended_at = time.time()
            self.lines.append(summary)
        self._broadcast(summary)
        self._broadcast(None)

    def subscribe(self) -> "queue.Queue[Optional[str]]":
        q: "queue.Queue[Optional[str]]" = queue.Queue(maxsize=50000)
        with self._lock:
            self.subscribers.append(q)
            for line in self.lines:
                try:
                    q.put_nowait(line)
                except queue.Full:
                    break
            if self.ended_at is not None:
                q.put_nowait(None)
        return q

    def unsubscribe(self, q) -> None:
        with self._lock:
            try:
                self.subscribers.remove(q)
            except ValueError:
                pass

    def status(self) -> str:
        if self.exit_code is None:
            return "running"
        return "ok" if self.exit_code == 0 else "err"

    def to_summary(self, with_log: bool = False) -> dict:
        d = {"id": self.id, "cmd": self.cmd, "status": self.status(),
             "exit_code": self.exit_code, "started_at": self.started_at,
             "ended_at": self.ended_at}
        if with_log:
            with self._lock:
                d["log"] = list(self.lines)
        return d


JOBS: Dict[str, Job] = {}
JOBS_LOCK = threading.Lock()


# ---------------------------------------------------------------------------
# Disc detection: the USA pair, the Japanese pair and the May 2006 prototype
# ---------------------------------------------------------------------------

def _walk_for_isos(root: Path, max_depth: int, want: int, out: List[Path]) -> None:
    """Bounded depth-first scan for .iso files over 100 MB. Mutates ``out``."""
    if len(out) >= want or max_depth < 0:
        return
    try:
        entries = list(root.iterdir())
    except (OSError, PermissionError):
        return
    entries.sort(key=lambda p: (not p.is_file(), p.name.lower()))
    for child in entries:
        if len(out) >= want:
            return
        try:
            if child.is_file():
                if child.suffix.lower() == ".iso" and child.stat().st_size > 100 * 1024 * 1024:
                    out.append(child)
            elif child.is_dir() and not child.name.startswith("."):
                _walk_for_isos(child, max_depth - 1, want, out)
        except (OSError, PermissionError):
            continue


def detect_isos() -> List[str]:
    """Best-effort, fast, depth-bounded scan of likely folders for .iso files,
    plus the XS3_D1 / XS3_D2 / XS3_JP1 / XS3_JP2 / XS3_PROTO variables the
    self-tests use."""
    candidates: List[Path] = []
    for var in ("XS3_D1", "XS3_D2", "XS3_JP1", "XS3_JP2", "XS3_PROTO"):
        v = os.environ.get(var)
        if v and Path(v).is_file():
            candidates.append(Path(v))
    for root, depth in ((ROOT.parent, 2), (Path.home() / "Downloads", 2),
                        (Path.home() / "Desktop", 2), (Path.home() / "Documents", 2)):
        try:
            if root.is_dir():
                _walk_for_isos(root, depth, want=64, out=candidates)
        except OSError:
            continue
    return list(dict.fromkeys(str(p) for p in candidates))


_XS3 = re.compile(r"episode iii\b|episode 3\b|zarathustra|xenosaga ?(iii|3)\b|"
                  r"slus.?213\.?89|slus.?214\.?17|slps.?256\.?4[01]", re.I)
_JP_NAME = re.compile(r"\(japan\)|kaku katariki|slps", re.I)
_PROTO_NAME = re.compile(r"proto|\d{1,2}-\d{1,2}-0\d|press|beta|demo", re.I)
BUILD_LABELS = {"us": "USA", "jp": "Japan", "proto_2006_05": "May 2006 prototype"}


def _build_by_name(path: str) -> str:
    """Build guessed from the file and folder names: "jp", "proto_2006_05" or "us"."""
    p = Path(path)
    names = f"{p.parent.name} {p.name}"
    if _JP_NAME.search(names):
        return "jp"
    if _PROTO_NAME.search(names):
        return "proto_2006_05"
    return "us"


def _build_by_content(path: str) -> Optional[str]:
    """Build from the image itself (``region.region_of``: SYSTEM.CNF serial plus
    executable hash), or None when the image cannot be read or is unknown."""
    try:
        import region
        from iso9660 import IsoImage
        with IsoImage(path) as iso:
            name = region.region_of(iso).name
    except Exception:
        return None
    return None if name == "unknown" else name


def _disc_no(path: str) -> int:
    m = re.search(r"disc\s*([12])", Path(path).name, re.I) or \
        re.search(r"disc\s*([12])", Path(path).parent.name, re.I)
    return int(m.group(1)) if m else 1


def _serial_disc(path: str) -> Optional[int]:
    """Disc number from the boot serial (SLUS_213.89 / SLPS_256.40 = 1,
    SLUS_214.17 / SLPS_256.41 = 2)."""
    try:
        from iso9660 import IsoImage
        with IsoImage(path) as iso:
            s = iso.boot_elf_name() or ""
    except Exception:
        return None
    return {"SLUS_213.89": 1, "SLPS_256.40": 1, "SLUS_214.17": 2, "SLPS_256.41": 2}.get(s)


def xs3_builds(isos: List[str], check: bool = True) -> Dict[str, List[str]]:
    """The Episode III images among ``isos`` grouped by build, Disc 1 before
    Disc 2, one image per disc: {"us": [...], "jp": [...], "proto_2006_05": [...]}.

    Names pick the candidates (copies and other episodes are skipped); with
    ``check`` each one is then opened and ``region.region_of`` decides the
    build, and the boot serial decides the disc number. An image the kit cannot
    open keeps its name-based guess."""
    builds: Dict[str, Dict[int, str]] = {}
    for p in isos:
        name = Path(p).name
        if "copy" in name.lower() or "modded" in name.lower():
            continue
        if not (_XS3.search(name) or _XS3.search(Path(p).parent.name)):
            continue
        build = (_build_by_content(p) if check else None) or _build_by_name(p)
        disc = (_serial_disc(p) if check else None) or _disc_no(p)
        if build == "proto_2006_05":
            disc = 1
        builds.setdefault(build, {}).setdefault(disc, p)
    order = ("us", "jp", "proto_2006_05")
    ranked = sorted(builds, key=lambda b: order.index(b) if b in order else len(order))
    return {b: [builds[b][n] for n in sorted(builds[b])] for b in ranked}


def preferred_build(builds: Dict[str, List[str]]) -> Optional[str]:
    for b in ("us", "jp", "proto_2006_05"):
        if builds.get(b):
            return b
    return next(iter(builds), None)


# ---------------------------------------------------------------------------
# Dependencies: all five Python packages are required; programs are found
# ---------------------------------------------------------------------------

REQUIRED_PACKAGES = (       # (import name, display name) — requirements.txt
    ("numpy", "numpy"),
    ("PIL", "Pillow"),
    ("capstone", "capstone"),
    ("fontTools", "fonttools"),
    ("uharfbuzz", "uharfbuzz"),
)

_BLENDER_LOCATIONS = (
    "/Applications/Blender.app/Contents/MacOS/Blender",
    "~/Applications/Blender.app/Contents/MacOS/Blender",
    "/usr/bin/blender", "/usr/local/bin/blender", "/snap/bin/blender",
    "/var/lib/flatpak/exports/bin/org.blender.Blender",
    r"%ProgramFiles%\Blender Foundation\Blender*\blender.exe",
)


def _package_version(mod: str) -> str:
    """The installed version of a required package, or "" when it is missing."""
    try:
        m = __import__(mod)
    except Exception:
        return ""
    v = getattr(m, "__version__", None) or getattr(m, "version", None)
    if mod == "capstone":
        try:
            v = m.__version__ if hasattr(m, "__version__") else ".".join(map(str, m.cs_version()[:2]))
        except Exception:
            pass
    if not isinstance(v, str):
        try:
            from importlib import metadata
            v = metadata.version(dict(REQUIRED_PACKAGES).get(mod, mod))
        except Exception:
            v = "installed"
    return v


def detect_blender() -> str:
    """Path to a Blender executable, or "". A kit module that knows better
    (``blend.find_blender`` / ``blend.detect_blender``) is asked first."""
    try:
        import blend  # noqa: F401  (added in a later round; absent is fine)
        for fn in ("find_blender", "detect_blender"):
            if hasattr(blend, fn):
                p = getattr(blend, fn)()
                if p:
                    return str(p)
    except Exception:
        pass
    env = os.environ.get("BLENDER")
    if env and Path(env).exists():
        return env
    p = shutil.which("blender")
    if p:
        return p
    for raw in _BLENDER_LOCATIONS:
        expanded = os.path.expanduser(os.path.expandvars(raw))
        hits = sorted(glob.glob(expanded), reverse=True) if "*" in expanded else \
            ([expanded] if Path(expanded).exists() else [])
        if hits:
            return hits[0]
    return ""


def detect_deps() -> dict:
    """What the right-side panel shows: Python, the CLI and its import errors,
    the five required packages (version or ""), ffmpeg, Blender and 7-Zip."""
    def _safe(fn):
        try:
            return fn() or ""
        except Exception:
            return ""
    try:
        from browse_bundle import detect_ffmpeg
    except Exception:
        detect_ffmpeg = lambda: shutil.which("ffmpeg")  # noqa: E731
    try:
        from iso_ops import detect_sevenzip
    except Exception:
        detect_sevenzip = lambda: shutil.which("7z") or shutil.which("7za")  # noqa: E731
    try:
        import_errors = cli_import_errors() if _SCHEMA_CACHE is not None else {}
    except Exception as exc:
        import_errors = {"cli": f"{type(exc).__name__}: {exc}"}
    return {
        "python": sys.version.split()[0],
        "cli": str(CLI_TARGET) if CLI_TARGET.exists() else "",
        "cli_import_errors": import_errors,
        "packages": {disp: _package_version(mod) for mod, disp in REQUIRED_PACKAGES},
        "ffmpeg": _safe(detect_ffmpeg),
        "blender": _safe(detect_blender),
        "7z": _safe(detect_sevenzip),
    }


def default_out_dir(discs: List[str]) -> str:
    if discs:
        return str(Path(discs[0]).parent / "xs3-out")
    return str(Path.home() / "xs3" / "out")


def detect() -> dict:
    isos = detect_isos()
    builds = xs3_builds(isos)
    pref = preferred_build(builds)
    discs = builds.get(pref, []) if pref else []
    return {"root": str(ROOT), "isos": isos, "builds": builds, "build_labels": BUILD_LABELS,
            "build": pref, "discs": discs, "deps": detect_deps(),
            "default_out": default_out_dir(discs)}


# ---------------------------------------------------------------------------
# Filesystem browser for the picker
# ---------------------------------------------------------------------------

def list_roots() -> List[str]:
    roots: List[str] = []
    if os.name == "nt":
        for d in string.ascii_uppercase:
            p = Path(f"{d}:\\")
            if p.exists():
                roots.append(str(p))
    else:
        roots += ["/", str(Path.home())]
        for parent in ("/mnt", "/media", "/Volumes"):
            try:
                pp = Path(parent)
                if pp.is_dir():
                    roots += [str(c) for c in sorted(pp.iterdir()) if c.is_dir()]
            except (OSError, PermissionError):
                continue
    return list(dict.fromkeys(roots))


def list_dir(path_str: str, ext_filter: Optional[str] = None) -> dict:
    p = Path(path_str).expanduser() if path_str else Path.home()
    if not p.exists():
        p = Path.home()
    if not p.is_dir():
        p = p.parent
    p = p.resolve()
    entries: List[dict] = []
    err: Optional[str] = None
    try:
        children = sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
    except (OSError, PermissionError) as exc:
        children, err = [], str(exc)
    for child in children:
        try:
            if child.is_symlink() and not child.exists():
                continue
            if child.is_dir():
                if child.name.startswith("."):
                    continue
                entries.append({"name": child.name, "type": "dir", "path": str(child)})
            else:
                if ext_filter and child.suffix.lower().lstrip(".") != ext_filter.lower().lstrip("."):
                    continue
                entries.append({"name": child.name, "type": "file", "path": str(child),
                                "size": child.stat().st_size})
        except (OSError, PermissionError):
            continue
    parent = str(p.parent) if p.parent != p else None
    return {"path": str(p), "parent": parent, "entries": entries, "roots": list_roots(), "error": err}


# ---------------------------------------------------------------------------
# Embedded UI. The stylesheet (XS3_CSS, at the bottom of this file) is the
# earlier XS3 GUI's; the cards are generated from /schema.
# ---------------------------------------------------------------------------

INDEX_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>XENOSAGA III · Extractor</title>
<style>
/*__XS3_CSS__*/
</style>
</head>
<body>
<header>
  <div class="title">
    <h1>
      <span>Xenosaga</span><span class="iii">III</span>
      <span class="sep">·</span><span class="extractor">EXTRACTOR</span>
    </h1>
    <div class="tagline">Also sprach Zarathustra · disc unpacker</div>
  </div>
  <div class="actions">
    <button class="ghost" id="btn-refresh">Refresh status</button>
  </div>
</header>
<main>
  <section id="cards"></section>
  <aside id="right">
    <h2>Environment</h2>
    <div id="status-box"></div>
    <h2>Output</h2>
    <pre id="log"></pre>
  </aside>
</main>

<div class="modal" id="fs-modal" hidden>
  <div class="modal-backdrop" data-close></div>
  <div class="modal-window">
    <div class="modal-header">
      <h2 id="fs-title">Select…</h2>
      <button type="button" class="x" data-close>×</button>
    </div>
    <div class="fs-toolbar">
      <button type="button" class="ghost" id="fs-up">↑ Up</button>
      <div class="fs-crumb" id="fs-crumb"></div>
    </div>
    <div class="modal-error" id="fs-error" hidden></div>
    <div class="fs-quick" id="fs-quick" hidden></div>
    <div class="fs-list" id="fs-list"></div>
    <div class="fs-roots" id="fs-roots"></div>
    <div class="modal-footer">
      <div class="sel-path" id="fs-sel">No selection</div>
      <button type="button" class="ghost" data-close>Cancel</button>
      <button type="button" id="fs-select" disabled>Select</button>
    </div>
  </div>
</div>

<script>
const log = document.getElementById('log');
let currentEventSource = null;
const cardEls = {};
let _detectedIsos = [];
let _detect = null;

function setStatus(name, status) {
  const el = cardEls[name];
  if (!el) return;
  el.classList.remove('run','ok','err');
  if (status) el.classList.add(status);
  const badge = el.querySelector('.badge');
  badge.classList.remove('run','ok','err');
  badge.textContent = (status || 'idle');
  if (status) badge.classList.add(status);
}
function appendLog(line) { log.textContent += line + '\n'; log.scrollTop = log.scrollHeight; }
function fmtSize(bytes) {
  if (bytes < 1024) return bytes + ' B';
  const units = ['KB','MB','GB','TB']; let v = bytes / 1024, i = 0;
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
  return v.toFixed(v >= 10 ? 0 : 1) + ' ' + units[i];
}
function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'})[c]);
}
function baseName(p) { return p.split('/').pop().split('\\').pop(); }

async function runCommand(name, body) {
  if (currentEventSource) currentEventSource.close();
  log.textContent = '';
  setStatus(name, 'run');
  const res = await fetch('/run/' + encodeURIComponent(name), {
    method: 'POST', headers: {'Content-Type': 'application/x-www-form-urlencoded'}, body});
  if (!res.ok) {
    const t = await res.text(); let msg = t;
    try { const j = JSON.parse(t); if (j && j.error) msg = j.error; } catch (_) {}
    setStatus(name, 'err'); appendLog('[error] ' + msg); return;
  }
  const {job_id} = await res.json();
  const es = new EventSource('/stream/' + job_id);
  currentEventSource = es;
  es.onmessage = (e) => {
    if (e.data === '__eof__') {
      es.close();
      fetch('/job/' + job_id).then(r => r.json()).then(j => setStatus(name, j.status === 'ok' ? 'ok' : 'err'));
    } else { appendLog(e.data); }
  };
  es.onerror = () => { es.close(); };
}

// ------------------------------------------------------------------ picker
const fsModal = document.getElementById('fs-modal'), fsTitle = document.getElementById('fs-title');
const fsCrumb = document.getElementById('fs-crumb'), fsList = document.getElementById('fs-list');
const fsRoots = document.getElementById('fs-roots'), fsError = document.getElementById('fs-error');
const fsQuick = document.getElementById('fs-quick'), fsSel = document.getElementById('fs-sel');
const fsSelectBtn = document.getElementById('fs-select'), fsUp = document.getElementById('fs-up');
const fsState = { mode: 'file', filter: null, current: null, parent: null, selected: null, onChoose: null };

function _renderQuickPick() {
  const isos = fsState.filter === 'iso' ? _detectedIsos : [];
  if (!isos.length) { fsQuick.hidden = true; return; }
  fsQuick.hidden = false;
  fsQuick.innerHTML = '<span>Detected:</span>' + isos.map(p =>
    `<a class="qp" data-path="${escapeHtml(p)}" title="${escapeHtml(p)}">${escapeHtml(baseName(p))}</a>`).join('');
  fsQuick.querySelectorAll('.qp').forEach(a => {
    a.addEventListener('click', () => {
      fsQuick.querySelectorAll('.qp').forEach(x => x.classList.remove('selected'));
      a.classList.add('selected'); fsState.selected = a.dataset.path;
      fsSel.classList.add('has'); fsSel.textContent = a.dataset.path; fsSelectBtn.disabled = false;
    });
    a.addEventListener('dblclick', () => { fsState.selected = a.dataset.path; chooseAndClose(); });
  });
}
function openPicker({mode, filter, startPath, title, onChoose}) {
  Object.assign(fsState, {mode, filter: filter || null, current: null, parent: null, selected: null, onChoose});
  fsTitle.textContent = title || (mode === 'file' ? 'Select a file' : mode === 'any' ? 'Select a file or folder' : 'Select a folder');
  fsSel.classList.remove('has'); fsSel.textContent = 'No selection';
  fsSelectBtn.disabled = mode === 'file'; fsError.hidden = true;
  _renderQuickPick(); fsModal.hidden = false; loadDir(startPath || '');
}
function closePicker() { fsModal.hidden = true; fsState.onChoose = null; }
async function loadDir(path) {
  fsError.hidden = true;
  try {
    const qs = new URLSearchParams();
    if (path) qs.set('path', path);
    if (fsState.filter) qs.set('filter', fsState.filter);
    const res = await fetch('/browse-fs?' + qs.toString());
    if (!res.ok) { fsError.hidden = false; fsError.textContent = 'Cannot read directory.'; return; }
    const data = await res.json();
    if (data.error) { fsError.hidden = false; fsError.textContent = data.error; }
    fsState.current = data.path; fsState.parent = data.parent; fsState.selected = null;
    if (fsState.mode !== 'file') {
      fsState.selected = data.path; fsSel.classList.add('has'); fsSel.textContent = data.path; fsSelectBtn.disabled = false;
    } else { fsSel.classList.remove('has'); fsSel.textContent = 'No selection'; fsSelectBtn.disabled = true; }
    fsUp.disabled = !data.parent;
    renderCrumb(data.path); renderList(data.entries); renderRoots(data.roots);
  } catch (err) { fsError.hidden = false; fsError.textContent = 'Error loading directory: ' + err.message; }
}
function renderCrumb(fullPath) {
  const sep = fullPath.indexOf('\\') >= 0 && fullPath.indexOf('/') < 0 ? '\\' : '/';
  let parts;
  if (sep === '\\') { parts = fullPath.split('\\').filter(Boolean); if (parts.length && /^[A-Z]:$/i.test(parts[0])) parts[0] += '\\'; }
  else { parts = ['/'].concat(fullPath.split('/').filter(Boolean)); }
  let acc = '';
  fsCrumb.innerHTML = parts.map((p, i) => {
    if (sep === '/') acc = (i === 0) ? '/' : (acc.endsWith('/') ? acc : acc + '/') + p;
    else acc = (i === 0) ? p : (acc + (acc.endsWith('\\') ? '' : '\\') + p);
    const a = `<a data-path="${escapeHtml(acc)}">${escapeHtml(p)}</a>`;
    return i === parts.length - 1 ? a : a + '<span class="sep">/</span>';
  }).join('');
  fsCrumb.querySelectorAll('a').forEach(a => a.addEventListener('click', () => loadDir(a.dataset.path)));
}
function renderList(entries) {
  if (!entries.length) {
    fsList.innerHTML = `<div class="fs-empty">(empty${fsState.filter ? ' — no .' + fsState.filter + ' files here' : ''})</div>`;
    return;
  }
  fsList.innerHTML = entries.map(e => {
    const icon = e.type === 'dir' ? '📁' : '📄', iconCls = e.type === 'dir' ? 'icon dir' : 'icon';
    const size = e.type === 'file' ? `<span class="size">${fmtSize(e.size)}</span>` : '';
    return `<div class="fs-entry" data-type="${e.type}" data-path="${escapeHtml(e.path)}">
      <span class="${iconCls}">${icon}</span><span class="name">${escapeHtml(e.name)}</span>${size}</div>`;
  }).join('');
  fsList.querySelectorAll('.fs-entry').forEach(el => {
    el.addEventListener('click', () => {
      if (el.dataset.type === 'dir') { loadDir(el.dataset.path); }
      else if (fsState.mode === 'file' || fsState.mode === 'any') {
        fsList.querySelectorAll('.fs-entry.selected').forEach(x => x.classList.remove('selected'));
        el.classList.add('selected'); fsState.selected = el.dataset.path;
        fsSel.classList.add('has'); fsSel.textContent = el.dataset.path; fsSelectBtn.disabled = false;
      }
    });
    el.addEventListener('dblclick', () => {
      if (el.dataset.type === 'dir') loadDir(el.dataset.path);
      else if (fsState.mode === 'file' || fsState.mode === 'any') { fsState.selected = el.dataset.path; chooseAndClose(); }
    });
  });
}
function renderRoots(roots) {
  fsRoots.innerHTML = '<span>Roots:</span>' + roots.map(r => `<a data-path="${escapeHtml(r)}">${escapeHtml(r)}</a>`).join('');
  fsRoots.querySelectorAll('a').forEach(a => a.addEventListener('click', () => loadDir(a.dataset.path)));
}
function chooseAndClose() { if (!fsState.selected) return; const cb = fsState.onChoose; closePicker(); if (cb) cb(fsState.selected); }
fsUp.addEventListener('click', () => { if (fsState.parent) loadDir(fsState.parent); });
fsSelectBtn.addEventListener('click', chooseAndClose);
document.querySelectorAll('[data-close]').forEach(el => el.addEventListener('click', closePicker));
document.addEventListener('keydown', (e) => { if (!fsModal.hidden && e.key === 'Escape') closePicker(); });

// ------------------------------------------------------------------ cards from the CLI's parser
function discsOf(d) { return (d.builds && d.build && d.builds[d.build]) || d.discs || []; }
function isoDefault(f, d) {
  if (f.in_place) return '';                       // never pre-fill an original for an in-place writer
  const discs = discsOf(d);
  return f.kind === 'multi' ? discs.join('\n') : (discs[0] || '');
}
function defaultFor(f, d) {
  if (f.default !== null && f.default !== undefined) return String(f.default);
  if (f.dest === 'iso') return isoDefault(f, d);
  if (f.pick === 'save') return d.default_out ? d.default_out + '/' + (f.suggest || 'modded.iso') : '';
  if (f.dest === 'out') return d.default_out || '';
  if (f.dest === 'dump') return d.default_out || '';
  if (f.dest === 'text') return d.default_out ? d.default_out + '/text' : '';
  return '';
}
function fieldHtml(f, d) {
  const name = escapeHtml(f.dest), req = f.required ? '<span class="req">*</span>' : '';
  const label = `<label title="${escapeHtml(f.help)}">${escapeHtml(f.label)}${req}</label>`;
  if (f.kind === 'flag' || f.kind === 'flag-off') {
    return `<div class="row">${label}<div class="check-wrap"><input type="checkbox" name="${name}"${f.kind === 'flag-off' ? ' checked' : ''}>
      <span>${escapeHtml(f.help || f.flag)}</span></div></div>`;
  }
  if (f.kind === 'kinds') {
    const boxes = f.choices.map(k => `<label><input type="checkbox" name="${name}.${escapeHtml(k)}" checked> ${escapeHtml(k)}</label>`).join('');
    return `<div class="row">${label}<div class="kinds-wrap">${boxes}</div></div>`;
  }
  const opts = f.select || (f.choices ? [['', '(default)']].concat(f.choices.map(c => [c, c])) : null);
  if (opts) {
    const o = opts.map(([v, l]) => `<option value="${escapeHtml(v)}"${f.default !== null && String(f.default) === v ? ' selected' : ''}>${escapeHtml(l)}</option>`).join('');
    return `<div class="row">${label}<select name="${name}">${o}</select></div>`;
  }
  const value = escapeHtml(defaultFor(f, d)), ph = escapeHtml(f.placeholder || '');
  const isoAttr = f.dest === 'iso' && !f.in_place ? ' data-iso="1"' : '';
  const input = f.kind === 'multi'
    ? `<textarea name="${name}"${isoAttr} placeholder="${ph} (one per line)">${value}</textarea>`
    : `<input type="text" name="${name}"${isoAttr} placeholder="${ph}" value="${value}">`;
  if (!f.pick) return `<div class="row">${label}${input}</div>`;
  const btn = {file: 'Browse file', dir: 'Browse folder', save: 'Choose folder', any: 'Browse'}[f.pick] || 'Browse';
  return `<div class="row">${label}<div class="with-pick">${input}
    <button type="button" class="pick" data-pick="${f.pick}" data-pick-filter="${escapeHtml(f.filter || '')}"
      data-pick-for="${name}" data-suggest="${escapeHtml(f.suggest || '')}" data-multi="${f.kind === 'multi' ? 1 : 0}">${btn}</button></div></div>`;
}
function formBody(form) {
  const fd = new FormData(form);
  form.querySelectorAll('input[type=checkbox]').forEach(cb => fd.set(cb.name, cb.checked ? 'on' : ''));
  return new URLSearchParams(fd).toString();
}
function makeCard(step, c, d) {
  const div = document.createElement('div');
  div.className = 'card'; div.dataset.name = c.name;
  const alias = c.aliases.length ? ` <small class="alias">(also: ${c.aliases.map(escapeHtml).join(', ')})</small>` : '';
  const help = c.help || escapeHtml(c.short || '');
  div.innerHTML = `
    <div class="card-head"><span class="step">${step}.</span>
      <h3>${escapeHtml(c.name)}${alias}</h3><span class="badge">idle</span><span class="chev">▼</span></div>
    <div class="card-body">${help ? `<p class="help">${help}</p>` : ''}
      <form data-cmd="${escapeHtml(c.name)}">${c.fields.map(f => fieldHtml(f, d)).join('')}
        <div class="actions"><button type="submit">Run ${escapeHtml(c.name)}</button>
          <button type="button" class="ghost dryrun">Show command</button></div>
      </form></div>`;
  div.querySelector('.card-head').addEventListener('click', () => div.classList.toggle('open'));
  div.querySelectorAll('[data-iso]').forEach(el => el.addEventListener('input', () => { el.dataset.touched = '1'; }));
  div.querySelectorAll('button.pick').forEach(btn => btn.addEventListener('click', (e) => {
    e.stopPropagation();
    const el = btn.closest('.row').querySelector(`[name="${btn.dataset.pickFor}"]`);
    const multi = btn.dataset.multi === '1', mode = btn.dataset.pick;
    const current = multi ? (el.value.split('\n').filter(Boolean).pop() || '') : el.value;
    openPicker({
      mode: mode === 'save' ? 'dir' : mode, filter: btn.dataset.pickFilter || null,
      startPath: current || undefined,
      title: mode === 'save' ? 'Choose the folder for the new disc image' : undefined,
      onChoose: (p) => {
        if (mode === 'save') p = p.replace(/[\/\\]$/, '') + '/' + (btn.dataset.suggest || 'modded.iso');
        if (multi) el.value = (el.value.trim() ? el.value.trim() + '\n' : '') + p; else el.value = p;
        el.dataset.touched = '1';
      },
    });
  }));
  const form = div.querySelector('form');
  form.addEventListener('submit', (e) => { e.preventDefault(); runCommand(c.name, formBody(form)); });
  div.querySelector('.dryrun').addEventListener('click', (e) => {
    e.stopPropagation();
    fetch('/preview/' + encodeURIComponent(c.name), {method: 'POST',
      headers: {'Content-Type': 'application/x-www-form-urlencoded'}, body: formBody(form)})
      .then(r => r.json()).then(j => {
        log.textContent = '';
        if (j.error) { appendLog('[error] ' + j.error); return; }
        appendLog('# Would run:'); appendLog(j.cmd.map(x => /\s/.test(x) ? `"${x}"` : x).join(' '));
      });
  });
  cardEls[c.name] = div;
  return div;
}
// Re-fill every untouched disc field when another build is chosen.
function applyBuild(build) {
  if (!_detect) return;
  _detect.build = build;
  const discs = discsOf(_detect);
  document.querySelectorAll('[data-iso]').forEach(el => {
    if (el.dataset.touched) return;
    el.value = el.tagName === 'TEXTAREA' ? discs.join('\n') : (discs[0] || '');
  });
}

async function loadStatus() {
  const d = await (await fetch('/detect')).json();
  _detect = Object.assign(_detect || {}, d, _detect && _detect.build && d.builds[_detect.build] ? {build: _detect.build} : {});
  _detectedIsos = d.isos || [];
  const box = document.getElementById('status-box');
  const labels = d.build_labels || {};
  const buildNames = Object.keys(d.builds || {});
  const rows = [
    ['Python', d.deps.python, true],
    ['CLI', d.deps.cli || 'NOT FOUND', !!d.deps.cli],
  ];
  const errs = Object.entries(d.deps.cli_import_errors || {});
  if (errs.length) rows.push(['CLI modules', errs.map(([k, v]) => k + ': ' + v).join('; '), false]);
  Object.entries(d.deps.packages || {}).forEach(([k, v]) =>
    rows.push([k + ' (required)', v || 'MISSING: python -m pip install -r requirements.txt', !!v]));
  rows.push(['ffmpeg (audio, movies)', d.deps.ffmpeg || 'not found: browse skips audio and movies', !!d.deps.ffmpeg]);
  rows.push(['Blender (models)', d.deps.blender || 'not found: .glb files still open in any viewer', !!d.deps.blender]);
  rows.push(['7-Zip (prep only)', d.deps['7z'] || 'not found: only the older prep pipeline needs it', !!d.deps['7z']]);
  buildNames.forEach(b => rows.push([(labels[b] || b) + ' discs', d.builds[b].map(baseName).join(' + '), true]));
  if (!buildNames.length) rows.push(['Discs found', 'none (use Browse)', false]);
  let html = rows.map(([k, v, ok]) =>
    `<div class="row"><span>${escapeHtml(k)}</span><span class="v ${ok ? 'ok' : 'bad'}" title="${escapeHtml(String(v))}">${escapeHtml(String(v))}</span></div>`).join('');
  if (buildNames.length > 1) {
    html += `<div class="row"><span>Fill disc fields with</span><select id="build-pick">` +
      buildNames.map(b => `<option value="${escapeHtml(b)}"${b === _detect.build ? ' selected' : ''}>${escapeHtml(labels[b] || b)}</option>`).join('') +
      `</select></div>`;
  }
  box.innerHTML = html;
  const bp = document.getElementById('build-pick');
  if (bp) bp.addEventListener('change', () => applyBuild(bp.value));
  return _detect;
}

(async () => {
  const d = await loadStatus();
  const s = await (await fetch('/schema')).json();
  const cards = document.getElementById('cards');
  if (s.error) { appendLog('[error] could not read the CLI\'s commands: ' + s.error); return; }
  let section = null, step = 0;
  s.commands.forEach((c) => {
    if (c.section !== section) {
      section = c.section;
      const h = document.createElement('h2'); h.className = 'section'; h.textContent = section;
      cards.appendChild(h);
    }
    cards.appendChild(makeCard(++step, c, d));
  });
  const first = cards.querySelector('[data-name="region"]') || cards.querySelector('.card');
  if (first) first.classList.add('open');
})();
document.getElementById('btn-refresh').addEventListener('click', loadStatus);
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------

class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "Xenosaga3GUI/0.3"

    def log_message(self, fmt, *args):  # noqa: N802
        return

    def _send(self, status, body, content_type="text/plain", extra_headers=None):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra_headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _send_json(self, status, payload):
        self._send(status, json.dumps(payload), "application/json")

    def _local_host(self) -> bool:
        """The Host header must name this machine: a DNS-rebinding page (a foreign
        name that resolves to 127.0.0.1) sends its own name here and is refused,
        for reads such as /browse-fs as well as for commands."""
        host = self.headers.get("Host") or ""
        name = urlparse("//" + host).hostname or ""
        return name in ("127.0.0.1", "localhost")

    def _local_origin(self) -> bool:
        """Refuse cross-site requests: a page on another site must not be able
        to start commands here. Browsers send Origin on cross-site POSTs."""
        origin = self.headers.get("Origin")
        if not origin:
            return True
        host = urlparse(origin).hostname or ""
        return host in ("127.0.0.1", "localhost")

    def do_GET(self):  # noqa: N802
        url = urlparse(self.path)
        path = url.path
        if not self._local_host():
            return self._send_json(403, {"error": "this server answers only to localhost / 127.0.0.1"})
        if path in ("/", "/index.html"):
            return self._send(200, page(), "text/html; charset=utf-8")
        if path == "/detect":
            return self._send_json(200, detect())
        if path == "/schema":
            try:
                return self._send_json(200, {"commands": schema(), "sections": list(SECTIONS)})
            except Exception as exc:  # the page shows it instead of an empty list
                return self._send_json(200, {"error": f"{type(exc).__name__}: {exc}"})
        if path == "/browse-fs":
            params = parse_qs(url.query, keep_blank_values=True)
            return self._send_json(200, list_dir(params.get("path", [""])[0],
                                                 params.get("filter", [""])[0] or None))
        if path.startswith("/job/"):
            params = parse_qs(url.query, keep_blank_values=True)      # a bare ?log counts
            with JOBS_LOCK:
                job = JOBS.get(path[len("/job/"):])
            if not job:
                return self._send_json(404, {"error": "no such job"})
            return self._send_json(200, job.to_summary(with_log="log" in params))
        if path.startswith("/stream/"):
            return self._serve_stream(path[len("/stream/"):])
        return self._send(404, "not found")

    def do_POST(self):  # noqa: N802
        url = urlparse(self.path)
        if not self._local_host() or not self._local_origin():
            return self._send_json(403, {"error": "cross-origin request refused"})
        length = int(self.headers.get("Content-Length", "0") or 0)
        body = self.rfile.read(length).decode("utf-8", errors="replace") if length else ""
        form = parse_qs(body, keep_blank_values=True)
        for prefix, handler in (("/preview/", self._preview), ("/run/", self._run)):
            if url.path.startswith(prefix):
                return handler(unquote(url.path[len(prefix):]), form)
        return self._send(404, "not found")

    def _argv(self, name, form):
        cmd = find_command(name)
        if cmd is None:
            raise ValueError(f"unknown command: {name}")
        return build_argv(cmd, form)

    def _preview(self, name, form):
        try:
            return self._send_json(200, {"cmd": self._argv(name, form)})
        except Exception as exc:
            return self._send_json(400, {"error": str(exc)})

    def _run(self, name, form):
        try:
            argv = self._argv(name, form)
        except Exception as exc:
            return self._send_json(400, {"error": str(exc)})
        try:
            job = Job(argv, cwd=ROOT)
        except OSError as exc:
            shown = " ".join(shlex.quote(c) for c in argv)
            return self._send_json(500, {"error":
                f"could not start the extractor:\n  $ {shown}\n  {type(exc).__name__}: {exc}\n\n"
                f"Expected CLI at: {CLI_TARGET}"
                + ("  (NOT FOUND — rebuild so xeno-cli sits next to the GUI)" if not CLI_TARGET.exists() else "")})
        with JOBS_LOCK:
            JOBS[job.id] = job
        return self._send_json(200, {"job_id": job.id})

    def _serve_stream(self, job_id):
        with JOBS_LOCK:
            job = JOBS.get(job_id)
        if not job:
            return self._send(404, "no such job")
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        q = job.subscribe()
        try:
            while True:
                try:
                    line = q.get(timeout=15)
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
                    continue
                if line is None:
                    self.wfile.write(b"data: __eof__\n\n")
                    self.wfile.flush()
                    return
                for chunk in line.replace("\r", "").split("\n"):
                    self.wfile.write(b"data: " + chunk.encode("utf-8") + b"\n")
                self.wfile.write(b"\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            return
        finally:
            job.unsubscribe(q)


class ThreadingHTTPServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


_PAGE: Optional[str] = None


def page() -> str:
    global _PAGE
    if _PAGE is None:
        _PAGE = INDEX_HTML.replace("/*__XS3_CSS__*/", XS3_CSS)
    return _PAGE


# ---------------------------------------------------------------------------
# Self-test (no browser, no disc; the disc-detection check uses XS3_* when set)
# ---------------------------------------------------------------------------

def self_test() -> int:
    ok = True

    def check(cond, msg):
        nonlocal ok
        print(("ok    " if cond else "FAIL  ") + msg)
        ok &= bool(cond)

    import cli as climod
    real = cli_parser(climod)
    cmds = command_schema(real)
    names = {c["name"] for c in cmds} | {a for c in cmds for a in c["aliases"]}

    def leaves(sub, prefix=""):
        out = set()
        for n, p in sub.choices.items():
            if not prefix and n in HIDDEN:
                continue
            inner = _subparsers_of(p)
            out |= leaves(inner, prefix + n + " ") if inner else {prefix + n}
        return out
    want = leaves(_subparsers_of(real))
    check(want == names, f"every cli.py command has a card ({len(want)} commands, {len(cmds)} cards)")
    secs = [c["section"] for c in cmds]
    check(secs == sorted(secs, key=SECTIONS.index), "cards are ordered by section")
    check(all(s in SECTIONS for s in secs), "every card has a known section")
    other = sorted(c["name"] for c in cmds if c["section"] == "Other")
    print(f"      sections: " + ", ".join(f"{s} {secs.count(s)}" for s in SECTIONS if secs.count(s))
          + (f"; Other: {', '.join(other)}" if other else ""))
    check(not other, "no card of the real CLI falls into 'Other'" + (f" ({', '.join(other)})" if other else ""))
    check(section_of("lang scan") == "Text & translation" and section_of("font-whatever") == "Fonts & scripts"
          and section_of("repack-new") == "Modding" and section_of("zzz") == "Other",
          "section map: exact, parent, prefix and Other fallback")

    reg = next((c for c in cmds if c["name"] == "region"), None)
    if reg is not None:
        argv = build_argv(reg, {"iso": ["/d/Disc 1.iso\n/d/Disc 2.iso"]})[len(CLI_ARGV):]
        check(argv == ["region", "--iso", "/d/Disc 1.iso", "--iso", "/d/Disc 2.iso"],
              "region card -> argv (a repeated --iso)")
        try:
            build_argv(reg, {"iso": [""]})
            check(False, "a missing required field is refused")
        except ValueError as exc:
            check("required" in str(exc), "a missing required field is refused")
    browse = next((c for c in cmds if c["name"] == "browse"), None)
    if browse is not None:
        kinds = next(f for f in browse["fields"] if f["dest"] == "kinds")
        check(kinds["kind"] == "kinds" and "textures" in kinds["choices"], "browse --kinds becomes checkboxes")
        picked = {f"kinds.{k}": ["on"] for k in kinds["choices"][:2]}
        argv = build_argv(browse, {"dump": ["/d"], "stage": ["/s"], **picked})[len(CLI_ARGV):]
        check(argv[:1] == ["browse"] and argv[-2:] == ["--kinds", ",".join(kinds["choices"][:2])],
              "a subset of kinds")
    for c in cmds:
        for f in c["fields"]:
            if f["dest"] == "iso" and ("COPY" in (f["help"] or "") or c["name"] in _IN_PLACE_NAMES):
                check(f.get("in_place"), f"{c['name']}: an in-place --iso is never pre-filled")
                break

    # commands cli.py does not have yet: generic fields and nested sub-commands still work
    fake = argparse.ArgumentParser()
    fs = fake.add_subparsers(dest="cmd")
    p = fs.add_parser("patch", help="replace objects in a copy of the disc")
    p.add_argument("--iso", required=True, action="append")
    p.add_argument("--out", required=True)
    p.add_argument("--set", action="append", required=True)
    p.add_argument("--dry-run", action="store_true")
    lang = fs.add_parser("lang", help="language packs")
    ls = lang.add_subparsers(dest="lang_cmd")
    sc = ls.add_parser("scan", help="scan a translation for characters the font lacks")
    sc.add_argument("--text", required=True)
    sc.add_argument("--ttf", nargs="+", help="TrueType font file(s)")
    sc.add_argument("--size", type=float, default=22.0)
    sc.add_argument("bank")
    ls.add_parser("preview", help="render a line").add_argument("--line", required=True)
    fake_cmds = command_schema(fake)
    check([c["name"] for c in fake_cmds] == ["lang scan", "lang preview", "patch"],
          "nested sub-commands become one card each (sorted into their sections)")
    patch = next(c for c in fake_cmds if c["name"] == "patch")
    check(next(f for f in patch["fields"] if f["dest"] == "out").get("pick") == "save",
          "patch --out is a disc image to write, not a folder")
    argv = build_argv(patch, {"iso": ["a.iso"], "out": ["b.iso"], "set": ["x=1\ny=2"],
                              "dry_run": ["on"]})[len(CLI_ARGV):]
    check(argv == ["patch", "--iso", "a.iso", "--out", "b.iso", "--set", "x=1", "--set", "y=2", "--dry-run"],
          "patch card -> argv (append option, flag)")
    scan = fake_cmds[0]
    argv = build_argv(scan, {"text": ["/t"], "ttf": ["/f/a.ttf\n/f/b.ttf"], "size": ["24"],
                             "bank": ["cf0010"]})[len(CLI_ARGV):]
    check(argv == ["lang", "scan", "cf0010", "--text", "/t", "--ttf", "/f/a.ttf", "/f/b.ttf", "--size", "24"],
          "lang scan card -> argv (sub-command words, positional first, nargs='+' option)")
    ns = fake.parse_args(argv)
    check(ns.bank == "cf0010" and ns.ttf == ["/f/a.ttf", "/f/b.ttf"] and ns.size == 24.0,
          "argparse reads that argv back to the same values")
    try:
        build_argv(scan, {"text": ["/t"], "size": ["big"], "bank": ["x"]})
        check(False, "a non-number in a float field is refused")
    except ValueError:
        check(True, "a non-number in a float field is refused")

    names_in = [
        "/x/Xenosaga Episode III - Also sprach Zarathustra (USA) (Disc 2)/Xenosaga Episode III - Also sprach Zarathustra (USA) (Disc 2).iso",
        "/x/Xenosaga Episode III - Also sprach Zarathustra (USA) (Disc 1)/Xenosaga Episode III - Also sprach Zarathustra (USA) (Disc 1) copy.iso",
        "/x/Xenosaga Episode III - Also sprach Zarathustra (USA) (Disc 1)/Xenosaga Episode III - Also sprach Zarathustra (USA) (Disc 1).iso",
        "/x/Xenosaga Episode III - Zarathustra wa Kaku Katariki (Japan) (Disc 1)/Xenosaga Episode III - Zarathustra wa Kaku Katariki (Japan) (Disc 1).iso",
        "/x/Xenosaga Episode III - Zarathustra wa Kaku Katariki (Japan) (Disc 2)/Xenosaga Episode III - Zarathustra wa Kaku Katariki (Japan) (Disc 2).iso",
        "/x/Xenosaga Episode III - Also sprach Zarathustra (May 22, 2006 prototype)/PS2 - Xenosaga Episode III 5-24-06.iso",
        "/x/Xenosaga Episode II - Jenseits von Gut und Bose (USA) (Disc 1).iso",
    ]
    got = xs3_builds(names_in, check=False)
    check(got == {"us": [names_in[2], names_in[0]], "jp": [names_in[3], names_in[4]],
                  "proto_2006_05": [names_in[5]]},
          "disc detection by name: USA, Japan and prototype; copies and other episodes skipped")
    env = {k: os.environ.get(k) for k in ("XS3_D1", "XS3_D2", "XS3_JP1", "XS3_JP2", "XS3_PROTO")}
    have = {k: v for k, v in env.items() if v and Path(v).is_file()}
    if have:
        got = xs3_builds(list(have.values()), check=True)
        exp = {"XS3_D1": ("us", 0), "XS3_D2": ("us", 1), "XS3_JP1": ("jp", 0),
               "XS3_JP2": ("jp", 1), "XS3_PROTO": ("proto_2006_05", 0)}
        good = all(have[k] in got.get(b, []) for k, (b, _) in exp.items() if k in have)
        check(good, f"disc detection by content (region_of + serial) on {len(have)} real image(s): "
              + ", ".join(f"{b} {len(v)}" for b, v in got.items()))
    else:
        print("skip  disc detection by content (no XS3_* images set)")
    deps = detect_deps()
    check(set(deps["packages"]) == {"numpy", "Pillow", "capstone", "fonttools", "uharfbuzz"},
          "the five required packages are reported: "
          + ", ".join(f"{k} {v or 'MISSING'}" for k, v in deps["packages"].items()))
    check(all(deps["packages"].values()), "all five required packages are installed")
    print(f"      ffmpeg {deps['ffmpeg'] or '-'} | blender {deps['blender'] or '-'} | 7z {deps['7z'] or '-'}")
    html = page()
    check("__XS3_CSS__" not in html and ".card-head" in html and "/schema" in html
          and ".section" in html, "page assembled")
    print("self-test", "passed" if ok else "FAILED")
    return 0 if ok else 1


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind((HOST, 0))
        return s.getsockname()[1]


def serve(port: Optional[int] = None, open_browser: bool = True) -> int:
    if not CLI_TARGET.exists():
        if FROZEN:
            _fatal("CLI binary missing", f"Expected {CLI_TARGET.name} next to the GUI.\n\n"
                   "Extract the whole release zip first; running from inside the zip fails "
                   "(Windows only extracts the one file you click).")
        else:
            _fatal("cli.py missing", f"Expected cli.py next to gui.py at {CLI_TARGET}.")
    try:
        schema()
    except Exception as exc:
        _fatal("Could not read the CLI's commands", f"{type(exc).__name__}: {exc}")
    port = int(port or os.environ.get("PORT") or _free_port())
    url = f"http://localhost:{port}/"
    try:
        server = ThreadingHTTPServer((HOST, port), Handler)
    except OSError as exc:
        _fatal("Could not start local server", f"Failed to bind to {HOST}:{port} — {exc}.\n\n"
               "Most likely something else is already using that port.")
    print(f"[gui] {TITLE}")
    print(f"[gui] Open: {url}")
    errs = cli_import_errors()
    if errs:
        print(f"[gui] warning: cli.py could not import {', '.join(errs)}; "
              "install the requirements: python -m pip install -r requirements.txt")
    print("[gui] Press Ctrl+C to stop.", flush=True)
    if open_browser:
        threading.Thread(target=lambda: webbrowser.open(url), daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[gui] stopping")
    finally:
        server.server_close()
    return 0


def add_commands(subparsers) -> None:
    """Register ``gui`` (start this web GUI). Hidden from the GUI's own cards."""
    p = subparsers.add_parser("gui", help="start the local web GUI (127.0.0.1 only)")
    p.add_argument("--port", type=int, help="port to listen on (default: a free one)")
    p.add_argument("--no-browser", action="store_true", help="print the URL instead of opening a browser")
    p.set_defaults(func=lambda a: serve(a.port, not a.no_browser))


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Xenosaga III extractor: local web GUI (127.0.0.1 only). "
                                 "PORT=N in the environment also pins the port.")
    ap.add_argument("--port", type=int, help="port to listen on (default: $PORT or a free one)")
    ap.add_argument("--no-browser", action="store_true", help="print the URL instead of opening a browser")
    ap.add_argument("--self-test", action="store_true", help="run the GUI self-test and exit")
    a = ap.parse_args(sys.argv[1:] if argv is None else argv)   # --help / unknown flags exit here
    if a.self_test:
        return self_test()
    return serve(a.port, open_browser=not a.no_browser)


XS3_CSS = r"""
:root {
  --bg-deep:        #04070d;
  --bg-mid:         #0a1525;
  --bg-panel:       #0c1828;
  --bg-card:        #0e1c30;
  --bg-input:       #060d18;
  --border:         rgba(93, 213, 255, 0.16);
  --border-strong:  rgba(93, 213, 255, 0.38);
  --fg:             #d8e8f5;
  --muted:          #6e8aab;
  --accent:         #5dd5ff;
  --accent-warm:    #ff9d3a;
  --accent-glow:    rgba(93, 213, 255, 0.35);
  --ok:             #62ffa1;
  --warn:           #ffc15d;
  --err:            #ff6e7f;
  --grid-line:      rgba(93, 213, 255, 0.05);
}
* { box-sizing: border-box; }
html, body { height: 100%; }
body {
  margin: 0;
  background:
    radial-gradient(ellipse 70% 50% at 50% 0%, rgba(93, 213, 255, 0.06) 0%, transparent 70%),
    linear-gradient(180deg, var(--bg-deep) 0%, #02040a 100%);
  color: var(--fg);
  font-family: "Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
  font-size: 14px; line-height: 1.5;
  overflow: hidden;
}
/* Soft CRT-ish scanlines, very faint */
body::before {
  content: '';
  position: fixed; inset: 0; pointer-events: none; z-index: 1000;
  background: repeating-linear-gradient(180deg,
    transparent 0, transparent 2px,
    rgba(255, 255, 255, 0.012) 2px, rgba(255, 255, 255, 0.012) 3px);
  mix-blend-mode: lighten;
}

header {
  padding: 20px 28px 18px;
  border-bottom: 1px solid var(--border);
  display: flex; align-items: center; gap: 24px;
  background:
    linear-gradient(180deg, rgba(10, 21, 37, 0.92) 0%, rgba(10, 21, 37, 0.55) 100%);
  position: relative;
  backdrop-filter: blur(2px);
}
header::after {
  content: ''; position: absolute; left: 0; right: 0; bottom: -1px; height: 1px;
  background: linear-gradient(90deg, transparent, var(--accent) 50%, transparent);
  opacity: 0.5;
}
header .title { display: flex; flex-direction: column; gap: 2px; line-height: 1; }
header h1 {
  margin: 0;
  font-family: "Cormorant Garamond", "Cormorant", "Georgia", serif;
  font-size: 28px; font-weight: 400; letter-spacing: 0.12em;
  text-transform: uppercase;
}
header h1 .iii {
  color: var(--accent-warm);
  font-style: italic; font-weight: 500;
  margin: 0 0.15em;
  text-shadow: 0 0 14px rgba(255, 157, 58, 0.5);
}
header h1 .sep {
  color: var(--accent); opacity: 0.7; margin: 0 0.5em;
  font-weight: 300;
}
header h1 .extractor {
  font-family: "Inter", system-ui, sans-serif;
  font-size: 13px; letter-spacing: 0.35em; color: var(--muted);
  font-style: normal; font-weight: 500;
}
header .tagline {
  color: var(--muted); font-style: italic;
  font-family: "Cormorant Garamond", "Georgia", serif;
  font-size: 14px; letter-spacing: 0.04em;
  margin-top: 4px;
}
header .actions { margin-left: auto; display: flex; gap: 8px; }

main {
  display: grid; grid-template-columns: 1fr 480px;
  height: calc(100vh - 82px);
}
#cards {
  padding: 22px 28px 80px; overflow-y: auto;
}
#cards::-webkit-scrollbar { width: 10px; }
#cards::-webkit-scrollbar-thumb { background: rgba(93, 213, 255, 0.18); border-radius: 5px; }
#cards::-webkit-scrollbar-track { background: transparent; }

#right {
  border-left: 1px solid var(--border);
  background:
    linear-gradient(180deg, rgba(12, 24, 40, 0.85) 0%, rgba(8, 16, 28, 0.95) 100%);
  display: flex; flex-direction: column; min-height: 0;
}
#right h2 {
  font-family: "Cormorant Garamond", "Georgia", serif;
  font-size: 14px; font-weight: 500;
  margin: 14px 16px 6px;
  color: var(--accent);
  text-transform: uppercase; letter-spacing: 0.22em;
  position: relative; padding-left: 14px;
}
#right h2::before {
  content: ''; position: absolute; left: 0; top: 50%; width: 7px; height: 1px;
  background: var(--accent); transform: translateY(-50%);
  box-shadow: 0 0 6px var(--accent-glow);
}

#status-box { padding: 0 16px 14px; }
#status-box .row {
  display: flex; justify-content: space-between;
  padding: 5px 0; font-size: 13px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.04);
}
#status-box .row:last-child { border-bottom: 0; }
#status-box .row span:first-child {
  color: var(--muted); font-size: 12px; letter-spacing: 0.04em; text-transform: uppercase;
}
#status-box .row .v {
  font-family: ui-monospace, "SF Mono", Menlo, monospace; font-size: 12px;
  color: var(--muted); max-width: 60%;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
#status-box .row .v.ok  { color: var(--ok); }
#status-box .row .v.bad { color: var(--err); }

#log {
  flex: 1; margin: 0; padding: 14px 16px;
  background: #02050b; color: #b8d3eb;
  font-family: ui-monospace, "SF Mono", Menlo, monospace; font-size: 12px; line-height: 1.55;
  overflow-y: auto; white-space: pre-wrap;
  border-top: 1px solid var(--border);
  min-height: 0;
}
#log::-webkit-scrollbar { width: 8px; }
#log::-webkit-scrollbar-thumb { background: rgba(93, 213, 255, 0.2); border-radius: 4px; }

.card {
  background:
    linear-gradient(180deg, rgba(14, 28, 48, 0.7) 0%, rgba(10, 21, 37, 0.7) 100%);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 16px 18px;
  margin-bottom: 12px;
  transition: border-color 0.18s, box-shadow 0.18s;
  position: relative;
}
.card::before {
  content: ''; position: absolute; left: 0; top: 0; bottom: 0; width: 2px;
  background: transparent; transition: background 0.18s, box-shadow 0.18s;
  border-radius: 6px 0 0 6px;
}
.card.run { border-color: var(--accent); box-shadow: 0 0 22px rgba(93, 213, 255, 0.12); }
.card.run::before { background: var(--accent); box-shadow: 0 0 8px var(--accent-glow); }
.card.ok  { border-color: rgba(98, 255, 161, 0.4); }
.card.ok::before  { background: var(--ok); }
.card.err { border-color: rgba(255, 110, 127, 0.5); }
.card.err::before { background: var(--err); }

.card-head {
  display: flex; align-items: baseline; gap: 14px;
  cursor: pointer; user-select: none;
}
.card-head h3 {
  margin: 0;
  font-family: "Cormorant Garamond", "Georgia", serif;
  font-size: 18px; font-weight: 500;
  letter-spacing: 0.04em;
}
.card-head .step {
  font-family: "Cormorant Garamond", "Georgia", serif;
  color: var(--accent-warm); font-style: italic;
  font-size: 16px; min-width: 26px;
}
.card-head .badge {
  font-size: 10px; padding: 3px 9px; border-radius: 2px;
  background: rgba(110, 138, 171, 0.12);
  color: var(--muted);
  margin-left: auto;
  text-transform: uppercase; letter-spacing: 0.14em; font-weight: 600;
}
.card-head .badge.run { background: rgba(93, 213, 255, 0.18);  color: var(--accent); }
.card-head .badge.ok  { background: rgba(98, 255, 161, 0.18);  color: var(--ok); }
.card-head .badge.err { background: rgba(255, 110, 127, 0.18); color: var(--err); }
.card-head .chev {
  color: var(--muted); transition: transform 0.2s;
  margin-left: 10px; font-size: 12px;
}
.card.open .chev { transform: rotate(180deg); }

.card-body { display: none; margin-top: 14px; }
.card.open .card-body { display: block; }
.card-body p.help {
  margin: 0 0 14px; color: var(--muted); font-size: 13px;
  line-height: 1.55;
}
.card-body p.help code { color: var(--accent); font-size: 12px; }

.card .row {
  display: grid; grid-template-columns: 130px 1fr; gap: 12px;
  margin-bottom: 9px; align-items: center;
}
.card .row label {
  color: var(--muted); font-size: 12px;
  text-transform: uppercase; letter-spacing: 0.08em;
}
.card .row .with-pick {
  display: grid; grid-template-columns: 1fr auto; gap: 6px;
}
.card .row .check-wrap {
  display: flex; align-items: center; gap: 10px;
}
.card .row .check-wrap span { color: var(--muted); font-size: 12px; }

.card input[type=text], .card textarea, .card select {
  width: 100%; background: var(--bg-input); color: var(--fg);
  border: 1px solid var(--border);
  border-radius: 3px; padding: 8px 10px;
  font: inherit;
  font-family: ui-monospace, "SF Mono", Menlo, monospace;
  font-size: 12.5px; transition: border-color 0.15s, box-shadow 0.15s;
}
.card input[type=text]:focus, .card textarea:focus, .card select:focus {
  outline: none; border-color: var(--accent);
  box-shadow: 0 0 0 1px var(--accent-glow), 0 0 10px rgba(93, 213, 255, 0.18);
}
.card input[type=checkbox] {
  accent-color: var(--accent); width: 16px; height: 16px;
}
.card textarea { min-height: 70px; resize: vertical; line-height: 1.5; }
.card .actions { margin-top: 14px; display: flex; gap: 8px; }

button {
  background: linear-gradient(180deg, #5dd5ff 0%, #3da8d8 100%);
  color: #02101e; border: 0;
  padding: 8px 16px; border-radius: 3px;
  font: inherit; font-weight: 600; font-size: 12px;
  letter-spacing: 0.1em; text-transform: uppercase;
  cursor: pointer; transition: filter 0.15s, transform 0.05s;
  box-shadow: 0 0 12px rgba(93, 213, 255, 0.25);
}
button:hover { filter: brightness(1.15); }
button:active { transform: translateY(1px); }
button.ghost {
  background: transparent; color: var(--fg);
  border: 1px solid var(--border);
  font-weight: 500; box-shadow: none;
}
button.ghost:hover {
  background: rgba(93, 213, 255, 0.08);
  border-color: var(--accent);
}
button.pick {
  padding: 7px 12px; font-size: 11px;
  background: rgba(93, 213, 255, 0.12); color: var(--accent);
  border: 1px solid var(--border); box-shadow: none; font-weight: 500;
}
button.pick:hover {
  background: rgba(93, 213, 255, 0.2);
  border-color: var(--accent);
}
button:disabled { opacity: 0.4; cursor: not-allowed; }

code, kbd {
  background: rgba(93, 213, 255, 0.08); color: var(--accent);
  border-radius: 2px; padding: 1px 5px;
  font-family: ui-monospace, "SF Mono", Menlo, monospace; font-size: 12px;
}
.muted { color: var(--muted); }

/* ------------------------------------------------------------------ */
/* File picker modal                                                  */
/* ------------------------------------------------------------------ */
.modal[hidden] { display: none; }
.modal {
  position: fixed; inset: 0; z-index: 100;
  display: flex; align-items: center; justify-content: center;
}
.modal-backdrop {
  position: absolute; inset: 0;
  background: rgba(2, 5, 11, 0.82);
  backdrop-filter: blur(4px);
  animation: fadeIn 0.15s ease-out;
}
.modal-window {
  position: relative; z-index: 1;
  background:
    linear-gradient(180deg, var(--bg-card) 0%, var(--bg-mid) 100%);
  border: 1px solid var(--border-strong);
  box-shadow:
    0 0 0 1px var(--border),
    0 0 80px rgba(93, 213, 255, 0.18),
    0 20px 60px rgba(0, 0, 0, 0.5);
  border-radius: 8px;
  width: 760px; max-width: 92vw; height: 580px; max-height: 88vh;
  display: flex; flex-direction: column;
  animation: slideIn 0.18s ease-out;
  overflow: hidden;
}
@keyframes fadeIn { from { opacity: 0; } to { opacity: 1; } }
@keyframes slideIn {
  from { opacity: 0; transform: translateY(-8px) scale(0.985); }
  to   { opacity: 1; transform: translateY(0) scale(1); }
}
.modal-header {
  padding: 16px 22px; border-bottom: 1px solid var(--border);
  display: flex; align-items: center; gap: 12px;
  background:
    linear-gradient(180deg, rgba(93, 213, 255, 0.04), transparent);
}
.modal-header h2 {
  margin: 0;
  font-family: "Cormorant Garamond", "Georgia", serif;
  font-size: 18px; font-weight: 500; letter-spacing: 0.06em;
}
.modal-header .x {
  margin-left: auto; background: transparent; border: 0; color: var(--muted);
  font-size: 22px; cursor: pointer; padding: 0 6px; box-shadow: none;
  text-transform: none; letter-spacing: 0;
}
.modal-header .x:hover { color: var(--err); background: transparent; }
.fs-toolbar {
  padding: 12px 18px; border-bottom: 1px solid var(--border);
  display: flex; align-items: center; gap: 8px;
  font-size: 13px; color: var(--muted);
  background: rgba(2, 5, 11, 0.3);
}
.fs-crumb {
  flex: 1; overflow-x: auto; white-space: nowrap;
  font-family: ui-monospace, "SF Mono", Menlo, monospace; font-size: 12px;
}
.fs-crumb a {
  color: var(--accent); cursor: pointer; padding: 2px 4px;
  border-radius: 2px;
}
.fs-crumb a:hover { background: rgba(93, 213, 255, 0.12); }
.fs-crumb .sep { color: var(--muted); margin: 0 2px; opacity: 0.6; }
.fs-list {
  flex: 1; overflow-y: auto; padding: 4px 6px;
}
.fs-list::-webkit-scrollbar { width: 10px; }
.fs-list::-webkit-scrollbar-thumb { background: rgba(93, 213, 255, 0.18); border-radius: 5px; }
.fs-entry {
  display: flex; align-items: center; gap: 12px;
  padding: 8px 12px; cursor: pointer; border-radius: 3px;
  font-size: 13px;
}
.fs-entry:hover { background: rgba(93, 213, 255, 0.08); }
.fs-entry.selected {
  background: rgba(93, 213, 255, 0.18);
  outline: 1px solid var(--accent);
}
.fs-entry .icon {
  width: 18px; text-align: center; opacity: 0.85; font-size: 14px;
}
.fs-entry .icon.dir { color: var(--accent-warm); }
.fs-entry .name { flex: 1; }
.fs-entry .size {
  margin-left: auto; color: var(--muted); font-size: 11px;
  font-family: ui-monospace, "SF Mono", Menlo, monospace;
}
.fs-empty { padding: 30px; text-align: center; color: var(--muted); font-size: 13px; }
.fs-roots {
  border-top: 1px solid var(--border);
  padding: 8px 18px; display: flex; flex-wrap: wrap; gap: 6px;
  font-size: 11px; align-items: center;
}
.fs-roots span { color: var(--muted); text-transform: uppercase; letter-spacing: 0.1em; margin-right: 4px; }
.fs-roots a {
  color: var(--accent); padding: 3px 8px; border-radius: 2px;
  border: 1px solid var(--border); cursor: pointer;
  font-family: ui-monospace, "SF Mono", Menlo, monospace; font-size: 11px;
}
.fs-roots a:hover { background: rgba(93, 213, 255, 0.12); border-color: var(--accent); }
.modal-footer {
  padding: 14px 18px; border-top: 1px solid var(--border);
  display: flex; align-items: center; gap: 10px;
  background: rgba(2, 5, 11, 0.3);
}
.modal-footer .sel-path {
  flex: 1; min-width: 0;
  color: var(--muted); font-size: 12px;
  font-family: ui-monospace, "SF Mono", Menlo, monospace;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.modal-footer .sel-path.has { color: var(--fg); }
.modal-error {
  padding: 8px 18px; color: var(--err); font-size: 12px;
  background: rgba(255, 110, 127, 0.06);
  border-bottom: 1px solid rgba(255, 110, 127, 0.2);
}

/* added with the schema-driven cards (2026-11-20) */
#cards h2.section {
  margin: 18px 2px 8px; font-size: 11px; font-weight: 600;
  letter-spacing: 0.18em; text-transform: uppercase; color: var(--accent);
  border-bottom: 1px solid var(--border); padding-bottom: 4px;
}
#cards h2.section:first-child { margin-top: 0; }
.card .row .kinds-wrap { display: flex; flex-wrap: wrap; gap: 6px 16px; }
.card .row .kinds-wrap label {
  text-transform: none; letter-spacing: 0; font-size: 13px; color: var(--fg);
  display: flex; align-items: center; gap: 6px;
}
.card .row small.alias, .card-head small.alias { color: var(--muted); }
.card .row .req { color: var(--accent-warm); margin-left: 3px; }
#status-box select {
  background: var(--bg-input); color: var(--fg); border: 1px solid var(--border);
  border-radius: 2px; padding: 2px 6px; font-size: 12px;
}
.fs-quick {
  padding: 8px 18px; border-bottom: 1px solid var(--border);
  display: flex; flex-wrap: wrap; gap: 6px; align-items: center;
  background: rgba(93, 213, 255, 0.03);
}
.fs-quick span { color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: 0.1em; }
.fs-quick a {
  color: var(--fg); padding: 4px 10px; border-radius: 2px;
  border: 1px solid var(--border); cursor: pointer; font-size: 12px;
  font-family: ui-monospace, "SF Mono", Menlo, monospace;
  white-space: nowrap; max-width: 320px; overflow: hidden; text-overflow: ellipsis;
}
.fs-quick a:hover { background: rgba(93, 213, 255, 0.12); border-color: var(--accent); color: var(--accent); }
.fs-quick a.selected { background: rgba(93, 213, 255, 0.18); border-color: var(--accent); color: var(--accent); }
"""


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except BaseException as exc:
        import traceback
        _fatal("Unexpected error during startup",
               f"{type(exc).__name__}: {exc}\n\nTraceback:\n{traceback.format_exc()}")
