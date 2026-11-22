"""Cut a map (and its scene) to a polygon drawn on the ground plane.

Works on the engine's own structures and keeps every cross reference consistent, because the game indexes things by position:
    * scene objects = static meshes first, then props; sectors list them by that index,
    * hull polygons and collision boxes are global lists that sectors list as well.
Anything removed is dropped from every sector list and the remaining indices are renumbered.
Only VTO1 maps (what Torrente Online reads) are handled; an old VTOP map is converted first (vtoy.optconv).
Coordinates of the polygon are engine X, Z (what the HUD shows as Position)."""
from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

import numpy as np

from . import optconv
from .binutil import Writer
from .opt import OptMap, CollisionBox, VERTEX_DTYPE


# ------------------------------------------------------------------------------------------- geometry helpers
def points_in_polygon(pts_xz: np.ndarray, poly: Sequence[Sequence[float]]) -> np.ndarray:
    """Even-odd test, vectorised. pts_xz: (n, 2); poly: [(x, z), ...]."""
    pts = np.asarray(pts_xz, np.float64).reshape(-1, 2)
    inside = np.zeros(len(pts), bool)
    poly = np.asarray(poly, np.float64)
    n = len(poly)
    x, z = pts[:, 0], pts[:, 1]
    j = n - 1
    for i in range(n):
        xi, zi, xj, zj = poly[i, 0], poly[i, 1], poly[j, 0], poly[j, 1]
        cond = (zi > z) != (zj > z)
        with np.errstate(divide="ignore", invalid="ignore"):
            xint = (xj - xi) * (z - zi) / (zj - zi) + xi
        inside ^= cond & (x < xint)
        j = i
    return inside


# ------------------------------------------------------------------------------------------- sector block (VTO1)
@dataclass
class Sector:
    head: bytes                    # 76 bytes: matrix + extents
    objs: List[int]
    hulls: List[int]
    boxes: List[int]
    tail: int


@dataclass
class Block:
    polys: List[bytes] = field(default_factory=list)    # one blob per hull polygon (u32 n + n * 12 bytes)
    boxes: List[bytes] = field(default_factory=list)    # 76 bytes each
    sectors: List[Sector] = field(default_factory=list)


def read_block(m: OptMap) -> Block:
    blk = Block()
    if m.hulls_count:
        raw, pos = m.hulls_raw, 0
        for _ in range(m.hulls_count):
            k = struct.unpack_from("<I", raw, pos)[0]
            blk.polys.append(raw[pos:pos + 4 + 12 * k])
            pos += 4 + 12 * k
        for _ in range(m.declared_box_count):
            blk.boxes.append(raw[pos:pos + 76]); pos += 76
        sec = raw[pos:]
    else:
        for b in m.collision_boxes:
            w = Writer(); w.mat4(b.transform).vec3(b.half_extents); blk.boxes.append(w.bytes())
        sec = m.trailer
    pos = 0
    for _ in range(m.unused):
        head = sec[pos:pos + 76]; pos += 76
        lists = []
        for _ in range(3):
            k = struct.unpack_from("<I", sec, pos)[0]
            lists.append(list(struct.unpack_from("<%dI" % k, sec, pos + 4))); pos += 4 + 4 * k
        tail = struct.unpack_from("<I", sec, pos)[0]; pos += 4
        blk.sectors.append(Sector(head, *lists, tail))
    if pos != len(sec):
        raise ValueError("sector block of this map is not in the expected layout")
    return blk


def write_block(m: OptMap, blk: Block) -> None:
    w = Writer()
    for s in blk.sectors:
        w.raw(s.head)
        for lst in (s.objs, s.hulls, s.boxes):
            w.u32(len(lst))
            for i in lst:
                w.u32(i)
        w.u32(s.tail)
    sec = w.bytes()
    m.unused = len(blk.sectors)                  # header field = number of sector records
    if m.hulls_count or blk.polys:
        m.hulls_count = len(blk.polys)
        m.hulls_raw = b"".join(blk.polys) + b"".join(blk.boxes) + sec
        m.declared_box_count = len(blk.boxes)
        m.collision_boxes = []
        m.trailer = b""
    else:
        m.collision_boxes = [CollisionBox(np.frombuffer(b, "<f4", 16).reshape(4, 4).copy(), np.frombuffer(b, "<f4", 3, 64).copy())
                             for b in blk.boxes]
        m.trailer = sec


# ------------------------------------------------------------------------------------------- mesh clipping
def _clip_submesh(sm, poly, keep_inside: bool) -> int:
    """Drop the triangles whose centroid is on the wrong side; compact the vertices. Returns triangles kept."""
    idx = np.asarray(sm.indices).reshape(-1, 3)
    if len(idx) == 0:
        return 0
    c = sm.vertices["pos"][idx].mean(axis=1)           # (t, 3) engine coords (static meshes are stored in world space)
    ok = points_in_polygon(c[:, [0, 2]], poly)
    if not keep_inside:
        ok = ~ok
    idx = idx[ok]
    if len(idx) == 0:
        sm.indices = np.zeros(0, sm.indices.dtype)
        sm.vertices = sm.vertices[:0]
        return 0
    used, inv = np.unique(idx, return_inverse=True)
    sm.vertices = sm.vertices[used]
    sm.indices = inv.reshape(-1, 3).astype(sm.indices.dtype).reshape(-1)
    return len(idx)


@dataclass
class CropReport:
    meshes_removed: int = 0
    triangles_removed: int = 0
    props_removed: int = 0
    boxes_removed: int = 0
    hulls_removed: int = 0
    decals_removed: int = 0
    modules_removed: int = 0
    notes: List[str] = field(default_factory=list)

    def summary(self) -> str:
        return (f"removed: {self.meshes_removed} meshes, {self.triangles_removed} triangles, {self.props_removed} props, "
                f"{self.boxes_removed} collision boxes, {self.hulls_removed} hulls, {self.decals_removed} decals, "
                f"{self.modules_removed} modules")


def crop_map(m: OptMap, poly, keep_inside: bool = True) -> CropReport:
    """Cut ``m`` in place. ``poly`` = [(x, z), ...] in engine coordinates."""
    rep = CropReport()
    if len(poly) < 3:
        raise ValueError("the outline needs at least 3 points")
    if m.old_format:
        optconv.convert(m)
        rep.notes.append("the map was converted from the old format (VTOP) first")
    blk = read_block(m)

    def inside(xz):
        r = points_in_polygon(np.asarray(xz, np.float64).reshape(-1, 2), poly)
        return r if keep_inside else ~r

    # props first: a mesh that a surviving prop still uses must stay as it is
    prop_keep = []
    for p in m.props:
        prop_keep.append(bool(inside(np.asarray(p.transform, np.float64)[3, [0, 2]][None])[0]))
    used_by_kept = {p.mesh_index for p, k in zip(m.props, prop_keep) if k}
    mesh_keep = []
    for i, me in enumerate(m.meshes):
        if i in used_by_kept:
            mesh_keep.append(True)
            continue
        lod0 = 0
        for li, lod in enumerate(me.lods):
            for part in lod.parts:
                for sm in list(part.submeshes):
                    before = len(sm.indices) // 3
                    n = _clip_submesh(sm, poly, keep_inside)
                    rep.triangles_removed += before - n
                    if li == 0:
                        lod0 += n
                part.submeshes = [x for x in part.submeshes if len(x.indices)]
            lod.parts = [x for x in lod.parts if x.submeshes]
        total = lod0
        if total:
            me.lods = [lod for lod in me.lods if lod.parts]
        mesh_keep.append(total > 0)
    # the engine wants every mesh to keep at least one drawable sub-mesh in LOD 0: drop meshes that lost everything
    mesh_new = {}
    k = 0
    for i, keep in enumerate(mesh_keep):
        if keep:
            mesh_new[i] = k; k += 1
    # props that reference a removed mesh go away too
    prop_keep = [kp and p.mesh_index in mesh_new for p, kp in zip(m.props, prop_keep)]
    rep.meshes_removed = len(m.meshes) - len(mesh_new)
    rep.props_removed = len(m.props) - sum(prop_keep)
    old_meshes, old_props = m.meshes, m.props
    m.meshes = [me for i, me in enumerate(old_meshes) if i in mesh_new]
    m.props = [p for p, kp in zip(old_props, prop_keep) if kp]
    for p in m.props:
        p.mesh_index = mesh_new[p.mesh_index]
    # decals are scene objects too (numbered after the props)
    if m.decals:
        dkeep = inside(np.array([np.asarray(d.position, np.float64)[[0, 2]] for d in m.decals]))
    else:
        dkeep = np.zeros(0, bool)
    decal_new, k = {}, 0
    for i, kp in enumerate(dkeep):
        if kp:
            decal_new[i] = k; k += 1
    prop_new, k = {}, 0
    for i, kp in enumerate(prop_keep):
        if kp:
            prop_new[i] = k; k += 1
    m.scene_obj_count = _remap_objs(blk, len(old_meshes), len(old_props), mesh_new, prop_new, decal_new)
    # boxes / hulls
    if blk.boxes:
        centres = np.array([np.frombuffer(b, "<f4", 3, 48) for b in blk.boxes], np.float64)
        bk = inside(centres[:, [0, 2]])
    else:
        bk = np.zeros(0, bool)
    box_new, k = {}, 0
    for i, keep in enumerate(bk):
        if keep:
            box_new[i] = k; k += 1
    rep.boxes_removed = len(blk.boxes) - len(box_new)
    blk.boxes = [b for i, b in enumerate(blk.boxes) if i in box_new]
    hull_keep = []
    for pb in blk.polys:
        n = struct.unpack_from("<I", pb, 0)[0]
        pts = np.frombuffer(pb, "<f4", 3 * n, 4).reshape(n, 3)[:, :2] if n else np.zeros((0, 2))
        hull_keep.append(bool(inside(pts.mean(0)[None])[0]) if n else False)
    hull_new, k = {}, 0
    for i, keep in enumerate(hull_keep):
        if keep:
            hull_new[i] = k; k += 1
    rep.hulls_removed = len(blk.polys) - len(hull_new)
    blk.polys = [p for i, p in enumerate(blk.polys) if i in hull_new]
    for s in blk.sectors:
        s.hulls = [hull_new[i] for i in s.hulls if i in hull_new]
        s.boxes = [box_new[i] for i in s.boxes if i in box_new]
    if not blk.polys:
        m.hulls_count = 0
    write_block(m, blk)
    if not m.hulls_count and blk.polys == []:
        m.hulls_raw = b""
    # decals
    if m.decals:
        rep.decals_removed = int((~dkeep).sum())
        m.decals = [d for d, kp in zip(m.decals, dkeep) if kp]
    return rep


def remove_props(m: OptMap, drop) -> int:
    """Delete prop instances (indices into ``m.props``) keeping the sector lists consistent. Returns how many were removed."""
    drop = {i for i in drop if 0 <= i < len(m.props)}
    if not drop:
        return 0
    if m.old_format:
        optconv.convert(m)
    blk = read_block(m)
    n_mesh, n_prop = len(m.meshes), len(m.props)
    prop_new, k = {}, 0
    for i in range(n_prop):
        if i not in drop:
            prop_new[i] = k; k += 1
    m.props = [p for i, p in enumerate(m.props) if i not in drop]
    m.scene_obj_count = _remap_objs(blk, n_mesh, n_prop, _identity(n_mesh), prop_new, _identity(len(m.decals)))
    write_block(m, blk)
    return len(drop)


# ------------------------------------------------------------------------------------------- editing helpers
def _remap_objs(blk: Block, n_mesh_old: int, n_prop_old: int, mesh_map: dict, prop_map: dict, decal_map: dict,
                n_mesh_new: int = None, n_prop_new: int = None) -> int:
    """Rewrite every sector's object list. Scene objects are numbered meshes, then props, then decals (Online maps list the
    decals in the sectors too, and ``scene_obj_count`` = meshes + props + decals). The maps are old index -> new index;
    missing keys mean "removed". Returns the new ``scene_obj_count``."""
    nm = len(mesh_map) if n_mesh_new is None else n_mesh_new
    npr = len(prop_map) if n_prop_new is None else n_prop_new
    base_old = n_mesh_old + n_prop_old
    new = {}
    for i, j in mesh_map.items():
        new[i] = j
    for i, j in prop_map.items():
        new[n_mesh_old + i] = nm + j
    for i, j in decal_map.items():
        new[base_old + i] = nm + npr + j
    for s in blk.sectors:
        s.objs = [new[i] for i in s.objs if i in new]
    return nm + npr + len(decal_map)


def _identity(n: int) -> dict:
    return {i: i for i in range(n)}


def _overlapping(blk: Block, lo, hi, margin: float = 50.0):
    lo, hi = np.asarray(lo, np.float64), np.asarray(hi, np.float64)
    out = []
    for s in blk.sectors:
        mat = np.frombuffer(s.head, "<f4", 16).reshape(4, 4)
        ext = np.frombuffer(s.head, "<f4", 3, 64).astype(np.float64)
        c = mat[3, :3].astype(np.float64)
        half = np.maximum(np.abs(ext), np.abs(np.diag(mat[:3, :3])).astype(np.float64))
        if np.all(lo - margin <= c + half) and np.all(hi + margin >= c - half):
            out.append(s)
    leaves = [s for s in out if s.tail == 0]          # only the leaves of the sector tree hold lists (inner nodes are empty
    return leaves or out                                # in every shipped map)


def mesh_bounds(me) -> Tuple[np.ndarray, np.ndarray]:
    lo, hi = np.full(3, np.inf), np.full(3, -np.inf)
    for sm in me.render_submeshes():
        if len(sm.vertices):
            p = sm.vertices["pos"]
            lo, hi = np.minimum(lo, p.min(0)), np.maximum(hi, p.max(0))
    if not np.isfinite(lo).all():
        c = np.asarray(me.corners, np.float64)
        lo, hi = c.min(0), c.max(0)
    return lo.astype(np.float64), hi.astype(np.float64)


def remove_collision_in_box(m: OptMap, lo, hi, margin: float = 20.0, shrink: float = 0.0) -> Tuple[int, int]:
    """Drop the collision boxes whose centre and the hull polygons whose centroid lie inside the AABB [lo, hi].
    ``shrink`` > 0 keeps the things that are at the very edge. Returns (boxes, hulls) removed."""
    if m.old_format:
        optconv.convert(m)
    blk = read_block(m)
    lo = np.asarray(lo, np.float64) - margin + shrink
    hi = np.asarray(hi, np.float64) + margin - shrink

    def test(c, hull=False):
        if hull:                                           # hull = 2D footprint (x, z): no height to compare
            return np.all((c[:, [0, 2]] >= lo[[0, 2]]) & (c[:, [0, 2]] <= hi[[0, 2]]), axis=1)
        return np.all((c >= lo) & (c <= hi), axis=1)

    def vtest(xz):
        return np.all((xz >= lo[[0, 2]]) & (xz <= hi[[0, 2]]), axis=1)
    return _drop_collision(m, blk, test, vtest)


def remove_collision_in_polygon(m: OptMap, poly, y_range=None, outside: bool = False) -> Tuple[int, int]:
    if m.old_format:
        optconv.convert(m)
    blk = read_block(m)

    def test(c, hull=False):
        ok = points_in_polygon(c[:, [0, 2]], poly)
        if outside:
            ok = ~ok
        if y_range is not None and not hull:
            ok &= (c[:, 1] >= y_range[0]) & (c[:, 1] <= y_range[1])
        return ok

    def vtest(xz):
        ok = points_in_polygon(xz, poly)
        return ~ok if outside else ok
    return _drop_collision(m, blk, test, vtest)


def _drop_collision(m: OptMap, blk: Block, test, vtest=None) -> Tuple[int, int]:
    """``vtest(xz)`` (optional) marks hull vertices to cut out of the hulls that survive the centroid test and have more than
    4 points: a big hull (e.g. the walls of a whole maze) has its centroid far away from the part that was deleted."""
    if blk.boxes:
        cen = np.array([np.frombuffer(b, "<f4", 3, 48) for b in blk.boxes], np.float64)
        drop_b = test(cen)
    else:
        drop_b = np.zeros(0, bool)
    drop_h = []
    for pb in blk.polys:
        n = struct.unpack_from("<I", pb, 0)[0]
        # a hull polygon is stored as (x, z, tag): its centroid in (x, y, z) order has no height (y = 0, ignored by the tests)
        pts = np.frombuffer(pb, "<f4", 3 * n, 4).reshape(n, 3).astype(np.float64) if n else np.zeros((0, 3))
        cen_h = np.array([[pts[:, 0].mean(), 0.0, pts[:, 1].mean()]]) if n else None
        drop_h.append(bool(test(cen_h, True)[0]) if n else False)
    trimmed = 0
    if vtest is not None:
        for hi, pb in enumerate(blk.polys):
            n = struct.unpack_from("<I", pb, 0)[0]
            if drop_h[hi] or n <= 4:
                continue
            q = np.frombuffer(pb, "<f4", 3 * n, 4).reshape(n, 3)
            cut = np.asarray(vtest(q[:, :2].astype(np.float64)), bool)
            if not cut.any():
                continue
            keep = q[~cut]
            if len(keep) < 3:
                drop_h[hi] = True
            else:
                blk.polys[hi] = struct.pack("<I", len(keep)) + np.ascontiguousarray(keep, "<f4").tobytes() + bytes(pb[4 + 12 * n:])
                trimmed += int(cut.sum())
    bn, hn, k = {}, {}, 0
    for i, d in enumerate(drop_b):
        if not d:
            bn[i] = k; k += 1
    k = 0
    for i, d in enumerate(drop_h):
        if not d:
            hn[i] = k; k += 1
    nb, nh = len(blk.boxes) - len(bn), len(blk.polys) - len(hn)
    if nb or nh or trimmed:
        blk.boxes = [b for i, b in enumerate(blk.boxes) if i in bn]
        blk.polys = [p for i, p in enumerate(blk.polys) if i in hn]
        for s in blk.sectors:
            s.boxes = [bn[i] for i in s.boxes if i in bn]
            s.hulls = [hn[i] for i in s.hulls if i in hn]
        was_hulls = bool(m.hulls_count)
        write_block(m, blk)
        if was_hulls and not blk.polys:
            m.hulls_count = 0
    return nb, nh


def remove_meshes(m: OptMap, drop, collision: bool = True) -> Tuple[int, int, int]:
    """Delete static meshes (indices into ``m.meshes``) and the props that use them; also the collision that sits inside
    their bounds when ``collision`` (the game keeps collision apart from the drawing).
    Returns (meshes, props, collision pieces) removed."""
    drop = {i for i in drop if 0 <= i < len(m.meshes)}
    if not drop:
        return 0, 0, 0
    if m.old_format:
        optconv.convert(m)
    boxes = [mesh_bounds(m.meshes[i]) for i in drop]
    blk = read_block(m)
    n_mesh, n_prop = len(m.meshes), len(m.props)
    mesh_new, k = {}, 0
    for i in range(n_mesh):
        if i not in drop:
            mesh_new[i] = k; k += 1
    prop_drop = {i for i, p in enumerate(m.props) if p.mesh_index in drop}
    prop_new, k = {}, 0
    for i in range(n_prop):
        if i not in prop_drop:
            prop_new[i] = k; k += 1
    m.meshes = [me for i, me in enumerate(m.meshes) if i in mesh_new]
    m.props = [p for i, p in enumerate(m.props) if i in prop_new]
    for p in m.props:
        p.mesh_index = mesh_new[p.mesh_index]
    m.scene_obj_count = _remap_objs(blk, n_mesh, n_prop, mesh_new, prop_new, _identity(len(m.decals)))
    write_block(m, blk)
    removed = 0
    if collision:
        for lo, hi in boxes:                                  # collision whose centre sits inside the removed mesh
            b, h = remove_collision_in_box(m, lo, hi, margin=1.0)
            removed += b + h
        removed += remove_orphans_in(m, [(lo - 25.0, hi + 25.0) for lo, hi in boxes])   # leftovers nothing explains any more
    return len(drop), len(prop_drop), removed


def add_mesh(m: OptMap, mesh, margin: float = 50.0) -> int:
    """Append a static mesh (vertices in world space) and list it in every sector it overlaps. Returns its index."""
    if m.old_format:
        optconv.convert(m)
    blk = read_block(m)
    n_mesh, n_prop, n_dec = len(m.meshes), len(m.props), len(m.decals)
    lo, hi = mesh_bounds(mesh)
    m.meshes.append(mesh)
    m.scene_obj_count = _remap_objs(blk, n_mesh, n_prop, _identity(n_mesh), _identity(n_prop), _identity(n_dec),
                                    n_mesh_new=n_mesh + 1, n_prop_new=n_prop)
    secs = _overlapping(blk, lo, hi, margin) or blk.sectors   # layout not understood: list it everywhere
    for s in secs:
        s.objs.append(n_mesh)
    write_block(m, blk)
    return n_mesh


def add_prop(m: OptMap, prop, lo, hi, margin: float = 50.0) -> int:
    """Append a prop (an instance of an existing mesh) and list it in the sectors it overlaps. Returns its index."""
    if m.old_format:
        optconv.convert(m)
    blk = read_block(m)
    n_mesh, n_prop, n_dec = len(m.meshes), len(m.props), len(m.decals)
    m.props.append(prop)
    m.scene_obj_count = _remap_objs(blk, n_mesh, n_prop, _identity(n_mesh), _identity(n_prop), _identity(n_dec),
                                    n_mesh_new=n_mesh, n_prop_new=n_prop + 1)
    for s in _overlapping(blk, lo, hi, margin) or blk.sectors:
        s.objs.append(n_mesh + n_prop)
    write_block(m, blk)
    return n_prop


def add_decal(m: OptMap, decal, margin: float = 50.0) -> None:
    """Append a decal and list it in the sectors around it (decals are scene objects: Online draws them through the sectors)."""
    if m.old_format:
        optconv.convert(m)
    blk = read_block(m)
    n_mesh, n_prop, n_dec = len(m.meshes), len(m.props), len(m.decals)
    m.decals.append(decal)
    ids = _identity(n_dec)
    m.scene_obj_count = _remap_objs(blk, n_mesh, n_prop, _identity(n_mesh), _identity(n_prop), ids)
    pos = np.asarray(decal.position, np.float64)
    r = max(float(decal.scale_x), float(decal.scale_y), 1.0)
    for s in _overlapping(blk, pos - r, pos + r, margin) or blk.sectors:
        s.objs.append(n_mesh + n_prop + n_dec)
    m.scene_obj_count = n_mesh + n_prop + n_dec + 1
    write_block(m, blk)


def remove_decal(m: OptMap, decal) -> bool:
    i = next((k for k, d in enumerate(m.decals) if d is decal), None)
    if i is None:
        return False
    if m.old_format:
        optconv.convert(m)
    blk = read_block(m)
    n_mesh, n_prop, n_dec = len(m.meshes), len(m.props), len(m.decals)
    dmap = {k: (k if k < i else k - 1) for k in range(n_dec) if k != i}
    m.decals.pop(i)
    m.scene_obj_count = _remap_objs(blk, n_mesh, n_prop, _identity(n_mesh), _identity(n_prop), dmap)
    write_block(m, blk)
    return True


# ------------------------------------------------------------------------------------------------ orphan collision
_OFF = 1 << 20


def _pack(c: np.ndarray) -> np.ndarray:
    c = np.asarray(c, np.int64) + _OFF
    return (c[..., 0] << 42) | (c[..., 1] << 21) | c[..., 2]


def _surface_cells(m: OptMap, cell: float) -> np.ndarray:
    """Sorted packed grid cells (engine space) touched by the triangles of the static meshes and props (memory-lean)."""
    parts = []

    def flush(buf):
        if buf:
            parts.append(np.unique(np.concatenate(buf)))
            buf.clear()

    buf, held = [], [0]

    def add(sm, matrix=None):
        if len(sm.indices) < 3 or len(sm.vertices) == 0:
            return
        p = sm.vertices["pos"].astype(np.float64)
        if matrix is not None:
            p = (np.c_[p, np.ones(len(p))] @ matrix)[:, :3]
        tri = p[np.asarray(sm.indices, np.int64)[: len(sm.indices) // 3 * 3].reshape(-1, 3)]
        edge = np.max(np.linalg.norm(tri - np.roll(tri, 1, axis=1), axis=2), axis=1)
        n = np.clip(np.ceil(edge / cell).astype(int), 1, 40)
        for k in np.unique(n):
            t_all = tri[n == k]
            i, j = np.meshgrid(np.arange(k + 1), np.arange(k + 1), indexing="ij")
            ok = (i + j) <= k
            a_, b_ = (i[ok] / k)[None, :, None], (j[ok] / k)[None, :, None]
            per = max(1, 200000 // max(1, a_.shape[1]))
            for st in range(0, len(t_all), per):
                t = t_all[st:st + per]
                pts = t[:, None, 0] * (1 - a_ - b_) + t[:, None, 1] * a_ + t[:, None, 2] * b_
                buf.append(np.unique(_pack(np.floor(pts.reshape(-1, 3) / cell))))
                held[0] += len(buf[-1])
                if held[0] > 2_000_000:
                    flush(buf); held[0] = 0

    for me in m.meshes:
        for sm in me.render_submeshes():
            add(sm)
    for pr in m.props:
        if not 0 <= pr.mesh_index < len(m.meshes):
            continue
        me = m.meshes[pr.mesh_index]
        try:
            mat = np.linalg.inv(me.world_transform.astype(np.float64)) @ pr.transform.astype(np.float64)
        except np.linalg.LinAlgError:
            continue
        for sm in me.render_submeshes():
            add(sm, mat)
    flush(buf)
    return np.unique(np.concatenate(parts)) if parts else np.zeros(0, np.int64)


def orphan_collision(m: OptMap, margin: float = 10.0, cell: float = 50.0):
    """Collision boxes with no visible geometry within ``margin`` units: (box indices, hull indices = always empty).
    Invisible walls are *meant* to be like that, so the editor only offers it as a manual clean-up."""
    if m.old_format:
        optconv.convert(m)
    blk = read_block(m)
    cells = _surface_cells(m, cell)
    ob, oh = [], []
    if not len(cells):
        return list(range(len(blk.boxes))), oh
    for i, b in enumerate(blk.boxes):
        a = np.frombuffer(b, "<f4", 19).astype(np.float64)
        c, h = a[12:15], np.abs(a[16:19])
        ext = np.abs(a[:12].reshape(4, 3)[:3].T) @ h
        lo = np.floor((c - ext - margin) / cell).astype(np.int64)
        hi = np.floor((c + ext + margin) / cell).astype(np.int64)
        g = np.stack(np.meshgrid(*[np.arange(lo[k], hi[k] + 1) for k in range(3)], indexing="ij"), -1).reshape(-1, 3)
        key = _pack(g)
        pos = np.searchsorted(cells, key)
        pos[pos >= len(cells)] = len(cells) - 1
        if not np.any(cells[pos] == key):
            ob.append(i)
    return ob, oh          # hulls are not judged: their relation to the drawing is unknown


def remove_collision_indices(m: OptMap, box_idx, hull_idx=()) -> Tuple[int, int]:
    """Delete collision boxes / hulls by index (sector lists are renumbered)."""
    blk = read_block(m)
    bset, hset = set(box_idx), set(hull_idx)
    drop_b = np.array([i in bset for i in range(len(blk.boxes))], bool)
    hull_no = iter(range(len(blk.polys)))
    first = [True]

    def test(c, hull=False):
        if first[0] and not hull:      # _drop_collision asks about all boxes first, then one hull at a time
            first[0] = False
            return drop_b
        return np.array([next(hull_no) in hset])
    return _drop_collision(m, blk, test)


def remove_orphans_in(m: OptMap, bounds, pad: float = 5.0) -> int:
    """After deleting drawing, drop the collision boxes inside ``bounds`` [(lo, hi)...] that no remaining geometry explains.
    Boxes that still touch other geometry (the floor, a neighbouring wall) stay."""
    ob, _ = orphan_collision(m)
    if not ob:
        return 0
    blk = read_block(m)
    pick = []
    for i in ob:
        c = np.frombuffer(blk.boxes[i], "<f4", 3, 48).astype(np.float64)
        if any(np.all(c >= np.asarray(lo) - pad) and np.all(c <= np.asarray(hi) + pad) for lo, hi in bounds):
            pick.append(i)
    if not pick:
        return 0
    return sum(remove_collision_indices(m, pick))


# ------------------------------------------------------------------------------------------------ weather: rain / moon
RAIN_TEXTURE = "gota_lluvia"


def _stem_l(t) -> str:
    return str(t).replace("\\", "/").split("/")[-1].rsplit(".", 1)[0].lower()


def rain_mesh_index(m: OptMap) -> int:
    """Index of the mesh Online's rainy maps carry (24 quads textured gota_lluvia / gota_salpica / GOTA_AGUA_01), or -1."""
    for i, me in enumerate(m.meshes):
        if any(_stem_l(t) == RAIN_TEXTURE for mt in me.materials for t in mt.textures):
            return i
    return -1


def add_rain(m: OptMap, src: OptMap) -> bool:
    """Copy the rain mesh of ``src`` (e.g. Marbella) and its own sector into ``m``. False if ``m`` already has rain."""
    import copy
    if rain_mesh_index(m) >= 0:
        return False
    si = rain_mesh_index(src)
    if si < 0:
        raise ValueError("the source map has no rain mesh")
    if m.old_format:
        optconv.convert(m)
    sblk = read_block(src)
    ssec = next((s for s in sblk.sectors if si in s.objs), None)
    if ssec is None:
        raise ValueError("the rain mesh of the source map is not in any sector")
    blk = read_block(m)
    n_mesh, n_prop, n_dec = len(m.meshes), len(m.props), len(m.decals)
    m.meshes.append(copy.deepcopy(src.meshes[si]))
    m.scene_obj_count = _remap_objs(blk, n_mesh, n_prop, _identity(n_mesh), _identity(n_prop), _identity(n_dec),
                                    n_mesh_new=n_mesh + 1, n_prop_new=n_prop)
    blk.sectors.append(Sector(ssec.head, [n_mesh], [], [], ssec.tail))     # same far-away sector as the original map
    write_block(m, blk)
    return True


def remove_rain(m: OptMap) -> bool:
    i = rain_mesh_index(m)
    if i < 0:
        return False
    blk = read_block(m)
    own = [k for k, sc in enumerate(blk.sectors) if sc.objs == [i] and not sc.hulls and not sc.boxes]   # its own sector
    remove_meshes(m, {i}, collision=False)
    if own:
        blk = read_block(m)
        blk.sectors = [sc for k, sc in enumerate(blk.sectors) if k not in set(own)]
        write_block(m, blk)
    return True


def moon_decal(m: OptMap):
    return next((d for d in m.decals if str(d.name).lower().rsplit(".", 1)[0] == "luna"), None)
