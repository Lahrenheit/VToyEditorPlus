"""Map geometry (.opt) reader / writer. Two on-disk versions exist: 'VTOP' (old, Torrente 1) and 'VTO1' (Torrente Online).

Everything is parsed into real objects (meshes, props, decals, lights, collision boxes) and can be written back;
unknown fields are kept verbatim so an untouched map is byte-identical after a load/save cycle.
"""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import List, Optional

import numpy as np

from .binutil import Reader, VStr, Writer

VERTEX_DTYPE = np.dtype([("pos", "<f4", 3), ("nrm", "<f4", 3), ("uv", "<f4", 2)])
VERTEX2_DTYPE = np.dtype([("pos", "<f4", 3), ("nrm", "<f4", 3), ("uv", "<f4", 2), ("uv2", "<f4", 2)])


# the colour block of almost every material of the shipped maps (ambient 1, diffuse 0.68, specular 1, emissive 0):
# a block of zeros makes the game draw the mesh black, whatever the lights
STOCK_MATERIAL = bytes.fromhex("0000803f0000803f0000803f0000803f7b142e3f7b142e3f7b142e3f0000803f"
                               "0000803f0000803f0000803f0000803f00000000000000000000000000000000")


class LightType(enum.IntEnum):
    POINT = 0
    SPOT = 1
    DIRECTIONAL = 2
    AMBIENT = 3


@dataclass(eq=False)   # identity: comparing two of them must never compare numpy arrays (crashed the editor)
class Material:
    name: str = ""
    textures: List[str] = field(default_factory=list)   # [0] is the diffuse texture
    two_sided: bool = False
    uv_map: bytes = b"\0" * 64                           # 4x vec4 (texture transform), kept raw
    unk_float: float = 0.0

    @property
    def diffuse(self) -> str:
        return str(self.textures[0]) if self.textures else ""


@dataclass(eq=False)   # identity: comparing two of them must never compare numpy arrays (crashed the editor)
class SubMesh:
    stride_type: int = 0
    material_id: int = 0          # only in VTO1
    material_index: int = 0
    unk: int = 0
    vertices: np.ndarray = None   # structured array (VERTEX_DTYPE / VERTEX2_DTYPE)
    indices: np.ndarray = None    # uint16, shape (n_tris*3,)
    remap: Optional[np.ndarray] = None   # only in VTOP: maps local vertex -> shared vertex block of the mesh part


@dataclass(eq=False)   # identity: comparing two of them must never compare numpy arrays (crashed the editor)
class MeshPart:
    active: bool = True
    corners: bytes = b"\0" * 96
    shared_vertices: Optional[np.ndarray] = None   # VTOP only
    submeshes: List[SubMesh] = field(default_factory=list)


@dataclass(eq=False)   # identity: comparing two of them must never compare numpy arrays (crashed the editor)
class Lod:
    unk: int = 0
    parts: List[MeshPart] = field(default_factory=list)


@dataclass(eq=False)   # identity: comparing two of them must never compare numpy arrays (crashed the editor)
class CollisionBox:
    transform: np.ndarray = field(default_factory=lambda: np.eye(4, dtype=np.float32))
    half_extents: np.ndarray = field(default_factory=lambda: np.ones(3, dtype=np.float32))


@dataclass(eq=False)   # identity: comparing two of them must never compare numpy arrays (crashed the editor)
class StaticMesh:
    materials: List[Material] = field(default_factory=list)
    lods: List[Lod] = field(default_factory=list)
    old_collision_boxes: List[CollisionBox] = field(default_factory=list)   # VTOP only (stored inside the mesh)
    corners: np.ndarray = field(default_factory=lambda: np.zeros((8, 3), np.float32))
    world_transform: np.ndarray = field(default_factory=lambda: np.eye(4, dtype=np.float32))

    def render_submeshes(self):
        """(vertices, indices, material_index) for LOD 0 – what the game draws up close."""
        if not self.lods:
            return
        for part in self.lods[0].parts:
            for sm in part.submeshes:
                yield sm


@dataclass(eq=False)   # identity: comparing two of them must never compare numpy arrays (crashed the editor)
class Prop:
    mesh_index: int = 0
    transform: np.ndarray = field(default_factory=lambda: np.eye(4, dtype=np.float32))
    corners: np.ndarray = field(default_factory=lambda: np.zeros((8, 3), np.float32))
    old_collision_boxes: List[CollisionBox] = field(default_factory=list)   # VTOP only


@dataclass(eq=False)   # identity: comparing two of them must never compare numpy arrays (crashed the editor)
class Decal:
    name: str = ""
    position: np.ndarray = field(default_factory=lambda: np.zeros(3, np.float32))
    scale_x: float = 1.0
    scale_y: float = 1.0
    z_offset: float = 0.0


@dataclass(eq=False)   # identity: comparing two of them must never compare numpy arrays (crashed the editor)
class Light:
    type: LightType = LightType.POINT
    position: np.ndarray = field(default_factory=lambda: np.zeros(3, np.float32))
    direction: np.ndarray = field(default_factory=lambda: np.array([0, -1, 0], np.float32))
    radius: float = 0.0           # VTOP point light
    start: float = 0.0            # VTO1 point light
    end: float = 0.0
    cone: float = 0.0             # spot
    diffuse: tuple = (1, 1, 1, 1)
    ambient: tuple = (0, 0, 0, 1)
    specular: tuple = (0, 0, 0, 1)


@dataclass(eq=False)   # identity: comparing two of them must never compare numpy arrays (crashed the editor)
class OptMap:
    path: str = ""
    old_format: bool = False      # True => 'VTOP', False => 'VTO1'
    scene_obj_count: int = 0
    unused: int = 0
    meshes: List[StaticMesh] = field(default_factory=list)
    props: List[Prop] = field(default_factory=list)
    decals: List[Decal] = field(default_factory=list)
    lights: List[Light] = field(default_factory=list)
    hulls_count: int = 0
    hulls_raw: bytes = b""        # hull data is not decoded; kept verbatim (see notes in README)
    collision_boxes: List[CollisionBox] = field(default_factory=list)   # VTO1 global boxes
    declared_box_count: int = 0   # box count from the header (needed to rewrite maps whose hull block is kept raw)
    trailer: bytes = b""          # VTO1: sector/visibility records (counted by the header's 'unused' field), kept raw

    # ------------------------------------------------------------------------------------------
    @classmethod
    def load(cls, path: str) -> "OptMap":
        with open(path, "rb") as f:
            m = cls.parse(f.read())
        m.path = path
        return m

    @classmethod
    def parse(cls, data: bytes) -> "OptMap":
        r = Reader(data)
        magic = r.take(4)
        if magic not in (b"VTOP", b"VTO1"):
            raise ValueError(f"unknown map magic {magic!r}")
        m = cls(old_format=(magic == b"VTOP"))
        m.scene_obj_count = r.u32()
        n_mesh, n_prop, n_decal, n_light = r.u32(), r.u32(), r.u32(), r.u32()
        m.hulls_count = r.u32()
        n_box = 0 if m.old_format else r.u32()
        m.declared_box_count = n_box
        m.unused = r.u32()

        for _ in range(n_mesh):
            m.meshes.append(_read_mesh(r, m.old_format))
        for _ in range(n_prop):
            p = Prop(mesh_index=r.u32(), transform=r.mat4())
            p.corners = np.array([r.vec3() for _ in range(8)], np.float32)
            if m.old_format:
                p.old_collision_boxes = [_read_box(r) for _ in range(r.u32())]
            m.props.append(p)
        for _ in range(n_decal):
            name = r.sized_string()
            pos = np.array(r.vec3(), np.float32)
            m.decals.append(Decal(name, pos, r.f32(), r.f32(), r.f32()))
        for _ in range(n_light):
            m.lights.append(_read_light(r, m.old_format))
        # Hulls: format not decoded. In the files we have, hullsCount is always 0 (checked by tests).
        if m.hulls_count:
            m.hulls_raw = r.data[r.o:]
            r.o = len(r.data)
        else:
            m.collision_boxes = [_read_box(r) for _ in range(n_box)]
        m.trailer = r.data[r.o:]
        return m

    # ------------------------------------------------------------------------------------------
    def to_bytes(self) -> bytes:
        w = Writer()
        w.raw(b"VTOP" if self.old_format else b"VTO1")
        w.u32(self.scene_obj_count).u32(len(self.meshes)).u32(len(self.props)).u32(len(self.decals))
        w.u32(len(self.lights)).u32(self.hulls_count)
        if not self.old_format:
            w.u32(self.declared_box_count if self.hulls_count else len(self.collision_boxes))
        w.u32(self.unused)
        for mesh in self.meshes:
            _write_mesh(w, mesh, self.old_format)
        for p in self.props:
            w.u32(p.mesh_index).mat4(p.transform)
            w.raw(np.asarray(p.corners, "<f4").tobytes())
            if self.old_format:
                w.u32(len(p.old_collision_boxes))
                for b in p.old_collision_boxes:
                    _write_box(w, b)
        for d in self.decals:
            w.sized_string(d.name).vec3(d.position).f32(d.scale_x).f32(d.scale_y).f32(d.z_offset)
        for l in self.lights:
            _write_light(w, l, self.old_format)
        if self.hulls_count:
            w.raw(self.hulls_raw)
        else:
            for b in self.collision_boxes:
                _write_box(w, b)
        w.raw(self.trailer)
        return w.bytes()

    def save(self, path: Optional[str] = None) -> None:
        path = path or self.path
        with open(path, "wb") as f:
            f.write(self.to_bytes())

    # ------------------------------------------------------------------------------------------
    def all_collision_boxes(self):
        """Boxes in the order the game stores them (VTOP stores them per mesh/prop)."""
        if not self.old_format:
            return list(self.collision_boxes)
        out = []
        for me in self.meshes:
            out += me.old_collision_boxes
        for p in self.props:
            out += p.old_collision_boxes
        return out


# --------------------------------------------------------------------------------------------------
def _read_box(r: Reader) -> CollisionBox:
    return CollisionBox(r.mat4(), np.array(r.vec3(), np.float32))


def _write_box(w: Writer, b: CollisionBox) -> None:
    w.mat4(b.transform).vec3(b.half_extents)


def _read_mesh(r: Reader, old: bool) -> StaticMesh:
    mesh = StaticMesh()
    for _ in range(r.u32()):                               # materials
        mat = Material(name=r.sized_string())
        mat.textures = [r.sized_string() for _ in range(r.u32())]
        mat.two_sided = r.u8() != 0
        mat.uv_map = r.take(64)
        mat.unk_float = r.f32()
        mesh.materials.append(mat)
    for _ in range(r.u32()):                               # LODs
        lod = Lod(unk=r.u32())
        for _ in range(r.u32()):
            part = MeshPart(active=r.u8() != 0)
            shared_count = r.u32() if old else 0
            n_sub = r.u32()
            part.corners = r.take(96)
            if old and shared_count:
                part.shared_vertices = r.array(VERTEX_DTYPE, shared_count)
            for _ in range(n_sub):
                sm = SubMesh(stride_type=r.u32())
                if old:
                    sm.material_index = r.u32()
                    tri_count = r.u32()
                    vert_count = r.u32()
                    sm.unk = r.u32()
                    sm.remap = r.array("<u2", vert_count)
                    sm.indices = r.array("<u2", tri_count * 3)
                    if part.shared_vertices is not None and vert_count:
                        sm.vertices = part.shared_vertices[sm.remap]
                    else:
                        sm.vertices = np.zeros(0, VERTEX_DTYPE)
                else:
                    sm.material_id = r.u32()
                    sm.material_index = r.u32()
                    tri_count = r.u32()
                    vert_count = r.u32()
                    sm.unk = r.u32()
                    sm.indices = r.array("<u2", tri_count * 3)
                    sm.vertices = r.array(VERTEX2_DTYPE if sm.stride_type != 0 else VERTEX_DTYPE, vert_count)
                part_sub = sm
                part.submeshes.append(part_sub)
            lod.parts.append(part)
        mesh.lods.append(lod)
    if old:
        mesh.old_collision_boxes = [_read_box(r) for _ in range(r.u32())]
    mesh.corners = np.array([r.vec3() for _ in range(8)], np.float32)
    mesh.world_transform = r.mat4()
    return mesh


def _write_mesh(w: Writer, mesh: StaticMesh, old: bool) -> None:
    w.u32(len(mesh.materials))
    for mat in mesh.materials:
        w.sized_string(mat.name).u32(len(mat.textures))
        for t in mat.textures:
            w.sized_string(t)
        w.u8(1 if mat.two_sided else 0).raw(mat.uv_map).f32(mat.unk_float)
    w.u32(len(mesh.lods))
    for lod in mesh.lods:
        w.u32(lod.unk).u32(len(lod.parts))
        for part in lod.parts:
            w.u8(1 if part.active else 0)
            if old:
                w.u32(0 if part.shared_vertices is None else len(part.shared_vertices))
            w.u32(len(part.submeshes)).raw(part.corners)
            if old and part.shared_vertices is not None:
                w.raw(part.shared_vertices.astype(VERTEX_DTYPE, copy=False).tobytes())
            for sm in part.submeshes:
                w.u32(sm.stride_type)
                if old:
                    w.u32(sm.material_index).u32(len(sm.indices) // 3).u32(len(sm.remap)).u32(sm.unk)
                    w.raw(sm.remap.astype("<u2").tobytes()).raw(sm.indices.astype("<u2").tobytes())
                else:
                    w.u32(sm.material_id).u32(sm.material_index).u32(len(sm.indices) // 3).u32(len(sm.vertices)).u32(sm.unk)
                    w.raw(sm.indices.astype("<u2").tobytes())
                    w.raw(sm.vertices.tobytes())
    if old:
        w.u32(len(mesh.old_collision_boxes))
        for b in mesh.old_collision_boxes:
            _write_box(w, b)
    w.raw(np.asarray(mesh.corners, "<f4").tobytes()).mat4(mesh.world_transform)


def _read_light(r: Reader, old: bool) -> Light:
    l = Light(type=LightType(r.u32()))
    if l.type == LightType.POINT:
        l.position = np.array(r.vec3(), np.float32)
        if old:
            l.radius = r.f32()
        else:
            l.start, l.end = r.f32(), r.f32()
    elif l.type == LightType.SPOT:
        l.position = np.array(r.vec3(), np.float32)
        l.direction = np.array(r.vec3(), np.float32)
        l.cone = r.f32()
    elif l.type == LightType.DIRECTIONAL:
        l.direction = np.array(r.vec3(), np.float32)
    l.diffuse = tuple(r.f32() for _ in range(4))
    l.ambient = tuple(r.f32() for _ in range(4))
    l.specular = tuple(r.f32() for _ in range(4))
    return l


def _write_light(w: Writer, l: Light, old: bool) -> None:
    w.u32(int(l.type))
    if l.type == LightType.POINT:
        w.vec3(l.position)
        if old:
            w.f32(l.radius)
        else:
            w.f32(l.start).f32(l.end)
    elif l.type == LightType.SPOT:
        w.vec3(l.position).vec3(l.direction).f32(l.cone)
    elif l.type == LightType.DIRECTIONAL:
        w.vec3(l.direction)
    for col in (l.diffuse, l.ambient, l.specular):
        for c in col:
            w.f32(c)


def translate_mesh(mesh: StaticMesh, delta) -> None:
    """Move a static mesh by ``delta`` (engine coordinates): vertices, corner boxes and its world transform.

    Props that reference the mesh keep their world position because they are drawn with inverse(world_transform) first.
    VTOP collision boxes stored inside the mesh are moved too; the VTO1 sector block of the map is not recomputed."""
    d = np.asarray(delta, np.float32)

    def shift_corners(raw: bytes) -> bytes:
        return (np.frombuffer(raw, "<f4").reshape(8, 3) + d).astype("<f4").tobytes()

    for lod in mesh.lods:
        for part in lod.parts:
            part.corners = shift_corners(part.corners)
            if part.shared_vertices is not None:
                part.shared_vertices["pos"] += d
            for sm in part.submeshes:
                if part.shared_vertices is None and sm.vertices is not None and len(sm.vertices):
                    sm.vertices["pos"] += d
                elif sm.vertices is not None and len(sm.vertices):
                    sm.vertices = part.shared_vertices[sm.remap]
    mesh.corners = mesh.corners + d
    mesh.world_transform = mesh.world_transform.copy()
    mesh.world_transform[3, :3] += d
    for b in mesh.old_collision_boxes:
        b.transform = b.transform.copy()
        b.transform[3, :3] += d


def transform_mesh(mesh: StaticMesh, m3, centre) -> None:
    """Rotate / scale a static mesh in place: p' = (p - centre) @ m3 + centre (row-vector convention like the engine).
    Normals follow (re-normalised, which is exact for rotations and uniform scales). Props must not use the mesh."""
    m3 = np.asarray(m3, np.float64).reshape(3, 3)
    c = np.asarray(centre, np.float64)

    def pts(a):
        return (((np.asarray(a, np.float64) - c) @ m3) + c).astype(np.float32)

    for lod in mesh.lods:
        for part in lod.parts:
            part.corners = pts(np.frombuffer(part.corners, "<f4").reshape(8, 3)).astype("<f4").tobytes()
            for sm in part.submeshes:
                if sm.vertices is None or not len(sm.vertices):
                    continue
                sm.vertices["pos"] = pts(sm.vertices["pos"])
                n = np.asarray(sm.vertices["nrm"], np.float64) @ np.linalg.inv(m3).T
                ln = np.linalg.norm(n, axis=1, keepdims=True)
                sm.vertices["nrm"] = (n / np.maximum(ln, 1e-12)).astype(np.float32)
    mesh.corners = pts(mesh.corners)
    mesh.world_transform = mesh.world_transform.copy()
    mesh.world_transform[3, :3] = pts(mesh.world_transform[3, :3][None])[0]
