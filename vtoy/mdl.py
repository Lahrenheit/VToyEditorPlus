"""Half-Life / Counter-Strike 1.6 studio models (.mdl, version 10): the textures and the triangles of a model in its
first pose (sequence 0, frame 0), for the props of a CS map (cars, palm trees, awnings ... placed by cycler,
cycler_sprite, env_model ... entities).  Only what is needed to draw a model where the map puts it."""
from __future__ import annotations

import math
import os
import struct
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

STUDIO_NF_CHROME = 0x02
STUDIO_NF_ADDITIVE = 0x20
STUDIO_NF_MASKED = 0x40


@dataclass
class StudioTexture:
    name: str
    flags: int
    width: int
    height: int
    pixels: bytes
    palette: bytes

    def rgba(self) -> np.ndarray:
        idx = np.frombuffer(self.pixels, np.uint8).reshape(self.height, self.width)
        pal = np.frombuffer(self.palette.ljust(768, b"\0"), np.uint8).reshape(256, 3)
        out = np.empty((self.height, self.width, 4), np.uint8)
        out[..., :3] = pal[idx]
        out[..., 3] = 255
        if self.flags & STUDIO_NF_MASKED:
            out[idx == 255, 3] = 0
        return out


@dataclass
class StudioModel:
    name: str
    textures: List[StudioTexture] = field(default_factory=list)
    skins: List[List[int]] = field(default_factory=list)      # skin family -> skinref -> texture
    bones: np.ndarray = None                                  # (n, 4, 4) bone -> model space, first pose
    parts: list = field(default_factory=list)                 # body parts: [(base, [models])]; a model: [meshes]
                                                              # a mesh: (skinref, [(vert, uv(texels)) * 3 per triangle])

    def triangles(self, body: int = 0, skin: int = 0):
        """[(texture index, points (3, 3) model space, uv (3, 2) 0..1)] of the body chosen by ``body`` (the bodygroup
        number of the entity) with the skin family ``skin``."""
        out = []
        fam = self.skins[skin] if 0 <= skin < len(self.skins) else (self.skins[0] if self.skins else [])
        for base, models in self.parts:
            if not models:
                continue
            k = (body // max(base, 1)) % len(models)
            for skinref, tris in models[k]:
                t = fam[skinref] if 0 <= skinref < len(fam) else skinref
                if not 0 <= t < len(self.textures):
                    continue
                tx = self.textures[t]
                w, h = max(tx.width, 1), max(tx.height, 1)
                for pts, st in tris:
                    uv = np.asarray(st, np.float64) / np.array([w, h], np.float64)
                    out.append((t, np.asarray(pts, np.float64), uv))
        return out


def _angle_matrix(a) -> np.ndarray:
    """GoldSrc AngleQuaternion order: x roll, y pitch, z yaw - R = Rz(a2) Ry(a1) Rx(a0)."""
    cx, sx = math.cos(a[0]), math.sin(a[0])
    cy, sy = math.cos(a[1]), math.sin(a[1])
    cz, sz = math.cos(a[2]), math.sin(a[2])
    rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    return rz @ ry @ rx


def _first_frame(data: bytes, anim_at: int, bone: int, values: np.ndarray, scales: np.ndarray) -> np.ndarray:
    """The 6 values (position, rotation) of a bone at frame 0 of an animation."""
    out = values.copy()
    if anim_at < 0 or anim_at + 12 * (bone + 1) > len(data):
        return out
    offs = struct.unpack_from("<6H", data, anim_at + 12 * bone)
    base = anim_at + 12 * bone
    for j in range(6):
        if not offs[j]:
            continue
        p = base + offs[j]
        if p + 4 > len(data):
            continue
        valid, total = data[p], data[p + 1]
        if valid > 0 and total > 0:
            v = struct.unpack_from("<h", data, p + 2)[0]
            out[j] = values[j] + v * scales[j]
    return out


def _read_textures(data: bytes):
    ntex, texi, _texdata = struct.unpack_from("<3i", data, 180)
    nref, nfam, skini = struct.unpack_from("<3i", data, 192)
    texs = []
    for k in range(max(ntex, 0)):
        o = texi + 80 * k
        if o + 80 > len(data):
            break
        name = data[o:o + 64].split(b"\0")[0].decode("latin-1")
        flags, w, h, idx = struct.unpack_from("<4i", data, o + 64)
        if w <= 0 or h <= 0 or idx <= 0 or idx + w * h + 768 > len(data):
            texs.append(StudioTexture(name, flags, 1, 1, b"\0", bytes(768)))
            continue
        texs.append(StudioTexture(name, flags, w, h, data[idx:idx + w * h], data[idx + w * h:idx + w * h + 768]))
    skins = []
    for f in range(max(nfam, 0)):
        o = skini + 2 * nref * f
        if nref <= 0 or o + 2 * nref > len(data):
            break
        skins.append(list(struct.unpack_from(f"<{nref}h", data, o)))
    return texs, skins


def load(path: str) -> StudioModel:
    """A .mdl (with its ...T.mdl of textures when the textures are kept apart)."""
    data = open(path, "rb").read()
    if data[:4] != b"IDST" or struct.unpack_from("<i", data, 4)[0] != 10:
        raise ValueError(f"{os.path.basename(path)}: not a Half-Life model (IDST version 10)")
    name = data[8:72].split(b"\0")[0].decode("latin-1")
    m = StudioModel(name)
    m.textures, m.skins = _read_textures(data)
    if not m.textures:                                        # the textures in modelT.mdl
        stem, ext = os.path.splitext(path)
        for cand in (stem + "T" + ext, stem + "t" + ext):
            if os.path.isfile(cand):
                tdata = open(cand, "rb").read()
                if tdata[:4] in (b"IDST", b"IDSQ"):
                    m.textures, m.skins = _read_textures(tdata)
                break
    if not m.skins:
        m.skins = [list(range(len(m.textures)))]
    # bones, first pose
    nb, bi = struct.unpack_from("<2i", data, 140)
    nseq, seqi = struct.unpack_from("<2i", data, 164)
    anim_at = -1
    if nseq > 0 and seqi + 176 <= len(data):
        animindex = struct.unpack_from("<i", data, seqi + 124)[0]
        seqgroup = struct.unpack_from("<i", data, seqi + 156)[0]
        if seqgroup == 0:
            anim_at = animindex
    mats = np.zeros((max(nb, 0), 4, 4))
    for k in range(max(nb, 0)):
        o = bi + 112 * k
        parent = struct.unpack_from("<i", data, o + 32)[0]
        values = np.array(struct.unpack_from("<6f", data, o + 64), np.float64)
        scales = np.array(struct.unpack_from("<6f", data, o + 88), np.float64)
        v = _first_frame(data, anim_at, k, values, scales)
        loc = np.eye(4)
        loc[:3, :3] = _angle_matrix(v[3:6])
        loc[:3, 3] = v[:3]
        mats[k] = mats[parent] @ loc if 0 <= parent < k else loc
    m.bones = mats
    # body parts -> models -> meshes -> triangles
    nbp, bpi = struct.unpack_from("<2i", data, 204)
    for b in range(max(nbp, 0)):
        o = bpi + 76 * b
        nmod, base, modi = struct.unpack_from("<3i", data, o + 64)
        models = []
        for j in range(max(nmod, 0)):
            mo = modi + 112 * j
            nmesh, meshi, nverts, vinfo, vindex = struct.unpack_from("<5i", data, mo + 72)
            if nverts <= 0:
                models.append([])
                continue
            vb = np.frombuffer(data, np.uint8, nverts, vinfo).astype(np.int64)
            vv = np.frombuffer(data, np.float32, nverts * 3, vindex).reshape(nverts, 3).astype(np.float64)
            vb = np.clip(vb, 0, max(nb - 1, 0))
            if nb:
                M = mats[vb]
                vv = np.einsum("nij,nj->ni", M[:, :3, :3], vv) + M[:, :3, 3]
            meshes = []
            for q in range(max(nmesh, 0)):
                me = meshi + 20 * q
                ntris, trii, skinref = struct.unpack_from("<3i", data, me)
                tris = []
                p = trii
                while p + 2 <= len(data):
                    cnt = struct.unpack_from("<h", data, p)[0]
                    p += 2
                    if cnt == 0:
                        break
                    fan = cnt < 0
                    cnt = abs(cnt)
                    cmd = struct.unpack_from(f"<{4 * cnt}h", data, p)
                    p += 8 * cnt
                    ids = [(cmd[4 * i], cmd[4 * i + 2], cmd[4 * i + 3]) for i in range(cnt)]
                    for i in range(2, cnt):
                        if fan:
                            a, b_, c = ids[0], ids[i - 1], ids[i]
                        elif i % 2 == 0:
                            a, b_, c = ids[i - 2], ids[i - 1], ids[i]
                        else:
                            a, b_, c = ids[i - 1], ids[i - 2], ids[i]
                        if max(a[0], b_[0], c[0]) >= nverts:
                            continue
                        pts = vv[[a[0], b_[0], c[0]]]
                        st = [(a[1], a[2]), (b_[1], b_[2]), (c[1], c[2])]
                        tris.append((pts, st))
                meshes.append((skinref, tris))
            models.append(meshes)
        m.parts.append((max(base, 1), models))
    return m


PROP_CLASSES = ("cycler", "cycler_sprite", "env_model", "cycler_wreckage", "monster_furniture", "item_generic",
                "monster_generic", "env_sprite")


def entity_matrix(e: dict) -> np.ndarray:
    """Where a map's entity puts its model: origin and angles (pitch yaw roll; a studio model's pitch turns the other
    way), 4 x 4, model -> map."""
    o = np.zeros(3)
    ang = np.zeros(3)
    try:
        o = np.array([float(v) for v in e.get("origin", "0 0 0").split()[:3]])
    except ValueError:
        pass
    try:
        if "angles" in e:
            ang = np.array([float(v) for v in e["angles"].split()[:3]])
        elif "angle" in e:
            ang = np.array([0.0, float(e["angle"]), 0.0])
    except ValueError:
        pass
    pitch, yaw, roll = (math.radians(v) for v in ang)
    M = np.eye(4)
    M[:3, :3] = _angle_matrix((roll, -pitch, yaw))
    sc = 1.0
    try:
        sc = float(e.get("scale", 1.0)) or 1.0
    except ValueError:
        pass
    M[:3, :3] *= sc
    M[:3, 3] = o
    return M


def find_model(rel: str, roots) -> Optional[str]:
    """The file of a model the map names ("models/de_dust2_cs2/van.mdl") under one of ``roots`` (a mod folder like
    cstrike, or any folder: also looked for by its name only)."""
    rel = rel.replace("\\", "/").lstrip("/")
    for r in roots:
        if not r:
            continue
        for cand in (os.path.join(r, rel), os.path.join(r, os.path.basename(rel)),
                     os.path.join(r, "models", os.path.basename(rel))):
            if os.path.isfile(cand):
                return cand
        # case differences (a map made on Windows)
        d = os.path.join(r, os.path.dirname(rel))
        if os.path.isdir(d):
            want = os.path.basename(rel).lower()
            for f in os.listdir(d):
                if f.lower() == want:
                    return os.path.join(d, f)
    return None


def map_roots(bsp_path: str, extra=()) -> list:
    """Folders to look for the models of a map in: the mod folder over its maps folder (cstrike), the map's folder,
    and ``extra`` (the .wad folders, a folder the user gave)."""
    d = os.path.dirname(os.path.abspath(bsp_path))
    roots = [os.path.dirname(d), d]
    for x in extra or ():
        x = str(x).strip().strip('"')
        if x:
            roots.append(x if os.path.isdir(x) else os.path.dirname(x))
            roots.append(os.path.dirname(roots[-1]))
    seen, out = set(), []
    for r in roots:
        k = os.path.normcase(os.path.abspath(r))
        if k not in seen:
            seen.add(k)
            out.append(r)
    return out


@dataclass
class Prop:
    entity: dict
    model: StudioModel
    file: str
    matrix: np.ndarray
    tris: list                                               # [(texture index, points in the map (3, 3), uv (3, 2))]


def map_props(entities, roots) -> Tuple[List[Prop], List[str]]:
    """The studio models a map places: [Prop], [model files not found]."""
    cache: Dict[str, Optional[StudioModel]] = {}
    props, missing = [], []
    for e in entities:
        mdl = str(e.get("model", ""))
        if not mdl.lower().endswith(".mdl"):
            continue
        cls = e.get("classname", "").lower()
        if cls.startswith(("info_player", "hostage", "monster_scientist")):
            continue
        f = find_model(mdl, roots)
        if f is None:
            if mdl not in missing:
                missing.append(mdl)
            continue
        if f not in cache:
            try:
                cache[f] = load(f)
            except Exception:
                cache[f] = None
        m = cache[f]
        if m is None:
            continue
        try:
            body = int(float(e.get("body", 0)))
            skin = int(float(e.get("skin", 0)))
        except ValueError:
            body = skin = 0
        M = entity_matrix(e)
        tris = []
        for t, pts, uv in m.triangles(body, max(skin, 0)):
            tris.append((t, pts @ M[:3, :3].T + M[:3, 3], uv))
        if tris:
            props.append(Prop(e, m, f, M, tris))
    return props, missing
