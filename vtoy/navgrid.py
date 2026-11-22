"""Team balance: how far (and how long) each team has to go to the enemy flag, its own flag and the health packs.

The walkable floors of the height map are sampled on a grid (one node per cell and per level: decks above decks are
different nodes).  Neighbouring nodes are joined when a player could go from one to the other: at most ``step`` up, at most
``drop`` down (one way), no wall or collision box in between.  Dijkstra from each flag / from all health packs then gives
the walking distance from every start point.

Distances are along the grid (8 directions), so they are a few percent longer than the real shortest path - equally for both
teams, which is what matters for a comparison."""
from __future__ import annotations

import heapq
import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from .walk import World

SQ2 = math.sqrt(2.0)


@dataclass
class NavGrid:
    cell: float
    nodes: List[Tuple[int, int, float]] = field(default_factory=list)          # (ix, iz, y)
    at: Dict[Tuple[int, int], List[int]] = field(default_factory=dict)         # cell -> node ids (highest first)
    edges: List[List[Tuple[int, float]]] = field(default_factory=list)         # node -> [(node, cost)]
    back: List[List[Tuple[int, float]]] = field(default_factory=list)          # reversed edges

    def position(self, n: int) -> np.ndarray:
        ix, iz, y = self.nodes[n]
        return np.array([(ix + 0.5) * self.cell, y, (iz + 0.5) * self.cell])

    def nearest(self, pos, max_dist: float = 400.0, max_dy: float = 250.0) -> Optional[int]:
        """The node closest to an engine position (same level first)."""
        x, y, z = (float(v) for v in pos)
        cx, cz = int(math.floor(x / self.cell)), int(math.floor(z / self.cell))
        best, bd = None, 1e30
        r = int(math.ceil(max_dist / self.cell))
        for dx in range(-r, r + 1):
            for dz in range(-r, r + 1):
                for n in self.at.get((cx + dx, cz + dz), ()):
                    p = self.position(n)
                    dy = abs(p[1] - y)
                    if dy > max_dy:
                        continue
                    d = math.hypot(p[0] - x, p[2] - z) + dy * 2.0
                    if d < bd:
                        best, bd = n, d
        return best if bd <= max_dist + max_dy * 2 else None

    def distances(self, sources: Sequence[int], reverse: bool = False) -> Tuple[np.ndarray, np.ndarray]:
        """Dijkstra. ``reverse``: distances TO the sources (what a player walking towards a flag needs) instead of from them.
        Returns (distance per node - inf when unreachable, next node on the way to the source or -1)."""
        dist = np.full(len(self.nodes), np.inf)
        nxt = np.full(len(self.nodes), -1, np.int64)
        heap = []
        for s in sources:
            if s is not None and dist[s] > 0:
                dist[s] = 0.0
                heap.append((0.0, s))
        heapq.heapify(heap)
        adj = self.back if reverse else self.edges
        while heap:
            d, n = heapq.heappop(heap)
            if d > dist[n]:
                continue
            for m, c in adj[n]:
                nd = d + c
                if nd < dist[m]:
                    dist[m] = nd
                    nxt[m] = n
                    heapq.heappush(heap, (nd, m))
        return dist, nxt

    def path(self, start: int, nxt: np.ndarray) -> np.ndarray:
        """Points from ``start`` along ``nxt`` (as given by distances(..., reverse=True)) to the source."""
        pts, n, guard = [], start, 0
        while n >= 0 and guard < len(self.nodes) + 1:
            pts.append(self.position(n))
            n = int(nxt[n])
            guard += 1
        return np.array(pts)


def build(world: World, seeds, cell: float = 60.0, radius: float = 25.0, height: float = 175.0, step: float = 45.0,
          drop: float = 400.0, max_nodes: int = 250000, margin: float = 3000.0) -> NavGrid:
    """The part of the map a player can walk to from ``seeds`` (engine positions: start points, flags, health packs).
    Only that part is sampled: the sea floor around a ship is huge and nobody walks there."""
    g = NavGrid(cell)
    done: Dict[Tuple[int, int], List[int]] = {}
    sp = np.asarray([np.asarray(p, np.float64) for p in seeds], np.float64).reshape(-1, 3)
    if not len(sp):
        return g
    # nothing further than ``margin`` outside the box around the seeds: the game happens between them
    bx0, bz0 = int(math.floor((sp[:, 0].min() - margin) / cell)), int(math.floor((sp[:, 2].min() - margin) / cell))
    bx1, bz1 = int(math.floor((sp[:, 0].max() + margin) / cell)), int(math.floor((sp[:, 2].max() + margin) / cell))
    y_low = float(sp[:, 1].min()) - 2.0 * drop

    def nodes_of(ix: int, iz: int) -> List[int]:
        got = done.get((ix, iz))
        if got is not None:
            return got
        if ix < bx0 or ix > bx1 or iz < bz0 or iz > bz1:
            return []
        x, z = (ix + 0.5) * cell, (iz + 0.5) * cell
        ys: List[float] = []
        for y in world.levels_at(x, z):
            if ys and ys[-1] - y < 20.0:                      # the same floor listed twice (overlapping faces)
                continue
            ys.append(y)
        ids = []
        for k, y in enumerate(ys):
            if k > 0 and ys[k - 1] - y < height * 0.6:         # no head room under the level above
                continue
            if y < y_low or world.blocked(x, z, y, radius, height, step):   # far below everything / inside a wall or a box
                continue
            ids.append(len(g.nodes))
            g.nodes.append((ix, iz, y))
            g.edges.append([])
            g.back.append([])
        done[(ix, iz)] = ids
        if ids:
            g.at[(ix, iz)] = ids
        return ids

    def can(y: float, y2: float) -> bool:
        return y2 - y <= cell * 2.2 and y - y2 <= drop        # coarse test; ``climbs`` decides when it is more than a step

    def climbs(x0: float, z0: float, y0: float, x1: float, z1: float, y1: float) -> bool:
        """A rise bigger than one step is fine when it is a slope or a stair: walked in small moves, each within a step."""
        dist = math.hypot(x1 - x0, z1 - z0)
        n = max(2, int(math.ceil(dist / 12.0)))
        cur = y0
        for k in range(1, n + 1):
            t = k / n
            fy = world.floor_at(x0 + (x1 - x0) * t, z0 + (z1 - z0) * t, cur + step)
            if fy is None or cur - fy > drop:
                return False
            cur = fy
        return abs(cur - y1) < 1.0

    todo: List[int] = []
    seen = set()
    for p in seeds:
        x, y, z = (float(v) for v in p)
        cx, cz = int(math.floor(x / cell)), int(math.floor(z / cell))
        for dx in range(-2, 3):
            for dz in range(-2, 3):
                nodes_of(cx + dx, cz + dz)
        n = g.nearest(p)
        if n is not None and n not in seen:
            seen.add(n)
            todo.append(n)
    moves = ((1, 0, 1.0), (-1, 0, 1.0), (0, 1, 1.0), (0, -1, 1.0), (1, 1, SQ2), (1, -1, SQ2), (-1, 1, SQ2), (-1, -1, SQ2))
    while todo:
        n = todo.pop()
        ix, iz, y = g.nodes[n]
        for dx, dz, c in moves:
            best = None
            for m in nodes_of(ix + dx, iz + dz):
                y2 = g.nodes[m][2]
                if can(y, y2) and (best is None or abs(y2 - y) < abs(g.nodes[best][2] - y)):
                    best = m
            if best is None:
                continue
            if dx and dz:                                      # no cutting corners through a blocked cell
                if not any(can(y, g.nodes[m][2]) for m in nodes_of(ix + dx, iz)) or \
                        not any(can(y, g.nodes[m][2]) for m in nodes_of(ix, iz + dz)):
                    continue
            y2 = g.nodes[best][2]
            if y2 - y > step and not climbs((ix + 0.5) * cell, (iz + 0.5) * cell, y, (ix + dx + 0.5) * cell, (iz + dz + 0.5) * cell, y2):
                continue
            # the middle of the move must be free as well (thin walls between two cell centres)
            mx, mz = (ix + 0.5 + dx / 2) * cell, (iz + 0.5 + dz / 2) * cell
            # (a climb: half way up; a step or a drop: at the higher floor - one walks off the edge there, the wall
            # under the edge stops nobody)
            if world.blocked(mx, mz, (y + y2) / 2 if y2 - y > step else max(y, y2), radius, height, step):
                continue
            cost = c * cell + max(0.0, y2 - y)
            g.edges[n].append((best, cost))
            g.back[best].append((n, cost))
            if best not in seen:
                seen.add(best)
                todo.append(best)
        if len(g.nodes) > max_nodes:
            raise ValueError("the walkable area is too big for this cell size: use a bigger cell")
    return g


# ---------------------------------------------------------------------------------------------- the balance report
@dataclass
class TeamReport:
    team: int
    spawns: int = 0
    unreachable: int = 0                      # start points from which the enemy flag cannot be reached
    off_grid: int = 0                         # start points that are not on any floor
    to_enemy_flag: Tuple[float, float, float] = (0.0, 0.0, 0.0)       # min, mean, max distance
    to_own_flag: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    to_health: Tuple[float, float, float] = (0.0, 0.0, 0.0)
    flag_run: float = float("inf")            # enemy flag -> own flag (carrying it home)
    path: Optional[np.ndarray] = None         # a typical way to the enemy flag (from the start point nearest the mean)


def _stats(v: List[float]) -> Tuple[float, float, float]:
    v = [x for x in v if math.isfinite(x)]
    return (min(v), sum(v) / len(v), max(v)) if v else (float("inf"),) * 3


def balance(grid: NavGrid, spawns: Dict[int, list], flags: Dict[int, object], health: Sequence = (), speed: float = 450.0) -> dict:
    """``spawns``: {team: [positions]}, ``flags``: {team: position of ITS flag}, ``health``: positions (engine).
    Returns {'teams': {team: TeamReport}, 'advantage': text key, 'percent', 'faster', 'speed'}."""
    teams = sorted(spawns)
    fnode = {t: (grid.nearest(p) if p is not None else None) for t, p in flags.items()}
    to_flag = {t: grid.distances([n], reverse=True) for t, n in fnode.items() if n is not None}
    hn = [n for n in (grid.nearest(p) for p in health) if n is not None]
    to_h = grid.distances(hn, reverse=True)[0] if hn else None
    out: Dict[int, TeamReport] = {}
    for t in teams:
        rep = TeamReport(team=t, spawns=len(spawns[t]))
        enemy = next((u for u in flags if u != t), None)
        sn = [grid.nearest(p) for p in spawns[t]]
        rep.off_grid = sum(1 for n in sn if n is None)
        sn = [n for n in sn if n is not None]
        if enemy in to_flag and sn:
            d = [float(to_flag[enemy][0][n]) for n in sn]
            rep.unreachable = sum(1 for x in d if not math.isfinite(x))
            rep.to_enemy_flag = _stats(d)
            fin = [(abs(x - rep.to_enemy_flag[1]), n) for x, n in zip(d, sn) if math.isfinite(x)]
            if fin:
                rep.path = grid.path(min(fin)[1], to_flag[enemy][1])
            if t in to_flag and fnode.get(enemy) is not None:
                rep.flag_run = float(to_flag[t][0][fnode[enemy]])
        if t in to_flag and sn:
            rep.to_own_flag = _stats([float(to_flag[t][0][n]) for n in sn])
        if to_h is not None and sn:
            rep.to_health = _stats([float(to_h[n]) for n in sn])
        out[t] = rep
    res = {"teams": out, "speed": speed, "faster": None, "percent": 0.0, "nodes": len(grid.nodes)}
    if len(teams) >= 2:
        a, b = out[teams[0]], out[teams[1]]
        # an attack = reach the enemy flag and bring it home
        ta = a.to_enemy_flag[1] + a.flag_run
        tb = b.to_enemy_flag[1] + b.flag_run
        if math.isfinite(ta) and math.isfinite(tb) and max(ta, tb) > 0:
            res["percent"] = abs(ta - tb) / max(ta, tb) * 100.0
            res["faster"] = teams[0] if ta < tb else teams[1] if tb < ta else None
            res["attack"] = {teams[0]: ta, teams[1]: tb}
        elif math.isfinite(ta) != math.isfinite(tb):
            res["faster"] = teams[0] if math.isfinite(ta) else teams[1]
            res["percent"] = 100.0
    return res
