"""Small binary helpers shared by every parser."""
from __future__ import annotations

import struct
from typing import Tuple

import numpy as np


class VStr(str):
    """A string read from a file. Behaves like a normal ``str`` (cut at the first NUL, like a C string) but
    remembers its exact on-disk bytes so unchanged strings are written back byte-for-byte."""

    raw: bytes

    def __new__(cls, raw: bytes):
        text = raw.split(b"\0", 1)[0].decode("cp1252", "replace")
        obj = super().__new__(cls, text)
        obj.raw = raw
        return obj

    def __reduce__(self):  # copy / deepcopy / pickle must rebuild from the raw bytes
        return (VStr, (self.raw,))


class Reader:
    """Sequential little-endian reader over a bytes object."""

    def __init__(self, data: bytes, offset: int = 0):
        self.data = data
        self.o = offset

    def __len__(self) -> int:
        return len(self.data)

    @property
    def remaining(self) -> int:
        return len(self.data) - self.o

    def eof(self) -> bool:
        return self.o >= len(self.data)

    def take(self, n: int) -> bytes:
        if n < 0 or self.o + n > len(self.data):
            raise EOFError(f"need {n} bytes at {self.o}, only {len(self.data) - self.o} left")
        b = self.data[self.o:self.o + n]
        self.o += n
        return b

    def _unpack(self, fmt: str, size: int):
        if self.o + size > len(self.data):
            raise EOFError(f"need {size} bytes at {self.o}")
        v = struct.unpack_from(fmt, self.data, self.o)
        self.o += size
        return v

    def u8(self) -> int:
        return self._unpack("<B", 1)[0]

    def u32(self) -> int:
        return self._unpack("<I", 4)[0]

    def i32(self) -> int:
        return self._unpack("<i", 4)[0]

    def f32(self) -> float:
        return self._unpack("<f", 4)[0]

    def vec3(self) -> Tuple[float, float, float]:
        return self._unpack("<3f", 12)

    def mat4(self) -> np.ndarray:
        """Row-major 4x4 (same memory order as System.Numerics.Matrix4x4, row-vector convention)."""
        return np.frombuffer(self.take(64), "<f4").reshape(4, 4).astype(np.float32)

    def array(self, dtype: str, count: int) -> np.ndarray:
        dt = np.dtype(dtype)
        return np.frombuffer(self.take(dt.itemsize * count), dt, count).copy()

    def sized_string(self, size: int | None = None) -> str:
        """u32 length prefix (includes trailing NUL) + bytes. NULs are stripped."""
        if size is None:
            size = self.u32()
        return VStr(self.take(size) if size else b"")


class Writer:
    def __init__(self):
        self.buf = bytearray()

    def tell(self) -> int:
        return len(self.buf)

    def raw(self, b: bytes) -> "Writer":
        self.buf += b
        return self

    def u8(self, v: int) -> "Writer":
        self.buf += struct.pack("<B", v)
        return self

    def u32(self, v: int) -> "Writer":
        self.buf += struct.pack("<I", v & 0xFFFFFFFF)
        return self

    def i32(self, v: int) -> "Writer":
        self.buf += struct.pack("<i", v)
        return self

    def f32(self, v: float) -> "Writer":
        self.buf += struct.pack("<f", v)
        return self

    def vec3(self, v) -> "Writer":
        self.buf += struct.pack("<3f", *[float(x) for x in v])
        return self

    def mat4(self, m) -> "Writer":
        self.buf += np.asarray(m, "<f4").reshape(16).tobytes()
        return self

    def sized_string(self, s: str) -> "Writer":
        b = s.raw if isinstance(s, VStr) else s.encode("cp1252", "replace") + b"\0"
        self.u32(len(b))
        self.buf += b
        return self

    def bytes(self) -> bytes:
        return bytes(self.buf)


def ci_find(path: str) -> str:
    """Case-insensitive path resolution (the game's files are Windows-cased). Returns '' if missing."""
    import os

    path = path.replace("\\", "/")
    parts = [p for p in path.split("/") if p not in ("", ".")]
    cur = "/" if path.startswith("/") else "."
    for p in parts:
        try:
            names = os.listdir(cur)
        except OSError:
            return ""
        if p in names:
            cur = os.path.join(cur, p)
            continue
        low = {n.lower(): n for n in names}
        if p.lower() in low:
            cur = os.path.join(cur, low[p.lower()])
        else:
            return ""
    return cur
