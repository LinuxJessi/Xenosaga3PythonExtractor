"""
cli.py — Command line entry-point.

Workflow:

    1. ``prep``         — run 7-Zip to list and extract X3.* parts
    2. ``map-regions``  — assign each LBA source to its container chain
    3. ``toc``          — print a human-readable summary of the LBA tables
    4. ``scan``         — produce ``manifest_merged.csv`` of resolved rows
    5. ``extract``      — write bytes out to a mirrored tree
    6. ``verify``       — cross-check sizes (and optionally SHA-1) of extracts
    7. ``doctor``       — check that prerequisites are in place

The pipeline only writes outside the ``--out`` directory during ``extract``,
so it's safe to repeatedly re-run scan/verify while iterating.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List

import browse_bundle
import chrtex
import code_extract
import disasm_code
import iso_ops
from containers import (
    RegionMap,
    load_container_map_raw,
    merge_regions_into_map,
    write_container_map,
)
from lba import discover_lba_files
from regions import auto_assign_regions, parse_manual_assignments, validate_regions, RegionAssignmentError
import resolver
import scooper
import toc as toc_mod
import verify_cmd


def _ensure_dirs(work: Path) -> None:
    (work / "lba").mkdir(parents=True, exist_ok=True)
    (work / "toc").mkdir(parents=True, exist_ok=True)
    (work / "out").mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# prep
# ---------------------------------------------------------------------------

def cmd_prep(args: argparse.Namespace) -> None:
    iso = Path(args.iso)
    work = Path(args.work)
    _ensure_dirs(work)
    if not iso.exists():
        raise SystemExit(f"ISO not found: {iso}")

    listing = iso_ops.sevenzip_list(iso, args.sevenzip)
    (work / "disc_7z_list.txt").write_text(listing, encoding="utf-8")

    conts = iso_ops.parse_sevenzip_containers(listing)
    if not conts:
        raise SystemExit("No X3.* containers found in 7-Zip listing.")
    write_container_map(work / "container_map.json", conts, regions=None)
    iso_ops.sevenzip_extract(iso, work, ["X3.*"], args.sevenzip)
    print(
        f"[prep] Wrote disc_7z_list.txt, container_map.json ({len(conts)} containers) "
        f"and extracted X3.* to {work}"
    )
    print("[prep] Next: run `map-regions` (auto or --assign) to wire LBA sources to containers.")


# ---------------------------------------------------------------------------
# container-map (rebuild from existing listing)
# ---------------------------------------------------------------------------

def cmd_container_map(args: argparse.Namespace) -> None:
    work = Path(args.work)
    _ensure_dirs(work)
    list_path = Path(args.list)
    if not list_path.exists():
        raise SystemExit(f"List file not found: {list_path}")
    conts = iso_ops.parse_sevenzip_containers(list_path.read_text(errors="ignore"))
    if not conts:
        raise SystemExit("No X3.* containers found in listing.")
    write_container_map(work / "container_map.json", conts, regions=None)
    print(f"[container-map] Wrote {work / 'container_map.json'} with {len(conts)} containers")


# ---------------------------------------------------------------------------
# map-regions
# ---------------------------------------------------------------------------

def cmd_map_regions(args: argparse.Namespace) -> None:
    work = Path(args.work)
    cmap_path = work / "container_map.json"
    if not cmap_path.exists():
        raise SystemExit("Missing container_map.json. Run `prep` (or `container-map`) first.")

    raw = load_container_map_raw(cmap_path)
    from containers import ContainerSet  # local import to avoid top-level cycle
    containers = ContainerSet.from_dicts(raw["containers"])
    lba_files = discover_lba_files(work)
    if not lba_files:
        raise SystemExit("No Lba*.txt files found in work/lba.")

    ignore = list(args.ignore or [])
    if not ignore and args.auto_ignore_small:
        # Heuristic: a "catalog" file is < 1 MiB. The known Xenosaga III
        # catalogs are X3.00 (~110 KB), X3.10 (~52 KB) on Disc 1 and X3.20
        # (~26 KB) on Disc 2.
        ignore = [c.name for c in containers if c.size < args.auto_ignore_small]

    if args.assign:
        regions = parse_manual_assignments(
            args.assign,
            containers=containers,
            lba_sources=[f.name for f in lba_files],
        )
        rationale = f"manual assignment: {regions}"
    else:
        try:
            result = auto_assign_regions(
                containers=containers,
                lba_files=lba_files,
                ignore=ignore,
            )
        except RegionAssignmentError as exc:
            raise SystemExit(
                f"[map-regions] auto-assign failed: {exc}\n"
                f"Inspect sizes with `doctor` and retry with --assign or --ignore."
            )
        regions = result.regions
        rationale = result.rationale

    problems = validate_regions(
        containers=containers,
        regions=regions,
        lba_files=lba_files,
        ignored=ignore,
    )
    if problems:
        print("[map-regions] WARNING:")
        for p in problems:
            print(f"  - {p}")

    merge_regions_into_map(cmap_path, regions)
    print(f"[map-regions] Wrote regions into {cmap_path}")
    print(rationale)


# ---------------------------------------------------------------------------
# toc
# ---------------------------------------------------------------------------

def cmd_toc(args: argparse.Namespace) -> None:
    work = Path(args.work)
    _ensure_dirs(work)
    lba_files = discover_lba_files(work)
    if not lba_files:
        raise SystemExit("No Lba*.txt files found in work/lba.")
    out = work / "toc" / "toc_headers.json"
    toc = toc_mod.build_toc_headers(lba_files, out)
    print(f"[toc] Wrote {out}")
    print(toc_mod.format_human_summary(toc))


# ---------------------------------------------------------------------------
# scan
# ---------------------------------------------------------------------------

def cmd_scan(args: argparse.Namespace) -> None:
    work = Path(args.work)
    _ensure_dirs(work)
    cmap = work / "container_map.json"
    if not cmap.exists():
        raise SystemExit("Missing container_map.json. Run `prep` first.")
    lba_files = discover_lba_files(work)
    if not lba_files:
        raise SystemExit("No Lba*.txt files found in work/lba.")

    region_map = RegionMap.from_json(cmap)  # raises if regions missing/invalid
    out_csv = work / "out" / "manifest_merged.csv"
    out_summary = work / "out" / "dry_run_summary.json"
    _, counts = resolver.map_rows_to_containers(
        lba_files,
        region_map,
        work,
        out_csv,
        out_summary,
        sniff=args.sniff,
        probe_bytes=args.probe,
    )
    print(f"[scan] Wrote {out_csv}")
    print(f"[scan] counts: {counts}")


# ---------------------------------------------------------------------------
# extract
# ---------------------------------------------------------------------------

def cmd_extract(args: argparse.Namespace) -> None:
    work = Path(args.work)
    _ensure_dirs(work)
    cmap = work / "container_map.json"
    if not cmap.exists():
        raise SystemExit("Missing container_map.json. Run `prep` first.")
    region_map = RegionMap.from_json(cmap)
    stats = scooper.extract_all(
        manifest_csv=work / "out" / "manifest_merged.csv",
        region_map=region_map,
        x3_dir=work,
        out_root=Path(args.out),
        dry_run=args.dry_run,
        write_hash=args.hash,
        limit=args.limit,
    )
    print(f"[extract] OK={stats.ok} ERR={stats.err} SKIPPED={stats.skipped}")


# ---------------------------------------------------------------------------
# verify
# ---------------------------------------------------------------------------

def cmd_verify(args: argparse.Namespace) -> None:
    work = Path(args.work)
    out_root = Path(args.out)
    stats = verify_cmd.verify(
        manifest_csv=work / "out" / "manifest_merged.csv",
        out_root=out_root,
        check_hashes=args.hash,
        limit=args.limit,
    )
    if stats.issues:
        print("\n".join(stats.issues[:50]))
        if len(stats.issues) > 50:
            print(f"...and {len(stats.issues) - 50} more")
    print(
        f"[verify] checked={stats.checked} missing={stats.missing} "
        f"size_mismatch={stats.size_mismatch} hash_mismatch={stats.hash_mismatch} "
        f"hash_unknown={stats.hash_unknown}"
    )
    if stats.total_failures():
        sys.exit(1)


# ---------------------------------------------------------------------------
# doctor
# ---------------------------------------------------------------------------

def cmd_doctor(args: argparse.Namespace) -> None:
    work = Path(args.work)
    print(f"[doctor] work dir: {work.resolve()}")
    cmap = work / "container_map.json"
    if not cmap.exists():
        print("  - container_map.json: MISSING (run `prep` or `container-map`)")
    else:
        data = load_container_map_raw(cmap)
        conts = data.get("containers", [])
        print(f"  - container_map.json: ok ({len(conts)} containers)")
        for c in conts:
            present = (work / c["name"]).exists()
            print(f"      {c['name']}: size={c['size']:>14}  on-disk={'yes' if present else 'NO'}")
        regions = data.get("regions") or {}
        if not regions:
            print("  - regions: NOT ASSIGNED (run `map-regions`)")
        else:
            print("  - regions:")
            for src, names in regions.items():
                size = sum(int(c["size"]) for c in conts if c["name"] in names)
                print(f"      {src} -> {names}  (chain size 0x{size:X})")

    lba_files = discover_lba_files(work)
    if not lba_files:
        print("  - lba/Lba*.txt: MISSING")
    else:
        print(f"  - lba/: {[f.name for f in lba_files]}")
        from lba import lba_max_end
        for f in lba_files:
            end = lba_max_end(f)
            print(f"      {f.name}: max byte-end 0x{end:X} ({end / 1e9:.2f} GB)")

    if any((work / "X3.{}".format(s)).exists() for s in ("00", "01", "02", "10", "11", "12", "13")):
        # quick on-disk listing
        on_disk = sorted(p.name for p in work.iterdir() if p.is_file() and p.name.startswith("X3."))
        print(f"  - X3.* on disk: {on_disk}")
    else:
        print("  - X3.* on disk: NONE (run `prep`)")


# ---------------------------------------------------------------------------
# chr texture modding (chrtex.py; see docs/MODDING-CHARACTERS.md)
# ---------------------------------------------------------------------------

def cmd_chr_decode(args: argparse.Namespace) -> None:
    chrtex.cmd_decode(args.chr, args.out)


def cmd_chr_palettes(args: argparse.Namespace) -> None:
    chrtex.cmd_export_palettes(args.chr, args.out)


def cmd_chr_import_palettes(args: argparse.Namespace) -> None:
    chrtex.cmd_import_palettes(args.chr, args.palettes, args.out)


def cmd_chr_import_entry(args: argparse.Namespace) -> None:
    chrtex.cmd_import_entry(args.chr, args.name, args.png, args.out)


def cmd_chr_recolor(args: argparse.Namespace) -> None:
    data = Path(args.chr).read_bytes()
    new, edits = chrtex.recolor(data, args.hue, args.mode)
    Path(args.out).write_bytes(new)
    print(f"{edits} palette words -> {args.out}")


def cmd_chr_iso_extract(args: argparse.Namespace) -> None:
    chrtex.cmd_iso_extract(args.iso, args.path, args.out, args.lba)


def cmd_chr_iso_patch(args: argparse.Namespace) -> None:
    chrtex.cmd_iso_patch(args.iso, args.path, args.file, args.lba)


def cmd_chr_iso_sweep(args: argparse.Namespace) -> None:
    chrtex.cmd_iso_sweep(args.iso, args.match, args.mode, args.hue, args.lba)


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Xenosaga III Python Extractor")
    sp = ap.add_subparsers(dest="cmd", required=True)

    p = sp.add_parser("prep", help="List ISO and extract X3.* with 7-Zip")
    p.add_argument("--iso", required=True)
    p.add_argument("--work", required=True)
    p.add_argument("--sevenzip", help="Path to 7z/7za (optional)")
    p.set_defaults(func=cmd_prep)

    cm = sp.add_parser("container-map", help="Rebuild container_map.json from a saved 7z listing")
    cm.add_argument("--list", required=True, help="disc_7z_list.txt from `7z l -ba`")
    cm.add_argument("--work", required=True)
    cm.set_defaults(func=cmd_container_map)

    mr = sp.add_parser("map-regions", help="Assign each Lba*.txt to one or more X3.* containers")
    mr.add_argument("--work", required=True)
    mr.add_argument(
        "--assign",
        action="append",
        default=[],
        help="Manual mapping like Lba0.txt=X3.01 or Lba1.txt=X3.11,X3.12,X3.13 (repeatable)",
    )
    mr.add_argument(
        "--ignore",
        action="append",
        default=[],
        help="Container name to exclude from auto-assignment (e.g. X3.00). Repeatable.",
    )
    mr.add_argument(
        "--auto-ignore-small",
        type=int,
        default=1 << 20,
        help="Auto-exclude containers smaller than this size (bytes). Default 1 MiB. Set 0 to disable.",
    )
    mr.set_defaults(func=cmd_map_regions)

    t = sp.add_parser("toc", help="Print a human summary of the LBA tables")
    t.add_argument("--work", required=True)
    t.set_defaults(func=cmd_toc)

    s = sp.add_parser("scan", help="Resolve LBA rows to containers and write the manifest")
    s.add_argument("--work", required=True)
    s.add_argument("--sniff", action="store_true", help="Sniff first bytes for diagnostics")
    s.add_argument("--probe", type=int, default=256, help="Probe size when --sniff is set")
    s.set_defaults(func=cmd_scan)

    e = sp.add_parser("extract", help="Extract files per manifest into a mirror tree")
    e.add_argument("--work", required=True)
    e.add_argument("--out", required=True)
    e.add_argument("--dry-run", action="store_true")
    e.add_argument("--hash", action="store_true", help="Write SHA-1 hashes to _reports/hashes.sha1")
    e.add_argument("--limit", type=int, default=None, help="Stop after N processed rows (debug)")
    e.set_defaults(func=cmd_extract)

    v = sp.add_parser("verify", help="Check extracted files against the manifest")
    v.add_argument("--work", required=True)
    v.add_argument("--out", required=True)
    v.add_argument("--hash", action="store_true", help="Verify SHA-1s from _reports/hashes.sha1")
    v.add_argument("--limit", type=int, default=None)
    v.set_defaults(func=cmd_verify)

    d = sp.add_parser("doctor", help="Show what's set up and what's missing")
    d.add_argument("--work", required=True)
    d.set_defaults(func=cmd_doctor)

    b = sp.add_parser(
        "browse",
        help="Build a sibling browse/ tree of viewable / playable formats",
    )
    b.add_argument("--dump", required=True, help="The dump/ directory produced by `extract`")
    b.add_argument("--stage", required=True, help="Fast scratch directory for ffmpeg output")
    b.add_argument("--out", help="Final destination (omit to leave outputs in --stage)")
    b.add_argument("--ffmpeg", default="ffmpeg", help="Path to ffmpeg (default: from PATH)")
    b.add_argument("--jobs", type=int, default=4, help="Parallel ffmpeg jobs (default 4)")
    b.add_argument("--sfd-preset", default="veryfast", help="x264 preset for SFD transcode")
    b.add_argument("--sfd-crf", type=int, default=23, help="x264 CRF for SFD transcode")
    b.add_argument(
        "--kinds",
        help=(
            "Comma-separated bundle categories: "
            "images,text,textures,textures_png,audio,soundbanks,movies,carved. Default: all."
        ),
    )
    b.set_defaults(func=cmd_browse)

    ce = sp.add_parser(
        "code-extract",
        help="Pull non-X3 files (SLUS, OVL, IRX, SYSTEM.CNF) out of the ISO",
    )
    ce.add_argument("--iso", required=True, help="Path to the disc ISO")
    ce.add_argument("--out", required=True, help="Destination directory (e.g. browse/code/)")
    ce.add_argument("--sevenzip", help="Path to 7z/7za (optional)")
    ce.set_defaults(func=cmd_code_extract)

    cd = sp.add_parser("chr-decode", help="Decode a .chr's textures to PNG")
    cd.add_argument("--chr", required=True, help=".chr (or .wpn/.sme) file")
    cd.add_argument("--out", required=True, help="output directory for PNGs")
    cd.set_defaults(func=cmd_chr_decode)

    cp = sp.add_parser("chr-palettes", help="Export CLUT tiles as editable 16x16 PNGs")
    cp.add_argument("--chr", required=True)
    cp.add_argument("--out", required=True)
    cp.set_defaults(func=cmd_chr_palettes)

    ci = sp.add_parser("chr-import-palettes", help="Write edited palette PNGs back into a .chr")
    ci.add_argument("--chr", required=True, help="original .chr")
    ci.add_argument("--palettes", required=True, help="directory of edited pal_*.png")
    ci.add_argument("--out", required=True, help="patched .chr to write")
    ci.set_defaults(func=cmd_chr_import_palettes)

    ie = sp.add_parser("chr-import-entry", help="Repaint a texture (quantized to its palette)")
    ie.add_argument("--chr", required=True)
    ie.add_argument("--name", required=True, help="entry name, e.g. shion_hair00")
    ie.add_argument("--png", required=True, help="replacement image, same size")
    ie.add_argument("--out", required=True)
    ie.set_defaults(func=cmd_chr_import_entry)

    cr = sp.add_parser("chr-recolor", help="Hair recolor of one .chr (worked example)")
    cr.add_argument("--chr", required=True)
    cr.add_argument("--out", required=True)
    cr.add_argument("--mode", choices=["blue", "warm"], required=True,
                    help="blue: band-filter all tiles (KOS-MOS). warm: name-policy tiles (Shion)")
    cr.add_argument("--hue", type=float, default=0.92, help="target hue 0..1 (default rose pink)")
    cr.set_defaults(func=cmd_chr_recolor)

    xe = sp.add_parser("chr-iso-extract", help="Pull one file out of an ISO via the Lba tables")
    xe.add_argument("--iso", required=True)
    xe.add_argument("--path", required=True, help=r"disc path, e.g. \mdl\chr\pc\C3shion00.chr")
    xe.add_argument("--out", required=True)
    xe.add_argument("--lba", help="dir with Lba0.txt (default: the kit's lba/)")
    xe.set_defaults(func=cmd_chr_iso_extract)

    xp = sp.add_parser("chr-iso-patch", help="Write a same-size file back into an ISO (verified)")
    xp.add_argument("--iso", required=True)
    xp.add_argument("--path", required=True)
    xp.add_argument("--file", required=True)
    xp.add_argument("--lba", help="dir with Lba0.txt (default: the kit's lba/)")
    xp.set_defaults(func=cmd_chr_iso_patch)

    xs = sp.add_parser("chr-iso-sweep",
                       help="Recolor every matching .chr inside an ISO, in place (verified)")
    xs.add_argument("--iso", required=True, help="work on a COPY of your ISO")
    xs.add_argument("--match", required=True, help="filename substring, e.g. kosmos or shion")
    xs.add_argument("--mode", choices=["blue", "warm"], required=True)
    xs.add_argument("--hue", type=float, default=0.92)
    xs.add_argument("--lba", help="dir with Lba0.txt (default: the kit's lba/)")
    xs.set_defaults(func=cmd_chr_iso_sweep)

    da = sp.add_parser(
        "disasm",
        help="Disassemble PS2 ELFs (SLUS / OVL) and emit string xrefs. Needs `pip install capstone`.",
    )
    da.add_argument("--code-dir", required=True, help="Directory with extracted SLUS/OVL files")
    da.add_argument(
        "--elf",
        action="append",
        help="Specific ELF file to disassemble (repeatable). Default: auto-discover SLUS_* and *.OVL.",
    )
    da.add_argument("--out", help="Output directory for .disasm.txt and .strings_xrefs.txt (default: --code-dir)")
    da.set_defaults(func=cmd_disasm)

    return ap


def cmd_browse(args: argparse.Namespace) -> None:
    kinds = None
    if args.kinds:
        kinds = [k.strip() for k in args.kinds.split(",") if k.strip()]
    stats = browse_bundle.bundle(
        dump_root=Path(args.dump),
        stage_root=Path(args.stage),
        final_root=Path(args.out) if args.out else None,
        ffmpeg=args.ffmpeg,
        jobs=args.jobs,
        sfd_preset=args.sfd_preset,
        sfd_crf=args.sfd_crf,
        kinds=kinds,
    )
    if stats.audio_err or stats.soundbanks_err or stats.movies_err or stats.textures_png_err:
        sys.exit(1)


def cmd_code_extract(args: argparse.Namespace) -> None:
    stats = code_extract.extract_code(
        iso_path=Path(args.iso),
        out_dir=Path(args.out),
        seven_zip=args.sevenzip,
    )
    print(f"[code-extract] wrote {stats.files} files ({stats.total_bytes:,} bytes) to {args.out}")


def cmd_disasm(args: argparse.Namespace) -> None:
    code_dir = Path(args.code_dir)
    if not code_dir.exists():
        raise SystemExit(f"code dir not found: {code_dir}")
    explicit = [Path(p) for p in (args.elf or [])]
    elfs = explicit or code_extract.discover_executables(code_dir)
    if not elfs:
        raise SystemExit(
            f"no ELFs found under {code_dir}; pass --elf or run `code-extract` first."
        )
    out_dir = Path(args.out) if args.out else code_dir
    try:
        stats = disasm_code.disassemble_all(elfs, out_dir)
    except disasm_code.DisasmError as exc:
        raise SystemExit(f"[disasm] {exc}")
    print(
        f"[disasm] {stats.files} ELFs, "
        f"{stats.instructions:,} instructions, "
        f"{stats.unique_string_xrefs:,} unique strings xref'd"
    )


def main(argv: List[str] | None = None) -> None:
    ap = _build_parser()
    args = ap.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main(sys.argv[1:])
