"""Panels and view interaction of the map tools (window "Map tools"): map check, floor collision view, groups, snapping,
mirror / row copies, measuring, collision editing, pieces, map plan, play in game, install / uninstall, history / compare.

Mixin of ``Editor``; the logic lives in ``state_tools.ToolOps`` (tested without a window)."""
from __future__ import annotations

import os
import time

import numpy as np
from imgui_bundle import imgui

from . import ui
from .state import Selection
from .editor_more import MorePanels
from .. import settings as _settings
from ..language import tr

F = np.array([1.0, 1.0, -1.0])          # engine <-> display (the view mirrors z)


def _V2(x, y):
    return imgui.ImVec2(x, y)


def _V4(r, g, b, a):
    return imgui.ImVec4(r, g, b, a)


def _point_name(k: int) -> str:
    """A, B ... Z, A2, B2 ..."""
    return chr(65 + k % 26) + (str(k // 26 + 1) if k >= 26 else "")


class ToolPanels(MorePanels):
    # ------------------------------------------------------------------------------ state of the tools
    def tools_init(self) -> None:
        self.more_init()
        self.show_tools = True
        self.check_res = None
        self.grp_off = [0.0, 0.0, 0.0]
        self.grp_col = True
        self.snap_grid = 0.0
        self.snap_floor = False
        self.mir_axis, self.mir_plane, self.mir_team = 0, 0.0, True
        self.arr_n, self.arr_off = 3, [200.0, 0.0, 0.0]
        self.meas = []                   # measured points (engine)
        self.rect = None                 # rectangle selection in window pixels [x0, y0, x1, y1]
        self.col_sel = -1                # selected collision box
        self.col_half = [50.0, 100.0, 50.0]
        self.floor_size = [400.0, 400.0]
        self.wall_h, self.ramp_w = 200.0, 200.0
        self.piece_name, self.piece_yaw = "", 0.0
        self.sol_shape, self.sol_dim, self.sol_yaw = 0, [600.0, 200.0, 12.0], 0.0
        self.sol_tex, self.sol_tile = "tablones.tex", 128.0
        self.plan_tex, self.plan_cam, self.plan_px = 0, None, 420
        self.game_exe = str(_settings.get("game_exe", "") or "")
        self.game_args = str(_settings.get("game_args", "") or "")
        self.hist_diff = []
        self.opts.setdefault("hm", False)
        # batch 7: collision from meshes, OBJ import, face painting, lights, sounds / particles, walking test, balance
        self.ah = dict(floors=True, walls=True, ceilings=True, merge=True, replace=True, up=False, box=False, sure=False,
                       thick=10.0, min_h=0.0, tex="barandilla", missing=True)
        self.obj_path, self.obj_meta, self.obj_scale, self.obj_yaw, self.obj_up = "", None, 100.0, 0.0, 0
        self.obj_two, self.obj_col, self.obj_box = False, True, False
        self.paint_mode, self.paint_tex, self.paint_tile, self.paint_hit = 1, "", 0.0, None
        for k in ("lit", "light_ranges", "sound_ranges", "fx", "rain", "light_boxes", "decal_boxes"):
            self.opts.setdefault(k, False)
        self.light_col, self.light_start, self.light_end = [1.0, 0.95, 0.8], 250.0, 800.0
        self.fx_preset = 0
        self.walker, self.walk_team, self.walk_idx, self.walk_log = None, 0, 0, []
        self.walk_speed, self.walk_steph, self.walk_jump = 450.0, 45.0, 420.0
        self.bal_res, self.bal_text, self.bal_cell, self.bal_speed, self.bal_routes = None, [], 0, 450.0, True

    # ------------------------------------------------------------------------------ helpers
    def here_point(self, use_measure: bool = True):
        """Engine point 'here': the last measured point (``use_measure``), else what the middle of the view looks at,
        else the camera."""
        st = self.state
        if self.meas and use_measure:
            return np.asarray(self.meas[-1], np.float64)
        try:
            cam = st.camera
            p = st.pick_point(np.asarray(cam.pos, np.float64), np.asarray(cam.front, np.float64))
            if p is not None:
                return np.asarray(p, np.float64)
        except Exception:
            pass
        return np.asarray(st.camera.pos, np.float64) * F

    def to_screen(self, pts_display):
        """Window pixels (n, 2) and a 'visible' mask of display-space points, with the camera of the view."""
        import glfw
        st = self.state
        ww, wh = glfw.get_window_size(self.win)
        cam = st.camera
        vp = cam.projection(ww / max(wh, 1), 1.0, 100000.0) @ cam.view()
        p = np.asarray(pts_display, np.float64).reshape(-1, 3)
        c = np.c_[p, np.ones(len(p))] @ vp.T
        w = c[:, 3]
        ok = w > 1e-3
        ndc = c[:, :2] / np.where(ok, w, 1.0)[:, None]
        return np.c_[(ndc[:, 0] * 0.5 + 0.5) * ww, (0.5 - ndc[:, 1] * 0.5) * wh], ok

    def go_to(self, pos_engine) -> None:
        st = self.state
        p = np.asarray(pos_engine, np.float64) * F
        st.camera.pos = p + np.array([0.0, 250.0, 500.0])
        st.camera.face(p)

    def _try(self, fn, *a, **k):
        try:
            r = fn(*a, **k)
            if isinstance(r, str):
                self.log(r)
            return r
        except Exception as e:
            self.log(f"{getattr(fn, '__name__', 'action')} failed: {e}")
            return None

    # ------------------------------------------------------------------------------ view interaction
    def tools_press(self, o, d, mx: float, my: float) -> bool:
        """Left click in the view. True = handled here (the normal tools do nothing)."""
        import glfw
        st = self.state
        if self.more_press(o, d):                     # path points / object brush
            return True
        if self.tool == "measure":
            from .tools import point_under_ray, segment_under_ray
            alt = self.key(glfw.KEY_LEFT_ALT) or self.key(glfw.KEY_RIGHT_ALT)
            k = point_under_ray(o, d, self.meas)
            if k is not None and alt:                      # Alt+click a point: take it away
                self.meas.pop(k)
                return True
            if k is not None:                              # grab a point and drag it
                self.drag = dict(tool="meas", idx=k)
                return True
            seg = segment_under_ray(o, d, self.meas)
            if seg is not None:                            # click a line: a new point there
                i, q = seg
                self.meas.insert(i + 1, np.asarray(q, np.float64))
                self.drag = dict(tool="meas", idx=i + 1)
                return True
            p = st.pick_point(o, d)
            if p is not None:                              # one more point (A, B, C ...)
                self.meas.append(np.asarray(p, np.float64))
                self.drag = dict(tool="meas", idx=len(self.meas) - 1)
            return True
        if self.tool == "collision":
            i = st.pick_collision_box(o, d)
            self.col_sel = -1 if i is None else int(i)
            return True
        if self.tool == "paint":
            hit = st.paint_pick(o, d)
            if hit is None:
                return True
            self.paint_hit = hit
            if self.key(glfw.KEY_LEFT_SHIFT) or self.key(glfw.KEY_RIGHT_SHIFT):      # eyedropper: take that texture
                self.paint_tex = str(hit["texture"]).rstrip("\0")
                self.log(f"paint texture: {self.paint_tex}")
            elif self.paint_tex.strip():
                from ..facepaint import MODES
                self._try(st.paint_faces, hit, MODES[self.paint_mode], self.paint_tex.strip(), self.paint_tile)
            else:
                self.log("choose a texture first (Shift+click a face takes its texture)")
            return True
        if self.tool == "select":
            if self.key(glfw.KEY_LEFT_CONTROL) or self.key(glfw.KEY_RIGHT_CONTROL):
                sel, _ = st.pick_hit(o, d)
                if sel is not None:
                    if st.selection is not None and not st.multi_list():
                        st.toggle_multi(st.selection)             # the object already selected joins the group
                    st.toggle_multi(sel)
                    st.selection = sel if any(s.ref is sel.ref for s in st.multi_list()) else None
                return True
            if self.key(glfw.KEY_LEFT_SHIFT) or self.key(glfw.KEY_RIGHT_SHIFT):
                self.rect = [mx, my, mx, my]
                self.drag = dict(tool="rect")
                return True
            if st.multi_list():                                   # a plain click starts a new selection
                st.multi = []
        return False

    def tools_drag(self, mx: float, my: float) -> bool:
        if self.drag is not None and self.drag.get("tool") == "rect":
            if self.rect is not None:
                self.rect[2], self.rect[3] = mx, my
            return True
        return False

    def tools_release(self) -> bool:
        if self.drag is not None and self.drag.get("tool") in ("path", "meas"):
            self.drag = None
            return True
        if self.drag is not None and self.drag.get("tool") == "rect":
            self.drag = None
            self.finish_rect()
            return True
        return False

    def finish_rect(self) -> None:
        """Everything whose position is inside the dragged rectangle joins the group (modules and props, unlocked)."""
        st = self.state
        r, self.rect = self.rect, None
        if r is None or abs(r[2] - r[0]) < 4 or abs(r[3] - r[1]) < 4:
            return
        x0, x1 = sorted((r[0], r[2])); y0, y1 = sorted((r[1], r[3]))
        cands = []
        for rec in st.scene.modules:
            try:
                cands.append((Selection("module", rec, str(rec.object_name).rstrip("\0")),
                              np.asarray(st.position_of(Selection("module", rec, "")), np.float64)))
            except Exception:
                pass
        for k, pr in enumerate(st.opt.props if st.opt is not None else []):
            cands.append((Selection("prop", pr, f"prop {k}"), np.asarray(pr.transform, np.float64)[3, :3]))
        if not cands:
            return
        scr, ok = self.to_screen(np.array([p for _, p in cands]) * F)
        n = 0
        have = {id(s.ref) for s in st.multi_list()}
        for (sel, _), (sx, sy), vis in zip(cands, scr, ok):
            if vis and x0 <= sx <= x1 and y0 <= sy <= y1 and id(sel.ref) not in have and not st.is_locked(sel.ref, sel.kind):
                st.multi_list().append(sel); n += 1
        if st.multi_list():
            st.selection = st.multi_list()[-1]
        self.log(f"{n} objects added to the group ({len(st.multi_list())} in total)")

    def tools_commit(self) -> bool:
        """Called when a move / rotate / scale drag ends. True = the move was applied here (group / snapping)."""
        st = self.state
        sel = st.selection
        if sel is None or not self.manip or not np.any(self.pend_pos):
            return False
        group = st.multi_list()
        if len(group) > 1 and any(s.ref is sel.ref for s in group):
            self._try(st.group_move, np.array(self.pend_pos, np.float64), self.grp_col)
            if self.snap_grid > 0 or self.snap_floor:
                self._try(st.snap_selection, self.snap_grid, self.snap_floor)
            return True
        if self.snap_grid > 0 or self.snap_floor:
            try:
                new = st.snap_position(sel, st.position_of(sel) + self.pend_pos, self.snap_grid, self.snap_floor)
                st.set_position(sel, new)
            except Exception as e:
                self.log(f"could not apply: {e}")
            return True
        return False

    # ------------------------------------------------------------------------------ drawing in the 3D view
    def tools_draw3d(self) -> None:
        st, o = self.state, self.opts
        try:
            self.more_draw3d()
        except Exception as e:
            print(f"map tools view: {e!r}")
        depth = not o.get("no_depth", False)
        if o.get("hm"):
            try:
                floors, walls, slopes = st.hm_wire()
                if len(floors):
                    self.gl.draw_lines(floors, (0.2, 1.0, 0.35, 1), depth)
                if len(slopes):
                    self.gl.draw_lines(slopes, (1.0, 0.9, 0.1, 1), depth)
                if len(walls):
                    self.gl.draw_lines(walls, (1.0, 0.25, 0.2, 1), depth)
            except Exception as e:
                o["hm"] = False
                self.log(f"floor collision view: {e}")
        group = st.multi_list()
        if group:
            boxes = []
            off = self.pend_pos * F if (self.manip and st.selection is not None
                                        and any(s.ref is st.selection.ref for s in group)) else np.zeros(3)
            for s in group:
                try:
                    b = st.engine_bounds(s)
                    if b is not None:
                        lo, hi = b
                        c = (lo + hi) / 2 * F
                        boxes.append((c + off, np.abs(hi - lo) + 6.0))
                    else:
                        boxes.append((np.asarray(st.position_of(s), np.float64) * F + off, np.full(3, 70.0)))
                except Exception:
                    pass
            if boxes:
                self.gl.draw_boxes(boxes, (0.2, 0.9, 1.0, 1), False)
        if self.meas:
            pts = [np.asarray(p, np.float64) * F for p in self.meas]
            self.gl.draw_boxes([(p, np.full(3, 16.0)) for p in pts], (1.0, 0.4, 1.0, 1), False)
            if len(pts) >= 2:
                self.gl.draw_lines(list(zip(pts[:-1], pts[1:])), (1.0, 0.4, 1.0, 1), False)
        try:
            self.fx_draw3d()                            # sound / light ranges, particles, rain, balance routes
        except Exception as e:
            for k in ("light_ranges", "sound_ranges", "fx", "rain"):
                o[k] = False
            self.log(f"effects preview: {e!r}")
        if self.tool == "collision" and self.col_sel >= 0:
            try:
                c, h = st.collision_box(self.col_sel)
                from .. import regioncopy, crop
                lo, hi = regioncopy._box_bounds(crop.read_block(st.opt).boxes[self.col_sel])
                self.gl.draw_boxes([((lo + hi) / 2 * F, np.abs(hi - lo) + 4.0)], (1.0, 1.0, 1.0, 1), False)
            except Exception:
                self.col_sel = -1

    def tools_overlay(self) -> None:
        """2D things over the view: the selection rectangle and the measured distance."""
        if self.rect is not None:
            dl = imgui.get_background_draw_list()
            x0, x1 = sorted((self.rect[0], self.rect[2])); y0, y1 = sorted((self.rect[1], self.rect[3]))
            dl.add_rect(_V2(x0, y0), _V2(x1, y1), imgui.get_color_u32(_V4(0.2, 0.9, 1.0, 1.0)), rounding=0.0, thickness=1.5)
        if len(self.meas) >= 2:
            try:
                pts = [np.asarray(p, np.float64) for p in self.meas]
                dl = imgui.get_background_draw_list()
                col = imgui.get_color_u32(_V4(1.0, 0.6, 1.0, 1.0))
                mids = np.array([(a + b) / 2 * F for a, b in zip(pts[:-1], pts[1:])])
                scr, ok = self.to_screen(mids)
                for k, (a, b) in enumerate(zip(pts[:-1], pts[1:])):
                    if ok[k]:
                        dl.add_text(_V2(float(scr[k][0]) + 8, float(scr[k][1]) - 8), col, f"{np.linalg.norm(b - a) / 100:.2f} m")
                names, nok = self.to_screen(np.array([p * F for p in pts]))
                for k in range(len(pts)):
                    if nok[k]:
                        dl.add_text(_V2(float(names[k][0]) - 4, float(names[k][1]) - 22), col, _point_name(k))
            except Exception:
                pass

    # ------------------------------------------------------------------------------ the window
    def win_workbench(self) -> None:
        if not hasattr(self, "check_res"):
            self.tools_init()
        try:
            self.tools_overlay()
        except Exception as e:
            self.rect = None
            print(f"tools overlay: {e!r}")
        try:
            self.palette_ui()                             # Ctrl+P: find any tool by its name
        except Exception as e:
            print(f"command search: {e!r}")
        if not self.show_tools or self.state.scene is None:
            return
        imgui.set_next_window_pos(_V2(190, 60), imgui.Cond_.first_use_ever.value)
        imgui.set_next_window_size(_V2(400, 560), imgui.Cond_.first_use_ever.value)
        exp, self.show_tools = ui.begin("Map tools", True)
        if exp:
            cats = self.tool_categories()
            cur = getattr(self, "tools_cat", 0)
            for k, (name, _fns) in enumerate(cats):          # the categories, as a row of buttons (the chosen one lit)
                if k:
                    imgui.same_line()
                    if imgui.get_content_region_avail().x < 90:
                        imgui.new_line()
                lit = k == cur
                if lit:
                    imgui.push_style_color(imgui.Col_.button.value, _V4(0.85, 0.55, 0.1, 1.0))
                if imgui.small_button(tr(name) + f"##cat{k}"):
                    self.tools_cat = cur = k
                if lit:
                    imgui.pop_style_color()
            imgui.separator()
            for k, (name, fns) in enumerate(cats):
                if cur not in (0, k) or k == 0:
                    continue
                if cur == 0:
                    imgui.text_colored(_V4(0.95, 0.7, 0.3, 1.0), tr(name))
                for fn in fns:
                    self._cat_of[fn.__name__] = k
                    try:
                        fn()
                    except Exception as e:                   # one broken panel must not take the others (or the editor) down
                        imgui.text_disabled(f"{fn.__name__}: {e}")
        imgui.end()

    def tool_categories(self) -> list:
        """The Map tools in groups, so they are easy to find.  0 = all of them."""
        self.__dict__.setdefault("_cat_of", {})
        return [
            ("All", ()),
            ("Build", (self.sec_cscreate, self.sec_blank, self.sec_shapes, self.sec_bsp, self.sec_solid, self.sec_path, self.sec_measure, self.sec_group, self.sec_arrange,
                       self.sec_brush, self.sec_obj, self.sec_meshlib, self.sec_pieces)),
            ("Collision", (self.sec_collision, self.sec_autohm, self.sec_clean, self.sec_gaps)),
            ("Look", (self.sec_paint, self.sec_textures, self.sec_shading, self.sec_lightview, self.sec_weather, self.sec_fx,
                      self.sec_keys)),
            ("Gameplay", (self.sec_layout, self.sec_bombs, self.sec_climate, self.sec_spawns, self.sec_falls, self.sec_sim, self.sec_walk, self.sec_balance)),
            ("Check", (self.sec_check, self.sec_load, self.sec_sectors, self.sec_changes, self.sec_plan)),
            ("Game & files", (self.sec_play, self.sec_install, self.sec_history, self.sec_shortcuts)),
        ]

    # ---- 1 + 2: map check and floor collision view
    def sec_check(self) -> None:
        st = self.state
        if not self._header("Map check", True):
            return
        if imgui.button("Check the map"):
            self.check_res = self._try(st.validate_map) or []
        imgui.same_line()
        _, self.opts["hm"] = ui.checkbox("Show floor collision (.hm)", bool(self.opts.get("hm")))
        if self.opts.get("hm"):
            imgui.text_colored(_V4(0.2, 1.0, 0.35, 1), tr("green = floor"))
            imgui.same_line()
            imgui.text_colored(_V4(1.0, 0.9, 0.1, 1), tr("yellow = ramp"))
            imgui.same_line()
            imgui.text_colored(_V4(1.0, 0.3, 0.25, 1), tr("red = wall"))
        if self.check_res is None:
            imgui.text_disabled("Finds what crashes the game or breaks play before you test it.")
            return
        ne = sum(1 for r in self.check_res if r["level"] == "error")
        nw = sum(1 for r in self.check_res if r["level"] == "warning")
        imgui.text(f"{ne} errors, {nw} warnings")
        imgui.begin_child("##check", _V2(0, 150))
        for k, r in enumerate(self.check_res[:200]):
            col = {"error": _V4(1.0, 0.35, 0.3, 1), "warning": _V4(1.0, 0.8, 0.2, 1)}.get(r["level"], _V4(0.4, 1.0, 0.5, 1))
            if r["pos"] is not None:
                imgui.push_id(f"chk{k}")
                if imgui.small_button("Go to"):
                    self.go_to(r["pos"])
                imgui.pop_id()
                imgui.same_line()
            imgui.push_style_color(imgui.Col_.text.value, col)
            imgui.text_wrapped(r["msg"])
            imgui.pop_style_color()
        imgui.end_child()

    # ---- 4 + 5 + 6: group, snapping, mirror / row copies
    def sec_group(self) -> None:
        st = self.state
        if not self._header("Group / snap / copies", False):
            return
        ch, v = ui.checkbox("Collision goes with meshes / props (move, turn, scale, copy, delete)", st.carry_on())
        if ch:
            st.set_carry(v)
        imgui.text_disabled("The collision boxes and the .hm floor / wall faces inside the object go with it.")
        g = st.multi_list()
        imgui.text(f"{len(g)} objects in the group")
        imgui.text_disabled("Select tool: Ctrl+click adds / removes, Shift+drag = rectangle. Moving one moves all.")
        if imgui.button("Clear group"):
            st.multi = []
        imgui.same_line()
        if imgui.button("Lock##grp"):
            self._try(st.group_lock, True)
        imgui.same_line()
        if imgui.button("Unlock##grp"):
            self._try(st.group_lock, False)
        imgui.same_line()
        if imgui.button("Delete##grp"):
            self._try(st.group_delete)
        _, self.grp_off = ui.drag_float3("offset##grp", self.grp_off, 5.0)
        _, self.grp_col = ui.checkbox("move their collision too", self.grp_col)
        if imgui.button("Move group by offset"):
            self._try(st.group_move, self.grp_off, self.grp_col)
        imgui.separator()
        _, self.snap_grid = ui.drag_float("grid step (0 = off)", self.snap_grid, 5.0, 0.0, 1000.0)
        _, self.snap_floor = ui.checkbox("stand on the floor (.hm) when moved", self.snap_floor)
        if imgui.button("Snap selection now"):
            self._try(st.snap_selection, self.snap_grid, True)
        imgui.separator()
        ch, i = ui.combo("mirror axis", self.mir_axis, ["X  (left / right)", "Z  (front / back)"])
        if ch:
            self.mir_axis = i
        _, self.mir_plane = ui.drag_float("mirror plane at", self.mir_plane, 10.0)
        _, self.mir_team = ui.checkbox("copies go to the other team", self.mir_team)
        if imgui.button("Mirror copy"):
            self._try(st.mirror_copy, "xz"[self.mir_axis], self.mir_plane, self.mir_team)
        _, n = ui.drag_float("copies", float(self.arr_n), 0.2, 1.0, 50.0)
        self.arr_n = int(max(1, round(n)))
        _, self.arr_off = ui.drag_float3("step##arr", self.arr_off, 5.0)
        if imgui.button("Row of copies"):
            self._try(st.array_copy, self.arr_n, self.arr_off)

    # ---- 7: measuring
    def sec_measure(self) -> None:
        if not self._header("Measure", False):
            return
        if imgui.button("Measure tool (7)"):
            self.tool = "measure"
        imgui.same_line()
        if imgui.button("Clear##meas"):
            self.meas = []
        imgui.text_disabled("Click points in the view: A, B, C ... as many as you want. Click a point to drag it, click a line "
                            "to add a point in the middle, Alt+click a point to remove it. You can also type them "
                            "(double-click a field to write a number). The tools that use A-B take the first two.")
        self.meas_fields("meas", True)
        if len(self.meas) >= 2:
            pts = [np.asarray(p, np.float64) for p in self.meas]
            for k, (a, b) in enumerate(zip(pts[:-1], pts[1:])):
                d = b - a
                flat = float(np.hypot(d[0], d[2]))
                imgui.text(f"{_point_name(k)}-{_point_name(k + 1)}:  {np.linalg.norm(d) / 100:.2f} m   "
                           + tr("on the ground {0} m   height {1} m").replace("{0}", f"{flat / 100:.2f}").replace("{1}", f"{d[1] / 100:+.2f}"))
            if len(pts) > 2:
                tot = sum(float(np.linalg.norm(b - a)) for a, b in zip(pts[:-1], pts[1:]))
                last = float(np.linalg.norm(pts[-1] - pts[0]))
                imgui.text(tr("total {0} m   from {1} to {2} straight: {3} m").replace("{0}", f"{tot / 100:.2f}")
                           .replace("{1}", _point_name(0)).replace("{2}", _point_name(len(pts) - 1)).replace("{3}", f"{last / 100:.2f}"))
                lo, hi = np.min(pts, 0), np.max(pts, 0)
                imgui.text(tr("they take up {0} x {1} m, {2} m high").replace("{0}", f"{(hi[0] - lo[0]) / 100:.2f}")
                           .replace("{1}", f"{(hi[2] - lo[2]) / 100:.2f}").replace("{2}", f"{(hi[1] - lo[1]) / 100:.2f}"))
            else:
                d = pts[1] - pts[0]
                imgui.text(f"dx {d[0]:.0f}   dy {d[1]:.0f}   dz {d[2]:.0f}")
            if imgui.button("Use them as the points of the path"):
                self.path_pts = [p.copy() for p in pts]
                self.log(tr("{0} points copied to 'Path of several points'").replace("{0}", str(len(pts))))

    def solid_editor(self) -> None:
        """The selected solid made here: change its place, turn and size; its collision changes with it."""
        st = self.state
        sel = st.selection
        info = st.solid_of(sel) if sel is not None and sel.kind == "mesh" else None
        if info is None:
            if sel is not None and sel.kind == "mesh":
                imgui.text_disabled("The selected mesh was not made here (or was moved with the Move tool): "
                                    "its collision does not follow changes.")
            return
        imgui.separator()
        imgui.text_colored(_V4(0.4, 1.0, 0.5, 1), tr("Selected solid: change it and its collision changes with it"))
        key = id(sel.ref)
        if getattr(self, "_sol_edit_key", None) != key:
            self._sol_edit_key = key
            self._sol_edit = dict(info)
        e = self._sol_edit
        _, e["at"] = ui.drag_float3("position (bottom centre)##soled", e["at"], 2.0)
        _, e["yaw"] = ui.drag_float("turn (degrees)##soled", float(e["yaw"]), 1.0, -360.0, 360.0)
        _, e["length"] = ui.drag_float("length##soled", float(e["length"]), 2.0, 1.0, 50000.0)
        _, e["width"] = ui.drag_float("width##soled", float(e["width"]), 1.0, 1.0, 50000.0)
        _, e["height"] = ui.drag_float("height##soled", float(e["height"]), 1.0, 1.0, 50000.0)
        _, e["texture"] = ui.input_text("texture##soled", str(e["texture"]))
        changed = any(not np.allclose(np.asarray(e[k], np.float64), np.asarray(info[k], np.float64))
                      for k in ("at", "yaw", "length", "width", "height")) or e["texture"].strip() != info["texture"]
        if imgui.button("Apply (mesh + collision)##soled") and changed:
            r = self._try(st.edit_solid, sel, at=e["at"], yaw=e["yaw"], length=e["length"], width=e["width"],
                          height=e["height"], texture=e["texture"].strip())
            self._sol_edit_key = None
            self._col_key = None
        imgui.same_line()
        if imgui.button("Undo my changes##soled"):
            self._sol_edit = dict(info)
        if changed:
            imgui.text_colored(_V4(1.0, 0.8, 0.2, 1), tr("not applied yet"))
        imgui.text_disabled("Use these fields, not the Move / Rotate / Scale tools: those move only what you see.")

    def meas_fields(self, tag: str, many: bool = False) -> None:
        """The measured points as X / Y / Z fields: drag them, or double-click (Ctrl+click) one to type a number.
        A point not chosen yet gets a button that puts it where the view looks, to edit from there.  ``many``: every point
        (A, B, C ...) with a button to remove it and one to add the next; otherwise only A and B."""
        if many:
            for k in range(len(self.meas)):
                imgui.push_id(f"{tag}p{k}")
                if imgui.small_button("x"):
                    self.meas.pop(k)
                    imgui.pop_id()
                    return
                imgui.same_line()
                ch, v = ui.drag_float3(_point_name(k), self.meas[k], 1.0)
                if ch:
                    self.meas[k] = np.asarray(v, np.float64)
                imgui.pop_id()
            if imgui.button(tr("Write {0}").replace("{0}", _point_name(len(self.meas))) + f"##{tag}next"):
                self.meas.append(np.round(np.asarray(self.here_point(False), np.float64)))
            imgui.text_disabled("Write = a point where the view looks, to correct from there.")
            return
        for k in range(2):
            name = "AB"[k]
            if k < len(self.meas):
                ch, v = ui.drag_float3(f"{name}##{tag}{k}", self.meas[k], 1.0)
                if ch:
                    self.meas[k] = np.asarray(v, np.float64)
            else:
                imgui.text_colored(_V4(1.0, 0.7, 0.3, 1), tr(f"{name}: not chosen"))
                if k == len(self.meas):
                    imgui.same_line()
                    if imgui.button(f"Write {name}##{tag}"):
                        p = np.asarray(self.here_point(False), np.float64)
                        self.meas.append(np.round(p))

    # ---- solids: mesh + collision in one go
    def sec_solid(self) -> None:
        from .. import solids
        st = self.state
        if not self._header("Create solid (with collision)", False):
            return
        labels = ["Plank (walk on it)", "Block (crate, pillar)", "Wall", "Ramp", "Handrail", "Ship railing (bars + wooden rail)"]
        ch, i = ui.combo("shape", min(self.sol_shape, len(labels) - 1), labels)
        if ch and i != self.sol_shape:
            self.sol_shape = i
            self.sol_dim = list(solids.DEFAULTS[solids.SHAPES[i]])
        shape = solids.SHAPES[self.sol_shape]
        _, L = ui.drag_float("length", self.sol_dim[0], 5.0, 1.0, 50000.0)
        _, W = ui.drag_float("width", self.sol_dim[1], 2.0, 1.0, 50000.0)
        _, H = ui.drag_float("height", self.sol_dim[2], 2.0, 1.0, 50000.0)
        self.sol_dim = [max(L, 1.0), max(W, 1.0), max(H, 1.0)]
        _, self.sol_yaw = ui.drag_float("turn (degrees)##sol", self.sol_yaw, 5.0, -180.0, 180.0)
        _, self.sol_tex = ui.input_text("texture##sol", self.sol_tex)
        ft = getattr(self, "fill_tex", "")
        if ft and imgui.button("Use the Fill texture"):
            self.sol_tex = ft
        _, self.sol_tile = ui.drag_float("texture repeats every", self.sol_tile, 4.0, 8.0, 4096.0)
        if imgui.button("Create here"):
            self._try(st.add_solid, shape, self.here_point(), self.sol_dim[0], self.sol_dim[1], self.sol_dim[2], self.sol_yaw,
                      self.sol_tex.strip(), self.sol_tile)
            self._col_key = None
        imgui.same_line()
        if imgui.button("Create between A-B"):
            if len(self.meas) >= 2:
                self._try(st.add_solid_between, shape, self.meas[0], self.meas[1], self.sol_dim[1], self.sol_dim[2],
                          self.sol_tex.strip(), self.sol_tile)
                self._col_key = None
            else:
                self.tool = "measure"
                self.log("first choose the points A and B: click them in the view (Measure tool on), or use 'A = here' / 'B = here'")
        imgui.text_disabled("A-B = two points: its length and direction come from them (a ramp also its height).")
        pts = getattr(self, "path_pts", [])
        if imgui.button("Create along the path points (A, B, C ...)"):
            if len(pts) >= 2:
                closed = bool(getattr(self, "path", {}).get("closed"))
                if self.sol_tex.strip():
                    self._try(st.add_solid_path, shape, pts, self.sol_dim[1], self.sol_dim[2], self.sol_tex.strip(),
                              self.sol_tile, closed)
                else:
                    self._try(st.add_collision_path, pts, self.sol_dim[1], self.sol_dim[2], closed)
                self._col_key = None
            else:
                self.log("first mark the points in 'Path of several points' (two or more)")
        imgui.same_line()
        imgui.text_disabled(tr("{0} points").replace("{0}", str(len(pts))))
        imgui.text_disabled("Empty texture = only collision (invisible).")
        # choosing A and B right here
        self.meas_fields("sol")
        if imgui.button("Click A and B in the view##sol"):
            self.tool = "measure"
            self.meas = []
            self.log("click point A in the view, then point B (tool 7: Measure)")
        imgui.same_line()
        if imgui.button("A = here##sol"):
            self.meas = [np.asarray(self.here_point(False), np.float64)] + list(self.meas[1:2])
        imgui.same_line()
        if imgui.button("B = here##sol"):
            b = np.asarray(self.here_point(False), np.float64)
            self.meas = (self.meas[:1] or [b]) + [b]
        imgui.same_line()
        if imgui.button("Clear##solmeas"):
            self.meas = []
        if self.tool == "measure":
            imgui.text_disabled("Measure tool on: each click in the view puts A, then B (a third click starts again).")
        if len(self.meas) >= 2:
            d = self.meas[1] - self.meas[0]
            imgui.text_disabled(f"A-B: {np.hypot(d[0], d[2]):.0f} long on the ground, {d[1]:+.0f} high")
        self.solid_editor()
        if st.selection is not None and st.selection.kind in ("mesh", "prop"):
            if imgui.button("Delete selection with all its collision"):
                self._try(st.delete_with_collision, st.selection)
                self._col_key = None

    # ---- 8: collision editing
    def sec_collision(self) -> None:
        st = self.state
        if not self._header("Collision editing", False):
            return
        if imgui.button("Collision tool (8)"):
            self.tool = "collision"
            self.opts["collision"] = True
        imgui.text_disabled("Click a collision box in the view to edit it.")
        if self.col_sel >= 0:
            try:
                c, h = st.collision_box(self.col_sel)
                imgui.text(f"box {self.col_sel}")
                ch1, c2 = ui.drag_float3("centre##cb", c, 2.0)
                ch2, h2 = ui.drag_float3("half size##cb", h, 1.0)
                yaw = st.collision_box_yaw(self.col_sel)
                ch3, y2 = ui.drag_float("turn (degrees)##cb", yaw, 1.0, -360.0, 360.0)
                if ch1 or ch2 or ch3:
                    st.set_collision_box(self.col_sel, c2, h2, y2 if ch3 else None)
                    self._col_key = None
                if imgui.button("Delete box"):
                    self._try(st.delete_collision_box, self.col_sel)
                    self.col_sel = -1
                    self._col_key = None
            except Exception:
                self.col_sel = -1
        imgui.separator()
        _, self.col_half = ui.drag_float3("half size##newcb", self.col_half, 1.0)
        if imgui.button("Add box here"):
            p = self.here_point()
            i = self._try(st.add_collision_box, p + [0.0, self.col_half[1], 0.0], self.col_half)
            if i is not None:
                self.col_sel = int(i)
            self._col_key = None
        imgui.same_line()
        if imgui.button("Box around selection") and st.selection is not None:
            b = st.engine_bounds(st.selection)
            if b is not None:
                i = self._try(st.add_collision_box, (b[0] + b[1]) / 2, np.abs(b[1] - b[0]) / 2)
                if i is not None:
                    self.col_sel = int(i)
                self._col_key = None
        imgui.separator()
        imgui.text("Floor (.hm)")
        _, fx = ui.drag_float("floor size X", self.floor_size[0], 5.0, 10.0, 20000.0)
        _, fz = ui.drag_float("floor size Z", self.floor_size[1], 5.0, 10.0, 20000.0)
        self.floor_size = [fx, fz]
        if imgui.button("Add floor here"):
            self._try(st.add_floor_quad, self.here_point(), fx, fz)
        imgui.text_disabled("Walls and ramps go between the two measured points (Measure).")
        _, self.wall_h = ui.drag_float("wall height", self.wall_h, 5.0, 10.0, 5000.0)
        _, self.ramp_w = ui.drag_float("ramp width", self.ramp_w, 5.0, 10.0, 5000.0)
        two = len(self.meas) >= 2
        if imgui.button("Invisible wall A-B") and two:
            self._try(st.add_wall, self.meas[0], self.meas[1], self.wall_h)
            self._col_key = None
        imgui.same_line()
        if imgui.button("Ramp A-B") and two:
            a, b = sorted(self.meas[:2], key=lambda p: p[1])
            self._try(st.add_ramp, a, b, self.ramp_w)
        if imgui.tree_node("Floor faces near here"):
            try:
                near = st.floor_faces_near(self.here_point(), 500.0)[:12]
            except Exception:
                near = []
            for k, (f, kind, c) in enumerate(near):
                imgui.push_id(f"ff{k}")
                if imgui.small_button("Delete"):
                    self._try(st.delete_floor_face, f)
                imgui.same_line()
                imgui.text(f"{kind}  y {c[1]:.0f}  ({c[0]:.0f}, {c[2]:.0f})")
                imgui.pop_id()
            if not near:
                imgui.text_disabled("(none within 5 m)")
            imgui.tree_pop()

    # ---- 10: pieces
    def sec_pieces(self) -> None:
        st = self.state
        if not self._header("Pieces (reusable groups)", False):
            return
        _, self.piece_name = ui.input_text("name##piece", self.piece_name)
        if imgui.button("Save selection as a piece") and self.piece_name.strip():
            self._try(st.save_prefab, self.piece_name.strip())
        _, self.piece_yaw = ui.drag_float("turn (degrees)", self.piece_yaw, 5.0, -180.0, 180.0)
        for name in st.prefab_names():
            imgui.push_id("pc" + name)
            if imgui.small_button("Place here"):
                self._try(st.place_prefab, name, self.here_point(), self.piece_yaw)
            imgui.same_line()
            if imgui.small_button("x"):
                self._try(st.delete_prefab, name)
            imgui.same_line()
            imgui.text(name)
            imgui.pop_id()
        imgui.text_disabled("'Here' = the last measured point, or what the middle of the view looks at.")

    # ---- 9: map plan
    def plan_update(self) -> None:
        """Top view of the playable area drawn with the renderer, kept as a texture."""
        import copy as _copy
        st, o = self.state, self.opts
        c, half = st.plan_area()
        cam = _copy.copy(st.camera)
        cam.fov = 30.0
        h = half / np.tan(np.radians(cam.fov) / 2) * 1.05
        top = np.array([c[0], c[1], -c[2]])
        cam.pos = top + np.array([0.0, h, 0.0])
        cam.yaw, cam.pitch = -90.0, -89.9
        img = self.gl.capture(cam, st.scene, st.opt, 512, cull=o["cull"], sort_mode="texture", show_decals=o["decals"],
                              gamma=o["gamma"], use_scene_fog=False, show_sky=False)
        if self.plan_tex:
            self.gl.delete_later([self.plan_tex])
        self.plan_tex = self.gl.upload_rgba(img)
        self.plan_cam = cam

    def plan_project(self, pos_engine):
        cam = self.plan_cam
        vp = cam.projection(1.0, 1.0, 400000.0) @ cam.view()
        p = np.asarray(pos_engine, np.float64).reshape(-1, 3) * F
        c = np.c_[p, np.ones(len(p))] @ vp.T
        ndc = c[:, :2] / np.maximum(c[:, 3:4], 1e-6)
        return np.c_[ndc[:, 0] * 0.5 + 0.5, 0.5 - ndc[:, 1] * 0.5]

    def sec_plan(self) -> None:
        st = self.state
        if not self._header("Map plan (top view)", False):
            return
        if imgui.button("Update plan"):
            self._try(self.plan_update)
        imgui.same_line()
        imgui.text_colored(_V4(1.0, 0.3, 0.3, 1), tr("team 0"))
        imgui.same_line()
        imgui.text_colored(_V4(1.0, 0.9, 0.2, 1), tr("team 1"))
        imgui.same_line()
        imgui.text_colored(_V4(0.3, 1.0, 0.4, 1), tr("health"))
        if not self.plan_tex or self.plan_cam is None:
            imgui.text_disabled("Start points, flags and health packs seen from above. Click the plan to go there.")
            return
        size = float(self.plan_px)
        p0 = imgui.get_cursor_screen_pos()
        try:
            imgui.image(imgui.ImTextureRef(int(self.plan_tex)), _V2(size, size))
        except Exception:
            imgui.image(int(self.plan_tex), _V2(size, size))
        hovered = imgui.is_item_hovered()
        dl = imgui.get_window_draw_list()
        items = st.plan_items()
        if items:
            uv = self.plan_project(np.array([p for *_, p in items]))
            for (kind, team, name, _), (u, v) in zip(items, uv):
                if not (0 <= u <= 1 and 0 <= v <= 1):
                    continue
                x, y = p0.x + u * size, p0.y + v * size
                col = _V4(0.3, 1.0, 0.4, 1) if kind == "mp_salud" else (_V4(0.8, 0.5, 1.0, 1) if kind == "mp_camerastartposition"
                                                                        else (_V4(1.0, 0.3, 0.3, 1) if team == 0 else _V4(1.0, 0.9, 0.2, 1)))
                c32 = imgui.get_color_u32(col)
                if kind == "mp_flag":
                    dl.add_rect_filled(_V2(x - 5, y - 5), _V2(x + 5, y + 5), c32)
                    dl.add_rect(_V2(x - 6, y - 6), _V2(x + 6, y + 6), imgui.get_color_u32(_V4(0, 0, 0, 1)), rounding=0.0, thickness=1.0)
                else:
                    dl.add_circle_filled(_V2(x, y), 4.0 if kind == "mp_cstartpoint" else 3.0, c32)
        if self.bal_res is not None and self.bal_routes:             # team balance: a typical way to the enemy flag
            for team, rep in self.bal_res["teams"].items():
                if rep.path is None or len(rep.path) < 2:
                    continue
                uv = self.plan_project(rep.path)
                c32 = imgui.get_color_u32(_V4(1.0, 0.3, 0.3, 1) if team == 0 else _V4(1.0, 0.9, 0.2, 1))
                for (u0, v0), (u1, v1) in zip(uv[:-1], uv[1:]):
                    if 0 <= u0 <= 1 and 0 <= v0 <= 1 and 0 <= u1 <= 1 and 0 <= v1 <= 1:
                        dl.add_line(_V2(p0.x + u0 * size, p0.y + v0 * size), _V2(p0.x + u1 * size, p0.y + v1 * size), c32, thickness=2.0)
        if hovered and imgui.is_mouse_clicked(0):
            m = imgui.get_mouse_pos()
            u, v = (m.x - p0.x) / size, (m.y - p0.y) / size
            c, half = st.plan_area()
            self.go_to([c[0] + (u - 0.5) * 2 * half, c[1], c[2] - (v - 0.5) * 2 * half])
        imgui.text_disabled("squares = flags, big dots = start points, small green = health")

    # ---- 3: play in game
    def play_in_game(self) -> None:
        st = self.state
        if not self.save_scene_checked():
            return
        st.repack(self.vpk_out)
        self.log(st.launch_game(self.game_exe, self.game_args))

    def sec_play(self) -> None:
        st = self.state
        if not self._header("Play in the game", False):
            return
        ch, v = ui.input_text("game .exe", self.game_exe)
        if ch:
            self.game_exe = v.strip().strip('"')
            _settings.set("game_exe", self.game_exe)
        if imgui.button("Browse...##exe"):
            from .editor import pick_file
            p = pick_file("Game .exe", [("Programs", "*.exe"), (tr("All files"), "*.*")])
            if p:
                self.game_exe = p
                _settings.set("game_exe", p)
        if not self.game_exe:
            for e in st.game_exes()[:6]:
                if imgui.small_button(os.path.basename(e)):
                    self.game_exe = e
                    _settings.set("game_exe", e)
        ch, v = ui.input_text("arguments (optional)", self.game_args)
        if ch:
            self.game_args = v
            _settings.set("game_args", v)
        if imgui.button("Save, pack the VPK and play"):
            self._try(self.play_in_game)
        imgui.text_disabled("Saves the map, rebuilds demo.vpk and starts the game. Choose your map in the game's menu.")

    # ---- 11: install / uninstall
    def sec_install(self) -> None:
        st = self.state
        if not self._header("Install / share maps", False):
            return
        if imgui.button("Export this map as .zip"):
            self.export_path = os.path.join(st.export_dir(), st.map_stem() + ".zip")
            self.pending_popup = "export"
        imgui.same_line()
        if imgui.button("Install a map from .zip..."):
            from .editor import pick_file
            p = pick_file("Map zip", [("Zip", "*.zip"), (tr("All files"), "*.*")])
            if p:
                self._try(st.install_map_zip, p)
        imgui.text_disabled("Installing never replaces a file the game already has. Then 'Repackage VPK'.")
        for name in st.installed_maps():
            imgui.push_id("inst" + name)
            if imgui.small_button("Uninstall"):
                self._try(st.uninstall_map, name)
            imgui.same_line()
            imgui.text(name)
            imgui.pop_id()
        if imgui.button("Repackage VPK##inst"):
            self._try(st.repack, self.vpk_out)

    # ---- 12 + 13: history and comparison
    def sec_history(self) -> None:
        st = self.state
        if not self._header("History (last 10 saves)", False):
            return
        try:
            hist = st.history()
        except Exception:
            hist = []
        if not hist:
            imgui.text_disabled("Every save keeps a copy here; the last 10 can be brought back.")
        for stamp, e in hist:
            imgui.push_id("h" + stamp)
            if imgui.small_button("Restore"):
                if self._try(st.restore_history, stamp):
                    self.sel_scene = st.scene_name
                    self.rebake()
            imgui.same_line()
            if imgui.small_button("Compare"):
                self.hist_diff = self._try(st.compare_versions, stamp) or []
            imgui.same_line()
            imgui.text(f"{e.get('time', stamp)}  {e.get('note', '')}")
            imgui.pop_id()
        if self.hist_diff:
            imgui.text("Changes from that version to the files saved now:")
            imgui.begin_child("##diff", _V2(0, 140))
            for line in self.hist_diff[:300]:
                imgui.text_wrapped(line)
            imgui.end_child()

    # =============================================================================== batch 7
    # ---- drawing: ranges, particles, rain, routes
    def fx_draw3d(self) -> None:
        from .. import particles
        st, o = self.state, self.opts
        cam = np.asarray(st.camera.pos, np.float64)
        sel = st.selection.ref if st.selection is not None else None
        # sounds: how far each one is heard (max) and where it starts to fade (min)
        for r in st.sound_sources():
            if not (o.get("sound_ranges") or r is sel) or st.is_hidden(r):
                continue
            p = np.asarray(r.parsed.position, np.float64) * F
            if o.get("sound_ranges") and r is not sel and np.linalg.norm(p - cam) > 2.0 * float(r.parsed.max_distance) + 3000.0:
                continue
            bright = r is sel
            self.gl.draw_lines(particles.sphere_circles(p, float(r.parsed.max_distance)), (0.2, 0.9, 1.0, 1.0) if bright else (0.1, 0.55, 0.7, 1.0), not bright)
            if r.parsed.min_distance > 0:
                self.gl.draw_lines(particles.sphere_circles(p, float(r.parsed.min_distance), 24), (1.0, 1.0, 1.0, 1.0), not bright)
        # lights: full brightness up to 'start', dark at 'end'
        if o.get("light_ranges") and st.opt is not None:
            pts = [l for l in st.opt.lights if int(l.type) == 0]
            pts.sort(key=lambda l: float(((np.asarray(l.position, np.float64) * F - cam) ** 2).sum()))
            for l in pts[:40]:
                p = np.asarray(l.position, np.float64) * F
                c = [min(1.0, max(0.25, float(v))) for v in l.diffuse[:3]]
                self.gl.draw_boxes([(p, np.full(3, 24.0))], (c[0], c[1], c[2], 1.0), False)
                if l.end > 0:
                    self.gl.draw_lines(particles.sphere_circles(p, float(l.end)), (c[0], c[1], c[2], 1.0), True)
                if l.start > 0:
                    self.gl.draw_lines(particles.sphere_circles(p, float(l.start), 24), (1.0, 1.0, 1.0, 1.0), True)
        # the selected light (or the one seen alone): where it shines
        if st.opt is not None and o.get("light_gizmo", True):
            shown = []
            if st.selection is not None and st.selection.kind == "light":
                shown.append(st.selection.ref)
            solo = getattr(st, "light_solo", None)
            if solo is not None and all(x is not solo for x in shown):
                shown.append(solo)
            around = cam + np.asarray(st.camera.front, np.float64) * 1500.0
            for l in shown:
                if not any(x is l for x in st.opt.lights):
                    continue
                c = [min(1.0, max(0.3, float(v))) for v in l.diffuse[:3]]
                seg = st.light_gizmo(l, around)
                if len(seg):
                    self.gl.draw_lines(seg, (c[0], c[1], c[2], 1.0), False)
        # balance routes
        if self.bal_res is not None and self.bal_routes:
            for team, rep in self.bal_res["teams"].items():
                if rep.path is not None and len(rep.path) > 1:
                    q = (rep.path + [0.0, 40.0, 0.0]) * F
                    self.gl.draw_lines(np.stack([q[:-1], q[1:]], 1), (1.0, 0.3, 0.3, 1.0) if team == 0 else (1.0, 0.9, 0.2, 1.0), False)
        # particles (the emitter that is selected is always shown)
        t = time.time() - getattr(self, "_fx_t0", 0.0)
        if not hasattr(self, "_fx_t0"):
            self._fx_t0, t = time.time(), 0.0
        view = getattr(self.gl, "_view", None)
        if view is not None:
            right, up = np.asarray(view[0, :3], np.float64), np.asarray(view[1, :3], np.float64)
            for r in st.emitters():
                if not (o.get("fx") or r is sel) or st.is_hidden(r):
                    continue
                ps = r.parsed
                if np.linalg.norm(np.asarray(ps.position, np.float64) * F - cam) > 12000.0:
                    continue
                pos, size, frac = particles.emit(ps, t)
                pos = pos * F
                for b in range(4):                           # four ages: each with its colour and transparency
                    m = (frac >= b / 4) & (frac < (b + 1) / 4)
                    if not m.any():
                        continue
                    cr, cg, cb, ca = particles.colour_at(ps, (b + 0.5) / 4)
                    tex = self.gl.faded_texture(ps.texture, ca)
                    if tex is None:
                        continue
                    v, idx = particles.billboards(pos[m], size[m], right, up)
                    self.gl.draw_billboards(tex, v, idx, (cr, cg, cb))
        if o.get("rain"):
            self.gl.draw_lines(particles.rain(cam, time.time() % 1000.0), (0.75, 0.8, 0.9, 1.0), True)

    # ---- 7: collision from meshes
    def sec_autohm(self) -> None:
        st = self.state
        if not self._header("Collision from meshes (.hm)", False):
            return
        a = self.ah
        imgui.text_wrapped("Makes the floor / wall collision of the height map from the triangles you see - the way the game's own "
                           "maps were made. For copied ships, imported models, new buildings.")
        _, a["floors"] = ui.checkbox("floors and ramps", a["floors"])
        imgui.same_line()
        _, a["walls"] = ui.checkbox("walls", a["walls"])
        imgui.same_line()
        _, a["ceilings"] = ui.checkbox("ceilings", a["ceilings"])
        _, a["merge"] = ui.checkbox("join triangle pairs into quads (fewer faces)", a["merge"])
        _, a["replace"] = ui.checkbox("replace the faces already there (no duplicates)", a["replace"])
        _, a["up"] = ui.checkbox("thin two-sided floors: always walkable from above", a["up"])
        _, a["box"] = ui.checkbox("also one collision box around each object", a["box"])
        n = len(st.collision_targets("selection"))
        imgui.text(f"{n} meshes / props selected")
        if imgui.button("Make collision for the selection") and n:
            self._try(st.auto_collision, "selection", a["floors"], a["walls"], a["ceilings"], a["merge"], a["replace"], a["up"], a["box"])
            self._col_key = None
        imgui.separator()
        _, a["sure"] = ui.checkbox("I want to rebuild the collision of the WHOLE map", a["sure"])
        if a["sure"]:
            imgui.text_colored(_V4(1.0, 0.8, 0.2, 1), tr("Every floor / wall face is made again from the meshes; faces added by hand are lost."))
            if imgui.button("Rebuild the whole height map"):
                self._try(st.auto_collision, "map", a["floors"], a["walls"], a["ceilings"], a["merge"], True, a["up"], False)
                a["sure"] = False
        imgui.text_disabled("See the result with 'Show floor collision (.hm)' above. Undo works. Saved with the map.")
        imgui.separator()
        imgui.text("Collision boxes that follow the shape of the mesh")
        imgui.text_wrapped("Instead of one box as big as the whole object: one thin box per flat side (railings, fences, signs, "
                           "even when they turn a corner or are far apart in the same mesh) and one fitted box per solid piece. "
                           "Boxes stop players and bullets.")
        _, a["thick"] = ui.drag_float("thickness of flat sides", a["thick"], 1.0, 2.0, 200.0)
        _, a["min_h"] = ui.drag_float("at least this tall (0 = as the mesh)", a["min_h"], 5.0, 0.0, 1000.0)
        if imgui.button("Boxes from the mesh shape (selection)") and n:
            self._try(st.collision_from_shape, "selection", "", False, a["thick"], a["min_h"])
            self._col_key = None
        ch, v = ui.input_text("texture contains##shape", a["tex"])
        if ch:
            a["tex"] = v.strip()
        imgui.text_disabled("e.g. barandilla: only the triangles with that texture (empty = every triangle)")
        if imgui.button("Select the ones without collision"):
            self._try(st.select_without_collision, a["tex"])
        imgui.same_line()
        _, a["missing"] = ui.checkbox("only the ones without collision", a["missing"])
        if imgui.button("Boxes from the mesh shape for all of them (whole map)"):
            self._try(st.collision_from_shape, "map", a["tex"], a["missing"], a["thick"], a["min_h"])
            self._col_key = None
        imgui.text_disabled("See the boxes with 'Show collision boxes'. Locked and hidden objects are left alone.")

    # ---- 4: OBJ import
    def sec_obj(self) -> None:
        st = self.state
        if not self._header("Import model (OBJ)", False):
            return
        ch, v = ui.input_text("file##obj", self.obj_path)
        if ch:
            self.obj_path, self.obj_meta = v.strip().strip('"'), None
        if imgui.button("Browse...##obj"):
            from .editor import pick_file
            p = pick_file("OBJ model", [("Wavefront OBJ", "*.obj"), (tr("All files"), "*.*")])
            if p:
                self.obj_path, self.obj_meta = p, None
        if self.obj_path and self.obj_meta is None and os.path.isfile(self.obj_path):
            try:
                self.obj_meta = st.obj_info(self.obj_path)
            except Exception as e:
                self.obj_meta = {"error": str(e)}
        m = self.obj_meta
        if m and "error" in m:
            imgui.text_colored(_V4(1.0, 0.4, 0.3, 1), str(m["error"]))
        elif m:
            imgui.text(f"{m['triangles']} triangles, {len(m['materials'])} materials")
            sx, sy, sz = (v * self.obj_scale / 100.0 for v in m["size"])
            if self.obj_up == 1:
                sy, sz = sz, sy
            imgui.text(f"size in the map: {sx:.1f} x {sy:.1f} x {sz:.1f} m")
            for w in m["warnings"]:
                imgui.text_colored(_V4(1.0, 0.8, 0.2, 1), str(w))
        _, self.obj_scale = ui.drag_float("scale (100 = file in metres)", self.obj_scale, 1.0, 0.01, 100000.0)
        _, self.obj_yaw = ui.drag_float("turn (degrees)##obj", self.obj_yaw, 5.0, -180.0, 180.0)
        _, self.obj_up = ui.combo("up axis", self.obj_up, ["Y up (Blender export, most files)", "Z up (3ds Max, CAD)"])
        _, self.obj_two = ui.checkbox("two-sided faces (if parts look missing)", self.obj_two)
        _, self.obj_col = ui.checkbox("make its collision (floors / walls from its triangles)", self.obj_col)
        _, self.obj_box = ui.checkbox("one collision box around it", self.obj_box)
        if imgui.button("Import here") and self.obj_path:
            self._try(st.import_obj, self.obj_path, self.here_point(), max(self.obj_scale, 0.01), self.obj_yaw,
                      "yz"[self.obj_up], self.obj_two, self.obj_col, self.obj_box)
            self._col_key = None
        imgui.same_line()
        if imgui.button("Import where it was exported from") and self.obj_path:
            self._try(st.import_obj, self.obj_path, None, max(self.obj_scale, 0.01), 0.0,
                      "yz"[self.obj_up], self.obj_two, self.obj_col, self.obj_box, True)
            self._col_key = None
        imgui.text_disabled("Its textures (PNG / JPG / BMP / TGA named in the .mtl) become new .tex files; nothing of the game is replaced.")
        imgui.text_disabled("Faces with the material 'collision' become collision boxes (as exported below).")
        imgui.separator()
        imgui.text("Export to OBJ (for Blender)")
        if not hasattr(self, "obj_out"):
            self.obj_out, self.obj_out_all, self.obj_out_col = os.path.join(st.export_dir(), "pieza.obj"), False, True
        _, self.obj_out = ui.input_text("OBJ file##objout", self.obj_out)
        _, self.obj_out_all = ui.checkbox("the whole map (otherwise the selection and group)", self.obj_out_all)
        _, self.obj_out_col = ui.checkbox("with its collision boxes (material 'collision')", self.obj_out_col)
        if imgui.button("Export OBJ"):
            self._try(st.export_obj, self.obj_out, not self.obj_out_all, self.obj_out_col)
        imgui.text_disabled("1 unit of the OBJ = 1 m. Its textures are saved as PNG next to it.")

    # ---- 3: paint faces
    def paint_textures(self, text: str) -> list:
        st = self.state
        key = (len(st.fs.index), text.lower())
        if getattr(self, "_pt_key", None) != key:
            names = sorted({os.path.basename(p) for p in st.fs.list("texs", ".tex")}, key=str.lower)
            self._pt_key = key
            self._pt_list = [n for n in names if text.lower() in n.lower()][:40]
        return self._pt_list

    def sec_paint(self) -> None:
        st = self.state
        if not self._header("Paint faces (change texture per face)", False):
            return
        on = self.tool == "paint"
        if imgui.button("Paint tool (9)"):
            self.tool = "paint"
        imgui.same_line()
        imgui.text_colored(_V4(0.3, 1.0, 0.4, 1) if on else _V4(0.6, 0.6, 0.6, 1), tr("active: click faces in the view") if on else tr("not active"))
        _, self.paint_mode = ui.combo("what to paint", self.paint_mode,
                                      ["one triangle", "the flat area around it (a wall, a floor)", "everything with that material in the mesh"])
        _, self.paint_tex = ui.input_text("texture##paint", self.paint_tex)
        ft = getattr(self, "fill_tex", "")
        if ft and imgui.button("Use the Fill texture##paint"):
            self.paint_tex = ft
        if self.paint_tex and st.fs.texture(self.paint_tex) is None:
            imgui.begin_child("##ptex", _V2(0, 110))
            for n in self.paint_textures(os.path.splitext(self.paint_tex)[0]):
                if ui.selectable(n + "##pt", False):
                    self.paint_tex = n
            imgui.end_child()
        _, self.paint_tile = ui.drag_float("re-map: texture repeats every (0 = keep)", self.paint_tile, 4.0, 0.0, 4096.0)
        h = self.paint_hit
        if h is not None:
            imgui.text(f"last face: mesh {h['mesh']}, texture {str(h['texture'])}")
        imgui.text_disabled("Shift+click a face = take its texture. Props share their mesh: all its copies change. Undo works.")

    # ---- 2: lights
    def lit_state(self):
        """The packed lights for the renderer (None = unlit), rebuilt only when the lights or the camera area change."""
        st = self.state
        if not self.opts.get("lit") or st.opt is None:
            return None
        cam = np.asarray(st.camera.pos, np.float64)
        sig = (id(st.opt), id(getattr(st, "light_solo", None)), tuple(sorted(st._hidden())), tuple(np.round(cam / 300.0).astype(int)),
               hash(tuple((int(l.type), *[round(float(v), 2) for v in l.position], *[round(float(v), 3) for v in l.direction],
                           round(float(l.start), 1), round(float(l.end), 1), *[round(float(v), 3) for v in l.diffuse[:3]])
                          for l in st.opt.lights)))
        if getattr(self, "_lit_sig", None) != sig:
            self._lit_sig = sig
            self._lit = st.packed_lights()
        return self._lit

    def sec_lightview(self) -> None:
        from ..render import lights as _lights
        st, o = self.state, self.opts
        if not self._header("Lights (lit view)", False):
            return
        n = _lights.describe(st.opt) if st.opt is not None else {}
        imgui.text(f"{n.get('point', 0)} point, {n.get('directional', 0)} directional, {n.get('spot', 0)} spot, {n.get('ambient', 0)} ambient")
        _, o["lit"] = ui.checkbox("Lit view (see the map with its lights)", bool(o.get("lit")))
        if o.get("lit") and st.opt is not None and not st.opt.lights:
            imgui.text_colored(_V4(1.0, 0.8, 0.2, 1), tr("This map has no lights: it would be black. Add an ambient light."))
        _, o["light_ranges"] = ui.checkbox("Show the reach of the point lights", bool(o.get("light_ranges")))
        _, o["light_gizmo"] = ui.checkbox("Show where the selected light shines (arrows for a sun, rays for ambient)",
                                          bool(o.get("light_gizmo", True)))
        solo = getattr(st, "light_solo", None)
        if solo is not None and st.opt is not None and any(l is solo for l in st.opt.lights):
            imgui.text_colored(_V4(1.0, 0.8, 0.2, 1), tr("The lit view shows ONE light only: what it lights."))
            if imgui.button("Light with every light again"):
                st.set_light_solo(None)
        imgui.separator()
        _, self.light_col = ui.color_edit3("colour##newlight", self.light_col)
        _, self.light_start = ui.drag_float("full brightness up to", self.light_start, 5.0, 0.0, 50000.0)
        _, self.light_end = ui.drag_float("dark from", self.light_end, 5.0, 1.0, 50000.0)
        if imgui.button("Add a point light at the camera"):
            self._try(st.light_at_camera, 0, self.light_col, self.light_start, max(self.light_end, self.light_start + 1.0))
        imgui.text_wrapped("The game lights its maps in real time with these lights (nothing is painted into the meshes), so copied "
                           "ships and new pieces are lit like the originals wherever a light reaches. Edit them in DEBUG > Lights.")
        imgui.text_disabled("The lit view shows the 32 lights nearest to the camera; the falloff is approximate. The engine has no shadows.")

    # ---- 1: sounds and particles
    def sec_fx(self) -> None:
        from ..modules import PARTICLE_PRESETS
        st, o = self.state, self.opts
        if not self._header("Sounds and particles", False):
            return
        snd, em = st.sound_sources(), st.emitters()
        imgui.text(f"{len(snd)} sounds, {len(em)} particle emitters")
        _, o["sound_ranges"] = ui.checkbox("Show the reach of every sound", bool(o.get("sound_ranges")))
        imgui.text_disabled("blue = heard up to there, white = full volume inside. A selected sound always shows its own.")
        _, o["fx"] = ui.checkbox("Preview particles (smoke, fountains, bubbles)", bool(o.get("fx")))
        _, o["rain"] = ui.checkbox("Preview rain", bool(o.get("rain")))
        names = list(PARTICLE_PRESETS)
        _, self.fx_preset = ui.combo("kind##fx", min(self.fx_preset, len(names) - 1), names)
        if imgui.button("Add particle emitter here"):
            self._try(st.add_particles, names[self.fx_preset], self.here_point())
        if imgui.tree_node("Emitters and sounds of this map"):
            for k, r in enumerate((em + snd)[:80]):
                imgui.push_id(f"fx{k}")
                if imgui.small_button("Go to"):
                    self.go_to(r.parsed.position)
                    st.selection = Selection("module", r, str(r.object_name).rstrip("\0"))
                imgui.pop_id()
                imgui.same_line()
                p = r.parsed
                if hasattr(p, "max_distance"):
                    self.sound_row(str(p.wav), f"l{k}")
                    imgui.same_line()
                    imgui.text(f"{str(r.object_name)[:22]}  {p.min_distance:.0f}-{p.max_distance:.0f}")
                else:
                    imgui.text(f"{str(r.object_name)[:22]}  {str(p.texture)[:22]}  {p.rate:.0f}/s  {p.life:.1f} s")
            imgui.tree_pop()
        _, self.snd_loop = ui.checkbox("loop the sound being played##fx", bool(getattr(self, "snd_loop", False)))
        if getattr(self, "snd_msg", ""):
            imgui.text_wrapped(self.snd_msg)
        imgui.text_disabled("Edit their numbers in DEBUG > Modules (speed, spread, life, colours, size). The preview is approximate.")

    # ---- 5: walking test
    def start_walk(self, at=None) -> None:
        st = self.state
        w = st.start_walk(at)
        w.speed, w.step, w.jump_speed = self.walk_speed, self.walk_steph, self.walk_jump
        self.walker = w
        self.walk_log = []
        cam = st.camera
        cam.pos = w.eye_pos * F
        cam.pitch = 0.0
        if not w.on_ground:
            self.log("walk test: there is no floor under that point - it will fall")
        self.log("walk test: WASD walk, Space jump, Shift run, right mouse button look, Esc stop")

    def stop_walk(self) -> None:
        self.walker = None

    def walk_step(self, dt: float, fwd: float, right: float) -> None:
        """Called by the editor instead of the free camera while the walking test runs."""
        import glfw
        w, cam = self.walker, self.state.camera
        if w is None:
            return
        if self.key(glfw.KEY_ESCAPE):
            self.stop_walk()
            return
        f = np.asarray(cam.front, np.float64)
        fx, fz = f[0], f[2]
        n = float(np.hypot(fx, fz)) or 1.0
        fx, fz = fx / n, fz / n
        # display -> engine: z is mirrored; right = front x up
        mx = fwd * fx + right * (-fz)
        mz = fwd * (-fz) + right * (-fx)
        w.speed, w.step, w.jump_speed = self.walk_speed, self.walk_steph, self.walk_jump
        fell = w.fell
        w.update(dt, mx, mz, jump=self.key(glfw.KEY_SPACE), run=self.key(glfw.KEY_LEFT_SHIFT))
        if w.fell != fell:
            p = w.pos
            self.walk_log.append(np.asarray(p, np.float64).copy())
            self.log(f"walk test: fell out of the map after leaving the floor at {p[0]:.0f} {p[1]:.0f} {p[2]:.0f}")
        cam.pos = w.eye_pos * F

    def sec_walk(self) -> None:
        st = self.state
        if not self._header("Walk test (real collision)", False):
            return
        w = self.walker
        if w is None:
            if imgui.button("Walk from where the camera is"):
                self._try(self.start_walk)
            sp = st.spawn_positions()
            teams = sorted(sp)
            if teams:
                ti = min(self.walk_team, len(teams) - 1)
                _, self.walk_team = ui.combo("team##walk", ti, [f"team {t}" for t in teams])
                lst = sp[teams[min(self.walk_team, len(teams) - 1)]]
                _, self.walk_idx = ui.combo("start point##walk", min(self.walk_idx, len(lst) - 1), [n for n, _ in lst])
                if imgui.button("Walk from that start point"):
                    self._try(self.start_walk, lst[min(self.walk_idx, len(lst) - 1)][1])
        else:
            imgui.text_colored(_V4(0.3, 1.0, 0.4, 1), tr("Walking: WASD, Space = jump, Shift = run, Esc = stop"))
            if imgui.button("Stop walking"):
                self.stop_walk()
            p = w.pos
            imgui.text(f"position {p[0]:.0f} {p[1]:.0f} {p[2]:.0f}")
            imgui.text(tr("on the floor") if w.on_ground else tr("in the air"))
            imgui.text(f"walked {w.walked / 100:.0f} m, fell out {w.fell} times")
            for k, q in enumerate(self.walk_log[-5:]):
                imgui.push_id(f"wl{k}")
                if imgui.small_button("Go to"):
                    self.stop_walk()
                    self.go_to(q)
                imgui.pop_id()
                imgui.same_line()
                imgui.text(f"fell at {q[0]:.0f} {q[1]:.0f} {q[2]:.0f}")
        _, self.walk_speed = ui.drag_float("speed (units / s)", self.walk_speed, 5.0, 50.0, 3000.0)
        _, self.walk_steph = ui.drag_float("highest step climbed", self.walk_steph, 1.0, 5.0, 200.0)
        _, self.walk_jump = ui.drag_float("jump strength", self.walk_jump, 5.0, 0.0, 2000.0)
        imgui.text_disabled("Uses the floor (.hm) and the collision boxes as they are now, saved or not. The body's numbers are "
                            "reasonable guesses, not the game's: it finds holes and blocked ways, not exact jumps.")

    # ---- 6: team balance
    def sec_balance(self) -> None:
        st = self.state
        if not self._header("Team balance", False):
            return
        _, self.bal_cell = ui.combo("precision", self.bal_cell, ["fine (narrow stairs; up to a minute on big maps)", "coarse (fast)"])
        _, self.bal_speed = ui.drag_float("player speed (units / s)", self.bal_speed, 5.0, 50.0, 3000.0)
        if imgui.button("Measure the map"):
            res = self._try(st.balance_report, (45.0, 75.0)[self.bal_cell], max(self.bal_speed, 1.0))
            if res is not None:
                self.bal_res = res
                self.bal_text = st.balance_lines(res)
        imgui.same_line()
        _, self.bal_routes = ui.checkbox("show the routes", self.bal_routes)
        if not self.bal_text:
            imgui.text_disabled("How long each team needs to reach the enemy flag, bring it home and find a health pack, walking "
                                "over the real floor collision. Routes are drawn in the view and on the Map plan.")
            return
        for line in self.bal_text:
            if "WARNING" in line or "clear advantage" in line:
                imgui.text_colored(_V4(1.0, 0.45, 0.3, 1), tr(line))
            elif "slight advantage" in line:
                imgui.text_colored(_V4(1.0, 0.8, 0.2, 1), tr(line))
            elif "balanced" in line:
                imgui.text_colored(_V4(0.3, 1.0, 0.4, 1), tr(line))
            else:
                imgui.text(line)
        imgui.text_disabled("Measured again only when you press the button (after moving flags, start points or collision).")

    # ---- pieces of other maps (mesh library)
    def sec_meshlib(self) -> None:
        st = self.state
        if not self._header("Pieces of other maps (mesh library)", False):
            if getattr(self, "_ml_prev", None) is not None:
                self._ml_prev = None
                self.preview = None
            return
        maps = st.library_maps()
        if not maps:
            imgui.text_disabled("no other map of the game found")
            return
        if not hasattr(self, "ml_map"):
            self.ml_map, self.ml_filter, self.ml_sel, self.ml_parts, self.ml_part = 0, "", None, None, -1
            self.ml_yaw, self.ml_col, self.ml_box = 0.0, True, False
        self.ml_map = min(self.ml_map, len(maps) - 1)
        ch, self.ml_map = ui.combo("map##ml", self.ml_map, maps)
        if ch:
            self.ml_sel, self.ml_parts, self.ml_part = None, None, -1
        name = maps[self.ml_map]
        try:
            pieces = st.library_pieces(name)
        except Exception as e:
            imgui.text_colored(_V4(1.0, 0.45, 0.3, 1), str(e))
            return
        _, self.ml_filter = ui.input_text("texture contains##ml", self.ml_filter)
        f = self.ml_filter.lower().strip()
        rows = [p for p in pieces if not f or any(f in t.lower() for t in p["textures"])]
        imgui.text_disabled(f"{len(rows)} of {len(pieces)} pieces - point at one to see it in front of the camera")
        hovered = None
        imgui.begin_child("##mllist", _V2(0, 150))
        for k, p in enumerate(rows[:500]):
            sz = p["size"] / 100.0
            key = (p["kind"], p["index"])
            if ui.selectable(f"{p['label']}   {p['tris']} tris  {sz[0]:.1f}x{sz[1]:.1f}x{sz[2]:.1f} m##ml{k}", self.ml_sel == key):
                self.ml_sel, self.ml_parts, self.ml_part = key, None, -1
            if imgui.is_item_hovered():
                hovered = (key, None)
        imgui.end_child()
        if self.ml_sel is not None and imgui.button("Split it in its separate parts"):
            res = self._try(st.library_parts, name, *self.ml_sel)
            if res is not None:
                self.ml_parts, self.ml_part = res, -1
        if self.ml_parts:
            imgui.text_disabled(f"{len(self.ml_parts)} separate parts (biggest first)")
            imgui.begin_child("##mlparts", _V2(0, 110))
            for k, q in enumerate(self.ml_parts):
                sz = q["size"] / 100.0
                if ui.selectable(f"part {k + 1}: {q['count']} tris  {sz[0]:.1f}x{sz[1]:.1f}x{sz[2]:.1f} m  {', '.join(q['textures'][:2])}##mlp{k}",
                                 self.ml_part == k):
                    self.ml_part = k
                if imgui.is_item_hovered():
                    hovered = (self.ml_sel, k)
            imgui.end_child()
        want = hovered or ((self.ml_sel, self.ml_part if self.ml_part >= 0 else None) if self.ml_sel is not None else None)
        if want is not None:
            sig = (name, want)
            if getattr(self, "_ml_prev", None) != sig:
                self._ml_prev = sig
                try:
                    part = self.ml_parts[want[1]] if (want[1] is not None and self.ml_parts) else None
                    self.preview_source(None)
                    g = st.library_piece_preview(name, want[0][0], want[0][1], part)
                    self.glp.set_geometry(g)
                    self.preview = (g, None)
                except Exception as e:
                    self.preview = None
                    self.log(f"preview failed: {e!r}")
        if self.ml_sel is None:
            return
        _, self.ml_yaw = ui.drag_float("turn (degrees)##ml", self.ml_yaw, 5.0, -180.0, 180.0)
        _, self.ml_col = ui.checkbox("make its collision (floors / walls from its triangles)##ml", self.ml_col)
        _, self.ml_box = ui.checkbox("one collision box around it##ml", self.ml_box)
        label = "Bring this part here" if (self.ml_parts and self.ml_part >= 0) else "Bring it here"
        if imgui.button(label):
            part = self.ml_parts[self.ml_part] if (self.ml_parts and self.ml_part >= 0) else None
            self._try(st.import_library_piece, name, self.ml_sel[0], self.ml_sel[1], part, self.here_point(),
                      self.ml_yaw, self.ml_col, self.ml_box)
            self._col_key = None
            self.preview, self._ml_prev = None, None
        imgui.text_disabled("Textures are the game's own (shared by every map): nothing is copied or replaced. The source map is not "
                            "changed. A big mesh is often many separate things (the game merges them): split it to take one.")

    # ---- shading layer (glow, like mp_b_garaje)
    def sec_shading(self) -> None:
        st = self.state
        if not self._header("Shading layer (like mp_b_garaje)", False):
            return
        if not hasattr(self, "sh_tex"):
            self.sh_tex, self.sh_size, self.sh_aspect, self.sh_map = "glow_galo.tex", 650.0, 1.0, False
            self.sh_name, self.sh_c, self.sh_e, self.sh_col, self.sh_soft = "mio", 1.0, 0.25, [1.0, 1.0, 1.0], 1.0
        imgui.text_wrapped("Some maps are not flat because their meshes have a SECOND texture multiplied over the normal one: soft "
                           "spots of light (glow_galo.tex) repeated over floors and walls; between the spots it gets darker. "
                           "It is not the fog and not the lights.")
        names = st.glow_textures()
        if names:
            i = next((k for k, n in enumerate(names) if n.lower() == self.sh_tex.lower()), 0)
            ch, i = ui.combo("spot texture##sh", i, names)
            self.sh_tex = names[i]
        _, self.sh_size = ui.drag_float("one spot every (units)##sh", self.sh_size, 10.0, 50.0, 10000.0)
        _, self.sh_aspect = ui.drag_float("stretch (1 = round)##sh", self.sh_aspect, 0.01, 0.2, 5.0)
        _, self.sh_map = ui.checkbox("on the whole map (else: the selection / group)##sh", self.sh_map)
        scope = "map" if self.sh_map else "selection"
        n = len(st.shading_targets(scope))
        imgui.text(f"{n} meshes" + ("" if self.sh_map else " selected (a prop changes its mesh: all its copies)"))
        if imgui.button("Give them the shading layer (spots centred on the camera)"):
            self._try(st.apply_shading, self.sh_tex, self.sh_size, None, scope, self.sh_aspect)
        imgui.same_line()
        if imgui.button("Remove it##sh"):
            self._try(st.remove_shading, scope)
        if imgui.tree_node("Make my own spot texture"):
            _, self.sh_name = ui.input_text("name (glow_...)##sh", self.sh_name)
            _, self.sh_c = ui.drag_float("brightness in the middle##sh", self.sh_c, 0.01, 0.0, 1.0)
            _, self.sh_e = ui.drag_float("brightness at the border##sh", self.sh_e, 0.01, 0.0, 1.0)
            _, self.sh_col = ui.color_edit3("tint##sh", self.sh_col)
            _, self.sh_soft = ui.drag_float("softness##sh", self.sh_soft, 0.01, 0.2, 4.0)
            imgui.text_disabled("middle brighter = a pool of light; middle darker = a shadow in the middle")
            if imgui.button("Create the texture"):
                t = self._try(st.make_shading_texture, self.sh_name, self.sh_c, self.sh_e, self.sh_col, self.sh_soft)
                if t:
                    self.sh_tex = t
            imgui.tree_pop()
        imgui.text_disabled("The editor does not draw this layer: you see it in the game. Undo works.")

