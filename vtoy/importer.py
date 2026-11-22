"""Use assets of the older *Torrente, el juego* (read-only "library") inside an online game folder.

Rules (nothing of the online data is ever overwritten):
* textures are TeX1 (uncompressed) in the old game; the online engine only knows TeX2 (its vtKernel.dll has no TeX1
  loader), so they are converted to DXT1/DXT5 when imported;
* if the online folder already has a texture of the same name and it is the same picture (mean pixel difference below
  ``SAME_TEXTURE``), it is reused; if it is a different picture the old one is imported as ``tj_<name>`` and the
  model / map that uses it is rewritten to point at the new name;
* the same applies to models (.nfo), maps (.opt/.hm) and animations (.key): identical file = reuse, different file with
  the same name = import with the ``tj_`` prefix.
"""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

import numpy as np

from .nfo import Nfo
from .opt import OptMap
from . import optconv
from .tex import Texture, Texture1

PREFIX = "tj_"
SAME_TEXTURE = 8.0


def _stem(name: str) -> str:
    return os.path.splitext(name.replace("\\", "/").split("/")[-1])[0]


def _find_dir(root: str, sub: str) -> Optional[str]:
    """``root/sub/sub`` (how the 7z archives unpack), else ``root/sub``."""
    for cand in (os.path.join(root, sub, sub), os.path.join(root, sub)):
        if os.path.isdir(cand):
            return cand
    return None


class Library:
    """Read-only view of an unpacked 'Torrente, el juego' folder (``nfos/ texs/ keys/ scns/`` in any nesting)."""

    def __init__(self, root: str):
        self.root = root
        self.dirs = {s: _find_dir(root, s) for s in ("nfos", "texs", "keys", "scns")}
        self._tex: Dict[str, Optional[object]] = {}
        self._tex_index: Dict[str, str] = {}
        if self.dirs["texs"]:
            for dp, _, fn in os.walk(self.dirs["texs"]):
                for f in fn:
                    if f.lower().endswith(".tex"):
                        self._tex_index[_stem(f).lower()] = os.path.join(dp, f)

    def _list(self, sub: str, ext: str) -> List[str]:
        d = self.dirs.get(sub)
        out = []
        if d:
            for dp, _, fn in os.walk(d):
                for f in fn:
                    if f.lower().endswith(ext):
                        out.append(os.path.relpath(os.path.join(dp, f), d).replace("\\", "/"))
        return sorted(out, key=str.lower)

    def models(self) -> List[str]:
        return self._list("nfos", ".nfo")

    def scenes(self) -> List[str]:
        return self._list("scns", ".scn")

    def has_nfos_file(self, rel: str) -> bool:
        """Case-insensitive existence test of ``nfos/<rel>`` (accepts a leading 'nfos/')."""
        if not hasattr(self, "_nfo_files"):
            self._nfo_files = {r.lower() for r in self._list("nfos", "")}
        r = rel.replace("\\", "/").lstrip("/")
        if r.lower().startswith("nfos/"):
            r = r[5:]
        return r.lower() in self._nfo_files

    def real_nfos_name(self, rel: str) -> Optional[str]:
        r = rel.replace("\\", "/").lstrip("/")
        if r.lower().startswith("nfos/"):
            r = r[5:]
        if not hasattr(self, "_nfo_case"):
            self._nfo_case = {x.lower(): x for x in self._list("nfos", "")}
        return self._nfo_case.get(r.lower())

    def maps(self) -> List[str]:
        return self._list("nfos", ".opt")

    def keys(self) -> List[str]:
        return self._list("keys", ".key")

    def textures(self) -> List[str]:
        return sorted(self._tex_index, key=str.lower)

    def path(self, sub: str, rel: str) -> str:
        return os.path.join(self.dirs[sub], rel)

    def texture(self, name: str):
        k = _stem(name).lower()
        if k not in self._tex:
            p = self._tex_index.get(k)
            self._tex[k] = Texture.load(p) if p else None
        return self._tex[k]


@dataclass
class Report:
    copied: List[str] = field(default_factory=list)
    reused: List[str] = field(default_factory=list)
    renamed: List[str] = field(default_factory=list)
    missing: List[str] = field(default_factory=list)

    def summary(self) -> str:
        return (f"{len(self.copied)} copied, {len(self.reused)} reused, {len(self.renamed)} renamed with '{PREFIX}', "
                f"{len(self.missing)} missing")


class Importer:
    def __init__(self, lib: Library, target_root: str, log: Callable[[str], None] = print):
        self.lib, self.root, self.log = lib, target_root, log
        self.report = Report()
        self._tex_map: Dict[str, str] = {}
        self._target_tex = self._index(os.path.join(target_root, "texs"), ".tex")

    @staticmethod
    def _index(d: str, ext: str) -> Dict[str, str]:
        out = {}
        for dp, _, fn in os.walk(d):
            for f in fn:
                if f.lower().endswith(ext):
                    out[_stem(f).lower()] = os.path.join(dp, f)
        return out

    # ---------------------------------------------------------------- textures
    def texture(self, name: str) -> str:
        """Make sure texture ``name`` exists in the target (converted to TeX2). Returns the stem to reference."""
        stem = _stem(name)
        k = stem.lower()
        if not k or k == "<null>":
            return name
        if k in self._tex_map:
            return self._tex_map[k]
        src = self.lib.texture(stem)
        if src is None:
            if k not in self._target_tex:
                self.report.missing.append(f"texture {stem}")
            self._tex_map[k] = stem
            return stem
        new = src.to_texture2() if isinstance(src, Texture1) else src
        final = stem
        if k in self._target_tex:
            old = Texture.load(self._target_tex[k])
            same = (old.width, old.height) == (new.width, new.height) and \
                float(np.abs(old.decode().astype(int) - new.decode().astype(int)).mean()) < SAME_TEXTURE
            if same:
                self.report.reused.append(f"texture {stem}")
                self._tex_map[k] = stem
                return stem
            final = PREFIX + stem
            self.report.renamed.append(f"texture {stem} -> {final}")
        else:
            self.report.copied.append(f"texture {stem}")
        dst = os.path.join(self.root, "texs", final + ".tex")
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        new.save(dst)
        self._target_tex[final.lower()] = dst
        self._tex_map[k] = final
        return final

    # ---------------------------------------------------------------- models
    def model(self, rel: str) -> str:
        """Import ``nfos/<rel>`` (+ its textures). Returns the relative name inside the target ``nfos`` folder."""
        nfo = Nfo.load(self.lib.path("nfos", rel))
        for obj in nfo.objects:
            for m in obj.materials:
                if not m.texture:
                    continue
                new = self.texture(m.texture)
                if new != _stem(m.texture):
                    ext = os.path.splitext(m.texture)[1]
                    cstrs = m.chunk.find("CSTR")
                    if len(cstrs) > 1:
                        cstrs[1].data = (new + ext).encode("latin-1") + b"\0"
                        m.texture = new + ext
        data = nfo.to_bytes()
        return self._write("nfos", rel, data)

    def _write(self, sub: str, rel: str, data: bytes) -> str:
        dst = os.path.join(self.root, sub, rel)
        if os.path.exists(dst):
            if open(dst, "rb").read() == data:
                self.report.reused.append(f"{sub}/{rel}")
                return rel
            d, f = os.path.split(rel)
            rel = os.path.join(d, PREFIX + f) if d else PREFIX + f
            dst = os.path.join(self.root, sub, rel)
            self.report.renamed.append(f"{sub}/{os.path.join(d, f)} -> {rel}")
        else:
            self.report.copied.append(f"{sub}/{rel}")
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, "wb") as fh:
            fh.write(data)
        return rel.replace("\\", "/")

    # ---------------------------------------------------------------- maps
    def map(self, rel: str, as_name: Optional[str] = None) -> str:
        """Import a level (.opt + same-named .hm if present). Returns the new .opt name inside ``nfos``."""
        opt = OptMap.load(self.lib.path("nfos", rel))
        for mesh in opt.meshes:
            for mat in mesh.materials:
                for i, t in enumerate(mat.textures):
                    if t:
                        new = self.texture(str(t))
                        if new != _stem(str(t)):
                            mat.textures[i] = new + os.path.splitext(str(t))[1]
        for d in opt.decals:
            if d.name:
                new = self.texture(d.name)
                if new != _stem(d.name):
                    d.name = new + os.path.splitext(d.name)[1]
        optconv.convert(opt)             # VTOP (old game) -> VTO1, the layout Online's own maps use
        target = (as_name + ".opt") if as_name else rel          # the converted level is named like the new scene
        new_rel = self._write("nfos", target, opt.to_bytes())
        hm = os.path.splitext(rel)[0] + ".hm"
        if os.path.exists(self.lib.path("nfos", hm)):
            with open(self.lib.path("nfos", hm), "rb") as f:
                self._write("nfos", os.path.splitext(new_rel)[0] + ".hm", f.read())
        return new_rel

    # ---------------------------------------------------------------- animations
    def keys(self, rels: List[str]) -> None:
        for rel in rels:
            with open(self.lib.path("keys", rel), "rb") as f:
                self._write("keys", rel, f.read())
