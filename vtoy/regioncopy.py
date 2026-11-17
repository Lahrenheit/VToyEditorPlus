"""Copy everything of a map that lies inside a box (static meshes, props, decals, lights, collision boxes and hulls) to another
place of the same map, shifted by ``offset`` (engine coordinates).  New objects are listed in the sectors around them, so the
game's visibility / collision lookups find them.  Pure data: no GL."""
from __future__ import annotations

import copy
import struct
from dataclasses import dataclass
from typing import List

import numpy as np

from . import crop
from .opt import OptMap, translate_mesh


@dataclass
class CopyReport:
    meshes: int = 0
    props: int = 0
    decals: int = 0
    lights: int = 0
    boxes: int = 0
    hulls: int = 0

    def summary(self) -> str:
        return (f"{self.meshes} meshes, {self.props} props, {self.decals} decals, {self.lights} lights, "
                f"{self.boxes} collision boxes, {self.hulls} hulls")


def _inside(p, lo, hi) -> bool:
    return bool(np.all(np.asarray(p) >= lo) and np.all(np.asarray(p) <= hi))


def _box_bounds(raw: bytes):
    a = np.frombuffer(raw, "<f4", 19).astype(np.float64)
    c = a[12:15]
    half = np.abs(a[16:19])
    r = np.abs(a[:16].reshape(4, 4)[:3, :3]).T @ half
    return c - r, c + r


def _sector_box(s):
    a = np.frombuffer(s.head, "<f4", 19).astype(np.float64)
    return a[12:15], a[16:19]


def root_bounds(blk):
    """(lo, hi) of the whole sector tree (the first record is the root)."""
    c, e = _sector_box(blk.sectors[0])
    return c - e, c + e


def _sectors_for(blk, lo, hi, margin: float = 50.0):
    """Leaf sectors (tail == 0) that overlap the box: only leaves hold object / collision lists, the inner nodes are empty in
    every shipped map.  When none overlaps, the leaf whose centre is nearest."""
    lo, hi = np.asarray(lo, np.float64), np.asarray(hi, np.float64)
    leaves = [s for s in blk.sectors if s.tail == 0]
    out = []
    for s in leaves:
        c, e = _sector_box(s)
        if np.all(lo - margin <= c + e) and np.all(hi + margin >= c - e):
            out.append(s)
    if out:
        return out
    cen = (lo + hi) / 2
    best = min(leaves, key=lambda s: float(((_sector_box(s)[0] - cen) ** 2).sum()), default=None)
    return [best] if best is not None else []


def region_contents(m: OptMap, lo, hi):
    """Indices of what lies in the box (selection by centre): (meshes, props, decals, lights, boxes, hulls)."""
    lo, hi = np.asarray(lo, np.float64), np.asarray(hi, np.float64)
    meshes = []
    for i, me in enumerate(m.meshes):
        a, b = crop.mesh_bounds(me)
        if np.isfinite(a).all() and _inside((a + b) / 2, lo, hi):
            meshes.append(i)
    props = [i for i, p in enumerate(m.props) if _inside(p.transform[3, :3], lo, hi)]
    decals = [i for i, d in enumerate(m.decals) if _inside(d.position, lo, hi)]
    lights = [i for i, l in enumerate(m.lights) if _inside(l.position, lo, hi)]
    blk = crop.read_block(m)
    boxes = [i for i, b in enumerate(blk.boxes) if _inside(np.frombuffer(b, "<f4", 19)[12:15], lo, hi)]
    hulls = []
    for i, pb in enumerate(blk.polys):
        n = struct.unpack_from("<I", pb, 0)[0]
        q = np.frombuffer(pb, "<f4", 3 * n, 4).reshape(n, 3)
        if n and np.all(q[:, 0] >= lo[0]) and np.all(q[:, 0] <= hi[0]) and np.all(q[:, 1] >= lo[2]) and np.all(q[:, 1] <= hi[2]):
            hulls.append(i)
    return meshes, props, decals, lights, boxes, hulls


def copy_region(m: OptMap, lo, hi, offset) -> CopyReport:
    """Duplicate what lies in the box ``lo..hi`` shifted by ``offset``.  Props that use a copied mesh point to its copy."""
    if m.old_format:
        from . import optconv
        optconv.convert(m)
    off = np.asarray(offset, np.float32)
    meshes, props, decals, lights, boxes, hulls = region_contents(m, lo, hi)
    blk = crop.read_block(m)
    rlo, rhi = root_bounds(blk)
    tlo = np.maximum(np.asarray(lo, np.float64), rlo) + off
    thi = np.minimum(np.asarray(hi, np.float64), rhi) + off
    if not (np.all(tlo[[0, 2]] >= rlo[[0, 2]]) and np.all(thi[[0, 2]] <= rhi[[0, 2]])):
        raise ValueError("the copy would fall outside the map's sector tree (x %.0f..%.0f, z %.0f..%.0f): the game would not draw "
                         "or collide with it. Move it inside that area." % (rlo[0], rhi[0], rlo[2], rhi[2]))
    n_mesh, n_prop, n_dec = len(m.meshes), len(m.props), len(m.decals)
    rep = CopyReport(len(meshes), len(props), len(decals), len(lights), len(boxes), len(hulls))

    new_meshes = []
    mesh_map = {}
    for k, i in enumerate(meshes):
        me = copy.deepcopy(m.meshes[i])
        translate_mesh(me, off)
        new_meshes.append(me)
        mesh_map[i] = n_mesh + k
    new_props = []
    for i in props:
        p = copy.deepcopy(m.props[i])
        p.transform = p.transform.copy()
        p.transform[3, :3] += off
        p.corners = np.asarray(p.corners, np.float32) + off
        p.mesh_index = mesh_map.get(p.mesh_index, p.mesh_index)
        new_props.append(p)
    new_decals = []
    for i in decals:
        d = copy.deepcopy(m.decals[i])
        d.position = (np.asarray(d.position, np.float32) + off).astype(np.float32)
        new_decals.append(d)
    for i in lights:
        l = copy.deepcopy(m.lights[i])
        l.position = (np.asarray(l.position, np.float32) + off).astype(np.float32)
        m.lights.append(l)

    # scene objects are numbered: meshes, then props, then decals -> shift the old lists, then list the new objects
    nm, npr = n_mesh + len(new_meshes), n_prop + len(new_props)
    total = crop._remap_objs(blk, n_mesh, n_prop, crop._identity(n_mesh), crop._identity(n_prop), crop._identity(n_dec),
                             n_mesh_new=nm, n_prop_new=npr)
    m.meshes.extend(new_meshes)
    m.props.extend(new_props)
    m.decals.extend(new_decals)
    m.scene_obj_count = total + len(new_decals)

    for k, me in enumerate(new_meshes):
        a, b = crop.mesh_bounds(me)
        for s in _sectors_for(blk, a, b):
            s.objs.append(n_mesh + k)
    for k, p in enumerate(new_props):
        c = p.transform[3, :3].astype(np.float64)
        r = float(np.abs(np.asarray(p.corners, np.float64) - c).max()) if np.asarray(p.corners).size else 50.0
        for s in _sectors_for(blk, c - r, c + r):
            s.objs.append(nm + n_prop + k)
    for k, d in enumerate(new_decals):
        pos = np.asarray(d.position, np.float64)
        r = max(float(d.scale_x), float(d.scale_y), 1.0)
        for s in _sectors_for(blk, pos - r, pos + r):
            s.objs.append(nm + npr + n_dec + k)

    for i in boxes:
        a = np.frombuffer(blk.boxes[i], "<f4", 19).copy()
        a[12:15] += off
        new_raw = a.astype("<f4").tobytes()
        blk.boxes.append(new_raw)
        lo_b, hi_b = _box_bounds(new_raw)
        for s in _sectors_for(blk, lo_b, hi_b):
            s.boxes.append(len(blk.boxes) - 1)
    for i in hulls:
        pb = blk.polys[i]
        n = struct.unpack_from("<I", pb, 0)[0]
        q = np.frombuffer(pb, "<f4", 3 * n, 4).reshape(n, 3).copy()
        q[:, 0] += off[0]
        q[:, 1] += off[2]
        blk.polys.append(struct.pack("<I", n) + q.astype("<f4").tobytes())
        lo_h = [q[:, 0].min(), -1e9, q[:, 1].min()]
        hi_h = [q[:, 0].max(), 1e9, q[:, 1].max()]
        for s in _sectors_for(blk, lo_h, hi_h):
            s.hulls.append(len(blk.polys) - 1)
    crop.write_block(m, blk)
    return rep



# ------------------------------------------------------------------------------------------------ collision helpers
def make_box(centre, half, axes=None) -> bytes:
    """76-byte collision box: 4x4 matrix (rows = the box's axes, 3x3 ``axes`` or identity; translation row) + half extents.
    The shipped maps only turn boxes about the vertical axis."""
    a = np.zeros(19, np.float32)
    m = np.eye(4, dtype=np.float32)
    if axes is not None:
        m[:3, :3] = np.asarray(axes, np.float32)
    a[:16] = m.ravel()
    a[12:15] = centre
    a[16:19] = half
    return a.tobytes()


def add_box(m: OptMap, centre, half, axes=None) -> int:
    """Append a collision box and list it in the leaf sectors it touches. Returns its index."""
    blk = crop.read_block(m)
    raw = make_box(centre, half, axes)
    blk.boxes.append(raw)
    lo_b, hi_b = _box_bounds(raw)
    for s in _sectors_for(blk, lo_b, hi_b):
        s.boxes.append(len(blk.boxes) - 1)
    crop.write_block(m, blk)
    return len(blk.boxes) - 1


def find_boxes(m: OptMap, lo, hi) -> List[int]:
    """Boxes whose bounds lie completely inside lo..hi."""
    blk = crop.read_block(m)
    lo, hi = np.asarray(lo, np.float64), np.asarray(hi, np.float64)
    out = []
    for i, b in enumerate(blk.boxes):
        a, c = _box_bounds(b)
        if np.all(a >= lo) and np.all(c <= hi):
            out.append(i)
    return out


def cut_box(m: OptMap, idx: int, gaps_z) -> int:
    """Open gaps (list of (z0, z1) in engine z) in a long wall box so people can pass: the box keeps its index for the first
    piece, the other pieces are appended.  Returns the number of pieces."""
    blk = crop.read_block(m)
    a = np.frombuffer(blk.boxes[idx], "<f4", 19).astype(np.float64)
    R = a[:16].reshape(4, 4)[:3, :3]
    k = int(np.argmax(np.abs(R[:, 2])))                       # local axis that runs along z
    d = R[k, 2]
    if abs(d) < 0.7:
        return 1
    cz, half = a[14], a[16 + k]
    t0, t1 = -half, half
    cuts = []
    for g0, g1 in gaps_z:
        ta, tb = sorted(((g0 - cz) / d, (g1 - cz) / d))
        ta, tb = max(ta, t0), min(tb, t1)
        if ta < tb:
            cuts.append((ta, tb))
    cuts.sort()
    pieces, cur = [], t0
    for ta, tb in cuts:
        if ta - cur > 1.0:
            pieces.append((cur, ta))
        cur = max(cur, tb)
    if t1 - cur > 1.0:
        pieces.append((cur, t1))
    if len(pieces) == 1 and pieces[0] == (t0, t1):
        return 1
    new = []
    for ta, tb in pieces:
        b = a.copy()
        b[16 + k] = (tb - ta) / 2
        b[12:15] = a[12:15] + R[k] * ((ta + tb) / 2)
        new.append(b.astype("<f4").tobytes())
    if not new:                                              # the whole wall was a gap: keep a harmless sliver
        b = a.copy(); b[16 + k] = 0.5
        new = [b.astype("<f4").tobytes()]
    blk.boxes[idx] = new[0]
    for raw in new[1:]:
        blk.boxes.append(raw)
        lo_b, hi_b = _box_bounds(raw)
        for s in _sectors_for(blk, lo_b, hi_b):
            s.boxes.append(len(blk.boxes) - 1)
    # the first piece shrank: it may no longer touch every leaf that listed it - extra listings are harmless
    crop.write_block(m, blk)
    return len(new)


def add_bridge(m: OptMap, x0: float, x1: float, z: float, width: float, y_top: float, texture: str = "tablones.tex") -> dict:
    """A plank bridge along x between ``x0`` and ``x1`` centred at engine z ``z``: textured walkway + collision box."""
    from . import fill
    x0, x1 = sorted((x0, x1))
    h = width / 2
    poly = [(x0, z - h), (x1, z - h), (x1, z + h), (x0, z + h)]
    mesh = fill.make_patch(m, poly, y_top, texture, tile=128.0)
    mi = crop.add_mesh(m, mesh)
    bi = add_box(m, [(x0 + x1) / 2, y_top - 15.0, z], [(x1 - x0) / 2, 15.0, h])
    return {"mesh": mi, "box": bi}


def move_in_box(m: OptMap, lo, hi, offset, hm=None) -> dict:
    """Move the props (by their position) and the collision boxes (completely inside) of the box lo..hi by ``offset``, and
    the floor faces of the height map ``hm`` that lie inside it.  The moved things are also listed in the sector leaves of
    their new place, so the game keeps drawing them and colliding with them."""
    lo, hi, off = (np.asarray(v, np.float64) for v in (lo, hi, offset))
    blk = crop.read_block(m)
    n_mesh = len(m.meshes)
    props = []
    for k, p in enumerate(m.props):
        t = np.asarray(p.transform, np.float64)[3, :3]
        if _inside(t, lo, hi):
            p.transform = np.asarray(p.transform, np.float32).copy()
            p.transform[3, :3] = (t + off).astype(np.float32)
            props.append(k)
            nt = t + off
            for s in _sectors_for(blk, nt - 200.0, nt + 200.0):
                if n_mesh + k not in s.objs:
                    s.objs.append(n_mesh + k)
    boxes = []
    for i, raw in enumerate(blk.boxes):
        a, b = _box_bounds(raw)
        if np.all(a >= lo) and np.all(b <= hi):
            arr = np.frombuffer(raw, np.float32, 19).copy()
            arr[12:15] += off.astype(np.float32)
            blk.boxes[i] = arr.tobytes()
            boxes.append(i)
            na, nb = _box_bounds(blk.boxes[i])
            for s in _sectors_for(blk, na, nb):
                if i not in s.boxes:
                    s.boxes.append(i)
    crop.write_block(m, blk)
    faces = 0
    if hm is not None:
        from . import hmcopy
        keep, moved = [], []
        for f in hmcopy.unique_faces(hm):
            x0, z0, x1, z1 = hmcopy.face_bounds(f)
            ys = np.concatenate(f.contours)[:, 1]
            if x0 >= lo[0] and x1 <= hi[0] and z0 >= lo[2] and z1 <= hi[2] and ys.min() >= lo[1] and ys.max() <= hi[1]:
                moved.append(hmcopy.shifted(f, off[0], off[1], off[2]))
            else:
                keep.append(f)
        if moved:
            depth = hmcopy.tree_depth(hm.root)
            hm.root = hmcopy.build_tree(keep, hmcopy.box(hm.root), max(depth, 1))
            hmcopy.add_faces(hm, moved)
            faces = len(moved)
    return {"props": props, "boxes": boxes, "hm_faces": faces}


def move_boxes_in_box(m: OptMap, lo, hi, offset) -> int:
    """Move the collision boxes that lie completely inside lo..hi by ``offset`` (listed in the leaves of their new place too)."""
    lo, hi, off = (np.asarray(v, np.float64) for v in (lo, hi, offset))
    blk = crop.read_block(m)
    n = 0
    for i, raw in enumerate(blk.boxes):
        a, b = _box_bounds(raw)
        if np.all(a >= lo) and np.all(b <= hi):
            arr = np.frombuffer(raw, np.float32, 19).copy()
            arr[12:15] += off.astype(np.float32)
            blk.boxes[i] = arr.tobytes()
            na, nb = _box_bounds(blk.boxes[i])
            for s in _sectors_for(blk, na, nb):
                if i not in s.boxes:
                    s.boxes.append(i)
            n += 1
    if n:
        crop.write_block(m, blk)
    return n
