"""Turns a scene (.scn + .opt + models) into GPU-friendly, *pure numpy* data. No OpenGL in here, so it is unit-testable.

Coordinates: the engine is left-handed; like the original C# viewer everything is mirrored with ZFLIP (z -> -z) so it
can be drawn with a normal right-handed OpenGL camera. All vertex data is baked into that world space on the CPU.

Transparency (the "church floor culls the flags" bug of the C# editor)
---------------------------------------------------------------------
The C# renderer sorted draw calls by ``modelMatrix.Translation``. For static meshes that is always (0,0,0), so every
transparent mesh had the same key and the order was arbitrary; a depth pre-pass then let the nearer semi transparent
floor occlude what was behind it.  Here every transparent *triangle* is stored in one pool and, each frame, sorted
back-to-front by its own world-space centroid (``SceneGeometry.sort_transparent``) - no pre-pass, depth writes off.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np

ZFLIP = np.diag([1.0, 1.0, -1.0, 1.0])
MODEL_MODULES = ("rendernfo", "animatedrendernfo", "cglass", "mp_door", "mp_cosa", "mp_ccar", "mp_salud", "mp_flag",
                 "mp_boton", "mp_bombzone", "mp_bomba", "vagonmetro", "ventilador", "mp_moto", "torocar", "mp_coxe",
                 "mp_botikin", "mp_personaje")


@dataclass
class Batch:
    """Opaque geometry that shares one texture and culling mode (and its light texture, see ``lightmap``)."""
    texture: str
    two_sided: bool
    vertices: np.ndarray        # (n, 8) float32  pos3 nrm3 uv2
    indices: np.ndarray         # (m,) uint32
    lightmap: str = ""          # second texture drawn x 2 (the game's stage 1: a CS map's light, "glow_*" ...)
    uv2: Optional[np.ndarray] = None     # (n, 2) float32: its texture coordinates


@dataclass
class Instance:
    """Something the user can click: a static mesh, a prop or a module with a model."""
    kind: str                   # 'mesh' | 'prop' | 'module'
    label: str
    ref: object                 # StaticMesh | Prop | ModuleRecord
    lo: np.ndarray              # world-space AABB (already mirrored)
    hi: np.ndarray


@dataclass
class SceneGeometry:
    opaque: List[Batch] = field(default_factory=list)
    tverts: np.ndarray = field(default_factory=lambda: np.zeros((0, 8), np.float32))
    ttri: np.ndarray = field(default_factory=lambda: np.zeros((0, 3), np.uint32))
    ttex: np.ndarray = field(default_factory=lambda: np.zeros(0, np.int32))     # texture id per triangle
    ttwo: np.ndarray = field(default_factory=lambda: np.zeros(0, bool))        # two sided per triangle
    tex_names: List[str] = field(default_factory=list)
    instances: List[Instance] = field(default_factory=list)
    stats: Dict[str, int] = field(default_factory=dict)
    _tcent: Optional[np.ndarray] = None

    # --------------------------------------------------------------------------------------------
    @property
    def triangle_centroids(self) -> np.ndarray:
        if self._tcent is None:
            if len(self.ttri) == 0:
                self._tcent = np.zeros((0, 3), np.float32)
            else:
                p = self.tverts[:, :3]
                self._tcent = (p[self.ttri[:, 0]] + p[self.ttri[:, 1]] + p[self.ttri[:, 2]]) / 3.0
        return self._tcent

    def sort_transparent(self, cam_pos, mode: str = "triangle"):
        """Back-to-front draw order of the transparent pool.

        Returns ``(indices, runs)``: ``indices`` is a flat uint32 index buffer already sorted, ``runs`` a list of
        ``(texture_id, two_sided, first_index, index_count)`` that can be drawn with one call each.
        ``mode='triangle'`` sorts every triangle (correct for floors/flags/leaves), ``mode='texture'`` only keeps the
        legacy per-texture grouping (fast, used for comparison)."""
        n = len(self.ttri)
        if n == 0:
            return np.zeros(0, np.uint32), []
        d = self.triangle_centroids - np.asarray(cam_pos, np.float32)
        dist = (d * d).sum(1)
        if mode == "triangle":
            order = np.argsort(-dist, kind="stable")
        else:                                           # legacy: sort by texture group distance only
            order = np.lexsort((np.arange(n), self.ttex))
        tri = self.ttri[order]
        tex = self.ttex[order]
        two = self.ttwo[order]
        change = np.nonzero((tex[1:] != tex[:-1]) | (two[1:] != two[:-1]))[0] + 1
        starts = np.concatenate([[0], change])
        ends = np.concatenate([change, [n]])
        runs = [(int(tex[s]), bool(two[s]), int(s) * 3, int(e - s) * 3) for s, e in zip(starts, ends)]
        return tri.reshape(-1).astype(np.uint32), runs


# ------------------------------------------------------------------------------------------------
def transform_vertices(v8: np.ndarray, m: np.ndarray) -> np.ndarray:
    """Apply a 4x4 (row-vector convention) to pos and normal of an (n,8) vertex array."""
    out = np.empty((len(v8), 8), np.float32)
    a = np.asarray(m, np.float64)[:3, :3]
    out[:, :3] = v8[:, :3].astype(np.float64) @ a + np.asarray(m, np.float64)[3, :3]
    try:
        n = v8[:, 3:6].astype(np.float64) @ np.linalg.inv(a).T
    except np.linalg.LinAlgError:
        n = v8[:, 3:6].astype(np.float64) @ a
    ln = np.linalg.norm(n, axis=1, keepdims=True)
    out[:, 3:6] = n / np.maximum(ln, 1e-9)
    out[:, 6:8] = v8[:, 6:8]
    return out


def opt_submesh_vertices(sm) -> np.ndarray:
    v = sm.vertices
    return np.concatenate([v["pos"], v["nrm"], v["uv"]], axis=1).astype(np.float32)


def subdivide_triangles(verts: np.ndarray, tris: np.ndarray, max_edge: float, max_passes: int = 10):
    """Split every triangle whose longest edge exceeds ``max_edge`` (at that edge's midpoint) until none does.

    Needed for per-triangle depth sorting: a huge water plane made of 2 triangles has its centroid far away from the
    camera, so it would be (wrongly) drawn before small things lying right under it. verts (n,8) float32."""
    verts = np.asarray(verts, np.float32)
    tris = np.asarray(tris, np.int64)
    for _ in range(max_passes):
        p = verts[:, :3]
        e = np.stack([np.linalg.norm(p[tris[:, 1]] - p[tris[:, 0]], axis=1),
                      np.linalg.norm(p[tris[:, 2]] - p[tris[:, 1]], axis=1),
                      np.linalg.norm(p[tris[:, 0]] - p[tris[:, 2]], axis=1)], 1)
        big = e.max(1) > max_edge
        if not big.any():
            break
        keep, sp, le = tris[~big], tris[big], e[big].argmax(1)
        # rotate so that the longest edge is (a, b); c is the opposite corner
        idx = np.arange(len(sp))
        a = sp[idx, le]
        b = sp[idx, (le + 1) % 3]
        c = sp[idx, (le + 2) % 3]
        mid = (verts[a] + verts[b]) * 0.5
        nrm = mid[:, 3:6]
        mid[:, 3:6] = nrm / np.maximum(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-9)
        m = np.arange(len(verts), len(verts) + len(mid))
        verts = np.concatenate([verts, mid.astype(np.float32)])
        tris = np.concatenate([keep, np.stack([a, m, c], 1), np.stack([m, b, c], 1)])
    return verts, tris


class _Collector:
    """Accumulates baked geometry, merging by (texture, two_sided) and splitting transparent triangles."""

    def __init__(self, texture_alpha: Callable[[str], bool], max_edge: float = 400.0):
        self.alpha = texture_alpha
        self.max_edge = max_edge
        self.opq: Dict[Tuple[str, bool, str], List[Tuple[np.ndarray, np.ndarray, Optional[np.ndarray]]]] = {}
        self.tv: List[np.ndarray] = []
        self.tt: List[np.ndarray] = []
        self.tx: List[np.ndarray] = []
        self.t2: List[np.ndarray] = []
        self.tex_ids: Dict[str, int] = {}
        self.tbase = 0
        self.tri_count = 0

    def add(self, tex: str, two_sided: bool, verts: np.ndarray, indices: np.ndarray, lightmap: str = "", uv2=None):
        if len(indices) < 3 or len(verts) == 0:
            return
        if uv2 is None:
            lightmap = ""
        indices = indices[: len(indices) // 3 * 3]
        if self.alpha(tex):
            tid = self.tex_ids.setdefault(tex, len(self.tex_ids))
            if self.max_edge:
                verts, tri0 = subdivide_triangles(verts, indices.reshape(-1, 3), self.max_edge)
            else:
                tri0 = indices.reshape(-1, 3)
            self.tv.append(verts)
            tri = (tri0 + self.tbase).astype(np.uint32)
            self.tt.append(tri)
            self.tx.append(np.full(len(tri), tid, np.int32))
            self.t2.append(np.full(len(tri), two_sided, bool))
            self.tbase += len(verts)
        else:
            self.opq.setdefault((tex, two_sided, lightmap), []).append((verts, indices, uv2))
        self.tri_count += len(indices) // 3

    def finish(self, instances, stats) -> SceneGeometry:
        g = SceneGeometry(instances=instances, stats=stats)
        for (tex, two, lm), parts in self.opq.items():
            base, vs, ix, u2 = 0, [], [], []
            for v, i, w in parts:
                vs.append(v)
                ix.append(i.astype(np.uint32) + base)
                base += len(v)
                if lm:
                    u2.append(np.asarray(w, np.float32))
            g.opaque.append(Batch(tex, two, np.concatenate(vs), np.concatenate(ix), lm,
                                  np.concatenate(u2) if lm else None))
        g.opaque.sort(key=lambda b: (b.texture, b.two_sided))
        if self.tv:
            g.tverts = np.concatenate(self.tv)
            g.ttri = np.concatenate(self.tt)
            g.ttex = np.concatenate(self.tx)
            g.ttwo = np.concatenate(self.t2)
        g.tex_names = [n for n, _ in sorted(self.tex_ids.items(), key=lambda kv: kv[1])]
        stats["triangles"] = self.tri_count
        stats["transparent_triangles"] = len(g.ttri)
        return g


def _aabb(points: np.ndarray):
    return points.min(0), points.max(0)


def bake_scene(fs, scene, opt, include_models: bool = True, progress: Optional[Callable[[str], None]] = None,
               max_transparent_edge: float = 400.0, hide=frozenset(), anim=None, skip=frozenset(), hide_models=frozenset()):
    """Bake the whole scene. ``fs`` is a vtoy.gamefs.GameFS, ``scene`` a Scene (modules parsed), ``opt`` an OptMap.
    ``anim``: {id(module record): (KeyFile, frame)} poses those models with the key; ``skip``: ids of module records / static meshes / props not drawn."""
    alpha_cache: Dict[str, bool] = {}

    def has_alpha(tex: str) -> bool:
        key = tex.replace("\\", "/").split("/")[-1].rsplit(".", 1)[0].lower()
        if key not in alpha_cache:
            t = fs.texture(tex) if tex else None
            alpha_cache[key] = bool(t is not None and t.has_alpha)
        return alpha_cache[key]

    col = _Collector(has_alpha, max_transparent_edge)
    instances: List[Instance] = []
    stats = {"meshes": len(opt.meshes), "props": len(opt.props), "models": 0, "missing_models": 0}

    def add_mesh(mesh, matrix):
        pts = []
        for sm in mesh.render_submeshes():
            if len(sm.indices) < 3 or len(sm.vertices) == 0:
                continue
            mat = mesh.materials[sm.material_index] if sm.material_index < len(mesh.materials) else None
            v = transform_vertices(opt_submesh_vertices(sm), matrix)
            lm, uv2 = "", None
            if mat is not None and len(mat.textures) > 1 and getattr(sm, "stride_type", 0) == 1 \
                    and "uv2" in (sm.vertices.dtype.names or ()):
                lm, uv2 = str(mat.textures[1]), np.asarray(sm.vertices["uv2"], np.float32)
            col.add(mat.diffuse if mat else "", bool(mat.two_sided) if mat else False, v, sm.indices.astype(np.uint32),
                    lm, uv2)
            pts.append(v[:, :3])
        return np.concatenate(pts) if pts else None

    for i, me in enumerate(opt.meshes):
        if id(me) in skip:                                 # hidden in the editor (still in the map)
            continue
        pts = add_mesh(me, ZFLIP)
        if pts is not None:
            instances.append(Instance("mesh", f"mesh {i}", me, *_aabb(pts)))
    if progress:
        progress("static meshes done")
    for i, pr in enumerate(opt.props):
        if not 0 <= pr.mesh_index < len(opt.meshes) or id(pr) in skip:
            continue
        me = opt.meshes[pr.mesh_index]
        try:
            inv = np.linalg.inv(me.world_transform.astype(np.float64))
        except np.linalg.LinAlgError:
            continue
        pts = add_mesh(me, inv @ pr.transform.astype(np.float64) @ ZFLIP)
        if pts is not None:
            instances.append(Instance("prop", f"prop {i} (mesh {pr.mesh_index})", pr, *_aabb(pts)))
    if progress:
        progress("props done")

    if include_models:
        for rec in scene.modules:
            p = rec.parsed
            if p is None or rec.clean_name.lower() not in MODEL_MODULES or not getattr(p, "model_name", ""):
                continue
            if rec.clean_name.lower() in hide or id(rec) in skip:          # "Show health packs" etc. unchecked
                continue
            if hide_models and p.model_name.replace("\\", "/").split("/")[-1].rsplit(".", 1)[0].lower() in hide_models:
                continue                                  # "Show ParedT.nfo" unchecked
            model = fs.model(p.model_name)
            if model is None:
                stats["missing_models"] += 1
                continue
            stats["models"] += 1
            M = p.transform.astype(np.float64) @ ZFLIP
            pts = []
            posed = {}
            for obj, me in model.lod0_meshes():
                pre = None
                if anim and id(rec) in anim:
                    if id(obj) not in posed:
                        from ..animate import mesh_matrices
                        try:
                            posed[id(obj)] = mesh_matrices(obj, *anim[id(rec)])
                        except Exception:
                            posed[id(obj)] = {}
                    pre = posed[id(obj)].get(me.node_index)
                MM = M if pre is None else pre @ M
                for mi, v8, ind, _src in me.build():
                    mat = obj.materials[mi] if mi < len(obj.materials) else None
                    v = transform_vertices(v8, MM)
                    col.add(mat.texture if mat else "", False, v, ind)
                    pts.append(v[:, :3])
            if pts:
                instances.append(Instance("module", f"{rec.object_name} ({rec.clean_name})", rec, *_aabb(np.concatenate(pts))))
        if progress:
            progress("models done")
    return col.finish(instances, stats)


# ------------------------------------------------------------------------------------------------
def decal_quads(decals, view: np.ndarray, cam_pos):
    """Camera facing quads for the decals, as the C# viewer drew them. ``view`` is a 4x4 column-vector view matrix.

    Returns (vertices (n*4,8), indices (n*6,), order) with decals sorted back to front."""
    if not decals:
        return np.zeros((0, 8), np.float32), np.zeros(0, np.uint32), []
    right, up, back = view[0, :3], view[1, :3], view[2, :3]
    pos = np.array([d.position for d in decals], np.float64) * [1, 1, -1] + back * np.array([[d.z_offset] for d in decals])
    dist = ((pos - np.asarray(cam_pos)) ** 2).sum(1)
    order = list(np.argsort(-dist))
    verts, idx = [], []
    corners = [(-0.5, 0.5, 0, 0), (0.5, 0.5, 1, 0), (0.5, -0.5, 1, 1), (-0.5, -0.5, 0, 1)]
    for k, di in enumerate(order):
        d = decals[di]
        for cx, cy, u, v in corners:
            p = pos[di] + right * cx * d.scale_x + up * cy * d.scale_y
            verts.append([*p, *back, u, v])
        b = k * 4
        idx += [b, b + 2, b + 1, b, b + 3, b + 2]
    return np.array(verts, np.float32), np.array(idx, np.uint32), order


def cube_wire_edges() -> np.ndarray:
    """12 edges of a unit cube (24 vertices) for GL_LINES debug drawing."""
    c = np.array([[x, y, z] for x in (-.5, .5) for y in (-.5, .5) for z in (-.5, .5)], np.float32)
    e = [(0, 1), (2, 3), (4, 5), (6, 7), (0, 2), (1, 3), (4, 6), (5, 7), (0, 4), (1, 5), (2, 6), (3, 7)]
    return np.array([c[i] for pair in e for i in pair], np.float32)
