"""Reading Half-Life / Counter-Strike 1.6 maps (.bsp version 30): the faces that are drawn (with their texture name and
texture coordinates) and the entities (where players start, ...).  Units: 1 = 1 inch (2.54 cm), Z up.

    BspMap.load(path) -> .faces [BspFace(points (n,3), normal, texture, uv (n,2), model)], .entities [dict], .textures
"""
from __future__ import annotations

import re
import struct
from dataclasses import dataclass, field
from typing import Dict, List

import numpy as np

LUMPS = ("entities", "planes", "textures", "vertices", "visibility", "nodes", "texinfo", "faces", "lighting", "clipnodes",
         "leaves", "marksurfaces", "edges", "surfedges", "models")


@dataclass(eq=False)
class BspFace:
    points: np.ndarray
    normal: np.ndarray
    texture: str
    uv: np.ndarray            # texture coordinates (0..1 = one repeat of the texture)
    model: int = 0            # 0 = the world; others = brush entities (func_wall, func_door ...)


@dataclass(eq=False)
class BspMap:
    faces: List[BspFace] = field(default_factory=list)
    entities: List[Dict[str, str]] = field(default_factory=list)
    textures: Dict[str, tuple] = field(default_factory=dict)     # name -> (width, height)
    raw: bytes = b""
    models: List[tuple] = field(default_factory=list)            # (mins (3,), maxs (3,)) of each model (0 = world)

    def entity_model(self, e: Dict[str, str]):
        """(mins, maxs) of the brush model of a brush entity ("model": "*N"), or None."""
        m = e.get("model", "")
        if m.startswith("*") and m[1:].isdigit() and int(m[1:]) < len(self.models):
            return self.models[int(m[1:])]
        return None

    @classmethod
    def load(cls, path: str) -> "BspMap":
        return cls.parse(open(path, "rb").read())

    @classmethod
    def parse(cls, data: bytes) -> "BspMap":
        version = struct.unpack_from("<i", data, 0)[0]
        if version != 30:
            raise ValueError(f"not a Half-Life .bsp (version {version}, 30 expected)")
        lump = {}
        for i, name in enumerate(LUMPS):
            off, ln = struct.unpack_from("<ii", data, 4 + 8 * i)
            lump[name] = data[off:off + ln]
        planes = np.frombuffer(lump["planes"], np.dtype([("n", "<f4", 3), ("d", "<f4"), ("t", "<i4")]))
        verts = np.frombuffer(lump["vertices"], "<f4").reshape(-1, 3).astype(np.float64)
        edges = np.frombuffer(lump["edges"], "<u2").reshape(-1, 2)
        surfedges = np.frombuffer(lump["surfedges"], "<i4")
        texinfo = np.frombuffer(lump["texinfo"], np.dtype([("s", "<f4", 4), ("t", "<f4", 4), ("mip", "<i4"), ("flags", "<i4")]))
        # textures
        tl = lump["textures"]
        n_tex = struct.unpack_from("<i", tl, 0)[0]
        tex_names, tex_size = [], []
        for k in range(n_tex):
            o = struct.unpack_from("<i", tl, 4 + 4 * k)[0]
            if o < 0:
                tex_names.append(""); tex_size.append((64, 64)); continue
            name = tl[o:o + 16].split(b"\0")[0].decode("latin-1")
            w, h = struct.unpack_from("<II", tl, o + 16)
            tex_names.append(name); tex_size.append((w, h))
        faces_dt = np.dtype([("plane", "<u2"), ("side", "<u2"), ("first", "<i4"), ("n", "<u2"), ("ti", "<u2"),
                             ("styles", "u1", 4), ("light", "<i4")])
        faces = np.frombuffer(lump["faces"], faces_dt)
        models = np.frombuffer(lump["models"], np.dtype([("mins", "<f4", 3), ("maxs", "<f4", 3), ("origin", "<f4", 3),
                                                        ("head", "<i4", 4), ("vis", "<i4"), ("first", "<i4"), ("n", "<i4")]))
        owner = np.zeros(len(faces), np.int32)
        for mi, m in enumerate(models):
            owner[m["first"]:m["first"] + m["n"]] = mi
        out = cls()
        out.raw = data
        out.textures = {n: s for n, s in zip(tex_names, tex_size) if n}
        out.models = [(m["mins"].astype(np.float64), m["maxs"].astype(np.float64)) for m in models]
        for fi, f in enumerate(faces):
            idx = []
            for k in range(f["n"]):
                se = int(surfedges[f["first"] + k])
                e = edges[abs(se)]
                idx.append(int(e[0]) if se >= 0 else int(e[1]))
            pts = verts[idx]
            pl = planes[f["plane"]]
            n = pl["n"].astype(np.float64) * (-1.0 if f["side"] else 1.0)
            ti = texinfo[f["ti"]]
            mip = int(ti["mip"])
            name = tex_names[mip] if 0 <= mip < len(tex_names) else ""
            w, h = tex_size[mip] if 0 <= mip < len(tex_size) else (64, 64)
            s, t = ti["s"].astype(np.float64), ti["t"].astype(np.float64)
            uv = np.stack([(pts @ s[:3] + s[3]) / max(w, 1), (pts @ t[:3] + t[3]) / max(h, 1)], 1)
            out.faces.append(BspFace(pts, n, name, uv, int(owner[fi])))
        # entities
        text = lump["entities"].decode("latin-1", "replace")
        for block in re.findall(r"\{([^{}]*)\}", text):
            out.entities.append(dict(re.findall(r'"([^"]*)"\s+"([^"]*)"', block)))
        return out
