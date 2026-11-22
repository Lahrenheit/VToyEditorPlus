"""The light of a Counter-Strike / Half-Life map (.bsp lightmaps) on the meshes made from it.

CS draws every wall as texture x its lightmap (sun, shadows, the colour of the lamps).  Without it the walls of maps
whose textures are grey (de_dust2_cs2, de_mirage_cs2: the colour came from the light) look flat grey in the game.

The game draws a material with two textures as  first x second x 2  (stage 1: MODULATE2X, the "glow_*" / "Grad_*"
textures of its own maps, with the vertices' second texture coordinates); so the lightmaps of the map go into a few
atlas textures (128 = as bright as without them) and each mesh made from the .bsp gets one of them as second texture.

    bsp_lightmaps(raw)                      {face number: Chart}
    match_triangles(bsp, pl, tris)          the face of the .bsp each triangle (engine points) came from
    apply(opt, bsp, pl, write_texture, ...) lights every mesh of ``opt`` that came from the .bsp
    find_plan(bsp, opt)                     the Plan a map was laid with (when only the map and the .bsp are known)
"""
from __future__ import annotations

import math
import struct
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np

PAGE = 512            # atlas size (the game's biggest textures are 512)
ALIGN = 4             # charts on the DXT blocks: no block mixes two faces (no colour bleeding, mip levels 1-2 clean)
NEUTRAL = 128         # stored value that leaves the texture as it is (x 2)


@dataclass
class Chart:
    face: int
    s: np.ndarray          # texinfo s (4,)
    t: np.ndarray          # texinfo t (4,)
    smin: int              # floor(min s / 16)
    tmin: int
    w: int                 # luxels
    h: int
    rgb: np.ndarray        # (h, w, 3) float, raw light (style 0)


def _lumps(raw: bytes) -> dict:
    names = ("entities", "planes", "textures", "vertices", "visibility", "nodes", "texinfo", "faces", "lighting",
             "clipnodes", "leaves", "marksurfaces", "edges", "surfedges", "models")
    out = {}
    for i, n in enumerate(names):
        off, ln = struct.unpack_from("<ii", raw, 4 + 8 * i)
        out[n] = raw[off:off + ln]
    return out


def bsp_lightmaps(raw: bytes) -> Dict[int, Chart]:
    """{face number: Chart} of every face with a lightmap (style 0)."""
    L = _lumps(raw)
    verts = np.frombuffer(L["vertices"], "<f4").reshape(-1, 3).astype(np.float64)
    edges = np.frombuffer(L["edges"], "<u2").reshape(-1, 2)
    surfedges = np.frombuffer(L["surfedges"], "<i4")
    texinfo = np.frombuffer(L["texinfo"], np.dtype([("s", "<f4", 4), ("t", "<f4", 4), ("mip", "<i4"), ("flags", "<i4")]))
    faces = np.frombuffer(L["faces"], np.dtype([("plane", "<u2"), ("side", "<u2"), ("first", "<i4"), ("n", "<u2"),
                                                 ("ti", "<u2"), ("styles", "u1", 4), ("light", "<i4")]))
    light = np.frombuffer(L["lighting"], np.uint8)
    out: Dict[int, Chart] = {}
    for fi, f in enumerate(faces):
        if f["light"] < 0 or f["styles"][0] == 255:
            continue
        se = surfedges[f["first"]:f["first"] + f["n"]]
        idx = np.where(se >= 0, edges[np.abs(se), 0], edges[np.abs(se), 1])
        p = verts[idx]
        ti = texinfo[f["ti"]]
        s, t = ti["s"].astype(np.float64), ti["t"].astype(np.float64)
        vs = p @ s[:3] + s[3]
        vt = p @ t[:3] + t[3]
        smin, smax = math.floor(vs.min() / 16.0), math.ceil(vs.max() / 16.0)
        tmin, tmax = math.floor(vt.min() / 16.0), math.ceil(vt.max() / 16.0)
        w, h = smax - smin + 1, tmax - tmin + 1
        if w <= 0 or h <= 0 or w > PAGE - 8 or h > PAGE - 8:
            continue
        a = int(f["light"])
        if a + w * h * 3 > len(light):
            continue
        rgb = light[a:a + w * h * 3].reshape(h, w, 3).astype(np.float64)
        out[fi] = Chart(fi, s, t, smin, tmin, w, h, rgb)
    return out


# ----------------------------------------------------------------------------------------------- engine -> CS
def to_cs(pl, e) -> np.ndarray:
    """Inverse of Plan.point: engine points -> CS points."""
    q = (np.asarray(e, np.float64) - np.asarray(pl.at, np.float64)) @ pl.R().T / pl.scale
    return q[..., [0, 2, 1]] + np.asarray(pl.centre, np.float64)


def _face_table(bsp):
    """Every face of the .bsp where it is drawn (brush entities with an origin moved there), by plane."""
    from . import bspimport
    ents = bspimport.model_entities(bsp)
    shift = {}
    for m, e in ents.items():
        if "origin" in e:
            try:
                shift[m] = np.array([float(v) for v in e["origin"].split()])
            except ValueError:
                pass
    table = {}
    info = []
    for fi, f in enumerate(bsp.faces):
        p = np.asarray(f.points, np.float64)
        if len(p) < 3:
            info.append(None)
            continue
        off = shift.get(f.model, np.zeros(3))
        p = p + off
        n = np.asarray(f.normal, np.float64)
        n = n / max(np.linalg.norm(n), 1e-12)
        d = float(n @ p[0])
        # 2D polygon in the face's plane
        ax = int(np.argmax(np.abs(n)))
        keep = [k for k in range(3) if k != ax]
        info.append((p, n, d, keep, off))
        key = (int(round(n[0] * 20)), int(round(n[1] * 20)), int(round(n[2] * 20)), int(round(d / 16.0)))
        table.setdefault(key, []).append(fi)
    return table, info


NEUTRAL = (128, 128, 128)          # x 2 by the game: the texture as it is
SPILL = 2.0                        # CS units a triangle may go past the face it lies on before it is cut along the faces


def _unlit_face(f) -> bool:
    """Water: CS draws it without lightmap (its light would make it glow, x 2)."""
    t = str(getattr(f, "texture", "")).lower()
    return t.startswith("!") or t.startswith("*") or t.startswith("water")


def _edge_planes(p: np.ndarray, n: np.ndarray) -> list:
    """(m, o) per edge of the convex face p (normal n): a point x is inside when m . x >= o."""
    c = p.mean(0)
    out = []
    for k in range(len(p)):
        m = np.cross(n, p[(k + 1) % len(p)] - p[k])
        ln = np.linalg.norm(m)
        if ln < 1e-9:
            continue
        m = m / ln
        if m @ (c - p[k]) < 0:
            m = -m
        out.append((m, float(m @ p[k])))
    return out


def _clip_poly(poly: list, planes: list) -> list:
    for m, o in planes:
        res = []
        for i in range(len(poly)):
            a, b = poly[i], poly[(i + 1) % len(poly)]
            da, db = float(m @ a) - o, float(m @ b) - o
            if da >= 0:
                res.append(a)
            if (da >= 0) != (db >= 0):
                res.append(a + (b - a) * (da / (da - db)))
        poly = res
        if len(poly) < 3:
            return []
    return poly


def _poly_area(poly) -> float:
    return 0.5 * float(np.linalg.norm(sum(np.cross(poly[k] - poly[0], poly[k + 1] - poly[0])
                                          for k in range(1, len(poly) - 1))))


def _cut_along_faces(pl, table, info, charts, tri: np.ndarray, rec: np.ndarray, fo: np.ndarray, tol: float = 1.5):
    """Triangles (engine (n, 3, 3), their corners' vertex records (n, 3), matched face numbers) with each triangle that
    goes more than SPILL past its face cut into pieces, one per face of the .bsp of its plane it covers (the vertex
    records interpolated).  A triangle the faces do not cover (98 %) stays as it is."""
    cs = to_cs(pl, tri.reshape(-1, 3)).reshape(-1, 3, 3)
    planes = {}

    def pf(fi):
        if fi not in planes:
            planes[fi] = _edge_planes(info[fi][0], info[fi][1])
        return planes[fi]
    out_t, out_r, out_f = [], [], []
    cut = False
    for t in range(len(tri)):
        f = int(fo[t])
        if f < 0 or info[f] is None:
            out_t.append(tri[t:t + 1]); out_r.append(rec[t:t + 1]); out_f.append(fo[t:t + 1])
            continue
        q = cs[t]
        spill = max(max(o - float(m @ x) for m, o in pf(f)) for x in q) if pf(f) else 0.0
        area = _poly_area(list(q))
        if spill <= SPILL or area < 1e-3:
            out_t.append(tri[t:t + 1]); out_r.append(rec[t:t + 1]); out_f.append(fo[t:t + 1])
            continue
        n = np.cross(q[1] - q[0], q[2] - q[0])
        n /= np.linalg.norm(n)
        lo, hi = q.min(0) - tol, q.max(0) + tol
        cand = set()
        for s_ in (1.0, -1.0):
            m = n * s_
            d = float(m @ q[0])
            k0 = (int(round(m[0] * 20)), int(round(m[1] * 20)), int(round(m[2] * 20)), int(round(d / 16.0)))
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for dz in (-1, 0, 1):
                        for dd in (-1, 0, 1):
                            cand.update(table.get((k0[0] + dx, k0[1] + dy, k0[2] + dz, k0[3] + dd), ()))
        pieces, tot = [], 0.0
        for fi in cand:
            if fi not in charts or info[fi] is None:
                continue
            p, fn, fd = info[fi][0], info[fi][1], info[fi][2]
            if abs(abs(float(fn @ n)) - 1.0) > 2e-3 or abs(float(fn @ q.mean(0)) - fd) > tol:
                continue
            if float(fn @ info[f][1]) < 0.5:                 # the back of a thin brush: not this side
                continue
            if (p.max(0) < lo).any() or (p.min(0) > hi).any():
                continue
            poly = _clip_poly([x for x in q], pf(fi))
            if len(poly) >= 3:
                a = _poly_area(poly)
                if a > 1e-3:
                    pieces.append((fi, poly, abs(float(fn @ q.mean(0)) - fd), a))
        if pieces:                                        # only the faces of the nearest plane: a decal one unit in
            near = min(p_[2] for p_ in pieces)            # front of its wall is cut by its own face, not the wall's too
            pieces = [(fi, poly) for fi, poly, dist, a in pieces if dist <= near + 0.25]
            tot = sum(_poly_area(poly) for _fi, poly in pieces)
        if not pieces or tot < 0.98 * area or tot > 1.02 * area:     # (overlapping faces: left whole)
            out_t.append(tri[t:t + 1]); out_r.append(rec[t:t + 1]); out_f.append(fo[t:t + 1])
            continue
        cut = True
        a, v0, v1 = q[0], q[1] - q[0], q[2] - q[0]
        d00, d01, d11 = v0 @ v0, v0 @ v1, v1 @ v1
        den = d00 * d11 - d01 * d01
        for fi, poly in pieces:
            for k in range(1, len(poly) - 1):
                corners = (poly[0], poly[k], poly[k + 1])
                r = np.empty(3, rec.dtype)
                tt = np.empty((3, 3))
                for c, x in enumerate(corners):
                    v2 = x - a
                    w1 = (d11 * (v2 @ v0) - d01 * (v2 @ v1)) / den
                    w2 = (d00 * (v2 @ v1) - d01 * (v2 @ v0)) / den
                    w = np.array([1.0 - w1 - w2, w1, w2])
                    r[c] = rec[t][0]
                    for fld in rec.dtype.names:
                        val = sum(w[j] * rec[t][j][fld].astype(np.float64) for j in range(3))
                        if fld == "nrm":
                            val = val / max(np.linalg.norm(val), 1e-12)
                        r[c][fld] = val
                    tt[c] = w @ tri[t]
                out_t.append(tt[None]); out_r.append(r[None]); out_f.append(np.array([fi], np.int64))
    if not cut:
        return tri, rec, fo
    return np.concatenate(out_t), np.concatenate(out_r), np.concatenate(out_f)


def match_triangles(bsp, pl, tris: np.ndarray, charts: Dict[int, Chart], tol: float = 1.5, normals=None) -> np.ndarray:
    """``tris`` (n, 3, 3) engine points -> the .bsp face number each came from (-1: none with a lightmap).  ``normals``
    (n, 3) engine, the side each triangle is seen from: a face facing that way first (a thin sign, a board: its back,
    a unit behind and dark against the wall, is not taken for its front)."""
    if normals is not None:
        e = np.asarray(tris, np.float64).reshape(-1, 3, 3).mean(1)
        wn = to_cs(pl, e + np.asarray(normals, np.float64)) - to_cs(pl, e)
        wn /= np.maximum(np.linalg.norm(wn, axis=1, keepdims=True), 1e-12)
        out = _match(bsp, pl, tris, charts, tol, wn)
        rest = np.nonzero(out < 0)[0]
        if len(rest):
            out[rest] = _match(bsp, pl, np.asarray(tris)[rest], charts, tol, None)
        return out
    return _match(bsp, pl, tris, charts, tol, None)


def _match(bsp, pl, tris, charts, tol, wn):
    table, info = _face_table(bsp)
    faces = [fi for fi in charts if fi < len(info) and info[fi] is not None]
    if not faces or not len(tris):
        return np.full(len(tris), -1, np.int64)
    # every face: normal, distance, its edges as inward planes (distance outside = max over edges)
    K = max(len(info[fi][0]) for fi in faces)
    F = len(faces)
    FN = np.zeros((F, 3)); FD = np.zeros(F)
    EM = np.zeros((F, K, 3)); EO = np.full((F, K), 1e9)       # unused edge slots: never the farthest
    for j, fi in enumerate(faces):
        p, n, d, _keep, _off = info[fi]
        FN[j], FD[j] = n, d
        c = p.mean(0)
        for k in range(len(p)):
            e = p[(k + 1) % len(p)] - p[k]
            m = np.cross(n, e)
            ln = np.linalg.norm(m)
            if ln < 1e-9:
                continue
            m /= ln
            if m @ (c - p[k]) < 0:
                m = -m
            EM[j, k], EO[j, k] = -m, -(m @ p[k])        # outside distance = -(m . (x - a)) = (-m) . x - (-(m . a))
    col = {fi: j for j, fi in enumerate(faces)}
    sub = {}
    for key, lst in table.items():
        got = [col[fi] for fi in lst if fi in col]
        if got:
            sub[key] = got
    cs = to_cs(pl, tris.reshape(-1, 3)).reshape(-1, 3, 3)
    nn = np.cross(cs[:, 1] - cs[:, 0], cs[:, 2] - cs[:, 0])
    ln = np.linalg.norm(nn, axis=1)
    ok = ln > 1e-9
    nn[ok] /= ln[ok, None]
    c = cs.mean(1)
    out = np.full(len(tris), -1, np.int64)
    best_d = np.full(len(tris), np.inf)
    for flip in (1.0, -1.0):
        m = nn * flip
        kq = np.round(m * 20).astype(np.int64)
        db = np.round(np.einsum("ij,ij->i", m, c) / 16.0).astype(np.int64)
        keys = np.concatenate([kq, db[:, None]], 1)
        keys[~ok] = 10 ** 6
        uk, inv = np.unique(keys, axis=0, return_inverse=True)
        inv = inv.reshape(-1)
        for gi, k0 in enumerate(uk):
            if k0[0] == 10 ** 6:
                continue
            cand = set()
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for dz in (-1, 0, 1):
                        for dd in (-1, 0, 1):
                            got = sub.get((int(k0[0]) + dx, int(k0[1]) + dy, int(k0[2]) + dz, int(k0[3]) + dd))
                            if got:
                                cand.update(got)
            if not cand:
                continue
            cj = np.fromiter(cand, np.int64)
            ti = np.nonzero(inv == gi)[0]
            for s0 in range(0, len(ti), 2000):
                tt = ti[s0:s0 + 2000]
                cc, nt = c[tt], nn[tt]
                par = np.abs(np.abs(nt @ FN[cj].T) - 1.0) <= 2e-3                     # (t, f)
                if wn is not None:
                    par &= (wn[tt] @ FN[cj].T) > 0.5
                onp = np.abs(cc @ FN[cj].T - FD[cj][None, :]) <= tol
                outd = (np.einsum("tx,fkx->tfk", cc, EM[cj]) - EO[cj][None]).max(2)   # (t, f)
                outd = np.where(par & onp, outd, np.inf)
                j = outd.argmin(1)
                dj = outd[np.arange(len(tt)), j]
                better = (dj <= tol) & (dj < best_d[tt])
                out[tt[better]] = np.asarray(faces)[cj[j[better]]]
                best_d[tt[better]] = dj[better]
    return out


# ----------------------------------------------------------------------------------------------- atlas
class _Page:
    def __init__(self, size: int = PAGE):
        self.size = size
        self.img = np.zeros((size, size, 3), np.float64)
        self.x = self.y = self.row = 0
        self.placed: Dict[int, Tuple[int, int]] = {}      # face -> (x, y) of the luxel (0, 0)
        self.colours: Dict[tuple, Tuple[float, float]] = {}   # one light (a model's) -> its spot (u, v)

    def _spot(self, w: int, h: int):
        if w > self.size or h > self.size:
            return None
        x, y, row = self.x, self.y, self.row
        if x + w > self.size:
            x, y, row = 0, y + row, 0
        if y + h > self.size:
            return None
        return x, y, max(row, h)

    def fits(self, sizes: List[Tuple[int, int]]) -> bool:
        x, y, row = self.x, self.y, self.row
        for w, h in sorted(sizes, key=lambda s: -s[1]):
            if x + w > self.size:
                x, y, row = 0, y + row, 0
            if y + h > self.size:
                return False
            x += w
            row = max(row, h)
        return True

    def put(self, w: int, h: int):
        s = self._spot(w, h)
        if s is None:
            return None
        x, y, row = s
        self.x, self.y, self.row = x + w, y, row
        return x, y


def _cell(w: int, h: int) -> Tuple[int, int]:
    """Atlas cell of a chart: 1 luxel of border round it, rounded up to the DXT blocks."""
    return (-(-(w + 2) // ALIGN) * ALIGN, -(-(h + 2) // ALIGN) * ALIGN)


def tone(rgb: np.ndarray, ref: float, lit: float = 140.0, gamma: float = 0.55) -> np.ndarray:
    """Raw CS light -> stored value (128 = unchanged): the usual sunlit light (``ref``) a bit brighter than now,
    shadows darker.  Each colour on its own through a gamma curve, as CS's light gamma does: the colour of the light
    stays, softened (de_mirage's orange sun is warm, not orange paint)."""
    x = np.maximum(np.asarray(rgb, np.float64), 0.0) / max(ref, 1.0)
    out = lit * np.power(x, gamma)
    return np.clip(out, 18.0, 200.0)


class _FloorLight:
    """The light on the floor under a point (CS lights its models so: by the lightmap of the floor below them)."""

    def __init__(self, bsp, charts, ref, lit):
        self.items = []
        self.grid = {}
        _t, info = _face_table(bsp)
        for fi, c in charts.items():
            inf = info[fi] if fi < len(info) else None
            if inf is None:
                continue
            p, n, d, _keep, off = inf
            if n[2] < 0.7:
                continue
            k = len(self.items)
            self.items.append((p, n, d, c, off, tone(c.rgb, ref, lit)))
            lo, hi = p[:, :2].min(0) // 256, p[:, :2].max(0) // 256
            for gx in range(int(lo[0]), int(hi[0]) + 1):
                for gy in range(int(lo[1]), int(hi[1]) + 1):
                    self.grid.setdefault((gx, gy), []).append(k)

    def at(self, q):
        """Toned light (3,) on the highest floor at most 16 units above ``q`` (CS point), or None."""
        best, bz = None, -1e18
        for k in self.grid.get((int(q[0] // 256), int(q[1] // 256)), ()):
            p, n, d, c, off, px = self.items[k]
            z = (d - n[0] * q[0] - n[1] * q[1]) / n[2]
            if z > q[2] + 16.0 or z <= bz:
                continue
            m = len(p)
            inside = True
            sgn = 0.0
            for i in range(m):
                a0, a1 = p[i], p[(i + 1) % m]
                cr = (a1[0] - a0[0]) * (q[1] - a0[1]) - (a1[1] - a0[1]) * (q[0] - a0[0])
                if abs(cr) < 1e-9:
                    continue
                if sgn == 0.0:
                    sgn = cr
                elif cr * sgn < 0:
                    inside = False
                    break
            if not inside:
                continue
            pt = np.array([q[0], q[1], z]) - off
            ls = float(np.clip((pt @ c.s[:3] + c.s[3]) / 16.0 - c.smin, 0, c.w - 1))
            lt = float(np.clip((pt @ c.t[:3] + c.t[3]) / 16.0 - c.tmin, 0, c.h - 1))
            best, bz = px[int(round(lt)), int(round(ls))], z
        return best


def objects_of(tris: np.ndarray, which) -> List[np.ndarray]:
    """The triangles ``which`` of ``tris`` (n, 3, 3) grouped into objects: triangles sharing a corner (to 0.5 unit)
    are one object (a crate, a barrel, a palm tree)."""
    which = np.asarray(list(which), np.int64)
    if not len(which):
        return []
    parent = list(range(len(which)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    seen = {}
    keys = np.round(tris[which].reshape(-1, 3) * 2.0).astype(np.int64)
    for j, kk in enumerate(map(tuple, keys)):
        t = j // 3
        o = seen.setdefault(kk, t)
        if o != t:
            a, b = find(o), find(t)
            if a != b:
                parent[b] = a
    groups = {}
    for t in range(len(which)):
        groups.setdefault(find(t), []).append(which[t])
    return [np.array(g, np.int64) for g in groups.values()]


def _beside_faces(tris: np.ndarray, fo: np.ndarray, lone, reach: float = 160.0):
    """Triangles on no face of the .bsp (``lone``) in a mesh whose other triangles are (``fo`` >= 0): those lying in
    the plane of a matched triangle near them (within ``reach`` cm: a piece of the same wall or floor the faces do not
    quite cover) -> {triangle: that triangle's face}; the rest (a model's) -> [triangles]."""
    lone = [int(t) for t in lone]
    M = np.nonzero(fo >= 0)[0]
    if not len(M) or not lone:
        return {}, lone
    C = tris.mean(1)
    Nn = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    Nn /= np.maximum(np.linalg.norm(Nn, axis=1, keepdims=True), 1e-12)
    near, far = {}, []
    for t in lone:
        d = np.linalg.norm(C[M] - C[t], axis=1)
        same = ((Nn[M] @ Nn[t]) > 0.99) & (np.abs((C[M] - C[t]) @ Nn[t]) < 4.0) & (d <= reach)
        if same.any():
            j = M[np.nonzero(same)[0][np.argmin(d[same])]]
            near[t] = int(fo[j])
        else:
            far.append(t)
    return near, far


def _object_light(tris, lone, floor, pl, usual, quant) -> dict:
    """{triangle: colour} for the triangles on no face of the .bsp (its models, the editor's own meshes): one colour
    per object - the light on the floor under its middle, as CS lights a model.  (Per triangle, each took the floor
    under its own middle: an object came out patched with light and dark triangles.)"""
    cols = {}
    for g in objects_of(tris, lone):
        pts = tris[g].reshape(-1, 3)
        lo, hi = pts.min(0), pts.max(0)
        mid = (lo + hi) / 2.0
        got = floor.at(to_cs(pl, np.array([mid[0], lo[1] + 2.0, mid[2]]))) if floor is not None else None
        c = quant(got if got is not None else usual)
        for t in g:
            cols[int(t)] = c
    return cols


SMALL_FACE = 48.0           # CS units: a face no bigger than this (a side of a barrel, of a small crate) ...
NEAR_FACE = 64.0            # ... takes at least LIFT x the light of the faces around it (this far)
LIFT = 0.55


def lift_small_faces(bsp, charts: Dict[int, "Chart"], faces) -> int:
    """CS lights a small brush (a barrel, a crate) with one or two luxels per side, measured at points that often
    fall inside the wall or the barrel beside it: one side comes out nearly black next to a bright one (de_inferno's
    blue barrels looked broken in the game).  Each small face's light is raised to at least ``LIFT`` x the usual
    light of the faces around it (their 75th percentile): shading stays, the black patches go; a small face in a
    dark corner (all around it dark) stays dark.  Changes ``charts`` in place.  -> faces raised."""
    faces = [f for f in faces if f in charts]
    if not faces:
        return 0
    cen = {f: np.asarray(bsp.faces[f].points, np.float64).mean(0) for f in faces}
    lum = {f: float(charts[f].rgb.mean()) for f in faces}
    grid: Dict[tuple, list] = {}
    for f in faces:
        grid.setdefault(tuple((cen[f] // NEAR_FACE).astype(int)), []).append(f)
    n = 0
    for f in faces:
        P = np.asarray(bsp.faces[f].points, np.float64)
        if float(np.ptp(P, 0).max()) > SMALL_FACE:
            continue
        k = (cen[f] // NEAR_FACE).astype(int)
        near = [g for dx in (-1, 0, 1) for dy in (-1, 0, 1) for dz in (-1, 0, 1)
                for g in grid.get((k[0] + dx, k[1] + dy, k[2] + dz), ())
                if np.linalg.norm(cen[g] - cen[f]) <= NEAR_FACE]
        if len(near) < 3:
            continue
        floor = LIFT * float(np.percentile([lum[g] for g in near], 75))
        rgb = charts[f].rgb
        L = rgb.mean(2, keepdims=True)
        if float(L.min()) >= floor:
            continue
        charts[f].rgb = rgb * np.maximum(1.0, floor / np.maximum(L, 1.0))
        n += 1
    return n


def apply(opt, bsp, pl, write_texture: Callable[[str, np.ndarray], str], name: str,
          lit: float = 140.0, page: int = PAGE, meshes=None, objects: bool = True, ref: Optional[float] = None) -> dict:
    """Give every mesh of ``opt`` made from ``bsp`` (laid with ``pl``) the light of the .bsp: a second texture (an
    atlas page written with ``write_texture(wanted name, rgb (h, w, 3) uint8) -> file name``) and second texture
    coordinates.  Triangles no face of the .bsp lies under (its models - cars, palm trees, crates -, the editor's own)
    take the light of the floor under them, as CS lights its models: one light for a mesh that is all model, one per
    triangle for a mesh of the map with a few such triangles (``objects`` False: the map's usual light, and meshes
    with no face of the .bsp stay as they are).  Meshes already with two textures stay as they are.  ``meshes``: only
    these mesh numbers.  ``ref``: the brightness the light is measured against (``reference``; by default that of
    the faces lit now - a few faces added to a lit map take the whole map's, or they would come out brighter).
    Returns counts."""
    from .opt import VERTEX2_DTYPE
    charts = bsp_lightmaps(bsp.raw)
    if not charts:
        raise ValueError("this .bsp has no lightmaps (compiled without light)")
    # the map's area (a mesh far outside it - the stock map the .bsp was laid into - is not this map's)
    if bsp.models:
        wlo, whi = np.asarray(bsp.models[0][0], np.float64), np.asarray(bsp.models[0][1], np.float64)
        corners = np.array([[x, y, z] for x in (wlo[0], whi[0]) for y in (wlo[1], whi[1]) for z in (wlo[2], whi[2])])
        ec = pl.point(corners)
        area = (ec.min(0) - 50.0, ec.max(0) + 50.0)
    else:
        area = None
    jobs = []
    only = None if meshes is None else set(int(i) for i in meshes)
    for mi, m in enumerate(opt.meshes):
        if only is not None and mi not in only:
            continue
        if not m.lods or any(len(mat.textures) > 1 for mat in m.materials):
            continue
        subs = []
        for part in m.lods[0].parts:
            for sm in part.submeshes:
                if sm.vertices is None or len(sm.indices) < 3 or sm.remap is not None:
                    continue
                world = np.asarray(sm.vertices["pos"], np.float64)   # already where they are (the transform is not used)
                tri = world[sm.indices.reshape(-1, 3).astype(np.int64)]
                subs.append((sm, tri, sm.vertices[sm.indices.reshape(-1, 3).astype(np.int64)]))
        if subs:
            jobs.append((mi, m, subs))
    if not jobs:
        return {"meshes": 0, "pages": 0, "triangles": 0, "matched": 0}
    alltri = np.concatenate([t for _mi, _m, subs in jobs for _sm, t, _r in subs])
    face_of = match_triangles(bsp, pl, alltri, charts,
                              normals=np.concatenate([r["nrm"].astype(np.float64).mean(1) for _mi, _m, subs in jobs
                                                      for _sm, _t, r in subs]))
    # a triangle going past the face it lies on (an older import drew several faces of a plane with one polygon) is cut
    # along the faces: one lightmap each, no stretched edge of a dark one (the floor under a crate) across the floor
    table, info = _face_table(bsp)
    k = 0
    fos = []
    for _mi, _m, subs in jobs:
        for si, (sm, tri, rec) in enumerate(subs):
            n = len(tri)
            t2, r2, f2 = _cut_along_faces(pl, table, info, charts, tri, rec, face_of[k:k + n])
            k += n
            subs[si] = (sm, t2, r2)
            fos.append(f2)
    face_of = np.concatenate(fos)
    alltri = np.concatenate([t for _mi, _m, subs in jobs for _sm, t, _r in subs])
    unlit = np.array([f >= 0 and _unlit_face(bsp.faces[f]) for f in face_of], bool)
    face_of[unlit] = -2                                   # water: CS draws it without its light (as it is)
    used = sorted(set(int(f) for f in face_of if f >= 0))
    if not used:                                          # another map, laid elsewhere, or lit already
        return {"meshes": 0, "pages": 0, "triangles": len(alltri), "matched": 0}
    lifted = lift_small_faces(bsp, charts, used)
    if ref is None:
        lum = np.concatenate([charts[f].rgb.reshape(-1, 3).mean(1) for f in used])
        ref = float(np.percentile(lum, 90))
    allpx = np.concatenate([tone(charts[f].rgb, ref, lit).reshape(-1, 3) for f in used])
    usual = np.median(allpx, 0)                          # no floor under it: the map's usual light
    floor = _FloorLight(bsp, charts, ref, lit) if objects else None

    def quant(c):
        return tuple(int(v) for v in np.clip(np.round(np.asarray(c, np.float64) / 4.0) * 4.0, 0, 255))
    # the light of each triangle not on a face: per mesh (all model) or per triangle
    k = 0
    plan = []                                             # per job: (faces, {triangle: colour}) or None
    for mi, m, subs in jobs:
        n = sum(len(t) for _sm, t, _r in subs)
        fo = face_of[k:k + n]
        tris = alltri[k:k + n]
        k += n
        fs = sorted(set(int(f) for f in fo if f >= 0))
        lone = np.nonzero(fo < 0)[0]
        cols = {}
        if not fs and len(fo) and (fo == -2).all():
            cols = {int(t): NEUTRAL for t in lone}
        elif not fs:
            if floor is None:
                plan.append(None)
                continue
            box_lo, box_hi = tris.reshape(-1, 3).min(0), tris.reshape(-1, 3).max(0)
            mid = (box_lo + box_hi) / 2.0
            if area is not None and not ((area[0] <= mid) & (mid <= area[1])).all():
                plan.append(None)
                continue
            cols = _object_light(tris, lone, floor, pl, usual, quant)
        elif len(lone):
            near, far = _beside_faces(tris, fo, lone)
            for t, f in near.items():                      # a piece of a wall / floor on no face: the light of the
                c = charts[f]                              # face next to it, at its own place (no odd triangle)
                q = to_cs(pl, tris[t].mean(0)[None])[0] - _face_off(bsp, f)
                ls = int(round(float(np.clip((q @ c.s[:3] + c.s[3]) / 16.0 - c.smin, 0, c.w - 1))))
                lt = int(round(float(np.clip((q @ c.t[:3] + c.t[3]) / 16.0 - c.tmin, 0, c.h - 1))))
                cols[int(t)] = quant(tone(c.rgb[lt:lt + 1, ls:ls + 1], ref, lit)[0, 0])
            cols.update(_object_light(tris, far, floor, pl, usual, quant))
        for t in np.nonzero(fo == -2)[0]:
            cols[int(t)] = NEUTRAL
        plan.append((fs, cols))
    # pages: every mesh in one page
    pages: List[_Page] = []
    where = []
    for (mi, m, subs), pj in zip(jobs, plan):
        if pj is None:
            where.append(-1)
            continue
        fs, cols = pj
        cur = pages[-1] if pages else None
        colours = sorted(set(cols.values()))
        need = [_cell(charts[f].w, charts[f].h) for f in fs if cur is None or f not in cur.placed] + \
               [_cell(1, 1) for c in colours if cur is None or c not in cur.colours]
        if cur is None or not cur.fits(need):
            cur = _Page(page)
            pages.append(cur)
        for f in sorted(fs, key=lambda f: -charts[f].h):
            if f in cur.placed:
                continue
            c = charts[f]
            cw, ch = _cell(c.w, c.h)
            xy = cur.put(cw, ch)
            if xy is None:
                raise ValueError("a mesh's lightmaps do not fit a page")
            x, y = xy
            px = tone(c.rgb, ref, lit)
            big = np.pad(px, ((1, ch - c.h - 1), (1, cw - c.w - 1), (0, 0)), mode="edge")
            cur.img[y:y + ch, x:x + cw] = big
            cur.placed[f] = (x + 1, y + 1)
        for c in colours:
            if c in cur.colours:
                continue
            x, y = cur.put(*_cell(1, 1))
            cur.img[y:y + ALIGN, x:x + ALIGN] = c
            cur.colours[c] = ((x + ALIGN / 2) / page, (y + ALIGN / 2) / page)
        where.append(len(pages) - 1)
    if not pages:
        return {"meshes": 0, "pages": 0, "triangles": len(alltri), "matched": 0}
    names = []
    for i, p in enumerate(pages):
        names.append(write_texture(f"{name}_lm{i}", np.clip(p.img + 0.5, 0, 255).astype(np.uint8)))
    # new vertices: per triangle corner (the same corner of two faces has two lightmap spots), then shared again
    k = 0
    matched = objs = 0
    lit_meshes = 0
    for (mi, m, subs), pi, pj in zip(jobs, where, plan):
        n = sum(len(t) for _sm, t, _r in subs)
        fo = face_of[k:k + n]
        k += n
        if pi < 0:
            continue
        cols = pj[1]
        pg = pages[pi]
        j = 0
        for sm, tri, rec in subs:
            cnt = len(tri)
            ff = fo[j:j + cnt]
            uv2 = np.empty((cnt, 3, 2), np.float64)
            cs = to_cs(pl, tri.reshape(-1, 3)).reshape(-1, 3, 3)
            for ti in range(cnt):
                f = int(ff[ti])
                if f < 0:
                    uv2[ti] = pg.colours[cols[j + ti]]
                    objs += 1
                    continue
                matched += 1
                c = charts[f]
                off = _face_off(bsp, f)
                q = cs[ti] - off
                ls = (q @ c.s[:3] + c.s[3]) / 16.0 - c.smin
                lt = (q @ c.t[:3] + c.t[3]) / 16.0 - c.tmin
                ls = np.clip(ls, 0.0, c.w - 1.0)
                lt = np.clip(lt, 0.0, c.h - 1.0)
                x0, y0 = pg.placed[f]
                uv2[ti, :, 0] = (x0 + ls + 0.5) / page
                uv2[ti, :, 1] = (y0 + lt + 0.5) / page
            j += cnt
            flat = rec.reshape(-1)
            nv = np.zeros(len(flat), VERTEX2_DTYPE)
            for fld in ("pos", "nrm", "uv"):
                nv[fld] = flat[fld]
            nv["uv2"] = uv2.reshape(-1, 2)
            keys = np.ascontiguousarray(nv).view(np.dtype((np.void, nv.dtype.itemsize)))
            _u, first, inv = np.unique(keys, return_index=True, return_inverse=True)
            order = np.argsort(first)
            remap = np.empty_like(order)
            remap[order] = np.arange(len(order))
            if len(order) > 65535:
                raise ValueError("a mesh got too many vertices")
            sm.vertices = nv[first[order]]
            sm.indices = remap[inv.reshape(-1)].astype(np.uint16)
            sm.stride_type = 1
        for mat in m.materials:
            mat.textures = [mat.textures[0] if mat.textures else "", names[pi]]
        lit_meshes += 1
    return {"meshes": lit_meshes, "pages": len(pages), "triangles": len(alltri), "matched": matched,
            "objects": objs, "textures": names, "lifted": lifted}


def reference(opt, bsp, pl, charts=None) -> Optional[float]:
    """The brightness ``apply`` measured the light against for the meshes of ``opt`` (all of them) made from ``bsp``:
    the 90th percentile of the lightmaps of the faces they lie on; None when none does."""
    charts = charts if charts is not None else bsp_lightmaps(bsp.raw)
    tris = []
    for m in opt.meshes:
        for sm in m.render_submeshes():
            if sm.vertices is None or len(sm.indices) < 3 or sm.remap is not None:
                continue
            idx = np.asarray(sm.indices, np.int64)[: len(sm.indices) // 3 * 3].reshape(-1, 3)
            idx = idx[(idx < len(sm.vertices)).all(1)]
            tris.append(np.asarray(sm.vertices["pos"], np.float64)[idx])
    if not tris or not charts:
        return None
    face_of = match_triangles(bsp, pl, np.concatenate(tris), charts)
    used = sorted(set(int(f) for f in face_of if f >= 0))
    if not used:
        return None
    return float(np.percentile(np.concatenate([charts[f].rgb.reshape(-1, 3).mean(1) for f in used]), 90))


def strip(opt) -> int:
    """Take the light of a .bsp off again (the map as it was before): every mesh whose second texture is a light
    page (``*_lmN.tex``) gets one texture and plain vertices.  -> meshes changed."""
    import re
    from .opt import VERTEX_DTYPE
    n = 0
    for m in opt.meshes:
        if not m.materials or not any(len(mat.textures) > 1 and re.search(r"_lm\d+(_\d+)?\.tex$", str(mat.textures[1]), re.I)
                                      for mat in m.materials):
            continue
        for part in (p for lod in m.lods for p in lod.parts):
            for sm in part.submeshes:
                if sm.vertices is None or "uv2" not in (sm.vertices.dtype.names or ()):
                    continue
                nv = np.zeros(len(sm.vertices), VERTEX_DTYPE)
                for fld in ("pos", "nrm", "uv"):
                    nv[fld] = sm.vertices[fld]
                keys = np.ascontiguousarray(nv).view(np.dtype((np.void, nv.dtype.itemsize)))
                _u, first, inv = np.unique(keys, return_index=True, return_inverse=True)
                order = np.argsort(first)
                remap = np.empty_like(order)
                remap[order] = np.arange(len(order))
                sm.vertices = nv[first[order]]
                sm.indices = remap[inv.reshape(-1)][np.asarray(sm.indices, np.int64)].astype(np.uint16)
                sm.stride_type = 0
        for mat in m.materials:
            mat.textures = [mat.textures[0]] if mat.textures else []
        n += 1
    return n


def lit_meshes(opt) -> int:
    import re
    return sum(1 for m in opt.meshes if m.materials and any(
        len(mat.textures) > 1 and re.search(r"_lm\d+(_\d+)?\.tex$", str(mat.textures[1]), re.I) for mat in m.materials))


_OFF_CACHE: dict = {}


def _face_off(bsp, fi: int) -> np.ndarray:
    """The shift of a brush entity with an origin (its faces are drawn moved by it; the lightmap is of the unmoved face)."""
    key = id(bsp)
    if key not in _OFF_CACHE or _OFF_CACHE[key][0] is not bsp:      # (another .bsp at the same address: not its table)
        _OFF_CACHE.clear()
        _OFF_CACHE[key] = (bsp, _face_table(bsp)[1])
    inf = _OFF_CACHE[key][1][fi]
    return inf[4] if inf is not None else np.zeros(3)


# ----------------------------------------------------------------------------------------------- where it was laid
def find_plan(bsp, opt, yaws=(0.0, 90.0, 180.0, 270.0), scales=(2.54,)):
    """The Plan the meshes of ``opt`` were made with from ``bsp``: the turn and scale whose shift puts the most of the
    .bsp's corners on the map's vertices."""
    from . import bspimport
    mv = []
    for m in opt.meshes:
        for sm in m.render_submeshes():
            if sm.vertices is not None and len(sm.vertices):
                mv.append(np.asarray(sm.vertices["pos"], np.float64))
    if not mv:
        raise ValueError("the map has no meshes")
    mv = np.unique(np.round(np.concatenate(mv), 1), axis=0)
    fs = bspimport.drawn_faces(bsp)
    bv = np.unique(np.concatenate([f.points for f in fs if not f.model]), axis=0)
    rng = np.random.default_rng(1)
    best = None
    fl = np.floor(mv).astype(np.int64)
    mset = set()
    for dx in (0, 1):
        for dy in (0, 1):
            for dz in (0, 1):
                mset.update(map(tuple, fl + (dx, dy, dz)))      # a point within 1 of a vertex rounds onto one of these
    pack = lambda d: ((d[:, 0] + (1 << 20)) << 42) | ((d[:, 1] + (1 << 20)) << 21) | (d[:, 2] + (1 << 20))
    for scale in scales:
        for yaw in yaws:
            base = bspimport.Plan(float(scale), float(yaw), (0.0, 0.0, 0.0), (0.0, 0.0, 0.0))
            e = base.point(bv)
            a = e[rng.choice(len(e), min(24, len(e)), replace=False)]
            keys = np.concatenate([pack(np.round(mv - q).astype(np.int64)) for q in a])
            vals, cnt = np.unique(keys, return_counts=True)
            top = vals[np.argsort(-cnt)[:12]]
            sample = e[rng.choice(len(e), min(3000, len(e)), replace=False)]
            for k in top:
                cand = np.array([((k >> 42) & ((1 << 21) - 1)) - (1 << 20), ((k >> 21) & ((1 << 21) - 1)) - (1 << 20),
                                 (k & ((1 << 21) - 1)) - (1 << 20)], np.float64)
                q = np.round(sample + cand).astype(np.int64)
                hits = sum(1 for p in map(tuple, q) if p in mset)
                if best is None or hits > best[0]:
                    best = (hits, scale, yaw, cand, len(sample))
    hits, scale, yaw, cand, n = best
    if hits < max(4, 0.3 * n):
        raise ValueError("this map was not made from this .bsp (its walls are not where the .bsp's are)")
    # refine the shift to sub-unit precision: nearest map vertex of each .bsp corner that lands on one
    base = bspimport.Plan(float(scale), float(yaw), (0.0, 0.0, 0.0), (0.0, 0.0, 0.0))
    e = base.point(bv) + cand
    near = {}
    for v in mv:
        near.setdefault(tuple(np.round(v).astype(np.int64)), v)
    diffs = []
    for q in e:
        r = np.round(q).astype(np.int64)
        for dx in (-1, 0, 1):
            for dz in (-1, 0, 1):
                v = near.get((int(r[0]) + dx, int(r[1]), int(r[2]) + dz))
                if v is not None and np.abs(v - q).max() < 1.5:
                    diffs.append(v - q)
    shift = cand + (np.median(np.array(diffs), 0) if diffs else 0.0)
    return bspimport.Plan(float(scale), float(yaw), tuple(float(v) for v in shift), (0.0, 0.0, 0.0))
