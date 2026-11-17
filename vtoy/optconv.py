"""Convert a map of *Torrente, el juego* ('VTOP') into the 'VTO1' layout Torrente Online writes.

Reference: the Online map ``mp_dm_comercial.opt`` is the old ``comercial.opt`` converted by the developers, so the rules were
derived by comparing both files:
    * meshes: same vertices / indices / material index; the old 'stride' field (a dumped pointer) becomes 0, material_id 0,
      vertices are stored per sub-mesh instead of shared blocks + remap tables;
    * collision boxes stored inside every mesh/prop (old) become one global list (mesh boxes first, then prop boxes);
    * hull polygons (hulls_count) are identical in both formats;
    * the sector tree keeps its records (matrix, extents, list of scene objects, list of hulls) and gets a third list
      with the collision boxes that touch the sector (+ one u32 per record layout change).
The box lists are rebuilt with an overlap test, a little more generous than the original tool's rule (an extra candidate in a
sector is harmless, a missing one would let the player cross a wall)."""
from __future__ import annotations

import struct
from typing import List, Tuple

import numpy as np

from .binutil import Writer
from .opt import VERTEX_DTYPE, Light, LightType, OptMap


def _polys_size(raw: bytes, n: int) -> int:
    pos = 0
    for _ in range(n):
        k = struct.unpack_from("<I", raw, pos)[0]
        pos += 4 + 12 * k
    return pos


def _parse_old_sectors(buf: bytes, count: int):
    out, pos = [], 0
    for _ in range(count):
        head = buf[pos:pos + 76]
        pos += 76
        ls = []
        for _ in range(2):
            k = struct.unpack_from("<I", buf, pos)[0]
            ls.append(list(struct.unpack_from("<%dI" % k, buf, pos + 4)))
            pos += 4 + 4 * k
        y = struct.unpack_from("<I", buf, pos)[0]
        pos += 4
        out.append((head, ls, y))
    if pos != len(buf):
        raise ValueError(f"sector block does not end where expected ({pos} != {len(buf)})")
    return out


def _box_extents(boxes):
    cen = np.array([b.transform[3, :3] for b in boxes], np.float64).reshape(-1, 3)
    half = np.array([(np.abs(b.transform[:3, :3]) * b.half_extents[:, None]).sum(0) for b in boxes], np.float64).reshape(-1, 3)
    return cen, half


def convert(m: OptMap) -> OptMap:
    """Return ``m`` converted in place to the VTO1 layout (does nothing if it already is VTO1)."""
    if not m.old_format:
        return m
    boxes = m.all_collision_boxes()
    # --- meshes
    for mesh in m.meshes:
        for lod in mesh.lods:
            for part in lod.parts:
                for sm in part.submeshes:
                    if sm.vertices is None or len(sm.vertices) == 0:
                        sm.vertices = np.zeros(0, VERTEX_DTYPE)
                    sm.stride_type = 0
                    sm.material_id = 0
                    sm.remap = None
                part.shared_vertices = None
        mesh.old_collision_boxes = []
    for p in m.props:
        p.old_collision_boxes = []
    # --- point lights: radius -> [start, end]
    for l in m.lights:
        if l.type == LightType.POINT:
            l.start, l.end = 0.0, l.radius
    # --- sectors / hulls
    if m.hulls_count:
        psize = _polys_size(m.hulls_raw, m.hulls_count)
        polys, sec_buf = m.hulls_raw[:psize], m.hulls_raw[psize:]
    else:
        polys, sec_buf = b"", m.trailer
    sectors = _parse_old_sectors(sec_buf, m.unused) if m.unused else []
    cen, half = _box_extents(boxes)
    w = Writer()
    for head, (objs, hulls), y in sectors:
        c = np.frombuffer(head, "<f4", 16)[12:15].astype(np.float64)
        e = np.frombuffer(head, "<f4", 3, 64).astype(np.float64) * 2.0
        hit = []
        if len(boxes):
            mask = (np.abs(cen[:, 0] - c[0]) <= e[0] + half[:, 0]) & (np.abs(cen[:, 2] - c[2]) <= e[2] + half[:, 2])
            hit = [int(i) for i in np.where(mask)[0]]
        w.raw(head)
        for lst in (objs, hulls, hit):
            w.u32(len(lst))
            for i in lst:
                w.u32(i)
        w.u32(y)
    sect_bytes = w.bytes()
    bw = Writer()
    for b in boxes:
        bw.mat4(b.transform).vec3(b.half_extents)
    m.old_format = False
    if m.hulls_count:
        m.hulls_raw = polys + bw.bytes() + sect_bytes
        m.declared_box_count = len(boxes)
        m.collision_boxes = []
        m.trailer = b""
    else:
        m.collision_boxes = list(boxes)
        m.trailer = sect_bytes
    return m
