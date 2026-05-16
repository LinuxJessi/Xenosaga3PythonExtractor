"""
code_extract.py — Pull non-X3 files (SLUS, OVL, IRX, SYSTEM.CNF) out of the
PS2 ISO so they can be inspected / disassembled.

The X3.* "bigfile" containers are already extracted by :mod:`iso_ops` /
``prep``. This module covers everything else: the main PS2 ELF
(``SLUS_NNN.NN``), the loadable overlays (``OV01.OVL`` etc.) and the IOP
side modules under ``IOP/``. Same 7-Zip dependency as ``prep``.

The function does **not** extract X3.* — pass an explicit exclude list to
7-Zip so the call stays fast (each X3.* is hundreds of MB and would defeat
the point of this step).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List

import iso_ops


@dataclass
class CodeExtractStats:
    files: int = 0
    total_bytes: int = 0


def extract_code(iso_path: Path, out_dir: Path, seven_zip: str | None = None) -> CodeExtractStats:
    """Extract everything from ``iso_path`` *except* the X3.* containers into
    ``out_dir`` using 7-Zip.

    Output mirrors the ISO's directory layout — typically::

        out_dir/
          SYSTEM.CNF
          SLUS_213.89                  (or SLUS_214.17 on Disc 2)
          OV01.OVL  OV02.OVL  OV04.OVL
          IOP/CRI_ADXI.IRX
          IOP/IOPRP300.IMG
          IOP/IOPSUB.IRX  LIBSD.IRX  MCMAN.IRX  MCSERV.IRX
          IOP/PADMAN.IRX  SDRDRV.IRX  SIO2MAN.IRX  SNDFI.IRX
    """
    if not iso_path.exists():
        raise FileNotFoundError(f"ISO not found: {iso_path}")
    out_dir.mkdir(parents=True, exist_ok=True)

    # 7-Zip's -xr! pattern excludes recursively. We pull everything else.
    iso_ops.sevenzip_extract(
        iso_path,
        out_dir,
        patterns=("*",),
        seven_zip=seven_zip,
        extra_args=("-xr!X3.*",),
    )

    stats = CodeExtractStats()
    for p in out_dir.rglob("*"):
        if p.is_file():
            stats.files += 1
            stats.total_bytes += p.stat().st_size
    return stats


def discover_executables(code_dir: Path) -> List[Path]:
    """Return ELF binaries (SLUS / OVL) in ``code_dir``, in deterministic order.

    Skips IRX modules (they're IOP-side and have a different binary format)
    and obvious non-ELF data files.
    """
    out: List[Path] = []
    for p in sorted(code_dir.iterdir()):
        if not p.is_file():
            continue
        # SLUS / OVL files only; IRX modules and SYSTEM.CNF live elsewhere.
        if p.suffix.upper() in (".OVL",) or p.name.startswith("SLUS_"):
            with p.open("rb") as f:
                if f.read(4) == b"\x7fELF":
                    out.append(p)
    return out


__all__ = ["CodeExtractStats", "extract_code", "discover_executables"]
