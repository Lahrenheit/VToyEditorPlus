"""Twin ships for capture the flag: the Love Boat map twice, side by side, joined by wooden gangplanks, one team per ship.

Works on an EditorState (``st``): it copies the ship region of the map (``regioncopy``), duplicates its scene modules, moves the
flags to the stern of each ship, gives each team ``per_team`` spawn points on its own ship, opens the bulwark at the gangplanks,
builds the gangplanks and tints each ship in the colour of its flag.  Everything is new data (copies and new textures with
new names): no shipped file is overwritten."""
from __future__ import annotations

import copy
import os
from typing import Dict, List

import numpy as np

from . import crop, gamemode, hmcopy, regioncopy, tint
from .modules import MPStartPoint
from .scn import VStr
from .tex import Texture

# textures of the ship whose coloured parts become team colours: name -> hue ranges (degrees)
SHIP_TINT = {
    "METAL-loveboat": [(235.0, 310.0)],      # the purple band of the hull
    "loveboat-01": [(75.0, 175.0)],          # the green panels (cabins, funnel)
}


def ship_box(opt, margin: float = 250.0):
    """(lo, hi) of the hull: union of the big meshes around the middle of the map (the sea tiles and far decoration excluded)."""
    cand = []
    for me in opt.meshes:
        a, b = crop.mesh_bounds(me)
        if np.isfinite(a).all() and (b - a).max() > 1500 and abs((a[0] + b[0]) / 2) < 6000 and abs((a[2] + b[2]) / 2) < 12000 \
                and (b - a)[[0, 2]].max() < 20000:
            cand.append((a, b))
    if not cand:
        raise ValueError("no ship found in this map")
    lo = np.min([c[0] for c in cand], 0)
    hi = np.max([c[1] for c in cand], 0)
    return lo - [margin, 1e6, margin], hi + [margin, 1e6, margin], lo, hi


def _tint_textures(st, rec_names, team: str, out_dir: str) -> Dict[str, str]:
    """Create ``<name>_<team>.tex`` for the ship textures; returns {old texture file: new texture file}."""
    mapping = {}
    for base, ranges in SHIP_TINT.items():
        t = st.fs.texture(base)
        if t is None:
            continue
        rgba = t.decode()
        new = tint.recolor(rgba, ranges, tint.TEAM_HUE[team])
        nt = Texture.from_rgba(new, fmt=t.fmt if hasattr(t, "fmt") else None, mipmaps=t.has_mips)
        name = f"{base}_{team}"
        nt.save(os.path.join(out_dir, name + ".tex"))
        mapping[base.lower() + ".tex"] = name + ".tex"
    return mapping


def _retexture(opt, mesh_ids, mapping: Dict[str, str]) -> int:
    n = 0
    for i in mesh_ids:
        for mat in opt.meshes[i].materials:
            if mat.textures and mat.textures[0].lower().replace("\0", "") in mapping:
                new = mapping[mat.textures[0].lower().replace("\0", "")]
                mat.textures[0] = new
                mat.name = new.rsplit(".", 1)[0]
                n += 1
    return n


def _floor_y(opt, x: float, z: float, default: float) -> float:
    """Highest walkable surface under (x, z) from the map's meshes (engine coordinates), below the roof level."""
    best = None
    for me in opt.meshes:
        a, b = crop.mesh_bounds(me)
        if not (a[0] <= x <= b[0] and a[2] <= z <= b[2]):
            continue
        for sm in me.render_submeshes():
            if len(sm.indices) < 3:
                continue
            p = sm.vertices["pos"].astype(np.float64)[sm.indices.reshape(-1, 3)]
            d = (p[:, 1, 2] - p[:, 2, 2]) * (p[:, 0, 0] - p[:, 2, 0]) + (p[:, 2, 0] - p[:, 1, 0]) * (p[:, 0, 2] - p[:, 2, 2])
            ok = np.abs(d) > 1e-9
            dd = np.where(ok, d, 1.0)
            u = ((p[:, 1, 2] - p[:, 2, 2]) * (x - p[:, 2, 0]) + (p[:, 2, 0] - p[:, 1, 0]) * (z - p[:, 2, 2])) / dd
            v = ((p[:, 2, 2] - p[:, 0, 2]) * (x - p[:, 2, 0]) + (p[:, 0, 0] - p[:, 2, 0]) * (z - p[:, 2, 2])) / dd
            w = 1 - u - v
            hit = ok & (u >= 0) & (v >= 0) & (w >= 0)
            if hit.any():
                h = (u * p[:, 0, 1] + v * p[:, 1, 1] + w * p[:, 2, 1])[hit]
                h = h[h < 500.0]                                  # ignore roofs / masts
                if len(h) and (best is None or h.max() > best):
                    best = float(h.max())
    return default if best is None else best


def build(st, gap: float = 800.0, per_team: int = 16, bridges=(-2500.0, 500.0, 5000.0), bridge_width: float = 320.0, rails: bool = False,
          tint_ships: bool = True, log=print) -> dict:
    """Make the twin ships.  Ship A (the original, east) = yellow team, ship B (the copy, to the west) = red team."""
    opt, scene = st.opt, st.scene
    if sum(1 for r in scene.modules if r.clean_name.lower() == "mp_cstartpoint") > 2 * per_team - 1 and \
            any(str(r.object_name).upper().startswith("ROJO_") for r in scene.modules if r.clean_name.lower() == "mp_cstartpoint") \
            and sum(1 for r in scene.modules if r.clean_name.lower() == "mp_flag") and len(opt.meshes) > 200:
        raise ValueError("this map already has the twin ships (use Undo, or load the map again)")
    lo, hi, hlo, hhi = ship_box(opt)
    width = float(hhi[0] - hlo[0])
    off_x = -(width + gap)                                       # west: the sector tree of the map ends in the east
    rep = regioncopy.copy_region(opt, lo, hi, [off_x, 0.0, 0.0])
    log("copied ship: " + rep.summary())

    # ------------------------------------------------------------------ scene modules inside the box
    flags = {}
    old = list(scene.modules)
    inside = []
    for rec in old:
        k = rec.clean_name.lower()
        try:
            pos = np.array(st.position_of(_sel(rec)), np.float64)
        except Exception:
            continue
        if not (lo[0] <= pos[0] <= hi[0] and lo[2] <= pos[2] <= hi[2]):
            continue
        if k in ("mp_flag", "mp_cstartpoint", "mp_camerastartposition"):
            continue
        name = str(rec.object_name).rstrip("\0").lower()
        if name in ("mar", "olas") or "gaviota" in name:
            continue
        inside.append((rec, pos))
    dup = 0
    for rec, pos in inside:
        c = st.duplicate_module(rec)
        st.set_position(_sel(c), pos + [off_x, 0.0, 0.0])
        dup += 1
    log(f"{dup} scene modules duplicated for ship B")

    # ------------------------------------------------------------------ flags at the stern, spawns per team
    starts = [r for r in old if r.clean_name.lower() == "mp_cstartpoint"]
    flag_recs = [r for r in old if r.clean_name.lower() == "mp_flag"]
    stern_z = float(hhi[2] - 2700.0)                              # the open stern deck (engine +z end)
    cx = float((hlo[0] + hhi[0]) / 2)
    fy = _floor_y(opt, cx - off_x * 0, stern_z, float(hlo[1]))
    for r in flag_recs:
        nm = str(r.object_name).lower()
        team = "rojo" if "roja" in nm or "rojo" in nm else "amarillo"
        x = cx + (off_x if team == "rojo" else 0.0)
        r.parsed.transform[3, :3] = (x, fy + 1.0, stern_z)
        flags[team] = r
    # spawn points: every original point is used for both teams (they stand on the ship's decks); extra points are offsets of them
    base = [(np.array(r.parsed.position, np.float64), float(r.parsed.angle)) for r in starts]
    teams = {}
    for r in starts:
        teams.setdefault(r.parsed.team, []).append(r)
    team_of = {"amarillo": None, "rojo": None}
    for r in starts:
        nm = str(r.object_name).upper()
        if "ROJO" in nm:
            team_of["rojo"] = r.parsed.team
        elif "AMARILLO" in nm:
            team_of["amarillo"] = r.parsed.team
    scene.modules[:] = [m for m in scene.modules if m not in starts]
    made = {"amarillo": 0, "rojo": 0}
    for team, ox in (("amarillo", 0.0), ("rojo", off_x)):
        pts = []
        i = 0
        while len(pts) < per_team and base:
            p, a = base[i % len(base)]
            ring = i // len(base)
            jitter = np.array([0.0, 0.0, 0.0]) if ring == 0 else np.array([140.0 * (1 if ring % 2 else -1), 0.0, 90.0 * ring])
            pts.append((p + jitter + [ox, 0.0, 0.0], a))
            i += 1
        for p, a in pts:
            rec = gamemode.add_start_point(scene, p, a, team_of[team] if team_of[team] is not None else (0 if team == "amarillo" else 1))
            rec.object_name = VStr((gamemode.unique_name(scene, team.upper() + "_01") + "\0").encode("cp1252"))
            made[team] += 1
    log(f"spawn points: {made}")

    # ------------------------------------------------------------------ bridges: open the bulwarks, lay the planks
    blk_boxes_before = len(crop.read_block(opt).boxes)
    wall_a = regioncopy.find_boxes(opt, [hlo[0] - 150, -1e6, hlo[2] - 600], [hlo[0] + 250, 1e6, hhi[2] + 600])
    wall_b = regioncopy.find_boxes(opt, [hhi[0] + off_x - 250, -1e6, hlo[2] - 600], [hhi[0] + off_x + 150, 1e6, hhi[2] + 600])
    gaps = [(z - bridge_width / 2 - 40, z + bridge_width / 2 + 40) for z in bridges]
    cut = 0
    for i in wall_a + wall_b:
        lo_w, hi_w = regioncopy._box_bounds(crop.read_block(opt).boxes[i])
        if hi_w[2] - lo_w[2] > 3000 and hi_w[0] - lo_w[0] < 600:             # a long bulwark running along z
            cut += regioncopy.cut_box(opt, i, gaps) - 1
    try:
        hm = st.heightmap_edit()
    except ValueError as e:
        hm = None
        log(f"WARNING: {e}; the second ship will have no floor")
    lay = gangplank_layout(opt, hm, hlo, hhi, off_x, bridges, bridge_width)
    lay["rails"] = bool(rails)
    lay["rail_panel"] = st.fs.texture("barandillas_poli.tex") is not None
    n_planks = 0
    for z in bridges:
        n_planks += len(add_gangplank_meshes(opt, lay, z, bridge_width))
    if 500.0 in [float(z) for z in bridges]:
        for a_, b_ in crate_regions(hlo, hhi, off_x):
            regioncopy.move_in_box(opt, a_, b_, [0.0, 0.0, -500.0])
        log("crates by the middle gangplank moved 5 m towards the bow")
    log(f"{len(bridges)} gangplanks over the rails (top y {lay['top']:.0f}, ramps {lay['ramp']:.0f} long), "
        f"{cut} bulwark pieces opened")

    # ------------------------------------------------------------------ floor collision (.hm): the ground the players stand on
    hm_info = None
    if hm is not None:
        hm_info = twin_floor(hm, lo, hi, off_x, bridges, bridge_width, lay)
        log(f"floor collision (.hm): {hm_info['copied']} faces copied to ship B, {len(bridges)} gangplank floors + ramps")

    # ------------------------------------------------------------------ colours
    tinted = {}
    if tint_ships:
        tex_dir = os.path.join(st.fs.root, "texs")
        os.makedirs(tex_dir, exist_ok=True)
        n0 = len(opt.meshes) - rep.meshes - n_planks
        a_ids = [i for i in range(n0) if _in_box(opt.meshes[i], lo, hi)]
        b_ids = list(range(n0, n0 + rep.meshes))
        for team, ids in (("amarillo", a_ids), ("rojo", b_ids)):
            mp = _tint_textures(st, None, team, tex_dir)
            tinted[team] = _retexture(opt, ids, mp)
        st.fs.rescan()
    st.dirty_scene = st.dirty_map = st.needs_rebake = True
    return {"offset_x": off_x, "copied": rep.summary(), "modules": dup, "spawns": made, "bridges": len(bridges),
            "bulwark_cuts": cut, "tinted_materials": tinted, "flag_y": fy, "hm": hm_info}


# ---------------------------------------------------------------------------------------------- gangplanks
# The ship's side is a bulwark: a wall from the deck (y -107) up to y -15 plus a rail up to y 30, and the floor collision (.hm)
# has those walls too.  A plank at deck level runs into them, so each gangplank is: a ramp up on ship A's deck, a flat walkway
# just above the rails (from one ship's inner wall to the other's) and a ramp down on ship B's deck.

def _deck_edges(hm, x, z, deck_y):
    """x range of the deck floor face under (x, z) at deck height, from the height map; None if not found."""
    best = None
    for f in hmcopy.unique_faces(hm):
        if f.normal[1] < 0.95:
            continue
        x0, z0, x1, z1 = hmcopy.face_bounds(f)
        if x0 <= x <= x1 and z0 <= z <= z1 and abs(-f.distance - deck_y) < 25:
            if best is None or (x1 - x0) > (best[1] - best[0]):
                best = (x0, x1)
    return best


def _rail_top(hm, x0, x1, z0, z1, below: float = 300.0):
    top = None
    for f in hmcopy.unique_faces(hm):
        fx0, fz0, fx1, fz1 = hmcopy.face_bounds(f)
        if fx1 < x0 or fx0 > x1 or fz1 < z0 or fz0 > z1:
            continue
        p = np.concatenate(f.contours)
        y = p[:, 1][p[:, 1] < below]
        if len(y) and (top is None or y.max() > top):
            top = float(y.max())
    return top


def crate_regions(hlo, hhi, off_x, z: float = 500.0):
    """The stacks of crates (props of mesh #43 + their boxes) at the foot of the middle gangplank: both sides of both ships."""
    out = []
    for dx in (0.0, off_x):
        out.append(([hlo[0] + 100.0 + dx, -125.0, z - 380.0], [hlo[0] + 470.0 + dx, 40.0, z - 30.0]))   # west side
        out.append(([hhi[0] - 490.0 + dx, -125.0, z - 380.0], [hhi[0] - 130.0 + dx, 40.0, z - 30.0]))   # east side
    return out


def move_crates(st, stock_opt, gap: float = 800.0, dz: float = -500.0, log=print) -> dict:
    """Move the crates next to the middle gangplank ``dz`` along z (default 5 m towards the bow) on both ships."""
    lo, hi, hlo, hhi = ship_box(stock_opt)
    off_x = -(float(hhi[0] - hlo[0]) + gap)
    hm = None
    try:
        hm = st.heightmap_edit()
    except ValueError:
        pass
    tot = {"props": 0, "boxes": 0, "hm_faces": 0}
    for a, b in crate_regions(hlo, hhi, off_x):
        r = regioncopy.move_in_box(st.opt, a, b, [0.0, 0.0, dz], hm)
        for k in tot:
            tot[k] += len(r[k]) if isinstance(r[k], list) else r[k]
    st.dirty_map = st.needs_rebake = True
    log(f"crates moved {dz / 100:+.0f} m: {tot['props']} props, {tot['boxes']} collision boxes")
    return tot


def gangplank_layout(opt, hm, hlo, hhi, off_x, bridges, width, slope: float = 1.6) -> dict:
    """Where the gangplanks go: inner walls of both ships, deck height, height of the walkway (over the rails), ramp length."""
    cx = float((hlo[0] + hhi[0]) / 2)
    z_mid = float(bridges[len(bridges) // 2]) if bridges else 0.0
    deck_y = _floor_y(opt, hlo[0] + 300, z_mid, -107.0)
    xa_in, xe_in = float(hlo[0]) + 110.0, float(hhi[0]) - 130.0           # fallbacks (stock Love Boat measures)
    top = deck_y + 150.0
    if hm is not None:
        e = _deck_edges(hm, cx, z_mid, deck_y)
        if e and e[1] - e[0] > 1000:
            xa_in, xe_in = e
        tw = _rail_top(hm, float(hlo[0]) - 40, xa_in + 20, z_mid - width, z_mid + width)
        te = _rail_top(hm, xe_in - 20, float(hhi[0]) + 40, z_mid - width, z_mid + width)
        tops = [t for t in (tw, te) if t is not None and t > deck_y]
        if tops:
            top = max(tops) + 8.0
    ramp = max(120.0, (top - deck_y) * slope)
    return {"deck": float(deck_y), "top": float(top), "ramp": float(ramp), "xa_in": float(xa_in), "xb_in": float(xe_in + off_x)}


def _ramp_mesh(opt, x_low, x_high, y_low, y_high, z0, z1, texture="tablones.tex", tile=128.0):
    """Planks from (x_low, y_low) to (x_high, y_high), z0..z1 wide (two sided)."""
    from . import fill
    xa, xb = sorted((x_low, x_high))
    me = fill.make_patch(opt, [(xa, z0), (xb, z0), (xb, z1), (xa, z1)], 0.0, texture, tile)
    sm = me.lods[0].parts[0].submeshes[0]
    v = sm.vertices
    t = (v["pos"][:, 0] - x_low) / (x_high - x_low)
    v["pos"][:, 1] = (y_low + t * (y_high - y_low)).astype(np.float32)
    n = np.array([-(y_high - y_low) / (x_high - x_low), 1.0, 0.0]); n /= np.linalg.norm(n)
    v["nrm"] = n.astype(np.float32)
    # texture runs along the slope
    run = np.hypot(x_high - x_low, y_high - y_low)
    v["uv"][:, 0] = (t * run / tile).astype(np.float32)
    lo, hi = v["pos"].min(0), v["pos"].max(0)
    corners = np.array([[x, yy, z] for x in (lo[0], hi[0]) for yy in (lo[1], hi[1]) for z in (lo[2], hi[2])], np.float32)
    me.corners = corners
    me.lods[0].parts[0].corners = corners.astype("<f4").tobytes()
    me.world_transform[3, :3] = (lo + hi) / 2
    return me


def add_gangplank_meshes(opt, lay, z, width) -> list:
    """Walkway + two ramps (meshes) + a thin collision box under the walkway. Returns the new mesh indices."""
    h = width / 2
    out = []
    xa, xb, top, deck, L = lay["xa_in"], lay["xb_in"], lay["top"], lay["deck"], lay["ramp"]
    walk = regioncopy.add_bridge(opt, xb, xa, z, width, top)                          # flat, over both rails
    out.append(walk["mesh"])
    out.append(crop.add_mesh(opt, _ramp_mesh(opt, xa + L, xa, deck + 1.0, top, z - h, z + h)))   # ship A: up towards the west
    out.append(crop.add_mesh(opt, _ramp_mesh(opt, xb - L, xb, deck + 1.0, top, z - h, z + h)))   # ship B: up towards the east
    if lay.get("rails"):                                  # optional (off by default)
        out += add_gangplank_rails(opt, lay, z, width)
    return out


RAIL_H = 110.0          # handrail height above the planks (a player is ~170 tall: cannot step or fall over it)
RAIL_T = 8.0            # half thickness of the rail walls
RAIL_VIS_H = 88.0       # what you see: panel 80 + wooden bar 8 (the ship's own railings are 74 + bar)


def _rail_segments(lay, z, width):
    """(x_from, x_to, y_from, y_to, z_side) of the 6 rail pieces: both sides of ramp A, walkway, ramp B."""
    h = width / 2
    xa, xb, top, deck, L = lay["xa_in"], lay["xb_in"], lay["top"], lay["deck"], lay["ramp"]
    out = []
    for zs in (z - h, z + h):
        out.append((xa + L, xa, deck + 1.0, top, zs))
        out.append((xb, xa, top, top, zs))
        out.append((xb - L, xb, deck + 1.0, top, zs))
    return out


def add_gangplank_rails(opt, lay, z, width) -> list:
    """Railings on both sides of a gangplank, looking like the ship's own (metal panel of barandillas_poli.tex + wooden bar
    on top) + collision walls, so nobody (and no flag carrier) falls into the sea from it.  Returns the new mesh indices."""
    from . import solids
    meshes = []
    for x0, x1, y0, y1, zs in _rail_segments(lay, z, width):
        meshes += solids.railing_visual(opt, [x0, y0, zs], [x1, y1, zs], RAIL_VIS_H, "tablones.tex", lay.get("rail_panel", True))
        lo_y, hi_y = min(y0, y1) - 5.0, max(y0, y1) + RAIL_H + 10.0
        regioncopy.add_box(opt, [(x0 + x1) / 2, (lo_y + hi_y) / 2, zs], [abs(x1 - x0) / 2 + 4.0, (hi_y - lo_y) / 2, RAIL_T])
    return meshes


def _flat_rail(opt, x0, x1, y, zs):
    from . import fill
    a, b = sorted((x0, x1))
    return fill.make_patch(opt, [(a, zs - 6.0), (b, zs - 6.0), (b, zs + 6.0), (a, zs + 6.0)], y, "tablones.tex", tile=128.0)


def _rail_faces(lay, z, width) -> list:
    """Vertical walls for the floor collision (.hm), both directions, along every rail piece."""
    faces = []
    for x0, x1, y0, y1, zs in _rail_segments(lay, z, width):
        a, b = sorted((x0, x1))
        ya, yb = (y0, y1) if x0 <= x1 else (y1, y0)
        pts = np.array([(a, ya - 5.0, zs), (b, yb - 5.0, zs), (b, yb + RAIL_H, zs), (a, ya + RAIL_H, zs)], np.float32)
        for nz in (1.0, -1.0):
            faces.append(hmcopy.make_face(pts, (0.0, 0.0, nz)))
    return faces


def _ramp_face(x_low, x_high, y_low, y_high, z0, z1):
    pts = np.array([(x_low, y_low, z0), (x_high, y_high, z0), (x_high, y_high, z1), (x_low, y_low, z1)], np.float64)
    n = np.cross(pts[1] - pts[0], pts[3] - pts[0])
    if n[1] < 0:
        n = -n
    n /= np.linalg.norm(n)
    area = 0.5 * float(np.sum(pts[:, 0] * np.roll(pts[:, 2], -1) - np.roll(pts[:, 0], -1) * pts[:, 2]))
    if area < 0:
        pts = pts[::-1].copy()
    return hmcopy.HMFace(tuple(float(c) for c in n), -float(n @ pts[0]), [pts.astype(np.float32)])


def twin_floor(hm, lo, hi, off_x, bridges, bridge_width, lay) -> dict:
    """Floor collision of ship B (copy of ship A's faces) and of the gangplanks, in the height map ``hm`` (changed in place)."""
    info = hmcopy.copy_region(hm, (lo[0], lo[2]), (hi[0], hi[2]), off_x)
    h = bridge_width / 2
    xa, xb, top, deck, L = lay["xa_in"], lay["xb_in"], lay["top"], lay["deck"], lay["ramp"]
    extra = []
    for z in bridges:
        extra += bridge_faces(lay, z, bridge_width)
    hmcopy.add_faces(hm, extra)
    return info


def bridge_faces(lay, z, width) -> list:
    """Floor collision of one gangplank: the walkway, the two ramps and (with rails) the walls along them."""
    h = width / 2
    xa, xb, top, deck, L = lay["xa_in"], lay["xb_in"], lay["top"], lay["deck"], lay["ramp"]
    out = [hmcopy.floor_quad(xb, xa, z - h, z + h, top),
           _ramp_face(xa + L, xa, deck + 1.0, top, z - h, z + h),
           _ramp_face(xb - L, xb, deck + 1.0, top, z - h, z + h)]
    if lay.get("rails"):
        out += _rail_faces(lay, z, width)
    return out


def has_rails(opt, lay, bridges) -> bool:
    """Are there handrails (thin plank meshes along the gangplanks) in this map?"""
    for me in opt.meshes:
        texs = {str(t).lower().rstrip("\0") for m in me.materials for t in m.textures[:1]}
        if texs != {"tablones.tex"}:
            continue
        a, b = crop.mesh_bounds(me)
        if b[2] - a[2] < 20 and lay["xb_in"] - 300 < a[0] and b[0] < lay["xa_in"] + 300 and a[1] > lay["deck"] + 50:
            return True
    return False


def rebuild_floor(st, stock_opt, stock_hm, gap: float = 800.0, bridges=(-2500.0, 500.0, 5000.0), bridge_width: float = 320.0,
                  log=print, rails=None) -> dict:
    """Repair the .hm of a map made with the twin ships: start again from the stock Love Boat height map (``stock_hm``,
    measured on ``stock_opt``) and add ship B + gangplanks.  The editor keeps it in memory until the map is saved."""
    lo, hi, hlo, hhi = ship_box(stock_opt)
    off_x = -(float(hhi[0] - hlo[0]) + gap)
    lay = gangplank_layout(stock_opt, stock_hm, hlo, hhi, off_x, bridges, bridge_width)
    lay["rails"] = has_rails(st.opt, lay, bridges) if rails is None else bool(rails)
    lay["rail_panel"] = st.fs.texture("barandillas_poli.tex") is not None
    info = twin_floor(stock_hm, lo, hi, off_x, bridges, bridge_width, lay)
    st.hm_edit = stock_hm
    st.dirty_map = True
    log(f"floor collision rebuilt: {info['copied']} faces for ship B, {len(bridges)} gangplanks (save the map to write it)")
    info["layout"] = lay
    return info


def rebuild_gangplanks(st, stock_opt, stock_hm, gap: float = 800.0, bridges=(-2500.0, 500.0, 5000.0),
                       bridge_width: float = 320.0, log=print, rails: bool = False) -> dict:
    """For a map made before the ramps: remove the old flat planks (meshes + boxes between the ships), lay the new
    gangplanks and rebuild the floor collision."""
    opt = st.opt
    lo, hi, hlo, hhi = ship_box(stock_opt)
    off_x = -(float(hhi[0] - hlo[0]) + gap)
    lay = gangplank_layout(stock_opt, stock_hm, hlo, hhi, off_x, bridges, bridge_width)
    lay["rails"] = bool(rails)
    lay["rail_panel"] = st.fs.texture("barandillas_poli.tex") is not None
    x_lo, x_hi = float(hhi[0] + off_x) - 400.0, float(hlo[0]) + 400.0      # between the two ships (+ a bit of each deck)
    old = []
    for i, me in enumerate(opt.meshes):
        texs = {str(t).lower().rstrip("\0") for m in me.materials for t in m.textures[:1]}
        if texs != {"tablones.tex"} and texs != {"barandillas_poli.tex"}:       # planks, wooden bars, railing panels
            continue
        a, b = crop.mesh_bounds(me)
        if a[0] >= x_lo and b[0] <= x_hi and b[0] - a[0] > 200 and any(abs((a[2] + b[2]) / 2 - z) < bridge_width / 2 + 30 for z in bridges):
            old.append(i)
    boxes = []
    for z in bridges:
        for i in regioncopy.find_boxes(opt, [x_lo, lay["deck"] - 80.0, z - bridge_width],
                                       [x_hi, lay["top"] + RAIL_H + 40.0, z + bridge_width]):
            a, b = regioncopy._box_bounds(crop.read_block(opt).boxes[i])
            if b[0] - a[0] > 200:                   # planks / rails are long; the crates' boxes (~1 m) stay
                boxes.append(i)
    if boxes:
        crop.remove_collision_indices(opt, sorted(set(boxes)))
    if old:
        crop.remove_meshes(opt, set(old), collision=False)
    for z in bridges:
        add_gangplank_meshes(opt, lay, z, bridge_width)
    info = rebuild_floor(st, stock_opt, stock_hm, gap, bridges, bridge_width, log, rails=rails)
    st.dirty_map = st.needs_rebake = True
    log(f"gangplanks rebuilt: {len(old)} old plank meshes and {len(set(boxes))} boxes removed")
    return {"removed_meshes": len(old), "removed_boxes": len(set(boxes)), **info}


# ---------------------------------------------------------------------------------------------- gangplanks, one by one
# A gangplank is found in the map by what it is made of (a flat plank of tablones.tex from one ship to the other with a ramp
# at each end), so the list survives undo, renaming the map, zips and other PCs without being stored anywhere.

def _plank_meshes(opt):
    """(index, lo, hi) of the meshes made only of tablones.tex / barandillas_poli.tex."""
    out = []
    for i, me in enumerate(opt.meshes):
        texs = {str(t).lower().rstrip("\0") for m in me.materials for t in m.textures[:1]}
        if texs == {"tablones.tex"} or texs == {"barandillas_poli.tex"}:
            a, b = crop.mesh_bounds(me)
            out.append((i, a, b, texs == {"tablones.tex"}))
    return out


def find_bridges(opt, hlo, hhi) -> list:
    """The gangplanks of a twin-ships map: [{'z', 'width', 'rails', 'xa', 'xb', 'top', 'deck', 'ramp'}] sorted by z.
    ``hlo`` / ``hhi``: bounds of the stock hull (ship A, the original)."""
    planks = _plank_meshes(opt)
    out = []
    for i, a, b, wood in planks:
        if not wood or b[1] - a[1] > 0.5 or b[0] - a[0] < 500 or not 100 <= b[2] - a[2] <= 2500:
            continue
        if b[0] > hlo[0] + 3200 or a[0] > hlo[0]:                 # must leave ship A towards the west
            continue
        if sum(len(sm.vertices) for sm in opt.meshes[i].render_submeshes()) != 4:
            continue
        z, w, top, xa, xb = float((a[2] + b[2]) / 2), float(b[2] - a[2]), float(a[1]), float(b[0]), float(a[0])
        deck, L = top - 145.0, 0.0
        rails = False
        for j, c, d, wood2 in planks:
            if j == i:
                continue
            if wood2 and abs(c[2] - a[2]) < 1.5 and abs(d[2] - b[2]) < 1.5 and abs(d[1] - top) < 1.0 and d[1] - c[1] > 20 \
                    and (abs(c[0] - xa) < 1.5 or abs(d[0] - xb) < 1.5):
                deck, L = float(c[1]) - 1.0, float(d[0] - c[0])              # one of its ramps
            elif d[2] - c[2] < 20 and (abs((c[2] + d[2]) / 2 - a[2]) < 12 or abs((c[2] + d[2]) / 2 - b[2]) < 12) \
                    and c[0] >= xb - 400 and d[0] <= xa + 400 and c[1] >= top - 200:
                rails = True                                                 # a railing panel / bar along its side
        out.append({"z": z, "width": w, "rails": rails, "xa": xa, "xb": xb, "top": top, "deck": deck,
                    "ramp": L if L > 0 else max(120.0, (top - deck) * 1.6)})
    out.sort(key=lambda b: b["z"])
    return out


def _lay_of(b: dict, rail_panel: bool = True) -> dict:
    return {"xa_in": b["xa"], "xb_in": b["xb"], "top": b["top"], "deck": b["deck"], "ramp": b["ramp"],
            "rails": bool(b.get("rails")), "rail_panel": rail_panel}


def deck_profile(world, hlo, hhi, z: float):
    """(deck height, west edge x, east edge x) of ship A's deck at engine z, from its floor collision; None off the ship."""
    xs = np.arange(float(hlo[0]) - 100.0, float(hhi[0]) + 100.0, 5.0)
    lows = []
    for x in np.arange(float(hlo[0]) + 600.0, float(hhi[0]) - 600.0, 100.0):
        lv = [l for l in world.levels_at(float(x), z, box_tops=False) if -450.0 < l < 150.0]
        if lv:
            lows.append(min(lv))
    if not lows:
        return None
    deck = float(np.median(lows))
    on = [float(x) for x in xs if any(abs(l - deck) < 30.0 for l in world.levels_at(float(x), z, box_tops=False))]
    if not on:
        return None
    return deck, on[0], on[-1]


def bridge_layout(stock_hm, hlo, hhi, off_x: float, z: float, width: float, world=None) -> dict:
    """Measures of a gangplank at engine ``z``, ``width`` wide, anywhere along the ships (also where the hull narrows at
    the bow): the walkway runs between the innermost points of the two decks along its width, just above the rails."""
    from . import walk
    if world is None:
        world = walk.World(hmcopy.unique_faces(stock_hm))
    h = width / 2
    prof = []
    for zs in np.linspace(z - h, z + h, 5):
        pr = deck_profile(world, hlo, hhi, float(zs))
        if pr is None:
            raise ValueError("there is no deck there on the ships (move the gangplank along the ship)")
        prof.append((float(zs),) + pr)
    deck = float(np.median([p[1] for p in prof]))
    if max(abs(p[1] - deck) for p in prof) > 30.0:
        raise ValueError("the deck changes height across the gangplank there (move it a little)")
    xa = max(p[2] for p in prof)                              # west edge, the point furthest inboard
    xe = min(p[3] for p in prof)
    # what the walkway must clear: the bulwark and its rail (wall tops and floor tops near the edge), on both sides
    top = deck + 60.0
    for zs, _d, we, ee in prof:
        for x0, x1 in ((we - 160.0, we + 6.0), (ee - 6.0, ee + 160.0)):
            for x in np.arange(x0, x1 + 1.0, 10.0):
                for l in world.levels_at(float(x), zs, box_tops=False):
                    if deck < l < deck + 260.0:
                        top = max(top, l)
            for i in world._near(world._wg, (x0 + x1) / 2, zs, 90.0):
                w = world.walls[i]
                b = w.bounds
                if b[0] <= x1 and b[2] >= x0 and b[1] <= zs + 10 and b[3] >= zs - 10 and deck < w.y1 < deck + 260.0:
                    top = max(top, w.y1)
    top += 8.0
    ramp = max(120.0, (top - deck) * 1.6)
    return {"z": float(z), "width": float(width), "xa": float(xa), "xb": float(xe + off_x), "top": float(top), "deck": float(deck),
            "ramp": float(ramp)}


def remove_bridge(opt, hm, b: dict) -> dict:
    """Take one gangplank out of the map: its planks and railings, its collision boxes and its floor / wall faces."""
    h, L = b["width"] / 2, b["ramp"]
    lo = np.array([b["xb"] - L - 12.0, b["deck"] - 12.0, b["z"] - h - 14.0])
    hi = np.array([b["xa"] + L + 12.0, b["top"] + RAIL_H + 30.0, b["z"] + h + 14.0])
    old = [i for i, a, c, _w in _plank_meshes(opt) if np.all(a >= lo) and np.all(c <= hi)]
    boxes = []
    for i in regioncopy.find_boxes(opt, lo - [0, 40, 0], hi):
        a, c = regioncopy._box_bounds(crop.read_block(opt).boxes[i])
        if c[0] - a[0] > 150:                         # planks / rails are long; crate boxes stay
            boxes.append(i)
    if boxes:
        crop.remove_collision_indices(opt, sorted(set(boxes)))
    if old:
        crop.remove_meshes(opt, set(old), collision=False)
    nf = 0
    if hm is not None:
        keep = []
        for f in hmcopy.unique_faces(hm):
            p = np.concatenate(f.contours).astype(np.float64)
            n = f.normal
            mine = False
            if np.all(p >= lo) and np.all(p <= hi):
                if abs(n[1]) > 0.99 and np.abs(p[:, 1] - b["top"]).max() < 1.5:
                    mine = True                                               # the walkway
                elif abs(n[2]) < 0.01 and 0.2 < n[1] < 0.99 and (abs(p[:, 2].min() - (b["z"] - h)) < 1.5):
                    mine = True                                               # a ramp
                elif abs(n[2]) > 0.99 and (np.abs(p[:, 2] - (b["z"] - h)).max() < 1.5 or np.abs(p[:, 2] - (b["z"] + h)).max() < 1.5):
                    mine = True                                               # a rail wall
            if mine:
                nf += 1
            else:
                keep.append(f)
        if nf:
            hm.root = hmcopy.build_tree(keep, hmcopy.box(hm.root), max(hmcopy.tree_depth(hm.root), 1))
    return {"meshes": len(old), "boxes": len(set(boxes)), "faces": nf}


def add_bridge(opt, hm, b: dict, rail_panel: bool = True) -> dict:
    """Lay one gangplank (planks, optional railings, collision boxes, floor faces)."""
    lay = _lay_of(b, rail_panel)
    meshes = add_gangplank_meshes(opt, lay, b["z"], b["width"])
    nf = 0
    if hm is not None:
        faces = bridge_faces(lay, b["z"], b["width"])
        hmcopy.add_faces(hm, faces)
        nf = len(faces)
    return {"meshes": len(meshes), "faces": nf}


def ship_offset(opt, stock_hm, hlo, hhi, gap: float = 800.0, world=None) -> float:
    """How far west ship B is from ship A: measured on a gangplank of the map, else from ``gap``."""
    from . import walk
    if world is None:
        world = walk.World(hmcopy.unique_faces(stock_hm))
    offs = []
    for b in find_bridges(opt, hlo, hhi):
        pr = deck_profile(world, hlo, hhi, b["z"])
        if pr is not None and abs(b["xa"] - pr[1]) < 40.0:        # a straight part of the hull
            offs.append(b["xb"] - pr[2])
    return float(np.median(offs)) if offs else -(float(hhi[0] - hlo[0]) + gap)


def _in_box(mesh, lo, hi) -> bool:
    a, b = crop.mesh_bounds(mesh)
    c = (a + b) / 2
    return bool(np.all(c[[0, 2]] >= np.asarray(lo)[[0, 2]]) and np.all(c[[0, 2]] <= np.asarray(hi)[[0, 2]]))


def _sel(rec):
    from .app.state import Selection
    return Selection("module", rec, "")
