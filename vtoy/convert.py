"""Convert a scene of *Torrente, el juego* into a scene for *Torrente Online*.

What is carried over
    * the level (.opt + .hm) and every texture it uses (TeX1 -> TeX2), through ``Importer`` (nothing of Online is overwritten);
    * RenderNFO / AnimatedRenderNFO modules (same payload layout in both games) with their models, textures and
      animation (.KEY) files;
    * CCar -> mp_CCar (cars), salud -> mp_salud (health packs), SoundSource -> mp_SoundSource;
    * "decoration" modules of the old engine that only hold a model + matrix (PhysicsModel, Obstaculo_*, CommonItem...)
      become static RenderNFO modules (no physics, no scripts);
    * the player module (CTorrente) gives the place where the start points and the camera start are put.
What is NOT carried over: enemies, pedestrians, dogs, weapons, ammo, physics/scripts, the old level DLL logic. Those modules
belong to the old game's code and do not exist in Online; they are listed in the report.
The result is a plain Online "deathMatch" scene you can keep decorating in the editor."""
from __future__ import annotations

import copy
import os
import re
import struct
from collections import Counter
from typing import Callable, List, Optional

import numpy as np

from . import catalog, legacy
from .binutil import Reader, VStr
from .importer import Importer, Library, Report, _stem
from .modules import MODULE_TYPES, MPStartPoint
from .scn import ModuleRecord, Scene

# Online RenderNFO without animation: 10 bytes + 12 zeros (22 bytes). The old game used a 19 byte tail that Online's mp_*.dll do not read (crash).
RENDERNFO_TAIL = bytes.fromhex("01000000000100000000") + b"\0" * 12
CCAR_TAIL = bytes.fromhex("0100000000010000000000000000000000000000")[:22].ljust(22, b"\0")
MODEL_ONLY = {"physicsmodel", "obstaculo_1", "obstaculo_2", "obstaculo_3", "commonitem", "tuberia", "rollito",
              "rollitocomercial", "palo", "bate", "maletin", "dinero"}
DROPPED_NOTE = "no Online equivalent (old-game code)"


def _vstr(text: str) -> VStr:
    return VStr((text + "\0").encode("cp1252", "replace"))


def _model_and_matrix(data: bytes, offset: int = 0):
    r = Reader(data, offset)
    return r.sized_string(), r.mat4()


def _rewrite_key_ref(tail: bytes, new_rel: str) -> bytes:
    """Replace the animation path stored (as a sized string) in a RenderNFO tail by ``new_rel``."""
    m = re.search(rb"([\w\\/. \-]+?\.key)\x00", tail, re.I)
    if not m:
        return tail
    old_len_pos = m.start(1) - 4
    new = new_rel.replace("/", "\\").encode("cp1252") + b"\0"
    return tail[:old_len_pos] + struct.pack("<I", len(new)) + new + tail[m.end():]


class Converter:
    def __init__(self, lib: Library, target_root: str, template: Scene, log: Callable[[str], None] = print):
        self.lib, self.root, self.template, self.log = lib, target_root, template, log
        self.imp = Importer(lib, target_root, log)
        self.dropped: Counter = Counter()
        self.converted: Counter = Counter()
        self.notes: List[str] = []

    # ---------------------------------------------------------------- helpers
    def _import_model(self, name: str) -> Optional[str]:
        real = self.lib.real_nfos_name(catalog.norm_model(name))
        if real is None:
            self.imp.report.missing.append(f"model {name}")
            return None
        return "nfos/" + self.imp.model(real)

    def _import_key(self, tail: bytes) -> bytes:
        m = re.search(rb"([\w\\/. \-]+?\.key)\x00", tail, re.I)
        if not m or not self.lib.dirs.get("keys"):
            return tail
        ref = m.group(1).decode("cp1252", "replace").replace("\\", "/")
        keys = {k.lower(): k for k in self.lib.keys()}
        real = keys.get(ref.lower())
        if real is None:
            self.imp.report.missing.append(f"animation {ref}")
            return tail
        with open(self.lib.path("keys", real), "rb") as f:
            new_rel = self.imp._write("keys", real, f.read())
        return _rewrite_key_ref(tail, new_rel) if new_rel != real else tail

    def _add(self, sc: Scene, kind: str, obj_name: str, model: str, matrix: np.ndarray, tail: Optional[bytes] = None):
        cls = MODULE_TYPES[kind.lower()]
        o = cls(model_name=model, transform=np.asarray(matrix, np.float32).copy())
        if tail is not None:
            o.tail = tail
        sc.modules.append(ModuleRecord(_vstr(obj_name), _vstr(cls.KIND + ".dll"), b"", o))
        self.converted[cls.KIND] += 1

    # ---------------------------------------------------------------- main entry
    def convert(self, scene_rel: str, new_name: str, mode: str = "DM") -> str:
        old = Scene.load(self.lib.path("scns", scene_rel))
        # 1) level
        exists = lambda n: self.lib.has_nfos_file(n)
        map_name = legacy.resolve_map(old, exists)
        real_map = self.lib.real_nfos_name(map_name)
        if real_map is None or not real_map.lower().endswith(".opt"):
            raise FileNotFoundError(f"level of {scene_rel} ('{old.map_name}') not found in the library")
        new_opt = self.imp.map(real_map, os.path.splitext(os.path.basename(new_name))[0])
        sc = copy.deepcopy(self.template)
        sc.modules = []
        from . import gamemode
        gamemode.set_mode(sc, mode)          # main module of the chosen game mode (DM / DMT / DO / B)
        sc.desc_level = 10
        sc.desc_tail = b""
        sc.map_name = "nfos\\" + new_opt.replace("/", "\\")
        hm = os.path.splitext(new_opt)[0] + ".hm"
        if os.path.exists(os.path.join(self.root, "nfos", hm)):
            sc.heightmap_name = "nfos\\" + hm.replace("/", "\\")
        player: Optional[np.ndarray] = None

        # 2) modules
        for rec in old.modules:
            kind = rec.clean_name.lower()
            name = str(rec.object_name).rstrip("\0")
            data = rec.data
            try:
                if kind in ("rendernfo", "animatedrendernfo"):
                    mn, mat = _model_and_matrix(data)
                    new_model = self._import_model(mn)
                    tail = self._import_key(data[4 + struct.unpack_from("<I", data, 0)[0] + 64:])
                    if b".key" not in tail.lower():
                        tail = RENDERNFO_TAIL
                    self._add(sc, "rendernfo" if kind == "rendernfo" else "animatedrendernfo", name, new_model or mn, mat, tail)
                elif kind == "ccar":
                    mn, mat = _model_and_matrix(data)
                    self._add(sc, "mp_ccar", name, self._import_model(mn) or mn, mat, CCAR_TAIL)
                elif kind == "salud":
                    from .modules import MPSalud
                    o = MPSalud.from_bytes(data)
                    o.model_name = self._import_model(o.model_name) or o.model_name
                    sc.modules.append(ModuleRecord(_vstr(name), _vstr("mp_salud.dll"), b"", o))
                    self.converted["mp_salud"] += 1
                elif kind == "soundsource":
                    sc.modules.append(ModuleRecord(_vstr(name), _vstr("mp_SoundSource.dll"), data, None))
                    self.converted["mp_SoundSource"] += 1
                elif kind == "ctorrente":
                    _, mat = _model_and_matrix(data)
                    player = np.asarray(mat, np.float64)[3, :3]
                elif kind in MODEL_ONLY:
                    off = 24 if kind == "physicsmodel" else 0
                    mn, mat = _model_and_matrix(data, off)
                    if not mn.lower().endswith(".nfo"):
                        raise ValueError("no model")
                    self._add(sc, "rendernfo", name, self._import_model(mn) or mn, mat, RENDERNFO_TAIL)
                    self.converted["(static decoration from " + rec.clean_name + ")"] += 1
                else:
                    self.dropped[rec.clean_name or "(unnamed)"] += 1
            except Exception as e:                                 # a module we cannot read is reported, not fatal
                self.dropped[f"{rec.clean_name} (unreadable: {type(e).__name__})"] += 1

        # 3) start points + camera + what the chosen mode needs
        if player is None:
            self.notes.append("no player module found: start points were put at the map origin; move them in the editor")
        centre = player if player is not None else np.zeros(3)
        tpl = gamemode.Templates(os.path.join(self.root, "scns"))
        self.notes += gamemode.populate(sc, tpl, centre, mode)
        if not new_name.lower().endswith(".scn"):
            new_name += ".scn"
        path = os.path.join(self.root, "scns", new_name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        sc.path = path
        sc.save(path)
        return new_name

    @staticmethod
    def _camera_payload(centre: np.ndarray) -> bytes:
        """Online's mp_CameraStartPosition = eye (3 floats) + point looked at (3 floats)."""
        eye = centre + [0, 600, 900]
        return struct.pack("<6f", *eye, *centre)

    def summary(self) -> str:
        lines = [self.imp.report.summary()]
        lines.append("converted: " + ", ".join(f"{v} {k}" for k, v in self.converted.most_common()))
        if self.dropped:
            lines.append(f"not converted ({DROPPED_NOTE}): " + ", ".join(f"{v} {k}" for k, v in self.dropped.most_common()))
        lines += self.notes
        if self.imp.report.missing:
            lines.append("missing in the library: " + ", ".join(sorted(set(self.imp.report.missing))[:12]))
        return "\n".join(lines)
