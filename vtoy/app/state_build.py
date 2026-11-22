"""Editor tools (batch 7): collision generated from meshes, OBJ import, painting faces, the walking test, team balance,
lights for the lit view and particle emitters.  Mixin of EditorState; the work is done by vtoy.autohm / objimport /
facepaint / walk / navgrid / particles / render.lights, which do not know about the editor.

Like everything else here: files of other maps and of the game are never overwritten (new textures get new names)."""
from __future__ import annotations

import os
import re
from typing import Dict, List, Optional

import numpy as np

from .. import crop as cropmod

F = np.array([1.0, 1.0, -1.0])



MAX_TEX_STEM = 27          # a new texture's name without ".tex": the game's longest is 31 letters with it

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

    # ================================================================================== collision boxes following the mesh
    def _tris_matching(self, kind: str, index: int, texture: str = "") -> np.ndarray:
        """Triangles (engine) of a mesh / prop, only those of the materials whose texture contains ``texture`` when given."""
        from .. import autohm
        if not texture:
            return autohm.triangles_of(self.opt, kind, index)[0]
        me = self.opt.meshes[index] if kind == "mesh" else self.opt.meshes[self.opt.props[index].mesh_index]
        if kind == "mesh":
            M = np.eye(4)
        else:
            M = np.linalg.inv(np.asarray(me.world_transform, np.float64)) @ np.asarray(self.opt.props[index].transform, np.float64)
        want = texture.lower()
        out = []
        for sm in me.render_submeshes():
            if sm.vertices is None or not len(sm.vertices) or len(sm.indices) < 3 or sm.material_index >= len(me.materials):
                continue
            mat = me.materials[sm.material_index]
            if not any(want in str(t).lower() for t in ([mat.diffuse] + list(mat.textures or []))):
                continue
            idx = np.asarray(sm.indices, np.int64)[: len(sm.indices) // 3 * 3].reshape(-1, 3)
            idx = idx[(idx < len(sm.vertices)).all(1)]
            out.append((sm.vertices["pos"].astype(np.float64) @ M[:3, :3] + M[3, :3])[idx])
        return np.concatenate(out) if out else np.zeros((0, 3, 3))

    def _visible_items(self) -> list:
        """(kind, index) of what is drawn in the map: the static meshes (not the patterns of the props) and the props."""
        used = {p.mesh_index for p in self.opt.props}
        return [("mesh", i) for i in range(len(self.opt.meshes)) if i not in used] + [("prop", i) for i in range(len(self.opt.props))]

    def without_collision(self, texture: str = "", threshold: float = 0.5) -> list:
        """[(kind, index, covered 0..1)] of the meshes / props (with ``texture`` in one of their materials, when given)
        that have little or no collision: under ``threshold`` of their surface is inside a collision box or next to a
        wall of the height map."""
        from .. import meshbox
        if self.opt is None:
            return []
        try:
            hm = self.heightmap_edit()
        except ValueError:
            hm = None
        boxes, walls = meshbox.map_boxes(self.opt), meshbox.map_faces(hm)
        out = []
        for kind, i in self._visible_items():
            tris = self._tris_matching(kind, i, texture)
            if not len(tris):
                continue
            cv = meshbox.coverage(self.opt, hm, tris, boxes=boxes, walls=walls)
            if cv < threshold:
                out.append((kind, i, cv))
        return out

    def select_without_collision(self, texture: str = "", threshold: float = 0.5) -> str:
        """Select (all together) what ``without_collision`` finds."""
        from .state import Selection
        found = self.without_collision(texture, threshold)
        sels = []
        for kind, i, _cv in found:
            ref = self.opt.meshes[i] if kind == "mesh" else self.opt.props[i]
            if self.is_locked(ref, kind) or self.is_hidden(ref, kind):
                continue
            sels.append(Selection(kind, ref, f"{kind} {i}"))
        self.selection = sels[0] if sels else None
        self.multi = sels[1:]
        what = f" with '{texture}'" if texture else ""
        return (f"{len(sels)} objects{what} without collision selected" if sels else f"every object{what} already has collision")

    def collision_from_shape(self, scope: str = "selection", texture: str = "", only_missing: bool = False,
                             thickness: float = 10.0, min_height: float = 0.0, threshold: float = 0.5) -> str:
        """Collision boxes that follow the shape of the mesh (one thin box per flat side of a railing, one fitted box per
        solid piece) instead of one box around the whole object.  ``scope``: 'selection' or 'map' (every object, then
        best with ``texture`` and ``only_missing``).  ``texture``: only the triangles of materials with that texture."""
        from .. import meshbox, regioncopy
        if self.opt is None or self.opt.old_format:
            raise ValueError("this map has no collision boxes (old format)")
        if scope == "map":
            targets = self._visible_items()
        else:
            targets = self.collision_targets("selection")
            if not targets:
                raise ValueError("select a mesh or a prop of the map first")
        try:
            hm = self.heightmap_edit()
        except ValueError:
            hm = None
        boxes, walls = meshbox.map_boxes(self.opt), meshbox.map_faces(hm)
        jobs = []
        skipped = 0
        for kind, i in targets:
            ref = self.opt.meshes[i] if kind == "mesh" else self.opt.props[i]
            if scope == "map" and (self.is_locked(ref, kind) or self.is_hidden(ref, kind)):
                continue
            tris = self._tris_matching(kind, i, texture)
            if not len(tris):
                continue
            if only_missing and meshbox.coverage(self.opt, hm, tris, boxes=boxes, walls=walls) >= threshold:
                skipped += 1
                continue
            jobs.append(meshbox.fit(tris, thickness, min_height))
        if not jobs:
            return ("nothing to do: " + (f"{skipped} objects already have collision" if skipped else "no triangles"
                                         + (f" with '{texture}'" if texture else "")))
        self.push_undo(True, "collision boxes from the mesh")
        nb = 0
        for fitted in jobs:
            for c, h, ax in fitted:
                regioncopy.add_box(self.opt, c, h, ax)
                nb += 1
        self._ff_key = None
        self._walk_key = None
        self.dirty_map = True
        return (f"{nb} collision boxes following the shape of {len(jobs)} objects"
                + (f" ({skipped} that already had collision left alone)" if skipped else "") + " - save the map")

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
        stem = re.sub(r"[^A-Za-z0-9_\-]", "_", os.path.splitext(os.path.basename(wanted))[0]) or "tex"
        folder = os.path.join(self.fs.root, "texs")
        n = MAX_TEX_STEM                                   # the game's own names: at most 31 letters with ".tex"
        cands = [stem[:n], f"{prefix}_{stem}"[:n]] + [f"{prefix}_{stem}"[:n - 1 - len(str(k))] + f"_{k}" for k in range(2, 50)]
        cands = list(dict.fromkeys(cands))
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
                   collision: bool = True, box: bool = False, original: bool = False) -> str:
        """Add an OBJ model to the map as a static mesh (its textures are converted to new .tex files) and, unless
        ``collision`` is off, make its floor / wall collision from its own triangles.  The new mesh is selected."""
        from .. import autohm, objimport, regioncopy
        from .state import Selection
        if self.opt is None:
            raise ValueError("open a map first")
        model = objimport.parse_obj(path)
        # boxes exported with the model (material 'collision...') come back as collision boxes, not as a mesh
        coll_names = [k for k in model.groups if str(k).lower().startswith("collision")]
        coll_model = None
        if coll_names:
            import copy as _copy
            coll_model = _copy.copy(model)
            coll_model.groups = dict(model.groups)
            model.groups = {k: v for k, v in model.groups.items() if k not in coll_names}
            if not model.groups:
                raise ValueError("the OBJ file only has collision boxes")
        if at is None and original:                       # exported by this editor: back to where it was
            try:
                with open(path, encoding="utf-8", errors="replace") as fh:
                    for line in fh:
                        if line.startswith("# vtoy-origin"):
                            at = [float(v) for v in line.split()[2:5]]
                            break
                        if not line.startswith("#"):
                            break
            except OSError:
                pass
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
        if coll_model is not None:
            from .. import meshbox
            full = objimport.to_engine(coll_model, scale, at, yaw, up, ground=False)
            mesh_only = {k: v for k, v in full.items() if k not in coll_names}
            pm = np.concatenate([g.pos for g in mesh_only.values()])
            lo_m, hi_m = pm.min(0), pm.max(0)
            shift = np.asarray(at, np.float64) - [(lo_m[0] + hi_m[0]) / 2, lo_m[1], (lo_m[2] + hi_m[2]) / 2]
            for k in coll_names:
                g = full[k]
                tris = (g.pos + shift)[np.asarray(g.tris, np.int64)]
                for part in meshbox._components(tris):
                    c, h, R = meshbox.oriented_box(tris[part].reshape(-1, 3), 2.0)
                    regioncopy.add_box(self.opt, c, h, R)
                    nb += 1
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
            msg += f", {nb} collision boxes"
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
        mods = self.module_solids()
        key = (self._ff_key, id(self.opt), self.opt.scene_obj_count if self.opt is not None else 0,
               len(self.opt.hulls_raw) if self.opt is not None else 0, len(self.opt.trailer) if self.opt is not None else 0,
               mods[0])
        if getattr(self, "_walk_key", None) != key:
            self._walk_world = walk.World.from_map(self.opt, hm, extra_boxes=mods[1])
            self._walk_key = key
        return self._walk_world

    # modules whose model the game makes solid (cars, doors, walls / objects of RenderNFO ...); pickups and markers are not
    SOLID_MODULES = ("rendernfo", "animatedrendernfo", "cglass", "mp_door", "mp_cosa", "mp_ccar", "mp_boton", "mp_bombzone",
                     "vagonmetro", "mp_moto", "torocar", "mp_coxe")

    def module_solids(self):
        """(key, [76-byte boxes]): a box (turned with the module) around each part of the model of every solid module,
        so the walking test, the start point check ... bump into cars, doors and the objects of the scene like in the
        game (which collides with the object itself, not with the map's collision).  Cached by the modules' places."""
        from .. import meshbox, regioncopy
        if self.scene is None:
            return (None, [])
        recs = [r for r in self.scene.modules if r.parsed is not None and r.clean_name.lower() in self.SOLID_MODULES
                and getattr(r.parsed, "model_name", "") and hasattr(r.parsed, "transform")]
        key = tuple((id(r), str(r.parsed.model_name), np.asarray(r.parsed.transform, np.float32).tobytes()) for r in recs)
        if getattr(self, "_msol_key", None) == key:
            return (hash(key), self._msol)
        out = []
        local: Dict[str, list] = getattr(self, "_msol_local", {})
        for r in recs:
            name = str(r.parsed.model_name)
            if name not in local:
                parts = []
                try:
                    model = self.fs.model(name)
                except Exception:
                    model = None
                if model is not None:
                    for _obj, me in model.lod0_meshes():
                        try:
                            tris = [g[1][:, :3][np.asarray(g[2], np.int64)[: len(g[2]) // 3 * 3].reshape(-1, 3)]
                                    for g in me.build()]
                            t = np.concatenate(tris).astype(np.float64)
                        except Exception:
                            continue
                        if len(t):
                            parts.append(t)
                local[name] = parts
            M = np.asarray(r.parsed.transform, np.float64)
            for t in local[name]:
                w = t @ M[:3, :3] + M[3, :3]
                ext = w.reshape(-1, 3).max(0) - w.reshape(-1, 3).min(0)
                if float(ext.max()) < 80.0:                      # birds, small bits: nothing to bump into
                    continue
                if max(float(ext[0]), float(ext[2])) > 2500.0:     # sea, waves, sky, far scenery: not a wall to walk into
                    continue
                # boxes that follow the shape (a pair of railings is two boxes, not one across the walkway)
                for c, h, R in meshbox.fit(w, thickness=6.0, max_boxes=12):
                    out.append(regioncopy.make_box(c, h, R))
        self._msol_local = local
        self._msol_key, self._msol = key, out
        return (hash(key), out)

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
        opt = self.opt
        if self._hidden():                                   # hidden lights do not light the view either
            import types
            opt = types.SimpleNamespace(lights=[l for l in opt.lights if not self.is_hidden(l, "light")],
                                        old_format=getattr(opt, "old_format", False))
        solo = getattr(self, "light_solo", None)
        if solo is not None:
            if any(l is solo for l in self.opt.lights):     # only that light: what it lights, and nothing else
                import types
                opt = types.SimpleNamespace(lights=[solo], old_format=getattr(self.opt, "old_format", False))
            else:
                self.light_solo = None
        return lights.pack(opt, np.asarray(self.camera.pos, np.float64))

    def set_light_solo(self, l) -> None:
        """Light the lit view with ``l`` only (None: with every light again)."""
        self.light_solo = l

    def light_impact(self, l) -> str:
        """In words, what a light lights (for the ones whose box says nothing: ambient and directional)."""
        from ..opt import LightType
        t = int(l.type)
        c = [float(v) for v in l.diffuse[:3]]
        col = f"RGB {c[0]:.2f} {c[1]:.2f} {c[2]:.2f}"
        if t == LightType.AMBIENT:
            return (f"ambient: lights EVERY face of the map the same, from every side, no matter where it is ({col}, "
                    f"{100 * max(c):.0f}% brightness) - it is the darkest a place can be")
        if t == LightType.DIRECTIONAL:
            d = np.asarray(l.direction, np.float64)
            n = float(np.linalg.norm(d))
            if n < 1e-9:
                return "directional: it has no direction (0, 0, 0) - it lights nothing"
            d = d / n
            down = float(np.degrees(np.arcsin(np.clip(-d[1], -1, 1))))
            share = self._facing_share(-d)
            return (f"directional (a sun): lights the whole map from one side, no distance limit ({col}); it comes "
                    f"{abs(down):.0f} degrees from {'above' if down >= 0 else 'below'}; {100 * share:.0f}% of the surfaces of "
                    f"the map face it (the rest only get the ambient light)")
        if t == LightType.SPOT:
            return f"spot: a cone {float(l.cone):.0f} wide, up to {float(l.end or l.radius):.0f} units ({col})"
        return f"point: full brightness up to {float(l.start):.0f} units, dark from {float(l.end):.0f} ({col})"

    def _facing_share(self, towards) -> float:
        """Share of the area of the map's triangles whose front faces ``towards`` (engine)."""
        from .. import autohm
        key = getattr(self, "_face_cache_key", None)
        if key != (id(self.opt), len(self.opt.meshes), len(self.opt.props)):
            nrm, area = [], []
            used = {p.mesh_index for p in self.opt.props}
            items = [("mesh", i) for i in range(len(self.opt.meshes)) if i not in used] + [("prop", i) for i in range(len(self.opt.props))]
            for k, i in items:
                try:
                    tris, face = autohm.triangles_of(self.opt, k, i)
                except Exception:
                    continue
                if not len(tris):
                    continue
                g = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
                a = np.linalg.norm(g, axis=1)
                ok = a > 1e-9
                g = g[ok] / a[ok, None]
                g *= np.where((g * face[ok]).sum(1) < 0, -1.0, 1.0)[:, None]     # the side the artist meant to be seen
                nrm.append(g); area.append(a[ok] / 2)
            self._face_cache = (np.concatenate(nrm), np.concatenate(area)) if nrm else (np.zeros((0, 3)), np.zeros(0))
            self._face_cache_key = (id(self.opt), len(self.opt.meshes), len(self.opt.props))
        nrm, area = self._face_cache
        if not len(area):
            return 0.0
        return float(area[(nrm @ np.asarray(towards, np.float64)) > 0.05].sum() / area.sum())

    def light_gizmo(self, l, around=None) -> np.ndarray:
        """Line segments (display space, (n, 2, 3)) that show where a light shines: arrows over the area ``around``
        (display point; default the light) for a directional light, rays all round for an ambient one, the cone of a
        spot, the reach of a point light."""
        from .. import particles
        from ..opt import LightType
        t = int(l.type)
        p = np.asarray(l.position, np.float64) * F
        segs = []
        if t == LightType.DIRECTIONAL:
            d = np.asarray(l.direction, np.float64) * F
            n = float(np.linalg.norm(d))
            d = d / n if n > 1e-9 else np.array([0.0, -1.0, 0.0])
            c = p if around is None else np.asarray(around, np.float64)
            side = np.cross(d, [0.0, 1.0, 0.0])
            if np.linalg.norm(side) < 1e-6:
                side = np.array([1.0, 0.0, 0.0])
            side /= np.linalg.norm(side)
            up = np.cross(side, d)
            for a in (-2, -1, 0, 1, 2):
                for b in (-2, -1, 0, 1, 2):
                    tip = c + side * a * 400.0 + up * b * 400.0
                    tail = tip - d * 600.0
                    segs.append((tail, tip))
                    for w in (side, up):                    # the head of the arrow
                        segs.append((tip, tip - d * 80.0 + w * 40.0))
                        segs.append((tip, tip - d * 80.0 - w * 40.0))
            return np.asarray(segs, np.float64)
        if t == LightType.AMBIENT:
            k = np.arange(26)
            phi = np.arccos(1 - 2 * (k + 0.5) / 26)
            th = np.pi * (1 + 5 ** 0.5) * k
            dirs = np.stack([np.sin(phi) * np.cos(th), np.cos(phi), np.sin(phi) * np.sin(th)], 1)
            for v in dirs:
                segs.append((p + v * 60.0, p + v * 220.0))
            out = np.asarray(segs, np.float64)
            return np.concatenate([out, np.asarray(particles.sphere_circles(p, 60.0, 24), np.float64).reshape(-1, 2, 3)])
        if t == LightType.SPOT:
            d = np.asarray(l.direction, np.float64) * F
            n = float(np.linalg.norm(d))
            d = d / n if n > 1e-9 else np.array([0.0, -1.0, 0.0])
            reach = float(l.end or l.radius or 500.0)
            ang = np.radians(min(max(float(l.cone), 1.0), 170.0) / 2)
            side = np.cross(d, [0.0, 1.0, 0.0])
            if np.linalg.norm(side) < 1e-6:
                side = np.array([1.0, 0.0, 0.0])
            side /= np.linalg.norm(side)
            up = np.cross(side, d)
            ring = [p + (d * np.cos(ang) + (side * np.cos(a) + up * np.sin(a)) * np.sin(ang)) * reach for a in np.linspace(0, 2 * np.pi, 25)]
            for q in ring[::3]:
                segs.append((p, q))
            segs += list(zip(ring[:-1], ring[1:]))
            return np.asarray(segs, np.float64)
        out = []
        if float(l.end) > 0:
            out.append(np.asarray(particles.sphere_circles(p, float(l.end)), np.float64).reshape(-1, 2, 3))
        if float(l.start) > 0:
            out.append(np.asarray(particles.sphere_circles(p, float(l.start), 24), np.float64).reshape(-1, 2, 3))
        return np.concatenate(out) if out else np.zeros((0, 2, 3))

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

    CAR_MODELS = ("galloper", "corsa", "206_0", "furgo_cerrada", "ranchera", "coche_lujo", "deportivo", "taxi", "autobus",
                  "camion", "remolquecamion", "mini")

    def model_triangles(self, rec) -> np.ndarray:
        """(n, 3, 3) the triangles of a module's model where it stands (engine)."""
        p = rec.parsed
        model = self.fs.model(p.model_name)
        if model is None:
            raise ValueError(f"model {p.model_name} not found")
        M = np.asarray(p.transform, np.float64)
        tris = []
        for _obj, me in model.lod0_meshes():
            for _mi, v8, ind, _src in me.build():
                w = v8[:, :3].astype(np.float64) @ M[:3, :3] + M[3, :3]
                i = np.asarray(ind, np.int64)[: len(ind) // 3 * 3].reshape(-1, 3)
                tris.append(w[i])
        if not tris:
            raise ValueError("the model has no geometry")
        return np.concatenate(tris)

    def car_boxes(self, rec) -> list:
        """Collision boxes that follow a car's shape (low bonnet and boot, high cabin), not one box round it all."""
        from .. import meshbox
        return meshbox.profile_boxes(self.model_triangles(rec))

    def is_car_scenery(self, rec) -> bool:
        """A RenderNFO drawing one of the game's cars (made from an mp_CCar here, or placed so)."""
        if rec.clean_name.lower() != "rendernfo" or rec.parsed is None:
            return False
        n = os.path.basename(str(getattr(rec.parsed, "model_name", "") or "").rstrip("\0").replace("\\", "/")).lower()
        n = re.sub(r"_hd(\.nfo)$", r"\1", n)
        return any(n.startswith(c) for c in self.CAR_MODELS)

    def car_to_scenery(self, rec, box: bool = True, shaped: bool = True) -> str:
        """An mp_CCar (a car that blows up when shot) becomes plain scenery: the same model drawn by RenderNFO, which nothing
        can destroy, with collision so it still stops players and bullets: boxes that follow its shape (``shaped``: low
        bonnet and boot, high cabin - one sees and shoots over the low parts) or one box round it."""
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
        try:                                               # from now on it really is a RenderNFO (its panel, its saving)
            from ..modules import RenderNFO
            new = RenderNFO()
            for k, v in vars(rec.parsed).items():
                setattr(new, k, v)
            rec.parsed = new
        except Exception:
            pass
        nb = 0
        if box and self.opt is not None and not self.opt.old_format and self.opt.meshes:
            boxes = []
            if shaped:
                try:
                    boxes = self.car_boxes(rec)
                except ValueError:
                    boxes = []
            if not boxes:
                c, h, ax = self.model_box(rec)
                boxes = [(c, np.maximum(h, 2.0), ax)]
            regioncopy.add_boxes(self.opt, boxes)
            nb = len(boxes)
            self.dirty_map = True
        self.dirty_scene = True
        self._walk_key = None
        return (f"{str(rec.object_name).rstrip(chr(0))}: now scenery (RenderNFO) - it cannot be destroyed"
                + (f", with {nb} collision boxes that follow its shape" if nb > 1 else
                   ", with a collision box around it" if nb else "") + " - save the scene and the map")

    def car_collision_boxes(self, rec) -> list:
        """Indices of the collision boxes that lie inside a car's model (the ones car_to_scenery put there)."""
        from .. import crop as cropmod_
        from ..regioncopy import _box_bounds
        if self.opt is None or self.opt.old_format:
            return []
        t = self.model_triangles(rec).reshape(-1, 3)
        lo, hi = t.min(0), t.max(0)
        pad = np.maximum((hi - lo) * 0.08, 8.0)
        out = []
        for i, raw in enumerate(cropmod_.read_block(self.opt).boxes):
            blo, bhi = _box_bounds(raw)
            if np.all(blo >= lo - pad) and np.all(bhi <= hi + pad):
                out.append(i)
        return out

    def scenery_to_car(self, rec) -> str:
        """The other way: a car drawn as scenery (RenderNFO) becomes an mp_CCar again - it can be shot and blown up (the
        game's default car settings); the collision boxes inside it go (the car is solid by itself)."""
        from .. import crop as cropmod_
        from ..binutil import VStr
        from ..modules import DEFAULT_TAIL
        if not self.is_car_scenery(rec):
            raise ValueError("select a car drawn as scenery (RenderNFO with a car model)")
        if self.is_locked(rec):
            return "locked: not changed"
        self.push_undo(True, "scenery to car")
        boxes = self.car_collision_boxes(rec)
        rec.module_name = VStr(b"mp_CCar.dll\0")
        rec.parsed.tail = bytes.fromhex(DEFAULT_TAIL["mp_ccar"])
        try:
            from ..modules import MODULE_TYPES
            cls = MODULE_TYPES.get("mp_ccar")
            if cls is not None:
                new = cls()
                for k, v in vars(rec.parsed).items():
                    setattr(new, k, v)
                rec.parsed = new
        except Exception:
            pass
        if boxes:
            cropmod_.remove_collision_indices(self.opt, boxes)
            self.dirty_map = True
        self.dirty_scene = self.needs_rebake = True
        self._walk_key = None
        return (f"{str(rec.object_name).rstrip(chr(0))}: a car that can be blown up again (mp_CCar)"
                + (f", {len(boxes)} collision boxes inside it taken away" if boxes else "") + " - save the scene and the map")

    def cars_to_scenery(self, box: bool = True, shaped: bool = True) -> str:
        """Every mp_CCar of the scene (not the locked ones)."""
        recs = [r for r in self.scene.modules if r.clean_name.lower() == "mp_ccar" and r.parsed is not None and not self.is_locked(r)]
        if not recs:
            raise ValueError("this scene has no mp_CCar")
        self.push_undo(True, "car to scenery")
        self._undo_off = True
        try:
            for r in recs:
                self.car_to_scenery(r, box, shaped)
        finally:
            self._undo_off = False
        return f"{len(recs)} cars are now scenery (they cannot be destroyed) - save the scene and the map"

    def scenery_to_cars(self) -> str:
        """Every car of the scene drawn as scenery becomes an mp_CCar again (not the locked ones)."""
        recs = [r for r in self.scene.modules if self.is_car_scenery(r) and not self.is_locked(r)]
        if not recs:
            raise ValueError("this scene has no car drawn as scenery")
        self.push_undo(True, "scenery to car")
        self._undo_off = True
        try:
            for r in recs:
                self.scenery_to_car(r)
        finally:
            self._undo_off = False
        return f"{len(recs)} cars can be blown up again (mp_CCar) - save the scene and the map"

    # ================================================================================== weapons allowed on this map
    def mode_dll_source(self) -> str:
        """The DLL the scene's mode runs: this map's own copy if it has one, else the game's DLL next to demo.vpk (or '')."""
        name = str(self.scene.main_module_name).rstrip("\0")
        own = getattr(self, "custom_dlls", {}).get(name.lower())
        return self.find_game_dll(name)

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

    def weapon_sets(self, src: str = ""):
        """[5 x list of weapon ids or None]: the weapons each group is limited to (several of the group) on this map."""
        from .. import dllpatch
        src = src or self.mode_dll_source()
        if not src:
            return None
        try:
            return dllpatch.weapon_sets(open(src, "rb").read())
        except (OSError, ValueError):
            return None

    def weapon_choice(self, src: str = ""):
        """[5 x weapon id or 0]: the weapon each group is fixed to on this map (0 = each player's choice; None: unknown)."""
        from .. import dllpatch
        src = src or self.mode_dll_source()
        if not src:
            return None
        try:
            return dllpatch.weapon_choice(open(src, "rb").read())
        except (OSError, ValueError):
            return None

    def make_weapons_dll(self, allowed, src: str = "", out_dir: str = "", forced=None) -> str:
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
        try:
            second = dllpatch.bomb_zones(open(src, "rb").read())         # the other bomb zones this map's copy counts
            hud = dllpatch.bomb_zones_hud(open(src, "rb").read())
            radar = dllpatch.bomb_zones_radar(open(src, "rb").read())
            overtime = dllpatch.bomb_rules(open(src, "rb").read())       # its bomb time / overtime
            rain = dllpatch.bomb_rain(open(src, "rb").read())            # its rain (Marbella's shower)
            splash = dllpatch.bomb_splash(open(src, "rb").read())
            sounds = dllpatch.shower_sounds(open(src, "rb").read())      # its quieter storm
            volumes = dllpatch.shower_volumes(open(src, "rb").read())
        except (OSError, ValueError):
            second = overtime = None
            hud = radar = True
            rain = (False, False)
            splash = False
            sounds, volumes = None, (100, 100)
        try:                                                  # a DM / DMT / CTF copy that rains on this map
            other_weather = self._weather_other(open(src, "rb").read()) if not rain[0] else None
        except (OSError, AttributeError):
            other_weather = None
        base = os.path.splitext(os.path.basename(src))[0]
        base = re.sub("_" + re.escape(stem) + "$", "", base, flags=re.I)
        stock = self.find_game_dll(base + ".dll")            # always from the game's own DLL when there is one
        if stock and os.path.isfile(stock) and os.path.abspath(stock) != os.path.abspath(src):
            src = stock
        name = f"{base}_{stem}.dll"
        out_dir = out_dir or self.export_dir()
        os.makedirs(out_dir, exist_ok=True)
        dst = os.path.join(out_dir, name)
        if os.path.abspath(dst).lower() == os.path.abspath(src).lower():
            raise ValueError("the copy would be written over its source")
        rep = dllpatch.patch_weapon_groups(src, dst, allowed, forced)
        if (second and second[0]) or rain[0]:
            dllpatch.patch_bomb_zones(dst, dst, second[0] if second else [], bool(second and second[1]), hud, radar,
                                      rain=rain[0], storm=rain[1] or not rain[0], splash=splash,
                                      sounds=sounds if rain[0] else None, volumes=volumes)
        elif other_weather and dllpatch.can_have_weather(open(dst, "rb").read()):
            self._apply_weather_other(dst, other_weather)
        if overtime:
            dllpatch.patch_bomb_rules(dst, dst, overtime[0], overtime[1])
        fixed = dllpatch.weapon_choice(open(dst, "rb").read())
        sets = dllpatch.weapon_sets(open(dst, "rb").read())
        self.push_undo(False, "weapons DLL")
        self.scene.main_module_name = VStr((name + "\0").encode("cp1252"))
        self.custom_dlls = dict(getattr(self, "custom_dlls", {}), **{name.lower(): dst})
        self.dirty_scene = True
        self._wg_key = None
        on = ", ".join(str(i + 1) for i, a in enumerate(rep) if a) or "none"
        off = ", ".join(str(i + 1) for i, a in enumerate(rep) if not a) or "none"
        rounds = dllpatch.weapon_ammo(open(dst, "rb").read())
        only = "; ".join(f"group {g + 1}: only the {dllpatch.WEAPON_IDS.get(w, w)}"
                         + (f" ({rounds[g]} rounds, as when chosen in the menu)" if g in rounds else "")
                         for g, w in enumerate(fixed) if w and rep[g])
        some = "; ".join(f"group {g + 1}: only " + ", ".join(dllpatch.WEAPON_IDS.get(w, str(w)) for w in ids)
                         + f" (another choice of the menu gets the {dllpatch.WEAPON_IDS.get(ids[0], ids[0])})"
                         for g, ids in enumerate(sets) if ids and rep[g])
        only = "; ".join(x for x in (only, some) if x)
        return (f"{name}: weapon groups given: {on}; not given: {off}" + (f"; {only}" if only else "")
                + f". Copy it into the game folder (next to {base}.dll) on the server and on every player's PC")

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

    # ================================================================================== listening to the sounds of a map
    def module_sounds(self, rec) -> List[str]:
        """The .wav files a module names (a sound source, a door, a button, any kind) as the scene writes them; a particle
        emitter gives the sound of the sound source it points to."""
        import re
        p = rec.parsed
        try:
            raw = bytes(rec.data) if p is None else p.to_bytes()
        except Exception:
            raw = bytes(rec.data or b"")
        out = []
        for m in re.finditer(rb"([\x20-\x7e\x80-\xff]{1,150}?\.wav)\x00", raw, re.I):
            n = m.group(1).decode("cp1252", "replace").strip()
            if n not in out:
                out.append(n)
        link = str(getattr(p, "sound", "") or "").rstrip("\0").lower() if p is not None and rec.clean_name.lower() == "cparticlesystem" else ""
        if link:
            for r in self.scene.modules:
                if r is not rec and str(r.object_name).rstrip("\0").lower() == link:
                    out += [n for n in self.module_sounds(r) if n not in out]
        return out

    def sound_search_dirs(self) -> List[str]:
        """Where a sound is looked for (to tell the user when it is not found)."""
        base = getattr(self, "game_dir", "") or os.path.dirname(os.path.abspath(self.fs.root))
        return [os.path.join(base, "wavs"), os.path.join(self.fs.root, "wavs")]

    # ================================================================================== twin ships: the same lights on both
    def twin_lights(self, mirror: bool = True, gap: float = 800.0) -> str:
        """Give ship B (the copy) exactly the lights of ship A.  ``mirror``: each one on the opposite side of its ship, so
        the two ships are lit like a reflection of each other across the water between them; otherwise at the same place
        of the ship.  The lights B had are replaced; a sun / ambient light stored twice is left once."""
        import copy as _copy
        from .. import twinships
        hlo, hhi, hm, world = self._twin_stock()
        off = twinships.ship_offset(self.opt, hm, hlo, hhi, gap, world)
        if abs(off) < float(hhi[0] - hlo[0]) * 0.5:
            raise ValueError("this does not look like a twin ships map")
        pad = 150.0
        in_a = lambda l: hlo[0] - pad <= float(l.position[0]) <= hhi[0] + pad
        in_b = lambda l: hlo[0] - pad + off <= float(l.position[0]) <= hhi[0] + pad + off
        local = [l for l in self.opt.lights if int(l.type) in (0, 1)]
        src = [l for l in local if in_a(l)]
        if not src:
            raise ValueError("ship A has no point lights to copy")
        self.push_undo(True, "twin lights")
        old_b = [l for l in local if in_b(l) and not in_a(l)]
        cx = (float(hlo[0]) + float(hhi[0])) / 2
        keep, seen, dups = [], set(), 0
        for l in self.opt.lights:
            if any(l is o for o in old_b):
                continue
            if int(l.type) in (2, 3):                        # sun / ambient: the same one twice lights everything twice
                k = (int(l.type), tuple(np.round(np.asarray(l.direction, np.float64), 3)), tuple(round(float(v), 3) for v in l.diffuse[:3]))
                if k in seen:
                    dups += 1
                    continue
                seen.add(k)
            keep.append(l)
        new = []
        for l in src:
            c = _copy.deepcopy(l)
            p = np.asarray(l.position, np.float64).copy()
            p[0] = (2 * cx - p[0] if mirror else p[0]) + off
            c.position = p.astype(np.float32)
            if mirror:
                d = np.asarray(l.direction, np.float64).copy()
                d[0] = -d[0]
                c.direction = d.astype(np.float32)
            new.append(c)
        self.opt.lights[:] = keep + new
        self._forget_lock_keys()
        self.dirty_map = True
        moved = "; ".join(f"{np.round(o.position[0]):.0f} -> {np.round(n.position[0]):.0f}" for o, n in zip(old_b, new))
        if moved:
            self.log("ship B lights, x before -> after: " + moved)
        return (f"ship B now has the {len(new)} lights of ship A" + (" mirrored" if mirror else "") + f" ({len(old_b)} replaced"
                + (f", {dups} repeated sun / ambient lights removed" if dups else "") + ") - save the map")

    def light_ship(self, l) -> str:
        """'A' / 'B' for a point / spot light of a twin ships map ('' otherwise): shown in the list of lights."""
        if int(l.type) not in (0, 1) or self.opt is None:
            return ""
        key = id(self.opt)
        if getattr(self, "_ls_key", None) != key:
            self._ls_key, self._ls = key, None
            try:
                from .. import twinships
                hlo, hhi, hm, world = self._twin_stock()
                off = twinships.ship_offset(self.opt, hm, hlo, hhi, 800.0, world)
                if abs(off) >= float(hhi[0] - hlo[0]) * 0.5:
                    self._ls = (float(hlo[0]) - 150.0, float(hhi[0]) + 150.0, float(off))
            except Exception:
                self._ls = None
        if self._ls is None:
            return ""
        x = float(l.position[0])
        a0, a1, off = self._ls
        return "A" if a0 <= x <= a1 else ("B" if a0 + off <= x <= a1 + off else "")

    # ================================================================================== seeing far: no pop-in
    def map_extent(self):
        """(lo, hi) engine of the map itself: its meshes and props (where players can be).  Left out: the modules (sea,
        yachts, gulls), anything huge, and the pieces some maps park very far away from everything else."""
        boxes = []
        for inst in (self.geometry.instances if self.geometry is not None else []):
            a = np.array([inst.lo[0], inst.lo[1], -inst.hi[2]]); b = np.array([inst.hi[0], inst.hi[1], -inst.lo[2]])
            if inst.kind == "module" or float(np.max(b - a)) > 25000.0:
                continue
            boxes.append((a, b))
        if not boxes:
            raise ValueError("the map is empty")
        cen = np.array([(a + b) / 2 for a, b in boxes])
        mid = np.median(cen, axis=0)
        near = np.linalg.norm(cen - mid, axis=1) < 30000.0
        lo = np.min([a for (a, _), k in zip(boxes, near) if k], axis=0)
        hi = np.max([b for (_, b), k in zip(boxes, near) if k], axis=0)
        return lo, hi

    def view_distance_needed(self) -> float:
        lo, hi = self.map_extent()
        return float(np.ceil(np.linalg.norm(hi - lo) * 1.05 / 500.0) * 500.0)

    def see_whole_map(self) -> str:
        """Push the camera's far plane (and the fog, if it would hide things before it) so that from one end of the map the
        other end is still drawn.  The game stops drawing everything - map, models, players - beyond the far plane."""
        need = self.view_distance_needed()
        sc = self.scene
        if sc.cam_far >= need and sc.fog_far >= need:
            return f"the far plane ({sc.cam_far:.0f}) already covers the whole map ({need:.0f})"
        self.push_undo(False, "view distance")
        old = sc.cam_far
        sc.cam_far = float(max(sc.cam_far, need))
        if sc.fog_far < sc.cam_far * 1.02:                   # fog that ends before the far plane would hide the far end
            sc.fog_far = float(sc.cam_far * 1.05)
        sc.fog_near = float(max(sc.fog_near, sc.cam_far * 0.9)) if sc.fog_near >= old * 0.9 else sc.fog_near
        self.dirty_scene = True
        return (f"camera far plane {old:.0f} -> {sc.cam_far:.0f} (the map measures {need / 1.05:.0f} from end to end); "
                f"fog {sc.fog_near:.0f} - {sc.fog_far:.0f} - save the scene")

    def lod_meshes(self) -> int:
        return sum(1 for m in self.opt.meshes if len(m.lods) > 1) if self.opt is not None else 0

    def full_detail_meshes(self, only=None) -> str:
        """Meshes with levels of detail change to a simpler version as you walk away (some end as one triangle = they vanish).
        This keeps only the detailed version of each, drawn at any distance, like most meshes of the map already are."""
        from ..fill import LOD_FAR
        pick = None if only is None else {id(m) for m in only}
        n = sum(1 for m in self.opt.meshes if len(m.lods) > 1 and (pick is None or id(m) in pick)) if self.opt else 0
        if not n:
            return "no mesh of this map changes with the distance" if pick is None else \
                "it does not change with the distance (already full detail)"
        self.push_undo(True, "full detail")
        store = self._lod_store()
        for m in self.opt.meshes:
            if pick is not None and id(m) not in pick:
                continue
            if len(m.lods) > 1 and not self.is_locked(m, "mesh"):
                sig = _lod_sig(m)
                if sig is not None:                          # kept next to the editor: "Restore detail" puts them back
                    store[_here_key(sig)] = (sig[1], m.lods[0].unk, m.lods[1:])
                del m.lods[1:]
                m.lods[0].unk = LOD_FAR
        self._save_lod_store()
        self._forget_lock_keys()
        self.dirty_map = self.needs_rebake = True
        return f"{n} meshes now keep their full detail at any distance - save the map"

    # ================================================================================== levels of detail back
    def _lod_path(self) -> str:
        from .. import settings
        d = os.path.join(os.path.dirname(settings.path()), "lods")
        os.makedirs(d, exist_ok=True)
        return os.path.join(d, self.map_stem().lower() + ".vtlod")

    def _lod_store(self) -> dict:
        import pickle
        from .state_tools import _PieceUnpickler
        if getattr(self, "_lods_for", None) != self.map_stem().lower():
            self._lods, self._lods_for = {}, self.map_stem().lower()
            try:
                with open(self._lod_path(), "rb") as f:
                    self._lods = _PieceUnpickler(f).load()
            except Exception:
                self._lods = {}
        return self._lods

    def _kept_here(self, store):
        """The kept entries that belong to meshes of the map as it is now."""
        for m in self.opt.meshes:
            if len(m.lods) == 1:
                sig = _lod_sig(m)
                if sig is not None and _here_key(sig) in store:
                    yield m

    def _save_lod_store(self) -> None:
        import pickle
        try:
            with open(self._lod_path(), "wb") as f:
                pickle.dump(self._lods, f)
        except OSError as e:
            self.log(f"levels of detail not kept: {e}")

    def _game_lod_index(self) -> dict:
        """Signature -> (lowest point, LOD0 distance, far levels) of every mesh with levels of detail in the game's maps."""
        from ..opt import OptMap
        if getattr(self, "_glod", None) is None:
            idx = {}
            for rel in self.fs.list("nfos", ".opt"):
                p = self.fs.find(rel)
                try:
                    o = OptMap.load(p)
                except Exception:
                    continue
                for m in o.meshes:
                    if len(m.lods) > 1:
                        sig = _lod_sig(m)
                        if sig is not None and sig[0] not in idx:
                            idx[sig[0]] = (sig[1], m.lods[0].unk, m.lods[1:])
            self._glod = idx
        return self._glod

    def mesh_detail(self, mesh) -> dict:
        """{'lods': [triangles of each version], 'restorable': its far versions were kept} of one mesh (HD state)."""
        tri = [int(sum(len(sm.indices) // 3 for part in l.parts for sm in part.submeshes)) for l in mesh.lods]
        sig = _lod_sig(mesh) if len(mesh.lods) == 1 else None
        rest = bool(sig is not None and _here_key(sig) in self._lod_store())
        return {"lods": tri, "restorable": rest}

    def detail_restorable(self) -> int:
        """How many meshes of this map have only their detailed version now but had (or have, in the game) far ones."""
        if self.opt is None:
            return 0
        store = self._lod_store()
        n = 0
        for m in self.opt.meshes:
            if len(m.lods) == 1:
                sig = _lod_sig(m)
                if sig is not None and _here_key(sig) in store:
                    n += 1
        return n

    def restore_detail_meshes(self, search_game: bool = True, only=None) -> str:
        """Put back the simpler far versions of the meshes 'Full detail at any distance' took away: from what the editor
        kept, else from the game's own maps (a copied ship finds its original).  Meshes moved or copied whole are found too."""
        import copy as _copy
        from ..opt import translate_mesh
        if self.opt is None:
            raise ValueError("open a map first")
        store = self._lod_store()
        # what the editor kept says exactly which meshes lost their far versions; only without it (maps changed with an
        # older version) the game's maps are searched for each shape
        game = self._game_lod_index() if (search_game and not any(self._kept_here(store))) else {}
        todo = []
        pick = None if only is None else {id(m) for m in only}
        for m in self.opt.meshes:
            if len(m.lods) != 1 or self.is_locked(m, "mesh") or (pick is not None and id(m) not in pick):
                continue
            sig = _lod_sig(m)
            if sig is None:
                continue
            src = store.get(_here_key(sig)) or game.get(sig[0])
            if src is not None:
                todo.append((m, sig[1], src))
        if not todo:
            return "nothing to restore: no mesh of this map lost its far versions (or the original was not found)"
        self.push_undo(True, "restore detail")
        for m, lo, (lo0, unk, far) in todo:
            far = _copy.deepcopy(far)
            d = np.asarray(lo, np.float64) - np.asarray(lo0, np.float64)
            if np.abs(d).max() > 0.01:                        # the mesh was moved: the far versions go with it
                tmp = type(m)(materials=m.materials, lods=far, corners=np.zeros((8, 3), np.float32))
                tmp.world_transform = np.eye(4, dtype=np.float32)
                translate_mesh(tmp, d)
                far = tmp.lods
            m.lods[0].unk = unk
            m.lods[1:] = far
        self._forget_lock_keys()
        self.dirty_map = self.needs_rebake = True
        return f"{len(todo)} meshes have their far versions again (as the game had them) - save the map"

    # ================================================================================== shading layer (glow)
    def glow_textures(self) -> List[str]:
        names = {os.path.basename(p) for p in self.fs.list("texs", ".tex")}
        return sorted((n for n in names if n.lower().startswith("glow")), key=str.lower)

    def shading_targets(self, scope: str = "selection") -> list:
        """Mesh numbers the shading layer goes on: the selection / group (a prop gives its mesh: every copy changes),
        or every mesh of the map."""
        if self.opt is None:
            return []
        if scope == "map":
            used = {p.mesh_index for p in self.opt.props}
            return [i for i, m in enumerate(self.opt.meshes) if m.lods and (i in used or len(m.materials))]
        out = []
        for kind, i in self.collision_targets("selection"):
            mi = i if kind == "mesh" else self.opt.props[i].mesh_index
            if mi not in out:
                out.append(mi)
        return out

    def apply_shading(self, texture: str, size: float = 650.0, centre=None, scope: str = "selection", aspect: float = 1.0) -> str:
        """Give the meshes the shading layer of mp_b_garaje & co.: ``texture`` multiplied over their own, repeated every
        ``size`` units, a spot centred on ``centre`` (engine; default the camera)."""
        from .. import glowlayer
        if self.fs.texture(texture) is None:
            raise ValueError(f"texture {texture} not found")
        targets = [i for i in self.shading_targets(scope) if not self.is_locked(self.opt.meshes[i], "mesh")]
        if not targets:
            raise ValueError("select a mesh or a prop of the map first (or use 'whole map')")
        c = np.asarray(self.camera.pos, np.float64) * [1, 1, -1] if centre is None else np.asarray(centre, np.float64)
        self.push_undo(True, "shading layer")
        n = sum(glowlayer.apply(self.opt, i, texture, max(float(size), 10.0), c, aspect) for i in targets)
        self._forget_lock_keys()
        self.dirty_map = self.needs_rebake = True
        return (f"{len(targets)} meshes ({n} parts) have the shading layer {texture}, one spot every {size:.0f} - only visible "
                f"in the game - save the map")

    def remove_shading(self, scope: str = "selection") -> str:
        from .. import glowlayer
        targets = [i for i in self.shading_targets(scope) if not self.is_locked(self.opt.meshes[i], "mesh")]
        if not targets:
            raise ValueError("select a mesh or a prop of the map first (or use 'whole map')")
        self.push_undo(True, "remove shading")
        n = sum(glowlayer.remove(self.opt, i) for i in targets)
        self._forget_lock_keys()
        self.dirty_map = self.needs_rebake = True
        return f"shading layer removed from {n} parts of {len(targets)} meshes - save the map"

    def make_shading_texture(self, name: str, centre: float, edge: float, colour=(1.0, 1.0, 1.0), softness: float = 1.0) -> str:
        """A new spot texture glow_<name>.tex (never over an existing one)."""
        from .. import glowlayer
        stem = "glow_" + ("".join(ch for ch in name if ch.isalnum() or ch in "_-") or "vtoy")
        rgba = glowlayer.make_texture(centre, edge, colour, softness)
        return self._new_texture_name(stem, rgba, "glow_vtoy")

    # ================================================================================== pieces of other maps
    def library_maps(self) -> List[str]:
        """The maps (.opt) of the game the pieces can come from (not this one)."""
        own = os.path.basename(str(self.opt.path or "")).lower() if self.opt is not None else ""
        names = {os.path.basename(p) for p in self.fs.list("nfos", ".opt")}
        return sorted((n for n in names if n.lower() != own), key=str.lower)

    def _lib_map(self, name: str):
        from ..opt import OptMap
        if getattr(self, "_libmap", (None, None))[0] != name.lower():
            p = self.fs.find("nfos/" + name)
            if not p:
                raise ValueError(f"{name} not found")
            o = OptMap.load(p)
            if o.old_format:
                raise ValueError(f"{name} is in the old format: its pieces cannot be taken")
            self._libmap = (name.lower(), o)
        return self._libmap[1]

    def library_pieces(self, name: str) -> list:
        from .. import meshlib
        key = ("pieces", name.lower())
        if getattr(self, "_libpieces", (None,))[0] != key:
            self._libpieces = (key, meshlib.pieces(self._lib_map(name)))
        return self._libpieces[1]

    def library_parts(self, name: str, kind: str, index: int) -> list:
        from .. import meshlib
        return meshlib.parts(self._lib_map(name), kind, index)

    def library_piece_preview(self, name: str, kind: str, index: int, part=None):
        """Geometry of a piece of another map, in front of the camera, to see it before taking it."""
        from .. import meshlib
        from ..opt import OptMap
        from ..render.geometry import bake_scene
        from ..scn import Scene
        me = meshlib.extract(self._lib_map(name), kind, index, part)
        lo, hi = cropmod.mesh_bounds(me)
        dist = float(min(max(np.max(hi - lo) * 1.3, 500.0), 20000.0))
        at = (np.asarray(self.camera.pos, np.float64) + np.asarray(self.camera.front, np.float64) * dist) * [1, 1, -1]
        meshlib.place(me, at - [0.0, (hi - lo)[1] / 2, 0.0])
        o = OptMap()
        o.meshes.append(me)
        return bake_scene(self.fs, Scene(), o)

    def import_library_piece(self, name: str, kind: str, index: int, part=None, at=None, yaw: float = 0.0,
                             collision: bool = True, box: bool = False) -> str:
        """Bring a piece of another map into this one as a new mesh (its textures are the game's, nothing is copied).
        ``collision``: its floor / wall faces in the .hm, made from its triangles."""
        from .. import autohm, meshlib, regioncopy
        from .state import Selection
        if self.opt is None:
            raise ValueError("open a map first")
        me = meshlib.extract(self._lib_map(name), kind, index, part)
        meshlib.place(me, self._here() if at is None else at, yaw)
        missing = sorted({t for m in me.materials for t in m.textures if t and self.fs.texture(t) is None})
        self.push_undo(True, "piece of another map")
        mi = cropmod.add_mesh(self.opt, me)
        rep = None
        if collision:
            hm, _ = self._hm_or_new()
            rep = autohm.generate(self.opt, hm, [("mesh", mi)], replace=False)
        if box:
            tris, _ = autohm.triangles_of(self.opt, "mesh", mi)
            c, h = autohm.bounding_box(tris)
            regioncopy.add_box(self.opt, c, h)
        self.selection = Selection("mesh", me, f"mesh {mi}")
        self.multi = []
        self._ff_key = self._walk_key = None
        self.dirty_map = self.needs_rebake = True
        lo, hi = cropmod.mesh_bounds(me)
        sz = (hi - lo) / 100.0
        msg = (f"{kind} {index} of {name} added ({sum(len(s.indices) // 3 for s in me.render_submeshes())} triangles, "
               f"{sz[0]:.1f} x {sz[1]:.1f} x {sz[2]:.1f} m)")
        if rep is not None:
            msg += f"; collision: {rep['floor']} floor, {rep['wall']} wall faces"
        if missing:
            msg += "; MISSING textures: " + ", ".join(missing[:5])
        return msg + " - save the map"


def _lod_sig(m):
    """(signature of the detailed version of a mesh - its shape, wherever it is -, its lowest point) or None."""
    import hashlib
    pts = [s.vertices["pos"] for s in m.render_submeshes() if s.vertices is not None and len(s.vertices)]
    if not pts:
        return None
    p = np.concatenate(pts).astype(np.float64)
    lo = p.min(0)
    h = hashlib.md5(np.round(p - lo).astype(np.int32).tobytes()).hexdigest()
    return f"{len(p)}:{h}", lo


def _here_key(sig) -> str:
    """A kept mesh: its shape and where it is."""
    return sig[0] + "@" + ",".join(str(int(round(float(v)))) for v in sig[1])

