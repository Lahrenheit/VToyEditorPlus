"""Fly camera + small transform helpers (pure numpy, column-vector / OpenGL conventions)."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np


def perspective(fov_deg: float, aspect: float, near: float, far: float) -> np.ndarray:
    f = 1.0 / math.tan(math.radians(fov_deg) / 2.0)
    m = np.zeros((4, 4), np.float64)
    m[0, 0], m[1, 1] = f / aspect, f
    m[2, 2], m[2, 3] = (far + near) / (near - far), 2 * far * near / (near - far)
    m[3, 2] = -1.0
    return m


def look_at(eye, target, up=(0, 1, 0)) -> np.ndarray:
    eye, target, up = (np.asarray(x, np.float64) for x in (eye, target, up))
    f = target - eye
    f /= np.linalg.norm(f)
    s = np.cross(f, up)
    s /= np.linalg.norm(s)
    u = np.cross(s, f)
    m = np.eye(4)
    m[0, :3], m[1, :3], m[2, :3] = s, u, -f
    m[:3, 3] = -m[:3, :3] @ eye
    return m


@dataclass
class FlyCamera:
    pos: np.ndarray = field(default_factory=lambda: np.array([0.0, 170.0, 0.0]))
    yaw: float = -90.0
    pitch: float = 0.0
    fov: float = 75.0
    speed: float = 1000.0          # units / second (1 unit ~ 1 cm)

    @property
    def front(self) -> np.ndarray:
        y, p = math.radians(self.yaw), math.radians(self.pitch)
        return np.array([math.cos(y) * math.cos(p), math.sin(p), math.sin(y) * math.cos(p)])

    def look(self, dx: float, dy: float, sens: float = 0.1) -> None:
        self.yaw += dx * sens
        self.pitch = max(-89.0, min(89.0, self.pitch - dy * sens))

    def move(self, forward: float, right: float, up: float, dt: float, boost: bool = False, flat: bool = False) -> None:
        """``flat``: walk on the horizontal plane (no looking-direction climb)."""
        v = self.speed * dt * (5.0 if boost else 1.0)
        f = self.front
        if flat:
            f = np.array([f[0], 0.0, f[2]])
            f /= max(np.linalg.norm(f), 1e-9)
        r = np.cross(f, (0, 1, 0))
        r /= np.linalg.norm(r)
        self.pos = self.pos + v * (forward * f + right * r + up * np.array([0.0, 1.0, 0.0]))

    def view(self) -> np.ndarray:
        return look_at(self.pos, self.pos + self.front)

    def projection(self, aspect: float, near: float, far: float) -> np.ndarray:
        return perspective(self.fov, aspect, near, far)

    def face(self, target) -> None:
        d = np.asarray(target, np.float64) - self.pos
        d /= np.linalg.norm(d)
        self.pitch = math.degrees(math.asin(max(-1, min(1, d[1]))))
        self.yaw = math.degrees(math.atan2(d[2], d[0]))

    def ray(self, px: float, py: float, width: int, height: int, near: float = 1.0, far: float = 100000.0):
        """World ray (origin, unit direction) through window pixel (px, py)."""
        inv = np.linalg.inv(self.projection(width / height, near, far) @ self.view())
        x, y = 2 * px / width - 1, 1 - 2 * py / height
        a = inv @ np.array([x, y, -1, 1.0])
        b = inv @ np.array([x, y, 1, 1.0])
        a, b = a[:3] / a[3], b[:3] / b[3]
        d = b - a
        return a, d / np.linalg.norm(d)


def ray_aabb(origin, direction, lo, hi):
    """Slab test. Returns the entry distance or None."""
    with np.errstate(divide="ignore", invalid="ignore"):
        t1 = (lo - origin) / direction
        t2 = (hi - origin) / direction
    tmin = np.nanmax(np.minimum(t1, t2))
    tmax = np.nanmin(np.maximum(t1, t2))
    if tmax < max(tmin, 0.0):
        return None
    return max(tmin, 0.0)


# -------------------------------------------------------------------------- transform <-> editable values
def decompose(m: np.ndarray):
    """Row-vector 4x4 -> (position, euler XYZ degrees, scale). Rotation order matches compose()."""
    m = np.asarray(m, np.float64)
    pos = m[3, :3].copy()
    sc = np.linalg.norm(m[:3, :3], axis=1)
    sc = np.where(sc < 1e-9, 1.0, sc)
    r = m[:3, :3] / sc[:, None]
    # compose(): R = Rz(rz) @ Ry(ry) @ Rx(rx) applied on row vectors => r = Rx.T @ Ry.T @ Rz.T style; solve numerically
    sy = -r[0, 2]
    ry = math.asin(max(-1.0, min(1.0, sy)))
    if abs(sy) < 0.99999:
        rx = math.atan2(r[1, 2], r[2, 2])
        rz = math.atan2(r[0, 1], r[0, 0])
    else:
        rx = math.atan2(-r[2, 1], r[1, 1])
        rz = 0.0
    return pos, np.degrees([rx, ry, rz]), sc


def compose(pos, euler_deg, scale) -> np.ndarray:
    rx, ry, rz = np.radians(euler_deg)
    cx, sx, cy, sy, cz, sz = math.cos(rx), math.sin(rx), math.cos(ry), math.sin(ry), math.cos(rz), math.sin(rz)
    # column-vector rotation Rz*Ry*Rx, transposed for the engine's row-vector convention
    r = np.array([[cz * cy, cz * sy * sx - sz * cx, cz * sy * cx + sz * sx],
                  [sz * cy, sz * sy * sx + cz * cx, sz * sy * cx - cz * sx],
                  [-sy, cy * sx, cy * cx]])
    m = np.eye(4)
    m[:3, :3] = (r.T) * np.asarray(scale, np.float64)[:, None]
    m[3, :3] = pos
    return m.astype(np.float32)
