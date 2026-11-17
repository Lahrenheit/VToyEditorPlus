"""Editor tools (batch 7): collision generated from meshes, OBJ import, painting faces, the walking test, team balance,
lights for the lit view and particle emitters.  Mixin of EditorState; the work is done by vtoy.autohm / objimport /
facepaint / walk / navgrid / particles / render.lights, which do not know about the editor.

Like everything else here: files of other maps and of the game are never overwritten (new textures get new names)."""
from __future__ import annotations

import os
from typing import List, Optional

import numpy as np

from .. import crop as cropmod

F = np.array([1.0, 1.0, -1.0])


class BuildOps:
    # ================================================================================== which meshes
    def _index_of(self, sel):
        if sel is None or self.opt is None:
            return None
        if sel.kind == "mesh":
            return next((("mesh", i) for i, m in enumerate(self.opt.meshes) if m is sel.ref), None)
        if sel.kind == "prop":
            return next((("prop", i) for i, p in enumerate(self.opt.props) if p is sel.ref), None)
        return None

    def collision_targets(self, scope: str = "selection") -> list:
        """[(kind, index)]: the selected mesh / prop and those of the group, or every mesh and prop of the map."""
        if self.opt is None:
            return []
        if scope == "map":
            return [("mesh", i) for i in range(len(self.opt.meshes))] + [("prop", i) for i in range(len(self.opt.props))]
        out = []
        for s in ([self.selection] if self.selection is not None else []) + list(self.multi_list()):
            t = self._index_of(s)
            if t is not None and t not in out:
                out.append(t)
        return out

    # ================================================================================== 7. collision from meshes
    def _hm_or_new(self):
        """The height map being edited; a map without one gets an empty one (written as <map>.hm when the map is saved)."""
        from ..hm import HeightMap, HMSector
        try:
            return self.heightmap_edit(), False
        except ValueError:
            lo, hi = np.full(3, np.inf), np.full(3, -np.inf)
            for me in self.opt.meshes:
                a, b = cropmod.mesh_bounds(me)
                lo, hi = np.minimum(lo, a), np.maximum(hi, b)
            if not np.isfinite(lo).all():
                lo, hi = np.array([-1000.0, 0.0, -1000.0]), np.array([1000.0, 0.0, 1000.0])
            self.hm_edit = HeightMap(HMSector(float(lo[0]) - 10, float(lo[2]) - 10, float(hi[0]) + 10, float(hi[2]) + 10))
            return self.hm_edit, True

    def auto_collision(self, scope: str = "selection", floors: bool = True, walls: bool = True, ceilings: bool = True,
                       merge: bool = True, replace: bool = True, up_only: bool = False, box: bool = False,
                       min_area: float = 4.0) -> str:
        """Make the floor / wall faces of the height map from the triangles of the selected meshes (or of the whole map),
        the way the shipped height maps were made.  ``box`` also adds one collision box around each selected object."""
        from .. import autohm, regioncopy
        targets = self.collision_targets(scope)
        if not targets:
            raise ValueError("select a mesh or a prop of the map first (or use 'whole map')")
        self.push_undo(True, "collision from meshes")
        hm, created = self._hm_or_new()
        if scope == "map" and replace:                  # a clean start: everything is made again
            from .. import hmcopy
            hm.root = hmcopy.build_tree([], hmcopy.box(hm.root), 1)
            replace = False
        rep = autohm.generate(self.opt, hm, targets, floors, walls, ceilings, min_area, merge, replace, up_only)
        nb = 0
        if box and scope != "map":
            for kind, index in targets:
                tris, _ = autohm.triangles_of(self.opt, kind, index)
                if len(tris):
                    c, h = autohm.bounding_box(tris)
                    regioncopy.add_box(self.opt, c, h)
                    nb += 1
        self._ff_key = None
        self._walk_key = None
        self.dirty_map = True
        return (f"collision made from {rep['targets']} objects: {rep['floor']} floor, {rep['wall']} wall, {rep['ceiling']} ceiling faces "
                f"({rep['triangles']} triangles, {rep['quads']} joined in quads, {rep['removed']} old faces replaced)"
                + (f", {nb} collision boxes" if nb else "") + (" - new height map" if created else "") + " - save the map")

    # ================================================================================== 4. OBJ import
    def obj_info(self, path: str) -> dict:
        """What an OBJ file holds (to show before importing): triangles, materials, size in its own units."""
        from .. import objimport
        m = objimport.parse_obj(path)
        lo, hi = m.bounds()
        return {"name": m.name, "triangles": m.triangle_count, "materials": [(k, bool(v.image)) for k, v in m.materials.items() if k in m.groups],
                "size": tuple(float(v) for v in (hi - lo)), "warnings": list(m.warnings)}

    def _new_texture_name(self, wanted: str, rgba: np.ndarray, prefix: str) -> str:
        """Write ``rgba`` as a .tex of the game under a name nothing else uses (or reuse the file if it already is that
        picture). Returns the file name."""
        import re
        from ..tex import Texture
        stem = re.sub(r"[^A-Za-z0-9_\-]", "_", os.path.splitext(os.path.basename(wanted))[0])[:40] or "tex"
        folder = os.path.join(self.fs.root, "texs")
        cands = [stem, f"{prefix}_{stem}"] + [f"{prefix}_{stem}_{k}" for k in range(2, 50)]
        new = Texture.from_rgba(rgba, None, mipmaps=True)
        for c in cands:
            old = self.fs.texture(c + ".tex")
            if old is None:
                os.makedirs(folder, exist_ok=True)
                new.save(os.path.join(folder, c + ".tex"))
                self.fs.rescan()
                self.fs._tex.pop(c.lower(), None)
                return c + ".tex"
            try:
                if (old.width, old.height) == (new.width, new.height) and \
                        float(np.abs(old.decode().astype(int) - new.decode().astype(int)).mean()) < 2.0:
                    return c + ".tex"                    # the same picture is already there
            except Exception:
                pass
        raise ValueError(f"no free texture name for {wanted}")

    def import_obj(self, path: str, at=None, scale: float = 100.0, yaw: float = 0.0, up: str = "y", two_sided: bool = False,
                   collision: bool = True, box: bool = False) -> str:
        """Add an OBJ model to the map as a static mesh (its textures are converted to new .tex files) and, unless
        ``collision`` is off, make its floor / wall collision from its own triangles.  The new mesh is selected."""
        from .. import autohm, objimport, regioncopy
        from .state import Selection
        if self.opt is None:
            raise ValueError("open a map first")
        model = objimport.parse_obj(path)
        if model.triangle_count > 200000:
            raise ValueError(f"{model.triangle_count} triangles: too heavy for a map mesh (simplify it below 200000)")
        prefix = "".join(ch if ch.isalnum() or ch in "_-" else "_" for ch in model.name)[:24] or "obj"
        names = {}

        def texture_of(mat_name: str) -> str:
            if mat_name not in names:
                mat = model.materials.get(mat_name) or objimport.ObjMaterial(name=mat_name)
                try:
                    rgba = objimport.material_image(mat)
                except Exception as e:
                    self.log(f"material {mat_name}: picture not read ({e}); its colour is used")
                    mat = objimport.ObjMaterial(name=mat_name, color=mat.color)
                    rgba = objimport.material_image(mat)
                wanted = os.path.basename(mat.image) if mat.image else f"{prefix}_{mat_name or 'color'}"
                names[mat_name] = self._new_texture_name(wanted, rgba, prefix)
            return names[mat_name]

        at = np.asarray(self._here() if at is None else at, np.float64)
        self.push_undo(True, "import OBJ")
        me = objimport.to_mesh(model, self.opt, texture_of, scale, at, yaw, up, two_sided)
        mi = cropmod.add_mesh(self.opt, me)
        rep = None
        nb = 0
        if collision:
            hm, _ = self._hm_or_new()
            rep = autohm.generate(self.opt, hm, [("mesh", mi)], replace=False)
        if box:
            tris, _ = autohm.triangles_of(self.opt, "mesh", mi)
            c, h = autohm.bounding_box(tris)
            regioncopy.add_box(self.opt, c, h)
            nb = 1
        self.selection = Selection("mesh", me, model.name)
        self.multi = []
        self._ff_key = None
        self._walk_key = None
        self.dirty_map = self.needs_rebake = True
        lo, hi = cropmod.mesh_bounds(me)
        size = hi - lo
        msg = (f"{model.name}: {model.triangle_count} triangles, {len(me.materials)} materials "
               f"({', '.join(sorted(set(names.values())))}), {size[0] / 100:.1f} x {size[1] / 100:.1f} x {size[2] / 100:.1f} m")
        if rep is not None:
            msg += f"; collision: {rep['floor']} floor, {rep['wall']} wall, {rep['ceiling']} ceiling faces"
        if nb:
            msg += ", 1 collision box"
        for w in model.warnings:
            self.log("OBJ: " + w)
        return msg + " - save the map"

    # ================================================================================== 3. painting faces
    def paint_pick(self, origin, direction) -> Optional[dict]:
        """The map triangle under a view ray (display space)."""
        from .. import facepaint
        if self.opt is None:
            return None
        return facepaint.pick(self.opt, np.asarray(origin, np.float64) * F, np.asarray(direction, np.float64) * F)

    def paint_faces(self, hit: dict, mode: str, texture: str, tile: float = 0.0) -> str:
        """Give the picked triangle / the flat area around it / its whole material another texture."""
        from .. import facepaint
        from .state import Selection
        if hit is None:
            raise ValueError("click a face of the map")
        if self.fs.texture(texture) is None:
            raise ValueError(f"texture {texture} not found")
        me = self.opt.meshes[hit["mesh"]]
        if self.is_locked(me, "mesh"):
            return "locked: not painted"
        if not texture.lower().endswith(".tex"):
            texture += ".tex"
        self.push_undo(True, "paint faces")
        if mode == "material":
            r = facepaint.paint_material(self.opt, hit["mesh"], hit["material"], texture)
        else:
            r = facepaint.paint(self.opt, hit, facepaint.select(self.opt, hit, mode), texture, tile)
        self.dirty_map = self.needs_rebake = True
        return (f"{r['triangles']} triangles now use {texture}"
                + (f" (+{r['far_triangles']} in the far levels of detail)" if r["far_triangles"] else "")
                + (f" - this mesh is shown {r['users']} more times (props): all of them change" if r["users"] else "")
                + " - save the map")

    # ================================================================================== 5. walking test
    def walk_world(self):
        """Floors, walls and boxes of the map as it is being edited (cached until the collision changes)."""
        from .. import walk
        hm, _faces = self._floor_faces()
        key = (self._ff_key, id(self.opt), self.opt.scene_obj_count if self.opt is not None else 0,
               len(self.opt.hulls_raw) if self.opt is not None else 0, len(self.opt.trailer) if self.opt is not None else 0)
        if getattr(self, "_walk_key", None) != key:
            self._walk_world = walk.World.from_map(self.opt, hm)
            self._walk_key = key
        return self._walk_world

    def start_walk(self, at=None):
        """A walker standing at ``at`` (engine; default: under the camera)."""
        from .. import walk
        w = walk.Walker(self.walk_world())
        if at is None:
            p = np.asarray(self.camera.pos, np.float64) * F
            y = w.world.floor_at(p[0], p[2], p[1] + 10.0)
            at = np.array([p[0], y if y is not None else p[1] - w.eye, p[2]])
        w.place(at)
        return w

    def spawn_positions(self) -> dict:
        """{team: [(name, position)]} of the start points."""
        out = {}
        for r in self.scene.modules:
            if r.clean_name.lower() == "mp_cstartpoint" and r.parsed is not None:
                out.setdefault(int(r.parsed.team), []).append((str(r.object_name).rstrip("\0"), np.asarray(r.parsed.position, np.float64)))
        return out

    # ================================================================================== 6. team balance
    def balance_report(self, cell: float = 40.0, speed: float = 450.0) -> dict:
        """Distances / times of each team to the enemy flag, its own flag and the health packs (see vtoy.navgrid)."""
        from .. import navgrid
        world = self.walk_world()
        if not world.floors:
            raise ValueError("this map has no floor collision (.hm): nothing to walk on")
        spawns = {t: [p for _, p in lst] for t, lst in self.spawn_positions().items()}
        flags, health = {}, []
        for r in self.scene.modules:
            k = r.clean_name.lower()
            if r.parsed is None:
                continue
            if k == "mp_flag":
                flags[int(r.parsed.team)] = np.asarray(r.parsed.transform[3, :3], np.float64)
            elif k in ("mp_salud", "mp_botikin"):
                health.append(np.asarray(r.parsed.transform[3, :3], np.float64))
        if not spawns:
            raise ValueError("the scene has no start points")
        seeds = [p for lst in spawns.values() for p in lst] + list(flags.values()) + health
        grid = navgrid.build(world, seeds, cell=cell)
        res = navgrid.balance(grid, spawns, flags, health, speed)
        res["flags"], res["health"], res["cell"] = flags, len(health), cell
        return res

    @staticmethod
    def balance_lines(res: dict) -> List[str]:
        """The report as text lines (English; the panel translates the fixed parts)."""
        import math
        sp = res["speed"]
        fmt = lambda d: "-" if not math.isfinite(d) else f"{d / 100:.0f} m / {d / sp:.0f} s"
        out = []
        for t, r in sorted(res["teams"].items()):
            out.append(f"Team {t}: {r.spawns} start points")
            if res["flags"]:
                out.append(f"   to the enemy flag: {fmt(r.to_enemy_flag[1])} on average ({fmt(r.to_enemy_flag[0])} .. {fmt(r.to_enemy_flag[2])})")
                out.append(f"   flag back home: {fmt(r.flag_run)}      to its own flag: {fmt(r.to_own_flag[1])}")
            if res["health"]:
                out.append(f"   to the nearest health pack: {fmt(r.to_health[1])} on average (worst {fmt(r.to_health[2])})")
            if r.unreachable:
                out.append(f"   WARNING: from {r.unreachable} start points the enemy flag cannot be reached on foot")
            if r.off_grid:
                out.append(f"   WARNING: {r.off_grid} start points are not on any floor")
        if res.get("faster") is not None:
            p = res["percent"]
            verdict = "balanced" if p < 3 else ("slight advantage" if p < 8 else "clear advantage")
            out.append(f"Attack (go for the flag and bring it home): team {res['faster']} is {p:.1f} % faster - {verdict}")
        elif len(res["teams"]) >= 2 and len(res["flags"]) >= 2:
            if res.get("attack"):
                out.append("Attack: both teams need the same time - balanced")
            else:
                out.append("WARNING: neither team can walk to the enemy flag and back (check the floor collision between them)")
        return out

    # ================================================================================== 2. lights
    def packed_lights(self):
        """The map's lights for the lit view (None: the map has none)."""
        from ..render import lights
        if self.opt is None:
            return None
        return lights.pack(self.opt, np.asarray(self.camera.pos, np.float64))

    def light_at_camera(self, kind: int = 0, color=(1.0, 0.95, 0.8), start: float = 250.0, end: float = 800.0):
        """Add a light where the camera is (point) / looking where it looks (directional)."""
        from ..opt import LightType
        l = self.add_light(LightType(kind))
        l.position = (np.asarray(self.camera.pos, np.float64) * F).astype(np.float32)
        l.direction = (np.asarray(self.camera.front, np.float64) * F).astype(np.float32)
        l.start, l.end, l.radius = float(start), float(end), float(end)
        l.diffuse = (float(color[0]), float(color[1]), float(color[2]), 0.0)
        self.dirty_map = True
        return l

    # ================================================================================== 1. sounds and particles
    def emitters(self) -> list:
        return [r for r in self.scene.modules if r.clean_name.lower() == "cparticlesystem" and r.parsed is not None]

    def sound_sources(self) -> list:
        return [r for r in self.scene.modules if r.clean_name.lower() == "mp_soundsource" and r.parsed is not None]

    def add_particles(self, preset: str, at=None):
        """A new particle emitter with the numbers of one from the shipped maps."""
        from ..modules import PARTICLE_PRESETS
        if preset not in PARTICLE_PRESETS:
            raise ValueError(f"unknown preset {preset}")
        tex = PARTICLE_PRESETS[preset]["texture"]
        if self.fs.texture(tex) is None:
            raise ValueError(f"texture {tex} not found in the game")
        rec = self.add_module("CParticleSystem", "particles")
        p = rec.parsed
        for k, v in PARTICLE_PRESETS[preset].items():
            setattr(p, k, v)
        p.position = tuple(float(v) for v in (self._here() if at is None else at))
        from .state import Selection
        self.selection = Selection("module", rec, str(rec.object_name).rstrip("\0"))
        self.dirty_scene = True
        return rec

    # ================================================================================== twin ships: gangplanks one by one
    def _twin_stock(self):
        """(hull lo, hull hi, stock height map, its collision world) of the Love Boat the twin ships were made from."""
        from .. import hmcopy, twinships, walk
        from ..hm import HeightMap
        from ..opt import OptMap
        hm_p = self.fs.find("nfos/mp_dm_loveboat.hm")
        opt_p = self.fs.find("nfos/mp_dm_loveboat.opt")
        if not hm_p or not opt_p:
            raise ValueError("the stock nfos/mp_dm_loveboat.opt / .hm were not found")
        key = (hm_p, opt_p, os.path.getmtime(hm_p), os.path.getmtime(opt_p))
        if getattr(self, "_twin_key", None) != key:
            _lo, _hi, hlo, hhi = twinships.ship_box(OptMap.load(opt_p))
            hm = HeightMap.load(hm_p)
            self._twin_key, self._twin_data = key, (hlo, hhi, hm, walk.World(hmcopy.unique_faces(hm)))
        return self._twin_data

    def twin_bridges(self) -> list:
        """The gangplanks between the twin ships, found in the map itself: [{'z', 'width', 'rails', ...}] from bow to stern."""
        from .. import twinships
        if self.opt is None:
            return []
        key = (id(self.opt), len(self.opt.meshes), self.opt.scene_obj_count, len(self.opt.hulls_raw))
        if getattr(self, "_br_key", None) != key:
            hlo, hhi, _hm, _w = self._twin_stock()
            self._br_key, self._br_list = key, twinships.find_bridges(self.opt, hlo, hhi)
        return [dict(b) for b in self._br_list]

    def set_twin_bridges(self, wanted, gap: float = 800.0) -> str:
        """Make the gangplanks of the map exactly ``wanted`` = [{'z', 'width', 'rails'}]: the ones there are taken out
        (planks, railings, collision boxes, floor faces) and the wanted ones are laid, each over the rails at its place
        with a ramp at each end.  Everything else in the map and in its floor collision stays as it is."""
        from .. import twinships
        hlo, hhi, stock_hm, world = self._twin_stock()
        cur = twinships.find_bridges(self.opt, hlo, hhi)
        off = twinships.ship_offset(self.opt, stock_hm, hlo, hhi, gap, world)
        plans = []
        for w in wanted:
            width = float(w.get("width", 320.0))
            if not 80.0 <= width <= 2500.0:
                raise ValueError("a gangplank is 80 to 2500 wide")
            b = twinships.bridge_layout(stock_hm, hlo, hhi, off, float(w["z"]), width, world)
            b["rails"] = bool(w.get("rails"))
            plans.append(b)
        plans.sort(key=lambda b: b["z"])
        for a, b in zip(plans, plans[1:]):
            if b["z"] - b["width"] / 2 < a["z"] + a["width"] / 2 + 20.0:
                raise ValueError("two gangplanks would overlap: move one of them")
        self.push_undo(True, "gangplanks")
        try:
            hm = self.heightmap_edit()
        except ValueError:
            hm = None
        panel = self.fs.texture("barandillas_poli.tex") is not None
        rem = {"meshes": 0, "boxes": 0, "faces": 0}
        for b in cur:
            r = twinships.remove_bridge(self.opt, hm, b)
            for k in rem:
                rem[k] += r[k]
        for b in plans:
            twinships.add_bridge(self.opt, hm, b, panel)
        self._br_key = self._ff_key = self._walk_key = None
        self.selection = None
        self.multi = []
        self.dirty_map = self.needs_rebake = True
        return (f"gangplanks: {len(plans)} laid ({len(cur)} taken out: {rem['meshes']} meshes, {rem['boxes']} collision boxes, "
                f"{rem['faces']} floor faces)" + ("" if hm is not None else " - no height map: no floor") + " - save the map")

    # ================================================================================== cars that cannot be destroyed
    def model_box(self, rec):
        """(centre, half size, axes) of a box around the model of a module, turned like it when it stands upright."""
        p = rec.parsed
        model = self.fs.model(p.model_name)
        if model is None:
            raise ValueError(f"model {p.model_name} not found")
        pts = [v8[:, :3] for _obj, me in model.lod0_meshes() for _mi, v8, _ind, _src in me.build()]
        if not pts:
            raise ValueError("the model has no geometry")
        pts = np.concatenate(pts).astype(np.float64)
        M = np.asarray(p.transform, np.float64)
        A = M[:3, :3]
        sc = np.linalg.norm(A, axis=1)
        axes = A / np.where(sc < 1e-9, 1.0, sc)[:, None]
        if abs(axes[1, 1]) > 0.999:                        # upright: a box turned about the vertical axis, like the game's
            lo, hi = pts.min(0), pts.max(0)
            return ((lo + hi) / 2) @ A + M[3, :3], (hi - lo) / 2 * sc, axes
        w = pts @ A + M[3, :3]
        lo, hi = w.min(0), w.max(0)
        return (lo + hi) / 2, (hi - lo) / 2, np.eye(3)

    def car_to_scenery(self, rec, box: bool = True) -> str:
        """An mp_CCar (a car that blows up when shot) becomes plain scenery: the same model drawn by RenderNFO, which nothing
        can destroy, with a collision box around it so it still stops players and bullets."""
        from .. import regioncopy
        from ..binutil import VStr
        from ..modules import DEFAULT_TAIL
        if rec.clean_name.lower() != "mp_ccar" or rec.parsed is None:
            raise ValueError("select an mp_CCar module")
        if self.is_locked(rec):
            return "locked: not changed"
        self.push_undo(True, "car to scenery")
        rec.module_name = VStr(b"RenderNFO.dll\0")
        rec.parsed.tail = bytes.fromhex(DEFAULT_TAIL["rendernfo"])
        nb = 0
        if box and self.opt is not None and not self.opt.old_format and self.opt.meshes:
            c, h, ax = self.model_box(rec)
            regioncopy.add_box(self.opt, c, np.maximum(h, 2.0), ax)
            nb = 1
            self.dirty_map = True
        self.dirty_scene = True
        self._walk_key = None
        return (f"{str(rec.object_name).rstrip(chr(0))}: now scenery (RenderNFO) - it cannot be destroyed"
                + (", with a collision box around it" if nb else "") + " - save the scene and the map")

    def cars_to_scenery(self, box: bool = True) -> str:
        """Every mp_CCar of the scene (not the locked ones)."""
        recs = [r for r in self.scene.modules if r.clean_name.lower() == "mp_ccar" and r.parsed is not None and not self.is_locked(r)]
        if not recs:
            raise ValueError("this scene has no mp_CCar")
        self.push_undo(True, "car to scenery")
        self._undo_off = True
        try:
            for r in recs:
                self.car_to_scenery(r, box)
        finally:
            self._undo_off = False
        return f"{len(recs)} cars are now scenery (they cannot be destroyed) - save the scene and the map"

    # ================================================================================== weapons allowed on this map
    def mode_dll_source(self) -> str:
        """The DLL the scene's mode runs: this map's own copy if it has one, else the game's DLL next to demo.vpk (or '')."""
        name = str(self.scene.main_module_name).rstrip("\0")
        own = getattr(self, "custom_dlls", {}).get(name.lower())
        cands = [own, os.path.join(self.export_dir(), name)]
        for d in (getattr(self, "game_dir", "") or "", os.path.dirname(os.path.abspath(self.fs.root))):
            if d:
                cands += [os.path.join(d, name), os.path.join(d, "dll", name)]
        for c in cands:
            if c and os.path.isfile(c):
                return c
        return ""

    def weapon_groups(self, src: str = ""):
        """[bool x 5]: which weapon groups the mode DLL of this map hands out (None when the DLL is not found / not known)."""
        from .. import dllpatch
        src = src or self.mode_dll_source()
        if not src:
            return None
        try:
            return dllpatch.weapon_groups(open(src, "rb").read())
        except (OSError, ValueError):
            return None

    def make_weapons_dll(self, allowed, src: str = "", out_dir: str = "") -> str:
        """Only the weapon groups ticked in ``allowed`` (5 booleans: groups 1-5) are given to the players on THIS map: a copy
        ``<mode DLL>_<map>.dll`` of the mode DLL without the calls that hand out the other groups is written to the export
        folder and the scene uses it.  The game's own DLL is never modified."""
        import re
        from .. import dllpatch
        from ..binutil import VStr
        src = src or self.mode_dll_source()
        if not src or not os.path.isfile(src):
            raise ValueError("the mode DLL was not found: pick it in the game folder")
        stem = self.map_stem()
        base = os.path.splitext(os.path.basename(src))[0]
        base = re.sub("_" + re.escape(stem) + "$", "", base, flags=re.I)
        name = f"{base}_{stem}.dll"
        out_dir = out_dir or self.export_dir()
        os.makedirs(out_dir, exist_ok=True)
        dst = os.path.join(out_dir, name)
        rep = dllpatch.patch_weapon_groups(src, dst, allowed)
        self.push_undo(False, "weapons DLL")
        self.scene.main_module_name = VStr((name + "\0").encode("cp1252"))
        self.custom_dlls = dict(getattr(self, "custom_dlls", {}), **{name.lower(): dst})
        self.dirty_scene = True
        self._wg_key = None
        on = ", ".join(str(i + 1) for i, a in enumerate(rep) if a) or "none"
        off = ", ".join(str(i + 1) for i, a in enumerate(rep) if not a) or "none"
        return (f"{name}: weapon groups given: {on}; not given: {off}. Copy it into the game folder (next to "
                f"{base}.dll) on the server and on every player's PC")

    def weapon_pickups(self) -> list:
        """The weapons lying on the map (mp_generador): [(module, weapon id, weapon name, group 0-4 or -1)]."""
        import struct
        from .. import dllpatch
        out = []
        for r in self.scene.modules:
            if r.clean_name.lower() == "mp_generador" and r.parsed is None and len(r.data) >= 16:
                wid = struct.unpack_from("<i", r.data, 12)[0]
                out.append((r, wid, dllpatch.WEAPON_IDS.get(wid, f"weapon {wid}"), dllpatch.group_of_weapon(wid)))
        return out

    def remove_weapon_pickups(self, allowed) -> str:
        """Delete the weapons lying on the map that belong to the groups not ticked in ``allowed`` (a group that is not
        handed out could still be picked up from the floor)."""
        gone = [(r, name) for r, _wid, name, g in self.weapon_pickups() if 0 <= g < 5 and not allowed[g] and not self.is_locked(r)]
        if not gone:
            return "no weapon of those groups lies on this map"
        self.push_undo(False, "remove weapon pickups")
        ids = {id(r) for r, _ in gone}
        self.scene.modules[:] = [m for m in self.scene.modules if id(m) not in ids]
        if self.selection is not None and id(self.selection.ref) in ids:
            self.selection = None
        self.dirty_scene = True
        kinds = sorted({n for _, n in gone})
        return f"{len(gone)} weapon pickups removed ({', '.join(kinds)}) - save the scene"

