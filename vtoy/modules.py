"""Typed views of the scene modules (the "*.dll" entries of a .scn).

Every typed module can be built from the raw payload (`from_bytes`) and turned back into bytes (`to_bytes`).
Unparsed trailing bytes are kept in ``tail`` so an unmodified module round-trips byte-for-byte.
Modules that are not listed here stay as raw bytes inside the scene.
"""
from __future__ import annotations

import struct

import re
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple, Type

import numpy as np

from .binutil import Reader, VStr, Writer
from .scn import ModuleRecord, Scene

IDENTITY = np.eye(4, dtype=np.float32)


@dataclass(eq=False)   # identity: comparing two of them must never compare numpy arrays (crashed the editor)
class ModelModule:
    """Base for every module that starts with `[sized model name][4x4 matrix]` (RenderNFO, mp_CCar, mp_Door ...)."""

    model_name: str = ""
    transform: np.ndarray = field(default_factory=lambda: IDENTITY.copy())
    tail: bytes = b""

    KIND = "model"

    @classmethod
    def from_bytes(cls, data: bytes):
        r = Reader(data)
        name = r.sized_string()
        mat = r.mat4()
        obj = cls(model_name=name, transform=mat)
        obj._read_extra(r)
        return obj

    def _read_extra(self, r: Reader) -> None:
        self.tail = r.data[r.o:]

    def _write_extra(self, w: Writer) -> None:
        w.raw(self.tail)

    def to_bytes(self) -> bytes:
        w = Writer()
        w.sized_string(self.model_name).mat4(self.transform)
        self._write_extra(w)
        return w.bytes()

    # ---- convenience -----------------------------------------------------------------
    @property
    def position(self) -> np.ndarray:
        return self.transform[3, :3].copy()

    @position.setter
    def position(self, v) -> None:
        self.transform[3, :3] = np.asarray(v, np.float32)

    @property
    def key_name(self) -> Optional[str]:
        """Animation (.KEY) referenced in the tail of (Animated)RenderNFO-like modules, if any."""
        m = re.search(rb"([\w\\/. \-]+?\.key)\x00", self.tail, re.I)
        return m.group(1).decode("cp1252", "replace") if m else None


@dataclass(eq=False)   # identity: comparing two of them must never compare numpy arrays (crashed the editor)
class RenderNFO(ModelModule):
    KIND = "RenderNFO"


@dataclass(eq=False)   # identity: comparing two of them must never compare numpy arrays (crashed the editor)
class AnimatedRenderNFO(ModelModule):
    KIND = "AnimatedRenderNFO"


@dataclass(eq=False)   # identity: comparing two of them must never compare numpy arrays (crashed the editor)
class CGlass(ModelModule):
    KIND = "cglass"


@dataclass(eq=False)   # identity: comparing two of them must never compare numpy arrays (crashed the editor)
class MPDoor(ModelModule):
    KIND = "mp_Door"


@dataclass(eq=False)   # identity: comparing two of them must never compare numpy arrays (crashed the editor)
class MPCosa(ModelModule):
    KIND = "mp_Cosa"


@dataclass(eq=False)   # identity: comparing two of them must never compare numpy arrays (crashed the editor)
class MPCCar(ModelModule):
    KIND = "mp_CCar"


@dataclass(eq=False)   # identity: comparing two of them must never compare numpy arrays (crashed the editor)
class MPSalud(ModelModule):
    KIND = "mp_salud"
    unk_string1: str = ""
    unk_string2: str = ""
    health: int = 0

    def _read_extra(self, r: Reader) -> None:
        start = r.o
        try:
            self.unk_string1 = r.sized_string()
            self.unk_string2 = r.sized_string()
            self.health = r.i32()
            self.tail = r.data[r.o:]
        except EOFError:
            r.o = start
            self.unk_string1 = self.unk_string2 = ""
            self.health = 0
            self.tail = r.data[start:]
            self._raw_extra = True

    def _write_extra(self, w: Writer) -> None:
        if getattr(self, "_raw_extra", False):
            w.raw(self.tail)
            return
        w.sized_string(self.unk_string1).sized_string(self.unk_string2).i32(self.health).raw(self.tail)

    @property
    def effective_health(self) -> int:
        return 50 if self.health == 0 else self.health


@dataclass(eq=False)   # identity: comparing two of them must never compare numpy arrays (crashed the editor)
class MPFlag(ModelModule):
    KIND = "mp_Flag"
    unk_string1: str = ""
    unk_string2: str = ""
    team: int = 0

    def _read_extra(self, r: Reader) -> None:
        start = r.o
        try:
            self.unk_string1 = r.sized_string()
            self.unk_string2 = r.sized_string()
            self.team = r.u32()
            self.tail = r.data[r.o:]
        except EOFError:
            r.o = start
            self.tail = r.data[start:]
            self._raw_extra = True

    def _write_extra(self, w: Writer) -> None:
        if getattr(self, "_raw_extra", False):
            w.raw(self.tail)
            return
        w.sized_string(self.unk_string1).sized_string(self.unk_string2).u32(self.team).raw(self.tail)


@dataclass(eq=False)   # identity: comparing two of them must never compare numpy arrays (crashed the editor)
class MPStartPoint:
    KIND = "mp_CStartPoint"
    position: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    angle: float = 0.0           # radians
    team: int = 0
    order: int = 0
    tail: bytes = b""

    @classmethod
    def from_bytes(cls, data: bytes):
        r = Reader(data)
        o = cls(position=r.vec3(), angle=r.f32(), team=r.i32(), order=r.i32())
        o.tail = data[r.o:]
        return o

    def to_bytes(self) -> bytes:
        return Writer().vec3(self.position).f32(self.angle).i32(self.team).i32(self.order).raw(self.tail).bytes()

    @property
    def transform(self) -> np.ndarray:
        m = np.eye(4, dtype=np.float32)
        m[3, :3] = self.position
        return m


@dataclass(eq=False)   # identity: comparing two of them must never compare numpy arrays (crashed the editor)
class MPCameraStartPosition:
    """Spectator / intro camera: eye position + the point it looks at (engine coordinates)."""
    KIND = "mp_CameraStartPosition"
    position: Tuple[float, float, float] = (0.0, 500.0, 0.0)
    target: Tuple[float, float, float] = (0.0, 0.0, 500.0)
    tail: bytes = b""

    @classmethod
    def from_bytes(cls, data: bytes):
        v = struct.unpack_from("<6f", data, 0)
        return cls(tuple(v[:3]), tuple(v[3:]), data[24:])

    def to_bytes(self) -> bytes:
        return struct.pack("<6f", *self.position, *self.target) + self.tail


@dataclass(eq=False)   # identity: comparing two of them must never compare numpy arrays (crashed the editor)
class MPSoundSource:
    """3D sound: ``[wav name][flag u8][interval u32][position 3f][max distance][min distance]`` (engine coordinates).
    The helicopter of mp_dm_asalto uses ``wavs\\HELICOPTERO.wav`` with flag 0, interval 0, max 4448, min 25; the wind uses flag 1."""
    KIND = "mp_SoundSource"
    wav: str = "wavs\\HELICOPTERO.wav"
    loop: int = 0                # first byte of the settings (1 in the wind sources, 0 in the helicopter / animals / disco)
    interval: int = 0            # u32 after it (150 / 400 in the animals, 750 in the disco music: ticks between plays)
    position: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    max_distance: float = 4448.0
    min_distance: float = 25.0
    tail: bytes = b""

    @classmethod
    def from_bytes(cls, data: bytes):
        r = Reader(data)
        wav = r.sized_string()
        o = cls(wav=str(wav), loop=r.take(1)[0], interval=r.u32(), position=r.vec3(), max_distance=r.f32(), min_distance=r.f32())
        o.tail = data[r.o:]
        o._raw_wav = wav
        return o

    def to_bytes(self) -> bytes:
        w = Writer()
        w.sized_string(getattr(self, "_raw_wav", None) if getattr(self, "_raw_wav", None) is not None and str(self._raw_wav) == self.wav
                       else self.wav)
        return w.raw(bytes([self.loop & 255])).u32(self.interval).vec3(self.position).f32(self.max_distance).f32(self.min_distance) \
            .raw(self.tail).bytes()

    @property
    def transform(self) -> np.ndarray:
        m = np.eye(4, dtype=np.float32)
        m[3, :3] = self.position
        return m


@dataclass(eq=False)   # identity: comparing two of them must never compare numpy arrays (crashed the editor)
class CParticleSystem:
    """Particle emitter (smoke, fountains, bubbles, dust):
    ``[texture][position 3f][13 floats][colour start BGRA][colour end BGRA][size start][size end][sound object name][tail]``.

    The meaning of the 13 floats was worked out from the 155 emitters of the shipped maps (not from the game's code):
    velocity (3) | unk_a | spread | unk_b | radius of the emitter | particles per second | life in seconds | acceleration (3)
    | damping.  It fits what they do: fountains go up at 500-700 with acceleration -1000 (gravity) and damping 1; smoke rises
    with acceleration +500 and damping 0.92; bubbles start at 60 and their terminal speed with damping 0.95 is 58.
    Colours are D3D colours (blue, green, red, alpha bytes); the particle fades / grows from start to end."""
    KIND = "CParticleSystem"
    texture: str = "HUMO-03.tex"
    position: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    velocity: Tuple[float, float, float] = (0.0, 300.0, 0.0)
    unk_a: float = 0.03
    spread: float = 0.29
    unk_b: float = 0.0
    radius: float = 6.0
    rate: float = 7.0
    life: float = 4.0
    acceleration: Tuple[float, float, float] = (0.0, 500.0, 0.0)
    damping: float = 0.92
    color_start: Tuple[int, int, int, int] = (21, 21, 21, 75)        # red, green, blue, alpha
    color_end: Tuple[int, int, int, int] = (21, 21, 21, 0)
    size_start: float = 232.0
    size_end: float = 700.0
    sound: str = ""
    tail: bytes = b"\0" * 8

    @classmethod
    def from_bytes(cls, data: bytes):
        r = Reader(data)
        tex = r.sized_string()
        pos = r.vec3()
        f = struct.unpack_from("<13f", data, r.o); r.o += 52
        c1 = data[r.o:r.o + 4]; c2 = data[r.o + 4:r.o + 8]; r.o += 8
        s0, s1 = struct.unpack_from("<2f", data, r.o); r.o += 8
        snd = r.sized_string()
        o = cls(texture=str(tex), position=pos, velocity=tuple(f[0:3]), unk_a=f[3], spread=f[4], unk_b=f[5], radius=f[6],
                rate=f[7], life=f[8], acceleration=tuple(f[9:12]), damping=f[12],
                color_start=(c1[2], c1[1], c1[0], c1[3]), color_end=(c2[2], c2[1], c2[0], c2[3]),
                size_start=s0, size_end=s1, sound=str(snd))
        o.tail = data[r.o:]
        o._raw = (tex, snd)
        return o

    def to_bytes(self) -> bytes:
        raw = getattr(self, "_raw", (None, None))
        w = Writer()
        w.sized_string(raw[0] if raw[0] is not None and str(raw[0]) == self.texture else self.texture)
        w.vec3(self.position)
        w.raw(struct.pack("<13f", *self.velocity, self.unk_a, self.spread, self.unk_b, self.radius, self.rate, self.life,
                          *self.acceleration, self.damping))
        for c in (self.color_start, self.color_end):
            w.raw(bytes([int(c[2]) & 255, int(c[1]) & 255, int(c[0]) & 255, int(c[3]) & 255]))
        w.raw(struct.pack("<2f", self.size_start, self.size_end))
        w.sized_string(raw[1] if raw[1] is not None and str(raw[1]) == self.sound else self.sound)
        return w.raw(self.tail).bytes()

    @property
    def transform(self) -> np.ndarray:
        m = np.eye(4, dtype=np.float32)
        m[3, :3] = self.position
        return m


# particle presets taken from the shipped maps (name -> fields)
PARTICLE_PRESETS = {
    "smoke (Love Boat chimney)": dict(texture="HUMO-03.tex", velocity=(0.0, 300.0, 0.0), unk_a=0.03, spread=0.29, unk_b=0.0, radius=6.0,
                                      rate=7.0, life=4.0, acceleration=(0.0, 500.0, 0.0), damping=0.92,
                                      color_start=(21, 21, 21, 75), color_end=(21, 21, 21, 0), size_start=232.0, size_end=700.0),
    "fire smoke (mp_dm_asalto)": dict(texture="anim45_fuego.tex", velocity=(0.0, 300.0, 0.0), unk_a=0.03, spread=0.29, unk_b=0.0,
                                      radius=6.0, rate=7.0, life=4.0, acceleration=(0.0, 500.0, 0.0), damping=0.92,
                                      color_start=(21, 21, 21, 75), color_end=(21, 21, 21, 0), size_start=232.0, size_end=700.0),
    "fountain (mp_dm_plaza)": dict(texture="GOTA_AGUA_01.tex", velocity=(0.0, 700.0, 0.0), unk_a=-1.0, spread=0.1, unk_b=0.0, radius=0.2,
                                   rate=60.0, life=2.0, acceleration=(0.0, -1000.0, 0.0), damping=1.0,
                                   color_start=(0, 0, 0, 170), color_end=(0, 0, 0, 119), size_start=25.0, size_end=100.0),
    "bubbles (mp_b_anderguater)": dict(texture="burbuja.tex", velocity=(0.0, 60.0, 0.0), unk_a=0.0, spread=0.7, unk_b=1.0, radius=100.0,
                                       rate=30.0, life=50.0, acceleration=(0.0, 90.0, 0.0), damping=0.95,
                                       color_start=(194, 216, 226, 255), color_end=(173, 199, 207, 255), size_start=12.0, size_end=14.0),
    "coloured smoke (mp_b_industrial)": dict(texture="HUMO-02.tex", velocity=(0.0, 400.0, 0.0), unk_a=0.05, spread=1.0, unk_b=1.0,
                                             radius=6.0, rate=10.0, life=5.0, acceleration=(0.0, 700.0, 0.0), damping=0.8,
                                             color_start=(199, 208, 74, 255), color_end=(199, 208, 74, 0), size_start=100.0, size_end=200.0),
    # no shipped map has sparks: this one is built from the fountain (fast, short lived, pulled down by gravity) - try it in game
    "sparks (experimental)": dict(texture="GOTA_AGUA_01.tex", velocity=(0.0, 450.0, 0.0), unk_a=-1.0, spread=0.9, unk_b=0.0, radius=2.0,
                                  rate=40.0, life=0.7, acceleration=(0.0, -1000.0, 0.0), damping=1.0,
                                  color_start=(255, 170, 40, 255), color_end=(255, 80, 10, 0), size_start=10.0, size_end=4.0),
}


# --- modules that start with the common `[model][matrix]` header and carry a module specific tail (kept raw) ---
def _simple(kind: str, doc: str = ""):
    return type("MP" + kind.replace("_", ""), (ModelModule,), {"KIND": kind, "__doc__": doc or kind,
                                                               "__module__": __name__})


MPBoton = dataclass(_simple("mp_Boton"))
MPBombZone = dataclass(_simple("mp_BombZone"))
MPBomba = dataclass(_simple("mp_Bomba"))
VagonMetro = dataclass(_simple("VagonMetro"))
Ventilador = dataclass(_simple("Ventilador"))
MPMoto = dataclass(_simple("mp_Moto"))
ToroCar = dataclass(_simple("ToroCar"))
MPCoxe = dataclass(_simple("mp_coxe"))
MPBotikin = dataclass(_simple("mp_botikin"))
MPPersonaje = dataclass(_simple("mp_personaje"))


MODULE_TYPES: Dict[str, Type] = {
    c.KIND.lower(): c
    for c in (RenderNFO, AnimatedRenderNFO, CGlass, MPDoor, MPCosa, MPCCar, MPSalud, MPFlag, MPStartPoint, MPCameraStartPosition,
              MPSoundSource, CParticleSystem, MPBoton, MPBombZone, MPBomba, VagonMetro, Ventilador, MPMoto, ToroCar, MPCoxe, MPBotikin, MPPersonaje)
}


def parse_modules(scene: Scene) -> int:
    """Attach a typed object (``record.parsed``) to every known module. Returns how many were parsed."""
    n = 0
    for rec in scene.modules:
        cls = MODULE_TYPES.get(rec.clean_name.lower())
        if cls is None or rec.parsed is not None:
            continue
        try:
            rec.parsed = cls.from_bytes(rec.data)
            n += 1
        except Exception:   # malformed / unknown variant: keep raw bytes, never fail the whole scene
            rec.parsed = None
    return n


_NOKEY22 = "01000000000100000000" + "00" * 12
# Tail bytes (after model name + matrix) that real Online scenes use for a module of that kind that has no animation key.
# An empty tail makes the game crash while loading RenderNFO / AnimatedRenderNFO (it reads these fields).
DEFAULT_TAIL = {
    "rendernfo": _NOKEY22,
    "animatedrendernfo": "01000000000100000000010000000001" + "01" + "00000000" + "6f12033c",
    "mp_cosa": _NOKEY22,
    "mp_coxe": _NOKEY22,
    "mp_moto": _NOKEY22,
    "mp_personaje": _NOKEY22,
    "mp_ccar": _NOKEY22,
    "mp_door": "01000000000100000000000000000000000000000000010000000001000000000100000000000000000000000000",
    "mp_botikin": "010000000001000000" + "0064000000",
}


def new_module(scene: Scene, kind: str, object_name: str, before_terminator: bool = True) -> ModuleRecord:
    cls = MODULE_TYPES[kind.lower()]
    obj = cls()
    if isinstance(obj, ModelModule) and kind.lower() in DEFAULT_TAIL and not obj.tail:
        obj.tail = bytes.fromhex(DEFAULT_TAIL[kind.lower()])
    rec = ModuleRecord(VStr((object_name + "\0").encode("cp1252", "replace")), VStr((cls.KIND + ".dll\0").encode("cp1252", "replace")),
                       b"", obj)
    scene.modules.append(rec)       # the terminator is stored separately, so appending is always correct
    return rec
