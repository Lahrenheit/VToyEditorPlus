"""Model files (.nfo, magic 'VTFF') used by RenderNFO / AnimatedRenderNFO / mp_CCar ...

The file is a tree of chunks ``tag(4) | u32 size (INCLUDING the 8 byte header) | payload``.  ``Chunk`` keeps the tree
verbatim (so unmodified files are written back byte-for-byte); ``Nfo`` adds typed views on top:

    VTFF ─ INFO                       version stuff
         ├ OBJ1 ─ INFO                6 x u32 + 4x4 object matrix
         │      ├ MTR1 ─ CSTR(name) INFO CSTR(texture, e.g. "foo.bmp" -> texs/foo.tex)
         │      ├ TRA1 ─ CSTR(name) INFO(4x4 matrix, parent index)      (bones / dummy nodes, absolute bind pose)
         │      ├ LOD1 ─ INFO(float distance, u32 n_meshes)
         │      │      └ MSH1 ─ INFO(10 x i32 header, positions, uvs, normals, per triangle data, bbox)
         │      │             ├ STP1 ─ INFO   one polygon (material, corner count, (pos,uv,normal) per corner)
         │      │             └ ZTR1          bone influence list: bone u32, n u32, n x vertex u32, u32, [n x weight f32]
         │      └ BOX1                      u32 u32 + 8 corners
         └ LHT1 ─ INFO                lighting data (kept raw)
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import numpy as np

from .binutil import Reader, Writer

CONTAINERS = {b"VTFF", b"OBJ1", b"MTR1", b"TRA1", b"LOD1", b"MSH1", b"STP1", b"LHT1"}


# ------------------------------------------------------------------------------------------ chunk tree
@dataclass
class Chunk:
    tag: bytes
    data: bytes = b""                                   # leaf payload
    children: Optional[List["Chunk"]] = None            # container payload

    @property
    def name(self) -> str:
        return self.tag.decode("latin-1")

    def find(self, tag: str) -> List["Chunk"]:
        t = tag.encode()
        return [c for c in (self.children or []) if c.tag == t]

    def first(self, tag: str) -> Optional["Chunk"]:
        r = self.find(tag)
        return r[0] if r else None

    def payload(self) -> bytes:
        if self.children is not None:
            return b"".join(c.to_bytes() for c in self.children)
        return self.data

    def to_bytes(self) -> bytes:
        p = self.payload()
        return self.tag + struct.pack("<I", len(p) + 8) + p

    @classmethod
    def parse(cls, data: bytes, o: int = 0, end: Optional[int] = None):
        end = len(data) if end is None else end
        tag = data[o:o + 4]
        size = struct.unpack_from("<I", data, o + 4)[0]
        if size < 8 or o + size > end:
            raise ValueError(f"bad chunk {tag!r} size {size} at {o}")
        if tag in CONTAINERS:
            kids, p = [], o + 8
            while p < o + size:
                c, p = cls.parse(data, p, o + size)
                kids.append(c)
            return cls(tag, children=kids), o + size
        return cls(tag, data=data[o + 8:o + size]), o + size


def _cstr(c: Chunk) -> str:
    return c.data.split(b"\0", 1)[0].decode("latin-1")


def read_cstr_chunk(r: Reader) -> str:
    """Read a ``CSTR`` chunk (tag, u32 size incl. header, NUL terminated text) from a Reader and return the text."""
    if r.take(4) != b"CSTR":
        raise ValueError("expected CSTR chunk")
    size = r.u32()
    return r.take(size - 8).split(b"\0", 1)[0].decode("latin-1")


@dataclass
class Skin:
    """Bone influence of one ZTR1 block: ``vertex`` (position indices) are bound to ``bone`` with ``weight``."""
    bone: int
    vertex: np.ndarray
    weight: np.ndarray            # all ones for rigid (unweighted) bindings


# ------------------------------------------------------------------------------------------ typed views
@dataclass
class NfoMaterial:
    name: str
    texture: str                     # e.g. 'cc_crist.bmp'
    diffuse: Tuple[int, int, int, int]
    ambient: Tuple[int, int, int, int]
    specular: Tuple[int, int, int, int]
    power: float
    chunk: Chunk

    @property
    def texture_stem(self) -> str:
        return self.texture.rsplit(".", 1)[0] if "." in self.texture else self.texture


@dataclass
class NfoNode:
    name: str
    matrix: np.ndarray               # 4x4, row-vector convention, bind pose (absolute)
    parent: int
    chunk: Chunk


@dataclass
class NfoMesh:
    """One MSH1. Triangles index separate position / uv / normal arrays (OBJ style)."""
    header: Tuple[int, ...]
    positions: np.ndarray            # (nv,3)
    uvs: np.ndarray                  # (nuv,2)
    normals: np.ndarray              # (nn,3)
    tri_material: np.ndarray         # (nt,)  index into the object's materials
    tri_pos: np.ndarray              # (nt,3)
    tri_uv: np.ndarray               # (nt,3)
    tri_nrm: np.ndarray              # (nt,3)
    bbox: np.ndarray                 # (6,) min xyz, max xyz
    skin: List[Skin]
    chunk: Chunk

    @property
    def node_index(self) -> int:
        return self.header[1]

    def build(self):
        """Per material draw groups: yields ``(material_index, vertices, indices, src_pos)`` where vertices is a float32
        (n, 8) array ``pos3 nrm3 uv2``, indices a flat uint32 array local to the group and src_pos the original position
        index of every vertex (useful for skinning)."""
        verts, idx, tmat, src = self.build_all()
        if len(idx) == 0:
            return
        tri = idx.reshape(-1, 3)
        for m in np.unique(tmat):
            t = tri[tmat == m]
            used, inv = np.unique(t.ravel(), return_inverse=True)
            yield int(m), verts[used], inv.astype(np.uint32), src[used]

    def build_all(self):
        """Merge the three index streams into one indexed vertex buffer.

        Returns (vertices float32 (n,8) = pos3 nrm3 uv2, indices uint32 (nt*3,), tri_material (nt,), src_pos (n,) the
        original position index of every merged vertex – handy for skinning)."""
        if len(self.tri_pos) == 0:
            return np.zeros((0, 8), np.float32), np.zeros(0, np.uint32), self.tri_material, np.zeros(0, np.int64)
        key = np.stack([self.tri_pos.ravel(), self.tri_uv.ravel(), self.tri_nrm.ravel()], 1)
        uniq, inv = np.unique(key, axis=0, return_inverse=True)
        verts = np.concatenate([self.positions[uniq[:, 0]], self.normals[uniq[:, 2]], self.uvs[uniq[:, 1]]], 1)
        return verts.astype(np.float32), inv.reshape(-1).astype(np.uint32), self.tri_material, uniq[:, 0].astype(np.int64)

    def skin_weights(self, n_bones: int):
        """Dense per-position bone weights: (nv, k) bone ids and (nv, k) weights, k <= 4 strongest influences."""
        nv = len(self.positions)
        acc: List[dict] = [dict() for _ in range(nv)]
        for sk in self.skin:
            for vi, wt in zip(sk.vertex, sk.weight):
                if vi < nv:
                    acc[vi][sk.bone] = acc[vi].get(sk.bone, 0.0) + float(wt)
        ids = np.zeros((nv, 4), np.int32)
        ws = np.zeros((nv, 4), np.float32)
        for vi, d in enumerate(acc):
            top = sorted(d.items(), key=lambda kv: -kv[1])[:4]
            tot = sum(v for _, v in top) or 1.0
            for k, (b, v) in enumerate(top):
                ids[vi, k], ws[vi, k] = b, v / tot
        return ids, ws


@dataclass
class NfoLod:
    distance: float
    meshes: List[NfoMesh]
    chunk: Chunk


@dataclass
class NfoObject:
    matrix: np.ndarray
    materials: List[NfoMaterial]
    nodes: List[NfoNode]
    lods: List[NfoLod]
    boxes: List[np.ndarray]          # each (8,3) corners
    chunk: Chunk

    def node_world(self, i: int) -> np.ndarray:
        return self.nodes[i].matrix


def _parse_mesh(c: Chunk) -> NfoMesh:
    info = c.first("INFO").data
    h = struct.unpack_from("<10i", info)
    nv, nuv, nn, nt = h[3], h[4], h[5], h[6]
    r = Reader(info, 40)
    pos = r.array("<f4", nv * 3).reshape(-1, 3)
    uvs = r.array("<f4", nuv * 2).reshape(-1, 2)
    nrm = r.array("<f4", nn * 3).reshape(-1, 3)
    tm = r.array("<i4", nt)
    tp = r.array("<i4", nt * 3).reshape(-1, 3)
    tu = r.array("<i4", nt * 3).reshape(-1, 3)
    tn = r.array("<i4", nt * 3).reshape(-1, 3)
    bbox = r.array("<f4", 6)
    infl = []
    for z in c.find("ZTR1"):
        d = z.data
        if len(d) < 8:
            continue
        bone, cnt = struct.unpack_from("<2I", d)
        if len(d) == 8 + 8 * cnt + 4:
            idx = np.frombuffer(d, "<u4", cnt, 8)
            w = np.frombuffer(d, "<f4", cnt, 8 + 4 * cnt + 4)
            infl.append(Skin(bone, idx, w))
        elif len(d) == 8 + 4 * cnt + 4:
            infl.append(Skin(bone, np.frombuffer(d, "<u4", cnt, 8), np.ones(cnt, np.float32)))
        # other shapes are left untouched in the chunk tree
    return NfoMesh(h, pos, uvs, nrm, tm, tp, tu, tn, bbox, infl, c)


def _parse_object(c: Chunk) -> NfoObject:
    info = c.first("INFO").data
    mat = np.frombuffer(info, "<f4", 16, 24).reshape(4, 4).copy()
    materials, nodes, lods, boxes = [], [], [], []
    for m in c.find("MTR1"):
        names = [_cstr(x) for x in m.find("CSTR")]
        i = m.first("INFO").data
        cols = tuple(tuple(i[k * 4:k * 4 + 4]) for k in range(3))
        power = struct.unpack_from("<f", i, 16)[0] if len(i) >= 20 else 0.0
        materials.append(NfoMaterial(names[0] if names else "", names[1] if len(names) > 1 else "",
                                     cols[0], cols[1], cols[2], power, m))
    for t in c.find("TRA1"):
        i = t.first("INFO").data
        nodes.append(NfoNode(_cstr(t.first("CSTR")), np.frombuffer(i, "<f4", 16).reshape(4, 4).copy(),
                             struct.unpack_from("<i", i, 64)[0], t))
    for l in c.find("LOD1"):
        dist = struct.unpack_from("<f", l.first("INFO").data)[0]
        lods.append(NfoLod(dist, [_parse_mesh(x) for x in l.find("MSH1")], l))
    for b in c.find("BOX1"):
        boxes.append(np.frombuffer(b.data, "<f4", 24, 8).reshape(8, 3).copy())
    return NfoObject(mat, materials, nodes, lods, boxes, c)


@dataclass
class Nfo:
    root: Chunk
    objects: List[NfoObject] = field(default_factory=list)

    @classmethod
    def parse(cls, data: bytes) -> "Nfo":
        if data[:4] != b"VTFF":
            raise ValueError("not a VTFF model")
        root, end = Chunk.parse(data)
        if end != len(data):
            raise ValueError("trailing bytes after VTFF")
        return cls(root, [_parse_object(o) for o in root.find("OBJ1")])

    @classmethod
    def load(cls, path: str) -> "Nfo":
        with open(path, "rb") as f:
            return cls.parse(f.read())

    def to_bytes(self) -> bytes:
        return self.root.to_bytes()

    def save(self, path: str) -> None:
        with open(path, "wb") as f:
            f.write(self.to_bytes())

    # ------------------------------------------------------------------ convenience
    @property
    def main(self) -> NfoObject:
        return self.objects[0]

    def lod0_meshes(self):
        """Yield ``(object, mesh)`` for the highest detail level of every object."""
        for obj in self.objects:
            if obj.lods:
                for me in obj.lods[0].meshes:
                    yield obj, me

    def update_mesh(self, mesh: NfoMesh) -> None:
        """Re-encode a modified NfoMesh (positions / uvs / normals / triangle indices) into its chunk."""
        info = bytearray(mesh.chunk.first("INFO").data[:40])
        h = list(mesh.header)
        h[3], h[4], h[5], h[6] = len(mesh.positions), len(mesh.uvs), len(mesh.normals), len(mesh.tri_pos)
        info[:40] = struct.pack("<10i", *h)
        info += mesh.positions.astype("<f4").tobytes() + mesh.uvs.astype("<f4").tobytes() + mesh.normals.astype("<f4").tobytes()
        info += mesh.tri_material.astype("<i4").tobytes() + mesh.tri_pos.astype("<i4").tobytes()
        info += mesh.tri_uv.astype("<i4").tobytes() + mesh.tri_nrm.astype("<i4").tobytes() + mesh.bbox.astype("<f4").tobytes()
        mesh.chunk.first("INFO").data = bytes(info)
        mesh.header = tuple(h)

    def export_obj(self, path: str, lod: int = 0) -> None:
        """Wavefront OBJ export of one LOD (handy to inspect a model in Blender)."""
        lines, vo, to, no = [], 0, 0, 0
        for obj in self.objects:
            if lod >= len(obj.lods):
                continue
            for k, m in enumerate(obj.lods[lod].meshes):
                lines.append(f"o mesh_{k}")
                lines += [f"v {x:.5f} {y:.5f} {-z:.5f}" for x, y, z in m.positions]
                lines += [f"vt {u:.5f} {1 - v:.5f}" for u, v in m.uvs]
                lines += [f"vn {x:.5f} {y:.5f} {-z:.5f}" for x, y, z in m.normals]
                for (a, b, c), (ta, tb, tc), (na, nb, nc) in zip(m.tri_pos, m.tri_uv, m.tri_nrm):
                    lines.append("f " + " ".join(f"{p + vo + 1}/{t + to + 1}/{n + no + 1}"
                                                 for p, t, n in ((a, ta, na), (c, tc, nc), (b, tb, nb))))
                vo, to, no = vo + len(m.positions), to + len(m.uvs), no + len(m.normals)
        with open(path, "w") as f:
            f.write("\n".join(lines) + "\n")


NfoModel = Nfo     # name used by GameFS / the viewer
