"""
manifest.py — CSV schema for extraction manifests.

The manifest is the boundary between :mod:`resolver` (which decides where each
LBA row lives) and :mod:`scooper` (which writes the bytes). Keeping the schema
in one place means both sides stay in sync without import cycles.

Columns:

* ``source`` — name of the LBA file the row came from (``Lba0.txt``, ...).
* ``offset`` — region-local byte offset (decimal).
* ``length`` — byte length (decimal).
* ``index`` — original index field from the LBA (decimal).
* ``in_game_path`` — original ``\\foo\\bar.dat`` path.
* ``ext`` — lowercased extension or empty.
* ``top`` — first path segment or empty.
* ``region`` — LBA source name; same as ``source`` today, named separately so
  future schemes can let multiple sources share a region.
* ``container`` — name of the X3.* file that the row's first byte lives in.
  Empty when ``map_status != "ok"``.
* ``local_offset`` — byte offset inside that container (decimal). ``-1`` when
  the row couldn't be mapped.
* ``spans_containers`` — comma-separated list of all containers the row
  touches. Single-name when the row stays inside one container.
* ``map_status`` — one of ``ok``, ``unmapped``, ``out_of_bounds``,
  ``unknown_region``.
* ``magic`` — optional sniff result (``adx?``, ``bmp?``, ...); empty by default.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Iterator, List, Sequence
import csv

FIELDS: Sequence[str] = (
    "source",
    "offset",
    "length",
    "index",
    "in_game_path",
    "ext",
    "top",
    "region",
    "container",
    "local_offset",
    "spans_containers",
    "map_status",
    "magic",
)

OK = "ok"
UNMAPPED = "unmapped"
OUT_OF_BOUNDS = "out_of_bounds"
UNKNOWN_REGION = "unknown_region"


@dataclass
class ManifestRow:
    source: str
    offset: int
    length: int
    index: int
    in_game_path: str
    ext: str
    top: str
    region: str
    container: str
    local_offset: int
    spans_containers: str
    map_status: str
    magic: str = ""


def write_manifest(path: Path, rows: Iterable[ManifestRow]) -> None:
    """Write manifest CSV with the canonical column order."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(FIELDS))
        w.writeheader()
        for r in rows:
            w.writerow(asdict(r))


def read_manifest(path: Path) -> Iterator[dict]:
    """Stream rows as plain dicts. Integer columns are *not* parsed — callers
    do their own ``int(row["offset"])`` so they can decide what to do with
    malformed input."""
    with path.open(newline="", encoding="utf-8") as f:
        yield from csv.DictReader(f)


__all__ = [
    "FIELDS",
    "OK",
    "UNMAPPED",
    "OUT_OF_BOUNDS",
    "UNKNOWN_REGION",
    "ManifestRow",
    "write_manifest",
    "read_manifest",
]
