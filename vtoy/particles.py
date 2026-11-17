"""Preview of particle emitters (CParticleSystem) and rain in the editor.

The motion model comes from the numbers of the 155 emitters of the shipped maps (see vtoy.modules.CParticleSystem), not from
the game's code: a particle is born inside ``radius`` of the emitter with ``velocity`` (spread by ``spread``), is pushed by
``acceleration`` and slowed by ``damping`` (per frame at ~30 fps), lives ``life`` seconds and goes from the start colour /
size to the end ones.  Good enough to see where the smoke goes, how high a fountain reaches and how big it is; the exact look
(blending, texture animation) is the game's.

Everything is a pure function of time, so the preview does not keep state: ``emit(ps, t)`` gives the particles alive at t."""
from __future__ import annotations

import math
from typing import Tuple

import numpy as np

FPS = 30.0


def _hash(j: np.ndarray, cycle: np.ndarray, k: int) -> np.ndarray:
    """Repeatable pseudo-random numbers in [0, 1) for particle j in its ``cycle``-th life."""
    v = np.sin(j * 12.9898 + cycle * 78.233 + k * 37.719) * 43758.5453
    return v - np.floor(v)


def displacement(v0: np.ndarray, acc: np.ndarray, damping: float, age: np.ndarray) -> np.ndarray:
    """Where a particle is ``age`` seconds after its birth (relative to it)."""
    age = np.asarray(age, np.float64)[:, None]
    acc = np.asarray(acc, np.float64)[None, :]
    d = float(damping)
    if d <= 0.0 or d >= 0.99999:
        return v0 * age + 0.5 * acc * age * age
    k = -math.log(d) * FPS                               # dv/dt = a - k v
    term = acc / k
    return term * age + (v0 - term) * (1.0 - np.exp(-k * age)) / k


def emit(ps, t: float, max_particles: int = 300) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Particles of emitter ``ps`` alive at time ``t``: (positions (n, 3) engine, sizes (n,), age fraction (n,) 0..1)."""
    life = max(float(ps.life), 0.05)
    n = int(min(max(float(ps.rate) * life, 1.0), max_particles))
    j = np.arange(n, dtype=np.float64)
    phase = t / life + j / n
    cycle = np.floor(phase)
    frac = phase - cycle
    age = frac * life
    r = [_hash(j, cycle, k) for k in range(6)]
    # birth place: a disc of ``radius`` around the emitter
    ang = r[0] * 2 * math.pi
    rad = np.sqrt(r[1]) * float(ps.radius)
    start = np.stack([np.cos(ang) * rad, np.zeros(n), np.sin(ang) * rad], 1)
    # start speed: the emitter's velocity turned / stretched by ``spread``
    v = np.asarray(ps.velocity, np.float64)
    speed = float(np.linalg.norm(v))
    dirn = np.stack([r[2] * 2 - 1, r[3] * 2 - 1, r[4] * 2 - 1], 1)
    dirn /= np.maximum(np.linalg.norm(dirn, axis=1, keepdims=True), 1e-6)
    v0 = v[None, :] + dirn * (float(ps.spread) * speed * r[5])[:, None]
    pos = np.asarray(ps.position, np.float64)[None, :] + start + displacement(v0, np.asarray(ps.acceleration, np.float64), ps.damping, age)
    size = float(ps.size_start) + (float(ps.size_end) - float(ps.size_start)) * frac
    return pos, size, frac


def colour_at(ps, frac: float) -> Tuple[float, float, float, float]:
    """(r, g, b, a) 0..1 of a particle at ``frac`` of its life.  Emitters whose colour is pure black (water, blood) keep the
    colours of their texture."""
    c0, c1 = np.asarray(ps.color_start, np.float64), np.asarray(ps.color_end, np.float64)
    c = (c0 + (c1 - c0) * frac) / 255.0
    if max(ps.color_start[:3]) == 0 and max(ps.color_end[:3]) == 0:
        c[:3] = 1.0
    return float(c[0]), float(c[1]), float(c[2]), float(c[3])


def billboards(pos_display: np.ndarray, size: np.ndarray, right, up) -> Tuple[np.ndarray, np.ndarray]:
    """Camera facing quads: (vertices (n*4, 8) pos3 nrm3 uv2, indices (n*6,)) for points already in display space."""
    n = len(pos_display)
    if n == 0:
        return np.zeros((0, 8), np.float32), np.zeros(0, np.uint32)
    right, up = np.asarray(right, np.float64), np.asarray(up, np.float64)
    h = (np.asarray(size, np.float64) / 2)[:, None]
    v = np.zeros((n, 4, 8), np.float32)
    for k, (sx, sy, u, w) in enumerate(((-1, 1, 0, 0), (1, 1, 1, 0), (1, -1, 1, 1), (-1, -1, 0, 1))):
        v[:, k, :3] = pos_display + right * sx * h + up * sy * h
        v[:, k, 3:6] = (0.0, 1.0, 0.0)
        v[:, k, 6:8] = (u, w)
    base = (np.arange(n, dtype=np.uint32) * 4)[:, None]
    idx = (base + np.array([0, 2, 1, 0, 3, 2], np.uint32)[None, :]).reshape(-1)
    return v.reshape(-1, 8), idx


def reach(ps, samples: int = 24) -> Tuple[np.ndarray, np.ndarray]:
    """Bounding box (lo, hi) engine of where the particles of an emitter go during their life (its 'range')."""
    pts = np.concatenate([emit(ps, t)[0] for t in np.linspace(0.0, max(float(ps.life), 0.05), samples)])
    pad = max(float(ps.size_start), float(ps.size_end)) / 2
    return pts.min(0) - pad, pts.max(0) + pad


def rain(cam_pos, t: float, count: int = 600, radius: float = 1600.0, height: float = 1400.0, speed: float = 2600.0,
         length: float = 140.0) -> np.ndarray:
    """Falling streaks around the camera: (count, 2, 3) segments in the same space as ``cam_pos``."""
    j = np.arange(count, dtype=np.float64)
    z = np.zeros(count)
    ang = _hash(j, z, 1) * 2 * math.pi
    rad = np.sqrt(_hash(j, z, 2)) * radius
    # the streaks live in a grid fixed to the world, so they do not follow the camera when it moves
    cx = np.floor(cam_pos[0] / radius) * radius
    cz = np.floor(cam_pos[2] / radius) * radius
    x = cx + ((np.cos(ang) * rad - (cam_pos[0] - cx) + radius) % (2 * radius)) - radius + (cam_pos[0] - cx)
    zz = cz + ((np.sin(ang) * rad - (cam_pos[2] - cz) + radius) % (2 * radius)) - radius + (cam_pos[2] - cz)
    fall = (t * speed + _hash(j, z, 3) * height) % height
    y = cam_pos[1] + height / 2 - fall
    a = np.stack([x, y, zz], 1)
    b = a - [0.0, length, 0.0]
    return np.stack([a, b], 1).astype(np.float32)


def sphere_circles(centre, radius: float, segments: int = 48) -> np.ndarray:
    """Three circles (one per plane) of a sphere as (n, 2, 3) line segments - how the range of a sound / light is drawn."""
    a = np.linspace(0.0, 2 * math.pi, segments + 1)
    c, s = np.cos(a) * radius, np.sin(a) * radius
    o = np.zeros_like(c)
    out = []
    for ring in (np.stack([c, o, s], 1), np.stack([c, s, o], 1), np.stack([o, c, s], 1)):
        ring = ring + np.asarray(centre, np.float64)
        out.append(np.stack([ring[:-1], ring[1:]], 1))
    return np.concatenate(out).astype(np.float32)
