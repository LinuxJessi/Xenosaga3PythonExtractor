# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — Xenosaga III Translation Editor, stand-alone.

The translation editor as its own download, apart from the extractor kit:
double-click it and the editor opens in the browser, with no extractor cards.
Two binaries in one folder (``dist/Xenosaga3-Translation-Editor/``):

* ``Xenosaga-III-Translation-Editor(.exe)`` — windowed; the editor's local
  web server (``gui.py``: started under this name, with no ``gui`` executable
  beside it, it is the editor only; see ``gui.editor_only``).
* ``xeno-cli(.exe)`` — console; the CLI the editor runs a Build with
  (``tx-build``), and the bundle's self-test.

On macOS the folder is also wrapped as ``Xenosaga-III-Translation-Editor.app``
(a real app, with its own runtime: it no longer needs the Extractor app next
to it). The extractor's own bundle keeps its Translation editor button.

The same modules, packages and data as ``xenosaga-extractor.spec`` (the
editor's Build uses the kit's whole text pipeline: textpack, langpack, patch,
the family readers), minus the portable ffmpeg/7-Zip the extractor ships.

Build (from the repository root):
    python build.py --editor
or by hand:
    python packaging/render_version_info.py
    python packaging/build_icon.py
    pyinstaller --noconfirm --clean packaging/translation-editor.spec
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
    (str(REPO / "txspeakers.json"), "."),          # "By speaker" view (txspeakers.load)
    (str(REPO / "fonts"), "fonts"),                 # DejaVu Sans: letters the game font lacks
    (str(REPO / "docs"), "docs"),
    (str(REPO / "lba"), "lba"),
    (str(REPO / "README.md"), "."),
    (str(REPO / "LICENSE"), "."),
]
DATAS = [(src, dst) for src, dst in DATAS if Path(src).exists()]

REQUIRED = ["numpy", "PIL", "PIL.Image", "PIL.ImageDraw", "capstone",
            "fontTools", "fontTools.ttLib", "uharfbuzz"]
KIT = sorted(p.stem for p in REPO.glob("*.py") if p.stem not in ("gui", "cli", "build", "__init__"))
HIDDEN = REQUIRED + KIT + ["cli", "gui"]       # cli.py refuses every command when a listed module is missing


def _analysis(entry: str) -> Analysis:
    return Analysis(
        [str(REPO / entry)],
        pathex=[str(REPO)],
        binaries=[],
        datas=DATAS,
        hiddenimports=HIDDEN,
        hookspath=[],
        runtime_hooks=[],
        excludes=["tkinter", "test", "unittest", "pkg_resources", "setuptools"],   # see xenosaga-extractor.spec
        noarchive=False,
    )


ed_a = _analysis("gui.py")
cli_a = _analysis("cli.py")
ed_pyz = PYZ(ed_a.pure, ed_a.zipped_data)
cli_pyz = PYZ(cli_a.pure, cli_a.zipped_data)

ed_exe = EXE(
    ed_pyz,
    ed_a.scripts,
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
    ed_exe,
    ed_a.binaries,
    ed_a.zipfiles,
    ed_a.datas,
    cli_exe,
    cli_a.binaries,
    cli_a.zipfiles,
    cli_a.datas,
    strip=False,
    upx=False,
    name="Xenosaga3-Translation-Editor",
)

if sys.platform == "darwin":
    ICNS = HERE / "icon.icns"
    app = BUNDLE(
        coll,
        name="Xenosaga-III-Translation-Editor.app",
        icon=str(ICNS) if ICNS.exists() else None,
        bundle_identifier="io.github.linuxjessi.xenosaga3translationeditor",
        info_plist={
            "CFBundleName": "Xenosaga III Translation Editor",
            "CFBundleDisplayName": "Xenosaga III Translation Editor",
            "NSHighResolutionCapable": True,
        },
    )
