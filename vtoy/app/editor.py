"""Main window: glfw + OpenGL 3.3 + Dear ImGui (imgui-bundle).

Layout (like the original VToyEditor): one DEBUG panel with everything, a "Scene Textures" thumbnail window and an
FPS / Position / Angles overlay.  Click in the 3D view to capture the mouse (WASD + mouse look), Esc gives it back.
Written without a GPU available - see README."""
from __future__ import annotations

import os
import sys
import copy
import time
from typing import List

import glfw
import numpy as np
from imgui_bundle import imgui
from imgui_bundle.python_backends.glfw_backend import GlfwRenderer
from OpenGL import GL as gl

from . import ui
from . import tools
from .gl_renderer import GLRenderer
from .editor_tools import ToolPanels
from .. import crop as cropmod
from .state import EditorState, Selection
from ..opt import LightType
from ..render.camera import compose, decompose


from .. import settings as _settings
from .. import language
from ..language import tr


def _cfg_get(key, default=None):
    return _settings.load().get(key, default)


def _cfg_set(key, value) -> None:
    _settings.set(key, value)


def _b(r):
    return r[0] if isinstance(r, tuple) else r


def _v(e):
    return getattr(e, "value", e)


def V2(x, y):
    return imgui.ImVec2(x, y)


def V4(r, g, b, a):
    return imgui.ImVec4(r, g, b, a)


def wrapped(text: str, color=None, width: float = 0.0) -> None:
    """Text that wraps instead of being cut: at ``width`` pixels (auto-sized windows need one) or at the window edge."""
    imgui.push_text_wrap_pos(imgui.get_cursor_pos().x + width if width else 0.0)
    if color is not None:
        imgui.push_style_color(_v(imgui.Col_.text), color)
    imgui.text_unformatted(text)
    if color is not None:
        imgui.pop_style_color()
    imgui.pop_text_wrap_pos()


def pick_file(title: str, types) -> str:
    """Native open-file dialog (tkinter ships with Python on Windows). Returns '' when cancelled or unavailable."""
    try:
        import tkinter as tk
        from tkinter import filedialog
        r = tk.Tk(); r.withdraw(); r.attributes("-topmost", True)
        p = filedialog.askopenfilename(title=tr(title), filetypes=types)
        r.destroy()
        return p or ""
    except Exception:
        return ""


def image(tid: int, size: float) -> None:
    """imgui.image() changed signature between imgui-bundle versions (int id vs ImTextureRef)."""
    try:
        imgui.image(imgui.ImTextureRef(int(tid)), V2(size, size))
    except Exception:
        imgui.image(int(tid), V2(size, size))


def padlock(key: str, locked: bool, size: float = 0.0) -> bool:
    """A small padlock button drawn with lines (no icon font needed): closed and orange = locked, open and grey = editable.
    Returns True when clicked."""
    h = size or imgui.get_frame_height()
    w = h * 0.8
    p = imgui.get_cursor_screen_pos()
    clicked = imgui.invisible_button(key, V2(w, h))
    hov = imgui.is_item_hovered()
    try:                                          # drawing must never take the editor down (API differs between versions)
        dl = imgui.get_window_draw_list()
        col = imgui.get_color_u32(V4(1.0, 0.62, 0.15, 1.0) if locked else (V4(0.85, 0.85, 0.85, 1) if hov else V4(0.55, 0.6, 0.55, 1)))
        bx0, bx1 = p.x + w * 0.12, p.x + w * 0.88
        by0, by1 = p.y + h * 0.48, p.y + h * 0.9
        dl.add_rect_filled(V2(bx0, by0), V2(bx1, by1), col, 2.0)                       # body
        cx, r = (bx0 + bx1) / 2, (bx1 - bx0) * 0.3
        top = p.y + h * 0.12 + r if locked else p.y + h * 0.02 + r
        th = max(1.5, h * 0.09)
        dl.path_arc_to(V2(cx, top), r, 3.14159, 6.28318, 10)                          # shackle
        dl.path_stroke(col, thickness=th)
        left_bottom = by0 if locked else top + (by0 - top) * 0.35                      # open: the left leg is lifted out of the body
        dl.add_line(V2(cx - r, top), V2(cx - r, left_bottom), col, th)
        dl.add_line(V2(cx + r, top), V2(cx + r, by0), col, th)
        dl.add_circle_filled(V2(cx, (by0 + by1) / 2), max(1.0, h * 0.06), imgui.get_color_u32(V4(0.1, 0.1, 0.1, 1)))
    except Exception:
        try:
            imgui.get_window_draw_list().path_clear()
        except Exception:
            pass
    if hov:
        imgui.set_tooltip(tr("Locked: cannot be selected or edited (click to unlock)") if locked
                          else tr("Editable (click to lock)"))
    return bool(clicked)


def eyeball(key: str, hidden: bool, size: float = 0.0) -> bool:
    """A small eye button drawn with lines, to go next to the padlock: open eye = shown, grey eye crossed out = hidden in the
    editor (the object stays in the map).  Returns True when clicked."""
    h = size or imgui.get_frame_height()
    w = h * 0.95
    p = imgui.get_cursor_screen_pos()
    clicked = imgui.invisible_button(key, V2(w, h))
    hov = imgui.is_item_hovered()
    try:                                          # drawing must never take the editor down
        dl = imgui.get_window_draw_list()
        if hidden:
            col = imgui.get_color_u32(V4(0.75, 0.75, 0.75, 1) if hov else V4(0.42, 0.42, 0.42, 1))
        else:
            col = imgui.get_color_u32(V4(1.0, 1.0, 1.0, 1) if hov else V4(0.45, 0.85, 1.0, 1))
        cx, cy = p.x + w * 0.5, p.y + h * 0.5
        rx, th = w * 0.40, max(1.2, h * 0.07)
        # the two lids: arcs of a big circle above and below the middle line
        R = rx * 1.35
        dy = (R * R - rx * rx) ** 0.5
        a = float(np.arcsin(min(1.0, rx / R)))
        dl.path_arc_to(V2(cx, cy + dy), R, -1.5708 - a, -1.5708 + a, 10)             # upper lid
        dl.path_stroke(col, thickness=th)
        dl.path_arc_to(V2(cx, cy - dy), R, 1.5708 - a, 1.5708 + a, 10)               # lower lid
        dl.path_stroke(col, thickness=th)
        if hidden:
            dl.add_line(V2(cx - rx, cy + h * 0.26), V2(cx + rx, cy - h * 0.26), col, th * 1.3)    # crossed out
        else:
            dl.add_circle_filled(V2(cx, cy), max(1.5, h * 0.13), col)                # the pupil
    except Exception:
        try:
            imgui.get_window_draw_list().path_clear()
        except Exception:
            pass
    if hov:
        imgui.set_tooltip(tr("Hidden in the editor, still in the map (click to show)") if hidden
                          else tr("Shown (click to hide it in the editor; it stays in the map)"))
    return bool(clicked)


class Editor(ToolPanels):
    def __init__(self, root: str, scene: str | None = None, vpk_out: str | None = None, library: str | None = None):
        self.root = root
        self.vpk_out = vpk_out or os.path.join(os.path.dirname(os.path.abspath(root)), "demo.vpk")
        self.messages: List[str] = []
        self.state = EditorState(root, log=self.log)
        self.state.game_dir = os.path.dirname(os.path.abspath(self.vpk_out))
        self.initial_scene = scene
        self.opts = dict(cull=True, decals=True, scene_fog=True, mode=0, gamma=1.0, speed=600.0,
                         collision=False, no_depth=False, start=False, health=True, flags=True, camera=False, angle=False, paredt=True)
        self.sel_scene = ""
        self.sel_map = ""
        self.lib_path = library or ""
        self.lib_filter = ""
        self.lib_mode = 0
        self.lib_sel = ""
        self.new_scene_name = "mi_mapa"
        self.pick_filter = ""
        self.models_filter = ""
        self.model_sel = ""
        self.models_kind = 0
        self.models_lib = False
        self.pick_all = False
        self.preview = None
        self.scroll = 0.0
        self.pend_pos = np.zeros(3)
        self.pend_rot = np.zeros(3)
        self.pend_t = 0.0
        self.manip = False
        self.tex_selected = ""
        self.win_w, self.win_h = 1400, 850
        self.captured = False
        self.fly = False                 # ALT toggles: fly mode (mouse captured) <-> edit mode (visible pointer)
        self.tool = "select"
        self.axis_move = "free"
        self.axis_rot = "Y"
        self.drag = None
        self.hover = []
        self.hover_t = 0.0
        self.hover_xy = (-1.0, -1.0)
        self.prev_alt = False
        self.prev_rmb = False
        self.prev_keys = {}
        self.pen_pts = []                # outline points, engine (x, z)
        self.pen_y = 0.0
        self.pen_keep = True
        self.crop_name = "mapa_recortado"
        self.crop_rep = None
        self.sky_fog = False
        self.prev_lmb = False
        self.prev_esc = False
        self.prev_f11 = False
        self.fullscreen = False
        self.windowed_rect = (100, 100, 1400, 850)
        self.mouse_prev = None
        self.fps = 0.0
        self.grab = False                # Q: the copy follows the pointer until you click
        self.pend_scale = 1.0
        self.scale_in = 1.0
        self.show_prev = False
        self.want_capture = ""
        self._cap_cache = {}
        self._drafts = {}
        from ..audio import Player
        self.audio = Player()
        self.anim_rec = None
        self.anim_key = None
        self.anim_t0 = 0.0
        self.anim_speed = 1.0
        self.anim_last = -1
        self.anim_name = ""
        self.prev_view = ""
        self.parts_img = ""
        self.fill_tex = ""
        self.fill_tile = 256.0
        self.fill_y_from_pen = True
        self.save_as_name = ""
        self.export_path = ""
        self.prev_img = None
        self.prev_tex_id = 0
        self.prev_fmt = 0
        self.prev_msg = ""
        self.show_parts = False
        self.parts_filter = ""
        self.parts_sel = -1
        self.parts_out = ""
        self.del_collision = True
        self.pending_popup = ""
        self.opts["sky"] = True
        self._kind = 0
        self._newname = "new_object"
        self.toast_msg, self.toast_t = "", 0.0
        self.was_keys = False
        self.show_hud = True
        self.prev_f1 = False
        self.creating = False
        self.quit_ok = False
        self.tools_init()                              # map tools (editor_tools.py)
        self.load_view_options()

    @staticmethod
    def icon_files():
        """(.ico, .png) found in the ``icon`` folder: next to the exe first (so you can change it without rebuilding), then the
        one bundled in the exe, then the source tree.  A .ico always wins over a .png."""
        base = getattr(sys, "_MEIPASS", None)
        roots = [os.path.join(b, "icon") for b in (os.path.dirname(os.path.abspath(sys.argv[0])), base,
                                                   os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))) if b]
        ico = png = ""
        for r in roots:
            if os.path.isdir(r):
                fs = sorted(os.listdir(r))
                ico = ico or next((os.path.join(r, f) for f in fs if f.lower().endswith(".ico")), "")
                png = png or next((os.path.join(r, f) for f in fs if f.lower().endswith(".png")), "")
        return ico, png

    def set_window_icon(self) -> None:
        """Window / taskbar icon.  On Windows the .ico is set with the Win32 API (taskbar + title bar sizes); elsewhere, or if
        that fails, through glfw from the .ico / .png pixels."""
        try:
            ico, png = self.icon_files()
            if sys.platform == "win32":
                from . import winicon
                try:
                    hwnd = glfw.get_win32_window(self.win)
                except Exception:
                    hwnd = None
                if winicon.apply(hwnd, ico):
                    return
            src = ico or png
            if src:
                from PIL import Image
                im = Image.open(src)
                imgs = []
                for size in ((256, 256), (48, 48), (32, 32), (16, 16)):     # glfw picks the best one for each use
                    c = im.convert("RGBA").copy()
                    c.thumbnail(size)
                    imgs.append(c)
                glfw.set_window_icon(self.win, len(imgs), imgs)
        except Exception as e:
            print(f"window icon: {e!r}")             # no icon is not an error

    def log(self, m: str) -> None:
        print(m)
        self.messages = (self.messages + [m])[-6:]
        self.toast_msg, self.toast_t = m, time.time()

    # ------------------------------------------------------------------------------ lifecycle
    def run(self) -> None:
        if not glfw.init():
            raise RuntimeError("glfw.init() failed")
        glfw.window_hint(glfw.CONTEXT_VERSION_MAJOR, 3)
        glfw.window_hint(glfw.CONTEXT_VERSION_MINOR, 3)
        glfw.window_hint(glfw.OPENGL_PROFILE, glfw.OPENGL_CORE_PROFILE)
        glfw.window_hint(glfw.OPENGL_FORWARD_COMPAT, glfw.TRUE)
        from . import winicon
        winicon.set_app_id()                          # own taskbar button (not grouped under python.exe)
        self.win = glfw.create_window(self.win_w, self.win_h, "VToyEditor Plus+", None, None)
        if not self.win:
            glfw.terminate()
            raise RuntimeError("could not create an OpenGL 3.3 window")
        self.set_window_icon()
        glfw.make_context_current(self.win)
        glfw.swap_interval(1)
        try:                                              # which GPU draws the editor (the integrated one is slow)
            gpu = gl.glGetString(gl.GL_RENDERER).decode("latin-1", "replace")
            print("OpenGL renderer:", gpu)
            if any(k in gpu.lower() for k in ("intel", "uhd", "microsoft basic", "gdi generic")):
                print("WARNING: the editor runs on '" + gpu + "', not on the dedicated GPU - see README section 24")
        except Exception:
            pass
        imgui.create_context()
        language.set_language(_settings.load().get("language", "en"))
        language.install(imgui)
        try:                                              # window layout lives next to vtoy_editor.json
            imgui.get_io().set_ini_filename(os.path.join(os.path.dirname(_settings.path()), "imgui.ini"))
        except Exception:
            pass
        self.impl = GlfwRenderer(self.win)
        prev_scroll = glfw.set_scroll_callback(self.win, None)

        def on_scroll(w, xo, yo):
            if prev_scroll:
                prev_scroll(w, xo, yo)
            self.scroll += yo
        glfw.set_scroll_callback(self.win, on_scroll)
        self.gl = GLRenderer(self.state.fs)
        from .state_tools import PreviewFS
        self.glp = GLRenderer(PreviewFS(self.state.fs))   # draws the model being previewed (game or library files)
        if not self.lib_path:                         # the folder chosen with File > Torrente, el juego folder...
            saved = str(_cfg_get("library", "") or "")
            if saved and os.path.isdir(saved):
                self.lib_path = saved
        if self.lib_path:
            self.load_library()
        names = self.state.scene_names()
        if not names:
            self.log("no scenes found in <root>/scns")
        else:
            last = _cfg_get("last_scene") if _cfg_get("restore_last_scene", True) else None
            by_lower = {n.lower(): n for n in names}
            first = sorted(names, key=str.lower)[0]
            pick = self.initial_scene or (by_lower.get(str(last).lower()) if last else None) or first
            self.load(pick)
            lv = _cfg_get("last_view")
            if _cfg_get("restore_last_view", True) and isinstance(lv, dict) and str(lv.get("scene", "")).lower() == str(pick).lower() and self.state.scene is not None:
                try:                                  # back to where the camera was when the editor was closed
                    cam = self.state.camera
                    cam.pos = np.array(lv["pos"], np.float64)
                    cam.yaw, cam.pitch = float(lv["yaw"]), float(lv["pitch"])
                except Exception:
                    pass
        last = time.time()
        while True:
            glfw.poll_events()
            if glfw.window_should_close(self.win):
                if self.quit_ok or not (self.state.dirty_scene or self.state.dirty_map):
                    break
                glfw.set_window_should_close(self.win, False)     # unsaved edits: ask first
                self.pending_popup = "exit"
            fbw, fbh = glfw.get_framebuffer_size(self.win)
            if glfw.get_window_attrib(self.win, glfw.ICONIFIED) == 1 or fbw < 1 or fbh < 1:
                if self.captured:                               # never keep the pointer captured while minimised
                    self.set_captured(False)
                glfw.wait_events_timeout(0.1)
                last = time.time()
                continue
            self.impl.process_inputs()
            now = time.time(); dt = min(now - last, 0.1); last = now
            self.fps = 1.0 / dt if dt > 0 else self.fps
            self.win_w, self.win_h = fbw, fbh
            if time.time() - getattr(self, "_view_saved", 0.0) > 5.0:       # also covers a crash / kill
                self._view_saved = time.time()
                self.save_view()
            try:
                self.input(dt)
            except Exception as e:                      # a tool error must never close the editor
                self.drag = None
                self.grab = False
                self.log(f"input error: {e!r}")
                import traceback; traceback.print_exc()
            imgui.new_frame()
            self.gui()
            self.draw3d()
            imgui.render()
            try:
                self.impl.render(imgui.get_draw_data())
            except Exception as e:                      # a bad texture in a panel must not close the editor
                self.log(f"render error: {e!r}")
            for r in (self.gl, getattr(self, "glp", None)):   # textures replaced this frame are freed only now
                if r is not None:
                    r.flush_deletes()
            glfw.swap_buffers(self.win)
        self.save_view()
        self.impl.shutdown()
        self.audio.stop()
        glfw.terminate()

    VIEW_SKIP = ()                                     # every option of the view is remembered

    def view_options(self) -> dict:
        """What 'View options', the View menu and the show / hide boxes are set to (plain values only)."""
        d = {k: v for k, v in self.opts.items() if isinstance(v, (bool, int, float)) and k not in self.VIEW_SKIP}
        d["fov"] = float(self.state.camera.fov)
        return d

    def load_view_options(self) -> None:
        saved = _cfg_get("view_options")
        if not isinstance(saved, dict):
            return
        for k, v in saved.items():
            if k == "fov":
                try:
                    self.state.camera.fov = float(min(120.0, max(30.0, float(v))))
                except (TypeError, ValueError):
                    pass
            elif k in self.opts and isinstance(v, (bool, int, float)):
                cur = self.opts[k]
                self.opts[k] = bool(v) if isinstance(cur, bool) else (int(v) if isinstance(cur, int) else float(v))
        self._view_saved_opts = self.view_options()

    def save_view_options(self) -> None:
        cur = self.view_options()
        if cur != getattr(self, "_view_saved_opts", None):
            self._view_saved_opts = cur
            _cfg_set("view_options", cur)

    def save_view(self) -> None:
        """Remember the scene and the camera so the next start continues from the same place."""
        st = self.state
        self.save_view_options()
        if st.scene is None or not self.sel_scene:
            return
        cam = st.camera
        _cfg_set("last_scene", self.sel_scene)
        _cfg_set("last_view", dict(scene=self.sel_scene, pos=[float(v) for v in cam.pos], yaw=float(cam.yaw), pitch=float(cam.pitch)))

    def load(self, name: str) -> None:
        try:
            self.state.load(name)
            self.gl.set_geometry(self.state.geometry)
            self.sel_scene = name
            _cfg_set("last_scene", name)
            self.creating = False
            self.sel_map = os.path.basename(self.state.scene.map_name.replace("\\", "/"))
            self.tex_selected = ""
            self.pen_pts, self.crop_rep, self.drag = [], None, None
            self.pen_auto_height()
        except Exception as e:                       # keep the window alive if a map is broken
            self.log(f"could not load {name}: {e!r}")

    def rebake(self) -> None:
        self.state.bake()
        self.gl.set_geometry(self.state.geometry)

    # ------------------------------------------------------------------------------ input / mouse capture
    def key(self, k) -> bool:
        return glfw.get_key(self.win, k) == glfw.PRESS

    def set_captured(self, on: bool) -> None:
        self.captured = on
        self.mouse_prev = None
        glfw.set_input_mode(self.win, glfw.CURSOR, glfw.CURSOR_DISABLED if on else glfw.CURSOR_NORMAL)
        try:                                        # panels ignore the mouse while the camera owns it
            io = imgui.get_io()
            flag = _v(imgui.ConfigFlags_.no_mouse)
            io.config_flags = (io.config_flags | flag) if on else (io.config_flags & ~flag)
        except Exception:
            pass

    def toggle_fullscreen(self) -> None:
        """F11: borderless-style fullscreen on the monitor the window is on; again to go back to the window."""
        try:
            if not self.fullscreen:
                self.windowed_rect = (*glfw.get_window_pos(self.win), *glfw.get_window_size(self.win))
                mon = glfw.get_primary_monitor()
                for m in glfw.get_monitors():                     # pick the monitor that contains the window
                    mx, my = glfw.get_monitor_pos(m)
                    vm = glfw.get_video_mode(m)
                    wx, wy = self.windowed_rect[:2]
                    if mx <= wx < mx + vm.size.width and my <= wy < my + vm.size.height:
                        mon = m
                        break
                vm = glfw.get_video_mode(mon)
                glfw.set_window_monitor(self.win, mon, 0, 0, vm.size.width, vm.size.height, vm.refresh_rate)
            else:
                x, y, w, h = self.windowed_rect
                glfw.set_window_monitor(self.win, None, x, y, w, h, 0)
            self.fullscreen = not self.fullscreen
            glfw.swap_interval(1)
            self.mouse_prev = None
        except Exception as e:
            self.log(f"fullscreen failed: {e!r}")

    def set_fly(self, on: bool) -> None:
        self.fly = on
        self.set_captured(on)
        if on:
            self.drag = None

    def view_ray(self, mx: float, my: float):
        """Ray through the pointer (edit mode) or through the crosshair (fly mode)."""
        ww, wh = glfw.get_window_size(self.win)
        if self.fly:
            return self.state.camera.ray(ww / 2, wh / 2, ww, wh)
        return self.state.camera.ray(mx, my, ww, wh)

    def key_edge(self, k) -> bool:
        now = self.key(k)
        was = self.prev_keys.get(k, False)
        self.prev_keys[k] = now
        return now and not was

    def input(self, dt: float) -> None:
        """Edit mode (default): visible pointer, WASD flies, hold the right button to look around, left button uses the
        current tool, hovering shows information.  ALT = fly mode (pointer captured, crosshair); ALT / Esc = back."""
        cam, st = self.state.camera, self.state
        f11 = self.key(glfw.KEY_F11)
        if f11 and not self.prev_f11:
            self.toggle_fullscreen()
        self.prev_f11 = f11
        f12 = self.key(glfw.KEY_F12)
        if f12 and not getattr(self, "prev_f12", False) and self.state.scene is not None:
            self.want_shot = True
        self.prev_f12 = f12
        f1 = self.key(glfw.KEY_F1)
        if f1 and not self.prev_f1:
            self.show_hud = not self.show_hud
        self.prev_f1 = f1
        cam.speed = self.opts["speed"]
        alt = self.key(glfw.KEY_LEFT_ALT) or self.key(glfw.KEY_RIGHT_ALT)
        if alt and not self.prev_alt:
            self.commit_manip()
            self.set_fly(not self.fly)
        self.prev_alt = alt
        esc = self.key(glfw.KEY_ESCAPE)
        if esc and not self.prev_esc and self.fly:
            self.commit_manip()
            self.set_fly(False)
        self.prev_esc = esc
        lmb = glfw.get_mouse_button(self.win, glfw.MOUSE_BUTTON_LEFT) == glfw.PRESS
        rmb = glfw.get_mouse_button(self.win, glfw.MOUSE_BUTTON_RIGHT) == glfw.PRESS
        pressed, released = lmb and not self.prev_lmb, (not lmb) and self.prev_lmb
        self.prev_lmb = lmb
        mx, my = glfw.get_cursor_pos(self.win)
        dx, dy = (mx - self.mouse_prev[0], my - self.mouse_prev[1]) if self.mouse_prev is not None else (0.0, 0.0)
        self.mouse_prev = (mx, my)
        over_ui = (not self.captured) and ui.want_capture_mouse()
        if pressed and over_ui and st.scene is not None:
            st.push_undo(False, "edit fields")
        typing = (not self.fly) and ui.want_capture_keyboard()
        if not self.fly:                                   # right button held = look around
            if rmb and not self.prev_rmb and not over_ui:
                self.set_captured(True)
            elif not rmb and self.captured:
                self.set_captured(False)
        self.prev_rmb = rmb
        scroll, self.scroll = self.scroll, 0.0
        if over_ui:
            scroll = 0.0
        if st.scene is None:
            return
        used = False
        if not typing and not over_ui:
            used = self.manipulate(dx, dy, scroll)
        if self.captured and not used:
            cam.look(dx, dy)
        if not typing:
            f = float(self.key(glfw.KEY_W)) - float(self.key(glfw.KEY_S))
            r = float(self.key(glfw.KEY_D)) - float(self.key(glfw.KEY_A))
            if getattr(self, "walker", None) is not None:      # walking test: the body moves, the camera rides on it
                self.walk_step(dt, f, r)
            elif self.fly:                         # free movement (look direction, Space up, Ctrl / C down): ALT mode only
                u = float(self.key(glfw.KEY_E) or self.key(glfw.KEY_SPACE)) - float(self.key(glfw.KEY_C) or self.key(glfw.KEY_LEFT_CONTROL))
                cam.move(f, r, u, dt, boost=self.key(glfw.KEY_LEFT_SHIFT))
            else:                                  # edit mode: flat walking only, no going up / down
                cam.move(f, r, 0.0, dt, boost=self.key(glfw.KEY_LEFT_SHIFT), flat=True)
            for n, name in enumerate(tools.TOOLS):
                if self.key_edge(glfw.KEY_1 + n):
                    self.tool = name
            if self.key_edge(glfw.KEY_DELETE) and st.selection is not None:
                self.delete_selection()
            if self.key_edge(glfw.KEY_Q) and st.selection is not None and not self.grab:
                self.start_copy()
            if self.key_edge(glfw.KEY_H):                      # H hides the selection (and the group), Shift+H shows all again
                if self.key(glfw.KEY_LEFT_SHIFT) or self.key(glfw.KEY_RIGHT_SHIFT):
                    self.log(st.show_all())
                else:
                    self.log(st.hide_selection())
            ctrl_ = self.key(glfw.KEY_LEFT_CONTROL) or self.key(glfw.KEY_RIGHT_CONTROL)
            shift_ = self.key(glfw.KEY_LEFT_SHIFT) or self.key(glfw.KEY_RIGHT_SHIFT)
            if ctrl_ and self.key_edge(glfw.KEY_Z):
                self.do_redo() if shift_ else self.do_undo()
            if ctrl_ and self.key_edge(glfw.KEY_Y):
                self.do_redo()
            if self.tool == "pen" and self.key_edge(glfw.KEY_BACKSPACE) and self.pen_pts:
                self.pen_pts.pop()
        if self.grab:                                      # a copy is following the pointer
            if pressed or self.key_edge(glfw.KEY_ENTER):
                self.commit_manip(); self.grab = False
                return
            if esc:
                self.grab = False; self.commit_manip(); self.do_undo()
                return
        # ---- tools / hover (pointer over the view, or the crosshair in fly mode)
        if over_ui or typing or (rmb and not self.fly):
            return
        o, d = self.view_ray(mx, my)
        if pressed:
            self.tool_press(o, d, mx, my)
        elif lmb and self.drag is not None:
            self.tool_drag(o, d, mx, my, dx, dy)
        if released and self.drag is not None:
            self.tool_release()
        if self.drag is None and not lmb:
            now = time.time()
            moved = abs(mx - self.hover_xy[0]) + abs(my - self.hover_xy[1]) > 2 or self.fly
            if moved and now - self.hover_t > 0.12:
                self.hover_t, self.hover_xy = now, (mx, my)
                sel, _ = st.pick_hit(o, d)
                self.hover = st.describe(sel)
        else:
            self.hover = []

    # ------------------------------------------------------------------------------ tools (Illustrator-like)
    def delete_selection(self) -> None:
        st, sel = self.state, self.state.selection
        if sel is None:
            return
        was_cam = sel.kind == "module" and sel.ref.clean_name.lower() == "mp_camerastartposition"
        try:
            msg = st.delete_selection(sel, self.del_collision)
        except Exception as e:
            self.log(f"delete failed: {e!r}")
            return
        st.selection = None
        self.log(msg)
        if was_cam or any("mp_CameraStartPosition" in p for p in st.scene_problems()):
            self.log("WARNING: a mp_CameraStartPosition module must exist before saving the scene "
                     "(Add new module > mp_CameraStartPosition)")

    def start_copy(self) -> None:
        """Q: copy the selection and let the copy follow the pointer (like G) until you click / Enter. Esc cancels."""
        st = self.state
        try:
            new = st.duplicate_selection(st.selection, (0.0, 0.0, 0.0))
        except Exception as e:
            self.log(f"copy failed: {e}")
            return
        st.selection = new
        self.rebake()
        self.pend_pos[:] = 0
        self.pend_rot[:] = 0
        self.pend_scale = 1.0
        self.grab = True
        self.log("copy: move the mouse, click to place it (Esc cancels)")

    def do_undo(self) -> None:
        self.commit_manip()
        if self.state.can_undo():
            self.log(f"undo: {self.state.undo()}")
            self.rebake()
        else:
            self.log("nothing to undo")

    def do_redo(self) -> None:
        if self.state.can_redo():
            self.log(f"redo: {self.state.redo()}")
            self.rebake()
        else:
            self.log("nothing to redo")

    def save_scene_checked(self) -> bool:
        st = self.state
        bad = st.scene_problems()
        if bad:
            for b in bad:
                self.log(b)
            self.pending_popup = "problems"
            return False
        if st.dirty_map:
            st.save_map()                               # first: it may point the scene at a new .hm
        st.save_scene()
        try:                                            # the map check runs on every save (it never blocks the save)
            self.check_res = st.validate_map()
            ne = sum(1 for r in self.check_res if r["level"] == "error")
            nw = sum(1 for r in self.check_res if r["level"] == "warning")
            if ne or nw:
                self.log(f"map check: {ne} errors, {nw} warnings - see Map tools > Map check")
        except Exception as e:
            print(f"map check: {e!r}")
        return True

    def sel_geometry(self):
        st = self.state
        if st.selection is None:
            return None
        inst = next((i for i in st.geometry.instances if i.ref is st.selection.ref), None)
        if inst is None:
            return None
        return (inst.lo + inst.hi) / 2 + self.pend_pos * [1, 1, -1], inst.hi - inst.lo

    def tool_press(self, o, d, mx: float, my: float) -> None:
        st = self.state
        if self.tools_press(o, d, mx, my):             # measure / collision tools, Ctrl+click, Shift+drag rectangle
            return
        if self.tool == "pen":
            self.pen_press(o, d)
            return
        if self.tool == "fill" and self.key(glfw.KEY_LEFT_SHIFT):          # Shift+click = eyedropper: take that texture
            sel, _ = st.pick_hit(o, d)
            t = st.texture_of(sel) if sel else None
            if t:
                self.fill_tex = t
                self.log(f"fill texture: {t}")
            return
        if self.tool == "fill":
            self.pen_press(o, d)
            return
        movable = lambda s: s is not None and (self.tool != "rotate" or st.can_rotate_any(s)) \
            and (self.tool != "scale" or st.can_scale(s))
        axis = None
        if self.tool in ("move", "rotate") and movable(st.selection):
            g = self.sel_geometry()
            if g is not None:
                axis = tools.hit_handle(o, d, *g)
        if axis is None:
            sel, _ = st.pick_hit(o, d)
            st.selection = sel
            if sel is None:
                return
        sel = st.selection
        if self.tool == "select":
            return
        if self.tool == "rotate" and not st.can_rotate_any(sel):
            self.log("this object cannot be rotated" + (" (its mesh is shared by props: rotate those)" if sel.kind == "mesh" else ""))
            return
        if self.tool == "scale" and not st.can_scale(sel):
            self.log("this object cannot be scaled" + (" (its mesh is shared by props: scale those)" if sel.kind == "mesh" else ""))
            return
        self.pend_pos[:] = 0
        self.pend_rot[:] = 0
        self.pend_scale = 1.0
        plane_y = float(st.position_of(sel)[1])
        hit0 = tools.ray_plane_y(o, d, plane_y)
        self.drag = dict(tool=self.tool, axis=axis, plane_y=plane_y, hit0=hit0, my0=my, sel=sel,
                         dist=float(np.linalg.norm(st.position_of(sel) * [1, 1, -1] - st.camera.pos)))

    def tool_drag(self, o, d, mx: float, my: float, dx: float, dy: float) -> None:
        dr = self.drag
        if self.tools_drag(mx, my):
            return
        if dr["tool"] == "pen":                      # moving an outline point with the left button held
            hit = tools.ray_plane_y(o, d, self.pen_y)
            if hit is not None and 0 <= dr["idx"] < len(self.pen_pts):
                e = tools.display_to_engine(hit)
                self.pen_pts[dr["idx"]] = (float(e[0]) + dr["off"][0], float(e[2]) + dr["off"][1])
            return
        if dr["tool"] == "move":
            axis = dr["axis"] or next((a for a, k in (("X", glfw.KEY_X), ("Y", glfw.KEY_Y), ("Z", glfw.KEY_Z)) if self.key(k)), None) \
                or {"free": "free", "X": "X", "Y": "Y", "Z": "Z"}[self.axis_move]
            hit = tools.ray_plane_y(o, d, dr["plane_y"])
            if dr["hit0"] is None and hit is not None:
                dr["hit0"] = hit
            if hit is None:
                hit = dr["hit0"]
            if hit is None or dr["hit0"] is None:
                hit = dr["hit0"] = np.zeros(3)
            delta = tools.move_delta(axis, dr["hit0"], hit, my - dr["my0"], max(dr["dist"] * 0.0025, 0.3))
            self.pend_pos[:] = tools.display_to_engine(delta)
            self.manip = True
        elif dr["tool"] == "rotate":
            axis = dr["axis"] or next((a for a, k in (("X", glfw.KEY_X), ("Y", glfw.KEY_Y), ("Z", glfw.KEY_Z)) if self.key(k)), None) \
                or self.axis_rot
            self.pend_rot += tools.rotate_delta(axis, dx, dy)
            self.manip = True
        elif dr["tool"] == "scale":
            self.pend_scale = float(np.clip(self.pend_scale * np.exp(-dy * 0.006), 0.05, 20.0))
            self.manip = True

    def tool_release(self) -> None:
        if self.tools_release():
            return
        self.commit_manip()
        self.drag = None

    # ---- pen
    def draw_view_cones(self) -> None:
        """A triangle (field of view) at every start point and at the camera start position, showing where they look.
        Start points look along (sin angle, cos angle) in engine (x, z); the camera looks from its position to its target."""
        F = np.array([1.0, 1.0, -1.0])
        tri, mid = [], []
        for r in self.state.scene.modules:
            p = r.parsed
            if p is None:
                continue
            n = r.clean_name.lower()
            if n == "mp_cstartpoint":
                pos = np.array(p.position, np.float64) + [0, 60.0, 0]
                f = np.array([np.sin(p.angle), 0.0, np.cos(p.angle)])
                length, half = 70.0, np.radians(22)
            elif n == "mp_camerastartposition":
                pos = np.array(p.position, np.float64)
                f = np.array(p.target, np.float64) - pos
                length = float(np.linalg.norm(f))
                if length < 1e-6:
                    continue
                f = f / length
                length, half = 90.0, np.radians(22)
            else:
                continue
            side = np.cross(f, [0, 1.0, 0])
            if np.linalg.norm(side) < 1e-6:
                continue
            side /= np.linalg.norm(side)
            w = length * np.tan(half)
            a, b = pos + f * length + side * w, pos + f * length - side * w
            tri += [(pos * F, a * F), (pos * F, b * F), (a * F, b * F)]
            mid.append((pos * F, (pos + f * length) * F))
        if tri:
            self.gl.draw_lines(tri, (0.3, 1.0, 0.5, 1), False)
            self.gl.draw_lines(mid, (1.0, 1.0, 1.0, 1), False)

    def pen_press(self, o, d) -> None:
        """Click on an existing point = grab it (drag to move it); click elsewhere = new point."""
        hit = tools.ray_plane_y(o, d, self.pen_y)
        if hit is not None and self.pen_pts:
            e = tools.display_to_engine(hit)
            dist = float(np.linalg.norm(np.asarray(hit, np.float64) - np.asarray(self.state.camera.pos, np.float64)))
            radius = max(150.0, dist * 0.03)
            best, bd = -1, radius
            for i, (x, z) in enumerate(self.pen_pts):
                k = float(np.hypot(x - e[0], z - e[2]))
                if k < bd:
                    best, bd = i, k
            if best >= 0:
                x, z = self.pen_pts[best]
                self.drag = dict(tool="pen", idx=best, off=(x - float(e[0]), z - float(e[2])))
                return
            seg = self.pen_segment_near(float(e[0]), float(e[2]), radius)          # click on an edge: insert a point there
            if seg is not None:
                i, q = seg
                self.pen_pts.insert(i + 1, q)
                self.drag = dict(tool="pen", idx=i + 1, off=(q[0] - float(e[0]), q[1] - float(e[2])))
                return
        self.pen_add(o, d)

    def pen_segment_near(self, x: float, z: float, radius: float):
        """(index of the segment start, closest point) of the outline segment nearest to (x, z) within ``radius``."""
        pts = self.pen_pts
        if len(pts) < 2:
            return None
        n = len(pts)
        best, bd = None, radius
        for i in range(n if n > 2 else n - 1):               # closed outline once it has 3+ points
            a, b = np.array(pts[i]), np.array(pts[(i + 1) % n])
            ab = b - a
            L2 = float(ab @ ab)
            t = 0.0 if L2 < 1e-9 else min(max(float((np.array([x, z]) - a) @ ab) / L2, 0.0), 1.0)
            q = a + ab * t
            k = float(np.hypot(q[0] - x, q[1] - z))
            if k < bd and 0.0 < t < 1.0:
                best, bd = (i, (float(q[0]), float(q[1]))), k
        return best

    def pen_add(self, o, d) -> None:
        hit = tools.ray_plane_y(o, d, self.pen_y)
        if hit is None:
            self.log("pen: look at the ground (the point must fall on the height plane)")
            return
        e = tools.display_to_engine(hit)
        self.pen_pts.append((float(e[0]), float(e[2])))

    def pen_auto_height(self) -> None:
        ys = [self.state.position_of(type("S", (), {"kind": "module", "ref": r})())[1]
              for r in self.state.scene.modules if r.clean_name == "mp_CStartPoint" and r.parsed is not None]
        if ys:
            self.pen_y = float(np.median(ys))

    # ------------------------------------------------------------------------------ move / rotate the selection
    def manipulate(self, dx: float, dy: float, scroll: float) -> bool:
        """G + mouse = move on the ground plane (wheel = up/down); R + mouse = rotate (X/Y, wheel = roll);
        T + mouse (or wheel) = scale; Ctrl + wheel = rotate about Y (Shift = fine). Works on modules, props and map meshes.
        Changes are applied once you pause (a re-bake takes about half a second), the box shows the pending change.
        Returns True while the mouse is used for this instead of looking around."""
        st, cam = self.state, self.state.camera
        sel = st.selection
        g = self.key(glfw.KEY_G) or self.grab
        r, t = self.key(glfw.KEY_R), self.key(glfw.KEY_T)
        ctrl = self.key(glfw.KEY_LEFT_CONTROL) or self.key(glfw.KEY_RIGHT_CONTROL)
        shift = self.key(glfw.KEY_LEFT_SHIFT) or self.key(glfw.KEY_RIGHT_SHIFT)
        active = sel is not None and (g or r or t or (ctrl and scroll != 0.0))
        if active:
            changed = False
            try:
                pos = st.position_of(sel)
                dist = float(np.linalg.norm(pos * [1, 1, -1] - cam.pos))
            except Exception:
                dist = 1000.0
            k = max(dist * 0.0015, 0.2)
            if g:
                f = np.array([cam.front[0], 0.0, cam.front[2]])
                f /= max(np.linalg.norm(f), 1e-9)
                right = np.cross(cam.front, (0, 1, 0)); right /= max(np.linalg.norm(right), 1e-9)
                d = right * dx * k - f * dy * k + np.array([0, scroll * max(dist * 0.03, 5.0), 0])
                self.pend_pos += d * [1, 1, -1]            # display space -> engine space
                changed = bool(dx or dy or scroll)
            elif r:
                if st.can_rotate_any(sel):
                    self.pend_rot += [dy * 0.5, dx * 0.5, scroll * 5.0]
                    changed = bool(dx or dy or scroll)
                elif not getattr(self, "_warned_rot", False):
                    self._warned_rot = True
                    self.log("this object cannot be rotated" + (" (its mesh is shared by props: rotate those)" if sel.kind == "mesh" else ""))
            elif t:
                if st.can_scale(sel):
                    self.pend_scale = float(np.clip(self.pend_scale * np.exp(-dy * 0.006 + scroll * 0.06), 0.05, 20.0))
                    changed = bool(dy or scroll)
                elif not getattr(self, "_warned_rot", False):
                    self._warned_rot = True
                    self.log("this object cannot be scaled")
            elif ctrl and scroll and st.can_rotate_any(sel):
                self.pend_rot[1] += scroll * (1.0 if shift else 5.0)
                changed = True
            if changed:
                self.pend_t = time.time()
                self.manip = True
        if not (g or r or t):
            self._warned_rot = False
            if self.was_keys and self.manip and not self.grab and self.drag is None:
                self.commit_manip()
        self.was_keys = bool(g or r or t)
        # apply when you stop moving (also while the key is still held), so the result is visible right away
        if self.manip and not self.grab and time.time() - self.pend_t > (0.35 if not (g or r or t) else 0.6):
            self.commit_manip()
        return bool(sel is not None and (g or r or t))

    def commit_manip(self) -> None:
        st = self.state
        sel = st.selection
        if sel is not None and self.manip:
            try:
                if np.any(self.pend_pos) and not self.tools_commit():      # group move / snapping handle it themselves
                    st.set_position(sel, st.position_of(sel) + self.pend_pos)
                if np.any(self.pend_rot) and st.can_rotate_any(sel):
                    st.rotate_any(sel, self.pend_rot)
                if abs(self.pend_scale - 1.0) > 1e-4 and st.can_scale(sel):
                    st.scale_selection(sel, self.pend_scale)
            except Exception as e:
                self.log(f"could not apply: {e}")
        self.pend_pos[:] = 0
        self.pend_rot[:] = 0
        self.pend_scale = 1.0
        self.manip = False

    # ------------------------------------------------------------------------------ 3D
    def draw3d(self) -> None:
        st, o = self.state, self.opts
        if st.scene is None:
            return
        if st.needs_rebake:
            self.rebake()
        gl.glViewport(0, 0, self.win_w, self.win_h)
        try:
            self.gl.lit = self.lit_state()              # Map tools > Lights: the map with its own lights (None = as painted)
        except Exception as e:
            self.gl.lit = None
            o["lit"] = False
            self.log(f"lit view: {e!r}")
        self.gl.render(st.camera, self.win_w / max(self.win_h, 1), st.scene, st.opt, cull=o["cull"],
                       sort_mode=("triangle", "texture")[o["mode"]], show_decals=o["decals"],
                       gamma=o["gamma"], use_scene_fog=o["scene_fog"], show_sky=o["sky"])
        if self.anim_rec is not None:
            self.update_anim()
        if self.preview is not None or self.anim_rec is not None:
            self.glp.render(st.camera, self.win_w / max(self.win_h, 1), st.scene, st.opt, cull=o["cull"],
                            sort_mode="triangle", show_decals=False, gamma=o["gamma"], use_scene_fog=False, clear_buffers=False)
            g = self.preview[0] if self.preview is not None else None
            if g is not None and g.instances:
                self.gl.draw_boxes([((g.instances[0].lo + g.instances[0].hi) / 2, g.instances[0].hi - g.instances[0].lo)],
                                   (0.2, 0.8, 1, 1), True)
        depth = not o["no_depth"]
        wanted = {"start point": o["start"], "mp_salud": o["health"], "mp_flag": o["flags"], "camera": o["camera"]}
        boxes = [(np.array(p) * [1, 1, -1], 2 * h) for k, _, p, h in st.markers() if wanted.get(k) and k != "mp_salud"]
        health = [(np.array(p) * [1, 1, -1], 2 * h) for k, _, p, h in st.markers() if k == "mp_salud" and o["health"]]
        if health:
            self.gl.draw_boxes(health, (0.2, 1.0, 0.3, 1), depth)        # green = health pack
        if o["angle"]:
            self.draw_view_cones()
        if o["camera"]:
            for r in st.scene.modules:
                if r.clean_name.lower() == "mp_camerastartposition" and r.parsed is not None:
                    q = r.parsed
                    self.gl.draw_lines([(np.array(q.position, np.float64) * [1, 1, -1], np.array(q.target, np.float64) * [1, 1, -1])],
                                       (1, 0.4, 1, 1), False)
        if boxes:
            self.gl.draw_boxes(boxes, (1, 1, 0, 1), depth)
        if o["collision"]:
            key = (id(st.opt), len(st.opt.hulls_raw), len(getattr(st.opt, "collision_boxes", [])), st.opt.scene_obj_count)
            if getattr(self, "_col_key", None) != key:
                try:
                    self._col_wires = tools.collision_wires(st.opt)
                except Exception as e:
                    self._col_wires = (np.zeros((0, 12, 2, 3)), np.zeros((0, 2, 3)))
                    self.log(f"collision view: {e!r}")
                self._col_key = key
            cbx, chl = self._col_wires
            if len(cbx):
                self.gl.draw_lines(cbx, (1, .2, .2, 1), depth)
            if len(chl):
                self.gl.draw_lines(chl, (1, .55, .1, 1), depth)
            oi = [i for i in getattr(self, "orphan_idx", []) if i < len(cbx)]
            if oi:                                           # boxes "Find collision without geometry" would delete
                self.gl.draw_lines(cbx[oi], (1, 0.1, 1, 1), False)
        if st.selection is not None:
            # the box of the selected module (spawn, health pack, flag, sound...): bright yellow, seen through walls
            for k, rec, p, h in st.markers(all_kinds=True):
                if rec is st.selection.ref:
                    c = np.array(p, np.float64) * [1, 1, -1] + self.pend_pos * [1, 1, -1]
                    self.gl.draw_boxes([(c, 2 * h + 8.0)], (1, 1, 0, 1), False)
                    break
            inst = next((i for i in st.geometry.instances if i.ref is st.selection.ref), None)
            if inst is not None:
                off = self.pend_pos * [1, 1, -1]
                if self.manip and (np.any(self.pend_rot) or abs(self.pend_scale - 1.0) > 1e-4):
                    self.gl.draw_lines(tools.preview_box((inst.lo + inst.hi) / 2 + off, inst.hi - inst.lo, self.pend_rot,
                                                         self.pend_scale), (1, 0.6, 0, 1), False)
                else:
                    self.gl.draw_boxes([((inst.lo + inst.hi) / 2 + off, inst.hi - inst.lo)],
                                       (1, 0.6, 0, 1) if self.manip else (0, 1, 0, 1), depth)
                if self.tool in ("move", "rotate", "scale"):
                    c = (inst.lo + inst.hi) / 2 + off
                    gz = tools.gizmo(c, inst.hi - inst.lo)
                    active = (self.drag or {}).get("axis") or (self.axis_rot if self.tool == "rotate" else
                                                               self.axis_move if self.axis_move != "free" else None)
                    for a, (tip, hc, half) in gz.items():
                        col = tools.AXIS_COLORS[a] if a != active else (1, 1, 1, 1)
                        self.gl.draw_lines([(c, tip)], col, False)
                        self.gl.draw_boxes([(hc, half * 2)], col, False)
        if self.pen_pts:
            y = self.pen_y + (20.0 if self.tool != "fill" else 5.0)
            pts = [np.array([x, y, -z]) for x, z in self.pen_pts]
            segs = list(zip(pts, pts[1:] + pts[:1])) if len(pts) > 2 else list(zip(pts, pts[1:]))
            self.gl.draw_lines(segs, (1.0, 0.85, 0.1, 1), False)
            self.gl.draw_lines([(p, p + np.array([0, 3000.0, 0])) for p in pts], (1.0, 0.85, 0.1, 1), False)
            self.gl.draw_boxes([(p, np.full(3, 120.0)) for p in pts], (1, 0.3, 0.1, 1), False)
        try:
            self.tools_draw3d()                         # floor collision, group, measure, collision box (editor_tools.py)
        except Exception as e:
            print(f"tools draw: {e!r}")
        if getattr(self, "want_shot", False):           # before the preview capture (that one draws over a corner)
            self.want_shot = False
            try:
                self.log("screenshot saved: " + self.take_screenshot())
            except Exception as e:
                self.log(f"screenshot failed: {e!r}")
        if self.want_capture:
            try:
                self._finish_capture()
            except Exception as e:
                self.want_capture = ""
                self.log(f"capture failed: {e!r}")

    # ------------------------------------------------------------------------------ GUI
    def gui(self) -> None:
        self.main_menu()
        self.hud()
        self.win_debug()
        if self.state.scene is not None:
            self.win_tools()
            self.win_textures()
            self.win_models()
            self.win_preview()
            self.win_parts()
            self.win_workbench()
            self.popups()
            if self.hover and not self.fly and not self.captured and not ui.want_capture_mouse() and self.drag is None:
                imgui.set_tooltip("\n".join(self.hover[:8]))

    def win_tools(self) -> None:
        """Side tool bar: choose a tool, then click the object (or the ground with the pen) and act."""
        st = self.state
        imgui.set_next_window_pos(V2(10, 130), _v(imgui.Cond_.first_use_ever))
        imgui.set_next_window_size(V2(170, 430), _v(imgui.Cond_.first_use_ever))
        imgui.begin("Tools")
        for name, label in (("select", "1  Select"), ("move", "2  Move"), ("rotate", "3  Rotate / tilt"), ("scale", "4  Scale"),
                            ("pen", "5  Pen (crop)"), ("fill", "6  Fill"), ("measure", "7  Measure"),
                            ("collision", "8  Collision"), ("paint", "9  Paint faces")):
            on = self.tool == name
            if on:
                imgui.push_style_color(_v(imgui.Col_.button), V4(0.15, 0.45, 0.8, 1))
            if imgui.button(label, V2(150, 0)):
                self.tool = name
            if on:
                imgui.pop_style_color()
        imgui.separator()
        if self.tool == "move":
            ch, i = ui.combo("axis", ["free", "X", "Y", "Z"].index(self.axis_move), ["free", "X", "Y", "Z"])
            if ch:
                self.axis_move = ["free", "X", "Y", "Z"][i]
            imgui.text_wrapped("Click an object and drag. Free = on the ground. Or drag an axis handle. X/Y/Z keys lock an axis.")
        elif self.tool == "rotate":
            ch, i = ui.combo("axis", "YXZ".index(self.axis_rot), ["Y  yaw (turn)", "X  pitch (tilt)", "Z  roll (tilt)"])
            if ch:
                self.axis_rot = "YXZ"[i]
            imgui.text_wrapped("Click an object and drag left/right (X: up/down). The coloured handles tilt about that axis.")
        elif self.tool == "scale":
            imgui.text_wrapped("Click an object and drag up (bigger) / down (smaller). T + mouse or T + wheel also scales.")
        elif self.tool == "select":
            imgui.text_wrapped("Click an object: its properties show in DEBUG > Selection. Hover = quick info.")
            imgui.text_wrapped("Ctrl+click: add to the group. Shift+drag: rectangle.")
        elif self.tool == "measure":
            imgui.text_wrapped("Click two points: the distance shows in Map tools > Measure.")
        elif self.tool == "collision":
            imgui.text_wrapped("Click a collision box: edit it in Map tools > Collision editing.")
        elif self.tool == "paint":
            imgui.text_wrapped("Click a face to give it the texture chosen in Map tools > Paint faces. Shift+click takes a texture.")
        sel = st.selection
        if sel is not None:
            imgui.separator()
            imgui.text(f"{sel.kind}: {sel.label[:22]}")
            if imgui.button("Copy  (Q)", V2(150, 0)):
                self.start_copy()
            if imgui.button("Delete  (Del)", V2(150, 0)):
                self.delete_selection()
            if sel.kind in ("mesh", "prop"):
                _, self.del_collision = ui.checkbox("also delete its collision", self.del_collision)
            if sel.kind in ("mesh", "prop", "module"):
                _, self.scale_in = ui.drag_float("factor", self.scale_in, 0.01)
                if imgui.button("Apply scale", V2(150, 0)) and self.scale_in > 0:
                    try:
                        st.scale_selection(sel, self.scale_in)
                    except Exception as e:
                        self.log(str(e))
        if self.tool == "pen":
            self.pen_panel()
        elif self.tool == "fill":
            self.fill_panel()
        imgui.end()

    def pen_panel(self) -> None:
        st = self.state
        imgui.text_wrapped("Click points on the ground to outline the area to keep. Backspace removes the last point.")
        _, self.pen_y = ui.drag_float("ground height Y", self.pen_y, 5.0)
        if imgui.button("Auto height"):
            self.pen_auto_height()
        imgui.text(f"{len(self.pen_pts)} points")
        if imgui.button("Undo point") and self.pen_pts:
            self.pen_pts.pop()
        imgui.same_line()
        if imgui.button("Clear"):
            self.pen_pts = []
        _, self.pen_keep = ui.checkbox("keep inside (off = remove inside)", self.pen_keep)
        if len(self.pen_pts) >= 3:
            imgui.push_style_color(_v(imgui.Col_.button), V4(0.7, 0.25, 0.1, 1))
            if imgui.button("Crop map + scene to outline"):
                try:
                    self.crop_rep = st.crop_to_outline(self.pen_pts, self.pen_keep)
                    self.pen_pts = []
                    self.rebake()
                except Exception as e:
                    self.log(f"crop failed: {e!r}")
            imgui.pop_style_color()
        if len(self.pen_pts) >= 3:
            if imgui.button("Delete collision inside outline"):
                self.log(st.delete_collision_in_polygon(self.pen_pts))
                self.pen_pts = []
            if imgui.button("Delete geometry inside outline"):
                try:
                    self.log(st.delete_inside_outline(self.pen_pts))
                    self.pen_pts = []
                    self.rebake()
                except Exception as e:
                    self.log(f"failed: {e!r}")
        imgui.separator()
        if st.can_undo_crop() and imgui.button("UNDO CROP"):
            st.undo_crop(); self.crop_rep = None; self.rebake()
        if imgui.button("Find collision without geometry"):
            self.orphan_idx = st.find_orphan_collision()
            self.orphans = len(self.orphan_idx)
            self.opts["collision"] = True                     # show them (magenta) among the collision boxes
        if getattr(self, "orphans", None) is not None:
            imgui.text(f"{self.orphans} collision boxes have no drawing near them (magenta in the view)")
            for k, bi in enumerate(list(self.orphan_idx)[:25]):
                try:
                    c, h = st.collision_box_info(bi)
                except Exception:
                    continue
                imgui.push_id(f"orph{bi}")
                imgui.text(f"#{bi} at {c[0]:.0f} {c[1]:.0f} {c[2]:.0f}  size {2 * h[0]:.0f}x{2 * h[1]:.0f}x{2 * h[2]:.0f}")
                imgui.same_line()
                if imgui.button("Go"):
                    st.camera.pos = np.array([c[0], c[1] + max(600.0, 4 * h.max()), -c[2]], np.float64)
                    st.camera.pitch = -60.0
                imgui.same_line()
                if imgui.button("Delete"):
                    self.log(st.delete_collision_boxes([bi]))
                    self.orphan_idx = st.find_orphan_collision(); self.orphans = len(self.orphan_idx)
                    imgui.pop_id()
                    break
                imgui.pop_id()
            if self.orphans and imgui.button("Delete them (leftovers of deleted objects)"):
                self.log(st.delete_orphan_collision()); self.orphans = None; self.orphan_idx = []
        if self.crop_rep is not None:
            imgui.text_wrapped(self.crop_rep.summary())
            _, self.crop_name = ui.input_text("new map name", self.crop_name)
            if imgui.button("Save cropped map as new .opt"):
                try:
                    st.save_map_as(self.crop_name)
                    st.save_scene()
                except Exception as e:
                    self.log(f"could not save: {e!r}")
        imgui.text_disabled("The height map (.hm) is not cropped. The crop edits the map in memory:")
        imgui.text_disabled("save it under a NEW name so Online's own maps stay intact.")

    # ------------------------------------------------------------------------------ menu bar, dialogs
    def main_menu(self) -> None:
        st = self.state
        if not imgui.begin_main_menu_bar():
            return
        if imgui.begin_menu("File"):
            on = st.scene is not None
            if imgui.menu_item("Save scene (and edited map)", "", False, on)[0]:
                self.save_scene_checked()
            if imgui.menu_item("Save scene as...", "", False, on)[0]:
                self.save_as_name = os.path.splitext(st.scene_name)[0] + "_2"
                self.pending_popup = "saveas"
            if imgui.menu_item("Export this map as .zip...", "", False, on)[0]:
                self.export_path = os.path.join(self.state.export_dir(),
                                                st.map_stem() + ".zip")
                self.pending_popup = "export"
            if imgui.menu_item("Map preview 256x256...", "", False, on)[0]:
                self.show_prev = True
            if imgui.menu_item("Torrente, el juego folder...", "", False, True)[0]:
                self.pick_game_folder()
            if imgui.menu_item("Install map from zip...", "", False, True)[0]:
                pz = pick_file("Map zip", [("Zip", "*.zip"), (tr("All files"), "*.*")])
                if pz:
                    self._try(st.install_map_zip, pz)
            if imgui.menu_item("Save, pack and play in the game", "", False, on)[0]:
                self._try(self.play_in_game)
            if imgui.menu_item("Screenshot (full resolution)", "F12", False, on)[0]:
                self.want_shot = True
            if imgui.menu_item("Open screenshots folder", "", False, True)[0]:
                self.open_folder(self.screenshot_dir())
            imgui.end_menu()
        if imgui.begin_menu("Edit"):
            u = f"Undo {st.undo_label()}" if st.can_undo() else "Undo"
            r = f"Redo {st.redo_label()}" if st.can_redo() else "Redo"
            if imgui.menu_item(u, "Ctrl+Z", False, st.can_undo())[0]:
                self.do_undo()
            if imgui.menu_item(r, "Ctrl+Y", False, st.can_redo())[0]:
                self.do_redo()
            imgui.separator()
            has = st.selection is not None
            if imgui.menu_item("Copy selection", "Q", False, has)[0]:
                self.start_copy()
            if imgui.menu_item("Delete selection", "Del", False, has)[0]:
                self.delete_selection()
            imgui.end_menu()
        if imgui.begin_menu("View"):
            o = self.opts
            for key, label in (("sky", "Sky"), ("decals", "Decals"), ("scene_fog", "Scene fog"), ("collision", "Collision (boxes + hulls)")):
                if imgui.menu_item(label, "", o[key])[0]:
                    o[key] = not o[key]
            if imgui.menu_item("Map parts window", "", self.show_parts)[0]:
                self.show_parts = not self.show_parts
            if imgui.menu_item("Map tools window", "", self.show_tools)[0]:
                self.show_tools = not self.show_tools
            if imgui.menu_item("Floor collision (.hm)", "", bool(o.get("hm")))[0]:
                o["hm"] = not o.get("hm")
            if imgui.menu_item("Hide the selection", "H", False, True)[0]:
                self.log(self.state.hide_selection())
            if imgui.menu_item("Show all hidden objects", "Shift+H", False, True)[0]:
                self.log(self.state.show_all())
            for key, label in (("lit", "Lit view (map lights)"), ("light_ranges", "Light ranges"), ("sound_ranges", "Sound ranges"),
                               ("fx", "Particles preview"), ("rain", "Rain preview")):
                if imgui.menu_item(label, "", bool(o.get(key)))[0]:
                    o[key] = not o.get(key)
            imgui.end_menu()
        if imgui.begin_menu("Language"):
            for code in language.codes():
                if imgui.menu_item(language.name(code), "", code == language.current())[0]:
                    language.set_language(code)
                    _settings.set("language", code)
            imgui.end_menu()
        if imgui.begin_menu("Settings"):
            for key, label in (("restore_last_scene", "Open the last map on start"),
                               ("restore_last_view", "Restore the last camera position")):
                if imgui.menu_item(label, "", bool(_settings.load().get(key, True)))[0]:
                    _settings.set(key, not bool(_settings.load().get(key, True)))
            ch, v = ui.input_text("Export folder (empty = 'export' next to demo.vpk)", getattr(self, "_exp_dir", None)
                                  if getattr(self, "_exp_dir", None) is not None else str(_settings.load().get("export_dir", "")))
            if ch:
                self._exp_dir = v
                _settings.set("export_dir", v.strip())
            imgui.text_disabled(language.tr("Settings file: {0}").replace("{0}", _settings.path()))
            imgui.end_menu()
        imgui.end_main_menu_bar()

    def popups(self) -> None:
        st = self.state
        if self.pending_popup:
            imgui.open_popup({"saveas": "Save scene as", "export": "Export map", "problems": "Cannot save yet",
                              "exit": "Unsaved changes", "rename": "Rename map"}[self.pending_popup])
            self.pending_popup = ""
        if imgui.begin_popup("Save scene as"):
            imgui.text("New scene name (the working scene is not overwritten):")
            _, self.save_as_name = ui.input_text("name", self.save_as_name)
            imgui.text_disabled("The .opt, .hm and preview image are saved with the same new name.")
            if imgui.button("Save"):
                try:
                    self.log("saved " + st.save_scene_as(self.save_as_name))
                    self.sel_scene = st.scene_name
                    self.creating = True
                    imgui.close_current_popup()
                except Exception as e:
                    self.log(f"save as failed: {e}")
            imgui.same_line()
            if imgui.button("Cancel"):
                imgui.close_current_popup()
            imgui.end_popup()
        if imgui.begin_popup("Rename map"):
            imgui.text("Copies scene, .opt, .hm and preview to the new name (originals stay):")
            _, self.rename_name = ui.input_text("new name", getattr(self, "rename_name", ""))
            if imgui.button("Rename"):
                try:
                    self.log(st.rename_map(self.rename_name))
                    self.sel_scene = st.scene_name
                    imgui.close_current_popup()
                except Exception as e:
                    self.log(f"rename failed: {e}")
            imgui.same_line()
            if imgui.button("Cancel"):
                imgui.close_current_popup()
            imgui.end_popup()
        if imgui.begin_popup("Export map"):
            imgui.text("Zip with everything the map needs: scene, .opt, .hm, models, textures, animations (.key), sounds, music, DLLs:")
            _, self.export_path = ui.input_text("zip file", self.export_path)
            imgui.text_disabled("Save the scene / map first so the zip has your latest edits.")
            if imgui.button("Export"):
                try:
                    if st.dirty_scene or st.dirty_map:
                        self.log("note: unsaved edits are not in the zip (the files on disk are exported)")
                    info = st.export_map_zip(self.export_path)
                    self.log(f"exported {len(info['files'])} files -> {self.export_path}")
                    if info["missing"]:
                        self.log(f"NOT in the zip, {len(info['missing'])} files the map names were not found: "
                                 + ", ".join(info["missing"][:12]))
                    imgui.close_current_popup()
                except Exception as e:
                    self.log(f"export failed: {e!r}")
            imgui.same_line()
            if imgui.button("Cancel##exp"):
                imgui.close_current_popup()
            imgui.end_popup()
        if imgui.begin_popup_modal("Unsaved changes", None, _v(imgui.WindowFlags_.always_auto_resize))[0]:
            imgui.text("The scene or map has unsaved changes.")
            if imgui.button("Save and exit"):
                if self.save_scene_checked():
                    self.quit_ok = True
                    glfw.set_window_should_close(self.win, True)
                imgui.close_current_popup()
            imgui.same_line()
            if imgui.button("Exit without saving"):
                self.quit_ok = True
                glfw.set_window_should_close(self.win, True)
                imgui.close_current_popup()
            imgui.same_line()
            if imgui.button("Cancel##quit"):
                imgui.close_current_popup()
            imgui.end_popup()
        if imgui.begin_popup("Cannot save yet"):
            for b in st.scene_problems():
                imgui.text_wrapped(b)
            if imgui.button("OK"):
                imgui.close_current_popup()
            imgui.end_popup()

    def fill_panel(self) -> None:
        st = self.state
        imgui.text_wrapped("Fill a hole: click points on the ground around it, choose a texture, press Fill. "
                           "Shift + click on the map takes that texture. To fill with an existing element: select it and press Q "
                           "(a copy follows the mouse, click to place it).")
        _, self.pen_y = ui.drag_float("height Y", self.pen_y, 5.0)
        imgui.same_line()
        if imgui.button("Auto"):
            self.pen_auto_height()
        texs = st.scene_textures()
        cur = next((i for i, t in enumerate(texs) if t == self.fill_tex), -1)
        ch, i = ui.combo("texture", max(cur, 0), texs or ["(none)"])
        if ch and texs:
            self.fill_tex = texs[i]
        _, self.fill_tex = ui.input_text("##filltex", self.fill_tex)
        if st.selection is not None and imgui.button("Use selection's texture"):
            t = st.texture_of(st.selection)
            if t:
                self.fill_tex = t
        _, self.fill_tile = ui.drag_float("tile size", self.fill_tile, 5.0)
        imgui.text(f"{len(self.pen_pts)} points")
        if imgui.button("Undo point") and self.pen_pts:
            self.pen_pts.pop()
        imgui.same_line()
        if imgui.button("Clear##fill"):
            self.pen_pts = []
        if len(self.pen_pts) >= 3 and self.fill_tex and imgui.button("Fill polygon"):
            try:
                st.selection = st.add_fill_patch(self.pen_pts, self.pen_y, self.fill_tex, self.fill_tile)
                self.pen_pts = []
                self.rebake()
            except Exception as e:
                self.log(f"fill failed: {e!r}")
        imgui.text_disabled("The patch is flat and has no collision (use a copy of a floor piece if you need to walk on it).")
        fills = st.fills_list()
        if fills and imgui.tree_node_ex(f"Fills made in this session ({len(fills)})", _v(imgui.TreeNodeFlags_.default_open)):
            _, self.fill_step = ui.drag_float("nudge step", getattr(self, "fill_step", 50.0), 1.0)
            step = getattr(self, "fill_step", 50.0)
            for n, f in enumerate(list(fills)):
                imgui.push_id(f"fill{n}")
                if imgui.tree_node(f"fill {n + 1}: {len(f['pts'])} points, y={f['y']:.0f}"):
                    try:
                        if imgui.button("Select"):
                            st.selection = Selection("mesh", f["mesh"], "fill patch")
                        imgui.same_line()
                        if imgui.button("Delete"):
                            st.delete_fill(f); self.rebake(); imgui.tree_pop(); imgui.pop_id(); break
                        # engine X / Z: left-right is X, up-down (forward / back on the map) is Z
                        for label, dx, dz in (("Left", -step, 0), ("Right", step, 0), ("Up (+Z)", 0, step), ("Down (-Z)", 0, -step)):
                            if imgui.button(label):
                                st.edit_fill(f, dx=dx, dz=dz); self.rebake()
                            imgui.same_line()
                        imgui.new_line()
                        ch, y = ui.drag_float("height Y", f["y"], 1.0)
                        if ch:
                            st.edit_fill(f, y=y); self.rebake()
                        for k, (px, pz) in enumerate(list(f["pts"])):
                            ch, v = ui.drag_float3(f"pt{k}", [px, f["y"], pz], 2.0)
                            if ch:
                                pts = list(f["pts"]); pts[k] = (v[0], v[2])
                                st.edit_fill(f, pts=pts, y=v[1] if abs(v[1] - f["y"]) > 1e-6 else None); self.rebake()
                    except Exception as e:
                        imgui.text_disabled(str(e))
                    imgui.tree_pop()
                imgui.pop_id()
            imgui.tree_pop()

    # ------------------------------------------------------------------------------ map preview (<map>-tbn.tex)
    def _finish_capture(self) -> None:
        """Runs after the main render: draws the scene again off-screen into a 256x256 image."""
        st, o = self.state, self.opts
        mode, self.want_capture = self.want_capture, ""
        cam = copy.copy(st.camera)
        cam.pos = np.array(st.camera.pos, np.float64)
        if mode == "auto":
            # frame the playable area: where the players start (all start points), else the objects of normal size
            sp = [np.array(r.parsed.position, np.float64) * [1, 1, -1] for r in st.scene.modules
                  if r.parsed is not None and r.clean_name.lower() == "mp_cstartpoint"]
            insts = [i for i in st.geometry.instances if i.kind in ("mesh", "prop")]
            if sp:
                pts = np.array(sp)
                lo, hi = pts.min(axis=0), pts.max(axis=0)
                c = (lo + hi) / 2
                r = max(hi[0] - lo[0], hi[2] - lo[2], 3000.0) / 2 + 1500.0
            elif insts:
                small = [i for i in insts if max(i.hi[0] - i.lo[0], i.hi[2] - i.lo[2]) < 12000.0] or insts
                cen = np.array([(i.lo + i.hi) / 2 for i in small])
                lo = np.percentile(cen, 5, axis=0); hi = np.percentile(cen, 95, axis=0)
                c = (lo + hi) / 2
                c[1] = float(np.median(cen[:, 1]))
                r = max(hi[0] - lo[0], hi[2] - lo[2]) / 2 + 500.0
            else:
                c = None
            if c is not None:
                cam.pos = c + np.array([0.0, r * 1.3 + 200.0, r * 1.0])
                cam.face(c)
        # the real renderer (textures, sky, fog: what you see in the view); the CPU drawing is only a fallback
        try:
            img = self.gl.capture(cam, st.scene, st.opt, 256, cull=o["cull"], sort_mode=("triangle", "texture")[o["mode"]],
                                  show_decals=o["decals"], gamma=o["gamma"], use_scene_fog=o["scene_fog"], show_sky=o["sky"])
        except Exception as e:
            print(f"GL capture failed ({e!r}); drawing the preview on the CPU")
            from ..render import cpu_capture
            img = cpu_capture.render(st.fs, st.geometry, cam, st.scene, 256, cache=self._cap_cache)
        self.prev_img = img
        if self.prev_tex_id:
            self.gl.delete_later([self.prev_tex_id])
        self.prev_tex_id = self.gl.upload_rgba(img)
        self.prev_msg = f"captured ({mode})"

    # ------------------------------------------------------------------------------ screenshots (F12)
    def screenshot_dir(self) -> str:
        """``screenshots`` next to demo.vpk (created when needed)."""
        d = os.path.join(getattr(self.state, "game_dir", "") or os.getcwd(), "screenshots")
        os.makedirs(d, exist_ok=True)
        return d

    def take_screenshot(self) -> str:
        """The 3D view exactly as it is on screen, at the window's real resolution (the editor panels are not in it:
        it is read before they are drawn).  PNG in ``screenshots``."""
        from PIL import Image
        w, h = int(self.win_w), int(self.win_h)
        gl.glFinish()
        gl.glReadBuffer(gl.GL_BACK)
        gl.glPixelStorei(gl.GL_PACK_ALIGNMENT, 1)
        raw = gl.glReadPixels(0, 0, w, h, gl.GL_RGB, gl.GL_UNSIGNED_BYTE)
        img = np.frombuffer(bytes(raw) if not isinstance(raw, np.ndarray) else raw.tobytes(), np.uint8).reshape(h, w, 3)[::-1]
        name = f"{self.state.map_stem()}_{time.strftime('%Y%m%d_%H%M%S')}.png"
        path = os.path.join(self.screenshot_dir(), name)
        Image.fromarray(np.ascontiguousarray(img)).save(path)
        return path

    @staticmethod
    def open_folder(path: str) -> None:
        try:
            if sys.platform == "win32":
                os.startfile(path)                      # noqa: S606 - opens Explorer
        except Exception:
            pass

    def preview_frame(self) -> None:
        """The capture is square and keeps the vertical field of view: the frame is the central square of the view."""
        side = float(self.win_h)
        x0 = (self.win_w - side) / 2.0
        dl = imgui.get_background_draw_list()
        col = imgui.get_color_u32(V4(1, 0.9, 0.2, 1))
        dim = imgui.get_color_u32(V4(0, 0, 0, 0.45))
        if x0 > 0:
            dl.add_rect_filled(V2(0, 0), V2(x0, self.win_h), dim)
            dl.add_rect_filled(V2(x0 + side, 0), V2(self.win_w, self.win_h), dim)
        dl.add_rect(V2(x0, 1), V2(x0 + side - 1, self.win_h - 1), col, rounding=0.0, thickness=2.0)
        dl.add_text(V2(x0 + 8, 6), col, tr("preview capture area (256x256)"))

    def win_preview(self) -> None:
        if not self.show_prev:
            return
        try:
            self.preview_frame()                       # only a guide drawn over the view: never worth a crash
        except Exception as e:
            print(f"preview frame: {e!r}")
        st = self.state
        imgui.set_next_window_size(V2(300, 470), _v(imgui.Cond_.first_use_ever))
        exp, self.show_prev = imgui.begin("Map preview", True)
        if exp:
            imgui.text_wrapped(f"The game's map menu shows texs/{st.preview_name()}.tex (256x256).")
            if imgui.button("Capture current view"):
                self.want_capture = "view"
            imgui.same_line()
            if imgui.button("Capture automatic"):
                self.want_capture = "auto"
            if self.prev_tex_id:
                image(self.prev_tex_id, 256)
                _, self.prev_fmt = ui.combo("format", self.prev_fmt, [".tex  (what the game reads)", ".dds"])
                if imgui.button("Save preview"):
                    try:
                        self.prev_msg = "saved " + st.save_preview(self.prev_img, ("tex", "dds")[self.prev_fmt])
                        self.log(self.prev_msg)
                    except Exception as e:
                        self.log(f"preview failed: {e!r}")
            if self.prev_msg:
                imgui.text_wrapped(self.prev_msg[-80:])
        imgui.end()

    # ------------------------------------------------------------------------------ map parts (geometry + textures)
    def win_parts(self) -> None:
        if not self.show_parts:
            return
        st = self.state
        imgui.set_next_window_size(V2(520, 560), _v(imgui.Cond_.first_use_ever))
        exp, self.show_parts = imgui.begin("Map parts", True)
        if exp:
            op = st.opt
            imgui.text(f"{len(op.meshes)} meshes, {len(op.props)} props, {len(op.decals)} decals, {len(op.lights)} lights")
            _, self.parts_filter = ui.input_text("filter (texture / index)", self.parts_filter)
            rows = [r for r in st.map_parts() if not self.parts_filter or self.parts_filter.lower() in
                    (" ".join(r[2]) + f" #{r[0]}").lower()]
            imgui.begin_child("##parts", V2(0, 230))
            for i, tris, tex, lo, hi, users in rows[:600]:
                label = f"#{i}  {tris} tris  {', '.join(tex)[:34]}" + (f"  x{users} props" if users else "")
                if ui.selectable(label, i == self.parts_sel):
                    self.parts_sel = i
                    st.selection = Selection("mesh", op.meshes[i], f"mesh {i}")
            imgui.end_child()
            if 0 <= self.parts_sel < len(op.meshes):
                me = op.meshes[self.parts_sel]
                lo, hi = cropmod.mesh_bounds(me)
                imgui.text(f"mesh {self.parts_sel}: size {hi[0]-lo[0]:.0f} x {hi[1]-lo[1]:.0f} x {hi[2]-lo[2]:.0f}")
                if imgui.button("Go to"):
                    c = (lo + hi) / 2 * [1, 1, -1]
                    st.camera.pos = c + [0, float(hi[1] - lo[1]) + 150, 500 + float(hi[0] - lo[0])]
                    st.camera.face(c)
                imgui.same_line()
                if imgui.button("Delete mesh"):
                    self.log(st.delete_mesh(me, self.del_collision)); self.parts_sel = -1; self.rebake()
                _, self.parts_out = ui.input_text("export folder", self.parts_out or os.path.join(
                    st.export_dir(), st.map_stem() + "_textures"))
                _, self.parts_img = ui.input_text("image to import (png/jpg/dds/tex)", self.parts_img)
                imgui.text_disabled(f"imported textures are named {st.map_stem()}__<name> (only this map uses them)")
                seen = []
                for mat in me.materials:
                    for t in mat.textures[:1]:
                        if t and str(t) not in seen:
                            seen.append(str(t))
                for t in seen:
                    imgui.push_id(t)
                    imgui.text(t)
                    imgui.same_line()
                    if imgui.button("Extract PNG"):
                        try:
                            self.log("extracted " + st.extract_texture(t, self.parts_out, "png"))
                        except Exception as e:
                            self.log(f"extract failed: {e!r}")
                    imgui.same_line()
                    if imgui.button("Extract .tex"):
                        try:
                            self.log("extracted " + st.extract_texture(t, self.parts_out, "tex"))
                        except Exception as e:
                            self.log(f"extract failed: {e!r}")
                    imgui.same_line()
                    if imgui.button("Replace (this mesh)") and self.parts_img:
                        self._replace_tex(t, self.parts_sel)
                    imgui.same_line()
                    if imgui.button("Replace (all)") and self.parts_img:
                        self._replace_tex(t, None)
                    imgui.pop_id()
        imgui.end()

    def _replace_tex(self, tex: str, mesh_index) -> None:
        try:
            new = self.state.import_map_texture(self.parts_img, replace=tex, mesh_index=mesh_index)
            self.gl.invalidate_textures()
            self.rebake()
            self.log(f"texture {tex} -> {new}")
        except Exception as e:
            self.log(f"replace failed: {e!r}")

    def hud(self) -> None:
        if not self.show_hud:                       # F1 hides / shows the whole box
            return
        cam = self.state.camera
        imgui.set_next_window_pos(V2(10, 30))
        imgui.set_next_window_bg_alpha(0.55)
        flags = sum(_v(f) for f in (imgui.WindowFlags_.no_title_bar, imgui.WindowFlags_.no_resize, imgui.WindowFlags_.no_move,
                                    imgui.WindowFlags_.no_saved_settings, imgui.WindowFlags_.always_auto_resize,
                                    imgui.WindowFlags_.no_nav, imgui.WindowFlags_.no_inputs))
        imgui.begin("##hud", None, flags)
        imgui.text_colored(V4(0.2, 1.0, 0.2, 1.0), f"FPS: {self.fps:.0f}")
        fmt = lambda x, n: f"{x:.{n}f}".replace(".", ",")
        imgui.text(f"Position: {cam.pos[0]:.0f}, {cam.pos[1]:.0f}, {-cam.pos[2]:.0f}")   # engine coordinates (the view mirrors Z)
        imgui.text(f"Angles: {fmt(cam.pitch, 4)}, {fmt(cam.yaw % 360.0, 4)}")
        imgui.text_colored(V4(1, 1, 0.4, 1) if not self.fly else V4(0.4, 1, 0.6, 1),
                           ("EDIT mode: pointer + tools | right button = look | WASD walk (flat) | ALT = free mode") if not self.fly else
                           "FREE mode (ALT): mouse look | WASD move | Space / E up | Ctrl / C down | Shift fast | ALT / Esc = edit mode")
        imgui.text_disabled("F1 hide / show this box   F11 fullscreen")
        imgui.text(f"tool: {self.tool}   (1 select, 2 move, 3 rotate, 4 scale, 5 pen, 6 fill)")
        if self.fly and self.hover:
            for line in self.hover[:6]:
                imgui.text_colored(V4(0.8, 1, 0.8, 1), line)
        if self.state.selection is not None and not self.fly:
            imgui.text_colored(V4(0.4, 0.9, 1, 1), "G+mouse move | R+mouse rotate | T+mouse scale | Q copy | Del delete | Ctrl+Z undo")
        if self.manip:
            d, r_ = self.pend_pos, self.pend_rot
            imgui.text(f"move {d[0]:+.0f} {d[1]:+.0f} {d[2]:+.0f}  rot {r_[0]:+.0f} {r_[1]:+.0f} {r_[2]:+.0f}  scale x{self.pend_scale:.2f}")
        if self.toast_msg and time.time() - self.toast_t < 5.0:
            wrapped(self.toast_msg, V4(1, 0.8, 0.3, 1), 520)
        if self.state.scene is not None:
            nm = os.path.splitext(self.state.scene_name)[0].upper()
            imgui.text_colored(V4(0.5, 0.9, 1.0, 1), tr("CREATING MAP: " if self.creating else "EDITING MAP: ") + nm)
        imgui.end()

    def _header(self, label: str, default_open: bool = False) -> bool:
        flag = _v(imgui.TreeNodeFlags_.default_open) if default_open else 0
        return bool(_b(imgui.collapsing_header(label, flag)))

    def _list_two_columns(self, label: str, items, selected, height=190):
        imgui.begin_child(label, V2(0, height))
        imgui.columns(2, label + "cols", False)
        picked = None
        for n in items:
            if ui.selectable(n, n == selected):
                picked = n
            imgui.next_column()
        imgui.columns(1)
        imgui.end_child()
        return picked

    def win_debug(self) -> None:
        st, sc, o = self.state, self.state.scene, self.opts
        imgui.set_next_window_pos(V2(190, 110), _v(imgui.Cond_.first_use_ever))
        imgui.set_next_window_size(V2(420, 640), _v(imgui.Cond_.first_use_ever))
        imgui.begin("DEBUG")
        if sc is None:
            imgui.text("No scene loaded")
            imgui.end()
            return
        if imgui.button("Save scene"):
            self.save_scene_checked()
        imgui.same_line()
        if imgui.button("Save scene as..."):
            self.save_as_name = os.path.splitext(st.scene_name)[0] + "_2"
            self.pending_popup = "saveas"
        if imgui.button("Rename map..."):
            self.rename_name = os.path.splitext(st.scene_name)[0]
            self.pending_popup = "rename"
        if imgui.button("Repackage VPK"):
            st.repack(self.vpk_out)
        if imgui.button("Reload file system"):
            st.reload_fs(); self.gl.invalidate_textures()
            self.log("file system reloaded")
        for key, label in (("collision", "Show collision boxes"), ("no_depth", "Disable debug depth test"),
                           ("start", "Show start/spawn points"), ("health", "Show health packs"),
                           ("flags", "Show flag objects"), ("camera", "Show camera start position"),
                           ("angle", "Show camera angle (field of view)"), ("paredt", "Show ParedT.nfo (wall)")):
            old = o[key]
            o[key] = ui.checkbox(label, o[key])[1]
            if o[key] != old and key == "paredt":
                st.hide_models = set() if o[key] else {"paredt"}
                st.needs_rebake = True
            if o[key] != old and key in ("health", "flags"):
                kind = "mp_salud" if key == "health" else "mp_flag"
                (st.hide_kinds.discard if o[key] else st.hide_kinds.add)(kind)
                st.needs_rebake = True
        if st.dirty_scene or st.dirty_map:
            imgui.text_colored(V4(1, .6, .2, 1), "unsaved changes")
        for m in self.messages[-2:]:
            wrapped(m, V4(0.55, 0.55, 0.55, 1))

        if self._header("Scene list", True):
            p = self._list_two_columns("##scenes", st.scene_names(), self.sel_scene)
            if p:
                self.sel_scene = p
            if imgui.button("Refresh Scenes"):
                st.reload_fs()
            if imgui.button("Load Scene") and self.sel_scene:
                self.load(self.sel_scene)
                imgui.end()
                return
        self.sec_map_mesh()
        if self._header("Map file backups (.bak)", False):
            imgui.text_wrapped("Maps keep their own .opt / .hm when saved. A shared file that an older version changed can be "
                               "put back from its backup here.")
            for f, b in st.map_backups():
                imgui.push_id(f)
                users = st.scenes_using(os.path.basename(f))
                imgui.text(f"{os.path.basename(f)}  ({', '.join(users[:3]) or 'no other scene'})")
                imgui.same_line()
                if imgui.button("Restore"):
                    try:
                        self.log(st.restore_backup(f))
                    except Exception as e:
                        self.log(f"restore failed: {e}")
                imgui.pop_id()
        if self._header("Maps list", True):
            p = self._list_two_columns("##maps", st.map_names(), self.sel_map, 150)
            if p:
                self.sel_map = p
            if imgui.button("Refresh Maps"):
                st.reload_fs()
            if imgui.button("Load Map") and self.sel_map:
                try:
                    st.load_map(self.sel_map)
                    self.gl.set_geometry(st.geometry)
                except Exception as e:
                    self.log(f"could not load map: {e!r}")
        if st.opt is not None:
            self.sec_lights()
            self.sec_decals()
            self.sec_weather()
            self.sec_twin_ships()
        self.sec_library()
        self.sec_gamemode()
        self.sec_scene()
        self.sec_selection()
        self.sec_view()
        imgui.end()

    # ---- sections -------------------------------------------------------------------------------------
    def _x_button(self) -> bool:
        try:
            imgui.push_style_color(_v(imgui.Col_.button), V4(0.8, 0.1, 0.1, 1))
            r = imgui.button("X")
            imgui.pop_style_color()
            return bool(r)
        except Exception:
            return bool(imgui.button("X"))

    def load_library(self) -> None:
        try:
            self.log(self.state.open_game_folder(self.lib_path))
        except Exception as e:
            try:                                           # an unpacked data folder given directly
                self.state.set_library(self.lib_path)
            except Exception:
                self.log(f"library: {e}")
        self._lib_key = None

    def pick_game_folder(self) -> None:
        """File > Torrente, el juego folder...: choose where the old game is installed (or unpacked) and load it as library."""
        try:
            import tkinter as tk
            from tkinter import filedialog
            r = tk.Tk(); r.withdraw(); r.attributes("-topmost", True)
            p = filedialog.askdirectory(title=tr("Folder where 'Torrente, el juego' is installed (or its unpacked nfos/ texs/ scns/)"))
            r.destroy()
        except Exception as e:
            self.log(f"no file dialog: {e}")
            return
        if p:
            self.lib_path = p
            self.load_library()

    def library_rows(self) -> list:
        """What the library list shows for the chosen kind, worked out once (not every frame)."""
        from .state_tools import LIB_MODES
        st = self.state
        new = bool(getattr(self, "lib_new", True))
        key = (id(st.library), self.lib_mode, new, len(st.fs.index), self.lib_filter.lower())
        if getattr(self, "_lib_key", None) != key:
            self._lib_key = key
            try:
                items = st.library_items(LIB_MODES[self.lib_mode], new)
                self._lib_total = len(st.library_items(LIB_MODES[self.lib_mode], False)) if new else len(items)
            except Exception as e:
                items, self._lib_total = [], 0
                self.log(f"library: {e}")
            f = self.lib_filter.lower()
            self._lib_rows = [n for n in items if f in os.path.basename(n).lower() or f in n.lower()]
        return self._lib_rows

    def sec_library(self) -> None:
        st = self.state
        if not self._header("Library: Torrente, el juego", False):
            if getattr(self, "_lib_prev", None):           # the section was closed: its preview goes away
                self._lib_prev = None
                self.preview = None
            return
        _, self.lib_path = ui.input_text("folder", self.lib_path)
        if imgui.button("Browse..."):
            self.pick_game_folder()
        imgui.same_line()
        if imgui.button("Load library") and self.lib_path:
            self.load_library()
        lib = st.library
        if lib is None:
            imgui.text_disabled("nothing is imported or replaced in the game folder unless you press Import")
            return
        if not hasattr(self, "lib_new"):
            self.lib_new = True
        self.lib_mode = min(self.lib_mode, 4)
        _, self.lib_mode = ui.combo("show", self.lib_mode, ["models (.nfo)", "maps (.opt + .hm)", "old scenes (convert)",
                                                            "textures", "music"])
        _, self.lib_new = ui.checkbox("only what my game does not have (by file name)", self.lib_new)
        _, self.lib_filter = ui.input_text("filter##lib", self.lib_filter)
        items = self.library_rows()
        imgui.text_disabled(f"{len(items)} shown of {getattr(self, '_lib_total', len(items))}")
        hovered = None
        imgui.begin_child("##liblist", V2(0, 180))
        for n in items[:600]:
            if ui.selectable(f"{os.path.basename(n)}##{n}" if self.lib_mode == 4 else n, n == self.lib_sel):
                self.lib_sel = n
            if imgui.is_item_hovered():
                hovered = n
        imgui.end_child()
        if self.lib_mode == 0:                             # models: the one under the pointer (else the selected one) is shown
            want = hovered or (self.lib_sel if self.lib_sel in items else None)
            if want and want != getattr(self, "_lib_prev", None):
                self.show_library_preview(want)
            elif not want and getattr(self, "_lib_prev", None):
                self._lib_prev = None
                self.preview = None
            imgui.text_disabled("Pointing at a model shows it in front of the camera (nothing is imported yet).")
        elif getattr(self, "_lib_prev", None):
            self._lib_prev = None
            self.preview = None
        if not self.lib_sel or self.lib_sel not in items:
            return
        if self.lib_mode == 0:
            if imgui.button("Import and place in scene"):
                try:
                    rel, rep = st.import_model(self.lib_sel)
                    st.place_model(rel)
                    self.log(rep.summary())
                    self._lib_key = None
                except Exception as e:
                    self.log(f"import failed: {e!r}")
        elif self.lib_mode == 3:
            if imgui.button("Import this texture"):
                self._try(st.import_library_texture, self.lib_sel)
                self._lib_key = None
        elif self.lib_mode == 4:
            if imgui.button("Copy this music to the game"):
                self._try(st.import_library_music, self.lib_sel)
                self._lib_key = None
            imgui.text_disabled("Then choose it in Game mode / sky / spawns / music.")
        elif self.lib_mode == 2:
            _, self.new_scene_name = ui.input_text("new scene", self.new_scene_name)
            from .. import gamemode as gm
            codes = list(gm.MODES)
            _, self.conv_mode = ui.combo("Game mode", getattr(self, "conv_mode", 0), [f"{c} - {gm.MODES[c][0]}" for c in codes])
            if imgui.button("Convert to an Online scene"):
                try:
                    name, text = st.convert_scene(self.lib_sel, self.new_scene_name, codes[self.conv_mode])
                    for line in text.splitlines():
                        self.log(line)
                    self.load(name)
                    self.creating = True
                except Exception as e:
                    self.log(f"conversion failed: {e!r}")
            imgui.text_disabled("level + models + textures + animations; enemies/weapons/scripts are not converted")
        else:
            _, self.new_scene_name = ui.input_text("new scene", self.new_scene_name)
            from .. import gamemode as gm
            codes = list(gm.MODES)
            _, self.conv_mode = ui.combo("Game mode##m", getattr(self, "conv_mode", 0), [f"{c} - {gm.MODES[c][0]}" for c in codes])
            if imgui.button("Import map and create scene"):
                try:
                    rel, rep = st.import_map(self.lib_sel, os.path.splitext(os.path.basename(self.new_scene_name))[0])
                    name = st.new_scene(self.new_scene_name, rel, codes[self.conv_mode])
                    self.load(name)
                    self.creating = True
                    self.log(rep.summary())
                except Exception as e:
                    self.log(f"import failed: {e!r}")
        imgui.text_disabled("textures are converted to TeX2; Online files are never overwritten")

    def weapons_ui(self) -> None:
        """Which weapon groups (keys 1-5 in the game) the players get on this map: a copy of the mode DLL for this map."""
        st = self.state
        if not imgui.tree_node("Weapons allowed on this map"):
            return
        try:
            name = str(st.scene.main_module_name).rstrip("\0")
            if getattr(self, "_wg_for", None) != name:
                self._wg_for = name
                cur = st.weapon_groups()
                self.wg_known = cur is not None
                self.wg = list(cur) if cur is not None else [True] * 5
            imgui.text_wrapped(tr("Each player carries one weapon per group (keys 1 to 5 in the game). Untick a group and nobody "
                                  "gets its weapon on this map."))
            from ..dllpatch import GROUP_NAMES
            self.wg[0] = True                                # the knife always stays
            for g in range(5):
                if g == 0:
                    imgui.begin_disabled()
                _, self.wg[g] = ui.checkbox(f"{g + 1}  " + tr(GROUP_NAMES[g]) + f"##wg{g}", bool(self.wg[g]))
                if g == 0:
                    imgui.end_disabled()
            if not self.wg_known:
                imgui.text_colored(V4(1.0, 0.8, 0.2, 1.0), tr("The mode DLL of this map was not found next to the game: choose it."))
            if imgui.button("Make weapons DLL for this map"):
                try:
                    self.log(st.make_weapons_dll(self.wg))
                    self._wg_for = None
                except ValueError as e:
                    pth = pick_file("Mode DLL of the game", [("DLL", "*.dll")]) if "not found" in str(e) else ""
                    if pth:
                        try:
                            self.log(st.make_weapons_dll(self.wg, pth))
                            self._wg_for = None
                        except Exception as e2:
                            self.log(f"weapons DLL failed: {e2}")
                    elif "not found" not in str(e):
                        self.log(f"weapons DLL failed: {e}")
                except Exception as e:
                    self.log(f"weapons DLL failed: {e!r}")
            imgui.same_line()
            if imgui.button("All weapons again"):
                try:
                    if st.custom_dll_path():                 # this map's own copy: give every group again (other patches stay)
                        self.log(st.make_weapons_dll([True] * 5))
                    else:
                        self.log("this map already uses the game's own mode DLL: every weapon group is given")
                except Exception as e:
                    self.log(f"weapons DLL failed: {e}")
                self._wg_for = None
            imgui.text_disabled("The copy goes to the export folder and into the map's zip; the game's DLL is not touched. "
                                "Every player needs it, like the flag DLL.")
            pk = st.weapon_pickups()
            off = [(n, g) for _r, _w, n, g in pk if 0 <= g < 5 and not self.wg[g]]
            imgui.text(f"{len(pk)} weapons lie on this map to be picked up")
            if off:
                imgui.text_colored(V4(1.0, 0.8, 0.2, 1.0), f"{len(off)} of them are of the groups switched off")
                if imgui.button("Remove those pickups"):
                    try:
                        self.log(st.remove_weapon_pickups(self.wg))
                    except Exception as e:
                        self.log(f"not removed: {e}")
        finally:
            imgui.tree_pop()

    def sec_gamemode(self) -> None:
        st = self.state
        if st.scene is None or not self._header("Game mode / sky / spawns / music", False):
            return
        from .. import gamemode as gm
        codes = list(gm.MODES)
        cur = st.game_mode()
        ch, i = ui.combo("Mode", codes.index(cur) if cur in codes else 0,
                         [f"{c} - {gm.MODES[c][0]}" for c in codes])
        if ch:
            st.set_game_mode(codes[i]); cur = codes[i]
        imgui.text(f"main module: {str(st.scene.main_module_name).rstrip(chr(0))}")
        if imgui.button("Choose mode DLL..."):           # e.g. mp_CaptureLoveboat.dll (the Love Boat's own, with ship sway)
            pth = pick_file("Mode DLL", [("DLL", "*.dll"), (tr("All files"), "*.*")])
            if pth:
                try:
                    self.log(st.set_mode_dll(pth))
                except Exception as e:
                    self.log(f"mode DLL failed: {e!r}")
        imgui.same_line()
        if imgui.button("Standard DLL of this mode"):
            self.log(st.use_standard_mode_dll())
        if any(r.clean_name.lower() == "mp_flag" for r in st.scene.modules):
            if not hasattr(self, "flag_ret"):
                self.flag_ret = 0.0
            fl = next(str(r.module_name).rstrip("\0") for r in st.scene.modules if r.clean_name.lower() == "mp_flag")
            imgui.text(f"flags use: {fl}")
            _, self.flag_ret = ui.drag_float("dropped flag returns after (s)", self.flag_ret, 0.5, 0.0, 60.0)
            if imgui.button("Make flag DLL for this map"):
                try:
                    self.log(st.make_flag_dll(self.flag_ret))
                except ValueError:
                    pth = pick_file("mp_Flag.dll of the game", [("DLL", "*.dll")])
                    if pth:
                        try:
                            self.log(st.make_flag_dll(self.flag_ret, pth))
                        except Exception as e:
                            self.log(f"flag DLL failed: {e!r}")
                except Exception as e:
                    self.log(f"flag DLL failed: {e!r}")
            imgui.same_line()
            if imgui.button("Stock mp_Flag.dll"):
                self.log(st.use_stock_flag_dll())
        self.weapons_ui()
        imgui.text("Items are created where the camera is (engine coords).")
        if imgui.button("Start point team 0"):
            st.gm_add_start(0)
        imgui.same_line()
        if imgui.button("Start point team 1"):
            st.gm_add_start(1)
        if imgui.button("Ring of 14 start points"):
            st.gm_fill(14)
        imgui.same_line()
        if imgui.button("Camera start here"):
            st.gm_add_camera()
        if imgui.button("Health pack (50)"):
            st.gm_add_health("big")
        imgui.same_line()
        if imgui.button("Mini health (25)"):
            st.gm_add_health("small")
        if cur == "B":
            if imgui.button("Flag yellow (team 0)"):
                st.gm_add_flag(0)
            imgui.same_line()
            if imgui.button("Flag red (team 1)"):
                st.gm_add_flag(1)
        if cur == "DO":
            if imgui.button("Bomb zone"):
                st.gm_add_simple("mp_BombZone", "bombzone")
            imgui.same_line()
            if imgui.button("Button"):
                st.gm_add_simple("mp_Boton", "boton")
        music = str(st.scene.ambient_music).rstrip(chr(0))
        names = list(dict.fromkeys(list(gm.KNOWN_MUSIC) + st.music_files() + ([music] if music else [])))
        ch, i = ui.combo("Music", names.index(music) if music in names else 0, names)
        if ch:
            st.set_music(names[i])
        ch, v = ui.input_text("Music file (.ogg / .wav in the game's musica folder)", music)
        if ch:
            st.set_music(v)
        if imgui.button("Import music (.ogg / .wav)..."):
            p = pick_file("Music file", [("Music", "*.ogg *.wav"), (tr("All files"), "*.*")])
            if p:
                try:
                    st.set_music(st.import_music(p))
                except Exception as e:
                    self.log(f"music import failed: {e!r}")
        imgui.text_disabled(st.music_folder() or "musica folder not found next to demo.vpk")
        if imgui.button("Play music" if not self.audio.playing else "Stop music"):
            if self.audio.playing:
                self.audio.stop()
            else:
                path = st.music_path()
                msg = self.audio.play(path) if path else "music file not found in the musica folder: " + music
                self.music_msg = msg or "playing with " + self.audio.backend
        if getattr(self, "music_msg", ""):
            imgui.text_wrapped(self.music_msg)
        self.sec_sky()
        self.sec_map_preview()
        if imgui.button("Check scene"):
            self.gm_report = st.gm_check()
        for line in getattr(self, "gm_report", []) or []:
            imgui.text_wrapped("- " + line)

    def sec_map_preview(self) -> None:
        """Map thumbnail shown by the game's map menu: capture it (Map preview window) or load an image."""
        st = self.state
        imgui.separator()
        imgui.text("Map preview")
        try:
            tid = self.prev_tex_id or (self.gl.texture(st.preview_name() + ".tex") if st.fs.find(f"texs/{st.preview_name()}.tex") else 0)
            if tid:
                image(tid, 128)
            else:
                imgui.text_disabled("(this map has no preview yet)")
        except Exception:
            pass
        if not hasattr(self, "prev_png"):
            self.prev_png = ""
        _, self.prev_png = ui.input_text("preview image", self.prev_png)
        imgui.same_line()
        if imgui.button("Browse...##prev"):
            p = pick_file("Preview image", [("Images", "*.png *.jpg *.jpeg *.bmp *.tga"), (tr("All files"), "*.*")])
            if p:
                self.prev_png = p
        if imgui.button("Load image as preview") and self.prev_png:
            try:
                self.prev_img = st.load_preview_image(self.prev_png.strip().strip('"'))
                if self.prev_tex_id:
                    self.gl.delete_later([self.prev_tex_id])
                self.prev_tex_id = self.gl.upload_rgba(self.prev_img)
                self.log("preview image loaded - press 'Save preview'")
            except Exception as e:
                self.log(f"preview image failed: {e!r}")
        imgui.same_line()
        if imgui.button("Save preview##gm") and self.prev_img is not None:
            try:
                self.log("saved " + st.save_preview(self.prev_img, ("tex", "dds")[self.prev_fmt]))
            except Exception as e:
                self.log(f"preview failed: {e!r}")
        imgui.same_line()
        if imgui.button("Capture window..."):
            self.show_prev = True

    def sec_lights(self) -> None:
        st = self.state
        if not self._header("Lights", True):
            return
        if imgui.button("Add new light..."):
            imgui.open_popup("addlight")
        if imgui.begin_popup("addlight"):
            for t in (LightType.POINT, LightType.SPOT, LightType.DIRECTIONAL, LightType.AMBIENT):
                if imgui.menu_item(t.name + "_LIGHT", "", False)[0]:
                    st.add_light(t)
            imgui.end_popup()
        for i, l in enumerate(list(st.opt.lights)):
            imgui.push_id(f"light{i}")
            dead = self._x_button()
            imgui.same_line()
            if imgui.tree_node(f"{LightType(l.type).name}_LIGHT"):
                ch, v = ui.drag_float3("position", l.position, 5.0)
                if ch:
                    l.position = np.array(v, np.float32); st.dirty_map = True
                if LightType(l.type) in (LightType.SPOT, LightType.DIRECTIONAL):
                    ch, v = ui.drag_float3("direction", l.direction, 0.01)
                    if ch:
                        l.direction = np.array(v, np.float32); st.dirty_map = True
                for attr in ("radius", "start", "end", "cone"):
                    ch, v = ui.drag_float(attr, getattr(l, attr), 5.0)
                    if ch:
                        setattr(l, attr, float(v)); st.dirty_map = True
                for attr in ("diffuse", "ambient", "specular"):
                    c = getattr(l, attr)
                    ch, v = ui.color_edit3(attr, c[:3])
                    if ch:
                        setattr(l, attr, (*v, c[3] if len(c) > 3 else 1.0)); st.dirty_map = True
                imgui.tree_pop()
            imgui.pop_id()
            if dead:
                st.delete_light(l)

    def sec_decals(self) -> None:
        st = self.state
        if not self._header("Decals", True):
            return
        if imgui.button("Add new decal..."):
            names = [t for t in self.state.scene_textures()]
            st.add_decal(names[0] if names else "")
            st.needs_rebake = True
        for i, d in enumerate(list(st.opt.decals)):
            imgui.push_id(f"decal{i}")
            dead = self._x_button()
            imgui.same_line()
            if imgui.tree_node(f"{d.name or '(decal)'}###decal"):
                key = ("decal", i)
                draft = self._drafts.get(key, d.name)
                ch, v = ui.input_text("texture", draft)
                if ch:
                    self._drafts[key] = v
                if imgui.is_item_deactivated_after_edit():
                    d.name = self._drafts.pop(key, d.name).strip(); st.dirty_map = True; st.needs_rebake = True
                ch, v = ui.drag_float3("position", d.position, 5.0)
                if ch:
                    d.position = np.array(v, np.float32); st.dirty_map = True
                for attr in ("scale_x", "scale_y", "z_offset"):
                    ch, v = ui.drag_float(attr, getattr(d, attr), 1.0)
                    if ch:
                        setattr(d, attr, float(v)); st.dirty_map = True
                imgui.tree_pop()
            imgui.pop_id()
            if dead:
                st.delete_decal(d)

    def sec_sky(self) -> None:
        st = self.state
        cur = str(st.scene.sky_texture).rstrip(chr(0))
        opts = st.sky_options()
        names = [k for k, _, _ in opts]
        if cur and cur not in names:
            names.insert(0, cur)
        counts = {k: len(v) for k, v, _ in opts}
        ch, i = ui.combo("Sky", names.index(cur) if cur in names else 0,
                         [f"{k}   ({counts.get(k, 0)} scenes)" for k in names])
        if ch:
            st.set_sky(names[i], self.sky_fog)
            self.rebake()
        _, self.sky_fog = ui.checkbox("also copy fog of a scene with that sky", self.sky_fog)
        info = next((o for o in opts if o[0] == cur), None)
        if info:
            imgui.text_disabled("used by: " + ", ".join(info[1][:3]) + (" ..." if len(info[1]) > 3 else ""))
        try:
            tid = self.gl.texture(cur)
            image(tid, 96)
        except Exception:
            pass
        _, self.sky_png = ui.input_text("sky PNG", getattr(self, "sky_png", ""))
        if imgui.button("Import PNG as sky") and getattr(self, "sky_png", ""):
            try:
                base = os.path.splitext(os.path.basename(self.sky_png))[0]
                nm = base if base.lower().startswith("cielo") else "cielo_" + base
                st.import_sky_png(self.sky_png.strip('"'), nm)
                self.gl.invalidate_textures(); self.rebake()
            except Exception as e:
                self.log(f"sky import failed: {e!r}")
        imgui.same_line()
        if imgui.button("Export sky as PNG"):
            try:
                self.log("sky exported: " + st.export_sky_png(os.path.join(self.state.export_dir())))
            except Exception as e:
                self.log(f"sky export failed: {e!r}")

    def sec_twin_ships(self) -> None:
        st = self.state
        if st.scene is None or not self._header("Twin ships (capture the flag)", False):
            return
        imgui.text_wrapped(tr("Copies the ship of this map next to itself (west), joins both with wooden gangplanks, moves each flag to the "
                              "stern of its ship, gives each team its own spawn points and tints each ship in its flag colour. "
                              "Made for mp_b_loveboat; the original textures are not modified."))
        if not hasattr(self, "twin_gap"):
            self.twin_gap, self.twin_n, self.twin_std = 800.0, 16, True
        _, self.twin_gap = ui.drag_float("gap between ships", self.twin_gap, 10.0, 300.0, 4000.0)
        _, self.twin_n = ui.drag_float("spawn points per team", float(self.twin_n), 1.0, 2.0, 32.0)
        _, self.twin_std = ui.checkbox("use the standard capture-the-flag DLL", self.twin_std)
        if not hasattr(self, "twin_rails"):
            self.twin_rails = False
        _, self.twin_rails = ui.checkbox("handrails on the gangplanks (optional)", self.twin_rails)
        if imgui.button(tr("Make twin ships")):
            try:
                self.log(st.make_twin_ships(self.twin_gap, int(self.twin_n), standard_dll=self.twin_std, rails=self.twin_rails))
            except Exception as e:
                self.log(f"twin ships failed: {e!r}")
        imgui.text_disabled("mode DLL: " + str(st.scene.main_module_name).rstrip("\0"))
        if not hasattr(self, "base_angle"):
            self.base_angle = 0.0
        _, self.base_angle = ui.drag_float("base angle (deg)##twin", self.base_angle, 1.0, -180.0, 180.0)
        if imgui.button("Add bases under the flags"):
            try:
                self.log(st.add_flag_bases(None, self.base_angle))
            except Exception as e:
                self.log(f"flag bases failed: {e!r}")
        imgui.same_line()
        if imgui.button("Re-place both bases (angle / after moving a flag)"):
            try:
                self.log(st.add_flag_bases(None, self.base_angle, replace=True))
            except Exception as e:
                self.log(f"flag bases failed: {e!r}")
        if imgui.button("Use mp_CaptureTheFlag.dll"):
            self.log(st.use_standard_mode_dll())
        try:
            self.bridges_ui()
        except Exception as e:
            imgui.text_disabled(f"gangplanks: {e}")
        if imgui.button("Rebuild gangplanks (ramps over the rails)"):     # with / without handrails as ticked above
            try:
                self.log(st.rebuild_twin_gangplanks(self.twin_gap, self.twin_rails))
            except Exception as e:
                self.log(f"rebuild failed: {e!r}")
        if imgui.button("Move the crates by the middle gangplank 5 m (both ships)"):
            try:
                self.log(st.move_twin_crates(self.twin_gap))
            except Exception as e:
                self.log(f"move failed: {e!r}")
        if imgui.button("Rebuild floor collision (.hm) of twin ships"):
            try:
                self.log(st.rebuild_twin_floor(self.twin_gap))
            except Exception as e:
                self.log(f"rebuild failed: {e!r}")
        imgui.text_disabled("(for maps made before this fix: use the same gap as when they were made)")
    def bridges_ui(self) -> None:
        """Twin ships: add / move / widen / remove each gangplank; its railings, collision and floor go with it."""
        st = self.state
        if not imgui.tree_node("Gangplanks: add, move, remove"):
            return
        try:
            cur = st.twin_bridges()
            sig = tuple((round(b["z"]), round(b["width"]), bool(b["rails"])) for b in cur)
            if getattr(self, "_br_sig", None) != sig:
                self._br_sig = sig
                self.br_edit = [dict(z=float(b["z"]), width=float(b["width"]), rails=bool(b["rails"])) for b in cur]
            if not hasattr(self, "br_new"):
                self.br_new = dict(z=-4800.0, width=640.0, rails=True)
            wanted = None
            if not cur:
                imgui.text_disabled("No gangplanks found between the ships of this map.")
            for k, e in enumerate(self.br_edit):
                imgui.push_id(f"br{k}")
                imgui.text(f"{k + 1}")
                imgui.same_line()
                if imgui.small_button("Go to"):
                    b = cur[k]
                    self.go_to([(b["xa"] + b["xb"]) / 2, b["top"], b["z"]])
                imgui.same_line()
                if imgui.small_button("Remove"):
                    wanted = [x for j, x in enumerate(self.br_edit) if j != k]
                _, e["z"] = ui.drag_float("position along the ships", e["z"], 10.0)
                _, e["width"] = ui.drag_float("width", e["width"], 5.0, 80.0, 2500.0)
                _, e["rails"] = ui.checkbox("railings", e["rails"])
                imgui.pop_id()
                imgui.separator()
            if self.br_edit and imgui.button("Apply the changes"):
                wanted = list(self.br_edit)
            imgui.text(tr("New gangplank"))
            n = self.br_new
            _, n["z"] = ui.drag_float("position along the ships##new", n["z"], 10.0)
            _, n["width"] = ui.drag_float("width##new", n["width"], 5.0, 80.0, 2500.0)
            _, n["rails"] = ui.checkbox("railings##new", n["rails"])
            if imgui.small_button("Where the camera is"):
                n["z"] = float(-st.camera.pos[2])
            imgui.same_line()
            if imgui.small_button("Wide one at the bow"):
                n.update(z=-4800.0, width=640.0, rails=True)
            if imgui.button("Add this gangplank"):
                wanted = list(self.br_edit) + [dict(n)]
            if wanted is not None:
                try:
                    self.log(st.set_twin_bridges(wanted, getattr(self, "twin_gap", 800.0)))
                    self._col_key = None
                except Exception as e:
                    self.log(f"gangplanks: {e}")
                self._br_sig = None
            imgui.text_disabled("Each one goes over the rails with a ramp at both ends; planks, railings, collision boxes and "
                                "floor move or go away together. The position grows towards the stern (the bow is negative).")
        finally:
            imgui.tree_pop()

    def sec_weather(self) -> None:
        st = self.state
        if not self._header("Weather: rain / storm / moon", False):
            return
        imgui.text_wrapped("Rain is not map data: the game-mode DLL starts it only when the map is called mp_dm_marb / mp_b_marb / mp_b_gotico. "
                           "This makes a copy of that DLL that recognises YOUR map (the original is untouched).")
        if not hasattr(self, "rain_dll_path"):
            self.rain_dll_path = ""
        ch, v = imgui.input_text("stock DLL (e.g. mp_deathMatch.dll)", self.rain_dll_path)
        if ch:
            self.rain_dll_path = v.strip().strip('"')
        imgui.same_line()
        if imgui.button("Browse..."):
            p = pick_file("Mode DLL of the game (e.g. mp_deathMatch.dll)", [("DLL", "*.dll"), (tr("All files"), "*.*")])
            if p:
                self.rain_dll_path = p
        if imgui.button("Make rain DLL for this map"):
            try:
                self.log(st.make_rain_dll(self.rain_dll_path, st.export_dir()))
            except Exception as e:
                self.log(f"rain DLL failed: {e!r}")
        if imgui.button("Storm look (cielo_war sky + dark fog)"):
            try:
                st.storm_preset(); self.rebake()
            except Exception as e:
                self.log(f"storm failed: {e!r}")
        imgui.text_disabled("Lightning only exists in the capture DLLs (mp_CaptureChucrch / mp_CaptureThehall).")
        moon = st.moon()
        ch, v = ui.checkbox("Moon (decal 'luna', like Moonlight)", moon is not None)
        if ch:
            try:
                st.set_moon(v); self.rebake()
            except Exception as e:
                self.log(f"moon failed: {e!r}")
        if moon is not None:
            ch, p = ui.drag_float3("moon position", moon.position, 10.0)
            if ch:
                moon.position = np.array(p, np.float32); st.dirty_map = True
            ch, sz = ui.drag_float("moon size", moon.scale_x, 10.0)
            if ch:
                moon.scale_x = moon.scale_y = float(sz); st.dirty_map = True

    def sec_scene(self) -> None:
        st, sc = self.state, self.state.scene
        if not self._header("Scene", True):
            return
        for attr, label in (("fog_near", "Fog near plane"), ("fog_far", "Fog far plane")):
            ch, v = ui.drag_float(label, getattr(sc, attr), 10.0)
            if ch:
                setattr(sc, attr, float(v)); st.dirty_scene = True
        ch, c = ui.color_edit3("Fog color", sc.fog_color_f)
        if ch:
            sc.fog_color = tuple(int(round(x * 255)) for x in c); st.dirty_scene = True
        for attr, label in (("cam_near", "Camera near plane"), ("cam_far", "Camera far plane")):
            ch, v = ui.drag_float(label, getattr(sc, attr), 10.0)
            if ch:
                setattr(sc, attr, float(v)); st.dirty_scene = True
        if imgui.tree_node_ex("Modules", _v(imgui.TreeNodeFlags_.default_open)):
            from ..modules import MODULE_TYPES
            kinds = sorted(MODULE_TYPES)
            if imgui.button("Add new module..."):
                imgui.open_popup("addmod")
            if imgui.begin_popup("addmod"):
                _, self._newname = ui.input_text("object name", self._newname)
                for k in kinds:
                    if imgui.menu_item(MODULE_TYPES[k].KIND, "", False)[0]:
                        rec = st.add_module(k, self._newname)
                        try:
                            st.set_position(Selection("module", rec, self._newname), st._here())
                        except Exception:
                            pass
                        st.selection = Selection("module", rec, self._newname)
                imgui.end_popup()
            if imgui.button("Lock all"):
                self.log(f"{st.lock_all(True)} modules locked")
            imgui.same_line()
            if imgui.button("Unlock all"):
                self.log(f"{st.lock_all(False)} modules unlocked")
            self.hidden_bar()
            for i, rec in enumerate(list(sc.modules)):
                imgui.push_id(f"mod{i}")
                selected = st.selection is not None and st.selection.ref is rec
                flags = _v(imgui.TreeNodeFlags_.selected) if selected else 0
                locked = st.is_locked(rec)
                if padlock("##lock", locked):
                    st.set_locked(rec, not locked)
                imgui.same_line()
                hid = st.is_hidden(rec)
                if eyeball("##eye", hid):
                    st.set_hidden(rec, not hid)
                imgui.same_line()
                name = str(rec.object_name).rstrip("\0")
                if imgui.tree_node_ex(f"{rec.clean_name}  {name}###module", flags):
                    self.module_body(rec)
                    imgui.tree_pop()
                imgui.pop_id()
            imgui.tree_pop()

    def hidden_bar(self) -> None:
        """How many objects are hidden in the editor + the button that shows them all again."""
        n = self.state.hidden_count()
        if not n:
            return
        imgui.text_colored(V4(0.45, 0.85, 1.0, 1.0), f"{n} hidden in the editor (still in the map)")
        imgui.same_line()
        if imgui.small_button("Show all"):
            self.log(self.state.show_all())

    def _model_combo(self, rec, p) -> None:
        """Dropdown with the models of this module type; hovering an entry previews that model in front of the camera
        (like the Models window), clicking uses it, closing the list without choosing keeps the previous model."""
        st = self.state
        key = id(rec)
        opened = bool(imgui.begin_combo("models##mc", str(p.model_name)))
        if opened:
            if getattr(self, "_mc_key", None) != key:
                self._mc_key, self._mc_orig = key, p.model_name
            kind = rec.clean_name.lower()
            _, self.pick_filter = ui.input_text("filter##pm", self.pick_filter)
            _, self.pick_all = ui.checkbox("all models", self.pick_all)
            rows = [(n, 0, "game") for n in st.nfo_names()] if self.pick_all else \
                (st.models_for(kind) or [(n, 0, "game") for n in st.nfo_names()])
            rows = [r for r in rows if self.pick_filter.lower() in r[0].lower()][:500]
            cur = str(p.model_name).replace("\\", "/").lower()
            hovered = None
            chosen = None
            imgui.begin_child("##mclist", V2(420, 260))
            for n, uses, _src in rows:
                if ui.selectable(f"{n}   ({uses} uses)" if uses else n, n.lower() == cur):
                    chosen = n
                if imgui.is_item_hovered():
                    hovered = n
            imgui.end_child()
            if chosen is not None:
                self._mc_orig = chosen
                self._preview_model(p, chosen)
                self._mc_hover = None
                self.preview = None
                imgui.close_current_popup()
            elif hovered is not None and hovered != getattr(self, "_mc_hover", None):
                # same preview as the Models window: the model shown in front of the camera (the scene is not touched)
                self._mc_hover = hovered
                self.show_preview(hovered, quiet=True)
            imgui.end_combo()
        elif getattr(self, "_mc_key", None) == key:
            # list closed: keep what was chosen (the hover preview goes away)
            self._preview_model(p, self._mc_orig)
            self._mc_key = None
            if getattr(self, "_mc_hover", None) is not None:
                self._mc_hover = None
                self.preview = None

    # nicer names for raw fields ("*" = any module); the stored field keeps its name
    FIELD_LABELS = {
        "*": {"unk_string1": "animation (.KEY) name - empty in the game", "unk_string2": "unused text - leave empty"},
        "MPSalud": {"health": "health given (0 = 50)"},
        "MPFlag": {"team": "team (0 / 1)"},
        "MPSoundSource": {"max_distance": "heard up to (max distance)", "min_distance": "full volume inside (min distance)"},
        "CParticleSystem": {"velocity": "start speed", "spread": "spread (0 = a jet, 1 = everywhere)", "radius": "size of the source",
                            "rate": "particles per second", "life": "life (seconds)", "acceleration": "push (gravity = -1000 Y)",
                            "damping": "air drag (1 = none)", "size_start": "size at birth", "size_end": "size at the end",
                            "sound": "sound object (optional)", "unk_a": "unknown A", "unk_b": "unknown B"},
    }

    def _preview_model(self, p, name: str) -> None:
        if str(p.model_name) != name:
            p.model_name = name
            self.state.dirty_scene = self.state.needs_rebake = True

    def module_body(self, rec) -> None:
        """Fields of a module; greyed out (read only) while its padlock is closed."""
        locked = self.state.is_locked(rec)
        if locked:
            imgui.text_colored(V4(1.0, 0.62, 0.15, 1.0), tr("Locked - open the padlock to edit"))
            imgui.begin_disabled(True)
        try:
            self._module_body(rec)
        finally:
            if locked:
                imgui.end_disabled()
        if locked and imgui.button("Go to##locked"):     # finding a locked object is still allowed
            st = self.state
            sel = Selection("module", rec, rec.object_name)
            try:
                st.camera.pos = st.position_of(sel) * [1, 1, -1] + [0, 150, 400]
                st.camera.face(st.position_of(sel) * [1, 1, -1])
            except Exception:
                pass

    def _module_body(self, rec) -> None:
        st = self.state
        imgui.text(f"object: {rec.object_name}")
        if rec.clean_name.lower() == "mp_flag":
            if not hasattr(self, "base_angle"):
                self.base_angle = 0.0
            _, self.base_angle = ui.drag_float("base angle (deg)", self.base_angle, 1.0, -180.0, 180.0)
            if imgui.button("Add base (pedestal) under this flag"):
                try:
                    self.log(st.add_flag_bases([rec], self.base_angle))
                except Exception as e:
                    self.log(f"flag base failed: {e!r}")
            imgui.same_line()
            if imgui.button("Re-place base here"):            # after moving the flag or changing the angle
                try:
                    self.log(st.add_flag_bases([rec], self.base_angle, replace=True))
                except Exception as e:
                    self.log(f"flag base failed: {e!r}")
        p = rec.parsed
        if p is None:
            imgui.text_disabled("(not decoded - kept as raw bytes)")
            return
        if rec.clean_name.lower() == "mp_ccar":
            if imgui.button("Make it indestructible (scenery + collision box)"):
                try:
                    self.log(st.car_to_scenery(rec))
                except Exception as e:
                    self.log(f"not changed: {e}")
            imgui.same_line()
            if imgui.button("All the cars of the map"):
                try:
                    self.log(st.cars_to_scenery())
                except Exception as e:
                    self.log(f"not changed: {e}")
            imgui.text_disabled("mp_CCar is the car that blows up; as RenderNFO it is only drawn, so a box is added to keep it solid.")
        sel = Selection("module", rec, rec.object_name)
        try:
            ch, v = ui.drag_float3("position", st.position_of(sel), 1.0)    # Ctrl+click on a field = type the value
            if ch:
                st.set_position(sel, v)
        except Exception:
            pass
        m = getattr(p, "transform", None)
        if isinstance(m, np.ndarray) and not hasattr(p, "angle") and "transform" in getattr(p, "__dataclass_fields__", {}):
            _, e, sc = decompose(m)
            ch1, e2 = ui.drag_float3("rotation (deg)", e, 0.5)
            ch2, sc2 = ui.drag_float3("scale", sc, 0.01)
            if ch1 or ch2:                                  # only rebuilt when edited, so untouched matrices stay as they were
                p.transform = compose(m[3, :3], e2, sc2).astype(np.float32)
                st.dirty_scene = st.needs_rebake = True
        elif hasattr(p, "angle"):
            ch, a = ui.drag_float("angle (deg)", float(np.degrees(p.angle)), 1.0)
            if ch:
                p.angle = float(np.radians(a)); st.dirty_scene = True
        if hasattr(p, "target") and hasattr(p, "position") and not hasattr(p, "model_name"):
            pos_ = np.array(p.position, np.float64); d_ = np.array(p.target, np.float64) - pos_
            dist_ = float(np.linalg.norm(d_))
            head_ = float(np.degrees(np.arctan2(d_[0], d_[2]))) if dist_ > 1e-6 else 0.0
            pit_ = float(np.degrees(np.arcsin(np.clip(d_[1] / dist_, -1, 1)))) if dist_ > 1e-6 else 0.0
            ch1, head_ = ui.drag_float("angle (deg)", head_, 1.0)           # same two fields as CStartPoint
            ch1r, hr_ = ui.drag_float("angle", float(np.radians(head_)), 0.01)
            if ch1r:
                head_, ch1 = float(np.degrees(hr_)), True
            ch2, pit_ = ui.drag_float("look pitch (deg)", pit_, 0.5)
            ch3, dist_ = ui.drag_float("look distance", dist_ if dist_ > 1e-6 else 1000.0, max(5.0, dist_ * 0.002))
            if ch1 or ch2 or ch3:
                hr, pr = np.radians(head_), np.radians(np.clip(pit_, -89, 89))
                t_ = pos_ + max(dist_, 1.0) * np.array([np.cos(pr) * np.sin(hr), np.sin(pr), np.cos(pr) * np.cos(hr)])
                p.target = tuple(float(x) for x in t_); st.dirty_scene = True
            if imgui.button("Bring look-at close (1000 units)") and dist_ > 1e-6:
                p.target = tuple(float(x) for x in pos_ + d_ / dist_ * 1000.0); st.dirty_scene = True
            ch, v = ui.drag_float3("look at (raw)", np.array(p.target, np.float64), max(1.0, dist_ * 0.002))
            if ch:
                p.target = tuple(float(x) for x in v); st.dirty_scene = True
        if hasattr(p, "model_name"):
            ch, v = ui.input_text("model_name", p.model_name)
            if ch:
                p.model_name = v; st.dirty_scene = st.needs_rebake = True
            self._model_combo(rec, p)
            if hasattr(p, "tail") and hasattr(p, "key_name"):
                cur_key = p.key_name or ""
                ck = (str(p.model_name), len(st.all_keys()))
                if getattr(self, "_ks_cache", (None,))[0] != ck:            # computed once per model, not every frame
                    cands = st.key_candidates(p.model_name)
                    self._ks_cache = (ck, [""] + cands + [k for k in st.all_keys() if k not in set(cands)])
                ks = self._ks_cache[1]
                ch, i = ui.combo("animation (.KEY)", ks.index(cur_key) if cur_key in ks else 0, [k or "(none)" for k in ks])
                if ch:
                    st.set_module_key(rec, ks[i])
                sw = st.default_sound_for(p.model_name)
                if imgui.button(tr("Add sound here") + (f" ({sw.split(chr(92))[-1]})" if sw else "")):
                    st.add_model_sound(rec)
                if p.key_name:
                    playing = self.anim_rec is rec
                    if imgui.button(tr("Stop animation") if playing else tr("Play animation")):
                        self.stop_anim() if playing else self.start_anim(rec, p.key_name)
                    imgui.same_line()
                    ch, self.anim_speed = ui.drag_float("speed", self.anim_speed, 0.05, 0.05, 4.0)
        nice = self.FIELD_LABELS.get(type(p).__name__, {})
        for name, val in st.editable_fields(p):
            if name in ("model_name", "position", "target"):
                continue
            label = (nice.get(name) or self.FIELD_LABELS["*"].get(name) or name) + "##" + name
            if isinstance(val, str):
                ch, nv = ui.input_text(label, val)
            elif isinstance(val, (int, bool)):
                ch, nv = ui.input_int(label, val)
            elif isinstance(val, float):
                small = abs(val) <= 2.0 and name in ("spread", "damping", "unk_a", "unk_b")
                ch, nv = ui.drag_float(label, val, 0.01 if small else 1.0)
            elif isinstance(val, tuple) and len(val) == 3:
                ch, nv = ui.drag_float3(label, val, 5.0)
                nv = tuple(float(x) for x in nv)
            else:
                ch, nv = False, None
            if ch and nv is not None:
                setattr(p, name, nv); st.dirty_scene = True
                if hasattr(p, "model_name"):               # only what is drawn as a model needs the scene baked again
                    st.needs_rebake = True
        for name in ("color_start", "color_end"):          # particle colours: red, green, blue + opacity (0-255)
            c = getattr(p, name, None)
            if not (isinstance(c, tuple) and len(c) == 4):
                continue
            ch1, rgb = ui.color_edit3(("colour at birth" if name == "color_start" else "colour at the end") + "##" + name,
                                      [c[0] / 255.0, c[1] / 255.0, c[2] / 255.0])
            ch2, al = ui.drag_float(("opacity at birth" if name == "color_start" else "opacity at the end") + "##a" + name,
                                    float(c[3]), 1.0, 0.0, 255.0)
            if ch1 or ch2:
                setattr(p, name, (*[int(round(max(0.0, min(1.0, float(x))) * 255)) for x in rgb], int(max(0, min(255, round(al))))))
                st.dirty_scene = True
        if type(p).__name__ in ("MPSalud", "MPFlag"):
            imgui.text_disabled("The two texts are empty in every map of the game (an animation name and an unused text).")
        if type(p).__name__ == "MPSalud":
            imgui.text_disabled("Health packs have no respawn time here: the game's mp_salud.dll decides when they come back.")
        if imgui.button("Select"):
            st.selection = sel
        imgui.same_line()
        if imgui.button("Move here"):                      # put the object where the camera is (engine coordinates)
            st.set_position(sel, st.camera.pos * [1, 1, -1])
        imgui.same_line()
        if imgui.button("Go to"):
            try:
                st.camera.pos = st.position_of(sel) * [1, 1, -1] + [0, 150, 400]
                st.camera.face(st.position_of(sel) * [1, 1, -1])
            except Exception:
                pass
        imgui.same_line()
        if imgui.button("Duplicate"):
            st.duplicate_module(rec)
        imgui.same_line()
        if imgui.button("Delete"):
            st.delete_module(rec)

    # ------------------------------------------------------------------------------ Map Mesh (static meshes + props, with padlocks)
    def _mesh_rows(self):
        """(index, triangles, textures, lo, hi, props) per static mesh, cached until the scene is baked again."""
        st = self.state
        key = (id(st.geometry), id(st.opt), len(st.opt.meshes) if st.opt else 0, len(st.opt.props) if st.opt else 0)
        if getattr(self, "_mesh_rows_key", None) != key:
            self._mesh_rows_key = key
            self._mesh_rows_cache = st.map_parts() if st.opt is not None else []
        return self._mesh_rows_cache

    def _go_to_box(self, lo, hi) -> None:
        st = self.state
        c = (np.asarray(lo, np.float64) + np.asarray(hi, np.float64)) / 2 * [1, 1, -1]
        r = float(max(np.max(np.asarray(hi) - np.asarray(lo)), 200.0))
        st.camera.pos = c + np.array([0.0, r * 0.6 + 150.0, r * 0.9 + 300.0])
        st.camera.face(c)

    def sec_map_mesh(self) -> None:
        st = self.state
        if st.opt is None or not self._header("Map Mesh", False):
            return
        if not hasattr(self, "mesh_filter"):
            self.mesh_filter, self.mesh_sel_i, self.prop_sel_i = "", -1, -1
        rows = self._mesh_rows()
        imgui.text(f"{len(st.opt.meshes)} meshes, {len(st.opt.props)} props")
        _, self.mesh_filter = ui.input_text("filter (texture / #index)##mm", self.mesh_filter)
        if imgui.button("Lock all##mm"):
            self.log(f"{st.lock_all(True, 'mesh')} meshes locked")
        imgui.same_line()
        if imgui.button("Unlock all##mm"):
            self.log(f"{st.lock_all(False, 'mesh')} meshes unlocked")
        imgui.push_id("mmhid")
        self.hidden_bar()
        imgui.pop_id()
        f = self.mesh_filter.lower().strip()
        shown = [r for r in rows if not f or f in (" ".join(r[2]) + f" #{r[0]}").lower()][:800]
        imgui.begin_child("##mapmesh", V2(0, 220))
        for i, tris, tex, lo, hi, users in shown:
            if i >= len(st.opt.meshes):
                continue
            me = st.opt.meshes[i]
            imgui.push_id(f"mm{i}")
            locked = st.is_locked(me, "mesh")
            if padlock("##lk", locked):
                st.set_locked(me, not locked, "mesh")
            imgui.same_line()
            hid = st.is_hidden(me, "mesh")
            if eyeball("##eye", hid):
                st.set_hidden(me, not hid, "mesh")
            imgui.same_line()
            label = f"#{i}  {tris} tris  {', '.join(tex)[:30]}" + (f"  x{users} props" if users else "")
            sel = st.selection is not None and st.selection.ref is me
            if ui.selectable(label, sel):
                self.mesh_sel_i = i
                if not locked:
                    st.selection = Selection("mesh", me, f"mesh {i}")
                if imgui.is_mouse_double_clicked(0):
                    self._go_to_box(lo, hi)
            imgui.pop_id()
        imgui.end_child()
        if 0 <= self.mesh_sel_i < len(st.opt.meshes) and imgui.button("Go to mesh"):
            r = next((r for r in rows if r[0] == self.mesh_sel_i), None)
            if r:
                self._go_to_box(r[3], r[4])
        imgui.text_disabled("Double click = go to.  Closed padlock = cannot be picked, moved or deleted.")
        if st.opt.props and imgui.tree_node("Props (instances of meshes)"):
            if imgui.button("Lock all##pp"):
                self.log(f"{st.lock_all(True, 'prop')} props locked")
            imgui.same_line()
            if imgui.button("Unlock all##pp"):
                self.log(f"{st.lock_all(False, 'prop')} props unlocked")
            imgui.begin_child("##mapprops", V2(0, 160))
            for k, pr in enumerate(st.opt.props[:800]):
                if f and f not in f"#{pr.mesh_index} prop {k}":
                    continue
                imgui.push_id(f"pp{k}")
                locked = st.is_locked(pr, "prop")
                if padlock("##lk", locked):
                    st.set_locked(pr, not locked, "prop")
                imgui.same_line()
                hid = st.is_hidden(pr, "prop")
                if eyeball("##eye", hid):
                    st.set_hidden(pr, not hid, "prop")
                imgui.same_line()
                t = np.asarray(pr.transform)[3, :3]
                if ui.selectable(f"prop {k}  (mesh #{pr.mesh_index})  {t[0]:.0f} {t[1]:.0f} {t[2]:.0f}",
                                 st.selection is not None and st.selection.ref is pr):
                    if not locked:
                        st.selection = Selection("prop", pr, f"prop {k}")
                    if imgui.is_mouse_double_clicked(0):
                        self._go_to_box(t - 150, t + 150)
                imgui.pop_id()
            imgui.end_child()
            imgui.tree_pop()

    def sec_selection(self) -> None:
        st = self.state
        sel = st.selection
        if id(sel) != getattr(self, "_last_sel", None):          # a new pick opens this section
            self._last_sel = id(sel)
            if sel is not None:
                imgui.set_next_item_open(True)
        if not self._header("Selection (click in the view)", False):
            return
        if sel is None:
            imgui.text("nothing selected")
            return
        imgui.text(f"{sel.kind}: {sel.label}")
        for line in st.describe(sel)[2:]:
            imgui.text_disabled(line)
        if sel.kind == "module":
            try:
                self.module_body(sel.ref)
            except Exception as e:
                imgui.text_disabled(str(e))
            return
        locked = st.is_locked(sel.ref, sel.kind)
        if padlock("##sellock", locked):
            st.set_locked(sel.ref, not locked, sel.kind)
            if not locked:                                   # just locked: it is deselected
                return
        imgui.same_line()
        if eyeball("##seleye", st.is_hidden(sel.ref, sel.kind)):
            st.set_hidden(sel.ref, not st.is_hidden(sel.ref, sel.kind), sel.kind)
            if st.selection is None:                         # just hidden: it is deselected
                return
        imgui.same_line()
        imgui.text(tr("Locked") if locked else tr("Editable"))
        if locked:
            imgui.begin_disabled(True)
        try:
            self._selection_fields(sel)
        finally:
            if locked:
                imgui.end_disabled()

    def _selection_fields(self, sel) -> None:
        st = self.state
        try:
            ch, v = ui.drag_float3("position", st.position_of(sel), 1.0)
            if ch:
                st.set_position(sel, v)
            if st.has_matrix(sel) or (sel.kind == "mesh" and st.can_scale(sel)):
                ch, v = ui.drag_float3("rotation (deg)", st.rotation_of(sel), 0.5)
                if ch:
                    st.set_rotation(sel, v)
                ch, v = ui.drag_float3("scale", st.scale_of(sel), 0.01)
                if ch:
                    st.set_scale(sel, np.maximum(v, 0.01))
            elif sel.kind == "mesh":
                imgui.text_disabled("rotation / scale: this mesh is shared by props (edit those)")
        except Exception as e:
            imgui.text_disabled(str(e))
        self.mesh_texture_ui(sel)

    def mesh_texture_ui(self, sel) -> None:
        st = self.state
        mesh = st.mesh_of(sel)
        if mesh is None or not mesh.materials:
            return
        if imgui.tree_node("Change texture"):
            n = len(mesh.materials)
            self.mat_i = min(getattr(self, "mat_i", 0), n - 1)
            labels = [f"{k}: {mesh.materials[k].textures[0] if mesh.materials[k].textures else '-'}" for k in range(n)]
            _, self.mat_i = ui.combo("material", self.mat_i, labels)
            _, self.tex_filter = ui.input_text("filter", getattr(self, "tex_filter", ""))
            f = self.tex_filter.lower()
            cand = [os.path.basename(p) for p in st.fs.list("texs", ".tex") if f in os.path.basename(p)][:14]
            for c in cand:
                if ui.selectable(c, False):
                    try:
                        st.set_mesh_texture(mesh, self.mat_i, c); self.rebake()
                    except Exception as e:
                        self.log(f"could not change texture: {e!r}")
            _, self.tex_png = ui.input_text("or PNG file", getattr(self, "tex_png", ""))
            if imgui.button("Use this PNG for the material") and self.tex_png:
                try:
                    cur = str(mesh.materials[self.mat_i].textures[0])
                    i = next(k for k, m in enumerate(st.opt.meshes) if m is mesh)
                    st.import_map_texture(self.tex_png.strip('"'), replace=cur, mesh_index=i)
                    self.gl.invalidate_textures(); self.rebake()
                except Exception as e:
                    self.log(f"could not import: {e!r}")
            imgui.tree_pop()

    def sec_view(self) -> None:
        o = self.opts
        if not self._header("View options", False):
            return
        for key, label in (("cull", "back-face culling"), ("decals", "decals"), ("scene_fog", "scene fog"), ("sky", "sky")):
            o[key] = ui.checkbox(label, o[key])[1]
        _, o["mode"] = ui.combo("transparent sort", o["mode"], ["per triangle (fixed)", "per texture (legacy)"])
        _, o["gamma"] = ui.slider_float("gamma", o["gamma"], 0.5, 2.5)
        _, o["speed"] = ui.slider_float("camera speed", o["speed"], 50, 5000)
        _, self.state.camera.fov = ui.slider_float("fov", self.state.camera.fov, 30, 120)

    # ------------------------------------------------------------------------------ textures window
    def win_textures(self) -> None:
        st = self.state
        imgui.set_next_window_pos(V2(self.win_w - 380, 110), _v(imgui.Cond_.first_use_ever))
        imgui.set_next_window_size(V2(370, 520), _v(imgui.Cond_.first_use_ever))
        imgui.begin("Scene Textures")
        names = st.scene_textures()
        if self.tex_selected:
            t = st.fs.texture(self.tex_selected)
            if t:
                imgui.text(f"{self.tex_selected}  {t.width}x{t.height} {'DXT5' if t.fmt else 'DXT1'} mips={t.mip_count}")
                base = os.path.splitext(os.path.basename(self.tex_selected.replace('\\', '/')))[0]
                png = os.path.join(self.state.export_dir(), base + ".png")
                if imgui.button("Export PNG"):
                    os.makedirs(os.path.dirname(png), exist_ok=True); t.to_png(png); self.log(f"wrote {png}")
                imgui.same_line()
                if not hasattr(self, "tex_keep"):
                    self.tex_keep, self.tex_global = True, False
                if imgui.button("Replace from image..."):
                    p = pick_file("Image for " + base + ".tex",
                                  [("Images", "*.png *.jpg *.jpeg *.bmp *.tga"), (tr("All files"), "*.*")])
                    if p:
                        try:
                            if self.tex_global:
                                msg = st.replace_texture_from_image(self.tex_selected, p, self.tex_keep)
                            else:
                                msg = st.replace_texture_for_map(self.tex_selected, p, self.tex_keep)
                                self.tex_selected = st.local_texture_name(base) + ".tex"
                            self.log(msg)
                            self.gl.invalidate_textures(); self.gl.last_sort_pos = None
                        except Exception as e:
                            self.log(f"replace failed: {e}")
                _, self.tex_keep = ui.checkbox("keep the original size", self.tex_keep)
                _, self.tex_global = ui.checkbox("change it for ALL maps (overwrite the original file)", self.tex_global)
                if not self.tex_global:
                    imgui.text_disabled("Only this map: a new texture <map>__<name>.tex; the original stays.")
                pre = st.map_stem() + "__"
                if base.lower().startswith(pre.lower()):
                    if imgui.button("Back to the original texture"):
                        try:
                            self.log(st.back_to_original_texture(self.tex_selected))
                            self.tex_selected = base[len(pre):] + ".tex"
                        except Exception as e:
                            self.log(f"failed: {e}")
                elif imgui.button("Restore original file (.bak)"):
                    try:
                        self.log(st.restore_texture(self.tex_selected))
                        self.gl.invalidate_textures(); self.gl.last_sort_pos = None
                    except Exception as e:
                        self.log(f"restore failed: {e}")
        else:
            imgui.text_disabled("click a texture")
        imgui.separator()
        size = 64.0
        cols = max(1, int(imgui.get_content_region_avail().x // (size + 10)))
        imgui.begin_child("##texgrid", V2(0, 0))
        for i, n in enumerate(names):
            image(self.gl.texture(n), size)
            if imgui.is_item_hovered():
                imgui.set_tooltip(n)
                if imgui.is_mouse_clicked(0):
                    self.tex_selected = n
            if (i + 1) % cols:
                imgui.same_line()
        imgui.end_child()
        imgui.end()

    # ------------------------------------------------------------------------------ models browser (3D preview)
    def win_models(self) -> None:
        st = self.state
        imgui.set_next_window_pos(V2(self.win_w - 380, 650), _v(imgui.Cond_.first_use_ever))
        imgui.set_next_window_size(V2(370, 360), _v(imgui.Cond_.first_use_ever))
        imgui.begin("Models (.nfo)")
        kinds = st.kinds_with_models()
        _, self.models_kind = ui.combo("module type", self.models_kind, ["(all models -> RenderNFO)"] + kinds)
        kind = kinds[self.models_kind - 1] if self.models_kind > 0 else "rendernfo"
        if st.library is not None:
            _, self.models_lib = ui.checkbox("include models from the library", self.models_lib)
        _, self.models_filter = ui.input_text("filter##models", self.models_filter)
        if self.models_kind == 0:
            rows = [(n, 0, "game") for n in st.nfo_names()]
            if self.models_lib and st.library is not None:
                have = {n.lower() for n in st.nfo_names()}
                rows += [("nfos/" + n, 0, "lib") for n in st.library.models() if ("nfos/" + n).lower() not in have]
        else:
            rows = st.models_for(kind, self.models_lib)
        rows = [r for r in rows if self.models_filter.lower() in r[0].lower()]
        imgui.text_disabled(f"{len(rows)} models - click one to see it in the 3D view")
        imgui.begin_child("##modlist", V2(0, -34))
        for n, uses, src in rows[:1500]:
            label = n + (f"   ({uses} uses)" if uses else "") + ("   [library]" if src == "lib" else "")
            if ui.selectable(label, n == self.model_sel):
                self.model_sel = n
                if src == "lib":                       # bring it into the game folder first (never overwrites)
                    try:
                        rel, _ = st.import_model(n[len("nfos/"):])
                        self.model_sel = "nfos/" + rel
                    except Exception as e:
                        self.log(f"import failed: {e!r}")
                        continue
                self.show_preview(self.model_sel)
        imgui.end_child()
        if self.preview is not None and imgui.button(f"Place as {kind}"):
            st.place_model(os.path.relpath(os.path.join(st.fs.root, self.model_sel), os.path.join(st.fs.root, "nfos")), kind)
            self.clear_preview()
        imgui.same_line()
        if imgui.button("Re-place here") and self.model_sel:
            self.show_preview(self.model_sel)
        imgui.same_line()
        if imgui.button("Hide preview"):
            self.clear_preview()
        imgui.end()

    def preview_source(self, lib) -> None:
        """Where the preview renderer reads textures / models from: the game (None) or the library."""
        pfs = self.glp.fs
        if getattr(pfs, "lib", None) is not lib:
            pfs.lib = lib
            self.glp.delete_later([t for t in self.glp.textures.values() if t != self.glp.white])
            self.glp.textures.clear()

    def show_library_preview(self, rel: str) -> None:
        """A model of the 'Torrente, el juego' library in front of the camera, with its own textures (nothing is imported)."""
        try:
            self.preview_source(self.state.library)
            g, rec = self.state.preview_library_model(rel, self.glp.fs)
            self.glp.set_geometry(g)
            self.preview = (g, rec)
            self._lib_prev = rel
        except Exception as e:
            self.preview = None
            self._lib_prev = None
            self.log(f"preview failed: {e!r}")

    def show_preview(self, name: str, quiet: bool = False) -> None:
        try:
            self.preview_source(None)
            self._lib_prev = None
            g, rec = self.state.preview_geometry(name)
            self.glp.set_geometry(g)
            self.preview = (g, rec)
            if not quiet:
                self.log(f"preview {name}: {g.stats.get('triangles', 0) + g.stats.get('transparent_triangles', 0)} triangles")
                if not g.instances:
                    self.log("(that model has no drawable meshes)")
        except Exception as e:
            self.preview = None
            self.log(f"preview failed: {e!r}")

    def start_anim(self, rec, key_name: str) -> None:
        """Play the .KEY of a module on its model: the static copy is hidden and a posed copy is drawn each frame."""
        st = self.state
        key = st.fs.keys(key_name)
        if key is None or key.frames == 0:
            self.log(f"animation not found: {key_name}")
            return
        self.preview = None
        self.anim_rec, self.anim_key, self.anim_name = rec, key, key_name
        self.anim_t0, self.anim_last = time.time(), -1
        st.skip_recs = {id(rec)}
        st.needs_rebake = True
        self.log(f"playing {key_name}: {key.frames} frames")

    def stop_anim(self) -> None:
        if self.anim_rec is None:
            return
        self.anim_rec = self.anim_key = None
        self.state.skip_recs = set()
        self.state.needs_rebake = True

    def update_anim(self) -> None:
        from ..animate import KEY_FPS
        st = self.state
        if self.anim_rec not in st.scene.modules:          # the module was deleted / another scene opened
            self.stop_anim()
            return
        n = self.anim_key.frames
        frame = ((time.time() - self.anim_t0) * KEY_FPS * self.anim_speed) % n
        if int(frame) != self.anim_last:                   # the key has one pose per frame: rebuild only when it changes
            self.anim_last = int(frame)
            try:
                self.glp.set_geometry(st.anim_geometry(self.anim_rec, self.anim_key, float(int(frame))))
            except Exception as e:
                self.log(f"animation failed: {e!r}")
                self.stop_anim()

    def clear_preview(self) -> None:
        self.preview = None
        self.model_sel = ""
