#!/usr/bin/env python3
"""Episode II / III `.pxy` meshes -> glTF 2.0 binary (`.glb`).

    python pxy.py --self-test
    python pxy.py FILE.pxy                       # summary + invariant report
    python pxy.py FILE.pxy --glb OUT.glb [--txy FILE.txy] [--xhr FILE.xhr]
    python pxy.py PACKAGE.chr --glb OUT.glb      # .chr/.wpn/.map: the
                                                 # package's own pxy/txy/xhr

Borrowed from the Xenosaga Episode II kit, Xenosaga2PythonExtractor/pxy.py
(same author, MIT), 2026-11-20.  Episode III ships the same `.pxy`
version 0.15 (it is the full render mesh, not a proxy/collision mesh).
Changed for Episode III (proof: docs/MODELS.md, and the survey sweep):

* Two more mesh-batch layouts beside the Episode II one ("F"):
  "Q" (quantized; 35+ character/enemy models, KOS-MOS among them): a
  V4-32 header row whose z word is a float position scale, then ONE
  signed (USN = 0) UNPACK V4-16 of 2n rows at address 1: n positions
  (pos = i16 * scale / 4096) then n normals (nrm = i16 / 4096); S and T
  are the w halves (i16 / 4096).  There is no restart bit: the batch is
  one strip (triangles = n - 2).  Colours / weights / palette stay at
  2n+1 / 4n+1 / 5n+1.
  "U" (unlit field maps): V4-32 x (n+1) = header + (x, y, z, S); S-32 x n
  at n+1 = T with bit 0 = strip restart (as in F); V4-8 colours at 2n+1;
  optional V4-32 face normals at 3n+1.  No vertex normals, no skinning.
  The glTF gets COLOR_0 (baked lighting, 128 = 1.0), no NORMAL, and a
  KHR_materials_unlit material; the facing turn and the "strips face one
  way" check need vertex normals and are skipped for these batches.
* A second, complete pxy can sit inside the first at the offset in header
  word +0xD0 (310 maps; the engine draws both, FUN_00290590).  `parse`
  reads it as `p.child`; `check` and `to_glb` include it;
  `header_triangles` / `all_draws` cover both.
* `_decode_draw` accepts a signed UNPACK for V4-16 (layout Q) only.
* Textures come from a `TextureSet` (below), which decodes through the
  Episode III kit's chrtex.py (package txy blocks, standalone `.txy`, and
  its two-bank overlay for field maps) instead of the XS2 txy.py.  The
  link rule is the XS2 one unchanged: TEX0.TBP0 - 0x3800 == entry GS
  address (txy entry word +0x00, kept by chrtex as `gsaddr`).
* `self_test()` returns 0 and covers layouts Q and U; `add_commands()`
  exists (the CLI is in models_sweep.py).

The rest of this docstring is the Episode II description (layout F).

A `.pxy` is a header, tables (materials, nodes, matrices, draw list, draw
items) and a raw VIF1 stream.  The stream is cut by the draw list into
*draws*; each draw is a run of *batches* `STCYCL 1,1; UNPACK...; MSCNT`.
The VU1 microprogram the engine runs on them (five variants in `.vudata`
of SLUS_208.92, see docs/MODELS.md) reads, relative to VIF1_TOPS:

    material batch (header y == 1)
        +0   x = shader id, y = 1, w = f32 SW (texture width / TEX0 width)
        +1   GIF tag: x = NLOOP | 0x8000 (count of register qwords),
             w = f32 TW (texture height / TEX0 height)
        +2   TEX0 value (x, y = the 64 bits)     +4  CLAMP value
        +5.. ALPHA, TEX1 ..., then further shader parameters (not decoded)

    mesh batch (header y == 0 or 3), n = header x & 0x7FFF, n <= 30
        +0        x = n | 0x8000, w = flags: bit 0 per-vertex colours,
                  bits 1-4 skin mode (0 none, 2 one matrix, 4/8 weighted)
        +1        n * (x, y, z, S)      positions; w is texture S * SW
        +1+n      n * (nx, ny, nz, T)   normals; w is texture T * TW, and
                  bit 0 of the raw word is the strip-restart flag
        +1+2n     n (or 1) * RGBA bytes (128 = 1.0)
        +1+3n     n * face normal (static files only; not exported)
        +1+4n     n * weights (2 or 4 floats)
        +1+5n     n * 4 bytes: matrix palette offsets (slot * 4), 255 = end

A flagged vertex k starts a new strip: no triangle is drawn for k and
k + 1.  Triangle (k-2, k-1, k) is counter-clockwise when k - (strip start)
is even.  Texture coordinates are S / SW, T / TW in the texture's own
0..1 space (the GS addresses the texture inside a 1024-wide page with a
region-repeat window).

Every structural assumption is checked while decoding; anything else
raises `PxyError`.  `check()` runs the numeric invariants.
"""
import struct
import sys

import numpy as np

import vif

__all__ = ["PxyError", "Pxy", "parse", "check", "to_glb", "self_test"]

GS_TEXTURE_BASE = 0x3800     # TBP0/CBP = this + the .txy entry's address
MAX_BATCH = 30               # 1 + 6n <= 183 (output packet starts there)
IDENT = np.eye(4)


class PxyError(ValueError):
    pass


def _cstr(b):
    return b.split(b"\0")[0].decode("latin1")


class Material(object):
    """A 0x60-byte record of the material table."""
    def __init__(self, index, rec):
        w = struct.unpack_from("<16I", rec, 0x20)
        f = struct.unpack_from("<16f", rec, 0x20)
        self.index = index
        self.name = _cstr(rec[:0x20])
        self.flags = w[0]
        self.shader = w[1]
        # +0x28 high half: the record's own index in 52,761 of the
        # disc's 52,819 records (it is NOT a .txy entry index: textures
        # are found through TEX0, see link_textures)
        self.ordinal = w[2] >> 16
        self.word28_low = w[2] & 0xFFFF
        self.sw, self.tw = f[9], f[11]
        self.words = w


class Node(object):
    """A 0x70-byte node record: a named part with its matrix palette."""
    def __init__(self, index, rec, matrix):
        self.index = index
        self.name = _cstr(rec[:0x30])
        pal = rec[0x30:0x70]
        self.palette = list(bytearray(pal.split(b"\0")[0]))  # 1-based
        self.matrix = matrix               # row-vector 4x4


class Item(object):
    """A 0x60-byte draw item: which draw, under which node, and bounds."""
    def __init__(self, index, rec):
        w = struct.unpack_from("<8i", rec, 0)
        self.index = index
        self.words = w
        self.draw = w[1] & 0xFFFF
        self.node = w[4] & 0xFFFF
        self.flags = w[6]
        # +0x1C: 0 = drawn two-sided, 1 / 2-3 = back faces culled with
        # opposite signs (FUN_001ce4c4 sends it to VU address 0x3C6)
        self.cull, = struct.unpack_from("<b", rec, 0x1C)
        f = struct.unpack_from("<16f", rec, 0x20)
        self.bbox_min = np.array(f[0:3])
        self.bbox_max = np.array(f[4:7])
        self.sphere = np.array(f[8:12])
        self.sphere2 = np.array(f[12:16])
        self.group = None


class MaterialState(object):
    """A material batch of the VIF stream."""
    def __init__(self, off, q, f):
        self.off = off
        self.shader = int(q[0, 0])
        self.sw = float(f[0, 3])
        self.tw = float(f[1, 3])
        self.nreg = int(q[1, 0]) & 0x7FFF
        self.qwords = len(q)
        t0 = int(q[2, 0]) | int(q[2, 1]) << 32
        self.tex0 = t0
        self.tbp0 = t0 & 0x3FFF
        self.tbw = (t0 >> 14) & 0x3F
        self.psm = (t0 >> 20) & 0x3F
        self.tex_w = 1 << ((t0 >> 26) & 0xF)
        self.tex_h = 1 << ((t0 >> 30) & 0xF)
        self.cbp = (t0 >> 37) & 0x3FFF
        cl = int(q[4, 0]) | int(q[4, 1]) << 32
        self.clamp = cl
        self.wms, self.wmt = cl & 3, (cl >> 2) & 3
        self.alpha = int(q[5, 0]) | int(q[5, 1]) << 32
        self.textured = self.tbw != 0
        self.txy_entry = None              # filled by link_textures()

    @property
    def key(self):
        return (self.tex0, self.clamp, self.shader, self.sw, self.tw, self.alpha)


class Batch(object):
    """A decoded mesh batch."""
    __slots__ = ("off", "n", "kind", "flags", "pos", "nrm", "st", "adc",
                 "colors", "weights", "slots", "face", "material",
                 "skin_mode", "layout")

    @property
    def unlit(self):
        """Layout U: no vertex normals (nrm is None)."""
        return self.nrm is None

    @property
    def per_vertex_color(self):
        return bool(self.flags & 1)

    def triangles(self):
        """(m,3) local vertex indices, counter-clockwise."""
        sup = self.adc.copy()
        sup[1:] |= self.adc[:-1]
        sup[:2] = True
        start = np.maximum.accumulate(np.where(self.adc, np.arange(self.n),
                                               0))
        k = np.nonzero(~sup)[0]
        odd = ((k - start[k]) & 1).astype(bool)
        a = np.where(odd, k - 1, k - 2)
        b = np.where(odd, k - 2, k - 1)
        return np.stack([a, b, k], axis=1)


class Draw(object):
    def __init__(self, index, off, qwc, word2, word3, sphere):
        self.index, self.off, self.qwc = index, off, qwc
        self.word2, self.word3, self.sphere = word2, word3, sphere
        self.batches = []
        self.materials = []
        self.items = []

    @property
    def node(self):
        return self.items[0].node if self.items else None


class Pxy(object):
    pass


# ------------------------------------------------------------------ parsing

def _mat_table(buf, off, n, what):
    if off + n * 0x40 > len(buf):
        raise PxyError("%s table runs past the file" % what)
    return np.frombuffer(buf, "<f4", n * 16, off).reshape(n, 4, 4).astype(
        np.float64)


def parse(buf, decode=True):
    """Parse a .pxy.  With decode=False the VIF stream is left alone."""
    if buf[:4] != b"pxy\0":
        raise PxyError("not a pxy (magic)")
    p = Pxy()
    p.version, = struct.unpack_from("<f", buf, 4)
    p.flags, p.size = struct.unpack_from("<II", buf, 8)
    if p.size != len(buf):
        raise PxyError("size field %#x != file length %#x" % (p.size, len(buf)))
    p.name = _cstr(buf[0x10:0x30])
    h = struct.unpack_from("<20I", buf, 0x30)
    p.header_words = h
    (p.word30, n_nodes, n_mat, o_draw, o_item, n_group, n_item, o_vif, n_draw,
     o_group, o_mat, n_joint, n_nodemat, o_invbind, o_nodemat, o_node,
     o_skinbuf, o_ext1, o_ext2, o_ext3) = h
    if n_nodemat != n_nodes:
        raise PxyError("node count %d != node matrix count %d"
                       % (n_nodes, n_nodemat))
    p.sphere = np.array(struct.unpack_from("<4f", buf, 0x80))
    p.bbox_min = np.array(struct.unpack_from("<3f", buf, 0x90))
    p.bbox_max = np.array(struct.unpack_from("<3f", buf, 0xA0))
    p.triangle_count, = struct.unpack_from("<I", buf, 0xB4)
    p.wordBC, = struct.unpack_from("<I", buf, 0xBC)
    p.n_joint_matrices = n_joint
    p.offsets = dict(draws=o_draw, items=o_item, vif=o_vif, groups=o_group,
                     materials=o_mat, inv_bind=o_invbind, node_mats=o_nodemat,
                     nodes=o_node, skin_buffer=o_skinbuf, ext1=o_ext1,
                     ext2=o_ext2, ext3=o_ext3)
    for name, off, size in (("group", o_group, n_group * 0x20),
                            ("material", o_mat, n_mat * 0x60),
                            ("node", o_node, n_nodes * 0x70),
                            ("draw", o_draw, n_draw * 0x20),
                            ("item", o_item, n_item * 0x60)):
        if off + size > len(buf):
            raise PxyError("%s table runs past the file" % name)
    p.groups = []
    for i in range(n_group):
        o = o_group + i * 0x20
        idx, first, count, z = struct.unpack_from("<4I", buf, o + 0x10)
        p.groups.append(dict(name=_cstr(buf[o:o + 0x10]).strip(), index=idx,
                             first=first, count=count))
    p.materials = [Material(i, buf[o_mat + i * 0x60:o_mat + (i + 1) * 0x60])
                   for i in range(n_mat)]
    p.inv_bind = _mat_table(buf, o_invbind, n_joint, "inverse bind")
    p.node_mats = _mat_table(buf, o_nodemat, n_nodes, "node matrix")
    p.nodes = [Node(i, buf[o_node + i * 0x70:o_node + (i + 1) * 0x70],
                    p.node_mats[i]) for i in range(n_nodes)]
    p.draws = []
    for i in range(n_draw):
        o = o_draw + i * 0x20
        off, qwc, w2, w3 = struct.unpack_from("<4I", buf, o)
        p.draws.append(Draw(i, off, qwc, w2, w3, np.array(
            struct.unpack_from("<4f", buf, o + 0x10))))
    # the draws tile the VIF region exactly, in order
    pos = o_vif
    for d in sorted(p.draws, key=lambda d: d.off):
        if d.off != pos:
            raise PxyError("draw %d starts at %#x, expected %#x"
                           % (d.index, d.off, pos))
        pos = d.off + d.qwc * 16
    if pos != o_draw:
        raise PxyError("VIF stream ends at %#x, draw list is at %#x"
                       % (pos, o_draw))
    p.items = []
    for i in range(n_item):
        it = Item(i, buf[o_item + i * 0x60:o_item + (i + 1) * 0x60])
        if it.draw >= n_draw or it.node >= max(n_nodes, 1):
            raise PxyError("item %d: draw %d / node %d out of range"
                           % (i, it.draw, it.node))
        for g in p.groups:
            if g["first"] <= i < g["first"] + g["count"]:
                it.group = g["name"]
        p.items.append(it)
        p.draws[it.draw].items.append(it)
    for d in p.draws:
        if len(set(it.node for it in d.items)) > 1:
            raise PxyError("draw %d is used under several nodes" % d.index)
    if decode:
        for d in p.draws:
            _decode_draw(buf, p, d)
    # Episode III: header words 0xC0..0xFF are eight (offset, size) slots.
    # Slot 2 (+0xD0) is the offset of a second, complete pxy inside this
    # one; the engine draws this pxy, then that one (FUN_00290590 calls the
    # draw function FUN_001a1d18 on `pxy` and on `pxy + *(pxy + 0xD0)`),
    # and FUN_0028d760 / FUN_0024e678 drive its node matrices (+0x60 count,
    # +0x68 table) from the "PAM " block that slot 7 (+0xF8) points at.
    # Slot 0 (+0xC0) is the "WAT " block (FUN_0024e2c8 -> FUN_0024d478).
    p.child = None
    p.child_offset = 0
    if len(buf) >= 0x100:
        p.ext_slots = struct.unpack_from("<16I", buf, 0xC0)
        co = p.ext_slots[4]
        if co:
            if co + 0x10 > len(buf) or buf[co:co + 4] != b"pxy\0":
                raise PxyError("header +0xD0 = %#x: no pxy there" % co)
            csize, = struct.unpack_from("<I", buf, co + 12)
            if co + csize > len(buf):
                raise PxyError("pxy at +0xD0 (%#x, %#x bytes) runs past the "
                               "file" % (co, csize))
            p.child = parse(buf[co:co + csize], decode)
            p.child_offset = co
            if p.child.child is not None:
                raise PxyError("pxy at +0xD0 has its own +0xD0 pxy "
                               "(never seen)")
    return p


def header_triangles(p):
    """Header triangle count of a pxy plus that of its +0xD0 pxy."""
    return p.triangle_count + (p.child.triangle_count if p.child else 0)


def all_draws(p):
    """The draws of a pxy, then those of its +0xD0 pxy."""
    return list(p.draws) + (list(p.child.draws) if p.child else [])


def _decode_draw(buf, p, d):
    end = d.off + d.qwc * 16
    cur = []
    state = None
    for c in vif.walk(buf, d.off, end):
        if c.name == "STCYCL":
            if (c.cl, c.wl) != (1, 1) or cur:
                raise PxyError("unexpected STCYCL at %#x" % c.off)
        elif c.is_unpack:
            # Episode III: a signed unpack is the quantized V4-16 block
            if not c.flg or c.mask or c.mode \
                    or (not c.usn and c.fmt != "V4-16"):
                raise PxyError("unexpected UNPACK flags at %#x" % c.off)
            cur.append(c)
        elif c.name == "MSCNT":
            if not cur:
                raise PxyError("MSCNT without data at %#x" % c.off)
            kind = _batch_kind(buf, cur)
            if kind == 1:
                state = _decode_material(buf, cur)
                d.materials.append(state)
            else:
                b = _decode_mesh(buf, cur, kind)
                b.material = state
                d.batches.append(b)
            cur = []
        elif c.name == "NOP":
            if cur:
                raise PxyError("NOP inside a batch at %#x" % c.off)
        else:
            raise PxyError("unexpected VIF command %s at %#x"
                           % (c.name, c.off))
    if cur:
        raise PxyError("draw %d ends inside a batch" % d.index)


def _batch_kind(buf, cur):
    c = cur[0]
    if c.fmt != "V4-32" or c.addr != 0 or c.count < 1:
        raise PxyError("batch at %#x does not start with V4-32 at 0" % c.off)
    kind, = struct.unpack_from("<I", buf, c.data_off + 4)
    if kind not in (0, 1, 3):
        raise PxyError("unknown batch kind %d at %#x" % (kind, c.off))
    return kind


def _decode_material(buf, cur):
    c = cur[0]
    if len(cur) != 1:
        raise PxyError("material batch at %#x has %d unpacks"
                       % (c.off, len(cur)))
    q = np.frombuffer(buf, "<u4", c.count * 4, c.data_off).reshape(-1, 4)
    f = np.frombuffer(buf, "<f4", c.count * 4, c.data_off).reshape(-1, 4)
    nreg = int(q[1, 0]) & 0x7FFF if c.count > 1 else 0
    if c.count < 9 or nreg < 7 or 2 + nreg > c.count \
            or int(q[1, 0]) >> 15 != 1 or int(q[1, 2]) != 0xE:
        raise PxyError("material batch at %#x: bad register block" % c.off)
    return MaterialState(c.off, q, f)


def _decode_mesh(buf, cur, kind):
    """Dispatch on the batch layout (F = Episode II float, Q = Episode III
    quantized V4-16, U = Episode III unlit map); anything else raises."""
    c = cur[0]
    hx, = struct.unpack_from("<I", buf, c.data_off)
    n = hx & 0x7FFF
    if c.count == 2 * n + 1:
        return _decode_mesh_f(buf, cur, kind)
    if c.count == 1 and len(cur) > 1 and cur[1].fmt == "V4-16" \
            and not cur[1].usn and cur[1].addr == 1:
        return _decode_mesh_q(buf, cur, kind)
    if c.count == n + 1 and len(cur) > 1 and cur[1].fmt == "S-32" \
            and cur[1].addr == n + 1:
        return _decode_mesh_u(buf, cur, kind)
    raise PxyError("mesh batch at %#x: %d rows for n=%d, no known layout"
                   % (c.off, c.count, n))


def _mesh_header(buf, c, need_z0):
    hx, hy, hz, hw = struct.unpack_from("<4I", buf, c.data_off)
    n = hx & 0x7FFF
    if hx >> 15 != 1 or (need_z0 and hz != 0) or hw & ~0x1F:
        raise PxyError("mesh batch at %#x: unexpected header %r"
                       % (c.off, (hx, hy, hz, hw)))
    if not 1 <= n <= MAX_BATCH:
        raise PxyError("mesh batch at %#x: %d vertices" % (c.off, n))
    return n, hz, hw


def _new_batch(c, n, kind, hw, layout):
    b = Batch()
    b.off, b.n, b.kind, b.flags = c.off, n, kind, hw
    b.layout = layout
    b.skin_mode = hw & 0x1E
    if b.skin_mode not in (0, 2, 4, 8):          # the only modes the microcode's skinning was read for
        raise PxyError("mesh batch at %#x: skin mode %#x not understood" % (c.off, b.skin_mode))
    b.colors = b.weights = b.slots = b.face = None
    return b


def _rest_blocks(c, unpacks):
    rest = {}
    for u in unpacks:
        if u.addr in rest:
            raise PxyError("mesh batch at %#x: address %d unpacked twice"
                           % (c.off, u.addr))
        rest[u.addr] = u
    return rest


def _tail_blocks(buf, c, rest, b, skin_ok=True):
    """Colour (2n+1), face normal (3n+1), weights (4n+1) and palette
    (5n+1) blocks: the same addresses in every layout."""
    n, hw = b.n, b.flags
    u = rest.pop(2 * n + 1, None)
    if u is not None:
        want = n if hw & 1 else 1
        if u.fmt != "V4-8" or u.count != want:
            raise PxyError("mesh batch at %#x: colour block %s x%d, flags %#x"
                           % (c.off, u.fmt, u.count, hw))
        b.colors = np.frombuffer(buf, "u1", u.count * 4,
                                 u.data_off).reshape(-1, 4)
    u = rest.pop(3 * n + 1, None)
    if u is not None:
        if u.fmt != "V4-32" or u.count != n:
            raise PxyError("mesh batch at %#x: bad block at 3n+1" % c.off)
        b.face = np.frombuffer(buf, "<f4", n * 4, u.data_off).reshape(
            -1, 4)[:, :3].astype(np.float64)
    if b.skin_mode and not skin_ok:
        raise PxyError("mesh batch at %#x: skinning in an unlit batch"
                       % c.off)
    if b.skin_mode:
        u = rest.pop(5 * n + 1, None)
        if u is None or u.fmt != "V4-8" or u.count != n:
            raise PxyError("mesh batch at %#x: skin mode %d without palette "
                           "bytes" % (c.off, b.skin_mode))
        b.slots = np.frombuffer(buf, "u1", n * 4, u.data_off).reshape(
            -1, 4).astype(np.int32)
        u = rest.pop(4 * n + 1, None)
        if b.skin_mode == 2:
            if u is not None:
                raise PxyError("mesh batch at %#x: weights in rigid mode"
                               % c.off)
        else:
            if u is None or u.count != n or u.fmt not in ("V2-32", "V4-32"):
                raise PxyError("mesh batch at %#x: skin mode %d without "
                               "weights" % (c.off, b.skin_mode))
            k = 2 if u.fmt == "V2-32" else 4
            w = np.frombuffer(buf, "<f4", n * k, u.data_off).reshape(-1, k)
            b.weights = np.zeros((n, 4))
            b.weights[:, :k] = w
    if rest:
        raise PxyError("mesh batch at %#x: unexplained unpack at %r"
                       % (c.off, sorted(rest)))
    return b


def _decode_mesh_f(buf, cur, kind):
    """Layout F (Episode II): V4-32 x (2n+1)."""
    c = cur[0]
    n, _, hw = _mesh_header(buf, c, need_z0=True)
    b = _new_batch(c, n, kind, hw, "F")
    raw = np.frombuffer(buf, "<u4", c.count * 4, c.data_off).reshape(-1, 4)
    f = np.frombuffer(buf, "<f4", c.count * 4, c.data_off).reshape(-1, 4)
    b.pos = f[1:n + 1, :3].astype(np.float64)
    b.nrm = f[n + 1:, :3].astype(np.float64)
    # T shares its word with the restart flag (bit 0): cleared here, so two vertices that
    # differ only in the flag still have the same T
    t = (raw[n + 1:, 3] & np.uint32(0xFFFFFFFE)).view("<f4")
    b.st = np.stack([f[1:n + 1, 3], t], axis=1).astype(np.float64)
    b.adc = (raw[n + 1:, 3] & 1).astype(bool)
    return _tail_blocks(buf, c, _rest_blocks(c, cur[1:]), b)


def _decode_mesh_q(buf, cur, kind):
    """Layout Q (Episode III quantized): V4-32 x 1 header (z = f32
    position scale), signed V4-16 x 2n at address 1."""
    c, q = cur[0], cur[1]
    n, hz, hw = _mesh_header(buf, c, need_z0=False)
    if q.count != 2 * n:
        raise PxyError("mesh batch at %#x: V4-16 block of %d rows for n=%d"
                       % (c.off, q.count, n))
    scale, = struct.unpack("<f", struct.pack("<I", hz))
    if not (np.isfinite(scale) and scale > 0):
        raise PxyError("mesh batch at %#x: position scale %r" % (c.off, scale))
    b = _new_batch(c, n, kind, hw, "Q")
    a = np.frombuffer(buf, "<i2", q.count * 4, q.data_off).reshape(-1, 4)
    b.pos = a[:n, :3].astype(np.float64) * (scale / 4096.0)
    b.nrm = a[n:, :3].astype(np.float64) / 4096.0
    t = a[n:, 3].astype(np.int32) & ~1
    b.st = np.stack([a[:n, 3].astype(np.float64), t.astype(np.float64)],
                    axis=1) / 4096.0
    b.adc = np.zeros(n, bool)       # one strip per batch: no restart bit
    return _tail_blocks(buf, c, _rest_blocks(c, cur[2:]), b)


def _decode_mesh_u(buf, cur, kind):
    """Layout U (Episode III field maps): V4-32 x (n+1) = header +
    (x, y, z, S); S-32 x n at n+1 = T | restart bit; no vertex normals."""
    c, tb = cur[0], cur[1]
    n, _, hw = _mesh_header(buf, c, need_z0=False)
    if tb.count != n:
        raise PxyError("mesh batch at %#x: T block of %d rows for n=%d"
                       % (c.off, tb.count, n))
    b = _new_batch(c, n, kind, hw, "U")
    f = np.frombuffer(buf, "<f4", c.count * 4, c.data_off).reshape(-1, 4)
    traw = np.frombuffer(buf, "<u4", n, tb.data_off)
    b.pos = f[1:, :3].astype(np.float64)
    b.nrm = None
    t = (traw & np.uint32(0xFFFFFFFE)).view("<f4")
    b.st = np.stack([f[1:, 3], t], axis=1).astype(np.float64)
    b.adc = (traw & 1).astype(bool)
    return _tail_blocks(buf, c, _rest_blocks(c, cur[2:]), b, skin_ok=False)


# ------------------------------------------------------------ interpretation

def batch_joints(p, node, b):
    """(joint-matrix indices (n,4), weights (n,4)) of a skinned batch;
    -1 marks unused influences.  Raises on anything out of range."""
    s = b.slots
    used = s != 255
    # 255 ends the list: once ended, every later byte must be 255 too,
    # except in rigid mode where the microcode reads only the first byte
    if b.skin_mode == 2:
        used[:, 1:] = False
    else:
        ended = np.logical_or.accumulate(~used, axis=1)
        if (used & ended).any():                 # the microcode stops at the first 255
            raise PxyError("batch at %#x: palette byte after the end of its list" % b.off)
        used &= ~ended
    if (s[used] & 3).any():
        raise PxyError("batch at %#x: palette byte not a multiple of 4"
                       % b.off)
    slot = s // 4
    n_j = p.n_joint_matrices
    if n_j <= 64:
        jm = slot.copy()
        limit = n_j
    else:
        pal = np.array(p.nodes[node].palette + [0] * 64, dtype=np.int32)[:64]
        limit = len(p.nodes[node].palette)
        jm = pal[np.minimum(slot, 63)] - 1
        # Episode III: a 63-entry list fills the node's 0x40-byte field up
        # to its terminator, yet vertices still use slot 63 (E3obj287 /
        # M3_npcr15).  Which matrix the engine has in that slot is not
        # known, so those vertices are left unbound (the skeleton root, as
        # for a rigid 255 byte) and counted by palette_overrun(); see
        # docs/MODELS.md.  Any other slot past the list still raises.
        if limit == 63:
            used &= ~(slot == 63)
    if used.any() and (int(slot[used].max()) >= limit
                       or int(jm[used].min()) < 0
                       or int(jm[used].max()) >= n_j):
        raise PxyError("batch at %#x: joint reference out of range" % b.off)
    jm = np.where(used, jm, -1)
    if b.skin_mode == 2:
        w = np.zeros((b.n, 4))
        w[:, 0] = used[:, 0]
    else:
        w = np.where(used, b.weights, 0.0)
    return jm, w


def palette_overrun(p, node, b):
    """Vertices of a skinned batch that use slot 63 past a full 63-entry
    node palette (left unbound by batch_joints)."""
    if not b.skin_mode or p.n_joint_matrices <= 64 or node is None:
        return 0
    if len(p.nodes[node].palette) != 63:
        return 0
    s = b.slots // 4
    u = b.slots != 255
    if b.skin_mode == 2:
        u[:, 1:] = False
    return int((u & (s == 63)).any(axis=1).sum())


def _signed(v):
    return v - (1 << 32) if v >> 31 else v


def _size_ok(m, e):
    return abs(m.sw * m.tex_w - _signed(e["w"])) < 1e-3 and \
        abs(m.tw * m.tex_h - _signed(e["h"])) < 1e-3


def link_textures(p, txy_entries):
    """Attach the .txy entry to every material batch by its TEX0 address.
    Returns the number of textured batches left without an entry."""
    by_addr = {}
    for e in txy_entries:
        by_addr.setdefault(e["gsaddr"], []).append(e)
    missing = 0
    for d in p.draws:
        for m in d.materials:
            if not m.textured:
                continue
            cands = [e for e in by_addr.get(m.tbp0 - GS_TEXTURE_BASE, [])
                     if e["fmt"] == m.psm]
            # several entries can share an address (other banks, other
            # palettes): prefer the one whose size and CLUT also agree
            cands.sort(key=lambda e: (not _size_ok(m, e),
                                      e["cbp"] != m.cbp - GS_TEXTURE_BASE))
            m.txy_entry = cands[0] if cands else None
            missing += m.txy_entry is None
    return missing


def check(p, txy_entries=None):
    """Numeric invariants.  Returns a dict of counters; `failed` lists
    the names of the gates this file does not pass."""
    r = dict(batches=0, vertices=0, triangles=0, failed=[])
    bad_unit = bad_wsum = n_w = 0
    wind_ok = wind_n = face_ok = face_n = 0
    uv_n = uv_in01 = uv_in11 = 0
    uv_max = 0.0
    box_out = box_n = 0
    sphere_out = 0
    nrm_n = 0
    skin_static = 0
    no_material = 0
    unbound = 0
    strips_n = strips_same = 0
    unlit_n = 0
    overrun = 0
    for d in p.draws:
        allpos = []
        for b in d.batches:
            r["batches"] += 1
            no_material += b.material is None
            r["vertices"] += b.n
            tris = b.triangles()
            r["triangles"] += len(tris)
            if b.nrm is not None:            # layout U has none
                ln = np.linalg.norm(b.nrm, axis=1)
                nrm_n += b.n
                bad_unit += int((np.abs(ln - 1) > 2e-3).sum())
            else:
                unlit_n += 1
            if b.adc[:2].any():
                r["failed"].append("restart flag on the first two vertices")
            if b.skin_mode:
                if d.node is None:
                    raise PxyError("skinned draw %d has no item" % d.index)
                jm, w = batch_joints(p, d.node, b)
                overrun += palette_overrun(p, d.node, b)
                n_w += b.n
                ws = w.sum(axis=1)
                # a rigid vertex whose byte is 255 is left unskinned
                free = (ws == 0) if b.skin_mode == 2 else np.zeros(b.n, bool)
                unbound += int(free.sum())
                bad_wsum += int(((np.abs(ws - 1) > 2e-3) & ~free).sum())
                if (w < -1e-6).any():
                    r["failed"].append("negative weight")
                if not np.allclose(p.node_mats[d.node], IDENT, atol=1e-6):
                    skin_static += 1
            if b.material is not None and b.material.textured \
                    and b.material.sw > 0 and b.material.tw > 0:
                uv = b.st / (b.material.sw, b.material.tw)
                uv_n += b.n
                uv_in01 += int(((uv >= -1e-3) & (uv <= 1 + 1e-3)).all(axis=1).sum())
                uv_in11 += int((np.abs(uv) <= 1 + 1e-3).all(axis=1).sum())
                uv_max = max(uv_max, float(np.abs(uv).max()))
            if len(tris):
                P = b.pos
                g = np.cross(P[tris[:, 1]] - P[tris[:, 0]],
                             P[tris[:, 2]] - P[tris[:, 0]])
                gl = np.linalg.norm(g, axis=1)
                # degenerate: no area, or an edge collapsed to float noise
                # (crystal tips in E3_REN08/09 repeat a vertex up to 2e-6
                # apart, and those slivers face either way at random)
                el = np.stack([np.linalg.norm(P[tris[:, a]] - P[tris[:, c]],
                                              axis=1)
                               for a, c in ((0, 1), (1, 2), (2, 0))], axis=1)
                ok = (gl > 1e-12) & (el.min(axis=1) > 1e-5 * el.max(axis=1))
            if len(tris) and b.nrm is not None:
                vn = b.nrm[tris].sum(axis=1)
                dall = (g * vn).sum(axis=1)
                dv = dall[ok]
                wind_n += int(ok.sum())
                wind_ok += int((dv > 0).sum())
                # within one strip every triangle must face the same way
                # relative to the normals (tests the alternation rule,
                # whatever way the strip as a whole was authored)
                start = np.maximum.accumulate(np.where(b.adc,
                                                       np.arange(b.n), 0))
                sid = start[tris[:, 2]][ok]
                front = dv > 0
                for s0 in np.unique(sid):
                    fr = front[sid == s0]
                    if len(fr) > 1:
                        strips_n += 1
                        strips_same += bool(fr.all() or not fr.any())
            if len(tris):
                if b.face is not None:
                    df = (g[ok] / gl[ok, None] * b.face[tris[:, 2]][ok]).sum(
                        axis=1)
                    face_n += int(ok.sum())
                    face_ok += int((df < -0.99).sum())
            allpos.append(b.pos)
        if allpos and d.items:
            P = np.concatenate(allpos)
            it = d.items[0]
            tol = 1e-3 * max(1.0, float(np.abs(P).max()))
            box_n += len(P)
            box_out += int(((P < it.bbox_min - tol)
                            | (P > it.bbox_max + tol)).any(axis=1).sum())
            dist = np.linalg.norm(P - it.sphere[:3], axis=1)
            sphere_out += int((dist > it.sphere[3] + tol).sum())
    r.update(normals=nrm_n, normals_not_unit=bad_unit, weighted=n_w,
             weights_not_one=bad_wsum, winding_tested=wind_n,
             winding_agree=wind_ok, face_tested=face_n, face_agree=face_ok,
             uv_vertices=uv_n, uv_in_0_1=uv_in01, uv_in_m1_1=uv_in11,
             uv_abs_max=uv_max, bbox_tested=box_n, bbox_outside=box_out,
             sphere_outside=sphere_out, skinned_under_moved_node=skin_static,
             batches_without_material=no_material,
             rigid_vertices_unbound=unbound, strips_tested=strips_n,
             strips_one_facing=strips_same, unlit_batches=unlit_n,
             palette_overrun=overrun)
    lay = {}
    for d in p.draws:
        for b in d.batches:
            lay[b.layout] = lay.get(b.layout, 0) + 1
    r["layouts"] = lay
    r["header_triangles"] = p.triangle_count
    if r["triangles"] != p.triangle_count:
        r["failed"].append("triangle count %d != header %d"
                           % (r["triangles"], p.triangle_count))
    if box_out:
        r["failed"].append("%d vertices outside their item box" % box_out)
    if sphere_out:
        r["failed"].append("%d vertices outside their item sphere"
                           % sphere_out)
    if bad_wsum:
        r["failed"].append("%d weight rows do not sum to 1" % bad_wsum)
    if nrm_n and bad_unit > 0.01 * nrm_n:
        r["failed"].append("%d of %d normals not unit length"
                           % (bad_unit, nrm_n))
    if strips_n and strips_same < 0.9 * strips_n:
        r["failed"].append("only %d of %d strips face one way"
                           % (strips_same, strips_n))
    if no_material:
        r["failed"].append("%d mesh batches precede any material batch"
                           % no_material)
    if skin_static:
        r["failed"].append("skinned batch under a non-identity node matrix")
    if (p.flags & 1) and any(b.skin_mode for d in p.draws for b in d.batches):
        r["failed"].append("skinned batch in a file flagged static")
    if txy_entries is not None:
        tex = [m for d in p.draws for m in d.materials if m.textured]
        r["material_batches_textured"] = len(tex)
        miss = link_textures(p, txy_entries)
        size_bad = 0
        for m in tex:
            e = m.txy_entry
            if e is None:
                continue
            if not _size_ok(m, e):
                size_bad += 1
        r["texture_unlinked"] = miss
        r["texture_size_mismatch"] = size_bad
        if miss:
            r["failed"].append("%d material batches name no .txy entry" % miss)
        if size_bad:
            r["failed"].append("%d material batches disagree with the .txy "
                               "entry size" % size_bad)
    if p.child is not None:
        # the +0xD0 pxy: same gates, its own header count; counters add up
        # (the package's one txy serves both: 0 unlinked on every disc)
        rc = check(p.child, txy_entries)
        r["child_triangles"] = rc["triangles"]
        for k, v in rc.items():
            if k == "failed":
                r["failed"] += ["pxy at +0xD0: " + f for f in v]
            elif k == "layouts":
                for lk, lv in v.items():
                    r["layouts"][lk] = r["layouts"].get(lk, 0) + lv
            elif k == "uv_abs_max":
                r[k] = max(r[k], v)
            elif isinstance(v, (int, np.integer)) and not isinstance(v, bool):
                r[k] = r.get(k, 0) + v
    return r


# -------------------------------------------------------------------- glTF

def _weld(arrays):
    """Merge identical vertices.  arrays: list of (n,k) float/int arrays.
    Returns (unique row indices, inverse)."""
    packed = np.concatenate([np.ascontiguousarray(a, dtype=np.float32)
                             .reshape(len(a), -1) for a in arrays], axis=1)
    v = np.ascontiguousarray(packed).view(
        np.dtype((np.void, packed.dtype.itemsize * packed.shape[1])))
    _, first, inv = np.unique(v.ravel(), return_index=True,
                              return_inverse=True)
    return first, inv.ravel()


def _alpha_mode(d):
    groups = set(it.group for it in d.items)
    if "alpha" in groups:
        return "BLEND" if groups == {"alpha"} else "MASK"
    return "OPAQUE"


def referenced_joints(p):
    """Joint-matrix indices that at least one vertex is bound to."""
    used = set()
    for d in p.draws:
        for b in d.batches:
            if b.skin_mode:
                jm, w = batch_joints(p, d.node, b)
                used.update(int(v) for v in np.unique(jm[w > 0]))
    return used


def skeleton_from(p, x):
    """Bind skeleton for glTF.  Returns (parents, world matrices
    (row-vector), inverse bind matrices per joint matrix, notes).  One
    transform per .xhr record when `x` is given (the mesh's joint matrix j
    is transform j + 2), else one per joint matrix under a single root.

    For a joint some vertex is bound to, the world matrix is the inverse
    of the mesh's own inverse bind matrix, so the rest pose reproduces the
    mesh exactly whatever the .xhr rest values say.  Every other transform
    keeps its .xhr rest matrix (and its glTF inverse bind matrix is the
    inverse of that): the mesh files carry inverse bind matrices that no
    vertex uses and that do not belong to the transform at their index."""
    n_j = p.n_joint_matrices
    bind = np.stack([np.linalg.inv(m) for m in p.inv_bind]) if n_j else \
        np.zeros((0, 4, 4))
    notes = {}
    if x is None:
        return [-1] * n_j, bind, p.inv_bind.copy(), notes
    if len(x.joints) < n_j + 2:
        raise PxyError("skeleton has %d transforms, mesh needs %d"
                       % (len(x.joints), n_j + 2))
    used = referenced_joints(p)
    world = x.world_matrices()
    parents = [j.parent for j in x.joints]
    inv = p.inv_bind.copy()
    differs = []
    unused_differs = []
    for j in range(n_j):
        err = float(np.abs(world[j + 2] - bind[j]).max())
        if j in used:
            if err > 1e-3:
                differs.append(j + 2)
            world[j + 2] = bind[j]
        else:
            if err > 1e-3:
                unused_differs.append(j + 2)
            inv[j] = np.linalg.inv(world[j + 2])
    notes["rest_differs"] = differs
    notes["unused_bind_differs"] = unused_differs
    return parents, world, inv, notes


# ---------------------------------------------------------------- textures

def png_bytes(w, h, rgba):
    """RGBA bytes -> PNG file bytes (stdlib only)."""
    import zlib

    def chunk(tag, payload):
        return (struct.pack(">I", len(payload)) + tag + payload
                + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF))
    stride = w * 4
    raw = b"".join(b"\0" + rgba[y * stride:(y + 1) * stride]
                   for y in range(h))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


class TextureSet(object):
    """The texture entries of one txy and a way to decode them.

    Built on the Episode III kit's chrtex.py: `entries` are its parsed
    entries (each with `gsaddr`, the word at +0x00 that TEX0 points at),
    `decode(wanted)` yields `(entry, w, h, rgba)` for the entries whose
    index is in `wanted` (all when None).  Field maps' multi-bank txy
    decode each entry against its own bank's GS state (chrtex, the XS2
    txy.py rule, with a fallback to the other bank states for entries
    whose bank word leaves them empty)."""

    def __init__(self, data, t):
        self.data, self.t = data, t
        self.entries = t["entries"]
        if self.entries and "gsaddr" not in self.entries[0]:
            raise PxyError("chrtex entries carry no gsaddr")

    def decode(self, wanted=None):
        import chrtex
        t = self.t
        if wanted is not None:
            t = dict(t, entries=[e for e in t["entries"] if e["i"] in wanted])
        return chrtex.decode_entries(self.data, t)


def package_textures(data):
    """TextureSet of a STORED MR package (`xcpack.normalize` first), or
    None when it has no (or an empty) txy slot."""
    import chrtex
    try:
        return TextureSet(data, chrtex.parse_txy(
            data, *chrtex.parse_chr(data)["txy"]))
    except chrtex.ChrError:
        return None


def txy_textures(txy_data):
    """TextureSet of a standalone `.txy` file (same format as the package
    block, without the 0x40-byte package pre-header)."""
    import chrtex
    try:
        return TextureSet(txy_data, chrtex.parse_txy(txy_data, -0x40,
                                                     len(txy_data)))
    except chrtex.ChrError as e:
        raise PxyError("txy: %s" % e)


def to_glb(p, textures=None, x=None, name=None):
    """Serialise a parsed .pxy.  `textures`: a `TextureSet` (or the bytes
    of a standalone .txy); `x`: a parsed .xhr (skeleton hierarchy)."""
    import gltf
    if not all_draws(p):
        # (E3_HAK16.map / E3_HAK01_EV03 have no draw of their own: all their
        # mesh is the +0xD0 pxy.)  An empty glb would be invalid glTF.
        raise PxyError("no draws in this pxy or at +0xD0 (%d-byte pxy, %d "
                       "materials): nothing to write"
                       % (p.size, len(p.materials)))
    if p.child is not None and any(b.skin_mode for d in p.child.draws
                                   for b in d.batches):
        raise PxyError("skinned batch in the pxy at +0xD0 (never seen)")
    g = gltf.GlbBuilder("Xenosaga3PythonExtractor pxy.py")
    warnings = []
    # ---- textures
    tex_index = {}
    if isinstance(textures, (bytes, bytearray)):
        textures = txy_textures(bytes(textures))
    if textures is not None:
        link_textures(p, textures.entries)
        if p.child is not None:
            link_textures(p.child, textures.entries)
        used = {}
        for d in all_draws(p):
            for m in d.materials:
                if m.txy_entry is not None:
                    used[m.txy_entry["i"]] = m.txy_entry
        pngs = {}
        for e, w, h, rgba in textures.decode(set(used)):
            if e["i"] in used and e["i"] not in pngs:
                pngs[e["i"]] = (png_bytes(w, h, rgba), e["name"])
        images = {i: g.add_image(png, nm) for i, (png, nm) in
                  sorted(pngs.items())}
    else:
        images = {}
    mat_index = {}

    def material(d, st, unlit=False):
        mode = _alpha_mode(d)
        key = (st.key if st is not None else None, mode, unlit)
        if key in mat_index:
            return mat_index[key]
        tex = None
        nm = "untextured"
        extras = {}
        if st is not None:
            extras = {"shader": st.shader, "tex0": "%016x" % st.tex0,
                      "clamp": "%016x" % st.clamp}
            e = st.txy_entry
            if e is not None:
                nm = "%s_s%d" % (e["name"], st.shader)
                if e["i"] in images:
                    wrap = {0: gltf.REPEAT, 1: gltf.CLAMP_TO_EDGE,
                            2: gltf.CLAMP_TO_EDGE, 3: gltf.REPEAT}
                    tk = (e["i"], st.wms, st.wmt)
                    if tk not in tex_index:
                        tex_index[tk] = g.add_texture(
                            images[e["i"]], wrap[st.wms], wrap[st.wmt])
                    tex = tex_index[tk]
            elif st.textured:
                nm = "tbp%04x" % st.tbp0
        mat_index[key] = g.add_material(nm, tex, alpha_mode=mode,
                                        extras=extras, unlit=unlit)
        return mat_index[key]

    # ---- skeleton
    skinned = any(b.skin_mode for d in p.draws for b in d.batches)
    skin = None
    root_joint = None
    if skinned:
        parents, world, inv_bind, notes = skeleton_from(p, x)
        if notes.get("rest_differs"):
            warnings.append("xhr rest pose differs from the bind pose at "
                            "transforms %r (bind pose used)"
                            % notes["rest_differs"])
        ov = sum(palette_overrun(p, d.node, b) for d in p.draws
                 for b in d.batches)
        if ov:
            warnings.append("%d vertices use palette slot 63 past a full "
                            "63-entry node palette; left unbound" % ov)
        if notes.get("unused_bind_differs"):
            warnings.append("inverse bind matrices no vertex uses do not "
                            "match the xhr at transforms %r (xhr used)"
                            % notes["unused_bind_differs"])
        n_t = len(parents)
        first = len(g.nodes)
        base = 0 if x is not None else None
        for i in range(n_t):
            pw = world[parents[i]] if parents[i] >= 0 else IDENT
            local = world[i] @ np.linalg.inv(pw)        # row-vector
            tr, q, s = gltf.trs_from_matrix(local.T)
            nm = (x.joints[i].name if x is not None else "j%02d" % i)
            g.add_node(nm, translation=tr, rotation=q, scale=s)
        root_joint = g.add_node("skeleton", root=True)
        for i in range(n_t):
            g.add_child(first + parents[i] if parents[i] >= 0 else root_joint,
                        first + i)
        joff = 2 if x is not None else 0
        joint_nodes = [first + j + joff for j in range(p.n_joint_matrices)]
        ibm = [m.T for m in inv_bind]
        joint_nodes.append(root_joint)          # for unskinned batches
        ibm.append(IDENT)
        skin = g.add_skin(p.name or "skin", joint_nodes, ibm, root_joint)
    def emit(p, root=True, skinned=skinned):
        """Meshes of one pxy, one per node; returns (triangles, glTF
        node indices).  `p` shadows the outer one on purpose; the +0xD0
        pxy is emitted with root=False, skinned=False."""
        added = []
        by_node = {}
        for d in p.draws:
            if d.batches:
                by_node.setdefault(d.node if d.node is not None else 0,
                                   []).append(d)
        n_tris = 0
        for node_i in sorted(by_node):
            prims = {}
            for d in by_node[node_i]:
                for b in d.batches:
                    prims.setdefault(material(d, b.material, b.unlit),
                                     []).append((d, b))
            out = []
            node_skinned = False
            for mat, lst in sorted(prims.items()):
                P, N, UV, COL, J, W, IDX = [], [], [], [], [], [], []
                base = 0
                any_color = False
                unlit = lst[0][1].unlit        # one material key = one layout kind
                for d, b in lst:
                    st = b.material
                    P.append(b.pos)
                    N.append(b.nrm if b.nrm is not None else np.zeros((b.n, 3)))
                    if st is not None and st.sw > 0 and st.tw > 0:
                        UV.append(b.st / (st.sw, st.tw))
                    else:
                        UV.append(b.st)
                    if b.colors is None:
                        c = np.full((b.n, 4), 128.0)
                    else:
                        c = np.broadcast_to(b.colors.astype(np.float64),
                                            (b.n, 4))
                        any_color = True
                    COL.append(np.clip(c / 128.0, 0.0, 1.0))
                    if skinned:
                        if b.skin_mode:
                            jm, w = batch_joints(p, node_i, b)
                            ws = w.sum(axis=1, keepdims=True)
                            w = w / np.where(ws == 0, 1, ws)
                            jm = np.where(w > 0, jm, 0)
                            free = ws[:, 0] == 0        # rigid, byte 255
                            jm[free, 0] = p.n_joint_matrices
                            w[free, 0] = 1.0
                        else:
                            jm = np.zeros((b.n, 4), dtype=np.int64)
                            jm[:, 0] = p.n_joint_matrices
                            w = np.zeros((b.n, 4))
                            w[:, 0] = 1.0
                        J.append(jm)
                        W.append(w)
                        node_skinned = True
                    tris = b.triangles()
                    if len(tris) and not b.unlit:
                        # the engine draws these two-sided and the strips'
                        # facing is not reliable (see docs/MODELS.md): turn
                        # each triangle to face along its vertex normals
                        # (layout U has none: strip-parity winding is kept)
                        gn = np.cross(b.pos[tris[:, 1]] - b.pos[tris[:, 0]],
                                      b.pos[tris[:, 2]] - b.pos[tris[:, 0]])
                        back = (gn * b.nrm[tris].sum(axis=1)).sum(axis=1) < 0
                        tris[back] = tris[back][:, [1, 0, 2]]
                    IDX.append(tris + base)
                    base += b.n
                idx = np.concatenate(IDX)
                if not len(idx):
                    continue
                cols = [np.concatenate(P), np.concatenate(N), np.concatenate(UV),
                        np.concatenate(COL)]
                if skinned:
                    cols += [np.concatenate(J), np.concatenate(W)]
                first_i, inv = _weld(cols)
                tri = inv[idx]
                # degenerate triangles are kept: the count then equals the file's own
                n_tris += len(tri)
                nrm = cols[1][first_i]
                ln = np.linalg.norm(nrm, axis=1, keepdims=True)
                nrm = np.where(ln > 1e-6, nrm / np.where(ln == 0, 1, ln),
                               [0.0, 0.0, 1.0])
                prim = dict(positions=cols[0][first_i],
                            normals=None if unlit else nrm,
                            uvs=cols[2][first_i], indices=tri.reshape(-1),
                            material=mat)
                if any_color or unlit:
                    prim["colors"] = cols[3][first_i]
                if skinned:
                    prim["joints"] = cols[4][first_i]
                    prim["weights"] = cols[5][first_i]
                out.append(prim)
            if not out:
                continue
            nd = p.nodes[node_i] if node_i < len(p.nodes) else None
            nm = nd.name if nd is not None and nd.name else "node%d" % node_i
            mesh = g.add_mesh(nm, out)
            if node_skinned:
                added.append(g.add_node(nm, mesh=mesh, skin=skin, root=root))
            else:
                added.append(g.add_node(
                    nm, mesh=mesh, root=root,
                    matrix=nd.matrix.T if nd is not None else None))
        return n_tris, added

    n_tris, _ = emit(p)
    child_info = None
    if p.child is not None:
        c = p.child
        c_tris, c_nodes = emit(c, False, False) if c.draws else (0, [])
        n_tris += c_tris
        if c_nodes:
            # grouped under one node named after the inner pxy's own name
            g.add_node(c.name or "pxy", children=c_nodes, root=True,
                       extras={"pxy_at": "0x%x" % p.child_offset,
                               "triangles": c_tris})
        child_info = {"offset": p.child_offset, "name": c.name,
                      "triangles": c_tris, "draws": len(c.draws)}
    if n_tris == 0 or not g.meshes:
        raise PxyError("%d draws decoded but no triangles (%d-byte pxy): "
                       "nothing to write" % (len(p.draws), p.size))
    g.extras = {"source": p.name, "pxy_version": round(float(p.version), 2),
                "pxy_flags": p.flags, "triangles": n_tris,
                "warnings": warnings}
    if child_info is not None:
        g.extras["pxy_at_0xD0"] = child_info
    return g.to_bytes(name or p.name or "pxy")


# --------------------------------------------------------------- self-test

def _synthetic(skinned=True, n_joint=3, xs3=False):
    """A two-draw file: a material batch and two mesh batches, one of them
    weighted, with a strip restart; built from scratch.  With `xs3` (a
    static file) the second draw holds an Episode III layout-Q quad and a
    layout-U triangle instead of the rigid triangle."""
    w = lambda cmd, num, imm: struct.pack("<I", cmd << 24 | num << 16 | imm)
    stcycl = w(0x01, 0, 0x0101)
    mscnt = w(0x17, 0, 0)

    def unpack(fmt, addr, rows, signed=False):
        code = {"V4-32": 0x6C, "V2-32": 0x64, "V4-8": 0x6E, "V4-16": 0x6D,
                "S-32": 0x60}[fmt]
        body = b"".join(rows)
        body += b"\0" * (-len(body) % 4)
        return w(code, len(rows), (0x8000 if signed else 0xC000) | addr) \
            + body
    f4 = lambda *v: struct.pack("<4f", *v)
    sw, tw = 64 / 1024.0, 32 / 512.0
    tex0 = (0x3800 + 0x40) | 16 << 14 | 0x13 << 20 | 10 << 26 | 9 << 30 \
        | (0x3800 + 0x80) << 37
    mat = [struct.pack("<IIIf", 10, 1, 10, sw),
           struct.pack("<IIIf", 0x8007, 0x10000000, 0xE, tw),
           struct.pack("<QQ", tex0, 0), bytes(16),
           struct.pack("<QQ", 0x1F0003FF, 0)] + [bytes(16)] * 12
    mat_batch = stcycl + unpack("V4-32", 0, mat) + mscnt
    stream = mat_batch
    # a quad as one strip, then a restart and a second quad
    quad = [(0, 0, 0), (1, 0, 0), (0, 1, 0), (1, 1, 0)]
    pts = quad + [(x + 2, y, 0) for x, y, _ in quad]
    uvs = [(x * 0.5, y * 0.5) for x, y, _ in pts]
    n = len(pts)

    def tflt(v, flag):
        raw, = struct.unpack("<I", struct.pack("<f", v))
        return struct.pack("<I", (raw & ~1) | flag)
    rows = [struct.pack("<IIII", 0x8000 | n, 0, 0, (1 | 4) if skinned else 1)]
    rows += [f4(x, y, z, u * sw) for (x, y, z), (u, v) in zip(pts, uvs)]
    rows += [struct.pack("<3f", 0, 0, 1) + tflt(v * tw, 1 if i == 4 else 0)
             for i, (u, v) in enumerate(uvs)]
    mesh = unpack("V4-32", 0, rows)
    mesh += unpack("V4-8", 2 * n + 1, [bytes(bytearray(
        [128, 64 + i, 128, 128])) for i in range(n)])
    if skinned:
        mesh += unpack("V2-32", 4 * n + 1, [struct.pack("<2f", 0.75, 0.25)] * n)
        mesh += unpack("V4-8", 5 * n + 1, [bytes(bytearray(
            [0, 4, 255, 255]))] * n)
    stream += stcycl + mesh + mscnt
    # second draw: a rigid triangle with one colour for the batch
    rows = [struct.pack("<IIII", 0x8003, 3, 0, 2 if skinned else 0),
            f4(0, 0, 1, 0), f4(1, 0, 1, 0), f4(0, 1, 1, 0)]
    rows += [struct.pack("<3f", 0, 0, 1) + tflt(0.0, 0)] * 3
    tri = unpack("V4-32", 0, rows) + unpack("V4-8", 7, [b"\x80\x80\x80\x80"])
    if skinned:
        tri += unpack("V4-8", 16, [bytes(bytearray([8, 255, 255, 255]))] * 3)
    d0 = stream + b"\0" * (-len(stream) % 16)
    d1 = mat_batch + stcycl + tri + mscnt
    if xs3:
        # layout Q: header (z = f32 scale 2.0), signed V4-16 x 2n at 1
        qp = [(0, 0, 1), (1, 0, 1), (0, 1, 1), (1, 1, 1)]
        sc = 2.0
        qrows = [struct.pack("<IIfI", 0x8004, 0, sc, 0)]
        q16 = [struct.pack("<4h", *[int(round(v * 4096 / sc)) for v in pt]
                           + [int(round(pt[0] * sw * 4096))]) for pt in qp]
        q16 += [struct.pack("<4h", 0, 0, 4096, int(round(pt[1] * tw * 4096)))
                for pt in qp]
        qb = unpack("V4-32", 0, qrows) + unpack("V4-16", 1, q16, signed=True)
        qb += unpack("V4-8", 9, [b"\x80\x80\x80\x80"])
        # layout U: V4-32 x (n+1), S-32 T at n+1, colours 2n+1, face 3n+1
        up = [(0, 0, 1), (1, 0, 1), (0, 1, 1)]
        urows = [struct.pack("<IIII", 0x8003, 0, 0, 1)]
        urows += [f4(x, y, z, x * sw) for x, y, z in up]
        ub = unpack("V4-32", 0, urows)
        ub += unpack("S-32", 4, [tflt(y * tw, 0) for x, y, z in up])
        ub += unpack("V4-8", 7, [bytes(bytearray([200, 100, 50, 128]))] * 3)
        ub += unpack("V4-32", 10, [f4(0, 0, -1, 0)] * 3)
        d1 = mat_batch + stcycl + qb + mscnt + stcycl + ub + mscnt
    d1 += b"\0" * (-len(d1) % 16)
    n_j = n_joint if skinned else 0
    rng = np.random.RandomState(3)
    bind = []
    for j in range(n_j):
        m = np.eye(4)
        a = rng.uniform(-1, 1)
        m[:3, :3] = [[np.cos(a), np.sin(a), 0], [-np.sin(a), np.cos(a), 0],
                     [0, 0, 1]]
        m[3, :3] = rng.uniform(-1, 1, 3)
        bind.append(m)
    o_group, o_mat = 0x4B0, 0x4F0
    o_node = o_mat + 0x60
    o_inv = o_node + 0x70
    o_skin = o_inv + n_j * 0x40
    o_nm = o_skin + n_j * 0x40
    o_vif = o_nm + 0x40
    o_draw = o_vif + len(d0) + len(d1)
    o_item = o_draw + 0x40
    size = o_item + 2 * 0x60
    buf = bytearray(size)
    struct.pack_into("<4sfII", buf, 0, b"pxy\0", 0.15, 0 if skinned else 1,
                     size)
    buf[0x10:0x18] = b"synth\0\0\0"
    struct.pack_into("<20I", buf, 0x30, 1, 1, 1, o_draw, o_item, 2, 2, o_vif,
                     2, o_group, o_mat, n_j, 1, o_inv, o_nm, o_node, o_skin,
                     0, 0, 0)
    struct.pack_into("<I", buf, 0xB4, 7 if xs3 else 5)
    buf[o_group:o_group + 9] = b"non-alpha"
    struct.pack_into("<4I", buf, o_group + 0x10, 0, 0, 2, 0)
    buf[o_group + 0x20:o_group + 0x25] = b"alpha"
    struct.pack_into("<4I", buf, o_group + 0x30, 1, 2, 0, 0)
    buf[o_mat:o_mat + 7] = b"lambert"
    struct.pack_into("<3I", buf, o_mat + 0x20, 0xF, 10, 5 << 16)
    buf[o_node:o_node + 4] = b"body"
    buf[o_node + 0x30:o_node + 0x33] = b"\x01\x02\x03"
    for j, m in enumerate(bind):
        struct.pack_into("<16f", buf, o_inv + j * 0x40,
                         *np.linalg.inv(m).reshape(-1))
        struct.pack_into("<16f", buf, o_skin + j * 0x40, *IDENT.reshape(-1))
    struct.pack_into("<16f", buf, o_nm, *IDENT.reshape(-1))
    buf[o_vif:o_vif + len(d0)] = d0
    buf[o_vif + len(d0):o_draw] = d1
    struct.pack_into("<4I", buf, o_draw, o_vif, len(d0) // 16, 0, 0)
    struct.pack_into("<4I", buf, o_draw + 0x20, o_vif + len(d0),
                     len(d1) // 16, 0, 1)
    for i, (lo, hi) in enumerate((((0, 0, 0), (3, 1, 0)),
                                  ((0, 0, 1), (1, 1, 1)))):
        o = o_item + i * 0x60
        struct.pack_into("<8i", buf, o, 1, i, 0, 0, 0, i, 0, 0)
        struct.pack_into("<4f", buf, o + 0x20, lo[0], lo[1], lo[2], 0)
        struct.pack_into("<4f", buf, o + 0x30, hi[0], hi[1], hi[2], 0)
        c = [(a + b) / 2.0 for a, b in zip(lo, hi)]
        struct.pack_into("<4f", buf, o + 0x40, c[0], c[1], c[2], 2.0)
    entries = [dict(i=5, name="tex", gsaddr=0x40, fmt=0x13, w=64, h=32,
                    cbp=0x80)]
    return bytes(buf), pts, uvs, bind, entries


def self_test():
    import gltf
    data, pts, uvs, bind, entries = _synthetic(True)
    p = parse(data)
    assert p.name == "synth" and len(p.draws) == 2 and len(p.materials) == 1
    assert p.materials[0].ordinal == 5 and p.nodes[0].palette == [1, 2, 3]
    b = p.draws[0].batches[0]
    assert b.n == 8 and b.per_vertex_color and b.skin_mode == 4
    assert np.allclose(b.pos, pts)
    st = b.material
    assert st.shader == 10 and st.tex_w == 1024 and st.tex_h == 512
    assert st.tbp0 == 0x3840 and st.cbp == 0x3880 and st.psm == 0x13
    assert np.allclose(b.st / (st.sw, st.tw), uvs, atol=1e-6)
    # strip rule: restart at vertex 4 -> two quads, four triangles, CCW
    tris = b.triangles().tolist()
    assert tris == [[0, 1, 2], [2, 1, 3], [4, 5, 6], [6, 5, 7]], tris
    jm, w = batch_joints(p, 0, b)
    assert jm[0].tolist() == [0, 1, -1, -1] and w[0].tolist() == [.75, .25, 0, 0]
    jm, w = batch_joints(p, 0, p.draws[1].batches[0])
    assert jm[0].tolist() == [2, -1, -1, -1] and w[0, 0] == 1
    r = check(p, entries)
    assert not r["failed"], r["failed"]
    assert r["triangles"] == 5 and r["winding_agree"] == r["winding_tested"] == 5
    assert r["uv_vertices"] == 11 and r["uv_in_0_1"] == 9      # u = 1.5 twice
    assert r["batches_without_material"] == 0
    assert r["strips_tested"] == 2 and r["strips_one_facing"] == 2
    assert abs(r["uv_abs_max"] - 1.5) < 1e-6
    # the skinned GLB, read back, must give the static mesh in rest pose
    glb = to_glb(p)
    js, binc = gltf.read_glb(glb)
    assert len(js["skins"][0]["joints"]) == 4
    mesh_nodes = [i for i, nd in enumerate(js["nodes"]) if "mesh" in nd]
    worst = 0.0
    for i in mesh_nodes:
        for static, skinned in gltf.skinned_positions(js, binc, i):
            worst = max(worst, float(np.abs(static - skinned).max()))
    assert worst < 1e-5, worst
    nt = sum(js["accessors"][pr["indices"]]["count"] // 3
             for m in js["meshes"] for pr in m["primitives"])
    assert nt == 5
    # static variant
    data2 = _synthetic(False)[0]
    p2 = parse(data2)
    assert not check(p2)["failed"]
    js2, _ = gltf.read_glb(to_glb(p2))
    assert "skins" not in js2
    # Episode III layouts Q (quantized V4-16) and U (unlit map)
    p3 = parse(_synthetic(False, xs3=True)[0])
    bq, bu = p3.draws[1].batches
    assert (bq.layout, bu.layout) == ("Q", "U")
    assert np.allclose(bq.pos, [(0, 0, 1), (1, 0, 1), (0, 1, 1), (1, 1, 1)])
    assert np.allclose(bq.nrm, [(0, 0, 1)] * 4)
    assert bq.triangles().tolist() == [[0, 1, 2], [2, 1, 3]]
    sq = bq.material
    assert np.allclose(bq.st / (sq.sw, sq.tw), [(0, 0), (1, 0), (0, 1),
                                                (1, 1)], atol=1e-3)
    assert bu.unlit and bu.nrm is None and bu.colors.shape == (3, 4)
    assert bu.triangles().tolist() == [[0, 1, 2]]
    r3 = check(p3, entries)
    assert not r3["failed"], r3["failed"]
    assert r3["triangles"] == 7 and r3["layouts"] == {"F": 1, "Q": 1, "U": 1}
    assert r3["face_tested"] == r3["face_agree"] == 1
    assert r3["unlit_batches"] == 1 and r3["texture_unlinked"] == 0
    js3, _ = gltf.read_glb(to_glb(p3))
    unlit_m = [i for i, m in enumerate(js3["materials"])
               if "KHR_materials_unlit" in m.get("extensions", {})]
    assert len(unlit_m) == 1 and js3["extensionsUsed"] == [
        "KHR_materials_unlit"]
    up = [pr for m in js3["meshes"] for pr in m["primitives"]
          if pr["material"] in unlit_m]
    assert len(up) == 1 and "NORMAL" not in up[0]["attributes"] \
        and "COLOR_0" in up[0]["attributes"]
    assert sum(js3["accessors"][pr["indices"]]["count"] // 3
               for m in js3["meshes"] for pr in m["primitives"]) == 7
    # damage must be caught, not skipped
    bad = bytearray(data)
    o = p.draws[0].batches[0].off
    struct.pack_into("<I", bad, o + 4, 0x800C)          # n = 12, rows say 8
    wrong_tris = bytearray(data)
    struct.pack_into("<I", wrong_tris, 0xB4, 6)
    for blob, exc in ((bytes(bad), PxyError), (data[:-16], PxyError),
                      (b"pxz\0" + data[4:], PxyError)):
        try:
            parse(blob)
        except exc:
            pass
        else:
            raise AssertionError("parse accepted a damaged file")
    assert check(parse(bytes(wrong_tris)))["failed"]
    stray = bytearray(data)
    struct.pack_into("<I", stray, p.offsets["vif"], 0x20000000)   # STMASK
    try:
        parse(bytes(stray))
    except (PxyError, vif.VifError):
        pass
    else:
        raise AssertionError("parse accepted a stray VIF command")
    # a second pxy at header +0xD0 (Episode III maps): parsed, checked and
    # exported with the first; an outer pxy with no draw of its own (the
    # E3_HAK16 shape) still converts through it
    data3 = _synthetic(False, xs3=True)[0]
    outer = bytearray(data3) + data3
    struct.pack_into("<I", outer, 12, len(outer))
    struct.pack_into("<I", outer, 0xD0, len(data3))
    po = parse(bytes(outer))
    assert po.child is not None and po.child_offset == len(data3)
    assert header_triangles(po) == 14 and len(all_draws(po)) == 4
    ro = check(po, entries)
    assert not ro["failed"], ro["failed"]
    assert ro["triangles"] == 14 and ro["child_triangles"] == 7
    assert ro["layouts"] == {"F": 2, "Q": 2, "U": 2}
    jso, _ = gltf.read_glb(to_glb(po, None))
    assert jso["extras"]["pxy_at_0xD0"]["triangles"] == 7
    assert sum(jso["accessors"][pr["indices"]]["count"] // 3
               for m in jso["meshes"] for pr in m["primitives"]) == 14
    shell = bytearray(outer)
    struct.pack_into("<I", shell, 0x30 + 8 * 4, 0)       # outer: no draws
    struct.pack_into("<I", shell, 0x30 + 6 * 4, 0)       # ... and no items
    struct.pack_into("<I", shell, 0x30 + 3 * 4, len(data3))  # draw list at end
    struct.pack_into("<I", shell, 0x30 + 7 * 4, len(data3))  # VIF empty
    struct.pack_into("<I", shell, 0xB4, 0)
    ps = parse(bytes(shell))
    assert not ps.draws and header_triangles(ps) == 7
    rs = check(ps)
    assert not rs["failed"] and rs["triangles"] == 7, rs["failed"]
    jss, _ = gltf.read_glb(to_glb(ps))
    assert sum(jss["accessors"][pr["indices"]]["count"] // 3
               for m in jss["meshes"] for pr in m["primitives"]) == 7
    print("pxy self-test ok (layout F skinned + static, layout Q quantized, "
          "layout U unlit, pxy at +0xD0, checks, glb read-back, damage "
          "rejection)")
    return 0


def add_commands(subparsers):
    """Library module: registers no CLI subcommand (kit convention; the
    `model` / `models` commands live in models_sweep.py)."""
    return None


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description=".pxy mesh -> .glb")
    ap.add_argument("file", nargs="?")
    ap.add_argument("--txy")
    ap.add_argument("--xhr")
    ap.add_argument("--glb")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test or not a.file:
        return self_test()
    with open(a.file, "rb") as f:
        raw = f.read()
    tex = x = None
    entries = None
    if raw[:2] == b"Xc":                  # .chr / .wpn / .map package
        import models_sweep
        p, tex, x = models_sweep.load_package(raw)
        if p is None:
            print("%s: empty pxy slot" % a.file)
            return 0
    else:
        p = parse(raw)
    if a.txy:
        with open(a.txy, "rb") as f:
            tex = txy_textures(f.read())
    if tex is not None:
        entries = tex.entries
    if a.xhr:
        import xhr
        with open(a.xhr, "rb") as f:
            x = xhr.parse(f.read())
    r = check(p, entries)
    print("%s: pxy %.2f flags %#x, %d nodes, %d materials, %d joint matrices,"
          " %d draws, %d items" % (p.name, p.version, p.flags, len(p.nodes),
                                   len(p.materials), p.n_joint_matrices,
                                   len(p.draws), len(p.items)))
    for k in sorted(r):
        if k != "failed":
            print("  %-26s %s" % (k, r[k]))
    print("  invariants: %s" % ("all pass" if not r["failed"]
                                else "; ".join(r["failed"])))
    if x is not None and p.n_joint_matrices \
            and len(x.joints) >= p.n_joint_matrices + 2:
        used = referenced_joints(p)
        w = x.world_matrices()
        n = p.n_joint_matrices
        e = np.abs(np.einsum("nij,njk->nik", p.inv_bind, w[2:2 + n])
                   - IDENT).reshape(n, -1).max(axis=1)
        print("  xhr rest pose vs bind pose, max |invBind*world - I|: %.3g "
              "over the %d joints vertices use, %.3g over the other %d"
              % (max([e[j] for j in used] or [0]), len(used),
                 max([e[j] for j in range(n) if j not in used] or [0]),
                 n - len(used)))
    if a.glb:
        blob = to_glb(p, tex, x)
        with open(a.glb, "wb") as f:
            f.write(blob)
        print("wrote %s (%d bytes)" % (a.glb, len(blob)))
    return 1 if r["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
