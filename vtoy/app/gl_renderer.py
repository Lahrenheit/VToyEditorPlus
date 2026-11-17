"""Thin OpenGL 3.3 layer. All geometry comes pre-baked from vtoy.render.geometry; nothing here decides *what* to draw
except the draw order. NOTE: written without access to a GPU - see README ("untested")."""
from __future__ import annotations

import ctypes
import os
from typing import Dict, Optional

import numpy as np
from OpenGL import GL as gl

from ..render.geometry import SceneGeometry, cube_wire_edges, decal_quads

SHADERS = os.path.join(os.path.dirname(__file__), "shaders")


def _compile(src: str, kind) -> int:
    s = gl.glCreateShader(kind)
    gl.glShaderSource(s, src)
    gl.glCompileShader(s)
    if not gl.glGetShaderiv(s, gl.GL_COMPILE_STATUS):
        raise RuntimeError(gl.glGetShaderInfoLog(s).decode(errors="replace"))
    return s


def make_program(vert: str, frag: str) -> int:
    with open(os.path.join(SHADERS, vert)) as f:
        v = _compile(f.read(), gl.GL_VERTEX_SHADER)
    with open(os.path.join(SHADERS, frag)) as f:
        fr = _compile(f.read(), gl.GL_FRAGMENT_SHADER)
    p = gl.glCreateProgram()
    gl.glAttachShader(p, v); gl.glAttachShader(p, fr)
    gl.glLinkProgram(p)
    if not gl.glGetProgramiv(p, gl.GL_LINK_STATUS):
        raise RuntimeError(gl.glGetProgramInfoLog(p).decode(errors="replace"))
    gl.glDeleteShader(v); gl.glDeleteShader(fr)
    return p


def sky_sphere(radius: float = 15000.0, rings: int = 24, segs: int = 48):
    """Unit-ish sphere around the camera. u = azimuth, v = 0 at the zenith, 0.5 at the horizon, 1 at the nadir
    (the game's sky textures are painted that way: sky on top, fog colour in the lower half)."""
    vs, ids = [], []
    for r in range(rings + 1):
        el = np.pi / 2 - np.pi * r / rings
        for k in range(segs + 1):
            az = 2 * np.pi * k / segs
            p = np.array([np.cos(el) * np.cos(az), np.sin(el), np.cos(el) * np.sin(az)])
            vs.append([*(p * radius), *(-p), k / segs, r / rings])
    for r in range(rings):
        for k in range(segs):
            a = r * (segs + 1) + k; b = a + segs + 1
            ids += [a, b, a + 1, a + 1, b, b + 1]
    return np.asarray(vs, np.float32), np.asarray(ids, np.uint32)


class GLRenderer:
    STRIDE = 8 * 4

    def __init__(self, fs):
        self.fs = fs
        self.scene_prog = make_program("scene_shader.vert", "scene_shader.frag")
        self.dbg_prog = make_program("debug_shader.vert", "debug_shader.frag")
        self.textures: Dict[str, int] = {}
        self.white = self._upload_rgba(np.full((1, 1, 4), 255, np.uint8))
        # opaque / transparent / decal buffers (VAO, VBO, EBO)
        self.opaque = []                                  # [(vao, vbo, ebo, count, tex, two_sided)]
        self.t_vao, self.t_vbo, self.t_ebo = self._make_vao(dynamic=True)
        self.d_vao, self.d_vbo, self.d_ebo = self._make_vao(dynamic=True)
        self.geometry: Optional[SceneGeometry] = None
        self.t_runs = []
        self.cube = gl.glGenVertexArrays(1), gl.glGenBuffers(1)
        gl.glBindVertexArray(self.cube[0]); gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self.cube[1])
        edges = cube_wire_edges(); self.cube_n = len(edges)
        gl.glBufferData(gl.GL_ARRAY_BUFFER, edges.nbytes, edges, gl.GL_STATIC_DRAW)
        gl.glEnableVertexAttribArray(0); gl.glVertexAttribPointer(0, 3, gl.GL_FLOAT, False, 12, None)
        self.tmp_lines = gl.glGenVertexArrays(1), gl.glGenBuffers(1)
        self.last_sort_pos = None
        self.sky_vao, self.sky_vbo, self.sky_ebo = self._make_vao(False)
        v, i = sky_sphere()
        gl.glBufferData(gl.GL_ARRAY_BUFFER, v.nbytes, v, gl.GL_STATIC_DRAW)
        gl.glBindBuffer(gl.GL_ELEMENT_ARRAY_BUFFER, self.sky_ebo)
        gl.glBufferData(gl.GL_ELEMENT_ARRAY_BUFFER, i.nbytes, i, gl.GL_STATIC_DRAW)
        self.sky_n = len(i)

    # ------------------------------------------------------------------ resources
    def _make_vao(self, dynamic: bool):
        vao = gl.glGenVertexArrays(1); vbo = gl.glGenBuffers(1); ebo = gl.glGenBuffers(1)
        gl.glBindVertexArray(vao)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, vbo); gl.glBindBuffer(gl.GL_ELEMENT_ARRAY_BUFFER, ebo)
        for i, (n, off) in enumerate(((3, 0), (3, 12), (2, 24))):
            gl.glEnableVertexAttribArray(i)
            gl.glVertexAttribPointer(i, n, gl.GL_FLOAT, False, self.STRIDE, ctypes.c_void_p(off))
        return vao, vbo, ebo

    def _upload_rgba(self, rgba: np.ndarray, mips: bool = True) -> int:
        h, w = rgba.shape[:2]
        t = gl.glGenTextures(1)
        gl.glBindTexture(gl.GL_TEXTURE_2D, t)
        gl.glPixelStorei(gl.GL_UNPACK_ALIGNMENT, 1)
        gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_RGBA8, w, h, 0, gl.GL_RGBA, gl.GL_UNSIGNED_BYTE, np.ascontiguousarray(rgba))
        if mips:
            gl.glGenerateMipmap(gl.GL_TEXTURE_2D)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, gl.GL_LINEAR_MIPMAP_LINEAR if mips else gl.GL_LINEAR)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, gl.GL_LINEAR)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_S, gl.GL_REPEAT)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_T, gl.GL_REPEAT)
        return t

    def upload_rgba(self, rgba: np.ndarray) -> int:
        return self._upload_rgba(rgba, mips=False)

    def texture(self, name: str) -> int:
        key = os.path.splitext(name.replace("\\", "/").split("/")[-1])[0].lower()
        if key not in self.textures:
            tex = self.fs.texture(name)
            self.textures[key] = self._upload_rgba(tex.decode()) if tex else self.white
        return self.textures[key]

    def invalidate_textures(self) -> None:
        """Forget every loaded texture.  The GL objects are freed at the END of the frame (flush_deletes): the editor
        panels drawn this frame may still show them (deleting them earlier crashed the editor in imgui's render)."""
        self.delete_later([t for t in self.textures.values() if t != self.white])
        self.textures.clear()
        self.fs._tex.clear()

    def delete_later(self, ids) -> None:
        self.__dict__.setdefault("_pending_delete", []).extend(int(i) for i in ids if i)

    def flush_deletes(self) -> None:
        ids = self.__dict__.get("_pending_delete") or []
        if ids:
            gl.glDeleteTextures(ids)
            self._pending_delete = []

    def set_geometry(self, g: SceneGeometry) -> None:
        for vao, vbo, ebo, *_ in self.opaque:
            gl.glDeleteVertexArrays(1, [vao]); gl.glDeleteBuffers(2, [vbo, ebo])
        self.opaque = []
        for b in g.opaque:
            vao, vbo, ebo = self._make_vao(False)
            gl.glBufferData(gl.GL_ARRAY_BUFFER, b.vertices.nbytes, np.ascontiguousarray(b.vertices, np.float32), gl.GL_STATIC_DRAW)
            gl.glBufferData(gl.GL_ELEMENT_ARRAY_BUFFER, b.indices.nbytes, np.ascontiguousarray(b.indices, np.uint32), gl.GL_STATIC_DRAW)
            self.opaque.append((vao, vbo, ebo, len(b.indices), b.texture, b.two_sided))
        gl.glBindVertexArray(self.t_vao)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self.t_vbo)
        gl.glBufferData(gl.GL_ARRAY_BUFFER, g.tverts.nbytes, np.ascontiguousarray(g.tverts, np.float32), gl.GL_STATIC_DRAW)
        self.geometry = g
        self.last_sort_pos = None

    # ------------------------------------------------------------------ drawing
    def _u(self, prog, name):
        return gl.glGetUniformLocation(prog, name)

    lit = None            # None = unlit (textures as they are); or the dict of vtoy.render.lights.pack (the "Lit view")

    def _loc(self, name):
        cache = self.__dict__.setdefault("_locs", {})
        if name not in cache:
            cache[name] = gl.glGetUniformLocation(self.scene_prog, name)
        return cache[name]

    def _send_lights(self, lit) -> None:
        """Fill the light array of the scene shader (the shader itself is the original one: D3D style vertex lighting)."""
        gl.glUniform1i(self._loc("uIsUnlit"), 0)
        gl.glUniform3f(self._loc("globalAmbient"), *[float(v) for v in lit["ambient"]])
        ls = lit["lights"][:32]
        gl.glUniform1i(self._loc("numLights"), len(ls))
        if self.__dict__.get("_lit_sent") is lit:
            return
        self._lit_sent = lit
        for i, l in enumerate(ls):
            b = f"lights[{i}]."
            gl.glUniform1i(self._loc(b + "type"), int(l["type"]))
            gl.glUniform3f(self._loc(b + "position"), *[float(v) for v in l["position"]])
            gl.glUniform3f(self._loc(b + "direction"), *[float(v) for v in l["direction"]])
            gl.glUniform1f(self._loc(b + "range"), float(l["range"]))
            gl.glUniform1f(self._loc(b + "att0"), float(l["att0"]))
            gl.glUniform1f(self._loc(b + "att1"), float(l["att1"]))
            gl.glUniform1f(self._loc(b + "att2"), float(l["att2"]))
            gl.glUniform1f(self._loc(b + "theta"), float(l["theta"]))
            gl.glUniform1f(self._loc(b + "phi"), float(l["phi"]))
            gl.glUniform1f(self._loc(b + "falloff"), float(l["falloff"]))
            for k in ("ambient", "diffuse", "specular"):
                c = [float(v) for v in l[k]][:4]
                gl.glUniform4f(self._loc(b + k), c[0], c[1], c[2], 1.0)

    def _scene_uniforms(self, view, proj, cam_pos, fog_color, fog_near, fog_far, alpha_cutoff, gamma, lit=None):
        p = self.scene_prog
        gl.glUseProgram(p)
        gl.glUniformMatrix4fv(self._u(p, "model"), 1, gl.GL_TRUE, np.eye(4, dtype=np.float32))
        gl.glUniformMatrix4fv(self._u(p, "view"), 1, gl.GL_TRUE, view.astype(np.float32))
        gl.glUniformMatrix4fv(self._u(p, "projection"), 1, gl.GL_TRUE, proj.astype(np.float32))
        gl.glUniform3f(self._u(p, "viewPos"), *map(float, cam_pos))
        gl.glUniform1i(self._u(p, "uIsUnlit"), 1)
        gl.glUniform1i(self._u(p, "numLights"), 0)
        gl.glUniform3f(self._u(p, "globalAmbient"), 1, 1, 1)
        gl.glUniform3f(self._u(p, "uFogColor"), *fog_color)
        gl.glUniform1f(self._u(p, "uFogNear"), float(fog_near))
        gl.glUniform1f(self._u(p, "uFogFar"), float(max(fog_far, fog_near + 1)))
        gl.glUniform1f(self._u(p, "alphaCutoff"), float(alpha_cutoff))
        gl.glUniform1f(self._u(p, "uGamma"), float(gamma))
        gl.glUniform1i(self._u(p, "uTexture0"), 0)
        gl.glActiveTexture(gl.GL_TEXTURE0)
        if lit:
            try:
                self._send_lights(lit)
            except Exception:                   # never lose the picture because of the lights
                gl.glUniform1i(self._u(p, "uIsUnlit"), 1)

    @staticmethod
    def _cull(two_sided: bool, enabled: bool):
        if two_sided or not enabled:
            gl.glDisable(gl.GL_CULL_FACE)
        else:
            gl.glEnable(gl.GL_CULL_FACE); gl.glCullFace(gl.GL_BACK); gl.glFrontFace(gl.GL_CW)

    def render(self, cam, aspect, scene, opt, *, cull=True, sort_mode="triangle", show_decals=True, gamma=1.0,
               use_scene_fog=True, clear=(0.2, 0.2, 0.25), clear_buffers=True, show_sky=True):
        g = self.geometry
        view = cam.view()
        proj = cam.projection(aspect, max(float(getattr(scene, 'cam_near', 1.0)), 1.0), max(float(getattr(scene, 'cam_far', 0.0)), 20000.0))
        fog = scene.fog_color_f if use_scene_fog else (0.7, 0.7, 0.75)
        fog_c = tuple(fog() if callable(fog) else fog)
        if clear_buffers:
            gl.glClearColor(*(fog_c if use_scene_fog else clear), 1.0)
            gl.glClear(gl.GL_COLOR_BUFFER_BIT | gl.GL_DEPTH_BUFFER_BIT)
        sky = str(getattr(scene, "sky_texture", "") or "").rstrip("\0")
        if show_sky and clear_buffers and sky:
            self._scene_uniforms(view, proj, cam.pos, fog_c, 1e8, 2e8, 0.0, gamma)
            gl.glDisable(gl.GL_DEPTH_TEST); gl.glDepthMask(gl.GL_FALSE); gl.glDisable(gl.GL_CULL_FACE)
            m = np.eye(4, dtype=np.float32); m[:3, 3] = np.asarray(cam.pos, np.float32)
            gl.glUniformMatrix4fv(self._u(self.scene_prog, "model"), 1, gl.GL_TRUE, m)
            gl.glBindTexture(gl.GL_TEXTURE_2D, self.texture(sky))
            gl.glBindVertexArray(self.sky_vao)
            gl.glDrawElements(gl.GL_TRIANGLES, self.sky_n, gl.GL_UNSIGNED_INT, None)
            gl.glDepthMask(gl.GL_TRUE)
        if g is None:
            return
        near, far = (scene.fog_near, scene.fog_far) if use_scene_fog else (1e8, 2e8)
        self._scene_uniforms(view, proj, cam.pos, fog_c, near, far, 0.0, gamma, lit=self.lit)
        gl.glEnable(gl.GL_DEPTH_TEST); gl.glDepthMask(gl.GL_TRUE); gl.glDisable(gl.GL_BLEND)
        # 1) opaque
        for vao, _, _, count, tex, two in self.opaque:
            self._cull(two, cull)
            gl.glBindTexture(gl.GL_TEXTURE_2D, self.texture(tex))
            gl.glBindVertexArray(vao)
            gl.glDrawElements(gl.GL_TRIANGLES, count, gl.GL_UNSIGNED_INT, None)
        # 2) transparent pool, one sorted index buffer, depth write OFF, no depth pre-pass
        gl.glEnable(gl.GL_BLEND); gl.glBlendFunc(gl.GL_SRC_ALPHA, gl.GL_ONE_MINUS_SRC_ALPHA)
        gl.glDepthMask(gl.GL_FALSE)
        cp = np.asarray(cam.pos, np.float32)
        if len(g.ttri):
            if self.last_sort_pos is None or np.abs(self.last_sort_pos - cp).max() > 1.0 or sort_mode != getattr(self, "_mode", None):
                idx, self.t_runs = g.sort_transparent(cp, sort_mode)
                gl.glBindVertexArray(self.t_vao)
                gl.glBindBuffer(gl.GL_ELEMENT_ARRAY_BUFFER, self.t_ebo)
                gl.glBufferData(gl.GL_ELEMENT_ARRAY_BUFFER, idx.nbytes, idx, gl.GL_DYNAMIC_DRAW)
                self.last_sort_pos, self._mode = cp.copy(), sort_mode
            gl.glBindVertexArray(self.t_vao)
            for tid, two, first, count in self.t_runs:
                self._cull(two, cull)
                gl.glBindTexture(gl.GL_TEXTURE_2D, self.texture(g.tex_names[tid]))
                gl.glDrawElements(gl.GL_TRIANGLES, count, gl.GL_UNSIGNED_INT, ctypes.c_void_p(first * 4))
        # 3) decals (camera-facing quads, back to front)
        if show_decals and opt is not None and opt.decals:
            verts, idx, order = decal_quads(opt.decals, view, cam.pos)
            gl.glDisable(gl.GL_CULL_FACE)
            gl.glBindVertexArray(self.d_vao)
            gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self.d_vbo)
            gl.glBufferData(gl.GL_ARRAY_BUFFER, verts.nbytes, verts, gl.GL_DYNAMIC_DRAW)
            gl.glBindBuffer(gl.GL_ELEMENT_ARRAY_BUFFER, self.d_ebo)
            gl.glBufferData(gl.GL_ELEMENT_ARRAY_BUFFER, idx.nbytes, idx, gl.GL_DYNAMIC_DRAW)
            for k, di in enumerate(order):
                gl.glBindTexture(gl.GL_TEXTURE_2D, self.texture(opt.decals[di].name))
                gl.glDrawElements(gl.GL_TRIANGLES, 6, gl.GL_UNSIGNED_INT, ctypes.c_void_p(k * 6 * 4))
        gl.glDepthMask(gl.GL_TRUE)
        gl.glDisable(gl.GL_BLEND)
        self._view, self._proj = view, proj

    def capture(self, cam, scene, opt, size: int = 256, **kw) -> np.ndarray:
        """Map preview image. Draws into the lower-left ``size`` square of the window's own back buffer (scissored, so nothing else
        is touched; it is overdrawn by the next frame) and reads it back: no framebuffer / renderbuffer objects are created, which
        is what some drivers crashed on."""
        prev_vp = [int(v) for v in gl.glGetIntegerv(gl.GL_VIEWPORT)]
        gl.glEnable(gl.GL_SCISSOR_TEST)
        gl.glScissor(0, 0, size, size)
        gl.glViewport(0, 0, size, size)
        self.last_sort_pos = None
        try:
            self.render(cam, 1.0, scene, opt, **kw)
            gl.glFinish()
            gl.glReadBuffer(gl.GL_BACK)
            gl.glPixelStorei(gl.GL_PACK_ALIGNMENT, 1)
            raw = gl.glReadPixels(0, 0, size, size, gl.GL_RGBA, gl.GL_UNSIGNED_BYTE)
            img = np.frombuffer(bytes(raw) if not isinstance(raw, np.ndarray) else raw.tobytes(), np.uint8)
            img = img.reshape(size, size, 4)[::-1].copy()
        finally:
            gl.glDisable(gl.GL_SCISSOR_TEST)
            gl.glViewport(*prev_vp)
            self.last_sort_pos = None
        img[..., 3] = 255
        return img

    def capture_fbo(self, cam, scene, opt, size: int = 256, **kw) -> np.ndarray:
        """Render the scene off-screen into a ``size`` x ``size`` image (RGBA uint8, top row first).
        Colour and depth are renderbuffers (no texture binding to disturb) and the previous framebuffer / viewport are restored."""
        prev_fbo = int(gl.glGetIntegerv(gl.GL_FRAMEBUFFER_BINDING) or 0)
        prev_vp = [int(v) for v in gl.glGetIntegerv(gl.GL_VIEWPORT)]
        fbo = gl.glGenFramebuffers(1); col = gl.glGenRenderbuffers(1); dep = gl.glGenRenderbuffers(1)
        try:
            gl.glBindRenderbuffer(gl.GL_RENDERBUFFER, col)
            gl.glRenderbufferStorage(gl.GL_RENDERBUFFER, gl.GL_RGBA8, size, size)
            gl.glBindRenderbuffer(gl.GL_RENDERBUFFER, dep)
            gl.glRenderbufferStorage(gl.GL_RENDERBUFFER, gl.GL_DEPTH_COMPONENT24, size, size)
            gl.glBindRenderbuffer(gl.GL_RENDERBUFFER, 0)
            gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, fbo)
            gl.glFramebufferRenderbuffer(gl.GL_FRAMEBUFFER, gl.GL_COLOR_ATTACHMENT0, gl.GL_RENDERBUFFER, col)
            gl.glFramebufferRenderbuffer(gl.GL_FRAMEBUFFER, gl.GL_DEPTH_ATTACHMENT, gl.GL_RENDERBUFFER, dep)
            status = gl.glCheckFramebufferStatus(gl.GL_FRAMEBUFFER)
            if status != gl.GL_FRAMEBUFFER_COMPLETE:
                raise RuntimeError(f"off-screen framebuffer not complete (0x{int(status):x})")
            gl.glDisable(gl.GL_SCISSOR_TEST)
            gl.glViewport(0, 0, size, size)
            self.last_sort_pos = None
            self.render(cam, 1.0, scene, opt, **kw)
            gl.glFinish()
            gl.glReadBuffer(gl.GL_COLOR_ATTACHMENT0)
            gl.glPixelStorei(gl.GL_PACK_ALIGNMENT, 1)
            raw = gl.glReadPixels(0, 0, size, size, gl.GL_RGBA, gl.GL_UNSIGNED_BYTE)
            img = np.frombuffer(bytes(raw) if not isinstance(raw, np.ndarray) else raw.tobytes(), np.uint8)
            img = img.reshape(size, size, 4)[::-1].copy()
        finally:
            gl.glBindFramebuffer(gl.GL_FRAMEBUFFER, prev_fbo)
            gl.glViewport(*prev_vp)
            gl.glDeleteFramebuffers(1, [fbo]); gl.glDeleteRenderbuffers(2, [col, dep])
            self.last_sort_pos = None
        img[..., 3] = 255
        return img

    def faded_texture(self, name: str, alpha: float):
        """The texture with its alpha multiplied by ``alpha`` (in 8 steps, cached) - particles fade without a special shader.
        None when it would be invisible."""
        q = int(round(max(0.0, min(1.0, alpha)) * 8))
        if q <= 0:
            return None
        if q >= 8:
            return self.texture(name)
        key = os.path.splitext(name.replace("\\", "/").split("/")[-1])[0].lower() + f"@a{q}"
        if key not in self.textures:
            tex = self.fs.texture(name)
            if tex is None:
                self.textures[key] = self.white
            else:
                rgba = tex.decode().copy()
                rgba[..., 3] = (rgba[..., 3].astype(np.uint16) * q // 8).astype(np.uint8)
                self.textures[key] = self._upload_rgba(rgba)
        return self.textures[key]

    def draw_billboards(self, tex: int, verts, idx, tint=(1.0, 1.0, 1.0)):
        """Blended quads (n*4 vertices of 8 floats, display space) drawn with the scene shader: particles.
        ``tint`` multiplies the texture colour."""
        if tex is None or not len(idx) or getattr(self, "_view", None) is None:
            return
        p = self.scene_prog
        gl.glUseProgram(p)
        gl.glUniformMatrix4fv(self._u(p, "model"), 1, gl.GL_TRUE, np.eye(4, dtype=np.float32))
        gl.glUniformMatrix4fv(self._u(p, "view"), 1, gl.GL_TRUE, self._view.astype(np.float32))
        gl.glUniformMatrix4fv(self._u(p, "projection"), 1, gl.GL_TRUE, self._proj.astype(np.float32))
        gl.glUniform1i(self._u(p, "uIsUnlit"), 0)                 # "lit" by the ambient colour only = a tint
        gl.glUniform1i(self._u(p, "numLights"), 0)
        gl.glUniform3f(self._u(p, "globalAmbient"), *[float(v) for v in tint[:3]])
        gl.glUniform1f(self._u(p, "uFogNear"), 1e8)
        gl.glUniform1f(self._u(p, "uFogFar"), 2e8)
        gl.glUniform1f(self._u(p, "alphaCutoff"), 0.0)
        gl.glUniform1i(self._u(p, "uTexture0"), 0)
        gl.glActiveTexture(gl.GL_TEXTURE0)
        gl.glEnable(gl.GL_DEPTH_TEST); gl.glDepthMask(gl.GL_FALSE)
        gl.glEnable(gl.GL_BLEND); gl.glBlendFunc(gl.GL_SRC_ALPHA, gl.GL_ONE_MINUS_SRC_ALPHA)
        gl.glDisable(gl.GL_CULL_FACE)
        verts = np.ascontiguousarray(verts, np.float32)
        idx = np.ascontiguousarray(idx, np.uint32)
        gl.glBindVertexArray(self.d_vao)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self.d_vbo)
        gl.glBufferData(gl.GL_ARRAY_BUFFER, verts.nbytes, verts, gl.GL_DYNAMIC_DRAW)
        gl.glBindBuffer(gl.GL_ELEMENT_ARRAY_BUFFER, self.d_ebo)
        gl.glBufferData(gl.GL_ELEMENT_ARRAY_BUFFER, idx.nbytes, idx, gl.GL_DYNAMIC_DRAW)
        gl.glBindTexture(gl.GL_TEXTURE_2D, tex)
        gl.glDrawElements(gl.GL_TRIANGLES, len(idx), gl.GL_UNSIGNED_INT, None)
        gl.glDepthMask(gl.GL_TRUE)
        gl.glDisable(gl.GL_BLEND)

    def draw_lines(self, segments, color, depth_test=False):
        """segments: iterable of (a, b) display-space points; drawn as GL_LINES."""
        if isinstance(segments, np.ndarray):
            pts = segments.astype(np.float32).reshape(-1, 3)
        else:
            pts = np.asarray([p for seg in segments for p in seg], np.float32).reshape(-1, 3)
        if not len(pts):
            return
        p = self.dbg_prog
        gl.glUseProgram(p)
        gl.glUniformMatrix4fv(self._u(p, "view"), 1, gl.GL_TRUE, self._view.astype(np.float32))
        gl.glUniformMatrix4fv(self._u(p, "projection"), 1, gl.GL_TRUE, self._proj.astype(np.float32))
        gl.glUniformMatrix4fv(self._u(p, "model"), 1, gl.GL_TRUE, np.eye(4, dtype=np.float32))
        gl.glUniform4f(self._u(p, "uColor"), *color)
        (gl.glEnable if depth_test else gl.glDisable)(gl.GL_DEPTH_TEST)
        gl.glBindVertexArray(self.tmp_lines[0]); gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self.tmp_lines[1])
        gl.glBufferData(gl.GL_ARRAY_BUFFER, pts.nbytes, pts, gl.GL_DYNAMIC_DRAW)
        gl.glEnableVertexAttribArray(0); gl.glVertexAttribPointer(0, 3, gl.GL_FLOAT, False, 12, None)
        gl.glDrawArrays(gl.GL_LINES, 0, len(pts))
        gl.glEnable(gl.GL_DEPTH_TEST)

    def draw_boxes(self, boxes, color, depth_test=False):
        """boxes: iterable of (centre(3), size(3)) in *display* (already mirrored) coordinates."""
        p = self.dbg_prog
        gl.glUseProgram(p)
        gl.glUniformMatrix4fv(self._u(p, "view"), 1, gl.GL_TRUE, self._view.astype(np.float32))
        gl.glUniformMatrix4fv(self._u(p, "projection"), 1, gl.GL_TRUE, self._proj.astype(np.float32))
        gl.glUniform4f(self._u(p, "uColor"), *color)
        (gl.glEnable if depth_test else gl.glDisable)(gl.GL_DEPTH_TEST)
        gl.glDisable(gl.GL_CULL_FACE)
        gl.glBindVertexArray(self.cube[0])
        for c, s in boxes:
            m = np.diag([s[0], s[1], s[2], 1.0]).astype(np.float32)
            m[:3, 3] = c
            gl.glUniformMatrix4fv(self._u(p, "model"), 1, gl.GL_TRUE, m)
            gl.glDrawArrays(gl.GL_LINES, 0, self.cube_n)
        gl.glEnable(gl.GL_DEPTH_TEST)
