"""Backups of translation-editor projects.

A project file (``NAME.json``) gets a folder next to it, ``NAME backups/``,
holding dated copies:

* **automatic**: taken by the server just before a save replaces the file,
  at most one every ``AUTO_EVERY`` seconds, so the history of a working
  session is there without anyone thinking about it. The newest
  ``KEEP_AUTO`` are kept, plus the last one of each of the past
  ``KEEP_DAYS`` days; older automatic copies are deleted.
* **checkpoints**: taken on request with a label ("End of disc 1"). Never
  deleted by this module.
* **before restore**: the file as it was, taken before a restore replaces it
  (so a restore can itself be undone). Kept like checkpoints.

A copy identical to the newest backup is not written again. File names:
``NAME 2026-11-20 225301 auto.json``, ``... checkpoint - End of disc 1.json``,
``... before-restore.json``. Standard library only.

    python3 txbackup.py list PROJECT.json
    python3 txbackup.py checkpoint PROJECT.json "End of disc 1"
    python3 txbackup.py restore PROJECT.json BACKUP.json
    python3 txbackup.py selftest
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional

AUTO_EVERY = 10 * 60      # seconds between automatic backups
KEEP_AUTO = 20            # newest automatic backups always kept
KEEP_DAYS = 30            # plus the last automatic backup of each of these days

KINDS = ("auto", "checkpoint", "before-restore")
_NAME_RE = re.compile(r"^(?P<stem>.*) (?P<date>\d{4}-\d{2}-\d{2}) (?P<time>\d{6}) "
                      r"(?P<kind>auto|checkpoint|before-restore)(?: - (?P<label>.*))?\.json$")
_BAD = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


class BackupError(ValueError):
    pass


def folder(project: str) -> Path:
    p = Path(project).expanduser()
    return p.with_name(p.stem + " backups")


def _digest(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def _clean_label(label: str) -> str:
    label = _BAD.sub(" ", (label or "").strip())
    label = re.sub(r"\s+", " ", label).strip(" .")
    return label[:80]


def list_backups(project: str) -> List[dict]:
    """Newest first: [{path, name, kind, label, time (epoch), when (local text),
    translations (count or None), size}]."""
    d = folder(project)
    if not d.is_dir():
        return []
    out = []
    for f in d.iterdir():
        m = _NAME_RE.match(f.name)
        if not m or not f.is_file():
            continue
        try:
            t = datetime.strptime(m["date"] + m["time"], "%Y-%m-%d%H%M%S").timestamp()
        except ValueError:
            continue
        n = None
        try:
            n = len(json.loads(f.read_text("utf-8")).get("translations") or {})
        except (OSError, ValueError, AttributeError):
            pass
        out.append({"path": str(f), "name": f.name, "kind": m["kind"], "label": m["label"] or "",
                    "time": t, "when": datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M:%S"),
                    "translations": n, "size": f.stat().st_size})
    out.sort(key=lambda b: (b["time"], b["name"]), reverse=True)
    return out


def _write(project: str, data: bytes, kind: str, label: str = "") -> Optional[str]:
    if kind not in KINDS:
        raise BackupError(f"unknown backup kind {kind!r}")
    newest = list_backups(project)
    if newest and kind == "auto":
        try:
            if _digest(Path(newest[0]["path"]).read_bytes()) == _digest(data):
                return None        # nothing changed since the last copy
        except OSError:
            pass
    d = folder(project)
    d.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d %H%M%S")
    lab = _clean_label(label)
    name = f"{Path(project).stem} {stamp} {kind}" + (f" - {lab}" if lab else "") + ".json"
    dest = d / name
    i = 2
    while dest.exists():           # two in the same second
        dest = d / (name[:-5] + f" ({i}).json")
        i += 1
    tmp = dest.with_name(dest.name + ".partial")
    tmp.write_bytes(data)
    os.replace(tmp, dest)
    return str(dest)


def auto(project: str, now: Optional[float] = None) -> Optional[str]:
    """Called before a save replaces ``project``: copy the file as it is now
    if the newest backup is older than AUTO_EVERY. Then prune."""
    p = Path(project).expanduser()
    if not p.is_file():
        return None
    now = time.time() if now is None else now
    backs = list_backups(str(p))
    autos = [b for b in backs if b["kind"] == "auto"]
    if autos and now - autos[0]["time"] < AUTO_EVERY:
        return None
    made = _write(str(p), p.read_bytes(), "auto")
    prune(str(p))
    return made


def checkpoint(project: str, label: str = "", data: Optional[bytes] = None) -> str:
    """A labelled copy of the project (``data`` = the bytes to keep, else the
    file on disk). Always written, even if identical to an earlier one."""
    p = Path(project).expanduser()
    if data is None:
        if not p.is_file():
            raise BackupError(f"no project file at {p}")
        data = p.read_bytes()
    made = _write(str(p), data, "checkpoint", label)
    return made or ""


def prune(project: str) -> List[str]:
    """Delete automatic backups beyond the newest KEEP_AUTO, except the last of
    each of the past KEEP_DAYS days. Checkpoints are never deleted."""
    autos = [b for b in list_backups(project) if b["kind"] == "auto"]
    keep = {b["path"] for b in autos[:KEEP_AUTO]}
    days = {}
    cutoff = time.time() - KEEP_DAYS * 86400
    for b in autos:                                   # newest first
        day = b["when"][:10]
        if b["time"] >= cutoff and day not in days:
            days[day] = b["path"]
    keep |= set(days.values())
    gone = []
    for b in autos:
        if b["path"] not in keep:
            try:
                os.remove(b["path"])
                gone.append(b["path"])
            except OSError:
                pass
    return gone


def _inside(project: str, backup: str) -> Path:
    b = Path(backup).expanduser().resolve()
    d = folder(project).resolve()
    if b.parent != d or not _NAME_RE.match(b.name) or not b.is_file():
        raise BackupError("that file is not one of this project's backups")
    return b


def restore(project: str, backup: str) -> str:
    """Replace ``project`` with ``backup`` (one of its own backups); the file
    as it was is kept first as a 'before-restore' backup. -> that backup's path."""
    p = Path(project).expanduser()
    b = _inside(str(p), backup)
    data = b.read_bytes()
    try:
        json.loads(data.decode("utf-8"))["translations"]
    except (ValueError, KeyError, TypeError, UnicodeDecodeError):
        raise BackupError(f"{b.name} is not a readable project file") from None
    before = ""
    if p.is_file():
        before = _write(str(p), p.read_bytes(), "before-restore") or ""
    tmp = p.with_name(p.name + ".partial")
    tmp.write_bytes(data)
    os.replace(tmp, p)
    return before


def save_copy(project_data: bytes, dest: str, overwrite: bool = False) -> str:
    """Write the project to another place (a USB stick, a cloud folder)."""
    d = Path(dest).expanduser()
    if d.suffix.lower() != ".json":
        raise BackupError("a project copy must end in .json")
    if not d.parent.is_dir():
        raise BackupError(f"no folder {d.parent}")
    if d.exists() and not overwrite:
        raise BackupError(f"{d.name} already exists there")
    tmp = d.with_name(d.name + ".partial")
    tmp.write_bytes(project_data)
    os.replace(tmp, d)
    return str(d)


# ---------------------------------------------------------------------------

def selftest() -> int:
    ok = True

    def check(c, msg):
        nonlocal ok
        print(("ok   " if c else "FAIL ") + msg)
        ok = ok and bool(c)

    with tempfile.TemporaryDirectory() as td:
        proj = Path(td) / "My game (FR).json"
        proj.write_text(json.dumps({"format": 1, "language": "fr", "translations": {"a": {"text": "x"}}}))
        b1 = auto(str(proj))
        check(b1 and Path(b1).parent.name == "My game (FR) backups", "first save makes an automatic backup")
        check(auto(str(proj)) is None, "no second automatic backup within 10 minutes")
        check(auto(str(proj), now=time.time() + AUTO_EVERY + 5) is None, "identical content is not copied again")
        proj.write_text(json.dumps({"format": 1, "language": "fr", "translations": {"a": {"text": "y"}, "b": {"text": "z"}}}))
        b2 = auto(str(proj), now=time.time() + AUTO_EVERY + 5)
        check(bool(b2), "changed content after 10 minutes is copied")
        c = checkpoint(str(proj), 'End of disc 1: Woglinde/"Elsa"')
        lst = list_backups(str(proj))
        check(any(x["kind"] == "checkpoint" and x["label"] == "End of disc 1 Woglinde Elsa" for x in lst),
              "checkpoint keeps a cleaned label")
        check(lst[0]["translations"] == 2, "list counts translations")
        before = restore(str(proj), b1)
        check(json.loads(proj.read_text())["translations"]["a"]["text"] == "x", "restore puts the old file back")
        check(before and "before-restore" in before, "restore keeps the replaced file")
        try:
            restore(str(proj), str(proj))
            check(False, "restore refuses a file outside the backups folder")
        except BackupError:
            check(True, "restore refuses a file outside the backups folder")
        # pruning: 30 old automatic backups on one day -> KEEP_AUTO left (+ checkpoints untouched)
        d = folder(str(proj))
        for i in range(30):
            (d / f"My game (FR) 2026-01-01 {i:06d} auto.json").write_text('{"translations": {}}')
        prune(str(proj))
        autos = [x for x in list_backups(str(proj)) if x["kind"] == "auto"]
        check(len(autos) == KEEP_AUTO, f"pruning keeps the newest {KEEP_AUTO} automatic backups ({len(autos)})")
        check(any(x["kind"] == "checkpoint" for x in list_backups(str(proj))), "checkpoints are never pruned")
        out = save_copy(proj.read_bytes(), str(Path(td) / "copy.json"))
        check(Path(out).is_file(), "save a copy elsewhere")
        try:
            save_copy(proj.read_bytes(), str(Path(td) / "copy.json"))
            check(False, "save a copy refuses to overwrite")
        except BackupError:
            check(True, "save a copy refuses to overwrite")
    print("selftest " + ("passed" if ok else "FAILED"))
    return 0 if ok else 1


def main(argv=None) -> int:
    a = list(sys.argv[1:] if argv is None else argv)
    if not a or a[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    cmd = a[0]
    try:
        if cmd == "selftest":
            return selftest()
        if cmd == "list" and len(a) == 2:
            for b in list_backups(a[1]):
                print(f"{b['when']}  {b['kind']:<14} {b['translations'] if b['translations'] is not None else '?':>6}  "
                      f"{b['label']}")
            return 0
        if cmd == "checkpoint" and len(a) in (2, 3):
            print(checkpoint(a[1], a[2] if len(a) == 3 else ""))
            return 0
        if cmd == "restore" and len(a) == 3:
            before = restore(a[1], a[2])
            print(f"restored; the replaced file is kept as {before}" if before else "restored")
            return 0
    except BackupError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
