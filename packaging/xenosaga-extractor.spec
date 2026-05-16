# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — Xenosaga III Python Extractor (Windows release).

Two binaries in one folder:

* ``gui.exe``       — windowed launcher; the local web GUI.
* ``xeno-cli.exe``  — console; the same CLI ``gui.py`` shells out to.

Both ship in the same ``dist/Xenosaga3-Extractor/`` directory next to a
``tools/`` subdirectory that the release workflow populates with
portable ``ffmpeg.exe`` and ``7z.exe``. ``browse_bundle.detect_ffmpeg``
and ``iso_ops.detect_sevenzip`` know to look there first.

AV-friendliness notes — none of these *eliminate* false positives, but
each one demonstrably reduces them:

* one-folder, not one-file (one-file extracts to %TEMP% at startup,
  which is a classic packer behaviour heuristically flagged by AV)
* ``upx=False`` (UPX-packed exes are the single strongest "this is
  malware" signal in most engines' weights)
* full Windows version resource attached to both binaries
* placeholder icon committed so we never ship a default-icon exe
* ``console=False`` for the GUI (no scary console window) but
  ``console=True`` for the CLI so users still see output when they run
  it directly from a terminal

Build (from repo root, on Windows):
    python -m pip install -r requirements.txt pyinstaller pillow capstone
    python packaging/render_version_info.py
    python packaging/build_icon.py
    pyinstaller --noconfirm --clean packaging/xenosaga-extractor.spec
"""
from pathlib import Path

HERE = Path(SPECPATH).resolve()
REPO = HERE.parent

ICON = HERE / "icon.ico"
ICON_ARG = str(ICON) if ICON.exists() else None

DATAS = [
    (str(REPO / "container_map.json"), "."),
    (str(REPO / "disc_7z_list.txt"), "."),
    (str(REPO / "docs"), "docs"),
    (str(REPO / "lba"), "lba"),
    (str(REPO / "README.md"), "."),
    (str(REPO / "LICENSE"), "."),
]
DATAS = [(src, dst) for src, dst in DATAS if Path(src).exists()]

HIDDEN = [
    "PIL",
    "PIL.Image",
    "PIL.ImageDraw",
    "capstone",
]


def _analysis(entry: str) -> Analysis:
    return Analysis(
        [str(REPO / entry)],
        pathex=[str(REPO)],
        binaries=[],
        datas=DATAS,
        hiddenimports=HIDDEN,
        hookspath=[],
        runtime_hooks=[],
        excludes=["tkinter", "test", "unittest"],
        noarchive=False,
    )


gui_a = _analysis("gui.py")
cli_a = _analysis("cli.py")

# Skipped MERGE() — its tuple signature is fiddly across PyInstaller
# versions and COLLECT below already deduplicates identical files
# (python3X.dll, common .pyds) by destination path. We pay a small
# .pyz duplication cost in exchange for a much simpler spec.

gui_pyz = PYZ(gui_a.pure, gui_a.zipped_data)
cli_pyz = PYZ(cli_a.pure, cli_a.zipped_data)

gui_exe = EXE(
    gui_pyz,
    gui_a.scripts,
    [],
    exclude_binaries=True,
    name="gui",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=ICON_ARG,
    version=str(HERE / "version_info_gui.txt"),
)

cli_exe = EXE(
    cli_pyz,
    cli_a.scripts,
    [],
    exclude_binaries=True,
    name="xeno-cli",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    icon=ICON_ARG,
    version=str(HERE / "version_info_cli.txt"),
)

coll = COLLECT(
    gui_exe,
    gui_a.binaries,
    gui_a.zipfiles,
    gui_a.datas,
    cli_exe,
    cli_a.binaries,
    cli_a.zipfiles,
    cli_a.datas,
    strip=False,
    upx=False,
    name="Xenosaga3-Extractor",
)
