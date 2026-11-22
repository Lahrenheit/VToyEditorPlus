"""Ready-made shapes to build with (box, cylinder, cone, ramp, stairs, pyramid, prism from points ...), as faces.

Every shape is made in its own frame (x = width, y = up, z = depth; origin = bottom centre), then turned ``yaw`` degrees
about the vertical axis and put at ``at`` (engine).  Faces are (points (n, 3), outward normal); concave outlines are cut
in triangles here, so every face can be drawn as a fan.

    faces(kind, size, at, yaw, sides, steps)   the shape
    from_points(kind, points, height, ...)     a shape drawn by points (like in a drawing program):
        'polygon'  the outline A, B, C ... raised ``height`` (a prism; concave outlines are fine)
        'rect'     A and B are two opposite corners of the base (turned like A -> B's first side when ``aligned``)
        'circle'   A is the centre, B a point of the edge
"""
from __future__ import annotations

import math
from typing import List, Sequence, Tuple

import numpy as np

KINDS = ("box", "cylinder", "cone", "ramp", "stairs", "pyramid", "wall", "disc")
POINT_KINDS = ("polygon", "rect", "circle")
DEFAULT_SIZE = {"box": (200.0, 200.0, 200.0), "cylinder": (150.0, 300.0, 150.0), "cone": (200.0, 300.0, 200.0),
                "ramp": (200.0, 150.0, 400.0), "stairs": (200.0, 200.0, 400.0), "pyramid": (300.0, 250.0, 300.0),
                "wall": (600.0, 300.0, 20.0), "disc": (300.0, 12.0, 300.0)}

Face = Tuple[np.ndarray, np.ndarray]


def _rot_y(deg: float) -> np.ndarray:
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, 0.0, -s], [0.0, 1.0, 0.0], [s, 0.0, c]])


def _quad(*p) -> np.ndarray:
    return np.array(p, np.float64)


def _normal(pts: np.ndarray) -> np.ndarray:
    n = np.zeros(3)
    for i in range(len(pts)):
        n += np.cross(pts[i], pts[(i + 1) % len(pts)])
    ln = np.linalg.norm(n)
    return n / ln if ln > 1e-12 else np.array([0.0, 1.0, 0.0])


def _box(x0, x1, y0, y1, z0, z1) -> List[Face]:
    out = []
    for pts, n in (((x0, y1, z0), (x0, y1, z1), (x1, y1, z1), (x1, y1, z0)), (0, 1, 0)), \
                  (((x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1)), (0, -1, 0)), \
                  (((x0, y0, z0), (x0, y1, z0), (x1, y1, z0), (x1, y0, z0)), (0, 0, -1)), \
                  (((x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)), (0, 0, 1)), \
                  (((x0, y0, z0), (x0, y0, z1), (x0, y1, z1), (x0, y1, z0)), (-1, 0, 0)), \
                  (((x1, y0, z0), (x1, y1, z0), (x1, y1, z1), (x1, y0, z1)), (1, 0, 0)):
        out.append((_quad(*pts), np.array(n, np.float64)))
    return out


def _ring(rx: float, rz: float, sides: int, y: float) -> np.ndarray:
    a = np.linspace(0, 2 * math.pi, sides, endpoint=False)
    return np.stack([rx * np.cos(a), np.full(sides, y), rz * np.sin(a)], 1)


def triangulate(outline: np.ndarray) -> List[Tuple[int, int, int]]:
    """Ear clipping of a simple polygon given as (n, 2) points (either winding).  Returns index triples."""
    p = np.asarray(outline, np.float64)
    n = len(p)
    if n < 3:
        return []
    area = 0.5 * sum(p[i, 0] * p[(i + 1) % n, 1] - p[(i + 1) % n, 0] * p[i, 1] for i in range(n))
    idx = list(range(n)) if area > 0 else list(range(n))[::-1]

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    def inside(pt, a, b, c):
        return cross(a, b, pt) >= 0 and cross(b, c, pt) >= 0 and cross(c, a, pt) >= 0
    out = []
    guard = 0
    while len(idx) > 3 and guard < 10000:
        guard += 1
        m = len(idx)
        for k in range(m):
            i0, i1, i2 = idx[(k - 1) % m], idx[k], idx[(k + 1) % m]
            a, b, c = p[i0], p[i1], p[i2]
            if cross(a, b, c) <= 1e-9:
                continue
            if any(inside(p[j], a, b, c) for j in idx if j not in (i0, i1, i2)):
                continue
            out.append((i0, i1, i2))
            idx.pop(k)
            break
        else:                                           # nothing clean left (a self-crossing outline): fan the rest
            break
    for k in range(1, len(idx) - 1):
        out.append((idx[0], idx[k], idx[k + 1]))
    return out


def prism(outline_xz: np.ndarray, y0: float, y1: float) -> List[Face]:
    """A solid with the outline (n, 2) (x, z) as base, from height y0 to y1."""
    o = np.asarray(outline_xz, np.float64)
    tris = triangulate(o)
    out = []
    for a, b, c in tris:
        top = np.array([[o[i, 0], y1, o[i, 1]] for i in (a, b, c)])
        n = _normal(top)
        if n[1] < 0:
            top = top[::-1]
        out.append((top, np.array([0.0, 1.0, 0.0])))
        bot = top.copy()
        bot[:, 1] = y0
        out.append((bot[::-1], np.array([0.0, -1.0, 0.0])))
    cen = o.mean(0)
    for i in range(len(o)):
        a, b = o[i], o[(i + 1) % len(o)]
        q = _quad((a[0], y0, a[1]), (b[0], y0, b[1]), (b[0], y1, b[1]), (a[0], y1, a[1]))
        e = b - a
        n = np.array([e[1], 0.0, -e[0]])
        ln = np.linalg.norm(n)
        if ln < 1e-9:
            continue
        n /= ln
        # outward: away from the inside (test a point just next to the edge middle)
        mid = (a + b) / 2 + n[[0, 2]] * 0.5
        if _point_in(mid, o):
            n = -n
        out.append((q, n))
    return out


def _point_in(pt, poly) -> bool:
    x, y = pt
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1 + 1e-300) + x1:
            inside = not inside
    return inside


def local_faces(kind: str, size, sides: int = 16, steps: int = 8) -> List[Face]:
    w, h, d = (max(float(v), 0.5) for v in size)
    if kind in ("box", "wall"):
        return _box(-w / 2, w / 2, 0.0, h, -d / 2, d / 2)
    if kind in ("cylinder", "disc"):
        n = max(3, int(sides))
        return prism(_ring(w / 2, d / 2, n, 0.0)[:, [0, 2]], 0.0, h)
    if kind == "cone":
        n = max(3, int(sides))
        base = _ring(w / 2, d / 2, n, 0.0)
        apex = np.array([0.0, h, 0.0])
        out = [(base[::-1].copy(), np.array([0.0, -1.0, 0.0]))]
        for i in range(n):
            tri = np.array([base[i], apex, base[(i + 1) % n]])
            nn = _normal(tri)
            if nn @ ((base[i] + base[(i + 1) % n]) / 2 - [0, 0, 0]) < 0:
                tri = tri[::-1]
                nn = -nn
            out.append((tri, nn))
        return out
    if kind == "pyramid":
        b = np.array([[-w / 2, 0, -d / 2], [w / 2, 0, -d / 2], [w / 2, 0, d / 2], [-w / 2, 0, d / 2]], np.float64)
        apex = np.array([0.0, h, 0.0])
        out = [(b.copy(), np.array([0.0, -1.0, 0.0]))]
        for i in range(4):
            tri = np.array([b[i], apex, b[(i + 1) % 4]])
            nn = _normal(tri)
            mid = (b[i] + b[(i + 1) % 4]) / 2
            if nn @ mid < 0:
                tri, nn = tri[::-1], -nn
            out.append((tri, nn))
        return out
    if kind == "ramp":                                  # rises along +z: from the floor at -d/2 to h at +d/2
        z0, z1, x0, x1 = -d / 2, d / 2, -w / 2, w / 2
        slope = _quad((x0, 0, z0), (x0, h, z1), (x1, h, z1), (x1, 0, z0))
        out = [(slope, _normal(slope) if _normal(slope)[1] > 0 else -_normal(slope)),
               (_quad((x0, 0, z0), (x1, 0, z0), (x1, 0, z1), (x0, 0, z1)), np.array([0.0, -1.0, 0.0])),
               (_quad((x0, 0, z1), (x1, 0, z1), (x1, h, z1), (x0, h, z1)), np.array([0.0, 0.0, 1.0])),
               (np.array([[x0, 0, z0], [x0, 0, z1], [x0, h, z1]], np.float64), np.array([-1.0, 0.0, 0.0])),
               (np.array([[x1, 0, z0], [x1, h, z1], [x1, 0, z1]], np.float64), np.array([1.0, 0.0, 0.0]))]
        return out
    if kind == "stairs":                                # ``steps`` boxes rising along +z
        n = max(1, int(steps))
        out = []
        for k in range(n):
            za = -d / 2 + d * k / n
            out += _box(-w / 2, w / 2, 0.0, h * (k + 1) / n, za, d / 2 if k == n - 1 else -d / 2 + d * (k + 1) / n)
        return out
    raise ValueError(f"unknown shape {kind}")


def place(faces: List[Face], at, yaw: float = 0.0) -> List[Face]:
    R = _rot_y(yaw)
    t = np.asarray(at, np.float64)
    return [(p @ R + t, n @ R) for p, n in faces]


def faces(kind: str, size, at, yaw: float = 0.0, sides: int = 16, steps: int = 8) -> List[Face]:
    return place(local_faces(kind, size, sides, steps), at, yaw)


def from_points(kind: str, points: Sequence, height: float, sides: int = 24) -> List[Face]:
    """A shape drawn by points (engine): see the module text.  The base stands on the lowest point."""
    pts = [np.asarray(p, np.float64) for p in points]
    if kind == "polygon":
        if len(pts) < 3:
            raise ValueError("mark at least three points for the outline")
        y0 = min(p[1] for p in pts)
        o = np.array([[p[0], p[2]] for p in pts])
        return prism(o, y0, y0 + float(height))
    if len(pts) < 2:
        raise ValueError("mark two points")
    a, b = pts[0], pts[1]
    y0 = min(a[1], b[1])
    if kind == "rect":
        x0, x1 = sorted((a[0], b[0]))
        z0, z1 = sorted((a[2], b[2]))
        if x1 - x0 < 1 or z1 - z0 < 1:
            raise ValueError("the two corners must not be in a line")
        return _box(x0, x1, y0, y0 + float(height), z0, z1)
    if kind == "circle":
        r = float(np.hypot(*(b - a)[[0, 2]]))
        if r < 1:
            raise ValueError("the edge point is on the centre")
        ring = _ring(r, r, max(3, int(sides)), 0.0)[:, [0, 2]] + a[[0, 2]]
        return prism(ring, a[1] if True else y0, a[1] + float(height))
    raise ValueError(f"unknown shape {kind}")


def triangles(faces_: List[Face]) -> np.ndarray:
    """(n, 3, 3) triangles of the faces (fans)."""
    out = []
    for p, _n in faces_:
        for k in range(1, len(p) - 1):
            out.append([p[0], p[k], p[k + 1]])
    return np.asarray(out, np.float64).reshape(-1, 3, 3)


def edges(faces_: List[Face]) -> np.ndarray:
    """(n, 2, 3) outline segments of the faces (for a wire preview)."""
    out = []
    for p, _n in faces_:
        for k in range(len(p)):
            out.append([p[k], p[(k + 1) % len(p)]])
    return np.asarray(out, np.float64).reshape(-1, 2, 3)
