"""Transform animation files (.key, magic 'FKEY').

Layout (reverse engineered from the shipped files):
    'FKEY' | u32 0xFFFFFFFF | 'INFO' | u32 size | u32 version (0x10001) | u32 nodes | u32 frames
    nodes x  CSTR (node name, matches the TRA1 node names of the model)
    frames x 'KEY1' | u32 8 | nodes x (quat x,y,z,w | pos x,y,z | scale x,y,z) | u32 n_events | n x (tag, u32 size, payload)
Events are chunks such as 'SND2' (a sound trigger, e.g. a footstep) fired when the animation reaches that frame.
Poses are local to the node's parent. Some files leave `scale` uninitialised, so it is not trusted.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

import numpy as np

from .binutil import Reader, Writer
from .nfo import read_cstr_chunk



@dataclass
class KeyEvent:
    tag: str                  # 'SND1' / 'SND2' (sound), 'GENE' (generic), 'VIS1' (show/hide an object by name) ...
    payload: bytes = b""
    open_ended: bool = False  # size field was 0xFFFFFFFF: payload = CSTR chunk + u32 (VIS1)

    @property
    def text(self) -> str:
        """Best effort name stored in the payload (object name for VIS1)."""
        b = self.payload[8:] if self.open_ended else self.payload
        return b.split(b"\0", 1)[0].decode("cp1252", "replace")


KEY_DTYPE = np.dtype([("rot", "<f4", 4), ("pos", "<f4", 3), ("scale", "<f4", 3)])


@dataclass
class KeyFile:
    version: int = 0x10001
    node_names: List[str] = field(default_factory=list)
    poses: np.ndarray = None            # (frames, nodes) structured KEY_DTYPE
    info_size: int = 0
    events: List[List[KeyEvent]] = field(default_factory=list)   # per frame
    tail: bytes = b""
    key1_sizes: List[int] = field(default_factory=list)   # size field of every KEY1 chunk (8, or 0xFFFFFFFF in some old files)

    @property
    def frames(self) -> int:
        return 0 if self.poses is None else self.poses.shape[0]

    @classmethod
    def parse(cls, data: bytes) -> "KeyFile":
        r = Reader(data)
        if r.take(4) != b"FKEY":
            raise ValueError("not an FKEY animation")
        r.u32()                                    # 0xFFFFFFFF (open-ended container)
        if r.take(4) != b"INFO":
            raise ValueError("missing INFO")
        k = cls(info_size=r.u32())
        k.version, nodes, frames = r.u32(), r.u32(), r.u32()
        k.node_names = [read_cstr_chunk(r) for _ in range(nodes)]
        k.poses = np.zeros((frames, nodes), KEY_DTYPE)
        for f in range(frames):
            if r.take(4) != b"KEY1":
                raise ValueError("expected KEY1")
            k.key1_sizes.append(r.u32())
            k.poses[f] = r.array(KEY_DTYPE, nodes)
            evs = []
            for _ in range(r.u32()):
                tag = r.take(4).decode("cp1252", "replace")
                size = r.u32()
                if size == 0xFFFFFFFF:          # open-ended: CSTR name chunk followed by a u32 value
                    start = r.o
                    if r.take(4) != b"CSTR":
                        raise ValueError("open-ended event without CSTR")
                    r.take(r.u32() - 8)
                    r.u32()
                    evs.append(KeyEvent(tag, r.data[start:r.o], True))
                else:
                    evs.append(KeyEvent(tag, r.take(size - 8)))
            k.events.append(evs)
        k.tail = data[r.o:]
        return k

    @classmethod
    def load(cls, path: str) -> "KeyFile":
        with open(path, "rb") as f:
            return cls.parse(f.read())

    def to_bytes(self) -> bytes:
        w = Writer().raw(b"FKEY").u32(0xFFFFFFFF).raw(b"INFO").u32(self.info_size)
        w.u32(self.version).u32(len(self.node_names)).u32(self.frames)
        for n in self.node_names:
            b = n.encode("cp1252", "replace") + b"\0"
            w.raw(b"CSTR").u32(8 + len(b)).raw(b)
        for f in range(self.frames):
            w.raw(b"KEY1").u32(self.key1_sizes[f] if f < len(self.key1_sizes) else 8).raw(self.poses[f].tobytes())
            evs = self.events[f] if f < len(self.events) else []
            w.u32(len(evs))
            for e in evs:
                w.raw(e.tag.encode("cp1252", "replace")).u32(0xFFFFFFFF if e.open_ended else 8 + len(e.payload)).raw(e.payload)
        return w.raw(self.tail).bytes()

    def sample(self, node: int, frame: float):
        """Interpolated (quat xyzw, position) of a node at a (fractional, looping) frame."""
        if self.frames == 0:
            return np.array([0, 0, 0, 1], np.float32), np.zeros(3, np.float32)
        f0 = int(np.floor(frame)) % self.frames
        f1 = (f0 + 1) % self.frames
        a = float(frame - np.floor(frame))
        q0, q1 = self.poses["rot"][f0, node].astype(np.float64), self.poses["rot"][f1, node].astype(np.float64)
        if np.dot(q0, q1) < 0:
            q1 = -q1
        q = q0 * (1 - a) + q1 * a
        q /= max(np.linalg.norm(q), 1e-9)
        p = self.poses["pos"][f0, node] * (1 - a) + self.poses["pos"][f1, node] * a
        return q.astype(np.float32), p.astype(np.float32)
