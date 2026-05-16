"""
iso_ops.py — 7-Zip helpers and container map construction.

7-Zip is the only external dependency. Two operations are wrapped:

* ``7z l -ba <iso>`` — list the contents of an ISO (no header).
* ``7z x -y -o<dir> <iso> X3.*`` — extract the X3.* parts to a directory.

The listing is parsed to discover the X3.* container files. The resulting
``container_map.json`` only carries container *sizes* — it does **not** assign
LBA sources to containers; that is the job of ``regions.py``.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Iterable, List, Optional, Sequence
import os
import re
import shlex
import shutil
import subprocess
import sys

from containers import Container, write_container_map


# ---------------------------------------------------------------------------
# WSL ↔ Windows path translation
# ---------------------------------------------------------------------------
# When running under WSL and invoking a Windows-side 7-Zip binary (the common
# case here — the Linux p7zip doesn't read PS2 UDF ISOs as cleanly), the 7z
# process receives Windows-style arguments. Linux-rooted paths like
# ``/home/jessi/foo.iso`` are uninterpretable to it. ``wslpath -w`` converts
# them to ``\\wsl.localhost\Ubuntu\home\jessi\foo.iso``.
#
# We translate paths transparently when:
#   * we're running on Linux,
#   * ``wslpath`` is on PATH,
#   * the resolved 7z binary points at a Windows ``.exe`` (heuristic: script
#     wrapper around ``7z.exe`` or directly named ``*.exe``).

@lru_cache(maxsize=1)
def _is_wsl() -> bool:
    if os.name != "posix":
        return False
    try:
        with open("/proc/version", "r") as f:
            v = f.read().lower()
        return "microsoft" in v
    except OSError:
        return False


@lru_cache(maxsize=1)
def _wslpath_available() -> bool:
    return shutil.which("wslpath") is not None


def _looks_like_windows_7z(seven_zip: str) -> bool:
    """True if the resolved 7z binary is Windows-side (so it expects Win paths)."""
    p = shutil.which(seven_zip) or seven_zip
    if not p:
        return False
    if p.lower().endswith(".exe"):
        return True
    # Wrapper script that delegates to a Windows .exe?
    try:
        with open(p, "rb") as f:
            head = f.read(4096)
        if b"7z.exe" in head or b"7Z.EXE" in head:
            return True
    except (OSError, IsADirectoryError):
        return False
    return False


def _to_win(path: str) -> str:
    """Translate a path to its Windows equivalent if we're on WSL. No-op
    otherwise. Translation only happens for absolute paths; relative paths
    pass through unchanged."""
    if not _is_wsl() or not _wslpath_available():
        return path
    if not os.path.isabs(path):
        return path
    try:
        return subprocess.check_output(["wslpath", "-w", path], text=True).strip()
    except subprocess.CalledProcessError:
        return path


def _translate_args_for_7z(seven_zip: str, args: Sequence[str]) -> List[str]:
    """If the 7z binary is Windows-side, translate path-bearing args via wslpath."""
    if not _looks_like_windows_7z(seven_zip):
        return list(args)
    out: List[str] = []
    for a in args:
        if a.startswith("-o") and len(a) > 2:
            out.append("-o" + _to_win(a[2:]))
        elif a.startswith("-"):
            # other 7z switch — leave alone
            out.append(a)
        elif os.path.isabs(a):
            out.append(_to_win(a))
        else:
            out.append(a)
    return out


# ---------------------------------------------------------------------------
# Subprocess helper
# ---------------------------------------------------------------------------

def _run(cmd: Sequence[str], cwd: Optional[Path] = None, timeout: Optional[int] = None) -> str:
    printable = " ".join(shlex.quote(str(c)) for c in cmd)
    print(f"[cmd] {printable}")
    try:
        cp = subprocess.run(
            list(cmd),
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        # The Windows error for "binary on PATH but missing" is opaque
        # ("WinError 2: The system cannot find the file specified"). Rewrite
        # it so the user knows it's the *tool*, not their ISO.
        raise FileNotFoundError(
            f"Could not run {cmd[0]!r}. "
            f"Install 7-Zip (https://www.7-zip.org/) and either add it to PATH "
            f"or pass --sevenzip /full/path/to/7z.exe."
        ) from exc
    if cp.returncode != 0:
        raise RuntimeError(
            f"Command failed (code {cp.returncode}): {printable}\n"
            f"STDOUT:\n{cp.stdout}\nSTDERR:\n{cp.stderr}"
        )
    return cp.stdout


# ---------------------------------------------------------------------------
# 7-Zip location & invocation
# ---------------------------------------------------------------------------

# Common install locations 7-Zip puts itself in on each OS. PATH is checked
# first; this list only matters when PATH doesn't include 7-Zip (which is
# the default state on Windows — the installer doesn't touch PATH).
_COMMON_7Z_LOCATIONS_WIN = (
    r"%ProgramFiles%\7-Zip\7z.exe",
    r"%ProgramFiles(x86)%\7-Zip\7z.exe",
    r"%LOCALAPPDATA%\Programs\7-Zip\7z.exe",
    r"%USERPROFILE%\scoop\apps\7zip\current\7z.exe",
    r"%USERPROFILE%\scoop\shims\7z.exe",
    r"%ChocolateyInstall%\bin\7z.exe",
    r"C:\Program Files\7-Zip\7z.exe",
    r"C:\Program Files (x86)\7-Zip\7z.exe",
)
_COMMON_7Z_LOCATIONS_POSIX = (
    "/usr/bin/7z",
    "/usr/local/bin/7z",
    "/opt/homebrew/bin/7z",
    "/snap/bin/7z",
)


def detect_sevenzip() -> Optional[str]:
    """Return the full path to a usable 7-Zip executable, or None.

    Order of preference:
      1. Portable copy under ``tools/`` next to a frozen exe (Windows release).
      2. ``7z`` / ``7z.exe`` / ``7za`` / ``7zz`` on PATH.
      3. Common per-OS install locations (Windows installer default,
         scoop/chocolatey, Homebrew, snap, …).
    """
    if getattr(sys, "frozen", False):
        tools = Path(sys.executable).resolve().parent / "tools"
        if tools.is_dir():
            for name in ("7z.exe" if os.name == "nt" else "7z", "7za", "7zz"):
                candidate = tools / name
                if candidate.exists():
                    return str(candidate)
    for name in ("7z.exe" if os.name == "nt" else "7z", "7z", "7za", "7zz"):
        p = shutil.which(name)
        if p:
            return p
    locations = _COMMON_7Z_LOCATIONS_WIN if os.name == "nt" else _COMMON_7Z_LOCATIONS_POSIX
    for raw in locations:
        expanded = os.path.expandvars(raw)
        if Path(expanded).exists():
            return expanded
    return None


def sevenzip_path(custom: Optional[str] = None) -> str:
    """Resolve the 7-Zip executable. ``custom`` wins; then PATH; then common
    install locations. Falls back to the bare name as a last resort so that
    ``_run`` can still surface a sensible error."""
    if custom:
        return custom
    found = detect_sevenzip()
    if found:
        return found
    return "7z.exe" if os.name == "nt" else "7z"


def sevenzip_list(iso_path: Path, seven_zip: Optional[str] = None) -> str:
    seven = sevenzip_path(seven_zip)
    if not iso_path.exists():
        raise FileNotFoundError(f"ISO not found: {iso_path}")
    args = _translate_args_for_7z(seven, [str(iso_path)])
    return _run([seven, "l", "-ba"] + args)


def sevenzip_extract(
    iso_path: Path,
    out_dir: Path,
    patterns: Iterable[str],
    seven_zip: Optional[str] = None,
    extra_args: Iterable[str] = (),
) -> None:
    """Extract entries matching ``patterns`` from ``iso_path`` to ``out_dir``.

    ``extra_args`` lets callers pass 7-Zip switches such as ``-xr!X3.*`` to
    exclude paths from the extraction.
    """
    seven = sevenzip_path(seven_zip)
    out_dir.mkdir(parents=True, exist_ok=True)
    args = _translate_args_for_7z(
        seven,
        [f"-o{out_dir}", str(iso_path), *patterns, *extra_args],
    )
    _run([seven, "x", "-y"] + args)


# ---------------------------------------------------------------------------
# Parsing `7z l -ba` output into containers
# ---------------------------------------------------------------------------

# 7z's `-ba` listing has no header. Each line looks like
#     2003-04-15 10:00:00 ....A    104857600              X3.01
# Sometimes there are two number columns (size, packed size). Sometimes the
# filename is preceded by a directory path inside the ISO. We accept either.
_CONTAINER_LINE = re.compile(
    r"""^\s*
        (?:\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\s+\S+\s+)?  # optional datetime + attrs
        (?P<size>\d+)\s+                                      # size
        (?:\d+\s+)?                                           # optional packed size
        (?:[^\s]+[\\/])?                                      # optional directory prefix inside ISO
        (?P<name>X3\.\d+)                                     # X3.NN(N...)
        \s*$
    """,
    re.VERBOSE,
)


def parse_sevenzip_containers(listing_text: str) -> List[Container]:
    """Parse a ``7z l -ba`` listing and return X3.* containers in order."""
    out: List[Container] = []
    for line in listing_text.splitlines():
        m = _CONTAINER_LINE.match(line)
        if not m:
            continue
        out.append(Container(name=m.group("name"), size=int(m.group("size"))))
    return out


def discover_containers_in_dir(work_dir: Path) -> List[Container]:
    """Return ``X3.NN`` files actually sitting in ``work_dir`` with their sizes.

    Falls back to a directory scan when ``container_map.json`` is missing or
    when the user copied the X3.* parts in by hand.
    """
    out: List[Container] = []
    rx = re.compile(r"^X3\.\d+$")
    for p in sorted(work_dir.iterdir()) if work_dir.exists() else []:
        if p.is_file() and rx.match(p.name):
            out.append(Container(name=p.name, size=p.stat().st_size))
    return out


def build_container_map_from_listing(
    listing_text: str,
    out_path: Path,
) -> List[Container]:
    """Parse a 7z listing and write the (regions-less) v2 container_map.json."""
    conts = parse_sevenzip_containers(listing_text)
    if not conts:
        raise ValueError("No X3.* containers found in 7-Zip listing text.")
    write_container_map(out_path, conts, regions=None)
    return conts


__all__ = [
    "sevenzip_path",
    "sevenzip_list",
    "sevenzip_extract",
    "parse_sevenzip_containers",
    "discover_containers_in_dir",
    "build_container_map_from_listing",
]
