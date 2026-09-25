"""
browse_bundle.py — Build a sibling ``browse/`` tree of immediately-playable
or viewable formats.

Each "kind" maps a set of source extensions to a destination subdirectory
under the stage tree, with one of a handful of conversion strategies:

* ``images``       — copy ``.jpg``/``.jpeg`` into ``images/``.
* ``text``         — copy ``.txt``/``.mes``/``.t`` into ``text/``, decode the
                     ``.txd`` menu-text tables, and sniff string tables out
                     of the binary-extension files that carry dialogue
                     (``.sb`` scene banks, ``mnu/us/*.bin`` databases,
                     ``.dat``) as ``*.strings.txt``.
* ``textures``     — copy ``.xtx``/``.tm2``/``.txd``/``.txy``/``.bmp``/``.png``
                     into ``textures/`` (raw bytes; XTX/TXD/TXY need a viewer).
* ``textures_png`` — decode ``.xtx``/``.tm2`` to PNG under ``textures_png/``.
                     Linear 32-bpp RGBA files decode directly; the 8
                     GS-swizzled 8-bpp files per disc are unswizzled and
                     paletted by coherence-ranked CLUT selection (shape is
                     right, tint is known-wrong — sepia/grey — fix planned;
                     see xtx_decode.py) plus a ``*_index.png`` ground-truth
                     map.
* ``package_textures`` — decode every texture that lives INSIDE another file:
                     the ``txy`` block of ``.chr`` / ``.wpn`` / ``.map``
                     MR packages (LZSS field maps decompressed on the fly)
                     and the free-standing txy records in ``.esd`` / ``.esp``
                     effect libraries and ``.sme`` bundles. PNGs go under
                     ``textures_png/_packages/<carrier>/NN_name.png``, with
                     sha1 de-duplication and a ``package_textures.csv``
                     manifest (see chrtex.py / xcpack.py).
* ``audio``        — decode ``.adx`` to PCM WAV via ffmpeg into ``audio/``.
* ``soundbanks``   — decode ``.dap`` DTPK sound banks to one WAV per cue
                     under ``soundbanks/`` (pure Python, no ffmpeg), plus the
                     ``dap`` bank embedded in each combatant ``.sme`` bundle.
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
import struct
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List, Optional, Set, Tuple


ALL_KINDS = ("images", "text", "textures", "textures_png", "package_textures",
             "audio", "soundbanks", "movies", "carved")


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
    "text":         {".txt", ".mes", ".t", ".txd"},
    "textures":     {".xtx", ".tm2", ".txy", ".bmp", ".png"},
    "textures_png": {".xtx", ".tm2"},
    "audio":        {".adx"},
    "soundbanks":   {".dap"},
    "movies":       {".sfd"},
    # ``carved`` is filename-based — handled separately.
    # ``package_textures`` and the text sniff / sme sound banks run as
    # serial sweeps after the per-file pool (they share de-dup state).
}

# Files the package-texture sweep opens: MR packages with a txy block, and
# carriers of free-standing txy records.
_PACKAGE_EXTS = {".chr", ".wpn", ".map"}
_TXY_CARRIER_EXTS = {".esd", ".esp", ".sme"}
# Binary-extension files that hold NUL-separated string tables.
_STRING_TABLE_EXTS = {".sb", ".bin", ".dat", ".shp"}

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
    soundbanks_ok: int = 0
    soundbanks_err: int = 0
    soundbank_cues: int = 0
    movies_ok: int = 0
    movies_err: int = 0
    carved_jpgs: int = 0
    skipped: int = 0
    text_txd: int = 0
    text_sniffed: int = 0
    package_carriers: int = 0
    package_textures: int = 0
    package_dups: int = 0
    package_err: int = 0
    package_decompressed: int = 0
    sme_banks: int = 0
    sme_cues: int = 0
    errors: List[str] = field(default_factory=list)

    def total_ok(self) -> int:
        return (
            self.images + self.text + self.textures + self.textures_png_ok
            + self.audio_ok + self.soundbanks_ok + self.movies_ok + self.carved_jpgs
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


def _decode_dap(in_path: Path, out_dir: Path) -> Tuple[int, str]:
    """Returns (cues_written, error). 0 cues with no error = sequence-only bank."""
    try:
        import dap_decode
        n = dap_decode.decode_to_wavs(in_path.read_bytes(), out_dir, in_path.stem)
        return n, ""
    except Exception as exc:
        return -1, f"{exc}"


def _convert_one(
    in_path: Path,
    dump_root: Path,
    stage_root: Path,
    ffmpeg: str,
    sfd_args: List[str],
    kinds: Set[str],
) -> Tuple[str, Optional[str], int]:
    rel = in_path.relative_to(dump_root)
    ext = in_path.suffix.lower()

    # Zero-byte LBA entries faithfully extracted as empty files. Nothing to do.
    if in_path.stat().st_size == 0:
        return ("skip", None, 0)

    if "images" in kinds and ext in _EXTS["images"]:
        dest = stage_root / "images" / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(in_path, dest)
        return ("images", None, 0)

    if "text" in kinds and ext in _EXTS["text"]:
        dest = stage_root / "text" / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        if ext == ".txd":
            # menu text table: u32 offset table (first offset / 4 = count)
            # then NUL-terminated strings with $cmd; control codes
            try:
                lines = decode_txd(in_path.read_bytes())
            except ValueError as exc:
                return ("text", f"TXD {rel}: {exc}", 0)
            dest.with_suffix(".txd.txt").write_text(
                "\n".join(f"{i}\t{t}" for i, t in enumerate(lines)) + "\n",
                encoding="utf-8")
            return ("text_txd", None, 0)
        shutil.copy2(in_path, dest)
        return ("text", None, 0)

    if "textures" in kinds and ext in _EXTS["textures"]:
        dest = stage_root / "textures" / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(in_path, dest)
        # fall through: the same .xtx/.tm2 also feeds textures_png (the
        # early return here used to skip every PNG decode whenever both
        # kinds were requested — i.e. in the default run)
        if not ("textures_png" in kinds and ext in _EXTS["textures_png"]):
            return ("textures", None, 0)

    if "textures_png" in kinds and ext == ".xtx":
        dest = (stage_root / "textures_png" / rel).with_suffix(".png")
        ok, err = _decode_xtx(in_path, dest)
        return ("textures_png", None if ok else f"XTX {rel}: {err}", 0)

    if "textures_png" in kinds and ext == ".tm2":
        dest = (stage_root / "textures_png" / rel).with_suffix(".png")
        ok, err = _decode_tm2(in_path, dest)
        return ("textures_png", None if ok else f"TM2 {rel}: {err}", 0)

    if "audio" in kinds and ext in _EXTS["audio"]:
        dest = (stage_root / "audio" / rel).with_suffix(".wav")
        dest.parent.mkdir(parents=True, exist_ok=True)
        ok, err = _run_ffmpeg([ffmpeg, "-y", "-loglevel", "error", "-i", str(in_path), str(dest)])
        return ("audio", None if ok else f"ADX {rel}: {err}", 0)

    if "soundbanks" in kinds and ext in _EXTS["soundbanks"]:
        out_dir = stage_root / "soundbanks" / rel.parent
        cues, err = _decode_dap(in_path, out_dir)
        if cues < 0:
            return ("soundbanks", f"DAP {rel}: {err}", 0)
        return ("soundbanks", None, cues)

    if "movies" in kinds and ext in _EXTS["movies"]:
        dest = (stage_root / "movies" / rel).with_suffix(".mp4")
        dest.parent.mkdir(parents=True, exist_ok=True)
        cmd = [ffmpeg, "-y", "-loglevel", "error", "-i", str(in_path)] + sfd_args + [str(dest)]
        ok, err = _run_ffmpeg(cmd)
        return ("movies", None if ok else f"SFD {rel}: {err}", 0)

    return ("skip", None, 0)


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



# ---------------------------------------------------------------------------
# text: .txd tables + string sniffing
# ---------------------------------------------------------------------------

def decode_txd(data: bytes) -> List[str]:
    """Strings of a ``.txd`` menu-text table (``mnu/us/menutext.txd``,
    ``synopsis.txd``, ``discchg.txd``, ``devchk.txd``). Layout: u32
    offsets from file start, one per string, the table ending where the
    first string starts; strings are NUL-terminated, ``\\n`` is literal."""
    if len(data) < 8:
        raise ValueError("too short")
    first, second = struct.unpack_from("<II", data, 0)
    if 0 < first < 65536 and 4 + first * 4 == second:
        # count-prefixed variant (menutext.txd): u32 count, then offsets
        count = first
        offs = struct.unpack_from(f"<{count}I", data, 4)
    elif first % 4 == 0 and 4 <= first <= len(data):
        count = first // 4
        offs = struct.unpack_from(f"<{count}I", data, 0)
    else:
        raise ValueError("not an offset table")
    out = []
    for o in offs:
        if o > len(data):
            raise ValueError("offset beyond file")
        end = data.find(b"\x00", o)
        raw = data[o:end if end >= 0 else len(data)]
        out.append(_decode_game_text(raw))
    return out


def _decode_game_text(raw: bytes) -> str:
    """UTF-8 first (the US disc), else Shift-JIS (dev leftovers)."""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp932", "replace")


def _sniff_strings(data: bytes, min_len: int = 4) -> Optional[List[str]]:
    """Printable runs (ASCII + UTF-8/SJIS multibyte) separated by NULs or
    binary bytes, or None when the blob is not text-bearing enough."""
    import re
    probe = data[:65536]
    printable = sum(1 for c in probe if 32 <= c < 127 or c in (9, 10, 13))
    nonzero = sum(1 for c in probe if c)
    if printable < 64 or printable / max(1, nonzero) < 0.35:
        return None
    # the US disc's text is plain ASCII with \n escapes; multibyte runs in
    # these files are pointer/float soup, not Japanese, so keep to ASCII
    runs = re.findall(rb"[\x20-\x7e\t\r\n]{%d,}" % min_len, data)
    out = []
    for r in runs:
        t = r.decode("ascii").strip()
        letters = sum(1 for c in t if c.isalpha())
        # byte soup that happens to be printable has few letters; real
        # text is mostly letters, digits, spaces and punctuation
        if len(t) >= min_len and letters >= 3 and letters >= len(t) * 0.45:
            out.append(t)
    return out if len(out) >= 2 else None


def decode_sb_strings(data: bytes) -> Optional[List[str]]:
    """The dialogue table of a ``cf/us/*.sb`` scene bank.

    ``SB  `` header: u16 x2 version, then up to six u32 section offsets at
    0x0C. Every section is ``{u32 kind, u32 count, u32 offsets[count],
    payload}``; the one whose payload is NUL-terminated text is the
    scene's message table — field dialogue and choices ("Board the E.S.?",
    "Yes\\nNo"), voice-cue ids, and the writers' EUC-JP scene comments
    (BGM notes, stage directions) that the US disc still carries."""
    if data[:4] != b"SB  " or len(data) < 0x28:
        return None
    for s in struct.unpack_from("<6I", data, 0x0C):
        if not s or s + 8 > len(data):
            continue
        kind, count = struct.unpack_from("<II", data, s)
        if kind != 8 or count == 0 or count > 20000 or s + 8 + count * 4 > len(data):
            continue
        offs = struct.unpack_from(f"<{count}I", data, s + 8)
        base = s + 8 + count * 4
        if any(base + o > len(data) for o in offs):
            continue
        out, textual = [], 0
        for o in offs:
            end = data.find(b"\x00", base + o)
            raw = data[base + o:end if end >= 0 else len(data)]
            try:
                t = raw.decode("euc_jp")
            except UnicodeDecodeError:
                t = raw.decode("cp932", "replace")
            if raw and all(32 <= b < 127 or b >= 0x80 for b in raw):
                textual += 1
            out.append(t)
        if textual >= max(2, len(out) // 2):
            return out
    return None


def _sniff_string_tables(dump_root: Path, stage_root: Path, stats: BundleStats) -> None:
    """Export the dialogue / database strings hidden in binary-extension
    files as ``text/<rel>.strings.txt``: ``cf/us/*.sb`` scene banks (the
    in-map dialogue: "Board the E.S.?", shop lines, NPC talk),
    ``mnu/us/*.bin`` databases (character/enemy/item text), ``.dat``
    tables (``mg1/us/Message.Dat``), ``.shp`` (skipped — item-id bytes)."""
    n = 0
    for p in sorted(dump_root.rglob("*")):
        if not p.is_file() or "_reports" in p.parts or p.suffix.lower() not in _STRING_TABLE_EXTS:
            continue
        if p.suffix.lower() == ".shp":
            continue
        try:
            data = p.read_bytes()
        except OSError as exc:
            stats.errors.append(f"strings {p}: {exc}")
            continue
        if not data:
            continue
        lines = decode_sb_strings(data) if p.suffix.lower() == ".sb" else None
        if lines is None:
            lines = _sniff_strings(data)
        if not lines:
            continue
        rel = p.relative_to(dump_root)
        dest = stage_root / "text" / rel.parent / (rel.name + ".strings.txt")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text("\n".join(lines) + "\n", encoding="utf-8")
        n += 1
    stats.text_sniffed = n
    print(f"[browse] text: {stats.text_txd} .txd tables decoded, "
          f"{n} string tables sniffed out of binary files -> text/", flush=True)


# ---------------------------------------------------------------------------
# soundbanks: the dap bank inside each .sme bundle
# ---------------------------------------------------------------------------

def _sme_soundbanks(dump_root: Path, stage_root: Path, stats: BundleStats) -> None:
    """Every ``pac/**/*.sme`` combatant bundle with a ``dap`` sub-resource
    carries a complete DTPK bank (0x40 zero pre-header, then the same
    preamble + segment chain as a ``.dap`` file): the character's battle
    voice/SE cues. Written next to the standalone banks as
    ``soundbanks/<rel>/<stem>_dap_NN.wav``."""
    import dap_decode
    import xcpack
    banks = cues = 0
    for p in sorted(dump_root.rglob("*.sme")):
        if not p.is_file() or "_reports" in p.parts:
            continue
        try:
            data = xcpack.normalize(p.read_bytes())
            subs = xcpack.sub_resources(data)
        except (xcpack.XcError, OSError):
            continue
        if "dap" not in subs or subs["dap"][1] < 0x90:
            continue
        off, size = subs["dap"]
        blob = data[off + 0x40:off + size]
        rel = p.relative_to(dump_root)
        out_dir = stage_root / "soundbanks" / rel.parent
        try:
            n = dap_decode.decode_to_wavs(blob, out_dir, rel.stem + "_dap")
        except Exception as exc:  # noqa: BLE001 — per-file, keep sweeping
            stats.errors.append(f"SME dap {rel}: {exc}")
            continue
        banks += 1
        cues += n
    stats.sme_banks, stats.sme_cues = banks, cues
    print(f"[browse] soundbanks: {banks} banks embedded in .sme bundles "
          f"({cues} cues) -> soundbanks/", flush=True)


# ---------------------------------------------------------------------------
# package_textures: txy blocks inside packages and effect libraries
# ---------------------------------------------------------------------------

def _package_worker(args):
    """Decode every texture of one carrier file. Runs in a worker process;
    writes the PNGs itself and returns manifest rows
    ``(rel, offset_label, name, fmt, w, h, sha1, png_rel)`` plus flags."""
    src, dump_root, stage_root = args
    import hashlib
    import chrtex
    import xcpack
    src, dump_root, stage_root = Path(src), Path(dump_root), Path(stage_root)
    rel = src.relative_to(dump_root)
    ext = src.suffix.lower()
    try:
        raw = src.read_bytes()
    except OSError as exc:
        return rel, [], f"{rel}: {exc}", False
    if not raw:
        return rel, [], None, False
    records = []   # (label, sub_off, sub_size, data)
    decompressed = False
    try:
        if ext in _PACKAGE_EXTS:
            data = xcpack.normalize(raw)
            decompressed = data is not raw
            subs = xcpack.sub_resources(data)
            if "txy" in subs and subs["txy"][1]:
                records.append(("txy", subs["txy"][0], subs["txy"][1], data))
        else:
            data = raw
            if ext == ".sme" and xcpack.is_xc(raw):
                data = xcpack.normalize(raw)
                decompressed = data is not raw
            for off, size, name in xcpack.iter_txy_records(data):
                records.append((f"0x{off:x}", off, size, data))
    except xcpack.XcError as exc:
        return rel, [], f"{rel}: {exc}", decompressed
    rows = []
    err = None
    out_dir = stage_root / "textures_png" / "_packages" / rel
    for label, off, size, data in records:
        try:
            t = chrtex.parse_txy(data, off, size)
        except chrtex.ChrError as exc:
            if "empty" in str(exc) or "no pixel" in str(exc):
                continue                     # stub record, nothing to draw
            err = f"{rel} @{label}: {exc}"
            continue
        except (struct.error, IndexError, ValueError) as exc:
            err = f"{rel} @{label}: {type(exc).__name__}: {exc}"
            continue
        try:
            for e, w, h, rgba in chrtex.decode_entries(data, t):
                sha = hashlib.sha1(rgba).hexdigest()
                stem = f"{e['i']:02d}_{e['name'] or 'unnamed'}"
                if len(records) > 1:
                    stem = f"{label}_{stem}"
                rows.append((label, e["name"], e["fmt"], w, h, sha, stem, rgba))
        except (chrtex.ChrError, struct.error, IndexError, ValueError) as exc:
            err = f"{rel} @{label}: {type(exc).__name__}: {exc}"
    # write PNGs (duplicates within one carrier are still written: they are
    # distinct entries of that package); cross-carrier de-dup happens in the
    # parent, which deletes files it has already seen
    written = []
    if rows:
        out_dir.mkdir(parents=True, exist_ok=True)
        for label, name, fmt, w, h, sha, stem, rgba in rows:
            dest = out_dir / f"{stem}.png"
            k = 1
            while dest.exists():
                k += 1
                dest = out_dir / f"{stem}~{k}.png"
            chrtex.write_png(dest, w, h, rgba)
            written.append((label, name, fmt, w, h, sha, str(dest.relative_to(stage_root))))
    return rel, written, err, decompressed


def _package_textures(dump_root: Path, stage_root: Path, stats: BundleStats, jobs: int) -> None:
    import csv
    from concurrent.futures import ProcessPoolExecutor
    carriers = [p for p in sorted(dump_root.rglob("*"))
                if p.is_file() and "_reports" not in p.parts
                and p.suffix.lower() in (_PACKAGE_EXTS | _TXY_CARRIER_EXTS)]
    print(f"[browse] package_textures: sweeping {len(carriers)} packages / "
          f"effect libraries ({max(1, jobs)} processes) ...", flush=True)
    seen: dict = {}
    manifest = []
    tasks = [(str(p), str(dump_root), str(stage_root)) for p in carriers]
    done = 0
    with ProcessPoolExecutor(max_workers=max(1, jobs)) as ex:
        for rel, written, err, decompressed in ex.map(_package_worker, tasks, chunksize=4):
            done += 1
            if written:
                stats.package_carriers += 1
            if decompressed:
                stats.package_decompressed += 1
            if err:
                stats.package_err += 1
                stats.errors.append(f"package {err}")
            for label, name, fmt, w, h, sha, png_rel in written:
                dup = seen.get(sha)
                if dup is not None:
                    try:
                        (stage_root / png_rel).unlink()
                    except OSError:
                        pass
                    stats.package_dups += 1
                    manifest.append([str(rel), label, name, f"0x{fmt:02x}", w, h,
                                     sha[:12], "", dup, "lzss" if decompressed else ""])
                    continue
                seen[sha] = png_rel
                stats.package_textures += 1
                manifest.append([str(rel), label, name, f"0x{fmt:02x}", w, h,
                                 sha[:12], png_rel, "", "lzss" if decompressed else ""])
            if done % 500 == 0:
                print(f"[browse]   {done}/{len(carriers)} carriers, "
                      f"{stats.package_textures} textures so far", flush=True)
    stage_root.mkdir(parents=True, exist_ok=True)
    with open(stage_root / "package_textures.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["carrier", "record", "name", "fmt", "width", "height",
                    "sha1", "written", "duplicate_of", "packed"])
        w.writerows(manifest)
    print(f"[browse] package_textures: {stats.package_textures} PNGs from "
          f"{stats.package_carriers} carriers ({stats.package_dups} duplicates "
          f"skipped, {stats.package_err} carriers with errors, "
          f"{stats.package_decompressed} LZSS packages decompressed) "
          f"-> textures_png/_packages/ + package_textures.csv", flush=True)


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

    import time as _time
    t0 = _time.monotonic()
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
                kind, err, extra = fut.result()
                if kind == "images":
                    stats.images += 1
                elif kind == "text":
                    if err is None: stats.text += 1
                    else: stats.errors.append(err)
                elif kind == "text_txd":
                    stats.text_txd += 1
                elif kind == "textures":
                    stats.textures += 1
                elif kind == "textures_png":
                    if "textures" in kinds_set:
                        stats.textures += 1      # the raw copy happened too
                    if err is None: stats.textures_png_ok += 1
                    else: stats.textures_png_err += 1; stats.errors.append(err)
                elif kind == "audio":
                    if err is None: stats.audio_ok += 1
                    else: stats.audio_err += 1; stats.errors.append(err)
                elif kind == "soundbanks":
                    if err is None:
                        stats.soundbanks_ok += 1
                        stats.soundbank_cues += extra
                    else: stats.soundbanks_err += 1; stats.errors.append(err)
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
                        f"dap={stats.soundbanks_ok}+{stats.soundbanks_err}e "
                        f"sfd={stats.movies_ok}+{stats.movies_err}e",
                        flush=True,
                    )

    if "carved" in kinds_set:
        _carve_jpegs(dump_root, stage_root, stats)
    if "text" in kinds_set:
        _sniff_string_tables(dump_root, stage_root, stats)
    if "soundbanks" in kinds_set:
        _sme_soundbanks(dump_root, stage_root, stats)
    if "package_textures" in kinds_set:
        _package_textures(dump_root, stage_root, stats, jobs)

    print(
        f"[browse] done: images={stats.images} text={stats.text} textures={stats.textures} "
        f"textures_png={stats.textures_png_ok}+{stats.textures_png_err}err "
        f"audio={stats.audio_ok}+{stats.audio_err}err "
        f"soundbanks={stats.soundbanks_ok}+{stats.soundbanks_err}err ({stats.soundbank_cues} cues) "
        f"movies={stats.movies_ok}+{stats.movies_err}err "
        f"carved={stats.carved_jpgs} "
        f"txd={stats.text_txd} strings={stats.text_sniffed} "
        f"sme_banks={stats.sme_banks} ({stats.sme_cues} cues) "
        f"package_textures={stats.package_textures}"
        f"+{stats.package_dups}dup+{stats.package_err}err "
        f"from {stats.package_carriers} carriers "
        f"({stats.package_decompressed} LZSS packages) "
        f"in {_time.monotonic() - t0:.0f} s"
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
