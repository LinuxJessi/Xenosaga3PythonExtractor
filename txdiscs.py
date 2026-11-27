"""txdiscs.py — which disc images a translation project is about (Episode III).

Episode III is two discs. The text of the menus, the battles, the scene
scripts and the mini-game is in the X3.00 family (chain 0), the same bytes on
both discs; each disc then has its own story chain (chain 1 on Disc 1, chain 2
on Disc 2) with that disc's movie subtitles. The translation editor is handed
ONE image path (the page's step 1, ``tx-build --retail``); this module finds
the other disc of the pair so that one project covers both:

    pair(iso) -> [Disc 1 path, Disc 2 path]      (or [iso] when the other disc
                                                  is not found)

The partner is, in order: the one given with ``set_partner(iso, other)`` (the
CLI's ``--disc2``) or the ``XS3_TX_DISC2`` environment variable, else an image
of the SAME build with the other disc number found next to ``iso``: in its
folder, in a sibling folder (``Game (Disc 1)/`` and ``Game (Disc 2)/``), or one
level below either. Candidates whose name is ``iso``'s with the disc number
swapped are tried first. Only images that pass ``region.mixed_regions`` with
``iso`` (one build, different disc numbers) are accepted. Nothing is written.

    info(path) -> {"ok", "build", "codec", "lang", "disc", "boot", "message"}
    retail_id(iso) -> sha1 over the set: per disc its number, boot executable
                      name + sha256 and every X3.x0 index (which records each
                      object's sector and size)

Supported bases: the builds ``region.py`` knows (USA SLUS_213.89/214.17, the
May 2006 prototype, Japan SLPS_256.40/41). Any other image is refused with a
readable message.

    python txdiscs.py selftest [--iso DISC]
"""
from __future__ import annotations

import hashlib
import os
import re
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

GAME = "Xenosaga Episode III"
BUILD_NAMES = {"us": "USA", "proto_2006_05": "May 2006 prototype", "jp": "Japan"}

_INFO: Dict[tuple, dict] = {}
_PAIR: Dict[tuple, List[str]] = {}
_PARTNER: Dict[str, str] = {}
_LONE_AT: Dict[tuple, float] = {}
_PAIR_STAT: Dict[tuple, tuple] = {}


def _stats(paths) -> tuple:
    out = []
    for q in paths:
        try:
            st = os.stat(q)
            out.append((q, st.st_size, st.st_mtime_ns))
        except OSError:
            out.append((q, None, None))
    return tuple(out)
LONE_RECHECK = 10.0                  # seconds a "no other disc found" answer is kept


class DiscError(ValueError):
    pass


def _key(path: str) -> tuple:
    st = os.stat(path)
    return (str(Path(path).resolve()), st.st_size, st.st_mtime_ns)


def info(path: str) -> dict:
    """What one image is (cached per path, size, mtime). ``ok`` is True for a
    known Episode III build."""
    key = _key(path)
    got = _INFO.get(key)
    if got is not None:
        return got
    out = {"ok": False, "build": None, "codec": None, "lang": None, "disc": 0, "boot": None,
           "exe_sha256": None, "index_sha1": {}, "message": "not a disc image this kit can read"}
    try:
        import region
        from chains import disc_number
        from disc import Disc
        with Disc(path) as d:
            reg = region.detect(d)
            out["boot"] = d.boot_elf_name()
            if reg.name == "unknown":
                out["message"] = (f"not a known {GAME} build: the boot executable is "
                                  f"{out['boot'] or 'missing'} ({reg.note or 'no profile'})")
            else:
                out.update(ok=True, build=reg.name, codec=reg.codec, lang=reg.lang,
                           disc=disc_number(d.iso), exe_sha256=region.exe_sha256(d),
                           index_sha1={c: hashlib.sha1(b).hexdigest() for c, b in sorted(d.index_data.items())},
                           message=f"{GAME} ({BUILD_NAMES.get(reg.name, reg.name)}), disc "
                                   f"{disc_number(d.iso) or '?'} ({out['boot']})")
    except Exception as exc:                                       # noqa: BLE001 - any unreadable file
        out["message"] = f"cannot be read as a {GAME} disc ({type(exc).__name__}: {exc})"
    _INFO[key] = out
    return out


def set_partner(iso: str, other: Optional[str]) -> None:
    """Name the other disc of ``iso``'s pair for this process (None forgets it)."""
    k = str(Path(iso).resolve())
    if other:
        _PARTNER[k] = str(Path(other).expanduser().resolve())
    else:
        _PARTNER.pop(k, None)
    _PAIR.clear()


_DISC_NO = re.compile(r"(?i)(dis[ck]\s*)([12])")


def _swapped(name: str, want: int) -> str:
    return _DISC_NO.sub(lambda m: m.group(1) + str(want), name)


def _candidates(p: Path, want: int) -> List[Path]:
    """Images near ``p`` that could be disc ``want``: same folder, sibling
    folders, one level below either; the name with the number swapped first."""
    seen, out = set(), []

    def add(q: Path):
        try:
            r = q.resolve()
        except OSError:
            return
        if r != p and r not in seen and q.is_file():
            seen.add(r)
            out.append(q)

    add(p.with_name(_swapped(p.name, want)))
    if not p.parent.name:                 # an image in a volume's root: no sibling folders to look in
        return out
    add(p.parent.with_name(_swapped(p.parent.name, want)) / _swapped(p.name, want))
    roots = [p.parent, p.parent.parent]
    for root in roots:
        try:
            subs = sorted(root.iterdir())
        except OSError:
            continue
        for q in subs:
            if q.is_file() and q.suffix.lower() == ".iso":
                add(q)
            elif q.is_dir() and root is roots[1] and not q.name.startswith("."):
                try:
                    for r in sorted(q.iterdir()):
                        if r.is_file() and r.suffix.lower() == ".iso":
                            add(r)
                except OSError:
                    continue
    # names that mention the game or share the image's stem come before strangers
    stem = _DISC_NO.sub("", p.stem).lower()
    head = out[:2] if out and out[0].name == _swapped(p.name, want) else []
    rest = [q for q in out if q not in head]
    rest.sort(key=lambda q: (_DISC_NO.sub("", q.stem).lower() != stem, "xenosaga" not in q.name.lower()))
    return head + rest[:40]


def _is_partner(a: dict, b: dict) -> bool:
    if not (a["ok"] and b["ok"]) or a["build"] != b["build"] or not a["disc"] or not b["disc"]:
        return False
    if a["disc"] == b["disc"]:
        return False
    # one build's two discs carry the same X3.00 index
    return a["index_sha1"].get(0) == b["index_sha1"].get(0)


def pair(iso: str) -> List[str]:
    """[Disc 1, Disc 2] of the set ``iso`` belongs to, or [iso] alone."""
    p = Path(iso).expanduser().resolve()
    me = info(str(p))
    if not me["ok"]:
        raise DiscError(f"{p}: {me['message']}")
    key = _key(str(p))
    got = _PAIR.get(key)
    if got is not None and len(got) == 2 and _PAIR_STAT.get(key) == _stats(got):
        return list(got)                 # (a pair whose other image is gone or replaced is made again)
    if got is not None and len(got) == 1 and time.time() - _LONE_AT.get(key, 0) < LONE_RECHECK:
        return list(got)                 # (a lone disc is looked for again after a few seconds: the other
                                         #  disc may have been put next to it since)
    want = 2 if me["disc"] == 1 else 1
    other = None
    named = _PARTNER.get(str(p))
    if named and not Path(named).is_file():
        raise DiscError(f"{named}: no such image (the other disc that was named for {p.name})")
    if named and Path(named).resolve() == p:
        raise DiscError(f"{named} is the same image as the first one; name the OTHER disc of the set")
    if named:
        oi = info(named)
        if not _is_partner(me, oi):
            raise DiscError(f"{named} is not the other disc of {p.name}'s set ({oi['message']}; "
                            f"{p.name} is {me['message']})")
        other = str(Path(named).resolve())
    env = os.environ.get("XS3_TX_DISC2")
    if other is None and env and Path(env).is_file() and Path(env).resolve() != p \
            and _is_partner(me, info(env)):         # a variable for another set is simply not this one's
        other = str(Path(env).resolve())
    if other is None and me["disc"]:
        for q in _candidates(p, want):
            try:
                if _is_partner(me, info(str(q))):
                    other = str(q.resolve())
                    break
            except OSError:
                continue
    out = [str(p)] if other is None else sorted([str(p), other], key=lambda s: info(s)["disc"])
    _PAIR[key] = out
    _PAIR_STAT[key] = _stats(out)
    _LONE_AT[key] = time.time()
    return list(out)


def describe(iso: str) -> str:
    """One line for the catalog notes: what set the rows cover."""
    ps = pair(iso)
    me = info(ps[0])
    build = BUILD_NAMES.get(me["build"], me["build"])
    if len(ps) == 2:
        return (f"{GAME} ({build}), Disc 1 + Disc 2: {Path(ps[0]).name} and {Path(ps[1]).name}; a build "
                f"writes patched copies of both")
    n = me["disc"]
    if me["build"] == "proto_2006_05":
        return f"{GAME} ({build}): one disc"
    return (f"{GAME} ({build}), disc {n} only: the other disc was not found next to it, so the movie "
            f"subtitles of disc {3 - n if n else '?'} are not listed and a build writes this disc only "
            f"(the other disc would keep its original menus and dialogue). Put both images in one "
            f"folder (or in folders side by side), or use tx-build --disc2")


def _id_of(paths: List[str]) -> str:
    h = hashlib.sha1()
    for p in paths:
        i = info(p)
        h.update(f"{i['disc']}\0{i['boot']}\0{i['exe_sha256']}\0".encode())
        for c, s in sorted(i["index_sha1"].items()):
            h.update(f"{c}:{s}\0".encode())
    return h.hexdigest()


def retail_id(iso: str) -> str:
    return _id_of(pair(iso))


def lone_ids(iso: str) -> List[str]:
    """For a set of two discs: the retail id each disc has when it is opened
    ALONE (a project made while only that disc was found carries it). Empty for
    a lone disc."""
    ps = pair(iso)
    return [_id_of([p]) for p in ps] if len(ps) == 2 else []


def selftest(iso: Optional[str]) -> int:
    ok = True

    def check(cond, what):
        nonlocal ok
        print(("ok   " if cond else "FAIL ") + what)
        ok = ok and bool(cond)

    check(_swapped("Game (Disc 1).iso", 2) == "Game (Disc 2).iso" and _swapped("x_disk2.iso", 1) == "x_disk1.iso",
          "disc number swapped in a name")
    a = {"ok": True, "build": "us", "disc": 1, "index_sha1": {0: "x", 1: "y"}}
    b = {"ok": True, "build": "us", "disc": 2, "index_sha1": {0: "x", 2: "z"}}
    check(_is_partner(a, b) and not _is_partner(a, a) and not _is_partner(a, dict(b, build="jp"))
          and not _is_partner(a, dict(b, index_sha1={0: "q"})), "partner rule: one build, other number, same X3.00")
    if iso:
        i = info(iso)
        check(i["ok"], f"info: {i['message']}")
        ps = pair(iso)
        check(len(ps) in (1, 2) and all(Path(p).is_file() for p in ps), f"pair: {[Path(p).name for p in ps]}")
        if len(ps) == 2:
            check(pair(ps[1]) == ps and retail_id(ps[0]) == retail_id(ps[1]),
                  "either disc of the pair gives the same set and the same retail id")
        print("     " + describe(iso))
        print("     retail id " + retail_id(iso))
    print("selftest", "passed" if ok else "FAILED")
    return 0 if ok else 1


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("selftest")
    s.add_argument("--iso")
    a = ap.parse_args(argv)
    return selftest(a.iso)


if __name__ == "__main__":
    sys.exit(main())
