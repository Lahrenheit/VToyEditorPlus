"""Height map / floor collision (.hm, magic 'VTHM'): a quadtree of sectors, each holding floor faces (plane + contours)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np

from .binutil import Reader, Writer


@dataclass(eq=False)   # identity: comparing two of them must never compare numpy arrays (crashed the editor)
class HMFace:
    normal: tuple = (0.0, 1.0, 0.0)
    distance: float = 0.0
    contours: List[np.ndarray] = field(default_factory=list)     # each (n,3) float32


@dataclass(eq=False)   # identity: comparing two of them must never compare numpy arrays (crashed the editor)
class HMSector:
    x_min: float = 0.0
    x_max: float = 0.0
    z_min: float = 0.0
    z_max: float = 0.0
    faces: List[HMFace] = field(default_factory=list)
    children: Optional[List["HMSector"]] = None                  # 4 children or None

    def walk(self):
        yield self
        for c in self.children or ():
            yield from c.walk()


@dataclass(eq=False)   # identity: comparing two of them must never compare numpy arrays (crashed the editor)
class HeightMap:
    root: HMSector = field(default_factory=HMSector)

    @classmethod
    def parse(cls, data: bytes) -> "HeightMap":
        r = Reader(data)
        if r.take(4) != b"VTHM":
            raise ValueError("not a VTHM height map")
        hm = cls(_read_sector(r))
        if not r.eof():
            raise ValueError(f"{r.remaining} unexpected bytes after height map")
        return hm

    @classmethod
    def load(cls, path: str) -> "HeightMap":
        with open(path, "rb") as f:
            return cls.parse(f.read())

    def to_bytes(self) -> bytes:
        w = Writer().raw(b"VTHM")
        _write_sector(w, self.root)
        return w.bytes()

    def save(self, path: str) -> None:
        with open(path, "wb") as f:
            f.write(self.to_bytes())

    def triangles(self):
        """All floor faces as a flat (n,3,3) triangle fan list (for visualisation)."""
        tris = []
        for sec in self.root.walk():
            for face in sec.faces:
                for c in face.contours:
                    for i in range(1, len(c) - 1):
                        tris.append((c[0], c[i], c[i + 1]))
        return np.array(tris, np.float32).reshape(-1, 3, 3)


def _read_sector(r: Reader) -> HMSector:
    s = HMSector(r.f32(), r.f32(), r.f32(), r.f32())
    for _ in range(r.u32()):
        n = np.array(r.vec3(), np.float32)
        f = HMFace(tuple(n), r.f32())
        for _ in range(r.u32()):
            f.contours.append(r.array("<f4", r.u32() * 3).reshape(-1, 3))
        s.faces.append(f)
    n_children = r.u32()                       # always 4 (quadtree) or 0
    if n_children:
        s.children = [_read_sector(r) for _ in range(n_children)]
    return s


def _write_sector(w: Writer, s: HMSector) -> None:
    w.f32(s.x_min).f32(s.x_max).f32(s.z_min).f32(s.z_max).u32(len(s.faces))
    for f in s.faces:
        w.vec3(f.normal).f32(f.distance).u32(len(f.contours))
        for c in f.contours:
            w.u32(len(c)).raw(np.asarray(c, "<f4").tobytes())
    if s.children:
        w.u32(len(s.children))
        for c in s.children:
            _write_sector(w, c)
    else:
        w.u32(0)
