#!/usr/bin/env python3
"""Turn a model into a ready-to-open Blender file (.blend).

    python cli.py blend --glb kosmos.glb --out kosmos.blend [--open]
    python cli.py blend --iso D1.iso --path 'mdl\\chr\\pc\\C3kosmos00.chr' --out kosmos.blend
    python cli.py blend --glb kosmos.glb --out kosmos.blend --render kosmos.png
    python blend.py --self-test

Why a .blend and not "open Blender and import the .glb": a teammate who
opened a kit .glb in Blender 5.4 reported three traps, and this module
closes each one.

1. The glTF importer gives every bone a custom shape (an Icosphere kept in
   a hidden collection `glTF_not_exported`), so the viewport fills with
   balls that look like the model.  Here the importer runs with
   `disable_bone_shape=True`, any custom shape left is cleared, the
   `glTF_not_exported` collection and its objects are removed, and the
   armature is drawn as Stick.
2. `open -a Blender --args --python x.py` does nothing when Blender is
   already running.  Here a separate `blender --background
   --factory-startup` process builds the scene and saves it; `--open`
   then starts a NEW Blender process on the saved file (the executable
   itself, not `open -a`), which works whether or not one is running.
3. The default Solid shading shows a grey model.  The saved file has
   every 3D viewport set to Material Preview and framed on the model.

What the build step does, in Blender (`BUILD_SCRIPT`): factory startup;
delete the default Cube (the default Camera and Light are kept: the camera
is moved to frame the model so F12 renders it, the light is placed beside
it); import the .glb with images packed into the .blend; drop custom bone
shapes; armature display Stick, in front; viewport shading MATERIAL; view
framed on the model's bounding box; save.  An optional `--render PNG`
renders the camera view (Workbench with texture colours by default,
`--engine eevee` for Eevee).

A second background run (`VERIFY_SCRIPT`) opens the saved .blend and
reports what is in it; `verify()` checks: the armature count equals the
.glb's skin count (one for a skinned model), the mesh-object count equals
the .glb's mesh-node count, every image is packed (no external file), no
bone has a custom shape, no `glTF_not_exported` collection, and every 3D
viewport is in MATERIAL shading.  The command fails when any check fails.

Blender is found in this order: `--blender PATH`, the `XS3_BLENDER` or
`BLENDER` environment variable, then per OS: macOS
`/Applications/Blender.app` (and `~/Applications`), Windows
`Program Files\\Blender Foundation\\Blender <ver>\\blender.exe` (newest
version), Linux/other `blender` on PATH (plus /snap/bin, /usr/bin,
/opt/blender).  Checked here with Blender 5.4.0 Alpha on macOS; the
Windows and Linux lookups are not run on those systems.

New for this kit (2026-11-20); nothing borrowed.
"""
from __future__ import annotations

import glob
import json
import os
import posixpath
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import gltf  # noqa: E402

MARK = "XS3BLEND "          # prefix of the result line a Blender script prints


class BlendError(RuntimeError):
    pass


# ------------------------------------------------------------ find Blender

def _version_key(p: str):
    import re
    nums = re.findall(r"\d+", Path(p).parent.name)
    return [int(n) for n in nums]


def candidates(system: Optional[str] = None, env: Optional[Dict[str, str]] = None) -> List[str]:
    """Places to look for the Blender executable on `system` (platform.system()
    name), in order.  Only paths; existence is checked by `find_blender`."""
    system = system or platform.system()
    env = os.environ if env is None else env
    out: List[str] = []
    for k in ("XS3_BLENDER", "BLENDER"):
        if env.get(k):
            out.append(env[k])
    if system == "Darwin":
        # posixpath, not os.path: the lookup is also built (and self-tested) on
        # Windows, where os.path.join would put backslashes in a macOS path
        for root in ("/Applications", posixpath.expanduser("~/Applications")):
            out.append(posixpath.join(root, "Blender.app", "Contents", "MacOS", "Blender"))
            out += sorted(glob.glob(posixpath.join(root, "Blender*.app", "Contents", "MacOS",
                                                   "Blender")), reverse=True)
    elif system == "Windows":
        roots = [env.get("ProgramFiles", r"C:\Program Files"),
                 env.get("ProgramFiles(x86)", r"C:\Program Files (x86)")]
        if env.get("LOCALAPPDATA"):
            roots.append(os.path.join(env["LOCALAPPDATA"], "Programs"))
        for r in roots:
            hits = glob.glob(os.path.join(r, "Blender Foundation", "Blender*", "blender.exe"))
            out += sorted(hits, key=_version_key, reverse=True)
        steam = os.path.join(roots[1], "Steam", "steamapps", "common", "Blender", "blender.exe")
        out.append(steam)
    w = shutil.which("blender")
    if w:
        out.append(w)
    if system not in ("Darwin", "Windows"):
        out += ["/snap/bin/blender", "/usr/bin/blender", "/usr/local/bin/blender"]
        out += sorted(glob.glob("/opt/blender*/blender"), reverse=True)
    seen, uniq = set(), []
    for p in out:
        if p not in seen:
            seen.add(p)
            uniq.append(p)
    return uniq


def find_blender(override: Optional[str] = None) -> str:
    """Path of a Blender executable, or BlendError listing where it looked."""
    if override:
        p = Path(override)
        if p.suffix == ".app" and p.is_dir():          # a macOS bundle given as such
            p = p / "Contents" / "MacOS" / "Blender"
        if p.is_file():
            return str(p)
        raise BlendError(f"--blender {override}: no such executable")
    looked = candidates()
    for p in looked:
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    raise BlendError("Blender not found; install it from blender.org or pass --blender PATH "
                     "(or set XS3_BLENDER). Looked in: " + "; ".join(looked))


def blender_version(blender: str) -> str:
    r = subprocess.run([blender, "--background", "--factory-startup", "--version"],
                       capture_output=True, text=True, timeout=120)
    for line in r.stdout.splitlines():
        if line.startswith("Blender"):
            return line.strip()
    return "unknown"


# --------------------------------------------------- scripts run in Blender

# Runs inside Blender. argv after "--": one JSON object
# {glb, out, render, engine, resolution}.
BUILD_SCRIPT = r'''
import bpy, json, sys, math
from mathutils import Vector

cfg = json.loads(sys.argv[sys.argv.index("--") + 1])
res = {"warnings": []}

for name in ("Cube",):
    ob = bpy.data.objects.get(name)
    if ob is not None and ob.type == "MESH":
        me = ob.data
        bpy.data.objects.remove(ob, do_unlink=True)
        if me.users == 0:
            bpy.data.meshes.remove(me)

before = set(bpy.data.objects)
kw = dict(filepath=cfg["glb"], import_pack_images=True)
props = bpy.ops.import_scene.gltf.get_rna_type().properties
if "disable_bone_shape" in props:
    kw["disable_bone_shape"] = True
else:
    res["warnings"].append("importer has no disable_bone_shape option; shapes cleared afterwards")
r = bpy.ops.import_scene.gltf(**kw)
if "FINISHED" not in r:
    raise SystemExit("glTF import failed: %r" % (r,))
new = [o for o in bpy.data.objects if o not in before]

# trap 1: custom bone shapes and the hidden collection that holds them
shapes = set()
for o in bpy.data.objects:
    if o.type == "ARMATURE":
        for pb in o.pose.bones:
            if pb.custom_shape is not None:
                shapes.add(pb.custom_shape)
                pb.custom_shape = None
        o.data.display_type = "STICK"
        o.show_in_front = True
coll = bpy.data.collections.get("glTF_not_exported")
if coll is not None:
    for o in list(coll.objects):
        shapes.add(o)
    bpy.data.collections.remove(coll)
for o in shapes:
    if o.name in bpy.data.objects and o.users <= 1:
        data = o.data
        bpy.data.objects.remove(o, do_unlink=True)
        if data is not None and getattr(data, "users", 1) == 0:
            bpy.data.meshes.remove(data)
res["removed_shapes"] = len(shapes)

# packed images (the importer packs; pack anything it left external)
for im in bpy.data.images:
    if im.source == "FILE" and im.packed_file is None and im.filepath:
        try:
            im.pack()
        except RuntimeError as e:
            res["warnings"].append("could not pack %s: %s" % (im.name, e))

# bounding box of the imported meshes, in world space
bpy.context.view_layer.update()
lo = Vector((1e30,) * 3); hi = Vector((-1e30,) * 3)
meshes = [o for o in new if o.type == "MESH"]
for o in meshes:
    for c in o.bound_box:
        w = o.matrix_world @ Vector(c)
        lo = Vector(map(min, lo, w)); hi = Vector(map(max, hi, w))
if not meshes:
    lo, hi = Vector((-1, -1, 0)), Vector((1, 1, 2))
centre = (lo + hi) / 2
size = max((hi - lo).length, 1e-3)
res["bbox"] = [list(lo), list(hi)]

# trap 3: Material Preview, framed on the model, in every 3D viewport
for scr in bpy.data.screens:
    for area in scr.areas:
        if area.type != "VIEW_3D":
            continue
        for sp in area.spaces:
            if sp.type == "VIEW_3D":
                sp.shading.type = "MATERIAL"
                sp.clip_end = max(sp.clip_end, size * 20)
                sp.clip_start = min(sp.clip_start, size / 1000)
                r3 = sp.region_3d
                if r3 is not None:
                    r3.view_location = centre
                    r3.view_distance = size * 1.1
                    r3.view_perspective = "PERSP"

# camera framing the model from the front-right, light beside it
scene = bpy.context.scene
cam = bpy.data.objects.get("Camera")
if cam is not None and cam.type == "CAMERA":
    d = Vector((0.45, -1.0, 0.18)).normalized()
    fov = cam.data.angle
    dist = (size * 0.55) / math.tan(fov / 2)
    cam.location = centre + d * dist
    cam.rotation_euler = (-d).to_track_quat("-Z", "Y").to_euler()
    cam.data.clip_end = max(cam.data.clip_end, dist + size * 4)
    cam.data.clip_start = min(cam.data.clip_start, size / 1000)
    scene.camera = cam
light = bpy.data.objects.get("Light")
if light is not None and light.type == "LIGHT":
    light.location = centre + Vector((size, -size, size))
    light.data.energy = max(light.data.energy, 250.0 * size * size)

res["meshes"] = len(meshes)
res["armatures"] = sum(1 for o in new if o.type == "ARMATURE")
res["images"] = sum(1 for im in bpy.data.images if im.source == "FILE")
bpy.ops.wm.save_as_mainfile(filepath=cfg["out"], compress=True)
res["saved"] = cfg["out"]

if cfg.get("render"):
    eng = cfg.get("engine", "workbench")
    if eng == "eevee":
        items = [i.identifier for i in scene.render.bl_rna.properties["engine"].enum_items]
        scene.render.engine = "BLENDER_EEVEE" if "BLENDER_EEVEE" in items else "BLENDER_EEVEE_NEXT"
        # match Material Preview's look: a neutral grey world
        world = scene.world or bpy.data.worlds.new("World")
        scene.world = world
        world.use_nodes = True
        bg = world.node_tree.nodes.get("Background")
        if bg is not None:
            bg.inputs[0].default_value = (0.35, 0.35, 0.38, 1.0)
            bg.inputs[1].default_value = 0.8
    else:
        scene.render.engine = "BLENDER_WORKBENCH"
        sh = scene.display.shading
        sh.light = "STUDIO"
        sh.color_type = "TEXTURE"
        sh.show_backface_culling = False
    scene.render.resolution_x, scene.render.resolution_y = cfg.get("resolution", [960, 1280])
    scene.render.resolution_percentage = 100
    scene.render.film_transparent = False
    scene.render.image_settings.file_format = "PNG"
    scene.render.filepath = cfg["render"]
    bpy.ops.render.render(write_still=True)
    res["render"] = cfg["render"]
    res["engine"] = scene.render.engine

print("XS3BLEND " + json.dumps(res))
'''

# Runs inside Blender on a saved .blend; reports what is in it.
VERIFY_SCRIPT = r'''
import bpy, json
res = {
    "armatures": sum(1 for o in bpy.data.objects if o.type == "ARMATURE"),
    "meshes": sum(1 for o in bpy.data.objects if o.type == "MESH"),
    "objects": sorted(o.name for o in bpy.data.objects),
    "images": sum(1 for im in bpy.data.images if im.source == "FILE"),
    "images_all": sorted(im.name for im in bpy.data.images),
    "images_unpacked": [im.name for im in bpy.data.images
                        if im.source == "FILE" and im.packed_file is None],
    "custom_shapes": sum(1 for o in bpy.data.objects if o.type == "ARMATURE"
                         for pb in o.pose.bones if pb.custom_shape is not None),
    "armature_display": sorted({o.data.display_type for o in bpy.data.objects
                                if o.type == "ARMATURE"}),
    "not_exported_collection": "glTF_not_exported" in bpy.data.collections,
    "shading": sorted({sp.shading.type for scr in bpy.data.screens for a in scr.areas
                       if a.type == "VIEW_3D" for sp in a.spaces if sp.type == "VIEW_3D"}),
    "materials": len(bpy.data.materials),
    "version": bpy.app.version_string,
}
print("XS3BLEND " + json.dumps(res))
'''


def _run(blender: str, script: str, args: List[str], blend_file: Optional[str] = None,
         timeout: int = 900) -> dict:
    with tempfile.TemporaryDirectory() as td:
        sp = Path(td) / "xs3_blend_script.py"
        sp.write_text(script, encoding="utf-8")
        cmd = [blender, "--background", "--factory-startup"]
        if blend_file:
            cmd.append(blend_file)
        cmd += ["--python-exit-code", "3", "--python", str(sp), "--"] + args
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    for line in r.stdout.splitlines():
        if line.startswith(MARK):
            res = json.loads(line[len(MARK):])
            res["_returncode"] = r.returncode
            return res
    tail = "\n".join((r.stdout + r.stderr).strip().splitlines()[-25:])
    raise BlendError(f"Blender exited {r.returncode} without a result line:\n{tail}")


# --------------------------------------------------------------- top level

def expected_from_glb(glb: bytes) -> dict:
    """What the .blend must hold: one armature per glTF skin, one mesh object
    per mesh node, and at least one image when the .glb carries images."""
    js, _ = gltf.read_glb(glb)
    return dict(armatures=len(js.get("skins", ())),
                meshes=sum(1 for n in js.get("nodes", ()) if "mesh" in n),
                images=len(js.get("images", ())))


def verify(blend_path: str, expect: dict, blender: str) -> dict:
    """Open `blend_path` in a second background Blender and check it.
    Returns the report with a "failed" list (empty when every check passes)."""
    rep = _run(blender, VERIFY_SCRIPT, [], blend_file=str(blend_path))
    failed = []
    if rep["armatures"] != expect["armatures"]:
        failed.append("armatures %d, expected %d" % (rep["armatures"], expect["armatures"]))
    if rep["meshes"] != expect["meshes"]:
        failed.append("mesh objects %d, expected %d" % (rep["meshes"], expect["meshes"]))
    if expect["images"] and not rep["images"]:
        failed.append("no images, the .glb has %d" % expect["images"])
    if rep["images_unpacked"]:
        failed.append("images not packed: %s" % rep["images_unpacked"][:5])
    if rep["custom_shapes"]:
        failed.append("%d bones keep a custom shape" % rep["custom_shapes"])
    if rep["not_exported_collection"]:
        failed.append("glTF_not_exported collection still present")
    if rep["armature_display"] and rep["armature_display"] != ["STICK"]:
        failed.append("armature display %s, expected STICK" % rep["armature_display"])
    if rep["shading"] != ["MATERIAL"]:
        failed.append("viewport shading %s, expected MATERIAL" % rep["shading"])
    rep["failed"] = failed
    rep["expected"] = expect
    return rep


def build(glb_path: str, out_path: str, blender: Optional[str] = None,
          render: Optional[str] = None, engine: str = "workbench",
          resolution=(960, 1280), check: bool = True) -> dict:
    """Build `out_path` (.blend) from `glb_path` in background Blender, then
    (check=True) verify it with a second run.  Returns {"build", "verify"}."""
    blender = blender or find_blender()
    glb_path = str(Path(glb_path).resolve())
    out = Path(out_path).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()
    cfg = dict(glb=glb_path, out=str(out), engine=engine, resolution=list(resolution))
    if render:
        rp = Path(render).resolve()
        rp.parent.mkdir(parents=True, exist_ok=True)
        cfg["render"] = str(rp)
    b = _run(blender, BUILD_SCRIPT, [json.dumps(cfg)])
    if not out.is_file():
        raise BlendError(f"Blender reported success but {out} was not written")
    if render and not Path(cfg["render"]).is_file():
        raise BlendError(f"render {cfg['render']} was not written")
    result = {"build": b}
    if check:
        result["verify"] = verify(str(out), expected_from_glb(Path(glb_path).read_bytes()),
                                  blender)
    return result


def open_in_blender(blend_path: str, blender: Optional[str] = None) -> None:
    """Start a new Blender process on the file (works when one is already running)."""
    blender = blender or find_blender()
    kw = {}
    if os.name == "nt":
        kw["creationflags"] = 0x00000008 | 0x00000200   # DETACHED_PROCESS | NEW_PROCESS_GROUP
    else:
        kw["start_new_session"] = True
    subprocess.Popen([blender, str(Path(blend_path).resolve())], stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kw)


# --------------------------------------------------------------------- CLI

def _cmd_blend(a) -> int:
    try:
        blender = find_blender(a.blender)
    except BlendError as e:
        print("blend: %s" % e, file=sys.stderr)
        return 2
    tmp = None
    glb = a.glb
    if a.iso or a.dump:
        if not a.path:
            print("blend: --iso/--dump needs --path", file=sys.stderr)
            return 2
        import models_sweep
        src = models_sweep.open_source(a.iso or a.dump)
        try:
            blob, p, r = models_sweep.convert(src, a.path, set(src.table))
        except KeyError as e:
            print("blend: %s" % e, file=sys.stderr)
            return 2
        if blob is None:
            print("blend: %s has no mesh (empty pxy slot or a layout not understood)" % a.path,
                  file=sys.stderr)
            return 1
        tmp = tempfile.TemporaryDirectory()
        glb = str(Path(tmp.name) / "model.glb")
        Path(glb).write_bytes(blob)
        print("%s: %d triangles, checks %s" % (a.path, r["triangles"],
                                               "all pass" if not r["failed"] else r["failed"]))
    elif not glb:
        print("blend: give --glb, or --iso/--dump with --path", file=sys.stderr)
        return 2
    elif not Path(glb).is_file():
        print("blend: --glb %s: no such file" % glb, file=sys.stderr)
        return 2
    out = a.out or (Path(glb).with_suffix(".blend") if a.glb
                    else a.path.replace("/", "\\").rsplit("\\", 1)[-1].rsplit(".", 1)[0] + ".blend")
    try:
        res = build(glb, str(out), blender, render=a.render, engine=a.engine)
    except (BlendError, subprocess.TimeoutExpired) as e:
        print("blend: %s" % e, file=sys.stderr)
        return 1
    finally:
        if tmp is not None:
            tmp.cleanup()
    b, v = res["build"], res["verify"]
    print("wrote %s (%s; %d mesh objects, %d armature, %d images packed, %d bone shapes "
          "removed)" % (b["saved"], v["version"], v["meshes"], v["armatures"], v["images"],
                        b["removed_shapes"]))
    for w in b.get("warnings", ()):
        print("  warning: %s" % w)
    if b.get("render"):
        print("rendered %s (%s)" % (b["render"], b["engine"]))
    print("  verify: %s" % ("all pass" if not v["failed"] else "; ".join(v["failed"])))
    if v["failed"]:
        return 1
    if a.open:
        open_in_blender(b["saved"], blender)
        print("opening %s in a new Blender window" % b["saved"])
    return 0


def add_commands(subparsers):
    """Register `blend`.  Idempotent: models_sweep.add_commands also calls it,
    so cli.py gets the command whether or not it lists this module."""
    if "blend" in getattr(subparsers, "choices", {}):
        return None
    p = subparsers.add_parser("blend", help="A model -> a ready-to-open .blend "
                              "(textures packed, Material Preview, no bone balls)")
    p.add_argument("--glb", help="a .glb written by `model`/`models`")
    p.add_argument("--iso", help="or a disc image (any region) ...")
    p.add_argument("--dump", help="... or a dump folder laid out like the disc")
    p.add_argument("--path", help=r"with --iso/--dump: in-game path, e.g. 'mdl\chr\pc\C3kosmos00.chr'")
    p.add_argument("--out", help="output .blend (default: next to the .glb / <name>.blend)")
    p.add_argument("--open", action="store_true", help="open the .blend in a new Blender window")
    p.add_argument("--blender", help="Blender executable (or .app on macOS)")
    p.add_argument("--render", help="also render the camera view to this PNG")
    p.add_argument("--engine", choices=("workbench", "eevee"), default="workbench",
                   help="render engine for --render (default workbench)")
    p.set_defaults(func=_cmd_blend)
    return p


# --------------------------------------------------------------- self-test

def self_test() -> int:
    import argparse
    fails = 0

    def check(cond, msg):
        nonlocal fails
        print(("ok   " if cond else "FAIL ") + msg)
        fails += not cond

    # lookup rules (pure; no Blender needed)
    c = candidates("Darwin", {})
    check(c[0] == "/Applications/Blender.app/Contents/MacOS/Blender", "macOS bundle looked up first")
    c = candidates("Windows", {"ProgramFiles": r"C:\PF", "XS3_BLENDER": r"D:\b\blender.exe"})
    check(c[0] == r"D:\b\blender.exe", "XS3_BLENDER overrides the OS lookup")
    check(any("Steam" in x for x in c), "Windows lookup includes the Steam install")
    c = candidates("Linux", {})
    check("/snap/bin/blender" in c, "Linux lookup includes /snap/bin/blender")
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers()
    add_commands(sp)
    check(add_commands(sp) is None, "add_commands is idempotent")
    ns = ap.parse_args(["blend", "--glb", "x.glb", "--out", "y.blend", "--open"])
    check(ns.open and ns.func is _cmd_blend, "argparse wiring")

    # a synthetic skinned two-mesh glb -> .blend, when Blender is installed
    try:
        blender = find_blender()
    except BlendError as e:
        print("SKIP Blender build/verify (%s)" % str(e).split(";")[0])
        blender = None
    if blender:
        from PIL import Image
        import io
        buf = io.BytesIO()
        Image.new("RGBA", (4, 4), (200, 30, 30, 255)).save(buf, "PNG")
        js = _synthetic_glb(buf.getvalue())
        with tempfile.TemporaryDirectory() as td:
            g = Path(td) / "t.glb"
            g.write_bytes(js)
            out = Path(td) / "t.blend"
            png = Path(td) / "t.png"
            res = build(str(g), str(out), blender, render=str(png), resolution=(64, 64))
            v = res["verify"]
            check(out.is_file() and not v["failed"],
                  "synthetic glb -> .blend: %d mesh, %d armature, %d image packed, shading %s%s"
                  % (v["meshes"], v["armatures"], v["images"], v["shading"],
                     "" if not v["failed"] else " FAILED " + "; ".join(v["failed"])))
            check(png.is_file() and png.stat().st_size > 0, "synthetic render written")
            # verify() must catch a file that keeps the factory scene untouched
            bad = Path(td) / "bad.blend"
            _run(blender, "import bpy, sys\nbpy.ops.wm.save_as_mainfile(filepath=sys.argv[-1])\n"
                 "print('XS3BLEND {}')", [str(bad)])
            vb = verify(str(bad), dict(armatures=1, meshes=1, images=1), blender)
            check(len(vb["failed"]) >= 3, "verify rejects a plain factory scene (%s)"
                  % "; ".join(vb["failed"]))
        # KOS-MOS from a real disc (XS3_D1 or XS3_JP1): 28 mesh nodes,
        # one skin, 53 images in the .glb -> all of them in the .blend
        for env in ("XS3_D1", "XS3_JP1"):
            iso = os.environ.get(env)
            if not iso:
                print("SKIP %s KOS-MOS .blend (env %s unset)" % (env, env))
                continue
            import models_sweep
            src = models_sweep.open_source(iso)
            blob, _p, _r = models_sweep.convert(src, "mdl\\chr\\pc\\C3kosmos00.chr",
                                                set(src.table))
            with tempfile.TemporaryDirectory() as td:
                g = Path(td) / "k.glb"
                g.write_bytes(blob)
                exp = expected_from_glb(blob)
                v = build(str(g), str(Path(td) / "k.blend"), blender)["verify"]
                check(not v["failed"] and exp == dict(armatures=1, meshes=28, images=53)
                      and v["images"] == 53,
                      "%s C3kosmos00 -> .blend: %d mesh objects, %d armature, %d images "
                      "packed, %d custom bone shapes, shading %s%s"
                      % (env, v["meshes"], v["armatures"], v["images"], v["custom_shapes"],
                         v["shading"], "" if not v["failed"] else " FAILED " +
                         "; ".join(v["failed"])))
        print("     Blender: %s" % blender)
    print("blend self-test %s" % ("ok" if not fails else "FAILED (%d)" % fails))
    return 1 if fails else 0


def _synthetic_glb(png: bytes) -> bytes:
    """One textured triangle skinned to a two-joint skeleton, plus one
    static textured triangle (2 mesh nodes, 1 skin, 1 image)."""
    import struct
    import numpy as np
    bins = bytearray()
    views, accs = [], []

    def add(arr, typ, comp, target=None, minmax=False):
        while len(bins) % 4:
            bins.append(0)
        off = len(bins)
        bins.extend(arr.tobytes())
        v = {"buffer": 0, "byteOffset": off, "byteLength": arr.nbytes}
        if target:
            v["target"] = target
        views.append(v)
        a = {"bufferView": len(views) - 1, "componentType": comp,
             "count": int(arr.shape[0]), "type": typ}
        if minmax:
            a["min"] = arr.min(0).tolist()
            a["max"] = arr.max(0).tolist()
        accs.append(a)
        return len(accs) - 1

    pos = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0]], np.float32)
    uv = np.array([[0, 0], [1, 0], [0, 1]], np.float32)
    idx = np.array([0, 1, 2], np.uint16)
    j = np.array([[0, 0, 0, 0], [1, 0, 0, 0], [1, 0, 0, 0]], np.uint8)
    w = np.array([[1, 0, 0, 0]] * 3, np.float32)
    ibm = np.array([np.eye(4).T.reshape(-1), np.eye(4).T.reshape(-1)], np.float32)
    ap, au, ai = add(pos, "VEC3", 5126, 34962, True), add(uv, "VEC2", 5126, 34962), \
        add(idx, "SCALAR", 5123, 34963)
    aj, aw, ab = add(j, "VEC4", 5121, 34962), add(w, "VEC4", 5126, 34962), \
        add(ibm, "MAT4", 5126)
    while len(bins) % 4:
        bins.append(0)
    views.append({"buffer": 0, "byteOffset": len(bins), "byteLength": len(png)})
    bins.extend(png)
    while len(bins) % 4:
        bins.append(0)
    prim = {"attributes": {"POSITION": ap, "TEXCOORD_0": au}, "indices": ai, "material": 0}
    sprim = {"attributes": {"POSITION": ap, "TEXCOORD_0": au, "JOINTS_0": aj,
                            "WEIGHTS_0": aw}, "indices": ai, "material": 0}
    js = {"asset": {"version": "2.0"}, "scene": 0,
          "scenes": [{"nodes": [0, 2, 3]}],
          "nodes": [{"name": "root", "children": [1]},
                    {"name": "j1", "translation": [0, 1, 0]},
                    {"name": "skinned", "mesh": 0, "skin": 0},
                    {"name": "static", "mesh": 1, "translation": [2, 0, 0]}],
          "meshes": [{"primitives": [sprim]}, {"primitives": [prim]}],
          "skins": [{"joints": [0, 1], "inverseBindMatrices": ab}],
          "materials": [{"pbrMetallicRoughness": {"baseColorTexture": {"index": 0}},
                         "doubleSided": True}],
          "textures": [{"source": 0}],
          "images": [{"bufferView": len(views) - 1, "mimeType": "image/png", "name": "red"}],
          "accessors": accs, "bufferViews": views,
          "buffers": [{"byteLength": len(bins)}]}
    ibm_fix = np.array([np.eye(4).T.reshape(-1),
                        np.linalg.inv(np.array([[1, 0, 0, 0], [0, 1, 0, 1], [0, 0, 1, 0],
                                                [0, 0, 0, 1]], np.float64)).T.reshape(-1)],
                       np.float32)
    o = views[accs[ab]["bufferView"]]["byteOffset"]
    bins[o:o + ibm_fix.nbytes] = ibm_fix.tobytes()
    jb = json.dumps(js).encode()
    while len(jb) % 4:
        jb += b" "
    return (struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(jb) + 8 + len(bins))
            + struct.pack("<II", len(jb), 0x4E4F534A) + jb
            + struct.pack("<II", len(bins), 0x004E4942) + bytes(bins))


def main(argv=None) -> int:
    import argparse
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] == "--self-test":
        return self_test()
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sp = ap.add_subparsers(dest="cmd")
    add_commands(sp)
    a = ap.parse_args(["blend"] + argv if argv[0] != "blend" else argv)
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
