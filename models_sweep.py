#!/usr/bin/env python3
"""Episode III models: one model -> .glb, and a sweep of every model on a
disc (the numbers quoted in docs/MODELS.md come from this tool).

    python models_sweep.py --self-test
    python cli.py model  --iso D1.iso --path 'mdl\\chr\\pc\\C3kosmos00.chr' --out kosmos.glb
    python cli.py models --iso D1.iso [--iso D2.iso] --out DIR [--filter kosmos]

A model is any of

* an MR package (`xcpack.py`) `.chr` / `.wpn` / `.map`: its `pxy` slot is
  the mesh, `txy` the textures, `xhr` the skeleton (sub-resource data at
  0x40 + the directory offset; field maps are LZSS-compressed and go
  through `xcpack.normalize`; a few maps have an empty pxy slot), or
* a standalone `.pxy` (mnu/, mg1/, mdl/map/ev ...), with the `.txy` and
  `.xhr` of the same name in the same folder when the disc has them.

The sweep takes a `read(path) -> bytes` callable and a list of in-game
paths, so it runs on an ISO (`IsoSource`, through the disc's own
X3.00/X3.10/X3.20 indexes via x3index.py: works on the retail discs and
the May 2006 prototype alike), through the foundation `disc.Disc`
(`DiscSource`: any region, USA, Japan or prototype; the `model` and
`models` commands use it), on a dump folder (`DirSource`), or on any
other reader the kit grows (`open_source` picks one).

Borrowed from the Xenosaga Episode II kit,
Xenosaga2PythonExtractor/models_sweep.py (same author, MIT), 2026-11-20:
the per-model invariant row, the GLB read-back and the skinning check
are the XS2 `sweep_one` / `report` logic.  Changed: models are found by
walking packages and standalone pxy through a reader instead of `.pxy`
files in a dump; textures come from chrtex.py via `pxy.TextureSet`;
glb files and a `models.csv` are written; `add_commands()` registers
`model` and `models`; `browse_models()` is the browse hook.  The XS2
VIF-opcode inventory mode was not carried over.

2026-11-21: motion.  `model` takes `--motion PATH[#SLOTS]` (repeatable),
`--no-motion` and `--matched-only`; without `--motion` it adds every
same-stem motion (`xap.same_stem_sources`: pac/cf and pac/bat `.sme`,
same-stem `.xap`, and a `.wpn`'s own clips).  The sweep (and so browse
kind "models") does the same and adds the CSV columns `motion` and
`motion_counts_differ` (as Episode II's browse.py); `--no-motion` on
`models` turns it off.  The motion decoder is xap.py.
"""
import csv
import fnmatch
import io
import os
import struct
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import gltf    # noqa: E402
import pxy     # noqa: E402
import vif     # noqa: E402
import xap     # noqa: E402
import xcpack  # noqa: E402
import xhr     # noqa: E402

PACKAGE_EXTS = (".chr", ".wpn", ".map")
MODEL_EXTS = PACKAGE_EXTS + (".pxy",)
SECTOR = 2048
CSV_FIELDS = ["disc", "path", "kind", "status", "layouts", "verts",
              "batch_verts", "tris", "header_tris", "joints", "xhr",
              "textures", "texture_unlinked", "skin_rest_err", "failed",
              "notes", "motion", "motion_counts_differ", "glb"]


def norm_path(path):
    """In-game path key: backslashes, one leading backslash, lower case."""
    k = path.strip().replace("/", "\\")
    if not k.startswith("\\"):
        k = "\\" + k
    return k.lower()


# ------------------------------------------------------------------ readers

class IsoSource(object):
    """Files of an ISO through the disc's own X3.x0 indexes.

    Every sector number in an index counts from the index file's first
    sector and the bigfiles follow it contiguously (x3index.py), so a
    file's ISO byte offset is (index extent + sector) * 2048.  Picklable
    (worker processes reopen the image)."""

    def __init__(self, iso):
        import x3index
        self.iso = str(iso)
        self.table = {}
        root = _iso_root(self.iso)
        for name in ("X3.00", "X3.10", "X3.20"):
            if name not in root:
                continue
            ext, size = root[name]
            with open(self.iso, "rb") as f:
                f.seek(ext * SECTOR)
                data = f.read(size)
            for e in x3index.parse_index(data):
                self.table[norm_path(e.path)] = (
                    (ext + e.sector) * SECTOR, e.size, e.path)
        if not self.table:
            raise ValueError("%s: no X3.00/X3.10/X3.20 index in the ISO root"
                             % self.iso)
        self.paths = [v[2] for v in self.table.values()]

    def __call__(self, path):
        try:
            off, size, _ = self.table[norm_path(path)]
        except KeyError:
            raise KeyError("%s: not in this disc's index" % path)
        with open(self.iso, "rb") as f:
            f.seek(off)
            data = f.read(size)
        if len(data) != size:
            raise IOError("%s: short read" % path)
        return data


def _iso_root(iso):
    """name -> (extent sector, size) of every ISO9660 root file."""
    with open(iso, "rb") as f:
        f.seek(16 * SECTOR)
        pvd = f.read(SECTOR)
        if pvd[1:6] != b"CD001":
            raise ValueError("%s: not an ISO9660 image" % iso)
        rext, = struct.unpack_from("<I", pvd, 156 + 2)
        rsz, = struct.unpack_from("<I", pvd, 156 + 10)
        f.seek(rext * SECTOR)
        d = f.read(rsz)
    out, off = {}, 0
    while off < len(d):
        ln = d[off]
        if ln == 0:
            off = (off // SECTOR + 1) * SECTOR
            continue
        ext, = struct.unpack_from("<I", d, off + 2)
        sz, = struct.unpack_from("<I", d, off + 10)
        nl = d[off + 32]
        name = d[off + 33:off + 33 + nl].split(b";")[0].decode("latin1")
        out[name.upper()] = (ext, sz)
        off += ln
    return out


class DirSource(object):
    """Files of a dump folder laid out like the disc (dump/mdl/chr/...)."""

    def __init__(self, root):
        self.root = Path(root)
        self.table = {}
        for d, _, names in os.walk(self.root):
            for n in names:
                rel = os.path.relpath(os.path.join(d, n), self.root)
                gp = "\\" + rel.replace(os.sep, "\\")
                self.table[norm_path(gp)] = gp
        self.paths = sorted(self.table.values())

    def __call__(self, path):
        gp = self.table[norm_path(path)]
        return (self.root / gp.lstrip("\\").replace("\\", os.sep)).read_bytes()


class DiscSource(object):
    """Files of any disc the kit's `disc.Disc` opens: every chain's own
    X3.x0 index (USA, Japan, the May 2006 prototype; no region table), then
    the ISO filesystem.  Takes an ISO path or an open `Disc`.  Picklable:
    worker processes reopen the image by path."""

    def __init__(self, disc_or_path):
        import disc as _disc
        if isinstance(disc_or_path, (str, Path)):
            self._disc = _disc.Disc(disc_or_path)
        else:
            self._disc = disc_or_path
        self.iso = str(self._disc.path)
        self.table = {}
        for _c, e in self._disc.entries():
            k = norm_path(e.path)
            if k not in self.table:
                self.table[k] = "\\" + e.path.replace("/", "\\").lstrip("\\")
        if not self.table:
            raise ValueError("%s: no X3.x0 index on this image" % self.iso)
        self.paths = list(self.table.values())

    def region(self):
        """Profile name of the image (region.region_of), e.g. us / jp."""
        import region
        return region.region_of(self._disc).name

    def __getstate__(self):
        return {"iso": self.iso}

    def __setstate__(self, st):
        self.__init__(st["iso"])

    def __call__(self, path):
        try:
            return self._disc.read(path)
        except FileNotFoundError:
            raise KeyError("%s: not in this disc's index" % path)


def open_source(x):
    """A reader for any model source: an ISO path (through `DiscSource`, so
    any region), a dump folder, a `disc.Disc`, an existing source, or a
    `(read, paths)` pair (returned as is)."""
    if isinstance(x, (IsoSource, DirSource, DiscSource, tuple)):
        return x
    if isinstance(x, (str, Path)):
        return DirSource(x) if Path(x).is_dir() else DiscSource(x)
    if hasattr(x, "entries") and hasattr(x, "read"):
        return DiscSource(x)
    raise TypeError("not a model source: %r" % (x,))


# ------------------------------------------------------------------ loading

def _sub(data, subs, tag):
    if tag not in subs or not subs[tag][1]:
        return None
    o, n = subs[tag]
    if 0x40 + o + n > len(data):
        raise pxy.PxyError("%s slot runs past the package" % tag)
    return data[0x40 + o:0x40 + o + n]


def load_package(raw):
    """(Pxy or None, TextureSet or None, Xhr or None) of an MR package.
    The Pxy is None when the package has no / an empty pxy slot."""
    data = xcpack.normalize(raw)
    subs = xcpack.sub_resources(data)
    pb = _sub(data, subs, "pxy")
    if pb is None:
        return None, None, None
    p = pxy.parse(pb)
    xb = _sub(data, subs, "xhr")
    x = xhr.parse(xb) if xb is not None else None
    return p, pxy.package_textures(data), x


def _stem(path):
    return path[:path.rfind(".")] if "." in path.rsplit("\\", 1)[-1] \
        else path


def load_model(read, path, have=None):
    """(Pxy or None, TextureSet or None, Xhr or None, notes) of a model
    path.  `have`: set of norm_path keys present (for a standalone .pxy's
    .txy/.xhr companions; probed with `read` when None)."""
    notes = {}
    if path.lower().endswith(".pxy"):
        p = pxy.parse(read(path))
        tex = x = None
        for ext in (".txy", ".xhr"):
            comp = _stem(path) + ext
            if have is not None and norm_path(comp) not in have:
                continue
            try:
                blob = read(comp)
            except (KeyError, FileNotFoundError):
                continue
            if ext == ".txy":
                tex = pxy.txy_textures(blob)
                notes["txy"] = comp
            else:
                x = xhr.parse(blob)
                notes["xhr_file"] = comp
        return p, tex, x, notes
    p, tex, x = load_package(read(path))
    return p, tex, x, notes


def convert(read, path, have=None, name=None):
    """(glb bytes or None, Pxy, check dict) for one model path."""
    p, tex, x, _ = load_model(read, path, have)
    if p is None:
        return None, None, None
    r = pxy.check(p, tex.entries if tex is not None else None)
    if not r["triangles"]:
        return None, p, r
    skinned = any(b.skin_mode for d in p.draws for b in d.batches)
    if x is not None and len(x.joints) < p.n_joint_matrices + 2:
        x = None
    glb = pxy.to_glb(p, tex, x if skinned else None,
                     name or path.rsplit("\\", 1)[-1])
    return glb, p, r


def add_motion(read, blob, x, path, specs=None, index=None,
               matched_only=False):
    """Append motion to a model's .glb (xap.add_to_glb).  `specs`: the
    --motion strings, else the same-stem motion of `index`
    (xap.motion_index).  Returns (blob, summary, skipped, notes); summary
    and skipped as xap.add_to_glb.  Raises xap.XapError when a --motion
    spec cannot be read."""
    notes = []
    if specs:
        srcs = []
        for spec in specs:
            try:
                srcs.append(xap.load_motion(read, spec))
            except KeyError as e:
                raise xap.XapError("%s: %s" % (spec, e))
    else:
        srcs, notes = xap.same_stem_sources(read, path, index or {})
    if not srcs:
        return blob, [], [], notes
    blob, summary, skipped = xap.add_to_glb(blob, x, srcs, matched_only)
    return blob, summary, skipped, notes


def motion_text(summary):
    """(models.csv "motion", "motion_counts_differ") from a summary."""
    per = {}
    for sm in summary:
        src = sm["name"].split("#", 1)[0]
        per.setdefault(src, []).append(sm)
    parts = []
    for src, sms in per.items():
        odd = [s for s in sms if s["counts_differ"]]
        t = "%s: %d animations" % (src, len(sms))
        if odd:
            t += " (%s)" % ", ".join(
                "#%s %s" % (s["name"].split("#", 1)[1].split(" ", 1)[0],
                            xap.mismatch_text(s["counts_differ"]))
                for s in odd)
        parts.append(t)
    return "; ".join(parts), sum(bool(s["counts_differ"]) for s in summary)


# -------------------------------------------------------------------- sweep

def glb_names(paths):
    """In-game model path -> relative .glb path.  `stem.glb`, unless two
    models in one folder share a stem (then `name.ext.glb`)."""
    seen = {}
    for pth in paths:
        k = norm_path(_stem(pth))
        seen[k] = seen.get(k, 0) + 1
    out = {}
    for pth in paths:
        rel = pth.lstrip("\\").replace("\\", "/")
        if seen[norm_path(_stem(pth))] > 1:
            out[pth] = rel + ".glb"
        else:
            out[pth] = rel[:rel.rfind(".")] + ".glb"
    return out


def select(paths, filt=None):
    """Model paths (packages + standalone pxy) of a path list, sorted,
    optionally filtered by a case-insensitive substring or glob."""
    out = [q for q in paths if q.lower().endswith(MODEL_EXTS)]
    if filt:
        f = filt.lower()
        if any(ch in f for ch in "*?["):
            out = [q for q in out if fnmatch.fnmatch(q.lower(), f)
                   or fnmatch.fnmatch(q.lower().replace("\\", "/"), f)]
        else:
            out = [q for q in out if f in q.lower()
                   or f in q.lower().replace("\\", "/")]
    return sorted(out, key=str.lower)


def sweep_one(read, path, have=None, out_file=None, verify=True,
              motion_index=None):
    """Decode, check, write and read back one model.  Returns a CSV row.
    `motion_index` (xap.motion_index): add the same-stem motion; None:
    no motion."""
    kind = path.rsplit(".", 1)[-1].lower()
    row = dict(path=path, kind=kind, status="", layouts="", verts="",
               batch_verts="", tris="", header_tris="", joints="", xhr="",
               textures="", texture_unlinked="", skin_rest_err="",
               failed="", notes="", motion="", motion_counts_differ="",
               glb="")
    try:
        p, tex, x, notes = load_model(read, path, have)
    except (pxy.PxyError, vif.VifError, xhr.XhrError, xcpack.XcError,
            ValueError, KeyError, IndexError, struct.error) as e:
        row["status"] = "decode-failed"
        row["failed"] = "%s: %s" % (type(e).__name__, e)
        return row
    if p is None:
        row["status"] = "empty"
        row["failed"] = "empty pxy slot"
        return row
    try:
        r = pxy.check(p, tex.entries if tex is not None else None)
    except pxy.PxyError as e:
        row["status"] = "decode-failed"
        row["failed"] = "check: %s" % e
        return row
    row["layouts"] = " ".join("%s:%d" % kv for kv in sorted(r["layouts"].items()))
    row["batch_verts"] = r["vertices"]
    row["tris"] = r["triangles"]
    row["header_tris"] = pxy.header_triangles(p)
    row["joints"] = p.n_joint_matrices
    row["texture_unlinked"] = r.get("texture_unlinked", "")
    skinned = any(b.skin_mode for d in p.draws for b in d.batches)
    if x is not None:
        row["xhr"] = "%.1f/%d" % (x.version, len(x.joints))
        if len(x.joints) < p.n_joint_matrices + 2:
            row["xhr"] += " (too few transforms)"
            x = None
    else:
        row["xhr"] = "none"
    failed = list(r["failed"])
    if p.child is not None:
        row["notes"] = "pxy at +0xD0: %d triangles" % r["child_triangles"]
    if not r["triangles"]:
        # a non-empty pxy that decodes to nothing, neither itself nor at
        # +0xD0 (none on any disc since the +0xD0 pxy is read): not "ok",
        # and no (invalid, empty) glb
        row["status"] = "unexplained"
        row["failed"] = "; ".join(failed + [
            "%d draws, 0 triangles decoded from a %d-byte pxy with %d "
            "materials; no glb written" % (len(pxy.all_draws(p)), p.size,
                                           len(p.materials))])
        return row
    try:
        blob = pxy.to_glb(p, tex, x if skinned else None,
                          path.rsplit("\\", 1)[-1])
    except Exception as e:              # report, never hide
        row["status"] = "glb-failed"
        row["failed"] = "; ".join(failed + ["to_glb: %r" % (e,)])
        return row
    if verify:
        try:
            js, binc = gltf.read_glb(blob)
            nt = nv = 0
            for m in js.get("meshes", ()):
                for pr in m["primitives"]:
                    nt += js["accessors"][pr["indices"]]["count"] // 3
                    nv += js["accessors"][pr["attributes"]["POSITION"]]["count"]
            row["verts"] = nv
            row["textures"] = len(js.get("images", ()))
            row["notes"] = "; ".join(
                ([row["notes"]] if row["notes"] else [])
                + list(js.get("extras", {}).get("warnings", ())))
            if nt != pxy.header_triangles(p):
                failed.append("glb triangles %d != header %d"
                              % (nt, pxy.header_triangles(p)))
            if skinned:
                worst = 0.0
                for i, nd in enumerate(js["nodes"]):
                    if "mesh" in nd and "skin" in nd:
                        for st, sk in gltf.skinned_positions(js, binc, i):
                            if len(st):
                                worst = max(worst,
                                            float(np.abs(st - sk).max()))
                row["skin_rest_err"] = "%.3g" % worst
                if worst >= 1e-5:
                    failed.append("skinned rest pose off by %.3g" % worst)
        except Exception as e:
            row["status"] = "glb-failed"
            row["failed"] = "; ".join(failed + ["read_glb: %r" % (e,)])
            return row
    if motion_index is not None and skinned and x is not None:
        try:                             # never blocks the mesh
            blob, summ, _, mnotes = add_motion(read, blob, x, path,
                                               index=motion_index)
            row["motion"], nd = motion_text(summ)
            row["motion_counts_differ"] = nd if summ else ""
            if mnotes:
                row["notes"] = "; ".join(([row["notes"]] if row["notes"]
                                          else []) + mnotes)
        except Exception as e:
            row["motion"] = "not decoded: %s" % e
    if out_file:
        out_file = Path(out_file)
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_bytes(blob)
        row["glb"] = str(out_file)
    row["failed"] = "; ".join(failed)
    row["status"] = "ok" if not failed else "check-failed"
    return row


_WORKER = {}


def _init_worker(read, have, out_dir, names, verify, mindex=None):
    _WORKER.update(read=read, have=have, out_dir=out_dir, names=names,
                   verify=verify, mindex=mindex)


def _work(path):
    w = _WORKER
    out = Path(w["out_dir"]) / w["names"][path] if w["out_dir"] else None
    return sweep_one(w["read"], path, w["have"], out, w["verify"],
                     w.get("mindex"))


def sweep(read, paths, out_dir=None, filt=None, jobs=1, verify=True,
          disc="", log=None, motion=True):
    """Sweep every model among `paths` (in-game paths readable by `read`).
    Writes `<out_dir>/<path>.glb` when out_dir is given; `motion` adds the
    same-stem clips (xap.py).  Returns rows."""
    models = select(paths, filt)
    have = set(norm_path(q) for q in paths)
    names = glb_names(models)
    mindex = xap.motion_index(paths) if motion else None
    rows = []
    if jobs > 1 and len(models) > 1:
        import concurrent.futures as cf
        import pickle
        try:
            pickle.dumps(read)
        except Exception:
            jobs = 1
    if jobs > 1 and len(models) > 1:
        with cf.ProcessPoolExecutor(jobs, initializer=_init_worker,
                                    initargs=(read, have, out_dir, names,
                                              verify, mindex)) as ex:
            for i, row in enumerate(ex.map(_work, models, chunksize=4)):
                rows.append(row)
                if log and (i % 100 == 99 or row["status"] != "ok"):
                    log("  [%d/%d] %s %s" % (i + 1, len(models), row["status"],
                                             row["path"]))
    else:
        _init_worker(read, have, out_dir, names, verify, mindex)
        for i, pth in enumerate(models):
            row = _work(pth)
            rows.append(row)
            if log and (i % 100 == 99 or row["status"] != "ok"):
                log("  [%d/%d] %s %s" % (i + 1, len(models), row["status"],
                                         pth))
    for row in rows:
        row["disc"] = disc
    return rows


def write_csv(rows, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)


def summarize(rows):
    """Counters for a sweep (what docs/MODELS.md quotes)."""
    s = dict(models=len(rows))
    for st in ("ok", "check-failed", "decode-failed", "glb-failed", "empty",
               "unexplained"):
        s[st] = sum(1 for r in rows if r["status"] == st)
    dec = [r for r in rows if r["tris"] != ""]
    s["tri_mismatch"] = sum(1 for r in dec if r["tris"] != r["header_tris"])
    s["triangles"] = sum(int(r["tris"]) for r in dec)
    by = {}
    for r in rows:
        k = (r["kind"], r["status"])
        by[k] = by.get(k, 0) + 1
    s["by_kind"] = {"%s %s" % k: v for k, v in sorted(by.items())}
    lay = {}
    for r in rows:
        for part in r["layouts"].split():
            name, n = part.split(":")
            lay[name] = lay.get(name, 0) + 1
    s["files_with_layout"] = lay
    skin = [float(r["skin_rest_err"]) for r in rows if r["skin_rest_err"]]
    s["skinned"] = len(skin)
    s["skin_rest_err_max"] = max(skin) if skin else 0.0
    s["texture_unlinked"] = sum(int(r["texture_unlinked"] or 0) for r in rows)
    s["xhr"] = sum(1 for r in rows if r["xhr"] not in ("", "none"))
    return s


def report(rows, out=sys.stdout):
    s = summarize(rows)
    out.write("models: %(models)d; ok %(ok)d, check-failed %(check-failed)d, "
              "decode-failed %(decode-failed)d, glb-failed %(glb-failed)d, "
              "empty pxy slot %(empty)d, unexplained (decodes to nothing) "
              "%(unexplained)d\n" % s)
    out.write("triangles %d; header != decoded in %d; texture batches "
              "unlinked %d; skinned %d (rest-pose error max %.3g); with xhr "
              "%d\n" % (s["triangles"], s["tri_mismatch"],
                        s["texture_unlinked"], s["skinned"],
                        s["skin_rest_err_max"], s["xhr"]))
    out.write("files per batch layout: %s\n" % s["files_with_layout"])
    out.write("by kind/status: %s\n" % s["by_kind"])
    for r in rows:
        if r["status"] not in ("ok", "empty"):
            out.write("  %s %s: %s\n" % (r["status"], r["path"], r["failed"]))
    return s


# ------------------------------------------------------------ browse hook

def browse_models(dump_or_reader, out_dir, jobs=None, filt=None, log=None):
    """Browse kind "models": every model -> `<out_dir>/<path>.glb` plus
    `<out_dir>/models.csv`.  `dump_or_reader`: anything `open_source`
    takes (a dump folder, an ISO path of any region, a `disc.Disc`, a
    source, or a `(read, paths)` pair)."""
    src = open_source(dump_or_reader)
    if isinstance(src, tuple):
        read, paths = src
    else:
        read, paths = src, src.paths
    jobs = jobs or max(1, (os.cpu_count() or 2) - 1)
    rows = sweep(read, paths, out_dir, filt=filt, jobs=jobs, log=log)
    write_csv(rows, Path(out_dir) / "models.csv")
    return rows


# --------------------------------------------------------------------- CLI

def _cmd_model(a):
    if a.iso:
        src = DiscSource(a.iso)
    elif a.dump:
        src = DirSource(a.dump)
    else:
        print("model: give --iso or --dump", file=sys.stderr)
        return 2
    have = set(src.table)
    try:
        glb, p, r = convert(src, a.path, have)
    except KeyError as e:
        print("model: %s" % e, file=sys.stderr)
        return 2
    if glb is None and p is not None:
        print("%s: pxy %.2f, %d draws, 0 triangles from a %d-byte pxy with %d "
              "materials (nor at +0xD0); no glb written"
              % (a.path, p.version, len(pxy.all_draws(p)), p.size,
                 len(p.materials)))
        return 1
    if glb is None:
        print("%s: empty pxy slot (no mesh in this package)" % a.path)
        return 1
    out = Path(a.out or (a.path.rsplit("\\", 1)[-1].rsplit("/", 1)[-1]
                         .rsplit(".", 1)[0] + ".glb"))
    out.parent.mkdir(parents=True, exist_ok=True)
    print("%s: pxy %.2f, %d draws, %d triangles (header %d), layouts %s, "
          "%d joint matrices" % (a.path, p.version, len(pxy.all_draws(p)),
                                 r["triangles"], pxy.header_triangles(p),
                                 r["layouts"], p.n_joint_matrices))
    if p.child is not None:
        print("  of which the pxy at +0xD0 (%r): %d draws, %d triangles"
              % (p.child.name, len(p.child.draws), r["child_triangles"]))
    print("  checks: %s" % ("all pass" if not r["failed"]
                            else "; ".join(r["failed"])))
    motion = "off" if a.no_motion else "no"
    if not a.no_motion:
        _, _, x, _ = load_model(src, a.path, have)
        skinned = any(b.skin_mode for d in p.draws for b in d.batches)
        if x is None or not skinned or len(x.joints) < p.n_joint_matrices + 2:
            motion = "no (no skeleton in the .glb)"
            if a.motion:
                print("model: --motion needs a skinned model with its .xhr",
                      file=sys.stderr)
                return 2
        else:
            try:
                glb, summ, skipped, notes = add_motion(
                    src, glb, x, a.path, a.motion,
                    None if a.motion else xap.motion_index(src.paths),
                    a.matched_only)
            except xap.XapError as e:
                print("model: motion: %s" % e, file=sys.stderr)
                return 2
            for n in notes:
                print("  motion not decoded: %s" % n)
            for sm in summ:
                if sm["counts_differ"]:
                    print("  motion: %s: run counts differ from the "
                          "skeleton's (clip/xhr); not known to be made for it"
                          % sm["name"])
            for sk in skipped:
                print("  motion: %s left out: run counts differ (clip/xhr "
                      "%s)" % (sk["name"], xap.mismatch_text(sk["counts"])))
            differ = sum(bool(sm["counts_differ"]) for sm in summ)
            motion = "%d animations" % len(summ)
            if differ:
                motion += " (%d with run counts that differ, flagged)" % differ
            if skipped:
                motion += ", %d left out (run counts differ)" % len(skipped)
    print("  motion: %s" % motion)
    out.write_bytes(glb)
    print("wrote %s (%d bytes)" % (out, len(glb)))
    return 0 if not r["failed"] else 1


def _cmd_models(a):
    out = Path(a.out)
    srcs = []
    for iso in a.iso or []:
        srcs.append(DiscSource(iso))
    if a.dump:
        srcs.append(DirSource(a.dump))
    if not srcs:
        print("models: give --iso (repeatable) or --dump", file=sys.stderr)
        return 2
    all_rows = []
    for k, src in enumerate(srcs):
        label = "disc%d" % (k + 1) if len(srcs) > 1 else ""
        dest = out / label if label else out
        reg = src.region() if hasattr(src, "region") else "dump"
        print("%s: %s [%s]" % (label or "models",
                               getattr(src, "iso", None) or src.root, reg))
        rows = sweep(src, src.paths, None if a.no_glb else dest,
                     filt=a.filter, jobs=a.jobs or max(1, (os.cpu_count()
                                                           or 2) - 1),
                     disc=label, log=print, motion=not a.no_motion)
        report(rows)
        all_rows += rows
    write_csv(all_rows, out / "models.csv")
    print("wrote %s" % (out / "models.csv"))
    bad = [r for r in all_rows
           if r["status"] not in ("ok", "empty", "unexplained")]
    return 1 if bad else 0


def add_commands(subparsers):
    """Register `model` (one model -> .glb) and `models` (sweep), and
    `blend` (blend.py: a model -> .blend) so cli.py has it through this
    module's entry; blend.add_commands skips itself if already there."""
    m = subparsers.add_parser(
        "model", help="One model (.chr/.wpn/.map package or .pxy) -> .glb "
        "for Blender")
    m.add_argument("--iso", help="disc image (read through its X3 index)")
    m.add_argument("--dump", help="or a dump folder laid out like the disc")
    m.add_argument("--path", required=True,
                   help=r"in-game path, e.g. 'mdl\chr\pc\C3kosmos00.chr'")
    m.add_argument("--out", help="output .glb (default: <name>.glb)")
    m.add_argument("--motion", action="append", metavar="PATH[#SLOTS]",
                   help=r"motion to add as glTF animations: a .sme / .wpn "
                   r"package or a .xap / .fap, e.g. 'pac\cf\C3kosmos00.sme#1' "
                   "(repeatable; default: every same-stem motion)")
    m.add_argument("--no-motion", action="store_true",
                   help="mesh and skeleton only")
    m.add_argument("--matched-only", action="store_true",
                   help="leave out clips whose run counts differ from the "
                   "skeleton's")
    m.set_defaults(func=_cmd_model)
    s = subparsers.add_parser(
        "models", help="Every model on a disc -> .glb + models.csv")
    s.add_argument("--iso", action="append",
                   help="disc image; repeat for several (disc1/, disc2/ ...)")
    s.add_argument("--dump", help="or a dump folder laid out like the disc")
    s.add_argument("--out", required=True, help="output folder")
    s.add_argument("--filter", help="substring or glob on the in-game path")
    s.add_argument("--jobs", type=int, default=0,
                   help="worker processes (default: CPUs - 1)")
    s.add_argument("--no-glb", action="store_true",
                   help="decode, check and read back, but write no files")
    s.add_argument("--no-motion", action="store_true",
                   help="do not add the same-stem motion clips")
    s.set_defaults(func=_cmd_models)
    import blend
    blend.add_commands(subparsers)
    return m, s


# --------------------------------------------------------------- self-test

def _package(tags_blobs):
    """A stored MR package from [(tag, bytes or None)]."""
    n = len(tags_blobs)
    head = bytearray(0x40)
    body = bytearray()
    dirent = bytearray()
    off = 0x40                                   # data at 0x40 + offset
    for tag, blob in tags_blobs:
        blob = blob or b""
        while (off + len(body)) % 0x10:
            body.append(0)
        dirent += struct.pack("<II", (off + len(body)) if blob else 0,
                              len(blob))
        body += blob
    data = bytearray(0x40) + dirent.ljust(off, b"\0")[:off] + body
    struct.pack_into("<2sHIIH2s", head, 0, b"Xc", 1, len(data), len(data),
                     n, b"Xp")
    for i, (tag, _) in enumerate(tags_blobs):
        head[0x10 + i * 4:0x14 + i * 4] = tag.encode().ljust(4, b"\0")
    data[:0x40] = head
    return bytes(data)


def _env_disc_checks():
    """Disc checks when XS3_D1 / XS3_D2 / XS3_PROTO / XS3_JP1 / XS3_JP2
    are set (every disc is read through DiscSource, i.e. disc.Disc)."""
    fails = 0
    any_disc = False
    # C3kosmos02 is one of the region-differing packages (SYNTHESIS T9):
    # the JP mesh has 3,113 triangles, the USA (and prototype) one 3,227
    kosmos02 = {"XS3_D1": 3227, "XS3_D2": 3227, "XS3_JP1": 3113,
                "XS3_JP2": 3113}
    for env in ("XS3_D1", "XS3_D2", "XS3_PROTO", "XS3_JP1", "XS3_JP2"):
        iso = os.environ.get(env)
        if not iso:
            print("SKIP %s disc check (env %s unset)" % (env, env))
            continue
        any_disc = True
        src = DiscSource(iso)
        have = set(src.table)
        if env in ("XS3_D1", "XS3_JP1"):
            # the Disc-based reader and the X3-index reader agree byte for byte
            p0 = "\\mdl\\chr\\pc\\C3kosmos00.chr"
            ok = src(p0) == IsoSource(iso)(p0)
            print("%s %s [%s]: DiscSource == IsoSource for %s" % (
                "ok  " if ok else "FAIL", env, src.region(), p0))
            fails += not ok
        if env in kosmos02:
            p2 = "\\mdl\\chr\\pc\\C3kosmos02.chr"
            row = sweep_one(src, p2, have)
            ok = row["status"] == "ok" and row["tris"] == kosmos02[env]
            print("%s %s: %s: %s, %s tris (expected %d for this region)" % (
                "ok  " if ok else "FAIL", env, p2, row["status"], row["tris"],
                kosmos02[env]))
            fails += not ok
        path = "\\mdl\\chr\\pc\\C3kosmos00.chr"
        row = sweep_one(src, path, have)
        ok = (row["status"] == "ok" and row["tris"] == row["header_tris"]
              and float(row["skin_rest_err"]) < 1e-5
              and row["texture_unlinked"] == 0)
        print("%s %s: %s: %s tris (header %s), layouts %s, skin rest error "
              "%s, %s textures, unlinked %s" % (
                  "ok  " if ok else "FAIL", env, path, row["tris"],
                  row["header_tris"], row["layouts"], row["skin_rest_err"],
                  row["textures"], row["texture_unlinked"]))
        fails += not ok
        for path in ("\\mdl\\obj\\E3obj287.chr", "\\mnu\\umn.pxy",
                     "\\mdl\\map\\cf\\E3_ELS01.map",
                     "\\mdl\\map\\ev\\E3_ELS01_EV01.pxy"):
            if norm_path(path) not in have:
                print("SKIP %s %s (not on this disc)" % (env, path))
                continue
            row = sweep_one(src, path, have)
            ok = row["status"] == "ok" and row["tris"] == row["header_tris"]
            print("%s %s: %s: %s tris (header %s), layouts %s, %s textures"
                  % ("ok  " if ok else "FAIL", env, path, row["tris"],
                     row["header_tris"], row["layouts"], row["textures"]))
            fails += not ok
        # two-bank field map: every texture entry must decode to real pixels
        # (the old all-banks overlay left 39 of E3_UMD07's 130 entries empty)
        path = "\\mdl\\map\\cf\\E3_UMD07.map"
        if norm_path(path) in have:
            _p, tex, _x, _n = load_model(src, path, have)
            dec = list(tex.decode()) if tex is not None else []
            empty = [e["name"] for e, _w, _h, rgba in dec if not any(rgba)]
            ok = bool(dec) and not empty
            print("%s %s: %s: %d texture entries, %d all-zero %s" % (
                "ok  " if ok else "FAIL", env, path, len(dec), len(empty), empty[:3]))
            fails += not ok
        # E3_HAK16.map has no draw of its own: its whole mesh is the pxy at
        # header +0xD0 (36 nodes, 20,244 triangles on USA Disc 1)
        path = "\\mdl\\map\\cf\\E3_HAK16.map"
        if norm_path(path) in have:
            import tempfile
            with tempfile.TemporaryDirectory() as td:
                g = Path(td) / "h.glb"
                row = sweep_one(src, path, have, g)
                ok = (row["status"] == "ok" and row["tris"] == row["header_tris"]
                      and row["tris"] > 0 and g.exists())
            print("%s %s: %s: status %s, %s tris (header %s, all from the "
                  "pxy at +0xD0), glb written: %s" % (
                      "ok  " if ok else "FAIL", env, path, row["status"],
                      row["tris"], row["header_tris"], bool(row["glb"])))
            fails += not ok
    return fails, any_disc


def self_test():
    import tempfile
    skinned = pxy._synthetic(True)[0]
    static = pxy._synthetic(False, xs3=True)[0]
    x3 = xhr._synthetic(3.0)[0]
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        (root / "mdl" / "chr").mkdir(parents=True)
        (root / "mnu").mkdir()
        (root / "mdl" / "chr" / "a00.chr").write_bytes(
            _package([("pxy", skinned), ("txy", None), ("xhr", x3)]))
        (root / "mdl" / "chr" / "e00.chr").write_bytes(
            _package([("pxy", None), ("txy", None)]))
        (root / "mdl" / "chr" / "bad.chr").write_bytes(
            _package([("pxy", skinned[:0x4C] + b"\0\0\0\0"
                       + skinned[0x50:])]))
        (root / "mnu" / "s.pxy").write_bytes(static)
        (root / "mnu" / "s.txt").write_bytes(b"not a model")
        src = DirSource(root)
        assert len(src.paths) == 5
        assert select(src.paths, "MNU") == ["\\mnu\\s.pxy"]
        assert select(src.paths, "*/chr/a*") == ["\\mdl\\chr\\a00.chr"]
        out = root / "out"
        rows = sweep(src, src.paths, out, jobs=1)
        st = {r["path"]: r for r in rows}
        assert len(rows) == 4, [r["path"] for r in rows]
        a = st["\\mdl\\chr\\a00.chr"]
        assert a["status"] == "ok", a
        assert a["xhr"] == "3.0/10" and float(a["skin_rest_err"]) < 1e-5
        assert a["tris"] == a["header_tris"] == 5
        assert st["\\mdl\\chr\\e00.chr"]["status"] == "empty"
        assert st["\\mdl\\chr\\bad.chr"]["status"] == "decode-failed"
        s = st["\\mnu\\s.pxy"]
        assert s["status"] == "ok" and s["layouts"] == "F:1 Q:1 U:1", s
        assert (out / "mdl" / "chr" / "a00.glb").exists()
        assert (out / "mnu" / "s.glb").exists()
        gltf.read_glb((out / "mnu" / "s.glb").read_bytes())
        write_csv(rows, out / "models.csv")
        back = list(csv.DictReader(open(out / "models.csv")))
        assert len(back) == 4 and set(back[0]) == set(CSV_FIELDS)
        sink = io.StringIO()
        sm = report(rows, sink)
        assert sm["ok"] == 2 and sm["empty"] == 1 and sm["decode-failed"] == 1
        assert sm["tri_mismatch"] == 0
        assert glb_names(["\\a\\x.chr", "\\a\\x.pxy", "\\a\\y.wpn"]) == {
            "\\a\\x.chr": "a/x.chr.glb", "\\a\\x.pxy": "a/x.pxy.glb",
            "\\a\\y.wpn": "a/y.glb"}
        # browse hook on the dump folder
        rows2 = browse_models(str(root), root / "browse", jobs=1)
        assert len(rows2) == 4 and (root / "browse" / "models.csv").exists()
        # argparse wiring
        import argparse
        ap = argparse.ArgumentParser()
        add_commands(ap.add_subparsers(dest="cmd"))
        ns = ap.parse_args(["model", "--dump", str(root), "--path",
                            "mdl/chr/a00.chr", "--out",
                            str(root / "one.glb")])
        assert ns.func(ns) == 0 and (root / "one.glb").exists()
    print("ok   synthetic: package (skinned, xhr 3.0), empty slot, damaged "
          "package, standalone pxy (layouts F/Q/U), CSV, glb names, browse "
          "hook, CLI wiring")
    fails, _ = _env_disc_checks()
    if fails:
        print("models_sweep self-test FAILED (%d disc checks)" % fails)
        return 1
    print("models_sweep self-test ok")
    return 0


def main(argv=None):
    import argparse
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] == "--self-test":
        return self_test()
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    add_commands(ap.add_subparsers(dest="cmd", required=True))
    a = ap.parse_args(argv)
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
