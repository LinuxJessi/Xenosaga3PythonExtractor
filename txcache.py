"""txcache.py — the translation editor's cache on disk (Episode III).

Reading every string of a disc set takes half a minute (the scene scripts'
code is disassembled to tell shown text from debug prints), and pairing the
USA text with the Japanese takes about as long, so both results are kept
between runs. This module is the ONE place that decides where, how much and
for how long; ``txcatalog``, ``txsource`` and ``txtarget`` (the installed-font
index) store through it.

Where::

    $XS3_TX_CACHE/xs3-txeditor                 when set (a sub-folder of the folder you choose)
    ~/Library/Caches/xs3-txeditor              macOS
    %LOCALAPPDATA%\\xs3-txeditor\\Cache          Windows
    $XDG_CACHE_HOME/xs3-txeditor               elsewhere (default ~/.cache/xs3-txeditor)

Never inside the kit's own folder, and never in a folder that holds a disc
image of the set being read: a location that is either is refused and the
platform default is used (``cache_dir``), or, for a disc folder, the entry is
simply not written (``store(avoid=...)``).

What::

    catalog-<retail id>-<code stamp>.json.gz   one per disc set and kit version
    source-<key>.json.gz                       one per (USA set, Japanese set) pairing
    fonts-v1.json                              the installed-font index (small)

An entry is named by what it was made from: the retail id is a hash over each
disc's boot executable and every index (which record each object's sector and
size), the stamp a hash over the code of every module the rows come from. A
different disc set, a patched copy or another version of the kit therefore
never reads someone else's entry; it makes its own. The payload repeats its
kind, key and stamp and is checked on read: a truncated or foreign file is a
miss (and is removed), never an error.

How much: entries are gzip-compressed (a catalog is about 4 MB, not 40). After
every write the folder is pruned: catalogs made by another version of the code
go first, then anything not used for 60 days, then the least recently used
until at most 6 catalogs, 6 pairings and 300 MB remain. "Used" is the file's
modification time, which a hit refreshes, so no index file can go stale.

Only files this module names are ever deleted: ``clear`` and ``prune`` match
the patterns above (and the leftovers of an interrupted write, ``xs3tx-*.tmp``),
so pointing ``XS3_TX_CACHE`` at a folder with other things in it loses nothing.
The first run also removes the entries the earlier versions left in
``~/.cache/xs3-txeditor`` (their format is no longer read).

    python txcache.py                  where it is, what is in it
    python txcache.py --clear          delete the entries
    python cli.py tx-cache [--clear]   the same
    python txcache.py --self-test
"""
from __future__ import annotations

import gzip
import json
import os
import re
import sys
import tempfile
import time
import zlib
from pathlib import Path
from typing import Iterable, List, Optional

ROOT = Path(__file__).resolve().parent
APP = "xs3-txeditor"
ENV = "XS3_TX_CACHE"
FORMAT = 1
MAX_ENTRIES = {"catalog": 6, "source": 6}
MAX_BYTES = 300 * 1024 * 1024
MAX_AGE_DAYS = 60
TMP_AGE = 3600                       # a temp file older than this belongs to a write that died

_ENTRY = re.compile(r"^(catalog|source)-([0-9a-f]{8,64})(?:-([0-9a-f]{8,64}))?\.json\.gz$")
_PLAIN = re.compile(r"^fonts-v\d+\.json$")
_TMP = re.compile(r"^xs3tx-.*\.tmp$")
# what the versions before this module wrote into ~/.cache/xs3-txeditor
_LEGACY = re.compile(r"^(?:[0-9a-f]{40}\.json|source-[0-9a-f]{8,64}\.json|fonts-v\d+\.json|tmp[a-z0-9_]+\.tmp)$")

_checked_legacy = [False]


def _inside(p: Path, parent: Path) -> bool:
    try:
        p.resolve().relative_to(parent.resolve())
        return True
    except (ValueError, OSError):
        return False


def default_dir() -> Path:
    home = Path.home()
    if sys.platform == "darwin":
        return home / "Library" / "Caches" / APP
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA")
        return (Path(base) if base else home / "AppData" / "Local") / APP / "Cache"
    base = os.environ.get("XDG_CACHE_HOME")
    return (Path(base) if base else home / ".cache") / APP


def legacy_dir() -> Path:
    return Path.home() / ".cache" / APP


def cache_dir() -> Path:
    """The cache folder (not created here). ``$XS3_TX_CACHE`` wins unless it is
    inside the kit's folder, which is refused."""
    env = os.environ.get(ENV, "").strip()
    if env:
        p = Path(env).expanduser() / APP            # its own sub-folder: nothing of yours is beside its files
        if not _inside(p, ROOT):
            return p
        print(f"[txcache] {ENV}={env} is inside the kit's folder; using {default_dir()} instead", file=sys.stderr)
    return default_dir()


def _owned(name: str) -> bool:
    return bool(_ENTRY.match(name) or _PLAIN.match(name) or _TMP.match(name))


def _files(d: Path) -> List[Path]:
    try:
        return [p for p in d.iterdir() if p.is_file() and not p.is_symlink() and _owned(p.name)]
    except OSError:
        return []


def _unlink(p: Path) -> int:
    try:
        n = p.stat().st_size
        p.unlink()
        return n
    except OSError:
        return 0


def _clean_legacy() -> None:
    """Once per process: drop what earlier versions left in ~/.cache/xs3-txeditor
    (only their own file names; the folder goes when it is then empty)."""
    if _checked_legacy[0]:
        return
    _checked_legacy[0] = True
    d = legacy_dir()
    try:
        names = [p for p in d.iterdir() if p.is_file() and not p.is_symlink() and _LEGACY.match(p.name)]
    except OSError:
        return
    same = d.resolve() == cache_dir().resolve() if d.exists() else False
    for p in names:
        if same and _PLAIN.match(p.name):
            continue                                   # the font index keeps its name and its format
        _unlink(p)
    if not same:
        try:
            d.rmdir()                                  # only when empty
        except OSError:
            pass


def entry_name(kind: str, key: str, stamp: str = "") -> str:
    if kind not in MAX_ENTRIES or not re.fullmatch(r"[0-9a-f]{8,64}", key) or \
            (stamp and not re.fullmatch(r"[0-9a-f]{8,64}", stamp)):
        raise ValueError(f"not a cache entry: {kind!r} {key!r} {stamp!r}")
    return f"{kind}-{key}" + (f"-{stamp}" if stamp else "") + ".json.gz"


def load(kind: str, key: str, stamp: str = "") -> Optional[dict]:
    """The stored value, or None (absent, unreadable, or not what its name says)."""
    _clean_legacy()
    p = cache_dir() / entry_name(kind, key, stamp)
    try:
        with gzip.open(p, "rt", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict) or data.get("format") != FORMAT or data.get("kind") != kind \
                or data.get("key") != key or data.get("stamp", "") != stamp:
            raise ValueError("not this entry")
    except FileNotFoundError:
        return None
    except (OSError, ValueError, EOFError, zlib.error):
        _unlink(p)                                     # truncated, damaged or foreign: a miss, and gone
        return None
    try:
        os.utime(p, None)                              # "used now": what pruning goes by
    except OSError:
        pass
    return data.get("value")


def store(kind: str, key: str, value, stamp: str = "", avoid: Iterable[str] = ()) -> Optional[Path]:
    """Write one entry (atomically), then prune. ``avoid`` = folders the cache
    must not be in (the disc images' folders): the entry is then not written.
    Returns the file, or None when nothing was written."""
    _clean_legacy()
    d = cache_dir()
    for a in avoid:
        try:
            if d.resolve() == Path(a).resolve():
                print(f"[txcache] {d} holds a disc image; nothing is cached there (set {ENV} to "
                      f"another folder)", file=sys.stderr)
                return None
        except OSError:
            continue
    name = entry_name(kind, key, stamp)
    tmp = None
    try:
        d.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(d), prefix="xs3tx-", suffix=".tmp")
        with os.fdopen(fd, "wb") as raw:
            with gzip.GzipFile(fileobj=raw, mode="wb", compresslevel=5, mtime=0) as gz:
                gz.write(json.dumps({"format": FORMAT, "kind": kind, "key": key, "stamp": stamp,
                                     "value": value}, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        os.replace(tmp, d / name)
        tmp = None
    except OSError as exc:
        print(f"[txcache] could not write {d / name}: {exc}", file=sys.stderr)
        return None
    finally:
        if tmp:
            try:
                os.unlink(tmp)
            except OSError:
                pass
    prune(keep=name)
    return d / name


def plain_path(name: str) -> Path:
    """Path of a small uncompressed file of the cache (the font index)."""
    if not _PLAIN.match(name):
        raise ValueError(f"not a cache file name: {name!r}")
    _clean_legacy()
    return cache_dir() / name


def prune(keep: str = "", now: Optional[float] = None) -> List[str]:
    """Apply the limits (module docstring). ``keep`` = an entry just written:
    it stays, and catalogs of the same disc set with another code stamp go."""
    now = time.time() if now is None else now
    d = cache_dir()
    gone: List[str] = []
    stats = []
    for p in _files(d):
        try:
            st = p.stat()
        except OSError:
            continue
        stats.append((p, st.st_mtime, st.st_size))
    kept = _ENTRY.match(keep) if keep else None
    left = []
    for p, mt, size in stats:
        m = _ENTRY.match(p.name)
        drop = False
        if _TMP.match(p.name):
            drop = now - mt > TMP_AGE
        elif m:
            if p.name == keep:
                drop = False
            elif kept and m.group(1) == "catalog" == kept.group(1) and m.group(3) != kept.group(3):
                drop = True                            # made by another version of the code
            elif now - mt > MAX_AGE_DAYS * 86400:
                drop = True
        if drop:
            _unlink(p)
            gone.append(p.name)
        else:
            left.append((p, mt, size))
    for kind, most in MAX_ENTRIES.items():
        mine = sorted((x for x in left if (_ENTRY.match(x[0].name) or [None, None])[1] == kind),
                      key=lambda x: (x[0].name == keep, x[1]), reverse=True)
        for p, _mt, _size in mine[most:]:
            _unlink(p)
            gone.append(p.name)
            left = [x for x in left if x[0] != p]
    total = sum(x[2] for x in left)
    for p, _mt, size in sorted((x for x in left if _ENTRY.match(x[0].name) and x[0].name != keep),
                               key=lambda x: x[1]):
        if total <= MAX_BYTES:
            break
        _unlink(p)
        gone.append(p.name)
        total -= size
    return gone


def info() -> dict:
    """{"path", "exists", "bytes", "entries": [{"name", "kind", "bytes", "used"}], "limits"}"""
    _clean_legacy()
    d = cache_dir()
    entries = []
    for p in sorted(_files(d)):
        try:
            st = p.stat()
        except OSError:
            continue
        m = _ENTRY.match(p.name)
        entries.append({"name": p.name, "kind": m.group(1) if m else ("fonts" if _PLAIN.match(p.name) else "temp"),
                        "bytes": st.st_size,
                        "used": time.strftime("%Y-%m-%d %H:%M", time.localtime(st.st_mtime))})
    return {"path": str(d), "exists": d.is_dir(), "bytes": sum(e["bytes"] for e in entries),
            "entries": entries, "env": ENV, "from_env": bool(os.environ.get(ENV, "").strip()),
            "limits": {"catalogs": MAX_ENTRIES["catalog"], "pairings": MAX_ENTRIES["source"],
                       "megabytes": MAX_BYTES // (1024 * 1024), "days": MAX_AGE_DAYS}}


def clear() -> dict:
    """Delete this module's files (nothing else in the folder). -> {"removed", "bytes", "path"}"""
    d = cache_dir()
    n = b = 0
    for p in _files(d):
        size = _unlink(p)
        if size or not p.exists():
            n += 1
            b += size
    try:
        d.rmdir()                                      # only when now empty
    except OSError:
        pass
    return {"removed": n, "bytes": b, "path": str(d)}


def describe() -> str:
    i = info()
    lines = [f"cache folder: {i['path']}" + ("  (from $" + ENV + ")" if i["from_env"] else "")
             + ("" if i["exists"] else "  (not created yet)"),
             f"{len(i['entries'])} file(s), {i['bytes'] / 1e6:.1f} MB; kept: at most {i['limits']['catalogs']} disc "
             f"sets, {i['limits']['pairings']} pairings, {i['limits']['megabytes']} MB, {i['limits']['days']} days "
             f"unused"]
    for e in i["entries"]:
        lines.append(f"  {e['bytes'] / 1e6:7.1f} MB  {e['used']}  {e['name']}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------

def self_test() -> int:
    ok = True

    def check(cond, what):
        nonlocal ok
        print(("ok   " if cond else "FAIL ") + what)
        ok = ok and bool(cond)

    old_env = os.environ.get(ENV)
    tmp = Path(tempfile.mkdtemp(prefix="xs3tx-cache-test-"))
    _checked_legacy[0] = True                          # the test never touches the real legacy folder
    try:
        os.environ[ENV] = str(ROOT / "cache-inside-kit")
        check(cache_dir() == default_dir(), "a location inside the kit's folder is refused")
        os.environ[ENV] = str(tmp)
        check(cache_dir() == tmp / APP, f"${ENV} names the folder (the cache is its {APP} sub-folder)")
        tmp = tmp / APP
        tmp.mkdir()
        a, b = "a" * 40, "b" * 40
        s1, s2 = "1" * 16, "2" * 16
        check(load("catalog", a, s1) is None, "absent entry: a miss")
        p = store("catalog", a, {"rows": [1, 2, 3], "é": "œ"}, s1)
        check(p is not None and p.name == f"catalog-{a}-{s1}.json.gz" and load("catalog", a, s1) == {"rows": [1, 2, 3], "é": "œ"},
              "store / load round trip (gzip)")
        check(load("catalog", b, s1) is None and load("catalog", a, s2) is None,
              "another disc set or another code stamp never reads this entry")
        (tmp / f"catalog-{b}-{s1}.json.gz").write_bytes(p.read_bytes())
        check(load("catalog", b, s1) is None and not (tmp / f"catalog-{b}-{s1}.json.gz").exists(),
              "an entry whose payload is another's is a miss, and removed")
        (tmp / f"catalog-{b}-{s1}.json.gz").write_bytes(p.read_bytes()[:40])
        check(load("catalog", b, s1) is None and not (tmp / f"catalog-{b}-{s1}.json.gz").exists(),
              "a truncated entry is a miss, and removed")
        good = p.read_bytes()
        (tmp / f"catalog-{b}-{s1}.json.gz").write_bytes(good[:20] + bytes(x ^ 0x5A for x in good[20:60]) + good[60:])
        check(load("catalog", b, s1) is None and not (tmp / f"catalog-{b}-{s1}.json.gz").exists(),
              "an entry with a damaged stream is a miss, and removed")
        store("catalog", a, {"v": 2}, s2)
        check(not (tmp / f"catalog-{a}-{s1}.json.gz").exists() and load("catalog", a, s2) == {"v": 2},
              "a catalog made by another version of the code is pruned when the new one is written")
        t0 = time.time() - 1000
        for k in range(8):
            (tmp / entry_name("source", f"{k:040x}")).write_bytes(b"x" * 10)
            os.utime(tmp / entry_name("source", f"{k:040x}"), (t0 + k, t0 + k))
        prune()
        left = sorted(x.name for x in tmp.iterdir() if x.name.startswith("source-"))
        check(len(left) == MAX_ENTRIES["source"] and entry_name("source", f"{0:040x}") not in left
              and entry_name("source", f"{7:040x}") in left, "the least recently used pairings go first (6 kept)")
        prune(keep=f"catalog-{a}-{s2}.json.gz", now=time.time() + (MAX_AGE_DAYS + 1) * 86400)
        check(not [x for x in tmp.iterdir() if x.name.startswith("source-")], "entries unused for 60 days go")
        other = tmp / "my-notes.txt"
        other.write_text("keep me")
        (tmp / "sub").mkdir()
        (tmp / "sub" / f"catalog-{a}-{s1}.json.gz").write_text("x")
        store("catalog", a, {"v": 3}, s2)
        plain_path("fonts-v1.json").write_text("[]")
        i = info()
        check(i["path"] == str(tmp) and {e["kind"] for e in i["entries"]} == {"catalog", "fonts"} and i["bytes"] > 0,
              "info lists this module's files and their size")
        r = clear()
        check(r["removed"] == 2 and other.read_text() == "keep me" and (tmp / "sub" / f"catalog-{a}-{s1}.json.gz").exists(),
              "clear removes this module's files only (a stranger's file and a sub-folder stay)")
        check(store("catalog", a, {"v": 4}, s2, avoid=[str(tmp)]) is None, "a folder that holds a disc image is not written to")
        try:
            entry_name("catalog", "../../etc", "")
            check(False, "a key that is not a hash is refused")
        except ValueError:
            check(True, "a key that is not a hash is refused")
    finally:
        if old_env is None:
            os.environ.pop(ENV, None)
        else:
            os.environ[ENV] = old_env
        import shutil
        shutil.rmtree(tmp.parent if tmp.name == APP else tmp, ignore_errors=True)
    print("selftest", "passed" if ok else "FAILED")
    return 0 if ok else 1


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--clear", action="store_true", help="delete the cache's entries")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return self_test()
    if a.clear:
        r = clear()
        print(f"removed {r['removed']} file(s), {r['bytes'] / 1e6:.1f} MB, from {r['path']}")
        return 0
    print(describe())
    return 0


if __name__ == "__main__":
    sys.exit(main())
