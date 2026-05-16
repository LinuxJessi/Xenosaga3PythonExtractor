"""
toc.py — Human-auditable summaries of the merged LBA tables.

Used by the ``toc`` subcommand to print a one-pager of "what's in the LBAs?"
before any extraction work happens. Reads the same LBA text files :mod:`lba`
consumes; never touches binary containers.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence
import csv
import json

from lba import LbaEntry, load_lba_files


def _summarise_rows(
    rows: Sequence[LbaEntry],
    *,
    examples_per_top: int = 10,
) -> Dict[str, Any]:
    by_top = Counter(r.top for r in rows)
    by_ext = Counter(r.ext for r in rows)
    by_source = Counter(r.source for r in rows)
    by_source_top: Dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        by_source_top[r.source][r.top] += 1

    examples_by_top: Dict[str, List[str]] = defaultdict(list)
    if examples_per_top > 0:
        for r in rows:
            bucket = examples_by_top[r.top]
            if len(bucket) < examples_per_top:
                bucket.append(r.in_game_path)

    return {
        "counts": {
            "total": len(rows),
            "by_top": dict(by_top),
            "by_ext": dict(by_ext),
            "by_source": dict(by_source),
            "by_source_top": {k: dict(v) for k, v in by_source_top.items()},
        },
        "examples_by_top": examples_by_top,
    }


def build_toc_headers(
    lba_files: Sequence[Path],
    out_json: Path,
    *,
    examples_per_top: int = 10,
) -> Dict[str, Any]:
    rows = load_lba_files(lba_files)
    toc = _summarise_rows(rows, examples_per_top=examples_per_top)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(toc, indent=2), encoding="utf-8")
    return toc


def build_toc_from_csv(
    merged_csv: Path,
    out_json: Path,
    *,
    examples_per_top: int = 10,
) -> Dict[str, Any]:
    if not merged_csv.exists():
        raise FileNotFoundError(f"Merged CSV not found: {merged_csv}")
    rows: List[LbaEntry] = []
    with merged_csv.open(newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            rows.append(
                LbaEntry(
                    source=row.get("source", "csv"),
                    offset=int(row["offset"]),
                    length=int(row["length"]),
                    index=int(row["index"]),
                    in_game_path=row["in_game_path"],
                    ext=row.get("ext", ""),
                    top=row.get("top", ""),
                )
            )
    toc = _summarise_rows(rows, examples_per_top=examples_per_top)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(toc, indent=2), encoding="utf-8")
    return toc


def format_human_summary(toc: Mapping[str, Any]) -> str:
    lines: List[str] = []
    counts = toc.get("counts", {})
    lines.append(f"Total rows: {counts.get('total', 0)}")
    by_source = counts.get("by_source", {})
    if by_source:
        lines.append("By LBA source:")
        for k, v in sorted(by_source.items()):
            lines.append(f"  {k}: {v}")
    by_top = counts.get("by_top", {})
    if by_top:
        lines.append("By top folder (top 10):")
        for k, v in sorted(by_top.items(), key=lambda kv: kv[1], reverse=True)[:10]:
            lines.append(f"  {k or '<root>'}: {v}")
    by_ext = counts.get("by_ext", {})
    if by_ext:
        lines.append("By extension (top 10):")
        for k, v in sorted(by_ext.items(), key=lambda kv: kv[1], reverse=True)[:10]:
            lines.append(f"  {k or '<none>'}: {v}")
    return "\n".join(lines)


__all__ = ["build_toc_headers", "build_toc_from_csv", "format_human_summary"]
