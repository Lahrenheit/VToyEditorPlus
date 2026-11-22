"""Floor / wall collision (.hm faces) generated from the triangles of map meshes.

The shipped height maps are just that: nearly every face is a triangle (some quads / polygons) of the visible geometry, with
its plane, facing the side you can touch: floors (normal up), walls, slopes and ceilings alike.  This module makes the same
faces from any static mesh or prop of the map, so a ship copied by hand, an imported model or a new building can be walked
on without drawing its collision by hand.

    triangles_of(opt, kind, index)      world triangles + the side they face (from the vertex normals)
    faces_from_triangles(tris, facing)  height map faces (coplanar pairs joined into quads)
    generate(opt, hm, targets, ...)     add them to a height map; returns a report
    bounding_box(tris)                  centre / half size of a box around them (for a quick collision box)
"""
from __future__ import annotations

from typing import List, Sequence, Tuple

import numpy as np

from . import hmcopy
from .hm import HMFace

WALKABLE = 0.45          # a face with normal.y above this is a floor / ramp you can stand on
MAX_TREE_DEPTH = 7       # deepest quadtree found in the shipped maps


def _mesh_matrix(opt, kind: str, index: int) -> Tuple[object, np.ndarray]:
    if kind == "mesh":
        return opt.meshes[index], np.eye(4)
    pr = opt.props[index]
    me = opt.meshes[pr.mesh_index]
    return me, np.linalg.inv(me.world_transform.astype(np.float64)) @ pr.transform.astype(np.float64)


def triangles_of(opt, kind: str, index: int) -> Tuple[np.ndarray, np.ndarray]:
    """(triangles (n, 3, 3), facing (n, 3)) of static mesh / prop ``index`` in engine coordinates (LOD 0).
    ``facing`` is the mean of the three vertex normals: the side of the triangle the artist meant to be seen."""
    me, M = _mesh_matrix(opt, kind, index)
    A = M[:3, :3]
    try:
        NA = np.linalg.inv(A).T
    except np.linalg.LinAlgError:
        NA = A
    tris, face = [], []
    for sm in me.render_submeshes():
        if sm.vertices is None or len(sm.vertices) == 0 or len(sm.indices) < 3:
            continue
        idx = np.asarray(sm.indices, np.int64)[: len(sm.indices) // 3 * 3].reshape(-1, 3)
        idx = idx[(idx < len(sm.vertices)).all(1)]
        p = sm.vertices["pos"].astype(np.float64) @ A + M[3, :3]
        n = sm.vertices["nrm"].astype(np.float64) @ NA
        tris.append(p[idx])
        face.append(n[idx].sum(1))
    if not tris:
        return np.zeros((0, 3, 3)), np.zeros((0, 3))
    return np.concatenate(tris), np.concatenate(face)


def _normals(tris: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    g = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    ln = np.linalg.norm(g, axis=1)
    return g / np.maximum(ln, 1e-12)[:, None], ln / 2


def classify(ny: float) -> str:
    return "floor" if ny >= WALKABLE else ("ceiling" if ny <= -WALKABLE else "wall")


def _convex(poly: np.ndarray, n: np.ndarray) -> bool:
    k = len(poly)
    s = [float(np.cross(poly[(i + 1) % k] - poly[i], poly[(i + 2) % k] - poly[(i + 1) % k]) @ n) for i in range(k)]
    return min(s) > -1e-6 or max(s) < 1e-6


def faces_from_triangles(tris, facing=None, floors: bool = True, walls: bool = True, ceilings: bool = True,
                         min_area: float = 4.0, merge: bool = True, up_only: bool = False) -> Tuple[List[HMFace], dict]:
    """Height map faces for the triangles.  ``facing`` (n, 3) says which side each one faces (default: its winding in a
    left-handed world, as the meshes of the game are stored); ``up_only`` turns every floor upwards whatever the normals say
    (thin two-sided planks).  Two triangles that share an edge and lie in one plane become one quad when it is convex."""
    tris = np.asarray(tris, np.float64).reshape(-1, 3, 3)
    stats = {"triangles": len(tris), "floor": 0, "wall": 0, "ceiling": 0, "tiny": 0, "quads": 0}
    if not len(tris):
        return [], stats
    g, area = _normals(tris)
    if facing is None:
        facing = -g                                   # left-handed winding: the visible side is the opposite of the cross product
    facing = np.asarray(facing, np.float64)
    flip = (g * facing).sum(1) < 0
    g[flip] = -g[flip]
    if up_only:
        turn = (np.abs(g[:, 1]) >= WALKABLE) & (g[:, 1] < 0)
        g[turn] = -g[turn]
    keep = []
    for i in range(len(tris)):
        if area[i] < min_area:
            stats["tiny"] += 1
            continue
        k = classify(g[i, 1])
        if (k == "floor" and floors) or (k == "wall" and walls) or (k == "ceiling" and ceilings):
            keep.append(i)
    used = set()
    out: List[HMFace] = []

    def emit(pts, n):
        try:
            out.append(hmcopy.make_face(pts, n))
        except ValueError:
            stats["tiny"] += 1
            return
        stats[classify(float(n[1]))] += 1

    if merge and keep:
        # pairs of coplanar triangles that share an edge -> quads
        edges = {}
        key_pt = lambda p: tuple(np.round(p, 1))
        plane_key = {}
        for i in keep:
            d = float(g[i] @ tris[i, 0])
            plane_key[i] = (tuple(np.round(g[i], 2)), round(d / 2.0))
            ks = [key_pt(p) for p in tris[i]]
            for a in range(3):
                e = tuple(sorted((ks[a], ks[(a + 1) % 3])))
                edges.setdefault((plane_key[i], e), []).append((i, a))
        for (_, _e), lst in edges.items():
            if len(lst) != 2:
                continue
            (i, a), (j, b) = lst
            if i in used or j in used or i == j:
                continue
            # quad: triangle i with the opposite vertex of j inserted on the shared edge
            ti, tj = tris[i], tris[j]
            opp = tj[(b + 2) % 3]
            quad = np.array([ti[(a + 2) % 3], ti[a], opp, ti[(a + 1) % 3]])
            if not _convex(quad, g[i]):
                continue
            used.update((i, j))
            stats["quads"] += 1
            emit(quad, g[i])
    for i in keep:
        if i not in used:
            emit(tris[i], g[i])
    return out, stats


def bounding_box(tris) -> Tuple[np.ndarray, np.ndarray]:
    """(centre, half size) of the axis aligned box around the triangles."""
    p = np.asarray(tris, np.float64).reshape(-1, 3)
    lo, hi = p.min(0), p.max(0)
    return (lo + hi) / 2, np.maximum((hi - lo) / 2, 2.0)


def remove_faces_in(hm, lo, hi, pad: float = 1.0) -> int:
    """Drop the faces that lie completely inside the box [lo, hi] (engine); used to regenerate without duplicates."""
    lo = np.asarray(lo, np.float64) - pad
    hi = np.asarray(hi, np.float64) + pad
    keep, n = [], 0
    for f in hmcopy.unique_faces(hm):
        p = np.concatenate(f.contours)
        if (p >= lo).all() and (p <= hi).all():
            n += 1
        else:
            keep.append(f)
    if n:
        hm.root = hmcopy.build_tree(keep, hmcopy.box(hm.root), max(hmcopy.tree_depth(hm.root), 1))
    return n


def add_faces(hm, faces: Sequence[HMFace]) -> None:
    """Like hmcopy.add_faces, but the tree may grow deeper (up to the deepest shipped one) when many faces are added."""
    allf = hmcopy.unique_faces(hm) + list(faces)
    b = list(hmcopy.box(hm.root))
    for f in faces:
        x0, z0, x1, z1 = hmcopy.face_bounds(f)
        b = [min(b[0], x0 - 1), min(b[1], z0 - 1), max(b[2], x1 + 1), max(b[3], z1 + 1)]
    depth = max(hmcopy.tree_depth(hm.root), 1)
    while depth < MAX_TREE_DEPTH and len(allf) > hmcopy.MAX_FACES * 4 ** depth:
        depth += 1
    hm.root = hmcopy.build_tree(allf, tuple(b), depth)


def generate(opt, hm, targets, floors: bool = True, walls: bool = True, ceilings: bool = True, min_area: float = 4.0,
             merge: bool = True, replace: bool = True, up_only: bool = False) -> dict:
    """Add collision faces for ``targets`` = [(kind, index)] ('mesh' | 'prop') to the height map ``hm``.
    ``replace`` first removes the faces already inside the bounds of each target (so running it twice does not pile them up)."""
    total = {"triangles": 0, "floor": 0, "wall": 0, "ceiling": 0, "tiny": 0, "quads": 0, "removed": 0, "targets": 0}
    new: List[HMFace] = []
    for kind, index in targets:
        tris, facing = triangles_of(opt, kind, index)
        if not len(tris):
            continue
        total["targets"] += 1
        if replace:
            p = tris.reshape(-1, 3)
            total["removed"] += remove_faces_in(hm, p.min(0), p.max(0))
        faces, st = faces_from_triangles(tris, facing, floors, walls, ceilings, min_area, merge, up_only)
        new += faces
        for k in ("triangles", "floor", "wall", "ceiling", "tiny", "quads"):
            total[k] += st[k]
    if new:
        add_faces(hm, new)
    total["faces"] = len(new)
    return total
