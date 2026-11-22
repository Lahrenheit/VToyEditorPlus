"""Map pieces of other maps of the game: list them, split them in their separate parts, take one out as a new mesh.

The maps of the engine merge their geometry by material and area, so one "mesh" is often many separate things far apart
(the glass of every skylight of a mall is a single mesh).  ``parts`` splits a mesh / prop in its connected pieces (triangles
that touch), so one skylight can be taken alone.

    pieces(opt)                        what a map has: [{kind, index, label, textures, tris, size, centre}]
    parts(opt, kind, index)            the separate pieces of one of them
    extract(opt, kind, index, part)    a new StaticMesh in world coordinates (props baked in), ready for crop.add_mesh
    place(mesh, at, yaw)               bottom centre of the mesh at ``at`` (engine), turned ``yaw`` degrees
"""
from __future__ import annotations

import copy
from typing import Dict, List, Optional

import numpy as np

from . import crop
from .fill import LOD_FAR
from .opt import Lod, MeshPart, StaticMesh, SubMesh, transform_mesh, translate_mesh


def _matrix(opt, kind: str, index: int):
    """(mesh, 4x4 row-vector matrix to world)."""
    if kind == "mesh":
        return opt.meshes[index], np.eye(4)
    pr = opt.props[index]
    me = opt.meshes[pr.mesh_index]
    return me, np.linalg.inv(np.asarray(me.world_transform, np.float64)) @ np.asarray(pr.transform, np.float64)


def _subs(me) -> List[SubMesh]:
    return [sm for part in (me.lods[0].parts if me.lods else []) for sm in part.submeshes
            if sm.vertices is not None and len(sm.vertices) and sm.indices is not None and len(sm.indices) >= 3]


def _tris(sm) -> np.ndarray:
    t = np.asarray(sm.indices, np.int64)
    t = t[: len(t) // 3 * 3].reshape(-1, 3)
    return t[(t < len(sm.vertices)).all(1)]


def _world_points(me, M) -> np.ndarray:
    p = np.concatenate([sm.vertices["pos"].astype(np.float64) for sm in _subs(me)]) if _subs(me) else np.zeros((0, 3))
    return p @ M[:3, :3] + M[3, :3]


def pieces(opt) -> List[dict]:
    """The static meshes (not the hidden patterns props are drawn from) and the props of a map."""
    used = {p.mesh_index for p in opt.props}
    out = []
    for kind, n in (("mesh", len(opt.meshes)), ("prop", len(opt.props))):
        for i in range(n):
            if kind == "mesh" and i in used:
                continue
            try:
                me, M = _matrix(opt, kind, i)
            except (IndexError, np.linalg.LinAlgError):
                continue
            p = _world_points(me, M)
            if not len(p):
                continue
            lo, hi = p.min(0), p.max(0)
            tex = sorted({m.diffuse for m in me.materials if m.diffuse}, key=str.lower)
            tris = sum(len(_tris(sm)) for sm in _subs(me))
            out.append({"kind": kind, "index": i, "textures": tex, "tris": tris, "size": hi - lo, "centre": (lo + hi) / 2,
                        "label": f"{kind} {i}: {', '.join(tex[:3])}{' ...' if len(tex) > 3 else ''}"})
    return out


def parts(opt, kind: str, index: int, max_parts: int = 400) -> List[dict]:
    """The separate pieces (triangles connected by their corners) of a mesh / prop, biggest first.
    Each: {'tris': {submesh number: triangle numbers}, 'count', 'size', 'centre', 'textures'}."""
    me, M = _matrix(opt, kind, index)
    subs = _subs(me)
    keys: Dict[tuple, int] = {}
    parent: List[int] = []

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    tri_nodes = []
    for si, sm in enumerate(subs):
        pos = np.round(sm.vertices["pos"].astype(np.float64), 1)
        ids = np.empty(len(pos), np.int64)
        for v, p in enumerate(map(tuple, pos)):
            k = keys.get(p)
            if k is None:
                k = keys[p] = len(parent)
                parent.append(k)
            ids[v] = k
        for t in _tris(sm):
            a, b, c = (find(int(ids[x])) for x in t)
            parent[b] = a
            parent[find(c)] = a
            tri_nodes.append((si, int(ids[t[0]])))
    groups: Dict[int, Dict[int, list]] = {}
    k = 0
    for si, sm in enumerate(subs):
        for ti in range(len(_tris(sm))):
            root = find(tri_nodes[k][1])
            groups.setdefault(root, {}).setdefault(si, []).append(ti)
            k += 1
    out = []
    for g in groups.values():
        pts = []
        for si, tl in g.items():
            t = _tris(subs[si])[tl]
            pts.append(subs[si].vertices["pos"].astype(np.float64)[t.reshape(-1)])
        p = np.concatenate(pts) @ M[:3, :3] + M[3, :3]
        lo, hi = p.min(0), p.max(0)
        out.append({"tris": {si: np.asarray(tl, np.int64) for si, tl in g.items()}, "count": sum(len(t) for t in g.values()),
                    "size": hi - lo, "centre": (lo + hi) / 2,
                    "textures": sorted({me.materials[subs[si].material_index].diffuse for si in g
                                        if subs[si].material_index < len(me.materials)}, key=str.lower)})
    out.sort(key=lambda d: -d["count"])
    return out[:max_parts]


def _finish(me: StaticMesh) -> StaticMesh:
    lo, hi = crop.mesh_bounds(me)
    me.corners = np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])], np.float32)
    me.world_transform = np.eye(4, dtype=np.float32)
    me.world_transform[3, :3] = (lo + hi) / 2
    return me


def extract(opt, kind: str, index: int, part: Optional[dict] = None) -> StaticMesh:
    """A copy, in world coordinates, of a mesh / prop of ``opt`` - all of it (every level of detail), or only ``part``
    (one entry of ``parts``; level of detail 0)."""
    src, M = _matrix(opt, kind, index)
    if part is None:
        me = copy.deepcopy(src)
    else:
        subs = _subs(src)
        new_subs = []
        first = 0
        for si, tl in sorted(part["tris"].items()):
            sm = subs[si]
            t = _tris(sm)[np.asarray(tl, np.int64)]
            used, inv = np.unique(t.reshape(-1), return_inverse=True)
            ns = SubMesh(stride_type=sm.stride_type, material_id=sm.material_id, material_index=sm.material_index, unk=first,
                         vertices=sm.vertices[used].copy(), indices=inv.astype(np.uint16))
            first += len(ns.indices)
            new_subs.append(ns)
        lo = np.concatenate([s.vertices["pos"] for s in new_subs]).min(0)
        me = StaticMesh(materials=copy.deepcopy(src.materials),
                        lods=[Lod(unk=LOD_FAR, parts=[MeshPart(active=True, corners=np.zeros((8, 3), "<f4").tobytes(), submeshes=new_subs)])],
                        corners=np.tile(lo, (8, 1)).astype(np.float32))
    if not np.allclose(M, np.eye(4)):
        transform_mesh(me, M[:3, :3], np.zeros(3))
        translate_mesh(me, M[3, :3])
    for lod in me.lods:                                     # the part boxes follow the vertices
        for prt in lod.parts:
            p = [s.vertices["pos"] for s in prt.submeshes if s.vertices is not None and len(s.vertices)]
            if p:
                p = np.concatenate(p)
                a, b = p.min(0), p.max(0)
                prt.corners = np.array([[x, y, z] for x in (a[0], b[0]) for y in (a[1], b[1]) for z in (a[2], b[2])], "<f4").tobytes()
    return _finish(me)


def place(me: StaticMesh, at, yaw: float = 0.0) -> StaticMesh:
    """Turn the mesh ``yaw`` degrees about its centre and put its bottom centre at ``at`` (engine)."""
    lo, hi = crop.mesh_bounds(me)
    c = (lo + hi) / 2
    if abs(yaw) > 1e-6:
        a = np.radians(yaw)
        R = np.array([[np.cos(a), 0, -np.sin(a)], [0, 1, 0], [np.sin(a), 0, np.cos(a)]])
        transform_mesh(me, R, c)
        lo, hi = crop.mesh_bounds(me)
        c = (lo + hi) / 2
    translate_mesh(me, np.asarray(at, np.float64) - [c[0], lo[1], c[2]])
    return _finish(me)
