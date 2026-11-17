"""Editor logic without any GUI / OpenGL: loading, selection, editing, saving. Fully unit-testable."""
from __future__ import annotations

import copy
import math
import os
import shutil
from dataclasses import fields, is_dataclass
from typing import Callable, List, Optional

import numpy as np

from .. import vpk
from ..gamefs import GameFS
from ..modules import MODULE_TYPES, new_module, parse_modules
from ..opt import Decal, Light, LightType, OptMap, translate_mesh
from ..render.camera import FlyCamera, ray_aabb
from .. import catalog
from ..binutil import VStr
from .. import legacy
from ..importer import Importer, Library
from .. import gamemode
from .. import crop as cropmod
from ..render.geometry import SceneGeometry, bake_scene


class Selection:
    def __init__(self, kind: str, ref, label: str = ""):
        self.kind, self.ref, self.label = kind, ref, label


from .state_ext import EditOps, undoable
from .state_tools import ToolOps
from .state_build import BuildOps


class EditorState(EditOps, ToolOps, BuildOps):
    def __init__(self, root: str, log: Optional[Callable[[str], None]] = None):
        self.fs = GameFS(root)
        self.log = log or (lambda m: None)
        self.scene = None
        self.scene_name = ""
        self.opt: Optional[OptMap] = None
        self.geometry: Optional[SceneGeometry] = None
        self.selection: Optional[Selection] = None
        self.camera = FlyCamera()
        self.dirty_scene = False
        self.dirty_map = False
        self.needs_rebake = False
        self.library: Optional[Library] = None
        self._catalog = None

    # ---------------------------------------------------------------------------------- loading
    def scene_names(self) -> List[str]:
        return [p.split("/")[-1] for p in self.fs.list("scns", ".scn")]

    def load(self, name: str) -> None:
        self.fs.rescan()
        self.fs._opt.clear()                          # always reload maps from disk
        self.scene = self.fs.scene(name)
        self.scene_name = name
        try:
            self.opt = self.fs.map(legacy.resolve_map(self.scene, lambda n: self.fs.find(n) is not None))
        except FileNotFoundError:                    # the scene points to a .opt that is not in the game files
            self.opt = OptMap()
            self.log(f"WARNING: map '{self.scene.map_name}' not found - pick another one with 'Load Map'")
        self.selection = None
        self.hm_edit = None
        self.load_locks()
        self.load_hidden()
        self.dirty_scene = self.dirty_map = False
        self.bake()
        self.place_camera_at_spawn()
        self.log(f"loaded {name}: {self.geometry.stats}")

    hide_kinds: set = None

    def bake(self) -> None:
        if self.hide_kinds is None:
            self.hide_kinds = set()
        self._forget_lock_keys()                    # meshes / props may have moved: lock keys are recomputed
        self.geometry = bake_scene(self.fs, self.scene, self.opt, hide=frozenset(getattr(self, "hide_kinds", ())),
                                   skip=frozenset(getattr(self, "skip_recs", ())) | self.hidden_ids(),
                                   hide_models=frozenset(getattr(self, "hide_models", ())))
        self.needs_rebake = False

    def place_camera_at_spawn(self) -> None:
        sp = [r.parsed for r in self.scene.modules if r.parsed is not None and r.clean_name.lower() == "mp_cstartpoint"]
        if sp:
            p = np.array(sp[0].position, np.float64) * [1, 1, -1] + [0, 170, 0]
            self.camera.pos = p
            self.camera.yaw = float(np.degrees(np.arctan2(-np.cos(sp[0].angle), np.sin(sp[0].angle))))
            self.camera.pitch = -3.0

    # ---------------------------------------------------------------------------------- picking
    def pick(self, origin, direction) -> Optional[Selection]:
        return self.pick_hit(origin, direction)[0]

    def map_names(self) -> List[str]:
        return [p.split("/")[-1] for p in self.fs.list("nfos", ".opt")]

    def load_map(self, name: str) -> None:
        """Use another .opt with the current scene (rewrites the scene's map field on save)."""
        self.opt = self.fs.map("nfos\\" + name)
        self.scene.map_name = "nfos\\" + name
        self.dirty_scene = True
        self.selection = None
        self.bake()
        self.log(f"map -> {name}")

    def scene_textures(self) -> List[str]:
        """Texture names used by the baked scene (+ decals), in first-use order."""
        seen, out = set(), []
        names = [b.texture for b in self.geometry.opaque] + list(self.geometry.tex_names)
        names += [d.name for d in (self.opt.decals if self.opt else [])]
        for n in names:
            k = os.path.splitext(n.replace("\\", "/").split("/")[-1])[0].lower()
            if k and k not in seen:
                seen.add(k); out.append(n)
        return out

    def _delete_prop_old(self, prop) -> None:
        i = next((k for k, p in enumerate(self.opt.props) if p is prop), None)
        if i is None:
            return
        cropmod.remove_props(self.opt, {i})
        self.dirty_map = self.needs_rebake = True
        self.selection = None

    def delete_light(self, l) -> None:
        self.opt.lights[:] = [x for x in self.opt.lights if x is not l]
        self.dirty_map = True

    def delete_decal(self, d) -> None:
        cropmod.remove_decal(self.opt, d)
        self.dirty_map = self.needs_rebake = True

    def reload_fs(self) -> None:
        self.fs.rescan()
        self.fs._tex.clear()

    def markers(self, all_kinds: bool = False):
        """Invisible-in-the-game objects drawn as debug boxes: (kind, module_record, engine position, half extents).
        ``all_kinds`` also returns health packs / flags (which are normally drawn as models)."""
        out = []
        hidden = self._hidden()
        for rec in (self.scene.modules if self.scene else []):
            p = rec.parsed
            n = rec.clean_name.lower()
            if p is None or (hidden and self.lock_key(rec) in hidden):       # hidden in the editor: no box either
                continue
            if n == "mp_cstartpoint":
                out.append(("start point", rec, p.position, np.array([37.5, 7.5, 37.5])))
            elif n == "mp_camerastartposition":
                out.append(("camera", rec, p.position, np.array([40.0, 40.0, 40.0])))
            elif n == "mp_soundsource":
                out.append(("sound", rec, p.position, np.array([30.0, 30.0, 30.0])))
            elif n == "cparticlesystem":
                out.append(("particles", rec, p.position, np.array([25.0, 25.0, 25.0])))
            elif n == "mp_salud":                       # health packs: always a box too (easy to see and to click)
                out.append((n, rec, p.transform[3, :3] + [0.0, 20.0, 0.0], np.array([25.0, 25.0, 25.0])))
            elif n == "mp_flag" and (all_kinds or not self.geometry.stats.get("models")):
                out.append((n, rec, p.transform[3, :3], np.array([25.0, 25.0, 25.0])))
        return out

    # ---------------------------------------------------------------------------------- editing
    def position_of(self, sel: Selection) -> np.ndarray:
        r = sel.ref
        if sel.kind == "prop":
            return r.transform[3, :3].astype(np.float64)
        if sel.kind == "module":
            p = r.parsed
            return np.array(p.position, np.float64)
        if sel.kind == "mesh":
            return r.world_transform[3, :3].astype(np.float64)
        raise ValueError(sel.kind)

    def set_position(self, sel: Selection, pos) -> None:
        if self.blocked_by_lock(sel):
            return
        pos = np.asarray(pos, np.float64)
        r = sel.ref
        if sel.kind == "prop":
            r.transform[3, :3] = pos
            self.dirty_map = True
        elif sel.kind == "module":
            p = r.parsed
            # only a real matrix FIELD can be written in place (sounds / particle emitters compute theirs from `position`)
            if "transform" in getattr(p, "__dataclass_fields__", {}) and isinstance(p.transform, np.ndarray) \
                    and not hasattr(p, "angle"):
                p.transform[3, :3] = pos
            else:
                p.position = tuple(float(x) for x in pos)
            self.dirty_scene = True
        elif sel.kind == "mesh":
            translate_mesh(r, pos - self.position_of(sel))
            self.dirty_map = True
        self.needs_rebake = True

    def set_transform(self, sel: Selection, matrix) -> None:
        if self.blocked_by_lock(sel):
            return
        if sel.kind == "prop":
            sel.ref.transform = np.asarray(matrix, np.float32)
            self.dirty_map = True
        elif sel.kind == "module" and hasattr(sel.ref.parsed, "transform") and not hasattr(sel.ref.parsed, "angle"):
            sel.ref.parsed.transform = np.asarray(matrix, np.float32)
            self.dirty_scene = True
        else:
            raise ValueError("this object has no editable matrix")
        self.needs_rebake = True

    def can_rotate(self, sel: Selection) -> bool:
        if sel.kind == "prop":
            return True
        p = getattr(sel.ref, "parsed", None) if sel.kind == "module" else None
        return p is not None and (hasattr(p, "angle") or isinstance(getattr(p, "transform", None), np.ndarray))

    def rotate_selection(self, sel: Selection, euler_deg) -> None:
        """Rotate about the object's own origin by ``euler_deg`` (degrees about world X, Y, Z). Scale / position stay."""
        from ..render.camera import compose
        if self.blocked_by_lock(sel):
            return
        d = np.asarray(euler_deg, np.float64)
        if sel.kind == "module" and hasattr(sel.ref.parsed, "angle"):      # start points only have a yaw
            sel.ref.parsed.angle = float(sel.ref.parsed.angle + np.radians(d[1]))
            self.dirty_scene = True
        else:
            obj = sel.ref if sel.kind == "prop" else sel.ref.parsed
            m = np.asarray(obj.transform, np.float64)
            rd = compose([0, 0, 0], d, [1, 1, 1])[:3, :3]
            new = m.copy()
            new[:3, :3] = m[:3, :3] @ rd
            obj.transform = new.astype(np.float32)
            if sel.kind == "prop":
                self.dirty_map = True
            else:
                self.dirty_scene = True
        self.needs_rebake = True

    def add_module(self, kind: str, object_name: str):
        object_name = gamemode.unique_name(self.scene, object_name)
        rec = new_module(self.scene, kind, object_name)
        self._template_tail(rec)
        self.dirty_scene = True
        self.needs_rebake = True
        return rec

    def _template_tail(self, rec) -> None:
        """Kinds without a known default tail (buttons, bomb, wagons, fans...) copy the tail of a module of the same kind from
        another scene: an empty / wrong tail makes the game crash while loading."""
        from ..modules import DEFAULT_TAIL, ModelModule
        p = rec.parsed
        kind = rec.clean_name.lower()
        if not isinstance(p, ModelModule) or p.tail or kind in DEFAULT_TAIL or kind in ("mp_salud", "mp_flag"):
            return
        cache = self.__dict__.setdefault("_tails", {})
        if kind not in cache:
            cache[kind] = None
            for path in self.fs.list("scns", ".scn"):
                try:
                    sc = self.fs.scene(os.path.basename(path))
                except Exception:
                    continue
                hit = next((r.parsed.tail for r in sc.modules if r.clean_name.lower() == kind and r.parsed is not None
                            and getattr(r.parsed, "tail", b"")), None)
                if hit:
                    cache[kind] = bytes(hit)
                    break
        if cache[kind]:
            p.tail = cache[kind]
            self.log(f"{rec.clean_name}: tail copied from an existing scene ({len(p.tail)} bytes)")
        else:
            self.log(f"WARNING: no template for {rec.clean_name}: it may crash the game; copy an existing one instead")

    def duplicate_module(self, rec):
        i = next(k for k, m in enumerate(self.scene.modules) if m is rec)
        c = copy.copy(rec)
        c.parsed = copy.deepcopy(rec.parsed)
        c.data = rec.data
        old = str(rec.object_name).rstrip("\0")
        base = "CStartPoint" if rec.clean_name.lower() == "mp_cstartpoint" else old
        c.object_name = VStr((gamemode.unique_name(self.scene, base if base != old else old) + "\0").encode("cp1252"))
        if base == "CStartPoint":
            c.object_name = VStr((gamemode._new_name(self.scene, "CStartPoint") + "\0").encode("cp1252"))
        self.scene.modules.insert(i + 1, c)
        self.dirty_scene = self.needs_rebake = True
        return c

    def delete_module(self, rec) -> None:
        if self.is_locked(rec):
            self.log(f"'{str(rec.object_name).rstrip(chr(0))}' is locked - open its padlock to delete it")
            return
        self.scene.modules[:] = [m for m in self.scene.modules if m is not rec]
        if self.selection and self.selection.ref is rec:
            self.selection = None
        self.dirty_scene = self.needs_rebake = True

    # ---- game modes ---------------------------------------------------------------------------------
    def templates(self):
        if getattr(self, "_tpl", None) is None:
            self._tpl = gamemode.Templates(os.path.join(self.fs.root, "scns"))
        return self._tpl

    def _here(self):
        return self.camera.pos * np.array([1, 1, -1])      # engine coordinates of the camera

    def _gm_done(self, rec):
        if rec is not None:
            self.dirty_scene = self.needs_rebake = True
        return rec

    def game_mode(self):
        return gamemode.mode_of(self.scene)

    def set_game_mode(self, code: str) -> None:
        gamemode.set_mode(self.scene, code)
        self.dirty_scene = True

    def _look_engine(self):
        """Unit vector of where the editor camera looks, in engine coordinates (the view mirrors Z)."""
        f = np.asarray(self.camera.front, np.float64)
        return np.array([f[0], f[1], -f[2]])

    def gm_add_start(self, team: int):
        d = self._look_engine()
        # start points look along (sin angle, cos angle) in engine (x, z)
        ang = math.atan2(d[0], d[2]) if math.hypot(d[0], d[2]) > 1e-6 else 0.0
        return self._gm_done(gamemode.add_start_point(self.scene, self._here(), ang, team))

    def gm_add_health(self, size: str = "big"):
        return self._gm_done(gamemode.add_health(self.scene, self.templates(), self._here(), size))

    def gm_add_flag(self, team: int):
        return self._gm_done(gamemode.add_flag(self.scene, self.templates(), self._here(), team))

    def gm_add_simple(self, kind: str, base: str):
        return self._gm_done(gamemode.add_simple(self.scene, self.templates(), kind, self._here(), base))

    def gm_add_camera(self):
        eye = self._here()
        target = eye + self._look_engine() * 1000.0
        return self._gm_done(gamemode.add_camera(self.scene, [float(x) for x in eye], [float(x) for x in target]))

    def gm_fill(self, n: int = 14):
        gamemode.ring_of_starts(self.scene, self._here(), n)
        self.dirty_scene = self.needs_rebake = True

    def gm_check(self):
        out = gamemode.check(self.scene)
        # start points must lie over the map: one at (0,0,0) or far outside it was one of the causes of a scene the game refused
        try:
            pts = np.concatenate([np.asarray(m.corners, np.float64).reshape(-1, 3) for m in self.opt.meshes])
            lo, hi = pts.min(0), pts.max(0)
            for r in self.scene.modules:
                p = r.parsed
                if r.clean_name == "mp_CStartPoint" and p is not None:
                    x, y, z = p.position
                    if not (lo[0] <= x <= hi[0] and lo[2] <= z <= hi[2]):
                        out.append(f"start point '{str(r.object_name).rstrip(chr(0))}' at ({x:.0f}, {y:.0f}, {z:.0f}) is outside the map.")
        except Exception:
            pass
        return out

    def set_music(self, name: str) -> None:
        self.scene.ambient_music = VStr((name + "\0").encode("cp1252"))
        self.dirty_scene = True

    # ---- inspection --------------------------------------------------------------------------------
    @staticmethod
    def _slab(origin, direction, lo, hi):
        """Vectorised ray / box test. Returns (hit mask, entry distance)."""
        d = np.where(np.abs(direction) < 1e-12, 1e-12, direction)
        t1, t2 = (lo - origin) / d, (hi - origin) / d
        tmin, tmax = np.minimum(t1, t2).max(axis=1), np.maximum(t1, t2).min(axis=1)
        return tmax >= np.maximum(tmin, 0.0), np.maximum(tmin, 0.0)

    BIG_MESH = 8000.0       # a static mesh wider than this (the ground) only wins when nothing else is under the pointer

    def pick_hit(self, origin, direction):
        """Nearest thing under a ray: (Selection | None, distance). Fast enough to run while the mouse moves."""
        origin, direction = np.asarray(origin, np.float64), np.asarray(direction, np.float64)
        cand = []                                  # (t, big, payload)
        g = self.geometry
        if g is not None and g.instances:
            if getattr(self, "_pick_cache", (None,))[0] is not g:
                self._pick_cache = (g, np.array([i.lo for i in g.instances], np.float64),
                                    np.array([i.hi for i in g.instances], np.float64))
            _, lo, hi = self._pick_cache
            ok, t = self._slab(origin, direction, lo, hi)
            for i in np.where(ok)[0]:
                inst = g.instances[i]
                if self.is_locked(inst.ref, inst.kind):
                    continue                       # padlock closed: cannot be picked
                big = inst.kind == "mesh" and float(np.max(hi[i] - lo[i])) > self.BIG_MESH
                cand.append((float(t[i]), big, inst, float(np.max(hi[i] - lo[i]))))
        mk = self.markers()
        if mk:
            c = np.array([np.array(m[2]) * [1, 1, -1] for m in mk], np.float64)
            h = np.array([np.broadcast_to(np.asarray(m[3], np.float64), (3,)) for m in mk])
            ok, t = self._slab(origin, direction, c - h, c + h)
            for i in np.where(ok)[0]:
                if self.is_locked(mk[i][1]):
                    continue
                cand.append((float(t[i]), False, (mk[i][0], mk[i][1]), float(2 * np.max(h[i]))))
        if not cand:
            return None, 0.0
        mods = [c for c in cand if isinstance(c[2], tuple) or c[2].kind == "module"]   # modules (cars, start points, health...) win over map geometry
        small = mods or [c for c in cand if not c[1]]
        # nearest wins; among about equally near ones the smaller object (a wall beats the room that contains it)
        t, _, best, _ = min(small or cand, key=lambda c: c[0] + 0.002 * c[3])
        if isinstance(best, tuple):
            return Selection("module", best[1], best[0]), t
        return Selection(best.kind, best.ref, best.label), t

    def describe(self, sel) -> List[str]:
        """Short human readable lines about a picked thing (hover tooltip)."""
        if sel is None:
            return []
        out = [f"{sel.kind}: {sel.label}"]
        try:
            x, y, z = self.position_of(sel)
            out.append(f"position  X {x:.0f}  Y {y:.0f}  Z {z:.0f}")
        except Exception:
            pass
        r = sel.ref
        if sel.kind == "module":
            out.append(f"module: {r.clean_name}   name: {str(r.object_name).rstrip(chr(0))}")
            p = r.parsed
            if p is not None:
                mn = getattr(p, "model_name", "")
                if mn:
                    out.append(f"model: {mn}")
                for k, v in self.editable_fields(p)[:6]:
                    if k != "model_name":
                        out.append(f"{k}: {v}")
        elif sel.kind == "prop":
            out.append(f"instance of mesh {r.mesh_index}")
            me = self.opt.meshes[r.mesh_index] if self.opt and 0 <= r.mesh_index < len(self.opt.meshes) else None
            if me is not None:
                out.append("textures: " + ", ".join(sorted({str(t) for m in me.materials for t in m.textures[:1]})[:4]))
        elif sel.kind == "mesh":
            out.append(f"{len(r.materials)} materials")
            out.append("textures: " + ", ".join(sorted({str(t) for m in r.materials for t in m.textures[:1]})[:4]))
        return out

    # ---- sky -----------------------------------------------------------------------------------------
    def sky_options(self):
        """[(sky texture, [scenes of the game that use it], (fog colour, near, far) of the first of them)], most used first."""
        if getattr(self, "_skies", None) is None:
            by = {}
            for n in self.scene_names():
                try:
                    sc = self.fs.scene(n)
                except Exception:
                    continue
                k = str(sc.sky_texture).rstrip("\0")
                if k:
                    by.setdefault(k, ([], (tuple(sc.fog_color), sc.fog_near, sc.fog_far)))[0].append(n)
            used = {k.lower() for k in by}
            for path in self.fs.list("texs", ".tex"):               # every texture called cielo*: usable as a sky too
                base = os.path.basename(path)
                if base.lower().startswith("cielo") and base.lower() not in used:
                    by[base] = ([], None)
            self._skies = sorted(((k, v[0], v[1]) for k, v in by.items()), key=lambda t: (-len(t[1]), t[0].lower()))
        return self._skies

    def set_sky(self, name: str, with_fog: bool = False) -> None:
        self.scene.sky_texture = VStr((name + "\0").encode("cp1252"))
        if with_fog:
            for k, _, fog in self.sky_options():
                if k == name and fog is not None:
                    self.scene.fog_color, self.scene.fog_near, self.scene.fog_far = tuple(fog[0]), fog[1], fog[2]
        self.dirty_scene = True

    # ---- crop to an outline ------------------------------------------------------------------------------
    def crop_to_outline(self, poly_engine_xz, keep_inside: bool = True):
        """Cut the map and the scene to the polygon (engine X, Z). Returns the report; ``undo_crop`` restores."""
        self._crop_undo = (copy.deepcopy(self.opt), list(self.scene.modules), self.dirty_map, self.dirty_scene)
        rep = cropmod.crop_map(self.opt, poly_engine_xz, keep_inside)
        poly = np.asarray(poly_engine_xz, np.float64)
        keep, gone = [], 0
        for rec in self.scene.modules:
            p = rec.parsed
            if p is None or rec.clean_name.lower() == "mp_camerastartposition":
                keep.append(rec); continue
            try:
                x, _, z = self.position_of(Selection("module", rec, ""))
            except Exception:
                keep.append(rec); continue
            inside = bool(cropmod.points_in_polygon(np.array([[x, z]]), poly)[0])
            if inside == keep_inside:
                keep.append(rec)
            else:
                gone += 1
        self.scene.modules = keep
        rep.modules_removed = gone
        self.selection = None
        self.dirty_map = self.dirty_scene = self.needs_rebake = True
        self.log("crop: " + rep.summary())
        return rep

    def can_undo_crop(self) -> bool:
        return getattr(self, "_crop_undo", None) is not None

    def undo_crop(self) -> None:
        if not self.can_undo_crop():
            return
        self.opt, mods, self.dirty_map, self.dirty_scene = self._crop_undo
        self.scene.modules = mods
        self._crop_undo = None
        self.selection = None
        self.needs_rebake = True

    def add_light(self, kind: LightType) -> Light:
        l = Light(type=kind, position=np.array(self.camera.pos * [1, 1, -1], np.float32), start=0.0, end=1000.0,
                  radius=1000.0)
        self.opt.lights.append(l)
        self.dirty_map = True
        return l

    def add_decal(self, name: str) -> Decal:
        d = Decal(name=name, position=np.array(self.camera.pos * [1, 1, -1], np.float32), scale_x=100.0, scale_y=100.0)
        cropmod.add_decal(self.opt, d)
        self.dirty_map = True
        return d

    # ---------------------------------------------------------------------------------- 'Torrente, el juego' library
    def set_library(self, path: str) -> Library:
        lib = Library(path)
        if not lib.models() and not lib.maps():
            raise FileNotFoundError(f"no nfos/ folder with models or maps found in {path}")
        self.library = lib
        self.log(f"library: {len(lib.models())} models, {len(lib.maps())} maps, {len(lib.textures())} textures, "
                 f"{len(lib.keys())} animations")
        return lib

    # ---------------------------------------------------------------------------------- module kind -> models
    def catalog(self, refresh: bool = False):
        """{module kind -> {model -> uses}} from this game's scenes (+ the library's scenes when one is loaded)."""
        if self._catalog is None or refresh:
            scenes = list(catalog.load_scenes(os.path.join(self.fs.root, "scns")))
            lib_scn = self.library.dirs.get("scns") if self.library else None
            own = catalog.build(scenes)
            lib = catalog.build(catalog.load_scenes(lib_scn)) if lib_scn else {}
            self._catalog = (own, lib)
        return self._catalog

    def kinds_with_models(self) -> List[str]:
        """Typed module kinds that carry a model and can be created from the editor, most used first."""
        from ..modules import MODULE_TYPES
        own, lib = self.catalog()
        ok = [k for k, c in MODULE_TYPES.items() if hasattr(c, "model_name") or "model_name" in getattr(c, "__dataclass_fields__", {})]
        total = lambda k: sum(own.get(k, {}).values()) + sum(lib.get(k, {}).values())
        return sorted(ok, key=lambda k: -total(k))

    def models_for(self, kind: str, include_library: bool = False):
        """[(model 'nfos/X.NFO', uses, source)] for a module kind. source = 'game' (already in the folder) or 'lib'."""
        own, lib = self.catalog()
        have = {n.lower(): n for n in self.nfo_names()}
        rows = {}
        for m, c in own.get(kind, {}).items():
            if m.lower() in have:
                rows[m.lower()] = [have[m.lower()], c, "game"]
        if include_library and self.library:
            libnames = {("nfos/" + n).lower(): "nfos/" + n for n in self.library.models()}
            for m, c in lib.get(kind, {}).items():
                key = m.lower()
                if key in rows:
                    rows[key][1] += c
                elif key in libnames:
                    rows[key] = [libnames[key], c, "lib"]
        return sorted(rows.values(), key=lambda r: (-r[1], r[0].lower()))

    def nfo_names(self) -> List[str]:
        """Every .nfo of the game folder as 'nfos/<name>.NFO' (the form scenes use in model_name)."""
        return sorted((os.path.relpath(self.fs.index[k], self.fs.root).replace("\\", "/") for k in self.fs.list("nfos", ".nfo")),
                      key=str.lower)

    def preview_geometry(self, model_name: str, distance: float = 700.0):
        """Bake a single model, placed ``distance`` units in front of the camera, for the 3D model browser."""
        from ..modules import new_module
        from ..opt import OptMap
        from ..scn import Scene
        sc = Scene()
        rec = new_module(sc, "rendernfo", "preview")
        rec.parsed.model_name = model_name
        rec.parsed.transform[3, :3] = (self.camera.pos + self.camera.front * distance) * [1, 1, -1]
        g = bake_scene(self.fs, sc, OptMap())
        return g, rec

    def import_model(self, rel: str):
        imp = Importer(self.library, self.fs.root, self.log)
        new = imp.model(rel)
        self.fs.rescan(); self.fs._tex.clear()
        self.log(f"imported {rel}: {imp.report.summary()}")
        return new, imp.report

    def place_model(self, nfo_rel: str, kind: str = "rendernfo"):
        """Add a module of ``kind`` (RenderNFO by default) using ``nfos/<nfo_rel>``, 600 units in front of the camera."""
        base = os.path.splitext(os.path.basename(nfo_rel))[0]
        rec = self.add_module(kind, gamemode._new_name(self.scene, base))
        rec.parsed.model_name = "nfos/" + nfo_rel.replace("\\", "/")
        keys = self.key_candidates(nfo_rel)
        if keys:                                    # animated objects only move when the module names their .KEY
            self.set_module_key(rec, keys[0])
            self.log(f"{rec.clean_name}: animation {keys[0]} assigned" + (f" (other candidates: {', '.join(keys[1:4])})" if len(keys) > 1 else ""))
        pos = (self.camera.pos + self.camera.front * 600.0) * [1, 1, -1]
        rec.parsed.transform[3, :3] = pos
        if self.default_sound_for(nfo_rel):             # the helicopter comes with its rotor sound, as in mp_dm_asalto
            self.add_model_sound(rec)
        self.selection = Selection("module", rec, rec.object_name)
        return rec

    def convert_scene(self, scene_rel: str, new_name: str, mode: str = "DM"):
        """Convert a scene of the library (Torrente, el juego) into an Online scene; returns (file name, text report)."""
        from ..convert import Converter
        prefix = gamemode.MODES[mode][2]
        names = [n for n in self.scene_names() if n.lower().startswith(prefix)]
        tpl = self.fs.scene(names[0]) if names else self.scene     # an Online scene of that mode gives sky / fog / camera
        cv = Converter(self.library, self.fs.root, tpl, self.log)
        name = cv.convert(scene_rel, new_name, mode)
        self.fs.rescan(); self.fs._tex.clear()
        self.log(f"converted {scene_rel} -> {name}")
        return name, cv.summary()

    def import_map(self, rel: str, as_name: Optional[str] = None):
        """``as_name``: the imported .opt / .hm get the name of the scene they are made for."""
        imp = Importer(self.library, self.fs.root, self.log)
        new = imp.map(rel, as_name or None)
        self.fs.rescan(); self.fs._tex.clear()
        self.log(f"imported map {rel}: {imp.report.summary()}")
        return new, imp.report

    def map_start_hint(self, opt_rel: str):
        """Where the player starts in the old game's scene that uses this map (engine coordinates), or None."""
        if self.library is None:
            return None
        import struct
        from ..scn import Scene
        want = os.path.splitext(os.path.basename(opt_rel))[0].lower()
        exists = lambda n: self.library.has_nfos_file(n)
        for sname in self.library.scenes():
            try:
                old = Scene.load(self.library.path("scns", sname))
                got = legacy.resolve_map(old, exists)
            except Exception:
                continue
            if got and os.path.splitext(os.path.basename(str(got)))[0].lower() == want:
                for rec in old.modules:
                    if rec.clean_name.lower() == "ctorrente":
                        n = struct.unpack_from("<I", rec.data, 0)[0]
                        m = np.frombuffer(rec.data, "<f4", 16, 4 + n).reshape(4, 4)
                        return m[3, :3].astype(np.float64)
        return None

    def new_scene(self, name: str, opt_rel: str, mode: str = "DM") -> str:
        """Create ``scns/<name>.scn`` for an imported map: settings of an Online scene of the chosen mode, plus the modules a
        playable scene needs (start points of both teams, camera, health packs, flags / bomb zone). They are put where the
        player starts in the old game's scene of that map when the library has it, otherwise where the camera is."""
        if not name.lower().endswith(".scn"):
            name += ".scn"
        path = os.path.join(self.fs.root, "scns", name)
        if os.path.exists(path):
            raise FileExistsError(path)
        names = [n for n in self.scene_names() if n.lower().startswith(gamemode.MODES[mode][2])]
        sc = copy.deepcopy(self.fs.scene(names[0]) if names else self.scene)
        sc.modules = []
        sc.path = path
        sc.map_name = "nfos\\" + opt_rel.replace("/", "\\")
        hm = os.path.splitext(opt_rel)[0] + ".hm"
        if os.path.exists(os.path.join(self.fs.root, "nfos", hm)):
            sc.heightmap_name = "nfos\\" + hm.replace("/", "\\")
        if sc.desc_level < 10:
            sc.desc_level = 10
        centre = self.map_start_hint(opt_rel)
        if centre is None:
            centre = self._here()
        gamemode.populate(sc, gamemode.Templates(os.path.join(self.fs.root, "scns")), centre, mode)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        sc.save(path)
        self.fs.rescan()
        self.log(f"created {path} ({mode}, start area {np.round(centre).tolist()})")
        return name

    # ---------------------------------------------------------------------------------- saving
    def _backup(self, path: str) -> None:
        bak = path + ".bak"
        if not os.path.exists(bak):
            shutil.copy2(path, bak)

    def save_scene(self) -> str:
        path = self.scene.path
        self._backup(path)
        self.scene.save(path)
        self.dirty_scene = False
        self.log(f"saved {path}")
        try:
            self.snapshot_history()                     # version history: the last 10 saves can be brought back
        except Exception as e:
            self.log(f"history not written: {e}")
        return path

    def save_map(self) -> str:
        """Write the edited map.  It always goes to this map's OWN files: a .opt / .hm that other scenes also use (the Love
        Boat scenes share mp_dm_loveboat.opt / .hm, for instance) is left untouched and this map gets ``<map>.opt`` /
        ``<map>.hm`` instead, with the scene pointing at them."""
        cur = self.opt.path
        if not cur:
            self.log("this scene has no map file; nothing to save")
            return ""
        path = self.own_file(cur, "opt")
        if os.path.abspath(path) == os.path.abspath(cur):
            self._backup(path)
        else:
            self.log(f"{os.path.basename(cur)} is used by other maps ({', '.join(self.scenes_using(os.path.basename(cur))[:4])}): "
                     f"this map gets its own {os.path.basename(path)}")
        self.opt.save(path)
        self.opt.path = path
        want = "nfos\\" + os.path.basename(path)
        if str(self.scene.map_name).rstrip("\0") != want:
            self.scene.map_name = VStr((want + "\0").encode("cp1252"))
            self.dirty_scene = True
        self.dirty_map = False
        self.log(f"saved {path}")
        if getattr(self, "hm_edit", None) is None:       # the height map follows: own copy if it is shared too
            name = str(self.scene.heightmap_name).rstrip("\0").replace("\\", "/")
            cur_hm = self.fs.find(name) if name else None
            if cur_hm:
                tgt = self.own_file(cur_hm, "hm")
                if os.path.abspath(tgt) != os.path.abspath(cur_hm):
                    shutil.copy2(cur_hm, tgt)
                    self.scene.heightmap_name = VStr(("nfos\\" + os.path.basename(tgt) + "\0").encode("cp1252"))
                    self.dirty_scene = True
                    self.log(f"height map copied to {os.path.basename(tgt)} ({os.path.basename(cur_hm)} stays as it was)")
        self.flush_heightmap()                          # floor collision edited with the map (twin ships)
        self.fs.rescan()
        return path

    def save_map_as(self, name: str) -> str:
        """Write the (edited) map under a new name next to the current one, copy its .hm and point the scene at both.
        Use this after cropping so the original map, which other scenes share, stays untouched."""
        if not name.lower().endswith(".opt"):
            name += ".opt"
        src = self.opt.path
        folder = os.path.dirname(src) if src else os.path.join(self.fs.root, "nfos", "nfos")
        dst = os.path.join(folder, name)
        if os.path.exists(dst):
            raise FileExistsError(dst)
        self.opt.save(dst)
        hm_src = os.path.splitext(src)[0] + ".hm" if src else ""
        new_hm = os.path.splitext(name)[0] + ".hm"
        if getattr(self, "hm_edit", None) is not None:            # floor collision edited in memory (twin ships)
            self.hm_edit.save(os.path.join(folder, new_hm))
            self.hm_edit = None
            self.scene.heightmap_name = VStr(("nfos\\" + new_hm + "\0").encode("cp1252"))
        elif hm_src and os.path.exists(hm_src):
            shutil.copy2(hm_src, os.path.join(folder, new_hm))
            self.scene.heightmap_name = VStr(("nfos\\" + new_hm + "\0").encode("cp1252"))
        self.opt.path = dst
        self.scene.map_name = VStr(("nfos\\" + name + "\0").encode("cp1252"))
        self.fs.rescan()
        self.dirty_map = False
        self.dirty_scene = True
        self.log(f"saved map {dst}")
        return dst

    def repack(self, out_path: str) -> int:
        os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
        if os.path.isfile(out_path) and not os.path.exists(out_path + ".bak"):
            shutil.copy2(out_path, out_path + ".bak")      # never lose the original vpk
        n = vpk.repack(self.fs.root, out_path)
        self.log(f"packed {n} entries into {out_path}")
        return n

    # ---------------------------------------------------------------------------------- generic field access
    @staticmethod
    def editable_fields(obj):
        """(name, value) pairs of simple public fields of a typed module (str / int / float / tuple of floats)."""
        out = []
        if not is_dataclass(obj):
            return out
        for f in fields(obj):
            v = getattr(obj, f.name)
            if f.name in ("transform", "tail") or isinstance(v, (bytes, np.ndarray)):
                continue
            if isinstance(v, (str, int, float)) or (isinstance(v, tuple) and all(isinstance(x, float) for x in v)):
                out.append((f.name, v))
        return out


def _install_undo() -> None:
    plain = ("add_module", "duplicate_module", "delete_module", "place_model", "add_start", "set_transform", "gm_add_start",
             "gm_add_health", "gm_add_flag", "gm_add_simple", "gm_add_camera", "gm_fill", "set_sky")
    mapped = ("crop_to_outline", "load_map", "add_light", "add_decal", "delete_light", "delete_decal")
    for n in plain:
        if hasattr(EditorState, n):
            setattr(EditorState, n, undoable(False, n.replace("_", " "))(getattr(EditorState, n)))
    for n in mapped:
        if hasattr(EditorState, n):
            setattr(EditorState, n, undoable(True, n.replace("_", " "))(getattr(EditorState, n)))
    for n, label in (("set_position", "move"), ("rotate_selection", "rotate")):
        fn = getattr(EditorState, n)

        def make(fn, label):
            def wrapper(self, sel, *a, **k):
                self.push_undo(sel.kind != "module", label)
                return fn(self, sel, *a, **k)
            wrapper.__name__ = fn.__name__
            return wrapper
        setattr(EditorState, n, make(fn, label))


_install_undo()
