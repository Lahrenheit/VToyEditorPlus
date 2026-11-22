"""Team colours for textures: shift the hue of the saturated areas that lie in given hue ranges (e.g. the purple band and the
green panels of the Love Boat) to red or yellow, keeping brightness and detail.  White / grey / wood pixels are not touched."""
from __future__ import annotations

import numpy as np

TEAM_HUE = {"rojo": 0.0, "amarillo": 52.0}       # degrees


def _rgb_to_hsv(rgb):
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    mx, mn = rgb.max(-1), rgb.min(-1)
    d = mx - mn
    h = np.zeros_like(mx)
    nz = d > 1e-6
    rc = nz & (mx == r)
    gc = nz & (mx == g) & ~rc
    bc = nz & ~rc & ~gc
    h[rc] = ((g - b)[rc] / d[rc]) % 6
    h[gc] = (b - r)[gc] / d[gc] + 2
    h[bc] = (r - g)[bc] / d[bc] + 4
    s = np.where(mx > 1e-6, d / np.maximum(mx, 1e-6), 0)
    return h * 60.0, s, mx


def _hsv_to_rgb(h, s, v):
    h = (h % 360.0) / 60.0
    c = v * s
    x = c * (1 - np.abs(h % 2 - 1))
    z = np.zeros_like(h)
    conds = [(h < 1), (h < 2), (h < 3), (h < 4), (h < 5), (h >= 5)]
    rs = [c, x, z, z, x, c]
    gs = [x, c, c, x, z, z]
    bs = [z, z, x, c, c, x]
    r = np.select(conds, rs); g = np.select(conds, gs); b = np.select(conds, bs)
    m = v - c
    return np.stack([r + m, g + m, b + m], -1)


def recolor(rgba: np.ndarray, hue_ranges, target_hue: float, min_sat: float = 0.18, min_val: float = 0.08) -> np.ndarray:
    """RGBA uint8 -> RGBA uint8 with the pixels whose hue is in ``hue_ranges`` (list of (lo, hi) degrees) moved to
    ``target_hue``.  Hue differences inside the area are kept (shrunk) so shading stays."""
    a = np.asarray(rgba, np.uint8)
    rgb = a[..., :3].astype(np.float64) / 255.0
    h, s, v = _rgb_to_hsv(rgb)
    sel = np.zeros(h.shape, bool)
    centre = np.zeros(h.shape)
    for lo, hi in hue_ranges:
        m = (h >= lo) & (h <= hi)
        sel |= m
        centre = np.where(m, (lo + hi) / 2, centre)
    sel &= (s >= min_sat) & (v >= min_val)
    if not sel.any():
        return a.copy()
    nh = np.where(sel, target_hue + (h - centre) * 0.25, h)
    ns = np.where(sel, np.clip(s * (1.15 if target_hue < 20 else 1.0), 0, 1), s)
    out = (np.clip(_hsv_to_rgb(nh, ns, v), 0, 1) * 255.0 + 0.5).astype(np.uint8)
    res = a.copy()
    res[..., :3] = np.where(sel[..., None], out, a[..., :3])
    return res
