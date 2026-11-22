"""Collision boxes that follow the shape of a mesh, and finding what has no collision.

One box around a whole object is fine for a crate, but a railing that turns a corner, or a mesh made of many railings far
apart (the maps merge them by texture), gets a huge box that blocks the whole street.  ``fit`` follows the mesh instead:

* it splits the triangles in their separate pieces (triangles that touch);
* a flat piece (a railing, a fence, a sign) gets one thin box, turned like the piece;
* a piece made of several flat sides that do not enclose anything (an L or U shaped railing, a fence round a roof) gets
  one thin box per side;
* a solid piece (closed, or that covers its own footprint: a crate, a column) gets one box turned to fit it best.

Boxes only ever turn about the vertical axis, like the ones of the shipped maps.

    fit(tris, thickness, min_height, max_boxes)  -> [(centre, half, axes)]
    coverage(opt, hm, tris)                      -> 0..1: how much of those triangles already has collision
"""
from __future__ import annotations

from typing import Dict, List, Sequence, Tuple

import numpy as np

Box = Tuple[np.ndarray, np.ndarray, np.ndarray]


# ------------------------------------------------------------------------------------------------ pieces
def _components(tris: np.ndarray, key_round: float = 0.5) -> List[np.ndarray]:
    """Indices of the triangles of each connected piece (corners within ``key_round`` units are the same point)."""
    n = len(tris)
    if not n:
        return []
    keys = np.round(tris.reshape(-1, 3) / key_round).astype(np.int64)
    _u, inv = np.unique(keys, axis=0, return_inverse=True)
    inv = inv.reshape(-1)
    parent = list(range(len(_u)))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for t in inv.reshape(n, 3):
        a = find(int(t[0]))
        for b in t[1:]:
            b = find(int(b))
            if b != a:
                parent[b] = a
    groups: Dict[int, list] = {}
    for i, t in enumerate(inv.reshape(n, 3)):
        groups.setdefault(find(int(t[0])), []).append(i)
    return [np.asarray(g, np.int64) for g in groups.values()]


def _normals(tris: np.ndarray):
    g = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    ln = np.linalg.norm(g, axis=1)
    return g / np.maximum(ln, 1e-12)[:, None], ln / 2


def _planes(tris: np.ndarray, angle: float = 12.0, gap: float = 6.0) -> List[np.ndarray]:
    """Group triangles that lie on the same plane (either side): normals within ``angle`` degrees and within ``gap`` units
    of each other.  Returns index arrays, biggest area first."""
    nrm, area = _normals(tris)
    order = np.argsort(-area)
    cos = np.cos(np.radians(angle))
    groups: List[list] = []
    refs: List[Tuple[np.ndarray, float]] = []
    cen = tris.mean(1)
    for i in order:
        if area[i] < 1e-6:
            continue
        n = nrm[i]
        for g, (rn, rd) in zip(groups, refs):
            if abs(float(n @ rn)) >= cos and abs(float(cen[i] @ rn) - rd) <= gap and \
               all(abs(float(p @ rn) - rd) <= gap for p in tris[i]):
                g.append(i)
                break
        else:
            groups.append([i])
            refs.append((n, float(cen[i] @ n)))
    return [np.asarray(g, np.int64) for g in groups]


# ------------------------------------------------------------------------------------------------ boxes
def _yaw_axes(a: float) -> np.ndarray:
    c, s = np.cos(a), np.sin(a)
    return np.array([[c, 0.0, s], [0.0, 1.0, 0.0], [-s, 0.0, c]])


def _cross2(a, b) -> float:
    return float(a[0] * b[1] - a[1] * b[0])


def _hull2(p: np.ndarray) -> np.ndarray:
    p = np.unique(np.round(p, 3), axis=0)
    if len(p) < 3:
        return p
    p = p[np.lexsort((p[:, 1], p[:, 0]))]

    def half(pts):
        h = []
        for q in pts:
            while len(h) >= 2 and _cross2(h[-1] - h[-2], q - h[-2]) <= 0:
                h.pop()
            h.append(q)
        return h
    lower, upper = half(p), half(p[::-1])
    return np.array(lower[:-1] + upper[:-1])


def oriented_box(points: np.ndarray, thickness: float = 10.0, min_height: float = 0.0) -> Box:
    """The box turned about the vertical axis with the smallest footprint around ``points`` (engine).  No side thinner than
    ``thickness``; at least ``min_height`` tall (grown upwards)."""
    p = np.asarray(points, np.float64).reshape(-1, 3)
    xz = p[:, [0, 2]]
    h = _hull2(xz)
    best = (np.inf, 0.0)
    angles = [0.0]
    if len(h) >= 2:
        e = np.roll(h, -1, 0) - h
        angles += list(np.arctan2(e[:, 1], e[:, 0]))
    for a in angles:
        ax = _yaw_axes(a)
        loc = p @ ax.T
        ext = loc.max(0) - loc.min(0)
        area = max(ext[0], 1e-3) * max(ext[2], 1e-3)
        if area < best[0] - 1e-6:
            best = (area, a)
    ax = _yaw_axes(best[1])
    loc = p @ ax.T
    lo, hi = loc.min(0), loc.max(0)
    if hi[1] - lo[1] < min_height:
        hi[1] = lo[1] + min_height
    half = np.maximum((hi - lo) / 2, thickness / 2)
    centre = ((lo + hi) / 2) @ ax
    return centre, half, ax


def _solid(tris: np.ndarray, box: Box) -> bool:
    """A piece that fills its box: its triangles seen from above cover most of the footprint, and it is not one flat side."""
    _c, half, _ax = box
    foot = 4 * half[0] * half[2]
    nrm, area = _normals(tris)
    top = float((area * np.abs(nrm[:, 1])).sum()) / 2         # closed things count their top and bottom
    return foot > 0 and top >= 0.45 * foot


def fit(tris, thickness: float = 10.0, min_height: float = 0.0, max_boxes: int = 64, flat_thin: float = 40.0) -> List[Box]:
    """Boxes following the shape of the triangles ``tris`` (n, 3, 3) (engine).  See the module text."""
    tris = np.asarray(tris, np.float64).reshape(-1, 3, 3)
    if not len(tris):
        return []
    out: List[Box] = []
    pieces = sorted(_components(tris), key=lambda g: -len(g))
    for g in pieces:
        t = tris[g]
        box = oriented_box(t, thickness, min_height)
        if min(box[1][0], box[1][2]) * 2 <= flat_thin or _solid(t, box):
            out.append(box)                                     # thin already (one flat side), or solid
            continue
        sides = _planes(t)
        if len(sides) <= 1:
            out.append(box)
            continue
        for s in sides:
            out.append(oriented_box(t[s], thickness, min_height))
    if len(out) > max_boxes:                                    # too many: the biggest pieces get their own, the rest one
        vol = [float(np.prod(b[1])) for b in out]
        keep = sorted(range(len(out)), key=lambda i: -vol[i])[: max_boxes - 1]
        rest = [i for i in range(len(out)) if i not in keep]
        pts = []
        for i in rest:
            c, h, ax = out[i]
            pts.append(np.array([[x, y, z] for x in (-h[0], h[0]) for y in (-h[1], h[1]) for z in (-h[2], h[2])]) @ ax + c)
        out = [out[i] for i in keep] + [oriented_box(np.concatenate(pts), thickness, min_height)]
    return out


# ------------------------------------------------------------------------------------------------ what has collision
def _samples(tris: np.ndarray, per: int = 1) -> np.ndarray:
    c = tris.mean(1)
    pts = [c]
    for k in range(3):                                          # towards each corner: long thin triangles too
        pts.append(c * 0.4 + tris[:, k] * 0.6)
    return np.concatenate(pts)


def coverage(opt, hm, tris, pad: float = 15.0, boxes=None, walls=None) -> float:
    """Share (0..1) of the points of ``tris`` that lie inside a collision box of the map or next to a wall face of its
    height map (within ``pad`` units)."""
    tris = np.asarray(tris, np.float64).reshape(-1, 3, 3)
    if not len(tris):
        return 1.0
    pts = _samples(tris)
    hit = np.zeros(len(pts), bool)
    lo_p, hi_p = pts.min(0) - pad, pts.max(0) + pad
    for c, half, R in (boxes if boxes is not None else map_boxes(opt)):
        r = np.abs(R).T @ half
        if np.any(c + r < lo_p) or np.any(c - r > hi_p):
            continue
        loc = (pts - c) @ np.linalg.inv(R)
        hit |= np.all(np.abs(loc) <= half + pad, axis=1)
    for n, d, lo, hi in (walls if walls is not None else map_faces(hm)):
        if np.any(hi + pad < lo_p) or np.any(lo - pad > hi_p):
            continue
        near = np.abs(pts @ n - d) <= pad
        near &= np.all((pts >= lo - pad) & (pts <= hi + pad), axis=1)
        hit |= near
    return float(hit.mean())


def map_boxes(opt) -> List[Box]:
    from . import crop
    out = []
    if opt is None:
        return out
    for raw in crop.read_block(opt).boxes:
        a = np.frombuffer(raw, "<f4", 19).astype(np.float64)
        out.append((a[12:15].copy(), np.abs(a[16:19]), a[:16].reshape(4, 4)[:3, :3].copy()))
    return out


def map_faces(hm, walls_only: bool = True) -> list:
    """(normal, distance, lo, hi) of the wall faces of a height map (``walls_only`` False: floors and ceilings too)."""
    from . import hmcopy
    out = []
    if hm is None:
        return out
    for f in hmcopy.unique_faces(hm):
        if not f.contours:
            continue
        p = np.concatenate(f.contours).astype(np.float64)
        if len(p) < 3:
            continue
        n = np.zeros(3)
        for c in f.contours:                                    # Newell: works whatever way the face winds
            c = np.asarray(c, np.float64)
            q = np.roll(c, -1, 0)
            n += np.array([((c[:, 1] - q[:, 1]) * (c[:, 2] + q[:, 2])).sum(),
                           ((c[:, 2] - q[:, 2]) * (c[:, 0] + q[:, 0])).sum(),
                           ((c[:, 0] - q[:, 0]) * (c[:, 1] + q[:, 1])).sum()])
        ln = np.linalg.norm(n)
        if ln < 1e-9:
            continue
        n /= ln
        if walls_only and abs(n[1]) > 0.7:
            continue
        out.append((n, float(p.mean(0) @ n), p.min(0), p.max(0)))
    return out


def corners(box: Box) -> np.ndarray:
    c, h, ax = box
    return np.array([[x, y, z] for x in (-h[0], h[0]) for y in (-h[1], h[1]) for z in (-h[2], h[2])]) @ ax + c


def profile_boxes(tris, slices: int = 16, merge: float = 0.12, thickness: float = 10.0) -> List[Box]:
    """Boxes that follow the side profile of a long object (a car, a van, a bus): cut along its length into ``slices``,
    each piece a box from its lowest to its highest point, as wide as it is there; pieces next to each other that are
    nearly the same (within ``merge`` of its height / width) become one.  The bonnet and the boot stay low and the
    cabin high: one sees - and shoots - over the low parts, as over a real car.  ``tris`` (n, 3, 3) engine."""
    t = np.asarray(tris, np.float64).reshape(-1, 3, 3)
    if not len(t):
        return []
    c0, h0, ax = oriented_box(t, thickness)
    long_i = 0 if h0[0] >= h0[2] else 2
    side_i = 2 - long_i
    length = 2 * h0[long_i]
    step = max(length / slices, 1.0)
    # triangles cut into small ones, so a long flat roof counts in every piece it covers
    pts = []
    work = [t]
    for _ in range(12):
        cur = work.pop() if work else None
        if cur is None:
            break
        e = np.max(np.linalg.norm(cur - np.roll(cur, 1, axis=1), axis=2), axis=1)
        small = cur[e <= step * 0.5]
        big = cur[e > step * 0.5]
        if len(small):
            pts.append(small.reshape(-1, 3))
            pts.append(small.mean(1))
        if not len(big):
            break
        a, b, c = big[:, 0], big[:, 1], big[:, 2]
        ab, bc, ca = (a + b) / 2, (b + c) / 2, (c + a) / 2
        work.append(np.concatenate([np.stack([a, ab, ca], 1), np.stack([ab, b, bc], 1), np.stack([ca, bc, c], 1),
                                    np.stack([ab, bc, ca], 1)]))
    if work:
        pts.append(work[-1].reshape(-1, 3))
    P = np.concatenate(pts)
    loc = P @ ax.T
    lo_l = loc[:, long_i].min()
    k = np.clip(((loc[:, long_i] - lo_l) / step).astype(int), 0, slices - 1)
    pieces = []
    for s in range(slices):
        q = loc[k == s]
        if not len(q):
            continue
        pieces.append([lo_l + s * step, lo_l + (s + 1) * step, q[:, 1].min(), q[:, 1].max(),
                       q[:, side_i].min(), q[:, side_i].max()])
    if not pieces:
        return [(c0, h0, ax)]
    height = max(p[3] for p in pieces) - min(p[2] for p in pieces)
    width = max(p[5] for p in pieces) - min(p[4] for p in pieces)
    merged = [pieces[0]]
    for p in pieces[1:]:
        m = merged[-1]
        if (abs(p[3] - m[3]) <= merge * height and abs(p[2] - m[2]) <= merge * height
                and abs(p[4] - m[4]) <= merge * width and abs(p[5] - m[5]) <= merge * width and abs(p[0] - m[1]) < 1e-6):
            m[1] = p[1]
            m[2], m[3] = min(m[2], p[2]), max(m[3], p[3])
            m[4], m[5] = min(m[4], p[4]), max(m[5], p[5])
        else:
            merged.append(list(p))
    out = []
    for l0, l1, y0, y1, s0, s1 in merged:
        lo = np.zeros(3)
        hi = np.zeros(3)
        lo[long_i], hi[long_i] = l0, l1
        lo[1], hi[1] = y0, y1
        lo[side_i], hi[side_i] = s0, s1
        half = np.maximum((hi - lo) / 2, thickness / 2)
        out.append((((lo + hi) / 2) @ ax, half, ax))
    return out
