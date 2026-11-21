"""Blender import check of kit .glb files with motion (docs/MOTION.md).

    blender -b --factory-startup --python motion_blender_check.py -- A.glb [B.glb ...]

For each file: imports it, and prints the number of actions, the armature's
bone count against the glTF skin's joint count, and for every action whether
its frame range is the clip's (extras start/end at 30 fps).  Exits 1 on any
mismatch."""
import json
import struct
import sys

import bpy

bad = 0
for path in sys.argv[sys.argv.index("--") + 1:]:
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.context.scene.render.fps = 30
    with open(path, "rb") as fh:
        data = fh.read()
    n = struct.unpack_from("<I", data, 12)[0]
    js = json.loads(data[20:20 + n])
    bpy.ops.import_scene.gltf(filepath=path)
    arms = [o for o in bpy.data.objects if o.type == "ARMATURE"]
    bones = len(arms[0].data.bones) if arms else 0
    joints = len(js["skins"][0]["joints"])
    acts = {a.name: a for a in bpy.data.actions}
    ok_range = 0
    for an in js.get("animations", ()):
        name = an["name"]
        act = acts.get(name) or next((a for k, a in acts.items()
                                      if k.startswith(name)), None)
        if act is None:
            print("  missing action", name)
            bad += 1
            continue
        want = an["extras"]["end"] - an["extras"]["start"]
        got = act.frame_range[1] - act.frame_range[0]
        if abs(round(want) - got) <= 1:
            ok_range += 1
        else:
            print("  frame range", name, tuple(act.frame_range), "want", want)
            bad += 1
    print("%s: %d animations, %d actions, %d with the clip's frame range; "
          "bones %d, skin joints %d" % (path, len(js.get("animations", ())),
                                         len(acts), ok_range, bones, joints))
    if bones != joints:
        bad += 1
print("blender check: %s" % ("ok" if not bad else "%d problems" % bad))
sys.exit(1 if bad else 0)
