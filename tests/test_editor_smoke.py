"""Headless smoke test of the GL/ImGui layer with glfw, PyOpenGL and imgui mocked out.

It cannot prove the pictures are right - only that every code path runs, shaders are loaded, arrays have the shapes the
GL calls expect and the editor loop survives a few frames, a click and a save. Real-GPU testing is still required."""
import os, sys, tempfile
import numpy as np
from unittest.mock import MagicMock
import _path
from _path import DATA
sys.path.insert(0, os.path.dirname(__file__))
from test_state import make_game_copy


def _forget_calls(m, seen=None):
    """Drop the call records of a mock and all its children (call counts stay)."""
    seen = set() if seen is None else seen
    if id(m) in seen:
        return
    seen.add(id(m))
    for name in ("call_args_list", "mock_calls", "method_calls"):
        lst = getattr(m, name, None)
        if lst is not None:
            lst.clear()
    for child in list(getattr(m, "_mock_children", {}).values()):
        if child is not None and hasattr(child, "_mock_children"):
            _forget_calls(child, seen)
    rv = getattr(m, "_mock_return_value", None)
    if rv is not None and hasattr(rv, "_mock_children"):
        _forget_calls(rv, seen)


def install_mocks():
    glfw, GL, imgui_m = MagicMock(name="glfw"), MagicMock(name="GL"), MagicMock(name="imgui")
    glfw.init.return_value = True
    glfw.PRESS = 1
    frames = {"n": 0}

    def should_close(_w):
        frames["n"] += 1
        return frames["n"] > 4
    glfw.window_should_close.side_effect = should_close
    glfw.get_framebuffer_size.return_value = (1400, 850)
    glfw.get_window_size.return_value = (1400, 850)
    glfw.get_window_pos.return_value = (100, 100)
    glfw.get_monitors.return_value = []
    glfw.get_cursor_pos.return_value = (700.0, 425.0)
    # frame 2 = a left click in the middle of the screen, nothing else pressed
    glfw.get_key.return_value = 0
    glfw.get_mouse_button.side_effect = lambda w, b: 1 if (b == glfw.MOUSE_BUTTON_LEFT and frames["n"] == 2) else 0
    GL.glReadPixels.side_effect = lambda x, y, w, h, fmt, typ: bytes(w * h * (3 if fmt is GL.GL_RGB else 4))
    GL.glGetShaderiv.return_value = 1
    GL.glGetProgramiv.return_value = 1
    GL.glGetUniformLocation.return_value = 3
    imgui_m.begin_main_menu_bar.return_value = True
    imgui_m.menu_item.return_value = (False, False)
    imgui_m.begin.side_effect = lambda *a, **k: (True, True)
    imgui_m.begin_menu.return_value = True
    imgui_m.selectable.return_value = (False, False)
    imgui_m.button.return_value = False
    imgui_m.small_button.return_value = False
    imgui_m.get_mouse_pos.return_value = MagicMock(x=5.0, y=5.0)
    imgui_m.input_text.side_effect = lambda l, v, *a, **k: (False, v)
    imgui_m.checkbox.side_effect = lambda l, v: (False, v)
    imgui_m.combo.side_effect = lambda l, i, items: (False, i)
    imgui_m.drag_float.side_effect = lambda l, v, *a: (False, v)
    imgui_m.drag_float3.side_effect = lambda l, v, *a: (False, v)
    imgui_m.slider_float.side_effect = lambda l, v, lo, hi: (False, v)
    imgui_m.color_edit3.side_effect = lambda l, v: (False, v)
    imgui_m.input_int.side_effect = lambda l, v: (False, v)
    imgui_m.get_io.return_value.want_capture_mouse = False
    imgui_m.get_io.return_value.want_capture_keyboard = False
    imgui_m.tree_node.return_value = True
    imgui_m.tree_node_ex.return_value = True
    imgui_m.begin_popup.return_value = True
    imgui_m.get_content_region_avail.return_value.x = 360.0
    imgui_m.is_item_hovered.return_value = True
    imgui_m.invisible_button.return_value = False
    imgui_m.get_frame_height.return_value = 20.0
    imgui_m.get_cursor_screen_pos.return_value = MagicMock(x=10.0, y=10.0)
    imgui_m.is_mouse_clicked.return_value = True
    # draw lists with the REAL imgui-bundle signatures (wrong positional arguments crashed the editor twice)
    class DrawList:
        def add_rect(self, p_min, p_max, col: int, rounding: float = 0.0, thickness: float = 1.0, flags: int = 0):
            assert isinstance(col, int) and isinstance(flags, int) and isinstance(thickness, float)
        def add_rect_filled(self, p_min, p_max, col: int, rounding: float = 0.0, flags: int = 0):
            assert isinstance(col, int) and isinstance(flags, int)
        def add_line(self, p1, p2, col: int, thickness: float = 1.0):
            assert isinstance(col, int)
        def add_circle_filled(self, center, radius: float, col: int, num_segments: int = 0):
            assert isinstance(col, int) and isinstance(num_segments, int)
        def add_text(self, pos, col: int, text: str):
            assert isinstance(col, int) and isinstance(text, str)
        def path_arc_to(self, center, radius: float, a_min: float, a_max: float, num_segments: int = 0):
            assert isinstance(num_segments, int)
        def path_stroke(self, col: int, thickness: float = 1.0, flags: int = 0):
            assert isinstance(col, int) and isinstance(flags, int)
        cleared = 0
        def path_clear(self):                     # only called when custom drawing (padlock, eye) raised: must stay 0
            type(self).cleared += 1
    imgui_m.get_window_draw_list.return_value = DrawList()
    imgui_m.get_background_draw_list.return_value = DrawList()
    imgui_m.get_foreground_draw_list.return_value = DrawList()
    imgui_m.get_color_u32.return_value = 0xFFFFFFFF
    pkg = MagicMock(name="imgui_bundle"); pkg.imgui = imgui_m
    sys.modules.update({"glfw": glfw, "OpenGL": MagicMock(GL=GL), "OpenGL.GL": GL, "imgui_bundle": pkg,
                        "imgui_bundle.python_backends": MagicMock(),
                        "imgui_bundle.python_backends.glfw_backend": MagicMock()})
    return glfw, GL, imgui_m


def test_smoke():
    glfw, GL, imgui_m = install_mocks()
    from vtoy.app.editor import Editor
    with tempfile.TemporaryDirectory() as tmp:
        root = make_game_copy(tmp)
        TJ = os.environ.get("VTOY_TJ_DATA", os.path.join(os.path.dirname(DATA), "tj"))
        ed = Editor(root, "mp_dm_plaza.scn", os.path.join(tmp, "out.vpk"), library=TJ if os.path.isdir(TJ) else None)
        ed.quit_ok = True            # the real window asks "save before exit?" when something is unsaved; the mock cannot answer
        ed.run()
        # keyboard/mouse manipulation: hold G, drag, release -> committed once
        car = next(r for r in ed.state.scene.modules if r.parsed is not None and hasattr(r.parsed, "model_name"))
        from vtoy.app.state import Selection
        ed.state.selection = Selection("module", car)
        before = ed.state.position_of(ed.state.selection).copy()
        import vtoy.app.editor as E
        held = {E.glfw.KEY_G}
        ed.key = lambda k: k in held
        assert ed.manipulate(30.0, -20.0, 0.0) and ed.manip
        held.clear(); ed.pend_t -= 1.0
        ed.manipulate(0, 0, 0)
        assert not ed.manip and not (ed.state.position_of(ed.state.selection) == before).all()
        held.add(E.glfw.KEY_LEFT_CONTROL)
        ed.manipulate(0, 0, 1.0); held.clear(); ed.pend_t -= 1.0; ed.manipulate(0, 0, 0)
        ed.toggle_fullscreen(); assert ed.fullscreen; ed.toggle_fullscreen(); assert not ed.fullscreen
        ed.show_preview(ed.state.nfo_names()[0]); assert ed.preview is not None
        # custom drawing straight (not through the try/except wrappers): checked against the real signatures
        ed.preview_frame()
        E.padlock("##t", True); E.padlock("##t2", False)
        ed.want_capture = "auto"; ed._finish_capture(); assert ed.prev_img.shape == (256, 256, 4)
        # --- map tools: every panel is drawn by ed.run() above; here the view interaction
        st0 = ed.state
        ed.opts["hm"] = True; ed.tools_draw3d(); ed.tools_overlay()
        ed.tool = "measure"
        o0 = np.asarray(st0.camera.pos, float); d0 = np.asarray(st0.camera.front, float)
        ed.tools_press(o0, d0, 700, 425); ed.tools_press(o0 + [50, 0, 0], d0, 720, 425)
        ed.tools_overlay(); ed.tools_draw3d(); ed.sec_measure()
        ed.tool = "collision"; ed.tools_press(o0, d0, 700, 425); ed.tools_draw3d(); ed.sec_collision()
        ed.tool = "select"
        ed.rect = [0.0, 0.0, 1400.0, 850.0]; ed.drag = dict(tool="rect")
        ed.tools_overlay()
        assert ed.tools_drag(1400.0, 850.0) and ed.tools_release() and ed.rect is None
        n_grp = len(st0.multi_list())
        ed.tools_draw3d(); ed.sec_group()
        st0.multi = []
        ed.plan_update(); assert ed.plan_tex; ed.sec_plan()
        for fn in (ed.sec_check, ed.sec_solid, ed.sec_pieces, ed.sec_play, ed.sec_install, ed.sec_history):
            fn()
        # --- batch 7 panels and drawing, called straight (no try/except wrapper in between)
        for fn in (ed.sec_autohm, ed.sec_obj, ed.sec_paint, ed.sec_lightview, ed.sec_fx, ed.sec_walk, ed.sec_balance):
            fn()
        ed.opts.update(lit=True, light_ranges=True, sound_ranges=True, fx=True, rain=True)
        ed.draw3d()
        assert ed.gl.lit is not None and ed.gl.lit["lights"] and GL.glUniform4f.called
        ed.fx_draw3d()
        assert all(ed.opts[k] for k in ("lit", "light_ranges", "sound_ranges", "fx", "rain"))     # nothing switched itself off
        assert any(k.endswith("@a4") or "@a" in k for k in ed.gl.textures), list(ed.gl.textures)[:5]   # faded particle textures
        ed.tool = "paint"
        hit = st0.paint_pick(o0, d0)
        if hit is not None:
            ed.tools_press(o0, d0, 700, 425)                           # no texture chosen: only a message
            held_keys = {E.glfw.KEY_LEFT_SHIFT}
            ed.key = lambda k: k in held_keys
            ed.tools_press(o0, d0, 700, 425)                           # Shift+click: eyedropper
            assert ed.paint_tex and ed.paint_hit is not None
            held_keys.clear()
            ed.paint_tex = "barandillas_poli.tex"; ed.paint_mode = 0
            ed.tools_press(o0, d0, 700, 425)
            assert st0.paint_pick(o0, d0)["texture"] == "barandillas_poli.tex"
            ed.do_undo()
        ed.key = lambda k: k in held
        ed.sec_paint(); ed.win_tools()
        ed.start_walk(); assert ed.walker is not None
        cam_before = np.asarray(st0.camera.pos, float).copy()
        for _ in range(10):
            ed.walk_step(1 / 30, 1.0, 0.0)
        ed.sec_walk()
        assert ed.walker.walked > 0 or not ed.walker.on_ground
        held.add(E.glfw.KEY_ESCAPE); ed.walk_step(1 / 30, 0.0, 0.0); held.clear()
        assert ed.walker is None
        st0.camera.pos = cam_before
        res = st0.balance_report(70.0)
        ed.bal_res, ed.bal_text = res, st0.balance_lines(res)
        ed.sec_balance(); ed.sec_plan(); ed.fx_draw3d()
        em = st0.emitters()[0]; ed._module_body(em)
        hp = next(r for r in st0.scene.modules if r.clean_name.lower() == "mp_salud"); ed._module_body(hp)
        st0.selection = Selection("module", st0.sound_sources()[0], ""); ed.fx_draw3d(); st0.selection = None
        if st0.library is not None:                                    # library: every kind of list + the hover preview
            for mode in range(5):
                ed.lib_mode = mode; ed.lib_sel = ""; ed._lib_key = None
                ed.sec_library()
                if mode == 0:
                    assert ed.preview is not None and ed._lib_prev and ed.glp.fs.lib is st0.library
            ed.lib_mode = 0
            ed.show_preview(st0.nfo_names()[0]); assert ed.glp.fs.lib is None and ed._lib_prev is None
        # batch 8: weapons, indestructible cars, view options remembered
        ed.weapons_ui()
        cc = next((r for r in st0.scene.modules if r.clean_name.lower() == "mp_ccar"), None)
        if cc is not None:
            ed._module_body(cc)
        ed.opts["gamma"] = 1.5; st0.camera.fov = 90.0
        ed.save_view()
        assert E._cfg_get("view_options")["gamma"] == 1.5 and E._cfg_get("view_options")["fov"] == 90.0
        ed.opts["gamma"] = 1.0; st0.camera.fov = 75.0
        ed.load_view_options(); assert ed.opts["gamma"] == 1.5 and st0.camera.fov == 90.0
        ed.opts["gamma"] = 1.0; st0.camera.fov = 75.0
        # listening to sounds: the rows, a sound that is not there, one that is (no audio device here: a message, no crash)
        snd = st0.sound_sources()[0]
        ed.module_sounds_ui(snd); ed._module_body(snd); ed.sec_fx()
        ed.play_sound("wavs\\no_such_sound.wav")
        assert "no_such_sound" in ed.snd_msg and not ed.audio.playing
        os.makedirs(os.path.join(st0.game_dir, "wavs"), exist_ok=True)
        with open(os.path.join(st0.game_dir, "wavs", "tono.wav"), "wb") as f:
            f.write(b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x40\x1f\x00\x00\x40\x1f\x00\x00\x01\x00\x08\x00data\x00\x00\x00\x00")
        ed.play_sound("wavs\\tono.wav")
        ed.sound_row("wavs\\tono.wav"); ed.audio.stop()
        # every kind of object x every tool: draw all panels, drag it with G (move / rotate / scale), copy it with Q, delete it.
        # Nothing may raise (a raise here is what closed the editor before)
        ed._ui_errors = set()
        logged = []
        real_log = ed.log
        ed.log = lambda m: (logged.append(str(m)), real_log(m))
        def samples():
            out, seen = [], set()
            for r in st0.scene.modules:
                if r.clean_name.lower() not in seen:
                    seen.add(r.clean_name.lower()); out.append(("module", r.clean_name.lower()))
            pick = [k for k in out if k[1] in ("rendernfo", "mp_cstartpoint", "mp_soundsource", "cparticlesystem", "mp_salud",
                                               "mp_flag", "mp_ccar", "mp_camerastartposition")] or out[:6]
            return pick + [("mesh", 0), ("prop", 0), ("light", 0), ("decal", 0)]
        def fresh(kind, key):
            if kind == "module":
                r = next((r for r in st0.scene.modules if r.clean_name.lower() == key), None)
                return None if r is None else Selection("module", r, key)
            lst = {"mesh": st0.opt.meshes, "prop": st0.opt.props, "light": st0.opt.lights, "decal": st0.opt.decals}[kind]
            return Selection(kind, lst[0], kind) if lst else None
        if not st0.opt.decals:
            st0.add_decal("tablones.tex")
        for kind, key in samples():
            for tool in ("move", "rotate", "scale"):
                sel = fresh(kind, key)
                if sel is None:
                    continue
                st0.selection, ed.tool = sel, tool
                for m in (GL, imgui_m):                           # (the mocks remember every call: millions here)
                    _forget_calls(m)
                ed.gui(); ed.draw3d()
                held.clear(); held.add(E.glfw.KEY_G)
                ed.manipulate(25.0, -10.0, 1.0); held.clear(); ed.pend_t -= 1.0; ed.manipulate(0, 0, 0)
                ed.gui(); ed.draw3d()
            sel = fresh(kind, key)
            if sel is not None:
                st0.selection = sel
                ed.start_copy(); ed.commit_manip() if hasattr(ed, "commit_manip") else None; ed.grab = False
                ed.gui(); ed.draw3d()
                if st0.selection is not None:
                    ed.delete_selection()
                ed.gui(); ed.draw3d()
                ed.do_undo(); ed.do_undo(); ed.gui(); ed.draw3d()
            st0.clear_undo()
        ed.log = real_log
        st0.selection = None; ed.tool = "select"
        bad = [m for m in logged if "error" in m.lower() and "(the editor keeps running)" in m]
        assert not ed._ui_errors and not bad, (ed._ui_errors, bad)
        assert not [m for m in logged if "Error" in m and ("Traceback" in m or "Attribute" in m or "Type" in m)], logged
        held.clear()
        # lights and decals: lists with Select / Move here / Go to / Duplicate / Delete, boxes in the view, selection panel
        ed.opts.update(light_boxes=True, decal_boxes=True)
        dcl = st0.add_decal("tablones.tex")
        ed.sec_lights(); ed.sec_decals()
        for kind, obj in (("light", st0.opt.lights[0]), ("decal", dcl)):
            st0.select_opt(kind, obj)
            ed.draw3d(); ed.sec_selection()
            assert st0.selection is not None and st0.selection.kind == kind and st0.pick_lights and st0.pick_decals
            assert ed.opt_buttons(kind, obj) is False
        assert ed.opts["light_boxes"] and ed.opts["decal_boxes"]              # drawing did not switch itself off
        # deleting a light that is not the first one of the list used to close the editor (== on numpy fields)
        la, lb = st0.add_light(E.LightType.POINT), st0.add_light(E.LightType.POINT)
        st0.select_opt("light", lb)
        imgui_m.button.side_effect = lambda label, *a, **k: label == "Delete"
        try:
            ed.sec_lights()
        finally:
            imgui_m.button.side_effect = None
            imgui_m.button.return_value = False
        assert not any(x is lb for x in st0.opt.lights)
        st0.set_hidden(dcl, True, "decal"); ed.draw3d(); ed.draw3d(); st0.show_all()
        st0.delete_selection(st0.selection); st0.selection = None
        ed.opts.update(light_boxes=False, decal_boxes=False)
        # hide / show: the eye next to the padlock
        dl = imgui_m.get_window_draw_list.return_value
        assert type(dl).cleared == 0                                   # padlocks and eyes drew without an error so far
        hp2 = next(r for r in st0.scene.modules if r.clean_name.lower() == "mp_salud")
        E.eyeball("##t1", False); E.eyeball("##t2", True); E.padlock("##t3", True)
        assert type(dl).cleared == 0
        st0.set_hidden(hp2, True)
        ed.hidden_bar(); ed.win_debug(); ed.sec_map_mesh()
        assert st0.hidden_count() == 1 and st0.needs_rebake
        ed.rebake()
        assert not any(i.ref is hp2 for i in st0.geometry.instances)
        st0.selection = Selection("module", st0.emitters()[0], "")
        ed.log(st0.hide_selection())
        assert st0.hidden_count() == 2 and st0.selection is None
        ed.fx_draw3d(); ed.main_menu(); ed.win_debug()
        ed.log(st0.show_all())
        assert st0.hidden_count() == 0 and type(dl).cleared == 0
        ed.rebake()
        ed.opts.update(lit=False, light_ranges=False, sound_ranges=False, fx=False, rain=False)
        ed.save_view()
        car = next(r for r in ed.state.scene.modules if str(r.object_name) == str(car.object_name))   # undo made new objects
        ed.rebake()
        ed.tool = "select"
        shot = ed.take_screenshot()
        from PIL import Image as _I
        assert os.path.exists(shot) and _I.open(shot).size == (ed.win_w, ed.win_h)
        # --- tools: select / move / rotate by dragging, pen + crop, hover info, sky list
        st = ed.state
        inst = next(i for i in st.geometry.instances if i.ref is car)
        c = (inst.lo + inst.hi) / 2
        o, d = c + np.array([0.0, 800.0, 0.0]), np.array([0.0, -1.0, 0.0])
        ed.tool = "move"; st.selection = None
        ed.tool_press(o, d, 700, 425)
        assert st.selection is not None and ed.drag is not None, (st.selection.kind, st.selection.label, str(car.object_name))
        base = st.position_of(st.selection).copy()
        ed.tool_drag(o + np.array([150.0, 0.0, 0.0]), d, 800, 425, 100, 0)
        assert abs(ed.pend_pos[0] - 150.0) < 1e-6 and ed.manip
        ed.tool_release()
        assert abs(st.position_of(st.selection)[0] - base[0] - 150.0) < 1e-3 and not ed.manip
        # a ray that never reaches the ground plane must not crash the drag (it used to)
        ed.tool_press(o, d, 700, 425)
        ed.drag["hit0"] = None
        ed.tool_drag(np.zeros(3), np.array([0.0, 1.0, 0.0]), 10, 10, 1, 1)
        ed.tool_release()
        ed.tool = "rotate"; ed.axis_rot = "Y"
        ed.tool_press(o, d, 700, 425)
        if ed.drag is not None:
            ed.tool_drag(o, d, 740, 425, 40, 0); assert ed.pend_rot[1] != 0
            ed.tool_release()
        assert st.describe(st.selection)
        ed.tool = "pen"; ed.pen_y = float(c[1])
        for dx, dz in ((-1e5, -1e5), (1e5, -1e5), (0, 1e5)):
            ed.pen_add(c + np.array([dx, 500.0, dz]), np.array([0, -1.0, 0]))
        assert len(ed.pen_pts) == 3
        # press on an existing point grabs it, dragging moves it (no new point is added)
        p0 = ed.pen_pts[0]
        o0 = np.array([p0[0], ed.pen_y + 500.0, -p0[1]]); dn = np.array([0, -1.0, 0])
        ed.tool_press(o0, dn, 700, 425)
        assert ed.drag is not None and ed.drag["tool"] == "pen" and len(ed.pen_pts) == 3
        ed.tool_drag(o0 + np.array([200.0, 0, 0]), dn, 720, 425, 20, 0)
        assert abs(ed.pen_pts[0][0] - (p0[0] + 200.0)) < 1e-3 and len(ed.pen_pts) == 3
        ed.tool_release(); assert ed.drag is None
        n_mod = len(st.scene.modules)
        rep = st.crop_to_outline(ed.pen_pts, True)
        assert rep.modules_removed == 0 or len(st.scene.modules) < n_mod
        st.undo_crop(); assert len(st.scene.modules) == n_mod
        assert st.sky_options() and st.sky_options()[0][0]
        st.set_sky(st.sky_options()[0][0], True)
        assert ed.state.scene is not None and ed.state.geometry is not None
        if os.path.isdir(TJ):
            assert ed.state.library is not None
        # --- new editing paths: rotate/scale/copy/delete on map meshes, undo/redo, preview capture, camera module
        n_m = len(st.opt.meshes)
        free = next(i for i in range(n_m) if not any(p.mesh_index == i for p in st.opt.props))
        st.selection = Selection("mesh", st.opt.meshes[free], "mesh")
        held.clear(); held.add(E.glfw.KEY_R)
        assert ed.manipulate(40.0, 0.0, 0.0) and ed.manip
        ed.rebake(); held.clear(); ed.pend_t -= 1.0; ed.manipulate(0, 0, 0)
        assert not ed.manip
        held.add(E.glfw.KEY_T); ed.manipulate(0.0, -30.0, 0.0); assert ed.pend_scale > 1.0
        held.clear(); ed.pend_t -= 1.0; ed.manipulate(0, 0, 0); ed.rebake()
        ed.start_copy(); assert ed.grab and len(st.opt.meshes) == n_m + 1
        ed.pend_pos[:] = (50, 0, 0); ed.manip = True; ed.commit_manip(); ed.grab = False
        ed.delete_selection(); assert len(st.opt.meshes) == n_m
        ed.do_undo(); assert len(st.opt.meshes) == n_m + 1
        ed.do_redo(); assert len(st.opt.meshes) == n_m
        for r in [r for r in st.scene.modules if r.clean_name.lower() == "mp_camerastartposition"]:
            st.selection = Selection("module", r, ""); ed.delete_selection()
        assert st.scene_problems()
        ed.main_menu(); ed.popups(); ed.win_parts(); ed.show_parts = True; ed.win_parts()
        ed.pending_popup = "about"; ed.popups(); assert getattr(ed, "_about_tex", None) is not None   # Help > About
        ed._find_scenefind, ed._find_mapfind = "dm mad", "madrid"; ed.win_debug()               # the name searches
        ed.gl.capture = lambda *a, **k: np.zeros((256, 256, 4), np.uint8)
        ed.want_capture = "auto"; ed.draw3d(); assert ed.prev_img is not None
        ed.tool = "fill"; ed.fill_panel(); ed.tool = "pen"
        st.add_module("mp_camerastartposition", "CameraStartPoint")
        assert GL.glDrawElements.called and GL.glBufferData.called
        assert GL.glCreateProgram.call_count == 4
        ed.state.save_scene(); ed.state.save_map()
        ed.load("mp_b_loveboat.scn")
        ed.state.make_twin_ships(800.0, 4, tint_ships=False)
        ed.sec_twin_ships(); ed.bridges_ui()
        assert len(ed.br_edit) == 3 and ed.br_new["width"] == 640.0
        ed.sec_gamemode()
        # batch 14: a Hammer map in the importer and the creator (wad report, texture modes), the bomb, weapon sets
        from test_batch14 import _arena
        rp = os.path.join(tmp, "arena.rmf"); _arena(rp)
        ed.bsp["path"] = rp; ed.bsp["texmode"] = 1; ed.sec_bsp(); ed.bsp["texmode"] = 0; ed.sec_bsp()
        assert ed.bsp["rep"]["textures"] == 3 and ed.bsp["rows"]
        ed.csnew["path"] = rp; ed.sec_cscreate(); assert ed.csnew["name"] == "mp_dmt_arena"
        ed.sec_bombs(); ed.weapons_ui()
        assert ed.state.repack(os.path.join(tmp, "out.vpk")) > 0
        assert os.path.getsize(os.path.join(tmp, "out.vpk")) > 0
    return True


if __name__ == "__main__":
    test_smoke(); print("test_smoke OK")
