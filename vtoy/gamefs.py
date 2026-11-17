"""Case-insensitive access to an unpacked game folder (the 'Out' folder: scns/, nfos/, texs/, keys/ ...)."""
from __future__ import annotations

import os
from typing import Dict, Optional

from .hm import HeightMap
from .keys import KeyFile
from .nfo import NfoModel
from .opt import OptMap
from .scn import Scene
from .tex import Texture
from .modules import parse_modules


def norm(path: str) -> str:
    return path.replace("\\", "/").strip("/").lower()


class GameFS:
    def __init__(self, root: str):
        self.root = os.path.abspath(root)
        self.index: Dict[str, str] = {}
        self.rescan()
        self._tex: Dict[str, Optional[Texture]] = {}
        self._nfo: Dict[str, Optional[NfoModel]] = {}
        self._opt: Dict[str, OptMap] = {}
        self._key: Dict[str, Optional[KeyFile]] = {}

    def rescan(self) -> None:
        self.index.clear()
        for dp, _, fns in os.walk(self.root, followlinks=True):
            for f in fns:
                full = os.path.join(dp, f)
                self.index[norm(os.path.relpath(full, self.root))] = full

    # ---- raw lookup --------------------------------------------------------------------
    def find(self, rel: str) -> Optional[str]:
        return self.index.get(norm(rel))

    def list(self, folder: str, *exts: str):
        pref = norm(folder) + "/"
        return sorted(p for p in self.index if p.startswith(pref) and (not exts or p.endswith(tuple(e.lower() for e in exts))))

    # ---- typed loaders (cached) --------------------------------------------------------------
    def scene(self, name: str) -> Scene:
        p = self.find(name if "/" in name or "\\" in name else f"scns/{name}")
        if p is None:
            raise FileNotFoundError(name)
        s = Scene.load(p)
        parse_modules(s)
        return s

    def map(self, rel: str) -> OptMap:
        key = norm(rel)
        if key not in self._opt:
            p = self.find(rel)
            if p is None:
                raise FileNotFoundError(rel)
            self._opt[key] = OptMap.load(p)
        return self._opt[key]

    def heightmap(self, rel: str) -> HeightMap:
        p = self.find(rel)
        if p is None:
            raise FileNotFoundError(rel)
        return HeightMap.load(p)

    def texture(self, name: str) -> Optional[Texture]:
        """`name` may be 'foo.tex', 'foo' or an artist's 'foo.bmp'; textures live in texs/."""
        base = os.path.splitext(norm(name).split("/")[-1])[0]
        if base not in self._tex:
            p = self.find(f"texs/{base}.tex")
            try:
                self._tex[base] = Texture.load(p) if p else None
            except Exception:
                self._tex[base] = None
        return self._tex[base]

    def model(self, name: str) -> Optional[NfoModel]:
        key = norm(name)
        if key not in self._nfo:
            p = self.find(key if key.startswith("nfos/") else f"nfos/{key}")
            try:
                self._nfo[key] = NfoModel.load(p) if p else None
            except Exception:
                self._nfo[key] = None
        return self._nfo[key]

    def keys(self, name: str) -> Optional[KeyFile]:
        key = norm(name)
        if key not in self._key:
            p = self.find(key if key.startswith("keys/") else f"keys/{key}")
            try:
                self._key[key] = KeyFile.load(p) if p else None
            except Exception:
                self._key[key] = None
        return self._key[key]
