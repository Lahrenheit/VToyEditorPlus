"""Reading Valve Hammer Editor maps (.rmf, version 2.2): the uncompiled Half-Life / Counter-Strike 1.6 map, made of brushes.

A brush (CMapSolid) is a convex block: its faces carry their corners, texture name and texture axes.  The world's brushes
and the brushes of the brush entities (func_wall, func_door ...) are read with the entities' key values, then turned into
what ``bspimport.convert`` reads from a compiled map (``to_bsp_like``):

* the faces that are drawn: every face of a brush that is not a tool texture (NULL, CLIP, SKY, AAATRIGGER ...), minus the
  parts hidden inside another brush (Hammer's maps overlap brushes: what is inside is never seen);
* the faces that are solid: the outside of all the solid brushes together, CLIP brushes included (what a player meets);
* the entities, with "model": "*N" for brush entities and the bounds of each.

    RmfMap.load(path) -> .solids [Solid], .entities [dict with "solids"], .world (dict)
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np

WORLD_CLASSES = ("func_detail", "func_group", "func_detail_illusionary_no")   # compiled into the world
TOOL_TEXTURES = ("null", "clip", "sky", "aaatrigger", "origin", "hint", "skip", "bevel", "trigger")


@dataclass(eq=False)
class Face:
    texture: str
    points: np.ndarray            # (n, 3) corners as Hammer keeps them
    u: np.ndarray                 # texture axis (3,), shift, scale
    v: np.ndarray
    ushift: float
    vshift: float
    uscale: float
    vscale: float
    normal: np.ndarray = None     # outward, unit
    d: float = 0.0                # plane: normal . p = d


@dataclass(eq=False)
class Solid:
    faces: List[Face]
    entity: int = -1              # -1 = the world; else the index in RmfMap.entities

    def planes(self):
        return [(f.normal, f.d) for f in self.faces]

    def bounds(self):
        p = np.concatenate([f.points for f in self.faces])
        return p.min(0), p.max(0)


@dataclass(eq=False)
class RmfMap:
    solids: List[Solid] = field(default_factory=list)
    entities: List[dict] = field(default_factory=list)           # key values, plus "origin" for point entities
    world: dict = field(default_factory=dict)

    @classmethod
    def load(cls, path: str) -> "RmfMap":
        return cls.parse(open(path, "rb").read())

    @classmethod
    def parse(cls, data: bytes) -> "RmfMap":
        r = _Reader(data)
        version = r.f()
        if data[4:7] != b"RMF":
            raise ValueError("not a Hammer .rmf map")
        if abs(version - 2.2) > 0.05:
            raise ValueError(f"unsupported .rmf version {version:.1f} (2.2 expected)")
        r.o = 7
        nvis = r.i()
        r.o += 140 * nvis                                     # visgroups: name, colour, id, visible
        out = cls()
        kind = r.s()
        if kind != "CMapWorld":
            raise ValueError("the .rmf has no world")
        r.o += 4 + 3                                          # visgroup, colour
        n = r.i()
        for _ in range(n):
            out._object(r, -1)
        out.world = out._entity_data(r, world=True)
        return out

    # ------------------------------------------------------------------ objects
    def _object(self, r: "_Reader", owner: int) -> None:
        kind = r.s()
        r.o += 4 + 3                                          # visgroup, colour
        if kind == "CMapSolid":
            r.o += 4                                          # children (none)
            nf = r.i()
            faces = [self._face(r) for _ in range(nf)]
            faces = [f for f in faces if f is not None]
            if len(faces) >= 4:
                c = np.concatenate([f.points for f in faces]).mean(0)
                for f in faces:                               # outward, whichever way Hammer wound it
                    if float(f.normal @ (f.points.mean(0) - c)) < 0:
                        f.normal = -f.normal
                        f.d = -f.d
                self.solids.append(Solid(faces, owner))
        elif kind == "CMapGroup":
            n = r.i()
            for _ in range(n):
                self._object(r, owner)
        elif kind == "CMapEntity":
            n = r.i()
            idx = len(self.entities)
            self.entities.append({})                          # filled after its brushes
            for _ in range(n):
                self._object(r, idx)
            kv = self._entity_data(r, world=False)
            self.entities[idx] = kv
        else:
            raise ValueError(f"unknown object {kind!r} in the .rmf")

    def _face(self, r: "_Reader") -> Optional[Face]:
        tex = r.raw(256).split(b"\0")[0].decode("latin-1")
        r.o += 4                                              # unused
        u = np.array(r.fs(3)); ushift = r.f()
        v = np.array(r.fs(3)); vshift = r.f()
        r.o += 4                                              # rotation (already in the axes)
        uscale, vscale = r.f(), r.f()
        r.o += 16
        nv = r.i()
        pts = np.array(r.fs(3 * nv), np.float64).reshape(-1, 3)
        plane = np.array(r.fs(9), np.float64).reshape(3, 3)
        if nv < 3:
            return None
        n = _newell(pts)                                      # turned outward by the solid (see _object)
        ln = np.linalg.norm(n)
        if ln < 1e-9:
            return None
        n = n / ln
        return Face(tex, pts, u, v, ushift, vshift, uscale or 1.0, vscale or 1.0, n, float(n @ pts.mean(0)))

    def _entity_data(self, r: "_Reader", world: bool) -> dict:
        kv = {"classname": r.s()}
        r.o += 4
        kv["spawnflags"] = str(r.i())
        nk = r.i()
        for _ in range(nk):
            k = r.s()
            kv[k] = r.s()
        if world:
            r.o += 12
            npaths = r.i()
            for _ in range(npaths):                           # paths (path_corner chains): skipped
                r.o += 128 + 128 + 4
                nn = r.i()
                for _ in range(nn):
                    r.o += 12 + 4 + 128
                    nk2 = r.i()
                    for _ in range(nk2):
                        r.s(); r.s()
        else:
            r.o += 14
            o = r.fs(3)
            r.o += 4
            if "origin" not in kv:
                kv["origin"] = "%g %g %g" % tuple(o)
        return kv

    # ------------------------------------------------------------------ what the map needs
    def textures(self) -> Dict[str, int]:
        """{texture: faces} of the faces that are drawn."""
        out: Dict[str, int] = {}
        for s in self.solids:
            for f in s.faces:
                if not tool_texture(f.texture):
                    out[f.texture] = out.get(f.texture, 0) + 1
        return out


NOT_SOLID = ("hint", "skip", "origin", "aaatrigger", "bevel")


def solid_brush(s: "Solid") -> bool:
    """False for the brushes a compiled map has no solid for: hint / skip / origin brushes, triggers, water ('!' or '*'
    textures)."""
    return not (all(f.texture.lower() in NOT_SOLID for f in s.faces) or
                all(f.texture[:1] in "!*" for f in s.faces))


def tool_texture(name: str) -> bool:
    n = name.lower()
    return any(w in n for w in TOOL_TEXTURES)


class _Reader:
    def __init__(self, data: bytes):
        self.d, self.o = data, 0

    def raw(self, n):
        b = self.d[self.o:self.o + n]
        if len(b) < n:
            raise ValueError("the .rmf ends too soon (damaged file?)")
        self.o += n
        return b

    def i(self):
        return struct.unpack("<i", self.raw(4))[0]

    def f(self):
        return struct.unpack("<f", self.raw(4))[0]

    def fs(self, n):
        return struct.unpack("<%df" % n, self.raw(4 * n))

    def s(self):
        n = self.raw(1)[0]
        return self.raw(n).split(b"\0")[0].decode("latin-1")


def _newell(p: np.ndarray) -> np.ndarray:
    n = np.zeros(3)
    for i in range(len(p)):
        a, b = p[i], p[(i + 1) % len(p)]
        n += [(a[1] - b[1]) * (a[2] + b[2]), (a[2] - b[2]) * (a[0] + b[0]), (a[0] - b[0]) * (a[1] + b[1])]
    return n


# ============================================================================== solid geometry: what is outside the others
EPS = 0.05


def _split(poly: np.ndarray, n: np.ndarray, d: float):
    """(front part, back part) of a convex polygon cut by the plane n.p = d (None when empty)."""
    dist = poly @ n - d
    if np.all(dist >= -EPS):
        return poly, None
    if np.all(dist <= EPS):
        return None, poly
    front, back = [], []
    k = len(poly)
    for i in range(k):
        a, b = poly[i], poly[(i + 1) % k]
        da, db = dist[i], dist[(i + 1) % k]
        if da >= -EPS:
            front.append(a)
        if da <= EPS:
            back.append(a)
        if (da > EPS and db < -EPS) or (da < -EPS and db > EPS):
            t = da / (da - db)
            x = a + (b - a) * t
            front.append(x)
            back.append(x)
    f = np.array(front) if len(front) >= 3 else None
    bk = np.array(back) if len(back) >= 3 else None
    return f, bk


def _outside(poly: np.ndarray, normal: np.ndarray, brush: Solid, keep_coplanar: bool) -> List[np.ndarray]:
    """The parts of ``poly`` (a face with outward ``normal``) not inside ``brush``.  A face lying ON a face of the brush
    that looks the other way is inside (two brushes touching: neither face is seen); one looking the same way is kept by
    one of the two brushes only (``keep_coplanar``)."""
    outs = []
    rest = poly
    for n, d in brush.planes():
        dist = rest @ n - d
        if np.all(np.abs(dist) <= EPS):                       # on this plane of the brush
            if float(n @ normal) > 0 and keep_coplanar:
                return [poly]
            continue
        front, back = _split(rest, n, d)
        if front is not None:
            outs.append(front)
        if back is None:
            return outs
        rest = back
    return outs                                               # ``rest`` is inside the brush: gone


def _area(p: np.ndarray) -> float:
    return 0.5 * float(np.linalg.norm(sum(np.cross(p[k] - p[0], p[k + 1] - p[0]) for k in range(1, len(p) - 1))))


def visible_parts(solids: List[Solid], face_ok: Callable[[Solid, Face], bool],
                  blocker: Callable[[Solid], bool]) -> List[Tuple[Solid, Face, np.ndarray]]:
    """[(solid, face, piece)] of the faces ``face_ok`` accepts, cut where they are inside one of the ``blocker`` brushes."""
    bounds = [s.bounds() for s in solids]
    lo = np.array([b[0] for b in bounds])
    hi = np.array([b[1] for b in bounds])
    blk = np.array([bool(blocker(s)) for s in solids])
    out = []
    for i, s in enumerate(solids):
        a, b = bounds[i]
        near = np.nonzero(blk & np.all(lo <= b + EPS * 2, 1) & np.all(hi >= a - EPS * 2, 1))[0]
        near = [j for j in near if j != i]
        for f in s.faces:
            if not face_ok(s, f):
                continue
            pieces = [f.points]
            fa, fb = f.points.min(0), f.points.max(0)
            for j in near:
                if not (np.all(lo[j] <= fb + EPS * 2) and np.all(hi[j] >= fa - EPS * 2)):
                    continue
                nxt = []
                for p in pieces:
                    nxt += _outside(p, f.normal, solids[j], keep_coplanar=j > i)
                pieces = nxt
                if not pieces:
                    break
            for p in pieces:
                if _area(p) > 0.5:
                    out.append((s, f, p))
    return out


# ============================================================================== the outside of a sealed map
def inside_space(rm: RmfMap, cell: float = 8.0, starts=None):
    """The empty space players can be in: a grid of ``cell`` units, the solid brushes (sky and CLIP ones too) filled in,
    flooded from the player starts (``starts``: CS points; the info_player_* of the map when None).  Returns a function
    point -> bool, or None when it cannot tell (no start, or the flood leaks out of the map: a map that is not sealed,
    which the CS compiler refuses too)."""
    if starts is None:
        starts = []
        for e in rm.entities:
            if e.get("classname", "").startswith("info_player") and "origin" in e:
                try:
                    starts.append([float(v) for v in e["origin"].split()])
                except ValueError:
                    pass
    solids = [s for s in rm.solids if solid_brush(s) and (s.entity < 0 or _blocks(rm.entities[s.entity]))]
    if not starts or not solids:
        return None
    from . import ndi
    lo = np.min([s.bounds()[0] for s in solids], 0) - 2 * cell
    hi = np.max([s.bounds()[1] for s in solids], 0) + 2 * cell
    shape = np.ceil((hi - lo) / cell).astype(int) + 1
    if np.prod(shape) > 120_000_000:
        return None
    solid = np.zeros(shape, bool)
    half = cell / 2.0
    for s in solids:
        a, b = s.bounds()
        i0 = np.clip(np.floor((a - lo) / cell).astype(int) - 1, 0, shape - 1)
        i1 = np.clip(np.ceil((b - lo) / cell).astype(int) + 1, 0, shape - 1)
        axes = [lo[k] + cell * np.arange(i0[k], i1[k] + 1) for k in range(3)]
        X, Y, Z = np.meshgrid(*axes, indexing="ij")
        inside = np.ones(X.shape, bool)
        for n, d in s.planes():                      # a cell the brush touches counts as solid (no leak through thin walls)
            inside &= (X * n[0] + Y * n[1] + Z * n[2] - d) <= half * float(np.abs(n).sum()) - 1e-3
        solid[i0[0]:i1[0] + 1, i0[1]:i1[1] + 1, i0[2]:i1[2] + 1] |= inside
    lab, _n = ndi.label(~solid)
    seeds = set()
    for p in starts:
        k = tuple(np.clip(np.round((np.asarray(p) - lo) / cell).astype(int), 0, shape - 1))
        if lab[k]:
            seeds.add(int(lab[k]))
    if not seeds:
        return None
    open_ = np.isin(lab, list(seeds))
    if open_[0, :, :].any() or open_[-1, :, :].any() or open_[:, 0, :].any() or open_[:, -1, :].any() or \
            open_[:, :, 0].any() or open_[:, :, -1].any():
        return None                                  # leaks: not sealed

    def ok(p) -> bool:
        k = np.round((np.asarray(p, np.float64) - lo) / cell).astype(int)
        if np.any(k < 0) or np.any(k >= shape):
            return False
        return bool(open_[tuple(k)])
    return ok


def _blocks(e: dict) -> bool:
    from . import bspimport
    c = e.get("classname", "").lower()
    return not (c.startswith("trigger") or c in bspimport.HIDDEN_CLASSES or c in bspimport.NONSOLID_CLASSES
                or c in bspimport.WATER_CLASSES or c.startswith("func_door"))


def _seen_from(ok, poly: np.ndarray, n: np.ndarray, cell: float) -> bool:
    """Is a piece of face next to the players' space (any of a few points just in front of it)?"""
    c = poly.mean(0)
    pts = [c] + [c + (q - c) * 0.8 for q in poly]
    return any(ok(p + n * (cell * 1.5)) for p in pts)


# ============================================================================== as a compiled map for bspimport
def to_bsp_like(rm: RmfMap, sizes: Callable[[str], Tuple[int, int]] = lambda n: (64, 64), outside: bool = True):
    """A ``bsp.BspMap`` of the .rmf: drawn faces (hidden parts cut away), entities (brush entities numbered "*N" with
    their bounds) and ``solid_faces`` {model: [(polygon, outward normal)]}: the outside of the solid brushes together (the
    world's brushes, CLIP ones included, as model 0; each brush entity on its own).  With ``outside`` (and a sealed map
    with player starts) the faces looking at the void outside the map are left out, as the CS compiler does."""
    from .bsp import BspFace, BspMap
    from . import bspimport
    for s in rm.solids:                                       # func_detail / func_group: part of the world once compiled
        if s.entity >= 0 and rm.entities[s.entity].get("classname", "").lower() in WORLD_CLASSES:
            s.entity = -1
    ents = []
    model_of: Dict[int, int] = {}
    for k, e in enumerate(rm.entities):
        e = dict(e)
        if any(s.entity == k for s in rm.solids):
            model_of[k] = len(model_of) + 1
            e["model"] = f"*{model_of[k]}"
            e.pop("origin", None)                             # its brushes are where they are (a .bsp keeps them round it)
        ents.append(e)
    out = BspMap()
    out.entities = [dict(rm.world)] + ents
    nmodels = len(model_of) + 1
    out.models = [None] * nmodels
    for m in range(nmodels):
        ss = [s for s in rm.solids if (model_of.get(s.entity, 0) if s.entity >= 0 else 0) == m]
        if ss:
            p = np.concatenate([np.concatenate([f.points for f in s.faces]) for s in ss])
            out.models[m] = (p.min(0), p.max(0))
        else:
            out.models[m] = (np.zeros(3), np.zeros(3))

    def model(s: Solid) -> int:
        return model_of.get(s.entity, 0) if s.entity >= 0 else 0

    def cls(s: Solid) -> str:
        return rm.entities[s.entity].get("classname", "").lower() if s.entity >= 0 else ""

    def all_tool(s: Solid) -> bool:
        return all(tool_texture(f.texture) for f in s.faces)
    # drawn: cut by the world's visible brushes only (a face inside a CLIP brush is still seen)
    drawn = visible_parts(rm.solids, lambda s, f: not tool_texture(f.texture),
                          lambda s: s.entity < 0 and not all_tool(s))
    ok = inside_space(rm) if outside else None       # what faces the void outside the sealed map is never seen
    if ok is not None:
        drawn = [(s, f, p) for s, f, p in drawn if _seen_from(ok, p, f.normal, 8.0)]
    out.sealed = ok is not None
    for s, f, p in drawn:
        w, h = sizes(f.texture)
        uv = np.stack([(p @ f.u / f.uscale + f.ushift) / max(w, 1), (p @ f.v / f.vscale + f.vshift) / max(h, 1)], 1)
        out.faces.append(BspFace(p.astype(np.float64), f.normal.astype(np.float64), f.texture, uv, model(s)))
        out.textures[f.texture] = (w, h)
    # solid: the world (CLIP brushes too) together; each brush entity by itself
    solid_faces: Dict[int, list] = {}
    groups: Dict[int, List[Solid]] = {}
    for s in rm.solids:
        c = cls(s)
        if s.entity >= 0 and (c.startswith("trigger") or c in bspimport.HIDDEN_CLASSES or c in bspimport.NONSOLID_CLASSES
                              or c in bspimport.WATER_CLASSES):
            continue
        if not solid_brush(s):
            continue
        groups.setdefault(model(s), []).append(s)
    for m, ss in groups.items():
        parts = visible_parts(ss, lambda s, f: True, lambda s: True)
        if ok is not None:
            parts = [(s, f, p) for s, f, p in parts if _seen_from(ok, p, f.normal, 8.0)]
        solid_faces[m] = [(p, f.normal.copy()) for s, f, p in parts]
    out.solid_faces = solid_faces
    return out
