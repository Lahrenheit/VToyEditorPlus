"""Solid things made in the editor: what you see (a textured mesh) and what you bump into (a collision box of the map +
floor / wall faces of the height map) created together, like the gangplanks of the twin ships.

Shapes, in their own frame (x = length, y = up, z = width; origin = bottom centre), then turned ``yaw`` degrees about the
vertical axis and put at ``at`` (engine coordinates):

    plank   a slab you walk on          block   a box (crate, pillar, platform)
    wall    a thin, tall box            ramp    a wedge rising from -x (floor) to +x (``height``)
    rail    a handrail on posts (the collision is a wall as long and as high as the rail)

Collision boxes are only ever turned about the vertical axis (as in every shipped map), so a ramp has no box: its slope,
back and sides are faces of the height map, which is what the stairs of the game use."""
from __future__ import annotations

from typing import List, Tuple

import numpy as np

from . import crop, hmcopy, regioncopy
from .fill import LOD_FAR
from .opt import STOCK_MATERIAL
from .opt import Lod, Material, MeshPart, StaticMesh, SubMesh, VERTEX_DTYPE

SHAPES = ("plank", "block", "wall", "ramp", "rail", "railing")
DEFAULTS = {"plank": (600.0, 200.0, 12.0), "block": (150.0, 150.0, 150.0), "wall": (600.0, 20.0, 250.0),
            "ramp": (400.0, 200.0, 150.0), "rail": (600.0, 12.0, 110.0), "railing": (600.0, 8.0, 88.0)}   # length, width, height

# The railings of the Love Boat: a see-through panel textured with the LEFT half of barandillas_poli.tex turned 90 degrees
# (u 0.493 at the bottom -> 0.046 at the top, v along the rail, one repeat every ~150 units = 6 bars) and a wooden bar on top.
RAIL_TEX = "barandillas_poli.tex"
RAIL_U = (0.493, 0.046)
RAIL_V_EVERY = 150.0
RAIL_BAR = 8.0


def rot_y(deg: float) -> np.ndarray:
    a = np.radians(deg)
    c, s = np.cos(a), np.sin(a)
    return np.array([[c, 0.0, -s], [0.0, 1.0, 0.0], [s, 0.0, c]])


def _box_faces(x0, x1, y0, y1, z0, z1) -> List[Tuple[np.ndarray, tuple]]:
    P = lambda *q: np.array(q, np.float64)
    return [(P((x0, y1, z0), (x1, y1, z0), (x1, y1, z1), (x0, y1, z1)), (0, 1, 0)),      # top
            (P((x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1)), (0, -1, 0)),     # bottom
            (P((x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0)), (0, 0, -1)),
            (P((x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)), (0, 0, 1)),
            (P((x0, y0, z0), (x0, y0, z1), (x0, y1, z1), (x0, y1, z0)), (-1, 0, 0)),
            (P((x1, y0, z0), (x1, y0, z1), (x1, y1, z1), (x1, y1, z0)), (1, 0, 0))]


def local_faces(shape: str, length: float, width: float, height: float, post_every: float = 150.0):
    """Faces [(points (k, 3), outward normal)] of the visible mesh, in the shape's own frame."""
    L, W, H = float(length), float(width), float(height)
    x0, x1, z0, z1 = -L / 2, L / 2, -W / 2, W / 2
    if shape in ("plank", "block", "wall"):
        return _box_faces(x0, x1, 0.0, H, z0, z1)
    if shape == "ramp":
        P = lambda *q: np.array(q, np.float64)
        n = np.array([-H, L, 0.0]); n /= np.linalg.norm(n)
        return [(P((x0, 0, z0), (x1, H, z0), (x1, H, z1), (x0, 0, z1)), tuple(n)),              # the slope
                (P((x0, 0, z0), (x1, 0, z0), (x1, 0, z1), (x0, 0, z1)), (0, -1, 0)),            # bottom
                (P((x1, 0, z0), (x1, 0, z1), (x1, H, z1), (x1, H, z0)), (1, 0, 0)),             # back
                (P((x0, 0, z0), (x1, 0, z0), (x1, H, z0)), (0, 0, -1)),
                (P((x0, 0, z1), (x1, 0, z1), (x1, H, z1)), (0, 0, 1))]
    if shape == "rail":
        t = max(W, 4.0)
        faces = _box_faces(x0, x1, H - t, H, -t / 2, t / 2)                                     # the bar
        n = max(2, int(round(L / max(post_every, 20.0))) + 1)
        for k in range(n):
            x = x0 + t / 2 + (L - t) * k / (n - 1)
            faces += _box_faces(x - t / 2, x + t / 2, 0.0, H - t, -t / 2, t / 2)                # posts
        return faces
    raise ValueError(f"unknown shape {shape}")


def mesh_from_faces(opt, faces, texture: str, tile: float = 128.0) -> StaticMesh:
    """A static mesh of flat faces (world space), each with its own vertices, planar texture coordinates and normal."""
    vs, idx = [], []
    for face in faces:
        pts, n = face[0], face[1]
        uvs = face[2] if len(face) > 2 else None                 # explicit texture coordinates (railing panels)
        pts = np.asarray(pts, np.float64)
        n = np.asarray(n, np.float64); n = n / np.linalg.norm(n)
        u = pts[1] - pts[0]; u /= max(np.linalg.norm(u), 1e-9)
        w = np.cross(n, u)
        base = len(vs)
        for k, p in enumerate(pts):
            vs.append((p, n, tuple(uvs[k]) if uvs is not None else (float((p - pts[0]) @ u) / tile, float((p - pts[0]) @ w) / tile)))
        for k in range(1, len(pts) - 1):
            idx += [base, base + k, base + k + 1]
    v = np.zeros(len(vs), VERTEX_DTYPE)
    v["pos"] = np.array([a for a, _, _ in vs], np.float32)
    v["nrm"] = np.array([b for _, b, _ in vs], np.float32)
    v["uv"] = np.array([c for _, _, c in vs], np.float32)
    donor = next((mat for me in opt.meshes for mat in me.materials if mat.textures), None)
    if not texture.lower().endswith(".tex"):
        texture += ".tex"
    block = donor.uv_map if donor is not None and any(donor.uv_map[:48]) else STOCK_MATERIAL
    mat = Material(name=texture.rsplit(".", 1)[0], textures=[texture], two_sided=True,
                   uv_map=block, unk_float=donor.unk_float if donor else 100.0)
    lo, hi = v["pos"].min(0), v["pos"].max(0)
    corners = np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])], np.float32)
    part = MeshPart(active=True, corners=corners.astype("<f4").tobytes(),
                    submeshes=[SubMesh(stride_type=0, material_id=0, material_index=0, unk=0, vertices=v,
                                       indices=np.asarray(idx, np.uint16))])
    me = StaticMesh(materials=[mat], lods=[Lod(unk=LOD_FAR, parts=[part])], corners=corners)
    me.world_transform = np.eye(4, dtype=np.float32)
    me.world_transform[3, :3] = (lo + hi) / 2
    return me


def railing_visual(opt, a, b, height: float = 88.0, wood_tex: str = "tablones.tex", panel: bool = True) -> list:
    """The look of a ship's railing along the line a -> b (engine points on the floor; it may slope): a see-through metal
    panel + a wooden bar on top (or only bar and posts when ``panel`` is off / the texture is not there).
    Returns the indices of the new meshes (no collision: see ``build`` / the gangplanks)."""
    a, b = np.asarray(a, np.float64), np.asarray(b, np.float64)
    d = b - a
    L = float(np.hypot(d[0], d[2]))
    if L < 1.0:
        raise ValueError("the two points are on top of each other")
    ux = np.array([d[0], 0.0, d[2]]) / L                       # along the rail (horizontal)
    side = np.cross([0.0, 1.0, 0.0], ux)                         # across it
    rise = float(d[1])
    at = lambda x, y, z=0.0: a + ux * x + np.array([0.0, y + rise * x / L, 0.0]) + side * z
    out = []
    hp = max(height - RAIL_BAR, 10.0)
    if panel:
        v1 = L / RAIL_V_EVERY
        quad = (np.array([at(0, 0), at(L, 0), at(L, hp), at(0, hp)]), tuple(side),
                [(RAIL_U[0], 0.0), (RAIL_U[0], v1), (RAIL_U[1], v1), (RAIL_U[1], 0.0)])
        out.append(crop.add_mesh(opt, mesh_from_faces(opt, [quad], RAIL_TEX)))
    wood = []
    t = RAIL_BAR
    for pts, n in _box_faces(0.0, L, hp, hp + t, -t / 2, t / 2):                       # the bar on top
        wood.append((np.array([at(q[0], q[1], q[2]) for q in pts]), np.asarray(n, np.float64) @ np.array([ux, [0, 1, 0], side])))
    if not panel:                                                                       # no panel texture: wooden posts
        n_posts = max(2, int(round(L / 150.0)) + 1)
        for k in range(n_posts):
            x = t / 2 + (L - t) * k / (n_posts - 1)
            for pts, n in _box_faces(x - t / 2, x + t / 2, 0.0, hp, -t / 2, t / 2):
                wood.append((np.array([at(q[0], q[1], q[2]) for q in pts]), np.asarray(n, np.float64) @ np.array([ux, [0, 1, 0], side])))
    out.append(crop.add_mesh(opt, mesh_from_faces(opt, wood, wood_tex, 128.0)))
    return out


def collision_faces(shape: str, length: float, width: float, height: float):
    """Local faces of the height map: [(points, outward normal)] - where you can stand and what stops you."""
    L, W, H = float(length), float(width), float(height)
    if shape == "railing":
        shape, W = "rail", max(W, 8.0)
    if shape == "rail":
        t = max(W, 4.0)
        return [f for f in _box_faces(-L / 2, L / 2, 0.0, H, -t / 2, t / 2) if abs(f[1][1]) < 0.5]     # 4 walls, no top
    return [f for f in local_faces(shape, L, W, H) if f[1][1] > -0.5]                                  # all but the bottom


def build(opt, hm, shape: str, at, length: float, width: float, height: float, yaw: float = 0.0,
          texture: str = "tablones.tex", tile: float = 128.0, has_texture=None) -> dict:
    """Add the solid to the map ``opt`` (mesh + collision box) and to the height map ``hm`` (may be None: no floor then).
    Returns {'mesh': index, 'box': index | None, 'faces': n}."""
    if shape not in SHAPES:
        raise ValueError(f"unknown shape {shape}")
    if min(length, width, height) <= 0:
        raise ValueError("length, width and height must be > 0")
    at = np.asarray(at, np.float64)
    R = rot_y(yaw)
    world = lambda p: np.asarray(p, np.float64) @ R + at
    if shape == "railing":
        panel = has_texture(RAIL_TEX) if has_texture is not None else True
        mi = railing_visual(opt, world((-length / 2, 0.0, 0.0)), world((length / 2, 0.0, 0.0)), height, texture, panel)[0]
    else:
        vis = [(world(p), tuple(np.asarray(n, np.float64) @ R)) for p, n in local_faces(shape, length, width, height)]
        mi = crop.add_mesh(opt, mesh_from_faces(opt, vis, texture, tile))
    bi = None
    if shape != "ramp":
        w_box = max(width, 4.0)
        bi = regioncopy.add_box(opt, world((0.0, height / 2, 0.0)), [length / 2, height / 2, w_box / 2], axes=R)
    nf = 0
    if hm is not None:
        faces = [hmcopy.make_face(world(p), np.asarray(n, np.float64) @ R) for p, n in collision_faces(shape, length, width, height)]
        hmcopy.add_faces(hm, faces)
        nf = len(faces)
    return {"mesh": mi, "box": bi, "faces": nf}


def between(shape: str, a, b, width: float, height: float):
    """Placement of a solid that runs from point ``a`` to point ``b`` (engine): (at, length, yaw, height).
    A plank's top is level with the points; a ramp rises from the lower point to the higher one; walls and rails stand on them."""
    a, b = np.asarray(a, np.float64), np.asarray(b, np.float64)
    if shape == "ramp" and a[1] > b[1]:
        a, b = b, a
    d = b - a
    length = float(np.hypot(d[0], d[2]))
    if length < 1.0:
        raise ValueError("the two points are on top of each other")
    yaw = float(np.degrees(np.arctan2(-d[2], d[0])))
    mid = (a + b) / 2
    if shape == "ramp":
        h = max(float(d[1]), 1.0)
        return np.array([mid[0], a[1], mid[2]]), length, yaw, h
    y = min(a[1], b[1])
    if shape == "plank":
        y -= height
    return np.array([mid[0], y, mid[2]]), length, yaw, float(height)
