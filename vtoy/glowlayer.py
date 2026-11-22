"""The shading layer of the maps ("glow"): what makes mp_b_garaje and others not look flat.

It is not real-time light and not the fog: those maps give their meshes a SECOND texture, multiplied over the normal one,
mapped with a second set of texture coordinates (uv2).  The texture is a soft round spot (``glow_galo.tex``: white centre,
dark edge) and uv2 is a flat projection of the world seen from above, repeated every few metres: under the lamps the
textures keep their colour, between them they get darker.  Measured on mp_b_garaje: uv2 = x / ~600 and -z / ~700 for the
floors; walls use the plane they face.  Coloured spots (glow_galo_amar / azul) tint as well.

    apply(opt, mesh, texture, size, centre)     give a mesh that layer (every level of detail)
    remove(opt, mesh)                            take it away again
    make_texture(centre, edge, colour, softness) a new spot texture (light pool, or dark in the middle = a shadow)
"""
from __future__ import annotations

from typing import Tuple

import numpy as np

from .opt import VERTEX2_DTYPE, VERTEX_DTYPE


def _to2(v: np.ndarray) -> np.ndarray:
    if v.dtype == VERTEX2_DTYPE:
        return v
    out = np.zeros(len(v), VERTEX2_DTYPE)
    for k in ("pos", "nrm", "uv"):
        out[k] = v[k]
    return out


def _to1(v: np.ndarray) -> np.ndarray:
    if v.dtype == VERTEX_DTYPE:
        return v
    out = np.zeros(len(v), VERTEX_DTYPE)
    for k in ("pos", "nrm", "uv"):
        out[k] = v[k]
    return out


def project(pos: np.ndarray, nrm: np.ndarray, size: float, centre=(0.0, 0.0, 0.0), aspect: float = 1.0) -> np.ndarray:
    """uv2 for points: floors / ceilings from above (x, -z), walls from the side they face; one repeat every ``size``
    units, a spot centred on ``centre``."""
    p = np.asarray(pos, np.float64) - np.asarray(centre, np.float64)
    n = np.abs(np.asarray(nrm, np.float64))
    su, sv = float(size), float(size) * float(aspect)
    uv = np.empty((len(p), 2))
    top = (n[:, 1] >= n[:, 0]) & (n[:, 1] >= n[:, 2])
    side_x = ~top & (n[:, 0] >= n[:, 2])
    side_z = ~top & ~side_x
    uv[top] = np.stack([p[top, 0] / su, -p[top, 2] / sv], 1)
    uv[side_x] = np.stack([p[side_x, 2] / su, -p[side_x, 1] / sv], 1)
    uv[side_z] = np.stack([p[side_z, 0] / su, -p[side_z, 1] / sv], 1)
    return (uv + 0.5).astype(np.float32)


def apply(opt, mesh_index: int, texture: str, size: float = 650.0, centre=(0.0, 0.0, 0.0), aspect: float = 1.0) -> int:
    """Give mesh ``mesh_index`` the shading layer ``texture`` (every material, every level of detail; textures without
    a picture are left alone).  Returns the number of submeshes changed."""
    if not texture.lower().endswith(".tex"):
        texture += ".tex"
    me = opt.meshes[mesh_index]
    for m in me.materials:
        if m.textures:
            m.textures = [m.textures[0], texture] + list(m.textures[2:])
    n = 0
    for lod in me.lods:
        for part in lod.parts:
            if part.shared_vertices is not None:          # old (VTOP) layout: not touched
                continue
            for sm in part.submeshes:
                if sm.vertices is None or not len(sm.vertices):
                    continue
                if sm.material_index < len(me.materials) and not me.materials[sm.material_index].textures:
                    continue
                v = _to2(sm.vertices).copy()
                v["uv2"] = project(v["pos"], v["nrm"], size, centre, aspect)
                sm.vertices = v
                sm.stride_type = 1
                n += 1
    return n


def remove(opt, mesh_index: int) -> int:
    """Take the shading layer away from a mesh (its second texture and uv2)."""
    me = opt.meshes[mesh_index]
    for m in me.materials:
        if len(m.textures) > 1:
            m.textures = [m.textures[0]] + list(m.textures[2:])
    n = 0
    for lod in me.lods:
        for part in lod.parts:
            for sm in part.submeshes:
                if sm.stride_type != 0 and sm.vertices is not None and part.shared_vertices is None:
                    sm.vertices = _to1(sm.vertices)
                    sm.stride_type = 0
                    n += 1
    return n


def layer_of(me) -> Tuple[str, int]:
    """(second texture, number of submeshes using it) of a mesh; ('', 0) without layer."""
    tex = next((str(m.textures[1]) for m in me.materials if len(m.textures) > 1), "")
    n = sum(1 for lod in me.lods[:1] for p in lod.parts for s in p.submeshes if s.stride_type != 0)
    return (tex, n) if n else ("", 0)


def make_texture(centre: float = 1.0, edge: float = 0.25, colour=(1.0, 1.0, 1.0), softness: float = 1.0,
                 size: int = 64) -> np.ndarray:
    """RGBA of a round spot: ``centre`` brightness in the middle, ``edge`` at the border (0..1; under 1 darkens), tinted by
    ``colour``.  centre > edge = a pool of light (like glow_galo); centre < edge = a shadow in the middle."""
    y, x = np.mgrid[0:size, 0:size].astype(np.float64)
    r = np.hypot(x - (size - 1) / 2, y - (size - 1) / 2) / (size / 2)
    t = np.clip(r, 0, 1) ** max(0.2, float(softness))
    t = t * t * (3 - 2 * t)                               # smooth step: no ring at the border
    val = centre + (edge - centre) * t
    rgb = np.clip(val[..., None] * np.asarray(colour, np.float64)[None, None, :], 0, 1)
    out = np.empty((size, size, 4), np.uint8)
    out[..., :3] = np.round(rgb * 255)
    out[..., 3] = 255
    return out
