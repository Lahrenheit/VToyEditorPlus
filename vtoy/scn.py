"""Scene (.scn, magic 'VTS1') reader / writer.

Differences from the original C# editor:
  * every module is kept in its original order (known ones are parsed lazily, unknown ones stay raw);
  * the module count is always recomputed when writing;
  * the descriptor size is recomputed, and any bytes after the last module are preserved.
"""
from __future__ import annotations

import os
import struct
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from .binutil import Reader, VStr, Writer


@dataclass
class ModuleRecord:
    object_name: str
    module_name: str            # e.g. "mp_CCar.dll"
    data: bytes = b""
    parsed: object = None       # typed module object (see modules.py) or None

    @property
    def clean_name(self) -> str:
        """Module type: the DLL name without extension.  A patched copy is named ``<type>@<tag>.dll`` (e.g.
        ``mp_Flag@mp_b_piratas.dll``) and still counts as ``<type>``."""
        return os.path.splitext(str(self.module_name).rstrip("\0"))[0].split("@")[0]

    def payload(self) -> bytes:
        if self.parsed is not None and hasattr(self.parsed, "to_bytes"):
            return self.parsed.to_bytes()
        return self.data


@dataclass
class Scene:
    path: str = ""
    main_object_name: str = ""
    main_module_name: str = ""
    map_name: str = ""
    heightmap_name: str = ""
    shadow_light_direction: Tuple[float, float, float] = (0.0, 0.0, -1.0)
    sky_texture: str = ""
    fog_color: Tuple[int, int, int] = (0, 0, 0)      # 0-255 RGB (kept as ints => lossless round trip)
    fog_near: float = 0.0
    fog_far: float = 0.0
    cam_near: float = 1.0
    cam_far: float = 1000.0
    ambient_music: str = ""
    desc_level: int = 10           # how many descriptor fields the file has (old 'Torrente el juego' scenes: 2 = map+heightmap)
    count_adjust: int = 0          # module count in the file minus the entries really present (old scenes)
    desc_tail: bytes = b""        # unknown bytes at the end of the descriptor, kept verbatim
    modules: List[ModuleRecord] = field(default_factory=list)
    has_terminator: bool = True  # final empty module entry (name sizes 0) counted in the module count
    trailer: bytes = b""        # bytes after the terminator (usually 4 zero bytes, sometimes more)

    # ---- helpers -----------------------------------------------------------------
    @property
    def fog_color_f(self):
        return tuple(c / 255.0 for c in self.fog_color)

    def modules_of(self, clean_name: str):
        return [m for m in self.modules if m.clean_name.lower() == clean_name.lower()]

    # ---- reading ------------------------------------------------------------------
    @classmethod
    def parse(cls, data: bytes, path: str = "") -> "Scene":
        r = Reader(data)
        if r.take(4) != b"VTS1":
            raise ValueError("not a VTS1 scene")
        s = cls(path=path)
        def rs(_key=None):
            return r.sized_string()

        n_modules = r.u32()
        s.main_object_name = rs("main_object")
        s.main_module_name = rs("main_module")
        descriptor_size = r.u32()
        desc_start = r.o
        dr = Reader(r.take(descriptor_size))
        steps = [
            lambda: setattr(s, "map_name", dr.sized_string()),
            lambda: setattr(s, "heightmap_name", dr.sized_string()),
            lambda: setattr(s, "shadow_light_direction", dr.vec3()),
            lambda: setattr(s, "sky_texture", dr.sized_string()),
            lambda: setattr(s, "fog_color", ((lambda v: ((v >> 16) & 0xFF, (v >> 8) & 0xFF, v & 0xFF))(dr.u32()))),
            lambda: setattr(s, "fog_near", dr.f32()),
            lambda: setattr(s, "fog_far", dr.f32()),
            lambda: setattr(s, "cam_near", dr.f32()),
            lambda: setattr(s, "cam_far", dr.f32()),
            lambda: setattr(s, "ambient_music", dr.sized_string()),
        ]
        s.desc_level = 0
        for step in steps:
            mark = dr.o
            try:
                step()
            except EOFError:
                dr.o = mark
                break
            s.desc_level += 1
        s.desc_tail = dr.data[dr.o:]
        s.descriptor_size_in_file = descriptor_size
        s.descriptor_size_parsed = dr.o
        for _ in range(n_modules):
            mark = r.o
            try:
                obj = r.sized_string()
                mod = r.sized_string()
                size = r.u32()
                ok = size <= r.remaining and (not mod or str(mod).lower().endswith(".dll"))
                if not ok:
                    raise EOFError("not a module entry")
                s.modules.append(ModuleRecord(obj, mod, r.take(size)))
            except (EOFError, ValueError, struct.error):
                r.o = mark        # older scenes: the counted terminator slot is missing and a data block follows
                break
        if s.modules and not s.modules[-1].module_name and not s.modules[-1].object_name and not s.modules[-1].data:
            s.modules.pop()
            s.has_terminator = True
        else:
            s.has_terminator = False
        s.count_adjust = n_modules - len(s.modules) - (1 if s.has_terminator else 0)
        s.trailer = data[r.o:]
        return s

    @classmethod
    def load(cls, path: str) -> "Scene":
        with open(path, "rb") as f:
            return cls.parse(f.read(), path)

    # ---- writing ------------------------------------------------------------------
    def to_bytes(self) -> bytes:
        def ws(w, text, _key=None, zero=False):
            w.sized_string(text)

        desc = Writer()
        r_, g_, b_ = self.fog_color
        writers = [
            lambda: desc.sized_string(self.map_name),
            lambda: desc.sized_string(self.heightmap_name),
            lambda: desc.vec3(self.shadow_light_direction),
            lambda: desc.sized_string(self.sky_texture),
            lambda: desc.u32((r_ << 16) | (g_ << 8) | b_),
            lambda: desc.f32(self.fog_near),
            lambda: desc.f32(self.fog_far),
            lambda: desc.f32(self.cam_near),
            lambda: desc.f32(self.cam_far),
            lambda: desc.sized_string(self.ambient_music),
        ]
        for fn in writers[:self.desc_level]:
            fn()
        desc.raw(self.desc_tail)

        w = Writer()
        w.raw(b"VTS1").u32(len(self.modules) + (1 if self.has_terminator else 0) + self.count_adjust)
        ws(w, self.main_object_name, "main_object"); ws(w, self.main_module_name, "main_module")
        w.u32(len(desc.buf))
        w.raw(desc.bytes())
        for m in self.modules:
            payload = m.payload()
            ws(w, m.object_name); ws(w, m.module_name)
            w.u32(len(payload)).raw(payload)
        if self.has_terminator:
            w.u32(0).u32(0).u32(0)   # empty object name, empty module name, no data
        w.raw(self.trailer)
        return w.bytes()

    def save(self, path: Optional[str] = None) -> None:
        path = path or self.path
        tmp = path + ".tmp"
        with open(tmp, "wb") as f:      # 'wb' truncates (the C# editor used OpenWrite and left stale tail bytes)
            f.write(self.to_bytes())
        os.replace(tmp, path)
