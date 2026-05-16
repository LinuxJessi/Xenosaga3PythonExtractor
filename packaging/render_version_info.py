"""Render per-binary Windows version-info resources from the template.

PyInstaller wants a separate version_info file per EXE because the
``InternalName`` and ``OriginalFilename`` fields differ between
``gui.exe`` and ``xeno-cli.exe``. We keep a single template and stamp
two concrete files at build time so the version number stays in sync
with ``__init__.__version__``.

Run me from anywhere; output goes to ``packaging/version_info_gui.txt``
and ``packaging/version_info_cli.txt``.
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent

sys.path.insert(0, str(REPO))
from __init__ import __version__  # noqa: E402

TEMPLATE = (HERE / "version_info.txt").read_text(encoding="utf-8")


def _filevers_tuple(version: str) -> str:
    """Turn '0.2.0' (or '0.2.0-rc1') into '0, 2, 0, 0'."""
    head = version.split("-", 1)[0]
    parts = [int(p) for p in head.split(".") if p.isdigit()]
    while len(parts) < 4:
        parts.append(0)
    return ", ".join(str(p) for p in parts[:4])


def render(internal: str, description: str) -> str:
    return (
        TEMPLATE
        .replace("__FILEVERS__", _filevers_tuple(__version__))
        .replace("__VERSION__", __version__)
        .replace("__INTERNAL__", internal)
        .replace("__DESCRIPTION__", description)
    )


def main() -> None:
    (HERE / "version_info_gui.txt").write_text(
        render("gui", "Xenosaga III Extractor — Local GUI"),
        encoding="utf-8",
    )
    (HERE / "version_info_cli.txt").write_text(
        render("xeno-cli", "Xenosaga III Extractor — Command Line"),
        encoding="utf-8",
    )
    print(f"Rendered version-info for v{__version__}")


if __name__ == "__main__":
    main()
