#!/usr/bin/env python3
"""Format-neutral glTF 2.0 binary (.glb) writer and reader.

Borrowed from the Xenosaga Episode II kit, Xenosaga2PythonExtractor/gltf.py
(same author, MIT), 2026-11-20.  Changed for Episode III: `add_material`
takes `unlit=True`, which writes the KHR_materials_unlit extension (and
lists it in `extensionsUsed`) for the field-map meshes, whose batches
carry baked vertex colours and no vertex normals; `self_test()` returns 0;
`add_commands()` registers `glb-info`.  Everything else is the XS2 code.

Lineage: the buffer-view/accessor bookkeeping, the GLB container packing
and the matrix helpers (`matmul`, `invert_rigid`, `quat_from_matrix`) are
lifted from the Xenosaga Episode I kit, `Xenosaga1PythonExtractor/lex.py`
(`to_glb`, `_matmul`, `_invert_rigid`, `_quat_from_matrix`; same author,
MIT), 2026-11-10.  There they were welded to the `.lex` structures; here
they take plain numpy arrays, so any mesh decoder can use them.

Conventions used by this module:

* Matrices given to the builder are 4x4 in **column-vector** form
  (`v' = M @ v`, translation in the last column), the glTF convention.
  Game files that store row-vector matrices (translation in the last
  row) pass `M.T`.
* Triangles are counter-clockwise front faces.
* UV (0, 0) is the top-left texel, as in glTF and on the PS2 GS.

    python gltf.py --self-test
    python gltf.py FILE.glb          # print a summary of a .glb
"""
import json
import math
import struct
import sys

import numpy as np

__all__ = ["GlbBuilder", "read_glb", "accessor_array", "matmul",
           "invert_rigid", "quat_from_matrix", "trs_from_matrix",
           "skinned_positions", "self_test"]

FLOAT, USHORT, UINT, UBYTE = 5126, 5123, 5125, 5121
ARRAY_BUFFER, ELEMENT_ARRAY_BUFFER = 34962, 34963
REPEAT, CLAMP_TO_EDGE, MIRRORED_REPEAT = 10497, 33071, 33648
_NCOMP = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}
_DTYPE = {FLOAT: "<f4", USHORT: "<u2", UINT: "<u4", UBYTE: "u1"}


# ---------------------------------------------------------------- matrices

def matmul(a, b):
    """4x4 product of two nested-list matrices (lifted from lex.py)."""
    return [[sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4)]
            for i in range(4)]


def invert_rigid(m):
    """Inverse of a column-vector rotation+translation matrix (lex.py)."""
    r = [[m[j][i] for j in range(3)] for i in range(3)]
    t = [m[0][3], m[1][3], m[2][3]]
    nt = [-sum(r[i][k] * t[k] for k in range(3)) for i in range(3)]
    return [[r[0][0], r[0][1], r[0][2], nt[0]],
            [r[1][0], r[1][1], r[1][2], nt[1]],
            [r[2][0], r[2][1], r[2][2], nt[2]],
            [0.0, 0.0, 0.0, 1.0]]


def quat_from_matrix(m):
    """(x, y, z, w) from the 3x3 rotation of a column-vector matrix
    (lifted from lex.py)."""
    t = m[0][0] + m[1][1] + m[2][2]
    if t > 0:
        s = math.sqrt(t + 1.0) * 2
        q = ((m[2][1] - m[1][2]) / s, (m[0][2] - m[2][0]) / s,
             (m[1][0] - m[0][1]) / s, 0.25 * s)
    elif m[0][0] > m[1][1] and m[0][0] > m[2][2]:
        s = math.sqrt(1.0 + m[0][0] - m[1][1] - m[2][2]) * 2
        q = (0.25 * s, (m[0][1] + m[1][0]) / s, (m[0][2] + m[2][0]) / s,
             (m[2][1] - m[1][2]) / s)
    elif m[1][1] > m[2][2]:
        s = math.sqrt(1.0 + m[1][1] - m[0][0] - m[2][2]) * 2
        q = ((m[0][1] + m[1][0]) / s, 0.25 * s, (m[1][2] + m[2][1]) / s,
             (m[0][2] - m[2][0]) / s)
    else:
        s = math.sqrt(1.0 + m[2][2] - m[0][0] - m[1][1]) * 2
        q = ((m[0][2] + m[2][0]) / s, (m[1][2] + m[2][1]) / s, 0.25 * s,
             (m[1][0] - m[0][1]) / s)
    n = math.sqrt(sum(c * c for c in q)) or 1.0
    return tuple(c / n for c in q)


def trs_from_matrix(m):
    """(translation, quaternion xyzw, scale) of a column-vector matrix
    without shear.  A mirrored matrix gets a negative X scale."""
    m = np.asarray(m, dtype=np.float64)
    t = m[:3, 3]
    s = np.linalg.norm(m[:3, :3], axis=0)
    if np.linalg.det(m[:3, :3]) < 0:
        s[0] = -s[0]
    r = m[:3, :3] / np.where(s == 0, 1.0, s)
    q = quat_from_matrix(r.tolist())
    return [float(x) for x in t], [float(x) for x in q], [float(x) for x in s]


def _quat_matrix(q):
    x, y, z, w = q
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


# ----------------------------------------------------------------- builder

class GlbBuilder(object):
    """Collects buffers, meshes, materials, nodes and one optional skin,
    then serialises a .glb."""

    def __init__(self, generator="gltf.py"):
        self.generator = generator
        self.bin = bytearray()
        self.views = []
        self.accessors = []
        self.images = []
        self.samplers = []
        self.textures = []
        self.materials = []
        self.meshes = []
        self.nodes = []
        self.skins = []
        self.scene_nodes = []
        self.extras = {}
        self.extensions_used = []

    # -- lifted from lex.py to_glb ------------------------------------
    def add_view(self, blob, target=None, stride=None):
        while len(self.bin) % 4:
            self.bin.append(0)
        v = {"buffer": 0, "byteOffset": len(self.bin),
             "byteLength": len(blob)}
        if target is not None:
            v["target"] = target
        if stride is not None:
            v["byteStride"] = stride
        self.views.append(v)
        self.bin.extend(blob)
        return len(self.views) - 1

    def add_accessor(self, view, ctype, count, atype, mn=None, mx=None,
                     normalized=False):
        acc = {"bufferView": view, "componentType": ctype, "count": count,
               "type": atype}
        if mn is not None:
            acc["min"], acc["max"] = list(mn), list(mx)
        if normalized:
            acc["normalized"] = True
        self.accessors.append(acc)
        return len(self.accessors) - 1

    # -- arrays ---------------------------------------------------------
    def add_array(self, arr, ctype, atype, target=ARRAY_BUFFER, minmax=False,
                  normalized=False):
        a = np.ascontiguousarray(arr, dtype=_DTYPE[ctype])
        n = _NCOMP[atype]
        a = a.reshape(-1, n) if n > 1 else a.reshape(-1)
        view = self.add_view(a.tobytes(), target)
        mn = mx = None
        if minmax and len(a):
            mn = [float(x) for x in np.atleast_1d(a.min(axis=0))]
            mx = [float(x) for x in np.atleast_1d(a.max(axis=0))]
        return self.add_accessor(view, ctype, len(a), atype, mn, mx,
                                 normalized)

    # -- textures and materials ---------------------------------------
    def add_image(self, png, name=None):
        img = {"bufferView": self.add_view(png), "mimeType": "image/png"}
        if name:
            img["name"] = name
        self.images.append(img)
        return len(self.images) - 1

    def add_texture(self, image, wrap_s=REPEAT, wrap_t=REPEAT, nearest=False):
        s = {"magFilter": 9728 if nearest else 9729,
             "minFilter": 9728 if nearest else 9987,
             "wrapS": wrap_s, "wrapT": wrap_t}
        if s not in self.samplers:
            self.samplers.append(s)
        self.textures.append({"sampler": self.samplers.index(s),
                              "source": image})
        return len(self.textures) - 1

    def add_material(self, name, texture=None, alpha_mode="OPAQUE",
                     alpha_cutoff=0.5, double_sided=True,
                     base_color=(1.0, 1.0, 1.0, 1.0), extras=None,
                     unlit=False):
        pbr = {"metallicFactor": 0.0, "roughnessFactor": 0.9}
        if tuple(base_color) != (1.0, 1.0, 1.0, 1.0):
            pbr["baseColorFactor"] = [float(c) for c in base_color]
        if texture is not None:
            pbr["baseColorTexture"] = {"index": texture}
        m = {"name": name, "pbrMetallicRoughness": pbr,
             "doubleSided": bool(double_sided)}
        if alpha_mode != "OPAQUE":
            m["alphaMode"] = alpha_mode
            if alpha_mode == "MASK":
                m["alphaCutoff"] = alpha_cutoff
        if extras:
            m["extras"] = extras
        if unlit:
            m["extensions"] = {"KHR_materials_unlit": {}}
            if "KHR_materials_unlit" not in self.extensions_used:
                self.extensions_used.append("KHR_materials_unlit")
        self.materials.append(m)
        return len(self.materials) - 1

    # -- geometry -------------------------------------------------------
    def add_mesh(self, name, primitives):
        """primitives: dicts with `positions` (n,3) and `indices` (m,)
        and optionally `normals` (n,3), `uvs` (n,2), `colors` (n,4 floats
        0..1), `joints` (n,4 ints), `weights` (n,4), `material`."""
        out = []
        for p in primitives:
            pos = np.asarray(p["positions"], dtype=np.float32)
            n = len(pos)
            idx = np.asarray(p["indices"], dtype=np.uint32).reshape(-1)
            if len(idx) % 3 or (len(idx) and int(idx.max()) >= n):
                raise ValueError("bad triangle index list")
            attrs = {"POSITION": self.add_array(pos, FLOAT, "VEC3",
                                                minmax=True)}
            if p.get("normals") is not None:
                attrs["NORMAL"] = self.add_array(p["normals"], FLOAT, "VEC3")
            if p.get("uvs") is not None:
                attrs["TEXCOORD_0"] = self.add_array(p["uvs"], FLOAT, "VEC2")
            if p.get("colors") is not None:
                attrs["COLOR_0"] = self.add_array(p["colors"], FLOAT, "VEC4")
            if p.get("joints") is not None:
                attrs["JOINTS_0"] = self.add_array(p["joints"], USHORT, "VEC4")
                attrs["WEIGHTS_0"] = self.add_array(p["weights"], FLOAT,
                                                    "VEC4")
            if n < 65536:
                ia = self.add_array(idx, USHORT, "SCALAR",
                                    ELEMENT_ARRAY_BUFFER)
            else:
                ia = self.add_array(idx, UINT, "SCALAR", ELEMENT_ARRAY_BUFFER)
            prim = {"attributes": attrs, "indices": ia, "mode": 4}
            if p.get("material") is not None:
                prim["material"] = p["material"]
            out.append(prim)
        self.meshes.append({"name": name, "primitives": out})
        return len(self.meshes) - 1

    def add_node(self, name, mesh=None, skin=None, matrix=None,
                 translation=None, rotation=None, scale=None, children=None,
                 extras=None, root=False):
        nd = {"name": name}
        if mesh is not None:
            nd["mesh"] = mesh
        if skin is not None:
            nd["skin"] = skin
        if matrix is not None:
            m = np.asarray(matrix, dtype=np.float64)
            if not np.allclose(m, np.eye(4), atol=0):
                nd["matrix"] = [float(x) for x in m.T.reshape(-1)]
        if translation is not None and any(translation):
            nd["translation"] = [float(x) for x in translation]
        if rotation is not None and tuple(rotation) != (0.0, 0.0, 0.0, 1.0):
            nd["rotation"] = [float(x) for x in rotation]
        if scale is not None and tuple(scale) != (1.0, 1.0, 1.0):
            nd["scale"] = [float(x) for x in scale]
        if children:
            nd["children"] = list(children)
        if extras:
            nd["extras"] = extras
        self.nodes.append(nd)
        if root:
            self.scene_nodes.append(len(self.nodes) - 1)
        return len(self.nodes) - 1

    def add_child(self, parent, child):
        self.nodes[parent].setdefault("children", []).append(child)

    def add_skin(self, name, joint_nodes, inverse_bind, skeleton=None):
        """inverse_bind: (k,4,4) column-vector matrices, one per joint."""
        ibm = np.asarray(inverse_bind, dtype=np.float32).reshape(-1, 4, 4)
        if len(ibm) != len(joint_nodes):
            raise ValueError("one inverse bind matrix per joint")
        # glTF requires the IBM bottom row to be exactly (0,0,0,1); the
        # mesh tables and the inverses computed from them are affine but
        # carry float noise there (-3.6e-24 ... 1.1e-16), which the
        # Khronos validator rejects as ACCESSOR_INVALID_IBM.
        ibm = ibm.copy()
        ibm[:, 3, :] = (0, 0, 0, 1)
        # glTF stores matrices column-major
        acc = self.add_array(ibm.transpose(0, 2, 1).reshape(-1, 16), FLOAT,
                             "MAT4", target=None)
        s = {"name": name, "joints": list(joint_nodes),
             "inverseBindMatrices": acc}
        if skeleton is not None:
            s["skeleton"] = skeleton
        self.skins.append(s)
        return len(self.skins) - 1

    # -- output (container packing lifted from lex.py to_glb) ---------
    def to_bytes(self, scene_name="scene"):
        g = {"asset": {"version": "2.0", "generator": self.generator},
             "scene": 0,
             "scenes": [{"name": scene_name, "nodes": self.scene_nodes}],
             "nodes": self.nodes, "meshes": self.meshes,
             "buffers": [{"byteLength": (len(self.bin) + 3) & ~3}],
             "bufferViews": self.views, "accessors": self.accessors}
        if self.materials:
            g["materials"] = self.materials
        if self.images:
            g["images"], g["samplers"] = self.images, self.samplers
            g["textures"] = self.textures
        if self.skins:
            g["skins"] = self.skins
        if self.extras:
            g["extras"] = self.extras
        if self.extensions_used:
            g["extensionsUsed"] = list(self.extensions_used)
        js = json.dumps(g, separators=(",", ":")).encode()
        while len(js) % 4:
            js += b" "
        binc = bytearray(self.bin)
        while len(binc) % 4:
            binc.append(0)
        total = 12 + 8 + len(js) + 8 + len(binc)
        return (struct.pack("<4sII", b"glTF", 2, total)
                + struct.pack("<I4s", len(js), b"JSON") + js
                + struct.pack("<I4s", len(binc), b"BIN\0") + bytes(binc))


# ------------------------------------------------------------------ reader

def read_glb(data):
    """(json dict, binary chunk) of a .glb."""
    magic, ver, total = struct.unpack_from("<4sII", data, 0)
    if magic != b"glTF" or ver != 2 or total != len(data):
        raise ValueError("not a glTF 2 binary")
    n, tag = struct.unpack_from("<I4s", data, 12)
    if tag != b"JSON":
        raise ValueError("first chunk is not JSON")
    js = json.loads(data[20:20 + n].decode())
    p = 20 + n
    n2, tag2 = struct.unpack_from("<I4s", data, p)
    if tag2 != b"BIN\0":
        raise ValueError("second chunk is not BIN")
    return js, data[p + 8:p + 8 + n2]


def accessor_array(js, binc, index):
    a = js["accessors"][index]
    v = js["bufferViews"][a["bufferView"]]
    n = _NCOMP[a["type"]]
    arr = np.frombuffer(binc, dtype=_DTYPE[a["componentType"]],
                        count=a["count"] * n, offset=v.get("byteOffset", 0))
    return arr.reshape(-1, n) if n > 1 else arr


def node_world_matrices(js):
    """Column-vector world matrix of every node."""
    nodes = js["nodes"]
    local = []
    for nd in nodes:
        if "matrix" in nd:
            m = np.array(nd["matrix"], dtype=np.float64).reshape(4, 4).T
        else:
            m = np.eye(4)
            m[:3, :3] = _quat_matrix(nd.get("rotation", (0, 0, 0, 1))) * \
                np.array(nd.get("scale", (1, 1, 1)), dtype=np.float64)
            m[:3, 3] = nd.get("translation", (0, 0, 0))
        local.append(m)
    parent = {}
    for i, nd in enumerate(nodes):
        for c in nd.get("children", ()):
            parent[c] = i
    world = [None] * len(nodes)

    def w(i):
        if world[i] is None:
            world[i] = local[i] if i not in parent else w(parent[i]) @ local[i]
        return world[i]
    for i in range(len(nodes)):
        w(i)
    return world


def skinned_positions(js, binc, node_index):
    """Positions of a skinned mesh node evaluated the glTF way in the
    file's rest pose: sum_i w_i * jointWorld_i * inverseBind_i * p.
    Returns a list of (static positions, skinned positions), one pair per
    primitive."""
    nd = js["nodes"][node_index]
    skin = js["skins"][nd["skin"]]
    world = node_world_matrices(js)
    ibm = accessor_array(js, binc, skin["inverseBindMatrices"])
    ibm = ibm.reshape(-1, 4, 4).transpose(0, 2, 1).astype(np.float64)
    jm = np.stack([world[j] @ ibm[k] for k, j in enumerate(skin["joints"])])
    out = []
    for prim in js["meshes"][nd["mesh"]]["primitives"]:
        at = prim["attributes"]
        p = accessor_array(js, binc, at["POSITION"]).astype(np.float64)
        j = accessor_array(js, binc, at["JOINTS_0"]).astype(np.int64)
        wt = accessor_array(js, binc, at["WEIGHTS_0"]).astype(np.float64)
        ph = np.concatenate([p, np.ones((len(p), 1))], axis=1)
        acc = np.zeros((len(p), 4))
        for k in range(4):
            acc += wt[:, k:k + 1] * np.einsum("nij,nj->ni", jm[j[:, k]], ph)
        out.append((p, acc[:, :3]))
    return out


# --------------------------------------------------------------- self-test

def self_test():
    b = GlbBuilder("gltf.py self-test")
    png = (b"\x89PNG\r\n\x1a\n" + b"\0" * 5)        # opaque blob, odd length
    tex = b.add_texture(b.add_image(png, "t"))
    mat = b.add_material("m", tex, alpha_mode="MASK")
    pos = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 2, 0]], "f4")
    # two joints: j0 at the origin, j1 a child translated +1 in y and
    # rotated 90 degrees about z; bind matrices are their inverses
    j0 = np.eye(4)
    j1 = np.eye(4)
    j1[:3, :3] = [[0, -1, 0], [1, 0, 0], [0, 0, 1]]
    j1[:3, 3] = [0, 1, 0]
    joints = np.array([[0, 0, 0, 0], [0, 0, 0, 0], [0, 1, 0, 0],
                       [1, 0, 0, 0]], "u2")
    weights = np.array([[1, 0, 0, 0], [1, 0, 0, 0], [.5, .5, 0, 0],
                        [1, 0, 0, 0]], "f4")
    mesh = b.add_mesh("tri", [dict(positions=pos, normals=np.tile(
        [0, 0, 1.0], (4, 1)), uvs=pos[:, :2], colors=np.ones((4, 4)),
        joints=joints, weights=weights, indices=[0, 1, 2, 0, 2, 3],
        material=mat)])
    t, q, s = trs_from_matrix(j1)
    n1 = b.add_node("j1", translation=t, rotation=q, scale=s)
    n0 = b.add_node("j0", children=[n1], root=True)
    noisy = np.linalg.inv(j1)
    noisy[3, :3] = (-3.6e-24, 1.1e-16, 0)            # float noise from inverses
    skin = b.add_skin("skin", [n0, n1], [np.linalg.inv(j0), noisy],
                      skeleton=n0)
    mn = b.add_node("mesh", mesh=mesh, skin=skin, root=True)
    blob = b.to_bytes("test")
    js, binc = read_glb(blob)
    assert len(blob) % 4 == 0 and js["buffers"][0]["byteLength"] == len(binc)
    for v in js["bufferViews"]:
        assert v["byteOffset"] % 4 == 0
        assert v["byteOffset"] + v["byteLength"] <= len(binc)
    prim = js["meshes"][0]["primitives"][0]
    assert np.array_equal(accessor_array(js, binc,
                                         prim["attributes"]["POSITION"]), pos)
    assert list(accessor_array(js, binc, prim["indices"])) == [0, 1, 2, 0, 2,
                                                              3]
    a = js["accessors"][prim["attributes"]["POSITION"]]
    assert a["min"] == [0, 0, 0] and a["max"] == [1, 2, 0]
    ibm = accessor_array(js, binc, js["skins"][0]["inverseBindMatrices"])
    assert all(list(m[[3, 7, 11, 15]]) == [0, 0, 0, 1] for m in ibm), \
        "IBM bottom row must be exactly 0,0,0,1"
    # rest pose: skinning with inverse binds must return the static mesh
    (p, sk), = skinned_positions(js, binc, mn)
    assert np.abs(p - sk).max() < 1e-6, np.abs(p - sk).max()
    # quaternion round trip, including a 180 degree turn
    for m in (j1[:3, :3], np.diag([1.0, -1.0, -1.0]),
              np.diag([-1.0, -1.0, 1.0])):
        assert np.abs(_quat_matrix(quat_from_matrix(m.tolist())) - m).max() \
            < 1e-9
    r = [[0, -1, 0, 3], [1, 0, 0, 4], [0, 0, 1, 5], [0, 0, 0, 1]]
    assert np.abs(np.array(matmul(r, invert_rigid(r))) - np.eye(4)).max() \
        < 1e-12
    try:
        b.add_mesh("bad", [dict(positions=pos, indices=[0, 1, 9])])
    except ValueError:
        pass
    else:
        raise AssertionError("accepted an out-of-range index")
    b2 = GlbBuilder("gltf.py self-test (unlit)")
    um = b2.add_material("u", unlit=True)
    b2.add_node("m", mesh=b2.add_mesh("t", [dict(positions=pos[:3],
                                                 indices=[0, 1, 2],
                                                 material=um)]), root=True)
    js2, _ = read_glb(b2.to_bytes())
    assert js2["extensionsUsed"] == ["KHR_materials_unlit"]
    assert js2["materials"][0]["extensions"] == {"KHR_materials_unlit": {}}
    assert "NORMAL" not in js2["meshes"][0]["primitives"][0]["attributes"]
    assert "extensionsUsed" not in js
    print("gltf self-test ok (writer, reader, skinning, quaternions, "
          "index check, exact IBM bottom row, unlit extension)")
    return 0


def _cmd_glb_info(a):
    return main([a.file])


def add_commands(subparsers):
    """Register `glb-info FILE.glb` (summary of a written model)."""
    p = subparsers.add_parser("glb-info", help="Summarise a .glb file "
                              "(nodes, meshes, materials, triangles)")
    p.add_argument("file")
    p.set_defaults(func=_cmd_glb_info)
    return p


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] == "--self-test":
        return self_test()
    with open(argv[0], "rb") as f:
        js, binc = read_glb(f.read())
    nv = nt = 0
    for m in js.get("meshes", ()):
        for p in m["primitives"]:
            nv += js["accessors"][p["attributes"]["POSITION"]]["count"]
            nt += js["accessors"][p["indices"]]["count"] // 3
    print("%s: %d nodes, %d meshes, %d materials, %d images, %d skins, "
          "%d vertices, %d triangles, %d bytes of buffers"
          % (argv[0], len(js.get("nodes", ())), len(js.get("meshes", ())),
             len(js.get("materials", ())), len(js.get("images", ())),
             len(js.get("skins", ())), nv, nt, len(binc)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
