"""Even more map tools: fair light between twin ships, weather / sky presets, animation paths, match simulation (every game
mode), changes since a saved version, gaps in the floor collision, buried objects, OBJ export with collision, symmetric
game-mode layouts."""
from __future__ import annotations

import math
import os
import struct
from typing import Dict, List, Optional

import numpy as np

from .. import crop as cropmod

F = np.array([1.0, 1.0, -1.0])

PRESETS = {
    # sky textures tried in order, fog colour, fog near / far (share of the camera far plane), ambient, sun colour, sun dir
    "day":    (["cielo_malibu", "cieloazulado", "CIELO_A"], (190, 210, 230), 0.45, 0.95, (0.55, 0.55, 0.55), (1.0, 0.97, 0.9), (0.3, -1.0, 0.4)),
    "sunset": (["cielo_laberinto", "cielo_mio", "CIELO_C"], (215, 140, 90), 0.35, 0.9, (0.42, 0.32, 0.28), (1.0, 0.62, 0.35), (0.9, -0.35, 0.2)),
    "night":  (["cielo_negro", "CIELO_E", "CIELO_D"], (12, 16, 30), 0.25, 0.8, (0.18, 0.2, 0.3), (0.3, 0.35, 0.55), (0.2, -1.0, 0.3)),
    "storm":  (["cielo_war", "CIELO_D"], (70, 72, 78), 0.15, 0.6, (0.3, 0.3, 0.33), (0.45, 0.45, 0.5), (0.1, -1.0, 0.1)),
    "fog":    ([], (160, 165, 170), 0.03, 0.35, (0.45, 0.45, 0.47), (0.6, 0.6, 0.62), (0.2, -1.0, 0.2)),
}



def _bleed_colours(rgba: np.ndarray, steps: int = 8) -> np.ndarray:
    """The colour of the see-through pixels (alpha 0) made that of the nearest visible ones (the rest: their average),
    so that smoothing or shrinking the texture brings no key colour (Half-Life's blue) into the edges."""
    out = rgba.copy()
    col = out[..., :3].astype(np.float32)
    known = out[..., 3] > 0
    if not known.any():
        return out
    for _ in range(steps):
        if known.all():
            break
        acc = np.zeros_like(col)
        cnt = np.zeros(known.shape, np.float32)
        for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0)):
            k = np.roll(known, (dy, dx), (0, 1))
            acc += np.roll(col, (dy, dx), (0, 1)) * k[..., None]
            cnt += k
        new = ~known & (cnt > 0)
        col[new] = acc[new] / cnt[new][:, None]
        known = known | new
    col[~known] = col[out[..., 3] > 0].mean(0)
    out[..., :3] = np.clip(col + 0.5, 0, 255).astype(np.uint8)
    return out


MESH_TILE = 3000.0         # an imported map's meshes: one per texture and per square of this side (engine units)
MESH_FACES = 600           # and at most this many faces each (the game's own meshes are small: <= 1427 corners)
MESH_MAX_VERTICES = 2000   # a mesh with more is cut (bigger ones closed the game at the end of the loading: aztec)
SECTOR_LEAF = 700.0        # a new map's sector leaves: the game's maps list a few dozen boxes / meshes per leaf


def mesh_tiles(faces, tile: float = MESH_TILE, most: int = MESH_FACES) -> list:
    """``faces`` (polygons with ``points``) of one texture in groups: by the square of side ``tile`` their middle
    is in, at most ``most`` each - so a mesh is drawn only where it is (the sectors) and none is very big."""
    groups = {}
    for f in faces:
        p = np.asarray(f.points if hasattr(f, "points") else f[0], np.float64)
        c = p.reshape(-1, 3).mean(0)
        groups.setdefault((int(np.floor(c[0] / tile)), int(np.floor(c[2] / tile))), []).append(f)
    out = []
    for key in sorted(groups):
        g = groups[key]
        for k in range(0, len(g), most):
            out.append(g[k:k + most])
    return out

class MoreOps2:
    # ================================================================================== 1. the same light on both ships
    def _ships(self):
        from .. import twinships
        hlo, hhi, hm, world = self._twin_stock()
        off = twinships.ship_offset(self.opt, hm, hlo, hhi, 800.0, world)
        if abs(off) < float(hhi[0] - hlo[0]) * 0.5:
            raise ValueError("this does not look like a twin ships map")
        return np.asarray(hlo, np.float64), np.asarray(hhi, np.float64), float(off)

    def _light_at(self, pts: np.ndarray, nrm: np.ndarray) -> np.ndarray:
        """Brightness (0..1, mean of R G B, both sides of the faces) of the map's lights at points with normals (engine)."""
        tot = np.zeros((len(pts), 3))
        for l in self.opt.lights:
            t = int(l.type)
            dif = np.asarray(l.diffuse[:3], np.float64)
            if t == 3:
                tot += dif
                continue
            if t == 2:
                d = np.asarray(l.direction, np.float64)
                n = np.linalg.norm(d)
                if n < 1e-9:
                    continue
                tot += np.abs(nrm @ (d / n))[:, None] * dif
                continue
            v = np.asarray(l.position, np.float64) - pts
            dist = np.linalg.norm(v, axis=1)
            end = float(l.end or l.radius or 0.0)
            if end <= 0:
                continue
            mid = max((max(float(l.start), 0.0) + end) / 2.0, 1.0)
            att = np.where(dist < end, 1.0 / (1.0 + dist * dist / (mid * mid)), 0.0)
            lam = np.abs((nrm * v).sum(1)) / np.maximum(dist, 1e-6)
            tot += (att * lam)[:, None] * dif + att[:, None] * np.asarray(l.ambient[:3], np.float64)
        return np.clip(tot, 0, 1).mean(1)

    def ship_light_report(self, cell: float = 400.0) -> dict:
        """How bright each ship is (the same light on the same part of each ship = fair): {'a', 'b', 'diff' (%),
        'spots': [{pos_a, a, b}] the parts lit most differently}."""
        hlo, hhi, off = self._ships()
        tris, _alpha, _o = self._map_tris()
        c = tris.mean(1)
        g = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
        area = np.linalg.norm(g, axis=1) / 2
        nrm = g / np.maximum(area * 2, 1e-9)[:, None]
        ina = (c[:, 0] >= hlo[0]) & (c[:, 0] <= hhi[0]) & (c[:, 2] >= hlo[2]) & (c[:, 2] <= hhi[2]) & (area > 1)
        inb = (c[:, 0] >= hlo[0] + off) & (c[:, 0] <= hhi[0] + off) & (c[:, 2] >= hlo[2]) & (c[:, 2] <= hhi[2]) & (area > 1)
        if not ina.any() or not inb.any():
            raise ValueError("the ships were not found in the map")
        la, lb = self._light_at(c[ina], nrm[ina]), self._light_at(c[inb], nrm[inb])
        A = float((la * area[ina]).sum() / area[ina].sum())
        B = float((lb * area[inb]).sum() / area[inb].sum())
        # the same part of each ship: squares in ship coordinates
        ka = np.floor((c[ina][:, [0, 2]] - hlo[[0, 2]]) / cell).astype(int)
        kb = np.floor((c[inb][:, [0, 2]] - hlo[[0, 2]] - [off, 0]) / cell).astype(int)
        sa: Dict[tuple, list] = {}
        sb: Dict[tuple, list] = {}
        for k, v, w, p in zip(map(tuple, ka), la, area[ina], c[ina]):
            sa.setdefault(k, [0.0, 0.0, p])
            sa[k][0] += v * w
            sa[k][1] += w
        for k, v, w in zip(map(tuple, kb), lb, area[inb]):
            sb.setdefault(k, [0.0, 0.0])
            sb[k][0] += v * w
            sb[k][1] += w
        spots = []
        for k in set(sa) & set(sb):
            a_, b_ = sa[k][0] / sa[k][1], sb[k][0] / sb[k][1]
            if abs(a_ - b_) > 0.05:
                spots.append({"pos_a": sa[k][2], "pos_b": sa[k][2] + [off, 0, 0], "a": a_, "b": b_})
        spots.sort(key=lambda d: -abs(d["a"] - d["b"]))
        return {"a": A, "b": B, "diff": 100.0 * abs(A - B) / max(A, B, 1e-6), "spots": spots, "offset": off}

    def fair_ship_lights(self) -> str:
        """Ship B gets exactly the lights of ship A at the same place of the ship (B is a copy moved along X, not a
        mirror), so every part of both ships is lit the same.  Suns and the ambient light are the same everywhere."""
        msg = self.twin_lights(mirror=False)
        try:
            r = self.ship_light_report()
            msg += f"; brightness A {100 * r['a']:.0f}% / B {100 * r['b']:.0f}% (difference {r['diff']:.1f}%)"
        except Exception:
            pass
        return msg

    # ================================================================================== 2. weather / sky presets
    def weather_preset(self, name: str, lights: bool = True) -> str:
        """Sky, fog (and, with ``lights``, the ambient light and the suns' colour) for a look: day, sunset, night, storm, fog."""
        if name not in PRESETS:
            raise ValueError(f"unknown preset {name}")
        skies, fog, near, far, amb, sun, sdir = PRESETS[name]
        self.push_undo(True, "weather " + name)
        have = {os.path.splitext(os.path.basename(p))[0].lower(): os.path.splitext(os.path.basename(p))[0]
                for p in self.fs.list("texs", ".tex")}
        sky = next((have[s.lower()] for s in skies if s.lower() in have), None)
        if sky:
            self.set_sky(sky + ".tex" if not sky.lower().endswith(".tex") else sky)
        cf = float(self.scene.cam_far or 11000.0)
        self.scene.fog_color = tuple(int(v) for v in fog)
        self.scene.fog_near, self.scene.fog_far = cf * near, cf * far
        self.dirty_scene = True
        done = [f"sky {sky}" if sky else "sky kept", "fog"]
        if lights and self.opt is not None:
            from ..opt import Light, LightType
            ambs = [l for l in self.opt.lights if int(l.type) == 3]
            if not ambs:
                ambs = [Light(type=LightType.AMBIENT)]
                self.opt.lights.append(ambs[0])
            ambs[0].diffuse = tuple(float(v) for v in amb) + (1.0,)
            suns = [l for l in self.opt.lights if int(l.type) == 2]
            if not suns:
                suns = [Light(type=LightType.DIRECTIONAL)]
                self.opt.lights.append(suns[0])
            for k, s in enumerate(suns):
                f = 1.0 if k == 0 else 0.5                          # the other suns: softer fill light
                s.diffuse = tuple(float(v) * f for v in sun) + (1.0,)
            d = np.asarray(sdir, np.float64)
            suns[0].direction = (d / np.linalg.norm(d)).astype(np.float32)
            self.dirty_map = True
            done.append("ambient light and suns")
        return f"{name}: " + ", ".join(done) + " - see it with Lit view, save scene and map"

    # ================================================================================== 3. animation paths
    def animation_paths(self, samples: int = 120) -> list:
        """[(module, points (n, 3) engine, key name)] where the animated models of the scene go (the part of the model
        that moves the most), for the view."""
        from ..keys import KeyFile
        out = []
        for r in self.scene.modules:
            p = r.parsed
            k = getattr(p, "key_name", None) if p is not None else None
            if not k or not isinstance(getattr(p, "transform", None), np.ndarray):
                continue
            path = self._key_path(k)
            if not path:
                continue
            try:
                kf = KeyFile.load(path)
            except Exception:
                continue
            if kf.frames < 2:
                continue
            pos = kf.poses["pos"].astype(np.float64)                 # (frames, nodes, 3)
            spread = (pos.max(0) - pos.min(0)).max(1)
            node = int(np.argmax(spread))
            if spread[node] < 5.0:
                continue
            idx = np.linspace(0, kf.frames - 1, min(samples, kf.frames)).astype(int)
            M = np.asarray(p.transform, np.float64)
            pts = pos[idx, node] @ M[:3, :3] + M[3, :3]
            out.append((r, pts, k))
        return out

    def transform_key(self, name: str, scale: float = 1.0, offset=(0.0, 0.0, 0.0), new_name: str = "",
                      use_in_module=None) -> str:
        """A copy of animation ``name`` whose movement is ``scale`` times as big and moved by ``offset`` (the route of a
        helicopter / a boat: wider, higher ...).  Saved next to it with a new name (never over a file)."""
        from ..keys import KeyFile
        src = self._key_path(name)
        if not src:
            raise ValueError(f"{name} not found in keys/")
        k = KeyFile.load(src)
        base = os.path.splitext(os.path.basename(src))[0]
        stem = os.path.splitext(os.path.basename(new_name.strip()))[0] if new_name.strip() else f"{base}_route"
        dst = os.path.join(os.path.dirname(src), stem + ".key")
        if os.path.exists(dst):
            raise ValueError(f"{stem}.key already exists - pick another name (it is never replaced)")
        pos = k.poses["pos"].astype(np.float64)
        spread = (pos.max(0) - pos.min(0)).max(1)
        node = int(np.argmax(spread)) if len(spread) else 0
        c = pos[:, node].mean(0)
        pos[:, node] = (pos[:, node] - c) * float(scale) + c + np.asarray(offset, np.float64)
        k.poses["pos"] = pos.astype(np.float32)
        with open(dst, "wb") as fh:
            fh.write(k.to_bytes())
        KeyFile.load(dst)
        self.fs.rescan()
        msg = f"{stem}.key made (route x{float(scale):g}, moved {np.round(offset).tolist()})"
        if use_in_module is not None:
            n = self.point_module_to_key(use_in_module, name, stem + ".key")
            if n:
                msg += " - the module uses it now, save the scene"
        return msg

    def point_module_to_key(self, rec, old: str, new_file: str) -> int:
        """Make module ``rec`` use another .key (same folder as the old one); the name's length prefix is kept right."""
        old = str(old).rstrip("\0")
        folder = old[: len(old) - len(os.path.basename(old.replace("\\", "/")))]
        new = folder + new_file
        p = rec.parsed
        if p is None or not hasattr(p, "tail"):
            return 0
        raw = bytes(p.tail)
        ob = old.encode("cp1252")
        i = raw.lower().find(ob.lower())
        if i < 0:
            return 0
        nb = new.encode("cp1252")
        j = i
        if i >= 4 and struct.unpack_from("<I", raw, i - 4)[0] in (len(ob), len(ob) + 1):
            had = struct.unpack_from("<I", raw, i - 4)[0]
            p.tail = raw[: i - 4] + struct.pack("<I", len(nb) + (had - len(ob))) + nb + raw[i + len(ob):]
        else:
            p.tail = raw[:j] + nb + raw[j + len(ob):]
        self.dirty_scene = self.needs_rebake = True
        return 1

    # ================================================================================== 4. match simulation
    def simulate_match(self, cell: float = 100.0, speed: float = 450.0, contact: Optional[float] = None) -> dict:
        """Players run from every start point to what the game mode makes them go to, along the shortest walkable way:
        capture the flag - to the enemy flag and back; destroy the target - to the target; team deathmatch - towards the
        other team; deathmatch - to the health packs and the middle.  Returns the routes, where the routes are used the
        most and where / when the teams (or players) meet first."""
        from .. import gamemode, navgrid
        world = self.walk_world()
        if not world.floors:
            raise ValueError("this map has no floor collision (.hm): nothing to walk on")
        sp = self.spawn_positions()
        mode0 = gamemode.mode_of(self.scene) or "DM"
        if contact is None:
            contact = 500.0 if mode0 == "DM" else 1000.0                 # in sight, roughly
        if not sp:
            raise ValueError("the scene has no start points")
        mode = gamemode.mode_of(self.scene) or "DM"
        mods = {}
        for r in self.scene.modules:
            p = r.parsed
            if p is None:
                continue
            pos = getattr(p, "position", None)
            if pos is None and isinstance(getattr(p, "transform", None), np.ndarray):
                pos = p.transform[3, :3]
            if pos is not None:
                mods.setdefault(r.clean_name.lower(), []).append((r, np.asarray(pos, np.float64)))
        flags = {int(r.parsed.team): q for r, q in mods.get("mp_flag", []) if hasattr(r.parsed, "team")}
        health = [q for _r, q in mods.get("mp_salud", [])]
        targets = [q for _r, q in mods.get("mp_bombzone", [])]
        seeds = [q for lst in sp.values() for _n, q in lst] + list(flags.values()) + health + targets
        g = navgrid.build(world, seeds, cell=cell)
        near = lambda q: g.nearest(q, 600.0, 400.0)
        cache: Dict[int, np.ndarray] = {}

        def to(goal_node):
            if goal_node not in cache:
                cache[goal_node] = g.distances([goal_node], reverse=True)[1]
            return cache[goal_node]
        everyone = [(t, n, q) for t, lst in sp.items() for n, q in lst]
        centre = np.mean([q for _t, _n, q in everyone], 0)
        routes = []
        for team, name, q in everyone:
            s = near(q)
            if s is None:
                continue
            goals = []
            if mode == "B" and flags:
                enemy = [f for t, f in flags.items() if t != team] or list(flags.values())
                goals = [enemy[0]] + ([flags[team]] if team in flags else [])
            elif mode == "DO" and targets:
                goals = [min(targets, key=lambda x: np.linalg.norm(x - q))]
            elif mode == "DMT" or (mode in ("B", "DO") and len(sp) > 1):
                other = [p for t, _n, p in everyone if t != team]
                goals = [np.mean(other, 0)] if other else [centre]
            else:
                goals = ([min(health, key=lambda x: np.linalg.norm(x - q))] if health else []) + [centre]
            pts = []
            cur = s
            for gpos in goals:
                gn = near(gpos)
                if gn is None:
                    continue
                nxt = to(gn)
                seg = g.path(cur, nxt)
                if len(seg) < 2 or g.nearest(seg[-1], 1.0, 1.0) is None and np.linalg.norm(seg[-1] - g.position(gn)) > cell * 2:
                    continue
                pts.extend(seg if not pts else seg[1:])
                cur = gn
            if len(pts) >= 2:
                routes.append({"team": team, "name": name, "points": np.asarray(pts)})
        if not routes:
            raise ValueError("no start point can walk to its goal")
        # traffic: how many routes go through each square
        heat: Dict[tuple, int] = {}
        for r in routes:
            seen = set()
            for p in r["points"]:
                k = (int(math.floor(p[0] / (cell * 4))), int(math.floor(p[2] / (cell * 4))))
                if k not in seen:
                    seen.add(k)
                    heat[k] = heat.get(k, 0) + 1
        busy = sorted(({"pos": np.array([(k[0] + 0.5) * cell * 4, 0.0, (k[1] + 0.5) * cell * 4]), "routes": v}
                       for k, v in heat.items()), key=lambda d: -d["routes"])[:15]
        for d in busy:
            y = world.floor_at(d["pos"][0], d["pos"][2], 1e6)
            d["pos"][1] = y if y is not None else centre[1]
        # first meetings: two players of different teams (any two in deathmatch) closer than ``contact``
        def timed(r):
            p = r["points"]
            seg = np.linalg.norm(np.diff(p, axis=0), axis=1)
            return p, np.concatenate([[0.0], np.cumsum(seg)]) / speed
        tl = [timed(r) for r in routes]
        meets = []
        for i in range(len(routes)):
            for j in range(i + 1, len(routes)):
                if mode != "DM" and routes[i]["team"] == routes[j]["team"]:
                    continue
                (pa, ta), (pb, tb) = tl[i], tl[j]
                T = np.arange(0.0, min(ta[-1], tb[-1]) + 0.5, 0.5)
                if not len(T):
                    continue
                A = np.stack([np.interp(T, ta, pa[:, k]) for k in range(3)], 1)
                B = np.stack([np.interp(T, tb, pb[:, k]) for k in range(3)], 1)
                d = np.linalg.norm(A - B, axis=1)
                hit = np.nonzero((d < contact) & (T >= 1.0))[0]          # (not already side by side at the start)
                if len(hit):
                    k = int(hit[0])
                    meets.append({"pos": (A[k] + B[k]) / 2, "time": float(T[k]), "who": f"{routes[i]['name']} / {routes[j]['name']}"})
        meets.sort(key=lambda m: m["time"])
        return {"mode": mode, "routes": routes, "busy": busy, "meets": meets[:20],
                "first": meets[0]["time"] if meets else None}

    # ================================================================================== 5. changes since a saved version
    def version_marks(self, stamp: str) -> list:
        """What changed between a saved version and the map / scene as they are now: [(kind, '+' | '-' | '~', pos engine)]."""
        import json
        from ..modules import parse_modules
        from ..opt import OptMap
        from ..scn import Scene
        d = self.history_dir()
        with open(os.path.join(d, stamp + ".json"), encoding="utf-8") as f:
            e = json.load(f)
        files = {k: open(os.path.join(d, "files", v["sha1"]), "rb").read() for k, v in e["files"].items()}
        out = []
        if "opt" in files and self.opt is not None:
            old = OptMap.parse(files["opt"])

            def sig_mesh(o):
                used = {p.mesh_index for p in o.props}
                r = {}
                for i, m in enumerate(o.meshes):
                    if i in used:
                        continue
                    lo, hi = cropmod.mesh_bounds(m)
                    if np.isfinite(lo).all():
                        r.setdefault(tuple(np.round(np.concatenate([lo, hi]), -1)), (lo + hi) / 2)
                return r

            def sig_prop(o):
                return {(p.mesh_index,) + tuple(np.round(np.asarray(p.transform, np.float64)[3, :3], -1)): np.asarray(p.transform, np.float64)[3, :3]
                        for p in o.props}
            for label, f in (("mesh", sig_mesh), ("prop", sig_prop)):
                a, b = f(old), f(self.opt)
                out += [(label, "+", b[k]) for k in set(b) - set(a)]
                out += [(label, "-", a[k]) for k in set(a) - set(b)]
            from .. import meshbox
            ba = {tuple(np.round(np.concatenate([c, h]), 0)): c for c, h, _R in meshbox.map_boxes(old)}
            bb = {tuple(np.round(np.concatenate([c, h]), 0)): c for c, h, _R in meshbox.map_boxes(self.opt)}
            out += [("box", "+", bb[k]) for k in set(bb) - set(ba)]
            out += [("box", "-", ba[k]) for k in set(ba) - set(bb)]
        if "scene" in files:
            sc = Scene.parse(files["scene"], "")
            parse_modules(sc)

            def mods(s):
                r = {}
                for m in s.modules:
                    p = m.parsed
                    pos = getattr(p, "position", None) if p is not None else None
                    if pos is None and p is not None and isinstance(getattr(p, "transform", None), np.ndarray):
                        pos = p.transform[3, :3]
                    if pos is not None:
                        r[str(m.object_name).rstrip("\0").lower()] = np.asarray(pos, np.float64)
                return r
            a, b = mods(sc), mods(self.scene)
            out += [("module", "+", b[k]) for k in set(b) - set(a)]
            out += [("module", "-", a[k]) for k in set(a) - set(b)]
            out += [("module", "~", b[k]) for k in set(a) & set(b) if np.linalg.norm(a[k] - b[k]) > 0.5]
        return out

    # ================================================================================== 6. gaps in the floor collision
    def floor_gaps(self, probe: float = 15.0, far: float = 70.0) -> list:
        """Cracks between floor faces of the .hm: just past the edge of a floor there is nothing, a little further there
        is floor again at about the same height (a foot can get stuck, or a player falls through).  [{'pos', 'width'}]"""
        from .. import hmcopy
        try:
            hm = self.heightmap_edit()
        except ValueError:
            return []
        world = self.walk_world()
        out = []
        for f in hmcopy.unique_faces(hm):
            n = np.asarray(f.normal, np.float64)
            if n[1] < 0.7:
                continue
            for c in f.contours:
                c = np.asarray(c, np.float64)
                if len(c) < 3:
                    continue
                cen = c.mean(0)
                for a, b in zip(c, np.roll(c, -1, 0)):
                    e = b - a
                    L = math.hypot(e[0], e[2])
                    if L < 20:
                        continue
                    m = (a + b) / 2
                    out_v = np.array([e[2], 0.0, -e[0]]) / L
                    if out_v @ (m - cen) < 0:
                        out_v = -out_v
                    q = m + out_v * probe
                    if world.floor_at(q[0], q[2], m[1] + 45.0) is not None:
                        continue
                    if world.blocked(q[0], q[2], m[1], 5.0, 120.0, 45.0):
                        continue
                    for dist in (35.0, far):
                        r = m + out_v * dist
                        y = world.floor_at(r[0], r[2], m[1] + 45.0)
                        if y is not None and abs(y - m[1]) < 45.0:
                            out.append({"pos": m, "width": dist})
                            break
        from .state_more import _clusters
        cl = _clusters([d["pos"] for d in out], 300.0)
        return cl

    # ================================================================================== 7. buried / lost objects
    def buried_objects(self, margin: float = 20.0) -> list:
        """Meshes and props that are completely under the floor (nobody can see them, but they are still drawn):
        [{'kind', 'index', 'pos', 'size'}]."""
        from .. import autohm
        world = self.walk_world()
        out = []
        for kind, i in self._visible_kinds():
            try:
                tris, _ = autohm.triangles_of(self.opt, kind, i)
            except Exception:
                continue
            if not len(tris):
                continue
            p = tris.reshape(-1, 3)
            lo, hi = p.min(0), p.max(0)
            size = hi - lo
            if size.max() > 3000:                                  # terrain, sea ...
                continue
            cx, cz = (lo[0] + hi[0]) / 2, (lo[2] + hi[2]) / 2
            top = world.floor_at(cx, cz, 1e7)
            if top is None or hi[1] > top - margin:
                continue
            under = world.floor_at(cx, cz, hi[1] + 5.0)            # a lower floor it could be standing on (a basement)
            if under is not None and under > lo[1] - 300.0:
                continue
            out.append({"kind": kind, "index": i, "pos": (lo + hi) / 2, "size": size, "depth": float(top - hi[1])})
        out.sort(key=lambda d: -d["depth"])
        return out

    # ================================================================================== 8. OBJ export (with collision)
    def export_obj(self, path: str, only_selection: bool = True, with_collision: bool = True) -> str:
        """The selected meshes / props (or the whole map) as an OBJ + MTL + PNG textures, for Blender.  The collision boxes
        inside go along as material 'collision': imported back with 'Import model (OBJ)' they become boxes again."""
        from PIL import Image
        from .. import autohm, meshbox
        if only_selection:
            items = []
            for s in self._selected():
                if s.kind == "mesh":
                    i = next((k for k, m in enumerate(self.opt.meshes) if m is s.ref), None)
                    if i is not None:
                        items.append(("mesh", i))
                elif s.kind == "prop":
                    i = next((k for k, p in enumerate(self.opt.props) if p is s.ref), None)
                    if i is not None:
                        items.append(("prop", i))
            if not items:
                raise ValueError("select meshes / props first")
        else:
            items = self._visible_kinds()
        folder = os.path.dirname(os.path.abspath(path))
        os.makedirs(folder, exist_ok=True)
        stem = os.path.splitext(os.path.basename(path))[0]
        groups: Dict[str, list] = {}
        lo_all, hi_all = np.full(3, np.inf), np.full(3, -np.inf)
        for kind, i in items:
            me, M = autohm._mesh_matrix(self.opt, kind, i)
            A = M[:3, :3]
            NA = np.linalg.inv(A).T if abs(np.linalg.det(A)) > 1e-12 else A
            for sm in me.render_submeshes():
                if sm.vertices is None or not len(sm.vertices) or len(sm.indices) < 3:
                    continue
                idx = np.asarray(sm.indices, np.int64)[: len(sm.indices) // 3 * 3].reshape(-1, 3)
                idx = idx[(idx < len(sm.vertices)).all(1)]
                mat = me.materials[sm.material_index] if sm.material_index < len(me.materials) else None
                tex = str((mat.textures[0] if mat is not None and mat.textures else "") or "untextured").rstrip("\0")
                p = sm.vertices["pos"].astype(np.float64) @ A + M[3, :3]
                n = sm.vertices["nrm"].astype(np.float64) @ NA
                groups.setdefault(tex, []).append((p, n, sm.vertices["uv"].astype(np.float64), idx))
                lo_all, hi_all = np.minimum(lo_all, p.min(0)), np.maximum(hi_all, p.max(0))
        if not groups:
            raise ValueError("nothing to export")
        origin = np.array([(lo_all[0] + hi_all[0]) / 2, lo_all[1], (lo_all[2] + hi_all[2]) / 2])
        boxes = []
        if with_collision:
            for c, h, R in meshbox.map_boxes(self.opt):
                if np.all(c >= lo_all - 5) and np.all(c <= hi_all + 5):
                    boxes.append((c, h, R))

        def to_obj(p):
            q = (np.asarray(p, np.float64) - origin) / 100.0
            return q * [1.0, 1.0, -1.0]
        lines = [f"# VToyEditor Plus+ export: {len(items)} objects, {len(boxes)} collision boxes",
                 f"# vtoy-origin {origin[0]:.3f} {origin[1]:.3f} {origin[2]:.3f}", f"mtllib {stem}.mtl", f"o {stem}"]
        mtl = []
        vbase = 1
        for tex, parts in groups.items():
            mname = os.path.splitext(tex)[0]
            mtl += [f"newmtl {mname}", "Kd 1 1 1"]
            t = self.fs.texture(tex)
            if t is not None:
                png = f"{mname}.png"
                try:
                    Image.fromarray(t.decode()).save(os.path.join(folder, png))
                    mtl.append(f"map_Kd {png}")
                except Exception:
                    pass
            lines.append(f"usemtl {mname}")
            for p, n, uv, idx in parts:
                q = to_obj(p)
                nn = n * [1.0, 1.0, -1.0]
                lines += [f"v {a:.5f} {b:.5f} {c:.5f}" for a, b, c in q]
                lines += [f"vt {u:.5f} {1.0 - v:.5f}" for u, v in uv]
                lines += [f"vn {a:.4f} {b:.4f} {c:.4f}" for a, b, c in nn]
                for t3 in idx + vbase:
                    a, b, c = (int(x) for x in t3)
                    lines.append(f"f {a}/{a}/{a} {c}/{c}/{c} {b}/{b}/{b}")      # mirrored z: the winding turns too
                vbase += len(p)
        if boxes:
            mtl += ["newmtl collision", "Kd 1 0 0", "d 0.3"]
            lines.append("usemtl collision")
            faces = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
            for c, h, R in boxes:
                q = np.array([[x, y, z] for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)], np.float64) * h @ R + c
                lines += [f"v {a:.5f} {b:.5f} {cc:.5f}" for a, b, cc in to_obj(q)]
                lines.append("vt 0 0")
                lines.append("vn 0 1 0")
                vt, vn = vbase, vbase
                for a, b, cc, d in faces:
                    A_, B_, C_, D_ = (vbase + x for x in (a, b, cc, d))
                    lines.append(f"f {A_}/{vt}/{vn} {C_}/{vt}/{vn} {B_}/{vt}/{vn}")
                    lines.append(f"f {A_}/{vt}/{vn} {D_}/{vt}/{vn} {C_}/{vt}/{vn}")
                vbase += 8
        with open(os.path.join(folder, stem + ".obj"), "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        with open(os.path.join(folder, stem + ".mtl"), "w", encoding="utf-8") as f:
            f.write("\n".join(mtl) + "\n")
        return (f"{stem}.obj: {len(items)} objects, {sum(len(p[3]) for g in groups.values() for p in g)} triangles, "
                f"{len(groups)} textures, {len(boxes)} collision boxes -> {folder}")

    # ================================================================================== 9. symmetric game-mode layouts
    def symmetric_layout(self, mode: str, base_a, base_b, per_team: int = 8, radius: float = 350.0,
                         health: int = 4) -> str:
        """Lay out a game mode fairly between two points (the two bases): ``per_team`` start points round each base
        facing the other one, the flags on the bases (capture the flag), the target in the middle (destroy the target),
        health packs in pairs at the same distance from each base.  Deathmatch: start points spread over the walkable
        map, as far apart from each other as possible.  The old start points / flags / targets are replaced."""
        from .. import gamemode
        a, b = np.asarray(base_a, np.float64), np.asarray(base_b, np.float64)
        tpl = self.templates()
        self.push_undo(True, "game mode layout")
        drop = {"mp_cstartpoint"} | ({"mp_flag"} if mode == "B" else set()) | ({"mp_bombzone"} if mode == "DO" else set())
        old_health = [r for r in self.scene.modules if r.clean_name.lower() == "mp_salud"]
        self.scene.modules[:] = [r for r in self.scene.modules if r.clean_name.lower() not in drop and not self.is_locked(r)
                                 or (r.clean_name.lower() in drop and self.is_locked(r))]
        floor = lambda q: self.floor_below(q[0], q[2], q[1] + 300.0)
        notes = []

        def put_start(q, look, team):
            y = floor(q)
            q = np.array([q[0], (y if y is not None else q[1]) + 20.0, q[2]])
            v = look - q
            gamemode.add_start_point(self.scene, q, math.atan2(v[0], v[2]), team)
        if mode == "DM":
            from .. import navgrid
            g = navgrid.build(self.walk_world(), [a, b], cell=150.0)
            if not g.nodes:
                raise ValueError("no walkable floor around those points")
            pts = np.array([g.position(n) for n in range(len(g.nodes))])
            chosen = [pts[int(np.argmin(np.linalg.norm(pts - (a + b) / 2, axis=1)))]]
            dmin = np.linalg.norm(pts - chosen[0], axis=1)
            while len(chosen) < per_team * 2:
                k = int(np.argmax(dmin))
                chosen.append(pts[k])
                dmin = np.minimum(dmin, np.linalg.norm(pts - pts[k], axis=1))
            mid = pts.mean(0)
            for k, q in enumerate(chosen):
                put_start(q, mid, k % 2)
        else:
            for team, (me, other) in enumerate(((a, b), (b, a))):
                for k in range(per_team):
                    ang = 2 * math.pi * k / per_team
                    q = me + np.array([radius * math.cos(ang), 0.0, radius * math.sin(ang)])
                    put_start(q, other, team)
            if mode == "B":
                for team, q in ((0, a), (1, b)):
                    y = floor(q)
                    if gamemode.add_flag(self.scene, tpl, (q[0], y if y is not None else q[1], q[2]), team) is None:
                        notes.append("no flag template found: add the flags by hand")
            if mode == "DO":
                m = (a + b) / 2
                y = floor(m)
                if gamemode.add_simple(self.scene, tpl, "mp_BombZone", (m[0], y if y is not None else m[1], m[2]), "bombzone") is None:
                    notes.append("no bomb zone template found: add it by hand")
        if health and not old_health:
            d = b - a
            side = np.array([-d[2], 0.0, d[0]])
            side /= max(np.linalg.norm(side), 1e-9)
            for k in range(max(1, health // 2)):
                t = 0.3 + 0.4 * k / max(1, health // 2 - 1) if health > 2 else 0.5
                for sgn, q in ((1, a + d * t), (-1, b - d * t)):            # the same place seen from each base
                    q = q + side * 400.0 * sgn * (1 if k % 2 == 0 else -1)
                    y = floor(q)
                    gamemode.add_health(self.scene, tpl, (q[0], (y if y is not None else q[1]) + 20.0, q[2]), "big" if k == 0 else "small")
        if mode in gamemode.MODES:
            gamemode.set_mode(self.scene, mode)
        self.dirty_scene = self.needs_rebake = True
        n = sum(1 for r in self.scene.modules if r.clean_name.lower() == "mp_cstartpoint")
        return f"{gamemode.MODES.get(mode, (mode,))[0]}: {n} start points" + "".join("; " + x for x in notes) + " - save the scene"


# ====================================================================================== models: full detail far away
def _model_rel(name: str) -> str:
    n = str(name).rstrip("\0").replace("\\", "/")
    return n if n.lower().startswith("nfos/") else "nfos/" + n


class ModelDetailOps:
    def model_lods(self, model_name: str) -> list:
        """[(distance, triangles)] of every level of detail of a model (.nfo), object by object (the main one first)."""
        from ..nfo import Nfo
        p = self.fs.find(_model_rel(model_name))
        if not p:
            raise ValueError(f"{model_name} not found in nfos/")
        n = Nfo.parse(open(p, "rb").read())
        out = []
        for o in n.objects:
            out.append([(float(l.distance), int(sum(m.header[6] for m in l.meshes))) for l in o.lods])
        return out

    def full_detail_model(self, rec, all_of_them: bool = True) -> str:
        """A copy of the module's model (<name>_hd.NFO, next to it; the original is not touched) whose far, simplified
        versions never come in (their switch distance is pushed to 100 km): the game draws the detailed one at any
        distance.  The module - and with ``all_of_them`` every module with the same model - uses the copy."""
        from ..nfo import Nfo
        p0 = rec.parsed
        name = str(getattr(p0, "model_name", "") or "").rstrip("\0")
        if not name:
            raise ValueError("this module has no model")
        src = self.fs.find(_model_rel(name))
        if not src:
            raise ValueError(f"{name} not found in nfos/")
        n = Nfo.parse(open(src, "rb").read())
        changed = 0
        for o in n.objects:
            for l in o.lods[1:]:
                info = l.chunk.first("INFO")
                if info is None or len(info.data) < 4:
                    continue
                info.data = struct.pack("<f", 1.0e7) + info.data[4:]
                changed += 1
        if not changed:
            lods = self.model_lods(name)
            return (f"{os.path.basename(name)} has a single version ({lods[0][0][1] if lods and lods[0] else 0} triangles): "
                    "it does not change with the distance. What changes is something else (a mesh of the map with far "
                    "versions: use 'Full detail at any distance' of the map)")
        base, ext = os.path.splitext(os.path.basename(src))
        if base.lower().endswith("_hd"):
            return f"{os.path.basename(src)} is already the full-detail copy"
        dst = os.path.join(os.path.dirname(src), base + "_hd" + (ext or ".NFO"))
        data = n.to_bytes()
        if os.path.exists(dst) and open(dst, "rb").read() != data:
            raise ValueError(f"{os.path.basename(dst)} already exists and is different - it is never replaced")
        if not os.path.exists(dst):
            with open(dst, "wb") as f:
                f.write(data)
        Nfo.parse(open(dst, "rb").read())                  # reads back
        self.fs.rescan()
        self.fs._nfo.clear()
        rel_dir = name.replace("\\", "/")
        rel_dir = rel_dir[: len(rel_dir) - len(os.path.basename(rel_dir))]
        new_name = (rel_dir + os.path.basename(dst)).replace("/", "\\") if "\\" in name else rel_dir + os.path.basename(dst)
        self.push_undo(False, "full detail model")
        n_mod = 0
        for r in self.scene.modules:
            q = r.parsed
            if q is None or not hasattr(q, "model_name"):
                continue
            if (r is rec) or (all_of_them and str(q.model_name).rstrip("\0").lower() == name.lower()):
                if self.is_locked(r) and r is not rec:
                    continue
                q.model_name = new_name
                n_mod += 1
        self.dirty_scene = self.needs_rebake = True
        lods = self.model_lods(name)[0]
        far = ", ".join(f"{t} triangles from {d / 100:.0f} m" for d, t in lods[1:])
        return (f"{os.path.basename(dst)}: always the detailed version ({lods[0][1]} triangles; it had {far}); "
                f"{n_mod} modules use it - save the scene (export takes the new model along)")


    def normal_detail_model(self, rec, all_of_them: bool = True) -> str:
        """Back from the full-detail copy (<name>_hd.NFO) to the game's model, with its simpler far versions: the module -
        and with ``all_of_them`` every module using the same copy - uses the original again (the copy stays in nfos/)."""
        p0 = rec.parsed
        name = str(getattr(p0, "model_name", "") or "").rstrip("\0")
        base, ext = os.path.splitext(os.path.basename(name.replace("\\", "/")))
        if not base.lower().endswith("_hd"):
            return f"{os.path.basename(name)} is the game's model already"
        orig = name[: len(name) - len(os.path.basename(name.replace("\\", "/")))] + base[:-3] + ext
        if not self.fs.find(_model_rel(orig)):
            raise ValueError(f"{os.path.basename(orig)} not found in nfos/")
        self.push_undo(False, "normal detail model")
        n_mod = 0
        for r in self.scene.modules:
            q = r.parsed
            if q is None or not hasattr(q, "model_name"):
                continue
            if (r is rec) or (all_of_them and str(q.model_name).rstrip("\0").lower() == name.lower()):
                if self.is_locked(r) and r is not rec:
                    continue
                q.model_name = orig
                n_mod += 1
        self.dirty_scene = self.needs_rebake = True
        return f"{os.path.basename(orig)}: the game's model again (simpler far away); {n_mod} modules - save the scene"


# ====================================================================================== shapes (like a drawing program)
class ShapeOps:
    NO_BOX = ("ramp", "stairs", "cone", "pyramid")          # climbed on: only floor / wall faces, a box would be a wall

    def shape_faces(self, kind: str, size=None, at=None, yaw: float = 0.0, sides: int = 16, steps: int = 8,
                    points=None, height: float = 200.0):
        """The faces of a shape (engine): a ready-made one at ``at``, or one drawn by ``points`` (polygon / rect / circle)."""
        from .. import shapes
        if kind in shapes.POINT_KINDS:
            return shapes.from_points(kind, points or [], height, sides)
        if at is None:
            raise ValueError("no place for the shape")
        return shapes.faces(kind, size or shapes.DEFAULT_SIZE[kind], at, yaw, sides, steps)

    def add_shape(self, kind: str, size=None, at=None, yaw: float = 0.0, texture: str = "tablones.tex", tile: float = 128.0,
                  collision: bool = True, sides: int = 16, steps: int = 8, points=None, height: float = 200.0) -> str:
        """A textured shape (box, cylinder, cone, ramp, stairs, pyramid, wall, disc, or drawn by points) added to the map as
        a mesh; with ``collision`` it is solid: collision boxes that follow it (not for the ones you climb: ramp, stairs,
        cone, pyramid) and floor / wall faces of the height map on every face but the bottom."""
        from .. import hmcopy, meshbox, regioncopy, shapes, solids
        from ..opt import translate_mesh
        from .state import Selection
        fs = self.shape_faces(kind, size, at, yaw, sides, steps, points, height)
        if not fs:
            raise ValueError("the shape has no faces")
        tex = (texture or "").strip()
        if not tex:
            raise ValueError("choose a texture (the fill)")
        if not tex.lower().endswith(".tex"):
            tex += ".tex"
        if self.fs.texture(tex) is None:
            raise ValueError(f"texture {tex} not found")
        self.push_undo(True, "add shape")
        me = solids.mesh_from_faces(self.opt, [(p, n) for p, n in fs], tex, float(tile))
        mi = cropmod.add_mesh(self.opt, me)
        nb = nf = 0
        if collision and not self.opt.old_format:
            tris = shapes.triangles(fs)
            if kind not in self.NO_BOX:
                for c, h, R in meshbox.fit(tris, thickness=8.0):
                    regioncopy.add_box(self.opt, c, h, R)
                    nb += 1
            try:
                hm = self.heightmap_edit()
            except ValueError:
                hm = None
            if hm is not None:
                new = []
                for p, n in fs:
                    if n[1] < -0.7:                      # the bottom: nobody stands under it
                        continue
                    try:
                        new.append(hmcopy.make_face(p, n))
                    except ValueError:
                        pass
                if new:
                    hmcopy.add_faces(hm, new)
                    nf = len(new)
        self.selection = Selection("mesh", self.opt.meshes[mi] if isinstance(mi, int) else me, f"mesh {mi}")
        self.multi = []
        self.dirty_map = self.needs_rebake = True
        self._walk_key = self._ff_key = None
        return (f"{kind}: {len(shapes.triangles(fs))} triangles, texture {tex}"
                + (f", {nb} collision boxes and {nf} floor / wall faces" if collision else ", no collision") + " - save the map")


class BspOps:
    """Counter-Strike 1.6 / Half-Life maps (.bsp) brought into the map, and emptying an area to make room for them."""

    @staticmethod
    def _wad_pool(wads) -> dict:
        from .. import wad
        pool = {}
        for w in wads or ():
            w = str(w).strip().strip('"')
            if w:
                try:
                    for k, v in wad.read_wad(w).items():
                        pool.setdefault(k, v)
                except (OSError, ValueError):
                    pass
        return pool

    def cs_map(self, path: str, wads=()):
        """The Counter-Strike / Half-Life map at ``path`` as a compiled map (bsp.BspMap): a .bsp as it is, a Hammer .rmf
        turned into one (its texture sizes come from the .wad files given).  Kept while the file does not change."""
        from ..bsp import BspMap
        key = (os.path.abspath(path), os.path.getmtime(path), tuple(wads or ()) if path.lower().endswith(".rmf") else ())
        got = getattr(self, "_cs_map_cache", None)
        if got is not None and got[0] == key:
            return got[1]
        if path.lower().endswith(".rmf"):
            from .. import rmf
            pool = self._wad_pool(wads)

            def sizes(n):
                m = pool.get(n.lower())
                return (m.width, m.height) if m is not None else (64, 64)
            b = rmf.to_bsp_like(rmf.RmfMap.load(path), sizes)
        else:
            b = BspMap.load(path)
        self._cs_map_cache = (key, b)
        return b

    def _lightmap_writer(self):
        """write(wanted name, rgb) -> a new .tex in texs/ (no mip levels: the pages hold many small pictures), under a
        name no other texture has (never over a texture of the game)."""
        import re
        from ..tex import Texture, DXT1
        from .state_build import MAX_TEX_STEM

        def write(wanted: str, rgb) -> str:
            stem = re.sub(r"[^A-Za-z0-9_\-]", "_", wanted)
            folder = os.path.join(self.fs.root, "texs")
            for k in range(1, 200):
                c = stem[:MAX_TEX_STEM] if k == 1 else stem[:MAX_TEX_STEM - 1 - len(str(k))] + f"_{k}"
                if self.fs.texture(c + ".tex") is None and not os.path.exists(os.path.join(folder, c + ".tex")):
                    os.makedirs(folder, exist_ok=True)
                    Texture.from_rgba(np.asarray(rgb, np.uint8), DXT1, mipmaps=False).save(os.path.join(folder, c + ".tex"))
                    self.fs.rescan()
                    getattr(self.fs, "_tex", {}).pop(c.lower(), None)
                    return c + ".tex"
            raise ValueError(f"no free texture name for {wanted}")
        return write

    def remove_bsp_light(self) -> str:
        """Take the light of a CS map off the meshes again (the map as before; "Add the light" puts it back)."""
        from .. import lightmap
        if self.opt is None or not lightmap.lit_meshes(self.opt):
            return "this map has no CS light"
        self.push_undo(True, "CS light off")
        n = lightmap.strip(self.opt)
        self.dirty_map = self.needs_rebake = True
        return f"the CS light taken off {n} meshes - save the map (the light textures stay in texs/, unused)"

    def bsp_missing_faces(self, path: str, plan=None):
        """The faces the .bsp this map was made from draws (as the importer draws them today) that no mesh or prop of
        the map draws, not even in part: walls / ceilings an older importer left out (behind shelves, against another
        brush - see "faces that look into the sky") or that were deleted; and of the faces drawn only in part, the
        pieces left out (bspimport.uncovered_parts).  (plan, [(points, normal, uv, CS texture)],
        {CS texture: the map's texture most of its drawn faces have})."""
        from .. import autohm, bspimport, lightmap
        if self.opt is None:
            raise ValueError("open a map first")
        if not str(path).lower().endswith(".bsp"):
            raise ValueError("a compiled CS map (.bsp) is needed")
        b = self.cs_map(path)
        pl = plan if plan is not None else lightmap.find_plan(b, self.opt)
        cv = bspimport.convert(b, pl, {}, None, lambda t: True, False)   # the faces only: no collision, no models
        cv0 = bspimport.convert(b, pl, {}, None, lambda t: True, False, lift=False, sides=True)  # decals where CS has them
        cs_of = {}                                                       # engine face middle -> CS texture
        for f in bspimport.drawn_faces(b):
            cs_of[tuple(np.round(pl.point(f.points).mean(0), 1))] = f.texture
        faces, faces0 = [], []
        for (_tex, fs), (_t0, fs0) in zip(cv.meshes.items(), cv0.meshes.items()):
            if len(fs) != len(fs0):                                      # (they must pair up face by face)
                raise ValueError("the faces of the map with and without the decals moved do not pair up")
            for f, g in zip(fs, fs0):
                P = np.asarray(f[0], np.float64)
                P0 = np.asarray(g[0], np.float64)
                faces.append((P, f[1], f[2], cs_of.get(tuple(np.round(P0.mean(0), 1)), "")))
                faces0.append((P0, g[1]))
        tris, ttex = [], []
        used = {p.mesh_index for p in self.opt.props}
        for kind, n in (("mesh", len(self.opt.meshes)), ("prop", len(self.opt.props))):
            for i in range(n):
                if kind == "mesh" and i in used:
                    continue
                try:
                    me, M = autohm._mesh_matrix(self.opt, kind, i)
                except Exception:
                    continue
                for sm in me.render_submeshes():
                    if sm.vertices is None or len(sm.indices) < 3:
                        continue
                    idx = np.asarray(sm.indices, np.int64)[: len(sm.indices) // 3 * 3].reshape(-1, 3)
                    idx = idx[(idx < len(sm.vertices)).all(1)]
                    pos = sm.vertices["pos"].astype(np.float64) @ M[:3, :3] + M[3, :3]
                    tris.append(pos[idx])
                    mat = me.materials[sm.material_index] if sm.material_index < len(me.materials) else None
                    ttex += [str(mat.diffuse) if mat is not None else ""] * len(idx)
        T = np.concatenate(tris) if tris else np.zeros((0, 3, 3))
        hits = {}
        miss = bspimport.uncovered_faces(faces, T, hits=hits)
        if miss:                                     # a decal still where CS has it (a map made before) is drawn
            m0 = set(bspimport.uncovered_faces([faces0[i] for i in miss], T))
            miss = [i for k, i in enumerate(miss) if k in m0]
        votes = {}
        for i, k in hits.items():
            if ttex[k]:
                v = votes.setdefault(faces[i][3], {})
                v[ttex[k]] = v.get(ttex[k], 0) + 1
        learned = {cs: max(v, key=v.get) for cs, v in votes.items()}
        # faces drawn only in part (an older import cut a piece out): their missing pieces (not a decal moved since)
        which = [i for i in sorted(hits) if np.shape(faces[i][0]) == np.shape(faces0[i][0])
                 and np.allclose(faces[i][0], faces0[i][0])]
        parts = bspimport.uncovered_parts(faces, T, which=which) if len(T) else []
        return pl, [faces[i] for i in miss] + [(Q, faces[i][1], uv, faces[i][3]) for i, Q, uv in parts], learned

    def split_big_meshes(self, most: int = MESH_MAX_VERTICES) -> str:
        """Meshes with more than ``most`` vertices cut into pieces of the map (by halves of the longest side, the
        triangles as they are, the light too).  An older import made one mesh per texture: de_aztec's biggest had
        7,331 vertices and with the CS light (40 bytes a vertex) 7,837 - the game closed at the end of the loading
        (the shipped maps: at most 1,427; ours that work: up to ~5,800 lit)."""
        import copy
        if self.opt is None:
            raise ValueError("open a map first")
        used = {p.mesh_index for p in self.opt.props}
        big = []
        for i, me in enumerate(self.opt.meshes):
            if i in used or len(me.lods) != 1 or len(me.lods[0].parts) != 1 or len(me.lods[0].parts[0].submeshes) != 1:
                continue
            sm = me.lods[0].parts[0].submeshes[0]
            if sm.vertices is None or len(sm.vertices) <= most or sm.remap is not None:
                continue
            big.append(i)
        if not big:
            return f"no mesh has more than {most} vertices"
        self.push_undo(True, "split big meshes")
        pieces = []
        for i in big:
            me = self.opt.meshes[i]
            sm = me.lods[0].parts[0].submeshes[0]
            idx = np.asarray(sm.indices, np.int64)[: len(sm.indices) // 3 * 3].reshape(-1, 3)
            pos = sm.vertices["pos"].astype(np.float64)
            cen = pos[idx].mean(1)

            def cut(tris):
                if len(np.unique(idx[tris])) <= most or len(tris) < 2:
                    return [tris]
                c = cen[tris]
                ax = int(np.argmax(np.ptp(c, 0)))
                order = tris[np.argsort(c[:, ax], kind="stable")]
                h = len(order) // 2
                return cut(order[:h]) + cut(order[h:])
            for tris in cut(np.arange(len(idx))):
                if not len(tris):
                    continue
                keep, inv = np.unique(idx[tris].reshape(-1), return_inverse=True)
                new = copy.deepcopy(me)
                nsm = new.lods[0].parts[0].submeshes[0]
                nsm.vertices = sm.vertices[keep].copy()
                nsm.indices = inv.astype(np.uint16)
                p = nsm.vertices["pos"].astype(np.float64)
                lo, hi = p.min(0), p.max(0)
                corners = np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])],
                                   np.float32)
                new.lods[0].parts[0].corners = corners.astype("<f4").tobytes()
                new.corners = corners
                pieces.append(new)
        for new in pieces:
            cropmod.add_mesh(self.opt, new)
        cropmod.remove_meshes(self.opt, set(big), False)
        self.dirty_map = self.needs_rebake = True
        self._changed_geometry()
        top = max(len(m.lods[0].parts[0].submeshes[0].vertices) for m in pieces)
        return (f"{len(big)} meshes with more than {most} vertices cut into {len(pieces)} (the biggest now {top}); "
                f"{len(self.opt.meshes)} meshes - save the map")

    @staticmethod
    def _tex_stem(name: str) -> str:
        """A texture's name as the .bsp import writes it: no CS prefix ("{", "-0", "!"...), no "cs_", no ".tex"."""
        n = str(name).replace("\\", "/").split("/")[-1].lower()
        if n.endswith(".tex"):
            n = n[:-4]
        if n.startswith("cs_"):
            n = n[3:]
        return n.lstrip("+-~{!0123456789") or n

    def fix_bsp_overlays(self, path: str, plan=None) -> str:
        """A map made from a .bsp before: its decals (signs, trims, stains one unit in front of a wall) moved out to
        bspfix.OVERLAY_GAP from the wall - they blinked; the triangles of additive / invisible brush entities (a beam
        of sunlight: a dark see-through sheet with black edges) taken out.  Only the drawing changes."""
        from .. import autohm, bspfix, lightmap
        from ..crop import remove_meshes
        if self.opt is None:
            raise ValueError("open a map first")
        b = self.cs_map(path)
        pl = plan if plan is not None else lightmap.find_plan(b, self.opt)
        shifts = bspfix.overlay_shifts(b)
        hidden = bspfix.hidden_faces(b)
        thin = bspfix.thin_backs(b) + [i for i in bspfix.decal_sides(b) if i not in set(bspfix.thin_backs(b))]
        thin += [i for i in bspfix.buried_faces(b) if i not in set(thin)]   # faces pressed on another brush
        n_hid = len(hidden)
        hidden = hidden + [i for i in thin if i not in set(hidden)]
        used = {p.mesh_index for p in self.opt.props}
        jobs = []
        for i, me in enumerate(self.opt.meshes):
            if i in used:
                continue
            try:
                _me, M = autohm._mesh_matrix(self.opt, "mesh", i)
            except Exception:
                continue
            if not np.allclose(M, np.eye(4), atol=1e-4):
                continue                                                  # only meshes laid in world coordinates
            for sm in me.render_submeshes():
                if sm.vertices is None or len(sm.indices) < 3 or sm.remap is not None:
                    continue
                idx = np.asarray(sm.indices, np.int64)[: len(sm.indices) // 3 * 3].reshape(-1, 3)
                mat = me.materials[sm.material_index] if sm.material_index < len(me.materials) else None
                jobs.append((i, sm, idx, str(mat.diffuse) if mat is not None else ""))
        if not jobs:
            return "no mesh of the .bsp in this map"
        tris = np.concatenate([sm.vertices["pos"].astype(np.float64)[idx] for _i, sm, idx, _t in jobs])
        tnrm = np.concatenate([sm.vertices["nrm"].astype(np.float64)[idx].mean(1) for _i, sm, idx, _t in jobs])
        ttex = np.concatenate([np.full(len(idx), self._tex_stem(t), object) for _i, _sm, idx, t in jobs])
        on_dec = bspfix.faces_under(b, pl, tris, sorted(shifts), normals=tnrm)
        # decals an older editor moved already, all to the same distance (one over another blinked): moved again
        old_sh = bspfix.overlay_shifts(b, layered=False)
        redo = {}                                     # triangle -> face, for the ones where they lie now
        for fi in sorted(shifts):
            d_old = old_sh.get(fi)
            if d_old is None or abs(d_old - shifts[fi]) < 0.05 or d_old < 0.05:
                continue
            f = b.faces[fi]
            n_ = np.asarray(f.normal, np.float64)
            n_ /= max(np.linalg.norm(n_), 1e-12)
            c_ = np.asarray(f.points, np.float64).mean(0)
            back = pl.point(c_) - pl.point(c_ + n_ * d_old)
            got = bspfix.faces_under(b, pl, tris + back, [fi], normals=tnrm)
            for t in np.nonzero((got >= 0) & (on_dec < 0))[0]:
                if ttex[t] == self._tex_stem(f.texture):
                    redo[int(t)] = fi
        on_hid = bspfix.faces_under(b, pl, tris, hidden, normals=tnrm)
        for arr in (on_dec, on_hid):                 # only the triangles drawn with that face's own texture (a car
            for t in np.nonzero(arr >= 0)[0]:        # beside an invisible bullet stop, a wall behind: not theirs)
                if ttex[t] != self._tex_stem(b.faces[int(arr[t])].texture):
                    arr[t] = -1
        some = np.nonzero((on_dec >= 0) | (on_hid >= 0))[0]
        if len(some):                     # on a face drawn anyway too (an invisible brush against a wall): it stays
            on_drawn = bspfix.faces_under(b, pl, tris[some], bspfix.drawn_others(b, list(shifts) + hidden),
                                          normals=tnrm[some])
            same = np.array([k >= 0 and ttex[s] == self._tex_stem(b.faces[int(k)].texture)
                             for s, k in zip(some, on_drawn)], bool) if len(some) else np.zeros(0, bool)
            on_dec[some[same]] = -1                  # (with its own texture: a bed under the water is not it)
            on_hid[some[same]] = -1
        again = np.zeros(len(tris), bool)
        for t, fi in redo.items():
            if on_hid[t] < 0:
                on_dec[t] = fi
                again[t] = True
        if not (on_dec >= 0).any() and not (on_hid >= 0).any():
            tw = self.remove_twin_triangles()
            if tw:
                return f"{tw} triangles of models drawn twice back to back taken out - save the map"
            return "nothing to fix: no decal on a wall, no beam of light, no thin slab drawn twice"
        thin_set = set(hidden[n_hid:])
        self.push_undo(True, "decals and beams of the .bsp")
        delta = {}
        for fi in set(int(f) for f in on_dec if f >= 0):
            f = b.faces[fi]
            n = np.asarray(f.normal, np.float64)
            n /= max(np.linalg.norm(n), 1e-12)
            c = np.asarray(f.points, np.float64).mean(0)
            delta[fi] = pl.point(c + n * shifts[fi]) - pl.point(c)
        re_delta = {}                                 # moved already by the old rule: the rest of the way
        for fi in set(redo.values()):
            if fi not in delta:
                continue
            n = np.asarray(b.faces[fi].normal, np.float64)
            n /= max(np.linalg.norm(n), 1e-12)
            c = np.asarray(b.faces[fi].points, np.float64).mean(0)
            re_delta[fi] = delta[fi] - (pl.point(c + n * old_sh[fi]) - pl.point(c))
        k = 0
        moved = gone = gone_thin = 0
        empty = set()
        for i, sm, idx, _t in jobs:
            n = len(idx)
            dec, hid, agn = on_dec[k:k + n], on_hid[k:k + n], again[k:k + n]
            k += n
            if not (dec >= 0).any() and not (hid >= 0).any():
                continue
            keep = hid < 0
            v = sm.vertices
            add = []
            new_idx = idx.copy()
            nv = len(v)
            for t in np.nonzero(keep & (dec >= 0))[0]:            # moved: corners of their own
                for c_ in range(3):
                    r = v[idx[t, c_]].copy()
                    dd = re_delta[int(dec[t])] if agn[t] else delta[int(dec[t])]
                    r["pos"] = (r["pos"].astype(np.float64) + dd).astype(r["pos"].dtype)
                    add.append(r)
                    new_idx[t, c_] = nv
                    nv += 1
                moved += 1
            gone += int(((~keep) & ~np.isin(hid, list(thin_set))).sum()) if thin_set else int((~keep).sum())
            gone_thin += int(((~keep) & np.isin(hid, list(thin_set))).sum()) if thin_set else 0
            if nv > 65535:
                raise ValueError("a mesh got too many vertices")
            if add:
                sm.vertices = np.concatenate([v, np.array(add, v.dtype)])
            new_idx = new_idx[keep]
            if not len(new_idx):
                empty.add(i)
            sm.indices = new_idx.reshape(-1).astype(np.uint16)
        drop = {i for i in empty if all(len(sm.indices) == 0 for sm in self.opt.meshes[i].render_submeshes())}
        if drop:
            remove_meshes(self.opt, drop, False)
        tw = self.remove_twin_triangles(undo=False)
        self.dirty_map = self.needs_rebake = True
        self._changed_geometry()
        return (f"{moved} triangles of decals moved {bspfix.OVERLAY_GAP:g} CS units off their walls, a decal over "
                f"another 2 units more (no blinking), "
                f"{gone} triangles of beams of light / invisible brushes taken out, "
                f"{gone_thin} triangles of the back of thin slabs (fences, straw, sheets - drawn from both sides by the "
                f"other face) and of faces pressed on another brush (a crate's bottom on the ground) taken out"
                + (f", {tw} triangles of models drawn twice back to back taken out" if tw else "") + (f" ({len(drop)} meshes left empty, deleted)" if drop else "") + " - save the map")

    def remove_twin_triangles(self, undo: bool = True) -> int:
        """Triangles of the map's own meshes lying on the same three corners as another of the same texture (CS models'
        two-sided leaves and cards: two triangles back to back - Torrente draws each from both sides, the two fight):
        one of each pair stays (bspfix.twin_triangles).  How many went."""
        from .. import bspfix
        from ..crop import remove_meshes
        if self.opt is None:
            raise ValueError("open a map first")
        used = {p.mesh_index for p in self.opt.props}
        plan = []
        for i, me in enumerate(self.opt.meshes):
            if i in used:
                continue
            for sm in me.render_submeshes():
                if sm.vertices is None or len(sm.indices) < 6 or sm.remap is not None:
                    continue
                idx = np.asarray(sm.indices, np.int64)[: len(sm.indices) // 3 * 3].reshape(-1, 3)
                ok = (idx < len(sm.vertices)).all(1)
                tw = np.zeros(len(idx), bool)
                tw[ok] = bspfix.twin_triangles(sm.vertices["pos"].astype(np.float64)[idx[ok]])
                if tw.any():
                    plan.append((i, sm, idx, tw))
        if not plan:
            return 0
        if undo:
            self.push_undo(True, "triangles drawn twice")
        n = 0
        empty = set()
        for i, sm, idx, tw in plan:
            sm.indices = idx[~tw].reshape(-1).astype(np.asarray(sm.indices).dtype)
            n += int(tw.sum())
            if not len(sm.indices):
                empty.add(i)
        drop = {i for i in empty if all(len(sm.indices) == 0 for sm in self.opt.meshes[i].render_submeshes())}
        if drop:
            remove_meshes(self.opt, drop, False)
        self.dirty_map = self.needs_rebake = True
        self._changed_geometry()
        return n

    def rebuild_bsp_floor(self, path: str, plan=None, water: str = "floor") -> str:
        """A map made from a .bsp before: its floor collision (.hm) made again from the .bsp with today's rules - the
        steps of stairs as one even slope (bspimport.step_ramps: de_inferno_go's banana and de_cbble's stairs stopped
        the player at every step).  The whole .hm is replaced (one undo step); the collision boxes stay as they are.
        Run "Bars, grilles, railings" again afterwards if the map had them."""
        from .. import bspimport, hmcopy, lightmap
        if self.opt is None:
            raise ValueError("open a map first")
        b = self.cs_map(path)
        pl = plan if plan is not None else lightmap.find_plan(b, self.opt)
        hm = self.heightmap_edit()
        before = len(hmcopy.unique_faces(hm))
        cv = bspimport.convert(b, pl, {}, None, lambda t: True, True, water=water, props=None, grilles=False)
        new = []
        for p_, n_ in cv.hm_faces:
            try:
                new.append(hmcopy.make_face(p_, n_))
            except ValueError:
                pass
        if not new:
            raise ValueError("the .bsp gave no floor (is it the map this one was made from?)")
        self.push_undo(True, "floor collision from the .bsp")
        lo = [min(hmcopy.face_bounds(f)[0] for f in new) - 1, min(hmcopy.face_bounds(f)[1] for f in new) - 1]
        hi = [max(hmcopy.face_bounds(f)[2] for f in new) + 1, max(hmcopy.face_bounds(f)[3] for f in new) + 1]
        hm.root = hmcopy.build_tree(new, (lo[0], lo[1], hi[0], hi[1]), max(hmcopy.tree_depth(hm.root), 1))
        gone, added = self._swap_wall_boxes(cv.stale_boxes, cv.fresh_boxes)
        self.dirty_map = True
        self._walk_key = self._ff_key = None
        self._changed_geometry()
        return (f"floor collision made again from {os.path.basename(path)}: {len(new)} faces (before {before}), "
                f"{cv.step_ramps} steps as ramps - stairs one even slope, {cv.slits} slits in floors and slopes closed, "
                f"{cv.lips} ramps on low edges, {cv.buried} floors cut under others, {cv.pierced} walls cut down to "
                f"the floor, {cv.lintels} crouch lintels removed, collision boxes {gone} out / {added} in - save the map")

    def _swap_wall_boxes(self, stale, fresh, tol: float = 1.5):
        """The collision boxes of the map equal (centre and size, ``tol`` cm) to one of ``stale`` go, ``fresh`` come in
        their place - only when some went (a map whose boxes are not those of the .bsp import keeps its own).
        -> (removed, added)."""
        from .. import crop, regioncopy
        if not stale:
            return 0, 0
        blk = crop.read_block(self.opt)
        if not blk.boxes:
            return 0, 0
        cen = np.array([np.frombuffer(b, "<f4", 3, 48) for b in blk.boxes], np.float64)
        half = np.array([np.sort(np.frombuffer(b, "<f4", 3, 64)) for b in blk.boxes], np.float64)
        drop = np.zeros(len(blk.boxes), bool)
        for c, h, _R in stale:
            d = (np.abs(cen - np.asarray(c, np.float64)).max(1) < tol) & \
                (np.abs(half - np.sort(np.asarray(h, np.float64))).max(1) < tol)
            drop |= d
        if not drop.any():
            return 0, 0

        def test(c, hull=False):
            if hull:
                return np.zeros(len(c), bool)
            return drop

        crop._drop_collision(self.opt, blk, test)
        added = len(regioncopy.add_boxes(self.opt, fresh)) if fresh else 0
        return int(drop.sum()), added

    def open_bsp_grilles(self, path: str, plan=None, progress=None) -> str:
        """A map made from a .bsp before: the walls of its collision over bars, grilles and railings (the clip hull
        fills the gaps between them, so bullets stopped at an invisible slab) cut down to the bars and the structure
        round them (bspgrille): bullets fly through the gaps as in CS, players still cannot get through.  Only the
        collision changes (the .hm's wall faces and the boxes behind them)."""
        from .. import bsphull, bspimport, bspgrille, hmcopy, lightmap, regioncopy
        if self.opt is None:
            raise ValueError("open a map first")
        if self.opt.old_format:
            raise ValueError("this map has no collision boxes (old format)")
        b = self.cs_map(path)
        if not getattr(b, "raw", b""):
            raise ValueError("a compiled CS map (.bsp) is needed")
        pl = plan if plan is not None else lightmap.find_plan(b, self.opt)
        h = bsphull.Hull(b.raw)
        hull_no = bspimport.COLLISION_HULL if h.models[0]["head"][bspimport.COLLISION_HULL] >= 0 else 1
        half = bspimport.HULL_HALF[hull_no]
        grid = bspgrille.Grilles(b.raw, hull_no, bspgrille.bsp_sheets(b))
        ents = bspimport.model_entities(b)
        panels = bspimport.open_panels(b)
        models = [0] + [m for m, e in ents.items() if not bspimport._hidden(e) and m not in panels and
                        e.get("classname", "").lower() not in bspimport.NONSOLID_CLASSES + bspimport.WATER_CLASSES]
        found = []                                                     # (engine wall, engine normal, [(piece, bar)])
        for j, m in enumerate(models):
            if progress:
                progress(j, len(models))
            e = ents.get(m) if m else None
            off = np.zeros(3)
            if e and "origin" in e:
                try:
                    off = np.array([float(v) for v in e["origin"].split()])
                except ValueError:
                    pass
            try:
                surf = bsphull.walls(b.raw, m, hull_no, half)
            except Exception:
                continue
            for q, nn in surf:
                if abs(nn[2]) >= 0.7:
                    continue
                parts = grid.open(m, q, nn, half)
                if parts:
                    ne = pl.direction(nn)
                    found.append((pl.point(q + off), ne / max(np.linalg.norm(ne), 1e-12),
                                  [(pl.point(g + off), bar) for g, bar in parts]))
        self.last_grilles = [(Q, n, [g for g, _b in parts]) for Q, n, parts in found]
        if not found:
            return "no bars, grille or railing with gaps in the collision of this map"

        def frame(Q, n):
            u = np.cross([0.0, 1.0, 0.0], n)
            u = u / max(np.linalg.norm(u), 1e-12)
            v = np.cross(n, u)
            return u, v

        def on_wall(Q, n, pts, tol=1.0, margin=1.0) -> bool:      # points on the wall's plane, their middle inside
            pts = np.asarray(pts, np.float64).reshape(-1, 3)
            if np.abs((pts - Q[0]) @ n).max() > tol:
                return False
            u, v = frame(Q, n)
            c = pts.mean(0)
            S, T = (Q - Q[0]) @ u, (Q - Q[0]) @ v
            return bool(bspgrille._inside(S, T, np.array([(c - Q[0]) @ u]), np.array([(c - Q[0]) @ v]), -margin)[0])
        with self._batch("bars and grilles of the .bsp"):
            blk = cropmod.read_block(self.opt)
            gone_b = set()
            if blk.boxes:
                A = np.array([np.frombuffer(raw, "<f4", 19) for raw in blk.boxes], np.float64)
                R2, C, HB = A[:, 8:11], A[:, 12:15], np.abs(A[:, 16:19])
                for Q, n, _parts in found:
                    lo, hi = Q.min(0) - 30.0, Q.max(0) + 30.0
                    cand = np.nonzero((np.abs(R2 @ n) > 0.999) & np.all((C >= lo) & (C <= hi), 1)
                                      & (np.abs((C - Q[0]) @ n + HB[:, 2]) < 0.6))[0]
                    for i in cand:
                        if int(i) not in gone_b and on_wall(Q, n, (C[i] + n * HB[i, 2])[None], 1.0, 1.0):
                            gone_b.add(int(i))
            new_b = []
            for _Q, n, parts in found:
                for g, bar in parts:
                    new_b += bspimport._wall_boxes(g, n, 15.0, 0.0 if bar else bspimport.STEP_MAX)
            if gone_b:
                cropmod.remove_collision_indices(self.opt, sorted(gone_b))
            if new_b:
                regioncopy.add_boxes(self.opt, new_b)
            nf_old = nf_new = 0
            try:
                hm = self.heightmap_edit()
            except ValueError:
                hm = None
            if hm is not None:
                keep = []
                allf = hmcopy.unique_faces(hm)
                pts = [np.concatenate(f.contours).astype(np.float64) if f.contours else np.zeros((0, 3)) for f in allf]
                FN = np.array([np.asarray(f.normal, np.float64) for f in allf]) if allf else np.zeros((0, 3))
                FC = np.array([p.mean(0) if len(p) else np.full(3, 1e9) for p in pts]) if allf else np.zeros((0, 3))
                drop = set()
                for Q, n, _parts in found:
                    lo, hi = Q.min(0) - 2.0, Q.max(0) + 2.0
                    cand = np.nonzero((np.abs(FN @ n) > 0.999) & (np.abs(FN[:, 1]) < 0.7)
                                      & np.all((FC >= lo) & (FC <= hi), 1) & (np.abs((FC - Q[0]) @ n) < 1.0))[0]
                    for i in cand:
                        if int(i) not in drop and len(pts[i]) >= 3 and on_wall(Q, n, pts[i]):
                            drop.add(int(i))
                for i, f in enumerate(allf):
                    if i in drop:
                        nf_old += 1
                        continue
                    keep.append(f)
                for _Q, n, parts in found:
                    for g, _bar in parts:
                        try:
                            keep.append(hmcopy.make_face(g, n))
                            nf_new += 1
                        except ValueError:
                            pass
                bnd = list(hmcopy.box(hm.root))
                for f in keep[-nf_new:] if nf_new else []:
                    x0, z0, x1, z1 = hmcopy.face_bounds(f)
                    bnd = [min(bnd[0], x0 - 1), min(bnd[1], z0 - 1), max(bnd[2], x1 + 1), max(bnd[3], z1 + 1)]
                hm.root = hmcopy.build_tree(keep, tuple(bnd), max(hmcopy.tree_depth(hm.root), 1))
        self.dirty_map = True
        self._walk_key = self._ff_key = None
        self._changed_geometry()
        return (f"{len(found)} walls over bars / grilles / railings cut down to the bars (bullets fly through the gaps, "
                f"players still stop): {len(gone_b)} boxes -> {len(new_b)}, {nf_old} wall faces -> {nf_new} - save the map")

    def restore_bsp_faces(self, path: str, plan=None) -> str:
        """Draw again the faces of the .bsp missing from the map (``bsp_missing_faces``): new meshes with the map's own
        textures of them (written from the .bsp when the map has not got one), with the CS light when the map has it.
        Nothing else changes: the collision, the other meshes, the props."""
        from .. import bspimport, lightmap, solids, wad
        pl, miss, learned = self.bsp_missing_faces(path, plan)
        if not miss:
            return "no face of the .bsp is missing from the map"
        b = self.cs_map(path)
        texmap, pool = {}, None
        for _p, _n, _uv, cs in miss:
            if cs in texmap:
                continue
            stem = cs.lstrip("+-~{!0123456789") or cs                   # the texture the map draws it with elsewhere,
            got = learned.get(cs) if learned.get(cs) and self.fs.texture(learned[cs]) is not None else None
            if got is None:                                              # else the one made from the .bsp
                got = next((c for c in (stem + ".tex", "cs_" + stem + ".tex") if self.fs.texture(c) is not None), None)
            if got is None:
                if pool is None:
                    pool = dict(wad.bsp_embedded(b.raw)) if getattr(b, "raw", b"") else {}
                m = pool.get(cs.lower())
                if m is not None:
                    got = self._mip_to_tex(m, cs, bspimport.translucent_textures(b).get(cs))
            if got is None:
                got = bspimport.guess_texture(cs, lambda t: self.fs.texture(t) is not None)
                if not got.lower().endswith(".tex"):
                    got += ".tex"
            texmap[cs] = got
        by_tex = {}
        for p, n, uv, cs in miss:
            by_tex.setdefault(texmap[cs], []).append((p, n, uv))
        self.push_undo(True, "faces of the .bsp back")
        n0 = len(self.opt.meshes)
        for tex, faces in sorted(by_tex.items()):
            for part in mesh_tiles(faces):
                cropmod.add_mesh(self.opt, solids.mesh_from_faces(self.opt, part, tex))
        new = range(n0, len(self.opt.meshes))
        lit = ""
        if lightmap.lit_meshes(self.opt) and getattr(b, "raw", b""):
            try:
                ref = lightmap.reference(self.opt, b, pl)
                r = lightmap.apply(self.opt, b, pl, self._lightmap_writer(), self.map_stem(), meshes=new, ref=ref)
                lit = f", with the CS light ({r['matched']} of {r['triangles']} triangles)"
            except ValueError as e:
                lit = f", no CS light on them: {e}"
        self.dirty_map = self.needs_rebake = True
        self._changed_geometry()
        tx = ", ".join(f"{t} ({len(f)})" for t, f in sorted(by_tex.items(), key=lambda x: -len(x[1]))[:6])
        return (f"{len(miss)} faces of the .bsp drawn again in {len(new)} meshes{lit}: {tx}"
                + (" ..." if len(by_tex) > 6 else "") + " - the collision is the same; save the map")

    def bsp_light(self, path: str, meshes=None, plan=None, undo: bool = True) -> str:
        """The light of the Counter-Strike map (its lightmaps: sun, shadows, the colour of its lamps) on the meshes of
        this map that were made from it - CS draws every wall as texture x light; without it the walls whose textures
        are grey (de_dust2_cs2, de_mirage_cs2) look flat grey.  New textures <map>_lm0, _lm1 ... (second texture of
        each mesh, drawn x 2 by the game like its own "glow" textures).  Where the map was laid is found from its walls
        when ``plan`` is not given."""
        from .. import lightmap
        if self.opt is None:
            raise ValueError("open a map first")
        if not str(path).lower().endswith(".bsp"):
            raise ValueError("the light is in the compiled map (.bsp), not in a Hammer .rmf")
        b = self.cs_map(path)
        pl = plan if plan is not None else lightmap.find_plan(b, self.opt)
        if undo:
            self.push_undo(True, "light of the .bsp")
        r = lightmap.apply(self.opt, b, pl, self._lightmap_writer(), self.map_stem(), meshes=meshes)
        if not r["meshes"]:
            return "no mesh to light (made from another map, or already lit)"
        self.dirty_map = self.needs_rebake = True
        cut = ""
        if meshes is None:                      # the light adds vertices: a mesh over the game's size is cut
            msg = self.split_big_meshes()
            cut = "" if msg.startswith("no mesh") else "; " + msg
        return (f"light of {os.path.basename(path)} on {r['meshes']} meshes ({r['matched']} of {r['triangles']} "
                f"triangles on its faces; {r.get('objects', 0)} of models and your own meshes take the light of the "
                f"floor under them), {r['pages']} light textures {r['textures'][0]}..." + cut)

    def cs_wad_report(self, path: str, wads=(), dirs=()) -> dict:
        """What the map's textures need: {'listed': the .wad files the map names, 'found': {name: path} of those found
        next to the map / in ``dirs`` but not given, 'given': the .wad files given, 'textures': how many textures it
        draws with, 'inside': how many the .bsp carries, 'in_wads': how many the given .wad files have, 'missing': the
        names nobody has (drawn with a Torrente texture that looks alike)}."""
        from .. import bspimport, wad
        b = self.cs_map(path, wads)
        names = sorted({f.texture for f in bspimport.drawn_faces(b)})
        inside = set(wad.bsp_embedded(b.raw)) if b.raw else set()
        pool = self._wad_pool(wads)
        listed = wad.listed_wads(b.entities[0] if b.entities else {})
        given = {os.path.basename(str(w)).lower() for w in wads or ()}
        found = wad.find_wads([n for n in listed if n.lower() not in given], wad.search_dirs(path, dirs))
        low = [n.lower() for n in names]
        models, models_missing = [], []
        if str(path).lower().endswith(".bsp"):                   # its studio models (cars, palm trees ...)
            from .. import mdl
            want = sorted({str(e.get("model", "")) for e in b.entities if str(e.get("model", "")).lower().endswith(".mdl")
                           and not e.get("classname", "").lower().startswith(("info_player", "hostage"))})
            roots = mdl.map_roots(path, list(wads or ()) + list(dirs or ()))
            for m_ in want:
                (models if mdl.find_model(m_, roots) else models_missing).append(m_)
        return {"models": models, "models_missing": models_missing,
                "listed": listed, "found": found, "given": list(wads or ()), "textures": len(names), "names": names,
                "inside": sum(1 for n in low if n in inside), "in_wads": sum(1 for n in low if n in pool and n not in inside),
                "missing": [n for n in names if n.lower() not in inside and n.lower() not in pool]}

    def bsp_textures(self, path: str, wads=()) -> list:
        """[(CS texture, Torrente texture guessed, faces)] of the drawn faces of the .bsp / .rmf."""
        from .. import bspimport
        b = self.cs_map(path, wads)
        count: Dict[str, int] = {}
        for f in bspimport.drawn_faces(b):
            count[f.texture] = count.get(f.texture, 0) + 1
        ok = lambda t: self.fs.texture(t) is not None
        return [(n, bspimport.guess_texture(n, ok), c) for n, c in sorted(count.items(), key=lambda kv: -kv[1])]

    def bsp_footprint(self, path: str, at, yaw: float = 90.0, scale: float = 2.54, wads=()):
        """Engine (lo, hi) the .bsp / .rmf would cover laid at ``at``."""
        from .. import bspimport
        b = self.cs_map(path, wads)
        return bspimport.footprint(b, bspimport.plan(b, at, yaw, scale))

    def clear_area(self, lo, hi, floor_y: Optional[float] = None, modules: bool = True) -> str:
        """Empty the rectangle lo..hi (x, z; engine): the meshes, props, collision boxes and height map walls lying
        completely inside it (and, with ``modules``, the modules standing in it).  The floor stays: meshes and height map
        faces no higher than ``floor_y`` + 15 (the lowest floor found there when None), and everything only partly inside
        (the stands of a stadium ...).  Locked things stay."""
        from .. import hmcopy, regioncopy
        lo = np.asarray(lo, np.float64)
        hi = np.asarray(hi, np.float64)
        x0, x1 = sorted((lo[0], hi[0]))
        z0, z1 = sorted((lo[2], hi[2]))
        pad = 60.0

        def inside(a, b) -> bool:
            return a[0] >= x0 - pad and b[0] <= x1 + pad and a[2] >= z0 - pad and b[2] <= z1 + pad
        if floor_y is None:
            levels = [float(cropmod.mesh_bounds(m)[1][1]) for m in self.opt.meshes
                      if inside(*cropmod.mesh_bounds(m)) and np.ptp(np.stack(cropmod.mesh_bounds(m))[:, 1]) < 60]
            if not levels:
                try:
                    levels = list(self.walk_world().levels_at((x0 + x1) / 2, (z0 + z1) / 2))
                except Exception:
                    levels = []
            floor_y = min(levels) if levels else -1e9
        top = floor_y + 15.0
        from .state import Selection
        with self._batch("clear area"):
            used = {p.mesh_index for p in self.opt.props}
            drop_m = set()
            for i, m in enumerate(self.opt.meshes):
                if i in used:
                    continue
                a, b = cropmod.mesh_bounds(m)
                if inside(a, b) and b[1] > top and not self.is_locked(m, "mesh"):
                    drop_m.add(i)
            drop_p = set()
            for i, p in enumerate(self.opt.props):
                try:
                    a, b = self.engine_bounds(Selection("prop", p, ""))
                except Exception:
                    continue
                if inside(np.asarray(a), np.asarray(b)) and not self.is_locked(p, "prop"):
                    drop_p.add(i)
            if drop_p:
                cropmod.remove_props(self.opt, drop_p)
            if drop_m:
                cropmod.remove_meshes(self.opt, drop_m, False)
            nb = 0
            if not self.opt.old_format:
                blk = cropmod.read_block(self.opt)
                gone = []
                for i, raw in enumerate(blk.boxes):
                    a, b = regioncopy._box_bounds(raw)
                    if inside(a, b) and b[1] > top:
                        gone.append(i)
                if gone:
                    cropmod.remove_collision_indices(self.opt, gone)
                nb = len(gone)
            nf = 0
            try:
                hm = self.heightmap_edit()
            except ValueError:
                hm = None
            if hm is not None:
                keep, gone_f = [], 0
                for f in hmcopy.unique_faces(hm):
                    p = np.concatenate(f.contours).astype(np.float64)
                    if len(p) and inside(p.min(0), p.max(0)) and p[:, 1].max() > top:
                        gone_f += 1
                    else:
                        keep.append(f)
                if gone_f:
                    hm.root = hmcopy.build_tree(keep, hmcopy.box(hm.root), max(hmcopy.tree_depth(hm.root), 1))
                nf = gone_f
            nmod = 0
            if modules and self.scene is not None:
                for r in list(self.scene.modules):
                    if r.parsed is None or self.is_locked(r) or r.clean_name.lower() == "mp_camerastartposition":
                        continue
                    try:
                        x, y, z = (float(v) for v in self.position_of(Selection("module", r, "")))
                    except Exception:
                        continue
                    if x0 <= x <= x1 and z0 <= z <= z1:
                        self.scene.modules.remove(r)
                        nmod += 1
        self.selection, self.multi = None, []
        self.dirty_map = self.dirty_scene = self.needs_rebake = True
        self._walk_key = self._ff_key = None
        self._changed_geometry()
        return (f"area emptied: {len(drop_m)} meshes, {len(drop_p)} props, {nb} collision boxes, {nf} floor / wall faces"
                + (f", {nmod} modules" if modules else "") + " (the floor stays) - save the map")

    def _free_spawns(self, recs, step: float = 15.0, reach: float = 90.0) -> int:
        """Start points that touch a wall / box (a CS start can be a hand away from a step) moved the least that frees
        them, on the same floor."""
        world = self.walk_world()
        moved = 0
        for r in recs:
            x, y, z = (float(v) for v in r.parsed.position)
            fy = world.floor_at(x, z, y + 60.0)
            feet = fy if fy is not None else y
            if not world.blocked(x, z, feet, 25.0, 175.0, 45.0):
                continue
            done = False
            for d in np.arange(step, reach + 0.1, step):
                for k in range(16):
                    a = 2 * math.pi * k / 16
                    nx, nz = x + d * math.cos(a), z + d * math.sin(a)
                    f2 = world.floor_at(nx, nz, y + 60.0)
                    if f2 is None or abs(f2 - feet) > 5.0 or world.blocked(nx, nz, f2, 25.0, 175.0, 45.0):
                        continue
                    r.parsed.position = (nx, y, nz)
                    moved += 1
                    done = True
                    break
                if done:
                    break
        return moved

    def bsp_props(self, path: str, b, wads=(), texmap=None):
        """The studio models (.mdl) a CS map places, looked for in the mod folder over its maps folder (cstrike/models/..)
        and next to the .wad files; their textures written as new game textures into ``texmap`` (key: mdl:...).
        -> ([mdl.Prop], [model files not found])."""
        from .. import bspimport, mdl
        props, missing = mdl.map_props(b.entities, mdl.map_roots(path, wads))
        props = bspimport.drawn_props(props)
        if texmap is not None:
            done = {}
            for pr in props:
                for k in sorted({t for t, _q, _uv in pr.tris}):
                    key = bspimport.prop_texture_key(pr, k)
                    if key in texmap:
                        continue
                    tx = pr.model.textures[k]
                    sig = (tx.width, tx.height, hash(tx.pixels), hash(tx.palette), tx.flags & mdl.STUDIO_NF_MASKED)
                    if sig not in done:                          # the same picture in two models: written once
                        done[sig] = self._mip_to_tex(tx, os.path.splitext(tx.name)[0] or "mdl")
                    texmap[key] = done[sig]
        return props, missing

    def import_bsp(self, path: str, at, yaw: float = 90.0, scale: float = 2.54, texmap=None, repeat=None,
                   collision: bool = True, spawns: bool = True, team_mode: bool = True, mode: Optional[str] = None,
                   per_team: Optional[int] = None, water: str = "floor", wads=(), props: bool = True,
                   light: bool = True) -> str:
        """Lay a Counter-Strike 1.6 / Half-Life map (.bsp) in the map at ``at`` (the middle of its floor): one textured mesh
        per texture, collision boxes behind its faces (one around each crate), floor / wall faces of the height map, and
        (``spawns``) a start point for each of its player starts: counter-terrorists team 0, terrorists team 1 (with
        ``team_mode`` the scene becomes a team deathmatch)."""
        from .. import bspimport, gamemode, hmcopy, regioncopy, solids
        from .state import Selection
        b = self.cs_map(path, wads)
        pl = bspimport.plan(b, at, yaw, scale)
        ok = lambda t: self.fs.texture(t) is not None
        prop_list, prop_missing = [], []
        if props and str(path).lower().endswith(".bsp"):        # its studio models: cars, palm trees, awnings ...
            texmap = dict(texmap or {})
            prop_list, prop_missing = self.bsp_props(path, b, wads, texmap)
        cv = bspimport.convert(b, pl, texmap, repeat, ok, collision and not self.opt.old_format, per_team=per_team,
                               water=water, props=prop_list)
        if mode is None:
            mode = "DMT" if team_mode else ""
        self.last_bsp_targets = cv.targets
        self.last_bsp_water = []                                     # (lo, hi) of its water: no start point in there
        for m, e in bspimport.model_entities(b).items():
            if e.get("classname", "").lower() in bspimport.WATER_CLASSES and m < len(b.models):
                lo, hi = b.models[m]
                q = pl.point(np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])]))
                self.last_bsp_water.append((q.min(0), q.max(0)))
        missing = sorted({t for t in cv.meshes if not ok(t)})
        if missing:
            raise ValueError("textures not found: " + ", ".join(missing))
        tpl = next((r for r in self.scene.modules if r.clean_name.lower() == "mp_cstartpoint" and r.parsed is not None),
                   None) if self.scene is not None else None
        if tpl is None and self.scene is not None:
            try:
                tpl = self.templates().by_kind.get("mp_cstartpoint")
            except Exception:
                tpl = None
        nm = nb = nf = ns = 0
        lit = ""
        with self._batch("import .bsp"):
            first = None
            n0 = len(self.opt.meshes)
            for tex, faces in sorted(cv.meshes.items()):
                for part in mesh_tiles(faces):                   # small meshes, each in one part of the map
                    me = solids.mesh_from_faces(self.opt, part, tex)
                    cropmod.add_mesh(self.opt, me)
                    first = first or me
                    nm += 1
            if light and str(path).lower().endswith(".bsp") and getattr(b, "raw", b""):
                try:                                             # its sun and shadows (lightmaps), like in CS
                    lit = " | " + self.bsp_light(path, range(n0, len(self.opt.meshes)), pl, undo=False)
                except ValueError as e:
                    lit = f" | no light from the .bsp: {e}"
            if cv.boxes:
                nb = len(regioncopy.add_boxes(self.opt, cv.boxes))
            if cv.hm_faces:
                try:
                    hm = self.heightmap_edit()
                except ValueError:
                    hm = None
                if hm is not None:
                    new = []
                    for p, n in cv.hm_faces:
                        try:
                            new.append(hmcopy.make_face(p, n))
                        except ValueError:
                            pass
                    if new:
                        hmcopy.add_faces(hm, new)
                    nf = len(new)
            if spawns and self.scene is not None:
                import copy as _copy
                from ..binutil import VStr
                order, made = {}, []
                for pos, ang, team in cv.spawns:
                    if tpl is not None:
                        r = _copy.copy(tpl)
                        r.parsed = _copy.deepcopy(tpl.parsed)
                        r.object_name = VStr((gamemode._new_name(self.scene, "StartPoint") + "\0").encode("cp1252"))
                        r.parsed.position, r.parsed.angle, r.parsed.team = pos, float(ang), int(team)
                        self.scene.modules.append(r)
                    else:
                        r = gamemode.add_start_point(self.scene, pos, ang, team)
                    r.parsed.order = order.get(team, 0)
                    order[team] = order.get(team, 0) + 1
                    made.append(r)
                    ns += 1
                if made and collision:                            # on the floor just made, like the game's own
                    self._walk_key = self._ff_key = None
                    self._changed_geometry()
                    world = self.walk_world()                     # the floor players stand on (also on a ramp's edge)
                    for r in made:
                        x, y, z = (float(v) for v in r.parsed.position)
                        fy = world.floor_at(x, z, y + 100.0)
                        if fy is not None and y - fy < 400.0:
                            r.parsed.position = (x, fy + 20.0, z)
                    self._free_spawns(made)
                if mode and ns:
                    gamemode.set_mode(self.scene, mode)
        if first is not None:
            self.selection, self.multi = Selection("mesh", first, ""), []
        self.dirty_map = self.dirty_scene = self.needs_rebake = True
        self._walk_key = self._ff_key = None
        self._changed_geometry()
        teams = {}
        for _p, _a, t in cv.spawns:
            teams[t] = teams.get(t, 0) + 1
        extra = ""
        if mode == "DO" and cv.targets and self.scene is not None:
            sites = []
            for t in cv.targets[:2]:
                fl = self.floor_below(t["floor"][0], t["floor"][2], t["floor"][1] + 50.0)
                at = np.array([t["floor"][0], fl if fl is not None else t["floor"][1], t["floor"][2]])
                size = np.asarray(t["hi"]) - np.asarray(t["lo"])
                sites.append((at, float(np.clip(min(size[0], size[2]) / 2, 164.0, 500.0))))
            extra = " | " + self.add_bomb_sites(sites)
        names = {"DMT": "team deathmatch", "DO": "destroy the target", "DM": "deathmatch", "B": "capture the flag"}
        if cv.open_panels:
            extra += f" | {cv.open_panels} breakable panels (sheets, boards over holes and windows) left open"
        if cv.invisible:
            extra += f" | {cv.invisible} faces of invisible walls not drawn (they still block)"
        if cv.props or prop_missing:
            extra += (f" | {cv.props} models (.mdl) placed, {cv.prop_boxes} of them solid"
                      + (f"; not found: {', '.join(prop_missing[:6])}" + (" ..." if len(prop_missing) > 6 else "")
                         if prop_missing else ""))
        return (f"{os.path.basename(path)}: {nm} meshes ({len(cv.textures)} textures), {nb} collision boxes, "
                f"{nf} floor / wall faces"
                + (f", {ns} start points (team 0: {teams.get(0, 0)}, team 1: {teams.get(1, 0)})" if ns else "")
                + (f", mode: {names.get(mode, mode)}" if spawns and mode and ns else "") + extra + lit
                + " - save the map and the scene")


class NewMapOps:
    """A whole new map out of a .bsp: emptying a copy of a map of the game, new sectors, the .wad textures, two bomb sites."""

    def bsp_wad_textures(self, path: str, wads=()) -> Dict[str, str]:
        """The textures of the .bsp found in the .bsp itself or in the .wad files given, written as new game textures
        (never over one of the game's: a name in use gets a ``cs_`` prefix).  {CS texture: Torrente texture}."""
        from .. import bspimport, wad
        b = self.cs_map(path, wads)
        pool = dict(wad.bsp_embedded(b.raw)) if b.raw else {}
        for k, v in self._wad_pool(wads).items():
            pool.setdefault(k, v)
        names = sorted({f.texture for f in bspimport.drawn_faces(b)})
        see = bspimport.translucent_textures(b)               # water, glass: see-through like in the map
        out = {}
        for n in names:
            m = pool.get(n.lower())
            if m is None:
                continue
            out[n] = self._mip_to_tex(m, n, see.get(n))
        return out

    def new_map_from_cs(self, path: str, name: str, mode: str = "DMT", wads=(), per_team: int = 16,
                        water: str = "floor", template: str = "", players_dm: int = 0, light: bool = True) -> str:
        """A whole new map ``name`` made from a Counter-Strike / Half-Life map (.bsp or Hammer .rmf), saved at once: the
        sky, sun and settings of a scene of the game of that ``mode`` (DM, DMT, B, DO; the Madrid one by default), the
        CS map at full size with its own textures (from the .bsp itself or the .wad files given; the ones nobody has get a
        Torrente texture that looks alike) and the collision a player meets in CS, its start points (``per_team`` per
        team: counter-terrorists team 0, terrorists team 1; in DM ``players_dm`` (2 x per_team) spread over the floor),
        health packs by each base, the flags (B) or its bomb sites A and B and the bomb (DO), new sectors and the intro
        camera over it."""
        from .. import gamemode, hmcopy
        from ..binutil import VStr
        mode = mode.upper()
        if mode not in self.BLANK_TEMPLATES:
            raise ValueError("mode: DM, DMT, B or DO")
        if not os.path.isfile(path):
            raise ValueError(f"{path} not found")
        tpl_name = template or self.BLANK_TEMPLATES[mode]
        if tpl_name not in self.scene_names():
            pref = gamemode.MODES[mode][2]
            cands = [n for n in self.scene_names() if n.lower().startswith(pref)]
            if not cands:
                raise ValueError(f"no scene of the game for mode {mode} to start from")
            tpl_name = cands[0]
        self.cs_map(path, wads)                                  # read it before anything changes (a bad file stops here)
        self.load(tpl_name)
        self._new_map_light = bool(light)
        self._last_rename_written = []
        msgs = [self.rename_map(name)]
        try:
            return self._new_map_from_cs_rest(path, name, mode, wads, per_team, water, players_dm, msgs)
        except Exception:                                    # half made: the new map's files go, the template is back
            for f in getattr(self, "_last_rename_written", []):
                try:
                    if os.path.isfile(f):
                        os.remove(f)
                except OSError:
                    pass
            self._last_rename_written = []
            try:
                self.fs.rescan()
                self.load(tpl_name)
                self.dirty_scene = self.dirty_map = False
            except Exception:
                pass
            raise

    def _new_map_from_cs_rest(self, path, name, mode, wads, per_team, water, players_dm, msgs) -> str:
        from .. import gamemode, hmcopy
        from ..binutil import VStr
        msgs.append(self.empty_map())
        tex = self.bsp_wad_textures(path, wads)
        rep = self.cs_wad_report(path, wads)
        msgs.append(f"textures: {len(tex)} of {rep['textures']} from the map / .wad"
                    + (f", {len(rep['missing'])} drawn with Torrente textures" if rep["missing"] else ""))
        imp_mode = {"DM": "DM", "DMT": "DMT", "B": "DMT", "DO": "DO"}[mode]
        msgs.append(self.import_bsp(path, (0.0, 0.0, 0.0), 0.0, 2.54, tex, None, True, True, mode=imp_mode,
                                    per_team=int(per_team) or None, water=water, wads=wads,
                                    light=getattr(self, "_new_map_light", True)))
        hm = self.heightmap_edit()                               # a height map tree that fits the new map
        faces = hmcopy.unique_faces(hm)
        if not faces:
            raise ValueError("the map has no floor")
        fb = np.array([hmcopy.face_bounds(f) for f in faces])
        hm.root = hmcopy.build_tree(faces, (fb[:, 0].min() - 50, fb[:, 1].min() - 50, fb[:, 2].max() + 50, fb[:, 3].max() + 50))
        self._walk_key = self._ff_key = None
        self._changed_geometry()
        tpl = self.templates()
        sp = {0: [], 1: []}
        for r in self.scene.modules:
            if r.clean_name.lower() == "mp_cstartpoint":
                sp.setdefault(int(r.parsed.team), []).append(np.asarray(r.parsed.position, np.float64))
        if not sp[0] and not sp[1]:
            raise ValueError("the map has no player starts (info_player_start / info_player_deathmatch)")
        if mode == "DM":
            n = int(players_dm) or 2 * (int(per_team) or max(len(sp[0]), len(sp[1]), 8))
            msgs.append(self.spread_spawns(max(n, 2), avoid=self.last_bsp_water))
            sp = {0: [np.asarray(r.parsed.position, np.float64) for r in self.scene.modules
                      if r.clean_name.lower() == "mp_cstartpoint"], 1: []}
            gamemode.set_mode(self.scene, "DM")

        def on_floor(p):
            fy = self.floor_below(p[0], p[2], p[1] + 80.0)
            return np.array([p[0], (fy if fy is not None else p[1]) + 20.0, p[2]])
        def near_floor(a, b):
            """A point between a start ``a`` and ``b`` on the same floor as the start (half way if it can): not on a
            roof, inside a house or over a pit."""
            base = self.floor_below(a[0], a[2], a[1] + 80.0)
            for f in (0.5, 0.35, 0.65, 0.2, 0.8, 0.1):
                q = a + (b - a) * f
                fy = self.floor_below(q[0], q[2], q[1] + 80.0)
                if fy is not None and base is not None and abs(fy - base) < 60.0:
                    return np.array([q[0], fy + 20.0, q[2]])
            return on_floor(a)
        teams = [t for t in (0, 1) if sp.get(t)]
        for t in teams:                                         # health by each base: a medikit and two small ones
            c = np.mean(sp[t], 0)
            pts = sorted(sp[t], key=lambda q: -np.linalg.norm(q - c))
            for k, size in enumerate(("big", "small", "small")):
                gamemode.add_health(self.scene, tpl, near_floor(pts[k % len(pts)], c), size)
        if mode == "B" and len(teams) == 2:                       # a flag just behind each base
            for t in (0, 1):
                c, o = np.mean(sp[t], 0), np.mean(sp[1 - t], 0)
                near = min(sp[t], key=lambda q: float(np.dot(q - c, o - c)))
                gamemode.add_flag(self.scene, tpl, on_floor(near + (near - c) * 0.3) - [0.0, 20.0, 0.0], t)
            gamemode.set_mode(self.scene, "B")
        if mode == "DO":
            zones = [r for r in self.scene.modules if r.clean_name.lower() == "mp_bombzone"]
            if not zones and len(teams) == 2:                     # a CS map without bomb sites: one by the defenders
                c0, c1 = np.mean(sp[0], 0), np.mean(sp[1], 0)
                msgs.append(self.add_bomb_sites([(on_floor(c0 + (c1 - c0) * 0.25) - [0.0, 20.0, 0.0], 300.0)], dll=False))
            if not any(r.clean_name.lower() == "mp_bomba" for r in self.scene.modules) and sp.get(1):
                bomb = tpl.clone("mp_Bomba", self.scene, "bomba")      # by the attackers' (terrorists') start
                if bomb is not None:
                    bomb.object_name = VStr(b"bomba\0")
                    c1 = np.mean(sp[1], 0)
                    M = np.asarray(bomb.parsed.transform, np.float64).copy()
                    M[3, :3] = on_floor(c1 + [0.0, 0.0, 120.0]) - [0.0, 20.0, 0.0]
                    bomb.parsed.transform = M.astype(np.float32)
        lo, hi = fb[:, :2].min(0), fb[:, 2:].max(0)
        mid = np.array([(lo[0] + hi[0]) / 2, 0.0, (lo[1] + hi[1]) / 2])
        span = float(max(hi[0] - lo[0], hi[1] - lo[1]))
        eye = mid + [-0.45 * span, 0.55 * span, -0.45 * span]
        cam = next((r for r in self.scene.modules if r.clean_name.lower() == "mp_camerastartposition"), None)
        if cam is not None:
            import struct as _st
            cam.data = _st.pack("<6f", *eye, *mid) + cam.data[24:]
            if cam.parsed is not None:
                cam.parsed.position, cam.parsed.target = tuple(eye), tuple(mid)
        else:
            gamemode.add_camera(self.scene, eye, mid)
        msgs.append(self.fresh_sectors(SECTOR_LEAF))
        self.dirty_scene = True
        self.save_map()
        self.save_scene()
        return " | ".join(m for m in msgs if m)

    def _mip_to_tex(self, m, name: str, alpha=None) -> str:
        """A Half-Life texture (wad.Mip) written as a new game texture (power-of-two size, mipmaps); its file name."""
        from PIL import Image
        rgba = m.rgba()
        if alpha is not None:
            rgba = rgba.copy()
            rgba[..., 3] = np.minimum(rgba[..., 3], alpha)
        if (rgba[..., 3] == 0).any():                              # "{" textures: their see-through pixels are blue;
            rgba = _bleed_colours(rgba)                            # filtered or shrunk, the blue shows at the edges
        h, w_ = rgba.shape[:2]
        p2 = lambda v: max(4, min(512, 1 << int(round(math.log2(max(v, 1))))))
        W, H = p2(w_), p2(h)                                       # the game's cards want power-of-two sizes
        if (W, H) != (w_, h):
            rgba = np.asarray(Image.fromarray(rgba).resize((W, H), Image.LANCZOS))
        return self._new_texture_name(name.lstrip("+-~{!0123456789") or name, rgba, "cs")

    def wad_textures(self, names, wads) -> Dict[str, str]:
        """Any textures of the .wad files by name (e.g. one to draw a CS texture with when the map's own is not in
        them), written as new game textures.  {name as asked: Torrente texture}; names not found are left out."""
        from .. import wad
        pool = {}
        for w in wads or ():
            w = str(w).strip().strip('"')
            if w:
                for k, v in wad.read_wad(w).items():
                    pool.setdefault(k, v)
        out = {}
        for n in names:
            key = str(n).strip().lower()
            if key.endswith(".tex"):
                key = key[:-4]
            if key in pool:
                out[n] = self._mip_to_tex(pool[key], key)
        return out

    def empty_map(self, keep_lights: bool = True) -> str:
        """Everything out of the map: meshes, props, decals, collision boxes, the height map's faces, the point / spot lights
        (the sun and the ambient light stay with ``keep_lights``) and the scene's modules but the intro camera."""
        from .. import hmcopy
        from ..opt import LightType
        with self._batch("empty the map"):
            nm, npr = len(self.opt.meshes), len(self.opt.props)
            if npr:
                cropmod.remove_props(self.opt, set(range(npr)))
            if self.opt.meshes:
                cropmod.remove_meshes(self.opt, set(range(len(self.opt.meshes))), False)
            nd = len(self.opt.decals)
            self.opt.decals[:] = []
            nb = 0
            if not self.opt.old_format:
                blk = cropmod.read_block(self.opt)
                nb = len(blk.boxes)
                if nb or blk.polys:
                    cropmod.remove_collision_indices(self.opt, list(range(nb)), list(range(len(blk.polys))))
            try:
                hm = self.heightmap_edit()
            except ValueError:
                hm = None
            nf = 0
            if hm is not None:
                nf = len(hmcopy.unique_faces(hm))
                hm.root = hmcopy.build_tree([], hmcopy.box(hm.root), 1)
            nl = len(self.opt.lights)
            if keep_lights:
                self.opt.lights[:] = [l for l in self.opt.lights if l.type in (LightType.DIRECTIONAL, LightType.AMBIENT)]
            else:
                self.opt.lights[:] = []
            nl -= len(self.opt.lights)
            nmod = 0
            if self.scene is not None:
                keep = [r for r in self.scene.modules if r.clean_name.lower() == "mp_camerastartposition"][:1]
                nmod = len(self.scene.modules) - len(keep)
                self.scene.modules[:] = keep
        self.selection, self.multi = None, []
        self.dirty_map = self.dirty_scene = self.needs_rebake = True
        self._walk_key = self._ff_key = None
        self._changed_geometry()
        return (f"map emptied: {nm} meshes, {npr} props, {nd} decals, {nb} collision boxes, {nf} floor / wall faces, "
                f"{nl} lights, {nmod} modules")

    def fresh_sectors(self, leaf: float = 3000.0) -> str:
        """A new sector tree (what the game draws from where) over everything the map has now: a quadtree of leaves about
        ``leaf`` wide, every mesh / prop / collision box listed in each leaf it overlaps.  For a map made anew."""
        from .. import regioncopy
        from .state import Selection
        if self.opt is None or self.opt.old_format:
            raise ValueError("this map has no sectors (old format)")
        blk = cropmod.read_block(self.opt)
        used = {p.mesh_index for p in self.opt.props}
        nm = len(self.opt.meshes)
        items = []                                              # (kind, index, lo, hi)
        for i, me in enumerate(self.opt.meshes):
            if i not in used:
                lo, hi = cropmod.mesh_bounds(me)
                items.append(("objs", i, lo, hi))
        for j, pr in enumerate(self.opt.props):
            me = self.opt.meshes[pr.mesh_index]
            lo, hi = cropmod.mesh_bounds(me)
            M = np.linalg.inv(np.asarray(me.world_transform, np.float64)) @ np.asarray(pr.transform, np.float64)
            q = np.array([[x, y, z] for x in (lo[0], hi[0]) for y in (lo[1], hi[1]) for z in (lo[2], hi[2])]) @ M[:3, :3] + M[3, :3]
            items.append(("objs", nm + j, q.min(0), q.max(0)))
        for b in range(len(blk.boxes)):
            lo, hi = regioncopy._box_bounds(blk.boxes[b])
            items.append(("boxes", b, lo, hi))
        if not items:
            raise ValueError("the map is empty")
        lo = np.min([np.asarray(t[2], np.float64) for t in items], 0) - 100.0
        hi = np.max([np.asarray(t[3], np.float64) for t in items], 0) + 100.0
        if self.scene is not None:                              # the modules (intro camera too) inside the sector area
            for r in self.scene.modules:
                try:
                    q = np.asarray(self.position_of(Selection("module", r, "")), np.float64)
                except Exception:
                    continue
                if np.all(np.isfinite(q)) and np.all(np.abs(q) < 1e6):
                    lo, hi = np.minimum(lo, q - 100.0), np.maximum(hi, q + 100.0)
        head0 = blk.sectors[0].head if blk.sectors else regioncopy.make_box((0, 0, 0), (1, 1, 1),
                                                                            np.diag([1.0, 1.0, -1.0]))
        base = np.frombuffer(head0, "<f4", 19).copy()

        def head(a, b):
            h = base.copy()
            h[12:15] = (a + b) / 2
            h[16:19] = (b - a) / 2
            return h.astype("<f4").tobytes()
        size = float(max(hi[0] - lo[0], hi[2] - lo[2]))
        depth = max(1, min(6, int(math.ceil(math.log2(max(size / leaf, 1.0))))))
        out = []

        def make(a, b, d):
            s = cropmod.Sector(head(a, b), [], [], [], 0)
            out.append(s)
            if d == 0:
                for kind, idx, l2, h2 in items:
                    if np.all(np.asarray(l2) - 50.0 <= b) and np.all(np.asarray(h2) + 50.0 >= a):
                        getattr(s, kind).append(idx)
                return
            s.tail = 4
            xm, zm = (a[0] + b[0]) / 2, (a[2] + b[2]) / 2
            for qa, qb in (((a[0], a[1], zm), (xm, b[1], b[2])), ((xm, a[1], zm), (b[0], b[1], b[2])),
                           ((a[0], a[1], a[2]), (xm, b[1], zm)), ((xm, a[1], a[2]), (b[0], b[1], zm))):
                make(np.array(qa), np.array(qb), d - 1)
        make(lo, hi, depth)
        self.push_undo(True, "new sectors")
        blk.sectors = out
        cropmod.write_block(self.opt, blk)
        self.dirty_map = True
        return f"new sectors: {len(out)} ({sum(1 for s in out if s.tail == 0)} leaves of about {size / 2 ** depth / 100:.0f} m)"

    def scene_bomb_zones(self) -> list:
        """Names of the bomb zones (mp_BombZone modules) of the scene, "bombZone" first."""
        names = [str(r.object_name).rstrip("\0")
                 for r in (self.scene.modules if self.scene is not None else []) if r.clean_name.lower() == "mp_bombzone"]
        return sorted(dict.fromkeys(names), key=lambda n: (n.lower() != "bombzone", n.lower()))

    def bomb_zone_rules(self):
        """(other zones, all, hud, radar) the map's DLL copy counts, or None (stock DLL / none)."""
        from .. import dllpatch
        src = self.mode_dll_source()
        try:
            if not src or not os.path.isfile(src):
                return None
            d = open(src, "rb").read()
            z = dllpatch.bomb_zones(d)
            return (z[0], z[1], dllpatch.bomb_zones_hud(d), dllpatch.bomb_zones_radar(d)) if z and z[0] else None
        except (OSError, ValueError):
            return None

    def do_dll_outdated(self) -> list:
        """What this map's destroy-the-target copy, made by an older editor, still does wrong ([] = up to date)."""
        from .. import dllpatch
        src = self.mode_dll_source()
        out = []
        try:
            if src and os.path.isfile(src):
                d = open(src, "rb").read()
                if dllpatch.bomb_rules_outdated(d):
                    out.append("a bomb that blows up at 0:00 can still lose the round")
                if dllpatch.bomb_zones_hud(d) and not dllpatch.bomb_zones_icons_off(d):
                    out.append("its objective icons stay on the screen in the next map")
                if dllpatch.bomb_zones(d) and dllpatch.bomb_zones(d)[1] and not dllpatch.bomb_zones_no_replant(d):
                    out.append("a zone already blown up takes a second bomb")
                if dllpatch.bomb_zones_late_end(d):
                    out.append("the game can close by itself a few seconds after leaving the map (rain / icons taken "
                               "off too late)")
        except (OSError, ValueError):
            pass
        return out

    def update_do_dll(self) -> str:
        """Make this map's destroy-the-target copy again with the current editor, keeping everything it does."""
        from ..binutil import VStr
        src = self.mode_dll_source()
        if not src or not os.path.isfile(src):
            raise ValueError("the mode DLL was not found: pick it in the game folder")
        old = self.do_dll_outdated()
        self.push_undo(False, "update DO DLL")
        name, dst, base = self._build_do_dll(src)
        self.scene.main_module_name = VStr((name + "\0").encode("cp1252"))
        self.custom_dlls = dict(getattr(self, "custom_dlls", {}), **{name.lower(): dst})
        self.dirty_scene = True
        return (f"{name} made again ({'; '.join(old) or 'nothing was wrong'} - fixed). Copy it into the game folder "
                f"(next to {base}.dll) on the server and on every player's PC")

    def bomb_rain_settings(self) -> dict:
        """{'rain', 'storm' (thunder and lightning with it), 'splash': what this map's destroy-the-target copy does, 'can': is the map's mode DLL one that can
        have it (the destroy-the-target one)}."""
        from .. import dllpatch
        out = {"rain": False, "storm": False, "splash": False, "can": False}
        src = self.mode_dll_source()
        try:
            if src and os.path.isfile(src):
                d = open(src, "rb").read()
                out["rain"], out["storm"] = dllpatch.bomb_rain(d)
                out["splash"] = dllpatch.bomb_splash(d)
                out["can"] = dllpatch.can_have_bomb_rain(d)
        except (OSError, ValueError):
            pass
        return out

    def make_bomb_rain_dll(self, rain: bool = True, storm: bool = True, splash: bool = False, src: str = "") -> str:
        """Rain in the destroy-the-target mode on THIS map: the game's DO DLLs never make rain (only the deathmatch /
        flag DLLs do, and only for Marbella / the church), so the map's copy of the DO DLL gets Marbella's shower
        (AddShower at the scene's start, taken away at its end), with ``storm`` its thunder and lightning (Marbella's) or
        without them (calm rain), and
        with ``splash`` the drops splashing on the floor round the camera (Marbella's splashes, every frame).
        Its bomb zones (all / HUD / minimap) and its bomb time / overtime stay; the game's DLL is never modified."""
        from .. import dllpatch
        from ..binutil import VStr
        src = src or self.mode_dll_source()
        if not src or not os.path.isfile(src):
            raise ValueError("the mode DLL was not found: pick it in the game folder")
        if not dllpatch.can_have_bomb_rain(open(src, "rb").read()):
            raise ValueError(f"{os.path.basename(src)} is not the destroy-the-target DLL (mp_DestroyTheTarget.dll)")
        self.push_undo(False, "rain DLL")
        cur = open(src, "rb").read()
        name, dst, base = self._build_do_dll(src, weather=(bool(rain), bool(storm), bool(rain and splash),
                                                           dllpatch.shower_sounds(cur), dllpatch.shower_volumes(cur)))
        got = dllpatch.bomb_rain(open(dst, "rb").read())
        got_splash = dllpatch.bomb_splash(open(dst, "rb").read())
        self.scene.main_module_name = VStr((name + "\0").encode("cp1252"))
        self.custom_dlls = dict(getattr(self, "custom_dlls", {}), **{name.lower(): dst})
        self.dirty_scene = True
        what = ("rain" + (" with thunder and lightning (like Marbella)" if got[1] else " without storm (no thunder, no lightning)")
                + (" and splashes on the floor" if got_splash else "")) if got[0] else "no rain"
        return (f"{name}: {what} (its bomb zones and bomb time stay). Copy it into the game folder (next to {base}.dll) "
                f"on the server and on every player's PC - save the scene")

    # ---- the weather of any mode: rain, storm or calm rain, quieter storm sounds
    def _storm_sounds(self, thunder: int = 100, rain: int = 100) -> list:
        """The 7 sounds of Marbella's shower (its rain, six thunders) for THIS map: a quieter copy of the game's own
        (``wavs/<map>_<volume>_trueno.wav`` ... written to the export folder, they go with the map's zip and are
        installed next to the game's sounds - the game's own are never changed) or '' (the game's own, at 100 %)."""
        from .. import audio, dllpatch
        out = []
        stem = self.map_stem()
        folder = os.path.join(self.export_dir(), "wavs")
        for k, orig in enumerate(dllpatch.SHOWER_SOUNDS):
            vol = int(max(0, min(100, rain if k == 0 else thunder)))
            if vol >= 100:
                out.append("")
                continue
            src = self.wav_path(orig)
            if not src:
                raise ValueError(f"the game's {orig} was not found (the game's wavs folder): its volume cannot be changed")
            base = os.path.basename(orig)
            room = 58 - len("wavs/") - len(base) - len(str(vol)) - 2
            name = f"wavs/{stem[:max(4, room)]}_{vol}_{base}"
            os.makedirs(folder, exist_ok=True)
            dst = os.path.join(folder, os.path.basename(name))
            audio.scale_wav(src, dst, vol / 100.0)
            self.custom_wavs = dict(getattr(self, "custom_wavs", {}), **{name.lower(): dst})
            out.append(name)
        return out

    def weather_settings(self) -> dict:
        """What the map's mode DLL does: {'kind': 'DO' / 'other' / None (cannot rain), 'can', 'rain', 'storm' (thunder
        and lightning), 'splash' (DO only), 'thunder' / 'rain_vol' (%), 'dll'}."""
        from .. import dllpatch
        out = {"kind": None, "can": False, "rain": False, "storm": True, "splash": False, "thunder": 100,
               "rain_vol": 100, "dll": ""}
        src = self.mode_dll_source() if self.scene is not None else ""
        if not src or not os.path.isfile(src):
            return out
        out["dll"] = os.path.basename(src)
        d = open(src, "rb").read()
        try:
            if dllpatch.can_have_bomb_rain(d):
                out.update(kind="DO", can=True)
                rain, storm = dllpatch.bomb_rain(d)
                out.update(rain=bool(rain), storm=bool(storm) or not rain, splash=dllpatch.bomb_splash(d))
            elif dllpatch.can_have_weather(d):
                out.update(kind="other", can=True)
                m = (dllpatch.weather_rain_map(d) or "").lower()
                out["rain"] = m == "?" or m == f"nfos\\{self.map_stem()}.opt".lower()
                out["storm"] = not dllpatch.weather_calm(d)
            out["thunder"], out["rain_vol"] = dllpatch.shower_volumes(d)
        except (ValueError, struct.error):
            pass
        return out

    def make_weather_dll(self, rain: bool = True, storm: bool = True, splash: bool = False, thunder: int = 100,
                         rain_vol: int = 100) -> str:
        """Rain on THIS map, in any mode: Marbella's shower with its storm (``storm``: lightning flashes and thunder) or
        calm rain, its thunder / rain at ``thunder`` / ``rain_vol`` % (quieter copies of the game's sounds, for this map
        only).  Destroy the target: the map's DO copy makes the shower itself (bomb zones and bomb time stay; ``splash``:
        the drops splash round the player).  Deathmatch / team deathmatch / flags: a copy of the mode DLL that rains on
        this map (it rained only on Marbella / the church), its storm made calm / quieter by a small hook after its
        AddShower.  The weapon groups chosen for the map stay; the game's DLLs and sounds are never modified."""
        from .. import dllpatch
        from ..binutil import VStr
        src = self.mode_dll_source()
        if not src or not os.path.isfile(src):
            raise ValueError("the mode DLL was not found: pick it in the game folder")
        d = open(src, "rb").read()
        sounds = self._storm_sounds(thunder, rain_vol) if rain else [""] * len(dllpatch.SHOWER_SOUNDS)
        vols = (int(thunder), int(rain_vol)) if rain else (100, 100)
        self.push_undo(False, "weather DLL")
        if dllpatch.can_have_bomb_rain(d):
            name, dst, base = self._build_do_dll(src, weather=(bool(rain), bool(storm), bool(rain and splash), sounds, vols))
        elif dllpatch.can_have_weather(d):
            name, dst, base = self._build_mode_dll(src, weather=(bool(rain), bool(storm), sounds, vols))
        else:
            raise ValueError(f"{os.path.basename(src)} cannot make rain: only the destroy-the-target DLL and the DLLs that "
                             f"rain on Marbella / the church (mp_deathMatch, mp_deathMatchTeam, mp_CaptureTheFlag, "
                             f"mp_CaptureChucrch ...) can")
        self.scene.main_module_name = VStr((name + "\0").encode("cp1252"))
        self.custom_dlls = dict(getattr(self, "custom_dlls", {}), **{name.lower(): dst})
        self.dirty_scene = True
        self._wg_key = None
        if not rain:
            what = "no rain"
        else:
            what = "rain" + (" with thunder and lightning" if storm else " without storm (no thunder, no lightning)")
            if splash and dllpatch.can_have_bomb_rain(d):
                what += ", splashes on the floor"
            if thunder < 100 or rain_vol < 100:
                what += f"; thunder at {int(thunder)} %, rain at {int(rain_vol)} % (" + \
                        ", ".join(os.path.basename(n) for n in sounds if n) + " - they go with the map's zip)"
        return (f"{name}: {what}. Copy it into the game folder (next to {base}.dll) on the server and on every player's "
                f"PC - save the scene")

    def _weather_other(self, data: bytes):
        """(rain, storm, sounds, volumes) of a DM / DMT / CTF copy made here, or None (it does not rain on this map)."""
        from .. import dllpatch
        try:
            m = (dllpatch.weather_rain_map(data) or "").lower()
            if not (m == "?" or m == f"nfos\\{self.map_stem()}.opt".lower()):
                return None
            return True, not dllpatch.weather_calm(data), dllpatch.shower_sounds(data), dllpatch.shower_volumes(data)
        except (ValueError, struct.error):
            return None

    def _apply_weather_other(self, path: str, weather) -> None:
        """Rain on this map in the DM / DMT / CTF copy at ``path`` (made from the game's DLL)."""
        from .. import dllpatch
        rain, storm, sounds, vols = weather
        if not rain:
            dllpatch.patch_weather(path, path, False, None)
            return
        m = (dllpatch.weather_rain_map(open(path, "rb").read()) or "").lower()
        if m != f"nfos\\{self.map_stem()}.opt".lower() and m != "?":
            dllpatch.patch_map_name(path, path, f"nfos\\{self.map_stem()}.opt")
        dllpatch.patch_weather(path, path, not storm, sounds, vols)

    def _build_mode_dll(self, src: str, weather=None):
        """This map's copy of a DM / DMT / CTF mode DLL, made again from the game's own DLL, with its weapon groups and
        ``weather`` = (rain, storm, sounds, volumes).  -> (copy's file name, its path, the game DLL's base name)."""
        import re
        import shutil
        from .. import dllpatch
        cur = open(src, "rb").read()
        weapons = None
        try:
            allowed, choice, sets = dllpatch.weapon_groups(cur), dllpatch.weapon_choice(cur), dllpatch.weapon_sets(cur)
            forced = [sets[g] if sets[g] else choice[g] for g in range(5)]
            if not all(allowed) or any(forced):
                weapons = (allowed, forced)
        except Exception:
            weapons = None
        stem = self.map_stem()
        base = re.sub("_" + re.escape(stem) + "$", "", os.path.splitext(os.path.basename(src))[0], flags=re.I)
        stock = self.find_game_dll(base + ".dll")
        start = stock if stock and os.path.isfile(stock) else src
        if os.path.abspath(start) == os.path.abspath(src) and weather and not weather[0] and self._weather_other(cur):
            raise ValueError(f"the game's {base}.dll was not found: the rain cannot be taken out of this copy")
        name = f"{base}_{stem}.dll"
        out_dir = self.export_dir()
        os.makedirs(out_dir, exist_ok=True)
        dst = os.path.join(out_dir, name)
        if os.path.abspath(dst).lower() == os.path.abspath(start).lower():
            raise ValueError("the copy would be written over the game's DLL")
        tmp = dst + ".tmp"
        shutil.copyfile(start, tmp)
        try:
            if weapons and os.path.abspath(start) != os.path.abspath(src):
                dllpatch.patch_weapon_groups(start, tmp, weapons[0], weapons[1])
            if weather is not None:
                self._apply_weather_other(tmp, weather)
            os.replace(tmp, dst)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
        return name, dst, base

    _KEEP = object()

    def _build_do_dll(self, src: str, zones=_KEEP, rules=_KEEP, weather=_KEEP):
        """This map's copy of the destroy-the-target DLL, always made again from the game's own DLL (so a copy made by
        an older version of the editor, with code in another place, is no trouble), with ``zones`` = (names, all, hud,
        radar) or None, ``rules`` = (seconds, overtime) or None and ``weather`` = (rain, storm, splash) or None; _KEEP = as
        the current copy has them.  -> (copy's file name, its path, the game DLL's base name)."""
        import re
        import shutil
        from .. import dllpatch
        cur = open(src, "rb").read()
        if zones is self._KEEP:
            try:
                z = dllpatch.bomb_zones(cur)
                zones = (z[0], z[1], dllpatch.bomb_zones_hud(cur), dllpatch.bomb_zones_radar(cur)) if z and z[0] else None
            except Exception:
                zones = None
        if weather is self._KEEP:
            try:
                weather = tuple(dllpatch.bomb_rain(cur)) + (dllpatch.bomb_splash(cur), dllpatch.shower_sounds(cur),
                                                            dllpatch.shower_volumes(cur))
            except Exception:
                weather = None
        if rules is self._KEEP:
            try:
                rules = dllpatch.bomb_rules(cur)
            except Exception:
                rules = None
        weapons = None                                    # its weapon groups (Weapons ▸ for this map) stay too
        try:
            allowed, choice, sets = dllpatch.weapon_groups(cur), dllpatch.weapon_choice(cur), dllpatch.weapon_sets(cur)
            forced = [sets[g] if sets[g] else choice[g] for g in range(5)]
            if not all(allowed) or any(forced):
                weapons = (allowed, forced)
        except Exception:
            weapons = None
        stem = self.map_stem()
        base = re.sub("_" + re.escape(stem) + "$", "", os.path.splitext(os.path.basename(src))[0], flags=re.I)
        stock = self.find_game_dll(base + ".dll")
        start = stock if stock and os.path.isfile(stock) else src
        name = f"{base}_{stem}.dll"
        out_dir = self.export_dir()
        os.makedirs(out_dir, exist_ok=True)
        dst = os.path.join(out_dir, name)
        if os.path.abspath(dst).lower() == os.path.abspath(start).lower():
            raise ValueError("the copy would be written over the game's DLL")
        tmp = dst + ".tmp"
        shutil.copyfile(start, tmp)
        try:
            if weapons and os.path.abspath(start) != os.path.abspath(src):
                dllpatch.patch_weapon_groups(start, tmp, weapons[0], weapons[1])
            rain = bool(weather and weather[0])
            if (zones and zones[0]) or rain:
                zones = zones or ([], False, False, False)
                dllpatch.patch_bomb_zones(tmp, tmp, zones[0], zones[1], zones[2] if len(zones) > 2 else True,
                                          zones[3] if len(zones) > 3 else True, rain=rain,
                                          storm=bool(len(weather) < 2 or weather[1]),
                                          splash=bool(rain and len(weather) > 2 and weather[2]),
                                          sounds=weather[3] if rain and len(weather) > 3 else None,
                                          volumes=weather[4] if rain and len(weather) > 4 else (100, 100))
            if rules and not (abs(float(rules[0]) - 20.0) < 1e-3 and not rules[1]):
                dllpatch.patch_bomb_rules(tmp, tmp, float(rules[0]), bool(rules[1]))
            os.replace(tmp, dst)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
        return name, dst, base

    def make_two_bomb_zones_dll(self, second: str = "bombZone_B", src: str = "", all_sites: bool = False) -> str:
        """A copy of the destroy-the-target DLL for this map that also counts the bomb zone ``second``."""
        return self.make_bomb_zones_dll([second], all_sites, src)

    def make_bomb_zones_dll(self, names=None, all_sites: bool = False, src: str = "", hud: bool = True,
                            radar: bool = True) -> str:
        """A copy of the destroy-the-target DLL for this map that also counts the bomb zones ``names`` (default: the
        scene's other mp_BombZone modules).  ``all_sites`` False: blowing up any zone wins the round; True: all of them
        must be blown up before the time runs out.  ``hud``: an icon per zone on the screen, intact or destroyed.
        ``radar``: the minimap points at the zone nearest to the player that is still standing.  The
        bomb time of the map's copy stays; the game's DLL is never modified."""
        from .. import dllpatch
        from ..binutil import VStr
        src = src or self.mode_dll_source()
        if not src or not os.path.isfile(src):
            raise ValueError("the mode DLL was not found: pick it in the game folder")
        if not dllpatch.can_have_second_bomb_zone(open(src, "rb").read()):
            raise ValueError(f"{os.path.basename(src)} is not the destroy-the-target DLL (mp_DestroyTheTarget.dll)")
        if names is None:
            names = [n for n in self.scene_bomb_zones() if n.lower() != "bombzone"]
        names = list(names)
        if not names:
            raise ValueError("the scene has no other bomb zone than 'bombZone' (add one: bomb sites)")
        name, dst, base = self._build_do_dll(src, zones=(names, bool(all_sites), bool(hud), bool(radar)))
        self.push_undo(False, "bomb zones DLL")
        extra = ""
        if all_sites:                                     # the bomb is used up when planted: one to pick up per zone
            import copy as _copy
            bombs = [r for r in self.scene.modules if r.clean_name.lower() == "mp_bomba"]
            if bombs and bombs[0].parsed is not None:
                k = len(bombs)
                while k < 1 + len(names):
                    k += 1
                    r = _copy.copy(bombs[0])
                    r.parsed = _copy.deepcopy(bombs[0].parsed)
                    taken = {str(m.object_name).rstrip("\0").lower() for m in self.scene.modules}
                    nm = f"bomba_{k}"
                    while nm.lower() in taken:
                        nm += "x"
                    r.object_name = VStr((nm + "\0").encode("cp1252"))
                    self.scene.modules.insert(self.scene.modules.index(bombs[-1]) + 1, r)
                    bombs.append(r)
                    extra = f"; bombs to pick up: {len(bombs)} (one per zone, where the first one is)"
        self.scene.main_module_name = VStr((name + "\0").encode("cp1252"))
        self.custom_dlls = dict(getattr(self, "custom_dlls", {}), **{name.lower(): dst})
        self.dirty_scene = True
        zones = ", ".join(["bombZone"] + names)
        how = (f"the round is won only by blowing up ALL the zones ({zones}) before the time runs out" if all_sites
               else f"the round is won by blowing up any zone ({zones})")
        if hud:
            how += "; the zones are shown on the HUD"
        if radar:
            how += "; the minimap points at the nearest zone still standing"
        return (f"{name}: {how}{extra}. Copy it into the game folder (next to {base}.dll) on the server and on every "
                f"player's PC")

    def bomb_settings(self) -> dict:
        """{'bombs': object names of the scene's bombs to pick up (mp_Bomba), 'fuse': seconds from planting to the
        explosion with this map's mode DLL, 'overtime': does it wait for a ticking bomb at 0:00, 'can_overtime': can
        this map's mode DLL do both (the destroy-the-target one)}."""
        from .. import dllpatch
        bombs = [r for r in self.scene.modules if r.clean_name.lower() == "mp_bomba"] if self.scene is not None else []
        fuse, ot, can, old = dllpatch.BOMB_FUSE_MS / 1000.0, False, False, False
        src = self.mode_dll_source()
        if src:
            try:
                d = open(src, "rb").read()
                got = dllpatch.bomb_rules(d)
                if got:
                    fuse, ot = got
                can = dllpatch.can_have_bomb_rules(d)
                old = dllpatch.bomb_rules_outdated(d)
            except OSError:
                pass
        return {"bombs": [str(r.object_name).rstrip("\0") for r in bombs], "fuse": fuse, "overtime": ot, "can_overtime": can,
                "outdated": old}

    def make_bomb_dll(self, seconds: float = 20.0, overtime: bool = True, src: str = "") -> str:
        """Destroy the target on THIS map: a planted bomb explodes ``seconds`` after it is planted (the game: 20 s) and,
        with ``overtime``, the round does not end at 0:00 while a bomb ticks - the clock shows the bomb's seconds.
        Both are done by a copy of the mode DLL, ``<mode DLL>_<map>.dll`` (its second bomb zone and weapons stay): the
        bomb a player plants is made by the game's bomb weapon from the game's own mp_bomba.dll, so a copy of that one
        would never be used.  The game's DLLs are never modified."""
        from .. import dllpatch
        from ..binutil import VStr
        bombs = [r for r in self.scene.modules if r.clean_name.lower() == "mp_bomba"]
        src = src or self.mode_dll_source()
        if not src or not os.path.isfile(src):
            raise ValueError("the mode DLL was not found: pick it in the game folder")
        if not dllpatch.can_have_bomb_rules(open(src, "rb").read()):
            raise ValueError(f"{os.path.basename(src)} is not the destroy-the-target DLL (mp_DestroyTheTarget.dll)")
        self.push_undo(False, "bomb DLL")
        msgs = []
        for r in bombs:                                   # an earlier version's mp_Bomba@<map>.dll is of no use
            if str(r.module_name).rstrip("\0").lower() != "mp_bomba.dll":
                r.module_name = VStr(b"mp_Bomba.dll\0")
        name, dst, base = self._build_do_dll(src, rules=(float(seconds), bool(overtime)))
        got = dllpatch.bomb_rules(open(dst, "rb").read())
        fuse, ot = got if got else (20.0, False)
        self.scene.main_module_name = VStr((name + "\0").encode("cp1252"))
        self.custom_dlls = dict(getattr(self, "custom_dlls", {}), **{name.lower(): dst})
        self.dirty_scene = True
        msgs.append(f"{name}: a planted bomb explodes {fuse:g} s after it is planted; at 0:00 "
                    + ("the round waits for a ticking bomb (the clock shows its seconds)" if ot
                       else "the round ends even with a bomb ticking (as the game does)"))
        return " | ".join(msgs) + (". Copy it into the game folder (next to " + base + ".dll) on the server and on every "
                                   "player's PC - save the scene")

    def add_bomb_sites(self, sites, second: str = "bombZone_B", dll: bool = True, all_sites: bool = False,
                       hud: bool = True, radar: bool = True) -> str:
        """Destroy the target with the bomb sites ``sites`` ([(engine floor point, radius)], A first): a bomb zone at each
        ("bombZone", ``second``), the bomb to carry (mp_Bomba) when there is none, and with two sites the DLL copy that
        counts both.  The zones are the model and settings of a bomb zone of the game's scenes."""
        import copy as _copy
        import struct as _st
        from .. import gamemode
        from ..binutil import VStr
        if not sites:
            raise ValueError("no bomb sites")
        from .. import dllpatch as _dp
        if len(sites) > 1 + _dp.MAX_EXTRA_ZONES:
            raise ValueError(f"at most {1 + _dp.MAX_EXTRA_ZONES} bomb zones (with the DLL copy)")
        tpl = self.templates()
        src = None
        for sc_name in ("mp_do_ruinas.scn", "mp_do_laberinto.scn"):         # a plain bomb zone (bomba_do.NFO)
            try:
                sc = self.fs.scene(sc_name)
                from ..modules import parse_modules
                parse_modules(sc)
                src = next((r for r in sc.modules if r.clean_name.lower() == "mp_bombzone" and r.parsed is not None), None)
            except Exception:
                src = None
            if src is not None:
                break
        src = src or tpl.by_kind.get("mp_bombzone")
        if src is None:
            raise ValueError("no bomb zone in the game's scenes to copy")
        with self._batch("bomb sites"):
            for r in [r for r in self.scene.modules if r.clean_name.lower() == "mp_bombzone"]:
                self.scene.modules.remove(r)
            names = ["bombZone", second] + [second[:-1] + c if second.endswith("B") else f"{second}_{c}"
                                            for c in "CDE"]
            for k, (at, radius) in enumerate(sites):
                r = _copy.copy(src)
                r.parsed = _copy.deepcopy(src.parsed)
                r.object_name = VStr((names[k] + "\0").encode("cp1252"))
                at = np.asarray(at, np.float64)
                M = np.asarray(r.parsed.transform, np.float64).copy()
                M[3, :3] = at
                r.parsed.transform = M.astype(np.float32)
                t = bytearray(r.parsed.tail)
                n = _st.unpack_from("<I", t, 0)[0]
                if len(t) >= 4 + n + 68:                                 # the second matrix (where it lies) and the radius
                    _st.pack_into("<3f", t, 4 + n + 48, *at)
                    _st.pack_into("<f", t, 4 + n + 64, float(radius))
                r.parsed.tail = bytes(t)
                self.scene.modules.append(r)
        msg = f"{len(sites)} bomb zones: " + ", ".join(names[:len(sites)])
        if dll and len(sites) >= 2:
            try:
                msg += " | " + self.make_bomb_zones_dll(names[1:len(sites)], all_sites, hud=hud, radar=radar)
            except ValueError as e:
                msg += f" | the DLL that counts them was not made: {e}"
        if self.scene is not None:
            gamemode.set_mode(self.scene, "DO") if gamemode.mode_of(self.scene) != "DO" else None
        self.dirty_scene = True
        return msg


class MaterialFixOps:
    """Materials whose colour block (ambient / diffuse / specular) is all zero: the game draws them black."""

    def retexture_from_neighbours(self, texture: str = "black.tex") -> str:
        """Every face drawn with ``texture`` (e.g. Counter-Strike's "black" in gaps between crates, in de_aztec) gets the
        texture of the faces around it (the most common one along its edges; the nearest face when none touches it),
        mapped at that texture's own scale - in line with a neighbour in the same plane.  Only the drawing changes:
        the collision (stairs, boxes...) stays exactly as it is."""
        from .. import autohm, solids
        want = texture.lower()
        if not want.endswith(".tex"):
            want += ".tex"
        used = {p.mesh_index for p in self.opt.props}
        targets = [i for i, me in enumerate(self.opt.meshes)
                   if i not in used and me.materials and str(me.materials[0].diffuse).lower() == want]
        if not targets:
            raise ValueError(f"no mesh is drawn with {texture}")
        T, UV, TX = [], [], []                                   # the other triangles (meshes and props)
        for kind, n in (("mesh", len(self.opt.meshes)), ("prop", len(self.opt.props))):
            for i in range(n):
                if kind == "mesh" and (i in targets or i in used):
                    continue
                me, M = autohm._mesh_matrix(self.opt, kind, i)
                for sm in me.render_submeshes():
                    if sm.vertices is None or len(sm.indices) < 3:
                        continue
                    idx = np.asarray(sm.indices, np.int64)[: len(sm.indices) // 3 * 3].reshape(-1, 3)
                    idx = idx[(idx < len(sm.vertices)).all(1)]
                    mat = me.materials[sm.material_index] if sm.material_index < len(me.materials) else None
                    t = str(mat.diffuse) if mat is not None else ""
                    if not t or t.lower() == want:
                        continue
                    pos = sm.vertices["pos"].astype(np.float64) @ M[:3, :3] + M[3, :3]
                    T.append(pos[idx]); UV.append(sm.vertices["uv"].astype(np.float64)[idx]); TX += [t] * len(idx)
        if not T:
            raise ValueError("there is nothing else in the map to take a texture from")
        T, UV = np.concatenate(T), np.concatenate(UV)
        key = lambda v: (round(v[0] / 2.0), round(v[1] / 2.0), round(v[2] / 2.0))
        at = {}
        for k in range(len(T)):
            for v in T[k]:
                at.setdefault(key(v), set()).add(k)
        C = T.mean(1)
        N = np.cross(T[:, 1] - T[:, 0], T[:, 2] - T[:, 0])
        N /= np.maximum(np.linalg.norm(N, axis=1, keepdims=True), 1e-12)
        mine = []                                                # (triangle, its normal)
        for i in targets:
            me = self.opt.meshes[i]
            for sm in me.render_submeshes():
                idx = np.asarray(sm.indices, np.int64)[: len(sm.indices) // 3 * 3].reshape(-1, 3)
                idx = idx[(idx < len(sm.vertices)).all(1)]
                pos = sm.vertices["pos"].astype(np.float64)
                nrm = sm.vertices["nrm"].astype(np.float64)
                for a in idx:
                    mine.append((pos[a], nrm[a].mean(0)))
        pick = [None] * len(mine)                               # index of the triangle whose texture it takes
        for j, (q, _n) in enumerate(mine):
            votes = {}
            for v in q:
                for k in at.get(key(v), ()):
                    votes[k] = votes.get(k, 0) + 1
            if votes:
                best = max(votes.values())
                cands = [k for k, c in votes.items() if c == best]
                count = {}
                for k in cands:
                    count[TX[k]] = count.get(TX[k], 0) + 1
                tex = max(count, key=count.get)
                pick[j] = next(k for k in cands if TX[k] == tex)
        for j, (q, _n) in enumerate(mine):                      # nothing touches it: the nearest face
            if pick[j] is None:
                pick[j] = int(np.argmin(np.linalg.norm(C - q.mean(0), axis=1)))
        out = {}
        for (q, nv), k in zip(mine, pick):
            tex = TX[k]
            n = np.cross(q[1] - q[0], q[2] - q[0])
            ln = np.linalg.norm(n)
            if ln < 1e-9:
                continue
            n /= ln
            if np.dot(n, nv) < 0:
                n = -n
            src, suv = T[k], UV[k]
            if abs(float(np.dot(n, N[k]))) > 0.99 and abs(float(np.dot(q[0] - src[0], N[k]))) < 2.0:
                # the same plane: the neighbour's own mapping, so the texture carries on across the edge
                e1, e2 = src[1] - src[0], src[2] - src[0]
                G = np.array([[e1 @ e1, e1 @ e2], [e1 @ e2, e2 @ e2]])
                try:
                    Gi = np.linalg.inv(G)
                    uv = []
                    for p in q:
                        a, b = Gi @ np.array([(p - src[0]) @ e1, (p - src[0]) @ e2])
                        uv.append(suv[0] + a * (suv[1] - suv[0]) + b * (suv[2] - suv[0]))
                    out.setdefault(tex, []).append((q, n, np.array(uv)))
                    continue
                except np.linalg.LinAlgError:
                    pass
            d3 = [np.linalg.norm(src[b] - src[a]) for a, b in ((0, 1), (1, 2), (2, 0))]
            d2 = [np.linalg.norm(suv[b] - suv[a]) for a, b in ((0, 1), (1, 2), (2, 0))]
            scale = float(np.median([x / y for x, y in zip(d3, d2) if y > 1e-6])) if any(y > 1e-6 for y in d2) else 128.0
            up = np.array([0.0, 1.0, 0.0]) if abs(n[1]) < 0.9 else np.array([0.0, 0.0, 1.0])
            ua = np.cross(up, n)
            ua /= np.linalg.norm(ua)
            va = np.cross(n, ua)
            out.setdefault(tex, []).append((q, n, np.array([[p @ ua / scale, -(p @ va) / scale] for p in q])))
        self.push_undo(True, "retexture " + texture)
        cropmod.remove_meshes(self.opt, set(targets), False)    # the drawing only: no collision is touched
        made = 0
        for tex, faces in sorted(out.items()):
            for part in mesh_tiles(faces):
                cropmod.add_mesh(self.opt, solids.mesh_from_faces(self.opt, part, tex))
                made += 1
        self.dirty_map = self.needs_rebake = True
        self._changed_geometry()
        kinds = ", ".join(f"{t} ({len(f)})" for t, f in sorted(out.items(), key=lambda x: -len(x[1]))[:6])
        return (f"{len(mine)} faces of {texture} now drawn with the textures around them: {kinds}; {made} meshes. "
                f"The collision is the same - save the map")


    def water_layers(self, texture: str) -> int:
        """How many triangles of ``texture`` fix_water_layers would take away (0: nothing to do)."""
        return len(self._water_drop(texture)[1])

    def _water_drop(self, texture: str):
        want = texture.lower()
        if not want.endswith(".tex"):
            want += ".tex"
        used = {p.mesh_index for p in self.opt.props} if self.opt is not None else set()
        targets = [i for i, me in enumerate(self.opt.meshes or [])
                   if i not in used and me.materials and str(me.materials[0].diffuse).lower() == want] \
            if self.opt is not None else []
        tris = []                                                # (mesh, submesh, triangle index, points)
        for i in targets:
            for sm in self.opt.meshes[i].render_submeshes():
                if sm.vertices is None or len(sm.indices) < 3:
                    continue
                idx = np.asarray(sm.indices, np.int64)[: len(sm.indices) // 3 * 3].reshape(-1, 3)
                pos = sm.vertices["pos"].astype(np.float64)
                for k, a in enumerate(idx):
                    if (a < len(pos)).all():
                        tris.append((i, sm, k, pos[a]))
        if not tris:
            return targets, set()
        P = np.array([t[3] for t in tris])
        N = np.cross(P[:, 1] - P[:, 0], P[:, 2] - P[:, 0])
        ln = np.linalg.norm(N, axis=1)
        N = N / np.maximum(ln, 1e-12)[:, None]
        C = P.mean(1)
        drop = set()
        up = [j for j in range(len(P)) if N[j, 1] > 0.7]
        for j in range(len(P)):
            if ln[j] < 1e-9 or N[j, 1] < -0.7:                   # the underside of the surface (the material is
                drop.add(j)                                      # two-sided: the top is seen from below too)
        for j in up:                                             # a layer under another one (a pool's bottom)
            c = C[j]
            for k in up:
                if k == j or not (c[1] + 1.0 < C[k][1] < c[1] + 600.0):
                    continue
                a, b, d = P[k][0][[0, 2]], P[k][1][[0, 2]], P[k][2][[0, 2]]
                q = c[[0, 2]]
                v0, v1, v2 = d - a, b - a, q - a
                den = v0[0] * v1[1] - v1[0] * v0[1]
                if abs(den) < 1e-9:
                    continue
                u = (v2[0] * v1[1] - v1[0] * v2[1]) / den
                w = (v0[0] * v2[1] - v2[0] * v0[1]) / den
                if u >= -1e-6 and w >= -1e-6 and u + w <= 1 + 1e-6:
                    drop.add(j)
                    break
        tops = [k for k in up if k not in drop]                  # a side under the surface (on the pool's wall,
        for j in range(len(P)):                                  # between two water brushes): under the water
            if j in drop or abs(N[j, 1]) > 0.7 or ln[j] < 1e-9:
                continue
            top_y = P[j][:, 1].max()
            c = C[j]
            for k in tops:
                lo, hi = P[k].min(0), P[k].max(0)
                if hi[1] >= top_y - 1.0 and lo[0] - 2 <= c[0] <= hi[0] + 2 and lo[2] - 2 <= c[2] <= hi[2] + 2 \
                        and hi[1] - top_y < 600.0:
                    drop.add(j)
                    break
        seen = {}                                                # sides drawn twice (both ways): one is enough
        for j in range(len(P)):
            if j in drop or abs(N[j, 1]) > 0.7:
                continue
            key = tuple(sorted(tuple(np.round(v, 1)) for v in P[j]))
            if key in seen:
                drop.add(j)
            else:
                seen[key] = j
        return targets, {(tris[j][0], id(tris[j][1]), tris[j][2]) for j in drop}

    def fix_water_layers(self, texture: str) -> str:
        """Water that flickers in the game (de_aztec): a water volume of a CS map came with every face - its top seen
        from above and from below, its bottom lying on the pool's floor (the same plane as the floor), its sides both
        ways.  Keeps only the top and one of each side (the material is made two-sided, so they are seen from both
        sides); only the drawing changes."""
        targets, drop = self._water_drop(texture)
        if not targets:
            raise ValueError(f"no mesh is drawn with {texture}")
        if not drop:
            return f"{texture}: nothing drawn twice - no change"
        self.push_undo(True, "water layers " + texture)
        gone = []
        for i in targets:
            me = self.opt.meshes[i]
            left = 0
            for sm in me.render_submeshes():
                if sm.vertices is None or len(sm.indices) < 3:
                    continue
                idx = np.asarray(sm.indices)[: len(sm.indices) // 3 * 3].reshape(-1, 3)
                keep = [k for k in range(len(idx)) if (i, id(sm), k) not in drop]
                sm.indices = idx[keep].reshape(-1).astype(np.asarray(sm.indices).dtype)
                left += len(keep)
            for mat in me.materials:
                mat.two_sided = True
            if not left:
                gone.append(i)
        if gone:
            cropmod.remove_meshes(self.opt, set(gone), False)
        self.dirty_map = self.needs_rebake = True
        self._changed_geometry()
        return (f"{texture}: {len(drop)} triangles taken away (the underside of the surface, the bottom lying on the "
                f"floor, the sides under the water) - only the top is drawn now, the collision is the same; save the map")

    def black_materials(self) -> list:
        """[(mesh index, material index)] of the materials with an all-zero colour block."""
        if self.opt is None:
            return []
        return [(i, k) for i, me in enumerate(self.opt.meshes) for k, m in enumerate(me.materials)
                if not any(bytes(m.uv_map)[:48])]

    def fix_black_materials(self) -> str:
        """Give those materials the colour block of the game's own materials (ambient 1, diffuse 0.68, specular 1)."""
        from ..opt import STOCK_MATERIAL
        bad = self.black_materials()
        if not bad:
            return "no black materials"
        self.push_undo(True, "fix black materials")
        for i, k in bad:
            self.opt.meshes[i].materials[k].uv_map = STOCK_MATERIAL
        self.dirty_map = self.needs_rebake = True
        return f"{len(bad)} materials of {len({i for i, _k in bad})} meshes get the game's colour block - save the map"


class SpreadOps:
    """Start points spread over the whole map (deathmatch: anywhere, always on the floor)."""

    def spread_points(self, n: int, seeds, avoid=(), cell: float = 60.0, taken=()) -> np.ndarray:
        """``n`` floor points (engine, on the floor) as far apart as possible - and from ``taken`` - over every floor a
        player can walk to from ``seeds``, free of walls / boxes / objects and never inside ``avoid`` ((lo, hi) boxes)."""
        from .. import navgrid
        pts = [np.asarray(s, np.float64) for s in seeds]
        if not pts:
            raise ValueError("no start point to begin from: put one on the floor first")
        world = self.walk_world()
        grid = navgrid.build(world, pts, cell=cell)
        if not grid.nodes:
            raise ValueError("no floor to walk on around the start points")
        src = [k for k in (grid.nearest(p) for p in pts) if k is not None]
        dist, _nx = grid.distances(src)
        back, _nb = grid.distances(src, reverse=True)       # and back again: no pit / ledge you cannot leave
        boxes = [(np.asarray(a, np.float64), np.asarray(b, np.float64)) for a, b in avoid]
        cand = []
        for k in np.nonzero(np.isfinite(dist) & np.isfinite(back))[0]:
            p = grid.position(int(k))
            if any(np.all(p >= a - [30.0, 30.0, 30.0]) and np.all(p <= b + [30.0, 250.0, 30.0]) for a, b in boxes):
                continue
            if world.blocked(p[0], p[2], p[1], 40.0, 175.0, 45.0):     # room around it (a bit more than a player)
                continue
            if not any(abs(y - p[1]) < 3.0 for y in world.levels_at(p[0], p[2], box_tops=False)):
                continue                                               # on the floor itself, not on top of a box / object
            cand.append(p)
        if len(cand) < n:
            raise ValueError(f"only {len(cand)} free places on the floor for {n} points")
        C = np.array(cand)
        W = np.array([1.0, 2.0, 1.0])                                     # another level counts more than the same floor
        d = np.full(len(C), np.inf)
        for t in taken:
            d = np.minimum(d, np.sqrt((((C - np.asarray(t, np.float64)) * W) ** 2).sum(1)))
        chosen = []
        if not np.isfinite(d).any():
            chosen = [int(np.argmin(((C - np.mean(pts, 0)) ** 2).sum(1)))]
            d = np.sqrt((((C - C[chosen[0]]) * W) ** 2).sum(1))
        while len(chosen) < n:
            k = int(np.argmax(d))
            chosen.append(k)
            d = np.minimum(d, np.sqrt((((C - C[k]) * W) ** 2).sum(1)))
        self._spread_free = len(cand)
        return C[chosen]

    def spread_spawns(self, n: int = 32, teams: int = 2, avoid=(), cell: float = 60.0, seeds=None) -> str:
        """Replace the start points by ``n`` new ones spread as far apart as possible over every floor a player can walk
        to from the current ones (or ``seeds``): on the floor (20 over it), free of walls / boxes / objects, never inside
        ``avoid`` (engine (lo, hi) boxes, e.g. under water).  Teams alternate 0, 1 (a deathmatch ignores them)."""
        import copy as _copy
        from .. import gamemode
        from ..binutil import VStr
        if n < 1:
            raise ValueError("at least one start point")
        old = [r for r in self.scene.modules if r.clean_name.lower() == "mp_cstartpoint" and r.parsed is not None]
        locked = [r for r in old if self.is_locked(r)]
        seeds = [np.asarray(s, np.float64) for s in (seeds if seeds is not None else [r.parsed.position for r in old])]
        P = self.spread_points(n - len(locked), seeds, avoid, cell, taken=[r.parsed.position for r in locked])
        C = P
        chosen = list(range(len(P)))
        tpl = old[0] if old else None
        mid = C.mean(0)
        with self._batch("spread start points"):
            for r in old:
                if r not in locked:
                    self.scene.modules.remove(r)
            for i, k in enumerate(chosen):
                p = C[k] + [0.0, 20.0, 0.0]
                ang = math.atan2(mid[0] - p[0], mid[2] - p[2]) % (2 * math.pi)       # facing the middle of the map
                if tpl is not None:
                    r = _copy.copy(tpl)
                    r.parsed = _copy.deepcopy(tpl.parsed)
                    r.object_name = VStr((gamemode._new_name(self.scene, "StartPoint") + "\0").encode("cp1252"))
                    self.scene.modules.append(r)
                else:
                    r = gamemode.add_start_point(self.scene, p, ang, 0)
                r.parsed.position, r.parsed.angle = tuple(float(v) for v in p), float(ang)
                r.parsed.team, r.parsed.order = i % max(teams, 1), i // max(teams, 1)
        self.dirty_scene = self.needs_rebake = True
        gap = min(float(np.sqrt((((C[a] - C[b]) * [1, 0, 1]) ** 2).sum())) for a in chosen for b in chosen if a != b) \
            if len(chosen) > 1 else 0.0
        return (f"{n} start points spread over {self._spread_free} free places on the floor (at least {gap / 100:.1f} m apart)"
                + (f"; {len(locked)} locked ones kept" if locked else "") + " - save the scene")


class BlankMapOps:
    """A new map from zero: a floor of a chosen shape and size, walls round it, and what the game mode needs."""

    BLANK_SHAPES = ("rectangle", "square", "circle", "octagon", "L")
    BLANK_TEMPLATES = {"DM": "mp_dm_madrid.scn", "DMT": "mp_dmt_madrid.scn", "B": "mp_b_madrid.scn", "DO": "mp_do_madrid.scn"}

    @staticmethod
    def blank_outline(shape: str, width: float, depth: float, sides: int = 32) -> np.ndarray:
        """The floor's outline (n, 2) (x, z) centred on 0, anticlockwise.  ``width`` along x, ``depth`` along z
        (square: width x width; circle / octagon: width = diameter, depth ignored; L: a quarter cut away)."""
        w, d = float(width) / 2, float(depth) / 2
        if shape == "square":
            d = w
        if shape in ("rectangle", "square"):
            return np.array([(-w, -d), (w, -d), (w, d), (-w, d)])
        if shape in ("circle", "octagon"):
            n = 8 if shape == "octagon" else max(8, int(sides))
            a = np.linspace(0, 2 * math.pi, n, endpoint=False) + (math.pi / n if shape == "octagon" else 0.0)
            return np.stack([w * np.cos(a), w * np.sin(a)], 1)
        if shape == "L":
            return np.array([(-w, -d), (w, -d), (w, 0.0), (0.0, 0.0), (0.0, d), (-w, d)])
        raise ValueError(f"unknown shape {shape}")

    def new_blank_map(self, name: str, mode: str = "DM", shape: str = "rectangle", width: float = 4000.0,
                      depth: float = 3000.0, wall_height: float = 400.0, wall_thick: float = 40.0,
                      floor_tex: str = "SUELOS_03.tex", wall_tex: str = "muro_liso.tex", players: int = 16,
                      template: str = "") -> str:
        """A whole new map ``name`` (its own scene, .opt, .hm): the sky, sun, ambient light and settings of ``template``
        (a scene of the game of that mode; the Madrid one by default), a floor of ``shape`` (width x depth, units = cm)
        with collision, walls ``wall_height`` high all round it, and for the mode: start points (``players`` per team on
        both ends in DMT / B / DO; 2 x ``players`` all over the floor in DM), flags (B), the bomb zone and the bomb (DO),
        health packs and the intro camera.  Saved at once."""
        from .. import gamemode, hmcopy, shapes
        mode = mode.upper()
        if mode not in self.BLANK_TEMPLATES:
            raise ValueError("mode: DM, DMT, B or DO")
        width, depth = max(float(width), 600.0), max(float(depth), 600.0)
        tpl_name = template or self.BLANK_TEMPLATES[mode]
        if tpl_name not in self.scene_names():
            pref = gamemode.MODES[mode][2]
            cands = [n for n in self.scene_names() if n.lower().startswith(pref)]
            if not cands:
                raise ValueError(f"no scene of the game for mode {mode} to start from")
            tpl_name = cands[0]
        for t in (floor_tex, wall_tex):
            if self.fs.texture(t) is None:
                raise ValueError(f"texture {t} not found")
        self.load(tpl_name)
        msgs = [self.rename_map(name), self.empty_map()]
        out = self.blank_outline(shape, width, depth)
        # the floor: a slab 30 thick whose top is y = 0
        self.add_shape("polygon", points=[(x, -30.0, z) for x, z in out], height=30.0, texture=floor_tex, tile=256.0,
                       collision=True)
        # the walls: one per side, outside the outline, overlapping at the corners
        cen = out.mean(0)
        n_w = 0
        for i in range(len(out)):
            a, b = out[i], out[(i + 1) % len(out)]
            e = b - a
            L = float(np.hypot(*e))
            if L < 1.0:
                continue
            nrm = np.array([e[1], -e[0]]) / L
            mid = (a + b) / 2
            if np.dot(mid - cen, nrm) < 0 and shape != "L":
                nrm = -nrm
            if shape == "L" and shapes._point_in(mid + nrm * 5.0, out):
                nrm = -nrm
            at = mid + nrm * (wall_thick / 2)
            yaw = math.degrees(math.atan2(-e[1], e[0]))
            self.add_shape("wall", (L + 2 * wall_thick, float(wall_height), float(wall_thick)), (at[0], 0.0, at[1]), yaw,
                           wall_tex, 256.0, True)
            n_w += 1
        hm = self.heightmap_edit()
        faces = hmcopy.unique_faces(hm)
        fb = np.array([hmcopy.face_bounds(f) for f in faces])
        hm.root = hmcopy.build_tree(faces, (fb[:, 0].min() - 50, fb[:, 1].min() - 50, fb[:, 2].max() + 50, fb[:, 3].max() + 50))
        self._walk_key = self._ff_key = None
        self._changed_geometry()
        tpl = self.templates()
        span_x = out[:, 0].max() - out[:, 0].min()
        span_z = out[:, 1].max() - out[:, 1].min()
        along = 0 if span_x >= span_z else 2                       # the bases at both ends of the longest side
        centre = np.array([cen[0], 0.0, cen[1]])
        spawns = []
        if mode == "DM":
            seed = gamemode.add_start_point(self.scene, centre + [0.0, 20.0, 0.0], 0.0, 0)
            msgs.append(self.spread_spawns(max(2, 2 * int(players)), seeds=[centre]))
        else:
            lo2, hi2 = out.min(0), out.max(0)

            def inside(x, z, m=120.0):                   # inside the floor, away from the walls
                return shapes._point_in((x, z), out) and all(
                    shapes._point_in((x + dx, z + dz), out) for dx, dz in ((m, 0), (-m, 0), (0, m), (0, -m)))
            grid_pts = [np.array([x, 0.0, z]) for x in np.arange(lo2[0] + 150.0, hi2[0] - 100.0, 150.0)
                        for z in np.arange(lo2[1] + 150.0, hi2[1] - 100.0, 150.0) if inside(x, z)]
            if len(grid_pts) < 2 * players:
                raise ValueError("the floor is too small for that many start points")
            for team, sign in ((0, -1.0), (1, 1.0)):
                # the places nearest this end of the longest side (a block of rows), facing the middle
                mine = sorted(grid_pts, key=lambda q: (sign * -q[along], abs(q[2 - along] - centre[2 - along])))[:players]
                for q in mine:
                    ang = math.atan2(centre[0] - q[0], centre[2] - q[2]) % (2 * math.pi)
                    gamemode.add_start_point(self.scene, q + [0.0, 20.0, 0.0], ang, team)
                    spawns.append((team, q))
            bases = {t: np.mean([q for tt, q in spawns if tt == t], 0) for t in (0, 1)}
            if mode == "B":
                used = [q for _t, q in spawns]
                free = [q for q in grid_pts if all(np.linalg.norm(q - u) > 100.0 for u in used)] or grid_pts
                for t in (0, 1):
                    toward = bases[t] - (bases[1 - t] - bases[t]) * 0.08      # just behind its base, on the floor
                    q = min(free, key=lambda g: float(np.linalg.norm(g - toward)))
                    gamemode.add_flag(self.scene, tpl, q, t)
            if mode == "DO":                       # defenders (team 0) by the target, attackers (team 1) with the bomb
                target = bases[0] + (centre - bases[0]) * 0.35
                msgs.append(self.add_bomb_sites([(target, 300.0)], dll=False))
                bomb = tpl.clone("mp_Bomba", self.scene, "bomba")
                if bomb is not None:
                    from ..binutil import VStr
                    bomb.object_name = VStr(b"bomba\0")
                    M = np.asarray(bomb.parsed.transform, np.float64).copy()
                    M[3, :3] = bases[1] + (centre - bases[1]) * 0.15
                    bomb.parsed.transform = M.astype(np.float32)
            gamemode.set_mode(self.scene, mode)
        sp = [np.asarray(r.parsed.position) for r in self.scene.modules if r.clean_name.lower() == "mp_cstartpoint"]
        for q, size in zip(self.spread_points(4, [centre], taken=sp), ("big", "big", "small", "small")):
            gamemode.add_health(self.scene, tpl, q + [0.0, 20.0, 0.0], size)
        cam = next((r for r in self.scene.modules if r.clean_name.lower() == "mp_camerastartposition"), None)
        if cam is not None:
            import struct as _st
            eye = centre + [-0.6 * span_x, max(span_x, span_z) * 0.6 + wall_height, -0.6 * span_z]
            cam.data = _st.pack("<6f", *eye, *centre) + cam.data[24:]
            if cam.parsed is not None:
                cam.parsed.position, cam.parsed.target = tuple(eye), tuple(centre)
        else:
            gamemode.add_camera(self.scene, centre + [-0.6 * span_x, span_x * 0.6, -0.6 * span_z], centre)
        msgs.append(self.fresh_sectors())
        self.dirty_scene = True
        self.save_map()
        self.save_scene()
        self.bake()
        n_sp = sum(1 for r in self.scene.modules if r.clean_name.lower() == "mp_cstartpoint")
        return (f"new map {self.scene_name} ({mode}, {shape} {width / 100:.0f} x "
                f"{(width if shape in ('square', 'circle', 'octagon') else depth) / 100:.0f} m): floor, {n_w} walls "
                f"{wall_height / 100:.1f} m high, {n_sp} start points - saved")
