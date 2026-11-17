"""Wavefront OBJ (+ MTL) -> a static mesh of the map.

OBJ files are right-handed, counter-clockwise, y up (or z up: ``up='z'``), usually in metres; the engine is left-handed
with 1 unit = 1 cm.  The model is scaled, its z is mirrored (which also turns the winding into the engine's: checked against
the shipped maps, where the visible side of a triangle is ``-cross(b - a, c - a)``), v is flipped (D3D textures start at the
top) and it is split in one submesh per material (16 bit indices: at most 65535 vertices each).

    model = parse_obj(path)
    mesh  = to_mesh(model, opt, texture_of, scale=100, at=(x, y, z), yaw=0)
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np

from .fill import LOD_FAR
from .opt import Lod, Material, MeshPart, StaticMesh, SubMesh, VERTEX_DTYPE

MAX_VERTS = 65535


@dataclass
class ObjMaterial:
    name: str = ""
    image: Optional[str] = None                 # full path of map_Kd (None: plain colour)
    color: Tuple[float, float, float] = (0.8, 0.8, 0.8)
    alpha: float = 1.0


@dataclass
class ObjGroup:
    pos: np.ndarray = None                      # (n, 3) float64, OBJ space
    nrm: np.ndarray = None                      # (n, 3)
    uv: np.ndarray = None                       # (n, 2)
    tris: np.ndarray = None                     # (m, 3) int


@dataclass
class ObjModel:
    name: str = ""
    groups: Dict[str, ObjGroup] = field(default_factory=dict)        # material name -> geometry
    materials: Dict[str, ObjMaterial] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)

    @property
    def triangle_count(self) -> int:
        return sum(len(g.tris) for g in self.groups.values())

    def bounds(self):
        p = np.concatenate([g.pos for g in self.groups.values()])
        return p.min(0), p.max(0)


def _read_text(path: str) -> List[str]:
    with open(path, "rb") as f:
        raw = f.read()
    for enc in ("utf-8", "cp1252"):
        try:
            return raw.decode(enc).splitlines()
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1").splitlines()


def parse_mtl(path: str) -> Dict[str, ObjMaterial]:
    out: Dict[str, ObjMaterial] = {}
    cur = None
    base = os.path.dirname(os.path.abspath(path))
    for line in _read_text(path):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        key, _, rest = s.partition(" ")
        key, rest = key.lower(), rest.strip()
        if key == "newmtl":
            cur = out.setdefault(rest, ObjMaterial(name=rest))
        elif cur is None:
            continue
        elif key == "kd":
            try:
                v = [float(x) for x in rest.split()[:3]]
                cur.color = tuple((v + v[-1:] * 3)[:3])
            except ValueError:
                pass
        elif key in ("d", "tr"):
            try:
                a = float(rest.split()[0])
                cur.alpha = a if key == "d" else 1.0 - a
            except (ValueError, IndexError):
                pass
        elif key == "map_kd":
            # options (-s 1 1 1 ...) come before the file name; the name may contain spaces
            parts = rest.split()
            while parts and parts[0].startswith("-"):
                n = {"-blendu": 1, "-blendv": 1, "-clamp": 1, "-bm": 1, "-mm": 2, "-o": 3, "-s": 3, "-t": 3}.get(parts[0].lower(), 1)
                parts = parts[1 + n:]
            name = " ".join(parts).replace("\\", "/")
            if name:
                for cand in (name, os.path.join(base, name), os.path.join(base, os.path.basename(name))):
                    if os.path.isfile(cand):
                        cur.image = os.path.abspath(cand)
                        break
    return out


def parse_obj(path: str) -> ObjModel:
    """Read an OBJ file: polygons are fanned into triangles, negative (relative) indices are understood, missing normals are
    computed (smooth per vertex).  Faces are grouped by material."""
    model = ObjModel(name=os.path.splitext(os.path.basename(path))[0])
    base = os.path.dirname(os.path.abspath(path))
    V: List[tuple] = []
    VT: List[tuple] = []
    VN: List[tuple] = []
    faces: Dict[str, List[list]] = {}
    cur = "default"
    for line in _read_text(path):
        s = line.strip()
        if not s or s[0] == "#":
            continue
        key, _, rest = s.partition(" ")
        if key == "v":
            p = rest.split()
            V.append((float(p[0]), float(p[1]), float(p[2])))
        elif key == "vt":
            p = rest.split()
            VT.append((float(p[0]), float(p[1]) if len(p) > 1 else 0.0))
        elif key == "vn":
            p = rest.split()
            VN.append((float(p[0]), float(p[1]), float(p[2])))
        elif key == "f":
            corners = []
            for tok in rest.split():
                a = tok.split("/")
                vi = int(a[0])
                ti = int(a[1]) if len(a) > 1 and a[1] else 0
                ni = int(a[2]) if len(a) > 2 and a[2] else 0
                corners.append((vi - 1 if vi > 0 else len(V) + vi,
                                ti - 1 if ti > 0 else (len(VT) + ti if ti < 0 else -1),
                                ni - 1 if ni > 0 else (len(VN) + ni if ni < 0 else -1)))
            if len(corners) >= 3:
                faces.setdefault(cur, []).append(corners)
        elif key == "usemtl":
            cur = rest.strip() or "default"
        elif key == "mtllib":
            mp = os.path.join(base, rest.strip())
            if os.path.isfile(mp):
                model.materials.update(parse_mtl(mp))
            else:
                model.warnings.append(f"material file {rest.strip()} not found (plain colours are used)")
    if not V or not faces:
        raise ValueError("the OBJ file has no faces")
    Va = np.asarray(V, np.float64)
    # smooth normals for corners without one
    smooth = None
    if any(c[2] < 0 for fl in faces.values() for f in fl for c in f):
        smooth = np.zeros_like(Va)
        for fl in faces.values():
            for f in fl:
                p = Va[[c[0] for c in f]]
                n = np.zeros(3)
                for i in range(len(p)):
                    n += np.cross(p[i], p[(i + 1) % len(p)])
                for c in f:
                    smooth[c[0]] += n
        ln = np.linalg.norm(smooth, axis=1, keepdims=True)
        smooth = smooth / np.maximum(ln, 1e-12)
    for mat, fl in faces.items():
        index: Dict[tuple, int] = {}
        pos, nrm, uv, tris = [], [], [], []
        for f in fl:
            ids = []
            for c in f:
                if not 0 <= c[0] < len(V):
                    raise ValueError("the OBJ file refers to a vertex that does not exist")
                k = index.get(c)
                if k is None:
                    k = index[c] = len(pos)
                    pos.append(V[c[0]])
                    nrm.append(VN[c[2]] if 0 <= c[2] < len(VN) else tuple(smooth[c[0]]) if smooth is not None else (0.0, 1.0, 0.0))
                    uv.append(VT[c[1]] if 0 <= c[1] < len(VT) else (0.0, 0.0))
                ids.append(k)
            for i in range(1, len(ids) - 1):
                tris.append((ids[0], ids[i], ids[i + 1]))
        model.groups[mat] = ObjGroup(np.asarray(pos, np.float64), np.asarray(nrm, np.float64), np.asarray(uv, np.float64),
                                     np.asarray(tris, np.int64).reshape(-1, 3))
        model.materials.setdefault(mat, ObjMaterial(name=mat))
    if not VT:
        model.warnings.append("the model has no texture coordinates: textures will look like one flat colour")
    return model


def material_image(mat: ObjMaterial, max_size: int = 1024) -> np.ndarray:
    """RGBA image of a material with power-of-two sides (what the engine's DXT textures need): its picture, or an 8x8 tile of
    its colour."""
    from PIL import Image
    if mat.image:
        im = Image.open(mat.image).convert("RGBA")
        pow2 = lambda v: int(min(max_size, max(4, 2 ** int(round(np.log2(max(v, 1)))))))
        w, h = pow2(im.width), pow2(im.height)
        if im.size != (w, h):
            im = im.resize((w, h), Image.LANCZOS)
        rgba = np.array(im, np.uint8)
    else:
        rgba = np.zeros((8, 8, 4), np.uint8)
        rgba[..., :3] = np.clip(np.asarray(mat.color) * 255.0, 0, 255).astype(np.uint8)
        rgba[..., 3] = 255
    if mat.alpha < 0.999:
        rgba[..., 3] = (rgba[..., 3].astype(np.float32) * max(mat.alpha, 0.0)).astype(np.uint8)
    return rgba


def to_engine(model: ObjModel, scale: float = 100.0, at=(0.0, 0.0, 0.0), yaw: float = 0.0, up: str = "y",
              ground: bool = True) -> Dict[str, ObjGroup]:
    """The groups in engine coordinates.  ``ground``: the lowest point of the model is put at ``at`` (its xz centre on it);
    otherwise the OBJ origin goes there."""
    from .solids import rot_y
    R = rot_y(yaw)

    def conv(a, is_pos):
        a = np.asarray(a, np.float64)
        if up == "z":
            a = np.stack([a[:, 0], a[:, 2], -a[:, 1]], 1)
        a = a * [1.0, 1.0, -1.0]                                  # right-handed -> left-handed
        return (a * scale if is_pos else a) @ R

    out = {name: ObjGroup(conv(g.pos, True), conv(g.nrm, False), np.stack([g.uv[:, 0], 1.0 - g.uv[:, 1]], 1), g.tris)
           for name, g in model.groups.items()}
    allp = np.concatenate([g.pos for g in out.values()])
    lo, hi = allp.min(0), allp.max(0)
    shift = np.asarray(at, np.float64) - ([(lo[0] + hi[0]) / 2, lo[1], (lo[2] + hi[2]) / 2] if ground else 0.0)
    for g in out.values():
        g.pos = g.pos + shift
        ln = np.linalg.norm(g.nrm, axis=1, keepdims=True)
        g.nrm = g.nrm / np.maximum(ln, 1e-12)
    return out


def _chunks(g: ObjGroup):
    """Split a group in pieces of at most MAX_VERTS vertices (each with its own vertex list)."""
    if len(g.pos) <= MAX_VERTS:
        yield g.pos, g.nrm, g.uv, g.tris
        return
    start = 0
    while start < len(g.tris):
        used: Dict[int, int] = {}
        tl = []
        k = start
        while k < len(g.tris) and len(used) + 3 <= MAX_VERTS:
            tl.append([used.setdefault(int(v), len(used)) for v in g.tris[k]])
            k += 1
        ids = np.fromiter(used.keys(), np.int64, len(used))
        yield g.pos[ids], g.nrm[ids], g.uv[ids], np.asarray(tl, np.int64)
        start = k


def to_mesh(model: ObjModel, opt, texture_of: Callable[[str], str], scale: float = 100.0, at=(0.0, 0.0, 0.0),
            yaw: float = 0.0, up: str = "y", two_sided: bool = False, ground: bool = True) -> StaticMesh:
    """A static mesh (vertices in world space) with one material per OBJ material.
    ``texture_of(material name)`` gives the .tex name to use for it."""
    groups = to_engine(model, scale, at, yaw, up, ground)
    donor = next((m for me in opt.meshes for m in me.materials if m.textures), None) if opt is not None else None
    mats, subs = [], []
    first = 0
    for name, g in groups.items():
        if not len(g.tris):
            continue
        tex = texture_of(name)
        if not tex.lower().endswith(".tex"):
            tex += ".tex"
        mi = len(mats)
        mats.append(Material(name=(name or "material")[:60], textures=[tex], two_sided=bool(two_sided),
                             uv_map=donor.uv_map if donor else b"\0" * 64, unk_float=donor.unk_float if donor else 100.0))
        for pos, nrm, uv, tris in _chunks(g):
            v = np.zeros(len(pos), VERTEX_DTYPE)
            v["pos"], v["nrm"], v["uv"] = pos.astype(np.float32), nrm.astype(np.float32), uv.astype(np.float32)
            idx = tris.astype(np.uint16).reshape(-1)
            # 'unk' is the position of the submesh in the index buffer of its part (true for 23296 of 23298 shipped submeshes)
            subs.append(SubMesh(stride_type=0, material_id=0, material_index=mi, unk=first, vertices=v, indices=idx))
            first += len(idx)
    if not subs:
        raise ValueError("the model has no triangles")
    allp = np.concatenate([s.vertices["pos"] for s in subs])
    lo, hi = allp.min(0), allp.max(0)
    corners = np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])], np.float32)
    part = MeshPart(active=True, corners=corners.astype("<f4").tobytes(), submeshes=subs)
    me = StaticMesh(materials=mats, lods=[Lod(unk=LOD_FAR, parts=[part])], corners=corners)
    me.world_transform = np.eye(4, dtype=np.float32)
    me.world_transform[3, :3] = (lo + hi) / 2
    return me
