"""Fill patches: a flat, textured polygon added to a map as a new static mesh (to cover holes that a crop leaves)."""
from __future__ import annotations

from typing import List, Sequence

import numpy as np

from .opt import Lod, Material, MeshPart, OptMap, StaticMesh, SubMesh, VERTEX_DTYPE
from .opt import STOCK_MATERIAL as _STOCK_MATERIAL

LOD_FAR = 1259902592          # bit pattern of 1e7 (what single-LOD meshes of real maps store as LOD distance)


def triangulate(poly: Sequence[Sequence[float]]) -> List[tuple]:
    """Ear clipping of a simple polygon given as (x, z) points. Returns index triples (any winding of the input)."""
    pts = np.asarray(poly, np.float64)
    n = len(pts)
    if n < 3:
        raise ValueError("a polygon needs at least 3 points")
    area = 0.5 * np.sum(pts[:, 0] * np.roll(pts[:, 1], -1) - np.roll(pts[:, 0], -1) * pts[:, 1])
    idx = list(range(n)) if area > 0 else list(range(n))[::-1]

    def cross(a, b, c):
        return (pts[b, 0] - pts[a, 0]) * (pts[c, 1] - pts[a, 1]) - (pts[b, 1] - pts[a, 1]) * (pts[c, 0] - pts[a, 0])

    def inside(p, a, b, c):
        return cross(a, b, p) >= -1e-9 and cross(b, c, p) >= -1e-9 and cross(c, a, p) >= -1e-9

    tris, guard = [], 0
    while len(idx) > 3 and guard < 10000:
        guard += 1
        for k in range(len(idx)):
            a, b, c = idx[k - 1], idx[k], idx[(k + 1) % len(idx)]
            if cross(a, b, c) <= 1e-9:
                continue
            if any(inside(p, a, b, c) for p in idx if p not in (a, b, c)):
                continue
            tris.append((a, b, c)); idx.pop(k)
            break
        else:                                  # degenerate polygon: fan the rest
            break
    if len(idx) >= 3:
        for k in range(1, len(idx) - 1):
            tris.append((idx[0], idx[k], idx[k + 1]))
    return tris


def make_patch(opt: OptMap, poly_xz, y: float, texture: str, tile: float = 256.0) -> StaticMesh:
    """A horizontal patch at height ``y`` (engine coordinates) covered with ``texture`` (repeating every ``tile`` units)."""
    tris = triangulate(poly_xz)
    pts = np.asarray(poly_xz, np.float64)
    v = np.zeros(len(pts), VERTEX_DTYPE)
    v["pos"][:, 0], v["pos"][:, 1], v["pos"][:, 2] = pts[:, 0], y, pts[:, 1]
    v["nrm"] = (0, 1, 0)
    v["uv"][:, 0], v["uv"][:, 1] = pts[:, 0] / tile, pts[:, 1] / tile
    idx = np.asarray(tris, np.uint16).reshape(-1)
    donor = next((mat for me in opt.meshes for mat in me.materials if mat.textures), None)
    mat = Material(name=texture.rsplit(".", 1)[0], textures=[texture], two_sided=True,
                   uv_map=donor.uv_map if donor is not None and any(donor.uv_map[:48]) else _STOCK_MATERIAL, unk_float=donor.unk_float if donor else 100.0)
    lo, hi = v["pos"].min(0), v["pos"].max(0)
    corners = np.array([[x, yy, z] for x in (lo[0], hi[0]) for yy in (lo[1], hi[1]) for z in (lo[2], hi[2])], np.float32)
    part = MeshPart(active=True, corners=corners.astype("<f4").tobytes(),
                    submeshes=[SubMesh(stride_type=0, material_id=0, material_index=0, unk=0, vertices=v, indices=idx)])
    me = StaticMesh(materials=[mat], lods=[Lod(unk=LOD_FAR, parts=[part])], corners=corners)
    me.world_transform = np.eye(4, dtype=np.float32)
    me.world_transform[3, :3] = (lo + hi) / 2
    return me
