"""txsource.py — show the Japanese original next to each USA string (Episode III).

The translation editor's rows are keyed to the disc set the project was
started from. For a project on the USA discs, a translator who reads Japanese
is better served by the line the writers wrote, so this module finds, for
every USA catalog row it can, the matching string on the Japanese Episode III
discs (SLPS_256.40 / SLPS_256.41). Nothing is written to any disc; the result
is a ``{row id: Japanese text}`` map the editor shows as the "original".

Public API (the Episode I module's, same shapes)::

    sources(iso) -> [{"id": "en-usa", ...}, {"id": "ja-jp", ..., "needs": ...}]
    identify_disc(path) -> "usa" | "jp" | "proto" | None
    align(usa_iso, source_iso, rows=None, log=print, use_cache=True) -> {
        "source": "ja-jp" | "en-usa",
        "texts": {row_id: display text}, "partial": [row_id, ...],
        "stats": {family: counts}, "by_cat": {category: counts},
        "detail": {family: {aligner counter: n}}, "notes": [str, ...]}
    class SourceError(ValueError)

Either disc of each set may be given: ``txdiscs.pair`` finds the other one,
and both sets are read whole (a set of one disc lacks the other disc's movie
subtitles on that side).

How each kind is paired. The methods are ``align.py``'s (``align-export``),
applied to the editor's rows; nothing here guesses beyond them:

* **scene scripts (.sb)**, same file name on both builds. When the two pools
  have the same number of strings they are paired index for index (567
  files). Otherwise the strings are aligned on their identifiers and
  speakers (``align.align_items``, ``difflib`` over identifier text and the
  speaker learned from the index-paired files); strings it leaves unpaired
  get no Japanese.
* **menu text (.txd)**: index for index (the two Japan-only menutext
  strings have no USA row).
* **containers with the same keys on both builds** (batdat.bin,
  njBtlText.bin, SegmentFileData.bin, the .mes recap messages): key for key.
  A database whose key list differs between the builds (DBC.bin, DBC2.bin,
  MVtext.bin, njDataText.bin, njDBcommon.bin: the entries are sorted by
  their names, so the order differs; Message.Dat: 933 against 871) is NOT
  paired: those rows show the English only.
* **movie and event subtitles**: by time overlap, as ``align-export`` does
  (the two builds were timed independently). A USA cue gets the Japanese
  cue(s) that overlap it; it is marked ``partial`` when that Japanese text is
  shared with another USA cue or made of several cues.

Rows of the catalog that hold the same bytes on both builds (director
scripts, files left in Japanese) pair with themselves and are not counted
as a translation source.

The result is cached through ``txcache`` (``source-<hash>.json.gz``; both
sets' retail ids, this module's and the readers' code, the row list).

    python3 txsource.py selftest --usa DISC [--source JPDISC]
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import tempfile
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import txcodec as tc  # noqa: E402
import txdiscs  # noqa: E402

VERSION = 1
SRC_EN = "en-usa"
SRC_JA = "ja-jp"
FPS = 30
LAST_CUE = 5 * FPS


class SourceError(ValueError):
    """The source disc cannot be used (wrong disc, unsupported, unreadable)."""


def _log_null(msg: str) -> None:
    pass


def identify_disc(path: str) -> Optional[str]:
    """"usa" | "jp" | "proto" | None. Never raises for a bad path."""
    try:
        i = txdiscs.info(path)
    except Exception:
        return None
    if not i["ok"]:
        return None
    return {"us": "usa", "jp": "jp", "proto_2006_05": "proto"}.get(i["build"])


def sources(iso_path_usa: Optional[str] = None) -> List[dict]:
    return [{"id": SRC_EN, "label": "English (USA discs)"},
            {"id": SRC_JA, "label": "Japanese (Xenosaga Episode III, Japan discs)",
             "needs": "path to either Japanese disc image"}]


# ---------------------------------------------------------------------------
# pairing
# ---------------------------------------------------------------------------

def _common(path: str, lang: str) -> str:
    """'cf\\us\\1210.sb' -> 'cf\\xx\\1210.sb' (the name both builds share)."""
    p = path.replace("/", "\\").lower().split("\\")
    return "\\".join("xx" if x == lang else x for x in p)


def _by_common(state) -> Dict[str, object]:
    return {_common(o.path, state.region.lang): o for o in state.objs.values()}


_TIME_RE = re.compile(r"^(\+)?(?:(\d+):(\d+):(\d+)|(\d+))$")


def _cue_times(state, obj) -> List[Tuple[int, int, str, str]]:
    """(start frame, end frame, row key, display text) of each cue row of a
    subtitle file; the time rules are align.parse_cues'."""
    import txfam_core as core
    starts: List[Tuple[int, int, str]] = []
    prev = 0
    for i, (body, _e) in enumerate(obj.lines):
        if not body or body.startswith(";") or body[:1] not in "+0123456789":
            continue
        m = re.match(r"^(\S+)[ \t]*(.*)$", body)
        tm = _TIME_RE.match(m.group(1))
        if not tm:
            continue
        f = int(tm.group(5)) if tm.group(5) is not None else \
            (int(tm.group(2)) * 60 + int(tm.group(3))) * FPS + int(tm.group(4))
        if tm.group(1):
            f += prev
        prev = f
        starts.append((f, i, m.group(2).rstrip()))
    out = []
    for k, (f, i, body) in enumerate(starts):
        if not body or (f == 0 and body.startswith("$")):
            continue
        end = starts[k + 1][0] if k + 1 < len(starts) else f + LAST_CUE
        rid = core.row_id("sub", obj.path, f"L{i}")
        if rid in state.by_id:
            out.append((f, max(end, f + 1), rid, state.by_id[rid]["src"]))
    return out


def _pair(us, jp, log) -> Tuple[Dict[str, str], List[str], Dict[str, Counter]]:
    import align as alignmod
    import textpack
    texts: Dict[str, str] = {}
    partial: List[str] = []
    detail: Dict[str, Counter] = defaultdict(Counter)
    ju, jj = _by_common(us), _by_common(jp)
    kinds = textpack.KINDS

    def items(state, obj):
        return kinds[obj.kind].items(obj.path, obj.data, state.region)

    def put(fam, obj_u, key, raw, codec):
        import txfam_core as core
        rid = core.row_id(fam, obj_u.path, key)
        if rid in us.by_id:
            texts[rid] = tc.to_display(raw, codec)

    # scene scripts
    pools = []
    for name in sorted(ju):
        ou = ju[name]
        if ou.kind != "sb":
            continue
        oj = jj.get(name)
        if oj is None:
            detail["sb"]["files only on the USA discs"] += 1
            continue
        pools.append((ou, items(jp, oj), items(us, ou)))
    smap = alignmod.speaker_map([(a, b) for _o, a, b in pools if len(a) == len(b)])
    for ou, a, b in pools:
        if len(a) == len(b):
            pairs = list(zip(range(len(a)), range(len(b))))
            detail["sb"]["files paired index for index"] += 1
        else:
            pairs, uj, uu = alignmod.align_items(a, b, smap)
            detail["sb"]["files aligned on identifiers and speakers"] += 1
            detail["sb"]["USA strings left unpaired"] += len(uu)
            detail["sb"]["Japanese strings left unpaired"] += len(uj)
        for i, j in pairs:
            put("sb", ou, b[j].key, a[i].raw, a[i].codec)
        detail["sb"]["strings paired"] += len(pairs)
    log(f"scene scripts: {detail['sb']['strings paired']} strings paired")

    # menus, tables, mini-game, whole files
    for name in sorted(ju):
        ou = ju[name]
        oj = jj.get(name)
        if ou.kind == "sb":
            continue
        fam = "mnu" if ou.kind in ("txd", "nj") else "bat" if ou.kind in ("batdat", "msgdat") else "sub"
        if oj is None:
            detail[fam]["files only on the USA discs"] += 1
            continue
        if ou.kind == "subtitle":
            if ou.role in ("movie", "event"):
                cu, cj = _cue_times(us, ou), _cue_times(jp, oj)
                share: Counter = Counter()
                hits = {}
                for (b0, b1, rid, _t) in cu:
                    hit = [k for k, (a0, a1, _r, _x) in enumerate(cj) if min(a1, b1) > max(a0, b0)]
                    hits[rid] = hit
                    share.update(hit)
                for rid, hit in hits.items():
                    if not hit:
                        detail[fam]["USA cues no Japanese cue overlaps"] += 1
                        continue
                    texts[rid] = "\n".join(cj[k][3] for k in hit)
                    detail[fam]["cues paired by time"] += 1
                    if len(hit) > 1 or any(share[k] > 1 for k in hit):
                        partial.append(rid)
                continue
            if ou.data == oj.data:
                detail[fam]["files identical on both builds (not a source)"] += 1
                continue
            ku = [(k, r) for k, r in ((s.key, rid) for rid, s in us.slots.items() if s.obj is ou)]
            kj = {s.key: rid for rid, s in jp.slots.items() if s.obj is oj}
            if [k for k, _ in ku] != list(kj):
                detail[fam]["files whose messages differ in number (not paired)"] += 1
                continue
            for k, rid in ku:
                texts[rid] = jp.by_id[kj[k]]["src"]
                detail[fam]["messages paired by number"] += 1
            continue
        a, b = items(jp, oj), items(us, ou)
        if ou.kind == "txd":
            for x, y in zip(a, b):
                put(fam, ou, y.key, x.raw, x.codec)
            detail[fam]["menu strings paired index for index"] += min(len(a), len(b))
            continue
        if [x.key for x in a] == [y.key for y in b]:
            if all(x.raw == y.raw for x, y in zip(a, b)):
                detail[fam]["files identical on both builds (not a source)"] += 1
                continue
            for x, y in zip(a, b):
                put(fam, ou, y.key, x.raw, x.codec)
            detail[fam]["strings paired key for key (same keys on both builds)"] += len(b)
        else:
            detail[fam][f"not paired: {Path(ou.path.replace(chr(92), '/')).name} "
                        f"({len(b)} USA strings, {len(a)} Japanese; the keys differ)"] += 1
    return texts, partial, detail


# ---------------------------------------------------------------------------
# cache / public
# ---------------------------------------------------------------------------
_STAMPED = ("txsource", "txfam_core", "txcodec", "align", "textpack", "textcodec", "sb", "txd", "njbin",
            "msgdat", "batdat", "subtitle")


def _code_stamp() -> str:
    import importlib.util
    h = hashlib.sha1()
    for name in _STAMPED:
        try:
            spec = importlib.util.find_spec(name)
            origin = getattr(spec, "origin", None) if spec is not None else None
            if origin and origin.endswith(".py") and os.path.isfile(origin):
                h.update(Path(origin).read_bytes())
            elif spec is not None and spec.loader is not None:
                import txcatalog
                h.update(txcatalog._code_digest(spec.loader.get_code(name)))
        except Exception:
            h.update(name.encode())
    return h.hexdigest()


def _rows_key(rows: List[dict]) -> str:
    h = hashlib.sha1()
    for r in rows:
        h.update(f"{r['id']}\0{r.get('cat')}\0{r.get('font')}\0{r.get('ctl')}\n".encode("utf-8", "replace"))
    return h.hexdigest()


def _stats(rows: List[dict], texts: Dict[str, str]) -> Tuple[dict, dict]:
    fam: Dict[str, Counter] = defaultdict(Counter)
    cat: Dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        hit = r["id"] in texts
        vis = not r.get("hide")
        for c in (fam[r["fam"]], cat[r["cat"]]):
            c["rows"] += 1
            c["aligned"] += hit
            c["unaligned"] += not hit
            c["visible"] += vis
            c["visible_aligned"] += vis and hit
    keys = ("rows", "aligned", "unaligned", "visible", "visible_aligned")
    return ({f: {k: c[k] for k in keys} for f, c in fam.items()},
            {f: {k: c[k] for k in keys} for f, c in cat.items()})


def align(usa_iso: str, source_iso: str, rows: Optional[List[dict]] = None,
          log: Callable[[str], None] = print, use_cache: bool = True) -> dict:
    """Source-language text for every catalog row of ``usa_iso``'s set that can
    be paired (module docstring). Raises ``SourceError`` for a disc that is
    not supported. Read-only."""
    import txfam_core as core
    kind_u = identify_disc(usa_iso)
    if kind_u not in ("usa", "proto"):
        raise SourceError(f"{usa_iso}: the Japanese original is shown for projects on the USA discs "
                          f"(or the May 2006 prototype); this is "
                          f"{'the Japanese disc itself' if kind_u == 'jp' else 'not an Episode III disc'}")
    kind_s = identify_disc(source_iso)
    if kind_s is None:
        raise SourceError(f"{source_iso}: not a Xenosaga Episode III disc this editor knows "
                          f"(expected the Japanese discs, SLPS_256.40 / SLPS_256.41)")
    if rows is None:
        import txcatalog
        rows = txcatalog.build_catalog(usa_iso, log=log)["rows"]
    if kind_s != "jp":
        texts = {r["id"]: r["src"] for r in rows if r["src"].strip()}
        stats, by_cat = _stats(rows, texts)
        return {"source": SRC_EN, "texts": texts, "partial": [], "stats": stats,
                "by_cat": by_cat, "detail": {}, "notes": ["English: the rows' own source text"]}
    key = hashlib.sha1("\0".join((str(VERSION), txdiscs.retail_id(usa_iso), txdiscs.retail_id(source_iso),
                                  _code_stamp(), _rows_key(rows))).encode()).hexdigest()
    import txcache
    if use_cache:
        data = txcache.load("source", key)
        if isinstance(data, dict) and data.get("version") == VERSION and data.get("source") == SRC_JA:
            data["notes"] = data.get("notes", []) + ["(from cache)"]
            data.pop("version", None)
            return data
    t0 = time.time()
    us = core.load(usa_iso)                                    # pure lookups: neither set becomes
    jp = core.load_set(txdiscs.pair(source_iso))               # "the" disc of this thread
    log("pairing the Japanese discs with the USA rows")
    texts, partial, detail = _pair(us, jp, log)
    notes: List[str] = []
    if len(txdiscs.pair(source_iso)) == 1:
        notes.append("only one Japanese disc was found: the other disc's movie subtitles have no Japanese")
    ids = {r["id"] for r in rows}
    texts = {k: v for k, v in texts.items() if k in ids}
    blank = [rid for rid, tx in texts.items() if not tx.strip()]
    for rid in blank:
        del texts[rid]
    partial = [rid for rid in partial if rid in texts]
    if blank:
        notes.append(f"{len(blank)} rows whose Japanese counterpart is blank are left out")
    stats, by_cat = _stats(rows, texts)
    notes.append(f"aligned in {time.time() - t0:.1f} s")
    res = {"source": SRC_JA, "texts": texts, "partial": partial, "stats": stats, "by_cat": by_cat,
           "detail": {f: dict(c) for f, c in detail.items()}, "notes": notes}
    if use_cache:
        txcache.store("source", key, dict(res, version=VERSION),
                      avoid=[str(Path(p).parent) for p in txdiscs.pair(usa_iso) + txdiscs.pair(source_iso)])
    return res


# ---------------------------------------------------------------------------

_JA_CHAR = re.compile(r"[぀-ヿ一-鿿！-～]")


def selftest(usa: str, source: Optional[str]) -> int:
    ok = True

    def check(cond, what):
        nonlocal ok
        print(("ok   " if cond else "FAIL ") + what)
        ok = ok and bool(cond)

    check(identify_disc(usa) in ("usa", "proto"), f"identify_disc: {identify_disc(usa)}")
    check(identify_disc("/nonexistent.iso") is None, "a bad path is None, not an exception")
    check(_common("cf\\us\\1210.sb", "us") == "cf\\xx\\1210.sb" and _common("mov\\jp\\bat\\a.txt", "jp") == "mov\\xx\\bat\\a.txt",
          "common names")
    import txcatalog
    rows = txcatalog.build_catalog(usa, log=lambda m: None)["rows"]
    res = align(usa, usa, rows, log=lambda m: None)
    check(res["source"] == SRC_EN and len(res["texts"]) > 1000, "the USA disc as its own source gives English")
    if source:
        try:
            align(source, usa, None, log=lambda m: None)
            check(False, "a Japanese base is refused")
        except SourceError:
            check(True, "a Japanese base is refused with a readable message")
        t = time.time()
        res = align(usa, source, rows, log=print, use_cache=False)
        byid = {r["id"]: r for r in rows}
        vis = [r for r in rows if not r["hide"]]
        got = sum(1 for r in vis if r["id"] in res["texts"])
        print(f"     {len(res['texts'])} rows have Japanese ({got} of the {len(vis)} offered rows) in {time.time() - t:.1f} s")
        for fam, st in sorted(res["stats"].items()):
            print(f"     {fam}: {st['visible_aligned']}/{st['visible']} offered rows; " +
                  "; ".join(f"{k} {v}" for k, v in sorted(res["detail"].get(fam, {}).items())))
        dlg = [r for r in vis if r["cat"].startswith("Dialogue") and r["id"] in res["texts"]]
        ja = sum(1 for r in dlg if _JA_CHAR.search(res["texts"][r["id"]]))
        check(dlg and ja / len(dlg) > 0.99, f"paired dialogue is Japanese text ({ja}/{len(dlg)})")
        named = [r for r in dlg if r["src"].startswith("[")]
        spk = [r for r in named if res["texts"][r["id"]].startswith("[")]
        check(named and len(spk) / len(named) > 0.99,
              f"a line with a speaker pairs with a line with a speaker ({len(spk)}/{len(named)})")
        check(all(k in byid for k in res["texts"]) and set(res["partial"]) <= set(res["texts"]),
              "every text is for a catalog row; partial rows have text")
        r0 = next((r for r in vis if r["cat"] == "Battle names & descriptions" and r["src"] == "Shion"), None)
        check(r0 is not None and res["texts"].get(r0["id"]) == "シオン", "batdat 'Shion' pairs with シオン")
        again = align(usa, source, rows, log=lambda m: None)       # stores it (use_cache off above neither reads nor writes)
        third = align(usa, source, rows, log=lambda m: None)
        check(again["texts"] == res["texts"] == third["texts"] and "(from cache)" in third["notes"],
              "a run with the cache on stores the pairing; the next one comes from the cache")
    print("selftest", "passed" if ok else "FAILED")
    return 0 if ok else 1


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("selftest")
    s.add_argument("--usa", required=True)
    s.add_argument("--source")
    a = ap.parse_args(argv)
    return selftest(a.usa, a.source)


if __name__ == "__main__":
    sys.exit(main())
