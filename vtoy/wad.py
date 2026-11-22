"""Half-Life / Counter-Strike texture packs (.wad, WAD3) and the textures some .bsp files carry inside: name -> RGBA.

    read_wad(path)          {name (lower case): Mip}
    bsp_embedded(bsp_bytes) {name: Mip} of the textures stored in the .bsp itself
    Mip.rgba()              (h, w, 4) uint8; names starting with '{' are see-through where the palette's last colour is
"""
from __future__ import annotations

import os
import struct
from dataclasses import dataclass
from typing import Dict

import numpy as np


@dataclass
class Mip:
    name: str
    width: int
    height: int
    pixels: bytes          # width * height palette indices (the biggest level)
    palette: bytes         # 256 * 3

    def rgba(self) -> np.ndarray:
        idx = np.frombuffer(self.pixels, np.uint8).reshape(self.height, self.width)
        pal = np.frombuffer(self.palette.ljust(768, b"\0"), np.uint8).reshape(256, 3)
        out = np.empty((self.height, self.width, 4), np.uint8)
        out[..., :3] = pal[idx]
        out[..., 3] = 255
        if self.name.startswith("{"):
            out[idx == 255, 3] = 0
        return out


def parse_miptex(blob: bytes, at: int = 0) -> Mip:
    name = blob[at:at + 16].split(b"\0")[0].decode("latin-1")
    w, h, o0, o1, o2, o3 = struct.unpack_from("<II4I", blob, at + 16)
    if not o0:
        raise ValueError(f"{name}: no pixels (kept in a .wad)")
    pix = blob[at + o0:at + o0 + w * h]
    pal_at = at + o3 + (w // 8) * (h // 8)
    n = struct.unpack_from("<H", blob, pal_at)[0] if pal_at + 2 <= len(blob) else 0
    pal = blob[pal_at + 2:pal_at + 2 + 3 * max(n, 256)][:768]
    return Mip(name, w, h, pix, pal)


def read_wad(path: str) -> Dict[str, Mip]:
    data = open(path, "rb").read()
    if data[:4] not in (b"WAD3", b"WAD2"):
        raise ValueError(f"{path}: not a .wad (WAD3)")
    n, ofs = struct.unpack_from("<ii", data, 4)
    out: Dict[str, Mip] = {}
    for i in range(n):
        pos, disk, size, typ, comp, _p, name = struct.unpack_from("<iiibbh16s", data, ofs + 32 * i)
        if typ not in (0x43, 0x40) or comp:
            continue
        try:
            m = parse_miptex(data, pos)
        except (ValueError, struct.error):
            continue
        out[m.name.lower()] = m
    return out


def bsp_embedded(data: bytes) -> Dict[str, Mip]:
    off, ln = struct.unpack_from("<ii", data, 4 + 8 * 2)
    tl = data[off:off + ln]
    out: Dict[str, Mip] = {}
    if len(tl) < 4:
        return out
    for k in range(struct.unpack_from("<i", tl, 0)[0]):
        o = struct.unpack_from("<i", tl, 4 + 4 * k)[0]
        if o < 0:
            continue
        try:
            m = parse_miptex(tl, o)
        except (ValueError, struct.error):
            continue
        out[m.name.lower()] = m
    return out


def listed_wads(worldspawn: dict) -> list:
    """The texture packs a map names in its worldspawn "wad" key (as file names, e.g. ['halflife.wad', 'cs_dust.wad'])."""
    out = []
    for part in str(worldspawn.get("wad", "")).replace("\\", "/").split(";"):
        name = part.strip().split("/")[-1]
        if name.lower().endswith(".wad") and name.lower() not in [o.lower() for o in out]:
            out.append(name)
    return out


def find_wads(names, dirs) -> dict:
    """{name: path} of the .wad files called ``names`` found in ``dirs`` (any case; the first folder that has it)."""
    want = {n.lower(): n for n in names}
    out = {}
    for d in dirs:
        try:
            files = os.listdir(d)
        except OSError:
            continue
        for f in files:
            k = f.lower()
            if k in want and want[k] not in out and os.path.isfile(os.path.join(d, f)):
                out[want[k]] = os.path.join(d, f)
    return out


def search_dirs(map_path: str, extra=()) -> list:
    """Where a map's .wad files usually are: its own folder, the mod folder above it (cstrike/maps -> cstrike), the
    Half-Life folders next to that one (valve, cstrike) and the folders given."""
    out = []
    here = os.path.dirname(os.path.abspath(map_path))
    up = os.path.dirname(here)
    cands = [here, up] + [os.path.join(os.path.dirname(up), m) for m in ("valve", "cstrike", "czero")] + list(extra)
    for d in cands:
        if d and os.path.isdir(d) and os.path.normcase(os.path.abspath(d)) not in [os.path.normcase(o) for o in out]:
            out.append(os.path.abspath(d))
    return out
