"""Flag pedestals ("bases") like the ones of mp_b_anderguater: copied from that map (mesh + its floor collision) and put
under the flags of another map.  The pedestal of the red flag goes under red flags and the yellow one under yellow flags."""
from __future__ import annotations

import copy
from typing import Dict, Optional, Tuple

import numpy as np

from . import crop, hmcopy
from .opt import transform_mesh, translate_mesh

SOURCE_SCENE = "mp_b_anderguater.scn"
PEDESTAL_TEXTURE = "bandera y pedestal.tex"


def team_of(rec) -> str:
    n = str(rec.object_name).lower()
    return "rojo" if ("roj" in n or "red" in n) else "amarillo"


def flag_pos(rec) -> np.ndarray:
    return np.asarray(rec.parsed.transform, np.float64)[3, :3].copy()


def _point_in_poly(x, z, pts) -> bool:
    inside = False
    n = len(pts)
    for i in range(n):
        x1, z1 = pts[i][0], pts[i][2]
        x2, z2 = pts[(i + 1) % n][0], pts[(i + 1) % n][2]
        if (z1 > z) != (z2 > z):
            xi = x1 + (z - z1) * (x2 - x1) / (z2 - z1)
            if x < xi:
                inside = not inside
    return inside


def ground_y(hm, x: float, z: float, below: float) -> Optional[float]:
    """Highest walkable floor of the height map under (x, z) that is not higher than ``below``."""
    best = None
    for f in hmcopy.unique_faces(hm):
        nx, ny, nz = f.normal
        if ny < 0.5:
            continue
        x0, z0, x1, z1 = hmcopy.face_bounds(f)
        if not (x0 <= x <= x1 and z0 <= z <= z1):
            continue
        if not any(_point_in_poly(x, z, c) for c in f.contours):
            continue
        y = -(f.distance + nx * x + nz * z) / ny
        if y <= below and (best is None or y > best):
            best = float(y)
    return best


def load_pedestals(fs) -> Dict[str, Tuple[object, list, np.ndarray]]:
    """{team: (mesh, hm faces, flag position)} taken from mp_b_anderguater."""
    from .hm import HeightMap
    from . import legacy
    sc = fs.scene(SOURCE_SCENE)
    opt = fs.map(legacy.resolve_map(sc, lambda n: fs.find(n) is not None))
    hm_p = fs.find(str(sc.heightmap_name).rstrip("\0").replace("\\", "/"))
    hm = HeightMap.load(hm_p) if hm_p else None
    out = {}
    for rec in sc.modules:
        if rec.clean_name.lower() != "mp_flag" or rec.parsed is None:
            continue
        p = flag_pos(rec)
        for me in opt.meshes:
            lo, hi = crop.mesh_bounds(me)
            if lo[0] - 5 <= p[0] <= hi[0] + 5 and lo[2] - 5 <= p[2] <= hi[2] + 5 and (hi - lo)[[0, 2]].max() < 400 and \
                    any(PEDESTAL_TEXTURE in str(t).lower() for m in me.materials for t in m.textures):
                faces = []
                if hm is not None:
                    for f in hmcopy.unique_faces(hm):
                        x0, z0, x1, z1 = hmcopy.face_bounds(f)
                        if x0 >= lo[0] - 3 and x1 <= hi[0] + 3 and z0 >= lo[2] - 3 and z1 <= hi[2] + 3:
                            faces.append(f)
                # the pedestals of mp_b_anderguater lean a little (1-1.5 degrees, on sloped ground): measure the plane of
                # their bottom so the copy can be put level
                v = np.concatenate([sm.vertices["pos"] for sm in me.render_submeshes()]).astype(np.float64)
                bot = v[v[:, 1] < lo[1] + 6.0]
                a, b, c = np.linalg.lstsq(np.c_[bot[:, 0], bot[:, 2], np.ones(len(bot))], bot[:, 1], rcond=None)[0]
                bottom_y = float(a * p[0] + b * p[2] + c)                   # bottom height under the pole
                out[team_of(rec)] = (me, faces, np.array([p[0], p[1] - bottom_y, p[2]]), lo, hi,
                                     level_matrix(np.array([-a, 1.0, -b])), bottom_y)
                break
    if not out:
        raise ValueError(f"no flag pedestal found in {SOURCE_SCENE}")
    return out


def find_base(opt, p) -> Optional[int]:
    """Index of the pedestal mesh under the point ``p`` (engine), or None."""
    for i, me in enumerate(opt.meshes):
        lo, hi = crop.mesh_bounds(me)
        if lo[0] - 5 <= p[0] <= hi[0] + 5 and lo[2] - 5 <= p[2] <= hi[2] + 5 and (hi - lo)[[0, 2]].max() < 400 and \
                any(PEDESTAL_TEXTURE in str(t).lower() for m in me.materials for t in m.textures):
            return i
    return None


def has_base(opt, p) -> bool:
    return find_base(opt, p) is not None


def level_matrix(n) -> np.ndarray:
    """Row-vector rotation (p' = p @ M) that turns the direction ``n`` into straight up."""
    n = np.asarray(n, np.float64); n /= np.linalg.norm(n)
    up = np.array([0.0, 1.0, 0.0])
    axis = np.cross(n, up)
    s_, c_ = np.linalg.norm(axis), float(n @ up)
    if s_ < 1e-9:
        return np.eye(3)
    k = axis / s_
    K = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
    R = np.eye(3) + s_ * K + (1 - c_) * (K @ K)                  # column-vector rotation
    return R.T


def rot_y(deg: float) -> np.ndarray:
    """Row-vector rotation about the vertical axis (p' = p @ M)."""
    a = np.radians(deg)
    c, s = np.cos(a), np.sin(a)
    return np.array([[c, 0.0, -s], [0.0, 1.0, 0.0], [s, 0.0, c]])


def square_angle(faces) -> float:
    """How much the pedestal is turned (degrees, -45..45): angle of the edges of its flat top."""
    for f in faces:
        if f.normal[1] > 0.99 and f.contours and len(f.contours[0]) == 4:
            c = np.asarray(f.contours[0], np.float64)
            d = c[1] - c[0]
            a = np.degrees(np.arctan2(d[2], d[0]))
            return float((a + 45.0) % 90.0 - 45.0)
    return 0.0


def rotated_face(f, m3, centre):
    c = np.asarray(centre, np.float64)
    cs = [(((np.asarray(k, np.float64) - c) @ m3) + c).astype(np.float32) for k in f.contours]
    n = np.asarray(f.normal, np.float64) @ m3
    n /= np.linalg.norm(n)
    return hmcopy.HMFace(tuple(float(v) for v in n), -float(n @ cs[0][0]), cs)


def remove_base(opt, hm, p) -> bool:
    """Take away the pedestal under ``p`` and its floor collision."""
    i = find_base(opt, p)
    if i is None:
        return False
    lo, hi = crop.mesh_bounds(opt.meshes[i])
    crop.remove_meshes(opt, {i}, collision=False)
    if hm is not None:
        keep, gone = [], 0
        for f in hmcopy.unique_faces(hm):
            x0, z0, x1, z1 = hmcopy.face_bounds(f)
            ys = np.concatenate(f.contours)[:, 1]
            if x0 >= lo[0] - 3 and x1 <= hi[0] + 3 and z0 >= lo[2] - 3 and z1 <= hi[2] + 3 and ys.min() >= lo[1] - 2:
                gone += 1
            else:
                keep.append(f)
        if gone:
            hm.root = hmcopy.build_tree(keep, hmcopy.box(hm.root), max(hmcopy.tree_depth(hm.root), 1))
    return True


def add_base(opt, hm, rec, pedestals, angle: float = 0.0, replace: bool = False) -> str:
    """Put a pedestal under the flag module ``rec`` and lift the flag onto it.  ``hm`` (may be None) gets its floor.
    ``angle`` = turn in degrees; 0 = sides along the map's axes (the pedestal of mp_b_anderguater stands at 45 degrees).
    ``replace``: an existing base is taken away first (to turn it, or after moving the flag)."""
    p = flag_pos(rec)
    if has_base(opt, p):
        if not replace:
            return f"{str(rec.object_name).rstrip(chr(0))}: already on a base"
        remove_base(opt, hm, p)
    team = team_of(rec)
    src = pedestals.get(team) or next(iter(pedestals.values()))
    mesh, faces, rel, lo, hi, level, bottom_y = src
    g = ground_y(hm, p[0], p[2], p[1] + 60.0) if hm is not None else None
    ground = g if g is not None else p[1] - 1.0
    # source: flag at (fx, bottom + rel_y, fz); the pedestal is centred on the flag pole
    src_flag = np.array([rel[0], bottom_y, rel[2]])
    delta = np.array([p[0] - src_flag[0], ground - bottom_y, p[2] - src_flag[2]])
    m = copy.deepcopy(mesh)
    translate_mesh(m, delta)
    turn = level @ rot_y(float(angle) - square_angle(faces))        # level first, then the wanted angle
    centre = np.array([p[0], ground, p[2]])
    transform_mesh(m, turn, centre)
    crop.add_mesh(opt, m)
    if hm is not None and faces:
        hmcopy.add_faces(hm, [rotated_face(hmcopy.shifted(f, *delta), turn, centre) for f in faces])
    rec.parsed.transform = np.asarray(rec.parsed.transform, np.float32).copy()
    rec.parsed.transform[3, 1] = np.float32(ground + rel[1])
    return f"{str(rec.object_name).rstrip(chr(0))}: base added ({team}, {angle:.0f} deg), flag at y {ground + rel[1]:.0f}"
