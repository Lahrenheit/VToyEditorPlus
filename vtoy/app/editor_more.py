"""Panels of the extra map tools (state_more.py): path, object brush, drop / align, fall finder, start points, load map,
collision clean-up, textures, sectors, animations."""
from __future__ import annotations

import os
import threading

import numpy as np
from imgui_bundle import imgui

from . import ui
from ..language import tr

F = np.array([1.0, 1.0, -1.0])


def _V4(r, g, b, a):
    return imgui.ImVec4(r, g, b, a)


def _V2(x, y):
    return imgui.ImVec2(x, y)


class MorePanels:
    def more_init(self) -> None:
        self.path_pts = []
        self.path_pick = False
        self.path = dict(shape=4, width=12.0, height=110.0, tex="tablones.tex", tile=128.0, closed=False, every=500.0,
                         turn=True, floor=True)
        self.brush_on = False
        self.brush = dict(radius=600.0, count=8, gap=150.0, smin=0.85, smax=1.2, turn=True)
        self.brush_palette = []
        self.brush_at = None
        self.fall_res = None
        self.spawn_res = None
        self.load_res = None
        self.load_show = True
        self.clean_res = None
        self.tex_old, self.tex_new, self.tex_sel = "", "", False
        self.key_sel, self.key_speed, self.key_new, self.key_use = "", 1.5, "", True
        self._job = None
        self.sim_res = None
        self.sim_show = True
        self.shp = dict(kind=0, size=[200.0, 200.0, 200.0], yaw=0.0, sides=16, steps=8, tex="tablones.tex", tile=128.0,
                        col=True, height=200.0, preview=True)
        self.shape_at = None
        self._shape_key = None
        self._shape_edges = None
        self.gap_res = None
        self.buried_res = None
        self.anim_show = False
        self.anim_scale, self.anim_off, self.anim_new = 1.5, [0.0, 0.0, 0.0], ""
        self.change_res = None
        self.layout = dict(mode=0, per=8, radius=350.0, health=4)
        self.layout_a = None
        self.layout_b = None
        self.weather_lights = True
        self.pal_open, self.pal_text, self.pal_sel = False, "", 0
        self.sc_cmd, self.sc_key = 0, "Ctrl+1"
        self.bsp = dict(path="", yaw=90.0, scale=2.54, at=None, col=True, spawns=True, dmt=True, clear=True, rows=None,
                        err="", foot=None, fkey=None, wads="", mode=1, per=0, texmode=0, rep=None)
        self.csnew = dict(path="", wads="", rep=None, rows=None, err="", mode=1, name="", per=16.0, water=0)
        try:
            from .. import settings as _settings
            self.bsp["wads"] = self.csnew["wads"] = str(_settings.get("cs_wads", "") or "")
        except Exception:
            pass

    def more_sections(self):
        return (self.sec_path, self.sec_brush, self.sec_arrange, self.sec_layout, self.sec_falls, self.sec_spawns,
                self.sec_sim, self.sec_gaps, self.sec_load, self.sec_clean, self.sec_textures, self.sec_sectors,
                self.sec_weather, self.sec_keys, self.sec_changes, self.sec_shortcuts)

    # ------------------------------------------------------------------------------ background jobs (slow searches)
    def _bg(self, name: str, fn, done) -> None:
        if self._job is not None:
            self.log("wait: another search is running")
            return
        box = {}

        def run():
            try:
                box["r"] = fn()
            except Exception as e:
                box["e"] = e
        th = threading.Thread(target=run, daemon=True)
        self._job = (name, th, box, done)
        th.start()

    def _job_poll(self) -> None:
        if self._job is None:
            return
        name, th, box, done = self._job
        if th.is_alive():
            imgui.text_colored(_V4(1, 0.8, 0.2, 1), tr("working: {0} ...").replace("{0}", tr(name)))
            return
        self._job = None
        if "e" in box:
            self.log(f"{name}: {box['e']}")
        else:
            done(box["r"])

    # ------------------------------------------------------------------------------ view clicks
    def more_press(self, o, d) -> bool:
        st = self.state
        if self.path_pick:
            import glfw
            o_, d_ = np.asarray(o, np.float64), np.asarray(d, np.float64)
            d_ = d_ / max(np.linalg.norm(d_), 1e-12)
            k = self.path_point_at(o_, d_)
            alt = self.key(glfw.KEY_LEFT_ALT) or self.key(glfw.KEY_RIGHT_ALT)
            if k is not None and alt:                          # Alt+click a point: take it away
                self.path_pts.pop(k)
                return True
            if k is not None:                                  # click a point: grab it (drag to move it)
                self.drag = dict(tool="path", idx=k)
                return True
            seg = self.path_segment_at(o_, d_)
            if seg is not None:                                # click a line between two points: a new point there
                i, q = seg
                self.path_pts.insert(i + 1, q)
                self.drag = dict(tool="path", idx=i + 1)
                return True
            p = st.pick_point(o, d)
            if p is not None:
                self.path_pts.append(np.asarray(p, np.float64))
                self.drag = dict(tool="path", idx=len(self.path_pts) - 1)
            return True
        if self.brush_on:
            p = st.pick_point(o, d)
            if p is not None:
                b = self.brush
                self.brush_at = np.asarray(p, np.float64)
                self._try(st.scatter, self.brush_palette, p, b["radius"], int(b["count"]), b["turn"], (b["smin"], b["smax"]),
                          b["gap"])
                self._col_key = None
            return True
        return False

    # ------------------------------------------------------------------------------ path points: grab / move / insert
    def path_point_at(self, o, d):
        """Number of the path point under the mouse (None: none)."""
        from .tools import point_under_ray
        return point_under_ray(o, d, self.path_pts)

    def path_segment_at(self, o, d):
        """(index of the first point, engine point) of the path line under the mouse."""
        from .tools import segment_under_ray
        return segment_under_ray(o, d, self.path_pts, bool(self.path.get("closed")))

    def path_drag(self, o, d) -> None:
        """Move the grabbed point: it slides at its own height; with Ctrl it sticks to what is under the mouse."""
        import glfw
        from . import tools
        k = self.drag.get("idx", -1)
        if not (0 <= k < len(self.path_pts)):
            return
        p = self.path_pts[k]
        if self.key(glfw.KEY_LEFT_CONTROL) or self.key(glfw.KEY_RIGHT_CONTROL):
            q = self.state.pick_point(o, d)
            if q is not None:
                self.path_pts[k] = np.asarray(q, np.float64)
            return
        hit = tools.ray_plane_y(o, d, float(p[1]))
        if hit is not None:
            e = tools.display_to_engine(hit)
            self.path_pts[k] = np.array([float(e[0]), float(p[1]), float(e[2])])

    def more_draw3d(self) -> None:
        gl = self.gl
        if self.path_pts:
            pts = [p * F for p in self.path_pts]
            gl.draw_boxes([(p, np.full(3, 18.0)) for p in pts], (0.3, 0.9, 1.0, 1), False)
            k = self.drag.get("idx") if isinstance(getattr(self, "drag", None), dict) and self.drag.get("tool") == "path" else None
            if k is not None and 0 <= k < len(pts):
                gl.draw_boxes([(pts[k], np.full(3, 30.0))], (1.0, 1.0, 0.2, 1), False)
            seg = list(zip(pts[:-1], pts[1:]))
            if self.path.get("closed") and len(pts) > 2:
                seg.append((pts[-1], pts[0]))
            if seg:
                gl.draw_lines(seg, (0.3, 0.9, 1.0, 1), False)
        if self.brush_on and self.brush_at is not None:
            from .. import particles
            c = np.asarray(particles.sphere_circles(self.brush_at * F, self.brush["radius"], 32), np.float64).reshape(-1, 2, 3)
            gl.draw_lines(c[: len(c) // 3], (0.4, 1.0, 0.4, 1), False)
        for res, col in ((self.fall_res and self.fall_res.get("voids"), (1.0, 0.2, 0.2, 1)),
                         (self.fall_res and self.fall_res.get("traps"), (1.0, 0.6, 0.1, 1))):
            if res:
                gl.draw_boxes([(d["pos"] * F + [0, 60, 0], np.full(3, 60.0 + min(d["count"], 40) * 3)) for d in res[:60]], col, False)
        if self.spawn_res:
            gl.draw_boxes([(np.asarray(d["pos"], np.float64) * F + [0, 90, 0], np.array([60.0, 180.0, 60.0])) for d in self.spawn_res],
                          (1.0, 0.3, 0.8, 1), False)
        if self.load_res and self.load_show:
            try:
                for segs, col in self.state.load_overlay(self.load_res):
                    gl.draw_lines(segs, col, False)
            except Exception:
                pass
        if self.shp.get("preview") and self._shape_edges is not None and len(self._shape_edges):
            q = self._shape_edges * F
            gl.draw_lines(list(map(tuple, q)), (1.0, 0.85, 0.2, 1), False)
        if self.sim_res and self.sim_show:
            cols = [(0.95, 0.85, 0.2, 1), (1.0, 0.3, 0.3, 1), (0.3, 0.6, 1.0, 1), (0.6, 1.0, 0.4, 1)]
            for r in self.sim_res["routes"]:
                p = r["points"] * F + [0, 40, 0]
                gl.draw_lines(list(zip(p[:-1], p[1:])), cols[int(r["team"]) % len(cols)], False)
            if self.sim_res["meets"]:
                gl.draw_boxes([(m["pos"] * F + [0, 80, 0], np.full(3, 90.0)) for m in self.sim_res["meets"]], (1, 1, 1, 1), False)
        if self.gap_res:
            gl.draw_boxes([(d["pos"] * F + [0, 30, 0], np.full(3, 50.0)) for d in self.gap_res[:80]], (1.0, 0.2, 0.9, 1), False)
        if self.buried_res:
            gl.draw_boxes([(d["pos"] * F, np.maximum(d["size"], 30.0)) for d in self.buried_res[:80]], (0.6, 0.4, 1.0, 1), False)
        if self.change_res:
            col = {"+": (0.3, 1.0, 0.3, 1), "-": (1.0, 0.25, 0.25, 1), "~": (1.0, 0.9, 0.2, 1)}
            for sign in "+-~":
                bx = [(np.asarray(p, np.float64) * F, np.full(3, 80.0)) for _k, sg, p in self.change_res if sg == sign]
                if bx:
                    gl.draw_boxes(bx, col[sign], False)
        if self.anim_show:
            try:
                for _r, pts, _k in self.state.animation_paths():
                    q = pts * F
                    gl.draw_lines(list(zip(q[:-1], q[1:])), (0.4, 1.0, 1.0, 1), False)
            except Exception:
                pass
        for q, col in ((self.layout_a, (1.0, 0.85, 0.1, 1)), (self.layout_b, (1.0, 0.3, 0.3, 1))):
            if q is not None:
                gl.draw_boxes([(np.asarray(q, np.float64) * F + [0, 100, 0], np.array([80.0, 200.0, 80.0]))], col, False)
        if self.clean_res and self.clean_res.get("_show"):
            boxes = self.clean_res.get("_boxes", [])
            if boxes:
                gl.draw_boxes(boxes, (1.0, 0.1, 0.1, 1), False)

    # ------------------------------------------------------------------------------ 1. path of several points
    def sec_path(self) -> None:
        from .. import solids
        st = self.state
        if not self._header("Path of several points (railings, rows of objects)", False):
            return
        p = self.path
        ch, v = ui.checkbox("Click points in the view (A, B, C ...)", self.path_pick)
        if ch:
            self.path_pick = v
            if v:
                self.brush_on = False
        imgui.text_disabled("Click: a new point (or grab a point and drag it, like the Pen). Click a line: a point in the middle. "
                            "Alt+click a point: remove it. Ctrl while dragging: stick it to what is under the mouse. "
                            "Turn it off to select again.")
        if imgui.button("Add point here (where the view looks)"):
            self.path_pts.append(np.asarray(self.here_point(False), np.float64))
        imgui.same_line()
        if imgui.button("Remove last") and self.path_pts:
            self.path_pts.pop()
        imgui.same_line()
        if imgui.button("Clear##path"):
            self.path_pts = []
        imgui.text(tr("{0} points, {1} m").replace("{0}", str(len(self.path_pts)))
                   .replace("{1}", f"{st.path_length(self.path_pts) / 100:.1f}" if len(self.path_pts) > 1 else "0"))
        for k, q in enumerate(self.path_pts[:12]):
            ch, nv = ui.drag_float3(f"{chr(65 + k) if k < 26 else k}##pp{k}", q, 1.0)
            if ch:
                self.path_pts[k] = np.asarray(nv, np.float64)
        _, p["closed"] = ui.checkbox("Closed (last point back to the first)", p["closed"])
        imgui.separator()
        imgui.text("A solid along it (each stretch with its collision)")
        labels = ["Plank (walk on it)", "Block (crate, pillar)", "Wall", "Ramp", "Handrail", "Ship railing (bars + wooden rail)"]
        ch, i = ui.combo("shape##path", p["shape"], labels)
        if ch and i != p["shape"]:
            p["shape"] = i
            dl = solids.DEFAULTS[solids.SHAPES[i]]
            p["width"], p["height"] = float(dl[1]), float(dl[2])
        _, p["width"] = ui.drag_float("width##path", p["width"], 1.0, 1.0, 5000.0)
        _, p["height"] = ui.drag_float("height##path", p["height"], 1.0, 1.0, 5000.0)
        _, p["tex"] = ui.input_text("texture##path", p["tex"])
        _, p["only_col"] = ui.checkbox("Only collision (invisible, no texture)", bool(p.get("only_col", False)))
        if not p["only_col"] and not p["tex"].strip():
            imgui.text_colored(_V4(1.0, 0.7, 0.3, 1), tr("no texture: tick 'Only collision' to make it invisible"))
        if imgui.button("Create along the path") and len(self.path_pts) >= 2:
            if p["only_col"] or not p["tex"].strip():
                self._try(st.add_collision_path, self.path_pts, p["width"], p["height"], p["closed"])
            else:
                self._try(st.add_solid_path, solids.SHAPES[p["shape"]], self.path_pts, p["width"], p["height"], p["tex"].strip(),
                          p["tile"], p["closed"])
            self._col_key = None
        imgui.text_disabled("Only collision: invisible walls along the points (over a railing that has none, for example). "
                            "See them with 'Show collision boxes'.")
        imgui.separator()
        imgui.text("Copies of the selected object along it")
        _, p["every"] = ui.drag_float("every (units, 100 = 1 m)##path", p["every"], 10.0, 10.0, 100000.0)
        _, p["turn"] = ui.checkbox("turned like the path", p["turn"])
        imgui.same_line()
        _, p["floor"] = ui.checkbox("on the floor##path", p["floor"])
        if imgui.button("Place copies along the path") and len(self.path_pts) >= 2:
            self._try(st.place_along_path, self.path_pts, p["every"], p["turn"], p["floor"])

    # ------------------------------------------------------------------------------ 2. object brush
    def sec_brush(self) -> None:
        st = self.state
        if not self._header("Object brush (trees, bushes, rocks)", False):
            return
        if imgui.button("Use the selected objects as the brush"):
            self.brush_palette = [s for s in st._selected() if s.kind in ("prop", "module", "mesh")]
            self.log(tr("brush: {0} objects").replace("{0}", str(len(self.brush_palette))))
        imgui.text_disabled("Select one object, or several with Ctrl+click: each spot gets one of them at random.")
        imgui.text(tr("brush: {0} objects").replace("{0}", str(len(self.brush_palette))))
        b = self.brush
        _, b["radius"] = ui.drag_float("radius##br", b["radius"], 10.0, 50.0, 20000.0)
        _, b["count"] = ui.drag_float("objects per click##br", float(b["count"]), 1.0, 1.0, 200.0)
        _, b["gap"] = ui.drag_float("at least this far apart##br", b["gap"], 5.0, 0.0, 5000.0)
        _, b["smin"] = ui.drag_float("smallest size##br", b["smin"], 0.01, 0.1, 5.0)
        _, b["smax"] = ui.drag_float("biggest size##br", b["smax"], 0.01, 0.1, 5.0)
        _, b["turn"] = ui.checkbox("turned at random##br", b["turn"])
        ch, v = ui.checkbox("Paint: each click in the view scatters them", self.brush_on)
        if ch:
            self.brush_on = v and bool(self.brush_palette)
            if v and not self.brush_palette:
                self.log("choose the brush objects first")
            if self.brush_on:
                self.path_pick = False
        if imgui.button("Scatter here (where the view looks)") and self.brush_palette:
            at = self.here_point(False)
            self.brush_at = np.asarray(at, np.float64)
            self._try(st.scatter, self.brush_palette, at, b["radius"], int(b["count"]), b["turn"], (b["smin"], b["smax"]), b["gap"])
        imgui.text_disabled("They stand on the floor (.hm). Ctrl+Z undoes one click.")

    # ------------------------------------------------------------------------------ 3 + 4. drop, align, distribute
    def sec_arrange(self) -> None:
        st = self.state
        if not self._header("Drop to the floor / align / distribute", False):
            return
        if imgui.button("Drop the selection to the floor"):
            self._try(st.drop_to_floor)
        imgui.text_disabled("Selection + group (Ctrl+click). The floor is the one players walk on (.hm).")
        imgui.text("Align (same value as the first selected):")
        for ax in ("x", "y", "z"):
            imgui.same_line()
            if imgui.small_button(f"{ax.upper()}##al"):
                self._try(st.align, ax, "first")
        imgui.text("Align to the lowest / highest:")
        imgui.same_line()
        if imgui.small_button("lowest Y"):
            self._try(st.align, "y", "min")
        imgui.same_line()
        if imgui.small_button("highest Y"):
            self._try(st.align, "y", "max")
        if imgui.button("Same distance between them (the two ends stay)"):
            self._try(st.distribute)

    # ------------------------------------------------------------------------------ 5. falls
    def sec_falls(self) -> None:
        st = self.state
        if not self._header("Fall / trap finder", False):
            return
        imgui.text_wrapped("Walks the map like a player from every start point. Red = an edge with no floor beyond it (you fall "
                           "out of the map). Orange = a place you can fall into but not walk out of.")
        if imgui.button("Search (takes a few seconds)"):
            self._bg("fall finder", st.fall_report, self._fall_done)
        self._job_poll()
        r = self.fall_res
        if r:
            imgui.text(tr("{0} edges without floor, {1} traps").replace("{0}", str(len(r["voids"]))).replace("{1}", str(len(r["traps"]))))
            for label, lst in (("edge", r["voids"]), ("trap", r["traps"])):
                for k, d in enumerate(lst[:15]):
                    imgui.push_id(f"fr{label}{k}")
                    if imgui.small_button("Go to"):
                        self.go_to(d["pos"])
                    imgui.same_line()
                    p = d["pos"]
                    imgui.text(f"{tr(label)}  {p[0]:.0f} {p[1]:.0f} {p[2]:.0f}  ({d['count']})")
                    imgui.pop_id()
            if imgui.button("Hide the marks##fall"):
                self.fall_res = None
        imgui.text_wrapped("Close the traps: an invisible wall on the edge where a player drops into a place he cannot "
                           "walk out of (a pit CS players crawl out of: Torrente's player cannot crouch).")
        if imgui.button("Close the traps##fall"):
            self._bg("close traps", st.trap_boxes, lambda r: (self.log(st.apply_trap_boxes(*r)),
                                                              setattr(self, "fall_res", None)))

    def _fall_done(self, r) -> None:
        self.fall_res = r
        self.log(f"fall finder: {len(r['voids'])} edges without floor, {len(r['traps'])} traps")

    # ------------------------------------------------------------------------------ 6. start points
    def sec_spawns(self) -> None:
        st = self.state
        if not self._header("Start point check", False):
            return
        if imgui.button("Check the start points"):
            def done(r):
                self.spawn_res = r
                self.log(tr("{0} start point problems").replace("{0}", str(len(r))))
            self._bg("start point check", st.spawn_report, done)
        imgui.text_disabled("Inside a wall, in the air, no floor under it, or in sight of the other team's start points.")
        self._job_poll()
        for k, d in enumerate(self.spawn_res or []):
            imgui.push_id(f"sp{k}")
            if imgui.small_button("Go to"):
                self.go_to(d["pos"])
            imgui.same_line()
            imgui.text_wrapped(f"{d['name']}: {tr(d['problem'])}")
            imgui.pop_id()
        if self.spawn_res == []:
            imgui.text_colored(_V4(0.3, 1, 0.4, 1), tr("no problems"))
        imgui.separator()
        if not hasattr(self, "spread_n"):
            self.spread_n = 32.0
        imgui.set_next_item_width(120)
        _, self.spread_n = ui.drag_float("start points##spread", float(self.spread_n), 1.0, 2.0, 128.0)
        imgui.same_line()
        if imgui.button("Spread them over the whole floor##spread"):
            self._try(st.spread_spawns, int(self.spread_n))
        imgui.text_disabled("For a deathmatch: the start points are replaced by new ones as far apart as possible on every "
                            "floor you can walk to (and back) from the current ones, always on the floor itself, with room "
                            "around them. Locked ones stay.")

    # ------------------------------------------------------------------------------ 7. load map
    def sec_load(self) -> None:
        st = self.state
        if not self._header("Load map (where the map is heavy)", False):
            return
        if imgui.button("Measure the load"):
            self.load_res = self._try(st.load_report)
        r = self.load_res
        if r:
            imgui.text(tr("{0} triangles, {1} see-through").replace("{0}", str(r["total"])).replace("{1}", str(r["transparent"])))
            _, self.load_show = ui.checkbox("Show the squares (green = light, red = heavy)", self.load_show)
            imgui.text_disabled("See-through triangles (leaves, fences, glass) cost the most: they are sorted one by one.")
            for k, d in enumerate(r["cells"][:10]):
                imgui.push_id(f"ld{k}")
                if imgui.small_button("Go to"):
                    self.go_to(np.array([d["x"], d["y"], d["z"]]))
                imgui.same_line()
                imgui.text(tr("{0} triangles ({1} see-through)").replace("{0}", str(d["tris"])).replace("{1}", str(d["transparent"])))
                imgui.pop_id()

    # ------------------------------------------------------------------------------ 8. collision clean-up
    def sec_clean(self) -> None:
        st = self.state
        if not self._header("Collision clean-up", False):
            return
        if imgui.button("Look for useless boxes"):
            def done(r):
                self.clean_res = r
                self._clean_boxes()
                self.log(tr("{0} duplicated, {1} inside another, {2} alone").replace("{0}", str(len(r["duplicate"])))
                         .replace("{1}", str(len(r["inside"]))).replace("{2}", str(len(r["alone"]))))
            self._bg("collision clean-up", st.collision_cleanup_report, done)
        self._job_poll()
        r = self.clean_res
        if not r:
            return
        imgui.text(tr("{0} duplicated, {1} inside another, {2} alone").replace("{0}", str(len(r["duplicate"])))
                   .replace("{1}", str(len(r["inside"]))).replace("{2}", str(len(r["alone"]))))
        ch, v = ui.checkbox("Show them in red", bool(r.get("_show")))
        if ch:
            r["_show"] = v
        if (r["duplicate"] or r["inside"]) and imgui.button("Remove the duplicated and the ones inside another"):
            self._try(st.remove_boxes, r["duplicate"] + r["inside"])
            self.clean_res = None
            self._col_key = None
            return
        if r["alone"]:
            imgui.text_wrapped(tr("'Alone' = nothing of the map near them: often an invisible wall on purpose (the edge of the "
                                  "map). Look before removing:"))
            for k, i in enumerate(r["alone"][:25]):
                imgui.push_id(f"cl{k}")
                c, h = st.collision_box(i)
                if imgui.small_button("Go to"):
                    self.go_to(c)
                imgui.same_line()
                if imgui.small_button("Remove"):
                    self._try(st.remove_boxes, [i])
                    self.clean_res = None
                    self._col_key = None
                    imgui.pop_id()
                    return
                imgui.same_line()
                imgui.text(f"box {i}  {2 * h[0]:.0f}x{2 * h[1]:.0f}x{2 * h[2]:.0f}")
                imgui.pop_id()

    def _clean_boxes(self) -> None:
        st, r = self.state, self.clean_res
        out = []
        for i in r["duplicate"] + r["inside"] + r["alone"]:
            try:
                c, h = st.collision_box(i)
                out.append((np.asarray(c, np.float64) * F, np.abs(np.asarray(h, np.float64)) * 2 + 4))
            except Exception:
                pass
        r["_boxes"] = out

    # ------------------------------------------------------------------------------ 9. textures
    def sec_textures(self) -> None:
        st = self.state
        if not self._header("Textures: search / replace", False):
            return
        nb = len(st.black_materials())
        if nb:
            imgui.text_colored(_V4(1.0, 0.45, 0.3, 1), tr("{0} materials without colour: the game draws them black").replace("{0}", str(nb)))
            if imgui.button("Fix black materials"):
                self._try(st.fix_black_materials)
                self.rebake()
        if not hasattr(self, "tex_fill"):
            self.tex_fill = "black.tex"
        _, self.tex_fill = ui.input_text("texture to cover with the ones around it", self.tex_fill)
        if imgui.button("Use the textures around it##fill"):
            self._try(st.retexture_from_neighbours, self.tex_fill)
            self.rebake()
        imgui.text_wrapped(tr("For the black squares of an imported CS map (\"black\" in gaps between crates): each face "
                              "takes the texture of the faces it touches. Only the drawing changes - the collision "
                              "(stairs, walls) stays, unlike deleting the mesh."))
        imgui.separator()
        if not hasattr(self, "tex_water"):
            self.tex_water = ""
            try:
                names = sorted({str(m.materials[0].diffuse) for m in st.opt.meshes if m.materials and
                                any(w in str(m.materials[0].diffuse).lower() for w in ("water", "agua", "mar_"))})
                self.tex_water = names[0] if names else ""
            except Exception:
                pass
        _, self.tex_water = ui.input_text("water texture##wl", self.tex_water)
        if imgui.button("Water that flickers in the game: draw only its top##wl") and self.tex_water.strip():
            self._try(st.fix_water_layers, self.tex_water.strip())
            self.rebake()
        imgui.text_wrapped(tr("A water volume of a CS map (de_aztec) came with every face: its top from above and from "
                              "below, its bottom lying on the pool's floor (the same plane: it flickers) and its sides "
                              "under the water. Only the top stays (seen from both sides); the collision is the same."))
        imgui.separator()
        imgui.text("The light of a CS map (its lightmaps: sun, shadows)")
        try:
            from .. import lightmap as _lm
            n_lit = _lm.lit_meshes(st.opt) if st.opt is not None else 0
        except Exception:
            n_lit = 0
        imgui.text(tr("This map: {0}").replace("{0}", tr("{0} meshes with the CS light").replace("{0}", str(n_lit))
                                                if n_lit else tr("no CS light")))
        ch, v = ui.checkbox("show the CS light in the editor (as the game draws it)##lm",
                            bool(getattr(self.gl, "show_lightmaps", True)))
        if ch:
            self.gl.show_lightmaps = bool(v)
        if not hasattr(self, "tex_lmbsp"):
            from .. import settings as _settings
            self.tex_lmbsp = str((_settings.get("bsp_of_map", {}) or {}).get(st.map_stem() if st.opt is not None else "", ""))
        _, self.tex_lmbsp = ui.input_text("the .bsp this map was made from##lm", self.tex_lmbsp)
        imgui.same_line()
        if imgui.small_button("...##lmbsp"):
            from .editor import pick_file
            got = pick_file("Counter-Strike / Half-Life map", [("CS 1.6 map", "*.bsp")])
            if got:
                self.tex_lmbsp = got
        if imgui.button("Add the light of the .bsp (sun, shadows)##lm") and self.tex_lmbsp.strip():
            path = self.tex_lmbsp.strip().strip('"')
            if self._try(st.bsp_light, path):
                try:
                    from .. import settings as _settings
                    d = dict(_settings.get("bsp_of_map", {}) or {})
                    d[st.map_stem()] = path
                    _settings.set("bsp_of_map", d)
                except Exception:
                    pass
            self.rebake()
        if n_lit:
            imgui.same_line()
            if imgui.button("Take the CS light off##lm"):
                self._try(st.remove_bsp_light)
                self.rebake()
        imgui.text_wrapped(tr("The map is saved as it is shown: with the CS light (save) or without it (take it off, "
                              "save). For a map made from a CS map whose walls look flat grey (de_dust2_cs2, "
                              "de_mirage_cs2): in CS the colour of those walls comes from the map's light. Its lightmaps "
                              "become a second texture of each mesh (drawn x 2 by the game, like its own glow textures); "
                              "its models (cars, palm trees, crates) take the light of the floor under them, as in CS."))
        if imgui.button("Walls with no texture (see-through): draw again the faces of the .bsp missing##lmfill") \
                and self.tex_lmbsp.strip():
            self._try(st.restore_bsp_faces, self.tex_lmbsp.strip().strip('"'))
            self.rebake()
        if imgui.button("Cut meshes too big for the game (the game closes after loading)##lmcut"):
            self._try(st.split_big_meshes)
            self.rebake()
        if imgui.button("Blinking decals / dark see-through sheets: fix them from the .bsp##lmdec") \
                and self.tex_lmbsp.strip():
            self._try(st.fix_bsp_overlays, self.tex_lmbsp.strip().strip('"'))
            self.rebake()
        imgui.text_wrapped(tr("Signs, trims and stains of the CS map lie one unit in front of their wall: in the game "
                              "they blink. They move a little further out. A beam of sunlight (an additive brush) "
                              "looks like a dark see-through sheet with black edges: it is taken out."))
        imgui.text_wrapped(tr("Thin slabs (fences, straw under a roof, planks) have two faces back to back; the game "
                              "draws each from both sides, so they blink: one of the two is taken out."))
        if imgui.button("Bars, grilles, railings: bullets through the gaps (from the .bsp)##lmgr") \
                and self.tex_lmbsp.strip():
            self._try(st.open_bsp_grilles, self.tex_lmbsp.strip().strip('"'))
        imgui.text_wrapped(tr("The collision of a CS map fills the gaps between bars narrower than a player: bullets "
                              "stopped at an invisible slab. It is cut down to the bars and the wall round them, as in "
                              "CS: bullets fly through the gaps, players still cannot get through."))
        if imgui.button("Stairs: make the floor collision again from the .bsp##lmfloor") and self.tex_lmbsp.strip():
            self._try(st.rebuild_bsp_floor, self.tex_lmbsp.strip().strip('"'))
        imgui.text_wrapped(tr("The floor collision (.hm) is made again from the .bsp with today's rules: a staircase is one even slope with nothing under it, a small step without a riser gets a ramp, the floor inside solid entities (a staircase, a crate) goes, walls of the crouching hull standing out of a floor are cut down and the lintels of crouch passages go (with their collision boxes). Then press the bars button again if the map has bars or railings."))
        imgui.text_wrapped(tr("A wall, ceiling or floor of the CS map that is not in this map (made with an older "
                              "editor, or deleted): one sees out of the map through it. Every face of the .bsp no mesh "
                              "draws, not even in part, becomes a new mesh with its texture (and the CS light if the "
                              "map has it); the collision stays the same."))
        imgui.separator()
        _, self.tex_old = ui.input_text("texture to replace", self.tex_old)
        _, self.tex_new = ui.input_text("new texture", self.tex_new)
        _, self.tex_sel = ui.checkbox("only in the selection (and group)", self.tex_sel)
        if imgui.button("Replace"):
            self._try(st.replace_texture, self.tex_old, self.tex_new, self.tex_sel)
        if imgui.tree_node("Textures of the map (most used first)"):
            for k, d in enumerate(st.texture_usage()[:80]):
                imgui.push_id(f"tu{k}")
                if imgui.small_button("Use"):
                    self.tex_old = d["texture"]
                imgui.same_line()
                imgui.text(tr("{0}: {1} triangles in {2} objects").replace("{0}", d["texture"]).replace("{1}", str(d["tris"]))
                           .replace("{2}", str(d["objects"])))
                imgui.pop_id()
            imgui.tree_pop()
        un = st.unused_textures()
        imgui.text(tr("{0} textures named but not used by any triangle (not exported)").replace("{0}", str(len(un))))
        if un and imgui.tree_node("which##unused"):
            for t in un[:60]:
                imgui.text(t)
            imgui.tree_pop()

    # ------------------------------------------------------------------------------ 10. sectors
    def sec_sectors(self) -> None:
        st = self.state
        if not self._header("Sectors (what the game draws from where)", False):
            return
        imgui.text_wrapped("The game splits the map in sectors and draws what each sector lists. Something moved far away may "
                           "not be listed where it is now: the game skips it from there. This adds what is missing.")
        if imgui.button("Rebuild the sectors"):
            self._try(st.rebuild_sectors)

    # ------------------------------------------------------------------------------ 11. animations
    def sec_keys(self) -> None:
        st = self.state
        if not self._header("Animations (.key): speed and route", False):
            return
        names = st.key_names()
        if names:
            labels = names
            cur = names.index(self.key_sel) if self.key_sel in names else 0
            _, i = ui.combo("animation of the scene", cur, labels)
            self.key_sel = names[i]
        _, self.key_sel = ui.input_text("animation (keys/...)", self.key_sel)
        if self.key_sel:
            try:
                info = st.key_info(self.key_sel)
                imgui.text(tr("{0} frames, {1} parts, {2} events").replace("{0}", str(info["frames"]))
                           .replace("{1}", str(info["nodes"])).replace("{2}", str(info["events"])))
            except Exception as e:
                imgui.text_disabled(str(e))
        _, self.key_speed = ui.drag_float("speed (2 = twice as fast)", self.key_speed, 0.05, 0.05, 20.0)
        _, self.key_new = ui.input_text("new name (empty = automatic)", self.key_new)
        sel = st.selection
        is_mod = sel is not None and sel.kind == "module"
        if is_mod:
            _, self.key_use = ui.checkbox("the selected module uses the new one", self.key_use)
        if imgui.button("Make the faster / slower copy"):
            self._try(st.retime_key, self.key_sel, self.key_speed, self.key_new,
                      sel.ref if (is_mod and self.key_use) else None)
        imgui.text_disabled("A new .key next to the old one (never over it). Sounds of the animation move with it.")
        imgui.separator()
        self.sec_keys_paths()

    # ------------------------------------------------------------------------------ fair game-mode layout
    LAYOUT_MODES = (("B", "Capture the flag"), ("DO", "Destroy the target"), ("DMT", "Team deathmatch"), ("DM", "Deathmatch"))

    def sec_layout(self) -> None:
        st = self.state
        if not self._header("Game mode layout (fair for both teams)", False):
            return
        L = self.layout
        _, L["mode"] = ui.combo("mode##lay", L["mode"], [tr(n) for _c, n in self.LAYOUT_MODES])
        for name, attr in (("A", "layout_a"), ("B", "layout_b")):
            if imgui.button(f"Base {name} = here##lay"):
                setattr(self, attr, np.asarray(self.here_point(False), np.float64))
            imgui.same_line()
            q = getattr(self, attr)
            imgui.text(f"{q[0]:.0f} {q[1]:.0f} {q[2]:.0f}" if q is not None else tr("not chosen"))
        imgui.text_disabled("Base A = team 0 (its flag), base B = team 1. In deathmatch they only mark the area.")
        _, L["per"] = ui.drag_float("start points per team##lay", float(L["per"]), 1.0, 1.0, 32.0)
        _, L["radius"] = ui.drag_float("around the base (radius)##lay", L["radius"], 10.0, 50.0, 5000.0)
        _, L["health"] = ui.drag_float("health packs (pairs, only if the map has none)##lay", float(L["health"]), 2.0, 0.0, 16.0)
        if imgui.button("Lay it out") and self.layout_a is not None and self.layout_b is not None:
            self._try(st.symmetric_layout, self.LAYOUT_MODES[L["mode"]][0], self.layout_a, self.layout_b, int(L["per"]),
                      L["radius"], int(L["health"]))
        imgui.text_disabled("The old start points (and flags / target) are replaced; locked ones stay. Ctrl+Z undoes it.")

    # ------------------------------------------------------------------------------ match simulation
    def sec_sim(self) -> None:
        st = self.state
        if not self._header("Match simulation (every game mode)", False):
            return
        imgui.text_wrapped("Every start point runs to what its game mode makes it go to, along the shortest way: capture the "
                           "flag = to the enemy flag and back, destroy the target = to the target, team deathmatch = towards "
                           "the other team, deathmatch = to a health pack and the middle.")
        if imgui.button("Simulate (takes a few seconds)"):
            def done(r):
                self.sim_res = r
                self.log(tr("simulation ({0}): {1} routes, first meeting after {2} s").replace("{0}", r["mode"])
                         .replace("{1}", str(len(r["routes"]))).replace("{2}", f"{r['first']:.1f}" if r["first"] is not None else "-"))
            self._bg("match simulation", st.simulate_match, done)
        self._job_poll()
        r = self.sim_res
        if not r:
            return
        _, self.sim_show = ui.checkbox("Show the routes (colour = team, white = where they meet)", self.sim_show)
        if r["first"] is not None:
            imgui.text(tr("first meeting after {0} s").replace("{0}", f"{r['first']:.1f}"))
        for k, m in enumerate(r["meets"][:10]):
            imgui.push_id(f"sm{k}")
            if imgui.small_button("Go to"):
                self.go_to(m["pos"])
            imgui.same_line()
            imgui.text(f"{m['time']:.1f} s  {m['who']}")
            imgui.pop_id()
        if imgui.tree_node("busiest places##sim"):
            for k, d in enumerate(r["busy"][:10]):
                imgui.push_id(f"sb{k}")
                if imgui.small_button("Go to"):
                    self.go_to(d["pos"])
                imgui.same_line()
                imgui.text(tr("{0} routes go through here").replace("{0}", str(d["routes"])))
                imgui.pop_id()
            imgui.tree_pop()
        if imgui.button("Hide##sim"):
            self.sim_res = None

    # ------------------------------------------------------------------------------ gaps in the floor, buried objects
    def sec_gaps(self) -> None:
        st = self.state
        if not self._header("Floor gaps and buried objects", False):
            return
        if imgui.button("Look for gaps in the floor collision"):
            self.gap_res = self._try(st.floor_gaps)
            if self.gap_res is not None:
                self.log(tr("{0} gaps in the floor").replace("{0}", str(len(self.gap_res))))
        imgui.text_disabled("A crack between two floors where a foot gets stuck or a player falls through (pink).")
        for k, d in enumerate((self.gap_res or [])[:12]):
            imgui.push_id(f"gp{k}")
            if imgui.small_button("Go to"):
                self.go_to(d["pos"])
            imgui.same_line()
            p = d["pos"]
            imgui.text(f"{p[0]:.0f} {p[1]:.0f} {p[2]:.0f}  ({d['count']})")
            imgui.pop_id()
        imgui.separator()
        if imgui.button("Look for objects under the floor"):
            self.buried_res = self._try(st.buried_objects)
            if self.buried_res is not None:
                self.log(tr("{0} objects under the floor").replace("{0}", str(len(self.buried_res))))
        imgui.text_disabled("Completely under the floor: nobody sees them, but the game still draws them (purple).")
        for k, d in enumerate((self.buried_res or [])[:12]):
            imgui.push_id(f"bu{k}")
            if imgui.small_button("Go to"):
                self.go_to(d["pos"])
            imgui.same_line()
            if imgui.small_button("Select"):
                from .state import Selection
                ref = st.opt.meshes[d["index"]] if d["kind"] == "mesh" else st.opt.props[d["index"]]
                st.selection, st.multi = Selection(d["kind"], ref, f"{d['kind']} {d['index']}"), []
            imgui.same_line()
            imgui.text(tr("{0} {1}, {2} m under the floor").replace("{0}", d["kind"]).replace("{1}", str(d["index"]))
                       .replace("{2}", f"{d['depth'] / 100:.1f}"))
            imgui.pop_id()

    # ------------------------------------------------------------------------------ weather / sky presets
    def sec_weather(self) -> None:
        st = self.state
        if not self._header("Weather and sky (presets)", False):
            return
        _, self.weather_lights = ui.checkbox("also the ambient light and the suns", self.weather_lights)
        for key, label in (("day", "Day"), ("sunset", "Sunset"), ("night", "Night"), ("storm", "Storm"), ("fog", "Fog")):
            if imgui.button(f"{tr(label)}##wp"):
                self._try(st.weather_preset, key, self.weather_lights)
                self.opts["sky"] = self.opts["scene_fog"] = True
                if self.weather_lights:
                    self.opts["lit"] = True
            imgui.same_line()
        imgui.new_line()
        imgui.text_disabled("Sky, fog colour and distance (and light colours). The view shows it as the game; Ctrl+Z undoes it.")

    # ------------------------------------------------------------------------------ animation paths (routes)
    def sec_keys_paths(self) -> None:
        st = self.state
        _, self.anim_show = ui.checkbox("Show where the animated models go (cyan)", self.anim_show)
        if self.key_sel:
            imgui.text("Change its route (a new .key):")
            _, self.anim_scale = ui.drag_float("route size (1 = as it is)##anim", self.anim_scale, 0.01, 0.05, 20.0)
            _, self.anim_off = ui.drag_float3("move the route##anim", self.anim_off, 5.0)
            _, self.anim_new = ui.input_text("new name##anim", self.anim_new)
            sel = st.selection
            is_mod = sel is not None and sel.kind == "module"
            if imgui.button("Make the new route"):
                self._try(st.transform_key, self.key_sel, self.anim_scale, self.anim_off, self.anim_new,
                          sel.ref if (is_mod and self.key_use) else None)

    # ------------------------------------------------------------------------------ changes since a saved version
    def sec_changes(self) -> None:
        st = self.state
        if not self._header("Changes since a saved version", False):
            return
        try:
            hist = st.history()
        except Exception:
            hist = []
        if not hist:
            imgui.text_disabled("No saved versions yet (they are kept each time you save).")
            return
        for k, e in enumerate(hist[:10]):
            stamp, ent = (e[0], e[1]) if isinstance(e, tuple) else (e, {})
            imgui.push_id(f"ch{k}")
            if imgui.small_button("Show changes"):
                self.change_res = self._try(st.version_marks, stamp)
                if self.change_res is not None:
                    self.log(tr("{0} changes since {1}").replace("{0}", str(len(self.change_res))).replace("{1}", str(stamp)))
            imgui.same_line()
            imgui.text(str(stamp) + ("  " + str(ent.get("note", "")) if isinstance(ent, dict) and ent.get("note") else ""))
            imgui.pop_id()
        r = self.change_res
        if r is not None:
            imgui.text_colored(_V4(0.3, 1, 0.3, 1), tr("green = new"))
            imgui.same_line()
            imgui.text_colored(_V4(1, 0.3, 0.3, 1), tr("red = taken away"))
            imgui.same_line()
            imgui.text_colored(_V4(1, 0.9, 0.2, 1), tr("yellow = moved"))
            for k, (kind, sign, p) in enumerate(r[:25]):
                imgui.push_id(f"cg{k}")
                if imgui.small_button("Go to"):
                    self.go_to(p)
                imgui.same_line()
                imgui.text(f"{sign} {tr(kind)}  {p[0]:.0f} {p[1]:.0f} {p[2]:.0f}")
                imgui.pop_id()
            if imgui.button("Hide##chg"):
                self.change_res = None

    # ------------------------------------------------------------------------------ command search (Ctrl+P) and shortcuts
    def commands(self) -> list:
        """[(name, function)] of everything the search and the shortcuts can run."""
        st = self.state
        out = [
            ("Save scene", lambda: self.save_scene_checked()),
            ("Undo", self.do_undo), ("Redo", self.do_redo),
            ("Check the map", lambda: setattr(self, "check_res", self._try(st.validate_map) or [])),
            ("Drop the selection to the floor", lambda: self._try(st.drop_to_floor)),
            ("Same distance between them", lambda: self._try(st.distribute)),
            ("Rebuild the sectors", lambda: self._try(st.rebuild_sectors)),
            ("Measure the load", lambda: setattr(self, "load_res", self._try(st.load_report))),
            ("Look for gaps in the floor collision", lambda: setattr(self, "gap_res", self._try(st.floor_gaps))),
            ("Show / hide Map tools", lambda: setattr(self, "show_tools", not self.show_tools)),
            ("Lit view on / off", lambda: self.opts.__setitem__("lit", not self.opts.get("lit"))),
            ("Show floor collision (.hm)", lambda: self.opts.__setitem__("hm", not self.opts.get("hm"))),
        ]
        for i, t in enumerate(("select", "move", "rotate", "scale", "pen", "fill", "measure", "collision", "paint")):
            out.append((f"Tool {i + 1}: {t}", (lambda t=t: setattr(self, "tool", t))))
        for h in sorted(getattr(self, "_seen_headers", set())):
            out.append((h, (lambda h=h: self._open(h))))
        return out

    def _open(self, header: str) -> None:
        self.show_tools = True
        self._open_section = header
        self.tools_cat = 0                                    # 'All': every section is drawn, so the chosen one opens

    def _run(self, name: str) -> None:
        for n, fn in self.commands():
            if n == name:
                try:
                    fn()
                except Exception as e:
                    self.log(f"{name}: {e}")
                return
        self.log(tr("command not found: {0}").replace("{0}", name))

    def palette_ui(self) -> None:
        if not self.pal_open:
            return
        imgui.open_popup("Find a tool")
        if imgui.begin_popup("Find a tool"):
            if imgui.is_window_appearing():
                imgui.set_keyboard_focus_here()
            ch, v = ui.input_text("##palq", self.pal_text)
            if ch:
                self.pal_text, self.pal_sel = v, 0
            words = [w for w in self.pal_text.lower().split() if w]
            hits = [n for n, _f in self.commands() if all(w in (n + " " + tr(n)).lower() for w in words)][:15]
            run = None
            for k, n in enumerate(hits):
                if ui.selectable(tr(n), k == self.pal_sel):
                    run = n
            import glfw
            if hits and self.key_edge(glfw.KEY_ENTER):
                run = hits[min(self.pal_sel, len(hits) - 1)]
            if self.key_edge(glfw.KEY_DOWN):
                self.pal_sel = min(self.pal_sel + 1, max(len(hits) - 1, 0))
            if self.key_edge(glfw.KEY_UP):
                self.pal_sel = max(self.pal_sel - 1, 0)
            if run or self.key_edge(glfw.KEY_ESCAPE):
                self.pal_open = False
                imgui.close_current_popup()
                if run:
                    self._run(run)
            imgui.end_popup()
        else:
            self.pal_open = False

    def palette_keys(self, ctrl: bool, shift: bool) -> None:
        import glfw
        if ctrl and self.key_edge(glfw.KEY_P):
            self.pal_open, self.pal_text, self.pal_sel = True, "", 0
            return
        from .. import settings
        sc = settings.get("shortcuts") or {}
        alt = self.key(glfw.KEY_LEFT_ALT) or self.key(glfw.KEY_RIGHT_ALT)
        for combo, name in sc.items():
            parts = [p.strip().lower() for p in str(combo).split("+") if p.strip()]
            if not parts:
                continue
            key = getattr(glfw, "KEY_" + parts[-1].upper(), None)
            if key is None:
                continue
            mods = set(parts[:-1])
            if ("ctrl" in mods) != bool(ctrl) or ("shift" in mods) != bool(shift) or ("alt" in mods) != bool(alt):
                continue
            if self.key_edge(key):
                self._run(name)

    def sec_shortcuts(self) -> None:
        from .. import settings
        if not self._header("Shortcuts and command search (Ctrl+P)", False):
            return
        imgui.text_wrapped("Ctrl+P opens a search: type part of a tool's name and press Enter. Below, give any of them your "
                           "own key.")
        names = [n for n, _f in self.commands()]
        if not names:
            return
        _, self.sc_cmd = ui.combo("command##sc", min(self.sc_cmd, len(names) - 1), [tr(n) for n in names])
        _, self.sc_key = ui.input_text("key (Ctrl+1, Shift+F5, Alt+G ...)##sc", self.sc_key)
        if imgui.button("Add shortcut"):
            combo = self.sc_key.strip()
            last = combo.split("+")[-1].strip().upper() if combo else ""
            import glfw
            if not combo or getattr(glfw, "KEY_" + last, None) is None:
                self.log(tr("unknown key: {0}").replace("{0}", combo))
            else:
                d = dict(settings.get("shortcuts") or {})
                d[combo] = names[min(self.sc_cmd, len(names) - 1)]
                settings.set("shortcuts", d)
        sc = dict(settings.get("shortcuts") or {})
        for k, (combo, name) in enumerate(sorted(sc.items())):
            imgui.push_id(f"sc{k}")
            if imgui.small_button("x"):
                sc.pop(combo, None)
                settings.set("shortcuts", sc)
                imgui.pop_id()
                break
            imgui.same_line()
            imgui.text(f"{combo}  ->  {tr(name)}")
            imgui.pop_id()
        imgui.text_disabled("Saved in vtoy_editor.json ('shortcuts'). Keys the editor already uses (WASD, G, R, T, Q, H ...) still do their job.")

    # ------------------------------------------------------------------------------ shapes (like a drawing program)
    SHAPE_LIST = (("box", "Box / cube / rectangle"), ("cylinder", "Cylinder (round column)"), ("cone", "Cone"),
                  ("ramp", "Ramp"), ("stairs", "Stairs"), ("pyramid", "Pyramid"), ("wall", "Wall"),
                  ("disc", "Disc (round platform)"), ("polygon", "Outline by points A, B, C ... (raised)"),
                  ("rect", "Rectangle by 2 points (opposite corners)"), ("circle", "Circle by 2 points (centre, edge)"))

    def _cs_file_ui(self, b, tag: str) -> bool:
        """The CS map file of the importer / creator: path, browse, and what its textures need (the .wad files it names,
        found next to it or not, how many textures nobody has).  True when a readable map is chosen."""
        st = self.state
        ch, v = ui.input_text("file (.bsp or .rmf)##" + tag, b["path"])
        if ch:
            b["path"], b["rows"], b["err"], b["rep"] = v.strip().strip('"'), None, "", None
        if imgui.button("Browse...##" + tag):
            from .editor import pick_file
            pth = pick_file("Counter-Strike / Half-Life map", [("CS 1.6 map", "*.bsp *.rmf"), ("BSP", "*.bsp"),
                                                               ("Hammer RMF", "*.rmf"), (tr("All files"), "*.*")])
            if pth:
                b["path"], b["rows"], b["err"], b["rep"] = pth, None, "", None
        if not b["path"] or not os.path.isfile(b["path"]):
            imgui.text_disabled("A compiled map (.bsp) or a Hammer map (.rmf) of Counter-Strike 1.6 / Half-Life.")
            return False
        wads = [w for w in b["wads"].split(";") if w.strip()]
        key = (b["path"], tuple(wads))
        if b.get("rep") is None or b.get("rep_key") != key:
            b["rep_key"] = key
            try:
                b["rep"] = st.cs_wad_report(b["path"], wads)
                b["err"] = ""
            except Exception as e:
                b["rep"], b["err"] = {}, str(e)
        if b["err"]:
            imgui.text_colored(_V4(1.0, 0.4, 0.3, 1), tr(b["err"]))
            return False
        rep = b["rep"]
        given = {os.path.basename(w).lower() for w in wads}
        if rep.get("listed"):
            imgui.text(tr("The map uses these texture packs (.wad):"))
            for n in rep["listed"]:
                if n.lower() in given:
                    imgui.text_colored(_V4(0.5, 0.9, 0.5, 1), "  " + n + "  " + tr("loaded"))
                elif n in rep.get("found", {}):
                    imgui.text_colored(_V4(1.0, 0.85, 0.3, 1), "  " + n + "  " + tr("found next to the map, not loaded"))
                else:
                    imgui.text_colored(_V4(1.0, 0.5, 0.4, 1), "  " + n + "  " + tr("not loaded"))
            if rep.get("found") and imgui.button(tr("Load the {0} found").replace("{0}", str(len(rep["found"]))) + "##" + tag):
                low = {w.lower() for w in wads}
                wads += [p for p in rep["found"].values() if p.lower() not in low]
                b["wads"], b["rep"] = ";".join(wads), None
        n_tex = rep.get("textures", 0)
        miss = rep.get("missing", [])
        imgui.text(tr("{0} textures: {1} inside the map, {2} in the loaded .wad files, {3} missing")
                   .replace("{0}", str(n_tex)).replace("{1}", str(rep.get("inside", 0)))
                   .replace("{2}", str(rep.get("in_wads", 0))).replace("{3}", str(len(miss))))
        if miss:
            imgui.text_colored(_V4(1.0, 0.75, 0.3, 1), tr(
                "Load the .wad files this map needs (Half-Life folders valve and cstrike: halflife.wad, cs_dust.wad ...) "
                "to get its own textures. Without them, the missing ones are drawn with Torrente textures that look alike."))
            if imgui.is_item_hovered():
                imgui.set_tooltip(", ".join(miss[:40]) + (" ..." if len(miss) > 40 else ""))
        mods, mmiss = rep.get("models", []), rep.get("models_missing", [])
        if mods or mmiss:
            imgui.text(tr("Models (.mdl: cars, palm trees ...): {0} found, {1} missing")
                       .replace("{0}", str(len(mods))).replace("{1}", str(len(mmiss))))
            if mmiss:
                imgui.text_colored(_V4(1.0, 0.75, 0.3, 1), tr(
                    "Missing models are looked for in the folder over the map's maps folder (cstrike/models/...) and next "
                    "to the .wad files; put them there to bring them too."))
                if imgui.is_item_hovered():
                    imgui.set_tooltip(", ".join(mmiss[:30]) + (" ..." if len(mmiss) > 30 else ""))
        self._wad_list_ui(b)
        return True

    def sec_bsp(self) -> None:
        """A Counter-Strike 1.6 / Half-Life map (.bsp / .rmf) laid into this map."""
        st = self.state
        if not self._header("Import a Counter-Strike 1.6 map (.bsp / .rmf)", False):
            return
        b = self.bsp
        if not self._cs_file_ui(b, "bsp"):
            return
        wads = [w for w in b["wads"].split(";") if w.strip()]
        if imgui.button("Put it where the view looks##bsp") or b["at"] is None:
            b["at"] = np.asarray(self.here_point(False), np.float64)
        imgui.same_line()
        _, b["at"] = ui.drag_float3("place (middle of its floor)##bsp", b["at"], 5.0)
        _, b["yaw"] = ui.drag_float("turn (degrees)##bsp", b["yaw"], 5.0, -360.0, 360.0)
        _, b["scale"] = ui.drag_float("units per CS unit (2.54 = real size)##bsp", b["scale"], 0.01, 0.1, 20.0)
        key = (b["path"], tuple(np.round(b["at"], 1)), round(b["yaw"], 2), round(b["scale"], 3), tuple(wads))
        if key != b["fkey"]:
            b["fkey"] = key
            try:
                b["foot"] = st.bsp_footprint(b["path"], b["at"], b["yaw"], b["scale"], wads)
            except Exception:
                b["foot"] = None
        if b["foot"] is not None:
            lo, hi = b["foot"]
            imgui.text(tr("It covers {0} x {1} m, {2} m high").replace("{0}", f"{(hi[0] - lo[0]) / 100:.1f}")
                       .replace("{1}", f"{(hi[2] - lo[2]) / 100:.1f}").replace("{2}", f"{(hi[1] - lo[1]) / 100:.1f}"))
        _, b["texmode"] = ui.combo("textures##bsp", int(b.get("texmode", 0)),
                                   [tr("its own (from the map and the .wad files)"),
                                    tr("Torrente textures (choose one for each)")])
        if b["texmode"] == 1:
            if b["rows"] is None:
                try:
                    b["rows"] = [[n, g, c, 1.0] for n, g, c in st.bsp_textures(b["path"], wads)]
                except Exception as e:
                    b["rows"], b["err"] = [], str(e)
            imgui.text("CS texture -> Torrente texture (repeats)")
            imgui.begin_child("##bsptex", _V2(0, 150))
            ft = getattr(self, "fill_tex", "")
            for k, row in enumerate(b["rows"]):
                imgui.push_id(9000 + k)
                imgui.text(f"{row[0]} ({row[2]})")
                imgui.set_next_item_width(170)
                _, row[1] = ui.input_text("##t", row[1])
                imgui.same_line()
                imgui.set_next_item_width(70)
                _, row[3] = ui.drag_float("##r", float(row[3]), 0.05, 0.05, 32.0)
                if ft:
                    imgui.same_line()
                    if imgui.small_button(tr("Fill texture")):
                        row[1] = ft
                imgui.pop_id()
            imgui.end_child()
        _, b["clear"] = ui.checkbox("empty the place first (what stands there; the floor stays)##bsp", b["clear"])
        _, b["col"] = ui.checkbox("solid (collision boxes and floor / wall faces)##bsp", b["col"])
        _, b["light"] = ui.checkbox("its light: sun, shadows, lamps (the lightmaps of the .bsp)##bsp", b.get("light", True))
        _, b["water"] = ui.combo("water (pools)##bsp", int(b.get("water", 0)),
                                 [tr("a floor: walk on the water"), tr("a hole: whoever goes in falls out of the map")])
        _, b["spawns"] = ui.checkbox("start points from its player starts (CT team 0, T team 1)##bsp", b["spawns"])
        if b["spawns"]:
            modes = ["keep the scene's mode", "team deathmatch", "destroy the target (its bomb sites A and B)",
                     "deathmatch (start points all over the floor)"]
            _, b["mode"] = ui.combo("game mode##bsp", int(b["mode"]), [tr(m) for m in modes])
            _, b["per"] = ui.drag_float("start points per team (0 = all of them)##bsp", float(b["per"]), 1.0, 0.0, 64.0)
        if imgui.button("Import##bsp"):
            def go():
                msgs = []
                if int(b.get("texmode", 0)) == 0:            # its own textures: converted from the map / the .wad files
                    texmap, rep_ = st.bsp_wad_textures(b["path"], wads), None
                    missing = len(b.get("rep", {}).get("missing", []))
                    msgs.append(tr("{0} textures of its own").replace("{0}", str(len(texmap)))
                                + (", " + tr("{0} like it (Torrente)").replace("{0}", str(missing)) if missing else ""))
                else:
                    if wads:                          # a texture of the table named as one of the .wad: converted now
                        asked = [r[1] for r in b["rows"] if r[1].strip() and st.fs.texture(r[1].strip()) is None]
                        got = st.wad_textures(asked, wads) if asked else {}
                        for r in b["rows"]:
                            if r[1] in got:
                                r[1] = got[r[1]]
                    texmap, rep_ = {r[0]: r[1] for r in b["rows"]}, {r[0]: float(r[3]) for r in b["rows"]}
                if b["clear"] and b["foot"] is not None:
                    lo, hi = b["foot"]
                    msgs.append(st.clear_area(np.asarray(lo) - 100.0, np.asarray(hi) + 100.0))
                mode = ["", "DMT", "DO", "DM"][int(b["mode"])] if b["spawns"] else ""
                msgs.append(st.import_bsp(b["path"], b["at"], b["yaw"], b["scale"], texmap, rep_, b["col"], b["spawns"],
                                          bool(mode), mode=mode, per_team=int(b["per"]) or None,
                                          water=("floor", "hole")[int(b.get("water", 0))], wads=wads,
                                          light=bool(b.get("light", True))))
                if mode == "DM":                     # anywhere on the floor: as many as both teams had (or 2 x per team)
                    n = 2 * int(b["per"]) if int(b["per"]) else sum(
                        1 for r in st.scene.modules if r.clean_name.lower() == "mp_cstartpoint")
                    msgs.append(st.spread_spawns(max(n, 2), avoid=st.last_bsp_water))
                return " | ".join(msgs)
            self._try(go)
            self._col_key = None
        imgui.text_disabled("Then save the map and the scene. To empty a bigger place (a whole pitch), use 'Empty an area' "
                            "with two Measure points first.")
        if len(self.meas) >= 2 and imgui.button("Empty an area: between Measure points A and B##bsp"):
            self._try(st.clear_area, self.meas[0], self.meas[1])
            self._col_key = None
        imgui.separator()
        if imgui.button("A whole new map from it...##bsp"):
            self.csnew["path"], self.csnew["wads"], self.csnew["rep"] = b["path"], b["wads"], None
            self._open("Create from .bsp / .rmf (a whole new map from a CS 1.6 map)")

    def sec_cscreate(self) -> None:
        """A whole new map from a Counter-Strike 1.6 map: its geometry, textures, collision, start points and the mode."""
        st = self.state
        if not self._header("Create from .bsp / .rmf (a whole new map from a CS 1.6 map)", False):
            return
        c = self.csnew
        imgui.text_wrapped(tr("A new map of the game made from a Counter-Strike 1.6 map: at real size, with its own textures, "
                              "the collision a player meets in CS (stairs, clip walls, crates), its start points, health "
                              "packs and what the mode needs. The sky, sun and settings come from the Madrid scene of that "
                              "mode."))
        if not self._cs_file_ui(c, "csnew"):
            return
        stem = os.path.splitext(os.path.basename(c["path"]))[0].lower()
        modes = ["DM", "DMT", "B", "DO"]
        if not c.get("name") or c.get("name_for") != (c["path"], c["mode"]):
            c["name_for"] = (c["path"], c["mode"])
            short = stem.split("_", 1)[1] if "_" in stem else stem
            c["name"] = ("mp_dm_", "mp_dmt_", "mp_b_", "mp_do_")[c["mode"]] + short
        ch, c["mode"] = ui.combo("game mode##csnew", int(c["mode"]), [tr("deathmatch"), tr("team deathmatch"),
                                                                      tr("capture the flag"), tr("destroy the target")])
        _, c["name"] = ui.input_text("name of the new map##csnew", c["name"])
        _, c["per"] = ui.drag_float(("players per team" if c["mode"] else "players (x2 start points)") + "##csnew",
                                    float(c["per"]), 1.0, 1.0, 32.0)
        _, c["water"] = ui.combo("water (pools)##csnew", int(c.get("water", 0)),
                                 [tr("a floor: walk on the water"), tr("a hole: whoever goes in falls out of the map")])
        _, c["light"] = ui.checkbox("its light: sun, shadows, lamps (the lightmaps of the .bsp)##csnew", c.get("light", True))
        if c["mode"] == 3:
            imgui.text_disabled("Its bomb sites A and B become the bomb zones; the bomb lies by the terrorists' start.")
        miss = len((c.get("rep") or {}).get("missing", []))
        if miss:
            imgui.text_colored(_V4(1.0, 0.75, 0.3, 1), tr("{0} textures are missing: load the .wad files above, or create "
                                                          "it with Torrente textures that look alike.").replace("{0}", str(miss)))
        name = c["name"].strip()
        exists = name and (name + ".scn").lower() in {n.lower() for n in st.scene_names()}
        if exists:
            imgui.text_colored(_V4(1.0, 0.5, 0.4, 1), tr("A map with that name already exists: choose another name."))
        if imgui.button("Create the new map##csnew") and name and not exists:
            wads = [w for w in c["wads"].split(";") if w.strip()]
            msg = self._try(st.new_map_from_cs, c["path"], name, modes[int(c["mode"])], wads, int(c["per"]),
                            ("floor", "hole")[int(c.get("water", 0))], "", 0, bool(c.get("light", True)))
            if msg:
                self.load(st.scene_name)
                self._col_key = None

    def sec_blank(self) -> None:
        """A new map from zero: floor of a shape, walls, and what the mode needs."""
        st = self.state
        if not self._header("New map from zero (floor and walls)", False):
            return
        if not hasattr(self, "blank"):
            self.blank = dict(name="mp_dm_nuevo", mode=0, shape=0, w=4000.0, d=3000.0, h=400.0, t=40.0,
                              floor="SUELOS_03.tex", wall="muro_liso.tex", players=16.0)
        p = self.blank
        modes = ["DM", "DMT", "B", "DO"]
        _, p["name"] = ui.input_text("name of the new map##blank", p["name"])
        ch, p["mode"] = ui.combo("game mode##blank", p["mode"], [tr("deathmatch"), tr("team deathmatch"),
                                                                  tr("capture the flag"), tr("destroy the target")])
        if ch:                                                   # the usual prefix of that mode
            stem = p["name"].split("_", 2)[-1] if p["name"].count("_") >= 2 else p["name"]
            p["name"] = ("mp_dm_", "mp_dmt_", "mp_b_", "mp_do_")[p["mode"]] + stem
        names = [tr("rectangle"), tr("square"), tr("circle"), tr("octagon"), tr("L shape")]
        _, p["shape"] = ui.combo("shape##blank", p["shape"], names)
        kind = st.BLANK_SHAPES[p["shape"]]
        if kind in ("square", "circle", "octagon"):
            _, p["w"] = ui.drag_float(("side (cm)" if kind == "square" else "diameter (cm)") + "##blank", p["w"], 10.0, 600.0, 100000.0)
        else:
            _, p["w"] = ui.drag_float("width (cm)##blank", p["w"], 10.0, 600.0, 100000.0)
            _, p["d"] = ui.drag_float("depth (cm)##blank", p["d"], 10.0, 600.0, 100000.0)
        _, p["h"] = ui.drag_float("wall height (cm)##blank", p["h"], 5.0, 50.0, 5000.0)
        _, p["t"] = ui.drag_float("wall thickness (cm)##blank", p["t"], 1.0, 5.0, 500.0)
        _, p["floor"] = ui.input_text("floor texture##blank", p["floor"])
        _, p["wall"] = ui.input_text("wall texture##blank", p["wall"])
        ft = getattr(self, "fill_tex", "")
        if ft:
            if imgui.small_button(tr("Fill texture") + " -> " + tr("floor") + "##blank"):
                p["floor"] = ft
            imgui.same_line()
            if imgui.small_button(tr("Fill texture") + " -> " + tr("walls") + "##blank"):
                p["wall"] = ft
        _, p["players"] = ui.drag_float(("players per team" if p["mode"] else "players (x2 start points)") + "##blank",
                                        float(p["players"]), 1.0, 1.0, 32.0)
        imgui.text_disabled("Sky, sun and settings come from the Madrid scene of that mode. 100 cm = 1 m.")
        if imgui.button("Create the new map##blank"):
            msg = self._try(st.new_blank_map, p["name"].strip(), modes[p["mode"]], kind, p["w"], p["d"], p["h"], p["t"],
                            p["floor"].strip(), p["wall"].strip(), int(p["players"]))
            if msg:
                self.load(st.scene_name)
                self._col_key = None

    def sec_climate(self) -> None:
        """Weather: rain, storm or calm rain, quieter thunder - any mode (DO, DM, DMT, flags)."""
        st = self.state
        if not self._header("Weather: rain / storm (this map)", False):
            return
        wkey = (st.scene_name, str(st.scene.main_module_name))
        if getattr(self, "_wx_key", None) != wkey:
            self._wx_key = wkey
            try:
                self._wx = st.weather_settings()
            except Exception:
                self._wx = {"kind": None, "can": False, "rain": False, "storm": True, "splash": False, "thunder": 100,
                            "rain_vol": 100, "dll": ""}
            w = self._wx
            self._wx_rain = bool(w["rain"]) or not w["can"]
            self._wx_storm = bool(w["storm"])
            self._wx_splash = bool(w["splash"])
            self._wx_thunder = int(w["thunder"])
            self._wx_rainvol = int(w["rain_vol"])
        w = self._wx
        if not w["can"]:
            imgui.text_wrapped(tr("The map's mode DLL ({0}) cannot make rain. Rain comes from Marbella's shower: the "
                                  "destroy-the-target DLL (any DO map) and the DLLs that rain on Marbella / the church "
                                  "(mp_deathMatch, mp_deathMatchTeam, mp_CaptureTheFlag, mp_CaptureChucrch ...) can have it.")
                               .replace("{0}", w["dll"] or "?"))
        else:
            now = tr("no rain")
            if w["rain"]:
                now = tr("rain") + (tr(" with storm (thunder, lightning)") if w["storm"] else tr(" without storm"))
                if w.get("splash"):
                    now += tr(" + splashes on the floor")
                if w["thunder"] < 100 or w["rain_vol"] < 100:
                    now += tr(" (thunder {0} %, rain {1} %)").replace("{0}", str(w["thunder"])).replace("{1}", str(w["rain_vol"]))
            imgui.text(tr("Now ({0}): {1}").replace("{0}", w["dll"]).replace("{1}", now))
            _, self._wx_rain = ui.checkbox("rain like Marbella (the whole map)##wx", bool(self._wx_rain))
            _, self._wx_storm = ui.checkbox("storm: thunder and lightning flashes (like Marbella); unticked: calm rain##wx",
                                            bool(self._wx_storm))
            if w["kind"] == "DO":
                _, self._wx_splash = ui.checkbox("drops splash on the floor round the player (like Marbella)##wx",
                                                 bool(self._wx_splash))
            if self._wx_storm:
                _, v = imgui.slider_int(tr("thunder volume %") + "##wx", int(self._wx_thunder), 0, 100)
                self._wx_thunder = int(v)
            _, v = imgui.slider_int(tr("rain volume %") + "##wx", int(self._wx_rainvol), 0, 100)
            self._wx_rainvol = int(v)
            imgui.text_wrapped(tr("Below 100 %: quieter copies of the game's storm sounds for THIS map only "
                                  "(wavs/<map>_<volume>_trueno.wav ...: they go with the map's zip; the game's own sounds "
                                  "and the other maps stay as they are). Lightning flashes come with the storm."))
            if w["kind"] == "DO":
                imgui.text_disabled("Destroy the target: the bomb zones, the HUD, the minimap and the bomb time of the "
                                    "map's DLL stay as they are.")
            else:
                imgui.text_disabled("Deathmatch / teams / flags: a copy of the mode DLL that rains on this map; the weapon "
                                    "groups chosen for the map stay.")
            if imgui.button("Apply the weather to this map##wx"):
                self._try(st.make_weather_dll, bool(self._wx_rain), bool(self._wx_storm), bool(self._wx_splash),
                          int(self._wx_thunder) if self._wx_storm else 100, int(self._wx_rainvol))
                self._wx_key = self._bz_key = self._bomb_key = self._do_old_key = None
        if imgui.button("Storm look (cielo_war sky + dark fog)##wx"):
            self._try(st.storm_preset)
            self.rebake()

    def sec_bombs(self) -> None:
        """Destroy the target with two bomb sites."""
        st = self.state
        if not self._header("Destroy the target: bomb sites and the bomb", False):
            return
        zones = [r for r in st.scene.modules if r.clean_name.lower() == "mp_bombzone"]
        okey = (st.scene_name, str(st.scene.main_module_name))
        if getattr(self, "_do_old_key", None) != okey:
            self._do_old_key = okey
            try:
                self._do_old = st.do_dll_outdated()
            except Exception:
                self._do_old = []
        if self._do_old:
            imgui.text_colored(_V4(1.0, 0.85, 0.2, 1), tr("This map's DLL was made by an older editor: {0}.")
                               .replace("{0}", "; ".join(tr(x) for x in self._do_old)))
            if imgui.button("Update the map's DLL##doold"):
                self._try(st.update_do_dll)
                self._do_old_key = self._bz_key = self._bomb_key = None
        imgui.text(tr("Bomb zones: {0}").replace("{0}", ", ".join(str(r.object_name).rstrip("\0") for r in zones) or "-"))
        zkey = (st.scene_name, str(st.scene.main_module_name), len(zones))
        if getattr(self, "_bz_key", None) != zkey:
            self._bz_key = zkey
            try:
                self._bz_rule = st.bomb_zone_rules()
            except Exception:
                self._bz_rule = None
            if self._bz_rule is not None:
                self._bz_all = bool(self._bz_rule[1])
                self._bz_hud = bool(self._bz_rule[2]) if len(self._bz_rule) > 2 else True
                self._bz_radar = bool(self._bz_rule[3]) if len(self._bz_rule) > 3 else True
        rule = self._bz_rule
        if rule is None:
            imgui.text_disabled("Now: the game's DLL - only the zone called 'bombZone' ends the round.")
        else:
            imgui.text(tr("Now: {0}").replace("{0}", tr("ALL must be blown up: {0}") if rule[1] else tr("any one wins: {0}"))
                       .replace("{0}", ", ".join(["bombZone"] + list(rule[0])))
                       + (tr(" (on the HUD)") if len(rule) > 2 and rule[2] else "")
                       + (tr(" (minimap: the nearest)") if len(rule) > 3 and rule[3] else ""))
        imgui.text_disabled("The game's DO mode only ends the round when the zone called 'bombZone' blows up. With a copy "
                            "of its DLL made here, the other zones (bombZone_B, _C...) count too.")
        if imgui.button("Another bomb zone here (copy of bombZone)##bz"):
            def go():
                first = next((r for r in zones if str(r.object_name).rstrip("\0").lower() == "bombzone"), None)
                if first is None:
                    raise ValueError("there is no bomb zone called 'bombZone' to copy")
                import struct as _s

                def site(r):
                    n = _s.unpack_from("<I", r.parsed.tail, 0)[0]
                    rad = _s.unpack_from("<f", r.parsed.tail, 4 + n + 64)[0] if len(r.parsed.tail) >= 4 + n + 68 else 300.0
                    return np.asarray(r.parsed.transform, np.float64)[3, :3], rad
                order = [first] + [r for r in zones if r is not first and r.parsed is not None]
                sites = [site(r) for r in order]
                sites.append((np.asarray(self.here_point(False), np.float64), sites[0][1]))
                return st.add_bomb_sites(sites, all_sites=bool(getattr(self, "_bz_all", False)),
                                         hud=bool(getattr(self, "_bz_hud", True)),
                                         radar=bool(getattr(self, "_bz_radar", True)))
            self._try(go)
            self._bz_key = None
        _, self._bz_all = ui.checkbox("to win, blow up ALL the bomb zones before the time runs out##bz",
                                      bool(getattr(self, "_bz_all", False)))
        imgui.text_wrapped(tr("Unticked (like the game): the attackers win when any zone blows up. Ticked: a zone that "
                              "blows up does not end the round; the attackers win when the last one blows up, and if "
                              "the clock runs out first, the defenders win. A planted bomb is used up, so the scene gets "
                              "one bomb to pick up per zone (copies of the first one, at the same place)."))
        _, self._bz_hud = ui.checkbox("show the bomb zones on the HUD (icons, like mp_do_plaza)##bz",
                                      bool(getattr(self, "_bz_hud", True)))
        imgui.text_wrapped(tr("One icon per zone at the top right of the screen; it changes to the destroyed one when "
                              "its zone blows up (the icons of mp_do_plaza's objectives)."))
        _, self._bz_radar = ui.checkbox("the minimap points at the nearest bomb zone still standing##bz",
                                        bool(getattr(self, "_bz_radar", True)))
        imgui.text_wrapped(tr("The game's minimap always points at 'bombZone'. Ticked: at the zone nearest to you that "
                              "has not blown up yet, changing as you move or as zones blow up."))
        if imgui.button("Make the DLL that counts all the zones##bz"):
            self._try(st.make_bomb_zones_dll, None, bool(self._bz_all), "", bool(self._bz_hud), bool(self._bz_radar))
            self._bz_key = None
        imgui.separator()
        imgui.text_disabled("Rain / storm on this map: Gameplay > Weather (it keeps the bomb zones and the bomb time).")
        imgui.separator()
        imgui.text("The bomb")
        key = (st.scene_name, str(st.scene.main_module_name),
               tuple(str(r.module_name) for r in st.scene.modules if r.clean_name.lower() == "mp_bomba"))
        if getattr(self, "_bomb_key", None) != key:
            self._bomb_key = key
            try:
                self._bomb = st.bomb_settings()
            except Exception:
                self._bomb = {"bombs": [], "fuse": None, "overtime": False, "can_overtime": False}
            self._bomb_secs = float(self._bomb["fuse"] or 20.0)
            self._bomb_ot = bool(self._bomb["overtime"])
        bs = self._bomb
        if not bs["bombs"]:
            imgui.text_disabled("This scene has no bomb (mp_Bomba).")
            return
        imgui.text(tr("Now: it explodes {0} s after it is planted; at 0:00 {1}.")
                   .replace("{0}", f"{bs['fuse']:g}" if bs["fuse"] is not None else "?")
                   .replace("{1}", tr("the round waits for it") if bs["overtime"] else tr("the round ends")))
        _, self._bomb_secs = ui.drag_float("seconds from planting to the explosion (game: 20)##bomb", float(self._bomb_secs),
                                           1.0, 5.0, 600.0)
        if bs["can_overtime"]:
            _, self._bomb_ot = ui.checkbox("at 0:00 wait for a planted bomb: the clock shows its seconds##bomb",
                                           bool(self._bomb_ot))
        imgui.text_wrapped(tr("In the game the bomb's time is not added to the round's clock: if the clock reaches 0:00 "
                              "with the bomb planted, the round ends at once and the defenders win, even if the bomb "
                              "had a second left. With the box ticked the round goes on until the bomb explodes "
                              "(attackers win) or is defused and the clock runs out (defenders win), like in CS."))
        if imgui.button("Apply to this map##bomb"):
            self._try(st.make_bomb_dll, float(self._bomb_secs), bool(self._bomb_ot))
            self._bomb_key = None

    def _wad_list_ui(self, b) -> None:
        """The texture packs (.wad) of the importer: a list (add several at once, a whole folder, take one out), and how many
        of the map's textures each one has."""
        import os as _os
        st = self.state
        wads = [w for w in b["wads"].split(";") if w.strip()]
        imgui.text(tr("Texture packs (.wad): {0}").replace("{0}", str(len(wads))))
        need = [n.lower() for n in ((b.get("rep") or {}).get("names") or [r[0] for r in (b.get("rows") or [])])]
        key = (tuple(wads), tuple(need))
        if getattr(self, "_wad_info_key", None) != key:           # what each .wad has (read once per change)
            self._wad_info_key = key
            info = {}
            from .. import wad as _wad
            for w in wads:
                try:
                    names = set(_wad.read_wad(w))
                    info[w] = (len(names), sum(1 for n in need if n in names), "")
                except Exception as e:
                    info[w] = (0, 0, str(e))
            self._wad_info = info
            found = set()
            for w in wads:
                try:
                    found |= {n for n in need if n in set(_wad.read_wad(w))}
                except Exception:
                    pass
            self._wad_found = len(found)
        drop = None
        for k, w in enumerate(wads):
            imgui.push_id(9500 + k)
            if imgui.small_button("x"):
                drop = k
            imgui.same_line()
            n, hits, err = self._wad_info.get(w, (0, 0, ""))
            if err:
                imgui.text_colored(_V4(1.0, 0.4, 0.3, 1), f"{_os.path.basename(w)}: {err}")
            else:
                imgui.text(tr("{0}: {1} textures, {2} of this map").replace("{0}", _os.path.basename(w))
                           .replace("{1}", str(n)).replace("{2}", str(hits)))
            imgui.pop_id()
        if drop is not None:
            del wads[drop]
            b["wads"] = ";".join(wads)
        if need and wads:
            imgui.text_disabled(tr("{0} of the {1} textures of the map are in these packs")
                                .replace("{0}", str(self._wad_found)).replace("{1}", str(len(need))))
        add = []
        if imgui.button("Add .wad (several at once)...##bsp"):
            from .editor import pick_files
            add = pick_files("Half-Life texture packs", [("WAD", "*.wad"), (tr("All files"), "*.*")])
        imgui.same_line()
        if imgui.button("Add every .wad of a folder...##bsp"):
            from .editor import pick_folder
            d = pick_folder("Folder with .wad files (e.g. cstrike or valve)")
            if d:
                try:
                    add = sorted(_os.path.join(d, f) for f in _os.listdir(d) if f.lower().endswith(".wad"))
                except OSError:
                    add = []
        if wads:
            imgui.same_line()
            if imgui.button("Clear##bspwads"):
                wads = []
                b["wads"] = ""
        if add:
            low = {w.lower() for w in wads}
            wads += [w for w in add if w.lower() not in low]
            b["wads"] = ";".join(wads)
        if b["wads"] != b.get("_saved_wads"):                 # remembered for the next time (both panels)
            b["_saved_wads"] = b["wads"]
            try:
                from .. import settings as _settings
                if _settings.get("cs_wads", "") != b["wads"]:
                    _settings.set("cs_wads", b["wads"])
            except Exception:
                pass
        imgui.text_disabled("When two packs have a texture with the same name, the first one in the list is used.")

    def sec_shapes(self) -> None:
        from .. import shapes
        st = self.state
        if not self._header("Shapes (box, cylinder, ramp, stairs ... or by points)", False):
            return
        p = self.shp
        ch, i = ui.combo("shape##shp", p["kind"], [tr(n) for _k, n in self.SHAPE_LIST])
        if ch and i != p["kind"]:
            p["kind"] = i
            k = self.SHAPE_LIST[i][0]
            if k in shapes.DEFAULT_SIZE:
                p["size"] = list(shapes.DEFAULT_SIZE[k])
        kind = self.SHAPE_LIST[p["kind"]][0]
        by_points = kind in shapes.POINT_KINDS
        if by_points:
            imgui.text_wrapped(tr("Uses the points of Measure (tool 7): {0} marked.").replace("{0}", str(len(self.meas))))
            if imgui.button("Measure tool (7)##shp"):
                self.tool = "measure"
            imgui.same_line()
            if imgui.button("Clear points##shp"):
                self.meas = []
            _, p["height"] = ui.drag_float("height##shp", p["height"], 2.0, 1.0, 20000.0)
            if kind == "circle":
                _, p["sides"] = ui.drag_float("sides (more = rounder)##shp", float(p["sides"]), 1.0, 3.0, 96.0)
        else:
            _, p["size"] = ui.drag_float3("width / height / depth##shp", p["size"], 2.0)
            _, p["yaw"] = ui.drag_float("turn (degrees)##shp", p["yaw"], 1.0, -360.0, 360.0)
            if kind in ("cylinder", "cone", "disc"):
                _, p["sides"] = ui.drag_float("sides (more = rounder)##shp", float(p["sides"]), 1.0, 3.0, 96.0)
            if kind == "stairs":
                _, p["steps"] = ui.drag_float("steps##shp", float(p["steps"]), 1.0, 1.0, 64.0)
            if imgui.button("Put it where the view looks##shp") or self.shape_at is None:
                self.shape_at = np.asarray(self.here_point(False), np.float64)
            imgui.same_line()
            _, self.shape_at = ui.drag_float3("place (bottom centre)##shp", self.shape_at, 2.0)
        _, p["tex"] = ui.input_text("texture (fill)##shp", p["tex"])
        ft = getattr(self, "fill_tex", "")
        if ft and imgui.button("Use the Fill texture##shp"):
            p["tex"] = ft
        _, p["tile"] = ui.drag_float("texture repeats every##shp", p["tile"], 4.0, 8.0, 4096.0)
        _, p["col"] = ui.checkbox("solid (with collision)##shp", p["col"])
        _, p["preview"] = ui.checkbox("preview in the view (yellow lines)##shp", p["preview"])
        args = dict(kind=kind, size=[max(1.0, float(v)) for v in p["size"]], at=self.shape_at, yaw=float(p["yaw"]),
                    sides=int(p["sides"]), steps=int(p["steps"]), points=[q.copy() for q in self.meas] if by_points else None,
                    height=float(p["height"]))
        key = repr((args["kind"], args["size"], None if args["at"] is None else np.round(args["at"], 1).tolist(), args["yaw"],
                    args["sides"], args["steps"], [np.round(q, 1).tolist() for q in (args["points"] or [])], args["height"]))
        if key != self._shape_key:
            self._shape_key = key
            try:
                fs = st.shape_faces(**args)
                self._shape_edges = shapes.edges(fs)
                self._shape_err = ""
            except Exception as e:
                self._shape_edges, self._shape_err = None, str(e)
        if getattr(self, "_shape_err", ""):
            imgui.text_colored(_V4(1.0, 0.7, 0.3, 1), tr(self._shape_err))
        if imgui.button("Create##shp") and self._shape_edges is not None:
            self._try(st.add_shape, args["kind"], args["size"], args["at"], args["yaw"], p["tex"].strip(), p["tile"], p["col"],
                      args["sides"], args["steps"], args["points"], args["height"])
            self._col_key = None
        imgui.text_disabled("Ramp, stairs, cone and pyramid get only floor faces (you walk up them); the rest also collision "
                            "boxes. After creating it, it is selected: move / turn / scale it like any mesh, its collision "
                            "goes with it.")
