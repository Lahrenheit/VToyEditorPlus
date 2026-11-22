"""Batch 14: Hammer maps (.rmf), a new map from a CS map, the bomb's time and overtime, several weapons per group."""
import os, shutil, struct, tempfile
import _path
import numpy as np
import pytest
from vtoy import dllpatch, rmf


def _nstr(s):
    b = s.encode("latin-1") + b"\0"
    return bytes([len(b)]) + b


def _rmf_face(tex, pts, n):
    """A face of an .rmf brush: its corners (wound clockwise seen from outside, like Hammer) and texture axes."""
    a = np.array([1.0, 0, 0]) if abs(n[0]) < 0.9 else np.array([0, 1.0, 0])
    u = np.cross(n, a)
    u /= np.linalg.norm(u)
    v = np.cross(n, u)
    out = tex.encode().ljust(256, b"\0") + struct.pack("<f", 0.0)
    out += struct.pack("<4f", *u, 0.0) + struct.pack("<4f", *v, 0.0) + struct.pack("<3f", 0.0, 1.0, 1.0) + b"\0" * 16
    out += struct.pack("<i", len(pts)) + b"".join(struct.pack("<3f", *p) for p in pts)
    out += b"".join(struct.pack("<3f", *p) for p in pts[:3])
    return out


def _rmf_box(lo, hi, tex="SANDWALL", top=None):
    from test_batch13 import _box_faces
    faces = []
    for pts, n in _box_faces(lo, hi):
        t = top if (top and n[2] > 0.5) else tex
        faces.append(_rmf_face(t, pts[::-1], n))                     # Hammer winds them the other way round
    return _nstr("CMapSolid") + struct.pack("<i3Bi", 0, 255, 255, 255, 0) + struct.pack("<i", len(faces)) + b"".join(faces)


def _rmf_entity(kv, origin=(0, 0, 0), solids=()):
    out = _nstr("CMapEntity") + struct.pack("<i3B", 0, 255, 255, 255) + struct.pack("<i", len(solids)) + b"".join(solids)
    out += _nstr(kv["classname"]) + b"\0" * 4 + struct.pack("<ii", 0, len(kv) - 1)
    for k, v in kv.items():
        if k != "classname":
            out += _nstr(k) + _nstr(v)
    out += b"\0" * 14 + struct.pack("<3f", *origin) + b"\0" * 4
    return out


def write_rmf(path, objects, world=None):
    w = dict(world or {"classname": "worldspawn"})
    data = struct.pack("<f", 2.2) + b"RMF" + struct.pack("<i", 0)
    data += _nstr("CMapWorld") + struct.pack("<i3B", 0, 255, 255, 255) + struct.pack("<i", len(objects)) + b"".join(objects)
    data += _nstr(w["classname"]) + b"\0" * 4 + struct.pack("<ii", 0, len(w) - 1)
    for k, v in w.items():
        if k != "classname":
            data += _nstr(k) + _nstr(v)
    data += b"\0" * 12 + struct.pack("<i", 0)
    open(path, "wb").write(data)


def _arena(path):
    """A floor 1024 x 1024, a crate standing on it, a CLIP ramp-block, a HINT brush (not solid), a func_wall, a buy zone
    and two starts of each team."""
    objs = [_rmf_box((0, 0, -16), (1024, 1024, 0), "SANDFLOOR"),
            _rmf_box((400, 400, 0), (464, 464, 64), "CRATE"),
            _rmf_box((700, 100, 0), (800, 200, 40), "CLIP"),
            _rmf_box((0, 0, 0), (1024, 1024, 128), "HINT"),
            _rmf_entity({"classname": "func_wall"}, solids=[_rmf_box((100, 800, 0), (200, 832, 96), "FENCE")]),
            _rmf_entity({"classname": "func_buyzone"}, solids=[_rmf_box((0, 0, 0), (200, 200, 64), "AAATRIGGER")]),
            _rmf_entity({"classname": "info_player_start", "angles": "0 90 0"}, (100, 100, 36)),
            _rmf_entity({"classname": "info_player_start", "angles": "0 90 0"}, (160, 100, 36)),
            _rmf_entity({"classname": "info_player_deathmatch", "angles": "0 270 0"}, (900, 900, 36)),
            _rmf_entity({"classname": "info_player_deathmatch", "angles": "0 270 0"}, (840, 900, 36))]
    write_rmf(path, objs)


def test_rmf_read_and_solid_faces():
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "arena.rmf")
        _arena(p)
        rm = rmf.RmfMap.load(p)
        assert len(rm.solids) == 6 and len(rm.entities) == 6
        assert {e["classname"] for e in rm.entities} >= {"func_wall", "info_player_start", "info_player_deathmatch"}
        assert next(e for e in rm.entities if e["classname"] == "info_player_deathmatch")["origin"] == "900 900 36"
        for s in rm.solids:                                     # every face looks out of its brush
            c = np.concatenate([f.points for f in s.faces]).mean(0)
            assert all(float(f.normal @ (f.points.mean(0) - c)) > 0 for f in s.faces)
        b = rmf.to_bsp_like(rm)
        tex = {f.texture for f in b.faces}
        assert tex == {"SANDFLOOR", "CRATE", "FENCE"}            # no CLIP, HINT, AAATRIGGER drawn
        assert not any(f.texture == "CRATE" and f.normal[2] < -0.5 for f in b.faces)   # its bottom is on the floor: hidden
        # the floor's top: drawn round the crate, not under it
        tops = [f.points for f in b.faces if f.texture == "SANDFLOOR" and f.normal[2] > 0.5]
        area = sum(0.5 * np.linalg.norm(sum(np.cross(q[k] - q[0], q[k + 1] - q[0]) for k in range(1, len(q) - 1)))
                   for q in tops)
        assert abs(area - (1024 * 1024 - 64 * 64)) < 1.0
        w = b.solid_faces[0]                                     # the world's outside: the CLIP block is solid ...
        assert any(abs(q[:, 2].max() - 40) < 1e-3 and n[2] > 0.5 for q, n in w)
        assert not any(abs(q[:, 2].max() - 128) < 1e-3 and n[2] > 0.5 for q, n in w)   # ... the HINT one is not
        assert len(b.solid_faces) == 2                           # the world and the func_wall (not the buy zone)
        assert b.entities[0]["classname"] == "worldspawn"
        fw = next(e for e in b.entities if e.get("classname") == "func_wall")
        assert fw["model"] == "*1" and "origin" not in fw


def test_rmf_import_into_a_new_map():
    from test_batch7 import _st
    from vtoy import bspimport
    with tempfile.TemporaryDirectory() as tmp:
        st = _st(tmp, own_texs=True)
        p = os.path.join(tmp, "arena.rmf")
        _arena(p)
        rep = st.cs_wad_report(p, [])
        assert rep["textures"] == 3 and len(rep["missing"]) == 3 and rep["listed"] == []
        b = st.cs_map(p)
        pl = bspimport.plan(b, (0.0, 0.0, 0.0), 0.0, 2.54)
        cv = bspimport.convert(b, pl, None, None, lambda n: True, True)
        assert len(cv.spawns) == 4 and {t for _p, _a, t in cv.spawns} == {0, 1}
        ys = {round(float(np.mean(q[:, 1])), 1) for q, n in cv.hm_faces if n[1] > 0.7}
        f0 = 16 * 2.54                                           # the map is laid on the bottom of its floor slab
        assert {round(f0, 1), round(f0 + 64 * 2.54, 1), round(f0 + 40 * 2.54, 1)} <= ys   # floor, crate, clip block
        assert round(f0 + 128 * 2.54, 1) not in ys               # the hint brush is nothing
        # a whole new map from it: its own scene / map, the starts of both teams, health packs, saved
        msg = st.new_map_from_cs(p, "mp_dmt_arena", "DMT", [], 2)
        assert "mp_dmt_arena" in msg
        assert st.scene_name.lower() == "mp_dmt_arena.scn"
        assert os.path.isfile(os.path.join(st.fs.root, "scns", "mp_dmt_arena.scn"))
        sp = [r for r in st.scene.modules if r.clean_name.lower() == "mp_cstartpoint"]
        assert sorted(int(r.parsed.team) for r in sp) == [0, 0, 1, 1]
        assert sum(1 for r in st.scene.modules if r.clean_name.lower() == "mp_salud") == 6
        for r in sp:                                             # on the floor
            x, y, z = (float(v) for v in r.parsed.position)
            assert abs(y - (16 * 2.54 + 20.0)) < 1.0


def _dll(name):
    src = os.path.join(os.path.dirname(os.environ.get("VTOY_FLAG_DLL", "")), name)
    if not os.path.isfile(src):
        pytest.skip(f"{name} of the game not available")
    return src


def test_bomb_fuse_and_overtime():
    """The bomb's time and the overtime live in the map's copy of the DO mode DLL (the planted bomb is made by the
    game's bomb weapon from the game's own mp_bomba.dll): two hooks - the scene's Run moves the planting time of each
    ticking bomb of the scene's bomb list once; "__timeout__" keeps the round going while one ticks."""
    dtt = _dll("dtt.dll")
    with tempfile.TemporaryDirectory() as tmp:
        stock = open(dtt, "rb").read()
        assert dllpatch.can_have_bomb_rules(stock) and dllpatch.bomb_rules(stock) is None
        assert dllpatch.bomb_fuse(stock) == 20.0
        pe = dllpatch._PE(bytearray(stock))
        h, r = dllpatch._hook_sites(stock, pe)
        c = os.path.join(tmp, "c.dll")
        dllpatch.patch_second_bomb_zone(dtt, c)
        assert dllpatch.patch_bomb_rules(c, c, 40, True) == (40.0, True)
        d = open(c, "rb").read()
        assert dllpatch.bomb_rules(d) == (40.0, True) and dllpatch.second_bomb_zone(d) == "bombZone_B"
        for at in (h, r):                                         # both hooks: jmp into the new code / nop
            assert d[at] == 0xE9 and d[at + 5] == 0x90
        i = d.find(dllpatch._OT_TAG)
        cave = struct.unpack_from("<I", d, i - 4)[0]
        code = d[cave:i]
        assert struct.pack("<ffff", 20000.0, 20000.0, 0.001, 0.05) in code        # +20 s, the game's fuse, ms->s
        assert b"\x8b\x91\x04\x01\x00\x00\x8b\xb9\xfc\x00\x00\x00" in code   # the scene's bomb list (count, array)
        assert b"\x83\xb8\xb0\x01\x00\x00\x01" in code                          # cmp [bomb+0x1B0],1: ticking
        # the jumps back land on the line after the hooks
        for at in (h, r):
            tgt = at + 5 + struct.unpack_from("<i", d, at + 1)[0]
            k = tgt - cave
            j = code.find(dllpatch._FS0 + b"\xe9", k)
            back = cave + j + 6 + 5 + struct.unpack_from("<i", code, j + 7)[0]
            assert back == at + 6
        # changed again, then back to the game's behaviour (the second zone stays)
        e = os.path.join(tmp, "e.dll")
        dllpatch.patch_bomb_rules(dtt, e, 30, False)
        dllpatch.patch_second_bomb_zone(e, e, "zonaB")
        d = open(e, "rb").read()
        assert dllpatch.bomb_rules(d) == (30.0, False) and dllpatch.second_bomb_zone(d) == "zonaB"
        dllpatch.patch_bomb_rules(e, e, 20, False)
        d = open(e, "rb").read()
        assert dllpatch.bomb_rules(d) is None and dllpatch.second_bomb_zone(d) == "zonaB"
        assert d[h:h + 6] == dllpatch._FS0 and d[r:r + 6] == dllpatch._FS0     # the game's lines again
        with pytest.raises(ValueError):
            dllpatch.patch_bomb_rules(dtt, e, 2, False)
        assert not dllpatch.can_have_bomb_rules(open(_dll("ctf.dll"), "rb").read())


def test_several_weapons_per_group():
    ctf = _dll("ctf.dll")
    with tempfile.TemporaryDirectory() as tmp:
        a = os.path.join(tmp, "a.dll")
        assert dllpatch.patch_weapon_groups(ctf, a, [True] * 5, [0, 0, [16, 8], [9, 11, 12], 0]) == [True] * 5
        d = open(a, "rb").read()
        assert dllpatch.weapon_sets(d) == [None, None, [16, 8], [9, 11, 12], None]
        assert dllpatch.weapon_choice(d) == [0] * 5
        # the original loads are kept in the copy: a new choice is made from it as from the game's own DLL
        stock = open(ctf, "rb").read()
        view = dllpatch._stock_view(d)
        diff = [i for i in range(len(view)) if view[i] != stock[i]]
        pe = dllpatch._PE(bytearray(stock))
        text = next(s for s in pe.secs if s["name"] == b".text")
        assert all(text["hdr"] <= i < text["hdr"] + 40 for i in diff)       # only the size of .text
        b = os.path.join(tmp, "b.dll")
        dllpatch.patch_weapon_groups(a, b, [True, True, True, False, True], [0, 0, [7], 0, [14, 15]])
        d = open(b, "rb").read()
        assert dllpatch.weapon_sets(d) == [None] * 5                 # one weapon = fixed; the whole group = all
        assert dllpatch.weapon_choice(d) == [0, 0, 7, 0, 0]
        assert dllpatch.weapon_groups(d) == [True, True, True, False, True]
        # the check: for each read of the profile, a call to a stub that ends with the original 6-byte load
        s = dllpatch._weapon_sites(stock)
        o = s["create_id"][2]
        assert d[o] == 0xB8 + ((stock[o + 1] >> 3) & 7) and struct.unpack_from("<I", d, o + 1)[0] == 7   # fixed
        dllpatch.patch_weapon_groups(ctf, b, [True] * 5, [0, 0, [6, 16], 0, 0])
        d = open(b, "rb").read()
        assert d[o] == 0xE8 and d[o + 5] == 0x90
        tgt = o + 5 + struct.unpack_from("<i", d, o + 1)[0]
        assert d[tgt:tgt + 2] == b"\x9c\x50" and stock[o:o + 6] in d[tgt:tgt + 24]
        with pytest.raises(ValueError):
            dllpatch.patch_weapon_groups(ctf, b, [True] * 5, [0, 0, [9, 6], 0, 0])     # 9 is not of group 3


def test_rmf_outside_faces_left_out():
    """A sealed room (walls, a sky ceiling) whose floor brush runs on outside it: what faces the void is not drawn nor
    solid, like the CS compiler does; an open map (it leaks) keeps everything."""
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "room.rmf")
        objs = [_rmf_box((-16, -16, -16), (800, 528, 0), "FLOOR"),                # runs 270 units out of the room
                _rmf_box((-16, -16, 0), (0, 528, 256), "WALL"), _rmf_box((512, -16, 0), (528, 528, 256), "WALL"),
                _rmf_box((0, -16, 0), (512, 0, 256), "WALL"), _rmf_box((0, 512, 0), (512, 528, 256), "WALL"),
                _rmf_box((-16, -16, 256), (528, 528, 272), "SKY"),
                _rmf_entity({"classname": "info_player_start"}, (256, 256, 36))]
        write_rmf(p, objs)
        b = rmf.to_bsp_like(rmf.RmfMap.load(p))
        assert b.sealed
        assert all(f.points.mean(0)[0] < 520 for f in b.faces)              # nothing drawn out there
        assert all(q.mean(0)[0] < 520 for q, n in b.solid_faces[0])
        tops = [f for f in b.faces if f.texture == "FLOOR" and f.normal[2] > 0.5]
        assert tops and all(f.points[:, 0].max() <= 512.01 for f in tops)
        objs[1] = _rmf_box((-16, -16, 0), (0, 200, 256), "WALL")             # a hole in a wall: it leaks
        write_rmf(p, objs)
        b = rmf.to_bsp_like(rmf.RmfMap.load(p))
        assert not b.sealed and any(f.points.mean(0)[0] > 600 for f in b.faces)


def test_clip_hull_thin_board_cut_by_the_tree():
    """A board 3 units thick floating in a room, its hull cut in two by a plane of the tree: its sides still come out 3
    units high (the trim of one piece's far edge reaches into the other piece), not a wall over the board."""
    from test_batch13 import _hull_bsp
    from vtoy import bsphull
    X, Y, Z, S, E = (1, 0, 0), (0, 1, 0), (0, 0, 1), -2, -1
    data = _hull_bsp([(X, 16, 1, S), (X, 184, S, 2), (Y, 16, 3, S), (Y, 184, S, 4), (Z, 164, S, 5), (Z, 36, 6, S),
                      (X, 34, 7, E), (X, 166, E, 8), (Y, 64, 9, E), (Y, 136, E, 10), (Z, 80, 11, 12),
                      (Z, 139, E, S), (Z, 64, S, E)])                  # board x 50..150, y 80..120, z 100..103
    sides = [(q, n) for q, n in bsphull.walls(data) if abs(n[2]) < 0.1 and 40 < q[:, 0].mean() < 160
             and 70 < q[:, 1].mean() < 130]
    assert sides
    for q, n in sides:
        assert q[:, 2].min() > 99.9 and q[:, 2].max() < 103.1, (q[:, 2].min(), q[:, 2].max())
    top = [q for q, n in bsphull.walls(data) if n[2] > 0.9 and abs(q[0, 2] - 103) < 1e-3]
    assert top and abs(sum(0.5 * np.linalg.norm(sum(np.cross(t[k] - t[0], t[k + 1] - t[0]) for k in range(1, len(t) - 1)))
                           for t in top) - 100 * 40) < 1.0


def test_clip_hull_slope_grown_straight_up():
    """The CS compiler grows a floor or a slope a player stands on straight up by 36 (not along its normal): a ramp
    comes back at its real place, meeting the floor without a gap or a step."""
    from test_batch13 import _hull_bsp
    from vtoy import bsphull
    X, Y, Z, S, E = (1, 0, 0), (0, 1, 0), (0, 0, 1), -2, -1
    n = np.array([-0.5, 0.0, 1.0]) / np.linalg.norm([-0.5, 0.0, 1.0])     # real ramp z = 0.5 (x - 100), x > 100
    d = float(n @ np.array([100.0, 0.0, 36.0]))                          # its hull: the same plane 36 higher
    data = _hull_bsp([(X, 16, 1, S), (X, 184, S, 2), (Y, 16, 3, S), (Y, 184, S, 4), (Z, 164, S, 5),
                      (Z, 36, 6, S), (tuple(n), d, E, S)], maxs=(200, 200, 200))
    ws = bsphull.walls(data)
    floor = [q for q, m in ws if m[2] > 0.99 and abs(q[0, 2]) < 1e-3]
    ramp = [q for q, m in ws if 0.8 < m[2] < 0.95]
    assert floor and ramp
    assert abs(max(q[:, 0].max() for q in floor) - 100.0) < 1.5                 # the floor ends where the ramp starts
    r = ramp[0]
    assert abs(r[:, 0].min() - 100.0) < 0.6 and abs(r[:, 2].min()) < 0.3       # the ramp starts on the floor
    for p in r:
        assert abs(p[2] - 0.5 * (p[0] - 100.0)) < 0.3                         # and lies on the real slope


def test_steps_become_short_ramps():
    """A 33 cm step (a diving board on the deck) becomes a ramp where there is deck in front of it, stays a wall over
    the water; a low face hidden under a ramp running up to a landing goes."""
    from vtoy import bspimport
    up = np.array([0.0, 1.0, 0.0])
    deck = (np.array([[-300, 0, -200], [0, 0, -200], [0, 0, 200], [-300, 0, 200.0]]), up)
    board = (np.array([[-200, 33, -20], [200, 33, -20], [200, 33, 20], [-200, 33, 20.0]]), up)
    side = (np.array([[-200, 0, -20], [200, 0, -20], [200, 33, -20], [-200, 33, -20.0]]), np.array([0, 0, -1.0]))
    faces, made = bspimport.step_ramps([deck, board, side])
    ramps = [p for p, n in faces if 0.7 < n[1] < 0.99]
    walls = [p for p, n in faces if abs(n[1]) < 0.17]
    assert made == 1 and len(ramps) == 1
    r = ramps[0]
    assert r[:, 0].max() <= 10.0 and abs(r[:, 1].max() - 33) < 1e-6 and abs(r[:, 1].min()) < 1e-6   # over the deck only
    assert walls and all(w[:, 0].min() >= -1.0 for w in walls)                     # the part over the water stays
    # a ramp running up to a landing 3 cm higher whose low front face is under the ramp: the face goes
    ramp = (np.array([[0, 0, 0], [100, 0, 0], [100, 50, 100], [0, 50, 100.0]]), np.array([0, 0.89, -0.45]))
    land = (np.array([[0, 53, 100], [100, 53, 100], [100, 53, 200], [0, 53, 200.0]]), up)
    front = (np.array([[0, 23, 100], [100, 23, 100], [100, 53, 100], [0, 53, 100.0]]), np.array([0, 0, -1.0]))
    faces, made = bspimport.step_ramps([ramp, land, front])
    assert len(faces) == 2 and not any(abs(n[1]) < 0.17 for _p, n in faces)


def test_bomb_zones_any_or_all():
    """The DO DLL copy counts several bomb zones in a section of its own: any one destroyed wins (the game's way with
    one zone) or only all of them; the hooks jump into it and every address it uses is the right one."""
    dtt = _dll("dtt.dll")
    with tempfile.TemporaryDirectory() as tmp:
        a = os.path.join(tmp, "a.dll")
        assert dllpatch.patch_bomb_zones(dtt, a, ["bombZone_B", "bombZone_C"]) == (["bombZone_B", "bombZone_C"], False)
        d = open(a, "rb").read()
        assert dllpatch.bomb_zones(d) == (["bombZone_B", "bombZone_C"], False) and dllpatch.bomb_zones_hud(d)
        assert dllpatch.second_bomb_zone(d) == "bombZone_B"
        pe = dllpatch._PE(bytearray(d))
        sec = dllpatch._section(pe, b".vtoyz")
        base = pe.base + sec["va"]
        assert struct.unpack_from("<I", d, pe.pe + 24 + 56)[0] == sec["va"] + 0x2000      # SizeOfImage
        P = lambda o: base + struct.unpack_from("<i", d, sec["ro"] + 0x800 + o)[0]
        win, nowin, site, init = struct.unpack_from("<IIII", d, sec["ro"] + 0xF00)
        assert (P(0), P(4), P(8)) == (win, nowin, init + 12) and win == site + 14
        for o, f in ((0xc, b"?ObjectByName@@YAPBVCObject@@AAVCString@@@Z"), (0x10, b"?AddSprite@@YAHABVCString@@HHHHHMMMM@Z"),
                     (0x14, b"?SpriteSetVisible@@YAXH_N@Z"), (0x18, b"?ConvertPixelToRender@@YAXHHAAH0HH@Z")):
            assert P(o) == dllpatch._import_slot(d, pe, f)
        for o, f in ((0x4c, b"?mainCharacter@CGame@@0HA"), (0x50, b"?ActorGetPosition@@YAAAUvtVector@@H@Z"),
                     (0x54, b"?Distance2@@YAMABUvtVector@@0@Z"), (0x58, b"?SetTargetName@Radar@@QAEXHAAVCString@@@Z"),
                     (0x5c, b"?ClearTarget@Radar@@QAEXH@Z")):
            assert P(o) == dllpatch._import_slot(d, pe, f)
        assert dllpatch.bomb_zones_radar(d) and struct.unpack_from("<i", d, sec["ro"] + 0x848)[0] == 1
        t = P(0x1c) - pe.base
        assert d[t:t + 20] == b"armas_grupo_345.tex\0"
        for va, to in ((site, base), (init, base + dllpatch._BZ_INIT)):                  # the hooks
            o = va - pe.base
            assert d[o] == 0xE9 and va + 5 + struct.unpack_from("<i", d, o + 1)[0] == to
        assert d[sec["ro"]:sec["ro"] + len(dllpatch._BZ_CODE)] == dllpatch._BZ_CODE
        # all of them, the bomb's time on top, again and again: the copy keeps working
        dllpatch.patch_bomb_rules(a, a, 35, True)
        dllpatch.patch_bomb_zones(a, a, ["bombZone_B"], True, False)
        dllpatch.patch_bomb_rules(a, a, 20, False)
        dllpatch.patch_bomb_rules(a, a, 40, True)
        d = open(a, "rb").read()
        assert dllpatch.bomb_zones(d) == (["bombZone_B"], True) and not dllpatch.bomb_zones_hud(d)
        assert dllpatch.bomb_rules(d) == (40.0, True) and len(d) == os.path.getsize(dtt) + 0x2000
        assert d.count(b"VTOYBZ2\0") == 1
        with pytest.raises(ValueError):
            dllpatch.patch_bomb_zones(dtt, a, ["a", "b", "c", "d", "e"])
        with pytest.raises(ValueError):
            dllpatch.patch_bomb_zones(dtt, a, ["x", "X"])


def test_bomb_zones_code_runs():
    """The zones' code itself (tools/asm/bombzones.s), run natively as a 32-bit program with the game faked: any / all,
    a zone that has blown up stays destroyed (the bug: the game's flag only lasts while it explodes), the HUD icons."""
    import shutil
    import subprocess
    gcc = shutil.which("gcc")
    if not gcc:
        pytest.skip("no gcc")
    here = os.path.join(os.path.dirname(__file__), "..", "tools", "asm", "harness.c")
    with tempfile.TemporaryDirectory() as tmp:
        code = bytearray(dllpatch._BZ_CODE + bytes(0x7f0 - len(dllpatch._BZ_CODE))
                         + struct.pack("<III", dllpatch._BZ_INIT, len(dllpatch._BZ_CODE), dllpatch._BZ_DTOR))
        struct.pack_into("<II", code, 0x7e0, dllpatch._BZ_SPLASH, dllpatch._BZ_SPRET)
        code += bytes(0x1c00 - len(code)) + dllpatch._BZ_CODE2                    # fix_shower (shower.inc)
        open(os.path.join(tmp, "bzcode.h"), "w").write(
            "static const unsigned char CODE[]={" + ",".join(str(x) for x in code) + "};\n")
        shutil.copy(here, os.path.join(tmp, "harness.c"))
        exe = os.path.join(tmp, "h")
        r = subprocess.run([gcc, "-m32", "-nostdlib", "-static", "-ffreestanding", "-fno-pie", "-no-pie", "-O1",
                            "-fno-stack-protector", "-mno-sse", "-o", exe, os.path.join(tmp, "harness.c")],
                           capture_output=True, text=True)
        if r.returncode != 0:
            pytest.skip("no 32-bit gcc: " + r.stderr[-200:])
        r = subprocess.run([exe], capture_output=True, text=True, timeout=30)
        assert r.returncode == 0, r.stdout


def test_small_floor_holes_closed():
    """A notch with no floor at a step's corner (the player fell out of dust2 there) gets a floor at the lowest floor
    around it; a wide opening (a pit, a pool) stays open; a small hole in an upper floor over a lower one is closed."""
    from vtoy import bspimport
    up = np.array([0.0, 1.0, 0.0])

    def quad(x0, z0, x1, z1, y):
        return (np.array([[x0, y, z0], [x0, y, z1], [x1, y, z1], [x1, y, z0]], float), up.copy())

    faces = [quad(0, 0, 400, 200, 0.0),                        # the low floor
             quad(0, 230, 400, 400, 80.0),                     # the high floor: a 30 cm notch between them ...
             quad(0, 200, 170, 230, 0.0), quad(200, 200, 400, 230, 0.0),   # ... closed but for 30 x 30 cm
             quad(500, 0, 700, 100, 0.0), quad(500, 300, 700, 400, 0.0),   # a 2 m wide pit: stays
             quad(500, 100, 550, 300, 0.0), quad(650, 100, 700, 300, 0.0),
             quad(0, 500, 400, 800, 0.0),                      # an upper floor with a 20 cm hole over a lower one
             quad(0, 500, 400, 640, 300.0), quad(0, 660, 400, 800, 300.0),
             quad(0, 640, 190, 660, 300.0), quad(210, 640, 400, 660, 300.0)]
    out, made = bspimport.fill_floor_gaps(faces)
    assert made == 2
    fl = [(q, q.min(0), q.max(0)) for q, n in out if n[1] > 0.3]
    assert bspimport._floor_heights(fl, 185.3, 215.7, -1e3, 1e3) == [0.0]          # the notch: at the low floor
    assert not bspimport._floor_heights(fl, 600.3, 200.7, -1e3, 1e3)                # the pit: still open
    assert max(bspimport._floor_heights(fl, 200.3, 650.7, -1e3, 1e3)) == 300.0      # the upper hole: closed
    # every floor reaches a hair past its edges: a seam of 2 cm between two floors is no hole
    out, made = bspimport.fill_floor_gaps([quad(0, 0, 100, 100, 0.0), quad(102, 0, 200, 100, 0.0)])
    fl = [(q, q.min(0), q.max(0)) for q, n in out]
    assert bspimport._floor_heights(fl, 101.0, 50.3, -1e3, 1e3)


def test_steep_slope_box():
    """A slope too steep to walk in CS (a rock face) is a floor for the game: it gets a box from its foot to its top
    (the player bumps into it); a gentle one or a low one does not."""
    from vtoy import bspimport
    p = np.array([[0, 0, 0], [100, 0, 0], [100, 120, 80], [0, 120, 80]], float)      # 56 degrees, 1.2 m high
    n = np.cross(p[1] - p[0], p[3] - p[0])
    n = n / np.linalg.norm(n) * (1 if n[1] > 0 else -1)
    assert bspimport.GAME_FLOOR_NY <= n[1] < bspimport.STEEP_NY
    c, half, R = bspimport._slope_box(p, n)
    corners = np.array([c + R[0] * half[0] * a + R[1] * half[1] * b + R[2] * half[2] * d
                        for a in (-1, 1) for b in (-1, 1) for d in (-1, 1)])
    assert np.allclose(corners.min(0), [0, 0, 0], atol=1e-6) and np.allclose(corners.max(0), [100, 120, 80], atol=1e-6)
    assert np.allclose(R @ R.T, np.eye(3)) and np.linalg.det(R) > 0
    low = p.copy()
    low[2:, 1] = 30.0                                                                   # a 30 cm rise: stepped over
    assert bspimport._slope_box(low, n) is None
    assert bspimport.COLLISION_HULL == 3 and bspimport.HULL_HALF[3] == (16.0, 16.0, 18.0)


def test_new_map_failing_half_way_leaves_nothing():
    """A new map from a CS map that fails after the template was copied under the new name takes its files away again
    (the user saw a Madrid named mp_dmt_nuketown); and the importer needs no scipy."""
    import sys
    from test_batch7 import _st
    with tempfile.TemporaryDirectory() as tmp:
        st = _st(tmp, own_texs=True)
        p = os.path.join(tmp, "arena.rmf")
        _arena(p)

        def boom(*a, **k):
            raise RuntimeError("no module named 'something'")
        st.import_bsp = boom
        with pytest.raises(RuntimeError):
            st.new_map_from_cs(p, "mp_dmt_arena2", "DMT", [], 2)
        root = st.fs.root
        left = [f for d in ("scns", "nfos", "texs") for f in os.listdir(os.path.join(root, d)) if "arena2" in f.lower()]
        assert left == [] and st.scene_name.lower() != "mp_dmt_arena2.scn"
    saved = sys.modules.get("scipy")
    sys.modules["scipy"] = None                                  # as on a PC without scipy
    try:
        from vtoy import bspimport
        up = np.array([0.0, 1.0, 0.0])
        q = lambda x0, z0, x1, z1: (np.array([[x0, 0, z0], [x0, 0, z1], [x1, 0, z1], [x1, 0, z0]], float), up)
        faces = [q(0, 0, 300, 140), q(0, 160, 300, 300), q(0, 140, 140, 160), q(160, 140, 300, 160)]   # a 20 cm hole
        out, made = bspimport.fill_floor_gaps(faces)
        assert made == 1
    finally:
        if saved is None:
            del sys.modules["scipy"]
        else:
            sys.modules["scipy"] = saved


def test_ndi_like_scipy():
    """vtoy.ndi gives what scipy.ndimage gave (where scipy is there to compare)."""
    from vtoy import ndi
    rng = np.random.default_rng(3)
    for shape in ((40, 50), (12, 15, 18), (9,)):
        m = rng.random(shape) < 0.55
        a, n = ndi.label(m)
        assert set(np.unique(a[m]).tolist()) == set(range(1, n + 1)) and not a[~m].any()
        for k, sl in enumerate(ndi.find_objects(a, n), 1):
            idx = np.nonzero(a == k)
            assert all(s.start == c.min() and s.stop == c.max() + 1 for s, c in zip(sl, idx))
    try:
        from scipy import ndimage
    except ImportError:
        return
    for shape in ((60, 70), (10, 20, 30)):
        m = rng.random(shape) < 0.6
        a, n = ndi.label(m)
        b, nb = ndimage.label(m)
        assert n == nb and len(set(zip(a[m].tolist(), b[m].tolist()))) == n
    m = rng.random((80, 90)) < 0.3
    assert (ndi.binary_dilation(m) == ndimage.binary_dilation(m)).all()
    assert (ndi.binary_dilation(m, True, 2) == ndimage.binary_dilation(m, np.ones((3, 3), bool), iterations=2)).all()
    x = rng.random((60, 70)).astype(np.float32)
    assert np.allclose(ndi.grey_closing(x, 7)[7:-7, 7:-7], ndimage.grey_closing(x, size=(7, 7))[7:-7, 7:-7])


def test_seethrough_texture_has_no_blue_edges():
    """A "{" texture of Half-Life (blue = see-through): the see-through pixels get the colour of the nearest visible
    ones, so the blue does not show at the edges once the texture is shrunk or filtered (de_aztec's vines)."""
    from vtoy.app.state_more2 import _bleed_colours
    a = np.zeros((16, 16, 4), np.uint8)
    a[..., 2] = 255                                            # the blue key, alpha 0
    a[4:8, 4:8] = (40, 160, 30, 255)                           # a leaf
    b = _bleed_colours(a)
    assert (b[..., 3] == a[..., 3]).all()
    assert (b[..., :3] == (40, 160, 30)).all()


def test_faces_looking_into_sky_are_not_drawn():
    """A world face whose front is inside a sky brush (or solid) is never seen in CS; drawn in Torrente it was an olive
    ceiling over de_aztec's streets.  The map's own tree (hull 0) tells; without one, every face stays."""
    from vtoy import bspimport
    assert bspimport._front_contents(b"") is None

    class NoTree:
        faces = []
        raw = b""
    assert bspimport.drawn_faces(NoTree()) == []


def _write_mdl(path, verts, tris_cmd, tex=(4, 4), masked=False, bone_pos=(0.0, 0.0, 0.0), bone_rot=(0.0, 0.0, 0.0)):
    """A tiny Half-Life studio model (version 10): one bone, one texture, one body part / model / mesh."""
    w, h = tex
    hdr = bytearray(244)
    body = bytearray()

    def at():
        return 244 + len(body)
    bone_at = at()
    bone = bytearray(112)
    bone[:4] = b"root"
    struct.pack_into("<i", bone, 32, -1)
    struct.pack_into("<6f", bone, 64, *bone_pos, *bone_rot)
    struct.pack_into("<6f", bone, 88, 1, 1, 1, 1, 1, 1)
    body += bone
    tex_at = at()
    t = bytearray(80)
    t[:8] = b"skin.bmp"
    struct.pack_into("<4i", t, 64, 0x40 if masked else 0, w, h, 0)
    body += t
    pix_at = at()
    struct.pack_into("<i", body, tex_at - 244 + 76, pix_at)
    body += bytes([1] * (w * h)) + bytes([10, 20, 30] * 256)
    skin_at = at()
    body += struct.pack("<h", 0) + b"\0\0"
    vinfo_at = at()
    body += bytes(len(verts)) + b"\0" * (-len(verts) % 4)
    v_at = at()
    body += np.asarray(verts, "<f4").tobytes()
    tri_at = at()
    body += struct.pack(f"<{len(tris_cmd)}h", *tris_cmd) + b"\0\0"
    mesh_at = at()
    body += struct.pack("<5i", 1, tri_at, 0, 0, 0)
    model_at = at()
    mo = bytearray(112)
    struct.pack_into("<5i", mo, 72, 1, mesh_at, len(verts), vinfo_at, v_at)
    body += mo
    bp_at = at()
    bp = bytearray(76)
    struct.pack_into("<3i", bp, 64, 1, 1, model_at)
    body += bp
    hdr[:4] = b"IDST"
    struct.pack_into("<i", hdr, 4, 10)
    struct.pack_into("<2i", hdr, 140, 1, bone_at)
    struct.pack_into("<3i", hdr, 180, 1, tex_at, pix_at)
    struct.pack_into("<3i", hdr, 192, 1, 1, skin_at)
    struct.pack_into("<2i", hdr, 204, 1, bp_at)
    open(path, "wb").write(bytes(hdr + body))


def test_studio_model_props():
    """CS maps' studio models (.mdl): read (strips, fans, the bone's pose, the texture), placed where the entity says
    (origin, yaw), drawn, and a box round the lower part of a solid one standing on the ground."""
    from vtoy import mdl, bspimport
    with tempfile.TemporaryDirectory() as tmp:
        os.makedirs(os.path.join(tmp, "cstrike", "maps"))
        os.makedirs(os.path.join(tmp, "cstrike", "models", "props"))
        f = os.path.join(tmp, "cstrike", "models", "props", "Crate.mdl")
        verts = [(0, 0, 0), (10, 0, 0), (10, 10, 0), (0, 10, 0)]
        # a strip of 3 (one triangle) and a fan of 4 (two triangles): (vert, normal, s, t)
        cmd = [3, 0, 0, 0, 0, 1, 0, 4, 0, 2, 0, 4, 4, -4, 0, 0, 0, 0, 2, 0, 4, 4, 3, 0, 0, 4, 1, 0, 4, 0]
        _write_mdl(f, verts, cmd, bone_pos=(0, 0, 5))
        m = mdl.load(f)
        tr = m.triangles()
        assert len(tr) == 3 and m.textures[0].name == "skin.bmp" and m.textures[0].width == 4
        assert all(np.allclose(q[:, 2], 5.0) for _t, q, _uv in tr)                  # moved by its bone
        assert np.allclose(tr[0][2][1], [1.0, 0.0])                                 # s / width, t / height
        bsp = os.path.join(tmp, "cstrike", "maps", "x.bsp")
        ents = [{"classname": "cycler_sprite", "model": "models/props/crate.mdl", "origin": "100 0 0", "angles": "0 90 0"},
                {"classname": "cycler_sprite", "model": "models/props/none.mdl", "origin": "0 0 0"}]
        props, missing = mdl.map_props(ents, mdl.map_roots(bsp))
        assert len(props) == 1 and missing == ["models/props/none.mdl"]              # found though named in lower case
        q = props[0].tris[0][1]
        assert np.allclose(q[1], [100, 10, 5], atol=1e-6)                           # (10, 0, 0) turned 90 about z
        img = m.textures[0].rgba()
        assert img.shape == (4, 4, 4) and tuple(img[0, 0, :3]) == (10, 20, 30)
        assert bspimport.prop_texture_key(props[0], 0) == "mdl:crate:skin.bmp"
        pl = bspimport.Plan(2.54, 0.0, (0.0, 0.0, 0.0), (0.0, 0.0, 0.0))
        assert bspimport.prop_box(props[0], None, pl) is None                       # flat (no height): walked over
        _write_mdl(f, [(0, 0, 0), (40, 0, 0), (40, 40, 50), (0, 40, 50)], cmd)
        props, _m = mdl.map_props(ents[:1], mdl.map_roots(bsp))
        c, half, R = bspimport.prop_box(props[0], lambda p: bspimport.CONTENTS_SOLID, pl)
        assert half[1] * 2 > 40 * 2.54 * 0.9                                        # the lower part, in cm
        assert bspimport.prop_box(props[0], lambda p: -1, pl) is None               # nothing under it: hanging
        _write_mdl(f, [(0, 0, 0), (40, 0, 0), (40, 40, 50), (0, 40, 50)], cmd, masked=True)
        props, _m = mdl.map_props(ents[:1], mdl.map_roots(bsp))
        assert bspimport.prop_box(props[0], lambda p: bspimport.CONTENTS_SOLID, pl) is None   # leaves: see-through


def test_rain_in_the_do_dll():
    """The DO DLLs never make rain: the copy gets Marbella's shower (AddShower at the scene's start, RemoveRenderObject at
    its end) through a new import of vtKernel; the zones, the HUD, the minimap and the bomb's time stay; taken out, the
    DLL's import table and the scene's end are the game's again."""
    dtt = _dll("dtt.dll")
    stock = open(dtt, "rb").read()
    assert dllpatch.can_have_bomb_rain(stock) and dllpatch.bomb_rain(stock) == (False, False)
    assert not dllpatch.can_have_bomb_rain(open(_dll("ctf.dll"), "rb").read())
    with tempfile.TemporaryDirectory() as tmp:
        a = os.path.join(tmp, "a.dll")
        assert dllpatch.patch_bomb_zones(dtt, a, [], rain=True) == ([], False)          # rain only
        d = open(a, "rb").read()
        assert dllpatch.bomb_rain(d) == (True, True) and dllpatch.bomb_zones(d) == ([], False)
        assert not dllpatch.bomb_zones_hud(d) and not dllpatch.bomb_zones_radar(d)
        pe = dllpatch._PE(bytearray(d))
        sec = dllpatch._section(pe, b".vtoyz")
        base = pe.base + sec["va"]
        P = lambda o: base + struct.unpack_from("<i", d, sec["ro"] + 0x800 + o)[0]
        imp = struct.unpack_from("<II", d, pe.pe + 24 + 104)
        assert sec["va"] + 0x1000 <= imp[0] < sec["va"] + 0x2000                         # the new import table
        for o, f in ((0x124, dllpatch._RAIN_IMPORTS[0]), (0x13c, dllpatch._RAIN_IMPORTS[2]),
                     (0x12c, b"?main@CGame@@0HA"), (0x0c, b"?ObjectByName@@YAPBVCObject@@AAVCString@@@Z")):
            assert P(o) == dllpatch._import_slot(d, pe, f)
        assert base <= P(0x124) < base + 0x2000 and base <= P(0x128) < base + 0x2000
        assert struct.unpack_from("<i", d, sec["ro"] + 0x920)[0] == 1
        assert struct.unpack_from("<f", d, sec["ro"] + 0x934)[0] == 30000.0
        assert struct.unpack_from("<3f", d, sec["ro"] + 0x950) == (0.0, -1500.0, 0.0)
        import re
        site = re.search(dllpatch._DZ_SITE, d, re.S)                                     # the game's own zone test
        assert site is not None                                                          # is left as it is
        i_off = re.search(dllpatch._BZ_INIT_SITE, stock, re.S).start()
        t_off = re.search(dllpatch._BZ_DTOR_SITE2, stock, re.S).start()               # the destructor's start
        text = dllpatch._section(pe, b".text")
        for off, to in ((i_off, base + dllpatch._BZ_INIT), (t_off, base + dllpatch._BZ_DTOR)):
            va = pe.base + text["va"] + off - text["ro"]
            assert d[off] == 0xE9 and va + 5 + struct.unpack_from("<i", d, off + 1)[0] == to
        t_va = pe.base + text["va"] + t_off - text["ro"]
        assert P(0x130) == t_va + 8 and not dllpatch.bomb_zones_late_end(d)
        # with zones, the bomb's time, calm rain; then without rain: the game's import table and end again
        dllpatch.patch_bomb_zones(a, a, ["bombZone_B", "bombZone_C"], True, True, True, rain=True, storm=False)
        dllpatch.patch_bomb_rules(a, a, 40, True)
        d = open(a, "rb").read()
        assert dllpatch.bomb_rain(d) == (True, False) and dllpatch.bomb_rules(d) == (40.0, True)
        assert struct.unpack_from("<i", d, dllpatch._section(dllpatch._PE(bytearray(d)), b".vtoyz")["ro"] + 0x938)[0] == 1
        assert dllpatch.bomb_zones(d) == (["bombZone_B", "bombZone_C"], True) and dllpatch.bomb_zones_hud(d)
        dllpatch.patch_bomb_zones(a, a, ["bombZone_B", "bombZone_C"], True, True, True)
        d = open(a, "rb").read()
        assert dllpatch.bomb_rain(d) == (False, False) and dllpatch.bomb_rules(d) == (40.0, True)
        # no rain, icons: the scene's end still hooked - the icons go (RemoveRenderObject, as the game's own icons)
        assert d[t_off] == 0xE9
        assert struct.unpack_from("<II", d, pe.pe + 24 + 104) == struct.unpack_from("<II", stock, pe.pe + 24 + 104)
        assert dllpatch.bomb_zones_icons_off(d)
        dllpatch.patch_bomb_zones(a, a, ["bombZone_B", "bombZone_C"], True, False, True)          # no icons either
        d = open(a, "rb").read()
        assert struct.unpack_from("<II", d, pe.pe + 24 + 104) == struct.unpack_from("<II", stock, pe.pe + 24 + 104)
        assert d[t_off:t_off + 8] == stock[t_off:t_off + 8] and d.count(b"VTOYBZ2\0") == 1
        assert len(d) == len(stock) + 0x2000
        # the splashes: a hook at the start of the scene's Run (its 4 pushes and 2 lines), the jump back after them
        dllpatch.patch_bomb_zones(a, a, ["bombZone_B", "bombZone_C"], True, True, True, rain=True, splash=True)
        d = open(a, "rb").read()
        assert dllpatch.bomb_splash(d) and dllpatch.bomb_rain(d) == (True, True) and dllpatch.bomb_rules(d) == (40.0, True)
        pe = dllpatch._PE(bytearray(d))
        sec = dllpatch._section(pe, b".vtoyz")
        base = pe.base + sec["va"]
        r_off = dllpatch._scene_run(stock, pe) + dllpatch._BZ_RUN_AT
        r_va = pe.va_of(r_off)
        assert d[r_off] == 0xE9 and r_va + 5 + struct.unpack_from("<i", d, r_off + 1)[0] == base + dllpatch._BZ_SPLASH
        j = sec["ro"] + dllpatch._BZ_SPRET
        assert d[j] == 0xE9 and base + dllpatch._BZ_SPRET + 5 + struct.unpack_from("<i", d, j + 1)[0] == r_va + 10
        P = lambda o: base + struct.unpack_from("<i", d, sec["ro"] + 0x800 + o)[0]
        for k, o in enumerate(range(0x168, 0x188, 4)):
            assert P(o) == dllpatch._import_slot(d, pe, dllpatch._RAIN_IMPORTS[3 + k])
        assert P(0x164) == dllpatch._import_slot(d, pe, b"?camera@CGame@@0HA")
        assert d[sec["ro"] + 0x990:sec["ro"] + 0x9a1] == b"gota_salpica.tex\0"
        dllpatch.patch_bomb_zones(a, a, ["bombZone_B", "bombZone_C"], True, True, True, rain=True)
        d = open(a, "rb").read()
        assert not dllpatch.bomb_splash(d) and d[r_off:r_off + 10] == stock[r_off:r_off + 10]
        assert not dllpatch.bomb_splash(stock)
        dllpatch.patch_bomb_zones(a, a, ["bombZone_B", "bombZone_C"], True, True, True)
        d = open(a, "rb").read()
        b = os.path.join(tmp, "b.dll")                         # the same as made straight from the game's DLL
        dllpatch.patch_bomb_zones(dtt, b, ["bombZone_B", "bombZone_C"], True, True, True)
        dllpatch.patch_bomb_rules(b, b, 40, True)
        assert open(b, "rb").read() == d
        with pytest.raises(ValueError):
            dllpatch.patch_bomb_zones(dtt, a, [])                # nothing to do


def test_rain_dll_keeps_the_rest_of_the_map_copy():
    from test_batch7 import _st
    dtt = _dll("dtt.dll")
    with tempfile.TemporaryDirectory() as tmp:
        st = _st(tmp, "mp_do_laberinto.scn")
        if str(st.scene.main_module_name).rstrip("\0").lower() != "mp_destroythetarget.dll":
            pytest.skip("not the DO DLL")
        game_dll = os.path.join(tmp, "mp_DestroyTheTarget.dll")
        shutil.copyfile(dtt, game_dll)
        st.custom_dlls = {"mp_destroythetarget.dll": game_dll}
        assert not st.bomb_rain_settings()["rain"] and st.bomb_rain_settings()["can"]
        st.make_bomb_dll(40.0, True)
        msg = st.make_bomb_rain_dll(True, False)
        assert "without storm" in msg
        d = open(st.mode_dll_source(), "rb").read()
        assert dllpatch.bomb_rules(d) == (40.0, True) and dllpatch.bomb_rain(d) == (True, False)
        assert st.bomb_rain_settings() == {"rain": True, "storm": False, "splash": False, "can": True}
        st.make_bomb_rain_dll(True, False, True)
        assert st.bomb_rain_settings()["splash"]
        assert dllpatch.bomb_rules(open(st.mode_dll_source(), "rb").read()) == (40.0, True)
        st.make_bomb_dll(30.0, False)                          # the bomb again: the rain stays
        d = open(st.mode_dll_source(), "rb").read()
        assert dllpatch.bomb_rules(d) == (30.0, False) and dllpatch.bomb_rain(d) == (True, False)
        assert dllpatch.bomb_splash(d)
        st.make_bomb_rain_dll(False)
        d = open(st.mode_dll_source(), "rb").read()
        assert dllpatch.bomb_rain(d) == (False, False) and dllpatch.bomb_rules(d) == (30.0, False)
        assert not dllpatch.bomb_splash(d) and st.bomb_zone_rules() is None


def test_imported_meshes_small_and_short_texture_names():
    """An imported map's meshes are cut by squares of the map (and at most MESH_FACES faces each), so the game draws
    only those near; a new texture's name stays within the game's longest (31 letters with ".tex")."""
    from vtoy.app import state_more2, state_build
    faces = [(np.array([[x, 0.0, z], [x + 10, 0.0, z], [x + 10, 0.0, z + 10]]), np.array([0, 1.0, 0]))
             for x in range(0, 9000, 100) for z in range(0, 3000, 100)]
    parts = state_more2.mesh_tiles(faces, 3000.0, 600)
    assert sum(len(p) for p in parts) == len(faces) and max(len(p) for p in parts) <= 600
    for p in parts:                                       # each part in one square
        keys = {(int(f[0].mean(0)[0] // 3000), int(f[0].mean(0)[2] // 3000)) for f in p}
        assert len(keys) == 1
    from test_batch7 import _st
    with tempfile.TemporaryDirectory() as tmp:
        st = _st(tmp, own_texs=True)
        rgba = np.zeros((8, 8, 4), np.uint8)
        rgba[..., 3] = 255
        a = st._new_texture_name("datepalm_fronds_01_saturated_extra", rgba, "cs")
        rgba2 = rgba.copy()
        rgba2[..., 0] = 200
        b = st._new_texture_name("datepalm_fronds_01_saturated_extra", rgba2, "cs")
        assert a != b and len(a) <= 31 and len(b) <= 31 and len(a) - 4 <= state_build.MAX_TEX_STEM


def test_weapons_of_deathmatch_dlls():
    """The team deathmatch DLL (and deathmatch, Chalet) hand the weapons out with other registers and the rounds from
    their own table, when created and when born again: knife + rifle only works there too, and the tables are indexed
    by the rifle; all weapons again = the game's DLL."""
    for name, style in (("dmt.dll", "dm"), ("dm.dll", "dm1")):
        src = _dll(name)
        stock = open(src, "rb").read()
        s = dllpatch._weapon_sites(stock)
        assert s["style"] == style and dllpatch.weapon_groups(stock) == [True] * 5
        with tempfile.TemporaryDirectory() as tmp:
            a = os.path.join(tmp, "a.dll")
            assert dllpatch.patch_weapon_groups(src, a, [True, False, True, False, False], [0, 0, 8, 0, 0]) == \
                [True, False, True, False, False]
            d = open(a, "rb").read()
            assert dllpatch.weapon_choice(d) == [0, 0, 8, 0, 0]
            for o in dllpatch._table_sites(d)[2]:                 # the rounds: the rifle's
                assert d[o] in range(0xB8, 0xC0) and struct.unpack_from("<I", d, o + 1)[0] == 8
            h = s["hands_id"]
            assert d[h] in range(0xB8, 0xC0) and struct.unpack_from("<I", d, h + 1)[0] == 8
            b = os.path.join(tmp, "b.dll")
            dllpatch.patch_weapon_groups(src, b, [True] * 5, [0, 0, [8, 16], 0, 0])
            assert dllpatch.weapon_sets(open(b, "rb").read())[2] == [8, 16]
            c = os.path.join(tmp, "c.dll")
            dllpatch.patch_weapon_groups(src, c, [True] * 5, [0] * 5)
            assert open(c, "rb").read() == stock


def test_breakable_panels_open_and_invisible_walls_not_drawn():
    """A thin func_breakable (a metal sheet over a hole, boards over a window: one shot opens it in CS) is left out;
    a brush entity with render amount 0 (an invisible wall, "nowallshot") is not drawn but still blocks; "{invis"
    faces are not drawn."""
    from vtoy import bspimport
    from vtoy.bsp import BspMap, BspFace

    def quad(x0, y0, z0, x1, y1, z1, tex, model):
        p = np.array([[x0, y0, z0], [x1, y1, z0], [x1, y1, z1], [x0, y0, z1]], np.float64)
        n = np.cross(p[1] - p[0], p[2] - p[0])
        return BspFace(p, n / np.linalg.norm(n), tex, np.zeros((4, 2)), model)
    b = BspMap()
    b.faces = [quad(0, 0, 0, 100, 0, 100, "wall", 0), quad(0, 10, 0, 80, 10, 72, "mtl054", 1),
               quad(0, 20, 0, 80, 20, 72, "nowallshot", 2), quad(0, 30, 0, 80, 30, 72, "{invis", 0),
               quad(0, 40, 0, 26, 40, 40, "plywood", 3)]
    b.models = [(np.zeros(3), np.array([100.0, 40, 100])), (np.array([0, 9.0, 0]), np.array([80, 11.0, 72])),
                (np.array([0, 19.0, 0]), np.array([80, 21.0, 72])), (np.array([0, 40.0, 0]), np.array([26, 66.0, 40]))]
    b.entities = [{"classname": "worldspawn"},
                  {"classname": "func_breakable", "model": "*1", "material": "2"},
                  {"classname": "func_wall", "model": "*2", "rendermode": "2", "renderamt": "0"},
                  {"classname": "func_breakable", "model": "*3"}]
    assert bspimport.open_panels(b) == {1}                      # the 26 x 26 crate stays
    assert bspimport.invisible_entity(b.entities[2]) and not bspimport.invisible_entity(b.entities[3])
    assert bspimport.skipped("{invis")
    pl = bspimport.plan(b, (0.0, 0.0, 0.0), 0.0, 2.54)
    cv = bspimport.convert(b, pl, {"wall": "a.tex", "mtl054": "b.tex", "nowallshot": "c.tex", "plywood": "d.tex"},
                           None, lambda n: True, True, hull=False)
    assert set(cv.meshes) == {"a.tex", "d.tex"} and cv.open_panels == 1 and cv.invisible == 1


def test_health_pack_time():
    """mp_salud.dll shows a picked pack again after GetTime() - picked > 5000 ms; the map's copy changes that time and
    the scene's packs use it, the game's DLL stays."""
    from test_batch7 import _st
    src = _dll("salud.dll")
    data = open(src, "rb").read()
    assert dllpatch.health_respawn(data) == dllpatch.HEALTH_RESPAWN_S
    with tempfile.TemporaryDirectory() as tmp:
        a = os.path.join(tmp, "a.dll")
        assert dllpatch.patch_health_respawn(src, a, 20) == (5.0, 20.0)
        d = open(a, "rb").read()
        assert dllpatch.health_respawn(d) == 20.0 and sum(x != y for x, y in zip(d, data)) <= 4 and len(d) == len(data)
        with pytest.raises(ValueError):
            dllpatch.patch_health_respawn(src, a, 0)
        with pytest.raises(ValueError):
            dllpatch.health_respawn(open(_dll("dtt.dll"), "rb").read())
        st = _st(tmp, "mp_dm_madrid.scn")
        if not st.health_packs():
            pytest.skip("no health packs in this scene")
        game = os.path.join(tmp, "mp_salud.dll")
        shutil.copyfile(src, game)
        st.custom_dlls = {"mp_salud.dll": game}
        assert st.health_settings()["seconds"] == 5.0
        msg = st.make_health_dll(12, game)
        assert "12 s" in msg and open(game, "rb").read() == data
        hs = st.health_settings()
        assert hs["seconds"] == 12.0 and hs["dll"].lower() == f"mp_salud@{st.map_stem()}.dll".lower()
        st.use_stock_health_dll()
        assert st.health_settings()["dll"] == "mp_salud.dll"


def test_black_faces_take_the_textures_around_them():
    """A face drawn with black.tex between two crates gets the crates' texture (the one along its edges), in the crate's
    own mapping when in its plane; the collision and the height map are not touched."""
    from test_batch7 import _st
    from vtoy import crop, solids
    with tempfile.TemporaryDirectory() as tmp:
        st = _st(tmp)
        nb = len(crop.read_block(st.opt).boxes)
        hm = st.heightmap_edit().to_bytes()
        tex = next(t for t in ("cesped.tex", "asfalto.tex", "muro_liso.tex") if st.fs.texture(t) is not None)
        far = np.array([90000.0, 0.0, 90000.0])
        up = np.array([0.0, 0.0, -1.0])
        crate = [(far + np.array([[0, 0, 0], [100, 0, 0], [100, 100, 0], [0, 100, 0]], float), up,
                  np.array([[0, 0], [1, 0], [1, 1], [0, 1]], float))]
        gap = [(far + np.array([[100, 0, 0], [140, 0, 0], [140, 100, 0], [100, 100, 0]], float), up, None)]
        st.opt.meshes  # the crate (texture) and the black gap next to it, in the same plane
        crop.add_mesh(st.opt, solids.mesh_from_faces(st.opt, crate, tex))
        crop.add_mesh(st.opt, solids.mesh_from_faces(st.opt, gap, "black.tex"))
        n = len(st.opt.meshes)
        msg = st.retexture_from_neighbours("black.tex")
        assert "2 faces of black.tex" in msg and tex in msg
        assert not any(m.materials and str(m.materials[0].diffuse).lower() == "black.tex" for m in st.opt.meshes)
        assert len(crop.read_block(st.opt).boxes) == nb and st.heightmap_edit().to_bytes() == hm
        new = st.opt.meshes[-1]
        sm = next(new.render_submeshes())
        p = sm.vertices["pos"].astype(float)
        uv = sm.vertices["uv"].astype(float)
        k = int(np.argmax(p[:, 0]))                          # the far corner: u = 1.4 (the crate's mapping carried on)
        assert abs(uv[k, 0] - 1.4) < 1e-3 and len(st.opt.meshes) == n
        with pytest.raises(ValueError):
            st.retexture_from_neighbours("black.tex")


def _lit_arena(path):
    """The arena of batch 13 with lightmaps: the floor bright and warm, the walls dark, the crate mid grey."""
    import math as _m
    import struct as _s
    from test_batch13 import make_arena
    from vtoy.bsp import LUMPS
    make_arena(path)
    raw = open(path, "rb").read()
    lump = {n: _s.unpack_from("<ii", raw, 4 + 8 * i) for i, n in enumerate(LUMPS)}
    get = lambda n: raw[lump[n][0]:lump[n][0] + lump[n][1]]
    verts = np.frombuffer(get("vertices"), "<f4").reshape(-1, 3).astype(float)
    edges = np.frombuffer(get("edges"), "<u2").reshape(-1, 2)
    surf = np.frombuffer(get("surfedges"), "<i4")
    ti = np.frombuffer(get("texinfo"), np.dtype([("s", "<f4", 4), ("t", "<f4", 4), ("mip", "<i4"), ("flags", "<i4")]))
    fdt = np.dtype([("plane", "<u2"), ("side", "<u2"), ("first", "<i4"), ("n", "<u2"), ("ti", "<u2"),
                    ("styles", "u1", 4), ("light", "<i4")])
    faces = np.frombuffer(get("faces"), fdt).copy()
    planes = np.frombuffer(get("planes"), np.dtype([("n", "<f4", 3), ("d", "<f4"), ("t", "<i4")]))
    light = b""
    for f in faces:
        se = surf[f["first"]:f["first"] + f["n"]]
        p = verts[np.where(se >= 0, edges[np.abs(se), 0], edges[np.abs(se), 1])]
        t = ti[f["ti"]]
        vs, vt = p @ t["s"][:3] + t["s"][3], p @ t["t"][:3] + t["t"][3]
        w = _m.ceil(vs.max() / 16) - _m.floor(vs.min() / 16) + 1
        h = _m.ceil(vt.max() / 16) - _m.floor(vt.min() / 16) + 1
        nz = planes[f["plane"]]["n"][2]
        col = (220, 190, 140) if nz > 0.5 else (60, 60, 70) if abs(nz) < 0.5 else (120, 120, 120)
        f["light"], f["styles"] = len(light), (0, 255, 255, 255)
        light += bytes(col) * (w * h)
    out = bytearray(raw)
    # faces in place (same size); the lighting lump at the end of the file
    o, n = lump["faces"]
    out[o:o + n] = faces.tobytes()
    li = LUMPS.index("lighting")
    _s.pack_into("<ii", out, 4 + 8 * li, len(out), len(light))
    out += light
    open(path, "wb").write(bytes(out))


def test_bsp_light_on_imported_meshes():
    """The lightmaps of a .bsp become a second texture (x 2) of the meshes made from it: the floor lit, the walls in
    the dark; the collision stays; a map imported without it gets it afterwards (where it was laid is found)."""
    from test_batch7 import _st
    from vtoy import crop, lightmap
    from vtoy.bsp import BspMap
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "arena.bsp")
        _lit_arena(p)
        b = BspMap.load(p)
        ch = lightmap.bsp_lightmaps(b.raw)
        assert len(ch) == len(b.faces)                               # every face (the sky too) has its lightmap
        st = _st(tmp, "mp_dm_almacen.scn")
        n0 = len(st.opt.meshes)
        before = [(len(m.materials[0].textures), m) for m in st.opt.meshes]
        msg = st.import_bsp(p, (90000.0, 0.0, 90000.0), 90.0, 2.54, None, None, True, False, False)
        assert "light of arena.bsp" in msg, msg
        nb = len(crop.read_block(st.opt).boxes)
        new = st.opt.meshes[n0:]
        assert new and all(len(m.materials[0].textures) == 2 for m in new)
        assert all(len(m.materials[0].textures) == k for k, m in before)        # the map's own meshes untouched
        lm = st.fs.texture(new[0].materials[0].textures[1]).decode()[..., :3].astype(float)
        bright, dark = [], []
        for m in new:
            for sm in m.render_submeshes():
                assert sm.stride_type == 1 and "uv2" in sm.vertices.dtype.names
                uv2 = sm.vertices["uv2"].astype(float)
                assert (uv2 >= 0).all() and (uv2 <= 1).all()
                tri = sm.indices.reshape(-1, 3).astype(int)
                for t in tri:
                    q = uv2[t].mean(0)
                    c = lm[int(q[1] * lm.shape[0]), int(q[0] * lm.shape[1])].mean()
                    ny = float(sm.vertices["nrm"][t[0]][1])
                    if ny > 0.9:
                        bright.append(c)
                    elif abs(ny) < 0.1:
                        dark.append(c)
        assert min(bright) > 120 and max(dark) < 100, (min(bright), max(dark))
        assert len(crop.read_block(st.opt).boxes) == nb
        # a map made without it: the light afterwards, the place found from its walls
        st2 = _st(os.path.join(tmp, "b"), "mp_dm_almacen.scn")
        m0 = len(st2.opt.meshes)
        st2.import_bsp(p, (90000.0, 0.0, 90000.0), 90.0, 2.54, None, None, True, False, False, light=False)
        assert all(len(m.materials[0].textures) == 1 for m in st2.opt.meshes[m0:])
        pl = lightmap.find_plan(b, st2.opt)
        from vtoy import bspimport
        good = bspimport.plan(b, (90000.0, 0.0, 90000.0), 90.0)
        assert np.allclose(pl.point([100, 200, 30]), good.point([100, 200, 30]), atol=0.5)
        msg = st2.bsp_light(p)
        assert "light of arena.bsp" in msg and all(len(m.materials[0].textures) == 2 for m in st2.opt.meshes[m0:])
        assert "no mesh to light" in st2.bsp_light(p)                         # once is enough
        from vtoy.render.geometry import bake_scene                          # the editor draws it (x 2)
        g = bake_scene(st2.fs, st2.scene, st2.opt, include_models=False)
        lit = [b for b in g.opaque if b.lightmap]
        assert lit and all(b.uv2 is not None and len(b.uv2) == len(b.vertices) for b in lit)
        tris = sum(len(sm.indices) for m in st2.opt.meshes[m0:] for sm in m.render_submeshes())
        assert "taken off" in st2.remove_bsp_light()                         # saved without it: as before
        assert all(len(m.materials[0].textures) == 1 and all(sm.stride_type == 0 for sm in m.render_submeshes())
                   for m in st2.opt.meshes[m0:])
        assert sum(len(sm.indices) for m in st2.opt.meshes[m0:] for sm in m.render_submeshes()) == tris
        assert "light of arena.bsp" in st2.bsp_light(p)                     # and back


def test_bsp_faces_missing_from_the_map_drawn_again():
    """mp_do_mirage_cs2's market: walls behind the shelves were left out by an older importer (one saw out of the map
    through them).  The faces of the .bsp no mesh draws come back as meshes (lit like the rest), nothing else changes;
    a face drawn in part counts as drawn."""
    from test_batch7 import _st
    from vtoy import bspimport, crop, lightmap
    from vtoy.bsp import BspMap
    # uncovered_faces: a quad on two triangles, a quad half on one, a quad on nothing (and one on another plane)
    sq = lambda x0, y=0.0: np.array([[x0, y, 0.0], [x0 + 10, y, 0.0], [x0 + 10, y, 10.0], [x0, y, 10.0]])
    n = np.array([0.0, -1.0, 0.0])
    a, b_ = sq(0.0), sq(20.0)
    tris = np.array([a[[0, 1, 2]], a[[0, 2, 3]], b_[[0, 1, 2]], sq(40.0, 5.0)[[0, 1, 2]], sq(40.0, 5.0)[[0, 2, 3]]])
    hits = {}
    assert bspimport.uncovered_faces([(a, n), (b_, n), (sq(40.0), n), (sq(60.0), n)], tris, hits=hits) == [2, 3]
    assert hits[0] in (0, 1) and hits[1] == 2
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "arena.bsp")
        _lit_arena(p)
        st = _st(tmp, "mp_dm_almacen.scn")
        n0 = len(st.opt.meshes)
        st.import_bsp(p, (90000.0, 0.0, 90000.0), 90.0, 2.54, None, None, True, False, False)
        assert st.bsp_missing_faces(p)[1] == []
        assert "no face of the .bsp is missing" in st.restore_bsp_faces(p)
        tris0 = sum(len(sm.indices) for m in st.opt.meshes[n0:] for sm in m.render_submeshes())
        gone = max(range(n0, len(st.opt.meshes)), key=lambda i: sum(len(sm.indices) for sm in st.opt.meshes[i].render_submeshes()))
        lost = sum(len(sm.indices) for sm in st.opt.meshes[gone].render_submeshes())
        tex = st.opt.meshes[gone].materials[0].textures[0]
        crop.remove_meshes(st.opt, {gone}, False)
        nb, hm = len(crop.read_block(st.opt).boxes), st.heightmap_edit().to_bytes()
        miss = st.bsp_missing_faces(p)[1]
        assert miss
        msg = st.restore_bsp_faces(p)
        assert f"{len(miss)} faces of the .bsp drawn again" in msg and "with the CS light" in msg, msg
        new = st.opt.meshes[len(st.opt.meshes) - 1]
        assert new.materials[0].textures[0] == tex and len(new.materials[0].textures) == 2   # its texture, lit
        assert st.bsp_missing_faces(p)[1] == []
        assert sum(len(sm.indices) for m in st.opt.meshes[n0:] for sm in m.render_submeshes()) >= tris0 - lost
        assert len(crop.read_block(st.opt).boxes) == nb and st.heightmap_edit().to_bytes() == hm
        # the light of the faces back: measured against the whole map's (not brighter than the rest)
        assert lightmap.reference(st.opt, BspMap.load(p), lightmap.find_plan(BspMap.load(p), st.opt)) is not None


def test_bomb_overtime_code_runs():
    """The bomb time / overtime code of a DO mode DLL, run natively (32-bit) with the game faked: the planting time
    moved once, 0:00 with a ticking bomb puts its seconds on the clock (it blows up at 0:00), a bomb that blew up and
    left the scene's list at once still holds 0:00 back a few seconds (it was the defenders' win: "fuera de tiempo"),
    and a 0:00 not of this round (round already won; the round before's, after the restart) is let go."""
    import re as _re
    import shutil
    import subprocess
    gcc = shutil.which("gcc")
    if not gcc:
        pytest.skip("no gcc")
    here = os.path.join(os.path.dirname(__file__), "..", "tools", "asm", "otharness.c")
    with tempfile.TemporaryDirectory() as tmp:
        d = os.path.join(tmp, "dtt.dll")
        dllpatch.patch_bomb_rules(_dll("dtt.dll"), d, 40, True)
        data = bytearray(open(d, "rb").read())
        pe = dllpatch._PE(data)
        h, r = dllpatch._hook_sites(bytes(data), pe)
        text = next(s_ for s_ in pe.secs if s_["name"] == b".text")
        size = struct.unpack_from("<I", data, pe.pe + 24 + 56)[0]
        img = bytearray(size)
        for s_ in pe.secs:
            img[s_["va"]:s_["va"] + min(s_["rs"], s_["vs"] or s_["rs"])] = data[s_["ro"]:s_["ro"] + min(s_["rs"], s_["vs"] or s_["rs"])]
        cave = struct.unpack_from("<I", data, data.find(b"VTOYBOMB") - 4)[0]
        c0 = text["va"] + cave - text["ro"]
        img[c0:text["va"] + text["rs"]] = img[c0:text["va"] + text["rs"]].replace(b"\x64\xa1\x00\x00\x00\x00",
                                                                                  b"\xb8\x00\x00\x00\x00\x90")
        slot = dllpatch._import_slot(bytes(data), pe, b"?GetTime@@YAMXZ") - pe.base
        m = _re.search(rb"\x8b[\x88-\x8f](....)\x6a\x00\x50\xff\x15"
                       + _re.escape(struct.pack("<I", dllpatch._import_slot(bytes(data), pe, b"?SetTime@ContadorTiempo@@QAEXHH@Z"))),
                       bytes(data), _re.S)
        clock = struct.unpack_from("<I", m.group(1))[0]
        to_rva = lambda off: off - text["ro"] + text["va"]
        open(os.path.join(tmp, "otcode.h"), "w").write(
            f"#define IMG_SIZE {(size + 0xfff) & ~0xfff}\n#define R_RVA {to_rva(r)}\n#define H_RVA {to_rva(h)}\n"
            f"#define SLOT_RVA {slot}\n#define CLOCK {clock}\n#define OVER 0x638\n"
            "static const unsigned char IMG[]={" + ",".join(str(x) for x in img) + "};\n")
        shutil.copy(here, os.path.join(tmp, "otharness.c"))
        exe = os.path.join(tmp, "h")
        r_ = subprocess.run([gcc, "-m32", "-nostdlib", "-static", "-ffreestanding", "-fno-pie", "-no-pie", "-O1",
                             "-fno-stack-protector", "-mno-sse", "-o", exe, os.path.join(tmp, "otharness.c")],
                            capture_output=True, text=True)
        if r_.returncode != 0:
            pytest.skip("no 32-bit gcc: " + r_.stderr[-200:])
        r_ = subprocess.run([exe], capture_output=True, text=True, timeout=30)
        assert r_.returncode == 0, r_.stdout


def test_water_drawn_once():
    """A water volume brought in with every face (de_aztec: it flickered in the game) keeps only its top: no
    underside, no bottom lying on the pool's floor, no sides under the water; other meshes and collision as before.
    A .bsp's func_water gives only its top too."""
    from test_batch7 import _st
    from vtoy import crop, solids, bspimport
    with tempfile.TemporaryDirectory() as tmp:
        st = _st(tmp, "mp_dm_almacen.scn")
        up, dn = np.array([0.0, 1.0, 0.0]), np.array([0.0, -1.0, 0.0])

        def quad(y, n, x0=0.0, z0=0.0, x1=400.0, z1=400.0):
            q = np.array([[x0, y, z0], [x0, y, z1], [x1, y, z1], [x1, y, z0]], float)
            return (q[::-1] if n[1] > 0 else q, n)

        def side(x, n):
            return (np.array([[x, 0, 0], [x, 41, 0], [x, 41, 400], [x, 0, 400]], float), n)
        faces = [quad(41, up), quad(41, dn), quad(0, up), quad(0, dn),
                 side(0, np.array([-1.0, 0, 0])), side(0, np.array([1.0, 0, 0])), side(400, np.array([1.0, 0, 0]))]
        n0 = len(st.opt.meshes)
        crop.add_mesh(st.opt, solids.mesh_from_faces(st.opt, faces, "watergreen.tex"))
        crop.add_mesh(st.opt, solids.mesh_from_faces(st.opt, [quad(0, up, -400, -400, 800, 800)], "floor_x.tex"))
        nb = len(crop.read_block(st.opt).boxes)
        assert st.water_layers("watergreen") == 12                  # 7 quads = 14 triangles, 2 stay
        st.fix_water_layers("watergreen.tex")
        me = st.opt.meshes[n0]
        left = [sm.vertices["pos"][sm.indices.reshape(-1, 3).astype(int)] for sm in me.render_submeshes()]
        left = np.concatenate(left)
        assert len(left) == 2 and np.allclose(left[:, :, 1], 41.0) and me.materials[0].two_sided
        assert sum(len(sm.indices) for sm in st.opt.meshes[n0 + 1].render_submeshes()) == 6    # the floor stays
        assert len(crop.read_block(st.opt).boxes) == nb and st.water_layers("watergreen") == 0
    # the .bsp: a func_water's top only
    box = (np.array([0.0, 0.0, -16.0]), np.array([100.0, 100.0, 0.0]))
    face = lambda z, nz, pts=None: bspimport.BspFace(np.array(pts if pts is not None else
                                                              [[0, 0, z], [100, 0, z], [100, 100, z]], float),
                                                     np.array([0.0, 0.0, nz] if pts is None else [1.0, 0, 0]), "!w", np.zeros((3, 2)), 3)
    assert bspimport._water_face_seen(face(0, 1.0), box)
    assert not bspimport._water_face_seen(face(0, -1.0), box) and not bspimport._water_face_seen(face(-16, 1.0), box)
    assert not bspimport._water_face_seen(face(0, 0, [[100, 0, -16], [100, 0, 0], [100, 100, 0]]), box)


def test_weather_stub_runs():
    """The ".vtoyw" stub of a DM / DMT / CTF copy, run natively (32-bit): AddShower as before (its arguments, its shower
    back, the caller's stack and registers), then calm rain / the map's quieter sounds."""
    import shutil
    import subprocess
    gcc = shutil.which("gcc")
    if not gcc:
        pytest.skip("no gcc")
    here = os.path.join(os.path.dirname(__file__), "..", "tools", "asm", "wharness.c")
    with tempfile.TemporaryDirectory() as tmp:
        open(os.path.join(tmp, "wcode.h"), "w").write(
            "static const unsigned char CODE[]={" + ",".join(str(x) for x in dllpatch._W_CODE) + "};\n")
        shutil.copy(here, os.path.join(tmp, "wharness.c"))
        exe = os.path.join(tmp, "h")
        r = subprocess.run([gcc, "-m32", "-nostdlib", "-static", "-ffreestanding", "-fno-pie", "-no-pie", "-O1",
                            "-fno-stack-protector", "-mno-sse", "-o", exe, os.path.join(tmp, "wharness.c")],
                           capture_output=True, text=True)
        if r.returncode != 0:
            pytest.skip("no 32-bit gcc: " + r.stderr[-200:])
        r = subprocess.run([exe], capture_output=True, text=True, timeout=30)
        assert r.returncode == 0, r.stdout


def _fake_storm_wavs(root):
    import wave
    os.makedirs(os.path.join(root, "wavs"), exist_ok=True)
    for orig in dllpatch.SHOWER_SOUNDS:
        w = wave.open(os.path.join(root, orig), "wb")
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(22050)
        w.writeframes(np.full(100, 20000, "<i2").tobytes())
        w.close()


def test_weather_any_mode():
    """Rain in deathmatch (a copy of its DLL that rains on this map), calm rain and quieter thunder (the copy's hook
    after AddShower, the map's own wavs at 40 %), kept by the weapons; off again: the game's DLL; and in DO the same
    weather through its copy (bomb time kept)."""
    import wave
    from test_batch7 import _st
    dm = _dll("dm.dll")
    with tempfile.TemporaryDirectory() as tmp:
        st = _st(tmp, "mp_dm_almacen.scn")
        _fake_storm_wavs(st.fs.root)
        st.fs.rescan()
        game_dll = os.path.join(tmp, "mp_deathMatch.dll")
        shutil.copyfile(dm, game_dll)
        st.scene.main_module_name = __import__("vtoy.binutil", fromlist=["VStr"]).VStr(b"mp_deathMatch.dll\0")
        st.custom_dlls = {"mp_deathmatch.dll": game_dll}
        w = st.weather_settings()
        assert w["kind"] == "other" and w["can"] and not w["rain"]
        msg = st.make_weather_dll(True, False, False, 40, 100)
        assert "without storm" in msg and "40 %" in msg
        stem = st.map_stem()
        w = st.weather_settings()
        assert w["rain"] and not w["storm"] and w["thunder"] == 40 and w["rain_vol"] == 100
        d = open(st.mode_dll_source(), "rb").read()
        assert dllpatch.weather_rain_map(d).lower() == f"nfos\\{stem}.opt".lower()
        names = dllpatch.shower_sounds(d)
        assert names[0] == "" and all(n.startswith(f"wavs/{stem}_40_") for n in names[1:])
        p = os.path.join(st.export_dir(), "wavs", os.path.basename(names[1]))
        a = np.frombuffer(wave.open(p).readframes(100), "<i2")
        assert a.max() == 8000                                      # 40 % of 20000
        st.make_weapons_dll([True, False, True, True, True])        # the weapons keep the weather
        d = open(st.mode_dll_source(), "rb").read()
        assert dllpatch.weapon_groups(d)[1] is False and dllpatch.weather_calm(d)
        assert dllpatch.weather_rain_map(d).lower() == f"nfos\\{stem}.opt".lower() and dllpatch.shower_volumes(d) == (40, 100)
        z = os.path.join(tmp, "m.zip")                              # the quieter thunder goes with the map
        st.save_map(); st.save_scene()
        st.export_map_zip(z)
        import zipfile
        assert ("wavs/" + os.path.basename(names[1])) in zipfile.ZipFile(z).namelist()
        st.make_weather_dll(True, True)                             # the storm, the game's sounds
        d = open(st.mode_dll_source(), "rb").read()
        assert not dllpatch.weather_calm(d) and dllpatch.shower_sound_names(d) == [] and st.weather_settings()["rain"]
        st.make_weather_dll(False)
        assert not st.weather_settings()["rain"]
    dtt = _dll("dtt.dll")
    with tempfile.TemporaryDirectory() as tmp:
        st = _st(tmp, "mp_do_laberinto.scn")
        if str(st.scene.main_module_name).rstrip("\0").lower() != "mp_destroythetarget.dll":
            pytest.skip("not the DO DLL")
        _fake_storm_wavs(st.fs.root)
        st.fs.rescan()
        game_dll = os.path.join(tmp, "mp_DestroyTheTarget.dll")
        shutil.copyfile(dtt, game_dll)
        st.custom_dlls = {"mp_destroythetarget.dll": game_dll}
        st.make_bomb_dll(40.0, True)
        st.make_weather_dll(True, True, True, 30, 70)
        w = st.weather_settings()
        assert w["kind"] == "DO" and w["rain"] and w["storm"] and w["splash"] and (w["thunder"], w["rain_vol"]) == (30, 70)
        d = open(st.mode_dll_source(), "rb").read()
        assert dllpatch.bomb_rules(d) == (40.0, True) and len(dllpatch.shower_sound_names(d)) == 7
        st.make_bomb_dll(30.0, False)                              # the bomb again: the quieter storm stays
        assert dllpatch.shower_volumes(open(st.mode_dll_source(), "rb").read()) == (30, 70)


def test_car_indestructible_and_back():
    """A car made scenery gets collision boxes that follow its shape (several: bonnet, cabin, boot - not one box round
    it all); back to a car that blows up: mp_CCar again and those boxes gone."""
    from test_batch7 import _st
    from vtoy import crop
    with tempfile.TemporaryDirectory() as tmp:
        st = _st(tmp, "mp_dm_vertigo.scn")
        cars = [r for r in st.scene.modules if r.clean_name == "mp_CCar" and r.parsed is not None]
        if not cars:
            pytest.skip("no car in this scene")
        car = cars[0]
        nb0 = len(crop.read_block(st.opt).boxes)
        boxes = st.car_boxes(car)
        assert len(boxes) >= 2
        tops = sorted(float(c[1] + h[1]) for c, h, _ax in boxes)
        assert tops[-1] - tops[0] > 10.0                          # not all the same height: low and high parts
        msg = st.car_to_scenery(car)
        assert "follow its shape" in msg and car.clean_name.lower() == "rendernfo" and st.is_car_scenery(car)
        assert len(crop.read_block(st.opt).boxes) == nb0 + len(boxes)
        msg = st.scenery_to_car(car)
        assert car.clean_name.lower() == "mp_ccar" and not st.is_car_scenery(car)
        assert len(crop.read_block(st.opt).boxes) == nb0, msg


def test_mesh_hd_one_by_one():
    """One mesh / prop of the map made HD (full detail at any distance) and back to the game's far versions, the
    others as they were."""
    from test_batch7 import _st
    with tempfile.TemporaryDirectory() as tmp:
        st = _st(tmp, "mp_dm_vertigo.scn")
        lod = [m for m in st.opt.meshes if len(m.lods) > 1]
        if len(lod) < 2:
            pytest.skip("no meshes with far versions here")
        one, other = lod[0], lod[1]
        n_other = len(other.lods)
        d = st.mesh_detail(one)
        assert len(d["lods"]) > 1 and not d["restorable"]
        assert "1 meshes" in st.full_detail_meshes([one])
        assert len(one.lods) == 1 and len(other.lods) == n_other and st.mesh_detail(one)["restorable"]
        st.restore_detail_meshes(True, [one])
        assert len(one.lods) == len(d["lods"]) and len(other.lods) == n_other


def test_lightmap_triangle_over_two_faces_is_cut():
    """An older import drew several faces of a plane with one polygon: a triangle of it lying on two faces of the .bsp
    is cut along them (one lightmap each - no stretched dark edge of one across the other); the back of a thin brush,
    in the same plane, is not one of them; water is drawn without the light."""
    from vtoy import bspimport, lightmap
    from vtoy.opt import VERTEX_DTYPE
    pl = bspimport.Plan(2.54, 0.0, (0.0, 0.0, 0.0), (0.0, 0.0, 0.0))
    sq = lambda x0, x1: np.array([[x0, 0, 0], [x1, 0, 0], [x1, 10, 0], [x0, 10, 0]], float)
    up, down = np.array([0.0, 0.0, 1.0]), np.array([0.0, 0.0, -1.0])
    info = [(sq(0, 10), up, 0.0, [0, 1], np.zeros(3)), (sq(10, 20), up, 0.0, [0, 1], np.zeros(3)),
            (sq(0, 20)[::-1], down, 0.0, [0, 1], np.zeros(3))]
    table = {}
    for fi, (p, n, d, _k, _o) in enumerate(info):
        table.setdefault((int(round(n[0] * 20)), int(round(n[1] * 20)), int(round(n[2] * 20)), int(round(d / 16))), []).append(fi)
    charts = {0: None, 1: None, 2: None}
    cs = np.array([[[0, 0, 0], [20, 0, 0], [0, 10, 0]]], float)
    tri = pl.point(cs.reshape(-1, 3)).reshape(1, 3, 3)
    rec = np.zeros((1, 3), VERTEX_DTYPE)
    rec["pos"] = tri
    rec["nrm"] = pl.direction(up)
    rec["uv"][0] = [[0, 0], [2, 0], [0, 1]]
    t2, r2, f2 = lightmap._cut_along_faces(pl, table, info, charts, tri, rec, np.array([0]))
    assert sorted(set(f2.tolist())) == [0, 1]
    area = lambda t: 0.5 * np.linalg.norm(np.cross(t[1] - t[0], t[2] - t[0]))
    assert abs(sum(area(t) for t in t2) - area(tri[0])) < 1e-6 * area(tri[0])
    back = lightmap.to_cs(pl, t2.reshape(-1, 3))                         # each piece on its own face
    for t, f in zip(back.reshape(-1, 3, 3), f2):
        assert (t[:, 0] >= (10 if f == 1 else 0) - 1e-6).all() and (t[:, 0] <= (20 if f == 1 else 10) + 1e-6).all()
        # the texture keeps its place: u = x / 10 on the whole triangle
    for t, r in zip(back.reshape(-1, 3, 3), r2):
        assert np.allclose(r["uv"][:, 0], t[:, 0] / 10.0, atol=1e-4)
    # inside its face: left as it is
    small = pl.point(np.array([[1, 1, 0], [9, 1, 0], [1, 9, 0]], float)).reshape(1, 3, 3)
    t3, _r3, f3 = lightmap._cut_along_faces(pl, table, info, charts, small, rec, np.array([0]))
    assert t3 is small and f3.tolist() == [0]
    assert lightmap._unlit_face(type("F", (), {"texture": "!waterblue"})()) and \
        not lightmap._unlit_face(type("F", (), {"texture": "bluewater"})())


def test_bsp_decals_lifted_and_beams_left_out():
    """de_dust2_cs2: decals one unit in front of a wall blinked in the game, a sunbeam (additive brush) was a dark
    see-through sheet.  A decal is drawn OVERLAY_GAP units off its wall, an additive brush not at all; a map made
    before gets the same (fix_bsp_overlays): decal triangles moved, beam triangles taken out; nothing else changes."""
    from test_batch13 import write_bsp, _box_faces
    from vtoy import bspfix, bspimport
    from vtoy.bsp import BspMap
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "dec.bsp")
        room = [(pts[::-1].copy(), -n, 0) for pts, n in _box_faces((0, 0, 0), (512, 512, 256)) if n[2] > -0.5]
        sign = [(np.array([[1, 100, 50], [1, 100, 150], [1, 200, 150], [1, 200, 50]], float), np.array([1.0, 0, 0]), 1)]
        beam = [(np.array([[300, 100, 0], [300, 100, 200], [300, 300, 200], [300, 300, 0]], float),
                 np.array([1.0, 0, 0]), 2),
                (np.array([[301, 100, 0], [301, 300, 0], [301, 300, 200], [301, 100, 200]], float),
                 np.array([-1.0, 0, 0]), 3)]
        write_bsp(p, [room, sign, beam], [("-0Sand", (128, 128)), ("{sign", (64, 64)), ("fade02", (64, 64)),
                                          ("black", (16, 16))],
                  [{"classname": "worldspawn"},
                   {"classname": "func_illusionary", "model": "*1", "rendermode": "4", "renderamt": "255"},
                   {"classname": "func_illusionary", "model": "*2", "rendermode": "5", "renderamt": "100"},
                   {"classname": "info_player_start", "origin": "200 200 40"},
                   {"classname": "info_player_deathmatch", "origin": "250 250 40"}])
        b = BspMap.load(p)
        si = next(i for i, f in enumerate(b.faces) if f.texture == "{sign")
        assert bspfix.overlay_shifts(b) == {si: pytest.approx(bspfix.OVERLAY_GAP - 1.0)}
        assert sorted(b.faces[i].texture for i in bspfix.hidden_faces(b)) == ["black", "fade02"]
        assert bspimport.invisible_entity({"rendermode": "5", "renderamt": "100"})
        pl = bspimport.plan(b)
        cv = bspimport.convert(b, pl, {}, None, lambda t: True, False)
        cv0 = bspimport.convert(b, pl, {}, None, lambda t: True, False, lift=False)
        from vtoy.lightmap import to_cs
        x_of = lambda c: [float(to_cs(pl, np.asarray(f[0]))[:, 0].mean()) for f in c.meshes[c.textures["{sign"]]
                          if abs(to_cs(pl, np.asarray(f[0]))[:, 1].mean() - 150) < 1]
        assert x_of(cv) == [pytest.approx(bspfix.OVERLAY_GAP)] and x_of(cv0) == [pytest.approx(1.0)]
        assert "fade02" not in cv.textures and "black" not in cv.textures and cv.overlays == 1
        # a map's triangles on the old sign / on the beam / on the wall
        tri = lambda q: pl.point(np.asarray(q, float))[None]
        T = np.concatenate([tri([[1, 110, 60], [1, 110, 140], [1, 190, 60]]),
                            tri([[300, 120, 10], [300, 120, 190], [300, 280, 10]]),
                            tri([[0, 300, 60], [0, 300, 140], [0, 400, 60]]),
                            tri([[4, 110, 60], [4, 110, 140], [4, 190, 60]])])
        assert bspfix.faces_under(b, pl, T, [si]).tolist() == [si, -1, -1, -1]
        hid = bspfix.faces_under(b, pl, T, bspfix.hidden_faces(b))
        assert hid[1] >= 0 and hid[0] == hid[2] == hid[3] == -1


def test_bomb_zone_takes_no_second_bomb():
    """All the zones to blow up: one already destroyed took a second bomb (one could plant there again).  The zones'
    code sets its radius to 0 until the round's reset (harness.c runs it); an older copy shows as outdated."""
    with tempfile.TemporaryDirectory() as tmp:
        c = os.path.join(tmp, "c.dll")
        dllpatch.patch_bomb_zones(_dll("dtt.dll"), c, ["bombZone_B"], True)
        d = open(c, "rb").read()
        assert dllpatch.bomb_zones_no_replant(d) and dllpatch.bomb_zones(d) == (["bombZone_B"], True)
        assert not dllpatch.bomb_zones_no_replant(open(_dll("dtt.dll"), "rb").read())


def test_big_meshes_cut():
    """mp_do_aztec closed the game after loading: an old import's mesh per texture had 7,837 vertices once lit (40
    bytes each).  split_big_meshes cuts a mesh over the limit in pieces of the map: the same triangles (the light too),
    the same collision; bsp_light does it by itself."""
    from test_batch7 import _st
    from vtoy import crop
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "arena.bsp")
        _lit_arena(p)
        st = _st(tmp, "mp_dm_almacen.scn")
        n0 = len(st.opt.meshes)
        st.import_bsp(p, (90000.0, 0.0, 90000.0), 90.0, 2.54, None, None, True, False, False)
        from vtoy import lightmap
        assert lightmap.lit_meshes(st.opt)                            # lit by the import

        def tris(o):
            out = []
            for me in o.meshes:
                for sm in me.render_submeshes():
                    q = sm.vertices["pos"].astype(np.float64)[sm.indices.reshape(-1, 3).astype(int)]
                    uvn = "uv2" if "uv2" in sm.vertices.dtype.names else "uv"
                    out += [tuple(np.round(np.sort(t, 0).ravel(), 3)) + tuple(np.round(np.sort(sm.vertices[uvn][i], 0).ravel(), 4))
                            for t, i in zip(q, sm.indices.reshape(-1, 3).astype(int))]
            return sorted(out)
        before = tris(st.opt)
        nb = len(crop.read_block(st.opt).boxes)
        biggest = max(len(me.lods[0].parts[0].submeshes[0].vertices) for me in st.opt.meshes[n0:])   # the import's
        most = max(4, biggest // 3)
        msg = st.split_big_meshes(most)
        assert "cut into" in msg, msg
        used = {pr.mesh_index for pr in st.opt.props}
        assert all(len(me.lods[0].parts[0].submeshes[0].vertices) <= most for i, me in enumerate(st.opt.meshes)
                   if i not in used and len(me.lods) == 1 and len(me.lods[0].parts) == 1
                   and len(me.lods[0].parts[0].submeshes) == 1 and me.lods[0].parts[0].submeshes[0].remap is None)
        assert tris(st.opt) == before and len(crop.read_block(st.opt).boxes) == nb
        assert "no mesh has more than" in st.split_big_meshes(most)
