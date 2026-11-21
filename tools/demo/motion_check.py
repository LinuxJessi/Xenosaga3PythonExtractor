"""Read-back check of `model --motion` output (docs/MOTION.md, "Checked").

    python tools/demo/motion_check.py "Disc 1.iso" OUTDIR

Writes OUTDIR/C3kosmos00.glb and OUTDIR/C3shion00.glb exactly as
`cli.py model` does (same-stem motion: pac/cf and pac/bat), reads every
animation back through gltf.py, samples it the glTF way at every frame and
compares each node's world matrix with xap.pose (the engine formula), runs
gltf.validate, and reports whether each clip's first and last pose agree
(a closed loop).  Prints a report and writes OUTDIR/report.txt."""
import os
import sys

import numpy as np

KIT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(
    __file__))))
sys.path.insert(0, KIT)
import gltf          # noqa: E402
import models_sweep  # noqa: E402
import xap           # noqa: E402

iso, out = sys.argv[1], sys.argv[2]
os.makedirs(out, exist_ok=True)
src = models_sweep.DiscSource(iso)
index = xap.motion_index(src.paths)
lines = []
worst_all = 0.0
for stem in ("C3kosmos00", "C3shion00"):
    path = "\\mdl\\chr\\pc\\%s.chr" % stem
    glb, p, r = models_sweep.convert(src, path)
    _, _, x, _ = models_sweep.load_model(src, path)
    glb, summ, _, notes = models_sweep.add_motion(src, glb, x, path,
                                                  index=index)
    with open(os.path.join(out, stem + ".glb"), "wb") as fh:
        fh.write(glb)
    js, binc = gltf.read_glb(glb)
    probs = gltf.validate(js, binc)
    node_of = {nd["name"]: i for i, nd in enumerate(js["nodes"])}
    height = float(np.ptp(x.world_matrices()[:, 3, 1])) or 1.0
    worst = 0.0
    closed = []
    for ai, sm in enumerate(summ):
        clip = sm["clip"]
        for f in clip.frames():
            ov = gltf.sample_animation(js, binc, ai, (f - int(clip.start)) / 30.0)
            gw = gltf.node_world_matrices(js, ov)
            _, w, _ = xap.pose(x, clip, float(f))
            for j in x.joints:
                worst = max(worst, float(np.abs(gw[node_of[j.name]]
                                                - w[j.index].T).max()))
        tr = sm["tracks"]
        w = np.stack([t["world"] for t in tr])
        gap = float(np.abs(w[:, 0] - w[:, -1]).max())
        closed.append((sm["name"], gap))
    worst_all = max(worst_all, worst)
    lines.append("%s: %d animations, %d bytes, glTF problems %d, read-back "
                 "worst |world - pose| %.2g (%.2g of the skeleton height)"
                 % (stem, len(summ), len(glb), len(probs), worst,
                    worst / height))
    n_closed = sum(g < 1e-4 for _, g in closed)
    lines.append("  clips whose first and last pose agree (1e-4): %d of %d"
                 % (n_closed, len(closed)))
    for name, gap in closed:
        lines.append("    %-40s loop gap %.3g" % (name, gap))
    for n in notes:
        lines.append("  note: %s" % n)
text = "\n".join(lines)
print(text)
with open(os.path.join(out, "report.txt"), "w") as fh:
    fh.write(text + "\n")
sys.exit(0 if worst_all < 1e-4 else 1)
