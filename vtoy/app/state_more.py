"""More map tools: paths of several points, the object brush, drop to the floor, align / distribute, the fall finder, spawn
checks, the load map, collision clean-up, texture search / replace, sector rebuild and re-timing .key animations.

All of it works on the map / scene being edited, one undo step per action, and never writes over a file of the game."""
from __future__ import annotations

import math
import os
from typing import Dict, List, Optional, Sequence

import numpy as np

from .. import crop as cropmod
from ..opt import translate_mesh

F = np.array([1.0, 1.0, -1.0])


class MoreOps:
    # ================================================================================== helpers
    def _selected(self) -> list:
        """The selection plus the group (Ctrl+click), without locked ones."""
        out = []
        for s in ([self.selection] if self.selection is not None else []) + list(getattr(self, "multi", []) or []):
            if s is None or any(o.ref is s.ref for o in out):
                continue
            if self.blocked_by_lock(s):
                continue
            out.append(s)
        return out

    def _batch(self, label: str):
        """One undo step for many edits: ``with self._batch('x'):``."""
        st = self

        class _B:
            def __enter__(self_):
                st.push_undo(True, label)
                st._undo_off = True
                return self_

            def __exit__(self_, *a):
                st._undo_off = False
                return False
        return _B()

    def _visible_kinds(self) -> list:
        used = {p.mesh_index for p in self.opt.props}
        return [("mesh", i) for i in range(len(self.opt.meshes)) if i not in used] + \
               [("prop", i) for i in range(len(self.opt.props))]

    def _map_tris(self):
        """(triangles (n, 3, 3) engine, transparent (n,) bool, owner (n,) item number) of everything drawn in the map,
        cached until the map changes."""
        from .. import autohm
        key = (id(self.opt), len(self.opt.meshes), len(self.opt.props), getattr(self, "_tri_ver", 0))
        if getattr(self, "_mt_key", None) == key:
            return self._mt
        tris, alpha, owner = [], [], []
        cache: Dict[str, bool] = {}

        def has_alpha(t: str) -> bool:
            k = str(t).lower()
            if k not in cache:
                tx = self.fs.texture(t) if t else None
                cache[k] = bool(tx is not None and tx.has_alpha)
            return cache[k]
        for n, (kind, i) in enumerate(self._visible_kinds()):
            try:
                me, M = autohm._mesh_matrix(self.opt, kind, i)
            except Exception:
                continue
            for sm in me.render_submeshes():
                if sm.vertices is None or not len(sm.vertices) or len(sm.indices) < 3:
                    continue
                idx = np.asarray(sm.indices, np.int64)[: len(sm.indices) // 3 * 3].reshape(-1, 3)
                idx = idx[(idx < len(sm.vertices)).all(1)]
                if not len(idx):
                    continue
                p = sm.vertices["pos"].astype(np.float64) @ M[:3, :3] + M[3, :3]
                mat = me.materials[sm.material_index] if sm.material_index < len(me.materials) else None
                tex = (mat.textures[0] if mat is not None and mat.textures else "") or (mat.diffuse if mat is not None else "")
                tris.append(p[idx])
                alpha.append(np.full(len(idx), has_alpha(tex)))
                owner.append(np.full(len(idx), n))
        if tris:
            self._mt = (np.concatenate(tris), np.concatenate(alpha), np.concatenate(owner))
        else:
            self._mt = (np.zeros((0, 3, 3)), np.zeros(0, bool), np.zeros(0, int))
        self._mt_key = key
        return self._mt

    def _changed_geometry(self):
        self._tri_ver = getattr(self, "_tri_ver", 0) + 1

    # ================================================================================== collision goes with its object
    def carry_on(self) -> bool:
        """Do moving, turning, scaling, copying and deleting a mesh / prop take its collision along? (Settings)"""
        if getattr(self, "_carry_off", False):
            return False
        v = getattr(self, "carry_collision", None)
        if v is None:
            try:
                from .. import settings
                v = settings.get("carry_collision")
            except Exception:
                v = None
            v = True if v is None else bool(v)
            self.carry_collision = v
        return bool(v)

    def set_carry(self, on: bool) -> None:
        from .. import settings
        self.carry_collision = bool(on)
        try:
            settings.set("carry_collision", bool(on))
        except Exception:
            pass

    def fresh_bounds(self, sel):
        """(lo, hi) engine of a mesh / prop from its vertices now (not the drawing baked a moment ago)."""
        if sel.kind == "mesh":
            lo, hi = cropmod.mesh_bounds(sel.ref)
            return np.asarray(lo, np.float64), np.asarray(hi, np.float64)
        if sel.kind == "prop":
            pr = sel.ref
            if not (0 <= pr.mesh_index < len(self.opt.meshes)):
                return None
            me = self.opt.meshes[pr.mesh_index]
            lo, hi = cropmod.mesh_bounds(me)
            M = np.linalg.inv(np.asarray(me.world_transform, np.float64)) @ np.asarray(pr.transform, np.float64)
            q = np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])]) @ M[:3, :3] + M[3, :3]
            return q.min(0), q.max(0)
        return None

    def carry_parts(self, sel):
        """The collision of a mesh / prop (what lies inside its bounds), or None (collision not carried / not solid)."""
        from .. import carry
        if sel is None or sel.kind not in ("mesh", "prop") or self.opt is None or not self.carry_on():
            return None
        b = self.fresh_bounds(sel)
        if b is None or not np.all(np.isfinite(b[0])):
            return None
        try:
            hm = self.heightmap_edit()
        except ValueError:
            hm = None
        boxes, faces = carry.collect(self.opt, hm, b[0], b[1])
        return (boxes, faces, hm) if (boxes or faces) else None

    def carry_apply(self, parts, A, copy: bool = False) -> tuple:
        from .. import carry
        if not parts:
            return (0, 0)
        boxes, faces, hm = parts
        r = carry.apply(self.opt, hm, boxes, faces, A, copy)
        self.dirty_map = True
        self._walk_key = None
        self._ff_key = None
        self._col_key = None
        return r

    def carry_remove(self, parts) -> tuple:
        from .. import carry
        if not parts:
            return (0, 0)
        boxes, faces, hm = parts
        r = carry.remove(self.opt, hm, boxes, faces)
        self.dirty_map = True
        self._walk_key = None
        self._ff_key = None
        return r

    # ================================================================================== suns / ambient lights: where the marker is
    # A directional or ambient light has NO position in the game's file: it lights the whole map (the .opt keeps only the
    # direction of a sun, and nothing of an ambient light but its colours).  The editor remembers where you put their
    # markers (vtoy_editor.json, "light_marks"), so they stay there after saving and loading.
    @staticmethod
    def light_has_position(l) -> bool:
        from ..opt import LightType
        return int(l.type) in (int(LightType.POINT), int(LightType.SPOT))

    def _light_mark_keys(self) -> list:
        from ..opt import LightType
        out, n = [], {}
        for l in (self.opt.lights if self.opt is not None else []):
            t = int(l.type)
            if t in (int(LightType.DIRECTIONAL), int(LightType.AMBIENT)):
                k = n.get(t, 0)
                n[t] = k + 1
                out.append((l, f"{t}:{k}"))
        return out

    def save_light_marks(self) -> None:
        from .. import settings
        try:
            marks = {k: [round(float(v), 1) for v in l.position] for l, k in self._light_mark_keys()}
            d = dict(settings.get("light_marks") or {})
            if marks:
                d[self.map_stem().lower()] = marks
            else:
                d.pop(self.map_stem().lower(), None)
            settings.set("light_marks", d)
        except Exception:
            pass

    def restore_light_marks(self) -> int:
        from .. import settings
        try:
            marks = (settings.get("light_marks") or {}).get(self.map_stem().lower(), {})
        except Exception:
            return 0
        n = 0
        for l, k in self._light_mark_keys():
            if k in marks:
                l.position = np.asarray(marks[k], np.float32)
                n += 1
        return n

    # ================================================================================== 1. paths of several points
    def add_solid_path(self, shape: str, points, width: float, height: float, texture: str = "tablones.tex",
                       tile: float = 128.0, closed: bool = False) -> str:
        """A railing / wall / plank ... that follows the points A, B, C ... (one solid per stretch, each with its collision,
        each editable later).  ``closed`` joins the last point with the first."""
        pts = [np.asarray(p, np.float64) for p in points]
        if len(pts) < 2:
            raise ValueError("mark at least two points")
        if closed and len(pts) > 2:
            pts = pts + [pts[0]]
        made = 0
        with self._batch("solid along a path"):
            for a, b in zip(pts[:-1], pts[1:]):
                if np.hypot(*(b - a)[[0, 2]]) < 1.0:
                    continue
                self.add_solid_between(shape, a, b, width, height, texture, tile)
                made += 1
        self._changed_geometry()
        return f"{made} stretches of {shape} along the path (each with its collision) - save the map"

    def add_collision_path(self, points, width: float = 12.0, height: float = 110.0, closed: bool = False,
                           step: float = 200.0) -> str:
        """Invisible collision along the points A, B, C ...: thin boxes ``width`` thick and ``height`` tall standing on the
        points, turned like each stretch.  A stretch that goes up or down is cut in pieces of ``step`` so the boxes follow
        the slope.  Nothing is drawn: for a railing that is already there but lets people through."""
        from .. import regioncopy
        if self.opt is None or self.opt.old_format:
            raise ValueError("this map has no collision boxes (old format)")
        pts = [np.asarray(p, np.float64) for p in points]
        if len(pts) < 2:
            raise ValueError("mark at least two points")
        if closed and len(pts) > 2:
            pts = pts + [pts[0]]
        w, h = max(float(width), 2.0), max(float(height), 2.0)
        self.push_undo(True, "collision along a path")
        n = 0
        for a, b in zip(pts[:-1], pts[1:]):
            flat = float(np.hypot(*(b - a)[[0, 2]]))
            if flat < 1.0:
                continue
            k = 1 if abs(b[1] - a[1]) < 20.0 else max(1, int(math.ceil(flat / step)))
            yaw = math.atan2(b[2] - a[2], b[0] - a[0])
            c_, s_ = math.cos(yaw), math.sin(yaw)
            R = np.array([[c_, 0.0, s_], [0.0, 1.0, 0.0], [-s_, 0.0, c_]])
            for j in range(k):
                p0, p1 = a + (b - a) * (j / k), a + (b - a) * ((j + 1) / k)
                lo_y, hi_y = min(p0[1], p1[1]), max(p0[1], p1[1]) + h
                L = flat / k
                centre = np.array([(p0[0] + p1[0]) / 2, (lo_y + hi_y) / 2, (p0[2] + p1[2]) / 2])
                # a little longer than the stretch: no gap at the corners
                regioncopy.add_box(self.opt, centre, np.array([L / 2 + w / 2, (hi_y - lo_y) / 2, w / 2]), R)
                n += 1
        self.dirty_map = True
        self._walk_key = None
        self._ff_key = None
        return f"{n} invisible collision boxes along the path ({self.path_length(pts) / 100:.1f} m) - save the map"

    def path_length(self, points) -> float:
        p = [np.asarray(q, np.float64) for q in points]
        return float(sum(np.linalg.norm(b - a) for a, b in zip(p[:-1], p[1:])))

    def place_along_path(self, points, every: float, turn: bool = True, on_floor: bool = True,
                         start: float = 0.0) -> str:
        """Copies of the selected object (prop, model module, mesh) every ``every`` units along the path, turned like
        the path (``turn``) and standing on the floor (``on_floor``)."""
        from .state import Selection
        src = self.selection
        if src is None or src.kind not in ("prop", "module", "mesh"):
            raise ValueError("select the object to repeat (a prop, a model or a mesh)")
        pts = [np.asarray(p, np.float64) for p in points]
        if len(pts) < 2:
            raise ValueError("mark at least two points")
        every = float(every)
        if every < 10:
            raise ValueError("the distance between copies must be at least 10")
        spots = []
        d = float(start)
        for a, b in zip(pts[:-1], pts[1:]):
            seg = float(np.linalg.norm(b - a))
            while d <= seg + 1e-6:
                t = d / seg if seg > 0 else 0.0
                spots.append((a + (b - a) * t, b - a))
                d += every
            d -= seg
        if len(spots) > 500:
            raise ValueError(f"that would make {len(spots)} copies: use a bigger distance")
        base = self.position_of(src)
        made = []
        with self._batch("copies along a path"):
            for at, direction in spots:
                new = self.duplicate_selection(src, at - base)
                if turn and new.kind != "mesh" and self.has_matrix(new):
                    yaw = math.degrees(math.atan2(-direction[2], direction[0]))
                    rot = self.rotation_of(new)
                    self.set_rotation(new, [rot[0], yaw, rot[2]])
                made.append(new)
            if on_floor:
                self._drop(made)
        self.selection = made[0] if made else src
        self.multi = made[1:]
        self._changed_geometry()
        return f"{len(made)} copies along the path ({self.path_length(pts) / 100:.1f} m) - they are selected"

    # ================================================================================== 2. the object brush
    def scatter(self, palette: Sequence, centre, radius: float = 600.0, count: int = 10, turn: bool = True,
                scale=(0.85, 1.2), gap: float = 120.0, seed: Optional[int] = None) -> str:
        """Copies of the objects in ``palette`` (selections: props, model modules, meshes) at random spots of a circle,
        standing on the floor, turned and sized at random - for trees, bushes, rocks."""
        rng = np.random.default_rng(seed)
        pal = [s for s in palette if s is not None and s.kind in ("prop", "module", "mesh")]
        if not pal:
            raise ValueError("select the objects to scatter first (Ctrl+click to choose several)")
        c = np.asarray(centre, np.float64)
        placed: List[np.ndarray] = []
        made = []
        tries = 0
        with self._batch("scatter"):
            while len(made) < int(count) and tries < int(count) * 30:
                tries += 1
                a, r = rng.uniform(0, 2 * math.pi), radius * math.sqrt(rng.uniform(0, 1))
                x, z = c[0] + r * math.cos(a), c[2] + r * math.sin(a)
                if any(math.hypot(x - p[0], z - p[2]) < gap for p in placed):
                    continue
                y = self.floor_below(x, z, c[1] + 400.0)
                if y is None:
                    continue
                src = pal[int(rng.integers(len(pal)))]
                base = self.position_of(src)
                new = self.duplicate_selection(src, np.array([x, y, z]) - base)
                if new.kind != "mesh" and self.has_matrix(new):
                    if turn:
                        rot = self.rotation_of(new)
                        self.set_rotation(new, [rot[0], float(rng.uniform(-180, 180)), rot[2]])
                    lo_s, hi_s = float(min(scale)), float(max(scale))
                    if hi_s - lo_s > 1e-6 or abs(lo_s - 1) > 1e-6:
                        f = float(rng.uniform(lo_s, hi_s))
                        sc = self.scale_of(new)
                        try:
                            self.set_scale(new, sc * f)
                        except ValueError:
                            pass
                placed.append(np.array([x, y, z]))
                made.append(new)
            self._drop(made)
        self._changed_geometry()
        return f"{len(made)} objects scattered" + ("" if len(made) == int(count) else " (no more room / floor there)")

    # ================================================================================== 3. drop to the floor
    def _bottom(self, sel) -> Optional[tuple]:
        """(x, z, y of its lowest point) of an object."""
        if sel.kind in ("mesh", "prop"):
            b = self.engine_bounds(sel)
            if b is None:
                if sel.kind == "mesh":
                    lo, hi = cropmod.mesh_bounds(sel.ref)
                    b = (lo, hi)
                else:
                    p = self.position_of(sel)
                    return float(p[0]), float(p[2]), float(p[1])
            lo, hi = b
            return float((lo[0] + hi[0]) / 2), float((lo[2] + hi[2]) / 2), float(lo[1])
        p = self.position_of(sel)
        return float(p[0]), float(p[2]), float(p[1])

    def _drop(self, sels) -> int:
        n = 0
        if any(s.kind in ("mesh", "prop") for s in sels):
            self.bake()                                   # fresh bounds for copies made a moment ago
        for s in sels:
            if s.kind in ("light", "decal") or self.blocked_by_lock(s):
                continue
            b = self._bottom(s)
            if b is None:
                continue
            x, z, y0 = b
            fy = self.floor_below(x, z, y0 + 60.0)
            if fy is None:
                continue
            if abs(fy - y0) < 0.05:
                continue
            self.set_position(s, self.position_of(s) + np.array([0.0, fy - y0, 0.0]))
            n += 1
        return n

    def spawns_to_floor(self, recs=None, above: float = 20.0, reach: float = 250.0) -> str:
        """Start points (mp_CStartPoint; default every one, not the locked) put on the collision floor under them
        (``above`` units over it, like the game's own).  A point up to ``reach`` under a floor comes up onto it."""
        if recs is None:
            recs = [r for r in self.scene.modules if r.clean_name.lower() == "mp_cstartpoint" and r.parsed is not None]
        recs = [r for r in recs if not self.is_locked(r)]
        if not recs:
            raise ValueError("no start points to put on the floor")
        moved, none = 0, 0
        self.push_undo(False, "start points on the floor")
        for r in recs:
            x, y, z = (float(v) for v in r.parsed.position)
            fy = self.floor_below(x, z, y + reach)
            if fy is None:
                none += 1
                continue
            if abs(fy + above - y) > 0.5:
                r.parsed.position = (x, fy + above, z)
                moved += 1
        self.dirty_scene = self.needs_rebake = True
        return (f"{moved} of {len(recs)} start points put on the floor"
                + (f"; {none} have no floor (collision) under them" if none else ""))

    def drop_to_floor(self) -> str:
        """Put the selected objects (and the group) on the floor that is under them (the floor players walk on)."""
        sels = self._selected()
        if not sels:
            raise ValueError("select something first")
        with self._batch("drop to the floor"):
            n = self._drop(sels)
        self._changed_geometry()
        return f"{n} of {len(sels)} objects put on the floor" + ("" if n == len(sels) else " (the rest already were, or had no floor under them)")

    # ================================================================================== 4. align / distribute
    def align(self, axis: str, to: str = "first") -> str:
        """Give the selected objects the same X / Y / Z (``to``: 'first' selected, 'min', 'max', 'mid')."""
        sels = self._selected()
        if len(sels) < 2:
            raise ValueError("select at least two objects (Ctrl+click)")
        k = "xyz".index(axis.lower())
        vals = [float(self.position_of(s)[k]) for s in sels]
        target = {"first": vals[0], "min": min(vals), "max": max(vals), "mid": (min(vals) + max(vals)) / 2}[to]
        with self._batch("align"):
            for s, v in zip(sels, vals):
                if abs(v - target) > 1e-6:
                    d = np.zeros(3)
                    d[k] = target - v
                    self.set_position(s, self.position_of(s) + d)
        self._changed_geometry()
        return f"{len(sels)} objects with the same {axis.upper()}"

    def distribute(self) -> str:
        """Same distance between the selected objects, on the straight line between the two farthest apart (they stay)."""
        sels = self._selected()
        if len(sels) < 3:
            raise ValueError("select at least three objects (Ctrl+click)")
        pos = [self.position_of(s) for s in sels]
        i0, j0 = max(((i, j) for i in range(len(pos)) for j in range(i + 1, len(pos))),
                     key=lambda ij: float(np.linalg.norm(pos[ij[0]] - pos[ij[1]])))
        a, b = pos[i0], pos[j0]                           # the two ends stay where they are
        d = b - a
        L = float(np.linalg.norm(d))
        if L < 1e-6:
            raise ValueError("the objects are all in the same place")
        order = sorted(range(len(sels)), key=lambda i: float((pos[i] - a) @ d))
        with self._batch("distribute"):
            for k, i in enumerate(order):
                self.set_position(sels[i], a + d * (k / (len(order) - 1)))
        self._changed_geometry()
        return f"{len(sels)} objects every {L / (len(sels) - 1) / 100:.2f} m"

    # ================================================================================== 5. where players fall / get stuck
    def fall_report(self, cell: float = 100.0) -> dict:
        """Walk the map like a player from every start point: {'voids': [...], 'traps': [...], 'nodes': n}.
        void = an edge where the next step has NO floor under it (out of the map);
        trap = a place you can reach (falling) but not walk back from to any start point."""
        from .. import navgrid
        world = self.walk_world()
        if not world.floors:
            raise ValueError("this map has no floor collision (.hm): nothing to walk on")
        seeds = [p for lst in self.spawn_positions().values() for _, p in lst]
        if not seeds:
            raise ValueError("the scene has no start points")
        g = navgrid.build(world, seeds, cell=cell)
        starts = [n for n in (g.nearest(p) for p in seeds) if n is not None]
        if not starts:
            raise ValueError("the start points are not on a floor")
        reach, _ = g.distances(starts)
        back, _ = g.distances(starts, reverse=True)
        voids, traps = [], []
        moves = ((1, 0), (-1, 0), (0, 1), (0, -1))
        for n, (ix, iz, y) in enumerate(g.nodes):
            if not np.isfinite(reach[n]):
                continue
            if not np.isfinite(back[n]):
                traps.append(g.position(n))
            for dx, dz in moves:
                x, z = (ix + 0.5 + dx * 0.75) * cell, (iz + 0.5 + dz * 0.75) * cell
                if world.blocked(x, z, y, 20.0, 175.0, 45.0):
                    continue
                if world.floor_at(x, z, y + 45.0) is None:
                    voids.append(np.array([x, y, z]))
                    break
        return {"voids": _clusters(voids, 800.0), "traps": _clusters(traps, 800.0), "nodes": len(g.nodes), "cell": cell}

    def close_traps(self, cell: float = 30.0, height: float = 220.0, least: int = 3) -> str:
        """An invisible wall (collision boxes) on every edge where a player drops into a trap - a place he can fall
        into but never walk out of (de_inferno's drain: a pit CS players crawl out of through a pipe; a Torrente
        player cannot crouch and stayed there for good).  Traps of fewer than ``least`` cells (``cell`` cm) are left
        alone.  One undo step.  -> a summary."""
        return self.apply_trap_boxes(*self.trap_boxes(cell, height, least))

    def apply_trap_boxes(self, boxes, msg: str) -> str:
        """The boxes of ``trap_boxes`` into the map (one undo step)."""
        from .. import regioncopy
        if not boxes:
            return msg
        self.push_undo(True, "close the traps")
        regioncopy.add_boxes(self.opt, boxes)
        self.dirty_map = True
        self._walk_key = self._ff_key = None
        self._changed_geometry()
        return msg

    def trap_boxes(self, cell: float = 30.0, height: float = 220.0, least: int = 3):
        """The boxes ``close_traps`` puts (it reads the map only: it may run in the background).
        -> (boxes [(centre, half, axes)], summary)."""
        from .. import navgrid
        world = self.walk_world()
        if not world.floors:
            raise ValueError("this map has no floor collision (.hm): nothing to walk on")
        seeds = [p for lst in self.spawn_positions().values() for _, p in lst]
        if not seeds:
            raise ValueError("the scene has no start points")
        g = navgrid.build(world, seeds, cell=cell, max_nodes=2000000)
        starts = [n for n in (g.nearest(p) for p in seeds) if n is not None]
        if not starts:
            raise ValueError("the start points are not on a floor")
        reach, _ = g.distances(starts)
        back, _ = g.distances(starts, reverse=True)
        trap = np.isfinite(reach) & ~np.isfinite(back)
        if not trap.any():
            return [], "no traps: from every place a player can reach he can walk back"
        # trap areas (joined cells), the small ones left alone
        area = np.full(len(g.nodes), -1, np.int64)
        sizes = []
        for s in np.nonzero(trap)[0]:
            if area[s] >= 0:
                continue
            k = len(sizes)
            area[s] = k
            todo, cnt = [int(s)], 0
            while todo:
                n = todo.pop()
                cnt += 1
                for m, _c in g.edges[n] + g.back[n]:
                    if trap[m] and area[m] < 0:
                        area[m] = k
                        todo.append(m)
            sizes.append(cnt)
        up = np.array([0.0, 1.0, 0.0])
        boxes, closed = [], set()
        for n in np.nonzero(np.isfinite(reach) & np.isfinite(back))[0]:
            a = g.position(n)
            for m, _c in g.edges[n]:
                if not trap[m] or sizes[area[m]] < least:
                    continue
                b = g.position(m)
                d = np.array([b[0] - a[0], 0.0, b[2] - a[2]])
                ln = float(np.linalg.norm(d))
                if ln < 1e-6:
                    continue
                d /= ln
                u = np.cross(up, d)
                R = np.array([u, up, np.cross(u, up)])
                if np.linalg.det(R) < 0:
                    R[2] = -R[2]
                c = np.array([(a[0] + b[0]) / 2, a[1] - 10.0 + (height + 10.0) / 2, (a[2] + b[2]) / 2])
                boxes.append((c, np.array([cell * 0.75, (height + 10.0) / 2, 5.0]), R))
                closed.add(int(area[m]))
        if not boxes:
            return [], "the traps are too small to close"
        return boxes, (f"{len(closed)} traps closed with {len(boxes)} invisible collision boxes on their edges "
                       f"({sum(1 for s in sizes if s < least)} small ones left) - save the map")

    # ================================================================================== 6. start points
    def spawn_report(self, sight: bool = True) -> list:
        """Problems of the start points: inside a wall / box, in the air, under the floor, and (``sight``) start points
        that see a start point of the other team.  [{name, team, pos, problem}]"""
        world = self.walk_world()
        out = []
        sp = self.spawn_positions()
        for team, lst in sp.items():
            for name, p in lst:
                x, y, z = (float(v) for v in p)
                fy = world.floor_at(x, z, y + 60.0)
                if fy is None:
                    out.append({"name": name, "team": team, "pos": p, "problem": "no floor under it (falls out of the map)"})
                elif y - fy > 60.0:
                    out.append({"name": name, "team": team, "pos": p, "problem": f"in the air ({(y - fy) / 100:.1f} m above the floor)"})
                feet = fy if fy is not None else y
                if world.blocked(x, z, feet, 25.0, 175.0, 45.0):
                    out.append({"name": name, "team": team, "pos": p, "problem": "inside a wall or a collision box"})
        if sight and len(sp) > 1:
            tris = self._sight_tris()
            teams = sorted(sp)
            for i, ta in enumerate(teams):
                for tb in teams[i + 1:]:
                    for na, pa in sp[ta]:
                        for nb, pb in sp[tb]:
                            a = np.asarray(pa, np.float64) + [0, 160.0, 0]
                            b = np.asarray(pb, np.float64) + [0, 160.0, 0]
                            if not _segment_hits(a, b, tris):
                                out.append({"name": f"{na} / {nb}", "team": -1, "pos": pa,
                                            "problem": f"sees the other team's start point {nb} ({np.linalg.norm(b - a) / 100:.0f} m)"})
        return out

    def _sight_tris(self) -> np.ndarray:
        """What stops the view: the map's triangles (see-through ones too: leaves and fences hide a player well enough)
        and the collision boxes."""
        tris, _alpha, _o = self._map_tris()
        out = [tris]
        for c, h, R in _boxes(self.opt):
            q = np.array([[x, y, z] for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)], np.float64) * h @ R + c
            faces = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
            out.append(np.array([[q[a], q[b], q[c_]] for a, b, c_, d in faces] + [[q[a], q[c_], q[d]] for a, b, c_, d in faces]))
        return np.concatenate(out) if out else np.zeros((0, 3, 3))

    # ================================================================================== 7. load map (performance)
    def load_report(self, cell: float = 1500.0) -> dict:
        """Triangles of the map per square of ``cell`` x ``cell`` units (seen from above): {'cells': [{x, z, tris,
        transparent}], 'total', 'transparent', 'cell'}, heaviest first.  See-through triangles (leaves, fences, glass)
        cost the most: they are sorted and drawn one by one, without the depth trick of the solid ones."""
        tris, alpha, _o = self._map_tris()
        if not len(tris):
            return {"cells": [], "total": 0, "transparent": 0, "cell": cell}
        c = tris.mean(1)
        ij = np.floor(c[:, [0, 2]] / cell).astype(np.int64)
        keys, inv = np.unique(ij, axis=0, return_inverse=True)
        inv = inv.reshape(-1)
        n_all = np.bincount(inv, minlength=len(keys))
        n_t = np.bincount(inv, weights=alpha.astype(np.float64), minlength=len(keys)).astype(int)
        ys = np.zeros(len(keys))
        np.maximum.at(ys, inv, c[:, 1])
        cells = [{"x": float((k[0] + 0.5) * cell), "z": float((k[1] + 0.5) * cell), "y": float(ys[i]), "tris": int(n_all[i]),
                  "transparent": int(n_t[i])} for i, k in enumerate(keys)]
        cells.sort(key=lambda d: -(d["tris"] + 3 * d["transparent"]))
        return {"cells": cells, "total": int(len(tris)), "transparent": int(alpha.sum()), "cell": cell}

    def load_overlay(self, report: dict) -> list:
        """[(segments (n, 2, 3) display space, rgba)] squares coloured green -> red by load."""
        cells = report.get("cells") or []
        if not cells:
            return []
        cost = np.array([d["tris"] + 3 * d["transparent"] for d in cells], np.float64)
        top = max(float(np.percentile(cost, 95)), 1.0)
        half = report["cell"] / 2 * 0.96
        out = []
        for d, w in zip(cells, cost):
            t = float(min(w / top, 1.0))
            col = (min(1.0, 2 * t), min(1.0, 2 * (1 - t)), 0.1, 1.0)
            y = d["y"] + 30
            q = [np.array([d["x"] + sx * half, y, d["z"] + sz * half]) * F for sx, sz in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
            segs = [(q[k], q[(k + 1) % 4]) for k in range(4)]
            if t > 0.66:                                          # the heavy ones get a cross too
                segs += [(q[0], q[2]), (q[1], q[3])]
            out.append((np.asarray(segs), col))
        return out

    # ================================================================================== 8. collision clean-up
    def collision_cleanup_report(self, pad: float = 25.0) -> dict:
        """Collision boxes that do nothing: {'duplicate': [i], 'inside': [i], 'alone': [i]} (indices).
        duplicate = same place, size and turn as an earlier box; inside = completely inside another box;
        alone = no triangle of the map and no floor / wall of the .hm near it (an invisible wall: check before removing)."""
        boxes = _boxes(self.opt)
        dup, inside, alone = [], [], []
        seen = {}
        corners = []
        for i, (c, h, R) in enumerate(boxes):
            key = tuple(np.round(np.concatenate([c, np.sort(h), np.abs(R).reshape(-1)]), 0))
            if key in seen:
                dup.append(i)
            else:
                seen[key] = i
            corners.append(np.array([[x, y, z] for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)], np.float64) * h @ R + c)
        dset = set(dup)
        inv = [np.linalg.inv(R) for _c, _h, R in boxes]
        vol = [float(np.prod(h)) for _c, h, _R in boxes]
        alo = np.array([c.min(0) for c in corners]) if corners else np.zeros((0, 3))
        ahi = np.array([c.max(0) for c in corners]) if corners else np.zeros((0, 3))
        for i in range(len(boxes)):
            if i in dset:
                continue
            cand = np.nonzero(np.all(alo <= alo[i] + 0.5, axis=1) & np.all(ahi >= ahi[i] - 0.5, axis=1))[0]
            for j in cand:
                j = int(j)
                if j == i or j in dset or vol[j] < vol[i] - 1e-6 or (abs(vol[j] - vol[i]) < 1e-6 and j > i):
                    continue
                c2, h2, _R2 = boxes[j]
                if np.all(np.abs((corners[i] - c2) @ inv[j]) <= h2 + 0.5):
                    inside.append(i)
                    break
        tris, _a, _o = self._map_tris()
        pts = np.concatenate([tris.mean(1), tris.reshape(-1, 3)]) if len(tris) else np.zeros((0, 3))
        try:
            hm = self.heightmap_edit()
        except ValueError:
            hm = None
        from .. import meshbox
        faces = meshbox.map_faces(hm, walls_only=False) if hm is not None else []
        used = dset | set(inside)
        for i, (c, h, R) in enumerate(boxes):
            if i in used:
                continue
            r = np.abs(R).T @ h + pad
            near = pts[np.all(np.abs(pts - c) <= r, axis=1)] if len(pts) else pts
            hit = len(near) and bool(np.any(np.all(np.abs((near - c) @ np.linalg.inv(R)) <= h + pad, axis=1)))
            if not hit:
                lo, hi = c - r, c + r
                hit = any(np.all(fhi >= lo) and np.all(flo <= hi) for _n, _d, flo, fhi in faces)
            if not hit:
                alone.append(i)
        return {"duplicate": dup, "inside": inside, "alone": alone, "boxes": len(boxes)}

    def remove_boxes(self, indices) -> str:
        idx = sorted({int(i) for i in indices})
        if not idx:
            return "nothing to remove"
        self.push_undo(True, "clean collision")
        cropmod.remove_collision_indices(self.opt, idx)
        self.dirty_map = True
        self._walk_key = None
        return f"{len(idx)} collision boxes removed - save the map"

    # ================================================================================== 9. textures
    def texture_usage(self) -> list:
        """[{texture, materials, tris, objects}] of the map, most used first (triangles that are drawn)."""
        from .. import autohm
        use: Dict[str, dict] = {}
        for kind, i in self._visible_kinds():
            try:
                me, _M = autohm._mesh_matrix(self.opt, kind, i)
            except Exception:
                continue
            seen = set()
            for sm in me.render_submeshes():
                if sm.material_index >= len(me.materials) or sm.indices is None:
                    continue
                mat = me.materials[sm.material_index]
                t = str((mat.textures[0] if mat.textures else "") or mat.diffuse).rstrip("\0")
                if not t:
                    continue
                d = use.setdefault(t.lower(), {"texture": t, "tris": 0, "objects": 0})
                d["tris"] += len(sm.indices) // 3
                if t.lower() not in seen:
                    seen.add(t.lower())
                    d["objects"] += 1
        return sorted(use.values(), key=lambda d: (-d["tris"], d["texture"].lower()))

    def replace_texture(self, old: str, new: str, only_selection: bool = False) -> str:
        """Every material that uses ``old`` (any case, with or without .tex) uses ``new`` instead - in the whole map, or
        only in the selected meshes / props."""
        def norm(t):
            t = str(t).rstrip("\0").replace("\\", "/").split("/")[-1].lower()
            return t if t.endswith(".tex") else t + ".tex"
        o, n = norm(old), str(new).strip()
        if not n:
            raise ValueError("write the new texture")
        if not n.lower().endswith(".tex"):
            n += ".tex"
        if self.fs.texture(n) is None:
            raise ValueError(f"texture {n} not found")
        if only_selection:
            meshes = []
            for s in self._selected():
                if s.kind == "mesh":
                    meshes.append(s.ref)
                elif s.kind == "prop":
                    meshes.append(self.opt.meshes[s.ref.mesh_index])
            if not meshes:
                raise ValueError("select meshes / props first")
        else:
            meshes = list(self.opt.meshes)
        self.push_undo(True, "replace texture")
        k = 0
        for me in meshes:
            for mat in me.materials:
                if mat.textures and norm(mat.textures[0]) == o:
                    mat.textures = [n] + list(mat.textures[1:])
                    k += 1
                elif not mat.textures and norm(mat.diffuse) == o:
                    mat.diffuse = n
                    k += 1
        if not k:
            return f"no material uses {o}"
        self.dirty_map = self.needs_rebake = True
        return f"{k} materials: {o} -> {n} - save the map"

    def unused_textures(self) -> list:
        """Textures named by materials of the map that no drawn triangle uses (the export leaves them out)."""
        named = set()
        for me in self.opt.meshes:
            for mat in me.materials:
                for t in list(mat.textures) + [mat.diffuse]:
                    t = str(t).rstrip("\0")
                    if t:
                        named.add(t.lower())
        used = set()
        for me in self.opt.meshes:
            for lod in me.lods:
                for part in lod.parts:
                    for sm in part.submeshes:
                        if sm.material_index < len(me.materials):
                            mat = me.materials[sm.material_index]
                            for t in list(mat.textures) + [mat.diffuse]:
                                if str(t).rstrip("\0"):
                                    used.add(str(t).rstrip("\0").lower())
        return sorted(named - used)

    # ================================================================================== 10. sectors
    def rebuild_sectors(self) -> str:
        """List every mesh, prop and collision box in all the sectors (parts of the map) it overlaps now.  After moving
        things far, the game may skip drawing them from some places: this fixes that.  Only adds (nothing is taken out)."""
        if self.opt is None or self.opt.old_format:
            raise ValueError("this map has no sectors (old format)")
        blk = cropmod.read_block(self.opt)
        if not blk.sectors:
            return "this map has no sectors"
        listed = {i for s in blk.sectors for i in s.objs}
        nm = len(self.opt.meshes)
        used = {p.mesh_index for p in self.opt.props}
        added = 0
        self.push_undo(True, "rebuild sectors")
        for i, me in enumerate(self.opt.meshes):
            if i in used or i not in listed:
                continue
            lo, hi = cropmod.mesh_bounds(me)
            added += _list_in(blk, i, lo, hi, "objs")
        for j, pr in enumerate(self.opt.props):
            oi = nm + j
            if oi not in listed:
                continue
            me = self.opt.meshes[pr.mesh_index]
            lo, hi = cropmod.mesh_bounds(me)
            M = np.linalg.inv(np.asarray(me.world_transform, np.float64)) @ np.asarray(pr.transform, np.float64)
            q = np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])]) @ M[:3, :3] + M[3, :3]
            added += _list_in(blk, oi, q.min(0), q.max(0), "objs")
        from .. import regioncopy
        for b in range(len(blk.boxes)):
            lo, hi = regioncopy._box_bounds(blk.boxes[b])
            added += _list_in(blk, b, lo, hi, "boxes")
        cropmod.write_block(self.opt, blk)
        self.dirty_map = True
        return f"sectors rebuilt: {added} missing entries added - save the map"

    # ================================================================================== 11. .key animations
    def key_names(self) -> list:
        """The .key files the scene's modules name (as written in the module), once each."""
        import re
        out, seen = [], set()
        for r in self.scene.modules:
            raw = bytes(r.payload()) if hasattr(r, "payload") else b""
            for m in re.findall(rb"[A-Za-z0-9_\\/.\-]+\.key", raw, flags=re.I):
                k = m.decode("cp1252", "replace")
                if k.lower() not in seen:
                    seen.add(k.lower())
                    out.append(k)
        return out

    def _key_path(self, name: str) -> str:
        n = str(name).rstrip("\0").replace("\\", "/")
        return self.fs.find("keys/" + n) or self.fs.find(n) or ""

    def key_info(self, name: str) -> dict:
        from ..keys import KeyFile
        p = self._key_path(name)
        if not p:
            raise ValueError(f"{name} not found in keys/")
        k = KeyFile.load(p)
        return {"path": p, "frames": k.frames, "nodes": len(k.node_names), "events": sum(len(e) for e in k.events),
                "node_names": list(k.node_names)}

    def retime_key(self, name: str, speed: float, new_name: str = "", use_in_module=None) -> str:
        """A copy of animation ``name`` played ``speed`` times as fast (2 = twice as fast, 0.5 = half), saved as
        ``new_name`` next to it (never over an existing file).  ``use_in_module``: a module whose fields name the old
        animation are changed to the new one."""
        from ..keys import KeyFile
        speed = float(speed)
        if not (0.05 <= speed <= 20):
            raise ValueError("speed between 0.05 and 20")
        src = self._key_path(name)
        if not src:
            raise ValueError(f"{name} not found in keys/")
        k = KeyFile.load(src)
        if k.frames < 2:
            raise ValueError("that animation has a single frame: nothing to speed up")
        base = os.path.splitext(os.path.basename(src))[0]
        stem = os.path.splitext(os.path.basename(new_name.strip()))[0] if new_name.strip() else \
            f"{base}_x{speed:g}".replace(".", "_")
        dst = os.path.join(os.path.dirname(src), stem + ".key")
        if os.path.exists(dst):
            raise ValueError(f"{stem}.key already exists - pick another name (it is never replaced)")
        old_frames = k.frames
        n_new = max(2, int(round((k.frames - 1) / speed)) + 1)
        t = np.linspace(0, k.frames - 1, n_new)
        f0 = np.floor(t).astype(int)
        f1 = np.minimum(f0 + 1, k.frames - 1)
        a = (t - f0)[:, None]
        P = np.zeros((n_new, len(k.node_names)), k.poses.dtype)
        for fld in ("pos", "scale"):
            P[fld] = k.poses[fld][f0] * (1 - a[..., None]) + k.poses[fld][f1] * a[..., None]
        q0 = k.poses["rot"][f0].astype(np.float64)
        q1 = k.poses["rot"][f1].astype(np.float64)
        sgn = np.where((q0 * q1).sum(-1, keepdims=True) < 0, -1.0, 1.0)
        q = q0 * (1 - a[..., None]) + q1 * sgn * a[..., None]
        q /= np.maximum(np.linalg.norm(q, axis=-1, keepdims=True), 1e-9)
        P["rot"] = q
        ev = [[] for _ in range(n_new)]
        for f, lst in enumerate(k.events):
            if lst:
                ev[min(n_new - 1, int(round(f * (n_new - 1) / (k.frames - 1))))].extend(lst)
        size = k.key1_sizes[0] if k.key1_sizes else 8
        k.poses, k.events, k.key1_sizes = P, ev, [size] * n_new
        with open(dst, "wb") as fh:
            fh.write(k.to_bytes())
        KeyFile.load(dst)                                 # reads back: the file is valid
        self.fs.rescan()
        msg = f"{stem}.key: {n_new} frames (was {old_frames})"
        rel_old = str(name).rstrip("\0")
        new_ref = rel_old[: len(rel_old) - len(os.path.basename(rel_old.replace("\\", "/")))] + stem + ".key"
        if use_in_module is not None and use_in_module.parsed is not None:
            obj = use_in_module.parsed
            n = 0
            for fld, v in list(vars(obj).items()):
                if isinstance(v, (str, bytes)):
                    s = v.decode("cp1252", "replace") if isinstance(v, bytes) else v
                    if s.rstrip("\0").lower() == rel_old.lower():
                        nv = new_ref + ("\0" if s.endswith("\0") else "")
                        setattr(obj, fld, type(v)(nv.encode("cp1252")) if isinstance(v, bytes) else type(v)(nv))
                        n += 1
            if not n:
                n = self.point_module_to_key(use_in_module, rel_old, stem + ".key")
            if n:
                self.dirty_scene = True
                msg += f"; the module now uses {new_ref} - save the scene"
        return msg + f" - saved as keys/{new_ref.replace(chr(92), '/')}"


# ------------------------------------------------------------------------------------------------ helpers
def _boxes(opt) -> list:
    from .. import meshbox
    return meshbox.map_boxes(opt)


def _clusters(points, radius: float) -> list:
    """Group points closer than ``radius``: [{'pos', 'count'}], biggest group first."""
    groups: List[list] = []
    for p in points:
        for g in groups:
            if np.linalg.norm(g[0] - p) < radius:
                g[1] += 1
                break
        else:
            groups.append([np.asarray(p, np.float64), 1])
    return [{"pos": g[0], "count": g[1]} for g in sorted(groups, key=lambda g: -g[1])]


def _segment_hits(a, b, tris) -> bool:
    """Does the segment a-b cross any triangle?"""
    if not len(tris):
        return False
    lo, hi = np.minimum(a, b) - 1, np.maximum(a, b) + 1
    tmin, tmax = tris.min(1), tris.max(1)
    m = np.all(tmax >= lo, axis=1) & np.all(tmin <= hi, axis=1)
    T = tris[m]
    if not len(T):
        return False
    d = b - a
    e1, e2 = T[:, 1] - T[:, 0], T[:, 2] - T[:, 0]
    p = np.cross(d, e2)
    det = (e1 * p).sum(1)
    ok = np.abs(det) > 1e-9
    inv = np.where(ok, 1.0 / np.where(ok, det, 1.0), 0.0)
    s = a - T[:, 0]
    u = (s * p).sum(1) * inv
    q = np.cross(s, e1)
    v = (q * d).sum(1) * inv
    t = (q * e2).sum(1) * inv
    hit = ok & (u >= 0) & (v >= 0) & (u + v <= 1) & (t > 0.01) & (t < 0.99)
    return bool(hit.any())


def _list_in(blk, idx: int, lo, hi, which: str) -> int:
    added = 0
    for s in cropmod._overlapping(blk, lo, hi, 0.0):
        lst = getattr(s, which)
        if idx not in lst:
            lst.append(idx)
            added += 1
    return added
