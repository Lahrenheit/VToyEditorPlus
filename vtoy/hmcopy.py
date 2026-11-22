"""Floor collision (.hm) editing for the twin ships: copy the faces of a region to another place, add flat floor quads, and rebuild the
sector quadtree around the result.

Sector fields of ``vtoy.hm.HMSector`` are stored in file order (x0, z0, x1, z1) although the dataclass calls them
x_min, x_max, z_min, z_max.  Floor faces live only in the LEAVES of the tree, each in every leaf its xz bounding box touches."""
from __future__ import annotations

from typing import List, Optional, Tuple

import numpy as np

from .hm import HeightMap, HMFace, HMSector

MAX_FACES = 9          # a sector is split while it holds more faces than this (as in every shipped .hm)
MAX_DEPTH = 5          # default only: the depth of the map's own tree is kept (it differs per map, 3..7)


def tree_depth(s: HMSector) -> int:
    return 0 if not s.children else 1 + max(tree_depth(c) for c in s.children)


def box(s: HMSector) -> Tuple[float, float, float, float]:
    """(x0, z0, x1, z1) of a sector."""
    return s.x_min, s.x_max, s.z_min, s.z_max


def unique_faces(hm: HeightMap) -> List[HMFace]:
    """Every face once (the leaves repeat them)."""
    seen = {}
    for s in hm.root.walk():
        for f in s.faces:
            pts = np.concatenate(f.contours) if f.contours else np.zeros((0, 3), np.float32)
            key = (np.round(np.asarray(f.normal, np.float64), 4).tobytes(), round(float(f.distance), 3), np.round(pts, 2).tobytes())
            seen.setdefault(key, f)
    return list(seen.values())


def face_bounds(f: HMFace):
    p = np.concatenate(f.contours)
    return float(p[:, 0].min()), float(p[:, 2].min()), float(p[:, 0].max()), float(p[:, 2].max())


def shifted(f: HMFace, dx: float, dy: float = 0.0, dz: float = 0.0) -> HMFace:
    """A copy of ``f`` moved by (dx, dy, dz); the plane equation n.p + d = 0 follows the move."""
    n = np.asarray(f.normal, np.float64)
    d = float(f.distance) - float(n @ np.array([dx, dy, dz]))
    cs = [(np.asarray(c, np.float32) + np.array([dx, dy, dz], np.float32)).astype(np.float32) for c in f.contours]
    return HMFace(tuple(float(v) for v in f.normal), d, cs)


def make_face(points, toward) -> HMFace:
    """A height map face through ``points`` (n, 3) whose stored normal points towards ``toward`` (a direction).
    Every face of the shipped maps is wound so that its winding normal is the OPPOSITE of the stored one (the engine is
    left-handed); this keeps that rule for floors, slopes and walls alike."""
    p = np.asarray(points, np.float64).reshape(-1, 3)
    w = np.zeros(3)
    for i in range(len(p)):
        w += np.cross(p[i], p[(i + 1) % len(p)])
    ln = float(np.linalg.norm(w))
    if ln < 1e-9:
        raise ValueError("degenerate face")
    w /= ln
    if float(w @ np.asarray(toward, np.float64)) > 0:          # winding normal must point away from the stored one
        p = p[::-1].copy()
        w = -w
    n = -w
    return HMFace(tuple(float(v) for v in n), -float(n @ p[0]), [p.astype(np.float32)])


def floor_quad(x0: float, x1: float, z0: float, z1: float, y: float) -> HMFace:
    """A horizontal walkable rectangle (normal up)."""
    x0, x1 = sorted((x0, x1)); z0, z1 = sorted((z0, z1))
    pts = np.array([(x0, y, z0), (x1, y, z0), (x1, y, z1), (x0, y, z1)], np.float32)
    area = 0.5 * float(np.sum(pts[:, 0] * np.roll(pts[:, 2], -1) - np.roll(pts[:, 0], -1) * pts[:, 2]))
    if area < 0:                                    # shipped up-facing floors have a positive xz signed area
        pts = pts[::-1].copy()
    return HMFace((0.0, 1.0, 0.0), -float(y), [pts])


def build_tree(faces: List[HMFace], bounds: Tuple[float, float, float, float], max_depth: int = MAX_DEPTH) -> HMSector:
    """Quadtree over ``bounds`` (x0, z0, x1, z1), same rules as the shipped files: faces only in leaves, each in every leaf its
    xz bounding box touches, split while a sector holds more than MAX_FACES faces, children ordered z-high first."""
    fb = [face_bounds(f) for f in faces]

    def make(b, idx, depth) -> HMSector:
        s = HMSector(b[0], b[1], b[2], b[3])
        if len(idx) > MAX_FACES and depth < max_depth:
            xm, zm = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
            kids = []
            # child order of the shipped files: (x low, z high), (x high, z high), (x low, z low), (x high, z low)
            for qb in ((b[0], zm, xm, b[3]), (xm, zm, b[2], b[3]), (b[0], b[1], xm, zm), (xm, b[1], b[2], zm)):
                sub = [i for i in idx if not (fb[i][2] < qb[0] or fb[i][0] > qb[2] or fb[i][3] < qb[1] or fb[i][1] > qb[3])]
                kids.append(make(qb, sub, depth + 1))
            s.children = kids
        else:
            s.faces = [faces[i] for i in idx]
        return s

    return make(bounds, list(range(len(faces))), 0)


def region_faces(hm: HeightMap, lo_xz, hi_xz) -> List[HMFace]:
    """Faces whose xz bounding box lies inside [lo, hi]."""
    out = []
    for f in unique_faces(hm):
        x0, z0, x1, z1 = face_bounds(f)
        if x0 >= lo_xz[0] and x1 <= hi_xz[0] and z0 >= lo_xz[1] and z1 <= hi_xz[1]:
            out.append(f)
    return out


def copy_region(hm: HeightMap, lo_xz, hi_xz, dx: float, dz: float = 0.0, pad: float = 600.0) -> dict:
    """Copy the floor faces inside the region by (dx, dz) and rebuild the tree so it covers the copy.  Faces that cover the whole sea
    floor are extended instead of copied.  Returns a small report; ``hm.root`` is replaced."""
    r = hm.root
    old = box(r)
    faces = unique_faces(hm)
    inside = region_faces(hm, lo_xz, hi_xz)
    moved = [shifted(f, dx, 0.0, dz) for f in inside]
    # the sea floor spans the whole old root: lay the same level under the new area as well
    ext = []
    for f in faces:
        x0, z0, x1, z1 = face_bounds(f)
        if abs(f.normal[1]) > 0.99 and x0 <= old[0] + 1 and z0 <= old[1] + 1 and x1 >= old[2] - 1 and z1 >= old[3] - 1:
            y = float(np.concatenate(f.contours)[:, 1].mean())
            nx0 = min(old[0], old[0] + dx, old[0] + dz * 0)
            ext.append(floor_quad(min(old[0], x0 + dx) - pad, old[0] + 50.0, old[1], old[3], y))
    allf = faces + moved + ext
    nb = [old[0], old[1], old[2], old[3]]
    for f in moved + ext:
        x0, z0, x1, z1 = face_bounds(f)
        nb = [min(nb[0], x0 - 1), min(nb[1], z0 - 1), max(nb[2], x1 + 1), max(nb[3], z1 + 1)]
    hm.root = build_tree(allf, tuple(nb), max(tree_depth(r), 1))
    return {"faces": len(faces), "copied": len(moved), "sea_floor_extensions": len(ext), "bounds": nb}


def add_faces(hm: HeightMap, new: List[HMFace]) -> None:
    """Add faces (any slope); the tree is rebuilt once and grows if they are outside of it."""
    faces = unique_faces(hm) + list(new)
    b = list(box(hm.root))
    for f in new:
        fx0, fz0, fx1, fz1 = face_bounds(f)
        b = [min(b[0], fx0 - 1), min(b[1], fz0 - 1), max(b[2], fx1 + 1), max(b[3], fz1 + 1)]
    hm.root = build_tree(faces, tuple(b), max(tree_depth(hm.root), 1))


def add_floor(hm: HeightMap, x0: float, x1: float, z0: float, z1: float, y: float) -> None:
    """Add a walkable rectangle (e.g. a gangplank); the tree is rebuilt (it grows if the rectangle is outside of it)."""
    faces = unique_faces(hm) + [floor_quad(x0, x1, z0, z1, y)]
    b = list(box(hm.root))
    fx0, fz0, fx1, fz1 = face_bounds(faces[-1])
    b = [min(b[0], fx0 - 1), min(b[1], fz0 - 1), max(b[2], fx1 + 1), max(b[3], fz1 + 1)]
    hm.root = build_tree(faces, tuple(b), max(tree_depth(hm.root), 1))
