"""
browse_bundle.py — Build a sibling ``browse/`` tree of immediately-playable
or viewable formats.

Each "kind" maps a set of source extensions to a destination subdirectory
under the stage tree, with one of a handful of conversion strategies:

* ``images``       — copy ``.jpg``/``.jpeg`` into ``images/``.
* ``text``         — copy ``.txt``/``.mes`` into ``text/``.
* ``textures``     — copy ``.xtx``/``.tm2``/``.txd``/``.txy``/``.bmp``/``.png``
                     into ``textures/`` (raw bytes; XTX/TXD/TXY need a viewer).
* ``textures_png`` — decode ``.xtx``/``.tm2`` to PNG under ``textures_png/``.
                     Linear 32-bpp RGBA only; the 8 GS-swizzled XTX files
                     come out scrambled (see README).
* ``audio``        — decode ``.adx`` to PCM WAV via ffmpeg into ``audio/``.
* ``movies``       — transcode ``.sfd`` (MPEG-PS + ADX) to H.264+AAC MP4 via
                     ffmpeg into ``movies/``.
* ``carved``       — carve every JPG embedded in ``credit.bin`` (and any other
                     listed container) into ``images/<rel>/<prefix>_NN.jpg``.

The stage directory should be on fast local storage; pass ``--out`` to
mirror to a final destination at the end (single rsync per disc instead of
per-file 9P writes when ``--out`` is on ``/mnt/c``).
"""
from __future__ import annotations

import glob
import os
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List, Optional, Set, Tuple


ALL_KINDS = ("images", "text", "textures", "textures_png", "audio", "movies", "carved")


# Common install locations for ffmpeg on each OS, used when ``ffmpeg`` isn't
# on PATH. PATH is always checked first.
_COMMON_FFMPEG_LOCATIONS_WIN = (
    r"%ProgramFiles%\ffmpeg\bin\ffmpeg.exe",
    r"%ProgramFiles(x86)%\ffmpeg\bin\ffmpeg.exe",
    r"%LOCALAPPDATA%\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-*\bin\ffmpeg.exe",
    r"%USERPROFILE%\scoop\apps\ffmpeg\current\bin\ffmpeg.exe",
    r"%USERPROFILE%\scoop\shims\ffmpeg.exe",
    r"%ChocolateyInstall%\bin\ffmpeg.exe",
    r"C:\ffmpeg\bin\ffmpeg.exe",
    r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
)
_COMMON_FFMPEG_LOCATIONS_POSIX = (
    "/usr/bin/ffmpeg",
    "/usr/local/bin/ffmpeg",
    "/opt/homebrew/bin/ffmpeg",
    "/snap/bin/ffmpeg",
)


def _bundled_dir() -> Optional[Path]:
    """Return the ``tools/`` dir shipped next to the frozen exe, if any.

    In a PyInstaller one-folder build, sys.executable is the launcher exe
    and its sibling ``tools/`` holds the portable ffmpeg / 7-Zip we ship
    in the Windows release zip. Returns None when running from source."""
    if not getattr(sys, "frozen", False):
        return None
    tools = Path(sys.executable).resolve().parent / "tools"
    return tools if tools.is_dir() else None


def detect_ffmpeg() -> Optional[str]:
    """Return the full path to a usable ffmpeg executable, or None.

    Order: bundled ``tools/`` (frozen builds), PATH, common install
    locations. Handles glob-style paths (e.g. WinGet's versioned dir)."""
    bundled = _bundled_dir()
    if bundled:
        name = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
        candidate = bundled / name
        if candidate.exists():
            return str(candidate)
    for name in ("ffmpeg.exe" if os.name == "nt" else "ffmpeg", "ffmpeg"):
        p = shutil.which(name)
        if p:
            return p
    locations = _COMMON_FFMPEG_LOCATIONS_WIN if os.name == "nt" else _COMMON_FFMPEG_LOCATIONS_POSIX
    for raw in locations:
        expanded = os.path.expandvars(raw)
        if "*" in expanded:
            # Glob match (e.g. WinGet's ffmpeg-<version>/bin/ffmpeg.exe).
            # Use stdlib glob — pathlib.Path.glob rejects absolute patterns on Python 3.14+.
            for m in sorted(glob.glob(expanded), reverse=True):
                if Path(m).exists():
                    return m
        elif Path(expanded).exists():
            return expanded
    return None

# Source extensions per kind, lowercase.
_EXTS = {
    "images":       {".jpg", ".jpeg"},
    "text":         {".txt", ".mes"},
    "textures":     {".xtx", ".tm2", ".txd", ".txy", ".bmp", ".png"},
    "textures_png": {".xtx", ".tm2"},
    "audio":        {".adx"},
    "movies":       {".sfd"},
    # ``carved`` is filename-based — handled separately.
}

CARVED_CONTAINER_NAMES = ("credit.bin",)


@dataclass
class BundleStats:
    images: int = 0
    text: int = 0
    textures: int = 0
    textures_png_ok: int = 0
    textures_png_err: int = 0
    audio_ok: int = 0
    audio_err: int = 0
    movies_ok: int = 0
    movies_err: int = 0
    carved_jpgs: int = 0
    skipped: int = 0
    errors: List[str] = field(default_factory=list)

    def total_ok(self) -> int:
        return (
            self.images + self.text + self.textures + self.textures_png_ok
            + self.audio_ok + self.movies_ok + self.carved_jpgs
        )


def _run_ffmpeg(cmd: List[str]) -> Tuple[bool, str]:
    try:
        cp = subprocess.run(cmd, capture_output=True, text=True)
    except FileNotFoundError as exc:
        return False, (
            f"ffmpeg binary not found at {cmd[0]!r}. Install ffmpeg or pass "
            f"--ffmpeg /full/path/to/ffmpeg.exe."
        )
    if cp.returncode != 0:
        msg = (cp.stderr or cp.stdout).strip().splitlines()
        return False, msg[-1] if msg else "unknown ffmpeg error"
    return True, ""


def _decode_xtx(in_path: Path, dst: Path) -> Tuple[bool, str]:
    try:
        import xtx_decode
        xtx_decode.decode_to_png(in_path.read_bytes(), dst)
        return True, ""
    except Exception as exc:
        return False, f"{exc}"


def _decode_tm2(in_path: Path, dst: Path) -> Tuple[bool, str]:
    try:
        import tm2_decode
        tm2_decode.decode_to_png(in_path.read_bytes(), dst)
        return True, ""
    except Exception as exc:
        return False, f"{exc}"


def _convert_one(
    in_path: Path,
    dump_root: Path,
    stage_root: Path,
    ffmpeg: str,
    sfd_args: List[str],
    kinds: Set[str],
) -> Tuple[str, Optional[str]]:
    rel = in_path.relative_to(dump_root)
    ext = in_path.suffix.lower()

    # Zero-byte LBA entries faithfully extracted as empty files. Nothing to do.
    if in_path.stat().st_size == 0:
        return ("skip", None)

    if "images" in kinds and ext in _EXTS["images"]:
        dest = stage_root / "images" / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(in_path, dest)
        return ("images", None)

    if "text" in kinds and ext in _EXTS["text"]:
        dest = stage_root / "text" / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(in_path, dest)
        return ("text", None)

    if "textures" in kinds and ext in _EXTS["textures"]:
        dest = stage_root / "textures" / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(in_path, dest)
        return ("textures", None)

    if "textures_png" in kinds and ext == ".xtx":
        dest = (stage_root / "textures_png" / rel).with_suffix(".png")
        ok, err = _decode_xtx(in_path, dest)
        return ("textures_png", None if ok else f"XTX {rel}: {err}")

    if "textures_png" in kinds and ext == ".tm2":
        dest = (stage_root / "textures_png" / rel).with_suffix(".png")
        ok, err = _decode_tm2(in_path, dest)
        return ("textures_png", None if ok else f"TM2 {rel}: {err}")

    if "audio" in kinds and ext in _EXTS["audio"]:
        dest = (stage_root / "audio" / rel).with_suffix(".wav")
        dest.parent.mkdir(parents=True, exist_ok=True)
        ok, err = _run_ffmpeg([ffmpeg, "-y", "-loglevel", "error", "-i", str(in_path), str(dest)])
        return ("audio", None if ok else f"ADX {rel}: {err}")

    if "movies" in kinds and ext in _EXTS["movies"]:
        dest = (stage_root / "movies" / rel).with_suffix(".mp4")
        dest.parent.mkdir(parents=True, exist_ok=True)
        cmd = [ffmpeg, "-y", "-loglevel", "error", "-i", str(in_path)] + sfd_args + [str(dest)]
        ok, err = _run_ffmpeg(cmd)
        return ("movies", None if ok else f"SFD {rel}: {err}")

    return ("skip", None)


def _gather(dump_root: Path, kinds: Set[str]) -> List[Path]:
    wanted_exts: Set[str] = set()
    for k in kinds:
        if k == "carved":
            continue
        wanted_exts |= _EXTS.get(k, set())
    out: List[Path] = []
    for p in dump_root.rglob("*"):
        if not p.is_file() or "_reports" in p.parts:
            continue
        if p.suffix.lower() in wanted_exts:
            out.append(p)
    return out


def _carve_jpegs(dump_root: Path, stage_root: Path, stats: BundleStats) -> None:
    """Run the JPEG carver over known container .bin files."""
    try:
        import carve_jpeg
    except Exception as exc:
        stats.errors.append(f"carved: {exc}")
        return
    names = {n.lower() for n in CARVED_CONTAINER_NAMES}
    for p in dump_root.rglob("*.bin"):
        if not p.is_file() or p.name.lower() not in names:
            continue
        rel = p.relative_to(dump_root).with_suffix("")
        dst = stage_root / "images" / rel
        n = carve_jpeg.carve_file(p, dst)
        stats.carved_jpgs += n


def bundle(
    dump_root: Path,
    stage_root: Path,
    final_root: Optional[Path] = None,
    *,
    ffmpeg: str = "ffmpeg",
    jobs: int = 4,
    sfd_preset: str = "veryfast",
    sfd_crf: int = 23,
    progress_every: int = 200,
    kinds: Optional[Iterable[str]] = None,
) -> BundleStats:
    """Build a browse/ tree from a dump/ tree.

    Args:
        dump_root: source dump directory (the extractor's output).
        stage_root: scratch directory for outputs.
        final_root: mirror ``stage_root`` here at the end (or omit to skip).
        ffmpeg: path to ffmpeg binary.
        jobs: thread count for parallel ffmpeg invocations.
        sfd_preset, sfd_crf: x264 knobs for SFD transcoding.
        kinds: which categories to produce. Default: all of :data:`ALL_KINDS`.
    """
    if not dump_root.exists():
        raise FileNotFoundError(f"dump_root not found: {dump_root}")
    stage_root.mkdir(parents=True, exist_ok=True)

    # Resolve ffmpeg if the caller left it as the bare default — otherwise
    # Windows users without ffmpeg on PATH get an opaque WinError 2 per file.
    if ffmpeg in ("ffmpeg", "ffmpeg.exe"):
        detected = detect_ffmpeg()
        if detected:
            ffmpeg = detected

    if kinds is None:
        kinds_set: Set[str] = set(ALL_KINDS)
    else:
        kinds_set = set(kinds)
        unknown = kinds_set - set(ALL_KINDS)
        if unknown:
            raise ValueError(f"unknown bundle kinds: {sorted(unknown)}; valid: {ALL_KINDS}")

    files = _gather(dump_root, kinds_set)
    print(f"[browse] kinds={sorted(kinds_set)} candidate files: {len(files)}")
    stats = BundleStats()

    if files:
        sfd_args = [
            "-c:v", "libx264", "-crf", str(sfd_crf), "-preset", sfd_preset,
            "-c:a", "aac", "-b:a", "160k",
        ]
        done = 0
        with ThreadPoolExecutor(max_workers=jobs) as ex:
            futures = {
                ex.submit(_convert_one, p, dump_root, stage_root, ffmpeg, sfd_args, kinds_set): p
                for p in files
            }
            for fut in as_completed(futures):
                kind, err = fut.result()
                if kind == "images":
                    stats.images += 1
                elif kind == "text":
                    stats.text += 1
                elif kind == "textures":
                    stats.textures += 1
                elif kind == "textures_png":
                    if err is None: stats.textures_png_ok += 1
                    else: stats.textures_png_err += 1; stats.errors.append(err)
                elif kind == "audio":
                    if err is None: stats.audio_ok += 1
                    else: stats.audio_err += 1; stats.errors.append(err)
                elif kind == "movies":
                    if err is None: stats.movies_ok += 1
                    else: stats.movies_err += 1; stats.errors.append(err)
                else:
                    stats.skipped += 1
                done += 1
                if progress_every and done % progress_every == 0:
                    print(
                        f"[browse] {done}/{len(files)}  "
                        f"img={stats.images} txt={stats.text} tex={stats.textures} "
                        f"png={stats.textures_png_ok}+{stats.textures_png_err}e "
                        f"adx={stats.audio_ok}+{stats.audio_err}e "
                        f"sfd={stats.movies_ok}+{stats.movies_err}e",
                        flush=True,
                    )

    if "carved" in kinds_set:
        _carve_jpegs(dump_root, stage_root, stats)

    print(
        f"[browse] done: images={stats.images} text={stats.text} textures={stats.textures} "
        f"textures_png={stats.textures_png_ok}+{stats.textures_png_err}err "
        f"audio={stats.audio_ok}+{stats.audio_err}err "
        f"movies={stats.movies_ok}+{stats.movies_err}err "
        f"carved={stats.carved_jpgs}"
    )
    if stats.errors:
        print("[browse] first 10 errors:")
        for e in stats.errors[:10]:
            print(f"  - {e}")

    if final_root is not None and final_root != stage_root:
        print(f"[browse] mirroring {stage_root} -> {final_root}")
        rsync = shutil.which("rsync")
        if rsync:
            subprocess.run([rsync, "-a", f"{stage_root}/", f"{final_root}/"], check=True)
        else:
            for src in stage_root.rglob("*"):
                if not src.is_file():
                    continue
                rel = src.relative_to(stage_root)
                dst = final_root / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)

    return stats


__all__ = ["BundleStats", "ALL_KINDS", "bundle"]
