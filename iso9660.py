"""iso9660.py — Minimal pure-Python ISO9660 reader (no 7-Zip).

Borrowed from Xenosaga2PythonExtractor/iso9660.py (itself a copy of
Xenosaga1PythonExtractor/iso9660.py), 2026-11-20. What changed for Episode III:

* the layer-1 zero-length root fix from the XS1 kit's working copy (Xenosaga I
  Reloaded) is carried over; it never fires on XS3, whose three known images
  (USA Disc 1, USA Disc 2, the May 2006 prototype) are all single-volume;
* ``make_test_image`` builds a tiny synthetic ISO9660 image, so this module and
  the write primitives in ``disc.py`` can be self-tested without touching (or
  copying) a real 4 GB disc;
* ``self_test`` and ``add_commands`` (``iso-ls``) per the kit convention.

Verified 2026-11-20 on all three XS3 images: every root file is found
(SYSTEM.CNF, SLUS_213.89 / SLUS_214.17, OV01/02/04.OVL, X3.00-X3.02 and
X3.10-X3.13 or X3.20-X3.23), ``boot_elf_name`` follows SYSTEM.CNF's BOOT2 line,
and the bigfiles sit back to back from LBA 3114 (X3.00).

Only what the kit needs is implemented: the primary volume descriptor, a
recursive directory walk, extent reads via mmap.
"""
from __future__ import annotations

import mmap
import re
import struct
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

SECTOR = 2048

# PS2 boot executables are named <region>_<num>.<num>: SLUS_213.89 (USA),
# SLPS_*, SLES_*, SCPS_*, etc.
BOOT_RE = re.compile(r"^S[A-Z]{3}_\d{3}\.\d{2}$")


@dataclass(frozen=True)
class IsoFile:
    path: str       # backslash-joined, e.g. "IOP\\PADMAN.IRX"
    lba: int
    size: int
    is_dir: bool
    layer: int = 0  # 0 = first volume, 1 = second (dual-layer) volume
    record_off: int = 0  # byte offset of the directory record in the image


class IsoImage:
    def __init__(self, iso_path: str | Path):
        self.path = Path(iso_path)
        self._fh = open(self.path, "rb")
        self.mm = mmap.mmap(self._fh.fileno(), 0, access=mmap.ACCESS_READ)
        pvd = self.mm[16 * SECTOR: 17 * SECTOR]
        if pvd[1:6] != b"CD001":
            self.close()
            raise ValueError(f"{iso_path}: no ISO9660 PVD at sector 16")
        self.volume_sectors = struct.unpack_from("<I", pvd, 80)[0]
        root_lba = struct.unpack_from("<I", pvd, 158)[0]
        root_len = struct.unpack_from("<I", pvd, 166)[0]
        self.files: Dict[str, IsoFile] = {}
        for f in self._walk(root_lba, root_len, ""):
            self.files[f.path] = f
        # second volume (DVD-9 layer 1): PVD sits at layer 0's volume end,
        # its LBAs are relative to 16 sectors before that PVD
        self.layer2_base: Optional[int] = None
        self.layer2_pvd_sector: Optional[int] = None
        l2 = self.volume_sectors
        if (l2 + 1) * SECTOR <= len(self.mm) and self.mm[l2 * SECTOR + 1:l2 * SECTOR + 6] == b"CD001":
            pvd2 = self.mm[l2 * SECTOR:(l2 + 1) * SECTOR]
            base = l2 - 16
            self.layer2_base = base
            self.layer2_pvd_sector = l2
            self.layer2_volume_sectors = struct.unpack_from("<I", pvd2, 80)[0]
            r_lba = struct.unpack_from("<I", pvd2, 158)[0]
            r_len = struct.unpack_from("<I", pvd2, 166)[0]
            if r_len == 0:
                # Xenosaga I Reloaded masters its layer-1 root record with data
                # length 0 (XS1 kit fix); all its records fit in one sector.
                r_len = SECTOR
            for f in self._walk(base + r_lba, r_len, "", base=base, layer=1):
                self.files.setdefault(f.path, f)

    # -- filesystem ---------------------------------------------------------

    def _walk(self, lba: int, length: int, prefix: str,
              base: int = 0, layer: int = 0) -> Iterator[IsoFile]:
        d = self.mm[lba * SECTOR: lba * SECTOR + length]
        i = 0
        while i < len(d):
            rl = d[i]
            if rl == 0:  # records never span sectors; skip to next
                i = (i // SECTOR + 1) * SECTOR
                continue
            nl = d[i + 32]
            if nl == 1 and d[i + 33] in (0, 1):  # "." / ".."
                i += rl
                continue
            elba = struct.unpack_from("<I", d, i + 2)[0] + base
            elen = struct.unpack_from("<I", d, i + 10)[0]
            is_dir = bool(d[i + 25] & 2)
            name = d[i + 33: i + 33 + nl].decode("ascii", "replace").split(";")[0]
            f = IsoFile(prefix + name, elba, elen, is_dir, layer, lba * SECTOR + i)
            yield f
            if is_dir:
                yield from self._walk(elba, elen, prefix + name + "\\", base, layer)
            i += rl

    def find(self, name: str) -> Optional[IsoFile]:
        """Case-insensitive lookup; '/' or '\\' separators, leading separator optional."""
        key = name.replace("/", "\\").lstrip("\\").split(";")[0]
        f = self.files.get(key)
        if f is not None:
            return f
        low = key.lower()
        for k, v in self.files.items():
            if k.lower() == low:
                return v
        return None

    # -- reads --------------------------------------------------------------

    def read_file(self, name: str, offset: int = 0, length: int | None = None) -> bytes:
        f = self.files[name]
        length = f.size - offset if length is None else min(length, f.size - offset)
        start = f.lba * SECTOR + offset
        return self.mm[start: start + length]

    def boot_elf_name(self) -> Optional[str]:
        """Name of the boot executable (e.g. "SLUS_213.89").

        Read from SYSTEM.CNF's BOOT2 line (``BOOT2 = cdrom0:\\SLUS_213.89;1``),
        falling back to the first root file matching the serial pattern.
        """
        if "SYSTEM.CNF" in self.files:
            cnf = self.read_file("SYSTEM.CNF").decode("ascii", "replace")
            m = re.search(r"BOOT2\s*=\s*cdrom0?:\\?([^;\r\n]+)", cnf)
            if m:
                name = m.group(1).strip().split("\\")[-1]
                if name in self.files:
                    return name
        for name, f in self.files.items():
            if not f.is_dir and BOOT_RE.match(name):
                return name
        return None

    @property
    def volume_end(self) -> int:
        """Byte offset where the ISO9660 volume claims to end."""
        return self.volume_sectors * SECTOR

    @property
    def image_size(self) -> int:
        return len(self.mm)

    def close(self) -> None:
        try:
            self.mm.close()
        finally:
            self._fh.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


# ------------------------------------------------------ synthetic test image

def _dir_record(name: bytes, lba: int, size: int, is_dir: bool) -> bytes:
    nl = len(name)
    rl = 33 + nl + (1 - nl % 2)          # pad to even length
    r = bytearray(rl)
    r[0] = rl
    struct.pack_into("<I", r, 2, lba)
    struct.pack_into(">I", r, 6, lba)
    struct.pack_into("<I", r, 10, size)
    struct.pack_into(">I", r, 14, size)
    r[25] = 2 if is_dir else 0
    struct.pack_into("<H", r, 28, 1)
    struct.pack_into(">H", r, 30, 1)
    r[32] = nl
    r[33:33 + nl] = name
    return bytes(r)


def make_test_image(path: str | Path, files: List[Tuple[str, bytes]],
                    tail_sectors: int = 0) -> Dict[str, int]:
    """Write a minimal single-volume ISO9660 image holding ``files`` (root level
    only, in the given order, each starting on a sector boundary and packed back
    to back, as the X3.* bigfiles are on the real discs). ``tail_sectors`` adds
    zero padding after the last file inside the volume. Returns name -> LBA.
    For self-tests only; it is not a mastering tool."""
    root_lba = 18
    lbas: Dict[str, int] = {}
    nxt = root_lba + 1
    for name, data in files:
        lbas[name] = nxt
        nxt += max(1, (len(data) + SECTOR - 1) // SECTOR)
    total = nxt + tail_sectors
    recs = _dir_record(b"\x00", root_lba, SECTOR, True) + _dir_record(b"\x01", root_lba, SECTOR, True)
    for name, data in files:
        recs += _dir_record(name.encode("ascii") + b";1", lbas[name], len(data), False)
    if len(recs) > SECTOR:
        raise ValueError("make_test_image: root directory must fit one sector")
    img = bytearray(total * SECTOR)
    pvd = bytearray(SECTOR)
    pvd[0] = 1
    pvd[1:6] = b"CD001"
    pvd[6] = 1
    struct.pack_into("<I", pvd, 80, total)
    struct.pack_into(">I", pvd, 84, total)
    pvd[156:156 + 34] = _dir_record(b"\x00", root_lba, SECTOR, True)
    img[16 * SECTOR:17 * SECTOR] = pvd
    img[17 * SECTOR:17 * SECTOR + 7] = b"\xffCD001\x01"   # set terminator
    img[root_lba * SECTOR:root_lba * SECTOR + len(recs)] = recs
    for name, data in files:
        o = lbas[name] * SECTOR
        img[o:o + len(data)] = data
    Path(path).write_bytes(bytes(img))
    return lbas


# ------------------------------------------------------------------ self-test

def _disc_paths() -> Dict[str, str]:
    import os
    return {k: os.environ[v] for k, v in (("D1", "XS3_D1"), ("D2", "XS3_D2"), ("PROTO", "XS3_PROTO"))
            if os.environ.get(v)}


def self_test() -> int:
    import tempfile
    ok = True

    def check(cond, msg):
        nonlocal ok
        print(("ok    " if cond else "FAIL  ") + msg)
        ok &= bool(cond)

    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "t.iso"
        cnf = b"BOOT2 = cdrom0:\\SLUS_999.99;1\r\nVER = 1.00\r\n"
        lbas = make_test_image(p, [("SYSTEM.CNF", cnf), ("SLUS_999.99", b"\x7fELF" + bytes(3000)),
                                   ("X3.00", bytes([1]) + bytes(SECTOR - 1))])
        iso = IsoImage(p)
        check(set(iso.files) == {"SYSTEM.CNF", "SLUS_999.99", "X3.00"}, "synthetic image: root walk finds 3 files")
        check(iso.files["X3.00"].lba == lbas["X3.00"], "synthetic image: extents as written")
        check(iso.boot_elf_name() == "SLUS_999.99", "boot_elf_name follows SYSTEM.CNF BOOT2")
        check(iso.read_file("SYSTEM.CNF") == cnf, "read_file returns the exact bytes")
        check(iso.find("/system.cnf") is iso.files["SYSTEM.CNF"], "find is case-insensitive, any separator")
        check(iso.volume_sectors * SECTOR == iso.image_size, "volume space covers the image")
        iso.close()
        try:
            bad = Path(td) / "bad.iso"
            bad.write_bytes(bytes(20 * SECTOR))
            IsoImage(bad)
            check(False, "a non-ISO file is refused")
        except ValueError:
            check(True, "a non-ISO file is refused")

    discs = _disc_paths()
    if not discs:
        print("SKIP  disc checks (set XS3_D1 / XS3_D2 / XS3_PROTO)")
    want_boot = {"D1": "SLUS_213.89", "D2": "SLUS_214.17", "PROTO": "SLUS_213.89"}
    for k, path in discs.items():
        with IsoImage(path) as iso:
            check(iso.boot_elf_name() == want_boot[k], f"{k}: boot executable {iso.boot_elf_name()}")
            check(iso.files["X3.00"].lba == 3114, f"{k}: X3.00 at LBA 3114")
            check(iso.layer2_base is None, f"{k}: single volume")
    print("self-test", "passed" if ok else "FAILED")
    return 0 if ok else 1


# ------------------------------------------------------------------------ CLI

def _cmd_iso_ls(a) -> int:
    with IsoImage(a.iso) as iso:
        print(f"# {a.iso}: {iso.volume_sectors} volume sectors, image {iso.image_size // SECTOR} sectors, "
              f"boot {iso.boot_elf_name()}")
        for f in sorted(iso.files.values(), key=lambda f: (f.lba, f.path)):
            print(f"{f.lba:>8} {f.size:>12} {'d' if f.is_dir else '-'} {f.path}")
    return 0


def add_commands(subparsers) -> None:
    """Register ``iso-ls`` (the ISO9660 filesystem of an image, by LBA)."""
    p = subparsers.add_parser("iso-ls", help="list the ISO9660 filesystem (LBA, size, path) of an image")
    p.add_argument("--iso", required=True)
    p.set_defaults(func=_cmd_iso_ls)


if __name__ == "__main__":
    if sys.argv[1:] == ["--self-test"]:
        sys.exit(self_test())
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    add_commands(ap.add_subparsers(dest="cmd", required=True))
    a = ap.parse_args()
    sys.exit(a.func(a))
