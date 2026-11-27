# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — Xenosaga III Python Extractor (Windows release).

Three binaries in one folder:

* ``gui.exe``       — windowed launcher; the local web GUI.
* ``xeno-cli.exe``  — console; the same CLI ``gui.py`` shells out to.
* ``Xenosaga-III-Translation-Editor.exe`` — the same GUI under a second
  name, opened on the translation editor.

All ship in the same ``dist/Xenosaga3-Extractor/`` directory next to a
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
    python -m pip install -r requirements.txt pyinstaller
    python packaging/render_version_info.py
    python packaging/build_icon.py
    pyinstaller --noconfirm --clean packaging/xenosaga-extractor.spec
"""
import sys
from pathlib import Path

HERE = Path(SPECPATH).resolve()
REPO = HERE.parent

ICON = HERE / "icon.ico"
ICON_ARG = str(ICON) if ICON.exists() else None

DATAS = [
    (str(REPO / "container_map.json"), "."),
    (str(REPO / "disc_7z_list.txt"), "."),
    # translation editor: speaker names for the "By speaker" view (txspeakers.load)
    (str(REPO / "txspeakers.json"), "."),
    # translation editor: the font a build takes a few missing Latin letters from
    # (txtarget.BUNDLED_FONT: DejaVu Sans 2.37 and its licence)
    (str(REPO / "fonts"), "fonts"),
    (str(REPO / "docs"), "docs"),
    (str(REPO / "lba"), "lba"),
    (str(REPO / "README.md"), "."),
    (str(REPO / "LICENSE"), "."),
]
DATAS = [(src, dst) for src, dst in DATAS if Path(src).exists()]

# The kit's requirements (requirements.txt) — all required, all bundled.
REQUIRED = [
    "numpy",
    "PIL",
    "PIL.Image",
    "PIL.ImageDraw",
    "capstone",
    "fontTools",
    "fontTools.ttLib",
    "uharfbuzz",
]

# Every module of the kit: cli.py imports the command modules by name
# (importlib, COMMAND_MODULES / SELF_TESTS) and several commands import
# lazily, so PyInstaller's static scan would miss them. Listing them all keeps
# a release complete (pattern from Xenosaga2PythonExtractor's spec).
KIT = sorted(p.stem for p in REPO.glob("*.py") if p.stem not in ("gui", "cli", "build", "__init__"))

# "gui" is listed too: cli.py's COMMAND_MODULES and SELF_TESTS name it, and
# cli.py refuses every command when one of those modules cannot import. A
# xeno-cli built without it answered every command with "cannot load gui.py"
# (found 2026-11-21 by running the bundle: `python build.py` now does that).
HIDDEN = REQUIRED + KIT + ["cli", "gui"]


def _analysis(entry: str) -> Analysis:
    return Analysis(
        [str(REPO / entry)],
        pathex=[str(REPO)],
        binaries=[],
        datas=DATAS,
        hiddenimports=HIDDEN,
        hookspath=[],
        runtime_hooks=[],
        # pkg_resources / setuptools: nothing in the kit or its requirements
        # imports them at run time, but PyInstaller's hooks pull them in when
        # the build Python has them, and an older setuptools' run-time hook
        # then stops the bundle at start ("The 'appdirs' package is required";
        # seen with Apple's Python 3.9, 2026-11-21).
        excludes=["tkinter", "test", "unittest", "pkg_resources", "setuptools"],
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

# The translation editor on its own: the same program as the GUI under a
# second name. gui.py opens the editor page first when its executable is
# called this (or is given --editor), so translators never pass through the
# extractor cards. Same PYZ and scripts: it costs one small launcher file.
tr_exe = EXE(
    gui_pyz,
    gui_a.scripts,
    [],
    exclude_binaries=True,
    name="Xenosaga-III-Translation-Editor",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=ICON_ARG,
    version=str(HERE / "version_info_gui.txt"),
)

# ("u", None, "OPTION"): unbuffered output. A frozen program ignores
# PYTHONUNBUFFERED, so without it the GUI's build log stayed empty until the
# CLI had finished (seen 2026-11-26 running the stand-alone editor's Build).
cli_exe = EXE(
    cli_pyz,
    cli_a.scripts,
    [("u", None, "OPTION")],
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
    tr_exe,
    cli_exe,
    cli_a.binaries,
    cli_a.zipfiles,
    cli_a.datas,
    strip=False,
    upx=False,
    name="Xenosaga3-Extractor",
)

# macOS: also wrap the folder into a double-clickable .app (the Episode I and
# II kits ship one). Both executables end up in Contents/MacOS/, so the GUI's
# sibling lookup for xeno-cli still resolves. PyInstaller ad-hoc-signs the
# bundle; a downloaded copy needs right-click -> Open once (unsigned developer).
if sys.platform == "darwin":
    ICNS = HERE / "icon.icns"
    app = BUNDLE(
        coll,
        name="Xenosaga-III-Extractor.app",
        icon=str(ICNS) if ICNS.exists() else None,
        bundle_identifier="io.github.linuxjessi.xenosaga3extractor",
        info_plist={
            "CFBundleName": "Xenosaga III Extractor",
            "CFBundleDisplayName": "Xenosaga III Extractor",
            "NSHighResolutionCapable": True,
        },
    )
