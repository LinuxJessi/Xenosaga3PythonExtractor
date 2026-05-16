"""
scooper.py — Byte-slice extraction from the manifest into a mirrored tree.

Consumes the CSV manifest produced by :mod:`resolver` and the ``container_map.json``
(via :class:`containers.RegionMap`). For every row whose ``map_status`` is
``ok``, opens the right container(s), seeks, reads, writes.

Behaviour matches the original Lybac/xenounpack pipeline that the LBA tables
were generated for: ``open(bigfile) → seek(offset) → read(size) → write(path)``.
No header adjustments, no sector arithmetic — the LBA already stores byte
offsets and byte sizes.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional
import hashlib

from containers import RegionMap
import manifest


@dataclass
class ExtractStats:
    ok: int = 0
    err: int = 0
    skipped: int = 0


def _normalise_rel_path(p: str) -> Path:
    """Turn a game path like ``\\evt\\s000100.xep`` into a safe relative Path.

    Disallows traversal segments to keep us inside ``out_root``.
    """
    raw = (p or "").lstrip("\\/").replace("\\", "/")
    parts: List[str] = []
    for seg in raw.split("/"):
        if seg in ("", "."):
            continue
        if seg == "..":
            continue
        parts.append(seg)
    return Path(*parts) if parts else Path("_unnamed_")


def extract_all(
    manifest_csv: Path,
    region_map: RegionMap,
    x3_dir: Path,
    out_root: Path,
    *,
    dry_run: bool = False,
    write_hash: bool = False,
    progress_every: int = 1000,
    limit: Optional[int] = None,
) -> ExtractStats:
    """Extract every ``ok`` row from ``manifest_csv`` into ``out_root``.

    Sets up a ``_reports`` subdirectory next to ``out_root`` containing the
    extraction log and (optionally) a ``hashes.sha1`` file.
    """
    out_root.mkdir(parents=True, exist_ok=True)
    reports = out_root / "_reports"
    reports.mkdir(parents=True, exist_ok=True)
    log_path = reports / "extract.log"
    hashes_path = reports / "hashes.sha1" if write_hash else None
    if hashes_path and hashes_path.exists():
        hashes_path.unlink()

    stats = ExtractStats()
    processed = 0

    with log_path.open("w", encoding="utf-8") as log:
        for row in manifest.read_manifest(manifest_csv):
            status = (row.get("map_status") or "").lower()
            source = row.get("source", "")
            rel = _normalise_rel_path(row.get("in_game_path", ""))
            offset = int(row.get("offset") or 0)
            length = int(row.get("length") or 0)
            container = row.get("container", "")
            local_off = int(row.get("local_offset") or -1)

            if status != manifest.OK:
                stats.skipped += 1
                log.write(
                    f"SKIP[{status}]: {source} 0x{offset:08X}+0x{length:08X} -> {rel}\n"
                )
                continue

            dest = out_root / rel
            if dry_run:
                log.write(
                    f"DRY: {source} 0x{offset:08X}+0x{length:08X} {container}@0x{local_off:08X} -> {dest}\n"
                )
                stats.ok += 1
            else:
                try:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    hasher = hashlib.sha1() if write_hash else None
                    region = region_map.region_for(source)
                    with dest.open("wb") as outfp:
                        for chunk in region.iter_read(x3_dir, offset, length):
                            outfp.write(chunk)
                            if hasher:
                                hasher.update(chunk)
                    if hasher and hashes_path:
                        with hashes_path.open("a", encoding="utf-8") as hf:
                            hf.write(f"{hasher.hexdigest()}  {rel.as_posix()}\n")
                    log.write(
                        f"OK:  {source} 0x{offset:08X}+0x{length:08X} {container}@0x{local_off:08X} -> {dest}\n"
                    )
                    stats.ok += 1
                except Exception as exc:
                    log.write(
                        f"ERR: {source} 0x{offset:08X}+0x{length:08X} {container}@0x{local_off:08X} -> {dest} :: {exc}\n"
                    )
                    stats.err += 1

            processed += 1
            if progress_every and processed % progress_every == 0:
                log.write(f"[progress] {processed} rows processed\n")
            if limit is not None and processed >= limit:
                break

    return stats


__all__ = ["ExtractStats", "extract_all"]
