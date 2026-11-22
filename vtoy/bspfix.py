"""Things of a CS map that Torrente draws worse than CS does, found on the .bsp the map was made from.

* Decals on walls: CS maps put signs, trims and stains on thin brush entities ("{" textures, func_illusionary /
  func_wall) one unit in front of the wall.  CS draws entities after the world, Torrente sorts by depth only: at a
  distance the two planes fight and the decal blinks (de_dust2_cs2's B site: the grey band and the vent stains).  They
  are moved out to OVERLAY_GAP units from the wall.
* Thin slabs (a fence, the straw under a roof, a plank; or a see-through world brush, whose two faces lie on one
  plane back to back): the map's meshes are drawn from both sides, so both faces show at one spot and blink.  One of
  each pair is left out (thin_backs) - the one facing the wall next to it.  World decals ("{" faces) move out too.
* Brush entities CS does not draw as solid colour: additive ones (render mode 5 - a beam of sunlight, its black
  sides vanish in CS) and invisible ones (render amount 0).  Torrente showed de_dust2_cs2's sunbeam before B as a dark
  see-through sheet with black edges.  They are left out (bspimport.invisible_entity); in a map made before, their
  triangles are taken out.
"""
from typing import Dict, List, Optional, Tuple

import numpy as np

OVERLAY_GAP = 4.0           # CS units between a decal and its wall (CS maps: 1; Torrente's depth needs more)
_TOL = 0.5                  # a decal is 1 unit off its wall: the plane test must tell them apart


def _entity_shift(bsp) -> Dict[int, np.ndarray]:
    from . import bspimport
    out = {}
    for m, e in bspimport.model_entities(bsp).items():
        if "origin" in e:
            try:
                out[m] = np.array([float(v) for v in e["origin"].split()])
            except ValueError:
                pass
    return out


def _see_through(f) -> bool:
    """A face with a see-through ("{": holes where the picture is blue) texture."""
    return str(f.texture).startswith("{")


def _inside(P: np.ndarray, n: np.ndarray, q: np.ndarray, tol: float = 1e-3) -> bool:
    s = [float(np.cross(P[(i + 1) % len(P)] - P[i], q - P[i]) @ n) for i in range(len(P))]
    return all(x >= -tol for x in s) or all(x <= tol for x in s)


def overlay_shifts(bsp, gap: float = OVERLAY_GAP, layered: bool = True) -> Dict[int, float]:
    """{face number: CS units to move it along its normal} for the faces of drawn brush entities lying less than
    ``gap`` in front of a world face drawn behind them (same direction, the decal's middle over it): each ends ``gap``
    off its wall.  ``layered``: a decal laid over another decal ends 2 units in front of where that one ends
    (de_cbble: a banner 2 units off the wall over a plaster sheet 1 unit off - both ended 4 off, the banner blinked);
    without it (editors up to v1.0.20) every decal ended ``gap`` off its wall."""
    from . import bspimport
    ents = bspimport.model_entities(bsp)
    drawn = bspimport.drawn_faces(bsp)
    world = [f for f in drawn if not f.model and not _see_through(f)]
    if not world:
        return {}
    WN = np.array([np.asarray(f.normal, np.float64) for f in world])
    WD = np.array([float(np.asarray(f.normal, np.float64) @ f.points[0]) for f in world])
    ids = {id(f): i for i, f in enumerate(bsp.faces)}
    shift = _entity_shift(bsp)
    out = {}
    found = []                                             # (face number, normal, points, test points, distance)
    planes: Dict[tuple, list] = {}
    for f in drawn:
        if not f.model and not _see_through(f):
            continue                                       # (a world brush with a see-through texture - straw under
        e = ents.get(f.model) if f.model else None         # a roof, a carving - is a decal as well)
        if bspimport._hidden(e) or bspimport.invisible_entity(e) or str(f.texture).startswith(("!", "*")) \
                or (e and e.get("classname", "").lower() in bspimport.WATER_CLASSES):
            continue                                       # (water lies on its pool's floor: not a decal)
        n = np.asarray(f.normal, np.float64)
        P = np.asarray(f.points, np.float64) + shift.get(f.model, 0.0)
        c = P.mean(0)
        d = c @ n - WD
        ok = np.nonzero((WN @ n > 0.999) & (d > -0.01) & (d < gap - 0.01))[0]
        best = None
        pts = [c] + [c + (q - c) * 0.8 for q in P]          # (the wall behind it may be cut in several faces)
        for k in ok:
            W = np.asarray(world[k].points, np.float64)
            if any(_inside(W, n, q - n * d[k]) for q in pts):
                best = d[k] if best is None else min(best, d[k])
        i = ids.get(id(f))
        if i is None:
            continue
        key = (f.model, tuple(np.round(n, 3)), round(float(c @ n), 1))
        planes.setdefault(key, []).append(i)
        if best is not None:
            out[i] = float(gap - best)
            found.append((i, n, P, pts, float(best)))
    if layered and len(found) > 1:                         # decals over decals: in their order, 2 units apart
        found.sort(key=lambda r: r[4])
        end = {}
        for a, (i, n, P, pts, best) in enumerate(found):
            e = gap
            for j, n2, P2, _p2, best2 in found[:a]:
                if n2 @ n > 0.999 and best2 < best - 0.05 and \
                        any(_inside(P2, n, q - n * (best - best2)) for q in pts):
                    e = max(e, end[j] + 2.0)
            end[i] = e
            out[i] = float(e - best)
    for key, fs in planes.items():                         # one sheet of a decal: all its faces move together
        got = [out[i] for i in fs if i in out]
        if got and key[0]:
            for i in fs:
                out[i] = max(got)
    return out


def decal_sides(bsp, most: float = 2.0) -> List[int]:
    """The edges and the back of the decals moved off their walls (overlay_shifts): the faces of the same brush across it,
    at most ``most`` units deep, and the one looking at the wall (on the wall's plane: it blinked with it - fy_pool_day's
    "no crapping" sign, whose back has the other sign's texture, so thin_backs did not pair them).  They stay at the wall while the decal moves out, a dark strip beside it (fy_pool_day's rules
    sign: its 1-unit edges, lit black) - left out."""
    shifts = overlay_shifts(bsp)
    if not shifts:
        return []
    by_model: Dict[int, list] = {}
    for i in shifts:
        f = bsp.faces[i]
        if f.model:
            by_model.setdefault(f.model, []).append(np.asarray(f.normal, np.float64))
    pts: Dict[int, list] = {}
    for f in bsp.faces:
        if f.model in by_model:
            pts.setdefault(f.model, []).append(np.asarray(f.points, np.float64))
    for m in list(by_model):                               # only a brush that is a decal all of it (thin across)
        allp = np.concatenate(pts[m])
        by_model[m] = [nd for nd in by_model[m] if float(np.ptp(allp @ nd)) <= most + 0.01]
    out = []
    for i, f in enumerate(bsp.faces):
        if not f.model or not by_model.get(f.model) or i in shifts or len(f.points) < 3:
            continue
        n = np.asarray(f.normal, np.float64)
        P = np.asarray(f.points, np.float64)
        for nd in by_model[f.model]:
            if (abs(float(n @ nd)) < 0.05 and float(np.ptp(P @ nd)) <= most + 0.01) or float(n @ nd) < -0.95:
                out.append(i)
                break
    return out


def faces_under(bsp, pl, tris: np.ndarray, faces: List[int], tol: float = _TOL, normals=None) -> np.ndarray:
    """For each engine triangle (n, 3, 3): the number of the face of ``faces`` (CS faces of ``bsp``, entity origins
    applied) it lies on (its middle in the face, the same plane within ``tol``, parallel - either side), or -1.
    ``normals``: the triangles' own normals (engine, (n, 3)) - then only a face looking the same way (the two faces
    of a see-through world brush lie on one plane back to back)."""
    from .lightmap import to_cs
    out = np.full(len(tris), -1, np.int64)
    if not len(tris) or not faces:
        return out
    shift = _entity_shift(bsp)
    polys = []
    for fi in faces:
        f = bsp.faces[fi]
        P = np.asarray(f.points, np.float64) + shift.get(f.model, 0.0)
        n = np.asarray(f.normal, np.float64)
        polys.append((fi, P, n / max(np.linalg.norm(n), 1e-12), P.min(0) - tol, P.max(0) + tol))
    lo = np.min([p[3] for p in polys], 0)
    hi = np.max([p[4] for p in polys], 0)
    cs = to_cs(pl, np.asarray(tris, np.float64).reshape(-1, 3)).reshape(-1, 3, 3)
    c = cs.mean(1)
    tn = np.cross(cs[:, 1] - cs[:, 0], cs[:, 2] - cs[:, 0])
    tn /= np.maximum(np.linalg.norm(tn, axis=1, keepdims=True), 1e-12)
    side = None
    if normals is not None:
        side = to_cs(pl, np.asarray(normals, np.float64).reshape(-1, 3)) - to_cs(pl, np.zeros((1, 3)))
        side /= np.maximum(np.linalg.norm(side, axis=1, keepdims=True), 1e-12)
    cand = np.nonzero(((c >= lo) & (c <= hi)).all(1))[0]
    cell = 64.0
    grid: Dict[tuple, list] = {}
    for k, (_fi, P, _n, a, b) in enumerate(polys):
        ia, ib = np.floor(a / cell).astype(int), np.floor(b / cell).astype(int)
        for x in range(ia[0], ib[0] + 1):
            for y in range(ia[1], ib[1] + 1):
                for z in range(ia[2], ib[2] + 1):
                    grid.setdefault((x, y, z), []).append(k)
    for t in cand:
        q = c[t]
        for k in grid.get(tuple(np.floor(q / cell).astype(int)), ()):
            fi, P, n, a, b = polys[k]
            if (q < a).any() or (q > b).any() or abs(float((q - P[0]) @ n)) > tol or abs(float(tn[t] @ n)) < 0.98:
                continue
            if side is not None and float(side[t] @ n) < 0.5:
                continue
            if _inside(P, n, q - n * float((q - P[0]) @ n)):
                out[t] = fi
                break
    return out


def drawn_others(bsp, skip) -> List[int]:
    """The faces a map made here draws (world and brush entities, not hidden or invisible), but those of ``skip``."""
    from . import bspimport
    ents = bspimport.model_entities(bsp)
    ids = {id(f): i for i, f in enumerate(bsp.faces)}
    skip = set(skip)
    out = []
    for f in bspimport.drawn_faces(bsp):
        i = ids.get(id(f))
        e = ents.get(f.model) if f.model else None
        if i is None or i in skip or (e and (bspimport._hidden(e) or bspimport.invisible_entity(e))):
            continue
        out.append(i)
    return out


THIN = 3.0                  # CS units: a slab this thin (a fence, straw, a sheet) has its two faces drawn as one


def thin_backs(bsp, most: float = THIN) -> List[int]:
    """The faces of thin slabs (a fence, the straw under a roof, a plank: two faces of one texture back to back, at
    most ``most`` apart) that are left out: the map's meshes are drawn from both sides, so the other face shows here
    too - both drawn, they are two pictures a unit or two apart and blink in the distance.  Of each pair the face
    nearer to another surface parallel to it (the wall a sheet leans on) goes; only a face the other one covers."""
    key = ("thin", float(most))
    memo = getattr(bsp, "_bspfix_memo", None)
    if memo is None:
        memo = {}
        try:
            bsp._bspfix_memo = memo
        except AttributeError:
            pass
    if key not in memo:
        memo[key] = _thin_backs(bsp, most)
    return list(memo[key])


def _thin_backs(bsp, most: float) -> List[int]:
    from . import bspimport
    ents = bspimport.model_entities(bsp)
    shift = _entity_shift(bsp)
    ids = {id(f): i for i, f in enumerate(bsp.faces)}
    F = [f for f in bspimport.drawn_faces(bsp) if id(f) in ids and len(f.points) >= 3
         and not (f.model and (bspimport._hidden(ents.get(f.model)) or bspimport.invisible_entity(ents.get(f.model))))
         and bspimport.water_face_drawn(bsp, f, ents.get(f.model) if f.model else None)]   # (not drawn anyway)
    if not F:
        return []
    P = [np.asarray(f.points, np.float64) + shift.get(f.model, 0.0) for f in F]
    N = np.array([np.asarray(f.normal, np.float64) / max(np.linalg.norm(f.normal), 1e-12) for f in F])
    C = np.array([p.mean(0) for p in P])
    lo = np.array([p.min(0) for p in P])
    hi = np.array([p.max(0) for p in P])
    stem = [str(f.texture).lower().lstrip("+-~{!0123456789") for f in F]
    fid = [ids[id(f)] for f in F]
    decals = set(overlay_shifts(bsp))

    def opposite(i):
        d = (C[i] - C) @ N[i]                           # how far behind face i (along its normal) each face lies
        ok = (N @ N[i] < -0.999) & (d > -0.01) & (d <= most + 0.01)
        ok &= np.all((lo <= hi[i] + most + 0.5) & (hi >= lo[i] - most - 0.5), 1)
        return [int(k) for k in np.nonzero(ok)[0] if stem[k] == stem[i]], d

    def covered(i, ks, d) -> bool:
        pts = [C[i]] + [C[i] + (q - C[i]) * 0.8 for q in P[i]]
        return all(any(_inside(P[k], N[k], q - N[i] * d[k]) for k in ks) for q in pts)

    def clearance(i) -> float:                          # nearest other surface parallel to face i, in front of it
        d = (C - C[i]) @ N[i]
        ok = (np.abs(N @ N[i]) > 0.999) & (d > 0.01) & (d < 8.0)
        ok &= np.all((lo <= hi[i] + 8.5) & (hi >= lo[i] - 8.5), 1)
        best = 8.0
        for k in np.nonzero(ok)[0]:
            if k == i or stem[k] == stem[i]:
                continue
            if _inside(P[k], N[k], C[i] + N[i] * d[k]):
                best = min(best, abs(float(d[k])))
        return best
    drop = set()
    out = []
    for i in range(len(F)):
        if i in drop:
            continue
        ks, d = opposite(i)
        ks = [k for k in ks if k not in drop]
        if not ks or not covered(i, ks, d):
            continue
        k = min(ks, key=lambda k: abs(float(d[k])))
        _ks2, d2 = opposite(k)
        if fid[i] in decals and fid[k] not in decals:   # a decal moved off its wall stays: its back goes
            if k > i and covered(k, [j for j in _ks2 if j not in drop], d2):
                drop.add(k)
                out.append(fid[k])
            continue
        if k > i and fid[k] not in decals and covered(k, [j for j in _ks2 if j not in drop], d2) \
                and clearance(k) < clearance(i):
            drop.add(k)                                 # this one faces something close (a wall): the other goes
            out.append(fid[k])
            continue
        drop.add(i)
        out.append(fid[i])
    return sorted(out)


def hidden_faces(bsp) -> List[int]:
    """Faces a map made here no longer draws, not hidden anyway: of invisible brush entities
    (bspimport.invisible_entity), and of water all but its top (the underside of the top, the bottom on the river's
    bed, the sides on its banks - drawn on the same planes they blinked: de_aztec's river)."""
    from . import bspimport
    ents = bspimport.model_entities(bsp)
    out = []
    for i, f in enumerate(bsp.faces):
        if len(f.points) < 3:
            continue
        e = ents.get(f.model) if f.model else None
        if f.model and bspimport._hidden(e):
            continue
        if f.model and bspimport.invisible_entity(e):
            out.append(i)
        elif not bspimport.water_face_drawn(bsp, f, e):
            out.append(i)
    return out


def _opaque(e: Optional[dict], f) -> bool:
    """A face nothing shows through: no see-through texture, no water, a brush entity drawn as solid colour."""
    t = str(f.texture)
    if t.startswith(("{", "!", "*")):
        return False
    if not e:
        return True
    try:
        mode, amt = int(e.get("rendermode", 0) or 0), float(e.get("renderamt", 255) or 0)
    except ValueError:
        return False
    return mode in (0, 4) or (mode in (1, 2) and amt >= 255)


def buried_faces(bsp, gap: float = 0.6, tree=None) -> List[int]:
    """Faces pressed against another brush, face to face (de_cbble_csgo: the bottom of a crate on the ground, the top
    of a beam against a ceiling, two func_walls touching): CS hides them, Torrente draws every face from both sides,
    so the two faces on one plane fight - a dark patch blinking on the floor, a ceiling flickering.  A face goes when
    faces looking the other way within ``gap`` cover it (its middle and corners), they are of brushes nothing shows
    through, and just in front of it is solid inside one of those brushes.  Decals moved off their walls stay.
    ``tree``: point contents of hull 0 to use (the file's by default)."""
    key = ("buried", float(gap), id(tree) if tree is not None else None)
    memo = getattr(bsp, "_bspfix_memo", None)
    if memo is None:
        memo = {}
        try:
            bsp._bspfix_memo = memo
        except AttributeError:
            pass
    if key not in memo:
        try:
            memo[key] = _buried_faces(bsp, gap, tree)
        except Exception:                                   # (a .bsp without its node tree: none)
            memo[key] = []
    return list(memo[key])


def _buried_faces(bsp, gap: float, tree=None) -> List[int]:
    from . import bspimport
    from .bspgrille import _Tree, SOLID
    if tree is None:
        raw = getattr(bsp, "raw", b"")
        if not raw:
            return []
        tree = _Tree(raw, 0)
        if not len(tree.plane):
            return []
    ents = bspimport.model_entities(bsp)
    shift = _entity_shift(bsp)
    ids = {id(f): i for i, f in enumerate(bsp.faces)}
    F = [f for f in bspimport.drawn_faces(bsp) if id(f) in ids and len(f.points) >= 3
         and not (f.model and (bspimport._hidden(ents.get(f.model)) or bspimport.invisible_entity(ents.get(f.model))))
         and bspimport.water_face_drawn(bsp, f, ents.get(f.model) if f.model else None)]
    if not F:
        return []
    decals = set(overlay_shifts(bsp))
    P = [np.asarray(f.points, np.float64) + shift.get(f.model, 0.0) for f in F]
    N = np.array([np.asarray(f.normal, np.float64) / max(np.linalg.norm(f.normal), 1e-12) for f in F])
    C = np.array([p.mean(0) for p in P])
    D = np.einsum("ij,ij->i", N, C)
    lo = np.array([p.min(0) for p in P])
    hi = np.array([p.max(0) for p in P])
    opaque = np.array([_opaque(ents.get(f.model) if f.model else None, f) for f in F])
    M = np.array([int(f.model) for f in F])
    # faces by plane (the direction either way, the distance in steps of 1 unit)
    sg = np.where(np.round(N, 3) @ np.array([1e6, 1e3, 1.0]) >= 0, 1.0, -1.0)
    groups: Dict[tuple, list] = {}
    for i in range(len(F)):
        groups.setdefault((tuple(np.round(N[i] * sg[i], 2)), int(np.floor(D[i] * sg[i]))), []).append(i)
    heads = {}

    def solid_in(m, Q):
        if m not in heads:
            heads[m] = tree.head(m) if m < len(getattr(tree, "models", range(m + 1))) else None
        if heads[m] is None:
            return np.zeros(len(Q), bool)
        return tree.contents(heads[m], Q - shift.get(m, 0.0)) == SOLID

    out = []
    for i in range(len(F)):
        if ids[id(F[i])] in decals:
            continue
        g = (tuple(np.round(N[i] * sg[i], 2)), int(np.floor(D[i] * sg[i])))
        ks = [k for dd in (-1, 0, 1) for k in groups.get((g[0], g[1] + dd), ())]
        ks = [k for k in ks if k != i and opaque[k] and N[k] @ N[i] < -0.999 and abs(D[k] + D[i]) <= gap
              and (lo[k] <= hi[i] + 0.5).all() and (hi[k] >= lo[i] - 0.5).all()]
        if not ks:
            continue
        pts = [C[i]] + [C[i] + (q - C[i]) * 0.8 for q in P[i]]
        cover = []
        for q in pts:
            k = next((k for k in ks if _inside(P[k], N[k], q - N[k] * float((q - P[k][0]) @ N[k]))), None)
            if k is None:
                break
            cover.append(M[k])
        if len(cover) < len(pts):
            continue
        Q = np.array(pts) + N[i] * 1.0
        if all(bool(solid_in(int(m), Q[j:j + 1])[0]) for j, m in enumerate(cover)):
            out.append(ids[id(F[i])])
    return sorted(out)


def twin_triangles(P: np.ndarray, tol: float = 0.01) -> np.ndarray:
    """For triangles ``P`` (n, 3, 3) of one texture: True for each one lying on the same three corners as one before it
    (either winding).  CS models make two-sided leaves, cards and lamp shades of two triangles back to back; Torrente
    draws every triangle from both sides, so the pair fights over the same spot (de_inferno_go's yuccas, poplars,
    lamps, pallets) - one is enough."""
    P = np.asarray(P, np.float64).reshape(-1, 3, 3)
    out = np.zeros(len(P), bool)
    seen = set()
    for t in range(len(P)):
        k = tuple(sorted(tuple(np.round(q / tol).astype(np.int64)) for q in P[t]))
        if len(set(k)) < 3:
            continue
        if k in seen:
            out[t] = True
        else:
            seen.add(k)
    return out
