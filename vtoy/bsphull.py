"""The real player collision of a Half-Life / CS 1.6 map: its clip hull.

A .bsp keeps the walls the player bumps into in "clip hulls" (hull 1 = a standing player): the solid brushes of the map
INCLUDING the invisible CLIP brushes the mapper added (stairs smoothed into ramps, walls you cannot climb, the edges of the
map), every one grown by the player's box (32 x 32 x 72 units).  ``walls`` cuts the hull back into the surfaces of the
solid as the player meets them, in the map's own units:

    walls(bsp_bytes, model=0)  -> [(polygon (n,3), outward unit normal)]
"""
from __future__ import annotations

import struct
from typing import List, Optional, Sequence, Tuple

import numpy as np

HULL1 = np.array([16.0, 16.0, 36.0])          # half size of the standing player's box in CS
EPS = 0.01
SOLID = -2



def _lumps(data: bytes):
    out = []
    for i in range(15):
        off, ln = struct.unpack_from("<ii", data, 4 + 8 * i)
        out.append(data[off:off + ln])
    return out


def _box_poly(lo, hi) -> List[Tuple[np.ndarray, np.ndarray]]:
    x0, y0, z0 = lo
    x1, y1, z1 = hi
    P = lambda *a: np.array(a, np.float64)
    return [(P((x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)), P(0, 0, 1)),
            (P((x0, y0, z0), (x0, y1, z0), (x1, y1, z0), (x1, y0, z0)), P(0, 0, -1)),
            (P((x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1)), P(0, -1, 0)),
            (P((x0, y1, z0), (x0, y1, z1), (x1, y1, z1), (x1, y1, z0)), P(0, 1, 0)),
            (P((x0, y0, z0), (x0, y0, z1), (x0, y1, z1), (x0, y1, z0)), P(-1, 0, 0)),
            (P((x1, y0, z0), (x1, y1, z0), (x1, y1, z1), (x1, y0, z1)), P(1, 0, 0))]


def _clip_poly(p: np.ndarray, n: np.ndarray, d: float):
    """The part of polygon p with n.x - d <= 0 (behind the plane), and the points lying on the plane."""
    s = p @ n - d
    out, on = [], []
    k = len(p)
    for i in range(k):
        j = (i + 1) % k
        a, b, sa, sb = p[i], p[j], s[i], s[j]
        if sa <= EPS:
            out.append(a)
            if sa >= -EPS:
                on.append(a)
        if (sa > EPS and sb < -EPS) or (sa < -EPS and sb > EPS):
            q = a + (b - a) * (sa / (sa - sb))
            out.append(q)
            on.append(q)
    return (np.array(out) if len(out) >= 3 else None), on


def _order_cap(points: Sequence[np.ndarray], n: np.ndarray) -> Optional[np.ndarray]:
    """The points of a cut, as a convex polygon wound anticlockwise seen from n."""
    if len(points) < 3:
        return None
    P = np.unique(np.round(np.array(points), 4), axis=0)
    if len(P) < 3:
        return None
    c = P.mean(0)
    u = P[0] - c
    if np.linalg.norm(u) < 1e-9:
        u = P[1] - c
    u /= np.linalg.norm(u)
    v = np.cross(n, u)
    ang = np.arctan2((P - c) @ v, (P - c) @ u)
    return P[np.argsort(ang)]


def split(poly, n: np.ndarray, d: float):
    """A convex polyhedron (list of (polygon, normal)) cut by the plane n.x = d: (back part, front part), None if empty.
    The new faces on the plane have normals +n (back part) / -n (front part)."""
    back, front, on = [], [], []
    for p, fn in poly:
        b, o = _clip_poly(p, n, d)
        f, _o = _clip_poly(p, -n, -d)
        if b is not None:
            back.append((b, fn))
        if f is not None:
            front.append((f, fn))
        on += o
    cap = _order_cap(on, n)
    if cap is not None and len(back) and len(front):
        # a cap needs area to count
        area = np.linalg.norm(sum(np.cross(cap[k] - cap[0], cap[k + 1] - cap[0]) for k in range(1, len(cap) - 1)))
        if area > 1e-4:
            back.append((cap, n.copy()))
            front.append((cap[::-1].copy(), -n))
    return (back if len(back) >= 4 else None), (front if len(front) >= 4 else None)


class Hull:
    def __init__(self, data: bytes):
        L = _lumps(data)
        self.planes = np.frombuffer(L[1], np.dtype([("n", "<f4", 3), ("d", "<f4"), ("t", "<i4")]))
        self.clip = np.frombuffer(L[9], np.dtype([("plane", "<i4"), ("c", "<i2", 2)]))
        self.models = np.frombuffer(L[14], np.dtype([("mins", "<f4", 3), ("maxs", "<f4", 3), ("origin", "<f4", 3),
                                                     ("head", "<i4", 4), ("vis", "<i4"), ("first", "<i4"), ("n", "<i4")]))

    def contents(self, node: int, p: np.ndarray) -> int:
        while node >= 0:
            c = self.clip[node]
            pl = self.planes[c["plane"]]
            node = int(c["c"][0] if float(p @ pl["n"]) - float(pl["d"]) >= 0 else c["c"][1])
        return node


def _clip_keep(p: np.ndarray, n: np.ndarray, d: float, keep_back: bool):
    q, _on = _clip_poly(p, n if keep_back else -n, d if keep_back else -d)
    return q


def _fragments(h: "Hull", node: int, p: np.ndarray, out: list) -> None:
    """Pieces of the polygon p by the contents of the hull leaf they lie in: [(piece, contents)]."""
    stack = [(node, p)]
    while stack:
        nd, q = stack.pop()
        if nd < 0:
            out.append((q, nd))
            continue
        c = h.clip[nd]
        pl = h.planes[c["plane"]]
        n = pl["n"].astype(np.float64)
        d = float(pl["d"])
        s = q @ n - d
        if s.min() >= -EPS:
            stack.append((int(c["c"][0]), q))
        elif s.max() <= EPS:
            stack.append((int(c["c"][1]), q))
        else:
            f = _clip_keep(q, n, d, False)
            b = _clip_keep(q, n, d, True)
            if f is not None:
                stack.append((int(c["c"][0]), f))
            if b is not None:
                stack.append((int(c["c"][1]), b))


def _plane_square(c: np.ndarray, n: np.ndarray, r: float) -> np.ndarray:
    """A square of half size r in the plane through c with normal n, wound anticlockwise seen from n."""
    u = np.cross(n, [0.0, 0.0, 1.0] if abs(n[2]) < 0.9 else [1.0, 0.0, 0.0])
    u /= np.linalg.norm(u)
    v = np.cross(n, u)
    return np.array([c + r * (u * x + v * y) for x, y in ((-1, -1), (1, -1), (1, 1), (-1, 1))])


FLOOR_NZ = 0.7                 # a face this flat (or flatter) is a floor: the compiler grows it straight up


def back_offset(n: np.ndarray, half: np.ndarray) -> np.ndarray:
    """How a hull face is moved back onto the map's real surface.  Measured on the compiled maps: a floor or a slope a
    player stands on is grown straight up by the box's height (36: the feet touch the surface whatever the slope), walls
    and steeper faces by the box's support along their normal (16 for a wall)."""
    if n[2] >= FLOOR_NZ:
        return np.array([0.0, 0.0, -float(half[2])])
    if n[2] <= -FLOOR_NZ:
        return np.array([0.0, 0.0, float(half[2])])
    return -n * float(np.abs(n) @ half)


def _neighbour_normal(h: "Hull", head: int, mid: np.ndarray, mdir: np.ndarray, n: np.ndarray, kind: int,
                      r: float = 6.0, deep: float = 80.0) -> np.ndarray:
    """Outward normal of the hull surface on the other side of an edge, felt with the hull itself: ``r`` units past
    the edge, how far down (the surface turns away, ``kind`` < 0) or up (it meets more solid, ``kind`` > 0) the surface
    is there."""
    x = mid + mdir * r
    if kind < 0:
        def solid(sv):
            return h.contents(head, x - n * sv) == SOLID
    else:
        def solid(sv):
            return h.contents(head, x + n * sv) != SOLID
    # the first change within ``deep`` (not just "is it solid that deep": a floor a few units thick over a cavity -
    # a bridge, a slab over a tunnel - has empty space under it again)
    step = 8.0                                                 # a slab in the hull is never that thin: it is grown too
    hi = None
    sv = step
    while sv <= deep + 1e-6:
        if solid(sv):
            hi = sv
            break
        sv += step
    if hi is None:
        return mdir.copy() if kind < 0 else -mdir.copy()       # a sheer drop / a wall rising past the probe: a wall
    lo = hi - step
    for _ in range(12):
        m = (lo + hi) / 2
        if solid(m):
            hi = m
        else:
            lo = m
    sv = hi
    g = (n * r + mdir * sv) if kind < 0 else (n * r - mdir * sv)
    return g / max(float(np.linalg.norm(g)), 1e-12)


def _edge_cuts(h: "Hull", head: int, q: np.ndarray, n: np.ndarray, half: np.ndarray, probe: float, may_split: bool,
               ctx=None):
    """Each edge of the hull face q moved by the box's reach across it: in where the surface turns away (convex: the
    top of a step), out where it meets more solid (concave: a wall standing on a floor, which then reaches the floor),
    left where the same surface goes on.  -> ([(in-plane outward direction, offset)], None), or (None, split plane)
    when that changes along an edge (a floor running along a wall that ends half way): q is then cut in two there."""
    k = len(q)
    cuts = []
    centre = q.mean(0)
    for i in range(k):
        a, b = q[i], q[(i + 1) % k]
        e = b - a
        L = float(np.linalg.norm(e))
        if L < 1e-6:
            continue
        u = e / L
        mdir = np.cross(u, n)                                  # in the face's plane, pointing away from the polygon
        if float(mdir @ (centre - (a + b) / 2)) > 0:
            mdir = -mdir

        def kind(t):
            beyond = a + e * t + mdir * probe
            if h.contents(head, beyond + n * probe) == SOLID:
                return 1                                       # concave
            if h.contents(head, beyond - n * probe) != SOLID:
                return -1                                      # convex
            return 0
        m = max(1, min(64, int(L / 4.0)))
        ts = [(j + 0.5) / m for j in range(m)]
        ks = [kind(t) for t in ts]
        if may_split and len(set(ks)) > 1:
            j = next(j for j in range(m - 1) if ks[j] != ks[j + 1])
            lo, hi = ts[j], ts[j + 1]
            for _ in range(10):
                mid = (lo + hi) / 2
                if kind(mid) == ks[j]:
                    lo = mid
                else:
                    hi = mid
            t = (lo + hi) / 2
            if 0.3 < t * L < L - 0.3:
                x = a + e * t
                return None, (u, float(x @ u))
        kd = max(set(ks), key=ks.count)
        reach = float(np.abs(mdir) @ half)
        shift = kd * reach
        mid_e = (a + b) / 2
        if kd != 0 and ctx is not None:                        # exactly: from the surface across the edge
            ng = _neighbour_normal(h, head, mid_e, mdir, n, kd)
            if n[2] >= FLOOR_NZ and ng[2] >= FLOOR_NZ:         # floor to floor / slope: both grown straight up, the
                shift = 0.0                                    # edge they share in the hull is where they meet
            else:                                              # the probe only feels the grown hull's corner:
                if ng[2] >= FLOOR_NZ:                          # the other side is a floor - taken as level - or a wall
                    ng = np.array([0.0, 0.0, 1.0])
                elif ng[2] <= -FLOOR_NZ:
                    ng = np.array([0.0, 0.0, -1.0])
                elif abs(ng[2]) < 0.5:
                    hz = np.array([ng[0], ng[1], 0.0])
                    if np.linalg.norm(hz) > 1e-6:
                        ng = hz / np.linalg.norm(hz)
            if not (n[2] >= FLOOR_NZ and ng[2] >= FLOOR_NZ) and abs(float(ng @ mdir)) > 0.2:
                vf, vg = back_offset(n, half), back_offset(ng, half)
                t = float(ng @ (vg - vf)) / float(ng @ mdir)
                if abs(t) <= 2.0 * float(half.max()):
                    shift = t
        if kd == 0:                                            # the surface goes on in the next piece: if it turns away
            shift = _far_edge_trim(h, head, mid_e, mdir, n, reach, probe)   # nearer than the box, trim here too
        cuts.append((mdir, float(((a + b) / 2) @ mdir) + shift, kd, reach, b))
    return cuts, None


def _far_edge_trim(h: "Hull", head: int, x: np.ndarray, mdir: np.ndarray, n: np.ndarray, reach: float,
                   probe: float) -> float:
    """The tree cuts one face into pieces: the surface may go on past this piece's edge for less than the box and then
    turn away (a thin board's side cut in two) - the trim of that far edge then reaches into this piece.  -> the shift of
    this edge (0, or negative: inwards)."""
    def surface(t):
        q = x + mdir * t
        return h.contents(head, q - n * probe) == SOLID and h.contents(head, q + n * probe) != SOLID
    if surface(reach):
        return 0.0
    lo, hi = 0.0, reach
    for _ in range(8):
        mid = (lo + hi) / 2
        if surface(mid):
            lo = mid
        else:
            hi = mid
    q = x + mdir * (hi + probe)
    if h.contents(head, q + n * probe) == SOLID:              # it meets more solid there: nothing to trim
        return 0.0
    if n[2] >= FLOOR_NZ:                                       # a floor going on as a gentle slope: nothing to trim
        ng = _neighbour_normal(h, head, x + mdir * lo, mdir, n, -1)
        if ng[2] >= FLOOR_NZ:
            return 0.0
    return min(0.0, lo - reach)


def _notch_corner(h: "Hull", head: int, cuts, n: np.ndarray, probe: float):
    """A corner of the face where the surface goes on across both edges but not across the corner itself - the corner
    of a hole in a floor, of a doorway in a wall: the grown hull keeps a box-sized square there that is really part of
    the hole.  -> ((m1, d1), (m2, d2)): the square is where m1.x > d1 and m2.x > d2; None when there is no such corner."""
    k = len(cuts)
    for i in range(k):
        m1, _d1, k1, r1, v = cuts[i]
        m2, _d2, k2, r2, _b = cuts[(i + 1) % k]
        if k1 != 0 or k2 != 0 or abs(float(m1 @ m2)) > 0.2:
            continue
        diag = v + (m1 + m2) * probe
        if h.contents(head, diag - n * probe) != SOLID:
            return (m1, float(v @ m1) - r1), (m2, float(v @ m2) - r2)
    return None


def walls(data: bytes, model: int = 0, hull: int = 1, half=HULL1) -> List[Tuple[np.ndarray, np.ndarray]]:
    """The surfaces of the map's solid as the player meets them in CS: [(polygon (n,3), outward normal)].

    The clip hull is the solid grown by the player's box.  Its boundary - the faces of its solid pieces where the other
    side is empty, cut exactly by the tree - is moved back onto the real surface: walls by the box along their normal
    (16), floors and slopes a player stands on straight down by 36 (the compiler grows those straight up, so a ramp comes
    back where it is drawn, meeting the floor without a gap).  Each edge is then moved by what the surface across it
    needs (felt with the hull): a step's riser ends at the step, walls reach down to the floor, floors reach the walls,
    a floor running into a slope meets it.  Invisible CLIP brushes come out as well (stairs as ramps, clip walls)."""
    h = Hull(data)
    m = h.models[model]
    head = int(m["head"][hull])
    if head < 0 or not len(h.clip):
        return []
    half = np.asarray(half, np.float64)
    lo0 = m["mins"].astype(np.float64) - 64.0
    hi0 = m["maxs"].astype(np.float64) + 64.0
    pieces = []
    stack = [(head, _box_poly(lo0, hi0))]
    while stack:
        node, poly = stack.pop()
        if node < 0:
            if node == SOLID:
                pieces.append(poly)
            continue
        c = h.clip[node]
        pl = h.planes[c["plane"]]
        back, front = split(poly, pl["n"].astype(np.float64), float(pl["d"]))
        if front is not None:
            stack.append((int(c["c"][0]), front))
        if back is not None:
            stack.append((int(c["c"][1]), back))
    out = []
    probe = 0.5
    for own, poly in enumerate(pieces):
        for p, n in poly:
            c = p.mean(0)
            if np.any(np.abs(c - lo0) < 0.5) or np.any(np.abs(c - hi0) < 0.5):
                continue                                       # the margin round the model
            frags = []
            _fragments(h, head, p + n * probe, frags)
            for q, cont in frags:
                if cont == SOLID or len(q) < 3:
                    continue
                todo, splits = [q - n * probe], 0              # back onto the hull's surface
                while todo:
                    q = todo.pop()
                    cuts, cut_at = _edge_cuts(h, head, q, n, half, probe, splits < 48, True)
                    if cut_at is not None:                     # what lies across one edge changes along it: in two
                        splits += 1
                        for keep_back in (True, False):
                            g = _clip_keep(q, cut_at[0], cut_at[1], keep_back)
                            if g is not None and len(g) >= 3:
                                todo.append(g)
                        continue
                    corner = _notch_corner(h, head, cuts, n, probe) if splits < 48 else None
                    if corner is not None:                     # a hole's corner: the hull fills a box-sized square
                        splits += 1                            # there that is not floor / wall: cut it off
                        (m1, d1), (m2, d2) = corner
                        g = _clip_keep(q, m1, d1, True)
                        if g is not None and len(g) >= 3:
                            todo.append(g)
                        g = _clip_keep(q, m1, d1, False)
                        if g is not None:
                            g = _clip_keep(g, m2, d2, True)
                        if g is not None and len(g) >= 3:
                            todo.append(g)
                        continue
                    g = _plane_square(q.mean(0), n, 1e5)
                    for mdir, dd, _k, _r, _b in cuts:
                        g = _clip_keep(g, mdir, dd, True)
                        if g is None:
                            break
                    lo_q, hi_q = q.min(0) - half - 1.0, q.max(0) + half + 1.0
                    for ax in range(3):                        # never further than the box's reach from the hull face
                        if g is None:
                            break
                        e_ax = np.eye(3)[ax]
                        g = _clip_keep(g, e_ax, float(hi_q[ax]), True)
                        if g is not None:
                            g = _clip_keep(g, e_ax, float(lo_q[ax]), False)
                    if g is None or len(g) < 3:
                        continue
                    g = g + back_offset(n, half)               # back onto the real surface
                    area = np.linalg.norm(sum(np.cross(g[j] - g[0], g[j + 1] - g[0]) for j in range(1, len(g) - 1)))
                    if area > 1.0:
                        out.append((g, n.copy()))
    return out
