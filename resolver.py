"""
resolver.py — Map LBA rows to ``(container, local_offset)`` using a RegionMap.

Reads:
  • LBA text files (Lba0/Lba1/Lba2.txt) for the rows themselves.
  • ``container_map.json`` for the LBA-source → container assignment.

Writes:
  • ``out/manifest_merged.csv`` with one row per LBA entry, annotated with the
    target container and local offset.
  • ``out/dry_run_summary.json`` with counts per ``map_status``.

If an LBA source is missing from the region map, every row from that source is
marked ``unknown_region`` rather than silently dropped or sent somewhere wrong.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Dict, List, Sequence, Tuple
import json

from containers import RegionMap, OffsetOutOfBounds
from lba import LbaEntry, load_lba_files
import manifest


# ---------------------------------------------------------------------------
# Optional magic sniffing (diagnostics only — never affects mapping decisions)
# ---------------------------------------------------------------------------

ADX_HDR0 = b"\x80\x00"
SFD_TAG = b"Sofdec"
CRID_TAG = b"CRID"
BMP_HDR = b"BM"
JPG_HDR = b"\xFF\xD8"
PNG_HDR = b"\x89PNG"


def guess_type_magic(buf: bytes) -> str:
    """Heuristic header sniff — for logs, not for routing decisions."""
    b = buf or b""
    if b.startswith(BMP_HDR):
        return "bmp?"
    if b.startswith(JPG_HDR):
        return "jpg?"
    if b.startswith(PNG_HDR):
        return "png?"
    if b.startswith(ADX_HDR0) or b[:64].find(b"CRI") >= 0:
        return "adx?"
    if b[:256].find(SFD_TAG) >= 0 or b[:64].find(CRID_TAG) >= 0:
        return "sfd?"
    if b[:4].isalnum():
        return "txt?"
    return ""


def _sniff(x3_dir: Path, container_name: str, local_off: int, probe_bytes: int) -> str:
    if probe_bytes <= 0:
        return ""
    p = x3_dir / container_name
    if not p.exists():
        return ""
    with p.open("rb") as f:
        f.seek(max(local_off, 0))
        return guess_type_magic(f.read(probe_bytes))


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------

def _entry_spans(region, entry: LbaEntry) -> Tuple[str, int, List[str], str]:
    """Resolve one LBA entry through a region. Returns
    ``(container, local_offset, all_containers_touched, map_status)``."""
    try:
        first_container, local_offset = region.resolve(entry.offset)
    except OffsetOutOfBounds:
        return "", -1, [], manifest.UNMAPPED
    end = entry.offset + entry.length
    if end > region.total_size:
        return first_container.name, local_offset, [first_container.name], manifest.OUT_OF_BOUNDS
    # Collect every container the slice touches.
    touched: List[str] = [first_container.name]
    cursor = entry.offset + (first_container.size - local_offset)
    while cursor < end:
        try:
            cont, _ = region.resolve(cursor)
        except OffsetOutOfBounds:
            return first_container.name, local_offset, touched, manifest.OUT_OF_BOUNDS
        if cont.name != touched[-1]:
            touched.append(cont.name)
        cursor += cont.size
    return first_container.name, local_offset, touched, manifest.OK


def map_rows_to_containers(
    lba_files: Sequence[Path],
    region_map: RegionMap,
    x3_dir: Path,
    out_csv: Path,
    out_summary: Path,
    *,
    sniff: bool = False,
    probe_bytes: int = 256,
) -> Tuple[List[manifest.ManifestRow], Dict[str, int]]:
    """Walk every LBA row, resolve it through the region map, and write CSV+JSON."""
    rows = load_lba_files(lba_files)
    out_rows: List[manifest.ManifestRow] = []
    counts: Counter = Counter()

    for r in rows:
        if not region_map.has(r.source):
            out_rows.append(
                manifest.ManifestRow(
                    source=r.source,
                    offset=r.offset,
                    length=r.length,
                    index=r.index,
                    in_game_path=r.in_game_path,
                    ext=r.ext,
                    top=r.top,
                    region=r.source,
                    container="",
                    local_offset=-1,
                    spans_containers="",
                    map_status=manifest.UNKNOWN_REGION,
                    magic="",
                )
            )
            counts[manifest.UNKNOWN_REGION] += 1
            continue

        region = region_map.region_for(r.source)
        cont_name, local_off, touched, status = _entry_spans(region, r)
        magic = _sniff(x3_dir, cont_name, local_off, probe_bytes) if (sniff and status == manifest.OK) else ""

        out_rows.append(
            manifest.ManifestRow(
                source=r.source,
                offset=r.offset,
                length=r.length,
                index=r.index,
                in_game_path=r.in_game_path,
                ext=r.ext,
                top=r.top,
                region=r.source,
                container=cont_name,
                local_offset=int(local_off),
                spans_containers=",".join(touched),
                map_status=status,
                magic=magic,
            )
        )
        counts[status] += 1

    manifest.write_manifest(out_csv, out_rows)
    out_summary.parent.mkdir(parents=True, exist_ok=True)
    out_summary.write_text(
        json.dumps({"counts": dict(counts), "total": len(out_rows)}, indent=2),
        encoding="utf-8",
    )
    return out_rows, dict(counts)


__all__ = ["guess_type_magic", "map_rows_to_containers"]
