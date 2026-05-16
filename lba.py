"""
lba.py — Parse Xenosaga LBA tables (Python-only)

An LBA file lists entries of the form ::

    OFFSET|LENGTH|INDEX|\\path\\to\\file

where each of OFFSET, LENGTH and INDEX is 8 hex digits. Lines beginning with
``...`` (the original tool's section separators) and blank lines are skipped.

Each Lba file is its own byte-addressed space starting at 0 — see
``containers.py`` for the region model that consumes these entries.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Sequence
import re

LBA_LINE_RE = re.compile(r"^([0-9A-Fa-f]{8})\|([0-9A-Fa-f]{8})\|([0-9A-Fa-f]{8})\|(.+)$")

# Matches the first path segment after the leading backslash, e.g. "evt" in
# "\\evt\\s000100.xep". Single backslashes in the source data — the v0.1 regex
# used four backslashes here, which silently produced empty strings for every
# row and broke the by-top diagnostics.
_TOP_SEGMENT_RE = re.compile(r"^\\([^\\/]+)[\\/]")
_EXT_RE = re.compile(r"(\.[A-Za-z0-9]+)$")


@dataclass(frozen=True)
class LbaEntry:
    source: str          # filename of the LBA the entry came from
    offset: int          # byte offset within the source's region
    length: int          # byte length
    index: int           # ordinal/id from the table
    in_game_path: str    # original path as in the LBA
    ext: str             # lowercased extension (with dot) or ''
    top: str             # first path segment, or ''


def _ext(path: str) -> str:
    m = _EXT_RE.search(path or "")
    return m.group(1).lower() if m else ""


def _top(path: str) -> str:
    m = _TOP_SEGMENT_RE.match(path or "")
    return m.group(1) if m else ""


def parse_lba_line(line: str, *, source: str) -> Optional[LbaEntry]:
    """Parse one LBA line. Returns ``None`` for blanks and section separators."""
    line = line.strip()
    if not line or line.startswith("..."):
        return None
    m = LBA_LINE_RE.match(line)
    if not m:
        return None
    path = m.group(4).rstrip("\r\n")
    return LbaEntry(
        source=source,
        offset=int(m.group(1), 16),
        length=int(m.group(2), 16),
        index=int(m.group(3), 16),
        in_game_path=path,
        ext=_ext(path),
        top=_top(path),
    )


def load_lba_file(path: Path) -> List[LbaEntry]:
    """Parse a single LBA text file, skipping blanks and separators."""
    if not path.exists():
        return []
    rows: List[LbaEntry] = []
    for raw in path.read_text(errors="ignore").splitlines():
        row = parse_lba_line(raw, source=path.name)
        if row is not None:
            rows.append(row)
    return rows


def load_lba_files(paths: Sequence[Path]) -> List[LbaEntry]:
    """Parse and concatenate multiple LBA files in order. Source order is
    preserved so callers can tell which file each entry came from via
    :attr:`LbaEntry.source`."""
    out: List[LbaEntry] = []
    for p in paths:
        out.extend(load_lba_file(p))
    return out


def lba_max_end(path: Path) -> int:
    """Return the highest ``offset + length`` value in an LBA file.

    Used by the region auto-assigner to size each source's container chain.
    """
    end = 0
    for row in load_lba_file(path):
        e = row.offset + row.length
        if e > end:
            end = e
    return end


def discover_lba_files(work_dir: Path) -> List[Path]:
    """Return Lba*.txt files in ``work_dir/lba`` sorted by name.

    Only ``Lba0.txt``, ``Lba1.txt``, ``Lba2.txt`` are recognised — extras are
    ignored so a stray file in the directory doesn't accidentally re-route data.
    """
    lba_dir = work_dir / "lba"
    if not lba_dir.exists():
        return []
    known = ("Lba0.txt", "Lba1.txt", "Lba2.txt")
    return [lba_dir / name for name in known if (lba_dir / name).exists()]


__all__ = [
    "LBA_LINE_RE",
    "LbaEntry",
    "parse_lba_line",
    "load_lba_file",
    "load_lba_files",
    "lba_max_end",
    "discover_lba_files",
]
