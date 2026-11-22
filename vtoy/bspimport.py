"""A Counter-Strike 1.6 / Half-Life map (.bsp) turned into Torrente Online pieces: textured meshes, collision boxes, floor /
wall faces of the height map and start points.

CS units are inches (1 = 2.54 cm, Z up, right-handed); the engine is 1 = 1 cm, Y up, left-handed.  The map is laid so the
middle of its drawn part (in plan) and its lowest floor go to ``at``; ``yaw`` turns it about the vertical (90 lays the
CS map's Y axis along the engine's X).  CS textures live in .wad files that the .bsp does not carry, so every CS texture is
drawn with a Torrente texture (``guess_texture`` picks one by the name; the editor lets you change each).

    plan(bsp, at, yaw, scale)                       the transform (a Plan) from CS to engine
    convert(bsp, plan, texmap, ...)                 -> Converted: meshes by texture, boxes, height map faces, spawns
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np

from .bsp import BspFace, BspMap

KILL_DROP = 6000.0            # cm under a pool-hole: the floor a falling player dies on
SKIP_WORDS = ("sky", "aaatrigger", "trigger", "clip", "null", "origin", "hint", "skip", "bevel", "invis")
INCH = 2.54

# (words in the CS name, Torrente textures to try in order); the first rule whose words all appear wins
GUESS_RULES: List[Tuple[Tuple[str, ...], Tuple[str, ...]]] = [
    (("mltry",), ("caja2", "CAJA-5", "caja1")),
    (("military",), ("caja2", "caja1")),
    (("crt",), ("caja1", "caja2")),
    (("crate",), ("caja1", "caja2")),
    (("door",), ("porton_arabe", "puerta_almacen", "catedra_muro")),
    (("wndw",), ("catedra_muro", "muro_liso")),
    (("window",), ("Ventanales", "catedra_muro")),
    (("sand", "wall"), ("catedra_muro", "muro_liso")),
    (("sand", "wll"), ("catedra_muro", "muro_liso")),
    (("trim",), ("muro_base", "muro_liso")),
    (("crete",), ("muro_liso", "muro_base")),
    (("concrete",), ("muro_liso",)),
    (("road",), ("SUELO_coliseum1", "SUELOS_03")),
    (("rock",), ("SUELOS_05", "SUELOS_14")),
    (("sand",), ("SUELOS_03", "SUELO_coliseum1")),
    (("grass",), ("SUELOS_04", "cesped")),
    (("dirt",), ("SUELOS_01",)),
    (("wood",), ("madera vieja", "catedra_madera")),
    (("brick",), ("muro_mitad", "catedra_muro")),
    (("wall",), ("muro_liso", "catedra_muro")),
    (("floor",), ("SUELOS_12", "SUELOS_01")),
]
FALLBACK = ("muro_liso", "catedra_muro", "SUELOS_03")


def skipped(name: str) -> bool:
    n = name.lower()
    return not n or any(w in n for w in SKIP_WORDS)


def guess_texture(name: str, exists: Callable[[str], bool] = lambda n: True) -> str:
    """A Torrente texture (``name.tex``) for the CS texture ``name``; ``exists`` says which textures the game has."""
    n = name.lower().lstrip("-+~{!0123456789")
    for words, picks in GUESS_RULES:
        if all(w in n for w in words):
            for p in picks:
                if exists(p + ".tex"):
                    return p + ".tex"
    for p in FALLBACK:
        if exists(p + ".tex"):
            return p + ".tex"
    return FALLBACK[0] + ".tex"


@dataclass
class Plan:
    scale: float = INCH
    yaw: float = 90.0
    at: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    centre: Tuple[float, float, float] = (0.0, 0.0, 0.0)      # the CS point that goes to ``at`` (middle in plan, floor)

    def R(self) -> np.ndarray:
        a = math.radians(self.yaw)
        c, s = math.cos(a), math.sin(a)
        return np.array([[c, 0.0, -s], [0.0, 1.0, 0.0], [s, 0.0, c]])

    def point(self, p) -> np.ndarray:
        """CS (x, y, z) -> engine; (x, y, z) -> (x, z, y) keeps the shape (right- to left-handed), then the turn."""
        p = np.asarray(p, np.float64) - np.asarray(self.centre, np.float64)
        q = p[..., [0, 2, 1]] * self.scale
        return q @ self.R() + np.asarray(self.at, np.float64)

    def direction(self, d) -> np.ndarray:
        d = np.asarray(d, np.float64)
        return d[..., [0, 2, 1]] @ self.R()

    def angle(self, cs_degrees: float) -> float:
        """A CS yaw (degrees, 0 = +x, about +z) -> a start point angle (radians, looking along (sin a, cos a) in x, z)."""
        a = math.radians(cs_degrees)
        d = self.direction((math.cos(a), math.sin(a), 0.0))
        return math.atan2(d[0], d[2]) % (2 * math.pi)


CONTENTS_SOLID, CONTENTS_SKY = -2, -6


def _front_contents(raw: bytes):
    """A function (point) -> what the map's own tree (hull 0) has there: -1 empty, -2 solid, -3 water, -6 sky ...;
    None when the .bsp has no tree to ask."""
    try:
        from . import bsphull
        L = bsphull._lumps(raw)
        planes = np.frombuffer(L[1], np.dtype([("n", "<f4", 3), ("d", "<f4"), ("t", "<i4")]))
        nodes = np.frombuffer(L[5], np.dtype([("plane", "<i4"), ("c", "<i2", 2), ("mins", "<i2", 3), ("maxs", "<i2", 3),
                                              ("ff", "<u2"), ("nf", "<u2")]))
        leafs = np.frombuffer(L[10], np.dtype([("contents", "<i4"), ("vis", "<i4"), ("mins", "<i2", 3),
                                               ("maxs", "<i2", 3), ("fm", "<u2"), ("nm", "<u2"), ("amb", "u1", 4)]))
    except Exception:
        return None
    if not len(nodes) or not len(leafs):
        return None
    pn = np.array([pl["n"] for pl in planes], np.float64) if len(planes) else np.zeros((0, 3))
    pd = planes["d"].astype(np.float64)
    child = nodes["c"].astype(np.int64)
    pidx = nodes["plane"].astype(np.int64)
    cont = leafs["contents"].astype(np.int64)

    def contents(p):
        node = 0
        while node >= 0:
            k = pidx[node]
            node = int(child[node, 0] if float(p @ pn[k]) - pd[k] >= 0 else child[node, 1])
        i = -node - 1
        return int(cont[i]) if 0 <= i < len(cont) else CONTENTS_SOLID
    return contents


def drawn_faces(bsp: BspMap):
    """The faces CS draws: no tool textures, and none of the world's faces that look into a sky brush or into solid
    (the top of a wall a sky brush sits on, the outer side of a "sky ceiling" - nobody sees them in CS; in a Torrente
    map they would be a ceiling over the streets, e.g. de_aztec's olive barrel2b tops)."""
    faces = [f for f in bsp.faces if not skipped(f.texture) and len(f.points) >= 3]
    raw = getattr(bsp, "raw", b"")
    look = _front_contents(raw) if raw else None
    if look is None:
        return faces
    out = []
    for f in faces:
        if getattr(f, "model", 0) == 0:
            p = np.asarray(f.points, np.float64)
            n = np.asarray(f.normal, np.float64)
            c = p.mean(0)
            # all of it: the middle and near each corner (a face partly against another brush - the pieces of an
            # arch over a door - is still seen where it is free)
            probes = [look(q + n * 1.0) for q in [c] + [c + (v - c) * 0.7 for v in p]]
            if all(r in (CONTENTS_SOLID, CONTENTS_SKY) for r in probes) and CONTENTS_SKY in probes:
                continue                                  # against solid only: buried, drawn anyway (no cracks)
        out.append(f)
    return out


# brush entities: how each class is brought in
HIDDEN_CLASSES = ("func_door", "func_door_rotating", "func_buyzone", "func_bomb_target", "func_hostage_rescue",
                  "func_vip_safetyzone", "func_escapezone", "func_ladder", "func_clip")      # doors: an open way through
NONSOLID_CLASSES = ("func_illusionary",)                     # seen, walked through
WATER_CLASSES = ("func_water",)                              # seen; its top is a floor (nobody swims in Torrente)


def _water_face_seen(f, box, look=None) -> bool:
    """Is this face of a water volume (func_water) one to draw?  Only its top, seen from above (the material is
    two-sided): the underside of the top, the bottom lying on the pool's floor (the same plane as the floor) and the
    sides under the surface (on the pool's walls, between two water brushes) were drawn too - the water flickered in
    the game (de_aztec)."""
    hi = np.asarray(box[1], np.float64)
    if float(f.normal[2]) <= 0.7:
        return False
    if look is not None:                                      # water at several levels (a river's steps): a top
        c = np.asarray(f.points, np.float64).mean(0)          # is seen when no water of its own lies on it
        try:
            return not look(c + np.array([0.0, 0.0, 1.0]))
        except (IndexError, ValueError):                      # (a .bsp with no tree: the box decides)
            pass
    return float(np.asarray(f.points)[:, 2].max()) >= hi[2] - 1.0


def _water_look(bsp: BspMap, model: int):
    """``look`` for _water_face_seen: is the point inside the brushes of this model (its hull 0)?"""
    memo = getattr(bsp, "_water_trees", None)
    if memo is None:
        memo = {}
        try:
            bsp._water_trees = memo
        except AttributeError:
            pass
    if "tree" not in memo:
        try:
            from .bspgrille import _Tree
            memo["tree"] = _Tree(bsp.raw, 0) if getattr(bsp, "raw", b"") else None
        except Exception:
            memo["tree"] = None
    tree = memo["tree"]
    if tree is None or not len(tree.plane):
        return None
    head = tree.head(model)
    if head < 0:
        return None
    return lambda p: bool(tree.contents(head, np.asarray(p, np.float64)[None])[0] != -1)


def water_face_drawn(bsp: BspMap, f, e: Optional[dict]) -> bool:
    """False for a face of water the import leaves out: of a func_water all but its top (_water_face_seen); of water
    in the world ("!" textures) all but the faces looking up (its surface; the rest lies on the bed and the banks)."""
    cls = e.get("classname", "").lower() if e else ""
    if cls in WATER_CLASSES:
        return not (f.model < len(bsp.models) and bsp.models[f.model] is not None
                    and not _water_face_seen(f, bsp.models[f.model], _water_look(bsp, f.model)))
    if not f.model and str(f.texture).startswith("!"):
        return float(f.normal[2]) > 0.7
    return True


def model_entities(bsp: BspMap) -> Dict[int, dict]:
    """{model number: the brush entity that owns it}."""
    out = {}
    for e in bsp.entities:
        m = e.get("model", "")
        if m.startswith("*") and m[1:].isdigit():
            out[int(m[1:])] = e
    return out


def _hidden(e: Optional[dict]) -> bool:
    if not e:
        return False
    c = e.get("classname", "").lower()
    return c.startswith("trigger") or c in HIDDEN_CLASSES


def invisible_entity(e: Optional[dict]) -> bool:
    """A brush entity not drawn here: a render mode other than normal with render amount 0 (an invisible func_wall
    that only blocks, like "nowallshot"), and an additive one (render mode 5: a beam of sunlight, a glow - CS adds
    its colours to the picture, its black parts vanish; Torrente would draw it as a dark see-through sheet with
    black edges: de_dust2_cs2 before B)."""
    if not e:
        return False
    try:
        mode = int(e.get("rendermode", "0"))
        return (mode != 0 and int(float(e.get("renderamt", "255"))) == 0) or mode == 5
    except ValueError:
        return False


PANEL_THICK = 16.0                                            # a func_breakable thinner than this (CS units): a panel


def open_panels(bsp: BspMap) -> set:
    """Models of the thin breakable panels (a metal sheet, boards, glass over a window or a hole): in CS one shot
    opens them, in Torrente they would stay forever - so they are left out and the opening is open."""
    out = set()
    solid = None
    for m, e in model_entities(bsp).items():
        if e.get("classname", "").lower() != "func_breakable" or m >= len(bsp.models) or bsp.models[m] is None:
            continue
        lo, hi = (np.asarray(v, np.float64) for v in bsp.models[m])
        size = hi - lo
        if min(size[0], size[1]) <= PANEL_THICK and size[2] >= 24.0 and max(size[0], size[1]) >= 24.0:
            # only one over an opening: open on both sides (a board leaning on a crate stays, drawn)
            if solid is None and getattr(bsp, "raw", b""):
                try:
                    from .bspgrille import _Tree
                    tree = _Tree(bsp.raw, 0)
                    solid = (tree, tree.head(0))
                except Exception:
                    solid = False
            if solid:
                tree, head = solid
                axis = 0 if size[0] <= size[1] else 1
                c = (lo + hi) / 2.0
                pts = []
                for sgn in (-1.0, 1.0):
                    for d in (8.0, 16.0, 24.0):
                        for dz in (-0.25, 0.0, 0.25):
                            q = c.copy()
                            q[axis] += sgn * (size[axis] / 2.0 + d)
                            q[2] += dz * size[2]
                            pts.append(q)
                if tree.solid(head, np.array(pts)).any():
                    continue
            out.add(m)
    return out


def translucent_textures(bsp: BspMap) -> Dict[str, int]:
    """{CS texture: alpha 0-255} for the textures only drawn by see-through brush entities (rendermode texture / additive
    with renderamt: water, glass)."""
    ents = model_entities(bsp)
    alpha: Dict[str, int] = {}
    solid = set()
    for f in drawn_faces(bsp):
        e = ents.get(f.model) if f.model else None
        try:
            mode = int(e.get("rendermode", "0")) if e else 0
            amt = int(float(e.get("renderamt", "255"))) if e else 255
        except ValueError:
            mode, amt = 0, 255
        if e and _hidden(e):
            continue
        if mode in (2, 4, 5) and amt < 255:
            alpha[f.texture] = min(alpha.get(f.texture, 255), max(40, amt))
        else:
            solid.add(f.texture)
    return {k: v for k, v in alpha.items() if k not in solid}


def plan(bsp: BspMap, at=(0.0, 0.0, 0.0), yaw: float = 90.0, scale: float = INCH) -> Plan:
    fs = drawn_faces(bsp)
    if not fs:
        raise ValueError("the .bsp has no faces to draw")
    pts = np.concatenate([f.points for f in fs])
    lo, hi = pts.min(0), pts.max(0)
    return Plan(float(scale), float(yaw), tuple(float(v) for v in at),
                (float((lo[0] + hi[0]) / 2), float((lo[1] + hi[1]) / 2), float(lo[2])))


def more_starts(bsp: BspMap, have, n: int, spacing: float = 56.0, reach: float = 160.0, hull=None) -> list:
    """Start points (CS origins) to bring a team's ``have`` up to ``n`` (de_inferno_go has 9 and 11 for 16 a side):
    beside the team's own, within ``reach`` of them, each a player's standing box (hull 1) on the floor with room
    round it, ``spacing`` from every other start, away from the map's models, and a straight walk from the nearest
    start of the team (no wall, no pit, steps up to 18 units).  Fewer if there is no room for more.  ``hull``: the
    player hull to use (the file's hull 1 by default)."""
    O = np.asarray(have, np.float64).reshape(-1, 3)
    if len(O) == 0 or len(O) >= n:
        return []
    h1 = hull
    if h1 is None:
        from .bspgrille import _Tree
        if not getattr(bsp, "raw", b""):
            return []
        h1 = _Tree(bsp.raw, 1)
        if not len(h1.plane):
            return []
    solid = [0] + [int(e["model"][1:]) for e in bsp.entities
                   if e.get("classname") in ("func_wall", "func_breakable", "func_door", "func_door_rotating")
                   and str(e.get("model", "")).startswith("*") and e["model"][1:].isdigit()]
    if hasattr(h1, "models"):
        solid = [m for m in solid if m < len(h1.models)]
    props = []
    for e in bsp.entities:
        if str(e.get("model", "")).lower().endswith(".mdl") and "origin" in e \
                and not e.get("classname", "").startswith("info_player"):
            try:
                props.append([float(v) for v in e["origin"].split()][:2])
            except ValueError:
                pass
    props = np.asarray(props, np.float64).reshape(-1, 2)

    def blocked(P):
        P = np.asarray(P, np.float64).reshape(-1, 3)
        s = np.zeros(len(P), bool)
        for m in solid:
            s |= h1.solid(h1.head(m), P)
        return s

    z = float(np.median(O[:, 2]))
    lo, hi = O.min(0)[:2] - reach, O.max(0)[:2] + reach
    XY = np.array([[x, y] for x in np.arange(lo[0], hi[0], 8.0) for y in np.arange(lo[1], hi[1], 8.0)])
    dz = np.arange(16.0, -48.0, -1.0)
    B = blocked(np.concatenate([np.c_[XY, np.full(len(XY), z + d)] for d in dz])).reshape(len(dz), len(XY))
    first = np.argmax(B, axis=0)                              # from the top down: the first solid one is the floor
    hit = B.any(axis=0) & (first > 0)
    G = np.c_[XY[hit], z + dz[first[hit] - 1] + 0.5]
    if not len(G):
        return []
    ok = np.ones(len(G), bool)
    for d in ([24.0, 0, 0], [-24.0, 0, 0], [0, 24.0, 0], [0, -24.0, 0]):
        ok &= ~blocked(G + d)                                # room for a player beside it
    if len(props):
        ok &= np.min(np.linalg.norm(G[:, None, :2] - props[None, :, :], axis=2), axis=1) > 72.0
    G = G[ok]

    def walk(a, p):
        t = np.linspace(0.0, 1.0, max(2, int(np.linalg.norm(p - a) / 4.0)))[:, None]
        Q = a + (p - a) * t
        return not blocked(Q + [0, 0, 18.0]).any() and blocked(Q - [0, 0, 40.0]).all()

    chosen = list(O)
    out = []
    for i in np.argsort(np.linalg.norm(G - O.mean(0), axis=1)):
        if len(chosen) >= n:
            break
        p = G[i]
        if np.min(np.linalg.norm(np.asarray(chosen)[:, :2] - p[:2], axis=1)) < spacing:
            continue
        if not walk(O[np.argmin(np.linalg.norm(O - p, axis=1))], p):
            continue
        chosen.append(p)
        out.append(p.copy())
    return out


def footprint(bsp: BspMap, pl: Plan) -> Tuple[np.ndarray, np.ndarray]:
    """Engine bounds (lo, hi) of the drawn part once laid with ``pl``."""
    pts = pl.point(np.concatenate([f.points for f in drawn_faces(bsp)]))
    return pts.min(0), pts.max(0)


@dataclass
class Converted:
    meshes: Dict[str, list] = field(default_factory=dict)     # Torrente texture -> [(points, normal, uvs)]
    boxes: list = field(default_factory=list)                 # (centre, half sizes, axes rows)
    hm_faces: list = field(default_factory=list)              # (points, normal) for the height map
    spawns: list = field(default_factory=list)                # (position, angle, team)
    textures: Dict[str, str] = field(default_factory=dict)    # CS texture -> Torrente texture used
    targets: list = field(default_factory=list)               # bomb sites: {name, lo, hi, floor (engine point)}
    step_ramps: int = 0                                       # steps turned into short ramps
    floor_gaps: int = 0                                       # small holes in the floors closed
    slits: int = 0                                            # slits in one floor / slope closed (bridge_plane_gaps)
    pierced: int = 0                                          # CS hull walls cut down to the floor they poked through
    lintels: int = 0                                          # walls hanging over crouch passages dropped
    lips: int = 0                                             # ramps on floor edges over a lower floor (no riser)
    buried: int = 0                                           # floors cut where another floor lies just above them
    stale_boxes: list = field(default_factory=list)           # boxes behind walls that trim / drop changed (before)
    fresh_boxes: list = field(default_factory=list)           # ... and after
    slope_boxes: int = 0                                      # boxes on slopes too steep to walk up in CS
    props: int = 0                                            # studio models drawn (cars, palm trees ...)
    prop_boxes: int = 0                                       # of them with a collision box
    open_panels: int = 0                                      # thin breakable panels left out (an opening)
    invisible: int = 0                                        # faces of invisible brush entities not drawn
    overlays: int = 0                                         # decal faces moved out from their walls (bspfix)
    thin: int = 0                                             # back faces of thin slabs not drawn (bspfix.thin_backs)
    twins: int = 0                                            # model triangles back to back with another, not drawn
    grilles: int = 0                                          # walls with gaps bullets fly through (bspgrille)


def _face_box(p: np.ndarray, n: np.ndarray, thick: float):
    """A box behind the flat face ``p`` (engine) ``thick`` deep.  Like the shipped maps' boxes it is only turned about the
    vertical (rows: x level along the face, y up, z level): exact for walls and floors, around a sloped face."""
    n = n / max(np.linalg.norm(n), 1e-12)
    up = np.array([0.0, 1.0, 0.0])
    h = np.array([n[0], 0.0, n[2]])
    if np.linalg.norm(h) > 1e-3:                              # wall or slope: x along it
        h /= np.linalg.norm(h)
        u = np.array([-h[2], 0.0, h[0]])
    else:                                                     # floor / ceiling: x along its first edge
        e = p[1] - p[0]
        u = np.array([e[0], 0.0, e[2]])
        u = u / np.linalg.norm(u) if np.linalg.norm(u) > 1e-6 else np.array([1.0, 0.0, 0.0])
    R = np.array([u, up, np.cross(u, up)])
    if np.linalg.det(R) < 0:
        R[2] = -R[2]
    q = np.concatenate([p, p - n * thick])
    loc = q @ R.T
    lo, hi = loc.min(0), loc.max(0)
    return ((lo + hi) / 2) @ R, np.maximum((hi - lo) / 2, 0.5), R


STEP_MAX = 46.0              # cm: the highest step a CS player walks up (18 units); higher is a wall
STEP_MIN = 2.0               # cm: lower than this is not a step at all
STEP_RUN = 2.0               # a step becomes a ramp this many times longer than high (about 27 degrees)
WATER_TEXTURE = "agua.tex"   # the sea of the Love Boat


def _wall_boxes(p: np.ndarray, n: np.ndarray, thick: float, min_h: float = STEP_MAX, strip: float = 60.0) -> list:
    """Boxes behind a vertical wall (engine) ``thick`` deep, only where it is higher than a step: a wall whose top is not
    level (the side of a ramp, a gable) gets a box per ``strip`` cm, each no higher than the wall's top there - a box
    never stands over the slope a player walks on."""
    n = n / max(np.linalg.norm(n), 1e-12)
    h = np.array([n[0], 0.0, n[2]])
    if np.linalg.norm(h) < 1e-3:
        return []
    h /= np.linalg.norm(h)
    u = np.array([-h[2], 0.0, h[0]])
    s = p @ u
    y = p[:, 1]
    s0, s1 = float(s.min()), float(s.max())
    if s1 - s0 < 1.0:
        return []

    def section(x):                                       # (lowest, highest) y of the wall at s = x
        ys = []
        k = len(p)
        for i in range(k):
            a, b = i, (i + 1) % k
            if (s[a] - x) * (s[b] - x) <= 0 and abs(s[b] - s[a]) > 1e-9:
                t = (x - s[a]) / (s[b] - s[a])
                ys.append(y[a] + t * (y[b] - y[a]))
            elif abs(s[a] - x) < 1e-9:
                ys.append(y[a])
        return (min(ys), max(ys)) if ys else None
    tops = [section(x) for x in (s0 + 0.01, s1 - 0.01)]
    if all(t is not None for t in tops) and abs(tops[0][1] - tops[1][1]) < 1.0 and abs(tops[0][0] - tops[1][0]) < 1.0:
        cuts = [s0, s1]                                   # a rectangle: one box
    else:
        k = max(1, int(np.ceil((s1 - s0) / strip)))
        cuts = list(np.linspace(s0, s1, k + 1))
    out = []
    d = float(p[0] @ h)
    for a, b in zip(cuts[:-1], cuts[1:]):
        sa, sb = section(a + 0.01), section(b - 0.01)
        if sa is None or sb is None:
            continue
        lo_y, hi_y = max(sa[0], sb[0]), min(sa[1], sb[1])
        if hi_y - lo_y <= min_h:
            continue
        R = np.array([u, [0.0, 1.0, 0.0], np.cross(u, [0.0, 1.0, 0.0])])
        if np.linalg.det(R) < 0:
            R[2] = -R[2]
        c = u * ((a + b) / 2) + np.array([0.0, (lo_y + hi_y) / 2, 0.0]) + h * (d - thick / 2)
        half = np.array([(b - a) / 2, (hi_y - lo_y) / 2, thick / 2])      # R's rows: along, up, across the wall
        out.append((c, np.maximum(half, 0.5), R))
    return out


COLLISION_HULL = 3                                         # CS's crouching hull: what a crouching player gets through
HULL_HALF = {1: (16.0, 16.0, 36.0), 3: (16.0, 16.0, 18.0)}
STEEP_NY = 0.7                                             # CS: steeper than this a player slides off (no floor)
GAME_FLOOR_NY = 0.3                                        # the game: a face of the .hm this level or more is a floor


def _slope_box(p: np.ndarray, n: np.ndarray):
    """A box filling a slope too steep for CS but a floor for the game (engine points, normal up-ish), from its foot to
    its top: a player bumps into it like into a wall instead of walking up a rock face and getting stuck in it."""
    n = n / max(np.linalg.norm(n), 1e-12)
    h = np.array([n[0], 0.0, n[2]])
    if np.linalg.norm(h) < 1e-3:
        return None
    h /= np.linalg.norm(h)
    up = np.array([0.0, 1.0, 0.0])
    u = np.cross(up, h)
    su, sh, y = p @ u, p @ h, p[:, 1]
    if y.max() - y.min() <= STEP_MAX:
        return None
    R = np.array([u, up, h])
    if np.linalg.det(R) < 0:
        R[0] = -R[0]
    c = u * (su.max() + su.min()) / 2 + up * (y.max() + y.min()) / 2 + h * (sh.max() + sh.min()) / 2
    half = np.array([(su.max() - su.min()) / 2, (y.max() - y.min()) / 2, (sh.max() - sh.min()) / 2])
    return (c, np.maximum(half, 0.5), R)


def _floor_at(floors, x: float, z: float, y: float, tol: float = 8.0) -> bool:
    """Is there a floor (engine polygons, normal up) at (x, z) within ``tol`` of height ``y``?"""
    return any(abs(fy - y) <= tol for fy in _floor_heights(floors, x, z, y - tol, y + tol))


def _floor_heights(floors, x: float, z: float, y_lo: float, y_hi: float) -> list:
    """Heights of the floors (engine polygons, normal up) at (x, z) between ``y_lo`` and ``y_hi``."""
    out = []
    for poly, lo, hi in floors:
        if not (lo[0] - 0.5 <= x <= hi[0] + 0.5 and lo[2] - 0.5 <= z <= hi[2] + 0.5):
            continue
        if y_hi < lo[1] or y_lo > hi[1]:
            continue
        q = poly[:, [0, 2]]
        k = len(q)
        sgn = 0
        ok = True
        for i in range(k):
            a, b = q[i], q[(i + 1) % k]
            c = (b[0] - a[0]) * (z - a[1]) - (b[1] - a[1]) * (x - a[0])
            if abs(c) < 1e-6:
                continue
            if sgn == 0:
                sgn = 1 if c > 0 else -1
            elif (c > 0) != (sgn > 0):
                ok = False
                break
        if not ok:
            continue
        n = np.cross(poly[1] - poly[0], poly[2] - poly[0])
        if abs(n[1]) < 1e-9:
            continue
        fy = poly[0][1] - (n[0] * (x - poly[0][0]) + n[2] * (z - poly[0][2])) / n[1]
        if y_lo <= fy <= y_hi:
            out.append(float(fy))
    return out


def _tread(floors, edge: np.ndarray, h: np.ndarray, y0: float, most: float, rise: float) -> float:
    """How far the floor in front of a step (at height ``y0``, from the step's ``edge`` along ``h``) goes before it
    drops (the next step down of a staircase), at most ``most``: a step's ramp ends there, on the top edge of the ramp
    below - one even slope up the stairs, never a ramp's foot hanging over the next one (de_inferno's banana, de_cbble's
    stairs: a player stopped at every such lip).  Never shorter than 0.6 x the rise (no slope steeper than ~60°)."""
    s = 2.0
    while s <= most:
        q = edge + h * s
        ys = _floor_heights(floors, q[0], q[2], y0 - 120.0, y0 + 2.0)
        if not ys or max(ys) < y0 - 3.0:
            lo, hi = s - 2.0, s                           # (to the mm: the next ramp starts right there)
            for _ in range(7):
                mid = (lo + hi) / 2
                q = edge + h * mid
                ys = _floor_heights(floors, q[0], q[2], y0 - 120.0, y0 + 2.0)
                if not ys or max(ys) < y0 - 3.0:
                    hi = mid
                else:
                    lo = mid
            return max(lo, rise * 0.6)
        s += 2.0
    return most


def step_ramps(faces: list, step_max: float = STEP_MAX, run: float = STEP_RUN) -> Tuple[list, int]:
    """Steps made walkable for the game: in CS a player walks up any step up to 18 units (46 cm), in Torrente he stops
    at a small one.  Every low vertical face of the height map (``faces``: engine (points, normal)) with a floor on top
    of it and a floor in front of it becomes a short ramp (``run`` times longer than high) lying on the lower floor up
    to the step's edge, and the vertical face goes - only along the part of the step that has both floors (a diving
    board: from the deck, not over the water).  A low face hidden under a floor in front of it (a ramp running up to a
    landing: a step only for the box of a CS player) goes too.  On stairs whose treads are shorter than the ramp, the
    ramp ends where its tread does (``_tread``): the ramps of a staircase join into one even slope.
    -> (new faces, ramps made)."""
    floors = []
    for p, n in faces:
        nn = n / max(np.linalg.norm(n), 1e-12)
        if nn[1] > 0.7:
            floors.append((p, p.min(0), p.max(0)))
    out, made = [], 0
    for p, n in faces:
        nn = n / max(np.linalg.norm(n), 1e-12)
        h = np.array([nn[0], 0.0, nn[2]])
        y0, y1 = float(p[:, 1].min()), float(p[:, 1].max())
        if abs(nn[1]) > 0.17 or not (STEP_MIN < y1 - y0 <= step_max) or np.linalg.norm(h) < 0.5:
            out.append((p, n))
            continue
        h /= np.linalg.norm(h)
        u = np.array([-h[2], 0.0, h[0]])
        top = p[p[:, 1] > y1 - 1.0]                       # the step's edge (level)
        ts = top @ u
        if len(top) < 2 or ts.max() - ts.min() < 10.0:
            out.append((p, n))
            continue
        a = top[int(np.argmin(ts))].copy()
        b = top[int(np.argmax(ts))].copy()
        a[1] = b[1] = y1
        rise = y1 - y0
        L = float((b - a) @ u)
        k = max(2, int(np.ceil(L / 10.0)) + 1)
        flags = []
        for t in np.linspace(0.02, 0.98, k):
            x = a + (b - a) * t
            front = x + h * 6.0
            if _floor_heights(floors, front[0], front[2], y0 + rise * 0.5, y1 + 8.0):
                flags.append(2)                           # buried under a floor in front of it: nothing there
            elif _floor_at(floors, *(x - h * 6.0)[[0, 2]], y1) and _floor_at(floors, *front[[0, 2]], y0):
                flags.append(1)                           # a step: a ramp
            else:
                flags.append(0)                           # a wall (a board's edge over the water)
        if not any(flags):
            out.append((p, n))
            continue
        ts_s = np.linspace(0.02, 0.98, k) * L
        bounds = [0.0] + [float((ts_s[i] + ts_s[i + 1]) / 2) for i in range(k - 1)] + [L]
        s0 = float(a @ u)
        runs, i = [], 0
        while i < k:                                      # stretches of the same kind along the step
            j = i
            while j + 1 < k and flags[j + 1] == flags[i]:
                j += 1
            runs.append((flags[i], bounds[i], bounds[j + 1]))
            i = j + 1
        length = max(rise * run, 15.0)
        for kind, t0, t1 in runs:
            if t1 - t0 < 1.0:
                continue
            piece = _clip_u(p, u, s0 + t0, s0 + t1)
            if kind == 0:
                if piece is not None:
                    out.append((piece, n))
                continue
            if kind == 2:
                continue
            pa, pb = a + u * t0, a + u * t1
            pa[1] = pb[1] = y1
            run_len = min(length, _tread(floors, (pa + pb) / 2, h, y0, length, rise))
            foot = np.array([0.0, -rise, 0.0]) + h * run_len
            ramp = np.array([pa, pb, pb + foot, pa + foot])
            nr = np.cross(ramp[1] - ramp[0], ramp[3] - ramp[0])
            if nr[1] < 0:
                ramp = ramp[::-1].copy()
                nr = -nr
            out.append((ramp, nr / np.linalg.norm(nr)))
            made += 1
    return out, made


def _floor_grid(faces, cell: float = 100.0):
    """The floors (normal up) of ``faces`` (engine (points, normal, ...)), by cells of ``cell`` cm: a lookup for
    ``_floor_heights``."""
    grid: Dict[Tuple[int, int], list] = {}
    for f in faces:
        p, n = f[0], f[1]
        nn = n / max(np.linalg.norm(n), 1e-12)
        if nn[1] < GAME_FLOOR_NY:
            continue
        lo, hi = p.min(0), p.max(0)
        e = (p, lo, hi)
        for i in range(int(np.floor(lo[0] / cell)), int(np.floor(hi[0] / cell)) + 1):
            for k in range(int(np.floor(lo[2] / cell)), int(np.floor(hi[2] / cell)) + 1):
                grid.setdefault((i, k), []).append(e)
    return grid


def _top_bottom_at(p: np.ndarray, u: np.ndarray, t: float):
    """Where the vertical line at p.u = t meets the (vertical) polygon ``p``: (lowest point, highest point) or None."""
    s = p @ u
    ys, pts = [], []
    for i in range(len(p)):
        a, b = p[i], p[(i + 1) % len(p)]
        sa, sb = s[i], s[(i + 1) % len(p)]
        if (sa - t) * (sb - t) <= 0 and abs(sb - sa) > 1e-9:
            q = a + (b - a) * ((t - sa) / (sb - sa))
            pts.append(q)
            ys.append(q[1])
    if len(pts) < 2:
        return None
    return pts[int(np.argmin(ys))], pts[int(np.argmax(ys))]


PIERCE_PROBE = 6.0                                         # cm in front of / behind a wall a floor is looked for


def trim_pierced_walls(coll: list, cell: float = 100.0) -> Tuple[list, int]:
    """A wall of CS's hull that pokes up through the middle of a floor (a floor at the same height on both sides of
    it, above the wall's foot and below its top) is cut down to that floor.  CS's crouching hull has such walls where
    the compiler left a thin empty pocket under a floor (de_inferno's banana: a pocket's wall stood 56 cm out of the
    floor across the whole street - an invisible wall that stopped players and bullets).  A real wall never does: a
    floor beside a wall ends at it.  ``coll``: [(engine points, normal, ...rest)].  -> (coll, walls cut)."""
    grid = _floor_grid(coll, cell)

    def floors_near(x, z):
        return grid.get((int(np.floor(x / cell)), int(np.floor(z / cell))), ())

    out, cut_n = [], 0
    for f in coll:
        p, n = f[0], f[1]
        nn = n / max(np.linalg.norm(n), 1e-12)
        h = np.array([nn[0], 0.0, nn[2]])
        y0, y1 = float(p[:, 1].min()), float(p[:, 1].max())
        if abs(nn[1]) > 0.17 or np.linalg.norm(h) < 0.5 or y1 - y0 < 4.0 or (len(f) > 3 and f[3]):
            out.append(f)
            continue
        h /= np.linalg.norm(h)
        u = np.array([-h[2], 0.0, h[0]])
        s = p @ u
        s0, s1 = float(s.min()), float(s.max())
        if s1 - s0 < 1.0:
            out.append(f)
            continue
        k = max(2, int(np.ceil((s1 - s0) / 10.0)) + 1)
        ts = np.linspace(s0 + 0.5, s1 - 0.5, k) if s1 - s0 > 1.5 else np.array([(s0 + s1) / 2])
        cuts = []
        for t in ts:
            tb = _top_bottom_at(p, u, float(t))
            c = None
            if tb is not None:
                lo, hi = tb
                if hi[1] - lo[1] > 4.0:
                    ok = []
                    for side in (-1.0, 1.0):
                        q = hi + h * (side * PIERCE_PROBE)
                        ok.append(_floor_heights(floors_near(q[0], q[2]), q[0], q[2], lo[1] + 2.0, hi[1] - 2.0))
                    best = [a for a in ok[0] if any(abs(a - b) <= 3.0 for b in ok[1])]
                    if best:
                        c = max(best)
            cuts.append(c)
        if all(c is None for c in cuts):
            out.append(f)
            continue
        bounds = [s0] + [float((ts[i] + ts[i + 1]) / 2) for i in range(len(ts) - 1)] + [s1]
        i = 0
        while i < len(ts):                                  # stretches: uncut, or cut at about the same height
            j = i
            while j + 1 < len(ts) and ((cuts[i] is None) == (cuts[j + 1] is None)) and \
                    (cuts[i] is None or abs(cuts[j + 1] - cuts[i]) <= 2.0):
                j += 1
            piece = _clip_u(p, u, bounds[i], bounds[j + 1])
            if piece is not None:
                if cuts[i] is not None:
                    top = max(c for c in cuts[i:j + 1])
                    piece, _uv = _clip(piece, np.zeros((len(piece), 2)), 1, top, True)
                    piece = piece if len(piece) >= 3 and piece[:, 1].max() - piece[:, 1].min() > 0.5 else None
                if piece is not None:
                    out.append((piece,) + tuple(f[1:]))
            i = j + 1
        cut_n += 1
    return out, cut_n


CROUCH_MIN = 80.0            # cm: under a wall hanging this high (or more) over a floor, a CS player crouches through
STAND_H = 183.0              # cm: CS's standing player (72 units); a wall hanging higher than this stops nobody


def _coll_boxes(f, thick: float) -> list:
    """The boxes ``convert`` puts behind one wall of the hull (``f``: engine points, normal, model, bar)."""
    q, n = f[0], f[1]
    ny = n[1] / max(np.linalg.norm(n), 1e-12)
    if abs(ny) >= 0.17:
        return []
    bar = len(f) > 3 and f[3]
    return _wall_boxes(q, n, min(thick, 15.0), 0.0 if bar else STEP_MAX)


def drop_hanging_walls(coll: list, cell: float = 100.0) -> Tuple[list, int]:
    """Walls hanging in the air over a floor, between a crouching and a standing player's height above it: the lintel
    of a passage CS players crawl through (de_inferno's drain).  A Torrente player cannot crouch, so the lintel stopped
    him at the passage; worse, the passage is often a pit he had jumped down into - he was stuck for good.  Such walls
    go (the player walks through standing).  ``coll``: [(engine points, normal, ...)].  -> (coll, walls dropped)."""
    grid = _floor_grid(coll, cell)

    def floors_near(x, z):
        return grid.get((int(np.floor(x / cell)), int(np.floor(z / cell))), ())

    out, n_drop = [], 0
    for f in coll:
        p, n = f[0], f[1]
        nn = n / max(np.linalg.norm(n), 1e-12)
        h = np.array([nn[0], 0.0, nn[2]])
        if abs(nn[1]) > 0.17 or np.linalg.norm(h) < 0.5 or (len(f) > 3 and f[3]):
            out.append(f)
            continue
        h /= np.linalg.norm(h)
        y0 = float(p[:, 1].min())
        bottom = p[p[:, 1] < y0 + 1.0]
        mid = bottom.mean(0)
        ok = True
        for side in (1.0, -1.0):                            # a floor under it on both sides, crouching room only
            q = mid + h * (side * PIERCE_PROBE)
            ys = _floor_heights(floors_near(q[0], q[2]), q[0], q[2], y0 - STAND_H, y0 + 1.0)
            if not ys or not (CROUCH_MIN <= y0 - max(ys) <= STAND_H):
                ok = False
                break
        if ok:
            n_drop += 1
            continue
        out.append(f)
    return out, n_drop


LIP_PROBE = (3.0, 12.0)      # cm out from a floor's edge: where the floor below it is looked for (it must be level)


def lip_ramps(faces: list, step_max: float = STEP_MAX, run: float = STEP_RUN) -> Tuple[list, int]:
    """A floor whose edge stands over a lower floor (up to a step) without a wall under the edge - CS's hull leaves no
    riser there when the step is small or belongs to another solid (de_inferno's drain: 10 cm; the first step of a
    staircase made as a func_wall: 20 cm) - so ``step_ramps`` makes no ramp and the game's player stops at it.  Such an
    edge gets a ramp down onto the lower floor, like a step.  ``faces``: engine (points, normal).  -> (faces, made)."""
    floors = []
    for p, n in faces:
        nn = n / max(np.linalg.norm(n), 1e-12)
        if nn[1] >= GAME_FLOOR_NY:
            floors.append((p, p.min(0), p.max(0)))
    grid: Dict[Tuple[int, int], list] = {}
    cell = 100.0
    for e in floors:
        lo, hi = e[1], e[2]
        for i in range(int(np.floor(lo[0] / cell)), int(np.floor(hi[0] / cell)) + 1):
            for k in range(int(np.floor(lo[2] / cell)), int(np.floor(hi[2] / cell)) + 1):
                grid.setdefault((i, k), []).append(e)

    def near(x, z):
        return grid.get((int(np.floor(x / cell)), int(np.floor(z / cell))), ())

    def heights(q, lo, hi):
        return _floor_heights(near(q[0], q[2]), q[0], q[2], lo, hi)

    new, made = [], 0
    for p, n in faces:
        nn = n / max(np.linalg.norm(n), 1e-12)
        if nn[1] < 0.9 or len(p) < 3:
            continue
        c = p.mean(0)
        for i in range(len(p)):
            a, b = p[i], p[(i + 1) % len(p)]
            e = b - a
            e[1] = 0.0
            L = float(np.linalg.norm(e))
            if L < 10.0:
                continue
            u = e / L
            h = np.array([u[2], 0.0, -u[0]])
            if float(h @ ((a + b) / 2 - c)) < 0:
                h = -h
            k = max(2, int(np.ceil(L / 10.0)) + 1)
            ts = np.linspace(0.05, 0.95, k)
            rises = []
            for t in ts:
                x = a + (b - a) * t
                q1, q2 = x + h * LIP_PROBE[0], x + h * LIP_PROBE[1]
                r = None
                if not heights(q1, x[1] - 0.6, x[1] + 0.6):
                    l1 = heights(q1, x[1] - step_max, x[1] - STEP_MIN)
                    l2 = heights(q2, x[1] - step_max, x[1] - STEP_MIN)
                    if l1 and l2 and abs(max(l1) - max(l2)) < 1.0 and not heights(q2, max(l1) + 1.0, x[1] + 0.6):
                        r = x[1] - max(l1)
                rises.append(r)
            j = 0
            while j < k:
                if rises[j] is None:
                    j += 1
                    continue
                m = j
                while m + 1 < k and rises[m + 1] is not None and abs(rises[m + 1] - rises[j]) < 1.0:
                    m += 1
                if m > j or L < 20.0:
                    t0 = 0.0 if j == 0 else (ts[j - 1] + ts[j]) / 2
                    t1 = 1.0 if m == k - 1 else (ts[m] + ts[m + 1]) / 2
                    pa, pb = a + (b - a) * t0, a + (b - a) * t1
                    rise = float(np.mean([r for r in rises[j:m + 1]]))
                    y_lo = float(((pa + pb) / 2)[1]) - rise
                    length = max(rise * run, 15.0)
                    run_len = min(length, _tread(floors, (pa + pb) / 2, h, y_lo, length, rise))
                    foot = np.array([0.0, -rise, 0.0]) + h * run_len
                    ramp = np.array([pa, pb, pb + foot, pa + foot])
                    nr = np.cross(ramp[1] - ramp[0], ramp[3] - ramp[0])
                    if nr[1] < 0:
                        ramp = ramp[::-1].copy()
                        nr = -nr
                    if np.linalg.norm(nr) > 1e-6:
                        new.append((ramp, nr / np.linalg.norm(nr)))
                        made += 1
                j = m + 1
    return faces + new, made


BURIED_CLEAR = 85.0          # cm: a floor with another floor less than this above it holds nobody (CS crouches in 91)


def _clip_half(q: np.ndarray, A: float, B: float, C: float) -> Optional[np.ndarray]:
    """The part of the convex 2-D polygon ``q`` (x, z) where A x + B z + C >= 0."""
    d = q[:, 0] * A + q[:, 1] * B + C
    out = []
    for i in range(len(q)):
        j = (i + 1) % len(q)
        if d[i] >= 0:
            out.append(q[i])
        if (d[i] >= 0) != (d[j] >= 0):
            out.append(q[i] + (q[j] - q[i]) * (d[i] / (d[i] - d[j])))
    if len(out) < 3:
        return None
    r = np.array(out)
    a = 0.5 * abs(float(np.sum(r[:, 0] * np.roll(r[:, 1], -1) - np.roll(r[:, 0], -1) * r[:, 1])))
    return r if a > 1e-3 else None


def _plane_y(p: np.ndarray, n: np.ndarray):
    """(a, b, c): y = a x + b z + c on the plane of the polygon ``p`` with normal ``n``."""
    nn = n / max(np.linalg.norm(n), 1e-12)
    d = -float(nn @ p[0])
    return -nn[0] / nn[1], -nn[2] / nn[1], -d / nn[1]


def _edges_halfplanes(q: np.ndarray):
    """The convex 2-D polygon ``q`` as half-planes (A, B, C) with A x + B z + C >= 0 inside."""
    s = 0.5 * float(np.sum(q[:, 0] * np.roll(q[:, 1], -1) - np.roll(q[:, 0], -1) * q[:, 1]))
    sg = 1.0 if s > 0 else -1.0
    hp = []
    for i in range(len(q)):
        a, b = q[i], q[(i + 1) % len(q)]
        A, B = -(b[1] - a[1]) * sg, (b[0] - a[0]) * sg
        ln = np.hypot(A, B)
        if ln < 1e-9:
            continue
        A, B = A / ln, B / ln
        hp.append((A, B, -(A * a[0] + B * a[1])))
    return hp


def drop_buried_floors(faces: list, clear: float = BURIED_CLEAR, cell: float = 100.0, solids=()) -> Tuple[list, int]:
    """The parts of floors lying less than ``clear`` under another floor go: nobody stands there, but the game found
    them - the flat tread of a step under its ramp (de_cbble: the player sank into the stairs and walked about inside
    them).  ``solids``: [(engine points, normal, bottom y)] the tops of solid brush entities (a staircase, a crate made
    as a func_wall): the map's floor under them goes at any depth down to their bottom - in CS it is inside the solid.
    Kept: the ramps / upper floors, and every part with room over it.  ``faces``: engine (points, normal).
    -> (faces, floors cut)."""
    fl = []
    for i, (p, n) in enumerate(faces):
        nn = n / max(np.linalg.norm(n), 1e-12)
        if nn[1] >= GAME_FLOOR_NY and len(p) >= 3:
            fl.append(i)
    grid: Dict[Tuple[int, int], list] = {}
    box = {}
    covers = {}                                          # index (past the faces) -> (points, normal, bottom)
    for k, (p, n, bottom) in enumerate(solids):
        nn = n / max(np.linalg.norm(n), 1e-12)
        if nn[1] < GAME_FLOOR_NY or len(p) < 3:
            continue
        j = len(faces) + k
        covers[j] = (p, n, float(bottom))
        box[j] = (p.min(0), p.max(0))
    for i in fl + list(covers):
        p = faces[i][0] if i < len(faces) else covers[i][0]
        lo, hi = p.min(0), p.max(0)
        box[i] = (lo, hi)
        for gx in range(int(np.floor(lo[0] / cell)), int(np.floor(hi[0] / cell)) + 1):
            for gz in range(int(np.floor(lo[2] / cell)), int(np.floor(hi[2] / cell)) + 1):
                grid.setdefault((gx, gz), []).append(i)
    out, cut = [], 0
    fset = set(fl)
    for i, (p, n) in enumerate(faces):
        if i not in fset:
            out.append((p, n))
            continue
        lo, hi = box[i]
        cand = set()
        for gx in range(int(np.floor(lo[0] / cell)), int(np.floor(hi[0] / cell)) + 1):
            for gz in range(int(np.floor(lo[2] / cell)), int(np.floor(hi[2] / cell)) + 1):
                cand.update(grid.get((gx, gz), ()))
        fa, fb, fc = _plane_y(p, n)
        q = p[:, [0, 2]].astype(np.float64)
        pieces = [q]
        changed = False
        for j in sorted(cand):
            if j == i:
                continue
            lo2, hi2 = box[j]
            solid = j in covers
            if hi2[0] < lo[0] or lo2[0] > hi[0] or hi2[2] < lo[2] or lo2[2] > hi[2] or hi2[1] < lo[1] + 0.5 or \
                    (not solid and lo2[1] > hi[1] + clear) or (solid and hi[1] < covers[j][2] - 2.0):
                continue
            pj, nj = (faces[j] if not solid else covers[j][:2])
            ga, gb, gc = _plane_y(pj, nj)
            # the region of j over i with 0.5 < (y_j - y_i) <= clear (a solid's top: i not under its bottom): convex
            hps = _edges_halfplanes(pj[:, [0, 2]].astype(np.float64))
            da, db, dc = ga - fa, gb - fb, gc - fc
            hps.append((da, db, dc - 0.5))
            if solid:
                hps.append((fa, fb, fc - (covers[j][2] - 2.0)))
            else:
                hps.append((-da, -db, clear - dc))
            nxt = []
            for g in pieces:
                inside = g
                for A, B, C in hps:
                    inside = _clip_half(inside, A, B, C)
                    if inside is None:
                        break
                if inside is None:
                    nxt.append(g)
                    continue
                changed = True
                rest = g                                  # g minus the convex region: its outside, edge by edge
                for A, B, C in hps:
                    o = _clip_half(rest, -A, -B, -C)
                    if o is not None:
                        nxt.append(o)
                    rest = _clip_half(rest, A, B, C)
                    if rest is None:
                        break
            pieces = nxt
            if not pieces:
                break
        if not changed:
            out.append((p, n))
            continue
        cut += 1
        for g in pieces:
            a2 = 0.5 * abs(float(np.sum(g[:, 0] * np.roll(g[:, 1], -1) - np.roll(g[:, 0], -1) * g[:, 1])))
            if a2 < 4.0:                                  # slivers under a few cm²
                continue
            y = fa * g[:, 0] + fb * g[:, 1] + fc
            out.append((np.column_stack([g[:, 0], y, g[:, 1]]), n))
    return out, cut


SEAM_GROW = 1.5                                            # cm every floor of the height map reaches past its edges
GAP_MAX = 70.0                                             # cm: a floor gap this narrow is never a solid's inside


def _grow_polygon(q: np.ndarray, n: np.ndarray, d: float) -> np.ndarray:
    """The flat convex polygon ``q`` (normal ``n``) with every edge moved out by ``d`` in its plane."""
    keep = [q[0]]
    for v in q[1:]:                                       # points closer than a few mm: one (their edge has no
        if np.linalg.norm(v - keep[-1]) > 0.3:            # reliable direction)
            keep.append(v)
    if len(keep) > 1 and np.linalg.norm(keep[0] - keep[-1]) <= 0.3:
        keep.pop()
    if len(keep) < 3:
        return q
    q = np.array(keep)
    k = len(q)
    c = q.mean(0)
    outs = []
    for i in range(k):
        e = q[(i + 1) % k] - q[i]
        ln = np.linalg.norm(e)
        if ln < 1e-9:
            outs.append(None)
            continue
        o = np.cross(e / ln, n)
        if np.dot(o, (q[i] + q[(i + 1) % k]) / 2 - c) < 0:
            o = -o
        outs.append(o / max(np.linalg.norm(o), 1e-12))
    res = []
    for i in range(k):
        a, b = outs[i - 1], outs[i]
        if a is None and b is None:
            res.append(q[i])
            continue
        if a is None or b is None:
            res.append(q[i] + d * (a if b is None else b))
            continue
        s = 1.0 + float(np.dot(a, b))
        m = (a + b) / max(s, 0.25)                        # miter, cut short at very sharp corners
        res.append(q[i] + d * m)
    return np.array(res)


def _inside_xz(p: np.ndarray, x: float, z: float) -> bool:
    """Is (x, z) inside the convex polygon ``p`` seen from above (not on its edge)?"""
    q = p[:, [0, 2]]
    sgn = 0
    for i in range(len(q)):
        a, b = q[i], q[(i + 1) % len(q)]
        c = (b[0] - a[0]) * (z - a[1]) - (b[1] - a[1]) * (x - a[0])
        if abs(c) < 1e-6:
            return False
        if sgn == 0:
            sgn = 1 if c > 0 else -1
        elif (c > 0) != (sgn > 0):
            return False
    return True


BRIDGE_MAX = 40.0                                          # cm: a slit this wide in one floor or slope is closed


SLIT_RISE = 20.0                                           # cm: the most two floors across a slit may differ


def bridge_plane_gaps(faces: list, gap_max: float = BRIDGE_MAX, rise: float = SLIT_RISE) -> Tuple[list, int]:
    """Slits in the floors of the height map closed (engine (points, normal), y up).  The clip hull's floors of a
    staircase come out in pieces: de_inferno_go's slope over a staircase with a slit of 5 units all across it,
    de_cbble's treads ending a few cm short of the next step's ramp - nothing to stand on there, so the player
    stopped, or caught at every step.  Two floors (anything the game stands on) with parallel edges facing each
    other less than ``gap_max`` apart, at heights less than ``rise`` apart, get the strip joining the two edges
    (where they run side by side) - unless something already lies there.  A CS player (81 cm wide) never falls
    through such a slit, so it is never meant.  -> (faces + strips, strips made)."""
    out = list(faces)
    floor_idx = []
    for i, (p, n) in enumerate(faces):
        nn = n / max(np.linalg.norm(n), 1e-12)
        if nn[1] >= GAME_FLOOR_NY and len(p) >= 3:
            floor_idx.append(i)
    if len(floor_idx) < 2:
        return out, 0
    CELL = 100.0
    edges = []                                             # (face, a2, b2, outward unit (xz), A3, B3)
    fgrid: Dict[tuple, list] = {}
    for i in floor_idx:
        p = faces[i][0]
        q = p[:, [0, 2]]
        c = q.mean(0)
        lo, hi = q.min(0), q.max(0)
        for gx in range(int(lo[0] // CELL), int(hi[0] // CELL) + 1):
            for gz in range(int(lo[1] // CELL), int(hi[1] // CELL) + 1):
                fgrid.setdefault((gx, gz), []).append(i)
        for k in range(len(q)):
            a, b = q[k], q[(k + 1) % len(q)]
            e = b - a
            ln = float(np.hypot(e[0], e[1]))
            if ln < 5.0:
                continue
            o = np.array([e[1], -e[0]]) / ln
            if o @ ((a + b) / 2 - c) < 0:
                o = -o
            edges.append((i, a, b, o, p[k], p[(k + 1) % len(p)]))
    egrid: Dict[tuple, list] = {}                          # every cell an edge's box (grown by gap_max) touches:
    cells_of = []                                          # a long edge meets a short one far from its middle
    for j, ed in enumerate(edges):
        lo = np.minimum(ed[1], ed[2]) - gap_max
        hi = np.maximum(ed[1], ed[2]) + gap_max
        cs_ = [(gx, gz) for gx in range(int(lo[0] // CELL), int(hi[0] // CELL) + 1)
               for gz in range(int(lo[1] // CELL), int(hi[1] // CELL) + 1)]
        cells_of.append(cs_)
        for c_ in cs_:
            egrid.setdefault(c_, []).append(j)
    pairs = []
    for j, (i, a, b, o, A3, B3) in enumerate(edges):
        near = set()
        for c_ in cells_of[j]:
            near.update(egrid.get(c_, ()))
        for j2 in sorted(near):
                    if j2 <= j:
                        continue
                    i2, a2, b2, o2 = edges[j2][:4]
                    if i2 == i or o[0] * o2[0] + o[1] * o2[1] > -0.95:      # facing each other (within 18°)
                        continue
                    g1 = (a2[0] - a[0]) * o[0] + (a2[1] - a[1]) * o[1]      # the other edge out in front
                    g2 = (b2[0] - a[0]) * o[0] + (b2[1] - a[1]) * o[1]
                    if not (0.1 < g1 <= gap_max and 0.1 < g2 <= gap_max) or max(g1, g2) <= 0.3:
                        continue
                    pairs.append((min(g1, g2), j, j2))

    def covered(pt) -> bool:
        for i3 in fgrid.get((int(pt[0] // CELL), int(pt[2] // CELL)), ()):
            p3, n3 = faces[i3]
            if _inside_xz(p3, pt[0], pt[2]):
                nn = n3 / max(np.linalg.norm(n3), 1e-12)
                y = p3[0][1] - (nn[0] * (pt[0] - p3[0][0]) + nn[2] * (pt[2] - p3[0][2])) / nn[1]
                if abs(y - pt[1]) <= rise + 10.0:
                    return True
        return False
    made = 0
    strips = []
    for gap, j, j2 in sorted(pairs):                       # the narrowest slit first
        i, a, b, o, A3, B3 = edges[j]
        _i2, a2, b2, _o2, A32, B32 = edges[j2]
        u = (b - a) / np.linalg.norm(b - a)
        s0, s1 = sorted((float((a2 - a) @ u), float((b2 - a) @ u)))
        lo, hi = max(0.0, s0), min(float((b - a) @ u), s1)
        if hi - lo < 5.0:
            continue
        L1 = max(float(np.linalg.norm(B3[[0, 2]] - A3[[0, 2]])), 1e-9)
        p1, p2 = A3 + (B3 - A3) * (lo / L1), A3 + (B3 - A3) * (hi / L1)
        sa, sb = float((A32[[0, 2]] - a) @ u), float((B32[[0, 2]] - a) @ u)
        if abs(sb - sa) < 1e-9:
            continue
        p3 = A32 + (B32 - A32) * ((hi - sa) / (sb - sa))
        p4 = A32 + (B32 - A32) * ((lo - sa) / (sb - sa))
        d1, d2 = p1[1] - p4[1], p2[1] - p3[1]              # edge j above the other one by
        mid = (p1 + p2 + p3 + p4) / 4.0                    # the middle of the slit
        if covered(mid) or any(_inside_xz(q, mid[0], mid[2]) and abs(q[:, 1].mean() - mid[1]) <= rise for q in strips):
            continue                                       # (another floor, or a strip, already lies there)
        if abs(d1) <= rise and abs(d2) <= rise:
            quad = np.array([p1, p2, p3, p4])              # a slit in one floor: the strip across it
        elif d1 * d2 > 0 and max(abs(d1), abs(d2)) <= STEP_MAX:
            # a step with a slit before it (de_cbble's stairs: the tread ends 9 cm short of the step down, whose riser
            # is cut low): a step ramp from the upper edge down onto the lower floor, as step_ramps makes
            if d1 > 0:
                U1, U2, low, dirn = p1, p2, faces[_i2], o
            else:
                U1, U2, low, dirn = p4, p3, faces[i], -o
            lp, ln_ = low
            lnn = ln_ / max(np.linalg.norm(ln_), 1e-12)
            if lnn[1] < 0.9:
                continue                                   # (only onto a level floor)
            drop = max(abs(d1), abs(d2))
            edge_o = float(np.array([U1[0], U1[2]]) @ dirn)
            depth = max(float(q[[0, 2]] @ dirn) for q in lp) - edge_o
            L = min(max(gap, drop * STEP_RUN), depth)
            if L < gap:
                continue
            y_low = float(lp[:, 1].mean())
            F1 = U1 + np.array([dirn[0], 0.0, dirn[1]]) * L
            F2 = U2 + np.array([dirn[0], 0.0, dirn[1]]) * L
            F1[1] = F2[1] = y_low
            quad = np.array([U1, U2, F2, F1])
        else:
            continue                                       # a real step or a wall: not a slit
        nq = np.cross(quad[1] - quad[0], quad[3] - quad[0])
        if np.linalg.norm(nq) < 1e-6:
            continue
        if nq[1] < 0:
            quad = quad[::-1].copy()
            nq = -nq
        nq /= np.linalg.norm(nq)
        if nq[1] < GAME_FLOOR_NY:
            continue
        out.append((quad, nq))
        strips.append(quad)
        made += 1
    return out, made


def fill_floor_gaps(faces: list, cell: float = 3.0, gap_max: float = GAP_MAX) -> Tuple[list, int]:
    """Small holes in the floors of the height map closed (engine (points, normal), cm, y up).  Cutting the clip hull's
    floors at a step's corner can leave a notch a few cm wide with no floor at all; in CS a player there stands on the
    hull of the brush beside it, but the game finds no floor under him and he falls out of the map.  Every gap seen
    from above - no floor, or a floor more than 1 m lower (a hole in an upper floor) - narrower than ``gap_max``
    everywhere (however long) gets a level floor at the lowest floor around it (never above any of them).  A solid's inside is never that
    small (the hull grows every solid by a player's width), nor is a pool.  -> (faces + patches, patches made)."""
    floors, grown = [], []
    for q, n in faces:
        nn = n / max(np.linalg.norm(n), 1e-12)
        if nn[1] >= 0.3 and len(q) >= 3:
            q = _grow_polygon(q, nn, SEAM_GROW)           # seams thinner than a cell: closed by every floor reaching
            floors.append((q, nn))                        # a hair under its neighbours
        grown.append((q, n))
    faces = grown
    if not floors:
        return faces, 0
    allp = np.concatenate([q for q, _n in floors])
    x0, z0 = allp[:, 0].min() - 2 * cell, allp[:, 2].min() - 2 * cell
    nx = int(np.ceil((allp[:, 0].max() + 2 * cell - x0) / cell))
    nz = int(np.ceil((allp[:, 2].max() + 2 * cell - z0) / cell))
    if nx * nz > 40_000_000:
        return faces, 0
    top = np.full((nx, nz), -np.inf, np.float32)
    for q, nn in floors:
        i0 = max(int(np.floor((q[:, 0].min() - x0) / cell)), 0)
        i1 = min(int(np.ceil((q[:, 0].max() - x0) / cell)) + 1, nx)
        j0 = max(int(np.floor((q[:, 2].min() - z0) / cell)), 0)
        j1 = min(int(np.ceil((q[:, 2].max() - z0) / cell)) + 1, nz)
        if i1 <= i0 or j1 <= j0:
            continue
        X, Z = np.meshgrid(x0 + (np.arange(i0, i1) + 0.5) * cell, z0 + (np.arange(j0, j1) + 0.5) * cell, indexing="ij")
        inside = np.ones(X.shape, bool)
        k = len(q)
        area = sum(q[i, 0] * q[(i + 1) % k, 2] - q[(i + 1) % k, 0] * q[i, 2] for i in range(k))
        sgn = 1.0 if area >= 0 else -1.0
        for i in range(k):                                # convex polygon: inside every edge (a hair outside too)
            a, b = q[i], q[(i + 1) % k]
            ex, ez = b[0] - a[0], b[2] - a[2]
            ln = np.hypot(ex, ez)
            if ln < 1e-9:
                continue
            inside &= sgn * (ex * (Z - a[2]) - ez * (X - a[0])) / ln >= -0.5
        if not inside.any():
            continue
        y = q[0, 1] - (nn[0] * (X - q[0, 0]) + nn[2] * (Z - q[0, 2])) / nn[1]
        sub = top[i0:i1, j0:j1]
        np.maximum(sub, np.where(inside, y, -np.inf).astype(np.float32), out=sub)
    from . import ndi
    has = np.isfinite(top)
    lim = int(np.ceil(gap_max / cell))
    out, made = list(faces), 0
    up = np.array([0.0, 1.0, 0.0])
    # a gap is narrow everywhere (no point of it farther than gap_max / 2 from a floor), however long it is
    half = gap_max / 2.0 / cell
    # 1) no floor at all: closed pieces of the "no floor" area
    lab, _n = ndi.label(~has)
    border = set(np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]])).tolist())
    holes = [(k, sl, lab) for k, sl in enumerate(ndi.find_objects(lab, _n), 1) if sl is not None and k not in border]
    # 2) a floor far below every floor around it (a hole in an upper floor over a lower one)
    tv = np.where(has, top, -1e9).astype(np.float32)
    closed = ndi.grey_closing(tv, lim + 1 if lim % 2 == 0 else lim + 2)
    low = has & (closed > tv + 100.0)
    del tv, closed
    lab2, _n2 = ndi.label(low)
    holes += [(k, sl, lab2) for k, sl in enumerate(ndi.find_objects(lab2, _n2), 1) if sl is not None]
    for k, sl, L in holes:
        a0, a1 = max(sl[0].start - 4, 0), min(sl[0].stop + 4, nx)
        b0, b1 = max(sl[1].start - 4, 0), min(sl[1].stop + 4, nz)
        m = L[a0:a1, b0:b1] == k
        if not ndi.narrow(m, half + 0.5):
            continue                                      # wide: a real opening (a pool, a pit, outside the map)
        T = top[a0:a1, b0:b1]
        ring = ndi.binary_dilation(m) & ~m
        rv = T[ring]
        rv = rv[np.isfinite(rv)]
        if not len(rv):
            continue
        if L is lab2 and rv.min() < T[m].max() + 100.0:   # only when the floor around is higher all round
            continue
        cover = ndi.binary_dilation(m, True, 2)                                   # overlap onto the floors around
        ringv = np.where(ring & np.isfinite(T), T, np.inf)
        for i in range(cover.shape[0]):                   # one strip per run of cells of a row
            j = 0
            row = cover[i]
            while j < len(row):
                if not row[j]:
                    j += 1
                    continue
                j2 = j
                while j2 + 1 < len(row) and row[j2 + 1]:
                    j2 += 1
                near = ringv[max(i - 3, 0):i + 4, max(j - 3, 0):j2 + 4]
                y = float(near.min()) if np.isfinite(near.min()) else float(rv.min())
                xa, xb = x0 + (a0 + i) * cell, x0 + (a0 + i + 1) * cell
                za, zb = z0 + (b0 + j) * cell, z0 + (b0 + j2 + 1) * cell
                out.append((np.array([[xa, y, za], [xa, y, zb], [xb, y, zb], [xb, y, za]], np.float64), up.copy()))
                j = j2 + 1
        made += 1
    return out, made


def _clip_u(p: np.ndarray, u: np.ndarray, lo: float, hi: float):
    """The part of the convex polygon ``p`` with lo <= p.u <= hi."""
    q = p
    for sgn, lim in ((1.0, hi), (-1.0, -lo)):
        d = sgn * (q @ u) - lim
        out = []
        for i in range(len(q)):
            a, b = q[i], q[(i + 1) % len(q)]
            da, db = d[i], d[(i + 1) % len(q)]
            if da <= 1e-9:
                out.append(a)
            if (da < -1e-9 < db) or (db < -1e-9 < da):
                out.append(a + (b - a) * (da / (da - db)))
        if len(out) < 3:
            return None
        q = np.array(out)
    return q


def _clip(pts: np.ndarray, uv: np.ndarray, axis: int, value: float, keep_below: bool):
    """Sutherland-Hodgman: the part of the convex polygon on one side of the plane coordinate[axis] = value."""
    out_p, out_u = [], []
    n = len(pts)
    inside = (pts[:, axis] <= value) if keep_below else (pts[:, axis] >= value)
    for i in range(n):
        j = (i + 1) % n
        if inside[i]:
            out_p.append(pts[i]); out_u.append(uv[i])
        if inside[i] != inside[j]:
            t = (value - pts[i, axis]) / (pts[j, axis] - pts[i, axis])
            out_p.append(pts[i] + t * (pts[j] - pts[i])); out_u.append(uv[i] + t * (uv[j] - uv[i]))
    return np.array(out_p).reshape(-1, 3), np.array(out_u).reshape(-1, 2)


def _overlaps_xy(pts, a, b) -> bool:
    lo, hi = pts.min(0), pts.max(0)
    return lo[0] < b[0] - 1.0 and hi[0] > a[0] + 1.0 and lo[1] < b[1] - 1.0 and hi[1] > a[1] + 1.0


def _cut_rect(f: BspFace, a, b) -> list:
    """The pieces of the (convex) face outside the rectangle a..b in plan (CS x, y): a hole cut in a floor."""
    out = []
    p, u = f.points, np.asarray(f.uv, np.float64)
    for axis, value, below in ((0, a[0], True), (0, b[0], False), (1, a[1], True), (1, b[1], False)):
        q, qu = _clip(p, u, axis, value, below)
        if len(q) >= 3:
            out.append(BspFace(q, f.normal, f.texture, qu, f.model))
        p, u = _clip(p, u, axis, value, not below)
        if len(p) < 3:
            break
    return out


PROP_MAX = 6000.0                                          # CS units: a prop bigger than this is a sky dome
PROP_BODY = 64.0                                           # CS units: the part of a prop a player bumps into


def drawn_props(props) -> list:
    """The props worth drawing: not the sky domes / cloud layers (bigger than PROP_MAX)."""
    out = []
    for pr in props or ():
        P = np.concatenate([q for _t, q, _uv in pr.tris])
        if np.max(P.max(0) - P.min(0)) <= PROP_MAX:
            out.append(pr)
    return out


def prop_texture_key(pr, k: int) -> str:
    """The name a texture of a studio model goes by in ``texmap``: mdl:<model file>:<texture>."""
    import os as _os
    return f"mdl:{_os.path.splitext(_os.path.basename(pr.file))[0].lower()}:{pr.model.textures[k].name.lower()}"


def prop_box(pr, look, pl):
    """A collision box (engine) round the lower part of a studio model standing on the ground (a car, a van, a pot, a
    bench), or None: hanging ones (awnings), see-through ones (palm leaves, ferns, branches - textures with holes),
    flat ones and big scenery are walked through / never reached, as in CS."""
    from .meshbox import oriented_box
    from .mdl import STUDIO_NF_MASKED, STUDIO_NF_ADDITIVE
    P = np.concatenate([q for _t, q, _uv in pr.tris])
    lo, hi = P.min(0), P.max(0)
    if np.max(hi[:2] - lo[:2]) > 600.0:
        return None
    seen = [pr.model.textures[k].flags & (STUDIO_NF_MASKED | STUDIO_NF_ADDITIVE | 0x01) for k, _q, _uv in pr.tris]
    if np.mean([bool(s) for s in seen]) > 0.5:
        return None
    if look is not None:
        c = np.array([(lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, lo[2] - 6.0])
        if look(c) != CONTENTS_SOLID:                         # nothing under it: hanging, or over a hole
            return None
    low = P[P[:, 2] <= lo[2] + PROP_BODY]
    if len(low) < 4:
        return None
    size = low.max(0) - low.min(0)
    if size[2] < 12.0 or min(size[0], size[1]) < 12.0:
        return None
    return oriented_box(pl.point(low), 0.0)


def uncovered_faces(faces, tris: np.ndarray, cell: float = 40.0, tol: float = 1.5, hits: Optional[dict] = None) -> List[int]:
    """Indices of ``faces`` ((points, normal, ...) engine) no part of which is drawn by any of ``tris`` ((n, 3, 3)
    engine triangles): their middle and a point near each corner are on no triangle of the same plane.  A face drawn
    only in part (cut by the user, or split differently) counts as drawn - adding it would flicker over that part.
    ``hits``: filled with {face index: a triangle index drawing it} for the others."""
    tris = np.asarray(tris, np.float64).reshape(-1, 3, 3)
    if not len(tris):
        return list(range(len(faces)))
    N = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    ln = np.linalg.norm(N, axis=1)
    ok = ln > 1e-6
    tris, N = tris[ok], N[ok] / ln[ok, None]
    lo = np.floor((tris.min(1) - tol) / cell).astype(np.int64)
    hi = np.floor((tris.max(1) + tol) / cell).astype(np.int64)
    grid: Dict[tuple, list] = {}
    for k in range(len(tris)):
        for x in range(lo[k, 0], hi[k, 0] + 1):
            for y in range(lo[k, 1], hi[k, 1] + 1):
                for z in range(lo[k, 2], hi[k, 2] + 1):
                    grid.setdefault((x, y, z), []).append(k)

    def on_one(p, n) -> int:
        ks = grid.get(tuple(np.floor(p / cell).astype(np.int64)))
        if not ks:
            return -1
        ks = np.asarray(ks)
        a = tris[ks, 0]
        keep = (np.abs(N[ks] @ n) > 0.98) & (np.abs(np.einsum("ij,ij->i", p - a, N[ks])) < tol)
        if not keep.any():
            return -1
        ks, a = ks[keep], a[keep]
        v0, v1, v2 = tris[ks, 2] - a, tris[ks, 1] - a, p - a
        d00, d01, d11 = (v0 * v0).sum(1), (v0 * v1).sum(1), (v1 * v1).sum(1)
        d20, d21 = (v2 * v0).sum(1), (v2 * v1).sum(1)
        den = d00 * d11 - d01 * d01
        good = np.abs(den) > 1e-9
        den = np.where(good, den, 1.0)
        u = (d11 * d20 - d01 * d21) / den
        v = (d00 * d21 - d01 * d20) / den
        inside = good & (u >= -0.01) & (v >= -0.01) & (u + v <= 1.01)
        return int(ks[np.argmax(inside)]) if inside.any() else -1

    out = []
    for i, f in enumerate(faces):
        P = np.asarray(f[0], np.float64)
        n = np.asarray(f[1], np.float64)
        n = n / max(np.linalg.norm(n), 1e-12)
        c = P.mean(0)
        k = next((k for k in (on_one(q, n) for q in [c] + [c + (v - c) * 0.8 for v in P]) if k >= 0), -1)
        if k < 0:
            out.append(i)
        elif hits is not None:
            hits[i] = int(np.nonzero(ok)[0][k])
    return out


def _cover_test(tris: np.ndarray, cell: float = 40.0, tol: float = 1.5):
    """A test "is the point p (engine) on one of the triangles ``tris`` lying in its plane (normal n)?"."""
    tris = np.asarray(tris, np.float64).reshape(-1, 3, 3)
    N = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    ln = np.linalg.norm(N, axis=1)
    ok = ln > 1e-6
    tris, N = tris[ok], N[ok] / ln[ok, None]
    lo = np.floor((tris.min(1) - tol) / cell).astype(np.int64)
    hi = np.floor((tris.max(1) + tol) / cell).astype(np.int64)
    grid: Dict[tuple, list] = {}
    for k in range(len(tris)):
        for x in range(lo[k, 0], hi[k, 0] + 1):
            for y in range(lo[k, 1], hi[k, 1] + 1):
                for z in range(lo[k, 2], hi[k, 2] + 1):
                    grid.setdefault((x, y, z), []).append(k)

    def on(p, n) -> bool:
        ks = grid.get(tuple(np.floor(p / cell).astype(np.int64)))
        if not ks:
            return False
        ks = np.asarray(ks)
        a = tris[ks, 0]
        keep = (np.abs(N[ks] @ n) > 0.98) & (np.abs(np.einsum("ij,ij->i", p - a, N[ks])) < tol)
        if not keep.any():
            return False
        ks, a = ks[keep], a[keep]
        v0, v1, v2 = tris[ks, 2] - a, tris[ks, 1] - a, p - a
        d00, d01, d11 = (v0 * v0).sum(1), (v0 * v1).sum(1), (v1 * v1).sum(1)
        d20, d21 = (v2 * v0).sum(1), (v2 * v1).sum(1)
        den = d00 * d11 - d01 * d01
        good = np.abs(den) > 1e-9
        den = np.where(good, den, 1.0)
        u = (d11 * d20 - d01 * d21) / den
        v = (d00 * d21 - d01 * d20) / den
        return bool((good & (u >= -0.01) & (v >= -0.01) & (u + v <= 1.01)).any())
    return on


def uncovered_parts(faces, tris: np.ndarray, which=None, cell: float = 5.0) -> list:
    """The parts of faces ((points, normal, uv) engine) drawn by the triangles ``tris`` only in part (an older import
    left a piece out: de_dust2_cs2's crate behind the pallet showed the sky through it): [(face index, points, uv)] -
    rectangles of ``cell`` cm on the face (cut by its edges) where it is not drawn, a little over the drawn part rather
    than a slit.  ``which``: the faces to look at (default all)."""
    on = _cover_test(tris)
    out = []
    for i in (range(len(faces)) if which is None else which):
        P = np.asarray(faces[i][0], np.float64)
        n = np.asarray(faces[i][1], np.float64)
        n = n / max(np.linalg.norm(n), 1e-12)
        UV = np.asarray(faces[i][2], np.float64)
        if len(P) < 3:
            continue
        c = P.mean(0)
        probe = [c] + [c + (q - c) * s for q in P for s in (0.5, 0.9)]
        got = [on(q, n) for q in probe]
        if all(got) or not any(got):
            continue
        u = P[1] - P[0]
        u /= max(np.linalg.norm(u), 1e-12)
        v = np.cross(n, u)
        S, T = (P - P[0]) @ u, (P - P[0]) @ v
        s0, s1, t0, t1 = S.min(), S.max(), T.min(), T.max()
        ns, nt = int(np.ceil((s1 - s0) / cell)), int(np.ceil((t1 - t0) / cell))
        if ns * nt > 40000:
            continue
        miss = np.zeros((ns, nt), bool)
        from .bspgrille import _inside, _clip
        for a in range(ns):
            for b in range(nt):
                sa, sb = s0 + a * cell, s0 + (a + 1) * cell
                ta, tb = t0 + b * cell, t0 + (b + 1) * cell
                pts = [((sa + sb) / 2, (ta + tb) / 2)] + [(x, y) for x in (sa + 0.1, sb - 0.1) for y in (ta + 0.1, tb - 0.1)]
                ins = [bool(_inside(S, T, np.array([x]), np.array([y]))[0]) for x, y in pts]
                if not any(ins):
                    continue
                miss[a, b] = any(not on(P[0] + u * x + v * y, n) for (x, y), k in zip(pts, ins) if k)
        if not miss.any():
            continue
        A = np.c_[S, T, np.ones(len(S))]                      # uv as an affine function of the face's plane
        M, *_ = np.linalg.lstsq(A, UV, rcond=None)
        poly2 = np.stack([S, T], 1)
        runs_open = {}
        rects = []
        for b in range(nt):
            col = miss[:, b]
            runs = []
            a = 0
            while a < ns:
                if col[a]:
                    k = a
                    while k + 1 < ns and col[k + 1]:
                        k += 1
                    runs.append((a, k + 1))
                    a = k + 1
                else:
                    a += 1
            nxt = {}
            for r in runs:
                nxt[r] = (runs_open.pop(r)[0], b + 1) if r in runs_open else (b, b + 1)
            rects += [(r[0], r[1], x, y) for r, (x, y) in runs_open.items()]
            runs_open = nxt
        rects += [(r[0], r[1], x, y) for r, (x, y) in runs_open.items()]
        for a0, a1, b0, b1 in rects:
            g = poly2
            for nn, dd in (((1.0, 0.0), s0 + a1 * cell), ((-1.0, 0.0), -(s0 + a0 * cell)),
                           ((0.0, 1.0), t0 + b1 * cell), ((0.0, -1.0), -(t0 + b0 * cell))):
                g = _clip(g, np.array(nn), dd)
                if g is None:
                    break
            if g is None:
                continue
            Q = P[0] + np.outer(g[:, 0], u) + np.outer(g[:, 1], v)
            if float(np.cross(Q[1] - Q[0], Q[2] - Q[0]) @ np.cross(P[1] - P[0], P[2] - P[0])) < 0:
                Q, g = Q[::-1].copy(), g[::-1].copy()
            out.append((i, Q, np.c_[g, np.ones(len(g))] @ M))
    return out


def convert(bsp: BspMap, pl: Plan, texmap: Optional[Dict[str, str]] = None, repeat: Optional[Dict[str, float]] = None,
            exists: Callable[[str], bool] = lambda n: True, collision: bool = True, thick: float = 20.0,
            spawn_above: float = 20.0, per_team: Optional[int] = None, water: str = "floor",
            hull: bool = True, props=None, lift: bool = True, thin: bool = True, grilles: bool = True,
            sides: Optional[bool] = None) -> Converted:
    """Everything the map needs, in engine coordinates.  ``texmap`` CS texture -> Torrente texture (guessed when missing);
    ``repeat`` CS texture -> how many times the Torrente texture repeats where the CS one repeated once.
    ``water``: 'floor' - the water is drawn and its top can be walked on; 'hole' - every pool is a hole: no water, no
    bottom, its walls are seen but not solid, whoever goes in falls out of the map.
    ``hull``: the floors and walls of the height map come from the map's player clip hull (what CS itself collides with,
    invisible CLIP brushes included: stairs as ramps, walls you cannot climb) instead of from the drawn faces.
    ``props``: the map's studio models (mdl.Prop), drawn with the textures ``texmap`` gives for prop_texture_key(...);
    the solid ones standing on the ground get a box round their lower part (see prop_box)."""
    texmap = dict(texmap or {})
    repeat = dict(repeat or {})
    out = Converted()
    solid_faces = getattr(bsp, "solid_faces", None) if collision else None    # a Hammer map: its brushes' outside
    use_hull = bool(hull and collision and getattr(bsp, "raw", b"")) and not solid_faces
    hull_no = 1
    if use_hull:
        try:
            from . import bsphull
            _h = bsphull.Hull(bsp.raw)
            use_hull = len(_h.clip) > 0 and _h.models[0]["head"][1] >= 0
            hull_no = COLLISION_HULL if _h.models[0]["head"][COLLISION_HULL] >= 0 else 1
        except Exception:
            use_hull = False
    models: Dict[int, list] = {}
    ents = model_entities(bsp)
    pools = []                                                # CS (lo, hi) of every water volume
    for m, e in ents.items():
        if e.get("classname", "").lower() in WATER_CLASSES and m < len(bsp.models):
            pools.append(bsp.models[m])

    def in_pool(pts) -> bool:
        lo, hi = pts.min(0), pts.max(0)
        return any(np.all(lo[:2] >= a[:2] - 2.0) and np.all(hi[:2] <= b[:2] + 2.0) and hi[2] <= b[2] + 1.0
                   for a, b in pools)
    faces_in = []
    exact = use_hull or bool(solid_faces)                      # collision from the map's own solid, not from what is drawn
    for f in drawn_faces(bsp):
        if water == "hole" and pools and not f.model and abs(f.normal[2]) > 0.7 and not exact:
            pieces = [f]
            for a, b in pools:                                # floors under a pool get the pool's rectangle cut out
                nxt = []
                for g in pieces:
                    if g.points[:, 2].max() <= b[2] + 1.0 and _overlaps_xy(g.points, a, b):
                        nxt += _cut_rect(g, a, b)
                    else:
                        nxt.append(g)
                pieces = nxt
            faces_in += pieces
        else:
            faces_in.append(f)
    panels = open_panels(bsp)
    out.open_panels = len(panels)
    from .bspfix import overlay_shifts
    lift = {id(bsp.faces[i]): d for i, d in overlay_shifts(bsp).items()} if lift else {}   # decals off their walls
    out.overlays = len(lift)
    from .bspfix import thin_backs
    from .bspfix import decal_sides
    sides = bool(lift) if sides is None else sides            # (the same faces left out with or without the lift)
    from .bspfix import buried_faces
    thin = {id(bsp.faces[i]) for i in thin_backs(bsp) + (decal_sides(bsp) if sides else []) + buried_faces(bsp)} \
        if thin else set()
    #   (one face of each thin slab drawn; the edges of a decal moved off its wall left out; faces pressed on others)
    out.thin = len(thin)
    for f in faces_in:
        src_f = f
        e = ents.get(f.model) if f.model else None
        if _hidden(e) or f.model in panels:                   # doors (open), triggers, buy zones, breakable panels
            continue
        if invisible_entity(e):                               # never drawn in CS (its walls still block, below)
            out.invisible += 1
            if e.get("classname", "").lower() not in NONSOLID_CLASSES:
                models.setdefault(f.model, []).append((pl.point(f.points), pl.direction(f.normal)))
            continue
        hole_wall = False
        if water == "hole" and pools:
            if e and e.get("classname", "").lower() in WATER_CLASSES:
                if f.normal[2] < 0.7 or not exists(WATER_TEXTURE):
                    continue                                  # only its surface is drawn: the sea, not solid
                p = pl.point(f.points)
                n = pl.direction(f.normal)
                uv = f.points[:, :2] / (80.0 / pl.scale)      # a wave pattern every 80 cm
                out.meshes.setdefault(WATER_TEXTURE, []).append((p, n / max(np.linalg.norm(n), 1e-12), uv))
                out.textures[f.texture] = WATER_TEXTURE
                continue
            if not f.model and in_pool(f.points):
                if abs(f.normal[2]) > 0.7 and not exact:
                    continue                                  # no bottom (nor anything flat under it): out of the map
                hole_wall = True                              # the pool's walls and bottom: seen, not solid
        cls = e.get("classname", "").lower() if e else ""
        if cls in WATER_CLASSES and f.model < len(bsp.models) and \
                not _water_face_seen(f, bsp.models[f.model], _water_look(bsp, f.model)):
            continue                                          # its bottom, the underside of its top, inner sides
        if not f.model and str(f.texture).startswith("!") and float(f.normal[2]) <= 0.7:
            continue                                          # water in the world: only its surface
        if e and "origin" in e and f.model:                   # a turning brush is built round its own origin
            try:
                f = BspFace(f.points + np.array([float(v) for v in e["origin"].split()]), f.normal, f.texture, f.uv, f.model)
            except ValueError:
                pass
        tex = texmap.get(f.texture) or guess_texture(f.texture, exists)
        if not tex.lower().endswith(".tex"):
            tex += ".tex"
        out.textures[f.texture] = tex
        if id(f) in lift or id(src_f) in lift:
            nn = np.asarray(f.normal, np.float64)
            f = BspFace(f.points + nn / max(np.linalg.norm(nn), 1e-12) * lift.get(id(src_f), lift.get(id(f), 0.0)),
                        f.normal, f.texture, f.uv, f.model)
        p = pl.point(f.points)
        n = pl.direction(f.normal)
        n /= max(np.linalg.norm(n), 1e-12)
        uv = np.asarray(f.uv, np.float64) * float(repeat.get(f.texture, 1.0))
        if id(src_f) not in thin:
            out.meshes.setdefault(tex, []).append((p, n, uv))
        if cls in NONSOLID_CLASSES or hole_wall:
            continue
        if cls in WATER_CLASSES:                              # only its surface: a floor to stand on, no box
            if collision and n[1] > 0.7:
                out.hm_faces.append((p, n))
            continue
        models.setdefault(f.model, []).append((p, n))
        if collision and n[1] > -0.7 and not use_hull and not solid_faces:
            out.hm_faces.append((p, n))
    if collision:
        for m, faces in models.items():
            if exact:                                         # boxes come from the real walls (below), the world's and
                continue                                      # the brush entities' (one box round a whole entity - the
                                                              # crates of a bomb site in one func_breakable - is a wall)
            if m == 0:                                        # the world: one box behind every face
                for p, n in faces:
                    area = 0.5 * np.linalg.norm(sum(np.cross(p[k] - p[0], p[k + 1] - p[0]) for k in range(1, len(p) - 1)))
                    if area < 25.0:
                        continue
                    # boxes only turn about the vertical: around a slope (a ramp, a rocky wall) a box would stand up
                    # as an invisible wall over it.  Slopes are solid through the height map's faces only.
                    if abs(n[1]) > 0.995 or abs(n[1]) < 0.17:
                        out.boxes.append(_face_box(p, n, thick))
            else:                                             # a brush entity (crates): one box around it
                from .meshbox import oriented_box
                out.boxes.append(oriented_box(np.concatenate([p for p, _n in faces]), 2.0))
    if use_hull or solid_faces:                              # the floors / walls the player meets in CS
        from . import bsphull
        coll = []                                            # (engine points, normal, model, a bar of a grille)
        grid = None
        if grilles and not solid_faces:                       # bars / railings: bullets fly through their gaps
            try:
                from .bspgrille import Grilles
                from .bspgrille import bsp_sheets
                grid = Grilles(bsp.raw, hull_no, bsp_sheets(bsp))
            except Exception:
                grid = None
        solid_models = [0] + [m for m, e in ents.items() if not _hidden(e) and m not in panels and
                              e.get("classname", "").lower() not in NONSOLID_CLASSES + WATER_CLASSES]
        for m in solid_models:
            e = ents.get(m) if m else None
            off = np.zeros(3)
            if e and "origin" in e:
                try:
                    off = np.array([float(v) for v in e["origin"].split()])
                except ValueError:
                    pass
            if solid_faces:
                surf, off = solid_faces.get(m, []), np.zeros(3)  # already where they stand
            else:
                try:
                    surf = bsphull.walls(bsp.raw, m, hull_no, HULL_HALF[hull_no])
                except Exception:
                    surf = []
            for q0, nn in surf:
                if nn[2] < -0.7:                              # ceilings: nobody stands under them
                    continue
                parts = None
                if grid is not None and abs(nn[2]) < 0.7:
                    try:
                        parts = grid.open(m, q0, nn, HULL_HALF[hull_no])
                    except Exception:
                        parts = None
                if parts is None:
                    parts = [(q0, False)]
                else:
                    out.grilles += 1
                for q, bar in parts:
                    q = q + off
                    pieces = [q]
                    if water == "hole" and pools:
                        if in_pool(q):
                            continue                              # in a pool-hole nothing holds a player
                        if abs(nn[2]) > 0.7:
                            for a, b in pools:
                                nxt = []
                                for g in pieces:
                                    if g[:, 2].max() <= b[2] + 1.0 and _overlaps_xy(g, a, b):
                                        nxt += [h.points for h in _cut_rect(BspFace(g, nn, "", np.zeros((len(g), 2)), 0), a, b)]
                                    else:
                                        nxt.append(g)
                                pieces = nxt
                    for g in pieces:
                        coll.append((pl.point(g), pl.direction(nn), m, bar))
    if use_hull or solid_faces:
        coll0 = coll
        coll, out.pierced = trim_pierced_walls(coll)
        coll, out.lintels = drop_hanging_walls(coll)
        kept = {id(f) for f in coll}
        was = {id(f) for f in coll0}
        for f in coll0:                                   # the boxes of the walls cut / dropped, before and after:
            if id(f) not in kept:                         # a map made before fixes its boxes with them
                out.stale_boxes += _coll_boxes(f, thick)
        for f in coll:
            if id(f) not in was:
                out.fresh_boxes += _coll_boxes(f, thick)
        faces, made = step_ramps([(q, n) for q, n, _m, _b in coll])
        faces, out.slits = bridge_plane_gaps(faces)
        faces, out.floor_gaps = fill_floor_gaps(faces)
        faces, out.lips = lip_ramps(faces)
        bottoms: Dict[int, float] = {}                    # the solid brush entities: their tops over the map's floor
        for q, n, m, _b in coll:                          # (down to the bottom of the entity: its box in the .bsp)
            if m and m not in bottoms:
                lo3, hi3 = (np.asarray(v, np.float64) for v in bsp.models[m][:2])
                try:
                    o3 = np.array([float(v) for v in (ents.get(m) or {}).get("origin", "0 0 0").split()])
                    lo3, hi3 = lo3 + o3, hi3 + o3
                except ValueError:
                    pass
                cs = np.array([[x, y, lo3[2]] for x in (lo3[0], hi3[0]) for y in (lo3[1], hi3[1])])
                bottoms[m] = float(pl.point(cs)[:, 1].min())
        tops = [(q, n, bottoms[m]) for q, n, m, bar in coll
                if m and not bar and n[1] / max(np.linalg.norm(n), 1e-12) >= GAME_FLOOR_NY]
        faces, out.buried = drop_buried_floors(faces, solids=tops)
        out.hm_faces += faces
        out.step_ramps = made
        for q, n, m, bar in coll:                             # boxes behind the world's walls higher than a step
            ny = n[1] / max(np.linalg.norm(n), 1e-12)        # (a bar of a grille, however low: it is up in the air)
            if abs(ny) < 0.17:
                out.boxes += _wall_boxes(q, n, min(thick, 15.0), 0.0 if bar else STEP_MAX)
            elif m == 0 and GAME_FLOOR_NY <= ny < STEEP_NY:   # a rock face: a wall in CS, a floor for the game
                b = _slope_box(q, n)
                if b is not None:
                    out.boxes.append(b)
                    out.slope_boxes += 1
    if props:
        look = _front_contents(bsp.raw) if getattr(bsp, "raw", b"") else None
        for pr in drawn_props(props):                       # (no sky domes, clouds: the game has its own sky)
            seen_tw = set()
            for k, q, uv in pr.tris:
                key = prop_texture_key(pr, k)
                tex = texmap.get(key)
                if not tex:
                    continue
                nn = -np.cross(q[1] - q[0], q[2] - q[0])          # a studio model's triangles turn clockwise
                if np.linalg.norm(nn) < 1e-9:
                    continue
                tw = (tex,) + tuple(sorted(tuple(np.round(np.asarray(c, np.float64) * 100).astype(np.int64)) for c in q))
                if tw in seen_tw:                                 # two-sided leaves / cards: one is drawn from both
                    out.twins += 1                                # sides already (bspfix.twin_triangles)
                    continue
                seen_tw.add(tw)
                n = pl.direction(nn / np.linalg.norm(nn))
                out.meshes.setdefault(tex, []).append((pl.point(q), n / max(np.linalg.norm(n), 1e-12), uv))
                out.textures[key] = tex
            out.props += 1
            if collision:
                b = prop_box(pr, look, pl)
                if b is not None:
                    out.boxes.append(b)
                    out.prop_boxes += 1
    if water == "hole" and pools and collision:              # far under every pool a floor nobody survives landing
        for a, b in pools:                                    # on: the game only lets a player fall onto a floor
            y = b[2] - KILL_DROP / pl.scale
            q = pl.point(np.array([[a[0], a[1], y], [b[0], a[1], y], [b[0], b[1], y], [a[0], b[1], y]]))
            out.hm_faces.append((q, pl.direction(np.array([0.0, 0.0, 1.0]))))
    middle = None
    if bsp.faces:
        lo, hi = footprint(bsp, pl)
        middle = (lo + hi) / 2
    starts = {0: [], 1: []}
    for e in bsp.entities:
        cls = e.get("classname", "")
        team = 0 if cls == "info_player_start" else 1 if cls == "info_player_deathmatch" else None
        if team is None or "origin" not in e:
            continue
        try:
            o = [float(v) for v in e["origin"].split()]
            if "angle" in e:
                ang = float(e["angle"])
            elif "angles" in e:
                ang = float(e["angles"].split()[1])
            else:
                ang = None
        except (ValueError, IndexError):
            continue
        pos = pl.point(o) + np.array([0.0, spawn_above, 0.0])
        if ang is not None:
            a = pl.angle(ang)
        elif middle is not None:                             # no direction in the map: look at the middle of the map
            a = math.atan2(middle[0] - pos[0], middle[2] - pos[2]) % (2 * math.pi)
        else:
            a = 0.0
        starts[team].append((tuple(float(v) for v in pos), a, team))
    for team, lst in starts.items():
        if per_team and 0 < len(lst) < per_team:              # too few in the map: more beside the team's own
            cls = "info_player_start" if team == 0 else "info_player_deathmatch"
            have = [e for e in bsp.entities if e.get("classname") == cls and "origin" in e]
            try:
                more = more_starts(bsp, [[float(v) for v in e["origin"].split()] for e in have], per_team)
            except Exception:                                 # (no player hull in the file: as many as it has)
                more = []
            for k, o in enumerate(more):
                ang = lst[k % len(lst)][1]
                lst.append((tuple(float(v) for v in pl.point(o) + np.array([0.0, spawn_above, 0.0])), ang, team))
        if per_team and len(lst) > per_team:                 # keep the ones nearest the middle of that team's group
            c = np.mean([p for p, _a, _t in lst], 0)
            lst = sorted(lst, key=lambda s: float(np.sum((np.asarray(s[0]) - c) ** 2)))[:per_team]
        out.spawns += lst
    for e in bsp.entities:                                   # bomb sites (func_bomb_target, info_bomb_target)
        cls = e.get("classname", "")
        if cls not in ("func_bomb_target", "info_bomb_target"):
            continue
        if cls == "func_bomb_target":
            mm = bsp.entity_model(e)
            if mm is None:
                continue
            q = pl.point(np.array([[x, y, z] for x in (mm[0][0], mm[1][0]) for y in (mm[0][1], mm[1][1])
                                   for z in (mm[0][2], mm[1][2])]))
            lo2, hi2 = q.min(0), q.max(0)
        else:
            try:
                c = pl.point([float(v) for v in e["origin"].split()])
            except (KeyError, ValueError):
                continue
            lo2, hi2 = c - [150.0, 0.0, 150.0], c + [150.0, 200.0, 150.0]
        name = e.get("target") or e.get("targetname") or f"site_{len(out.targets) + 1}"
        out.targets.append({"name": name, "lo": lo2, "hi": hi2,
                            "floor": np.array([(lo2[0] + hi2[0]) / 2, lo2[1], (lo2[2] + hi2[2]) / 2])})
    # A before B: by the name the map gives them (tgt_a, tgt_b ...), else as they come
    out.targets.sort(key=lambda t: (0 if t["name"].lower().rstrip().endswith("a") else
                                    1 if t["name"].lower().rstrip().endswith("b") else 2))
    return out
