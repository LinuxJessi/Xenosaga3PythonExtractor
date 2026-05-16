"""
carve_jpeg.py — Extract JPGs concatenated inside container ``.bin`` files.

``mnu/credit.bin`` (boot publisher / developer logo splash) is a simple
container: small u32 header + N JPEGs stored back-to-back. The same pattern
could appear in other ``.bin`` files; this carver finds every
``FF D8 FF [E0|E1|DB]`` / ``FF D9`` pair and writes each JPEG to a fresh
file, without trusting the surrounding header at all.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple


_SOI = re.compile(rb"\xff\xd8\xff[\xe0\xe1\xdb]")
_EOI = re.compile(rb"\xff\xd9")


@dataclass
class CarveStats:
    containers_seen: int = 0
    jpegs_extracted: int = 0


def carve_one(data: bytes) -> List[Tuple[int, int]]:
    """Return ``[(start, end), ...]`` of every JPG embedded in ``data``."""
    sois = [m.start() for m in _SOI.finditer(data)]
    eois = [m.end() for m in _EOI.finditer(data)]
    out: List[Tuple[int, int]] = []
    ei = 0
    for s in sois:
        while ei < len(eois) and eois[ei] <= s:
            ei += 1
        if ei >= len(eois):
            break
        out.append((s, eois[ei]))
        ei += 1
    return out


def carve_file(src: Path, out_dir: Path, name_prefix: str | None = None) -> int:
    """Carve all JPGs from ``src`` into ``out_dir``. Returns count extracted."""
    data = src.read_bytes()
    spans = carve_one(data)
    if not spans:
        return 0
    out_dir.mkdir(parents=True, exist_ok=True)
    prefix = name_prefix or src.stem
    for i, (start, end) in enumerate(spans):
        (out_dir / f"{prefix}_{i:02d}.jpg").write_bytes(data[start:end])
    return len(spans)


def carve_tree(
    dump_root: Path,
    out_root: Path,
    *,
    container_names: Tuple[str, ...] = ("credit.bin",),
) -> CarveStats:
    """Scan ``dump_root`` for known JPG-bearing container .bin files and
    extract every embedded image under ``out_root``, mirroring the source
    directory tree.
    """
    stats = CarveStats()
    for p in dump_root.rglob("*"):
        if not p.is_file() or p.name.lower() not in {n.lower() for n in container_names}:
            continue
        stats.containers_seen += 1
        rel = p.relative_to(dump_root).with_suffix("")  # strip .bin
        dst = out_root / rel
        n = carve_file(p, dst)
        stats.jpegs_extracted += n
    return stats


__all__ = ["CarveStats", "carve_one", "carve_file", "carve_tree"]
