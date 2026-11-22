"""Texture (.tex, magic 'TeX2') reader/writer with a pure numpy DXT1/DXT5 codec.

Header (21 bytes): 'TeX2' | u8 format (0=DXT1, 1=DXT5) | i32 unknown (always 1) | i32 width | i32 height | i32 data size
Data is the DXT payload of the base level, optionally followed by the complete mip chain.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import List

import numpy as np

DXT1, DXT5 = 0, 1


def level_size(w: int, h: int, fmt: int) -> int:
    return max(1, (w + 3) // 4) * max(1, (h + 3) // 4) * (8 if fmt == DXT1 else 16)


# ------------------------------------------------------------------------------- decoding
def _rgb565(c: np.ndarray) -> np.ndarray:
    c = c.astype(np.uint32)
    r = (c >> 11) & 31
    g = (c >> 5) & 63
    b = c & 31
    return np.stack([(r * 255 + 15) // 31, (g * 255 + 31) // 63, (b * 255 + 15) // 31], -1).astype(np.int32)


def _decode_color_blocks(blk: np.ndarray, dxt1: bool):
    """blk: (n, 8) uint8 -> rgb (n,16,3) uint8, alpha (n,16) uint8"""
    c0 = blk[:, 0].astype(np.uint16) | (blk[:, 1].astype(np.uint16) << 8)
    c1 = blk[:, 2].astype(np.uint16) | (blk[:, 3].astype(np.uint16) << 8)
    p0, p1 = _rgb565(c0), _rgb565(c1)
    four = (c0 > c1) | (not dxt1)
    pal = np.zeros((len(blk), 4, 3), np.int32)
    pal[:, 0], pal[:, 1] = p0, p1
    pal[:, 2] = np.where(four[:, None], (2 * p0 + p1) // 3, (p0 + p1) // 2)
    pal[:, 3] = np.where(four[:, None], (p0 + 2 * p1) // 3, 0)
    bits = blk[:, 4:8].copy().view("<u4")[:, 0]
    shifts = np.arange(16, dtype=np.uint32) * 2
    idx = ((bits[:, None] >> shifts[None, :]) & 3).astype(np.int64)
    rgb = np.take_along_axis(pal, idx[:, :, None].repeat(3, 2), axis=1)
    alpha = np.full((len(blk), 16), 255, np.uint8)
    if dxt1:
        alpha[(~four)[:, None] & (idx == 3)] = 0
    return rgb.astype(np.uint8), alpha


def _decode_alpha_blocks(blk: np.ndarray) -> np.ndarray:
    """blk: (n, 8) uint8 DXT5 alpha block -> (n,16) uint8"""
    a0 = blk[:, 0].astype(np.int32)
    a1 = blk[:, 1].astype(np.int32)
    pal = np.zeros((len(blk), 8), np.int32)
    pal[:, 0], pal[:, 1] = a0, a1
    for i in range(1, 7):
        pal[:, i + 1] = np.where(a0 > a1, ((7 - i) * a0 + i * a1) // 7, np.where(i < 5, ((5 - i) * a0 + i * a1) // 5, 0))
    pal[:, 6] = np.where(a0 > a1, pal[:, 6], 0)
    pal[:, 7] = np.where(a0 > a1, pal[:, 7], 255)
    bits = np.zeros(len(blk), np.uint64)
    for i in range(6):
        bits |= blk[:, 2 + i].astype(np.uint64) << np.uint64(8 * i)
    shifts = np.arange(16, dtype=np.uint64) * np.uint64(3)
    idx = ((bits[:, None] >> shifts[None, :]) & np.uint64(7)).astype(np.int64)
    return np.take_along_axis(pal, idx, axis=1).astype(np.uint8)


def decode_dxt(data: bytes, w: int, h: int, fmt: int) -> np.ndarray:
    """-> (h, w, 4) uint8 RGBA"""
    bw, bh = max(1, (w + 3) // 4), max(1, (h + 3) // 4)
    stride = 8 if fmt == DXT1 else 16
    need = bw * bh * stride
    buf = np.frombuffer(data[:need].ljust(need, b"\0"), np.uint8).reshape(-1, stride)
    if fmt == DXT1:
        rgb, a = _decode_color_blocks(buf, True)
    else:
        a = _decode_alpha_blocks(buf[:, :8])
        rgb, _ = _decode_color_blocks(buf[:, 8:], False)
    px = np.concatenate([rgb, a[:, :, None]], axis=2)           # (n,16,4)
    px = px.reshape(bh, bw, 4, 4, 4).transpose(0, 2, 1, 3, 4).reshape(bh * 4, bw * 4, 4)
    return px[:h, :w]


# ------------------------------------------------------------------------------- encoding
def _to565(rgb: np.ndarray) -> np.ndarray:
    r = (rgb[..., 0].astype(np.uint32) * 31 + 127) // 255
    g = (rgb[..., 1].astype(np.uint32) * 63 + 127) // 255
    b = (rgb[..., 2].astype(np.uint32) * 31 + 127) // 255
    return ((r << 11) | (g << 5) | b).astype(np.uint16)


def _blocks_of(img: np.ndarray) -> np.ndarray:
    h, w = img.shape[:2]
    ph, pw = (-h) % 4, (-w) % 4
    if ph or pw:
        img = np.pad(img, ((0, ph), (0, pw), (0, 0)), mode="edge")
    bh, bw = img.shape[0] // 4, img.shape[1] // 4
    return img.reshape(bh, 4, bw, 4, -1).transpose(0, 2, 1, 3, 4).reshape(bh * bw, 16, -1)


def _encode_color(px: np.ndarray, allow_alpha: bool) -> np.ndarray:
    """px: (n,16,4) uint8 -> (n,8) uint8 using a bounding-box endpoint fit (fast, decent quality)."""
    n = len(px)
    rgb = px[:, :, :3].astype(np.int32)
    transparent = (px[:, :, 3] < 128) if allow_alpha else np.zeros((n, 16), bool)
    has_t = transparent.any(1)
    big = np.where(transparent[:, :, None], 255, rgb)
    small = np.where(transparent[:, :, None], 0, rgb)
    lo, hi = big.min(1), small.max(1)
    lo = np.where(transparent.all(1)[:, None], 0, lo)
    hi = np.where(transparent.all(1)[:, None], 0, hi)
    # inset the box slightly (reduces error on average, like squish's range fit)
    inset = (hi - lo) // 16
    lo, hi = lo + inset, hi - inset
    c_hi, c_lo = _to565(hi), _to565(lo)
    # 4-colour mode needs c0 > c1; 3-colour (alpha) mode needs c0 <= c1
    c0 = np.where(has_t, np.minimum(c_hi, c_lo), np.maximum(c_hi, c_lo))
    c1 = np.where(has_t, np.maximum(c_hi, c_lo), np.minimum(c_hi, c_lo))
    p0, p1 = _rgb565(c0), _rgb565(c1)
    pal = np.zeros((n, 4, 3), np.int32)
    pal[:, 0], pal[:, 1] = p0, p1
    four = ~has_t
    pal[:, 2] = np.where(four[:, None], (2 * p0 + p1) // 3, (p0 + p1) // 2)
    pal[:, 3] = np.where(four[:, None], (p0 + 2 * p1) // 3, 0)
    d = ((rgb[:, :, None, :] - pal[:, None, :, :]) ** 2).sum(-1)       # (n,16,4)
    d[:, :, 3] = np.where(four[:, None], d[:, :, 3], 1 << 30)
    idx = d.argmin(2).astype(np.uint32)
    idx = np.where(transparent, 3, idx).astype(np.uint32)
    bits = np.zeros(n, np.uint32)
    for i in range(16):
        bits |= idx[:, i] << np.uint32(2 * i)
    out = np.zeros((n, 8), np.uint8)
    out[:, 0], out[:, 1] = (c0 & 255), (c0 >> 8)
    out[:, 2], out[:, 3] = (c1 & 255), (c1 >> 8)
    out[:, 4:8] = bits[:, None].view(np.uint8).reshape(n, 4) if False else bits.astype("<u4").view(np.uint8).reshape(n, 4)
    return out


def _encode_alpha(a: np.ndarray) -> np.ndarray:
    n = len(a)
    a = a.astype(np.int32)
    a0, a1 = a.max(1), a.min(1)             # a0 >= a1 -> 8-value mode
    pal = np.zeros((n, 8), np.int32)
    pal[:, 0], pal[:, 1] = a0, a1
    for i in range(1, 7):
        pal[:, i + 1] = ((7 - i) * a0 + i * a1) // 7
    d = np.abs(a[:, :, None] - pal[:, None, :])
    idx = d.argmin(2).astype(np.uint64)
    bits = np.zeros(n, np.uint64)
    for i in range(16):
        bits |= idx[:, i] << np.uint64(3 * i)
    out = np.zeros((n, 8), np.uint8)
    out[:, 0], out[:, 1] = a0, a1
    for i in range(6):
        out[:, 2 + i] = ((bits >> np.uint64(8 * i)) & np.uint64(255)).astype(np.uint8)
    return out


def encode_dxt(rgba: np.ndarray, fmt: int) -> bytes:
    blocks = _blocks_of(np.ascontiguousarray(rgba, np.uint8))
    if fmt == DXT1:
        return _encode_color(blocks, True).tobytes()
    col = _encode_color(blocks, False)
    al = _encode_alpha(blocks[:, :, 3])
    return np.concatenate([al, col], axis=1).tobytes()


def _downsample(img: np.ndarray) -> np.ndarray:
    h, w = img.shape[:2]
    h2, w2 = max(1, h // 2), max(1, w // 2)
    a = img[: h2 * 2 if h > 1 else 1, : w2 * 2 if w > 1 else 1].astype(np.float32)
    if h > 1:
        a = (a[0::2] + a[1::2]) / 2
    if w > 1:
        a = (a[:, 0::2] + a[:, 1::2]) / 2
    return np.clip(a + 0.5, 0, 255).astype(np.uint8)


# ------------------------------------------------------------------------------- file object
@dataclass
class Texture:
    fmt: int = DXT1
    unk: int = 1
    width: int = 0
    height: int = 0
    data: bytes = b""            # exactly what is stored after the header (base level [+ mips])
    declared_size: int = 0       # data-size field of the header (a few shipped files are 20 bytes short)

    @property
    def format_name(self) -> str:
        return "DXT1" if self.fmt == DXT1 else "DXT5"

    @property
    def has_mips(self) -> bool:
        return len(self.data) > level_size(self.width, self.height, self.fmt)

    @property
    def mip_count(self) -> int:
        w, h, n, total = self.width, self.height, 0, 0
        while total < len(self.data):
            total += level_size(w, h, self.fmt)
            n += 1
            if w == 1 and h == 1:
                break
            w, h = max(1, w // 2), max(1, h // 2)
        return max(n, 1)

    @classmethod
    def parse(cls, raw: bytes) -> "Texture":
        if raw[:4] == b"TeX1":
            return Texture1.parse(raw)
        if raw[:4] != b"TeX2":
            raise ValueError("not a TeX2 texture")
        fmt = raw[4]
        unk, w, h, size = struct.unpack_from("<4i", raw, 5)
        if fmt not in (DXT1, DXT5):
            raise ValueError(f"unknown texture format {fmt}")
        return cls(fmt, unk, w, h, raw[21:], size)

    @classmethod
    def load(cls, path: str) -> "Texture":
        with open(path, "rb") as f:
            return cls.parse(f.read())

    def to_bytes(self) -> bytes:
        return b"TeX2" + bytes([self.fmt]) + struct.pack("<4i", self.unk, self.width, self.height, self.declared_size) + self.data

    def save(self, path: str) -> None:
        with open(path, "wb") as f:
            f.write(self.to_bytes())

    # ---- pixels ------------------------------------------------------------------------
    def decode(self, level: int = 0) -> np.ndarray:
        """RGBA uint8 array (h, w, 4) for the given mip level."""
        w, h, off = self.width, self.height, 0
        for _ in range(level):
            off += level_size(w, h, self.fmt)
            w, h = max(1, w // 2), max(1, h // 2)
        return decode_dxt(self.data[off:off + level_size(w, h, self.fmt)], w, h, self.fmt)

    @property
    def has_alpha(self) -> bool:
        """True if any texel is not fully opaque (DXT1 = 1-bit cut-out, DXT5 = real alpha)."""
        return bool((self.decode()[:, :, 3] < 255).any())

    @classmethod
    def from_rgba(cls, rgba: np.ndarray, fmt: int | None = None, mipmaps: bool = False) -> "Texture":
        rgba = np.ascontiguousarray(rgba, np.uint8)
        if rgba.ndim == 3 and rgba.shape[2] == 3:
            rgba = np.concatenate([rgba, np.full(rgba.shape[:2] + (1,), 255, np.uint8)], 2)
        h, w = rgba.shape[:2]
        if fmt is None:
            fmt = DXT5 if (rgba[:, :, 3] < 255).any() else DXT1
        parts, cur = [encode_dxt(rgba, fmt)], rgba
        if mipmaps:
            while cur.shape[0] > 1 or cur.shape[1] > 1:
                cur = _downsample(cur)
                parts.append(encode_dxt(cur, fmt))
        data = b"".join(parts)
        return cls(fmt, 1, w, h, data, len(data))

    # ---- PNG helpers ---------------------------------------------------------------------
    def to_png(self, path: str, level: int = 0) -> None:
        from PIL import Image
        Image.fromarray(self.decode(level), "RGBA").save(path)

    @classmethod
    def from_png(cls, path: str, fmt: int | None = None, mipmaps: bool = False) -> "Texture":
        from PIL import Image
        return cls.from_rgba(np.array(Image.open(path).convert("RGBA")), fmt, mipmaps)

    # ---- DDS (DXT1 / DXT5, same block data as the .tex) ---------------------------------------
    def to_dds_bytes(self) -> bytes:
        four = b"DXT1" if self.fmt == DXT1 else b"DXT5"
        mips = self.mip_count
        head = b"DDS " + struct.pack("<7I", 124, 0xA1007, self.height, self.width,
                                     level_size(self.width, self.height, self.fmt), 0, mips)
        head += b"\0" * 44 + struct.pack("<II4s5I", 32, 4, four, 0, 0, 0, 0, 0)
        head += struct.pack("<5I", 0x401008 if mips > 1 else 0x1000, 0, 0, 0, 0)
        return head + self.data

    def save_dds(self, path: str) -> None:
        with open(path, "wb") as f:
            f.write(self.to_dds_bytes())

    @classmethod
    def from_dds(cls, path: str) -> "Texture":
        with open(path, "rb") as f:
            raw = f.read()
        if raw[:4] != b"DDS ":
            raise ValueError("not a DDS file")
        h, w = struct.unpack_from("<2I", raw, 12)
        four = raw[84:88]
        if four not in (b"DXT1", b"DXT5"):
            raise ValueError("only DXT1 / DXT5 DDS files are supported (save the image as PNG instead)")
        data = raw[128:]
        return cls(DXT1 if four == b"DXT1" else DXT5, 1, w, h, data, len(data))


# ------------------------------------------------------------------------------- legacy format (Torrente el juego)
@dataclass
class Texture1:
    """Legacy ``TeX1`` texture used by the older 'Torrente, el juego' engine: uncompressed, mip chain included.

    Header (17 bytes): 'TeX1' | u8 kind (0 = RGB24 stored R,G,B / 1 = ARGB32 stored A,R,G,B) | u32 mip count | u32 w | u32 h.
    The online engine only reads TeX2, so ``to_texture2()`` converts for importing."""
    kind: int = 0
    mips: int = 1
    width: int = 0
    height: int = 0
    data: bytes = b""
    legacy = True

    @property
    def fmt(self) -> int:
        return self.kind

    @property
    def format_name(self) -> str:
        return "RGB24 (TeX1)" if self.kind == 0 else "ARGB32 (TeX1)"

    @property
    def bpp(self) -> int:
        return 3 if self.kind == 0 else 4

    @property
    def mip_count(self) -> int:
        return self.mips

    @property
    def has_mips(self) -> bool:
        return self.mips > 1

    @classmethod
    def parse(cls, raw: bytes) -> "Texture1":
        if raw[:4] != b"TeX1":
            raise ValueError("not a TeX1 texture")
        kind = raw[4]
        mips, w, h = struct.unpack_from("<3I", raw, 5)
        if kind not in (0, 1):
            raise ValueError(f"unknown TeX1 kind {kind}")
        t = cls(kind, mips, w, h, raw[17:])
        need = 0
        ww, hh = w, h
        for _ in range(mips):
            need += ww * hh * t.bpp
            ww, hh = max(1, ww // 2), max(1, hh // 2)
        if need != len(t.data):
            raise ValueError(f"TeX1 size mismatch: expected {need} bytes, found {len(t.data)}")
        return t

    @classmethod
    def load(cls, path: str) -> "Texture1":
        with open(path, "rb") as f:
            return cls.parse(f.read())

    def to_bytes(self) -> bytes:
        return b"TeX1" + bytes([self.kind]) + struct.pack("<3I", self.mips, self.width, self.height) + self.data

    def save(self, path: str) -> None:
        with open(path, "wb") as f:
            f.write(self.to_bytes())

    def decode(self, level: int = 0) -> np.ndarray:
        w, h, off = self.width, self.height, 0
        for _ in range(level):
            off += w * h * self.bpp
            w, h = max(1, w // 2), max(1, h // 2)
        a = np.frombuffer(self.data, np.uint8, w * h * self.bpp, off).reshape(h, w, self.bpp)
        if self.kind == 0:
            return np.concatenate([a, np.full((h, w, 1), 255, np.uint8)], 2)
        return np.ascontiguousarray(a[:, :, [1, 2, 3, 0]])      # A,R,G,B -> R,G,B,A

    @property
    def has_alpha(self) -> bool:
        return self.kind == 1 and bool((self.decode()[:, :, 3] < 255).any())

    @classmethod
    def from_rgba(cls, rgba: np.ndarray, fmt: int | None = None, mipmaps: bool = False) -> "Texture1":
        rgba = np.ascontiguousarray(rgba, np.uint8)
        if rgba.ndim == 3 and rgba.shape[2] == 3:
            rgba = np.concatenate([rgba, np.full(rgba.shape[:2] + (1,), 255, np.uint8)], 2)
        h, w = rgba.shape[:2]
        kind = fmt if fmt is not None else (1 if (rgba[:, :, 3] < 255).any() else 0)
        levels, cur = [rgba], rgba
        while mipmaps and (cur.shape[0] > 1 or cur.shape[1] > 1):
            cur = _downsample(cur)
            levels.append(cur)
        enc = [(l[:, :, :3] if kind == 0 else l[:, :, [3, 0, 1, 2]]).tobytes() for l in levels]
        return cls(kind, len(levels), w, h, b"".join(enc))

    def to_png(self, path: str, level: int = 0) -> None:
        from PIL import Image
        Image.fromarray(self.decode(level), "RGBA").save(path)

    @classmethod
    def from_png(cls, path: str, fmt: int | None = None, mipmaps: bool = False) -> "Texture1":
        from PIL import Image
        return cls.from_rgba(np.array(Image.open(path).convert("RGBA")), fmt, mipmaps)

    def to_texture2(self, keep_mips: bool = True) -> "Texture":
        """Convert to the DXT format the online engine reads (DXT5 only if the texture really has alpha)."""
        base = self.decode(0)
        return Texture.from_rgba(base, DXT5 if self.has_alpha else DXT1, mipmaps=keep_mips and self.mips > 1)
