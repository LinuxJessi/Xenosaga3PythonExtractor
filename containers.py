"""
containers.py — Container set + region addressing for the Xenosaga III dump.

Each Xenosaga III disc carries a handful of large data files (named like
``X3.00``, ``X3.01``, ...). The disc also carries three index files — Lba0.txt,
Lba1.txt, Lba2.txt — each of which is its own byte-addressed namespace starting
from offset 0. So a row that says ``00000000|0000AC65|...`` in Lba1 does NOT
refer to the same place on disc as ``00000000|...`` in Lba0.

In v0.1 the resolver concatenated the X3.* parts into a single flat space and
fed every LBA row into it, which silently produced garbage for every row in
Lba1 and Lba2.

This module is the corrected data model:

* :class:`Container` — one X3.* file on disk plus its size.
* :class:`ContainerSet` — every container known after running 7-Zip.
* :class:`Region` — an ordered chain of containers belonging to one LBA source.
  Offsets inside a region are translated by walking the chain in order.
* :class:`RegionMap` — the full LBA-source-name → region mapping persisted in
  ``container_map.json``.

The v2 ``container_map.json`` schema::

    {
      "version": 2,
      "containers": [{"name": "X3.00", "size": 1647092736}, ...],
      "regions":   {"Lba0.txt": ["X3.00"], "Lba1.txt": ["X3.01", "X3.02"]}
    }

If ``regions`` is absent or empty, downstream steps refuse to run and ask the
caller to run ``cli.py map-regions`` first.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterator, List, Mapping, Optional, Sequence, Tuple
import json


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class ContainerError(Exception):
    """Base class for container/region errors."""


class UnknownContainer(ContainerError):
    """Referenced container name is not in the ContainerSet."""


class UnknownRegion(ContainerError):
    """Asked to resolve an LBA source that has no region assigned."""


class OffsetOutOfBounds(ContainerError):
    """Offset+length walks past the end of a region's container chain."""


# ---------------------------------------------------------------------------
# Container + ContainerSet
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Container:
    """One X3.* file on disk."""
    name: str
    size: int


class ContainerSet:
    """An ordered collection of containers, keyed by name."""

    def __init__(self, containers: Sequence[Container]):
        if len({c.name for c in containers}) != len(containers):
            raise ContainerError("Duplicate container names in set")
        self._by_name: Dict[str, Container] = {c.name: c for c in containers}
        self._order: Tuple[Container, ...] = tuple(containers)

    # construction ---------------------------------------------------------

    @classmethod
    def from_dicts(cls, dicts: Sequence[Mapping[str, object]]) -> "ContainerSet":
        return cls([Container(name=str(d["name"]), size=int(d["size"])) for d in dicts])

    # access ---------------------------------------------------------------

    def __iter__(self) -> Iterator[Container]:
        return iter(self._order)

    def __len__(self) -> int:
        return len(self._order)

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and name in self._by_name

    def get(self, name: str) -> Container:
        try:
            return self._by_name[name]
        except KeyError as exc:
            raise UnknownContainer(name) from exc

    @property
    def order(self) -> Tuple[Container, ...]:
        return self._order


# ---------------------------------------------------------------------------
# Region
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _ContainerSlot:
    container: Container
    base: int  # cumulative offset of this container's first byte in the region


class Region:
    """An LBA source's byte address space, backed by one or more containers."""

    def __init__(self, lba_source: str, containers: Sequence[Container]):
        if not containers:
            raise ContainerError(f"Region {lba_source!r} has no containers")
        self.lba_source = lba_source
        slots: List[_ContainerSlot] = []
        base = 0
        for c in containers:
            slots.append(_ContainerSlot(container=c, base=base))
            base += c.size
        self._slots: Tuple[_ContainerSlot, ...] = tuple(slots)
        self._total: int = base

    # introspection --------------------------------------------------------

    @property
    def total_size(self) -> int:
        return self._total

    @property
    def container_names(self) -> Tuple[str, ...]:
        return tuple(s.container.name for s in self._slots)

    # resolution -----------------------------------------------------------

    def resolve(self, offset: int) -> Tuple[Container, int]:
        """Map a region-local offset to (container, local_offset).

        Raises :class:`OffsetOutOfBounds` if the offset is not inside any
        container in the chain.
        """
        if offset < 0 or offset >= self._total:
            raise OffsetOutOfBounds(
                f"Offset 0x{offset:X} not inside region {self.lba_source!r} (size 0x{self._total:X})"
            )
        for slot in self._slots:
            end = slot.base + slot.container.size
            if slot.base <= offset < end:
                return slot.container, offset - slot.base
        raise OffsetOutOfBounds(f"Offset 0x{offset:X} fell through region chain")

    def iter_read(
        self,
        x3_dir: Path,
        offset: int,
        length: int,
        *,
        chunk_size: int = 2 * 1024 * 1024,
    ) -> Iterator[bytes]:
        """Yield bytes for ``[offset, offset+length)`` across container boundaries.

        Reuses an open file handle per container, so a slice that walks across
        two containers does at most two ``open`` calls.
        """
        if length < 0:
            raise ValueError("length must be non-negative")
        if length == 0:
            return
        if offset + length > self._total:
            raise OffsetOutOfBounds(
                f"Slice 0x{offset:X}+0x{length:X} walks past region {self.lba_source!r} "
                f"(size 0x{self._total:X})"
            )
        remaining = length
        cur = offset
        for slot in self._slots:
            if remaining <= 0:
                break
            end = slot.base + slot.container.size
            if cur >= end:
                continue
            local = cur - slot.base
            take = min(remaining, slot.container.size - local)
            path = x3_dir / slot.container.name
            with path.open("rb") as f:
                f.seek(local)
                left = take
                while left > 0:
                    buf = f.read(min(chunk_size, left))
                    if not buf:
                        raise IOError(
                            f"Short read in {slot.container.name} at 0x{local:X} "
                            f"(needed {left} more bytes)"
                        )
                    yield buf
                    left -= len(buf)
            cur += take
            remaining -= take


# ---------------------------------------------------------------------------
# RegionMap (LBA source → Region)
# ---------------------------------------------------------------------------

class RegionMap:
    """LBA-source-name → :class:`Region`.

    The map is built from ``container_map.json``: the ``containers`` array gives
    a :class:`ContainerSet`, and the ``regions`` object — keyed by LBA source
    filename — names the ordered containers that hold each source's data.
    """

    def __init__(self, containers: ContainerSet, regions: Mapping[str, Sequence[str]]):
        self._containers = containers
        self._regions: Dict[str, Region] = {}
        for lba_source, names in regions.items():
            chain = []
            for name in names:
                chain.append(containers.get(name))
            self._regions[lba_source] = Region(lba_source=lba_source, containers=chain)

    # construction ---------------------------------------------------------

    @classmethod
    def from_json(cls, path: Path) -> "RegionMap":
        data = json.loads(path.read_text(encoding="utf-8"))
        version = int(data.get("version", 0))
        if version != 2:
            raise ContainerError(
                f"{path} is container_map version {version}; v2 is required. "
                "Re-run `cli.py prep` (or migrate manually)."
            )
        containers = ContainerSet.from_dicts(data["containers"])
        regions = data.get("regions") or {}
        if not regions:
            raise ContainerError(
                f"{path} has no `regions` mapping. Run `cli.py map-regions` first."
            )
        return cls(containers, regions)

    # access ---------------------------------------------------------------

    def has(self, lba_source: str) -> bool:
        return lba_source in self._regions

    def region_for(self, lba_source: str) -> Region:
        try:
            return self._regions[lba_source]
        except KeyError as exc:
            raise UnknownRegion(lba_source) from exc

    @property
    def containers(self) -> ContainerSet:
        return self._containers

    @property
    def sources(self) -> Tuple[str, ...]:
        return tuple(self._regions.keys())


# ---------------------------------------------------------------------------
# container_map.json read/write helpers
# ---------------------------------------------------------------------------

def load_container_map_raw(path: Path) -> dict:
    """Return the parsed JSON. Used by tooling that may want to inspect/edit
    regions before constructing a :class:`RegionMap`."""
    return json.loads(path.read_text(encoding="utf-8"))


def write_container_map(
    path: Path,
    containers: Sequence[Container],
    regions: Optional[Mapping[str, Sequence[str]]] = None,
) -> None:
    """Write the v2 ``container_map.json`` schema."""
    payload = {
        "version": 2,
        "containers": [{"name": c.name, "size": int(c.size)} for c in containers],
        "regions": {k: list(v) for k, v in (regions or {}).items()},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def merge_regions_into_map(path: Path, regions: Mapping[str, Sequence[str]]) -> None:
    """Overwrite just the ``regions`` field of an existing container_map.json."""
    data = load_container_map_raw(path)
    data["regions"] = {k: list(v) for k, v in regions.items()}
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


__all__ = [
    "Container",
    "ContainerSet",
    "Region",
    "RegionMap",
    "ContainerError",
    "UnknownContainer",
    "UnknownRegion",
    "OffsetOutOfBounds",
    "load_container_map_raw",
    "write_container_map",
    "merge_regions_into_map",
]
