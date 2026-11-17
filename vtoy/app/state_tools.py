"""Editor tools (batch 6): map checker, floor-collision view, play in game, group selection, snapping, mirror / array copies,
collision editing, prefabs ("pieces"), map install / uninstall from the exported zip, version history and comparison.

Everything here works on an EditorState (mixin) and never overwrites a file another map uses."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import pickle
import shutil
import time
import zipfile
from typing import List, Optional

import numpy as np

from .. import crop as cropmod
from ..binutil import VStr

HISTORY_KEEP = 10


class _PieceUnpickler(pickle.Unpickler):
    """Pieces are pickles of the editor's own data classes and numpy arrays; nothing else may be loaded from a file
    (a piece downloaded from someone else must not be able to run code)."""
    _OK = {("builtins", n) for n in ("dict", "list", "tuple", "set", "frozenset", "bytes", "bytearray", "str", "int", "float",
                                     "bool", "complex", "slice", "range")}

    def find_class(self, module, name):
        if (module, name) in self._OK or module.split(".")[0] == "vtoy" or \
                (module.split(".")[0] == "numpy" and name in ("ndarray", "dtype", "_reconstruct", "scalar", "_frombuffer")):
            return super().find_class(module, name)
        raise pickle.UnpicklingError(f"this piece file contains something that is not editor data ({module}.{name})")
SPAWN_LIFT = 18.0          # start points stand this much above the floor (as in the shipped maps)


class PreviewFS:
    """What the model preview draws from: the game's files, or - while ``lib`` is set - the files of the 'Torrente, el
    juego' library first (so a library model is shown with its own textures before anything is imported)."""

    def __init__(self, fs):
        self.fs = fs
        self.lib = None
        self._models = {}

    @property
    def _tex(self):
        return self.fs._tex

    def texture(self, name):
        if self.lib is not None:
            try:
                t = self.lib.texture(name)
                if t is not None:
                    return t.to_texture2() if hasattr(t, "to_texture2") else t
            except Exception:
                pass
        return self.fs.texture(name)

    def model(self, name):
        if self.lib is not None:
            rel = str(name).replace("\\", "/").lstrip("/")
            if rel.lower().startswith("nfos/"):
                rel = rel[5:]
            key = (id(self.lib), rel.lower())
            if key not in self._models:
                m = None
                try:
                    real = self.lib.real_nfos_name(rel)
                    if real:
                        from ..nfo import NfoModel
                        m = NfoModel.load(self.lib.path("nfos", real))
                except Exception:
                    m = None
                self._models[key] = m
            if self._models[key] is not None:
                return self._models[key]
        return self.fs.model(name)


LIB_MODES = ("models", "maps", "scenes", "textures", "music")


class ToolOps:
    # ================================================================================== helpers
    def _floor_faces(self):
        """Up-facing floor faces of the height map in use (edited or on disk), cached by version."""
        from .. import hmcopy
        hm = getattr(self, "hm_edit", None)
        if hm is None:
            name = str(self.scene.heightmap_name).rstrip("\0").replace("\\", "/")
            p = self.fs.find(name) if name else None
            key = ("file", p, os.path.getmtime(p) if p and os.path.exists(p) else 0)
            if getattr(self, "_ff_key", None) != key:
                from ..hm import HeightMap
                self._ff_key, self._ff_hm = key, (HeightMap.load(p) if p else None)
            hm = self._ff_hm
        else:
            key = ("edit", id(hm), id(hm.root))
            if getattr(self, "_ff_key", None) != key:
                self._ff_key, self._ff_hm = key, hm
        if hm is None:
            return None, []
        if getattr(self, "_ff_faces_key", None) != self._ff_key:
            self._ff_faces_key = self._ff_key
            self._ff_faces = hmcopy.unique_faces(hm)
        return hm, self._ff_faces

    def floor_below(self, x: float, z: float, below: float) -> Optional[float]:
        """Highest floor (.hm) under (x, z) not above ``below`` (engine coordinates), or None."""
        from .. import flagbase, hmcopy
        _, faces = self._floor_faces()
        best = None
        for f in faces:
            nx, ny, nz = f.normal
            if ny < 0.5:
                continue
            x0, z0, x1, z1 = hmcopy.face_bounds(f)
            if not (x0 <= x <= x1 and z0 <= z <= z1):
                continue
            if not any(flagbase._point_in_poly(x, z, c) for c in f.contours):
                continue
            y = -(f.distance + nx * x + nz * z) / ny
            if y <= below and (best is None or y > best):
                best = float(y)
        return best

    def _sel(self, rec):
        from .state import Selection
        return Selection("module", rec, str(rec.object_name).rstrip("\0"))

    # ================================================================================== 1. map checker
    def validate_map(self) -> List[dict]:
        """Problems that crash the game or break play: [{level: error|warning, msg, pos (engine) | None}]."""
        from .. import regioncopy
        out = []

        def add(level, msg, pos=None):
            out.append({"level": level, "msg": msg, "pos": None if pos is None else np.asarray(pos, np.float64)})

        for p in self.scene_problems():
            add("error", p)
        # files the map needs
        try:
            self.map_dependencies()
            for m in getattr(self, "_missing_deps", []):
                ext = os.path.splitext(str(m))[1].lower()
                # without its map / floor / a model the game cannot load the scene; a texture or animation only looks wrong
                add("error" if ext in (".opt", ".hm", ".nfo", ".scn") else "warning", f"missing file: {m}")
        except Exception as e:
            add("warning", f"could not list the map's files: {e}")
        # DLLs that are not the game's own
        main = str(self.scene.main_module_name).rstrip("\0")
        if self.custom_dll_path():
            add("warning", f"mode DLL {main} is not a stock one: copy it into the game folder (server and players)")
        for p in self.custom_module_dlls():
            add("warning", f"{os.path.basename(p)} must be in the game folder (server and players)")
        # players / items need floor under them
        hm, faces = self._floor_faces()
        if hm is None:
            add("error", "the scene has no height map (.hm): nobody can stand anywhere")
        teams = {}
        for r in self.scene.modules:
            k = r.clean_name.lower()
            if k not in ("mp_cstartpoint", "mp_flag", "mp_salud") or r.parsed is None:
                continue
            try:
                pos = np.asarray(self.position_of(self._sel(r)), np.float64)
            except Exception:
                continue
            name = str(r.object_name).rstrip("\0")
            if k == "mp_cstartpoint":
                teams[r.parsed.team] = teams.get(r.parsed.team, 0) + 1
            if hm is not None:
                g = self.floor_below(pos[0], pos[2], pos[1] + 60.0)
                if g is None:
                    add("error", f"{name}: no floor under it (falls out of the map)", pos)
                elif pos[1] - g > 250.0:
                    add("warning", f"{name}: {pos[1] - g:.0f} above the floor", pos)
        mode = self.game_mode()
        if mode in ("DMT", "B", "DO"):
            for t in (0, 1):
                if not teams.get(t):
                    add("error", f"team {t} has no start points", None)
        if mode == "B":
            n = sum(1 for r in self.scene.modules if r.clean_name.lower() == "mp_flag")
            if n != 2:
                add("error", f"capture the flag needs 2 flags (found {n})")
        # everything inside the map's sector tree (outside = not drawn, no collision)
        try:
            blk = cropmod.read_block(self.opt)
            lo, hi = regioncopy.root_bounds(blk)
            for r in self.scene.modules:
                try:
                    pos = np.asarray(self.position_of(self._sel(r)), np.float64)
                except Exception:
                    continue
                if not (lo[0] - 1 <= pos[0] <= hi[0] + 1 and lo[2] - 1 <= pos[2] <= hi[2] + 1):
                    add("warning", f"{str(r.object_name).rstrip(chr(0))}: outside the map's sector area", pos)
        except Exception:
            pass
        if not out:
            add("ok", "no problems found")
        return out

    # ================================================================================== 2. floor collision view
    def hm_wire(self):
        """Display-space line segments of the .hm faces: (floors, walls, slopes), each (n, 2, 3) float32. Cached."""
        _, faces = self._floor_faces()
        key = getattr(self, "_ff_faces_key", None)
        if getattr(self, "_hmw_key", None) == key:
            return self._hmw
        segs = {"floor": [], "wall": [], "slope": []}
        for f in faces:
            ny = abs(f.normal[1])
            kind = "floor" if ny > 0.95 else ("wall" if ny < 0.3 else "slope")
            for c in f.contours:
                p = np.asarray(c, np.float32) * np.array([1, 1, -1], np.float32)
                p[:, 1] += 2.0 if kind != "wall" else 0.0
                segs[kind].append(np.stack([p, np.roll(p, -1, axis=0)], 1))
        self._hmw = tuple(np.concatenate(segs[k]) if segs[k] else np.zeros((0, 2, 3), np.float32)
                          for k in ("floor", "wall", "slope"))
        self._hmw_key = key
        return self._hmw

    # ================================================================================== 3. play in game
    def launch_game(self, exe: str, args: str = "") -> str:
        """Start the game (after the caller saved and repacked). The exe runs from its own folder."""
        import shlex
        import subprocess
        if not exe or not os.path.isfile(exe):
            raise ValueError("choose the game's .exe first")
        cmd = [exe] + (shlex.split(args, posix=False) if args.strip() else [])
        subprocess.Popen(cmd, cwd=os.path.dirname(exe))
        return "started " + " ".join(cmd)

    # ================================================================================== 4. group selection
    def multi_list(self) -> list:
        if getattr(self, "multi", None) is None:
            self.multi = []
        return self.multi

    def toggle_multi(self, sel) -> None:
        m = self.multi_list()
        for i, s in enumerate(m):
            if s.ref is sel.ref:
                del m[i]
                return
        if not self.blocked_by_lock(sel):
            m.append(sel)

    def _group(self) -> list:
        g = list(self.multi_list())
        if self.selection is not None and not any(s.ref is self.selection.ref for s in g):
            g.append(self.selection)
        return [s for s in g if not self.is_locked(s.ref, s.kind)]

    def group_move(self, offset, with_collision: bool = True) -> str:
        from .. import regioncopy
        off = np.asarray(offset, np.float64)
        g = self._group()
        if not g:
            raise ValueError("nothing selected")
        self.push_undo(True, "group move")
        self._undo_off = True
        try:
            nb = 0
            for s in g:
                bounds = self.engine_bounds(s) if (with_collision and s.kind in ("prop", "mesh")) else None
                self.set_position(s, np.asarray(self.position_of(s), np.float64) + off)
                if bounds is not None:
                    nb += regioncopy.move_boxes_in_box(self.opt, bounds[0] - 5.0, bounds[1] + 5.0, off)
        finally:
            self._undo_off = False
        self.needs_rebake = True
        return f"{len(g)} objects moved {np.round(off).tolist()}" + (f", {nb} collision boxes" if nb else "")

    def group_delete(self) -> str:
        g = self._group()
        self.push_undo(True, "group delete")
        self._undo_off = True
        try:
            for s in g:
                self.delete_selection(s, True)
        finally:
            self._undo_off = False
        self.multi = []
        self.selection = None
        return f"{len(g)} objects deleted"

    def group_lock(self, on: bool) -> str:
        g = list(self.multi_list()) + ([self.selection] if self.selection is not None else [])
        for s in g:
            self.set_locked(s.ref, on, s.kind)
        self.multi = []
        return f"{len(g)} objects {'locked' if on else 'unlocked'}"

    def select_in_box(self, lo, hi, kinds=("module", "prop")) -> int:
        """Add every object whose position is inside lo..hi (engine) to the group."""
        from .state import Selection
        lo, hi = np.asarray(lo, np.float64), np.asarray(hi, np.float64)
        n = 0
        if "module" in kinds:
            for r in self.scene.modules:
                try:
                    p = np.asarray(self.position_of(self._sel(r)), np.float64)
                except Exception:
                    continue
                if np.all(p >= lo) and np.all(p <= hi) and not self.is_locked(r):
                    self.multi_list().append(self._sel(r)); n += 1
        if "prop" in kinds:
            for k, pr in enumerate(self.opt.props):
                p = np.asarray(pr.transform, np.float64)[3, :3]
                if np.all(p >= lo) and np.all(p <= hi) and not self.is_locked(pr, "prop"):
                    self.multi_list().append(Selection("prop", pr, f"prop {k}")); n += 1
        return n

    # ================================================================================== 5. snapping
    def snap_position(self, sel, pos, grid: float = 0.0, floor: bool = True):
        p = np.asarray(pos, np.float64).copy()
        if grid and grid > 0:
            p[0] = round(p[0] / grid) * grid
            p[2] = round(p[2] / grid) * grid
        if floor:
            g = self.floor_below(p[0], p[2], p[1] + 120.0)
            if g is not None:
                lift = SPAWN_LIFT if (sel.kind == "module" and sel.ref.clean_name.lower() == "mp_cstartpoint") else 0.0
                p[1] = g + lift
        return p

    def snap_selection(self, grid: float = 0.0, floor: bool = True) -> str:
        g = self._group()
        if not g:
            raise ValueError("nothing selected")
        self.push_undo(any(s.kind != "module" for s in g), "snap")
        for s in g:
            self.set_position(s, self.snap_position(s, self.position_of(s), grid, floor))
        return f"{len(g)} objects snapped"

    # ================================================================================== 6. mirror / array copies
    @staticmethod
    def _mirror_matrix(m, axis: str, plane: float):
        S = np.diag([-1.0, 1.0, 1.0]) if axis == "x" else np.diag([1.0, 1.0, -1.0])
        out = np.asarray(m, np.float64).copy()
        out[:3, :3] = S @ out[:3, :3] @ S
        i = 0 if axis == "x" else 2
        out[3, i] = 2 * plane - out[3, i]
        return out.astype(np.float32)

    def mirror_copy(self, axis: str = "x", plane: float = 0.0, swap_team: bool = True) -> str:
        """Copy the selected objects to the other side of the plane x = plane (or z = plane), turned the mirrored way.
        Start points / flags / names can change team (rojo <-> amarillo, team 0 <-> 1)."""
        g = self._group()
        if not g:
            raise ValueError("nothing selected")
        self.push_undo(True, "mirror copy")
        self._undo_off = True
        made = []
        try:
            for s in g:
                new = self.duplicate_selection(s, (0.0, 0.0, 0.0))
                if new.kind == "module":
                    p = new.ref.parsed
                    if hasattr(p, "angle"):
                        pos = np.asarray(p.position, np.float64)
                        i = 0 if axis == "x" else 2
                        pos[i] = 2 * plane - pos[i]
                        p.position = tuple(float(v) for v in pos)
                        p.angle = float(-p.angle if axis == "x" else np.pi - p.angle)
                    elif isinstance(getattr(p, "transform", None), np.ndarray):
                        p.transform = self._mirror_matrix(p.transform, axis, plane)
                    if swap_team:
                        self._swap_team(new.ref, str(s.ref.object_name).rstrip("\0"))
                elif new.kind == "prop":
                    new.ref.transform = self._mirror_matrix(new.ref.transform, axis, plane)
                else:
                    lo, hi = self.engine_bounds(new) or (None, None)
                    if lo is not None:
                        from ..opt import translate_mesh
                        c = (lo + hi) / 2
                        d = np.zeros(3); i = 0 if axis == "x" else 2
                        d[i] = 2 * (plane - c[i])
                        translate_mesh(new.ref, d)
                made.append(new)
        finally:
            self._undo_off = False
        self.dirty_scene = self.dirty_map = self.needs_rebake = True
        self.multi = list(made)
        return f"{len(made)} mirrored copies (plane {axis} = {plane:.0f})"

    def _swap_team(self, rec, source_name: str = "") -> None:
        """Other team: team number, ROJO <-> AMARILLO in the name (taken from the object it was copied from) and flag model."""
        p = rec.parsed
        if hasattr(p, "team") and p.team in (0, 1):
            p.team = 1 - p.team
        name = source_name or str(rec.object_name).rstrip("\0")
        swaps = (("ROJO", "AMARILLO"), ("rojo", "amarillo"), ("Rojo", "Amarillo"), ("roja", "amarilla"), ("Roja", "Amarilla"))
        new = name
        for a, b in swaps:
            if a in name:
                new = name.replace(a, b); break
            if b in name:
                new = name.replace(b, a); break
        if new != name:
            from .. import gamemode
            rec.object_name = VStr((gamemode.unique_name(self.scene, new) + "\0").encode("cp1252"))
        mn = getattr(p, "model_name", None)
        if mn and isinstance(mn, str):
            for a, b in (("bandera_roja", "bandera_amarilla"),):
                if a in mn:
                    p.model_name = mn.replace(a, b)
                elif b in mn:
                    p.model_name = mn.replace(b, a)

    def array_copy(self, count: int, offset) -> str:
        """``count`` more copies of the selection, each ``offset`` further than the previous one."""
        g = self._group()
        if not g:
            raise ValueError("nothing selected")
        off = np.asarray(offset, np.float64)
        self.push_undo(True, "array copy")
        self._undo_off = True
        n = 0
        try:
            for s in g:
                for k in range(1, int(count) + 1):
                    self.duplicate_selection(s, off * k)
                    n += 1
        finally:
            self._undo_off = False
        return f"{n} copies"

    # ================================================================================== 7. measuring
    def pick_point(self, origin, direction):
        """Engine coordinates of the surface under a ray (or None)."""
        sel, t = self.pick_hit(origin, direction)
        if sel is None:
            return None
        d = np.asarray(origin, np.float64) + np.asarray(direction, np.float64) * t
        return d * [1, 1, -1]

    # ================================================================================== 8. collision editing
    def add_collision_box(self, centre, half) -> int:
        from .. import regioncopy
        self.push_undo(True, "add collision")
        i = regioncopy.add_box(self.opt, np.asarray(centre, np.float64), np.asarray(half, np.float64))
        self.dirty_map = True
        return i

    def boxes_near(self, point, radius: float = 600.0) -> list:
        """[(index, lo, hi)] of the collision boxes whose centre is within ``radius`` of point (engine), nearest first."""
        from .. import regioncopy
        p = np.asarray(point, np.float64)
        out = []
        for i, raw in enumerate(cropmod.read_block(self.opt).boxes):
            lo, hi = regioncopy._box_bounds(raw)
            d = float(np.linalg.norm((lo + hi) / 2 - p))
            if d <= radius:
                out.append((d, i, lo, hi))
        return [(i, lo, hi) for d, i, lo, hi in sorted(out, key=lambda t: t[0])]

    def delete_collision_box(self, idx: int) -> str:
        self.push_undo(True, "delete collision")
        cropmod.remove_collision_indices(self.opt, [int(idx)])
        self.dirty_map = True
        return f"collision box {idx} deleted"

    def add_floor_quad(self, centre, size_x: float, size_z: float) -> str:
        """A walkable rectangle in the height map (an invisible floor / a patch over a hole)."""
        from .. import hmcopy
        self.push_undo(True, "add floor")
        hm = self.heightmap_edit()
        c = np.asarray(centre, np.float64)
        hmcopy.add_faces(hm, [hmcopy.floor_quad(c[0] - size_x / 2, c[0] + size_x / 2, c[2] - size_z / 2, c[2] + size_z / 2, c[1])])
        self.dirty_map = True
        return f"floor {size_x:.0f} x {size_z:.0f} added at y {c[1]:.0f} - save the map"

    def add_wall(self, a, b, height: float = 200.0, thickness: float = 16.0) -> str:
        """An invisible wall from point a to point b (engine, on the floor): collision box + both .hm wall faces."""
        from .. import hmcopy, regioncopy
        a, b = np.asarray(a, np.float64), np.asarray(b, np.float64)
        self.push_undo(True, "add wall")
        # an axis-aligned wall along the longest direction
        d = b - a
        along_x = abs(d[0]) >= abs(d[2])
        y0 = min(a[1], b[1])
        if along_x:
            x0, x1 = sorted((a[0], b[0])); z = (a[2] + b[2]) / 2
            regioncopy.add_box(self.opt, [(x0 + x1) / 2, y0 + height / 2, z], [(x1 - x0) / 2, height / 2, thickness / 2])
            pts = np.array([(x0, y0, z), (x1, y0, z), (x1, y0 + height, z), (x0, y0 + height, z)], np.float32)
            faces = [hmcopy.make_face(pts, (0.0, 0.0, 1.0)), hmcopy.make_face(pts, (0.0, 0.0, -1.0))]
        else:
            z0, z1 = sorted((a[2], b[2])); x = (a[0] + b[0]) / 2
            regioncopy.add_box(self.opt, [x, y0 + height / 2, (z0 + z1) / 2], [thickness / 2, height / 2, (z1 - z0) / 2])
            pts = np.array([(x, y0, z0), (x, y0, z1), (x, y0 + height, z1), (x, y0 + height, z0)], np.float32)
            faces = [hmcopy.make_face(pts, (1.0, 0.0, 0.0)), hmcopy.make_face(pts, (-1.0, 0.0, 0.0))]
        try:
            hmcopy.add_faces(self.heightmap_edit(), faces)
        except ValueError:
            pass
        self.dirty_map = True
        return "invisible wall added - save the map"

    def collision_box(self, idx: int):
        """(centre, half extents) of collision box ``idx`` (engine coordinates, as stored)."""
        a = np.frombuffer(cropmod.read_block(self.opt).boxes[int(idx)], "<f4", 19).astype(np.float64)
        return a[12:15].copy(), a[16:19].copy()

    def set_collision_box(self, idx: int, centre, half) -> None:
        """Move / resize a collision box (its axes are kept); it is listed in the sectors of its new place too."""
        from .. import regioncopy
        self.push_undo(True, "edit collision")
        blk = cropmod.read_block(self.opt)
        a = np.frombuffer(blk.boxes[int(idx)], "<f4", 19).copy()
        a[12:15] = np.asarray(centre, np.float32)
        a[16:19] = np.maximum(np.asarray(half, np.float32), 1.0)
        blk.boxes[int(idx)] = a.astype("<f4").tobytes()
        lo, hi = regioncopy._box_bounds(blk.boxes[int(idx)])
        for sct in regioncopy._sectors_for(blk, lo, hi):
            if int(idx) not in sct.boxes:
                sct.boxes.append(int(idx))
        cropmod.write_block(self.opt, blk)
        self.dirty_map = True

    def pick_collision_box(self, origin, direction) -> Optional[int]:
        """Index of the nearest collision box under a view ray (display space), or None."""
        from .. import regioncopy
        from ..render.camera import ray_aabb
        o, d = np.asarray(origin, np.float64), np.asarray(direction, np.float64)
        key = (id(self.opt), len(self.opt.hulls_raw), self.opt.scene_obj_count, getattr(self, "_cb_ver", 0))
        raws = cropmod.read_block(self.opt).boxes
        best, bt = None, 1e30
        for i, raw in enumerate(raws):
            lo, hi = regioncopy._box_bounds(raw)
            dlo = np.array([lo[0], lo[1], -hi[2]]); dhi = np.array([hi[0], hi[1], -lo[2]])
            t = ray_aabb(o, d, dlo, dhi)
            if t is not None and 0 < t < bt:
                best, bt = i, t
        return best

    def add_ramp(self, low, high, width: float = 200.0) -> str:
        """A walkable slope in the height map from point ``low`` to point ``high`` (engine), ``width`` wide."""
        from .. import hmcopy
        a, b = np.asarray(low, np.float64), np.asarray(high, np.float64)
        d = b - a
        run = np.array([d[0], 0.0, d[2]])
        ln = float(np.linalg.norm(run))
        if ln < 1.0:
            raise ValueError("the two points are on top of each other")
        side = np.cross([0.0, 1.0, 0.0], run / ln) * (width / 2)
        pts = np.array([a - side, b - side, b + side, a + side], np.float64)
        n = np.cross(pts[1] - pts[0], pts[3] - pts[0])
        if n[1] < 0:
            n = -n
        n /= np.linalg.norm(n)
        area = 0.5 * float(np.sum(pts[:, 0] * np.roll(pts[:, 2], -1) - np.roll(pts[:, 0], -1) * pts[:, 2]))
        if area < 0:
            pts = pts[::-1].copy()
        self.push_undo(True, "add ramp")
        hmcopy.add_faces(self.heightmap_edit(), [hmcopy.HMFace(tuple(float(v) for v in n), -float(n @ pts[0]), [pts.astype(np.float32)])])
        self.dirty_map = True
        ang = float(np.degrees(np.arctan2(abs(d[1]), ln)))
        return f"ramp added: {ln:.0f} long, {abs(d[1]):.0f} high ({ang:.0f} degrees) - save the map"

    def floor_faces_near(self, point, radius: float = 400.0) -> list:
        """Height map faces whose centre is within ``radius`` of point (engine): [(face, kind, centre)] nearest first."""
        from .. import hmcopy
        p = np.asarray(point, np.float64)
        out = []
        for f in self._floor_faces()[1]:
            c = np.concatenate(f.contours).astype(np.float64).mean(0)
            dist = float(np.linalg.norm(c - p))
            if dist <= radius:
                ny = abs(f.normal[1])
                out.append((dist, f, "floor" if ny > 0.95 else ("wall" if ny < 0.3 else "slope"), c))
        return [(f, k, c) for _, f, k, c in sorted(out, key=lambda t: t[0])]

    def delete_floor_face(self, face) -> str:
        """Remove one face from the height map (the tree is rebuilt)."""
        from .. import hmcopy
        self.push_undo(True, "delete floor face")
        hm = self.heightmap_edit()
        key = (np.round(np.asarray(face.normal, np.float64), 4).tobytes(), round(float(face.distance), 3),
               np.round(np.concatenate(face.contours), 2).tobytes())
        keep = []
        gone = 0
        for f in hmcopy.unique_faces(hm):
            k = (np.round(np.asarray(f.normal, np.float64), 4).tobytes(), round(float(f.distance), 3),
                 np.round(np.concatenate(f.contours), 2).tobytes())
            if k == key:
                gone += 1
            else:
                keep.append(f)
        if not gone:
            raise ValueError("that face is not in the height map any more")
        hm.root = hmcopy.build_tree(keep, hmcopy.box(hm.root), max(hmcopy.tree_depth(hm.root), 1))
        self.dirty_map = True
        return "floor face deleted - save the map"

    # ================================================================================== 9. map plan (top view)
    def plan_area(self):
        """(centre xz, half size) of the playable area in engine coordinates: start points, flags and health packs."""
        pts = []
        for r in self.scene.modules:
            if r.clean_name.lower() in ("mp_cstartpoint", "mp_flag", "mp_salud") and r.parsed is not None:
                try:
                    pts.append(np.asarray(self.position_of(self._sel(r)), np.float64))
                except Exception:
                    pass
        if not pts:
            return np.zeros(3), 3000.0
        pts = np.array(pts)
        lo, hi = pts.min(0), pts.max(0)
        c = (lo + hi) / 2
        return c, float(max(hi[0] - lo[0], hi[2] - lo[2]) / 2 + 800.0)

    def plan_items(self) -> list:
        """What the plan marks: [(kind, team | None, name, position engine)] for start points, flags, health, camera."""
        out = []
        for r in self.scene.modules:
            k = r.clean_name.lower()
            if r.parsed is None or k not in ("mp_cstartpoint", "mp_flag", "mp_salud", "mp_camerastartposition"):
                continue
            try:
                pos = np.asarray(self.position_of(self._sel(r)), np.float64)
            except Exception:
                continue
            team = getattr(r.parsed, "team", None)
            out.append((k, team if team in (0, 1) else None, str(r.object_name).rstrip("\0"), pos))
        return out

    def game_exes(self) -> list:
        """.exe files in the game folder (to choose which one 'Play' starts)."""
        d = getattr(self, "game_dir", "") or os.path.dirname(os.path.abspath(self.fs.root))
        try:
            return sorted(os.path.join(d, f) for f in os.listdir(d)
                          if f.lower().endswith(".exe") and "unins" not in f.lower() and "vtoyeditor" not in f.lower())
        except OSError:
            return []

    # ================================================================================== 'Torrente, el juego' folder
    def locate_library(self, path: str, cache_dir: str = "") -> str:
        """The folder the library is read from, given what the user picked: the unpacked data itself, a folder that has it
        somewhere inside, or the game's installation (its .vpk archives are unpacked once into ``cache_dir``)."""
        from .. import vpk as vpkmod
        from ..importer import Library
        path = os.path.abspath(path)

        def ok(d):
            try:
                lib = Library(d)
                return bool(lib.models() or lib.maps())
            except Exception:
                return False
        if ok(path):
            return path
        packs = []
        for dp, dn, fn in os.walk(path, followlinks=True):
            depth = os.path.relpath(dp, path).count(os.sep) + (0 if dp == path else 1)
            if depth >= 3:
                dn[:] = []
            if any(d.lower() == "nfos" for d in dn) and ok(dp):
                return dp
            packs += [os.path.join(dp, f) for f in fn if f.lower().endswith(".vpk")]
        if not packs:
            raise FileNotFoundError(f"no nfos/ folder and no .vpk archive found in {path}")
        from .. import settings
        out = cache_dir or os.path.join(os.path.dirname(settings.path()), "tj_unpacked")
        os.makedirs(out, exist_ok=True)
        stamp = os.path.join(out, "vtoy_unpacked.json")
        want = {os.path.basename(p): [os.path.getsize(p), int(os.path.getmtime(p))] for p in sorted(packs)}
        have = {}
        try:
            with open(stamp, encoding="utf-8") as f:
                have = json.load(f)
        except (OSError, ValueError):
            pass
        if have != want:
            n = 0
            for p in sorted(packs):
                try:
                    n += vpkmod.unpack(p, out)
                    self.log(f"unpacked {os.path.basename(p)}")
                except Exception as e:
                    self.log(f"could not unpack {os.path.basename(p)}: {e}")
            with open(stamp, "w", encoding="utf-8") as f:
                json.dump(want, f)
            self.log(f"{n} files unpacked into {out}")
        if not ok(out):
            for dp, dn, _ in os.walk(out):
                if any(d.lower() == "nfos" for d in dn) and ok(dp):
                    return dp
            raise FileNotFoundError(f"the archives of {path} hold no models or maps the editor can read")
        return out

    def open_game_folder(self, path: str, cache_dir: str = "") -> str:
        """Menu 'Torrente, el juego folder...': find the data, load it as the library and remember the folder."""
        from .. import settings
        root = self.locate_library(path, cache_dir)
        lib = self.set_library(root)
        lib.source_root = os.path.abspath(path)
        settings.set("library", os.path.abspath(path))
        new = {m: len(self.library_items(m, True)) for m in LIB_MODES}
        return (f"Torrente, el juego: {new['models']} new models, {new['maps']} new maps, {new['scenes']} new scenes, "
                f"{new['textures']} new textures, {new['music']} new music"
                + " (things the game already has under the same name are not listed)")

    def _game_names(self, mode: str) -> set:
        if mode == "models":
            return {os.path.basename(p).lower() for p in self.fs.list("nfos", ".nfo")}
        if mode == "maps":
            return {os.path.basename(p).lower() for p in self.fs.list("nfos", ".opt")}
        if mode == "scenes":
            return {os.path.basename(p).lower() for p in self.fs.list("scns", ".scn")}
        if mode == "textures":
            return {os.path.splitext(os.path.basename(p))[0].lower() for p in self.fs.list("texs", ".tex")}
        if mode == "music":
            return {os.path.basename(p).lower() for p in self.music_files()}
        return set()

    def library_music(self) -> list:
        """Music of the library's game folder: .ogg anywhere near it, .wav only inside a music folder."""
        lib = self.library
        if lib is None:
            return []
        if getattr(lib, "_music", None) is None:
            out = []
            roots = {os.path.abspath(getattr(lib, "source_root", "") or lib.root), os.path.abspath(lib.root)}
            for root in roots:
                for dp, dn, fn in os.walk(root, followlinks=True):
                    depth = 0 if dp == root else os.path.relpath(dp, root).count(os.sep) + 1
                    if depth >= 4:
                        dn[:] = []
                    in_music = any(k in dp.lower() for k in ("music", "musica"))
                    for f in fn:
                        if f.lower().endswith(".ogg") or (in_music and f.lower().endswith(".wav")):
                            out.append(os.path.join(dp, f))
                    if len(out) > 3000:
                        break
            lib._music = sorted(set(out), key=lambda p: os.path.basename(p).lower())
        return lib._music

    def library_items(self, mode: str, only_new: bool = True) -> list:
        """Names the library offers for ``mode`` (see LIB_MODES); ``only_new`` leaves out what the game already has under
        the same file name (so nothing is duplicated)."""
        lib = self.library
        if lib is None:
            return []
        items = {"models": lib.models, "maps": lib.maps, "scenes": lib.scenes, "textures": lib.textures,
                 "music": self.library_music}[mode]()
        if not only_new:
            return list(items)
        have = self._game_names(mode)
        if mode == "textures":
            return [n for n in items if n.lower() not in have]
        return [n for n in items if os.path.basename(n).lower() not in have]

    def import_library_texture(self, name: str) -> str:
        """Copy one texture of the library into the game (converted to TeX2; never over a different existing one)."""
        from ..importer import Importer
        imp = Importer(self.library, self.fs.root, self.log)
        final = imp.texture(name)
        self.fs.rescan(); self.fs._tex.clear()
        return f"texture {final}.tex: {imp.report.summary()}"

    def import_library_music(self, path: str) -> str:
        """Copy a music file of the library into the game's music folder - unless the game already has one with that name."""
        d = self.music_folder()
        try:
            have = {f.lower() for f in os.listdir(d)} if d else set()
        except OSError:
            have = set()
        if os.path.basename(path).lower() in have | self._game_names("music"):
            raise ValueError(f"the game already has {os.path.basename(path)}: not copied (nothing is replaced)")
        name = self.import_music(path)
        return f"{name} copied to the game's music folder - choose it in Game mode / sky / spawns / music"

    def preview_library_model(self, rel: str, pfs, distance: float = 700.0):
        """Geometry of a library model in front of the camera, read through the preview file system ``pfs`` (PreviewFS)."""
        from ..modules import new_module
        from ..opt import OptMap
        from ..render.geometry import bake_scene
        from ..scn import Scene
        sc = Scene()
        rec = new_module(sc, "rendernfo", "preview")
        rec.parsed.model_name = "nfos/" + rel
        rec.parsed.transform[3, :3] = (self.camera.pos + self.camera.front * distance) * [1, 1, -1]
        return bake_scene(pfs, sc, OptMap()), rec

    # ================================================================================== solids (mesh + collision together)
    def add_solid(self, shape: str, at, length: float, width: float, height: float, yaw: float = 0.0,
                  texture: str = "tablones.tex", tile: float = 128.0) -> str:
        """A plank / block / wall / ramp / rail you can see AND bump into (see vtoy.solids). The new mesh is selected."""
        from .. import solids
        from .state import Selection
        if self.fs.texture(texture) is None:
            raise ValueError(f"texture {texture} not found")
        self.push_undo(True, "create solid")
        try:
            hm = self.heightmap_edit()
        except ValueError:
            hm = None
        r = solids.build(self.opt, hm, shape, at, length, width, height, yaw, texture, tile,
                         has_texture=lambda t: self.fs.texture(t) is not None)
        me = self.opt.meshes[r["mesh"]]
        self.selection = Selection("mesh", me, f"{shape}")
        self.multi = []
        self.dirty_map = self.needs_rebake = True
        return (f"{shape} created: {length:.0f} x {width:.0f} x {height:.0f}, " + ("collision box + " if r["box"] is not None else "")
                + f"{r['faces']} floor / wall faces" + ("" if hm is not None else " (no height map: no floor)") + " - save the map")

    def add_solid_between(self, shape: str, a, b, width: float, height: float, texture: str = "tablones.tex",
                          tile: float = 128.0) -> str:
        from .. import solids
        at, length, yaw, h = solids.between(shape, a, b, width, height)
        return self.add_solid(shape, at, length, width, h, yaw, texture, tile)

    def delete_with_collision(self, sel) -> str:
        """Delete a mesh / prop together with everything that makes it solid: the collision boxes inside its bounds and the
        floor / wall faces of the height map inside them."""
        from .. import hmcopy, regioncopy
        if sel is None or sel.kind not in ("mesh", "prop"):
            raise ValueError("select a mesh or a prop")
        if self.blocked_by_lock(sel):
            return "locked: not deleted"
        b = self.engine_bounds(sel)
        if b is None:
            raise ValueError("its bounds are not known yet")
        lo, hi = np.asarray(b[0], np.float64) - 3.0, np.asarray(b[1], np.float64) + 3.0
        self.push_undo(True, "delete solid")
        self._undo_off = True
        try:
            self.delete_selection(sel, False)
            boxes = [i for i, raw in enumerate(cropmod.read_block(self.opt).boxes)
                     if np.all(regioncopy._box_bounds(raw)[0] >= lo) and np.all(regioncopy._box_bounds(raw)[1] <= hi)]
            if boxes:
                cropmod.remove_collision_indices(self.opt, boxes)
            nf = 0
            try:
                hm = self.heightmap_edit()
                keep = []
                for f in hmcopy.unique_faces(hm):
                    x0, z0, x1, z1 = hmcopy.face_bounds(f)
                    ys = np.concatenate(f.contours)[:, 1]
                    if x0 >= lo[0] and x1 <= hi[0] and z0 >= lo[2] and z1 <= hi[2] and ys.min() >= lo[1] and ys.max() <= hi[1]:
                        nf += 1
                    else:
                        keep.append(f)
                if nf:
                    hm.root = hmcopy.build_tree(keep, hmcopy.box(hm.root), max(hmcopy.tree_depth(hm.root), 1))
            except ValueError:
                pass
        finally:
            self._undo_off = False
        self.selection = None
        self.dirty_map = self.needs_rebake = True
        return f"deleted with {len(boxes)} collision boxes and {nf} floor / wall faces - save the map"

    # ================================================================================== 10. prefabs (pieces)
    def prefab_dir(self) -> str:
        from .. import settings
        d = os.path.join(os.path.dirname(settings.path()), "prefabs")
        os.makedirs(d, exist_ok=True)
        return d

    def prefab_names(self) -> list:
        try:
            return sorted(os.path.splitext(f)[0] for f in os.listdir(self.prefab_dir()) if f.endswith(".vtpf"))
        except OSError:
            return []

    def save_prefab(self, name: str, with_collision: bool = True) -> str:
        """The selected objects (group) as a reusable piece: modules, meshes (props become meshes), collision boxes and
        floor faces (.hm) inside their area.  Stored in prefabs/<name>.vtpf next to the editor."""
        from .. import hmcopy, regioncopy
        from ..opt import transform_mesh, translate_mesh
        g = self._group()
        if not g:
            raise ValueError("select the objects first (Ctrl+click adds to the group)")
        los, his = [], []
        mods, meshes, areas = [], [], []
        for s in g:
            b = self.engine_bounds(s)
            p = np.asarray(self.position_of(s), np.float64)
            los.append(b[0] if b else p - 30); his.append(b[1] if b else p + 30)
            if b is not None and s.kind in ("mesh", "prop"):
                areas.append((np.asarray(b[0]) - 5.0, np.asarray(b[1]) + 5.0))     # collision is taken per object
            if s.kind == "module":
                mods.append(copy.deepcopy(s.ref))
            elif s.kind == "mesh":
                meshes.append(copy.deepcopy(s.ref))
            elif s.kind == "prop":
                me = copy.deepcopy(self.opt.meshes[s.ref.mesh_index])
                M = np.linalg.inv(np.asarray(me.world_transform, np.float64)) @ np.asarray(s.ref.transform, np.float64)
                transform_mesh(me, M[:3, :3], np.zeros(3))
                translate_mesh(me, M[3, :3])
                me.world_transform = np.eye(4, dtype=np.float32)
                me.world_transform[3, :3] = (np.asarray(cropmod.mesh_bounds(me)[0]) + cropmod.mesh_bounds(me)[1]) / 2
                meshes.append(me)
        lo, hi = np.min(los, 0), np.max(his, 0)
        anchor = np.array([(lo[0] + hi[0]) / 2, lo[1], (lo[2] + hi[2]) / 2])
        boxes, faces = [], []
        if with_collision:
            for raw in cropmod.read_block(self.opt).boxes:
                a, b = regioncopy._box_bounds(raw)
                if any(np.all(a >= l) and np.all(b <= h) for l, h in areas):
                    boxes.append(bytes(raw))
            _, ff = self._floor_faces()
            for f in ff:
                x0, z0, x1, z1 = hmcopy.face_bounds(f)
                ys = np.concatenate(f.contours)[:, 1]
                if any(x0 >= l[0] and x1 <= h[0] and z0 >= l[2] and z1 <= h[2] and ys.min() >= l[1] and ys.max() <= h[1] + 10
                       for l, h in areas):
                    faces.append(copy.deepcopy(f))
        data = {"version": 1, "anchor": anchor, "modules": mods, "meshes": meshes, "boxes": boxes, "faces": faces,
                "size": (hi - lo).tolist()}
        safe = "".join(c for c in name if c.isalnum() or c in "-_ ").strip() or "piece"
        path = os.path.join(self.prefab_dir(), safe + ".vtpf")
        with open(path, "wb") as f:
            pickle.dump(data, f)
        return f"piece '{safe}' saved: {len(mods)} modules, {len(meshes)} meshes, {len(boxes)} boxes, {len(faces)} floor faces"

    def place_prefab(self, name: str, at, yaw: float = 0.0) -> str:
        """Put a saved piece with its anchor (bottom centre) at ``at`` (engine), turned ``yaw`` degrees."""
        from .. import gamemode, hmcopy, regioncopy
        from ..flagbase import rot_y, rotated_face
        from ..opt import transform_mesh, translate_mesh
        with open(os.path.join(self.prefab_dir(), name + ".vtpf"), "rb") as f:
            data = _PieceUnpickler(f).load()                         # only editor data classes / numpy arrays
        at = np.asarray(at, np.float64)
        anchor = np.asarray(data["anchor"], np.float64)
        delta = at - anchor
        R = rot_y(yaw)
        self.push_undo(True, "place piece")
        self._undo_off = True
        try:
            for me in data["meshes"]:
                m = copy.deepcopy(me)
                translate_mesh(m, delta)
                if yaw:
                    transform_mesh(m, R, at)
                cropmod.add_mesh(self.opt, m)
            for raw in data["boxes"]:
                a = np.frombuffer(raw, np.float32, 19).astype(np.float64)
                c = a[12:15] + delta
                if yaw:
                    c = (c - at) @ R + at
                half = a[16:19]
                if yaw and abs(((yaw + 45) % 180) - 45) > 45:       # turned ~90 degrees: swap the half sizes
                    half = half[[2, 1, 0]]
                regioncopy.add_box(self.opt, c, half)
            if data["faces"]:
                try:
                    hm = self.heightmap_edit()
                    fs_ = [hmcopy.shifted(f, *delta) for f in data["faces"]]
                    if yaw:
                        fs_ = [rotated_face(f, R, at) for f in fs_]
                    hmcopy.add_faces(hm, fs_)
                except ValueError:
                    pass
            for rec in data["modules"]:
                r = copy.deepcopy(rec)
                r.object_name = VStr((gamemode.unique_name(self.scene, str(r.object_name).rstrip("\0")) + "\0").encode("cp1252"))
                self.scene.modules.append(r)
                s = self._sel(r)
                try:
                    p = (np.asarray(self.position_of(s), np.float64) + delta)
                    if yaw:
                        p = (p - at) @ R + at
                    self.set_position(s, p)
                except Exception:
                    pass
        finally:
            self._undo_off = False
        self.dirty_scene = self.dirty_map = self.needs_rebake = True
        return f"piece '{name}' placed"

    def delete_prefab(self, name: str) -> None:
        os.remove(os.path.join(self.prefab_dir(), name + ".vtpf"))

    # ================================================================================== 11. install / uninstall a map zip
    def install_dir(self) -> str:
        d = os.path.join(os.path.dirname(os.path.abspath(self.fs.root)), "vtoy_installed")
        os.makedirs(d, exist_ok=True)
        return d

    def install_map_zip(self, zip_path: str) -> str:
        """Put an exported map zip into the game: scenes / maps / textures / models / keys into the unpacked data, DLLs into
        the game folder, music into its folder.  A file that already exists is NOT replaced (identical = shared, different =
        skipped and reported).  What was written is remembered for 'Uninstall'.  Repackage the VPK afterwards."""
        game_dir = getattr(self, "game_dir", "") or os.path.dirname(os.path.abspath(self.fs.root))
        written, skipped = [], []
        with zipfile.ZipFile(zip_path) as z:
            names = [n for n in z.namelist() if not n.endswith("/")]
            try:
                man = json.loads(z.read("vtoy_manifest.json"))
            except KeyError:
                man = {"map": os.path.splitext(os.path.basename(zip_path))[0]}
            for n in names:
                if n == "vtoy_manifest.json" or ".." in n.replace("\\", "/").split("/"):
                    continue
                top = n.replace("\\", "/").split("/")[0].lower()
                if top == "dll":
                    dst = os.path.join(game_dir, os.path.basename(n))
                elif top == "musica":
                    mf = self.music_folder() or os.path.join(game_dir, "musica")
                    dst = os.path.join(mf, os.path.basename(n))
                elif top == "wavs":
                    wf = self.wav_folders()
                    dst = os.path.join(wf[0] if wf else os.path.join(game_dir, "wavs"), os.path.basename(n))
                elif top in ("scns", "nfos", "texs", "keys"):
                    found = self.fs.find(n.replace("\\", "/"))
                    dst = found or os.path.join(self.fs.root, *n.replace("\\", "/").split("/"))
                else:
                    continue
                data = z.read(n)
                if os.path.exists(dst):
                    with open(dst, "rb") as f:
                        if f.read() != data:
                            skipped.append(n)
                    continue
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                with open(dst, "wb") as f:
                    f.write(data)
                written.append(dst)
        rec = {"map": man.get("map"), "zip": os.path.basename(zip_path), "time": time.strftime("%Y-%m-%d %H:%M"),
               "written": written, "skipped": skipped}
        with open(os.path.join(self.install_dir(), f"{man.get('map')}.json"), "w", encoding="utf-8") as f:
            json.dump(rec, f, indent=1)
        self.fs.rescan(); self.fs._tex.clear()
        msg = f"installed {man.get('map')}: {len(written)} files written"
        if skipped:
            msg += f"; {len(skipped)} NOT replaced because the game already has a different file with that name: " + \
                   ", ".join(skipped[:5])
        return msg + " - now 'Repackage VPK'"

    def installed_maps(self) -> list:
        try:
            return sorted(os.path.splitext(f)[0] for f in os.listdir(self.install_dir()) if f.endswith(".json"))
        except OSError:
            return []

    def uninstall_map(self, name: str) -> str:
        p = os.path.join(self.install_dir(), name + ".json")
        with open(p, encoding="utf-8") as f:
            rec = json.load(f)
        n = 0
        for w in rec.get("written", []):
            if os.path.isfile(w):
                os.remove(w); n += 1
        os.remove(p)
        self.fs.rescan(); self.fs._tex.clear()
        return f"{name} uninstalled: {n} files removed - now 'Repackage VPK'"

    # ================================================================================== 12. version history
    def history_dir(self, stem: Optional[str] = None) -> str:
        base = getattr(self, "game_dir", "") or os.path.dirname(os.path.abspath(self.fs.root))
        d = os.path.join(base, "vtoy_history", stem or self.map_stem())
        os.makedirs(os.path.join(d, "files"), exist_ok=True)
        return d

    def _map_files_now(self) -> dict:
        out = {"scene": self.scene.path}
        if self.opt is not None and self.opt.path and os.path.exists(self.opt.path):
            out["opt"] = self.opt.path
        name = str(self.scene.heightmap_name).rstrip("\0").replace("\\", "/")
        hm = self.fs.find(name) if name else None
        if hm:
            out["hm"] = hm
        return out

    def snapshot_history(self, note: str = "") -> str:
        """Keep a copy of the saved scene / .opt / .hm (identical files are stored once). The last 10 are kept."""
        d = self.history_dir()
        entry = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "note": note, "files": {}}
        for kind, path in self._map_files_now().items():
            if not path or not os.path.exists(path):
                continue
            with open(path, "rb") as f:
                data = f.read()
            h = hashlib.sha1(data).hexdigest()
            blob = os.path.join(d, "files", h)
            if not os.path.exists(blob):
                with open(blob, "wb") as f:
                    f.write(data)
            entry["files"][kind] = {"path": path, "sha1": h}
        stamp = time.strftime("%Y%m%d_%H%M%S")
        k = 0
        while os.path.exists(os.path.join(d, f"{stamp}{'_' + str(k) if k else ''}.json")):
            k += 1
        stamp = f"{stamp}{'_' + str(k) if k else ''}"
        with open(os.path.join(d, stamp + ".json"), "w", encoding="utf-8") as f:
            json.dump(entry, f, indent=1)
        self._prune_history(d)
        return stamp

    def _prune_history(self, d: str) -> None:
        snaps = sorted(f for f in os.listdir(d) if f.endswith(".json"))
        for old in snaps[:-HISTORY_KEEP]:
            os.remove(os.path.join(d, old))
        used = set()
        for s in sorted(f for f in os.listdir(d) if f.endswith(".json")):
            with open(os.path.join(d, s), encoding="utf-8") as f:
                for v in json.load(f)["files"].values():
                    used.add(v["sha1"])
        for b in os.listdir(os.path.join(d, "files")):
            if b not in used:
                os.remove(os.path.join(d, "files", b))

    def history(self) -> list:
        """[(stamp, entry)] newest first."""
        d = self.history_dir()
        out = []
        for s in sorted((f for f in os.listdir(d) if f.endswith(".json")), reverse=True):
            with open(os.path.join(d, s), encoding="utf-8") as f:
                out.append((s[:-5], json.load(f)))
        return out

    def restore_history(self, stamp: str) -> str:
        """Put a saved version back (the current one is kept in the history first) and reload the scene."""
        d = self.history_dir()
        with open(os.path.join(d, stamp + ".json"), encoding="utf-8") as f:
            entry = json.load(f)
        self.snapshot_history("before restoring " + stamp)
        for kind, v in entry["files"].items():
            shutil.copy2(os.path.join(d, "files", v["sha1"]), v["path"])
        self.load(os.path.basename(entry["files"]["scene"]["path"]))
        return f"version {entry['time']} restored"

    # ================================================================================== 13. compare versions
    def compare_versions(self, stamp_a: str, stamp_b: Optional[str] = None) -> List[str]:
        """Differences between a saved version and another one (or the current files on disk): modules added / removed /
        moved, scene settings, map content and textures."""
        from ..hm import HeightMap
        from ..modules import parse_modules
        from ..opt import OptMap
        from ..scn import Scene
        d = self.history_dir()

        def files_of(stamp):
            if stamp is None:
                return {k: open(p, "rb").read() for k, p in self._map_files_now().items() if p and os.path.exists(p)}
            with open(os.path.join(d, stamp + ".json"), encoding="utf-8") as f:
                e = json.load(f)
            return {k: open(os.path.join(d, "files", v["sha1"]), "rb").read() for k, v in e["files"].items()}

        A, B = files_of(stamp_a), files_of(stamp_b)
        out = []
        if "scene" in A and "scene" in B:
            sa, sb = Scene.parse(A["scene"], ""), Scene.parse(B["scene"], "")
            parse_modules(sa); parse_modules(sb)

            def mods(sc):
                r = {}
                for m in sc.modules:
                    p = m.parsed
                    pos = None
                    if p is not None:
                        if hasattr(p, "position"):
                            pos = np.asarray(p.position, np.float64)
                        elif isinstance(getattr(p, "transform", None), np.ndarray):
                            pos = np.asarray(p.transform, np.float64)[3, :3]
                    r[str(m.object_name).rstrip("\0")] = (m.clean_name, pos)
                return r
            ma, mb = mods(sa), mods(sb)
            for n in sorted(set(mb) - set(ma)):
                out.append(f"+ module {n} ({mb[n][0]})")
            for n in sorted(set(ma) - set(mb)):
                out.append(f"- module {n} ({ma[n][0]})")
            for n in sorted(set(ma) & set(mb)):
                pa, pb = ma[n][1], mb[n][1]
                if pa is not None and pb is not None and np.linalg.norm(pa - pb) > 0.5:
                    out.append(f"~ {n} moved {np.round(pb - pa).tolist()}")
            for attr in ("main_module_name", "map_name", "heightmap_name", "sky_texture", "ambient_music"):
                va, vb = str(getattr(sa, attr, "")).rstrip("\0"), str(getattr(sb, attr, "")).rstrip("\0")
                if va != vb:
                    out.append(f"~ {attr}: {va} -> {vb}")
        if "opt" in A and "opt" in B and A["opt"] != B["opt"]:
            oa, ob = OptMap.parse(A["opt"]), OptMap.parse(B["opt"])
            ba, bb = cropmod.read_block(oa), cropmod.read_block(ob)
            for label, va, vb in (("meshes", len(oa.meshes), len(ob.meshes)), ("props", len(oa.props), len(ob.props)),
                                  ("decals", len(oa.decals), len(ob.decals)), ("lights", len(oa.lights), len(ob.lights)),
                                  ("collision boxes", len(ba.boxes), len(bb.boxes))):
                if va != vb:
                    out.append(f"~ {label}: {va} -> {vb}")

            def texs(o):
                return {str(t).lower().rstrip("\0") for m in o.meshes for mt in m.materials for t in mt.textures[:1]}
            ta, tb = texs(oa), texs(ob)
            for t in sorted(tb - ta):
                out.append(f"+ texture {t}")
            for t in sorted(ta - tb):
                out.append(f"- texture {t}")
        if "hm" in A and "hm" in B and A["hm"] != B["hm"]:
            from .. import hmcopy
            na, nb = len(hmcopy.unique_faces(HeightMap.parse(A["hm"]))), len(hmcopy.unique_faces(HeightMap.parse(B["hm"])))
            out.append(f"~ floor collision faces: {na} -> {nb}")
        return out or ["no differences"]
