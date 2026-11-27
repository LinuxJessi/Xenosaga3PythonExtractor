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
                     paletted from the CLUT tiles parked in the sheet, with
                     the CLUT the game binds wherever a draw from the
                     executable/overlays is known (engine_palettes.py: item
                     icons, thumbnails, titleobj, minigame, ~78% of the
                     window sheets; the rest ranked, see xtx_decode.py)
                     plus a ``*_index.png`` ground-truth map.
* ``package_textures`` — decode every texture that lives INSIDE another file:
                     the ``txy`` block of ``.chr`` / ``.wpn`` / ``.map``
                     MR packages (LZSS field maps decompressed on the fly)
                     and the free-standing txy records in ``.esd`` / ``.esp``
                     effect libraries and ``.sme`` bundles. PNGs go under
                     ``textures_png/_packages/<carrier>/NN_name.png``, with
                     sha1 de-duplication and a ``package_textures.csv``
                     manifest (see chrtex.py / xcpack.py).
* ``audio``        — decode ``.adx`` to PCM WAV via ffmpeg into ``audio/``.
* ``music``        — the soundtrack on its own: the 120 ADX streams that sit
                     directly in ``snd\\adx\\`` as WAV under ``music/``, with
                     ``music/music.csv`` (rate, length and the loop points
                     read from each stream's header; adx.py). When ``audio``
                     runs too, these streams are written under ``music/``
                     only, not a second time under ``audio/``.
* ``soundbanks``   — decode ``.dap`` DTPK sound banks to one WAV per cue
                     under ``soundbanks/`` (pure Python, no ffmpeg), plus the
                     ``dap`` bank embedded in each combatant ``.sme`` bundle.
* ``movies``       — transcode ``.sfd`` (MPEG-PS + ADX) to H.264+AAC MP4 via
                     ffmpeg into ``movies/``.
* ``carved``       — carve every JPG embedded in ``credit.bin`` (and any other
                     listed container) into ``images/<rel>/<prefix>_NN.jpg``.
* ``models``       — every model (``.chr``/``.wpn``/``.map`` packages and the
                     standalone ``.pxy``) as glTF binary under
                     ``models/<path>.glb`` plus ``models/models.csv``
                     (models_sweep.browse_models; see docs/MODELS.md).

Text is read with textcodec.py, following the build the dump came from
(``detect_dump_region``: the boot executable's sha256 when the dump holds
it, else the language folder of ``mnu\\xx\\menutext.txd``; ``--region``
overrides). USA and the May 2006 prototype: the USA display reading
(``UsCodec``) for strings the game draws, ``NoteCodec`` (per-string Shift-JIS
/ EUC-JP / USA) for the developers' notes inside .sb scene scripts. Japan
(SLPS_256.40/41): the JP print reading (``JpCodec``, lead >= 0xA0) for every
string, notes included. The containers are parsed by their own modules (sb,
txd, njbin, msgdat, batdat, subtitle); the ASCII sniff is only a USA fallback
for unparsed .bin/.dat files. Movie/event subtitles and .mes files also get a
UTF-8 ``*.utf8.txt`` reading next to the raw copy. On a JP dump the 140 JP-only
scenes (sb.JP_ONLY_SB, + bat mom1_b02) are marked "JP-only, load status
unknown" in their ``.strings.txt`` and listed in ``text/JP-ONLY.txt``. JP keeps
jpg\\, ef\\map\\, ef\\esp\\ and mnu\\pse\\ files at the folder root where USA has
``\\us\\`` (region.py M27); the kinds pick files by extension, so both layouts
are covered. Every byte the codecs cannot show as a character is written as a
``⟦XX⟧`` escape, so the text files are an exact reading of the bytes.

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

import re

import adx as adx_mod
import region as region_mod
import sb as sb_mod
import subtitle as subtitle_mod
import textcodec
import txd as txd_mod

_US = textcodec.UsCodec()
_TOP = re.compile(r"^(chain\d+|iso(-disc\d+)?)$", re.I)


def game_path(rel: Path) -> str:
    """The in-game path (backslashes, no leading one) of a file under a dump: the
    ``chainN/`` / ``iso/`` folder that ``disc.py dump`` writes is dropped."""
    parts = list(rel.parts)
    if parts and _TOP.match(parts[0]):
        parts = parts[1:]
    return "\\".join(parts)


def detect_dump_region(dump_root: Path) -> "region_mod.Region":
    """The build profile of a dump tree: the sha256 of a boot executable in it
    (SLUS_*/SLPS_* as ``dump --fs`` writes it) matched against region.PROFILES,
    else the language folder holding ``menutext.txd`` (region.lang_of: jp -> JP,
    us -> USA). USA when neither is found."""
    import hashlib
    for pat in ("SLUS_*", "SLPS_*", "*/SLUS_*", "*/SLPS_*"):
        for exe in sorted(dump_root.glob(pat)):
            if not exe.is_file():
                continue
            sha = hashlib.sha256(exe.read_bytes()).hexdigest()
            for p in region_mod.PROFILES:
                if sha == p.exe_sha256:
                    return p
    paths = [game_path(m.relative_to(dump_root)) for m in dump_root.rglob("menutext.txd")]
    lang = region_mod.lang_of(paths)
    for p in region_mod.PROFILES:
        if lang and p.lang == lang and p.name != "proto_2006_05":
            return p
    return region_mod.US


def _items(obj) -> list:
    it = obj.items
    return it() if callable(it) else it


def _item_text(item) -> str:
    return textcodec.codec_by_name(item.codec).to_text(item.raw)


ALL_KINDS = ("images", "text", "textures", "textures_png", "package_textures",
             "audio", "music", "soundbanks", "movies", "carved", "models")


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
    "music":        {".adx"},
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
    music_ok: int = 0
    music_err: int = 0
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
    models_ok: int = 0
    models_empty: int = 0
    models_err: int = 0
    errors: List[str] = field(default_factory=list)

    def total_ok(self) -> int:
        return (
            self.images + self.text + self.textures + self.textures_png_ok
            + self.audio_ok + self.music_ok + self.soundbanks_ok + self.movies_ok + self.carved_jpgs
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
    region=None,
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
                lines = decode_txd(in_path.read_bytes(), region)
            except ValueError as exc:
                return ("text", f"TXD {rel}: {exc}", 0)
            dest.with_suffix(".txd.txt").write_text(
                "\n".join(f"{i}\t{t}" for i, t in enumerate(lines)) + "\n",
                encoding="utf-8")
            return ("text_txd", None, 0)
        shutil.copy2(in_path, dest)
        gpath = game_path(rel)
        if subtitle_mod.role(gpath, region) in ("movie", "event", "pse-mes", "pse-script"):
            try:
                _name, text = subtitle_mod.to_text(gpath, in_path.read_bytes(), region)
                dest.with_name(dest.name + ".utf8.txt").write_text(text, encoding="utf-8")
            except (ValueError, UnicodeError) as exc:
                return ("text", f"subtitle {rel}: {exc}", 0)
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

    if ext == ".adx" and adx_mod.is_soundtrack(game_path(rel)):
        # the soundtrack: under music/ when that kind is on (and then not a
        # second time under audio/), else with the other streams under audio/
        if "music" in kinds:
            dest = stage_root / "music" / (in_path.stem + ".wav")
            dest.parent.mkdir(parents=True, exist_ok=True)
            ok, err = _run_ffmpeg([ffmpeg, "-y", "-loglevel", "error", "-i", str(in_path), str(dest)])
            return ("music", None if ok else f"ADX {rel}: {err}", 0)
    elif ext == ".adx" and "audio" not in kinds:
        return ("skip", None, 0)            # music only: voice and event streams are not music

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


def _music_table(dump_root: Path, stage_root: Path) -> int:
    """Write ``music/music.csv``: one row per soundtrack stream of the dump
    (adx.table_row: rate, channels, length, loop points from the header)."""
    import csv
    rows = []
    for p in sorted(dump_root.rglob("*")):
        if p.suffix.lower() != ".adx" or not p.is_file() or "_reports" in p.parts:
            continue
        gpath = game_path(p.relative_to(dump_root))
        if not adx_mod.is_soundtrack(gpath) or p.stat().st_size == 0:
            continue
        with open(p, "rb") as fh:
            head = fh.read(0x40)
        try:
            rows.append(adx_mod.table_row(gpath, head, p.stat().st_size))
        except adx_mod.AdxError as exc:
            rows.append([p.stem, gpath, str(p.stat().st_size)] + [""] * 9 + [str(exc)])
    if rows:
        out = stage_root / "music"
        out.mkdir(parents=True, exist_ok=True)
        with open(out / "music.csv", "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(adx_mod.CSV_HEADER)
            w.writerows(rows)
    return len(rows)


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

def decode_txd(data: bytes, region=None) -> List[str]:
    """Strings of a ``.txd`` menu-text table (``mnu/xx/menutext.txd``,
    ``synopsis.txd``, ``discchg.txd``, ``devchk.txd``), parsed by txd.py and
    read with the build's display codec (USA ``UsCodec``, JP ``JpCodec``;
    ``region`` None = USA). Raises ValueError (txd.TxdError) when the file is
    not an offset table."""
    return [_item_text(it) for it in _items(txd_mod.parse(data, region))]


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


def decode_sb_strings(data: bytes, region=None) -> Optional[List[str]]:
    """The text pool of an XS3 ``.sb`` scene script (sb.py), one line per
    string, or None when the file is not an XS3 ``SB`` v1.1 script.

    Each string is classified by ``sb.classify``: displayed text and
    identifiers are read with the USA codec; developers' notes (never drawn)
    with ``textcodec.NoteCodec``, which picks Shift-JIS, EUC-JP or the USA
    reading per string, and the line is prefixed ``[note cp932]`` /
    ``[note euc_jp]`` so the reader knows which reading was used (USA lines
    left in Japanese: ``[untranslated cp932]``). On a JP build (``region``
    'jp') every string uses the JP print reading and carries no prefix. Line
    breaks inside a string come out as ``⟦0A⟧``-style escapes, so a string
    is always one line."""
    try:
        script = sb_mod.parse(data, region)
    except sb_mod.SbError:
        return None
    out = []
    for it in _items(script):
        text = _item_text(it)
        if it.role in ("note", "untranslated"):
            out.append(f"[{it.role} {it.codec}] {text}" if it.codec != "us" else f"[{it.role}] {text}")
        else:
            out.append(text)
    return out


def decode_container_strings(gpath: str, data: bytes, region=None) -> Optional[List[str]]:
    """Lines (``key<TAB>text``) of the parsed text containers other than .sb/.txd:
    ``mg1\\xx\\Message.Dat`` (msgdat), ``batdat.bin`` (batdat) and the
    ``mnu\\xx\\*.bin`` menu databases (njbin). None when the file is none of these
    or does not parse."""
    low = gpath.lower()
    name = low.rsplit("\\", 1)[-1]
    try:
        if name == "message.dat":
            import msgdat
            obj = msgdat.parse(data, region)
        elif name == "batdat.bin":
            import batdat
            obj = batdat.parse(data, region)
        elif low.startswith("mnu\\") and name.endswith(".bin"):
            import njbin
            obj = njbin.parse(data, region)
        else:
            return None
    except (ValueError, IndexError, KeyError):
        return None
    lines = [f"{it.key}\t{_item_text(it)}" for it in _items(obj)]
    return lines or None


def _sniff_string_tables(dump_root: Path, stage_root: Path, stats: BundleStats,
                         region=None) -> None:
    """Export the dialogue / database strings hidden in binary-extension
    files as ``text/<rel>.strings.txt``: ``cf/us/*.sb`` scene banks (the
    in-map dialogue: "Board the E.S.?", shop lines, NPC talk),
    ``mnu/us/*.bin`` databases (character/enemy/item text), ``.dat``
    tables (``mg1/us/Message.Dat``), ``.shp`` (skipped — item-id bytes).
    Containers with a parser are read through it (``decode_container_strings``);
    the ASCII sniff runs only on a USA-codec build."""
    region = region_mod.as_region(region)
    jp = region.codec == "jp"
    jp_only = []
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
        rel = p.relative_to(dump_root)
        gpath = game_path(rel)
        lines = decode_sb_strings(data, region) if p.suffix.lower() == ".sb" else None
        if lines is None:
            lines = decode_container_strings(gpath, data, region)
        if lines is None and not jp:
            lines = _sniff_strings(data)
        if not lines:
            continue
        status = sb_mod.scene_status(gpath) if jp else None
        if status:
            jp_only.append(gpath)
            lines = [f"# {status}"] + lines
        dest = stage_root / "text" / rel.parent / (rel.name + ".strings.txt")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text("\n".join(lines) + "\n", encoding="utf-8")
        n += 1
    stats.text_sniffed = n
    if jp_only:
        dest = stage_root / "text" / "JP-ONLY.txt"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(f"# {len(jp_only)} scene scripts with no USA counterpart "
                        f"({sb_mod.JP_ONLY_STATUS})\n" + "\n".join(sorted(jp_only)) + "\n",
                        encoding="utf-8")
        print(f"[browse] text: {len(jp_only)} JP-only scenes listed in text/JP-ONLY.txt", flush=True)
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


def _models(dump_root: Path, stage_root: Path, stats: BundleStats, jobs: int) -> None:
    """Browse kind ``models``: models_sweep.browse_models over the dump tree,
    glb files under ``models/`` plus ``models/models.csv``."""
    import models_sweep
    out = stage_root / "models"
    print(f"[browse] models: converting every .chr/.wpn/.map/.pxy to glTF "
          f"({max(1, jobs)} processes) ...", flush=True)
    rows = models_sweep.browse_models(dump_root, out, jobs=max(1, jobs),
                                      log=lambda m: print(f"[browse] {m}", flush=True))
    for r in rows:
        st = r.get("status")
        if st == "ok":
            stats.models_ok += 1
        elif st == "empty":
            stats.models_empty += 1
        else:
            stats.models_err += 1
            stats.errors.append(f"model {r.get('path')}: {r.get('notes') or st}")
    print(f"[browse] models: {stats.models_ok} glb, {stats.models_empty} empty "
          f"pxy slots, {stats.models_err} failures -> models/ + models.csv", flush=True)


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
    region=None,
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
        region: build profile (region.Region or name) for the text readers;
            None detects it from the dump (``detect_dump_region``).
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

    region = detect_dump_region(dump_root) if region is None else region_mod.as_region(region)
    print(f"[browse] build {region.name} (text codec {region.codec}, language folder {region.lang})")

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
                ex.submit(_convert_one, p, dump_root, stage_root, ffmpeg, sfd_args, kinds_set,
                          region): p
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
                elif kind == "music":
                    if err is None: stats.music_ok += 1
                    else: stats.music_err += 1; stats.errors.append(err)
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

    if "music" in kinds_set:
        _music_table(dump_root, stage_root)
    if "carved" in kinds_set:
        _carve_jpegs(dump_root, stage_root, stats)
    if "text" in kinds_set:
        _sniff_string_tables(dump_root, stage_root, stats, region)
    if "soundbanks" in kinds_set:
        _sme_soundbanks(dump_root, stage_root, stats)
    if "package_textures" in kinds_set:
        _package_textures(dump_root, stage_root, stats, jobs)
    if "models" in kinds_set:
        _models(dump_root, stage_root, stats, jobs)

    print(
        f"[browse] done: images={stats.images} text={stats.text} textures={stats.textures} "
        f"textures_png={stats.textures_png_ok}+{stats.textures_png_err}err "
        f"audio={stats.audio_ok}+{stats.audio_err}err "
        f"music={stats.music_ok}+{stats.music_err}err "
        f"soundbanks={stats.soundbanks_ok}+{stats.soundbanks_err}err ({stats.soundbank_cues} cues) "
        f"movies={stats.movies_ok}+{stats.movies_err}err "
        f"carved={stats.carved_jpgs} "
        f"txd={stats.text_txd} strings={stats.text_sniffed} "
        f"sme_banks={stats.sme_banks} ({stats.sme_cues} cues) "
        f"package_textures={stats.package_textures}"
        f"+{stats.package_dups}dup+{stats.package_err}err "
        f"from {stats.package_carriers} carriers "
        f"({stats.package_decompressed} LZSS packages) "
        f"models={stats.models_ok}+{stats.models_empty}empty+{stats.models_err}err "
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


__all__ = ["BundleStats", "ALL_KINDS", "bundle", "detect_dump_region", "game_path",
           "decode_txd", "decode_sb_strings", "decode_container_strings"]


# ---------------------------------------------------------------------------
# self-test
# ---------------------------------------------------------------------------

def self_test() -> int:
    """Synthetic checks of the text readers and the kind list; with XS3_D1 set,
    also decodes menutext.txd and one scene script from the disc."""
    import struct as _st
    ok = True

    def check(cond, msg):
        nonlocal ok
        print(("ok    " if cond else "FAIL  ") + msg)
        ok = ok and bool(cond)

    check("models" in ALL_KINDS, "browse kind 'models' is registered")
    # a counted .txd with a Latin-1 lone byte and a gate pair (A1 DF = ×)
    strs = [b"M\xf6bius", b"<\xa1\xdf>", b"Line\\nTwo"]
    hdr = 4 + 4 * len(strs)
    offs, blob = [], b""
    for t in strs:
        offs.append(hdr + len(blob))
        blob += t + b"\0"
    data = _st.pack("<I", len(strs)) + _st.pack(f"<{len(strs)}I", *offs) + blob
    got = decode_txd(data)
    check(got == ["Möbius", "<×>", "Line\\nTwo"], f"decode_txd reads the USA codec: {got}")
    # an SB v1.1 script: code, globals, pool, entries, imports, name
    pool_strs = [b"[Shion]<l2>Board the E.S.?", b"seg_now",
                 "テストです".encode("cp932") + b"\x81\x40"]
    pool = sb_mod.build_pool(pool_strs)
    body = b"\x08\0\0\0\0\0\0\0" * 2   # code + globals sections (empty)
    pool_off = 0x40 + len(body)
    after = pool_off + len(pool)
    tail = b"\x08\0\0\0\0\0\0\0" * 2 + b"\x01\0\0\0us\\test\0\0"
    secs = [0x40, 0x48, pool_off, after, after + 8, after + 16]
    sbd = b"SB  " + _st.pack("<HH", 1, 1) + _st.pack("<6I", *secs)
    sbd += b"\0" * (0x40 - len(sbd)) + body + pool + tail
    lines = decode_sb_strings(sbd)
    check(lines is not None and lines[0] == "[Shion]<l2>Board the E.S.?",
          f"decode_sb_strings dialogue line: {lines and lines[0]!r}")
    check(lines is not None and lines[1] == "seg_now", "identifier read as ASCII")
    check(lines is not None and lines[2].startswith("[note cp932] テスト"),
          f"Shift-JIS note via NoteCodec: {lines and lines[2]!r}")
    check(decode_sb_strings(b"XX  " + b"\0" * 0x40) is None, "non-SB data -> None")

    # region plumbing on synthetic data
    check(game_path(Path("chain0/mnu/jp/menutext.txd")) == "mnu\\jp\\menutext.txd"
          and game_path(Path("iso-disc2/SYSTEM.CNF")) == "SYSTEM.CNF"
          and game_path(Path("cf/us/1210.sb")) == "cf\\us\\1210.sb", "game_path drops chainN/iso")
    jp_line = "[シオン]テスト<w30>".encode("euc_jp")
    jl = decode_sb_strings(sbd.replace(pool, sb_mod.build_pool([jp_line, b"seg_now", b"x"]))
                           .replace(b"\x01\0\0\0us\\test", b"\x01\0\0\0jp\\test"), "jp")
    check(jl is not None and jl[0] == "[シオン]テスト<w30>", f"JP .sb read with the JP codec: {jl and jl[0]!r}")
    jt = decode_txd(_st.pack("<I", 1) + _st.pack("<I", 8) + "オプション".encode("euc_jp") + b"\0", "jp")
    check(jt == ["オプション"], f"JP .txd read with the JP codec: {jt}")
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "chain0" / "mnu" / "jp").mkdir(parents=True)
        (root / "chain0" / "mnu" / "jp" / "menutext.txd").write_bytes(b"")
        check(detect_dump_region(root).name == "jp", "a dump with mnu/jp/menutext.txd detects as jp")
        (root / "chain0" / "mnu" / "jp" / "menutext.txd").unlink()
        (root / "chain0" / "mnu" / "us").mkdir()
        (root / "chain0" / "mnu" / "us" / "menutext.txd").write_bytes(b"")
        check(detect_dump_region(root).name == "us", "a dump with mnu/us/menutext.txd detects as us")

    # the music kind: the soundtrack is the streams directly in snd\adx\
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "chain0" / "snd" / "adx" / "mev").mkdir(parents=True)
        (root / "chain0" / "snd" / "adx" / "B01.adx").write_bytes(adx_mod._synthetic())
        (root / "chain0" / "snd" / "adx" / "mev" / "s010100_01.adx").write_bytes(adx_mod._synthetic(flag=0))
        stage = root / "stage"
        n = _music_table(root, stage)
        text = (stage / "music" / "music.csv").read_text(encoding="utf-8") if n else ""
        check(n == 1 and text.splitlines()[0].startswith("track,path,") and "B01,snd\\adx\\B01.adx" in text
              and "s010100" not in text, "music.csv lists the soundtrack stream and not the voice stream")
        check("music" in ALL_KINDS and _EXTS["music"] == {".adx"}, "music is a browse kind")
        k, err, _ = _convert_one(root / "chain0" / "snd" / "adx" / "mev" / "s010100_01.adx", root, stage,
                                 "ffmpeg-not-run", [], {"music"})
        check(k == "skip" and err is None, "music alone leaves the voice streams alone")

    jp_iso = os.environ.get("XS3_JP1")
    if not jp_iso:
        print("SKIP  JP disc checks (set XS3_JP1)")
    else:
        import disc as disc_mod
        d = disc_mod.Disc(jp_iso)
        try:
            mt = decode_txd(d.read("mnu\\jp\\menutext.txd"), "jp")
            check(len(mt) == 909 and mt[8] == "オプション" and not any("�" in t for t in mt),
                  f"JP1 menutext.txd: {len(mt)} strings, #8 {mt[8] if len(mt) > 8 else None!r}")
            sl = decode_sb_strings(d.read("cf\\jp\\1220.sb"), "jp")
            check(sl is not None and len(sl) > 116 and not any(t.startswith("[note") for t in sl)
                  and any("\u3040" <= c <= "\u30ff" for t in sl for c in t),
                  f"JP1 cf\\jp\\1220.sb: {sl and len(sl)} strings, kana, no note prefixes")
            md = decode_container_strings("mg1\\jp\\Message.Dat", d.read("mg1\\jp\\Message.Dat"), "jp")
            check(md is not None and len(md) == 871, f"JP1 Message.Dat via msgdat: {md and len(md)} messages")
            check(sb_mod.scene_status("cf\\jp\\1218.sb") == sb_mod.JP_ONLY_STATUS,
                  "JP-only scene status is available for the text kind")
        finally:
            d.close()

    iso = os.environ.get("XS3_D1")
    if not iso:
        print("SKIP  disc checks (set XS3_D1)")
    else:
        import disc as disc_mod
        d = disc_mod.Disc(iso)
        mt = decode_txd(d.read("mnu\\us\\menutext.txd"))
        check(len(mt) > 900 and not any("�" in t for t in mt),
              f"D1 menutext.txd: {len(mt)} strings, no replacement characters")
        sl = decode_sb_strings(d.read("cf\\us\\1210.sb"))
        check(sl is not None and any("Möbius" in t for t in sl),
              "D1 cf\\us\\1210.sb reads 'Möbius'")
    print("browse_bundle self-test:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__" and "--self-test" in sys.argv:
    sys.exit(self_test())
