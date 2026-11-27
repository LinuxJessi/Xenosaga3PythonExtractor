"""txserver.py — server side of the translation editor page (/editor, /tx/*).

gui.Handler delegates here before its own routes:

    if txserver.handle_get(self, url.path, url.query): return
    if txserver.handle_post(self, url.path, body_bytes, content_type): return

Both return False for any path that is not ``/editor`` or under ``/tx/``.
They answer through the handler's own ``_send`` / ``_send_json``.

Reads (catalog, checks, previews) run in-process because they are fast
and read-only. Writes go to two places only: the project JSON the
translator picked (atomic temp + rename) and, for Build, gui's existing
``/run/tx-build`` Job which shells out to ``cli.py tx-build`` like every
other card, so the CLI and the GUI keep one code path for ISO writes.

Safety: a per-launch token (``TOKEN``) is baked into the served page and
every POST must carry it in ``X-TX-Token``; requests whose Host header is
not the loopback address are refused, so another web page in the same
browser cannot drive the editor (or overwrite a project) by guessing the
port. Game text is never interpolated into HTML here; the page inserts
it with textContent.

Development: with ``TX_FAKE=1`` in the environment, ``/tx/catalog``
serves a tiny built-in catalog (and ``/tx/check`` / ``/tx/preview`` fall
back to a minimal token checker and plain textpack encoding when txcodec
is not importable), so the page can be exercised before the family
readers exist. Never set it for real work.

    python3 txserver.py selftest [--iso RETAIL]     # headless route test
    PORT=8932 python3 txserver.py serve              # page alone, no gui.py
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets
import sys
import threading
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import parse_qs, quote

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import txproject  # noqa: E402
import txbackup  # noqa: E402

TOKEN = secrets.token_hex(16)
FAKE = os.environ.get("TX_FAKE") == "1"
MAX_BODY = 64 * 1024 * 1024

_LOCK = threading.Lock()
_CATALOGS: Dict[tuple, dict] = {}       # (iso path, mtime) -> catalog + index
_CURRENT: Dict[str, object] = {"iso": None, "key": None}


# ---------------------------------------------------------------------------
# catalog
# ---------------------------------------------------------------------------

FAKE_ROWS = [
    {"id": "sb:cf/us/fake.sb#0001", "fam": "sb", "cat": "Dialogue — scenes", "grp": "1210", "ord": 1,
     "src": "[Shion]<l2>Allen, have you seen\nKOS-MOS anywhere?<f>", "ctx": "Shion",
     "font": "field", "ctl": "us", "measure": "font0", "px": None, "lim": None, "lock": None, "hide": None},
    {"id": "sb:cf/us/fake.sb#0002", "fam": "sb", "cat": "Dialogue — scenes", "grp": "1210", "ord": 2,
     "src": "[Allen]Er... no, Chief.<f>", "ctx": "Allen",
     "font": "field", "ctl": "us", "measure": "font0", "px": None, "lim": None, "lock": None, "hide": None},
    {"id": "sb:cf/us/fake2.sb#0001", "fam": "sb", "cat": "Dialogue — scenes", "grp": "1220", "ord": 1,
     "src": "[Allen]Er... no, Chief.<f>", "ctx": "Allen",
     "font": "field", "ctl": "us", "measure": "font0", "px": None, "lim": None, "lock": None, "hide": None},
    {"id": "sb:cf/us/fake2.sb#0002", "fam": "sb", "cat": "Script identifiers", "grp": "1220", "ord": 2,
     "src": "ce100_045", "ctx": "", "font": "field", "ctl": "us", "measure": None, "px": None,
     "lim": None, "lock": None, "hide": "identifier (a label or voice id the scripts look up by name)"},
    {"id": "mnu:mnu/us/fake.txd#0003", "fam": "mnu", "cat": "Menu text", "grp": "Menus", "ord": 0,
     "src": "⟦0D⟧⟦0A⟧Save data: %d block(s).\nContinue?", "ctx": "",
     "font": "field", "ctl": "us", "measure": "font0", "px": None, "lim": None, "lock": None, "hide": None},
    {"id": "mnu:mnu/us/fake.bin#00.0001", "fam": "mnu", "cat": "Database & menu tables", "grp": "DBC / 00",
     "ord": 0, "src": "$col707070;Zohar", "ctx": "",
     "font": "field", "ctl": "us", "measure": "font0", "px": None, "lim": None, "lock": None, "hide": None},
    {"id": "bat:bat/us/fake.bin#00.0000", "fam": "bat", "cat": "Battle names & descriptions", "grp": "table 00",
     "ord": 0, "src": "Boost", "ctx": "", "font": "field", "ctl": "us", "measure": "font0",
     "px": None, "lim": 12, "lock": None, "hide": None},
    {"id": "mnu:mnu/us/fake.bin#00.0002", "fam": "mnu", "cat": "Database & menu tables", "grp": "DBC / 00",
     "ord": 1, "src": "Reserve", "ctx": "", "font": "field", "ctl": "us", "measure": None,
     "px": None, "lim": 8, "lock": "holds a value pointing into its middle (meaning unknown): it cannot change",
     "hide": None},
    {"id": "sub:mov/us/fake.txt#L3", "fam": "sub", "cat": "Movie subtitles", "grp": "s000300", "ord": 0,
     "src": "KOS-MOS, surrender and become part of me!", "ctx": "00:00:02",
     "font": "field", "ctl": "us", "measure": "font0", "px": None, "lim": None, "lock": None, "hide": None},
] + [
    {"id": f"sb:cf/us/fake3.sb#{i:04d}", "fam": "sb", "cat": "Dialogue — scenes", "grp": "2940",
     "ord": i, "src": f"[KOS-MOS]Line {i}: target acquired.<f>", "ctx": "KOS-MOS", "font": "field",
     "ctl": "us", "measure": "font0", "px": None, "lim": None, "lock": None, "hide": None}
    for i in range(240)
]


def _fake_catalog() -> dict:
    from txcatalog import aggregate, build_tree
    rows = aggregate([[dict(r) for r in FAKE_ROWS]], log=lambda m: None)
    return {"rows": rows, "cats": build_tree(rows), "retail_id": "fake",
            "notes": ["TX_FAKE=1: built-in sample catalog, not the disc"]}


_BUILDING: Dict[tuple, threading.Event] = {}     # catalogs being read: key -> set when done


def _set_stamp(iso: str) -> tuple:
    """(path, size, mtime_ns) of every disc of the set ``iso`` belongs to, Disc 1
    first: what every per-set cache is keyed on, so a partner disc put next to
    it, replaced or taken away is another set (not only a changed ``iso``)."""
    p = str(Path(iso).expanduser().resolve())
    try:
        import txdiscs
        members = txdiscs.pair(p)
    except Exception:                      # noqa: BLE001 - not a disc: the image alone
        members = [p]
    out = []
    for q in members:
        try:
            st = os.stat(q)
            out.append((q, st.st_size, st.st_mtime_ns))
        except OSError:
            out.append((q, -1, -1))
    return tuple(out)


def get_catalog(iso: str) -> dict:
    """Catalog for ``iso``'s disc set, cached in memory per (path, mtime) of
    every disc of the set."""
    if FAKE:
        key = ("<fake>", 0)
    else:
        p = Path(iso).expanduser()
        if not p.is_file():
            raise FileNotFoundError(f"no such ISO: {iso}")
        me = str(p.resolve())
        try:                               # the set: a second disc put next to it, or replaced, is another catalog
            import txdiscs
            members = [str(q) for q in txdiscs.pair(me)] or [me]
        except Exception:                  # noqa: BLE001 - not a disc: build_catalog says so below
            members = [me]
        # keyed by Disc 1 of the set whichever disc was picked: the rows and the
        # retail id cover the whole set, so Disc 1 and Disc 2 are one catalog
        first = members[0] if me in members else me
        key = (first, os.stat(first).st_mtime_ns)
        key += tuple((q, os.stat(q).st_mtime_ns) for q in members if q != first)
    # A cold read takes ~30 s: it runs OUTSIDE _LOCK, so requests about other
    # (cached) sets go on meanwhile; a second request for the same set waits for
    # the first read instead of starting another.
    owner = False
    with _LOCK:
        for old in [k for k in _CATALOGS if k[0] == key[0] and k != key]:
            del _CATALOGS[old]             # the same image as part of another set: superseded
        cat = _CATALOGS.get(key)
        if cat is None:
            ev = _BUILDING.get(key)
            if ev is None:
                ev = _BUILDING[key] = threading.Event()
                owner = True
    if cat is None and not owner:
        # the reader hands its result over on the event itself: the entry may already
        # be gone from _CATALOGS (superseded by another set of the same image)
        if not ev.wait(900):
            raise TimeoutError(f"reading {iso} is taking more than 15 minutes; try again")
        cat, err = getattr(ev, "result", None), getattr(ev, "error", None)
        if cat is None:
            raise err or RuntimeError(f"reading {iso} failed")
    elif cat is None:
        try:
            if FAKE:
                cat = _fake_catalog()
            else:
                import txcatalog
                cat = txcatalog.build_catalog(key[0])
            cat["_index"] = {r["id"]: r for r in cat["rows"]}
            cat["_iso"] = key[0] if not FAKE else iso
            cat["_rev"] = hashlib.sha1(repr(key).encode("utf-8")).hexdigest()[:16]
            with _LOCK:
                _CATALOGS[key] = cat
            ev.result = cat
        except Exception as exc:
            ev.error = exc
            raise
        finally:
            with _LOCK:
                _BUILDING.pop(key, None)
            ev.set()
        if not FAKE:
            threading.Thread(target=_warm_families, args=(key[0],), daemon=True).start()
    with _LOCK:
        _CURRENT["iso"] = key[0] if not FAKE else iso
        _CURRENT["key"] = key
    return cat


def _warm_families(iso: str) -> None:
    """Load the family readers' rows in the background (the catalog may come
    from the disk cache), so the first per-row family check is instant."""
    import importlib
    for name in ("txfam_sb", "txfam_mnu", "txfam_bat", "txfam_sub"):
        try:
            importlib.import_module(name).validate({}, iso)
        except Exception:
            pass
    try:                 # and the length guides (a few seconds over Episode III's 23,000 offered rows)
        _length_guides(iso)
    except Exception:
        pass


def catalog_part_bytes(cat: dict, part: str, gz: bool) -> bytes:
    """JSON bytes of one compact part ("main" = visible rows plus the tree and
    notes, "hidden" = rows hidden by default), built once per catalog and kept
    with it, raw and gzipped."""
    import gzip
    import txcatalog
    with _LOCK:
        cache = cat.setdefault("_wire", {})
        key = (part, gz)
        got = cache.get(key)
        raw = cache.get((part, False))
    if got is not None:
        return got
    # built outside _LOCK (JSON + gzip of ~100k rows takes a while); two requests
    # racing build the same bytes, and the first one stored is kept
    if raw is None:
        payload = txcatalog.compact(cat["rows"], part)
        payload["rev"] = cat.get("_rev", "")      # both parts carry it: the page refuses hidden rows of another read
        if part == "main":
            display = ""
            if cat.get("_iso") and not FAKE:
                try:    # "us" = English text, "jp" = Japanese text: the page names the source after it
                    display = _txcodec().context(str(cat["_iso"])).display
                except Exception:
                    display = ""
            lone = []
            if cat.get("_iso") and not FAKE:
                try:    # a project made while one disc was alone carries that disc's id: it may move to the set
                    import txdiscs
                    lone = txdiscs.lone_ids(str(cat["_iso"]))
                except Exception:
                    lone = []
            payload.update({"cats": cat["cats"], "retail_id": cat.get("retail_id", ""), "retail_lone": lone,
                            "notes": cat.get("notes", []), "fake": FAKE,
                            "total": len(cat["rows"]), "display": display})
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        with _LOCK:
            raw = cache.setdefault((part, False), raw)
    if not gz:
        return raw
    data = gzip.compress(raw, 6)
    with _LOCK:
        return cache.setdefault(key, data)


def _current() -> Optional[dict]:
    """The catalog of a request that names no disc: the ONE catalog this
    server has loaded. With two disc sets open (two tabs on different builds)
    there is no "current" one: the request must name its disc, and is refused
    (LookupError -> 404) rather than answered from the other tab's disc."""
    with _LOCK:
        cats = list(_CATALOGS.values())
    if len(cats) > 1:
        raise LookupError("two disc sets are open in this editor; the request must name its disc (iso)")
    return cats[0] if cats else None


def _rows_for(body: dict) -> dict:
    """Catalog of the request's ``iso`` (the page always sends it), else the
    only one loaded (``_current``). The catalog carries its own image path in
    ``_iso``, so a check never mixes one image's rows with another's fonts."""
    iso = body.get("iso")
    if iso:
        return get_catalog(iso)
    cat = _current()
    if cat is None:
        raise LookupError("no catalog loaded yet; open a retail ISO first")
    return cat


def _was_lone_of(rid: str, cat: dict) -> bool:
    """``rid`` is one disc's own id within ``cat``'s set (a project made while that
    disc was found alone): the same lines, so reading or exporting it is fine."""
    try:
        import txdiscs
        return bool(cat.get("_iso")) and rid in txdiscs.lone_ids(str(cat["_iso"]))
    except Exception:                                       # noqa: BLE001
        return False


def _sole_iso() -> Optional[str]:
    """The image of the ONE catalog this server has loaded (None with none or
    several): what a request that names no disc is about."""
    with _LOCK:
        cats = list(_CATALOGS.values())
    return str(cats[0].get("_iso") or "") or None if len(cats) == 1 else None


def _scope(iso):
    """``with _scope(iso):`` the request's disc for everything that is not
    handed one explicitly (which letters a language lacks, what the codec may
    write). Per thread (txcodec.disc), so requests for different builds never
    see each other's disc; no disc named = no disc (the USA codec rules); a
    named disc that does not exist is refused (FileNotFoundError: a 404)."""
    tc = _txcodec()
    if tc is None or FAKE or not iso or not hasattr(tc, "disc"):
        return _nullctx()
    try:
        found = Path(str(iso)).expanduser().is_file()
    except OSError:
        found = False
    if not found:      # a disc that was named but is gone: say so, not answer with the USA rules
        raise FileNotFoundError(f"no such disc image: {iso} (moved or deleted? choose the disc again)")
    return tc.disc(str(Path(str(iso)).expanduser()))


# ---------------------------------------------------------------------------
# disc detection (the editor's step 1 picker)
# ---------------------------------------------------------------------------

# txproject.retail_id of the untouched Xenosaga Episode III sets: USA Disc 1 + 2 (and
# each disc alone), Japan Disc 1 + 2 (and each alone), the May 2006 prototype
KNOWN_RETAIL_IDS = {"048d1bde644abb4b13b446808083f2f66734302e", "e22e583c46000ff652c2f3fcb4b3fa615fdfcfb2",
                    "bfb5226046c295dfecbe9b831194d25b0668715c", "fa155bdcdf1ab4a2fe7e2e7cda360e5e91ea4818",
                    "e9c8e91e48efc3026d816d5ffddd966f547eb362", "cc23b4a484221f9336eb5cd9f80b225e2962ec9a",
                    "3b106662e2b225755ee3ef242b89bc79e105e108"}
_DISC_INFO: Dict[tuple, dict] = {}


def _disc_info(path: str) -> dict:
    """{"xs1": bool, "rid": str, "build": str} for one .iso, cached per its set's
    (path, size, mtime) stamps: the retail id covers both discs of a pair."""
    os.stat(path)                         # (OSError for a vanished file, as before)
    key = (path,) + _set_stamp(path)
    info = _DISC_INFO.get(key)
    if info is None:
        info = {"xs1": False, "rid": "", "build": ""}   # "xs1": the key name is the Episode I editor's; here = a known Episode III build
        try:
            import txdiscs
            di = txdiscs.info(path)
            if di["ok"]:
                info["xs1"] = True
                info["rid"] = txproject.retail_id(path)
                info["build"] = di.get("build") or ""
        except Exception:
            pass
        _DISC_INFO[key] = info
    return info


def detect_discs() -> List[dict]:
    """Xenosaga Episode III images (any known build, either disc) in the usual
    places, the untouched retail image(s) first: [{"path", "retail": bool}]. Other games and
    discs are left out (gui.detect_isos keeps the first ten .iso of any
    kind, which can push the right disc off its list)."""
    import gui
    cands: list = []
    for root, depth in ((gui.ROOT.parent, 2), (Path.home() / "Downloads", 2),
                        (Path.home() / "Desktop", 3), (Path.home() / "Documents", 3)):
        try:
            if root.is_dir():
                gui._walk_for_isos(root, depth, 400, cands)
        except OSError:
            continue
    out, seen = [], set()
    for p in cands:
        s = str(p)
        if s in seen:
            continue
        seen.add(s)
        try:
            info = _disc_info(s)
        except OSError:
            continue
        if info["xs1"]:
            out.append({"path": s, "retail": info["rid"] in KNOWN_RETAIL_IDS,
                        "build": {"us": "USA", "jp": "Japan", "proto_2006_05": "May 2006 prototype"}.get(info.get("build"), "")})
    out.sort(key=lambda d: not d["retail"])
    return out


# ---------------------------------------------------------------------------
# checks and previews
# ---------------------------------------------------------------------------

_FONTS: Dict[str, dict] = {}


def _txcodec():
    try:
        import txcodec
        return txcodec
    except ImportError:
        if FAKE:
            return None
        raise


def _fonts(iso: str) -> dict:
    tc = _txcodec()
    if tc is not None:
        return tc.load_fonts(iso)
    if iso not in _FONTS:
        from langpack import _load_disc_fonts
        f0, f1 = _load_disc_fonts(iso, None, None)
        _FONTS[iso] = {"font0": f0, "font1": f1}
    return _FONTS[iso]


_FAKE_TOK = re.compile(r"(?:⟦[0-9A-Fa-f]{2}⟧)+|<[^<>\n]{1,40}>|\$[a-z]+[0-9A-Fa-f,+\-]*;|\\(?:\d{1,3}|[A-Za-z])|%[-+0-9.]*[dsxXcb]")


def _fake_check(text: str, row: dict) -> dict:
    errors, warnings = [], []
    a, b = Counter(_FAKE_TOK.findall(row["src"])), Counter(_FAKE_TOK.findall(text))
    if a != b:
        missing = list((a - b).elements())
        extra = list((b - a).elements())
        hard = any(t.startswith(("⟦", "/[")) for t in missing + extra)
        msg = f"protected tokens differ (missing {missing}, extra {extra})"
        (errors if hard else warnings).append(msg)
    nbytes = len(text.encode("utf-8"))
    if row.get("lim") is not None and nbytes > row["lim"]:
        errors.append(f"{nbytes} bytes > limit {row['lim']}")
    return {"ok": not errors, "errors": errors, "warnings": warnings + ["(TX_FAKE check)"],
            "nbytes": nbytes, "px": None}


def _face(row: dict) -> str:
    """Face the row's text is encoded for: the row's ``face`` (every drawn
    Episode III row says font0), otherwise its width face, otherwise font1."""
    f = row.get("face") or row.get("measure")
    return f if f in ("font0", "font1") else "font1"


def check_one(row: dict, text: str, iso: Optional[str], target: Optional[dict] = None) -> dict:
    """One row's checks. ``target`` is the resolved project target
    (``resolve_target_body``); for a target that draws new letters the text
    goes through ``_target_row_check`` first, so the editor refuses what the
    build's glyph plan refuses and the codec sees ordinary glyph codes."""
    if row.get("lock"):
        return {"ok": False, "errors": [f"locked: {row['lock']}"], "warnings": [],
                "nbytes": None, "px": None}
    tc = _txcodec()
    if tc is None:
        return _fake_check(text, row)
    ctx = tc.context(iso) if (iso and not FAKE and hasattr(tc, "context")) else None
    pre_errors: List[str] = []
    pre_warnings: List[str] = []
    checked = text
    glyphs = ""
    if target and target.get("kind", "builtin") != "builtin":
        pre_errors, checked, glyphs, pre_warnings = _target_row_check(row, text, target)
        if checked is None:
            return {"ok": False, "errors": pre_errors, "warnings": pre_warnings,
                    "nbytes": None, "px": None, "glyphs": glyphs}
    measure = None
    if row.get("measure") and iso and not glyphs:
        # new letters have no retail width: the width is known after the build
        try:
            measure = _fonts(iso).get(row["measure"])
        except Exception:
            measure = None
    try:
        with tc.glyph_codes() if glyphs else _nullctx():
            with (tc.disc(ctx) if ctx is not None else _nullctx()):     # this row's disc, whatever the thread had
                res = tc.check(checked, row["src"], row["font"], row["ctl"], limit_bytes=row.get("lim"),
                               measure=measure, width_px=row.get("px"), face=_face(row))
    except Exception as exc:
        return {"ok": False, "errors": [f"checker failed: {type(exc).__name__}: {exc}"],
                "warnings": [], "nbytes": None, "px": None}
    errors = pre_errors + [e for e in res.get("errors", []) if e not in pre_errors]
    warnings = pre_warnings + [w for w in res.get("warnings", []) if w not in pre_warnings]
    if iso and not FAKE and text != row["src"]:
        with tc.glyph_codes() if glyphs else _nullctx():
            fe, fw = _family_rules(row, checked, iso)
        errors += [e for e in fe if e not in errors]
        warnings += [w for w in fw if w not in warnings]
        if any("-byte limit (" in e for e in errors):      # the family says why; drop the codec's bare line
            errors = [e for e in errors if not e.endswith("-byte limit")]
    out = {"ok": not errors, "errors": errors, "warnings": warnings,
           "nbytes": res.get("nbytes"), "px": res.get("px")}
    if glyphs:
        out["glyphs"] = glyphs
    if iso and not FAKE and text != row["src"] and res.get("px_lines"):
        _length_warnings(row, res["px_lines"], iso, out)
    return out


# ---------------------------------------------------------------------------
# length guides: how long the original game's own text of each kind ever gets
# ---------------------------------------------------------------------------
# Most rows have no hard limit (dialogue grows freely on the disc), so nothing
# stops a translation from running past its text box on screen. What can be
# known without booting the game is what retail itself does: per category,
# the widest line and the largest number of lines any original string has.
# A translation past both is flagged (a warning: the box sizes themselves are
# not decoded, so this is a guide, like the px guides).

_LENGTH_GUIDES: Dict[str, Dict[str, dict]] = {}


def _est_lines(px_lines: List[int], width: int) -> int:
    """Lines on screen when each line wider than ``width`` is wrapped."""
    return sum(max(1, -(-w // width)) for w in px_lines)


def _length_guides(iso: str) -> Dict[str, dict]:
    """Per category, over the visible, unlocked field-font rows of ``iso``:
    ``total`` = the longest original string (px of all its lines added up),
    ``lines`` = the most line breaks + 1 in one original string, ``est`` = the
    most lines on screen of one original string once lines wider than the
    row's own px guide are wrapped (rows that have a guide)."""
    key = (str(iso),) + _set_stamp(iso)    # the guides span both discs: either one changing makes new ones
    got = _LENGTH_GUIDES.get(key)
    if got is not None:
        return got
    tc = _txcodec()
    ctx = tc.context(iso) if hasattr(tc, "context") else None
    src_px: Dict[str, List[int]] = {}
    out: Dict[str, dict] = {"": src_px}     # "" = each row's own original, by id
    try:
        fonts = _fonts(iso)
        rows = get_catalog(iso)["rows"]
    except Exception:
        return {}
    for r in rows:
        if r.get("hide") or r.get("lock") or not r.get("measure") or r.get("font") != tc.FIELD:
            continue
        m = fonts.get(r["measure"])
        if m is None:
            continue
        try:
            data = tc.from_display(r["src"], r["font"], r["ctl"], _face(r), keep=r["src"], ctx=ctx)[0] \
                if ctx is not None else tc.from_display(r["src"], r["font"], r["ctl"], _face(r))[0]
        except Exception:
            continue
        pxl = src_px[r["id"]] = _px_lines(tc, m, r, data)
        g = out.setdefault(r["cat"], {"total": 0, "lines": 0, "est": 0})
        g["total"] = max(g["total"], sum(pxl))
        g["lines"] = max(g["lines"], len(pxl))
        if r.get("px"):
            g["est"] = max(g["est"], _est_lines(pxl, int(r["px"])))
    _LENGTH_GUIDES[key] = out
    return out


def _px_lines(tc, m, row: dict, data: bytes) -> List[int]:
    if hasattr(tc, "px_lines"):             # Episode III: the game's line break is not a 0x0A byte
        return tc.px_lines(m, row, data)
    return [m.width_of_bytes(x) for x in data.split(b"\n")]


def _length_warnings(row: dict, px_lines: List[int], iso: str, out: dict) -> None:
    """Adds to a check result: ``len_pct`` (drawn length against the original,
    100 = the same), ``wide`` (a line is past the row's px guide and can be
    wrapped), and a warning when the text is longer than anything the original
    game shows in this category."""
    guides = _length_guides(iso)
    g = guides.get(row.get("cat"))
    if not g:
        return
    src_pxl = guides[""].get(row["id"]) or []
    total, src = sum(px_lines), sum(src_pxl)
    if src:
        out["len_pct"] = round(100 * total / src)
    if row.get("px"):
        width = int(row["px"])
        if max(px_lines) > width and g["lines"] > 1 and _wrap_width(row, iso):
            out["wide"] = True
        est = _est_lines(px_lines, width)
        if est > g["est"] and est > _est_lines(src_pxl or [0], width):
            out["warnings"].append(f"about {est} lines on screen; no original text of this kind takes "
                                   f"more than {g['est']}. It may not fit its box: shorten it, then "
                                   f"look at this screen in the emulator")
    elif total > g["total"] and total > src:
        out["warnings"].append(f"longer than any original text of this kind ({total} px of letters; "
                               f"the longest original has {g['total']}). It may not fit its box: "
                               f"shorten it, then look at this screen in the emulator")


def _wrap_width(row: dict, iso: str) -> Optional[int]:
    if row.get("use") == "choice":         # each line of a choice is an option: never broken by the editor
        return None
    return int(row["px"]) if row.get("px") else None


_GLUE_BEFORE = set("?!:;»”)")          # French spacing: never start a line with these
_WORD_RE = re.compile(r"(?:/\[[^\]\n]*\]|<[^<>\n]{1,40}>|[^ ])+")      # a <k two words> tag is one word


def wrap_text(row: dict, text: str, iso: str, stand_in: str = "") -> str:
    """Break the lines of ``text`` that are wider than the row's width (see
    ``_wrap_width``) at spaces. Lines that fit, and line breaks already there,
    are kept. ``<...>`` tags are never split. Letters in ``stand_in`` (the few a
    script-hybrid target adds to the game font) are measured as "m"."""
    tc = _txcodec()
    width = _wrap_width(row, iso)
    m = _fonts(iso).get(row.get("measure")) if row.get("measure") else None
    if not width or m is None:
        return text

    ctx = tc.context(iso) if hasattr(tc, "context") else None

    def px(line: str) -> int:
        if stand_in:
            line = "".join("m" if c in stand_in else c for c in line)
        data = (tc.from_display(line, row["font"], row["ctl"], _face(row), keep=line, ctx=ctx)[0] if ctx is not None
                else tc.from_display(line, row["font"], row["ctl"], _face(row))[0])
        return m.width_of_bytes(data)

    res = []
    for line in text.split("\n"):
        try:
            if px(line) <= width:
                res.append(line)
                continue
            words = []
            for w in _WORD_RE.findall(line):
                if words and w and all(c in _GLUE_BEFORE for c in w):
                    words[-1] += " " + w
                elif words and words[-1] in ("«", "“", "("):
                    words[-1] += " " + w
                else:
                    words.append(w)
            cur = ""
            for w in words:
                cand = w if not cur else cur + " " + w
                if cur and px(cand) > width:
                    res.append(cur)
                    cur = w
                else:
                    cur = cand
            if cur:
                res.append(cur)
        except ValueError:              # a letter the font lacks: leave the line alone
            res.append(line)
    return "\n".join(res)


class _nullctx:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


# ---------------------------------------------------------------------------
# per-row checks for targets that draw new letters (txtarget)
# ---------------------------------------------------------------------------

_CMAPS: Dict[tuple, Optional[frozenset]] = {}
_CMAP_LOCK = threading.Lock()


def _cmap(path: str, face: int = 0) -> Optional[frozenset]:
    """Code points of one font face (cached per path, face, mtime); None when
    the font cannot be read or fonttools is missing."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    key = (path, int(face), st.st_mtime_ns)
    with _CMAP_LOCK:
        if key in _CMAPS:
            return _CMAPS[key]
    try:
        import txtarget
        cm = txtarget.font_cmap(path, int(face))
        val = frozenset(cm) if cm is not None else None
    except Exception:
        val = None
    with _CMAP_LOCK:
        _CMAPS[key] = val
    return val


def _drawn(c: str) -> bool:
    """A character that needs its own glyph in a font (not a combining mark,
    which the shaper places from its base letter, and not a space)."""
    import unicodedata
    return not c.isspace() and unicodedata.category(c) not in ("Mn", "Me")


def _char_list(chars: str, n: int = 12) -> str:
    import txcodec as tc
    shown = " ".join(chars[:n]) + (" …" if len(chars) > n else "")
    names = ", ".join(tc.char_name(c) for c in chars[:2])
    return f"{shown} ({names}{', ...' if len(chars) > 2 else ''})"


def _target_row_check(row: dict, text: str, t: dict):
    """What the build's glyph plan (txtarget.plan_glyphs / _plan_field /
    _check_font / _encode_with) would refuse for this row, before the codec
    runs. -> (errors, text for the codec with every new letter replaced by a
    glyph code, or None when the codec need not run; the new letters;
    warnings)."""
    import unicodedata
    import txcodec as tc
    import txtarget as tt
    font = row.get("font") or tc.FIELD
    face = _face(row)
    errors: List[str] = []
    warnings: List[str] = []
    cov = tt.coverage(text, t, font, face)
    if font == tc.ASCII:
        if cov["impossible"]:
            errors.append(f"drawn by the tag font (window title ribbons), which has only A-Z a-z 0-9 "
                          f": / . - and space and no room for new letters; {_char_list(cov['impossible'])} "
                          f"cannot be drawn there. Keep this row in Latin letters (transliterate it) "
                          f"or leave it untranslated")
            return errors, None, "", warnings
        return errors, text, "", warnings
    if cov["impossible"]:
        errors.append(f"cannot draw {_char_list(cov['impossible'])}")
    glyph = cov["glyph"]
    if not glyph:
        return errors, text, "", warnings
    battle = font == tc.BATTLE
    fpath = t.get("battle_font") if battle else t.get("font")
    fface = int((t.get("battle_face") if battle else t.get("face")) or 0)
    where = "battle labels" if battle else "dialogue and menus"
    need = "".join(c for c in glyph if _drawn(c))
    if not fpath and not battle and hasattr(tt, "with_font"):
        try:                                   # a few missing Latin letters: the build takes a font itself
            t2 = tt.with_font(t, glyph + (t.get("lacking") or ""))
            fpath, fface = t2.get("font"), int(t2.get("face") or 0)
        except tt.TargetError as exc:
            errors.append(str(exc))
            return errors, None, glyph, warnings
    if not fpath:
        errors.append(f"{_char_list(need or glyph)} must be drawn from a font file for {where}, and "
                      f"none is chosen: pick one in step 2 (Language setup)")
    elif not Path(fpath).is_file():
        errors.append(f"the font file {fpath} does not exist (step 2, Language setup)")
    else:
        cmap = _cmap(fpath, fface)
        if cmap is not None:
            miss = "".join(c for c in need if ord(c) not in cmap)
            if miss:
                errors.append(f"the font {_font_label(fpath, fface)} has no letter for "
                              f"{_char_list(miss)}; pick a font that covers them (step 2)")
    if t.get("rtl") and not battle and hasattr(tt, "_protect") and hasattr(tt, "_rtl_mid_controls"):
        body, saved = tt._protect(unicodedata.normalize("NFC", text), row.get("ctl", "c0"))
        for para in body.split("\n"):
            m = tt._EDGE_RE.match(para)
            bad = tt._rtl_mid_controls(m.group(2), saved) if m else []
            if bad:
                errors.append(f"right-to-left text cannot carry {', '.join(repr(b) for b in bad[:4])} in "
                              f"the middle of a line: the line is reordered word by word for display, "
                              f"so a colour or control code there would end up on other words. Put it "
                              f"at the start or end of the line, or leave it out")
                break
    # every new letter becomes a glyph code, as in a build, so the codec and
    # the family rules see ordinary text (bytes: 2 a letter in the field font,
    # 1 in the battle grid; the build may differ where letters join)
    subs = {}
    for i, c in enumerate(sorted(set(glyph))):
        # stand-in codes B0B0.. with low bytes B0-FD: on the USA build a low byte
        # A1-A4, A6 or AD would pair with the character typed after it
        # (textcodec.us_pair) and the codec would refuse a line the build accepts
        # (seen with a Cherokee caption, 2026-11-21: "A4 20 form a pair")
        subs[c] = tc.glyph_char((0x80 + i % 0x60) if battle else (0xB0B0 + (i // 78) * 0x100 + i % 78))
    checked = "".join(subs.get(c, c) for c in unicodedata.normalize("NFC", text))
    if row.get("lim") is not None:
        warnings.append(f"{len(set(glyph))} new letter(s): the byte count is an estimate until the "
                        f"build places them")
    return errors, checked, glyph, warnings


_FAMILY_MODULES = {"sb": "txfam_sb", "mnu": "txfam_mnu", "bat": "txfam_bat", "sub": "txfam_sub"}


def _family_rules(row: dict, text: str, iso: str):
    """The build's own per-row rules (speaker names, message buffers, choice
    counts, field sizes, shared budgets) plus txfam_ovl's notes on strings
    two printers draw, so the editor says what the build will say.
    -> (errors, warnings)."""
    name = _FAMILY_MODULES.get(row.get("fam") or row["id"].split(":", 1)[0])
    if name is None:
        return [], []
    try:
        import importlib
        mod = importlib.import_module(name)
        warnings: List[str] = []
        if hasattr(mod, "check_row"):          # Episode III: one row on its own (keyword links are a warning)
            errors, warnings = mod.check_row(row["id"], text, iso)
            return list(errors), list(warnings)
        errors = list(mod.validate({row["id"]: text}, iso).get(row["id"], []))
        if hasattr(mod, "warnings") and row.get("font") in ("battle", "ascii"):
            warnings = [w for w in mod.warnings({row["id"]: text}, iso).get(row["id"], [])
                        if "two printers" in w or "tag label" in w]
    except Exception as exc:
        return [f"family check failed: {type(exc).__name__}: {exc}"], []
    return errors, warnings




def _png_urls(pngs) -> List[str]:
    return ["data:image/png;base64," + base64.b64encode(p).decode("ascii") for p in pngs]


def preview_png(row: dict, text: str, iso: str, target: Optional[dict] = None) -> dict:
    """{"pngs": [data URL per line], "png": first, "face": "font0"|"font1"}
    (+ "font_label" when new letters were drawn from the target's font)"""
    if target and target.get("kind", "builtin") != "builtin" and row["font"] == "field":
        import txtarget as tt
        face = _face(row)
        if tt.coverage(text, target, "field", face)["glyph"]:
            if not target.get("font") and hasattr(tt, "with_font"):
                try:
                    target = tt.with_font(target, tt.coverage(text, target, "field", face)["glyph"]
                                          + (target.get("lacking") or ""))
                except tt.TargetError as exc:
                    raise ValueError(str(exc)) from None
            if not target.get("font"):
                raise ValueError("these letters are drawn from a font file: choose one in step 2 "
                                 "(Language setup) to see them")
            ctl = row.get("ctl") or "c0"
            shown = text
            try:
                pngs, _enc = tt.preview(iso, target, shown, "field", face, ctl)
            except tt.TargetError as exc:
                raise ValueError(str(exc)) from None
            urls = _png_urls(pngs)
            return {"pngs": urls, "png": urls[0] if urls else None, "face": face, "warnings": [],
                    "font_label": "preview with " + _font_label(target["font"], target.get("face", 0))}
    if row["font"] == "note":
        raise ValueError("this string is never drawn by the game (a developers' note or a script "
                         "command); no preview")
    face = _face(row)
    tc = _txcodec()
    warnings: List[str] = []
    if tc is not None and hasattr(tc, "context"):
        data, warnings = tc.from_display(text, row["font"], row["ctl"], face, ctx=tc.context(iso))
    elif tc is not None:
        data, warnings = tc.from_display(text, row["font"], row["ctl"], face)
    else:
        from textpack import encode_text
        data = encode_text(text)
    render_line = getattr(tc, "render_line", None)
    if render_line is None:
        from langpack import render_line
    font = _fonts(iso)[face]
    if tc is not None and tc.missing_capital_accents(font, face):
        # the build redraws these capitals (txcodec.fix_capital_accents); show that
        key = f"{iso}|{face}|fixed"
        if key not in _FONTS:
            _FONTS[key] = tc.fix_capital_accents(font, face)
        font = _FONTS[key]
    if tc is not None and tc.needs_metric_fix(text, font, face):
        # the build gives — ‾ _ real metrics when a translation uses them
        font = tc.fix_unmeasured(font, face)
    pngs = []
    for line in (tc.preview_lines(data, row.get("ctl") or "") if hasattr(tc, "preview_lines") else data.split(b"\n")):
        png = render_line(font, line, 2)
        pngs.append("data:image/png;base64," + base64.b64encode(png).decode("ascii"))
    return {"pngs": pngs, "png": pngs[0] if pngs else None, "face": face,
            "warnings": list(warnings)}


# ---------------------------------------------------------------------------
# step 2, Language setup: source text, target language, font, try-it preview
# ---------------------------------------------------------------------------
# Everything here reads; nothing writes. The page keeps the choice in the
# project (project["target"], project["source"], project["language_name"]).
# txtarget is being extended with a language registry (languages(query),
# detect_scripts(text), profile_for_custom(name, sample), capacity(...));
# each is used when present and replaced by a smaller local answer when not.

_PROFILE_KEYS = ("code", "name", "endonym", "kind", "script", "rtl", "alphabet", "lacking",
                 "sample", "fonts", "registry", "ready", "font_auto")


def _clean_profile(p: dict) -> dict:
    out = {k: p.get(k) for k in _PROFILE_KEYS if k in p}
    out.setdefault("code", "")
    out.setdefault("name", out["code"])
    out.setdefault("endonym", "")
    out.setdefault("kind", "builtin")
    out.setdefault("script", "")
    out["rtl"] = bool(out.get("rtl"))
    for k in ("alphabet", "lacking", "sample"):
        out[k] = str(out.get(k) or "")
    out["fonts"] = list(out.get("fonts") or [])
    for k in ("script_name", "aliases", "region", "regions", "speakers", "notes"):
        if p.get(k):
            out[k] = p[k]
    if not out.get("script_name"):
        out["script_name"] = _script_display(out["script"], out["sample"] + out["alphabet"])
    return out


def _script_display(code: str, sample: str = "") -> str:
    """A script's name for people: the registry's when it has one, else the
    Unicode name of the sample's letters (Cherokee, Devanagari, Nko...)."""
    import txtarget as tt
    names = getattr(tt, "SCRIPT_NAMES", None)
    if isinstance(names, dict) and names.get(code):
        return str(names[code])
    found = _scripts_in(sample)
    if found:
        return found[0]["name"]
    return code


_UNAME_RE = re.compile(r"^(.*?) (?:CAPITAL |SMALL )?(?:LETTER|SYLLABLE|CHARACTER|DIGIT|VOWEL|SIGN|"
                       r"MARK|LIGATURE|IDEOGRAPH|NUMBER|CONSONANT|TONE|ABBREVIATION|MEDIAL|COMBINING|"
                       r"FINAL|INITIAL|PUNCTUATION|SUBJOINED|INDEPENDENT|DEPENDENT)\b")


def _scripts_in(text: str) -> List[dict]:
    """[{"name", "count", "letters"}] of the scripts of ``text``'s letters, by
    the Unicode character names (no table): most letters first, Latin last
    unless it is the only one."""
    import unicodedata
    counts: Counter = Counter()
    letters: Dict[str, str] = {}
    for c in dict.fromkeys(text or ""):
        cat = unicodedata.category(c)
        if not (cat.startswith("L") or cat in ("Mn", "Mc", "Nd")) or ord(c) < 0x80 and cat == "Nd":
            continue
        try:
            nm = unicodedata.name(c)
        except ValueError:
            continue
        if nm.startswith("CJK "):
            key = "Han"
        else:
            m = _UNAME_RE.match(nm)
            key = (m.group(1) if m else nm.split()[0]).title()
        n = sum(1 for x in text if x == c)
        counts[key] += n
        letters[key] = letters.get(key, "") + c
    # a name cut short by an unusual character name ("OL CHIKI MU TTUDDAG" -> "Ol")
    # joins the longer name it starts ("Ol Chiki")
    for k in list(counts):
        longer = [o for o in counts if o != k and o.startswith(k + " ")]
        if longer:
            counts[longer[0]] += counts.pop(k)
            letters[longer[0]] += letters.pop(k)
    out = [{"name": k, "count": n, "letters": letters[k]} for k, n in counts.most_common()]
    out.sort(key=lambda d: (d["name"] == "Latin" and len(out) > 1, -d["count"]))
    return out


def list_languages(query: str = "") -> List[dict]:
    """Target languages for the setup list (txtarget.languages when present,
    else TARGETS filtered by English name, endonym or code)."""
    import txtarget as tt
    q = (query or "").strip().lower()
    if hasattr(tt, "languages"):
        try:
            got = tt.languages(query or "")
            return [_clean_profile(p) for p in got if isinstance(p, dict) and p.get("code") != "other"]
        except Exception:
            pass
    out = []
    for p in tt.TARGETS:
        if p["code"] == "other":
            continue
        hay = " ".join((p["code"], p["name"], p.get("endonym", ""))).lower()
        if not q or q in hay:
            out.append(_clean_profile(p))
    return out


def custom_language(name: str, sample: str, code: str = "") -> dict:
    """The kind, scripts and direction of a language the list lacks, from a
    sample sentence (txtarget.profile_for_custom when present)."""
    import unicodedata
    import txcodec as tc
    import txtarget as tt
    sample = unicodedata.normalize("NFC", sample or "")
    scripts = _scripts_in(sample)
    prof = None
    if hasattr(tt, "profile_for_custom"):
        try:
            prof = tt.profile_for_custom(name, sample)
        except Exception:
            prof = None
    if not isinstance(prof, dict):
        iso_script = ""
        if hasattr(tt, "detect_scripts"):
            try:
                ds = tt.detect_scripts(sample)
                if isinstance(ds, dict):
                    ds = sorted(ds.items(), key=lambda kv: -(kv[1] if isinstance(kv[1], (int, float)) else 0))
                for it in ds or []:
                    sc = it.get("script") if isinstance(it, dict) else (it[0] if isinstance(it, (list, tuple)) else it)
                    if sc and sc not in ("Zyyy", "Zinh", "Latn"):
                        iso_script = str(sc)
                        break
                    if sc == "Latn" and not iso_script:
                        iso_script = "Latn"
            except Exception:
                iso_script = ""
        letters = "".join(c for c in dict.fromkeys(sample) if not c.isspace())
        blt = tt.coverage(letters, "builtin")
        scr = tt.coverage(letters, "script")
        names = {d["name"] for d in scripts}
        if names & {"Hiragana", "Katakana"}:
            kind = "japanese"           # kana: the retail fonts' own Japanese, rare kanji drawn
        elif names - {"Latin"}:
            kind = "script"             # any other script: every letter drawn from a font
        elif not blt["impossible"]:
            kind = "builtin"            # Latin letters the accent block already has
        else:
            kind = "script-hybrid"      # Latin with a few letters drawn from a font
        rtl_n = sum(1 for c in sample if unicodedata.bidirectional(c) in ("R", "AL"))
        ltr_n = sum(1 for c in sample if unicodedata.bidirectional(c) == "L")
        prof = {"code": code or "other", "name": name or "My language", "endonym": "", "kind": kind,
                "script": iso_script if iso_script and (iso_script != "Latn" or kind != "script") else "",
                "rtl": rtl_n > ltr_n, "alphabet": "", "sample": sample,
                "lacking": scr["glyph"] if kind != "builtin" else ""}
    prof = _clean_profile(prof)
    if code:
        prof["code"] = code
    if name:
        prof["name"] = name
    prof["sample"] = prof["sample"] or sample
    prof["scripts"] = scripts
    prof["custom"] = True
    if not prof.get("script_name"):
        prof["script_name"] = scripts[0]["name"] if scripts else ""
    elif scripts and prof["script_name"] == prof.get("script"):
        prof["script_name"] = scripts[0]["name"] if scripts[0]["name"] != "Latin" or len(scripts) == 1 \
            else prof["script_name"]
    return prof


def resolve_target_body(t: Optional[dict], language: str = "") -> dict:
    """project["target"] as the page sends it -> txtarget.resolve_target."""
    import txtarget as tt
    t = dict(t or {})
    proj = {"target": {k: v for k, v in t.items() if k in tt._TARGET_KEYS}, "language": language or t.get("code", "")}
    return tt.resolve_target(proj)


def needed_letters(target: dict, extra: str = "") -> str:
    """Letters of the target language (alphabet, sample, the script's probe
    letters, plus ``extra``: the project's own text) that need a glyph."""
    import txtarget as tt
    prof = tt.profile(target.get("code", "")) or {}
    probe = getattr(tt, "_PROBE", {}).get(target.get("script") or prof.get("script") or "", "")
    text = (prof.get("alphabet") or "") + (prof.get("sample") or "") + probe + (target.get("sample") or "") + (extra or "")
    cov = tt.coverage(text, target)
    return "".join(c for c in cov["glyph"] if _drawn(c))


_FONT_ALL: Dict[str, object] = {"ready": False, "faces": None, "thread": None}


def _all_faces() -> List[dict]:
    """Every installed outline face with its cmap (built once, ~3 s)."""
    import txtarget as tt
    with _CMAP_LOCK:
        if _FONT_ALL["faces"] is not None:
            return _FONT_ALL["faces"]
    faces = []
    for f in tt._font_index():
        cm = _cmap(f["path"], f["face"])
        if cm:
            faces.append(dict(f, _cmap=cm))
    with _CMAP_LOCK:
        _FONT_ALL["faces"] = faces
    return faces


def _warm_fonts() -> None:
    """Read every installed font's cmap in the background (once), so the
    font list of the Language setup answers at once."""
    with _CMAP_LOCK:
        if _FONT_ALL["thread"] is not None or FAKE:
            return
        _FONT_ALL["thread"] = threading.Thread(target=lambda: _safe(_all_faces), daemon=True)
        _FONT_ALL["thread"].start()


def _safe(fn):
    try:
        return fn()
    except Exception:
        return None


def _font_label(path: str, face: int = 0) -> str:
    """The font's own family (and style unless Regular), from the installed
    index or the file's name table; the file name as a last resort."""
    try:
        import txtarget as tt
        for f in tt._font_index():
            if f["path"] == path and f["face"] == int(face or 0):
                st = f.get("style") or ""
                return f["family"] + ("" if st.lower() in ("regular", "") else " " + st)
        faces = tt._open_faces(path)
        ft = faces[int(face or 0)]
        fam, st = tt._name(ft, 1), tt._name(ft, 2)
        if fam:
            return fam + ("" if st.lower() in ("regular", "") else " " + st)
    except Exception:
        pass
    return Path(path).name


# Ties between fonts that draw every letter go to plain, widely installed
# sans faces (they stay readable at the game's 20-odd pixel size), and away
# from monospace, typewriter, display and condensed families.
_CLEAR_FAMILIES = ("noto sans", "helvetica neue", "helvetica", "arial", "pt sans", "segoe ui", "dejavu sans",
                   "liberation sans", "open sans", "lucida grande", "verdana", "tahoma", "geneva", "apple sd gothic",
                   "hiragino sans", "pingfang", "kohinoor", "geeza pro", "sf arabic", "arial hebrew", "thonburi",
                   "kefa", "mshtakan", "kailasa")
_ODD_WORDS = ("mono", "typewriter", "courier", "black", "narrow", "condensed", "comic", "chalk", "marker",
              "papyrus", "script", "brush", "stencil", "impact", "trattatello", "herculanum", "zapfino",
              "unicode ms", "symbol", "dings", "webdings", "bodoni", "didot", "rounded")


def rank_fonts(chars: str, prefer: List[str], limit: int = 14) -> List[dict]:
    """Installed faces ranked by how many of ``chars`` they draw; ties go to a
    family named after the language or script (``prefer``), then Noto, then
    Regular styles. -> [{path, face, family, style, label, covers, missing}]"""
    need = [c for c in dict.fromkeys(chars) if _drawn(c)]
    if not need:
        return []
    words = [w.lower() for w in prefer if w and len(w) > 2]
    rows = []
    for f in _all_faces():
        cm = f["_cmap"]
        have = sum(1 for c in need if ord(c) in cm)
        if not have:
            continue
        fam = f["family"] or Path(f["path"]).stem
        named = any(w in (fam + " " + Path(f["path"]).stem).lower().replace(" ", "")
                    or w in fam.lower() for w in [x.replace(" ", "") for x in words] + words)
        low = fam.lower()
        clear = next((i for i, c in enumerate(_CLEAR_FAMILIES) if low.startswith(c)), len(_CLEAR_FAMILIES))
        odd = any(w in low for w in _ODD_WORDS)
        rows.append((-(have / len(need)), "nastaliq" in low,
                     fam.startswith(".") or "lastresort" in low, not named,
                     not f.get("noto"), odd, (f.get("style") or "").lower() not in ("regular", "w3", "book", "roman", ""),
                     clear, low, f["path"], f["face"], f, have))
    rows.sort(key=lambda r: r[:11])
    out, seen = [], set()
    for r in rows:
        f, have = r[11], r[12]
        key = (f["family"], f.get("style"))
        if key in seen:
            continue
        seen.add(key)
        out.append({"path": f["path"], "face": f["face"], "family": f["family"], "style": f.get("style", ""),
                    "label": _font_label(f["path"], f["face"]), "covers": round(have / len(need), 4),
                    "missing": "".join(c for c in need if ord(c) not in f["_cmap"])[:40]})
        if len(out) >= limit:
            break
    return out


def font_info(path: str, chars: str = "") -> dict:
    """Faces of one font file and how much of ``chars`` each draws."""
    import txtarget as tt
    p = Path(path).expanduser()
    if not p.is_file():
        raise FileNotFoundError(f"no font file at {p}")
    if p.suffix.lower() not in (".ttf", ".otf", ".ttc", ".otc"):
        raise ValueError("a font file is .ttf, .otf, .ttc or .otc")
    try:
        faces = tt._open_faces(str(p))
    except ImportError:
        raise ValueError(tt.shaping_available()[1]) from None
    except Exception as exc:
        raise ValueError(f"cannot read the font {p.name}: {exc}") from None
    need = [c for c in dict.fromkeys(chars or "") if _drawn(c)]
    out = []
    for i, ft in enumerate(faces):
        cm = _cmap(str(p), i) or frozenset()
        have = sum(1 for c in need if ord(c) in cm)
        fam, st = tt._name(ft, 1), tt._name(ft, 2)
        out.append({"face": i, "family": fam, "style": st,
                    "label": (fam or p.stem) + ("" if st.lower() in ("regular", "") else " " + st),
                    "covers": round(have / len(need), 4) if need else None,
                    "missing": "".join(c for c in need if ord(c) not in cm)[:40]})
    return {"path": str(p), "faces": out}


def target_preview(iso: str, target_in: dict, text: str, face: str = "font1") -> dict:
    """The Try-it box: ``text`` drawn as the game would after a build, with
    the target's font for the letters the retail font lacks."""
    import txcodec as tc
    import txtarget as tt
    t = resolve_target_body(target_in, target_in.get("code", ""))
    face = face if face in ("font0", "font1") else "font1"
    text = (text or "")[:400]
    ttf = t.get("font") or None
    if ttf and not Path(ttf).is_file():
        return {"error": f"the font file {ttf} does not exist"}
    auto = None
    if not ttf and hasattr(tt, "with_font"):       # a few missing Latin letters: the font the build would take
        try:
            t = tt.with_font(t, tt.coverage(text, t, tc.FIELD, face)["glyph"] + (t.get("lacking") or ""))
            ttf, auto = t.get("font") or None, t.get("font_auto")
        except tt.TargetError:
            pass
    cov = tt.coverage(text, t, tc.FIELD, face, ttf=ttf, ttf_face=t.get("face", 0))
    info = {"native": cov["native"], "glyph": "".join(c for c in cov["glyph"] if _drawn(c)),
            "impossible": cov["impossible"], "missing": cov.get("missing_in_font") or "",
            "kind": t["kind"], "rtl": bool(t.get("rtl")),
            "font_label": (auto["label"] if auto else _font_label(ttf, t.get("face", 0))) if ttf else "",
            "font_auto": bool(auto)}
    if cov["impossible"]:
        what = ("the game font has no letter for it and this language is set up as built in: "
                "choose a language that draws new letters, or \"My language isn't listed\"") \
            if t["kind"] == "builtin" else "no build can draw it"
        return dict(info, error=f"{_char_list(cov['impossible'])}: {what}")
    if info["glyph"] and not ttf:
        return dict(info, error=f"{_char_list(info['glyph'])} are drawn from a font file: choose one "
                                f"below", need_font=True)
    if info["missing"]:
        return dict(info, error=f"{info['font_label']} has no letter for {_char_list(info['missing'])}")
    if not text.strip():
        return dict(info, pngs=[])
    try:
        if t["kind"] == "builtin" or not info["glyph"]:
            ctx = tc.context(iso) if hasattr(tc, "context") else None
            data, _w = tc.from_display(text, tc.FIELD, ctx.display if ctx is not None else "c0", face, ctx=ctx)
            render_line = getattr(tc, "render_line", None)
            if render_line is None:
                from langpack import render_line
            font = _fonts(iso)[face]
            lines = tc.preview_lines(data, "c0") if hasattr(tc, "preview_lines") else data.split(b"\n")
            pngs = [render_line(font, line, 2) for line in lines]
        else:
            pngs, _enc = tt.preview(iso, t, text, tc.FIELD, face, "c0")
    except (tt.TargetError, tc.TxEncodeError, ValueError) as exc:
        return dict(info, error=str(exc))
    return dict(info, pngs=_png_urls(pngs))


def target_capacity(iso: str, target_in: dict, edits: Dict[str, str]) -> Optional[object]:
    """txtarget.capacity(target, rows, edits) when the module has it."""
    import txtarget as tt
    if not hasattr(tt, "capacity"):
        return None
    t = resolve_target_body(target_in, target_in.get("code", ""))
    cat = get_catalog(iso)
    rows = cat["_index"]
    edits = {k: str(v) for k, v in (edits or {}).items() if k in rows and v}
    try:
        return tt.capacity(t, rows, edits)
    except TypeError:
        return tt.capacity(t, {k: rows[k] for k in edits}, edits)


# Japanese source (txsource): aligned once per pair of discs, in a thread so
# the page can show progress; the result stays in memory (and txsource keeps
# its own disk cache, so a relaunch costs ~1 s).
_SOURCE_JOBS: Dict[tuple, dict] = {}


def _source_key(usa: str, src: str) -> tuple:
    """(usa, its set stamp, src, its set stamp): key[0] / key[2] are the two named
    images; the stamps make a partner disc added or replaced on either side
    another alignment (align reads both discs of each side)."""
    a, b = Path(usa).expanduser().resolve(), Path(src).expanduser().resolve()
    return (str(a), _set_stamp(str(a)), str(b), _set_stamp(str(b)))


def source_job(usa: str, src: str) -> dict:
    import txsource
    if not Path(usa).expanduser().is_file():
        raise FileNotFoundError(f"no such ISO: {usa}")
    if not Path(src).expanduser().is_file():
        raise FileNotFoundError(f"no such ISO: {src}")
    key = _source_key(usa, src)
    with _LOCK:
        job = _SOURCE_JOBS.get(key)
        if job is None:
            for k in [k for k, j in _SOURCE_JOBS.items() if k[0] == key[0] and j["state"] != "running"]:
                del _SOURCE_JOBS[k]        # the same image paired with another (or changed) set: superseded
            job = {"state": "running", "log": "starting", "result": None, "error": None, "wire": {}}
            _SOURCE_JOBS[key] = job

            def run():
                try:
                    rows = get_catalog(key[0])["rows"] if not FAKE else None
                    job["log"] = "pairing the two disc sets (about 10 s the first time)"
                    res = txsource.align(key[0], key[2], rows=rows,
                                         log=lambda m: job.__setitem__("log", str(m)[:200]))
                    job["result"] = res
                    job["state"] = "done"
                except Exception as exc:   # SourceError carries a readable message
                    job["error"] = str(exc) if isinstance(exc, ValueError) else f"{type(exc).__name__}: {exc}"
                    job["state"] = "error"
            threading.Thread(target=run, daemon=True).start()
    return job


def source_wire(job: dict, gz: bool) -> bytes:
    """The finished alignment as JSON (gzipped on request), built once per job,
    outside _LOCK."""
    import gzip
    with _LOCK:
        got = job["wire"].get((gz,))
        raw = job["wire"].get((False,))
    if got is not None:
        return got
    if raw is None:
        r = job["result"]
        raw = json.dumps({"state": "done", "source": r.get("source"), "texts": r.get("texts", {}),
                          "partial": r.get("partial", []), "stats": r.get("stats", {}),
                          "by_cat": r.get("by_cat", {}), "notes": r.get("notes", [])},
                         ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        with _LOCK:
            raw = job["wire"].setdefault((False,), raw)
    if not gz:
        return raw
    data = gzip.compress(raw, 6)
    with _LOCK:
        return job["wire"].setdefault((True,), data)


def identify_source(path: str) -> dict:
    import txsource
    p = Path(path).expanduser()
    if not p.is_file():
        return {"kind": None, "ok": False, "message": f"no file at {p}"}
    kind = txsource.identify_disc(str(p))
    msgs = {"jp": (True, "Xenosaga Episode III (Japan, SLPS_256.40/41): the Japanese text is read from it "
                         "(the other Japanese disc is found next to it)"),
            "usa": (False, "this is a USA disc; the Japanese source is the Japanese disc"),
            "proto": (False, "this is the May 2006 prototype (English); the Japanese source is the Japanese disc"),
            None: (False, "not a Xenosaga Episode III disc this editor can read the Japanese from")}
    ok, msg = msgs.get(kind, msgs[None])
    return {"kind": kind, "ok": ok, "message": msg, "path": str(p)}


# ---------------------------------------------------------------------------
# request plumbing
# ---------------------------------------------------------------------------

def _q(query) -> dict:
    if isinstance(query, dict):
        return {k: (v[0] if isinstance(v, list) else v) for k, v in query.items()}
    return {k: v[0] for k, v in parse_qs(query or "", keep_blank_values=True).items()}


def _host_ok(handler) -> bool:
    host = (handler.headers.get("Host") or "").rsplit(":", 1)[0].strip("[]").lower()
    return host in ("127.0.0.1", "localhost", "::1")


def _err(handler, status: int, msg: str) -> bool:
    handler._send_json(status, {"error": msg})
    return True


def page_html() -> str:
    from txeditor_page import EDITOR_HTML
    import txspeakers
    spk = json.dumps(txspeakers.load(), ensure_ascii=False).replace("</", "<\\/")
    html = EDITOR_HTML.replace("__TX_TOKEN__", TOKEN).replace(
        "__TX_FAKE__", "true" if FAKE else "false").replace("__TX_SPEAKERS__", spk)
    if os.environ.get("XS3_EDITOR_ONLY") == "1":    # the stand-alone package: no extractor to go back to
        html = html.replace('<a class="back" href="/">&larr; Extractor cards</a>', '', 1)
    return html


def handle_get(handler, path: str, query) -> bool:
    if path != "/editor" and not path.startswith("/tx/"):
        return False
    if not _host_ok(handler):
        return _err(handler, 403, "editor routes answer on the loopback address only")
    q = _q(query)
    if path == "/editor":
        handler._send(200, page_html(), "text/html; charset=utf-8")
        return True
    try:
        with _scope(q.get("iso") or q.get("usa") or _sole_iso()):   # this request's disc, for this thread only
            return _get_routes(handler, path, q)
    except txproject.ProjectError as exc:
        return _err(handler, 400, str(exc))
    except (FileNotFoundError, LookupError) as exc:
        return _err(handler, 404, str(exc))
    except Exception as exc:
        return _err(handler, 500, f"{type(exc).__name__}: {exc}")


def cache_info() -> dict:
    """Where the editor's cache is and what is in it (txcache.info), plus what
    this server holds in memory."""
    import txcache
    out = txcache.info()
    with _LOCK:
        out["in_memory"] = len(_CATALOGS)
    return out


def _get_routes(handler, path: str, q: dict) -> bool:
    try:
        if path == "/tx/cache":
            handler._send_json(200, cache_info())
            return True
        if path == "/tx/detect":
            handler._send_json(200, {"discs": [] if FAKE else detect_discs()})
            return True
        if path == "/tx/catalog":
            iso = q.get("iso", "")
            if not iso and not FAKE:
                return _err(handler, 400, "missing ?iso=")
            cat = get_catalog(iso)
            part = q.get("part", "main")
            if part == "rows":      # the old list-of-dicts shape, for scripts and debugging
                payload = {k: v for k, v in cat.items() if not k.startswith("_")}
                payload["fake"] = FAKE
                handler._send(200, json.dumps(payload, ensure_ascii=False), "application/json; charset=utf-8")
                return True
            if part not in ("main", "hidden"):
                return _err(handler, 400, "part must be main, hidden or rows")
            gz = "gzip" in (handler.headers.get("Accept-Encoding") or "").lower()
            body = catalog_part_bytes(cat, part, gz)
            headers = {"Vary": "Accept-Encoding"}
            if gz:
                headers["Content-Encoding"] = "gzip"
            handler._send(200, body, "application/json; charset=utf-8", headers)
            return True
        if path == "/tx/project":
            p = q.get("path", "")
            if not p:
                return _err(handler, 400, "missing ?path=")
            fp = Path(p).expanduser()
            if not fp.is_file():
                return _err(handler, 404, f"no project file at {fp}")
            with _PROJECT_LOCK:            # the project and the version a later save names belong together
                payload = {"path": str(fp), "project": txproject.load(str(fp)), "mtime": _mtime(fp)}
            handler._send_json(200, payload)
            return True
        if path == "/tx/languages":
            import txtarget
            _warm_fonts()
            ok, msg = txtarget.shaping_available()
            handler._send_json(200, {"languages": list_languages(q.get("q", "")),
                                     "registry": hasattr(txtarget, "languages"),
                                     "capacity": hasattr(txtarget, "capacity"),
                                     "shaping": {"ok": ok, "message": msg}})
            return True
        if path == "/tx/identify-source":
            handler._send_json(200, identify_source(q.get("path", "")))
            return True
        if path == "/tx/source":
            usa, src = q.get("usa", ""), q.get("src", "")
            if not usa or not src:
                return _err(handler, 400, "missing ?usa= or ?src=")
            job = source_job(usa, src)
            if job["state"] == "running":
                handler._send_json(200, {"state": "running", "log": job["log"]})
            elif job["state"] == "error":
                with _LOCK:      # let the next request try again (another disc, a fixed path)
                    _SOURCE_JOBS.pop(_source_key(usa, src), None)
                handler._send_json(200, {"state": "error", "error": job["error"]})
            else:
                gz = "gzip" in (handler.headers.get("Accept-Encoding") or "").lower()
                headers = {"Vary": "Accept-Encoding"}
                if gz:
                    headers["Content-Encoding"] = "gzip"
                handler._send(200, source_wire(job, gz), "application/json; charset=utf-8", headers)
            return True
        if path == "/tx/export-tsv":
            p = q.get("path", "")
            if not p:
                return _err(handler, 400, "missing ?path=")
            project = txproject.load(str(Path(p).expanduser()))
            cat = get_catalog(q["iso"]) if q.get("iso") else _current()      # (_current refuses when two sets are open)
            if cat is None:
                return _err(handler, 409, "no catalog loaded yet; open a retail ISO first")
            rid, crid = project.get("retail_id") or "", cat.get("retail_id") or ""
            if rid and crid and crid != "fake" and rid != crid and not _was_lone_of(rid, cat):
                return _err(handler, 409, "this project was made for another disc set than the one open: "
                                          "open its own discs to export it")
            text = txproject.export_tsv(project, cat["rows"], only_translated=q.get("only") == "1")
            name = Path(p).stem + ".tsv"
            handler._send(200, text, "text/tab-separated-values; charset=utf-8",
                          {"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"})
            return True
    except txproject.ProjectError as exc:
        return _err(handler, 400, str(exc))
    except (FileNotFoundError, LookupError) as exc:
        return _err(handler, 404, str(exc))
    except Exception as exc:
        return _err(handler, 500, f"{type(exc).__name__}: {exc}")
    return _err(handler, 404, "no such editor route")


_PROJECT_LOCK = threading.Lock()


def _body_target(body: dict) -> Optional[dict]:
    """The resolved target a check / preview request names (``target`` = the
    project's target, ``language`` = its language), or None for the builtin
    path (no target, or one that draws nothing new)."""
    if FAKE or not (body.get("target") or body.get("language")):
        return None
    try:
        t = resolve_target_body(body.get("target"), str(body.get("language") or ""))
    except Exception:
        return None
    return t if t.get("kind", "builtin") != "builtin" else None


def _backups(handler, body: dict) -> bool:
    """POST /tx/backups {path, action, ...}: list | checkpoint (label, project)
    | restore (backup) | copy (dest, project, overwrite). See txbackup."""
    p = str(body.get("path") or "")
    if not p or Path(p).suffix.lower() != ".json":
        return _err(handler, 400, "missing project path (.json)")
    fp = Path(p).expanduser()
    act = str(body.get("action") or "list")
    data = None
    if body.get("project") is not None:
        data = txproject.dumps(txproject.normalise(body["project"])).encode("utf-8")
    try:
        with _PROJECT_LOCK:
            if act == "list":
                pass
            elif act == "checkpoint":
                made = txbackup.checkpoint(str(fp), str(body.get("label") or ""), data)
                handler._send_json(200, {"made": made, "backups": txbackup.list_backups(str(fp)),
                                         "folder": str(txbackup.folder(str(fp)))})
                return True
            elif act == "restore":
                if body.get("mtime") and str(body["mtime"]) != _mtime(fp):
                    return _err(handler, 409, f"{fp.name} changed since this tab last saved it (another tab?): "
                                              f"reopen it, then restore")
                before = txbackup.restore(str(fp), str(body.get("backup") or ""))
                handler._send_json(200, {"before": before, "project": txproject.load(str(fp)),
                                         "mtime": _mtime(fp), "backups": txbackup.list_backups(str(fp)),
                                         "folder": str(txbackup.folder(str(fp)))})
                return True
            elif act == "copy":
                if data is None:
                    data = fp.read_bytes()
                out = txbackup.save_copy(data, str(body.get("dest") or ""), bool(body.get("overwrite")))
                handler._send_json(200, {"copy": out})
                return True
            else:
                return _err(handler, 400, f"unknown action {act!r}")
    except (txbackup.BackupError, txproject.ProjectError) as exc:
        return _err(handler, 422, str(exc))
    except OSError as exc:
        return _err(handler, 500, f"{type(exc).__name__}: {exc}")
    handler._send_json(200, {"backups": txbackup.list_backups(str(fp)), "folder": str(txbackup.folder(str(fp)))})
    return True


def _mtime(fp: Path) -> str:
    """Version stamp of a project file (a string: ns mtimes exceed JS integers)."""
    try:
        return str(fp.stat().st_mtime_ns)
    except OSError:
        return ""


def handle_post(handler, path: str, body_bytes: bytes, content_type: str = "") -> bool:
    if path != "/editor" and not path.startswith("/tx/"):
        return False
    if not _host_ok(handler):
        return _err(handler, 403, "editor routes answer on the loopback address only")
    if not secrets.compare_digest(handler.headers.get("X-TX-Token", ""), TOKEN):
        return _err(handler, 403, "missing or wrong X-TX-Token (reload the editor page)")
    if len(body_bytes or b"") > MAX_BODY:
        return _err(handler, 413, "request too large")
    try:
        body = json.loads((body_bytes or b"{}").decode("utf-8") or "{}")
    except ValueError as exc:
        return _err(handler, 400, f"body must be JSON ({exc})")
    if not isinstance(body, dict):
        return _err(handler, 400, "body must be a JSON object")
    try:
        with _scope(body.get("iso") or _sole_iso()):      # this request's disc, for this thread only
            return _post_routes(handler, path, body)
    except txproject.ProjectError as exc:
        return _err(handler, 400, str(exc))
    except (FileNotFoundError, LookupError) as exc:
        return _err(handler, 404, str(exc))
    except Exception as exc:
        return _err(handler, 500, f"{type(exc).__name__}: {exc}")


def _post_routes(handler, path: str, body: dict) -> bool:
    try:
        if path == "/tx/cache/clear":
            import txcache
            res = txcache.clear()
            res["note"] = ("the files are gone; a disc already open in this window stays in memory until "
                           "the editor is closed")
            handler._send_json(200, res)
            return True
        if path == "/tx/project":
            p = body.get("path") or ""
            if not p:
                return _err(handler, 400, "missing path")
            fp = Path(p).expanduser()
            if fp.suffix.lower() != ".json":
                return _err(handler, 400, "project files must end in .json")
            with _PROJECT_LOCK:
                if body.get("create") and fp.exists():
                    return _err(handler, 409, f"{fp} already exists; open it instead")
                # last-writer-wins would let a second tab (or another program)
                # silently drop translations: a save names the version it
                # started from, and a file changed since then is not replaced
                base = body.get("mtime")
                if not isinstance(body.get("project"), dict):
                    return _err(handler, 400, "missing project")
                if not body.get("create") and base and not fp.exists():
                    handler._send_json(409, {"error": f"{fp.name} was deleted or moved since it was opened here; "
                                                      f"not recreated without asking", "gone": True})
                    return True
                if not body.get("create") and not base and fp.exists():
                    base = ""        # an update that names no version may not replace a file: answer with the file
                if base is not None and fp.exists() and str(base) != _mtime(fp):
                    handler._send_json(409, {
                        "error": f"{fp.name} was changed elsewhere (another editor tab?) since "
                                 f"it was opened here; not overwritten",
                        "conflict": True, "project": txproject.load(str(fp)),
                        "mtime": _mtime(fp)})
                    return True
                project = body["project"]
                if not project.get("retail_id") and body.get("iso") and not FAKE:
                    project["retail_id"] = txproject.retail_id(body["iso"])
                backup, backup_error = None, None
                if not body.get("create") and fp.exists():
                    try:                 # the file as it was, at most every 10 minutes (txbackup)
                        backup = txbackup.auto(str(fp))
                    except OSError as exc:
                        backup_error = f"{type(exc).__name__}: {exc}"
                txproject.save(str(fp), project)
                handler._send_json(200, {"ok": True, "path": str(fp), "backup": backup, "backup_error": backup_error,
                                         "project": txproject.load(str(fp)), "mtime": _mtime(fp)})
            return True
        if path == "/tx/backups":
            return _backups(handler, body)
        if path == "/tx/custom-language":
            handler._send_json(200, custom_language(str(body.get("name", "")), str(body.get("sample", "")),
                                                    str(body.get("code", "") or "")))
            return True
        if path == "/tx/fonts":
            t = resolve_target_body(body.get("target"), str(body.get("language", "")))
            t["sample"] = str((body.get("target") or {}).get("sample", "") or "")
            chars = needed_letters(t, str(body.get("chars", ""))[:20000])
            prefer = [str(x) for x in body.get("prefer") or []] + [t.get("name", "")]
            # the right regional forms of Han characters and the usual system face per script
            sc = str(t.get("script") or "")
            code = str(t.get("code") or "")
            prefer += {"Hans": ["PingFang SC", "Heiti SC"], "Hant": ["PingFang TC", "Heiti TC"],
                       "Kore": ["Apple SD Gothic Neo"], "Jpan": ["Hiragino Sans"]}.get(sc, [])
            if code == "ja":
                prefer += ["Hiragino Sans"]
            elif code.startswith("zh") and not sc:
                prefer += ["PingFang SC" if "Hant" not in code else "PingFang TC"]
            handler._send_json(200, {"chars": chars, "fonts": rank_fonts(chars, prefer)})
            return True
        if path == "/tx/font-info":
            try:
                handler._send_json(200, font_info(str(body.get("path", "")), str(body.get("chars", ""))[:20000]))
            except ValueError as exc:
                return _err(handler, 422, str(exc))
            return True
        if path == "/tx/target-preview":
            iso = body.get("iso") or (_current() or {}).get("_iso")
            if not iso:
                return _err(handler, 409, "choose the disc first (step 1): the preview uses its fonts")
            handler._send_json(200, target_preview(str(iso), body.get("target") or {},
                                                   str(body.get("text", "")), str(body.get("face", "font1"))))
            return True
        if path == "/tx/preflight":
            # the build's own checks over the whole project, nothing written (txbuild.preflight)
            iso = body.get("iso")
            if not isinstance(body.get("project"), dict):
                return _err(handler, 400, "missing project")
            if FAKE or not iso:
                handler._send_json(200, {"ok": True, "errors": {}, "warnings": {}, "edits": 0, "drafts": 0,
                                         "script": False, "notes": ["no disc: nothing to check against"]})
                return True
            import txbuild
            handler._send_json(200, txbuild.preflight(txproject.normalise(body["project"]), str(iso)))
            return True
        if path == "/tx/capacity":
            iso = body.get("iso") or (_current() or {}).get("_iso")
            if not iso:
                return _err(handler, 409, "choose the disc first (step 1)")
            res = target_capacity(str(iso), body.get("target") or {}, body.get("edits") or {})
            handler._send_json(200, {"available": res is not None, "capacity": res})
            return True
        if path == "/tx/check":
            cat = _rows_for(body)
            idx = cat["_index"]
            iso = cat.get("_iso")
            target = _body_target(body)
            out = {}
            for it in body.get("items") or []:
                row = idx.get(it.get("id"))
                if row is None:
                    out[it.get("id")] = {"ok": False, "errors": ["unknown id"], "warnings": [],
                                         "nbytes": None, "px": None}
                    continue
                out[row["id"]] = check_one(row, str(it.get("text", "")), iso, target)
            handler._send_json(200, {"results": out})
            return True
        if path == "/tx/wrap":
            cat = _rows_for(body)
            row = cat["_index"].get(body.get("id"))
            if row is None:
                return _err(handler, 404, "unknown id")
            text = str(body.get("text", ""))
            target = _body_target(body)
            kind = (target or {}).get("kind", "builtin")
            if FAKE or not cat.get("_iso") or kind not in ("builtin", "script-hybrid"):
                handler._send_json(200, {"text": text, "changed": False})
                return True
            # script-hybrid: the few letters the game font lacks are measured as "m" (about as wide
            # as the drawn glyph); a new-script target has no widths to measure with
            stand_in = (target or {}).get("lacking", "") if kind == "script-hybrid" else ""
            new = wrap_text(row, text, str(cat["_iso"]), stand_in)
            handler._send_json(200, {"text": new, "changed": new != text})
            return True
        if path == "/tx/preview":
            cat = _rows_for(body)
            row = cat["_index"].get(body.get("id"))
            if row is None:
                return _err(handler, 404, "unknown id")
            iso = cat.get("_iso")
            if FAKE and not (iso and Path(str(iso)).is_file()):
                return _err(handler, 409, "TX_FAKE: give a real ISO path to render previews")
            try:
                res = preview_png(row, str(body.get("text", "")), str(iso), _body_target(body))
            except ValueError as exc:   # includes txcodec.TxEncodeError
                return _err(handler, 422, str(exc))
            handler._send_json(200, res)
            return True
        if path == "/tx/import-tsv":
            cat = _rows_for(body)
            project, n, problems = txproject.import_tsv(
                str(body.get("tsv", "")), body.get("project") or txproject.new_project(),
                cat["rows"], state=body.get("state") or "draft")
            handler._send_json(200, {"project": project, "applied": n, "problems": problems})
            return True
        if path == "/tx/group":
            op = body.get("op")
            if op == "format":
                items = [(int(n), str(t)) for n, t in body.get("items") or []]
                handler._send_json(200, {"text": txproject.format_group(items, body.get("language", ""))})
                return True
            if op == "parse":
                parsed, notes = txproject.parse_group(str(body.get("text", "")))
                handler._send_json(200, {"items": {str(k): v for k, v in parsed.items()},
                                         "notes": notes})
                return True
            return _err(handler, 400, "op must be 'format' or 'parse'")
    except txproject.ProjectError as exc:
        return _err(handler, 400, str(exc))
    except (FileNotFoundError, LookupError) as exc:
        return _err(handler, 404, str(exc))
    except Exception as exc:
        return _err(handler, 500, f"{type(exc).__name__}: {exc}")
    return _err(handler, 404, "no such editor route")


# ---------------------------------------------------------------------------
# standalone harness (dev + selftest) — mirrors gui.Handler's helpers
# ---------------------------------------------------------------------------

def _make_server(port: int):
    import http.server
    import socketserver
    from urllib.parse import urlparse

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
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

        def do_GET(self):  # noqa: N802
            url = urlparse(self.path)
            if handle_get(self, url.path, url.query):
                return
            if url.path == "/":
                return self._send(302, "", extra_headers={"Location": "/editor"})
            if url.path in ("/detect", "/browse-fs"):
                import gui
                if url.path == "/detect":
                    return self._send_json(200, {"isos": gui.detect_isos(), "default_iso": ""})
                q = _q(url.query)
                return self._send_json(200, gui.list_dir(q.get("path", ""), q.get("filter") or None))
            self._send(404, "not found")

        def do_POST(self):  # noqa: N802
            url = urlparse(self.path)
            n = int(self.headers.get("Content-Length", "0") or 0)
            body = self.rfile.read(n) if n else b""
            if handle_post(self, url.path, body, self.headers.get("Content-Type", "")):
                return
            self._send(404, "not found")

    class S(socketserver.ThreadingMixIn, http.server.HTTPServer):
        daemon_threads = True
        allow_reuse_address = True

    return S(("127.0.0.1", port), H)


def selftest(iso: Optional[str]) -> int:
    """Drive every route through a real socket with urllib."""
    import tempfile
    import urllib.request
    global FAKE
    FAKE = not iso
    with _LOCK:                            # each self-test starts with no disc open in this process
        _CATALOGS.clear()
        _CURRENT.update(iso=None, key=None)
    srv = _make_server(0)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"
    ok = True

    def check(cond, what):
        nonlocal ok
        print(("ok   " if cond else "FAIL ") + what)
        ok = ok and bool(cond)

    def req(method, path, body=None, token=True):
        data = json.dumps(body).encode() if body is not None else None
        r = urllib.request.Request(base + path, data=data, method=method)
        r.add_header("Content-Type", "application/json")
        if token:
            r.add_header("X-TX-Token", TOKEN)
        try:
            with urllib.request.urlopen(r, timeout=600) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    st, raw = req("GET", "/tx/detect")
    check(st == 200 and isinstance(json.loads(raw).get("discs"), list), "GET /tx/detect")
    st, page = req("GET", "/editor")
    check(st == 200 and TOKEN.encode() in page and b"__TX_TOKEN__" not in page, "GET /editor injects token")
    isoq = quote(iso or "fake")
    import gzip
    import time
    from txcatalog import expand
    t0 = time.time()
    st, raw = req("GET", f"/tx/catalog?iso={isoq}")
    cat = json.loads(raw) if st == 200 else {}
    st2, raw2 = req("GET", f"/tx/catalog?iso={isoq}&part=hidden")
    hid = json.loads(raw2) if st2 == 200 else {"n": 0, "col": {}, "dict": {}}
    rows = (expand(cat) if cat.get("n") else []) + (expand(hid) if hid.get("n") else [])
    check(st == 200 and st2 == 200 and rows and len(rows) == cat.get("total"),
          f"GET /tx/catalog main {cat.get('n')} + hidden {hid.get('n')} rows "
          f"({len(raw):,} + {len(raw2):,} B, {time.time() - t0:.2f} s)")
    st, legacy = req("GET", f"/tx/catalog?iso={isoq}&part=rows")
    lrows = json.loads(legacy).get("rows", []) if st == 200 else []
    check(sorted(r["id"] for r in lrows) == sorted(r["id"] for r in rows), "part=rows has the same ids")
    r = urllib.request.Request(base + f"/tx/catalog?iso={isoq}", headers={"Accept-Encoding": "gzip"})
    with urllib.request.urlopen(r, timeout=600) as resp:
        enc, zbody = resp.headers.get("Content-Encoding"), resp.read()
    check(enc == "gzip" and gzip.decompress(zbody) == raw,
          f"gzip when accepted ({len(zbody):,} B)")
    edit = next((r for r in rows if not r["lock"] and not r["hide"] and r["font"] == "field" and r["measure"]),
                rows[0] if rows else None)
    st, _ = req("POST", "/tx/check", {"items": [{"id": edit["id"], "text": "x"}]}, token=False)
    check(st == 403, "POST without token -> 403")
    st, raw = req("POST", "/tx/check", {"items": [{"id": edit["id"], "text": edit["src"]},
                                                 {"id": "nope", "text": "x"}]})
    res = json.loads(raw).get("results", {}) if st == 200 else {}
    check(st == 200 and edit["id"] in res and res["nope"]["ok"] is False, f"POST /tx/check {res.get(edit['id'])}")
    with tempfile.TemporaryDirectory() as td:
        pp = os.path.join(td, "proj (fr).json")
        proj = txproject.new_project("fr", cat.get("retail_id", ""))
        proj["translations"][edit["id"]] = {"text": "Élan « ¿sí? »\nœ", "state": "done"}
        st, _ = req("POST", "/tx/project", {"path": pp, "project": proj})
        st2, raw = req("GET", "/tx/project?path=" + quote(pp))
        check(st == 200 and st2 == 200 and json.loads(raw)["project"]["translations"] == proj["translations"],
              "project save/load")
        st, _ = req("POST", "/tx/project", {"path": pp, "create": True, "project": proj})
        check(st == 409, "create refuses to overwrite")
        # two tabs: B saves from the version it opened after A already saved over it
        m0 = json.loads(raw)["mtime"]
        a = dict(proj, translations={**proj["translations"], "x:a": {"text": "A", "state": "draft"}})
        st, ra = req("POST", "/tx/project", {"path": pp, "project": a, "mtime": m0})
        b = dict(proj, translations={**proj["translations"], "x:b": {"text": "B", "state": "draft"}})
        st2, rb = req("POST", "/tx/project", {"path": pp, "project": b, "mtime": m0})
        on_disk = txproject.load(pp)["translations"]
        check(st == 200 and st2 == 409 and json.loads(rb).get("conflict") and "x:a" in on_disk
              and "x:b" not in on_disk, "a save from a stale version is refused (409), not last-writer-wins")
        st, _ = req("POST", "/tx/project", {"path": pp, "project": b, "mtime": json.loads(ra)["mtime"]})
        check(st == 200, "a save naming the current version goes through")
        st, _ = req("POST", "/tx/project", {"path": pp, "project": b})
        check(st == 409, "an update naming no version does not replace an existing project")
        st, _ = req("POST", "/tx/project", {"path": pp, "mtime": _mtime(Path(pp))})
        check(st == 400, "a save with no project is refused (no blank project written over it)")
        gone = os.path.join(td, "gone (fr).json")
        st, _ = req("POST", "/tx/project", {"path": gone, "project": b, "mtime": "123"})
        check(st == 409 and not os.path.exists(gone), "a project deleted since it was opened is not recreated")
        bad = dict(proj, translations={**proj["translations"], "sb:nope#0001": {"text": "x", "state": "done"}})
        st, raw = req("POST", "/tx/preflight", {"project": bad, "iso": iso})
        pf = json.loads(raw) if st == 200 else {}
        check(st == 200 and (FAKE or (not pf.get("ok") and "sb:nope#0001" in pf.get("errors", {}))),
              f"the whole-project check names a translation the build would refuse ({pf.get('errors')})")
        st, tsv = req("GET", f"/tx/export-tsv?path={quote(pp)}&iso={isoq}")
        st2, raw = req("POST", "/tx/import-tsv", {"tsv": tsv.decode("utf-8"), "project": txproject.new_project("fr")})
        back = json.loads(raw) if st2 == 200 else {}
        check(st == 200 and back.get("applied") == 1 and
              back["project"]["translations"][edit["id"]]["text"] == "Élan « ¿sí? »\nœ",
              f"TSV export/import round-trip ({back.get('problems')})")
    st, raw = req("POST", "/tx/group", {"op": "format", "items": [[1, "a\nb"], [2, "c"]]})
    txt = json.loads(raw)["text"]
    st2, raw = req("POST", "/tx/group", {"op": "parse", "text": "noise\n" + txt})
    check(json.loads(raw)["items"] == {"1": "a\nb", "2": "c"}, "group format/parse")
    if iso:
        # a later catalog load (another tab, another image) must not change what
        # a request that names its image is checked against
        with _LOCK:
            saved = dict(_CURRENT)
            _CATALOGS[("<other>", 0)] = {"rows": [], "_index": {}, "_iso": None}
            _CURRENT["key"], _CURRENT["iso"] = ("<other>", 0), None
        st, raw = req("POST", "/tx/check", {"items": [{"id": edit["id"], "text": edit["src"]}], "iso": iso})
        check(st == 200 and json.loads(raw)["results"][edit["id"]]["ok"],
              "check names its image: another catalog loaded later does not answer it")
        with _LOCK:
            _CURRENT.update(saved)
            del _CATALOGS[("<other>", 0)]
        import txcodec
        usa = txcodec.context(iso).display == "us"
        spk = next(r for r in rows if r["fam"] == "sb" and r["ctx"] and not r["hide"] and not r["lock"]
                   and "<f>" in r["src"] and __import__("txcodec").speaker_of(r["src"]) == r["ctx"])
        cue = next(r for r in rows if r["cat"] == "Movie subtitles" and not r["hide"])
        ctl = next((r for r in rows if not r["hide"] and not r["lock"] and "⟦0D⟧" in r["src"]), None)
        locked = next((r for r in rows if r["lock"]), None)
        note = next((r for r in rows if r["font"] == "note"), None)
        good, foreign = ("¿Señor? ¡Sí!", "Привет") if usa else ("テスト", "é")
        items = [{"id": spk["id"], "text": f"[{spk['ctx']}]{good}<f>"},
                 {"id": edit["id"], "text": foreign},
                 {"id": cue["id"], "text": good + "\n" + good},
                 {"id": spk["id"] + "x", "text": "x"}]
        if ctl:
            items.append({"id": ctl["id"], "text": "no control codes"})
        if locked:
            items.append({"id": locked["id"], "text": "x"})
        st, raw = req("POST", "/tx/check", {"items": items, "iso": iso})
        res = json.loads(raw)["results"]
        check(res[spk["id"]]["ok"] and res[spk["id"]]["px"], f"a dialogue line in the disc's own letters checks OK "
              f"({res[spk['id']]['px']} px, {res[spk['id']]['nbytes']} bytes)")
        check(not res[edit["id"]]["ok"], "letters the disc cannot draw are an error for a builtin language "
              f"({res[edit['id']]['errors'][:1]})")
        check(res[cue["id"]]["ok"], "a two-line subtitle cue checks OK")
        if ctl:
            check(not res[ctl["id"]]["ok"], "dropping a control code is an error")
        if locked:
            check(not res[locked["id"]]["ok"], "a locked string is refused")
        st, raw = req("POST", "/tx/check", {"items": [{"id": spk["id"], "text": f"[{spk['ctx']}]Привет <f>"}],
                                            "iso": iso, "language": "ru",
                                            "target": {"code": "ru", "kind": "script"}})
        r1 = json.loads(raw)["results"][spk["id"]] if st == 200 else {}
        if usa:
            check(not r1.get("ok") and any("font file" in e for e in r1.get("errors", [])),
                  "a new-letter language without a font says to choose one")
        st, raw = req("POST", "/tx/preview", {"id": edit["id"], "text": edit["src"]})
        prv = json.loads(raw) if raw else {}
        check(st == 200 and str(prv.get("png", "")).startswith("data:image/png;base64,"),
              f"POST /tx/preview ({st} {str(prv)[:120]})")
        if note:
            st, raw = req("POST", "/tx/preview", {"id": note["id"], "text": note["src"]})
            check(st == 422, "a developers' note has no preview (never drawn)")
        st, raw = req("GET", "/tx/languages")
        langs = json.loads(raw).get("languages", []) if st == 200 else []
        kinds = {l["code"]: l["kind"] for l in langs}
        check(len(langs) > 300 and (kinds.get("es") == "builtin" if usa else kinds.get("ja") == "builtin"),
              f"GET /tx/languages: {len(langs)} languages, kinds decided for this disc")
        st, raw = req("POST", "/tx/target-preview", {"iso": iso, "target": {"code": "es" if usa else "ja"},
                                                     "text": good})
        tp = json.loads(raw) if st == 200 else {}
        check(tp.get("pngs") and not tp.get("error"), f"POST /tx/target-preview draws a builtin sample ({tp.get('error')})")
        st, raw = req("GET", "/tx/identify-source?path=" + quote(iso))
        check(st == 200 and json.loads(raw).get("kind") in ("usa", "jp", "proto"), "GET /tx/identify-source")
        st, raw = req("GET", "/tx/languages?iso=" + isoq)
        fr = next((l for l in (json.loads(raw).get("languages", []) if st == 200 else []) if l["code"] == "fr"), {})
        check(fr.get("kind") == "script-hybrid" and fr.get("ready") == "auto" and "DejaVu" in str(fr.get("font_auto")),
              f"French on this disc: {len(fr.get('lacking', ''))} letter(s) lacking, added from the kit's font "
              f"with nothing to choose ({fr.get('ready')})")
        st, raw = req("POST", "/tx/check", {"items": [{"id": spk["id"], "text": f"[{spk['ctx']}]Œuvre, cœur<f>"}],
                                            "iso": iso, "language": "fr", "target": {"code": "fr"}})
        r1 = json.loads(raw)["results"][spk["id"]] if st == 200 else {}
        st2, raw2 = req("POST", "/tx/preview", {"id": spk["id"], "text": f"[{spk['ctx']}]Œuvre, cœur<f>", "iso": iso,
                                                "language": "fr", "target": {"code": "fr"}})
        pv = json.loads(raw2) if raw2 else {}
        check(r1.get("ok") and st2 == 200 and str(pv.get("png", "")).startswith("data:image/png")
              and "DejaVu" in str(pv.get("font_label")),
              f"a French line with œ and Œ and no font chosen checks OK and previews ({r1.get('errors')}; {pv.get('font_label')})")
        kwrow = next((r for r in rows if r.get("use") == "keyword" and r["lock"]), None)
        if kwrow:
            st, raw = req("POST", "/tx/check", {"items": [{"id": kwrow["id"], "text": "x"}], "iso": iso})
            r1 = json.loads(raw)["results"][kwrow["id"]]
            check(not r1["ok"] and "keyword" in r1["errors"][0], "a keyword row is locked: it follows its line's <k...> tag")
        wide = next((r for r in rows if r.get("px") and not r["hide"] and not r["lock"] and "<f>" in r["src"]
                     and not r["ctx"]), None) or next((r for r in rows if r.get("px") and not r["hide"]), None)
        if wide:
            long = ("Wort " if usa else "テスト ") * 40
            st, raw = req("POST", "/tx/wrap", {"id": wide["id"], "text": long.strip(), "iso": iso})
            w = json.loads(raw) if st == 200 else {}
            st, raw = req("POST", "/tx/check", {"items": [{"id": wide["id"], "text": w.get("text", "")}], "iso": iso})
            r1 = json.loads(raw)["results"][wide["id"]] if st == 200 else {}
            check(w.get("changed") and "\n" in w.get("text", "") and (r1.get("px") or 9999) <= wide["px"],
                  f"Wrap to fit breaks a long line at the traced box width ({wide['px']} px; widest line now "
                  f"{r1.get('px')} px)")
    st, raw = req("GET", "/tx/cache")
    ci = json.loads(raw) if st == 200 else {}
    st2, _ = req("POST", "/tx/cache/clear", {}, token=False)
    check(st == 200 and ci.get("path") and "bytes" in ci and st2 == 403,
          f"GET /tx/cache says where the cache is ({ci.get('path')}, {ci.get('bytes', 0) / 1e6:.1f} MB); "
          f"clearing needs the token")
    srv.shutdown()
    print("selftest", "passed" if ok else "FAILED")
    return 0 if ok else 1


def selftest_two(usa: str, jp: str, rounds: int = 40) -> int:
    """Two disc sets open in ONE server (two tabs on different builds): every
    request is answered for its own disc, with the requests interleaved."""
    import urllib.request
    import txcodec as tc
    import txtarget as tt
    ok = True

    def check(cond, what):
        nonlocal ok
        print(("ok   " if cond else "FAIL ") + what)
        ok = ok and bool(cond)

    # 1. the scope itself: per thread, restored on exit, also after an exception
    outer = tc.active()                   # (a self-test before this one may have left a disc in this thread)
    tc.set_active(None)
    with tc.disc(usa):
        a_us = tt.profile("es")["kind"]
        with tc.disc(jp):
            a_jp = tt.profile("es")["kind"]
            try:
                with tc.disc(usa):
                    raise RuntimeError("x")
            except RuntimeError:
                pass
            back_jp = tc.active().display
        back_us = tc.active().display
    check((a_us, a_jp, back_jp, back_us, tc.active()) == ("builtin", "script-hybrid", "jp", "us", None),
          "a disc scope nests and comes back, also after an exception; outside any scope there is no disc")
    tc.set_active(outer)
    with tc.disc(usa):
        c0 = tc.from_display("あ", tc.FIELD, "c0", ctx=tc.context(jp))[0]
    check(c0 == tc.from_display("あ", tc.FIELD, "jp", ctx=tc.context(jp))[0],
          "a check handed a disc uses THAT disc's codec, whatever the scope around it")
    gate = threading.Barrier(2)
    seen: Dict[str, object] = {}

    def holder():
        with tc.glyph_codes():
            gate.wait(10)                 # B checks while A's permission is open
            gate.wait(10)

    def other():
        gate.wait(10)
        try:
            tc.from_display(tc.glyph_char(0xB0A1), tc.FIELD, "us")
            seen["leak"] = True
        except tc.TxEncodeError:
            seen["leak"] = False
        gate.wait(10)

    ta, tb = threading.Thread(target=holder), threading.Thread(target=other)
    ta.start(); tb.start(); ta.join(); tb.join()
    check(seen.get("leak") is False, "one thread's permission to write new-letter codes is not another thread's")
    res: Dict[str, List[str]] = {"us": [], "jp": []}
    go = threading.Barrier(2)

    def worker(name, iso, want_es, yes, no):
        for _ in range(rounds):
            with tc.disc(iso):
                try:
                    go.wait(5)            # both threads are now inside their own scope
                except threading.BrokenBarrierError:
                    pass
                k = tt.profile("es")["kind"]
                if k != want_es or not tc.draws_natively(yes) or tc.draws_natively(no) \
                        or tt.coverage(no, "builtin")["impossible"] != no:
                    res[name].append(k)
    ta = threading.Thread(target=worker, args=("us", usa, "builtin", "é", "я"))
    tb = threading.Thread(target=worker, args=("jp", jp, "script-hybrid", "я", "é"))
    ta.start(); tb.start(); ta.join(); tb.join()
    check(not res["us"] and not res["jp"],
          f"{rounds} rounds, two threads inside different discs at the same moment: each gets its own answers "
          f"(é drawn on USA only, я on Japan only) ({len(res['us'])} / {len(res['jp'])} wrong)")

    # 2. the same over HTTP, through the server's own routes
    with _LOCK:
        _CATALOGS.clear()
        _CURRENT.update(iso=None, key=None)
    srv = _make_server(0)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"

    def req(method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        r = urllib.request.Request(base + path, data=data, method=method)
        r.add_header("Content-Type", "application/json")
        r.add_header("X-TX-Token", TOKEN)
        try:
            with urllib.request.urlopen(r, timeout=900) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    try:
        rows = {}
        for name, iso in (("us", usa), ("jp", jp)):
            cat = get_catalog(iso)
            rows[name] = next(r for r in cat["rows"] if r["fam"] == "sb" and r["ctx"] and not r["hide"]
                              and not r["lock"] and "<f>" in r["src"])
        st, raw = req("POST", "/tx/check", {"items": [{"id": rows["us"]["id"], "text": "x"}]})
        check(st == 404 and b"name its disc" in raw,
              "with two disc sets open, a request that names no disc is refused, not answered from the other tab")
        gone = str(Path(usa).with_name("no such disc (deleted).iso"))
        st, raw = req("GET", "/tx/languages?q=es&iso=" + quote(gone))
        check(st == 404 and b"no such disc image" in raw,
              "a request naming a disc that is gone is refused, not answered with the default rules")
        try:
            import txdiscs
            both = txdiscs.pair(usa)
        except Exception:                                       # noqa: BLE001
            both = []
        if len(both) == 2:
            n0 = len(_CATALOGS)
            check(get_catalog(both[1]) is get_catalog(both[0]) and len(_CATALOGS) == n0,
                  "Disc 2 of a set opens the same catalog as Disc 1 (one set, one entry)")
        st, raw = req("GET", "/tx/languages?q=es")
        es = next((l for l in (json.loads(raw).get("languages", []) if st == 200 else []) if l["code"] == "es"), {})
        check(es.get("kind") == "builtin", "the language list asked without a disc gives the documented default "
                                           "(USA rules), not the disc of whichever tab asked last")
        text = {"us": "[A]¿Señor? café<f>", "jp": "[A]Привет　テスト<f>"}
        ref = {}
        for name, iso in (("us", usa), ("jp", jp)):
            st, raw = req("POST", "/tx/preview", {"id": rows[name]["id"], "text": text[name], "iso": iso})
            ref[name] = json.loads(raw).get("pngs") if st == 200 else None
        check(ref["us"] and ref["jp"], "each disc previews a line in its own letters")
        wrong: List[str] = []

        def tab(name, iso, other):
            lang_ok = "builtin" if name == "us" else "script-hybrid"
            for n in range(rounds):
                st, raw = req("POST", "/tx/check", {"iso": iso, "items": [
                    {"id": rows[name]["id"], "text": text[name]}, {"id": rows[name]["id"] + "?", "text": "x"}]})
                r1 = json.loads(raw)["results"][rows[name]["id"]] if st == 200 else {"ok": False}
                st, raw = req("POST", "/tx/check", {"iso": iso, "items": [{"id": rows[name]["id"], "text": text[other]}]})
                r2 = json.loads(raw)["results"][rows[name]["id"]] if st == 200 else {"ok": True}
                if not r1["ok"] or r2["ok"]:
                    wrong.append(f"{name} check {n}")
                if n % 4 == 0:
                    st, raw = req("GET", "/tx/languages?q=es&iso=" + quote(iso))
                    es = next((l for l in json.loads(raw).get("languages", []) if l["code"] == "es"), {})
                    if es.get("kind") != lang_ok:
                        wrong.append(f"{name} languages {n}: {es.get('kind')}")
                    st, raw = req("POST", "/tx/preview", {"id": rows[name]["id"], "text": text[name], "iso": iso})
                    if st != 200 or json.loads(raw).get("pngs") != ref[name]:
                        wrong.append(f"{name} preview {n}")
        ta = threading.Thread(target=tab, args=("us", usa, "jp"))
        tb = threading.Thread(target=tab, args=("jp", jp, "us"))
        ta.start(); tb.start(); ta.join(); tb.join()
        check(not wrong, f"two tabs, {rounds} interleaved rounds of check / languages / preview over HTTP: every "
                         f"answer is for the request's own disc ({wrong[:3]})")
    finally:
        srv.shutdown()
    print("selftest", "passed" if ok else "FAILED")
    return 0 if ok else 1


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("selftest", help="route test (fake catalog unless --iso)")
    s.add_argument("--iso")
    s2 = sub.add_parser("selftest-two", help="two disc sets in one server, requests interleaved")
    s2.add_argument("--usa", required=True)
    s2.add_argument("--jp", required=True)
    sub.add_parser("serve", help="serve /editor alone on $PORT (dev)")
    a = ap.parse_args(argv)
    if a.cmd == "selftest":
        return selftest(a.iso)
    if a.cmd == "selftest-two":
        return selftest_two(a.usa, a.jp)
    port = int(os.environ.get("PORT", "8932"))
    srv = _make_server(port)
    print(f"editor on http://127.0.0.1:{port}/editor  (TX_FAKE={'1' if FAKE else '0'})")
    srv.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
