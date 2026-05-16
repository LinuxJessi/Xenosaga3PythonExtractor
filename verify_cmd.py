"""
verify_cmd.py — Cross-check extracted files against the manifest.

Three modes, all driven from the same subcommand:

* **presence** — every ``ok`` row in the manifest has a file on disk.
* **size**     — every present file matches the manifest's ``length`` (default).
* **hash**     — SHA-1 of each present file matches a recorded ``hashes.sha1``.

The size check is cheap (a ``stat`` call) and exposes the most common failure
mode of v0.1: silent truncation when a row was being read out of the wrong
address space. Hash verification needs ``hashes.sha1`` to exist, which means
the original ``extract`` was run with ``--hash``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional
import hashlib

import manifest


@dataclass
class VerifyStats:
    checked: int = 0
    missing: int = 0
    size_mismatch: int = 0
    hash_mismatch: int = 0
    hash_unknown: int = 0
    issues: List[str] = field(default_factory=list)

    def total_failures(self) -> int:
        return self.missing + self.size_mismatch + self.hash_mismatch


def _rel_from_in_game_path(p: str) -> Path:
    raw = (p or "").lstrip("\\/").replace("\\", "/")
    parts = [s for s in raw.split("/") if s not in ("", ".", "..")]
    return Path(*parts) if parts else Path("_unnamed_")


def _load_hashes(path: Path) -> Dict[str, str]:
    """Parse ``hashes.sha1`` (sha1sum-style: ``HEX  rel/path``)."""
    out: Dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.rstrip("\r\n")
        if not line:
            continue
        # split on the first run of 2+ spaces (sha1sum format uses "  ")
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        digest, rel = parts[0].strip(), parts[1].strip()
        out[rel] = digest
    return out


def _sha1_of(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha1()
    with path.open("rb") as f:
        while True:
            buf = f.read(chunk)
            if not buf:
                break
            h.update(buf)
    return h.hexdigest()


def verify(
    *,
    manifest_csv: Path,
    out_root: Path,
    check_hashes: bool = False,
    limit: Optional[int] = None,
) -> VerifyStats:
    if not manifest_csv.exists():
        raise FileNotFoundError(f"Missing manifest_merged.csv: {manifest_csv}")

    stats = VerifyStats()
    hashes_path = out_root / "_reports" / "hashes.sha1"
    expected_hashes = _load_hashes(hashes_path) if check_hashes else {}

    if check_hashes and not expected_hashes:
        stats.issues.append(
            f"[verify] hash check requested but {hashes_path} is empty or missing. "
            "Re-run `extract --hash` first."
        )

    for row in manifest.read_manifest(manifest_csv):
        if limit is not None and stats.checked >= limit:
            break
        if (row.get("map_status") or "").lower() != manifest.OK:
            continue
        rel = _rel_from_in_game_path(row.get("in_game_path", ""))
        path = out_root / rel
        stats.checked += 1

        if not path.exists():
            stats.missing += 1
            stats.issues.append(f"MISSING: {path}")
            continue

        try:
            expected_size = int(row.get("length") or 0)
        except (TypeError, ValueError):
            expected_size = None
        if expected_size is not None and path.stat().st_size != expected_size:
            stats.size_mismatch += 1
            stats.issues.append(
                f"SIZE: {path} got {path.stat().st_size}, expected {expected_size}"
            )

        if check_hashes:
            expected = expected_hashes.get(rel.as_posix())
            if expected is None:
                stats.hash_unknown += 1
            else:
                actual = _sha1_of(path)
                if actual != expected:
                    stats.hash_mismatch += 1
                    stats.issues.append(f"HASH: {path} got {actual}, expected {expected}")

    return stats


__all__ = ["VerifyStats", "verify"]
