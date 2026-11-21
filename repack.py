#!/usr/bin/env python3
"""repack.py — depack/repack any single file on an Episode III disc, in place.

The single-image, in-place front end of the write path (``patch.py`` is the
copy-based, multi-file, Disc 1 + Disc 2 layer every importer uses; chrtex.py
is the texture-aware front end). Since 2026-11-20 every location comes from
the disc's OWN X3.00 / X3.10 / X3.20 index through ``disc.Disc``, so these
commands work on the USA discs, the May 2006 prototype (whose layout differs
from retail in 364 X3.00 and 109 X3.10 entries) and the Japanese discs. The
bundled lba/*.txt tables are no longer read here; they are kept only as a test
oracle (``self_test`` checks the index against them on USA Disc 1 / Disc 2).

What it does (``repack-*`` in cli.py, or ``python repack.py ...``):

  * replace a file with one of the same size (always safe), or
  * with ``--pad``, a file of a different size that still fits the entry's
    allocation (the gap to the next entry's sector): written in place, the
    stale tail cleared, and the u32 size field in the index rewritten to the
    new length (``disc.Disc.write_entry``). Before 2026-11-20 ``--pad``
    zero-padded the file and left the old size in the index, so the engine
    kept reading the old byte count; that bug is fixed.
  * anything bigger, a Disc 1 + Disc 2 pair, or a copy instead of an in-place
    write: use ``cli.py patch`` (patch.py), which appends and repoints with
    ``--grow``.

Every write is read back. Entries that start on another file's sector
(``disc.Disc.sharers``) are refused in place.

Commands:
  info    <iso> <discpath>            index entry, LBA, holding X3 file, slack
  extract <iso> <discpath> <out>      pull one file
  patch   <iso> <discpath> <file>     write one file back in place  [--pad]
  tree    <iso> <moddir>              patch every file in a mirror tree
                                      (moddir/mdl/chr/... = \\mdl\\chr\\...)
                                      [--pad] [--dry-run]

<discpath> is the in-game path, e.g. \\mdl\\chr\\pc\\C3kosmos00.chr (quote it
in the shell; / works too; case-insensitive). ISO9660 files (SYSTEM.CNF, the
boot ELF, OVLs) resolve for info/extract. Work on a COPY of your ISO
(macOS: ``cp -c`` is instant).
"""
from __future__ import annotations

import os

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import disc as disc_mod                                            # noqa: E402
from disc import DiscError, norm                                   # noqa: E402

HERE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
SECTOR = 2048


@dataclass(frozen=True)
class Row:
    source: str        # "chain0" / "chain1" / "chain2"
    offset: int        # byte offset in the chain (index file = offset 0)
    size: int          # byte length (the index's size field)
    alloc: int         # bytes the file may occupy in place
    path: str          # in-game path as the index spells it, with a leading backslash
    chain: int = 0
    lba: int = 0       # absolute image sector
    entry: object = None


def _lba_note(lba_dir) -> None:
    if lba_dir:
        print(f"note: --lba {lba_dir} is ignored: locations now come from the disc's own index "
              "(lba/ is kept only as a test oracle)", file=sys.stderr)


class Disc:
    """One ISO through its own index (``disc.Disc``), with the row view the older
    callers use (``rows`` keyed by lower-case ``\\path``, ``read(row)``)."""

    def __init__(self, iso_path: str, lba_dir: Optional[str] = None, writable: bool = False):
        _lba_note(lba_dir)
        self.iso_path = Path(iso_path)
        try:
            self.d = disc_mod.Disc(iso_path, writable=writable)
        except ValueError as e:
            sys.exit(f"{iso_path}: {e}")
        self._rows()

    def _rows(self) -> None:
        self.rows: Dict[str, Row] = {}
        self.sources = [f"chain{c}" for c in self.d.chains]
        for c, e in self.d.entries():
            key = "\\" + norm(e.path)
            if key in self.rows:
                continue                      # chain 0 first, as disc.Disc.lookup
            self.rows[key] = Row(f"chain{c}", e.byte_offset, e.size, self.d.allocation(e),
                                 "\\" + e.path.lstrip("\\"), c,
                                 self.d.index_lba(c) + e.sector, e)

    @staticmethod
    def _read_root(iso_path) -> Dict[str, Tuple[int, int]]:
        """name -> (byte offset in ISO, size) for every ISO root file (kept for callers
        such as textpack.IndexDisc)."""
        from iso9660 import IsoImage
        with IsoImage(iso_path) as iso:
            return {f.path: (f.lba * SECTOR, f.size) for f in iso.files.values()
                    if "\\" not in f.path and not f.is_dir}

    def close(self) -> None:
        self.d.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # -- resolution ---------------------------------------------------------

    def row(self, discpath: str) -> Row:
        r = self.rows.get("\\" + norm(discpath))
        if not r:
            sys.exit(f"{discpath}: not in the index of {self.iso_path.name} "
                     f"({'/'.join(self.sources)}; is this the right disc?)")
        return r

    def iso_offset(self, r: Row) -> int:
        return self.d.absolute_offset(r.entry)

    # -- operations ---------------------------------------------------------

    def read(self, r: Row) -> bytes:
        return self.d.read_entry(r.entry)

    def write(self, r: Row, data: bytes, pad: bool) -> None:
        if len(data) != r.size and not pad:
            sys.exit(f"{r.path}: size mismatch (index {r.size}, file {len(data)}). Same-size only "
                     f"unless --pad (fits up to {r.alloc} bytes; the size field is updated)")
        try:
            self.d.write_entry(r.entry, data)
        except DiscError as e:
            sys.exit(f"{e}. In-place repack cannot grow a file: use `cli.py patch --iso ... --out ... "
                     f"--set '{r.path}=FILE' --grow` (copy-based, appends and repoints)")
        self._rows()


# ---------------------------------------------------------------------------
# commands (cli.py calls these with the same signatures as before)
# ---------------------------------------------------------------------------

def cmd_info(iso: str, discpath: str, lba_dir=None) -> None:
    with Disc(iso, lba_dir) as d:
        r = d.rows.get("\\" + norm(discpath))
        if r is None:
            f = d.d.iso.find(discpath)
            if f is None or f.is_dir:
                d.row(discpath)                       # exits with the message
            alloc = d.d.fs_allocation(f.path) if not disc_mod.BIGFILE_RE.match(f.path) else f.size
            print(f"{f.path}  (ISO9660 file)")
            print(f"  LBA {f.lba}   size {f.size} (0x{f.size:X})   room before the next extent {alloc}")
            return
        rd = d.d.readers[r.chain]
        holder, within = rd.locate(r.offset) if r.offset < rd.total else ("past the chain end (relocated)", 0)
        sh = d.d.sharers(r.entry)
        print(r.path)
        print(f"  index   {rd.names[0]} (chain {r.chain})   sector {r.entry.sector}   size {r.size} "
              f"(0x{r.size:X})")
        print(f"  lives in {holder} +0x{within:X} -> LBA {r.lba}, ISO byte 0x{d.iso_offset(r):X}")
        print(f"  allocation {r.alloc} bytes ({max(r.alloc - r.size, 0)} slack)")
        if sh:
            print(f"  starts on the sector of {sh[0].path}: in-place writes refused (use patch --grow)")
        if r.chain == 0:
            print("  chain 0: the same file is on Disc 1 and Disc 2 (patch both: cli.py patch --iso D1 --iso D2)")


def cmd_extract(iso: str, discpath: str, out: str, lba_dir=None) -> None:
    with Disc(iso, lba_dir) as d:
        r = d.rows.get("\\" + norm(discpath))
        if r is not None:
            data, name = d.read(r), r.path
        else:
            try:
                data, name = d.d.read(discpath), discpath
            except FileNotFoundError:
                d.row(discpath)
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_bytes(data)
    print(f"{name} ({len(data)} bytes) -> {out}")


def cmd_patch(iso: str, discpath: str, infile: str, pad=False, lba_dir=None) -> None:
    with Disc(iso, lba_dir, writable=True) as d:
        r = d.row(discpath)
        data = Path(infile).read_bytes()
        d.write(r, data, pad)
        print(f"patched {r.path} in {iso} ({r.size} -> {len(data)} bytes, verified)")


def cmd_tree(iso: str, moddir: str, pad=False, dry_run=False, lba_dir=None) -> None:
    root = Path(moddir)
    if not root.is_dir():
        sys.exit(f"{moddir}: not a directory")
    files = sorted(p for p in root.rglob("*") if p.is_file()
                   and not any(x.startswith(".") for x in p.relative_to(root).parts))
    if not files:
        sys.exit(f"{moddir}: no files found")
    patched = skipped = 0
    with Disc(iso, lba_dir, writable=not dry_run) as d:
        for p in files:
            discpath = "\\" + "\\".join(p.relative_to(root).parts)
            r = d.rows.get("\\" + norm(discpath))
            if r is None:
                print(f"  skip (not in this disc's index): {discpath}")
                skipped += 1
                continue
            data = p.read_bytes()
            if dry_run:
                fits = len(data) <= r.alloc and not d.d.sharers(r.entry)
                fit = ("same-size" if len(data) == r.size
                       else f"resize {len(data)}/{r.alloc}" if pad and fits
                       else "WOULD FAIL (needs patch --grow)")
                print(f"  would patch {r.path} [{fit}]")
                continue
            d.write(r, data, pad)
            print(f"  patched {r.path} ({len(data)} bytes)")
            patched += 1
    if not dry_run:
        print(f"{patched} patched, {skipped} skipped, all writes verified")


def add_commands(subparsers) -> None:
    """Nothing to register: cli.py registers repack-info / -extract / -patch / -tree
    and calls the cmd_* functions above."""


# ---------------------------------------------------------------------------
# self-test
# ---------------------------------------------------------------------------

def _lba_oracle(path: Path) -> Dict[str, Tuple[int, int]]:
    out = {}
    for line in path.read_text().splitlines():
        p = line.strip().split("|")
        if len(p) == 4:
            out[norm(p[3])] = (int(p[0], 16), int(p[1], 16))
    return out


def self_test() -> int:
    import contextlib
    import io
    import tempfile

    ok = True

    def check(cond, msg):
        nonlocal ok
        print(("ok    " if cond else "FAIL  ") + msg)
        ok &= bool(cond)

    def exits(fn, msg):
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                fn()
            check(False, msg)
        except SystemExit:
            check(True, msg)

    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        p = td / "syn.iso"
        disc_mod._synthetic_image(p)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cmd_info(str(p), "\\mnu\\us\\font0.bin")
        check("allocation 4096" in out.getvalue() and "X3.01" in out.getvalue(),
              "info: allocation and holding X3 file from the disc's own index")
        with contextlib.redirect_stdout(io.StringIO()):
            cmd_extract(str(p), "/mnu/us/menutext.txd", str(td / "m.txd"))
            cmd_extract(str(p), "SYSTEM.CNF", str(td / "s.cnf"))
        check((td / "m.txd").read_bytes() == b"menu text one\x00" * 40
              and (td / "s.cnf").read_bytes().startswith(b"BOOT2"), "extract: index entry and ISO file")
        (td / "same.bin").write_bytes(b"x" * 560)
        (td / "short.bin").write_bytes(b"short")
        (td / "big.bin").write_bytes(b"y" * 3000)
        with contextlib.redirect_stdout(io.StringIO()):
            cmd_patch(str(p), "mnu\\us\\menutext.txd", str(td / "same.bin"))
        with Disc(str(p)) as d:
            check(d.read(d.row("mnu\\us\\menutext.txd")) == b"x" * 560, "patch: same size in place")
        exits(lambda: cmd_patch(str(p), "mnu\\us\\menutext.txd", str(td / "short.bin")),
              "patch: a different size without --pad is refused")
        with contextlib.redirect_stdout(io.StringIO()):
            cmd_patch(str(p), "mnu\\us\\menutext.txd", str(td / "short.bin"), pad=True)
        with Disc(str(p)) as d:
            r = d.row("mnu\\us\\menutext.txd")
            check(r.size == 5 and d.read(r) == b"short",
                  "patch --pad: the index size field now says 5 (the old --pad left 560)")
        exits(lambda: cmd_patch(str(p), "mnu\\us\\menutext.txd", str(td / "big.bin"), pad=True),
              "patch --pad: past the allocation is refused (points at patch --grow)")
        exits(lambda: cmd_patch(str(p), "mnu\\us\\empty.bin", str(td / "short.bin"), pad=True),
              "patch: an entry on another file's sector is refused")
        mod = td / "mod" / "cf"
        mod.mkdir(parents=True)
        (mod / "Big.SB").write_bytes(b"\x66" * 3000)
        (mod / ".DS_Store").write_bytes(b"junk")
        with contextlib.redirect_stdout(io.StringIO()):
            cmd_tree(str(p), str(td / "mod"))
        with Disc(str(p)) as d:
            check(d.read(d.row("cf\\big.sb")) == b"\x66" * 3000, "tree: mirror tree patched, dotfiles ignored")
        check(set(Disc._read_root(p)) >= {"SYSTEM.CNF", "X3.00", "X3.01"},
              "_read_root still lists root files (textpack.IndexDisc)")

    discs = {k: os.environ[v] for k, v in (("D1", "XS3_D1"), ("D2", "XS3_D2"), ("PROTO", "XS3_PROTO"),
                                            ("JP1", "XS3_JP1")) if os.environ.get(v)}
    if not discs:
        print("SKIP  disc checks (set XS3_D1 / XS3_D2 / XS3_PROTO / XS3_JP1)")
    oracle = {0: HERE / "lba" / "Lba0.txt", 1: HERE / "lba" / "Lba1.txt", 2: HERE / "lba" / "Lba2.txt"}
    for k, path in discs.items():
        with Disc(path) as d:
            x300 = d.d.readers[0].sizes[0]
            if k in ("D1", "D2"):
                for c in d.d.chains:
                    want = _lba_oracle(oracle[c])
                    base = d.d.readers[c].sizes[0]
                    got = {norm(e.path): (e.byte_offset - base, e.size) for _, e in d.d.entries(c)}
                    same = sum(1 for p_, v in want.items() if got.get(p_) == v)
                    check(same == len(want) == len(got),
                          f"{k}: chain {c} index == lba/{oracle[c].name} oracle ({same}/{len(want)} rows)")
            if k == "PROTO":
                want = _lba_oracle(oracle[0])
                got = {norm(e.path): (e.byte_offset - x300, e.size) for _, e in d.d.entries(0)}
                diff = sum(1 for p_, v in got.items() if want.get(p_) != v)
                sized = sum(1 for p_, v in got.items() if p_ in want and want[p_][1] != v[1])
                check(diff > 0 and sized > 0,
                      f"PROTO: {diff} chain-0 rows sit elsewhere than USA lba/Lba0.txt says ({sized} differ in "
                      "size), so the index, not lba/, is what makes the prototype work")
                r = d.row("mnu\\us\\menutext.txd")
                check(len(d.read(r)) == 15486, "PROTO: menutext.txd 15,486 bytes via repack.Disc")
            if k == "JP1":
                r = d.row("mnu\\jp\\menutext.txd")
                check(r.size == 15574 and len(d.read(r)) == 15574, "JP1: mnu\\jp\\menutext.txd 15,574 bytes via repack.Disc")
                check(r.lba == 3110 + r.entry.sector, "JP1: LBA = X3.00 at 3110 + entry sector")
    print("self-test", "passed" if ok else "FAILED")
    return 0 if ok else 1


def main() -> None:
    a = sys.argv[1:]
    if a == ["--self-test"]:
        sys.exit(self_test())
    pad = "--pad" in a
    dry = "--dry-run" in a
    a = [x for x in a if x not in ("--pad", "--dry-run")]
    if len(a) >= 3 and a[0] == "info":
        cmd_info(a[1], a[2])
    elif len(a) >= 4 and a[0] == "extract":
        cmd_extract(a[1], a[2], a[3])
    elif len(a) >= 4 and a[0] == "patch":
        cmd_patch(a[1], a[2], a[3], pad)
    elif len(a) >= 3 and a[0] == "tree":
        cmd_tree(a[1], a[2], pad, dry)
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
