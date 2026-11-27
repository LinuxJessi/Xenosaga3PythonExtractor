#!/usr/bin/env python3
"""build.py — package the extractor into a self-contained one-folder bundle.

One command for what the release workflow does by hand, the same as the
Episode I and II kits' ``build.py``:

    python build.py            # the extractor kit, for THIS platform
    python build.py --editor   # the Translation Editor on its own (a separate download)
    python build.py --all      # both
    python build.py --clean    # wipe the previous output of what is built first

It renders the Windows version resources, makes the placeholder icon when no
real one is committed, drives the PyInstaller spec, and then runs the
finished bundle's own self-tests (``xeno-cli self-test`` and ``--self-test``
of the windowed program), so a bundle that is missing a module or a required
package fails here, not on someone else's machine.

Output, under ``dist/`` (ignored by git):

    Xenosaga3-Extractor/           gui(.exe)  xeno-cli(.exe)  _internal/
                                   Xenosaga-III-Translation-Editor(.exe): the
                                   GUI again, opened on the translation editor
    Xenosaga-III-Extractor.app     (built on macOS: the same folder, wrapped)

    Xenosaga3-Translation-Editor/  (--editor) Xenosaga-III-Translation-Editor(.exe)
                                   xeno-cli(.exe)  _internal/: the editor alone,
                                   no extractor cards (packaging/translation-editor.spec)
    Xenosaga-III-Translation-Editor.app   (--editor, macOS: that folder as a
                                   real app with its own runtime; double-click it)

``tools/`` (portable ffmpeg and 7-Zip) is added by the release workflow on
Windows; a local build finds those programs on PATH instead.

PyInstaller does not cross-compile: build Windows binaries on Windows, the
.app on macOS. ``--distpath`` / ``--workpath`` move the output and work
folders (the defaults are ``dist/`` and ``build/`` at the repository root,
where the release workflow expects them).
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PACKAGING = ROOT / "packaging"
SPEC = PACKAGING / "xenosaga-extractor.spec"
NAME = "Xenosaga3-Extractor"
APP_NAME = "Xenosaga-III-Extractor.app"
TR_NAME = "Xenosaga-III-Translation-Editor"
EDITOR_SPEC = PACKAGING / "translation-editor.spec"
EDITOR_NAME = "Xenosaga3-Translation-Editor"          # the stand-alone editor's folder

# import name -> what needs it; every one is a requirement (requirements.txt)
REQUIRED = (("numpy", "models, fonts, pictures"), ("PIL", "textures and pictures (Pillow)"),
            ("capstone", "disasm"), ("fontTools", "new scripts: glyph outlines"),
            ("uharfbuzz", "new scripts: shaping"))


def _run_selftest(argv) -> bool:
    try:
        r = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=600)
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"  could not run {argv[0]}: {exc}")
        return False
    tail = (r.stdout + r.stderr).strip().splitlines()[-1:] or ["(no output)"]
    print(f"  {Path(argv[0]).name} {' '.join(argv[1:])}: exit {r.returncode}, "
          + tail[0].encode("ascii", "backslashreplace").decode("ascii"))
    if r.returncode:                    # say which checks failed, not only the last line
        for line in (r.stdout + r.stderr).splitlines():
            if "FAIL" in line or "Traceback" in line or "Error" in line:
                print("    " + line.encode("ascii", "backslashreplace").decode("ascii"))
    return r.returncode == 0


def _prepare() -> None:
    """The two steps the release workflow runs before PyInstaller."""
    for script in ("render_version_info.py", "build_icon.py"):
        r = subprocess.run([sys.executable, str(PACKAGING / script)], cwd=str(ROOT))
        if r.returncode:
            sys.exit(f"packaging/{script} failed (exit {r.returncode})")


def _pyinstaller(pyinstaller, spec: Path, dist: Path, a) -> None:
    args = ["--noconfirm", "--distpath", str(dist), "--workpath", str(Path(a.workpath).resolve()), str(spec)]
    if a.clean:
        args.insert(0, "--clean")
    print(f"=== pyinstaller {' '.join(args)} ===", flush=True)
    pyinstaller(args)


def build_extractor(pyinstaller, dist: Path, a) -> bool:
    bundle, app = dist / NAME, dist / APP_NAME
    if a.clean:
        shutil.rmtree(bundle, ignore_errors=True)
        if sys.platform == "darwin":
            shutil.rmtree(app, ignore_errors=True)
    _pyinstaller(pyinstaller, SPEC, dist, a)
    ext = ".exe" if sys.platform == "win32" else ""
    gui, cli, tr = bundle / f"gui{ext}", bundle / f"xeno-cli{ext}", bundle / f"{TR_NAME}{ext}"
    ok = gui.exists() and cli.exists() and tr.exists()
    print("\n" + "-" * 60)
    print(f"extractor : {bundle}")
    for f in (gui, cli, tr):
        print(f"  {f.name}  {'OK' if f.exists() else 'MISSING'}")
    if sys.platform == "darwin":
        app_ok = (app / "Contents" / "MacOS" / "gui").exists()
        print(f"  {app.name}  {'OK' if app_ok else 'MISSING'}")
        ok = ok and app_ok
    if ok and not a.no_self_test:
        print("self-tests from the bundle:")
        ok = _run_selftest([str(cli), "self-test"]) and ok
        ok = _run_selftest([str(gui), "--self-test"]) and ok
    return ok


def build_editor(pyinstaller, dist: Path, a) -> bool:
    bundle, app = dist / EDITOR_NAME, dist / f"{TR_NAME}.app"
    if a.clean or (app.exists() and not (app / "Contents" / "MacOS" / "xeno-cli").exists()):
        shutil.rmtree(bundle, ignore_errors=True)
        shutil.rmtree(app, ignore_errors=True)    # (also the old launcher-only app of earlier builds)
    _pyinstaller(pyinstaller, EDITOR_SPEC, dist, a)
    ext = ".exe" if sys.platform == "win32" else ""
    ed, cli = bundle / f"{TR_NAME}{ext}", bundle / f"xeno-cli{ext}"
    ok = ed.exists() and cli.exists() and not (bundle / f"gui{ext}").exists()
    print("\n" + "-" * 60)
    print(f"editor    : {bundle}")
    for f in (ed, cli):
        print(f"  {f.name}  {'OK' if f.exists() else 'MISSING'}")
    if sys.platform == "darwin":
        app_ok = all((app / "Contents" / "MacOS" / n).exists() for n in (TR_NAME, "xeno-cli"))
        print(f"  {app.name}  {'OK' if app_ok else 'MISSING'}")
        ok = ok and app_ok
    if ok and not a.no_self_test:
        print("self-tests from the bundle:")
        ok = _run_selftest([str(cli), "self-test"]) and ok
        ok = _run_selftest([str(ed), "--self-test"]) and ok
    return ok


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--clean", action="store_true", help="wipe the previous output of what is built first")
    ap.add_argument("--editor", action="store_true", help="build the stand-alone Translation Editor instead")
    ap.add_argument("--all", action="store_true", help="build the extractor and the stand-alone editor")
    ap.add_argument("--distpath", default=str(ROOT / "dist"), help="where the bundles are written (default: dist/)")
    ap.add_argument("--workpath", default=str(ROOT / "build"), help="PyInstaller's work folder (default: build/)")
    ap.add_argument("--no-self-test", action="store_true", help="skip running the bundles' self-tests")
    a = ap.parse_args(argv)

    try:
        from PyInstaller.__main__ import run as pyinstaller
    except ImportError:
        sys.exit("PyInstaller is not installed in this Python.\n"
                 "  python -m pip install pyinstaller\n"
                 "then re-run:  python build.py")
    for mod, why in REQUIRED:
        try:
            __import__(mod)
        except ImportError:
            sys.exit(f"{mod} ({why}) is not installed in this Python, and the bundle must carry it.\n"
                     "  python -m pip install -r requirements.txt\n"
                     "then re-run:  python build.py")
    for spec in (SPEC, EDITOR_SPEC):
        if not spec.exists():
            sys.exit(f"spec not found: {spec}")

    dist = Path(a.distpath).resolve()
    _prepare()
    results = {}
    if a.all or not a.editor:
        results["extractor"] = build_extractor(pyinstaller, dist, a)
    if a.all or a.editor:
        results["editor"] = build_editor(pyinstaller, dist, a)
    ok = all(results.values())
    if ok:
        mac = sys.platform == "darwin"
        ship = []
        if "extractor" in results:
            ship.append(APP_NAME if mac else f"{NAME}/ (zip it)")
        if "editor" in results:
            ship.append(f"{TR_NAME}.app" if mac else f"{EDITOR_NAME}/ (zip it: the editor's own download)")
        print(f"\nDone. Ship {' and '.join(ship)}.")
    else:
        print("\nBuild incomplete or a bundled self-test failed: " +
              ", ".join(k for k, v in results.items() if not v) + "; see the output above.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
