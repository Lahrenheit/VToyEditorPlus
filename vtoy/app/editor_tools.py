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
from .. import settings as _settings
from ..language import tr

F = np.array([1.0, 1.0, -1.0])          # engine <-> display (the view mirrors z)


def _V2(x, y):
    return imgui.ImVec2(x, y)


def _V4(r, g, b, a):
    return imgui.ImVec4(r, g, b, a)


class ToolPanels:
    # ------------------------------------------------------------------------------ state of the tools
    def tools_init(self) -> None:
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
        self.ah = dict(floors=True, walls=True, ceilings=True, merge=True, replace=True, up=False, box=False, sure=False)
        self.obj_path, self.obj_meta, self.obj_scale, self.obj_yaw, self.obj_up = "", None, 100.0, 0.0, 0
        self.obj_two, self.obj_col, self.obj_box = False, True, False
        self.paint_mode, self.paint_tex, self.paint_tile, self.paint_hit = 1, "", 0.0, None
        for k in ("lit", "light_ranges", "sound_ranges", "fx", "rain"):
            self.opts.setdefault(k, False)
        self.light_col, self.light_start, self.light_end = [1.0, 0.95, 0.8], 250.0, 800.0
        self.fx_preset = 0
        self.walker, self.walk_team, self.walk_idx, self.walk_log = None, 0, 0, []
        self.walk_speed, self.walk_steph, self.walk_jump = 450.0, 45.0, 420.0
        self.bal_res, self.bal_text, self.bal_cell, self.bal_speed, self.bal_routes = None, [], 0, 450.0, True

    # ------------------------------------------------------------------------------ helpers
    def here_point(self):
        """Engine point 'here': the last measured point, else what the middle of the view looks at, else the camera."""
        st = self.state
        if self.meas:
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
        if self.tool == "measure":
            p = st.pick_point(o, d)
            if p is not None:
                if len(self.meas) >= 2:
                    self.meas = []
                self.meas.append(np.asarray(p, np.float64))
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
            if len(pts) == 2:
                self.gl.draw_lines([(pts[0], pts[1])], (1.0, 0.4, 1.0, 1), False)
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
        if len(self.meas) == 2:
            try:
                a, b = (np.asarray(p, np.float64) for p in self.meas)
                scr, ok = self.to_screen(((a + b) / 2 * F)[None])
                if ok[0]:
                    d = float(np.linalg.norm(b - a))
                    imgui.get_background_draw_list().add_text(_V2(float(scr[0][0]) + 8, float(scr[0][1]) - 8),
                                                              imgui.get_color_u32(_V4(1.0, 0.6, 1.0, 1.0)), f"{d / 100:.2f} m")
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
        if not self.show_tools or self.state.scene is None:
            return
        imgui.set_next_window_pos(_V2(190, 60), imgui.Cond_.first_use_ever.value)
        imgui.set_next_window_size(_V2(400, 560), imgui.Cond_.first_use_ever.value)
        exp, self.show_tools = ui.begin("Map tools", True)
        if exp:
            for fn in (self.sec_check, self.sec_group, self.sec_measure, self.sec_solid, self.sec_collision, self.sec_autohm,
                       self.sec_obj, self.sec_paint, self.sec_lightview, self.sec_fx, self.sec_walk, self.sec_balance,
                       self.sec_pieces, self.sec_plan,
                       self.sec_play, self.sec_install, self.sec_history):
                try:
                    fn()
                except Exception as e:                       # one broken panel must not take the others (or the editor) down
                    imgui.text_disabled(f"{fn.__name__}: {e}")
        imgui.end()

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
        imgui.text_disabled("Click two points in the view.")
        for k, p in enumerate(self.meas):
            imgui.text(f"{'AB'[k]}:  {p[0]:.0f}  {p[1]:.0f}  {p[2]:.0f}")
        if len(self.meas) == 2:
            a, b = self.meas
            d = b - a
            flat = float(np.hypot(d[0], d[2]))
            imgui.text(f"distance {np.linalg.norm(d):.0f}  =  {np.linalg.norm(d) / 100:.2f} m")
            imgui.text(f"on the ground {flat / 100:.2f} m   height {d[1] / 100:+.2f} m")
            imgui.text(f"dx {d[0]:.0f}   dy {d[1]:.0f}   dz {d[2]:.0f}")

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
        if imgui.button("Create between A-B") and len(self.meas) == 2:
            self._try(st.add_solid_between, shape, self.meas[0], self.meas[1], self.sol_dim[1], self.sol_dim[2],
                      self.sol_tex.strip(), self.sol_tile)
            self._col_key = None
        imgui.text_disabled("A-B = the two measured points: its length and direction come from them (a ramp also its height).")
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
                if ch1 or ch2:
                    st.set_collision_box(self.col_sel, c2, h2)
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
        two = len(self.meas) == 2
        if imgui.button("Invisible wall A-B") and two:
            self._try(st.add_wall, self.meas[0], self.meas[1], self.wall_h)
            self._col_key = None
        imgui.same_line()
        if imgui.button("Ramp A-B") and two:
            a, b = sorted(self.meas, key=lambda p: p[1])
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
        imgui.text_disabled("Its textures (PNG / JPG / BMP / TGA named in the .mtl) become new .tex files; nothing of the game is replaced.")

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
        sig = (id(st.opt), tuple(np.round(cam / 300.0).astype(int)),
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
                    imgui.text(f"{str(r.object_name)[:22]}  {os.path.basename(str(p.wav))[:22]}  {p.min_distance:.0f}-{p.max_distance:.0f}")
                else:
                    imgui.text(f"{str(r.object_name)[:22]}  {str(p.texture)[:22]}  {p.rate:.0f}/s  {p.life:.1f} s")
            imgui.tree_pop()
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
