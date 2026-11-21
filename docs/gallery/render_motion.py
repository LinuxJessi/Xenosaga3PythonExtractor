"""Render frames of kit-written .glb files playing one action each, for the
front-page GIFs (docs/MOTION.md).  EEVEE with the glTF materials, an
orthographic camera, transparent film.

    blender -b --factory-startup --python render_motion.py -- OUTDIR N SPEC [SPEC ...]
        [--turntable] [--size W H] [--cam az el] [--spacing D] [--fit-all]

SPEC is FILE.glb=ACTION (the glTF animation name, e.g.
'C3kosmos00.glb=pac/cf/C3kosmos00#01'), or FILE.glb alone for the rest pose.
The models stand side by side along Blender X.  N frames are spread over one
loop of the shortest action (frame k at round(k * length / N)).  With
--turntable the camera circles the models once over the N frames instead (the
action, if any, still plays).  --fit-all frames the camera on the figures'
extent over all N frames (for clips that travel), not frame 0 only.  Episode II's docs/gallery/render_motion_preview.py
was the starting point."""
import math
import os
import sys

import bpy
from mathutils import Vector

args = sys.argv[sys.argv.index("--") + 1:]
opts = {"--fit-all": False, "--turntable": False, "--size": (480, 480), "--cam": (28.0, 8.0),
        "--spacing": 0.8}
rest = []
i = 0
while i < len(args):
    a = args[i]
    if a in ("--turntable", "--fit-all"):
        opts[a] = True
        i += 1
    elif a in ("--size", "--cam"):
        opts[a] = (float(args[i + 1]), float(args[i + 2]))
        i += 3
    elif a == "--spacing":
        opts[a] = float(args[i + 1])
        i += 2
    else:
        rest.append(a)
        i += 1
out, n, specs = rest[0], int(rest[1]), rest[2:]
bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
sc.render.fps = 30
length = None
roots = []
for k, spec in enumerate(specs):
    path, _, want = spec.partition("=")
    before = set(bpy.data.objects)
    acts_before = set(bpy.data.actions)
    bpy.ops.import_scene.gltf(filepath=path)
    new = [o for o in bpy.data.objects if o not in before]
    arm = [o for o in new if o.type == "ARMATURE"][0]
    root = arm
    while root.parent:
        root = root.parent
    roots.append(root)
    root.location.x += (k - (len(specs) - 1) / 2) * opts["--spacing"]
    arm.animation_data_create()
    if want:
        mine = [a for a in bpy.data.actions if a not in acts_before]
        act = [a for a in mine
               if a.name == want or a.name.startswith(want + " [")
               or a.name.startswith(want + "_")]
        if not act:
            raise SystemExit("no action %r in %s (have %s)"
                             % (want, path, [a.name for a in mine][:8]))
        act = act[0]
        arm.animation_data.action = act
        if hasattr(arm.animation_data, "action_slot") and act.slots:
            arm.animation_data.action_slot = act.slots[0]
        end = int(round(act.frame_range[1]))
        length = end if length is None else min(length, end)
        print("clip", path, act.name, "frames", tuple(act.frame_range))
    else:
        arm.animation_data.action = None
if length is None:
    length = n

# frame the figures: bounding box of the meshes at frame 0 (--fit-all:
# at every rendered frame)
lo = Vector((1e9, 1e9, 1e9))
hi = Vector((-1e9, -1e9, -1e9))
for f in ([int(round(k * length / n)) for k in range(n)]
          if opts["--fit-all"] else [0]):
    sc.frame_set(f)
    dg = bpy.context.evaluated_depsgraph_get()
    for o in bpy.data.objects:
        # the model's meshes only (not the importer's hidden bone shapes)
        if o.type != "MESH" or not o.users_collection or o.hide_render \
                or not any(m.type == "ARMATURE" for m in o.modifiers) and \
                (o.parent is None or o.parent.type != "ARMATURE"):
            continue
        oe = o.evaluated_get(dg)
        for v in oe.to_mesh().vertices:
            w = oe.matrix_world @ v.co
            lo = Vector(map(min, lo, w))
            hi = Vector(map(max, hi, w))
        oe.to_mesh_clear()
center = (lo + hi) / 2
height = hi.z - lo.z
width = max(hi.x - lo.x, hi.y - lo.y)
print("bbox", tuple(lo), tuple(hi))

cam_data = bpy.data.cameras.new("cam")
cam_data.type = "ORTHO"
W, H = int(opts["--size"][0]), int(opts["--size"][1])
cam = bpy.data.objects.new("cam", cam_data)
sc.collection.objects.link(cam)
sc.camera = cam
az0, el = (math.radians(v) for v in opts["--cam"])
dist = 8.0


def place(az):
    # the characters face -Y; az 0 = straight in front
    cam.location = center + Vector((dist * math.sin(az) * math.cos(el),
                                    -dist * math.cos(az) * math.cos(el),
                                    dist * math.sin(el)))
    d = center - cam.location
    cam.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()


# fit: the box's corners projected on the camera's right / up axes
corners = [Vector((x, y, z)) for x in (lo.x, hi.x) for y in (lo.y, hi.y)
           for z in (lo.z, hi.z)]
ew = eh = 0.0
for az in ([az0 + 2 * math.pi * k / 16 for k in range(16)]
           if opts["--turntable"] else [az0]):
    place(az)
    bpy.context.view_layer.update()
    m = cam.matrix_world.to_3x3()
    right, up = m.col[0], m.col[1]
    xs = [c.dot(right) for c in corners]
    ys = [c.dot(up) for c in corners]
    ew, eh = max(ew, max(xs) - min(xs)), max(eh, max(ys) - min(ys))
pad = 1.08
cam_data.ortho_scale = (max(ew * pad, eh * pad * W / H) if W >= H
                        else max(eh * pad, ew * pad * H / W))
print("fit", ew, eh, cam_data.ortho_scale)
place(az0)
for name, rot, energy in (("key", (50, 0, 30), 3.5),
                          ("fill", (70, 0, -120), 1.2),
                          ("back", (60, 0, 160), 1.0)):
    ld = bpy.data.lights.new(name, "SUN")
    ld.energy = energy
    lo_ = bpy.data.objects.new(name, ld)
    lo_.rotation_euler = tuple(math.radians(a) for a in rot)
    sc.collection.objects.link(lo_)
world = bpy.data.worlds.new("w")
world.use_nodes = True
world.node_tree.nodes["Background"].inputs[0].default_value = (0.6, 0.6, 0.62, 1)
world.node_tree.nodes["Background"].inputs[1].default_value = 0.8
sc.world = world
engines = [e.identifier for e in
           bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items]
sc.render.engine = "BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in engines \
    else "BLENDER_EEVEE"
try:
    sc.eevee.taa_render_samples = 16
except AttributeError:
    pass
sc.view_settings.view_transform = "Standard"
sc.render.film_transparent = True
sc.render.resolution_x, sc.render.resolution_y = W, H
sc.render.image_settings.file_format = "PNG"
sc.render.image_settings.color_mode = "RGBA"
os.makedirs(out, exist_ok=True)
for k in range(n):
    f = int(round(k * length / n))
    sc.frame_set(f)
    if opts["--turntable"]:
        place(az0 + 2 * math.pi * k / n)
    sc.render.filepath = os.path.join(out, "frame_%03d_f%03d.png" % (k, f))
    bpy.ops.render.render(write_still=True)
    print("rendered", sc.render.filepath)
