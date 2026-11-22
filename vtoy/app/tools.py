"""Pure (GL / imgui free) helpers of the editing tools: ray / plane maths, the axis gizmo and the drag arithmetic."""
from __future__ import annotations

from typing import Dict, Optional, Tuple

import numpy as np

from ..render.camera import ray_aabb

TOOLS = ("select", "move", "rotate", "scale", "pen", "fill", "measure", "collision", "paint")
AXIS_COLORS = {"X": (1.0, 0.25, 0.25, 1), "Y": (0.3, 1.0, 0.3, 1), "Z": (0.35, 0.5, 1.0, 1)}
DISPLAY_DIR = {"X": np.array([1.0, 0, 0]), "Y": np.array([0, 1.0, 0]), "Z": np.array([0, 0, -1.0])}   # view mirrors engine Z


def ray_plane_y(origin, direction, y: float) -> Optional[np.ndarray]:
    """Point where the ray crosses the horizontal plane at height ``y`` (display space) or None."""
    d = np.asarray(direction, np.float64)
    if abs(d[1]) < 1e-9:
        return None
    t = (y - origin[1]) / d[1]
    if t <= 0:
        return None
    return np.asarray(origin, np.float64) + d * t


def gizmo(center, size) -> Dict[str, Tuple[np.ndarray, np.ndarray, np.ndarray]]:
    """axis -> (tip, handle centre, handle half size) for a selection centred at ``center`` (display space)."""
    c = np.asarray(center, np.float64)
    length = max(150.0, 0.7 * float(np.max(size)))
    half = np.full(3, 0.08 * length)
    return {a: (c + DISPLAY_DIR[a] * length, c + DISPLAY_DIR[a] * length, half) for a in "XYZ"}


def hit_handle(origin, direction, center, size) -> Optional[str]:
    best, best_t = None, 1e30
    for a, (_, hc, half) in gizmo(center, size).items():
        t = ray_aabb(origin, direction, hc - half, hc + half)
        if t is not None and t < best_t:
            best, best_t = a, t
    return best


def move_delta(axis: str, hit0, hit, screen_dy: float, scale: float) -> np.ndarray:
    """Display-space translation of a move drag. ``axis`` is free (ground plane), X, Y (screen up/down) or Z."""
    if axis == "Y":
        return np.array([0.0, -screen_dy * scale, 0.0])
    d = np.asarray(hit, np.float64) - np.asarray(hit0, np.float64)
    d[1] = 0.0
    if axis == "X":
        d[2] = 0.0
    elif axis == "Z":
        d[0] = 0.0
    return d


def rotate_delta(axis: str, dx: float, dy: float, speed: float = 0.5) -> np.ndarray:
    """Euler delta (degrees about engine X, Y, Z) of a rotate drag."""
    out = np.zeros(3)
    if axis == "X":
        out[0] = dy * speed
    elif axis == "Z":
        out[2] = dx * speed
    else:
        out[1] = dx * speed
    return out


def display_to_engine(v) -> np.ndarray:
    return np.asarray(v, np.float64) * [1, 1, -1]


_CORN = np.array([[x, y, z] for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)], np.float64)
_EDGES = [(i, j) for i in range(8) for j in range(i + 1, 8) if bin(i ^ j).count("1") == 1]


def obb_segments(centres, rots, halves) -> np.ndarray:
    """Wire segments (n, 12, 2, 3) of oriented boxes: centre (n,3), rotation rows = local axes (n,3,3), half sizes (n,3)."""
    c = np.atleast_2d(np.asarray(centres, np.float64))
    r = np.asarray(rots, np.float64).reshape(-1, 3, 3)
    h = np.atleast_2d(np.asarray(halves, np.float64))
    pts = np.einsum("nkj,njm->nkm", _CORN[None] * h[:, None, :], r) + c[:, None, :]
    return pts[:, _EDGES]


def preview_box(center_display, size, euler_deg_engine, scale: float = 1.0) -> np.ndarray:
    """Wire box of a selection with a pending rotation / scale (what the object will look like when applied)."""
    from ..render.camera import compose
    R = compose([0, 0, 0], euler_deg_engine, [1, 1, 1])[:3, :3].astype(np.float64)
    F = np.diag([1.0, 1.0, -1.0])
    return obb_segments(center_display, (F @ R @ F)[None], (np.asarray(size, np.float64) * scale / 2)[None])


def collision_wires(opt):
    """(box segments (n,12,2,3), hull segments (m,2,3)) in display space for the collision data of a map."""
    from .. import crop
    blk = crop.read_block(opt)
    F = np.diag([1.0, 1.0, -1.0])
    if blk.boxes:
        arr = np.array([np.frombuffer(b, "<f4", 19) for b in blk.boxes], np.float64)
        rot = arr[:, :16].reshape(-1, 4, 4)[:, :3, :3]
        c = arr[:, 12:15] * [1, 1, -1]
        half = np.abs(arr[:, 16:19]) + 1e-3
        rots = np.einsum("nij,jk->nik", rot, F)
        boxes = obb_segments(c, rots, half)
    else:
        boxes = np.zeros((0, 12, 2, 3))
    hulls = []
    level = float(np.median(arr[:, 13])) if blk.boxes else 0.0
    import struct
    for pb in blk.polys:
        n = struct.unpack_from("<I", pb, 0)[0]
        if n < 2:
            continue
        q = np.frombuffer(pb, "<f4", 3 * n, 4).reshape(n, 3).astype(np.float64)
        # a hull is a 2D footprint stored as (x, z, tag): the tag is not a height, so it is drawn flat at the map's usual level
        p = np.c_[q[:, 0], np.full(n, level), -q[:, 1]]
        hulls.extend(zip(p, np.roll(p, -1, 0)))
    return boxes, np.array(hulls).reshape(-1, 2, 3) if hulls else np.zeros((0, 2, 3))


# ------------------------------------------------------------------------------------------------ points under the mouse
_F = np.array([1.0, 1.0, -1.0])


def point_under_ray(o, d, points):
    """Index of the engine point (of ``points``) under a display-space ray, or None (picked within ~2.5 % of its depth)."""
    o, d = np.asarray(o, np.float64), np.asarray(d, np.float64)
    d = d / max(np.linalg.norm(d), 1e-12)
    best, bd = None, None
    for k, p in enumerate(points):
        q = np.asarray(p, np.float64) * _F
        t = float((q - o) @ d)
        if t <= 0:
            continue
        dist = float(np.linalg.norm(q - (o + d * t)))
        if dist <= max(35.0, t * 0.025) and (bd is None or dist < bd):
            best, bd = k, dist
    return best


def segment_under_ray(o, d, points, closed: bool = False):
    """(index of the first point, engine point on the line) of the line between two of ``points`` under the ray."""
    o, d = np.asarray(o, np.float64), np.asarray(d, np.float64)
    d = d / max(np.linalg.norm(d), 1e-12)
    pts = [np.asarray(p, np.float64) * _F for p in points]
    segs = list(zip(range(len(pts) - 1), pts[:-1], pts[1:]))
    if closed and len(pts) > 2:
        segs.append((len(pts) - 1, pts[-1], pts[0]))
    best, bd = None, None
    for i, a, b in segs:
        ab = b - a
        w = o - a
        A, B, C, D, E = d @ d, d @ ab, ab @ ab, d @ w, ab @ w
        den = A * C - B * B
        if abs(den) < 1e-9 or C < 1e-9:
            continue
        s_ = (B * E - C * D) / den
        t_ = (A * E - B * D) / den
        if s_ <= 0 or not (0.05 < t_ < 0.95):
            continue
        q = a + ab * t_
        dist = float(np.linalg.norm(o + d * s_ - q))
        if dist <= max(30.0, s_ * 0.02) and (bd is None or dist < bd):
            best, bd = (i, q * _F), dist
    return best
