"""Batch 13: Counter-Strike 1.6 maps (.bsp) brought into a map, emptying an area, weapons one by one."""
import math, os, struct, tempfile
import _path
import numpy as np
from test_batch7 import _st
from vtoy import bspimport, crop, hmcopy
from vtoy.bsp import BspMap


def _box_faces(lo, hi):
    """The 6 faces of an axis box as (points, outward normal), points wound like Quake (clockwise seen from outside)."""
    x0, y0, z0 = lo
    x1, y1, z1 = hi
    F = [((x0, y0, z1), (x0, y1, z1), (x1, y1, z1), (x1, y0, z1), (0, 0, 1)),
         ((x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0), (0, 0, -1)),
         ((x0, y0, z0), (x0, y0, z1), (x1, y0, z1), (x1, y0, z0), (0, -1, 0)),
         ((x0, y1, z0), (x1, y1, z0), (x1, y1, z1), (x0, y1, z1), (0, 1, 0)),
         ((x0, y0, z0), (x0, y1, z0), (x0, y1, z1), (x0, y0, z1), (-1, 0, 0)),
         ((x1, y0, z0), (x1, y0, z1), (x1, y1, z1), (x1, y1, z0), (1, 0, 0))]
    return [(np.array(f[:4], float), np.array(f[4], float)) for f in F]


def write_bsp(path, models, textures, entities):
    """A minimal Half-Life .bsp v30: ``models`` = [[(points, normal, texture index), ...], ...] (model 0 = the world)."""
    verts, edges, surf, planes, faces, texinfo, mrecs = [], [(0, 0)], [], [], [], [], []
    for m in models:
        first = len(faces)
        for pts, n, ti in m:
            planes.append((n, float(n @ pts[0])))
            fe = len(surf)
            for k in range(len(pts)):
                verts.append(pts[k])
                verts.append(pts[(k + 1) % len(pts)])
                edges.append((len(verts) - 2, len(verts) - 1))
                surf.append(len(edges) - 1)
            a = np.array([1.0, 0, 0]) if abs(n[0]) < 0.9 else np.array([0, 1.0, 0])
            s = np.cross(n, a); s /= np.linalg.norm(s)
            t = np.cross(n, s)
            texinfo.append((s, t, ti))
            faces.append((len(planes) - 1, fe, len(pts), len(texinfo) - 1))
        allp = np.concatenate([p for p, _n, _t in m])
        mrecs.append((allp.min(0), allp.max(0), first, len(m)))
    L = {}
    L["entities"] = ("".join("{\n" + "".join(f'"{k}" "{v}"\n' for k, v in e.items()) + "}\n" for e in entities)).encode() + b"\0"
    L["planes"] = b"".join(struct.pack("<3ffi", *n, d, 0) for n, d in planes)
    tl = struct.pack("<i", len(textures))
    offs, body = [], b""
    for name, (w, h) in textures:
        offs.append(4 + 4 * len(textures) + len(body))
        body += name.encode().ljust(16, b"\0") + struct.pack("<II4I", w, h, 0, 0, 0, 0)
    L["textures"] = tl + b"".join(struct.pack("<i", o) for o in offs) + body
    L["vertices"] = b"".join(struct.pack("<3f", *v) for v in verts)
    L["texinfo"] = b"".join(struct.pack("<4f4fii", *s, 0.0, *t, 0.0, ti, 0) for s, t, ti in texinfo)
    L["faces"] = b"".join(struct.pack("<HHiHH4Bi", pl, 0, fe, ne, ti, 0, 0, 0, 0, -1) for pl, fe, ne, ti in faces)
    L["edges"] = b"".join(struct.pack("<HH", a, b) for a, b in edges)
    L["surfedges"] = b"".join(struct.pack("<i", e) for e in surf)
    L["models"] = b"".join(struct.pack("<9f4iiii", *lo, *hi, 0, 0, 0, 0, 0, 0, 0, 0, fi, nf) for lo, hi, fi, nf in mrecs)
    from vtoy.bsp import LUMPS
    head = struct.pack("<i", 30)
    data = b""
    base = 4 + 8 * len(LUMPS)
    for name in LUMPS:
        blob = L.get(name, b"")
        head += struct.pack("<ii", base + len(data), len(blob))
        data += blob
    open(path, "wb").write(head + data)


def make_arena(path):
    """A 1024 x 2048 room (floor, 4 walls, inner faces), one crate (a brush entity), 2 + 2 player starts."""
    room = []
    lo, hi = (0, 0, 0), (1024, 2048, 256)
    for pts, n in _box_faces(lo, hi):
        room.append((pts[::-1].copy(), -n, 0 if n[2] > 0.5 or n[2] < -0.5 else 1))      # faces looking inwards
    room = [f for f in room if f[1][2] > -0.5]                                           # no ceiling
    room = [(p, n, 2 if n[2] > 0.5 else t) for p, n, t in room]                          # floor = sand
    crate = [(p, n, 3) for p, n in _box_faces((480, 960, 0), (544, 1024, 64))]
    sky = [(np.array([(0, 0, 300), (1024, 0, 300), (1024, 2048, 300), (0, 2048, 300)], float), np.array([0, 0, -1.0]), 0)]
    write_bsp(path, [room + sky, crate], [("sky", (16, 16)), ("-0csSandWall", (128, 240)), ("-0Sand", (128, 128)),
                                         ("SandCrtLrgSd", (64, 64))],
              [{"classname": "worldspawn"},
               {"classname": "info_player_start", "origin": "300 200 36", "angle": "90"},
               {"classname": "info_player_start", "origin": "700 200 36", "angle": "90"},
               {"classname": "info_player_deathmatch", "origin": "300 1800 36", "angle": "270"},
               {"classname": "info_player_deathmatch", "origin": "700 1800 36", "angle": "270"},
               {"classname": "func_wall", "model": "*1"}])


def test_bsp_reading_and_layout():
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "arena.bsp")
        make_arena(p)
        b = BspMap.load(p)
        assert len(b.faces) == 5 + 1 + 6 and {f.model for f in b.faces} == {0, 1}
        assert sum(1 for e in b.entities if e.get("classname", "").startswith("info_player")) == 4
        assert b.textures["-0Sand"] == (128, 128)
        drawn = bspimport.drawn_faces(b)
        assert len(drawn) == 11 and not any(f.texture == "sky" for f in drawn)
        # laid at a point, turned 90: CS +y runs along the engine +x, the floor at at.y, the middle at at.x / at.z
        pl = bspimport.plan(b, (1000.0, 50.0, -500.0), 90.0)
        lo, hi = bspimport.footprint(b, pl)
        assert abs(lo[1] - 50.0) < 1e-6 and abs(hi[1] - 50.0 - 256 * 2.54) < 1e-3
        assert abs((hi[0] - lo[0]) - 2048 * 2.54) < 1e-3 and abs((hi[2] - lo[2]) - 1024 * 2.54) < 1e-3
        assert np.allclose((lo + hi)[[0, 2]] / 2, (1000.0, -500.0))
        # the shape is not mirrored.  Seen from above, CS draws x right / y up (right-handed, z up) and the engine draws
        # x right / z up (left-handed, y up): CS x -> y and their images in the engine must turn the same way
        a, bb, c = pl.point([0, 0, 0]), pl.point([100, 0, 0]), pl.point([0, 100, 0])
        e1, e2 = (bb - a)[[0, 2]], (c - a)[[0, 2]]
        assert e1[0] * e2[1] - e1[1] * e2[0] > 0
        # a start point looking along CS +y (angle 90) looks along the engine +x
        assert abs(pl.angle(90.0) - math.pi / 2) < 1e-6
        cv = bspimport.convert(b, pl)
        assert len(cv.spawns) == 4 and sorted(t for _p, _a, t in cv.spawns) == [0, 0, 1, 1]
        assert cv.textures["-0Sand"].lower().startswith("suelos") and cv.textures["SandCrtLrgSd"].startswith("caja")
        assert len(cv.hm_faces) == 4 + 1 + 5                       # walls + floor of the room, the crate but its bottom
        assert len(cv.boxes) == 5 + 1                              # one behind each room face, one around the crate
        for c, h, R in cv.boxes:
            assert abs(R[1] @ [0, 1, 0] - 1.0) < 1e-6              # only turned about the vertical, like the game's own


def test_guess_texture():
    have = {"caja1.tex", "caja2.tex", "SUELOS_03.tex", "catedra_muro.tex", "muro_liso.tex"}
    ok = lambda t: t in have
    assert bspimport.guess_texture("MltryCrteSd2", ok) == "caja2.tex"
    assert bspimport.guess_texture("SandCrtSmSd", ok) == "caja1.tex"
    assert bspimport.guess_texture("-1csSandWall", ok) == "catedra_muro.tex"
    assert bspimport.guess_texture("-3Sand", ok) == "SUELOS_03.tex"
    assert bspimport.guess_texture("SandWllDoor", ok) == "catedra_muro.tex"     # no door texture: a wall one
    assert bspimport.guess_texture("zzz", ok) == "muro_liso.tex"
    assert bspimport.skipped("sky") and bspimport.skipped("AAATRIGGER") and not bspimport.skipped("-0Sand")


def test_import_bsp_into_a_map():
    with tempfile.TemporaryDirectory() as tmp:
        st = _st(tmp, "mp_dm_almacen.scn")
        p = os.path.join(tmp, "arena.bsp")
        make_arena(p)
        rows = st.bsp_textures(p)
        assert {r[0] for r in rows} == {"-0csSandWall", "-0Sand", "SandCrtLrgSd"}
        assert all(st.fs.texture(r[1]) is not None for r in rows)
        sp = np.array(next(q for lst in st.spawn_positions().values() for _n, q in lst), np.float64)
        floor = st.floor_below(sp[0], sp[2], sp[1] + 50)
        at = (sp[0] + 30000.0, (floor or 0.0) + 2.0, sp[2])        # off the map: a place of its own
        nm, nb0 = len(st.opt.meshes), len(crop.read_block(st.opt).boxes)
        nf0 = len(hmcopy.unique_faces(st.heightmap_edit()))
        n_sp = sum(1 for r in st.scene.modules if r.clean_name.lower() == "mp_cstartpoint")
        msg = st.import_bsp(p, at, 90.0, 2.54)
        assert "4 start points" in msg
        new_meshes = st.opt.meshes[nm:]                            # per Torrente texture and part of the map
        assert len({m.materials[0].textures[0].lower() for m in new_meshes}) == 3 and len(new_meshes) >= 3
        assert len(crop.read_block(st.opt).boxes) == nb0 + 6
        assert len(hmcopy.unique_faces(st.heightmap_edit())) == nf0 + 10
        new = [r for r in st.scene.modules if r.clean_name.lower() == "mp_cstartpoint"][n_sp:]
        assert len(new) == 4 and st.game_mode() == "DMT"
        for r in new:                                              # on the new floor, 20 over it, free of walls / crate
            x, y, z = r.parsed.position
            assert abs(y - (at[1] + 20.0)) < 1.0
        bad = [x for x in st.spawn_report(sight=False) if any(r.parsed.position == tuple(x["pos"]) for r in new)]
        assert not bad
        # empty the place again: what stands there goes, the new floor (lowest level there) stays
        lo, hi = st.bsp_footprint(p, at, 90.0, 2.54)
        msg = st.clear_area(lo - 50.0, hi + 50.0)
        assert "4 modules" in msg
        left = [i for i, m in enumerate(st.opt.meshes) if i >= nm]
        assert len(left) == 1 and "suelos" in st.opt.meshes[left[0]].materials[0].textures[0].lower()
        assert len(crop.read_block(st.opt).boxes) == nb0 + 1                   # the floor's box (under the floor)
        assert sum(1 for r in st.scene.modules if r.clean_name.lower() == "mp_cstartpoint") == n_sp
        st.save_map(); st.save_scene()
        st.load("mp_dm_almacen.scn")
        assert len(st.opt.meshes) == nm + 1


def test_weapon_groups_one_weapon_each():
    """The weapons panel's choice (one weapon of a group, all, none) is what the DLL patch gets."""
    from vtoy.dllpatch import WEAPON_GROUPS
    src = os.environ.get("VTOY_FLAG_DLL", "")
    ctf = os.path.join(os.path.dirname(src), "ctf.dll") if src else ""
    if not ctf or not os.path.isfile(ctf):
        return
    from vtoy import dllpatch
    data = open(ctf, "rb").read()
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "w.dll")
        forced = [0, 0, 16, 10, 14]                                # knife, pistol, cetme, grenade launcher, mines
        dllpatch.patch_weapon_groups(ctf, out, [True] * 5, forced)
        got = dllpatch.weapon_choice(open(out, "rb").read())
        assert list(got)[2:] == [16, 10, 14]
        assert all(f == 0 or f in WEAPON_GROUPS[g] for g, f in enumerate(forced))
        assert open(out, "rb").read() != data


def _write_wad(path, mips):
    """A WAD3 with the miptex ``mips`` [(name, w, h, indices bytes, palette bytes)]."""
    body, dirs = b"", []
    for name, w, h, pix, pal in mips:
        o0 = 40
        o1 = o0 + w * h
        o2 = o1 + (w // 2) * (h // 2)
        o3 = o2 + (w // 4) * (h // 4)
        mt = name.encode().ljust(16, b"\0") + struct.pack("<II4I", w, h, o0, o1, o2, o3)
        mt += pix + b"\0" * ((w // 2) * (h // 2) + (w // 4) * (h // 4) + (w // 8) * (h // 8))
        mt += struct.pack("<H", 256) + pal + b"\0\0"
        dirs.append((12 + len(body), len(mt), name))
        body += mt
    head = b"WAD3" + struct.pack("<ii", len(mips), 12 + len(body))
    d = b"".join(struct.pack("<iiibbh16s", pos, size, size, 0x43, 0, 0, n.encode()) for pos, size, n in dirs)
    open(path, "wb").write(head + body + d)


def test_wad_textures():
    from vtoy import wad
    with tempfile.TemporaryDirectory() as tmp:
        pal = bytes(range(256)) * 3
        pal = bytes(v for i in range(256) for v in (i, 255 - i, 7))
        pix = bytes((x + y) % 256 for y in range(16) for x in range(32))
        p = os.path.join(tmp, "t.wad")
        _write_wad(p, [("SandWallX", 32, 16, pix, pal), ("{fence", 16, 16, bytes([255] * 128 + [3] * 128), pal)])
        w = wad.read_wad(p)
        assert set(w) == {"sandwallx", "{fence"}
        a = w["sandwallx"].rgba()
        assert a.shape == (16, 32, 4) and tuple(a[0, 5, :3]) == (5, 250, 7) and a[..., 3].min() == 255
        f = w["{fence"].rgba()
        assert f[0, 0, 3] == 0 and f[15, 15, 3] == 255                 # '{': the last palette colour is see-through


def test_two_bomb_zones_dll():
    from vtoy import dllpatch
    src = os.path.join(os.path.dirname(os.environ.get("VTOY_FLAG_DLL", "")), "dtt.dll")
    if not os.path.isfile(src):
        return
    data = open(src, "rb").read()
    assert dllpatch.can_have_second_bomb_zone(data) and dllpatch.second_bomb_zone(data) is None
    with tempfile.TemporaryDirectory() as tmp:
        a, b = os.path.join(tmp, "a.dll"), os.path.join(tmp, "b.dll")
        assert dllpatch.patch_second_bomb_zone(src, a) == "bombZone_B"
        d = open(a, "rb").read()
        assert len(d) == len(data) + 0x2000 and dllpatch.second_bomb_zone(d) == "bombZone_B"   # + its section
        i = data.find(bytes.fromhex("3bfb74718a877801000084c07467"))
        assert d[i] == 0xE9 and d[i + 5:i + 14] == b"\x90" * 9         # the test jumps to the new code
        assert b"bombZone_B\0" in d                                     # the name, in the new section
        dllpatch.patch_second_bomb_zone(a, b, "sitioB")                  # again: only the name changes
        assert dllpatch.second_bomb_zone(open(b, "rb").read()) == "sitioB"
        diff = sum(x != y for x, y in zip(data, open(b, "rb").read()))
        assert diff < 100                                                # in the DLL's own bytes: headers + 2 hooks
        try:
            dllpatch.patch_second_bomb_zone(os.path.join(os.path.dirname(src), "ctf.dll"), b)
            assert False, "only the destroy-the-target DLL"
        except ValueError:
            pass


def test_new_do_map_from_bsp():
    """Empty a map, lay a .bsp with two bomb sites as destroy the target, new sectors."""
    with tempfile.TemporaryDirectory() as tmp:
        st = _st(tmp, "mp_dm_almacen.scn")
        p = os.path.join(tmp, "sites.bsp")
        room = []
        for pts, n in _box_faces((0, 0, 0), (2048, 2048, 256)):
            room.append((pts[::-1].copy(), -n, 1))
        room = [(q, n, 2 if n[2] > 0.5 else t) for q, n, t in room if n[2] > -0.5]
        trig_a = [(q, n, 0) for q, n in _box_faces((200, 1600, 0), (456, 1856, 128))]
        trig_b = [(q, n, 0) for q, n in _box_faces((1600, 1600, 0), (1856, 1856, 128))]
        ents = [{"classname": "worldspawn"}, {"classname": "func_bomb_target", "model": "*2", "target": "tgt_b"},
                {"classname": "func_bomb_target", "model": "*1", "target": "tgt_a"}]
        ents += [{"classname": "info_player_start", "origin": f"{300 + 100 * k} 1000 36"} for k in range(6)]
        ents += [{"classname": "info_player_deathmatch", "origin": f"{300 + 100 * k} 200 36", "angle": "90"} for k in range(6)]
        write_bsp(p, [room, trig_a, trig_b], [("aaatrigger", (16, 16)), ("-0csSandWall", (128, 240)), ("-0Sand", (128, 128))],
                  ents)
        msg = st.empty_map()
        assert not st.opt.meshes and not st.opt.props and not crop.read_block(st.opt).boxes
        assert not hmcopy.unique_faces(st.heightmap_edit())
        assert [r.clean_name.lower() for r in st.scene.modules] == ["mp_camerastartposition"]
        msg = st.import_bsp(p, (0.0, 0.0, 0.0), 0.0, 2.54, None, None, True, True, mode="DO", per_team=4)
        assert "team 0: 4, team 1: 4" in msg and st.game_mode() == "DO"
        zones = {str(r.object_name).rstrip("\0"): r for r in st.scene.modules if r.clean_name.lower() == "mp_bombzone"}
        assert set(zones) == {"bombZone", "bombZone_B"}
        a = np.asarray(zones["bombZone"].parsed.transform)[3, :3]
        assert abs(a[0] - (328 * 2.54 - 1024 * 2.54)) < 1.0                 # A (tgt_a) is the one at CS x 200..456
        # the CTs had no direction in the map: they look at the middle of the map
        cts = [r.parsed for r in st.scene.modules if r.clean_name.lower() == "mp_cstartpoint" and r.parsed.team == 0]
        for s in cts:
            to_mid = -np.asarray(s.position)[[0, 2]]
            assert np.dot([math.sin(s.angle), math.cos(s.angle)], to_mid) > 0
        assert st.validate_map is not None
        m = st.fresh_sectors(1500.0)
        blk = crop.read_block(st.opt)
        leaves = [s for s in blk.sectors if s.tail == 0]
        d = round(math.log(len(leaves), 4))                    # a full quadtree (it reaches the intro camera too)
        assert len(leaves) == 4 ** d and len(blk.sectors) == sum(4 ** k for k in range(d + 1))
        listed = {i for s in leaves for i in s.objs}
        assert listed == set(range(len(st.opt.meshes)))
        assert {i for s in leaves for i in s.boxes} == set(range(len(blk.boxes)))
        st.save_map(); st.save_scene()
        st.load(st.scene_name)
        assert len(crop.read_block(st.opt).sectors) == len(blk.sectors)


def test_walk_bumps_into_cars_and_scene_objects():
    """The game makes cars, doors and scene objects solid by their model: the walking test does too."""
    with tempfile.TemporaryDirectory() as tmp:
        st = _st(tmp, "mp_dm_vertigo.scn")
        key, boxes = st.module_solids()
        assert boxes and st.module_solids()[1] is boxes                   # cached while nothing moves
        w = st.walk_world()
        car = next(r for r in st.scene.modules if r.clean_name.lower() == "mp_ccar")
        p = np.asarray(car.parsed.transform, np.float64)[3, :3]
        ground = [y for y in w.levels_at(p[0], p[2], box_tops=False) if y <= p[1] + 50][0]
        assert w.blocked(p[0], p[2], ground, 25.0, 175.0, 45.0)
        assert w.levels_at(p[0], p[2])[0] > ground + 80.0                 # its roof can be stood on
        # moved away: the box goes with it (new world)
        M = np.asarray(car.parsed.transform, np.float64).copy()
        M[3, 0] += 100000.0
        car.parsed.transform = M.astype(np.float32)
        w2 = st.walk_world()
        assert w2 is not w and not w2.blocked(p[0], p[2], ground, 25.0, 175.0, 45.0) or \
            any(o is not car and np.linalg.norm(np.asarray(o.parsed.transform)[3, [0, 2]] - p[[0, 2]]) < 400
                for o in st.scene.modules if o.clean_name.lower() == "mp_ccar")


def _pool_bsp(path):
    """A room with a pool of water (func_water, see-through), a door (func_door_rotating, built round its origin) and a
    banner you walk through (func_illusionary); 2 + 2 player starts."""
    room = []
    for pts, n in _box_faces((0, 0, 0), (2048, 2048, 256)):
        room.append((pts[::-1].copy(), -n, 1))
    room = [(q, n, 2 if n[2] > 0.5 else t) for q, n, t in room if n[2] > -0.5]
    water = [(q, n, 3) for q, n in _box_faces((800, 800, -64), (1200, 1200, -8))]
    door = [(q, n, 1) for q, n in _box_faces((0, -60, -36), (4, 0, 44))]
    banner = [(q, n, 4) for q, n in _box_faces((300, 1500, 40), (304, 1600, 140))]
    write_bsp(path, [room, water, door, banner],
              [("aaatrigger", (16, 16)), ("-0csSandWall", (128, 240)), ("-0Sand", (128, 128)), ("bluewater", (64, 64)),
               ("poolrules", (64, 64))],
              [{"classname": "worldspawn"},
               {"classname": "func_water", "model": "*1", "rendermode": "2", "renderamt": "190"},
               {"classname": "func_door_rotating", "model": "*2", "origin": "500 500 44"},
               {"classname": "func_illusionary", "model": "*3"},
               {"classname": "info_player_start", "origin": "300 300 36"},
               {"classname": "info_player_start", "origin": "400 300 36"},
               {"classname": "info_player_deathmatch", "origin": "300 1800 36"},
               {"classname": "info_player_deathmatch", "origin": "400 1800 36"}])


def test_bsp_water_doors_and_see_through():
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "pool.bsp")
        _pool_bsp(p)
        b = BspMap.load(p)
        assert bspimport.translucent_textures(b) == {"bluewater": 190}
        pl = bspimport.plan(b, (0.0, 0.0, 0.0), 0.0)
        cv = bspimport.convert(b, pl, {"bluewater": "agua.tex", "poolrules": "cartel.tex"}, exists=lambda t: True)
        assert "agua.tex" in cv.meshes and len(cv.meshes["agua.tex"]) == 1           # the water's top is drawn ...
        assert "cartel.tex" in cv.meshes                                             # ... the banner too
        n_room = 5
        assert len(cv.boxes) == n_room                         # no box for the water, the banner or the (left out) door
        assert len(cv.hm_faces) == n_room + 1                  # the room + the water's top (a floor: nobody swims)
        drawn = sum(len(v) for v in cv.meshes.values())
        assert drawn == n_room + 1 + 6                         # room, water's top, banner: the door is not there (an open way)


def test_spread_start_points_over_the_floor():
    with tempfile.TemporaryDirectory() as tmp:
        st = _st(tmp, "mp_dm_almacen.scn")
        p = os.path.join(tmp, "pool.bsp")
        _pool_bsp(p)
        sp = np.array(next(q for lst in st.spawn_positions().values() for _n, q in lst), np.float64)
        at = (sp[0] + 30000.0, 0.0, sp[2])
        msg = st.import_bsp(p, at, 0.0, 2.54, None, None, True, True, mode="DM")
        assert st.game_mode() == "DM"
        # only the new start points: the old ones of the map are elsewhere
        for r in [r for r in st.scene.modules if r.clean_name.lower() == "mp_cstartpoint"]:
            if abs(r.parsed.position[0] - at[0]) > 4000:
                st.scene.modules.remove(r)
        msg = st.spread_spawns(12, avoid=st.last_bsp_water)
        assert msg.startswith("12 start points")
        w = st.walk_world()
        P = [np.asarray(r.parsed.position) for r in st.scene.modules if r.clean_name.lower() == "mp_cstartpoint"]
        assert len(P) == 12
        (wlo, whi), = st.last_bsp_water
        for q in P:
            assert any(abs(q[1] - 20.0 - y) < 3.0 for y in w.levels_at(q[0], q[2], box_tops=False))   # on the floor
            assert not (wlo[0] - 30 <= q[0] <= whi[0] + 30 and wlo[2] - 30 <= q[2] <= whi[2] + 30)   # not on the pool
        gaps = [np.linalg.norm((a - b)[[0, 2]]) for i, a in enumerate(P) for b in P[i + 1:]]
        assert min(gaps) > 600.0                                   # far apart in a 52 x 52 m room
        assert {r.parsed.team for r in st.scene.modules if r.clean_name.lower() == "mp_cstartpoint"} == {0, 1}
        assert not st.spawn_report(sight=False)


def test_pools_are_holes():
    """water='hole': the water's surface is drawn with the sea of the Love Boat (not solid), nothing holds a player in the
    pool: no floor inside its rectangle below its top."""
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "pool.bsp")
        _pool_bsp(p)
        b = BspMap.load(p)
        pl = bspimport.plan(b, (0.0, 0.0, 0.0), 0.0)
        cv = bspimport.convert(b, pl, {"bluewater": "agua.tex"}, exists=lambda t: True, water="hole")
        water = cv.meshes.get("agua.tex", [])                                     # the surface only, seen from above
        assert water and all(n[1] > 0.7 for _p, n, _uv in water)
        # the room's floor (z = 0, under the pool's top at -8? no: the pool goes down from -8 to -64, the floor at 0)
        # is above the water's top, so it is kept whole; nothing walkable inside the pool's rectangle below its top
        a, bb = b.models[1]
        for q, n in cv.hm_faces:
            cs = q / 2.54
        lo = pl.point(np.array([a[0] + 10, a[1] + 10, a[2]]))
        hi = pl.point(np.array([bb[0] - 10, bb[1] - 10, bb[2]]))
        for q, n in cv.hm_faces:
            if n[1] > 0.7 and q[:, 1].max() <= hi[1] + 1:
                inside = (q[:, 0].min() >= min(lo[0], hi[0]) and q[:, 0].max() <= max(lo[0], hi[0]) and
                          q[:, 2].min() >= min(lo[2], hi[2]) and q[:, 2].max() <= max(lo[2], hi[2]))
                assert not inside


def test_cut_rect_keeps_the_rest_of_the_floor():
    from vtoy.bsp import BspFace
    f = BspFace(np.array([[0, 0, 0], [100, 0, 0], [100, 100, 0], [0, 100, 0]], float), np.array([0, 0, 1.0]), "t",
                np.array([[0, 0], [1, 0], [1, 1], [0, 1]], float), 0)
    pieces = bspimport._cut_rect(f, np.array([40, 40, -50.0]), np.array([60, 60, 0.0]))
    area = lambda q: 0.5 * abs(sum(q[i, 0] * q[(i + 1) % len(q), 1] - q[(i + 1) % len(q), 0] * q[i, 1] for i in range(len(q))))
    assert len(pieces) == 4 and abs(sum(area(g.points) for g in pieces) - 9600.0) < 1e-6
    for g in pieces:                                              # texture coordinates follow the cut
        assert np.allclose(g.uv, g.points[:, :2] / 100.0)


def test_black_materials_and_blank_map():
    from vtoy.opt import STOCK_MATERIAL
    with tempfile.TemporaryDirectory() as tmp:
        st = _st(tmp, "mp_dm_almacen.scn")
        st.empty_map()
        st.add_shape("box", (200.0, 200.0, 200.0), (0.0, 0.0, 0.0), 0.0, "tablones.tex", 128.0, True)
        assert st.opt.meshes[0].materials[0].uv_map == STOCK_MATERIAL         # never a block of zeros (black in game)
        st.opt.meshes[0].materials[0].uv_map = b"\0" * 64
        assert st.black_materials() == [(0, 0)]
        assert any("draws them black" in v["msg"] for v in st.validate_map())
        st.fix_black_materials()
        assert not st.black_materials()
        for mode, shape in (("DMT", "rectangle"), ("B", "L"), ("DM", "circle")):
            msg = st.new_blank_map(f"mp_x_{mode.lower()}", mode, shape, 4000.0, 3000.0, 350.0, 40.0, "SUELOS_03.tex",
                                   "muro_liso.tex", 8)
            assert "saved" in msg and st.game_mode() == mode
            assert not st.black_materials()
            sp = [r for r in st.scene.modules if r.clean_name.lower() == "mp_cstartpoint"]
            assert len(sp) == 16
            if mode != "DM":
                assert sorted(r.parsed.team for r in sp) == [0] * 8 + [1] * 8
            assert not st.spawn_report(sight=False)
            msgs = [v["msg"] for v in st.validate_map()]
            assert msgs == ["no problems found"] or not any(v["level"] == "error" for v in st.validate_map()), msgs
            # walls: nobody walks out
            w = st.walk_world()
            p = np.asarray(sp[0].parsed.position)
            walker = st.start_walk(p - [0, 20.0, 0])
            for _ in range(600):
                walker.update(1 / 30, 1.0, 0.0)
            assert w.floor_at(walker.pos[0], walker.pos[2], walker.pos[1] + 10) is not None and walker.fell == 0
            assert st.scene_name in st.scene_names()


def test_fixed_weapon_keeps_its_own_ammunition():
    """A weapon fixed by the map gets ITS rounds (the DLL's own table: cetme 120 = 3 magazines), not those of the weapon
    the player chose in the menu (uzi 210), when created and when born again; groups not fixed are the game's code."""
    from vtoy import dllpatch
    src = os.path.join(os.path.dirname(os.environ.get("VTOY_FLAG_DLL", "")), "ctf.dll")
    if not os.path.isfile(src):
        return
    data = open(src, "rb").read()
    table = dllpatch.ammo_table(data)
    assert table[16] == 120 and table[6] == 210 and table[11] == 50 and table[14] == table[15]
    with tempfile.TemporaryDirectory() as tmp:
        a = os.path.join(tmp, "a.dll")
        dllpatch.patch_weapon_groups(src, a, [True] * 5, [0, 0, 16, 11, 14])
        d = open(a, "rb").read()
        assert dllpatch.weapon_ammo(d) == {2: 120, 3: 50, 4: table[14]}
        sites = dllpatch._table_sites(d)
        for g, w in ((2, 16), (3, 11), (4, 14)):                 # born again: the table looks up the fixed weapon
            assert 0xB8 <= d[sites[g][0]] <= 0xBF and struct.unpack_from("<I", d, sites[g][0] + 1)[0] == w
        # again with other weapons, and back to everybody's own choice: the game's bytes come back
        dllpatch.patch_weapon_groups(a, a, [True] * 5, [0, 0, 8, 9, 15])
        d = open(a, "rb").read()
        assert dllpatch.weapon_ammo(d) == {2: table[8], 3: table[9], 4: table[15]}
        b = os.path.join(tmp, "b.dll")
        dllpatch.patch_weapon_groups(src, b, [True] * 5)
        assert open(b, "rb").read() == data
        dllpatch.patch_weapon_groups(src, b, [True, True, True, False, True], [0, 0, 6, 0, 0])
        d = open(b, "rb").read()
        assert dllpatch.weapon_ammo(d) == {2: 210} and dllpatch.weapon_groups(d) == [True, True, True, False, True]


def test_no_box_over_a_ramp_and_a_floor_under_holes():
    """A ramp of the .bsp gets no collision box (a box turned only about the vertical would be an invisible wall over
    it; the height map's face is its collision), and under a pool-hole there is a floor far down (the game only lets a
    player fall onto a floor: without it he walks over the hole)."""
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "ramp.bsp")
        room = []
        for pts, n in _box_faces((0, 0, 0), (2048, 2048, 256)):
            room.append((pts[::-1].copy(), -n, 1))
        room = [(q, n, 2 if n[2] > 0.5 else t) for q, n, t in room if n[2] > -0.5]
        ramp = np.array([(800, 800, 0), (1200, 800, 0), (1200, 1200, 128), (800, 1200, 128)], float)
        rn = np.cross(ramp[1] - ramp[0], ramp[2] - ramp[0]); rn /= np.linalg.norm(rn)
        write_bsp(p, [room + [(ramp, rn, 2)]], [("aaatrigger", (16, 16)), ("-0csSandWall", (128, 240)),
                                                ("-0Sand", (128, 128))], [{"classname": "worldspawn"}])
        b = BspMap.load(p)
        cv = bspimport.convert(b, bspimport.plan(b, (0.0, 0.0, 0.0), 0.0), exists=lambda t: True)
        assert len(cv.boxes) == 5 and len(cv.hm_faces) == 6           # the ramp: a height map face, no box
        q = os.path.join(tmp, "pool.bsp")
        _pool_bsp(q)
        b = BspMap.load(q)
        pl = bspimport.plan(b, (0.0, 0.0, 0.0), 0.0)
        cv = bspimport.convert(b, pl, exists=lambda t: True, water="hole")
        low = [f for f, n in cv.hm_faces if f[:, 1].max() < -bspimport.KILL_DROP + 500]
        assert len(low) == 1 and np.allclose(np.ptp(low[0][:, [0, 2]], 0), (400 * 2.54, 400 * 2.54))


def test_any_wad_texture_by_name():
    """A texture of a .wad named in the importer's table (to draw a CS texture the .wad does not have) becomes a new
    game texture; unknown names are left out."""
    with tempfile.TemporaryDirectory() as tmp:
        st = _st(tmp, "mp_dm_almacen.scn", own_texs=True)
        pal = bytes(v for i in range(256) for v in (i, 255 - i, 7))
        p = os.path.join(tmp, "t.wad")
        _write_wad(p, [("out_snd1", 32, 16, bytes((x + y) % 256 for y in range(16) for x in range(32)), pal)])
        got = st.wad_textures(["out_snd1", "OUT_SND1.tex", "nope"], [p])
        assert set(got) == {"out_snd1", "OUT_SND1.tex"} and st.fs.texture(got["out_snd1"]) is not None
        t = st.fs.texture(got["out_snd1"])
        assert (t.width, t.height) == (32, 16)


def _hull_bsp(nodes, mins=(0, 0, 0), maxs=(200, 200, 200)):
    """A .bsp holding only a clip hull (planes, clipnodes, one model): nodes = [(normal, d, front child, back child)]."""
    planes = b"".join(struct.pack("<4fi", *n, d, 0) for n, d, f, b in nodes)
    clip = b"".join(struct.pack("<ihh", i, f, b) for i, (n, d, f, b) in enumerate(nodes))
    model = struct.pack("<9f4i3i", *mins, *maxs, 0, 0, 0, 0, 0, -1, -1, 0, 0, 0)
    lumps = [b""] * 15
    lumps[1], lumps[9], lumps[14] = planes, clip, model
    off, head, body = 4 + 15 * 8, struct.pack("<i", 30), b""
    for L in lumps:
        head += struct.pack("<ii", off + len(body), len(L))
        body += L
    return head + body


def test_clip_hull_walls_are_the_real_surfaces():
    """The clip hull (the solid grown by the player's box) gives back the surfaces at their real place: a room 200
    units and a block 64 high in it come out with the floor at 0, the block's top at 64, its side from the floor up to
    64 and the room's walls from floor to ceiling."""
    from vtoy import bsphull
    X, Y, Z, S, E = (1, 0, 0), (0, 1, 0), (0, 0, 1), -2, -1
    data = _hull_bsp([(X, 16, 1, S), (X, 184, S, 2), (Y, 16, 3, S), (Y, 184, S, 4), (Z, 164, S, 5), (Z, 36, 6, S),
                      (Z, 100, E, 7), (X, 84, S, E)])                 # block x >= 100, z < 64, grown by 16 / 36
    got = [(np.round(q.min(0), 3), np.round(q.max(0), 3), tuple(np.round(n).astype(int))) for q, n in bsphull.walls(data)]

    def has(lo, hi, n):
        return any(np.allclose(a, lo) and np.allclose(b, hi) and m == n for a, b, m in got)
    assert has((0, 0, 0), (100, 200, 0), (0, 0, 1))                    # floor up to the block
    assert has((100, 0, 64), (200, 200, 64), (0, 0, 1))                # top of the block
    assert has((100, 0, 0), (100, 200, 64), (-1, 0, 0))                # side of the block, from the floor up
    assert has((0, 0, 200), (200, 200, 200), (0, 0, -1))               # ceiling
    walls = [g for g in got if g[2] == (1, 0, 0)]                      # the wall at x = 0 reaches floor and ceiling
    assert min(a[2] for a, b, n in walls) == 0 and max(b[2] for a, b, n in walls) == 200
    assert all(a[1] == 0 and b[1] == 200 for a, b, n in walls)


def test_clip_hull_floor_along_a_wall_that_ends():
    """A floor running along a block that ends half way reaches the block where the block is and goes on beside it:
    no strip of floor missing at the block's foot (where a player or a health pack would fall through)."""
    from vtoy import bsphull
    X, Y, Z, S, E = (1, 0, 0), (0, 1, 0), (0, 0, 1), -2, -1
    data = _hull_bsp([(X, 16, 1, S), (X, 184, S, 2), (Y, 16, 3, S), (Y, 184, S, 4), (Z, 164, S, 5), (Z, 36, 6, S),
                      (Z, 100, E, 7), (X, 84, 8, E), (Y, 116, E, S)])  # block x >= 100, y < 100, z < 64
    floors = [q for q, n in bsphull.walls(data) if n[2] > 0.9 and abs(q[0, 2]) < 1e-6]

    def covered(x, y):
        for q in floors:
            s = [np.cross(q[(i + 1) % len(q)] - q[i], np.array([x, y, 0.0]) - q[i])[2] for i in range(len(q))]
            if min(s) >= -1e-6 or max(s) <= 1e-6:
                return True
        return False
    for x, y in [(5, 5), (99, 50), (99, 150), (150, 105), (150, 195), (195, 150), (50, 195)]:
        assert covered(x, y), (x, y)
    assert not covered(150, 50)                                        # under the block: no floor


def test_clip_hull_hole_corners():
    """A hole in the floor (a pool 100 x 100 in a room 200 x 200): the floor round it ends at the hole's edges and
    corners - the grown hull's box-sized squares at the corners are not left over the hole."""
    from vtoy import bsphull
    X, Y, Z, S, E = (1, 0, 0), (0, 1, 0), (0, 0, 1), -2, -1
    # floor at z 0 (grown: 36); hole x 50..150, y 50..150 down to z -100 (grown: 66..134, -64)
    data = _hull_bsp([(X, 16, 1, S), (X, 184, S, 2), (Y, 16, 3, S), (Y, 184, S, 4), (Z, 164, S, 5), (Z, -64, 6, S),
                      (Z, 36, E, 7), (X, 66, 8, S), (X, 134, S, 9), (Y, 66, 10, S), (Y, 134, S, E)],
                     mins=(0, 0, -100), maxs=(200, 200, 200))
    floors = [q for q, n in bsphull.walls(data) if n[2] > 0.9 and abs(q[0, 2]) < 1e-6]

    def covered(x, y):
        for q in floors:
            s = [np.cross(q[(i + 1) % len(q)] - q[i], np.array([x, y, 0.0]) - q[i])[2] for i in range(len(q))]
            if min(s) >= -1e-6 or max(s) <= 1e-6:
                return True
        return False
    for x, y in [(49, 49), (49, 151), (151, 49), (151, 151), (100, 45), (45, 100), (5, 5), (195, 195)]:
        assert covered(x, y), (x, y)
    for x, y in [(52, 52), (148, 148), (52, 148), (148, 52), (100, 100), (100, 55)]:
        assert not covered(x, y), (x, y)
