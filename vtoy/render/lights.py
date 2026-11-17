"""The lights of a map (.opt) packed for the scene shader ("Lit view").

Maps of the engine are lit by real-time vertex lighting, the way Direct3D 8 did it: an ambient colour, a few directional
lights (sun / moon / fill) and point lights with a start and an end distance (full brightness up to ``start``, nothing
after ``end``).  Nothing is baked into the meshes, so a copied ship or a new gangplank is lit exactly like the original
as long as the lights reach it.

The shader takes at most 32 lights; the directional ones always go in and the point lights nearest to the camera fill the
rest (the game does a similar choice per object, with fewer lights).  The falloff between ``start`` and ``end`` is
approximated with the quadratic attenuation Direct3D offers - close, not identical."""
from __future__ import annotations

from typing import List, Optional

import numpy as np

MAX_LIGHTS = 32
FLIP = np.array([1.0, 1.0, -1.0])            # engine -> display space


def _rgb(c) -> List[float]:
    c = [float(v) for v in c][:3]
    return (c + [0.0, 0.0, 0.0])[:3]


def point_attenuation(start: float, end: float):
    """(range, att0, att1, att2): 1 near the light, one half midway between start and end, cut at ``end``."""
    end = max(float(end), 1.0)
    mid = max((max(float(start), 0.0) + end) / 2.0, 1.0)
    return end, 1.0, 0.0, 1.0 / (mid * mid)


def pack(opt, cam_pos_display=None, limit: int = MAX_LIGHTS) -> Optional[dict]:
    """{'ambient': (r, g, b), 'lights': [...]} in display space, or None when the map has no lights at all."""
    lights = list(getattr(opt, "lights", ()) or ())
    if not lights:
        return None
    ambient = np.zeros(3)
    fixed, points = [], []
    for l in lights:
        t = int(l.type)
        if t == 3:                                                   # ambient: its diffuse colour is the ambient colour
            ambient += _rgb(l.diffuse)
            continue
        d = {"type": t, "position": (0.0, 0.0, 0.0), "direction": (0.0, -1.0, 0.0), "range": 1e9, "att0": 1.0, "att1": 0.0,
             "att2": 0.0, "theta": 0.0, "phi": 0.0, "falloff": 1.0,
             "diffuse": _rgb(l.diffuse), "ambient": _rgb(l.ambient) if t != 2 else [0.0, 0.0, 0.0], "specular": [0.0, 0.0, 0.0]}
        if t == 2:
            v = np.asarray(l.direction, np.float64) * FLIP
            n = float(np.linalg.norm(v))
            d["direction"] = tuple(v / n) if n > 1e-9 else (0.0, -1.0, 0.0)
            fixed.append(d)
            continue
        pos = np.asarray(l.position, np.float64) * FLIP
        d["position"] = tuple(pos)
        if t == 0:
            end = l.end if not getattr(opt, "old_format", False) else l.radius
            start = l.start if not getattr(opt, "old_format", False) else l.radius * 0.5
            d["range"], d["att0"], d["att1"], d["att2"] = point_attenuation(start, end)
        else:                                                         # spot
            v = np.asarray(l.direction, np.float64) * FLIP
            n = float(np.linalg.norm(v))
            d["direction"] = tuple(v / n) if n > 1e-9 else (0.0, -1.0, 0.0)
            cone = float(l.cone) if l.cone else 0.8
            d["theta"], d["phi"] = cone * 0.6, cone
            d["range"] = 1e5
        points.append((pos, d))
    if cam_pos_display is not None and len(points) > limit - len(fixed):
        cp = np.asarray(cam_pos_display, np.float64)
        points.sort(key=lambda it: float(((it[0] - cp) ** 2).sum()) - float(it[1]["range"]) ** 2 if it[1]["range"] < 1e8 else 0.0)
    out = fixed[:limit] + [d for _, d in points[: max(0, limit - len(fixed))]]
    return {"ambient": tuple(np.clip(ambient, 0.0, 1.0)), "lights": out, "total": len(lights) - sum(1 for l in lights if int(l.type) == 3)}


def describe(opt) -> dict:
    """Counts by kind, for the panel."""
    n = {"point": 0, "spot": 0, "directional": 0, "ambient": 0}
    for l in getattr(opt, "lights", ()) or ():
        n[("point", "spot", "directional", "ambient")[int(l.type)]] += 1
    return n
