"""txcatalog.py — every translatable string of the disc, as one catalog.

The translation editor shows one table of rows (schema in the family
modules: id, fam, cat, grp, ord, src, ctx, font, ctl, measure, px, lim,
lock, hide, dup). Each text family has its own reader module:

    txfam_sb    scene scripts: dialogue with its speaker, notes (.sb pools)
    txfam_mnu   menus, synopsis, database and menu tables (.txd, mnu .bin)
    txfam_bat   battle names and descriptions, the HaKox mini-game
    txfam_sub   movie / event subtitles, recap messages (whole text files)

(the four share one reader, ``txfam_core``, built on the kit's ``textpack``.)

This module only aggregates: it calls each family's ``rows(iso)``, keeps
the first row of any duplicated id, counts identical sources (the ``dup``
translation-memory hint) and builds the sidebar tree. A family module that
is missing or fails is skipped with a note, so the editor still opens with
whatever is available.

The result is cached through ``txcache`` (one gzip file per disc set in the
platform's cache folder, or ``$XS3_TX_CACHE``; bounded and pruned there). The
key is ``content_id``: the retail id (txproject.retail_id: the disc set's
executables and indexes) hashed with the bytes of every text object and both
fonts, so even a copy patched in place at the same sizes has its own entry;
plus a hash of the code of every module the rows come from, so
editing a reader, adding one, or upgrading a frozen release makes a new entry
and the old one is pruned. Nothing else is written; the ISO is only read.

    python3 txcatalog.py selftest --iso RETAIL
    python3 txcatalog.py dump --iso RETAIL --out catalog.json
"""
from __future__ import annotations

import importlib
import json
import os
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path
from typing import Callable, Dict, List, Optional

ROOT = Path(__file__).resolve().parent
FAMILIES = ("txfam_sb", "txfam_mnu", "txfam_bat", "txfam_sub")
CACHE_VERSION = 4                    # 4: txcache entries, rows by code use (3: deterministic stamps)

REQUIRED = ("id", "fam", "cat", "grp", "src")
DEFAULTS = {"ord": 0, "ctx": "", "font": "field", "ctl": "c0", "measure": None,
            "px": None, "lim": None, "lock": None, "hide": None, "use": ""}


def _log_stderr(msg: str) -> None:
    print(f"[txcatalog] {msg}", file=sys.stderr)


STAMPED = FAMILIES + ("txfam_core", "txcatalog", "txcodec", "txdiscs", "textpack", "textcodec", "sb", "txd",
                      "njbin", "msgdat", "batdat", "subtitle", "region", "font", "dialogue", "sbvm", "sbnatives")


def stamp_digest() -> str:
    """One hash over ``_family_stamp`` and the cache version (the cache entry's stamp)."""
    import hashlib
    return hashlib.sha1(json.dumps([CACHE_VERSION, _family_stamp()]).encode()).hexdigest()[:16]


def _family_stamp() -> List[list]:
    """(module, hash of its code) for every module the rows come from: the
    source file when there is one, else (a frozen build ships only
    bytecode) a deterministic digest of the code object, so a new release
    invalidates the cache too. (``marshal.dumps`` of a code object is not
    stable across processes, so it is never used here.)"""
    import hashlib
    import importlib.util
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    out = []
    for name in STAMPED:
        digest = None
        try:
            spec = importlib.util.find_spec(name)
            origin = getattr(spec, "origin", None) if spec is not None else None
            if origin and origin.endswith(".py") and os.path.isfile(origin):
                digest = hashlib.sha1(Path(origin).read_bytes()).hexdigest()[:16]
            elif spec is not None and spec.loader is not None:
                code = spec.loader.get_code(name)
                if code is not None:
                    digest = _code_digest(code).hex()[:16]
        except Exception:
            digest = None
        out.append([name, digest])
    return out


def _code_digest(code) -> bytes:
    """Deterministic digest of a code object: bytecode, names and constants,
    recursively, with set constants sorted (txsource uses the same)."""
    import hashlib
    h = hashlib.sha1()

    def walk(c):
        h.update(c.co_code)
        h.update(repr((c.co_names, c.co_varnames, c.co_argcount)).encode())
        for k in c.co_consts:
            if hasattr(k, "co_code"):
                walk(k)
            elif isinstance(k, frozenset):
                h.update(repr(sorted(repr(x) for x in k)).encode())
            else:
                h.update(repr(k).encode())

    walk(code)
    return h.digest()


def build_tree(rows: List[dict]) -> List[dict]:
    """[{cat, n, groups: [{grp, n}]}] in first-appearance order."""
    cats: Dict[str, Dict[str, int]] = {}
    for r in rows:
        g = cats.setdefault(r["cat"], {})
        g[r["grp"]] = g.get(r["grp"], 0) + 1
    return [{"cat": c, "n": sum(g.values()),
             "groups": [{"grp": k, "n": v} for k, v in g.items()]}
            for c, g in cats.items()]


def aggregate(per_family: List[List[dict]], log: Callable[[str], None] = _log_stderr) -> List[dict]:
    rows: List[dict] = []
    seen = set()
    dups = 0
    for fam_rows in per_family:
        for r in fam_rows:
            missing = [k for k in REQUIRED if k not in r]
            if missing:
                log(f"row without {missing}: {str(r)[:120]}")
                continue
            if r["id"] in seen:
                dups += 1
                continue
            seen.add(r["id"])
            row = dict(DEFAULTS)
            row.update(r)
            rows.append(row)
    if dups:
        log(f"{dups} rows had an id already used by an earlier row (kept the first)")
    counts = Counter(r["src"] for r in rows)
    for r in rows:
        r["dup"] = counts[r["src"]] - 1
    return rows


def _collect(iso_path: str, log) -> tuple:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    per, notes, complete = [], [], True
    for name in FAMILIES:
        try:
            mod = importlib.import_module(name)
        except ImportError as exc:
            if getattr(exc, "name", None) == name:
                notes.append(f"{name}: not installed yet, skipped")
            else:
                notes.append(f"{name}: import failed ({exc}), skipped")
                complete = False
            log(notes[-1])
            continue
        t = time.time()
        try:
            fam = list(mod.rows(iso_path))
        except Exception as exc:  # a broken reader must not take the editor down
            notes.append(f"{name}: rows() failed ({type(exc).__name__}: {exc}), skipped")
            log(notes[-1])
            complete = False
            continue
        log(f"{name}: {len(fam)} rows in {time.time() - t:.1f} s")
        per.append(fam)
    return per, notes, complete


def content_id(iso_path: str) -> str:
    """sha1 over the retail id AND the bytes of every text object and both
    fonts of the disc set: the key the catalog is cached under.

    The retail id alone (executables and indexes) does not see a same-length
    replacement written in place: a patched copy whose text changed without
    moving anything has the retail set's id. Its text does differ, so this
    hash does; reading the 900-odd objects takes about a second, the parsing
    the cache saves takes thirty."""
    import hashlib
    import region as regionmod
    import textpack
    import txdiscs
    from txproject import retail_id
    h = hashlib.sha1(retail_id(iso_path).encode())
    srcs = [textpack.DiscSource(p) for p in txdiscs.pair(iso_path)]
    try:
        reg = srcs[0].region
        for di, s in enumerate(srcs):
            paths = [p for _c, p in s.chained()]
            names = sorted(textpack._norm(p) for p, _k in textpack.collect(paths, reg))
            by = {textpack._norm(p): p for p in paths}
            for k in (0, 1):
                fp = regionmod.resolve(s.disc, f"mnu\\xx\\font{k}.bin", reg)
                if fp:
                    names.append(textpack._norm(fp))
                    by[textpack._norm(fp)] = fp
            for n in names:
                data = s.read(by[n])
                h.update(f"{di}\0{n}\0{len(data)}\0".encode())
                h.update(data)
    finally:
        for s in srcs:
            s.close()
    return h.hexdigest()


def build_catalog(iso_path: str, use_cache: bool = True,
                  log: Callable[[str], None] = _log_stderr) -> dict:
    """{"rows": [...], "cats": [...], "retail_id": str, "notes": [str]}

    ``use_cache`` off: the cache is neither read nor written."""
    import txcache
    from txproject import retail_id
    rid = retail_id(iso_path)
    stamp = stamp_digest()
    key = content_id(iso_path) if use_cache else rid
    if use_cache:
        data = txcache.load("catalog", key, stamp)
        try:
            if data is not None:
                return {"rows": data["rows"], "cats": data["cats"], "retail_id": rid,
                        "notes": list(data.get("notes", [])) + ["(from cache)"]}
        except (KeyError, TypeError):
            pass
    per, notes, complete = _collect(iso_path, log)
    isos: List[str] = []
    try:                                   # which discs the rows cover (Disc 1 + Disc 2, or one)
        import txdiscs
        notes.insert(0, txdiscs.describe(iso_path))
        isos = txdiscs.pair(iso_path)
    except Exception:
        pass
    try:                                   # scripts whose code could not be read (sorted by shape)
        import txfam_core
        notes.extend(txfam_core.load(iso_path).notes)
    except Exception:
        pass
    rows = aggregate(per, log)
    cats = build_tree(rows)
    if complete and rows and use_cache:
        txcache.store("catalog", key, {"notes": notes, "rows": rows, "cats": cats}, stamp,
                      avoid=[str(Path(p).parent) for p in isos])
    return {"rows": rows, "cats": cats, "retail_id": rid, "notes": notes}


# ---------------------------------------------------------------------------
# compact wire form for the editor page
#
# The full catalog is ~56k rows and ~20 MB as a list of dicts, mostly repeated
# keys and repeated short values; three quarters of the rows are hidden by
# default (debug prints, Japanese developer text, identifiers). The page gets
# column arrays instead: low-cardinality fields become an index into a per-field
# table (``dict``), the rest stay plain arrays, and the rows are split in two
# parts so the hidden ones are only sent when the translator asks for them.
# ``expand`` turns one part back into row dicts (used by the selftests).

COMPACT_VERSION = 3                  # 3: + use (what a script's code does with the string)
DICT_FIELDS = ("fam", "cat", "grp", "ctx", "font", "ctl", "measure", "face", "lock", "hide", "use")
PLAIN_FIELDS = ("id", "src", "ord", "px", "lim", "dup")


def compact(rows: List[dict], part: str = "main") -> dict:
    """One part of the catalog as column arrays.

    part "main" = rows with no ``hide`` reason, "hidden" = the others, "all" =
    every row. ``ix`` is each row's position in the full catalog so the page can
    keep the original order after merging the two parts."""
    if part not in ("main", "hidden", "all"):
        raise ValueError(f"part must be main, hidden or all, not {part!r}")
    sel = [(i, r) for i, r in enumerate(rows)
           if part == "all" or (part == "main") == (not r.get("hide"))]
    tables: Dict[str, list] = {f: [] for f in DICT_FIELDS}
    lookup: Dict[str, dict] = {f: {} for f in DICT_FIELDS}
    col: Dict[str, list] = {f: [] for f in DICT_FIELDS + PLAIN_FIELDS}
    col["ix"] = []
    for i, r in sel:
        col["ix"].append(i)
        for f in DICT_FIELDS:
            v = r.get(f)
            k = lookup[f].get(v)
            if k is None:
                k = lookup[f][v] = len(tables[f])
                tables[f].append(v)
            col[f].append(k)
        for f in PLAIN_FIELDS:
            col[f].append(r.get(f, DEFAULTS.get(f)))
    return {"v": COMPACT_VERSION, "part": part, "n": len(sel), "dict": tables, "col": col}


def expand(part: dict) -> List[dict]:
    """Inverse of ``compact`` (fields absent from the source row come back as None)."""
    col, tables = part["col"], part["dict"]
    out = []
    for j in range(part["n"]):
        r = {f: tables[f][col[f][j]] for f in DICT_FIELDS}
        for f in PLAIN_FIELDS:
            r[f] = col[f][j]
        out.append(r)
    return out


# ---------------------------------------------------------------------------

def selftest(iso: str) -> int:
    ok = True

    def check(cond, what):
        nonlocal ok
        print(("ok   " if cond else "FAIL ") + what)
        ok = ok and bool(cond)

    fake = [[{"id": "a:1", "fam": "evt", "cat": "C1", "grp": "G1", "src": "Hi"},
             {"id": "a:2", "fam": "evt", "cat": "C1", "grp": "G2", "src": "Hi"}],
            [{"id": "a:1", "fam": "ovl", "cat": "C2", "grp": "G3", "src": "dup id"},
             {"id": "b:1", "fam": "ovl", "cat": "C2", "grp": "G3", "src": "Yo", "lim": 4}]]
    rows = aggregate(fake, log=lambda m: None)
    check([r["id"] for r in rows] == ["a:1", "a:2", "b:1"], "duplicate id keeps the first row")
    check([r["dup"] for r in rows] == [1, 1, 0], "dup counts")
    check(rows[0]["lock"] is None and rows[2]["lim"] == 4, "defaults filled, values kept")
    tree = build_tree(rows)
    check(tree == [{"cat": "C1", "n": 2, "groups": [{"grp": "G1", "n": 1}, {"grp": "G2", "n": 1}]},
                   {"cat": "C2", "n": 1, "groups": [{"grp": "G3", "n": 1}]}], "cats tree")
    rows[1]["hide"] = "debug print"
    main_p, hid_p = compact(rows, "main"), compact(rows, "hidden")
    check(main_p["col"]["ix"] == [0, 2] and hid_p["col"]["ix"] == [1], "compact splits main/hidden")
    back = expand(main_p) + expand(hid_p)
    check(all({k: r.get(k) for k in DICT_FIELDS + PLAIN_FIELDS} == b for r, b in
              zip([rows[0], rows[2], rows[1]], back)), "compact/expand round-trip")
    if iso:
        t = time.time()
        cat = build_catalog(iso, use_cache=False, log=print)
        n = len(cat["rows"])
        print(f"     {n} rows, {len(cat['cats'])} categories in {time.time() - t:.1f} s; notes: {cat['notes']}")
        check(len({r['id'] for r in cat["rows"]}) == n, "ids unique in the real catalog")
        check(sum(c["n"] for c in cat["cats"]) == n, "tree counts add up")
        t = time.time()
        parts = [compact(cat["rows"], p) for p in ("main", "hidden")]
        sizes = [len(json.dumps(p, ensure_ascii=False, separators=(",", ":")).encode()) for p in parts]
        full = len(json.dumps(cat["rows"], ensure_ascii=False).encode())
        print(f"     compact: main {parts[0]['n']} rows {sizes[0]:,} B, hidden {parts[1]['n']} rows "
              f"{sizes[1]:,} B (full list of dicts {full:,} B) in {time.time() - t:.2f} s")
        merged = {r["id"]: r for p in parts for r in expand(p)}
        check(len(merged) == n and all(
            {k: r.get(k) for k in DICT_FIELDS + PLAIN_FIELDS} == merged[r["id"]] for r in cat["rows"]),
            "compact/expand round-trip on the real catalog")
    print("selftest", "passed" if ok else "FAILED")
    return 0 if ok else 1


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("selftest")
    s.add_argument("--iso")
    d = sub.add_parser("dump")
    d.add_argument("--iso", required=True)
    d.add_argument("--out", required=True)
    d.add_argument("--no-cache", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "selftest":
        return selftest(a.iso)
    cat = build_catalog(a.iso, use_cache=not a.no_cache, log=print)
    Path(a.out).write_text(json.dumps(cat, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(cat['rows'])} rows -> {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
