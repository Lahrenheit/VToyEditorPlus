"""Bars, grilles and railings of a CS map that bullets fly through.

The collision of a map made from a .bsp comes from its clip hull (bsphull): the solid grown by the player's box.  In it
a gap narrower than the player - between the bars of a window, between the pipes of a railing - is filled, so the wall
made from it is a plain slab and stops bullets too (Torrente has one collision for players and bullets).  In CS bullets
trace the map's real solid (hull 0) and fly through those gaps.

``open_wall(...)`` cuts a hull wall into the parts of it that stay solid: everything but the gaps.  A gap is a spot on
the wall where hull 0 is empty right through the bars, with real solid on both sides of it closer than the player's
box (left and right of it: a gap between bars; above and below it: a gap between pipes).  An empty spot bounded by the
wall's own edge is not a gap - an invisible CLIP brush (over a low wall, at the edge of the map) stays solid.
Bars painted on a see-through face ("{" texture on a non-solid brush, a CLIP brush behind it: de_mirage_cs2's barred
window) count as solid where their picture is (Sheet).
"""
from __future__ import annotations

from typing import List, Optional, Tuple

import numpy as np

from . import bsphull

SOLID = -2
CELL = 2.0                    # CS units: the grid the wall is felt with (a bar is 2 or more)
GAP_W = 16.0                  # a gap between bars: narrower than a Torrente player (less than the 32 of the CS box,
                              # so a player never slips between posts)
GAP_H = 38.0                  # a gap between pipes is lower than the crouching player's box (36)
MIN_GAP = 48.0                # square CS units: smaller openings are left closed (and under 5 % of the wall)
MAX_PIECES = 400


class _Tree:
    """Point contents of one hull of a .bsp, many points at once."""

    def __init__(self, raw: bytes, hull: int):
        L = bsphull._lumps(raw)
        pl = np.frombuffer(L[1], np.dtype([("n", "<f4", 3), ("d", "<f4"), ("t", "<i4")]))
        self.N = pl["n"].astype(np.float64)
        self.D = pl["d"].astype(np.float64)
        self.models = np.frombuffer(L[14], np.dtype([("mins", "<f4", 3), ("maxs", "<f4", 3), ("origin", "<f4", 3),
                                                     ("head", "<i4", 4), ("vis", "<i4"), ("first", "<i4"), ("n", "<i4")]))
        self.hull = hull
        if hull == 0:
            nodes = np.frombuffer(L[5], np.dtype([("plane", "<i4"), ("c", "<i2", 2), ("mins", "<i2", 3),
                                                 ("maxs", "<i2", 3), ("ff", "<u2"), ("nf", "<u2")]))
            leafs = np.frombuffer(L[10], np.dtype([("contents", "<i4"), ("vis", "<i4"), ("mins", "<i2", 3),
                                                  ("maxs", "<i2", 3), ("fm", "<u2"), ("nm", "<u2"), ("amb", "u1", 4)]))
            self.leaf_contents = leafs["contents"].astype(np.int64)
        else:
            nodes = np.frombuffer(L[9], np.dtype([("plane", "<i4"), ("c", "<i2", 2)]))
        self.plane = nodes["plane"].astype(np.int64)
        self.c0 = nodes["c"][:, 0].astype(np.int64)
        self.c1 = nodes["c"][:, 1].astype(np.int64)

    def head(self, model: int) -> int:
        return int(self.models[model]["head"][self.hull])

    def contents(self, head: int, P: np.ndarray) -> np.ndarray:
        P = np.asarray(P, np.float64).reshape(-1, 3)
        node = np.full(len(P), head, np.int64)
        if head < 0:
            return node if self.hull else self.leaf_contents[-node - 1]
        act = np.arange(len(P))
        X, Y, Z = P[:, 0], P[:, 1], P[:, 2]
        while len(act):
            nd = node[act]
            pi = self.plane[nd]
            Nn = self.N[pi]
            front = X[act] * Nn[:, 0] + Y[act] * Nn[:, 1] + Z[act] * Nn[:, 2] - self.D[pi] >= 0
            new = np.where(front, self.c0[nd], self.c1[nd])
            node[act] = new
            act = act[new >= 0]
        return self.leaf_contents[-node - 1] if self.hull == 0 else node

    def solid(self, head: int, P: np.ndarray) -> np.ndarray:
        return self.contents(head, P) == SOLID


def _frame(n: np.ndarray):
    u = np.cross([0.0, 0.0, 1.0], n)
    if np.linalg.norm(u) < 1e-6:
        u = np.cross([1.0, 0.0, 0.0], n)
    u /= np.linalg.norm(u)
    v = np.cross(n, u)
    return u, v / np.linalg.norm(v)


def _inside(S: np.ndarray, T: np.ndarray, s: np.ndarray, t: np.ndarray, margin: float = 0.0) -> np.ndarray:
    """Points (s, t) inside the convex polygon (S, T) (either winding), ``margin`` in from its edges."""
    k = len(S)
    area = float(np.sum(S * np.roll(T, -1) - np.roll(S, -1) * T))
    sign = 1.0 if area >= 0 else -1.0
    ok = np.ones(np.broadcast(s, t).shape, bool)
    for i in range(k):
        a0, a1 = S[i], T[i]
        b0, b1 = S[(i + 1) % k], T[(i + 1) % k]
        L = np.hypot(b0 - a0, b1 - a1)
        if L < 1e-9:
            continue
        cr = ((b0 - a0) * (t - a1) - (b1 - a1) * (s - a0)) * sign / L
        ok &= cr >= margin - 1e-6
    return ok


def _clip(poly: np.ndarray, n: np.ndarray, d: float) -> Optional[np.ndarray]:
    """The part of the 2-D polygon where p.n <= d."""
    out = []
    k = len(poly)
    for i in range(k):
        a, b = poly[i], poly[(i + 1) % k]
        da, db = float(a @ n) - d, float(b @ n) - d
        if da <= 0:
            out.append(a)
        if (da < 0 < db) or (db < 0 < da):
            out.append(a + (b - a) * (da / (da - db)))
    return np.array(out) if len(out) >= 3 else None


def _bounded(state: np.ndarray, axis: int, reach: int) -> np.ndarray:
    """For each cell: is the first cell that is not open (state 0), going both ways along ``axis``, solid (state 1)
    within ``reach`` cells?  state: 0 open, 1 solid, 2 outside the wall."""
    out = []
    for step in (1, -1):
        found = np.zeros(state.shape, bool)
        hit = np.zeros(state.shape, bool)
        for k in range(1, reach + 1):
            sh = np.full(state.shape, 2, state.dtype)
            if axis == 0:
                if step > 0:
                    sh[:-k] = state[k:] if k < state.shape[0] else sh[:-k]
                else:
                    sh[k:] = state[:-k] if k < state.shape[0] else sh[k:]
            else:
                if step > 0:
                    sh[:, :-k] = state[:, k:] if k < state.shape[1] else sh[:, :-k]
                else:
                    sh[:, k:] = state[:, :-k] if k < state.shape[1] else sh[:, k:]
            new = ~found & (sh != 0)
            hit |= new & (sh == 1)
            found |= new
            if found.all():
                break
        out.append(hit)
    return out[0] & out[1]


def slab_depth(clip: _Tree, chead: int, q: np.ndarray, n: np.ndarray, half: np.ndarray) -> float:
    """How deep the real solid behind the wall q (on the map's surface) goes: the hull's thickness there less the box
    on both sides (felt at a few points of the wall, the deepest)."""
    sup = float(np.abs(n) @ half)
    c = q.mean(0)
    pts = [c] + [c + (p - c) * 0.7 for p in q]
    ds = np.arange(0.25, 160.0, 0.5)
    best = 0.0
    for p in pts:
        x = p + n * sup
        sol = clip.solid(chead, x[None] - n[None] * ds[:, None])
        if not sol[0]:
            continue
        k = int(np.argmin(sol)) if not sol.all() else len(ds)
        best = max(best, (ds[k - 1] if k else 0.0) - 2 * sup)
    return float(np.clip(best, 1.0, 48.0))


class Sheet:
    """A drawn face with a see-through texture ("{": a grille, a fence painted on one face): solid where its texture
    is (palette colour 255 is the hole) - CS maps often draw a window's bars so, on a non-solid brush, with an
    invisible CLIP brush to stop players."""

    def __init__(self, P, n, uv, mask):
        self.P = np.asarray(P, np.float64)
        self.n = np.asarray(n, np.float64) / max(np.linalg.norm(n), 1e-12)
        self.d = float(self.P[0] @ self.n)
        self.lo, self.hi = self.P.min(0), self.P.max(0)
        A = np.c_[self.P, np.ones(len(self.P))]
        self.M, *_ = np.linalg.lstsq(A, np.asarray(uv, np.float64), rcond=None)   # 3-D -> uv (affine)
        self.mask = mask                                                          # (h, w) bool: drawn
        u, v = _frame(self.n)
        self.u, self.v = u, v
        self.S, self.T = (self.P - self.P[0]) @ u, (self.P - self.P[0]) @ v

    def solid(self, X: np.ndarray, along: np.ndarray) -> np.ndarray:
        """Points X pushed along ``along`` onto the sheet: on it, where its texture is drawn?"""
        den = float(along @ self.n)
        if abs(den) < 1e-6:
            return np.zeros(len(X), bool)
        k = (self.d - X @ self.n) / den
        Y = X + np.outer(k, along)
        ok = np.all((Y >= self.lo - 0.01) & (Y <= self.hi + 0.01), 1)
        if not ok.any():
            return ok
        idx = np.nonzero(ok)[0]
        R = Y[idx] - self.P[0]
        ins = _inside(self.S, self.T, R @ self.u, R @ self.v)
        idx = idx[ins]
        out = np.zeros(len(X), bool)
        if len(idx):
            uv = np.c_[Y[idx], np.ones(len(idx))] @ self.M
            h, w = self.mask.shape
            tx = np.floor(np.mod(uv[:, 0], 1.0) * w).astype(np.int64) % w
            ty = np.floor(np.mod(uv[:, 1], 1.0) * h).astype(np.int64) % h
            out[idx] = self.mask[ty, tx]
        return out


def bsp_sheets(bsp) -> List[Sheet]:
    """The see-through faces the map draws ("{" textures with their picture in the .bsp)."""
    from . import bspimport, wad
    try:
        mips = {k.lower(): m for k, m in wad.bsp_embedded(bsp.raw).items()}
    except Exception:
        return []
    ents = bspimport.model_entities(bsp)
    shift = {}
    for m, e in ents.items():
        try:
            shift[m] = np.array([float(x) for x in e["origin"].split()]) if "origin" in e else np.zeros(3)
        except ValueError:
            shift[m] = np.zeros(3)
    masks = {}
    out = []
    for f in bspimport.drawn_faces(bsp):
        name = str(f.texture).lower()
        if not name.startswith("{") or len(f.points) < 3:
            continue
        e = ents.get(f.model) if f.model else None
        if e is not None and (bspimport._hidden(e) or bspimport.invisible_entity(e)):
            continue
        if name not in masks:
            m = mips.get(name)
            masks[name] = None if m is None else (m.rgba()[..., 3] > 0)
        mk = masks[name]
        if mk is None or not mk.any() or mk.all():
            continue
        P = np.asarray(f.points, np.float64) + shift.get(f.model, np.zeros(3))
        out.append(Sheet(P, f.normal, f.uv, mk))
    return out


def open_wall(solid0: _Tree, head0: int, clip: _Tree, chead: int, q: np.ndarray, n: np.ndarray, half,
              sheets=()) -> Optional[List[Tuple[np.ndarray, bool]]]:
    """The hull wall q (CS points on the map's surface, normal n) without its gaps: [(polygon, is a bar)] - a bar:
    a piece that does not reach the wall's bottom (a pipe, a bar's upper part), solid however low it is.  None when
    the wall has no gap (it stays as it is)."""
    q = np.asarray(q, np.float64)
    n = np.asarray(n, np.float64)
    n = n / max(np.linalg.norm(n), 1e-12)
    if abs(n[2]) >= 0.7 or len(q) < 3:
        return None
    half = np.asarray(half, np.float64)
    u, v = _frame(n)
    o = q[0]
    S, T = (q - o) @ u, (q - o) @ v
    s0, s1, t0, t1 = S.min(), S.max(), T.min(), T.max()
    if s1 - s0 < 3.0 or t1 - t0 < 3.0:
        return None
    depth = slab_depth(clip, chead, q, n, half)
    ds = np.arange(0.5, depth, 2.0) if depth > 1.0 else np.array([0.5])

    lo_q, hi_q = q.min(0) - depth - 2.0, q.max(0) + depth + 2.0
    near = [sh for sh in sheets if abs(float(sh.n @ n)) > 0.99 and np.all(sh.lo <= hi_q) and np.all(sh.hi >= lo_q)
            and -2.0 <= float(n @ q[0]) - sh.d * float(sh.n @ n) <= depth + 2.0]

    def solid_at(s, t):
        P = o + np.outer(s, u) + np.outer(t, v)
        hit = solid0.solid(head0, P - n * ds[0])           # most points: solid right at the surface
        todo = np.nonzero(~hit)[0]
        if len(todo) and len(ds) > 1:                       # the rest: all the depths in one go
            Q = (P[todo][:, None, :] - n[None, None, :] * ds[1:, None]).reshape(-1, 3)
            hit[todo] = solid0.solid(head0, Q).reshape(len(todo), len(ds) - 1).any(1)
        for sh in near:                                     # bars painted on a see-through face
            todo = np.nonzero(~hit)[0]
            if not len(todo):
                break
            got = np.zeros(len(todo), bool)
            for a, c in ((-0.6, -0.6), (0.6, 0.6), (-0.6, 0.6), (0.6, -0.6), (0.0, 0.0)):   # bars thinner than a cell
                got |= sh.solid(P[todo] + u * a + v * c, -n)
            hit[todo] = got
        return hit
    # a quick look first: any open spot well inside?
    gs, gt = np.meshgrid(np.arange(s0 + 2.0, s1 - 1.0, 4.0), np.arange(t0 + 2.0, t1 - 1.0, 4.0), indexing="ij")
    gs, gt = gs.ravel(), gt.ravel()
    ins = _inside(S, T, gs, gt, 2.0)
    if not ins.any():
        return None
    gs, gt = gs[ins], gt[ins]
    hit = solid_at(gs, gt)
    if hit.all():
        return None
    ext = int(np.ceil(max(GAP_W, GAP_H) / CELL)) + 1  # a ring round the wall: a window's frame, the next bars
                                                      # (the clip hull's tree cuts a window in several walls)
    s0, t0 = s0 - ext * CELL, t0 - ext * CELL
    ns, nt = int(np.ceil((s1 - s0) / CELL)) + ext, int(np.ceil((t1 - t0) / CELL)) + ext
    if ns * nt > 4_000_000:
        return None
    cs = s0 + (np.arange(ns) + 0.5) * CELL
    ct = t0 + (np.arange(nt) + 0.5) * CELL
    GS, GT = np.meshgrid(cs, ct, indexing="ij")
    inside = _inside(S, T, GS, GT)
    state = np.full(GS.shape, 2, np.int8)
    state[inside] = 1
    # felt finely only round the open spots (the rest of the wall was solid at every coarse point)
    os_, ot = gs[~hit], gt[~hit]
    reach = max(GAP_W, GAP_H) + 6.0
    win = (GS >= os_.min() - reach) & (GS <= os_.max() + reach) & (GT >= ot.min() - reach) & (GT <= ot.max() + reach)
    idx = np.nonzero(win & inside)
    sol = solid_at(GS[idx], GT[idx])
    if not sol.any():
        return None                                   # nothing real there at all: a CLIP brush, it stays
    state[idx] = np.where(sol, 1, 0)
    ring = np.nonzero(win & ~inside)                  # outside the wall: real solid (a frame) bounds a gap too
    if len(ring[0]):
        state[ring] = np.where(solid_at(GS[ring], GT[ring]), 1, 0)
    opened = state == 0
    gap = opened & (_bounded(state, 0, int(GAP_W / CELL)) | _bounded(state, 1, int(GAP_H / CELL)))
    if gap.sum() * CELL * CELL < MIN_GAP or (gap & inside).sum() < 0.05 * inside.sum():
        return None
    keep = inside & ~gap
    # the kept cells in rectangles: runs along s per row of t, joined with the same run in the next rows
    rects = []
    open_runs = {}
    for j in range(nt):
        col = keep[:, j]
        runs = []
        i = 0
        while i < ns:
            if col[i]:
                k = i
                while k + 1 < ns and col[k + 1]:
                    k += 1
                runs.append((i, k + 1))
                i = k + 1
            else:
                i += 1
        nxt = {}
        for r in runs:
            if r in open_runs:
                nxt[r] = (open_runs.pop(r)[0], j + 1)
            else:
                nxt[r] = (j, j + 1)
        for r, (a, b) in open_runs.items():
            rects.append((r[0], r[1], a, b))
        open_runs = nxt
    for r, (a, b) in open_runs.items():
        rects.append((r[0], r[1], a, b))
    if len(rects) > MAX_PIECES:
        return None
    poly2 = np.stack([S, T], 1)
    out = []
    for i0, i1, j0, j1 in rects:
        g = poly2
        for nn, dd in (((1.0, 0.0), s0 + i1 * CELL), ((-1.0, 0.0), -(s0 + i0 * CELL)),
                       ((0.0, 1.0), t0 + j1 * CELL), ((0.0, -1.0), -(t0 + j0 * CELL))):
            g = _clip(g, np.array(nn), dd)
            if g is None:
                break
        if g is None:
            continue
        a2 = 0.5 * abs(float(np.sum(g[:, 0] * np.roll(g[:, 1], -1) - np.roll(g[:, 0], -1) * g[:, 1])))
        if a2 < 0.25:
            continue
        P = o + np.outer(g[:, 0], u) + np.outer(g[:, 1], v)
        if float(np.cross(P[1] - P[0], P[2] - P[0]) @ n) < 0:
            P = P[::-1].copy()
        out.append((P, bool(t0 + j0 * CELL > T.min() + 0.5)))
    return out


class Grilles:
    """open_wall for every wall of one .bsp (its trees read once)."""

    def __init__(self, raw: bytes, hull: int, sheets=()):
        self.s0 = _Tree(raw, 0)
        self.clip = _Tree(raw, hull)
        self.hull = hull
        self.sheets = list(sheets)

    def open(self, model: int, q, n, half):
        h0, hc = self.s0.head(model), self.clip.head(model)
        if h0 < 0 or hc < 0:
            return None
        return open_wall(self.s0, h0, self.clip, hc, q, n, half, self.sheets if model == 0 else ())
