"""
regions.py — Assign LBA sources to their X3.* containers.

This step has to happen between ``prep`` (which discovers containers) and
``scan`` (which needs to know where each LBA source lives). The user can
either:

* Run :func:`auto_assign_regions`, which pairs LBA sources with containers by
  matching each source's max byte-end against a chain of containers in their
  natural order. If sizes don't fit, the function raises so the user is forced
  to assign manually rather than silently produce garbage.
* Run :func:`parse_manual_assignments` with CLI ``--assign`` strings like
  ``"Lba0.txt=X3.00"`` or ``"Lba1.txt=X3.01,X3.02"``.

Both routes produce a ``regions`` mapping that gets merged into
``container_map.json`` via :func:`merge_regions_into_map`.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Sequence, Tuple

from containers import Container, ContainerSet, ContainerError
from lba import lba_max_end


class RegionAssignmentError(Exception):
    """Raised when we can't safely assign LBA sources to containers."""


# ---------------------------------------------------------------------------
# Manual mapping (CLI --assign)
# ---------------------------------------------------------------------------

def parse_manual_assignments(
    assignments: Iterable[str],
    *,
    containers: ContainerSet,
    lba_sources: Iterable[str],
) -> Dict[str, List[str]]:
    """Parse strings like ``"Lba0.txt=X3.00"`` or ``"Lba1.txt=X3.01,X3.02"``.

    Validates that every named container exists and that every LBA source is
    a known source. Returns a dict keyed by LBA source filename.
    """
    valid_sources = set(lba_sources)
    out: Dict[str, List[str]] = {}
    for raw in assignments:
        if "=" not in raw:
            raise RegionAssignmentError(f"Bad --assign value: {raw!r} (expected SRC=NAME[,NAME...])")
        src, names = raw.split("=", 1)
        src = src.strip()
        chain = [n.strip() for n in names.split(",") if n.strip()]
        if not chain:
            raise RegionAssignmentError(f"Empty container list in {raw!r}")
        if src not in valid_sources:
            raise RegionAssignmentError(
                f"Unknown LBA source {src!r}; known: {sorted(valid_sources)}"
            )
        for name in chain:
            if name not in containers:
                raise RegionAssignmentError(
                    f"Container {name!r} not found in container set; "
                    f"known: {[c.name for c in containers]}"
                )
        if src in out:
            raise RegionAssignmentError(f"Duplicate --assign for {src!r}")
        out[src] = chain
    return out


# ---------------------------------------------------------------------------
# Auto-mapping (size matching)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AutoAssignment:
    regions: Dict[str, List[str]]
    rationale: str  # human-readable explanation of how we picked the mapping


def auto_assign_regions(
    *,
    containers: ContainerSet,
    lba_files: Sequence[Path],
    ignore: Iterable[str] = (),
) -> AutoAssignment:
    """Assign each LBA source a contiguous slice of the container list.

    Algorithm: walk the containers in their natural order, skipping any in
    ``ignore`` (typically catalog files like ``X3.00``, ``X3.10``, ``X3.20``
    that hold engine-internal indices rather than asset bytes). For each LBA
    in the order passed, consume containers one at a time until the cumulative
    size covers the LBA's max byte-end. If totals reconcile with no
    unaccounted-for containers, the assignment is unambiguous.

    Raises :class:`RegionAssignmentError` if the sizes don't fit, so the
    caller is forced to use ``--assign`` rather than silently producing
    garbage.
    """
    if not lba_files:
        raise RegionAssignmentError("No LBA files to assign")
    if len(containers) == 0:
        raise RegionAssignmentError("ContainerSet is empty")

    ignore_set = set(ignore)
    container_list: List[Container] = [c for c in containers if c.name not in ignore_set]
    if not container_list:
        raise RegionAssignmentError(
            f"All containers were excluded by --ignore {sorted(ignore_set)}"
        )

    needs: List[Tuple[str, int]] = [(f.name, lba_max_end(f)) for f in lba_files]

    regions: Dict[str, List[str]] = {}
    rationale_lines: List[str] = []
    if ignore_set:
        rationale_lines.append(f"  ignored containers: {sorted(ignore_set)}")
    ci = 0
    for src, max_end in needs:
        chain: List[str] = []
        covered = 0
        while covered < max_end:
            if ci >= len(container_list):
                raise RegionAssignmentError(
                    f"Ran out of containers while covering {src} "
                    f"(needs 0x{max_end:X}, covered 0x{covered:X})"
                )
            c = container_list[ci]
            chain.append(c.name)
            covered += c.size
            ci += 1
        slack = covered - max_end
        rationale_lines.append(
            f"  {src}: needs 0x{max_end:X}, got 0x{covered:X}"
            f"{' (slack 0x{:X})'.format(slack) if slack > 0x10_0000 else ''} -> {chain}"
        )
        regions[src] = chain

    if ci != len(container_list):
        leftovers = [c.name for c in container_list[ci:]]
        raise RegionAssignmentError(
            f"Leftover containers after auto-assign: {leftovers}. "
            f"Sizes did not reconcile — review with --ignore or use --assign manually."
        )

    rationale = "auto-assigned by walking LBA-end totals through container list:\n" + "\n".join(
        rationale_lines
    )
    return AutoAssignment(regions=regions, rationale=rationale)


# ---------------------------------------------------------------------------
# Validation (post-assignment sanity check)
# ---------------------------------------------------------------------------

def validate_regions(
    *,
    containers: ContainerSet,
    regions: Mapping[str, Sequence[str]],
    lba_files: Sequence[Path],
    ignored: Iterable[str] = (),
) -> List[str]:
    """Return a list of human-readable problems with the proposed assignment.

    ``ignored`` names containers the caller deliberately excluded (catalogs like
    ``X3.00``/``X3.10``/``X3.20``); we won't flag those as unassigned.

    Returns an empty list when the assignment is sane.
    """
    problems: List[str] = []
    by_src = {f.name: f for f in lba_files}
    ignored_set = set(ignored)

    used: List[str] = []
    for src, names in regions.items():
        for n in names:
            if n in used:
                problems.append(f"container {n!r} assigned to multiple regions (latest: {src})")
            used.append(n)
        if src not in by_src:
            problems.append(f"region {src!r} has no matching LBA file on disk")
            continue
        chain_size = sum(containers.get(n).size for n in names)
        max_end = lba_max_end(by_src[src])
        if max_end > chain_size:
            problems.append(
                f"region {src!r}: LBA max-end 0x{max_end:X} exceeds container chain size 0x{chain_size:X}"
            )

    for c in containers:
        if c.name not in used and c.name not in ignored_set:
            problems.append(f"container {c.name!r} is not assigned to any region")

    return problems


__all__ = [
    "AutoAssignment",
    "RegionAssignmentError",
    "auto_assign_regions",
    "parse_manual_assignments",
    "validate_regions",
]
