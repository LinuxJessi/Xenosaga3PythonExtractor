"""txproject.py — the translation editor's project file, TSV and paste formats.

A translation project is a small JSON file that holds ONLY what the
translator typed, keyed by the catalog row ids (which are retail-relative:
in-game path + the container's own string key, see txfam_core). It never stores an encoded
or re-exported tree, because re-exporting a patched disc gives misleading
budgets and moved keys; every build starts again from the retail image the
project is pinned to (``retail_id``).

    {"format": 1, "language": "fr", "retail_id": "<sha1>",
     "translations": {id: {"text": str, "state": "draft"|"done"}},
     "target": {...}}            # optional, see txtarget.normalise_target

Three text interchange formats live here so the server and the page agree
on one definition:

* TSV: ``id <TAB> source <TAB> translation`` with ``\\n``, ``\\t`` and
  ``\\\\`` escapes, for spreadsheets and CAT tools.
* The numbered "group paste" block used by the editor's "Copy group for
  translation" / "Paste translations into group" buttons: one line per
  string, ``[n] text``, with internal line breaks written as ``⏎``. Machine
  translators and chat assistants keep ``[n]`` markers and a symbol like ``⏎``
  far more reliably than they keep blank-line structure, and when they do
  re-wrap a long line the continuation is simply joined back with a space.

Run ``python3 txproject.py selftest --iso RETAIL`` to check the formats
round-trip and that the retail id can be computed (read-only).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

FORMAT = 1
STATES = ("draft", "done")
NEWLINE_MARK = "\u23ce"          # ⏎
BOOT_ELF = "SLUS_213.89"         # Xenosaga Episode III (USA) Disc 1; any build txdiscs knows is accepted


class ProjectError(ValueError):
    pass


# ---------------------------------------------------------------------------
# retail id
# ---------------------------------------------------------------------------

def retail_id(iso_path: str) -> str:
    """sha1 over the disc set ``iso_path`` belongs to (``txdiscs.pair``: Disc 1
    + Disc 2 when the other disc is found): per disc its number, the boot
    executable's name and sha256, and the sha1 of every X3.x0 index.

    An index entry records each object's sector and size, so a kit import
    that moves an object or changes its length shows up here, as does a
    patched executable. A same-length, in-place replacement of an object is
    still invisible; nothing short of hashing the whole image catches that.
    Either disc of a pair gives the same id; a disc opened alone gives
    another (its catalog lacks the other disc's subtitles). Read-only.
    """
    import txdiscs
    try:
        return txdiscs.retail_id(iso_path)
    except (txdiscs.DiscError, OSError) as exc:
        raise ProjectError(str(exc)) from None


# ---------------------------------------------------------------------------
# project load / save / merge
# ---------------------------------------------------------------------------

def new_project(language: str = "fr", rid: str = "") -> dict:
    return {"format": FORMAT, "language": language, "retail_id": rid,
            "translations": {}}


def normalise(project: dict) -> dict:
    """Validate a project dict and return a clean copy (drops empty texts,
    unknown states become "draft")."""
    if not isinstance(project, dict):
        raise ProjectError("project must be a JSON object")
    fmt = project.get("format", FORMAT)
    if fmt != FORMAT:
        raise ProjectError(f"unsupported project format {fmt!r} (this kit reads {FORMAT})")
    tr_in = project.get("translations") or {}
    if not isinstance(tr_in, dict):
        raise ProjectError("'translations' must be an object of id -> {text, state}")
    tr: Dict[str, dict] = {}
    for k, v in tr_in.items():
        if isinstance(v, str):
            v = {"text": v, "state": "draft"}
        if not isinstance(v, dict) or not isinstance(v.get("text"), str):
            raise ProjectError(f"translation {k!r} has no text")
        if v["text"] == "":
            continue
        st = v.get("state") if v.get("state") in STATES else "draft"
        tr[str(k)] = {"text": v["text"], "state": st}
    out = {"format": FORMAT,
           "language": str(project.get("language") or "fr"),
           "retail_id": str(project.get("retail_id") or ""),
           "translations": tr}
    # what the translator reads from (the editor's step 2): {"id": "en-usa"} or
    # {"id": "ja-jp", "path": <a Japanese Episode III ISO>} (txsource); and the
    # name a custom language was given (its target code may be "other")
    src = project.get("source")
    if src is not None:
        if not isinstance(src, dict) or not isinstance(src.get("id", ""), str):
            raise ProjectError("'source' must be an object {\"id\": ..., \"path\": ...}")
        out["source"] = {k: str(src[k]) for k in ("id", "path") if src.get(k)}
    if isinstance(project.get("language_name"), str) and project["language_name"].strip():
        out["language_name"] = project["language_name"].strip()
    tgt = project.get("target")
    if tgt is not None:
        # what the build draws the language with (txtarget.normalise_target:
        # code, kind, script, rtl, font, face, px, align, ...); kept as given
        if not isinstance(tgt, dict):
            raise ProjectError("'target' must be an object (see txtarget.py)")
        from txtarget import normalise_target, TargetError
        try:
            out["target"] = normalise_target(tgt)
        except TargetError as exc:
            raise ProjectError(f"target: {exc}") from None
    return out


def load(path: str) -> dict:
    with open(path, "r", encoding="utf-8", newline="") as fh:
        try:
            data = json.load(fh)
        except json.JSONDecodeError as exc:
            raise ProjectError(f"{path}: not valid JSON ({exc})") from None
    return normalise(data)


def dumps(project: dict) -> str:
    p = normalise(project)
    p["translations"] = dict(sorted(p["translations"].items()))
    return json.dumps(p, ensure_ascii=False, indent=1) + "\n"


def save(path: str, project: dict) -> None:
    """Atomic write: temp file in the same folder, fsync, rename."""
    text = dumps(project)
    dst = Path(path).expanduser()
    dst.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="." + dst.name + ".", suffix=".tmp", dir=str(dst.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, 0o644)        # mkstemp makes 0600; a project is an ordinary document
        os.replace(tmp, dst)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def merge(base: dict, other: dict, overwrite: bool = False) -> Tuple[dict, int]:
    """Copy translations from ``other`` into ``base``; existing entries are
    kept unless ``overwrite``. Returns (new project, number of ids taken)."""
    out = normalise(base)
    n = 0
    for k, v in normalise(other)["translations"].items():
        if overwrite or k not in out["translations"]:
            if out["translations"].get(k) != v:
                out["translations"][k] = dict(v)
                n += 1
    return out, n


# ---------------------------------------------------------------------------
# TSV
# ---------------------------------------------------------------------------

def tsv_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace("\t", "\\t").replace("\n", "\\n").replace("\r", "\\r")


def tsv_unescape(s: str) -> str:
    out, i = [], 0
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s):
            nxt = s[i + 1]
            rep = {"n": "\n", "t": "\t", "\\": "\\", "r": "\r"}.get(nxt)
            if rep is not None:
                out.append(rep)
                i += 2
                continue
        out.append(c)
        i += 1
    return "".join(out)


TSV_HEADER = "id\tsource\ttranslation"


def _unquote_cell(c: str) -> str:
    """Undo spreadsheet quoting: Excel / LibreOffice save a tab-delimited cell
    that contains a double quote as "...", with each inner quote doubled
    (tabs and line breaks are already \\t / \\n here, so a quote is the only
    reason a cell gets quoted). Anything else is left as typed."""
    if len(c) >= 2 and c[0] == '"' and c[-1] == '"':
        inner = c[1:-1]
        if '""' in inner and '"' not in inner.replace('""', ""):
            return inner.replace('""', '"')
    return c


def export_tsv(project: dict, rows: Iterable[dict], only_translated: bool = False) -> str:
    """One line per catalog row (locked rows skipped), header first."""
    tr = normalise(project)["translations"]
    lines = [TSV_HEADER]
    for r in rows:
        if r.get("lock"):
            continue
        t = tr.get(r["id"], {}).get("text", "")
        if only_translated and not t:
            continue
        lines.append("\t".join((r["id"], tsv_escape(r.get("src", "")), tsv_escape(t))))
    return "\n".join(lines) + "\n"


def import_tsv(text: str, project: dict, rows: Optional[Iterable[dict]] = None,
               state: str = "draft") -> Tuple[dict, int, List[str]]:
    """Apply a TSV (id, source, translation) to ``project``.

    Lines with an empty translation are skipped (they do not clear work).
    With ``rows`` given, unknown or locked ids are reported and skipped, and
    a source column that no longer matches the catalog is reported as a
    note but still imported. Returns (project, applied, problems).
    """
    out = normalise(project)
    known = {r["id"]: r for r in rows} if rows is not None else None
    problems: List[str] = []
    n = 0
    for ln, raw in enumerate(text.lstrip("\ufeff").splitlines(), 1):
        if not raw.strip() or (ln == 1 and raw.strip().lower().startswith("id\t")):
            continue
        cols = raw.split("\t")
        if len(cols) < 3:
            problems.append(f"line {ln}: expected 3 tab-separated columns, got {len(cols)}")
            continue
        cols = [_unquote_cell(c) for c in cols]
        rid, src, tr = cols[0].strip(), tsv_unescape(cols[1]), tsv_unescape("\t".join(cols[2:]))
        if not tr:
            continue
        if known is not None:
            row = known.get(rid)
            if row is None:
                problems.append(f"line {ln}: unknown id {rid}")
                continue
            if row.get("lock"):
                problems.append(f"line {ln}: {rid} is locked ({row['lock']})")
                continue
            if src and src != row.get("src", ""):
                problems.append(f"line {ln}: {rid} source differs from the disc (imported anyway)")
        have = out["translations"].get(rid)
        if have and have.get("text") == tr:
            continue                       # the same text: its state (done, flagged…) is kept, nothing to count
        out["translations"][rid] = {"text": tr, "state": state}
        n += 1
    return out, n, problems


# ---------------------------------------------------------------------------
# numbered group-paste blocks
# ---------------------------------------------------------------------------

GROUP_INTRO = ("Translate each numbered line into {lang}. Keep every [number] marker, "
               "every \u23ce symbol and every \u27e6..\u27e7, <...> or $...; code exactly as written. "
               "One numbered line out per numbered line in.")

_MARK_RE = re.compile(r"^\s*[\[\uff3b](\d{1,5})[\]\uff3d]\s?(.*)$")
_NL_RE = re.compile("\u23ce")       # exactly: spaces around it are text (indents, padding)


def format_group(items: List[Tuple[int, str]], language: str = "") -> str:
    """``items`` = [(number, display text)]. Line breaks become ⏎."""
    lines = []
    if language:
        lines += [GROUP_INTRO.format(lang=language), ""]
    for n, text in items:
        lines.append(f"[{n}] " + text.replace("\r\n", "\n").replace("\n", NEWLINE_MARK))
    return "\n".join(lines) + "\n"


def parse_group(text: str) -> Tuple[Dict[int, str], List[str]]:
    """Inverse of format_group. Lines before the first marker are ignored;
    a line without a marker continues the previous block (joined with a
    space, since real line breaks are spelled ⏎). Returns ({n: text}, notes)."""
    out: Dict[int, List[str]] = {}
    notes: List[str] = []
    cur: Optional[int] = None
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        m = _MARK_RE.match(raw)
        if m:
            cur = int(m.group(1))
            if cur in out:
                notes.append(f"[{cur}] appears twice; the last one wins")
            out[cur] = [m.group(2)]
        elif cur is not None and raw.strip():
            out[cur].append(raw.strip())
    res = {}
    for n, parts in out.items():
        joined = " ".join(p for p in parts if p != "") if len(parts) > 1 else parts[0]
        res[n] = _NL_RE.sub("\n", joined)
    return res, notes


# ---------------------------------------------------------------------------
# selftest
# ---------------------------------------------------------------------------

def selftest(iso: Optional[str]) -> int:
    ok = True

    def check(cond, what):
        nonlocal ok
        print(("ok   " if cond else "FAIL ") + what)
        ok = ok and bool(cond)

    tricky = "Ligne 1\tTab \\ «guillemets» ¿qué? ¡sí!\nLigne 2 ⟦0C⟧⟦54⟧ /[label(Shion)]"
    check(tsv_unescape(tsv_escape(tricky)) == tricky, "TSV escape round-trip")
    rows = [{"id": "evt:a", "src": "Hello\nthere", "lock": None},
            {"id": "ovl:b", "src": "Item\tX", "lock": None},
            {"id": "ovl:c", "src": "id", "lock": "identifier"}]
    p = new_project("fr", "x")
    p["translations"]["evt:a"] = {"text": tricky, "state": "done"}
    tsv = export_tsv(p, rows)
    check("ovl:c" not in tsv, "TSV export skips locked rows")
    p2, n, probs = import_tsv(tsv, new_project("fr", "x"), rows)
    check(n == 1 and p2["translations"]["evt:a"]["text"] == tricky and not probs,
          f"TSV import round-trip (n={n}, problems={probs})")
    _, n3, probs3 = import_tsv("evt:zz\ta\tb\novl:c\tid\tident\n", new_project(), rows)
    check(n3 == 0 and len(probs3) == 2, "TSV import rejects unknown + locked ids")
    p4, n4, _ = import_tsv('\ufeffid\tsource\ttranslation\nevt:a\tHello\t"Le ""Club"" U.M.N."\n'
                           'ovl:b\tItem\t"Oui"\n', new_project(), rows)
    check(n4 == 2 and p4["translations"]["evt:a"]["text"] == 'Le "Club" U.M.N.'
          and p4["translations"]["ovl:b"]["text"] == '"Oui"',
          "TSV import undoes spreadsheet quoting and a BOM, keeps a plain quoted text")

    items = [(1, "Bonjour.\nÇa va ?"), (2, "« Oui » ⟦0D⟧"), (3, "Fin")]
    block = format_group(items, "French")
    parsed, notes = parse_group(block)
    check(parsed == dict(items) and not notes, "group format/parse round-trip")
    ws = [(1, "\n  Vector Com., Inc.\n                Vector"), (2, "Air "), (3, "x  \n y")]
    parsed, notes = parse_group(format_group(ws))
    check(parsed == dict(ws), f"group round-trip keeps indents and trailing spaces: {parsed}")
    messy = ("Here you go:\n\n[1] Bonjour.⏎Ça va ?\n[2] « Oui »\n  suite du texte\n"
             "［3］ Fin\n[2] « Oui » ⟦0D⟧\n")
    parsed, notes = parse_group(messy)
    check(parsed == {1: "Bonjour.\nÇa va ?", 2: "« Oui » ⟦0D⟧", 3: "Fin"} and len(notes) == 1,
          f"group parse tolerates preamble, re-wraps, full-width marks, duplicates: {parsed}")

    with tempfile.TemporaryDirectory() as td:
        fp = os.path.join(td, "sub", "p.json")
        save(fp, p)
        check(load(fp) == normalise(p), "project save/load round-trip (atomic write)")
        check(not [f for f in os.listdir(os.path.dirname(fp)) if f.endswith(".tmp")],
              "no temp file left behind")
    m, nm = merge(new_project(), p)
    check(nm == 1 and m["translations"] == p["translations"], "merge")

    if iso:
        import time
        t = time.time()
        rid = retail_id(iso)
        check(re.fullmatch(r"[0-9a-f]{40}", rid) is not None,
              f"retail_id {rid} ({time.time() - t:.2f} s)")
    print("selftest", "passed" if ok else "FAILED")
    return 0 if ok else 1


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("selftest")
    s.add_argument("--iso")
    r = sub.add_parser("retail-id")
    r.add_argument("--iso", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "selftest":
        return selftest(a.iso)
    print(retail_id(a.iso))
    return 0


if __name__ == "__main__":
    sys.exit(main())
