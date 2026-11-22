"""Walking test: a body that moves over the collision of a map the way a player would, without opening the game.

What stops a player in the game is the height map (.hm: floors, slopes, walls) and the collision boxes of the map (.opt);
``World`` reads both, ``Walker`` is a capsule-ish body (a circle of ``radius`` seen from above, ``height`` tall) with gravity,
a step height and wall sliding.  The numbers (speed, step, jump) are sensible guesses for a person in a world where one unit
is about one centimetre - they are NOT read from the game, so use it to find holes, missing floors and blocked passages,
not to time a jump to the centimetre."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

WALKABLE = 0.45        # floors: normal.y above this
CELL = 300.0


def _in_poly(x: float, z: float, poly: np.ndarray) -> bool:
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, zi, xj, zj = poly[i][0], poly[i][1], poly[j][0], poly[j][1]
        if (zi > z) != (zj > z) and x < (xj - xi) * (z - zi) / (zj - zi) + xi:
            inside = not inside
        j = i
    return inside


def _edge_dist(x: float, z: float, poly: np.ndarray) -> float:
    best = 1e30
    n = len(poly)
    for i in range(n):
        ax, az = poly[i]; bx, bz = poly[(i + 1) % n]
        dx, dz = bx - ax, bz - az
        l2 = dx * dx + dz * dz
        t = 0.0 if l2 < 1e-12 else max(0.0, min(1.0, ((x - ax) * dx + (z - az) * dz) / l2))
        best = min(best, math.hypot(x - ax - t * dx, z - az - t * dz))
    return best


@dataclass
class Floor:
    poly: np.ndarray            # (n, 2) x, z
    plane: Tuple[float, float, float, float]      # nx, ny, nz, d   (n.p + d = 0)
    bounds: Tuple[float, float, float, float]

    def y_at(self, x: float, z: float) -> float:
        nx, ny, nz, d = self.plane
        return -(d + nx * x + nz * z) / ny


@dataclass
class Wall:
    pts: list                   # [(x, y, z)] of the face
    y0: float
    y1: float
    normal: Tuple[float, float] = (0.0, 0.0)      # the side it faces (x, z)
    bounds: Tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)

    def outline(self, lo: float, hi: float) -> List[Tuple[float, float]]:
        """The part of the face between heights ``lo`` and ``hi`` seen from above: [(x, z)] (a line for an upright wall,
        a thin polygon for a leaning one)."""
        poly = self.pts
        for sign, lim in ((1.0, lo), (-1.0, hi)):
            out = []
            n = len(poly)
            for i in range(n):
                p, q = poly[i], poly[(i + 1) % n]
                dp, dq = sign * (p[1] - lim), sign * (q[1] - lim)
                if dp >= 0:
                    out.append(p)
                if (dp >= 0) != (dq >= 0):
                    t = dp / (dp - dq)
                    out.append((p[0] + (q[0] - p[0]) * t, lim, p[2] + (q[2] - p[2]) * t))
            poly = out
            if len(poly) < 2:
                return []
        return [(p[0], p[2]) for p in poly]


@dataclass
class Box:
    centre: np.ndarray
    axes: np.ndarray            # rows = the box's axes (unit)
    half: np.ndarray

    @property
    def y0(self) -> float:
        return self.by0

    @property
    def y1(self) -> float:
        return self.by1

    def __post_init__(self):
        self._ry = float(np.abs(self.axes[:, 1]) @ self.half)
        # footprint: the rectangle of the two most horizontal axes
        order = np.argsort(np.abs(self.axes[:, 1]))
        h0, h1 = int(order[0]), int(order[1])
        u = self.axes[h0][[0, 2]]; v = self.axes[h1][[0, 2]]
        lu, lv = float(np.linalg.norm(u)), float(np.linalg.norm(v))
        self.ux, self.uz = float(u[0] / max(lu, 1e-9)), float(u[1] / max(lu, 1e-9))
        self.vx, self.vz = float(v[0] / max(lv, 1e-9)), float(v[1] / max(lv, 1e-9))
        self.hu, self.hv = float(self.half[h0]) * lu, float(self.half[h1]) * lv
        self.cx, self.cz = float(self.centre[0]), float(self.centre[2])
        self.by0, self.by1 = float(self.centre[1] - self._ry), float(self.centre[1] + self._ry)
        r = np.abs(self.axes[:, [0, 2]]).T @ self.half
        self.bounds = (float(self.centre[0] - r[0]), float(self.centre[2] - r[1]), float(self.centre[0] + r[0]), float(self.centre[2] + r[1]))

    def local(self, x: float, z: float) -> Tuple[float, float]:
        dx, dz = x - self.cx, z - self.cz
        return dx * self.ux + dz * self.uz, dx * self.vx + dz * self.vz

    def contains(self, x: float, z: float, margin: float = 0.0) -> bool:
        a, b = self.local(x, z)
        return abs(a) <= self.hu + margin and abs(b) <= self.hv + margin


class World:
    """Floors, walls and boxes of a map, in engine coordinates, with a coarse grid to find the ones near a point."""

    def __init__(self, faces=(), boxes=()):
        self.floors: List[Floor] = []
        self.walls: List[Wall] = []
        self.boxes: List[Box] = []
        self._fg: Dict[tuple, List[int]] = {}
        self._wg: Dict[tuple, List[int]] = {}
        self._bg: Dict[tuple, List[int]] = {}
        self.y_min = 0.0
        ys = []
        for f in faces:
            pts = np.asarray(f.contours[0], np.float64) if f.contours else np.zeros((0, 3))
            if len(pts) < 3:
                continue
            nx, ny, nz = (float(v) for v in f.normal)
            ys.append(float(pts[:, 1].min()))
            if ny >= WALKABLE:
                poly = pts[:, [0, 2]]
                fl = Floor(poly, (nx, ny, nz, float(f.distance)),
                           (float(poly[:, 0].min()), float(poly[:, 1].min()), float(poly[:, 0].max()), float(poly[:, 1].max())))
                self._put(self._fg, fl.bounds, len(self.floors))
                self.floors.append(fl)
            elif ny > -WALKABLE:                       # a wall (or a slope too steep to stand on)
                h = math.hypot(nx, nz)
                if h < 1e-6:
                    continue
                dev = np.abs(pts @ np.array([nx, ny, nz]) + float(f.distance)).max()
                if dev > 10.0:                         # a few shipped faces are not flat at all: nothing sensible to hit
                    continue
                w = Wall([tuple(float(v) for v in p) for p in pts], float(pts[:, 1].min()), float(pts[:, 1].max()), (nx / h, nz / h),
                         (float(pts[:, 0].min()), float(pts[:, 2].min()), float(pts[:, 0].max()), float(pts[:, 2].max())))
                self._put(self._wg, w.bounds, len(self.walls))
                self.walls.append(w)
        for raw in boxes:
            a = np.frombuffer(raw, "<f4", 19).astype(np.float64) if isinstance(raw, (bytes, bytearray)) else None
            if a is None:
                c, ax, half = raw
                bx = Box(np.asarray(c, np.float64), np.asarray(ax, np.float64), np.abs(np.asarray(half, np.float64)))
            else:
                ax = a[:16].reshape(4, 4)[:3, :3].copy()
                ln = np.linalg.norm(ax, axis=1)
                half = np.abs(a[16:19]) * np.where(ln < 1e-9, 1.0, ln)
                bx = Box(a[12:15].copy(), ax / np.where(ln < 1e-9, 1.0, ln)[:, None], half)
            self._put(self._bg, bx.bounds, len(self.boxes))
            self.boxes.append(bx)
            ys.append(bx.y0)
        fy = [float(f.y_at((f.bounds[0] + f.bounds[2]) / 2, (f.bounds[1] + f.bounds[3]) / 2)) for f in self.floors]
        self.y_min = min(fy) if fy else (min(ys) if ys else 0.0)          # the lowest floor

    @classmethod
    def from_map(cls, opt, hm, extra_boxes=()) -> "World":
        """The map's floors / walls (.hm) and collision boxes, plus ``extra_boxes`` (76-byte boxes: e.g. around the
        cars and doors of the scene, which the game makes solid by their model)."""
        from . import crop, hmcopy
        faces = hmcopy.unique_faces(hm) if hm is not None else []
        try:
            boxes = list(crop.read_block(opt).boxes) if opt is not None and not opt.old_format else []
        except Exception:
            boxes = []
        return cls(faces, boxes + list(extra_boxes))

    @staticmethod
    def _put(grid, b, idx, pad: float = 0.0):
        for cx in range(int(math.floor((b[0] - pad) / CELL)), int(math.floor((b[2] + pad) / CELL)) + 1):
            for cz in range(int(math.floor((b[1] - pad) / CELL)), int(math.floor((b[3] + pad) / CELL)) + 1):
                grid.setdefault((cx, cz), []).append(idx)

    @staticmethod
    def _near(grid, x, z, r):
        x0, x1 = int(math.floor((x - r) / CELL)), int(math.floor((x + r) / CELL))
        z0, z1 = int(math.floor((z - r) / CELL)), int(math.floor((z + r) / CELL))
        if x0 == x1 and z0 == z1:
            return grid.get((x0, z0), ())
        out = set()
        for cx in range(int(math.floor((x - r) / CELL)), int(math.floor((x + r) / CELL)) + 1):
            for cz in range(int(math.floor((z - r) / CELL)), int(math.floor((z + r) / CELL)) + 1):
                out.update(grid.get((cx, cz), ()))
        return out

    # ------------------------------------------------------------------ queries
    def levels_at(self, x: float, z: float, box_tops: bool = True) -> List[float]:
        """Heights of every surface you could stand on at (x, z), highest first."""
        ys = []
        for i in self._fg.get((int(math.floor(x / CELL)), int(math.floor(z / CELL))), ()):
            f = self.floors[i]
            b = f.bounds
            if b[0] <= x <= b[2] and b[1] <= z <= b[3] and (_in_poly(x, z, f.poly) or _edge_dist(x, z, f.poly) < 0.5):
                ys.append(f.y_at(x, z))
        if box_tops:
            for i in self._bg.get((int(math.floor(x / CELL)), int(math.floor(z / CELL))), ()):
                if self.boxes[i].contains(x, z):
                    ys.append(self.boxes[i].y1)
        return sorted(ys, reverse=True)

    def floor_at(self, x: float, z: float, below: float) -> Optional[float]:
        """Highest standing surface at (x, z) not above ``below``."""
        for y in self.levels_at(x, z):
            if y <= below:
                return y
        return None

    def push_out(self, x: float, z: float, feet: float, radius: float, height: float, step: float) -> Tuple[float, float, bool]:
        """Move the circle (x, z) out of the walls and boxes that reach between the knees and the head.
        Returns (x, z, touched)."""
        lo, hi = feet + step, feet + height
        touched = False
        for _ in range(3):
            moved = False
            for i in self._near(self._wg, x, z, radius):
                w = self.walls[i]
                if w.y1 <= lo or w.y0 >= hi:
                    continue
                wb = w.bounds
                if x < wb[0] - radius or x > wb[2] + radius or z < wb[1] - radius or z > wb[3] + radius:
                    continue
                poly = w.outline(lo, hi)
                n = len(poly)
                if n < 2:
                    continue
                bd, bp = radius, None
                for k in range(n if n > 2 else 1):
                    ax, az = poly[k]; bx, bz = poly[(k + 1) % n]
                    dx, dz = bx - ax, bz - az
                    l2 = dx * dx + dz * dz
                    t = 0.0 if l2 < 1e-12 else max(0.0, min(1.0, ((x - ax) * dx + (z - az) * dz) / l2))
                    px, pz = ax + t * dx, az + t * dz
                    d = math.hypot(x - px, z - pz)
                    if d < bd:
                        bd, bp = d, (px, pz)
                if bp is None:
                    if n > 2 and _in_poly(x, z, poly):           # under / over a leaning wall: out through its face
                        x, z = x + w.normal[0] * radius, z + w.normal[1] * radius
                        moved = touched = True
                    continue
                ex, ez = x - bp[0], z - bp[1]
                if bd < 1e-6:
                    ex, ez, bd = w.normal[0], w.normal[1], 1.0
                x, z = bp[0] + ex / bd * radius, bp[1] + ez / bd * radius
                moved = touched = True
            for i in self._near(self._bg, x, z, radius):
                b = self.boxes[i]
                if b.by1 <= lo or b.by0 >= hi:
                    continue
                bb = b.bounds
                if x < bb[0] - radius or x > bb[2] + radius or z < bb[1] - radius or z > bb[3] + radius:
                    continue
                a, c = b.local(x, z)
                hu, hv = b.hu, b.hv
                qa, qc = max(-hu, min(hu, a)), max(-hv, min(hv, c))
                da, dc = a - qa, c - qc
                d = math.hypot(da, dc)
                if d >= radius:
                    continue
                if d < 1e-6:                                    # the centre is inside: leave through the nearest side
                    pa, pc = hu - abs(a), hv - abs(c)
                    if pa < pc:
                        a = math.copysign(hu + radius, a)
                    else:
                        c = math.copysign(hv + radius, c)
                else:
                    a, c = qa + da / d * radius, qc + dc / d * radius
                x = b.cx + a * b.ux + c * b.vx
                z = b.cz + a * b.uz + c * b.vz
                moved = touched = True
            if not moved:
                break
        return x, z, touched

    def blocked(self, x: float, z: float, feet: float, radius: float, height: float, step: float) -> bool:
        nx, nz, hit = self.push_out(x, z, feet, radius, height, step)
        return hit and math.hypot(nx - x, nz - z) > radius * 0.5


@dataclass
class Walker:
    world: World
    pos: np.ndarray = field(default_factory=lambda: np.zeros(3))      # feet, engine coordinates
    radius: float = 25.0
    height: float = 175.0
    eye: float = 160.0
    step: float = 45.0             # highest step climbed without jumping
    speed: float = 450.0           # units per second
    jump_speed: float = 420.0
    gravity: float = 1400.0
    vy: float = 0.0
    on_ground: bool = False
    fell: int = 0                  # times it fell out of the map
    walked: float = 0.0
    last_ground: Optional[np.ndarray] = None
    status: str = ""

    def place(self, pos) -> None:
        """Put the body at ``pos`` (engine): on the floor right under it if there is one within 3 m."""
        self.pos = np.asarray(pos, np.float64).copy()
        y = self.world.floor_at(self.pos[0], self.pos[2], self.pos[1] + self.step)
        if y is not None and self.pos[1] - y < 300.0:
            self.pos[1] = y
            self.on_ground = True
            self.last_ground = self.pos.copy()
        else:
            self.on_ground = False
        self.vy = 0.0
        self.status = ""

    def update(self, dt: float, move_x: float = 0.0, move_z: float = 0.0, jump: bool = False, run: bool = False) -> None:
        """Advance ``dt`` seconds. (move_x, move_z) is the wished direction in engine coordinates (any length <= 1)."""
        dt = min(max(dt, 0.0), 0.1)
        w = self.world
        ln = math.hypot(move_x, move_z)
        if ln > 1.0:
            move_x, move_z = move_x / ln, move_z / ln
        dist = ln and self.speed * (1.6 if run else 1.0) * dt * min(ln, 1.0)
        steps = max(1, int(math.ceil(dist / (self.radius * 0.5)))) if dist else 0
        x, y, z = (float(v) for v in self.pos)
        for _ in range(steps):
            nx = x + move_x / max(ln, 1e-9) * dist / steps
            nz = z + move_z / max(ln, 1e-9) * dist / steps
            nx, nz, _hit = w.push_out(nx, nz, y, self.radius, self.height, self.step)
            if any(y + self.step < lv < y + self.height for lv in w.levels_at(nx, nz, box_tops=False)):
                continue                                        # a floor at chest height (a ledge, the underside of a stair)
            if self.on_ground:
                fy = w.floor_at(nx, nz, y + self.step)
                if fy is not None and fy > y + 0.01 and w.blocked(nx, nz, fy, self.radius, self.height, self.step):
                    continue                                    # the step up ends inside a wall: stay
                if fy is not None and fy >= y - self.step:
                    y = fy                                      # walk / climb a step / go down a small one
                else:
                    self.on_ground = False                      # walked off an edge
            self.walked += math.hypot(nx - x, nz - z)
            x, z = nx, nz
        if self.on_ground and jump:
            self.vy = self.jump_speed
            self.on_ground = False
        if not self.on_ground:
            self.vy -= self.gravity * dt
            ny = y + self.vy * dt
            fy = w.floor_at(x, z, max(y, ny) + (self.step if self.vy <= 0 else 0.0))
            if self.vy <= 0 and fy is not None and ny <= fy:
                y, self.vy, self.on_ground = fy, 0.0, True
            else:
                y = ny
        else:
            fy = w.floor_at(x, z, y + self.step)
            if fy is None or fy < y - self.step:
                self.on_ground = False
            else:
                y = fy
        self.pos = np.array([x, y, z])
        if self.on_ground:
            self.last_ground = self.pos.copy()
            self.status = ""
        elif y < w.y_min - 300.0 or (self.last_ground is not None and y < self.last_ground[1] - 2500.0
                                     and w.floor_at(x, z, y) is None):
            self.fell += 1
            self.status = "fell out of the map"
            if self.last_ground is not None:
                self.pos = self.last_ground.copy()
                self.vy, self.on_ground = 0.0, True
            else:
                self.pos[1] = w.y_min - 300.0
                self.vy = 0.0

    @property
    def eye_pos(self) -> np.ndarray:
        return self.pos + [0.0, self.eye, 0.0]
