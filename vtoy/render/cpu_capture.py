"""Map preview without OpenGL: the baked scene is drawn on the CPU (numpy + Pillow, painter's algorithm).
Used by the "Map preview" capture: a thumbnail does not need the GPU, and it can never crash the driver."""
from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw


def _sample_table(fs, names, cache):
    """name -> small RGBA uint8 array (<= 64 px) used to colour a triangle from its centroid uv (None = no texture)."""
    for n in names:
        if n in cache:
            continue
        arr = None
        try:
            t = fs.texture(n)
            if t is not None:
                lvl = 0
                if getattr(t, "has_mips", False):
                    lvl = max(0, min(t.mip_count - 1, int(np.log2(max(1, max(t.width, t.height) // 64)))))
                arr = np.asarray(t.decode(lvl))
        except Exception:
            arr = None
        cache[n] = arr


def _colors(tex_arr, uv, fallback=(150, 150, 150)):
    if tex_arr is None or tex_arr.size == 0:
        return np.tile(np.array(fallback + (255,), np.uint8), (len(uv), 1))
    h, w = tex_arr.shape[:2]
    u = np.mod(uv[:, 0], 1.0); v = np.mod(uv[:, 1], 1.0)
    return tex_arr[(v * (h - 1)).astype(int), (u * (w - 1)).astype(int)][:, :4]


def render(fs, geometry, cam, scene, size=256, ss=2, background=None, cache=None) -> np.ndarray:
    """-> (size, size, 4) uint8 RGBA, alpha 255. ``cam`` is a FlyCamera, ``geometry`` a SceneGeometry (display space)."""
    cache = cache if cache is not None else {}
    S = size * ss
    fog = scene.fog_color_f() if callable(getattr(scene, "fog_color_f", None)) else (0.6, 0.7, 0.85)
    bg = tuple(int(255 * c) for c in (background or fog))[:3]
    im = Image.new("RGB", (S, S), bg)
    if geometry is None:
        return np.asarray(im.resize((size, size), Image.LANCZOS).convert("RGBA"))
    vp = cam.projection(1.0, 20.0, 60000.0) @ cam.view()
    batches = [(b.texture, b.vertices, b.indices.reshape(-1, 3)) for b in geometry.opaque]
    if len(geometry.ttri):
        for ti, name in enumerate(geometry.tex_names):
            m = geometry.ttex == ti
            if m.any():
                batches.append((name, geometry.tverts, geometry.ttri[m]))
    _sample_table(fs, {b[0] for b in batches}, cache)
    sun = np.array([0.4, 0.8, 0.5]); sun /= np.linalg.norm(sun)
    P, C, D = [], [], []
    for name, verts, tri in batches:
        if len(tri) == 0:
            continue
        pos = verts[:, :3].astype(np.float64)
        clip = np.c_[pos, np.ones(len(pos))] @ vp.T
        w = clip[:, 3]
        ok_v = w > 1e-3
        ndc = clip[:, :2] / np.where(ok_v, w, 1.0)[:, None]
        scr = np.c_[(ndc[:, 0] * 0.5 + 0.5) * S, (0.5 - ndc[:, 1] * 0.5) * S]
        ok = ok_v[tri].all(1)
        sx = scr[tri][:, :, 0]; sy = scr[tri][:, :, 1]
        ok &= (sx.max(1) > 0) & (sx.min(1) < S) & (sy.max(1) > 0) & (sy.min(1) < S)
        ok &= ((sx.max(1) - sx.min(1)) < 4 * S) & ((sy.max(1) - sy.min(1)) < 4 * S)
        idx = np.nonzero(ok)[0]
        if not len(idx):
            continue
        t = tri[idx]
        uv = verts[:, 6:8][t].mean(1)
        col = _colors(cache.get(name), uv).astype(np.float32)
        p0, p1, p2 = pos[t[:, 0]], pos[t[:, 1]], pos[t[:, 2]]
        n = np.cross(p1 - p0, p2 - p0)
        n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-9)
        shade = 0.55 + 0.45 * np.abs(n @ sun)
        keep = col[:, 3] > 40
        rgb = (col[:, :3] * shade[:, None]).clip(0, 255).astype(np.uint8)
        P.append(scr[t][keep]); C.append(rgb[keep]); D.append(w[t][keep].mean(1))
    if P:
        P = np.concatenate(P); C = np.concatenate(C); D = np.concatenate(D)
        dr = ImageDraw.Draw(im)
        for i in np.argsort(-D):
            dr.polygon([tuple(p) for p in P[i]], fill=tuple(int(x) for x in C[i]))
    out = np.asarray(im.resize((size, size), Image.LANCZOS).convert("RGBA")).copy()
    out[..., 3] = 255
    return out
