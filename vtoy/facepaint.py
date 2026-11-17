"""Change the texture of some faces of a map mesh (not of the whole texture file, not of every map that shares it).

A mesh is a list of submeshes, each drawn with one material (= one texture).  Painting moves the chosen triangles to a new
submesh with a copy of the material that names the other texture; the vertices (and their texture coordinates) stay as
they are unless ``tile`` asks for a flat projection.

    hit = pick(opt, origin, direction)                 the triangle under a ray (engine coordinates)
    tris = select(opt, hit, 'triangle' | 'flat' | 'material')
    paint(opt, hit, tris, 'ladrillo.tex')

Props are copies of one mesh: painting a prop paints the mesh, so every copy of it changes (``users`` in the result)."""
from __future__ import annotations

import copy
from typing import Dict, List, Optional

import numpy as np

from . import crop

MODES = ("triangle", "flat", "material")


def _tris(sm) -> np.ndarray:
    idx = np.asarray(sm.indices, np.int64)
    return idx[: len(idx) // 3 * 3].reshape(-1, 3)


def _ray_tris(o, d, p):
    """Distance along the ray to each triangle of p (n, 3, 3); inf where it misses (both sides count)."""
    e1, e2 = p[:, 1] - p[:, 0], p[:, 2] - p[:, 0]
    h = np.cross(d, e2)
    a = (e1 * h).sum(1)
    ok = np.abs(a) > 1e-12
    f = np.where(ok, 1.0 / np.where(ok, a, 1.0), 0.0)
    s = o - p[:, 0]
    u = f * (s * h).sum(1)
    q = np.cross(s, e1)
    v = f * (q @ d)
    t = f * (e2 * q).sum(1)
    hit = ok & (u >= -1e-6) & (v >= -1e-6) & (u + v <= 1 + 1e-6) & (t > 1e-4)
    return np.where(hit, t, np.inf)


def _ray_box(o, d, lo, hi) -> bool:
    with np.errstate(divide="ignore", invalid="ignore"):
        inv = 1.0 / np.where(np.abs(d) < 1e-12, 1e-12, d)
    t0, t1 = (lo - o) * inv, (hi - o) * inv
    tn, tf = np.minimum(t0, t1).max(), np.maximum(t0, t1).min()
    return tf >= max(tn, 0.0)


def pick(opt, origin, direction) -> Optional[dict]:
    """The nearest triangle of a static mesh / prop hit by the ray (engine coordinates), or None.
    {'kind', 'index', 'mesh', 'part', 'sub', 'tri', 't', 'point', 'material', 'texture'}"""
    o = np.asarray(origin, np.float64)
    d = np.asarray(direction, np.float64)
    d = d / max(np.linalg.norm(d), 1e-12)
    best = None
    targets = [("mesh", i, i, None) for i in range(len(opt.meshes))]
    for i, pr in enumerate(opt.props):
        if 0 <= pr.mesh_index < len(opt.meshes):
            me = opt.meshes[pr.mesh_index]
            try:
                M = np.linalg.inv(me.world_transform.astype(np.float64)) @ pr.transform.astype(np.float64)
            except np.linalg.LinAlgError:
                continue
            targets.append(("prop", i, pr.mesh_index, M))
    for kind, index, mi, M in targets:
        me = opt.meshes[mi]
        if not me.lods:
            continue
        if M is None:
            lo, hi = crop.mesh_bounds(me)
            if not _ray_box(o, d, lo - 1.0, hi + 1.0):
                continue
            ro, rd = o, d
        else:                                           # bring the ray into the mesh's own space
            try:
                Mi = np.linalg.inv(M)
            except np.linalg.LinAlgError:
                continue
            ro = o @ Mi[:3, :3] + Mi[3, :3]
            rd = d @ Mi[:3, :3]
            lo, hi = crop.mesh_bounds(me)
            if not _ray_box(ro, rd, lo - 1.0, hi + 1.0):
                continue
        for pi, part in enumerate(me.lods[0].parts):
            for si, sm in enumerate(part.submeshes):
                if sm.vertices is None or len(sm.vertices) == 0 or len(sm.indices) < 3:
                    continue
                tr = _tris(sm)
                tr = np.where((tr < len(sm.vertices)).all(1)[:, None], tr, 0)
                t = _ray_tris(ro, rd, sm.vertices["pos"].astype(np.float64)[tr])
                k = int(np.argmin(t))
                if not np.isfinite(t[k]):
                    continue
                # t is measured in the ray's own space; props may be scaled, so compare world distances
                pt = ro + rd * t[k]
                wp = pt if M is None else pt @ M[:3, :3] + M[3, :3]
                dist = float(np.linalg.norm(wp - o))
                if best is None or dist < best["t"]:
                    mat = me.materials[sm.material_index] if sm.material_index < len(me.materials) else None
                    best = {"kind": kind, "index": index, "mesh": mi, "part": pi, "sub": si, "tri": k, "t": dist,
                            "point": wp, "material": sm.material_index, "texture": mat.diffuse if mat else ""}
    return best


def select(opt, hit: dict, mode: str = "flat", angle: float = 8.0) -> np.ndarray:
    """Triangle numbers (of the hit submesh) to paint: the one hit, the flat area around it (triangles joined by an edge
    whose normals differ less than ``angle`` degrees from the one hit) or the whole submesh."""
    sm = opt.meshes[hit["mesh"]].lods[0].parts[hit["part"]].submeshes[hit["sub"]]
    tr = _tris(sm)
    if mode == "triangle":
        return np.array([hit["tri"]], np.int64)
    if mode == "material":
        return np.arange(len(tr), dtype=np.int64)
    p = sm.vertices["pos"].astype(np.float64)
    n = np.cross(p[tr[:, 1]] - p[tr[:, 0]], p[tr[:, 2]] - p[tr[:, 0]])
    n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
    seed = int(hit["tri"])
    flat = (n @ n[seed]) >= np.cos(np.radians(angle))
    key = {}
    for i, v in enumerate(np.round(p, 1)):
        key[i] = tuple(v)
    edges: Dict[tuple, List[int]] = {}
    for t in np.nonzero(flat)[0]:
        ks = [key[int(v)] for v in tr[t]]
        for a in range(3):
            edges.setdefault(tuple(sorted((ks[a], ks[(a + 1) % 3]))), []).append(int(t))
    adj: Dict[int, set] = {}
    for lst in edges.values():
        for a in lst:
            adj.setdefault(a, set()).update(lst)
    seen, todo = {seed}, [seed]
    while todo:
        t = todo.pop()
        for u in adj.get(t, ()):
            if u not in seen:
                seen.add(u)
                todo.append(u)
    return np.array(sorted(seen), np.int64)


def _was_cumulative(part) -> bool:
    acc = 0
    for sm in part.submeshes:
        if sm.unk != acc:
            return False
        acc += len(sm.indices)
    return True


def _renumber(part) -> None:
    acc = 0
    for sm in part.submeshes:
        sm.unk = acc
        acc += len(sm.indices)


def _material_for(me, old_index: int, texture: str) -> int:
    if not texture.lower().endswith(".tex"):
        texture += ".tex"
    old = me.materials[old_index]
    for i, m in enumerate(me.materials):
        if (m.textures and str(m.textures[0]).rstrip("\0").lower() == texture.lower() and m.two_sided == old.two_sided
                and len(m.textures) == len(old.textures) and [str(t).lower() for t in m.textures[1:]] == [str(t).lower() for t in old.textures[1:]]):
            return i
    new = copy.deepcopy(old)
    new.textures = [texture] + list(old.textures[1:])
    new.name = texture.rsplit(".", 1)[0][:60]
    me.materials.append(new)
    return len(me.materials) - 1


def _split(part, si: int, tri_ids: np.ndarray, new_material: int, tile: float = 0.0) -> int:
    """Move triangles ``tri_ids`` of submesh ``si`` to a new submesh (inserted right after it). Returns how many moved."""
    sm = part.submeshes[si]
    tr = _tris(sm)
    mask = np.zeros(len(tr), bool)
    mask[tri_ids] = True
    if not mask.any():
        return 0
    cumulative = _was_cumulative(part)

    def compact(tris):
        used = np.unique(tris)
        remap = np.zeros(len(sm.vertices), np.int64)
        remap[used] = np.arange(len(used))
        return sm.vertices[used].copy(), remap[tris].astype(np.uint16).reshape(-1)

    if mask.all():
        sm.material_index = new_material
        new = sm
    else:
        nv, ni = compact(tr[mask])
        kv, ki = compact(tr[~mask])
        new = type(sm)(stride_type=sm.stride_type, material_id=0, material_index=new_material, unk=0, vertices=nv, indices=ni,
                       remap=None)
        sm.vertices, sm.indices = kv, ki
        part.submeshes.insert(si + 1, new)
    if tile > 0 and len(new.vertices):
        p = new.vertices["pos"].astype(np.float64)
        n = new.vertices["nrm"].astype(np.float64).sum(0)
        ax = int(np.argmax(np.abs(n)))                        # project along the axis the faces look at
        a, b = [(2, 1), (0, 2), (0, 1)][ax]
        uv = new.vertices["uv"].copy()
        uv[:, 0], uv[:, 1] = p[:, a] / tile, -p[:, b] / tile if ax != 1 else p[:, b] / tile
        new.vertices["uv"] = uv
    if cumulative:
        _renumber(part)
    return int(mask.sum())


def _on_triangles(points: np.ndarray, tris: np.ndarray, tol: float = 2.0) -> np.ndarray:
    """True for the points that lie on one of the triangles (n, 3, 3)."""
    out = np.zeros(len(points), bool)
    if not len(points) or not len(tris):
        return out
    a = tris[:, 0]
    e1, e2 = tris[:, 1] - a, tris[:, 2] - a
    n = np.cross(e1, e2)
    ln = np.maximum(np.linalg.norm(n, axis=1), 1e-12)
    n = n / ln[:, None]
    d00, d01, d11 = (e1 * e1).sum(1), (e1 * e2).sum(1), (e2 * e2).sum(1)
    den = np.where(np.abs(d00 * d11 - d01 * d01) < 1e-12, 1e-12, d00 * d11 - d01 * d01)
    for s in range(0, len(points), 2048):
        P = points[s:s + 2048]
        w = P[:, None, :] - a[None]
        dist = np.abs((w * n[None]).sum(2))
        d20, d21 = (w * e1[None]).sum(2), (w * e2[None]).sum(2)
        v = (d11 * d20 - d01 * d21) / den
        u = (d00 * d21 - d01 * d20) / den
        m = (dist <= tol) & (v >= -0.02) & (u >= -0.02) & (u + v <= 1.02)
        out[s:s + 2048] = m.any(1)
    return out


def paint(opt, hit: dict, tri_ids, texture: str, tile: float = 0.0) -> dict:
    """Give triangles ``tri_ids`` of the hit submesh the texture ``texture``.  The farther levels of detail of the mesh get
    the same change on the triangles that lie on the painted ones.
    Returns {'triangles', 'far_triangles', 'material', 'users'} (users = props that show this mesh)."""
    me = opt.meshes[hit["mesh"]]
    part = me.lods[0].parts[hit["part"]]
    sm = part.submeshes[hit["sub"]]
    old_mat = sm.material_index
    if old_mat >= len(me.materials):
        raise ValueError("this submesh has no material")
    tri_ids = np.asarray(tri_ids, np.int64)
    tr = _tris(sm)
    tri_ids = tri_ids[(tri_ids >= 0) & (tri_ids < len(tr))]
    if not len(tri_ids):
        raise ValueError("nothing to paint")
    painted = sm.vertices["pos"].astype(np.float64)[tr[tri_ids]]
    new_mat = _material_for(me, old_mat, texture)
    n = 0 if (new_mat == old_mat and tile <= 0) else _split(part, hit["sub"], tri_ids, new_mat, tile)
    far = 0
    if new_mat != old_mat:
        for lod in me.lods[1:]:
            for p2 in lod.parts:
                k = 0
                while k < len(p2.submeshes):
                    s2 = p2.submeshes[k]
                    if s2.material_index == old_mat and s2.vertices is not None and len(s2.indices) >= 3:
                        t2 = _tris(s2)
                        t2ok = (t2 < len(s2.vertices)).all(1)
                        cen = s2.vertices["pos"].astype(np.float64)[np.where(t2ok[:, None], t2, 0)].mean(1)
                        ids = np.nonzero(_on_triangles(cen, painted) & t2ok)[0]
                        if len(ids):
                            far += _split(p2, k, ids, new_mat, tile)
                            if len(ids) < len(t2):
                                k += 1                   # skip the submesh just inserted
                    k += 1
    users = sum(1 for pr in opt.props if pr.mesh_index == hit["mesh"])
    return {"triangles": n, "far_triangles": far, "material": new_mat, "users": users}


def paint_material(opt, mesh_index: int, material_index: int, texture: str) -> dict:
    """Change the texture of one material of a mesh (every face that uses it, in every level of detail)."""
    me = opt.meshes[mesh_index]
    if not texture.lower().endswith(".tex"):
        texture += ".tex"
    m = me.materials[material_index]
    if m.textures:
        m.textures[0] = texture
    else:
        m.textures = [texture]
    n = sum(len(s.indices) // 3 for lod in me.lods[:1] for p in lod.parts for s in p.submeshes if s.material_index == material_index)
    return {"triangles": n, "far_triangles": 0, "material": material_index,
            "users": sum(1 for pr in opt.props if pr.mesh_index == mesh_index)}


def textures_of(opt, mesh_index: int) -> List[str]:
    return [m.diffuse for m in opt.meshes[mesh_index].materials]
