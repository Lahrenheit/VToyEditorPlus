"""Batch 15: bars and railings bullets fly through, thin slabs drawn once, faces drawn in part."""
import os
import tempfile
import _path

import numpy as np
import pytest


class _Solid:
    """A stand-in for a hull of a .bsp: solid where ``f`` says so."""

    def __init__(self, f):
        self.f = f

    def solid(self, head, P):
        P = np.asarray(P, np.float64).reshape(-1, 3)
        return np.array([bool(self.f(p)) for p in P])


def _window(bars=True):
    """A window 100 wide, 64 high in a wall on y = 0 .. 8 (facing -y), vertical bars 2 thick every 12 units; the
    clip hull (the player's box grown 16 units) fills it all."""
    def real(p):
        x, y, z = p
        if not (0 <= y <= 8):
            return False
        if x < 0 or x > 100 or z < 0 or z > 64:
            return True                                           # the wall round the window
        return bars and y <= 2 and any(10 + 12 * k <= x <= 12 + 12 * k for k in range(8))
    clip = lambda p: -16 <= p[1] <= 24
    q = np.array([[0, 0, 0], [100, 0, 0], [100, 0, 64], [0, 0, 64]], float)[::-1].copy()
    return _Solid(real), _Solid(clip), q


def test_bars_let_bullets_through_the_gaps():
    """de_mirage_cs2: bullets stopped at a window's bars and a railing (the clip hull fills gaps narrower than a player,
    the collision is one slab).  The wall is cut down to the bars: what stays is real solid; the gaps are open."""
    from vtoy import bspgrille
    real, clip, q = _window()
    half = np.array([16.0, 16.0, 18.0])
    parts = bspgrille.open_wall(real, 0, clip, 0, q, np.array([0.0, -1.0, 0.0]), half)
    assert parts is not None
    xs = sorted({(round(P[:, 0].min()), round(P[:, 0].max())) for P, _bar in parts})
    assert len(parts) == 8 and all(b - a <= 3 for a, b in xs)           # the eight bars, nothing else
    for P, _bar in parts:
        assert np.allclose(P[:, 1], 0.0) and P[:, 2].min() == pytest.approx(0) and P[:, 2].max() == pytest.approx(64)
        assert float(np.cross(P[1] - P[0], P[2] - P[0]) @ np.array([0.0, -1.0, 0.0])) > 0
    # no bars: nothing real in the opening - an invisible CLIP brush: it stays as it is
    real0, clip0, q0 = _window(bars=False)
    assert bspgrille.open_wall(real0, 0, clip0, 0, q0, np.array([0.0, -1.0, 0.0]), half) is None
    # a clip brush over a low wall: open above, but nothing real above it - it stays
    low = _Solid(lambda p: 0 <= p[1] <= 8 and p[2] <= 20)
    assert bspgrille.open_wall(low, 0, clip0, 0, q0, np.array([0.0, -1.0, 0.0]), half) is None


def test_railing_gaps_between_pipes():
    """A railing on a low wall: pipes along it (gaps lower than the crouching player) - the low wall and the pipes stay,
    the gaps between them open; the pipes up in the air are bars (a box however low)."""
    from vtoy import bspgrille

    def real(p):
        x, y, z = p
        if not (0 <= y <= 3) or not (0 <= x <= 200):
            return False
        return z <= 30 or 58 <= z <= 61 or 88 <= z <= 91 or x <= 3 or x >= 197
    clip = _Solid(lambda p: -16 <= p[1] <= 19 and -16 <= p[0] <= 216 and p[2] <= 109)
    q = np.array([[0, 0, 0], [200, 0, 0], [200, 0, 91], [0, 0, 91]], float)[::-1].copy()
    parts = bspgrille.open_wall(_Solid(real), 0, clip, 0, q, np.array([0.0, -1.0, 0.0]), np.array([16.0, 16, 18]))
    assert parts is not None
    area = sum(0.5 * np.linalg.norm(sum(np.cross(P[k] - P[0], P[k + 1] - P[0]) for k in range(1, len(P) - 1)))
               for P, _b in parts)
    want = 200 * 31 + 2 * (200 * 3) + 2 * (4 * (57 - 31) + 4 * (88 - 62))   # low wall, two pipes, two posts
    assert area == pytest.approx(want, rel=0.06)
    assert any(bar for P, bar in parts if P[:, 2].min() > 50)            # a pipe: a bar
    assert not any(bar for P, bar in parts if P[:, 2].min() < 0.5)       # the low wall is not


def test_thin_slab_one_face_drawn():
    """de_dust2_cs2: straw under the roofs, fences, carvings blinked - two faces of a thin slab (or a see-through world
    brush: two faces on one plane back to back) both drawn, the game draws each from both sides.  One of each pair is
    left out: the one looking at the wall next to it."""
    from test_batch13 import write_bsp, _box_faces
    from vtoy import bspfix, bspimport
    from vtoy.bsp import BspMap
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "thin.bsp")
        room = [(pts[::-1].copy(), -n, 0) for pts, n in _box_faces((0, 0, 0), (512, 512, 256)) if n[2] > -0.5]
        sheet = [np.array([[200, 100, 0], [200, 100, 100], [200, 300, 100], [200, 300, 0]], float),
                 np.array([[202, 100, 0], [202, 300, 0], [202, 300, 100], [202, 100, 100]], float)]
        world = room + [(sheet[0], np.array([-1.0, 0, 0]), 1), (sheet[1], np.array([1.0, 0, 0]), 1)]
        carve = [(np.array([[1, 100, 50], [1, 100, 150], [1, 200, 150], [1, 200, 50]], float), np.array([1.0, 0, 0]), 2),
                 (np.array([[1, 100, 50], [1, 200, 50], [1, 200, 150], [1, 100, 150]], float), np.array([-1.0, 0, 0]), 2)]
        write_bsp(p, [world + carve], [("-0Sand", (128, 128)), ("fence", (64, 64)), ("{kasbah", (64, 64))],
                  [{"classname": "worldspawn"}, {"classname": "info_player_start", "origin": "300 300 40"}])
        b = BspMap.load(p)
        thin = bspfix.thin_backs(b)
        got = sorted((b.faces[i].texture, tuple(np.round(b.faces[i].normal, 3))) for i in thin)
        assert got[0][0] == "fence" and got[1] == ("{kasbah", (-1.0, 0.0, 0.0)), got   # the one facing the wall
        assert len(got) == 2
        ka = next(i for i, f in enumerate(b.faces) if f.texture == "{kasbah" and f.normal[0] > 0)
        assert bspfix.overlay_shifts(b) == {ka: pytest.approx(bspfix.OVERLAY_GAP - 1.0)}   # a world decal moves out
        pl = bspimport.plan(b)
        cv = bspimport.convert(b, pl, {}, None, lambda t: True, False)
        cv0 = bspimport.convert(b, pl, {}, None, lambda t: True, False, thin=False)
        assert cv.thin == 2 and sum(map(len, cv.meshes.values())) == sum(map(len, cv0.meshes.values())) - 2


def test_face_drawn_in_part_gets_the_rest():
    """de_dust2_cs2's crate behind the pallet: an older import drew only part of a face - the sky showed through the
    rest.  uncovered_parts gives the missing piece (a little over the drawn part, never a slit), with its uv."""
    from vtoy import bspimport
    P = np.array([[0, 0, 0], [100, 0, 0], [100, 80, 0], [0, 80, 0]], float)
    uv = P[:, :2] / 100.0
    n = np.array([0.0, 0.0, 1.0])
    drawn = np.array([[[0, 0, 0], [100, 0, 0], [100, 40, 0]], [[0, 0, 0], [100, 40, 0], [0, 40, 0]]], float)
    parts = bspimport.uncovered_parts([(P, n, uv)], drawn)
    assert parts
    lo = min(Q[:, 1].min() for _i, Q, _uv in parts)
    assert 35 <= lo <= 40
    area = sum(0.5 * np.linalg.norm(sum(np.cross(Q[k] - Q[0], Q[k + 1] - Q[0]) for k in range(1, len(Q) - 1)))
               for _i, Q, _uv in parts)
    assert 100 * 40 <= area <= 100 * 46
    for _i, Q, w in parts:
        assert np.allclose(w, Q[:, :2] / 100.0)
    assert not bspimport.uncovered_parts([(P, n, uv)], np.concatenate([drawn, drawn + [0, 40, 0]]))


def test_water_only_its_surface():
    """de_aztec: the river still blinked - a map made before draws every face of the water (the underside of its
    surface on the same plane, its bottom on the bed, its sides on the banks).  hidden_faces lists all but the top, so
    fix_bsp_overlays takes their triangles out; water in the world ("!" textures) keeps only the faces looking up."""
    from test_batch13 import write_bsp, _box_faces
    from vtoy import bspfix, bspimport
    from vtoy.bsp import BspMap
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "water.bsp")
        room = [(pts[::-1].copy(), -n, 0) for pts, n in _box_faces((0, 0, 0), (512, 512, 256)) if n[2] > -0.5]
        top = np.array([[100, 100, 16], [300, 100, 16], [300, 300, 16], [100, 300, 16]], float)
        water = [(top, np.array([0.0, 0, 1]), 1), (top[::-1].copy(), np.array([0.0, 0, -1]), 1),
                 (np.array([[100, 100, 0], [100, 300, 0], [300, 300, 0], [300, 100, 0]], float), np.array([0.0, 0, -1]), 1)]
        write_bsp(p, [room + water], [("-0Sand", (128, 128)), ("!river", (64, 64))],
                  [{"classname": "worldspawn"}, {"classname": "info_player_start", "origin": "400 400 40"}])
        b = BspMap.load(p)
        hid = bspfix.hidden_faces(b)
        assert sorted((b.faces[i].texture, float(b.faces[i].normal[2])) for i in hid) == [("!river", -1.0)] * 2
        up = next(f for f in b.faces if f.texture == "!river" and f.normal[2] > 0)
        assert bspimport.water_face_drawn(b, up, None)
        cv = bspimport.convert(b, bspimport.plan(b), {}, None, lambda t: True, False)
        assert len(cv.meshes[cv.textures["!river"]]) == 1


def test_decal_edges_left_out():
    """fy_pool_day: beside the rules sign a black strip - the sign moved off its wall, its 1-unit edges (lit black)
    stayed at the wall.  The edges of a brush that is all decal (thin across) are left out with it."""
    from test_batch13 import write_bsp, _box_faces
    from vtoy import bspfix, bspimport
    from vtoy.bsp import BspMap
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "sign.bsp")
        room = [(pts[::-1].copy(), -n, 0) for pts, n in _box_faces((0, 0, 0), (512, 512, 256)) if n[2] > -0.5]
        sign = [(pts, n, 1) for pts, n in _box_faces((0, 100, 50), (1, 200, 150))]       # 1 unit thick, on x = 0
        write_bsp(p, [room, sign], [("-0Sand", (128, 128)), ("rules", (64, 64))],
                  [{"classname": "worldspawn"}, {"classname": "func_illusionary", "model": "*1"},
                   {"classname": "info_player_start", "origin": "300 300 40"}])
        b = BspMap.load(p)
        front = [i for i in bspfix.overlay_shifts(b)]
        assert len(front) == 1 and b.faces[front[0]].normal[0] > 0.9
        sides = bspfix.decal_sides(b)
        assert len(sides) == 5 and sum(abs(b.faces[i].normal[0]) < 0.1 for i in sides) == 4   # its 4 edges
        assert sum(b.faces[i].normal[0] < -0.9 for i in sides) == 1                              # and its back
        cv = bspimport.convert(b, bspimport.plan(b), {}, None, lambda t: True, False)
        assert len(cv.meshes[cv.textures["rules"]]) == 1                                  # the front only


def test_more_starts_for_a_team():
    """de_inferno_go: 9 counter-terrorist and 11 terrorist starts for 16 a side.  The rest are made beside the team's
    own: on the floor, room round each, apart from each other, a walk away from the others - none in a wall, a pit
    or on the other side of a wall."""
    from vtoy import bspimport

    class _Hull:                                    # a floor at z 0, a wall at x 300..316, a pit at y > 400
        def head(self, m):
            return m

        def solid(self, head, P):
            P = np.asarray(P, np.float64).reshape(-1, 3)
            if head:
                return np.zeros(len(P), bool)
            x, y, z = P[:, 0] , P[:, 1], P[:, 2]
            floor = (z - 36 <= 0) & (y <= 400)
            wall = (x >= 300 - 16) & (x <= 316 + 16)
            return floor | wall

    class _B:
        entities = [{"classname": "worldspawn"}]
    have = [[100.0 + 60 * k, 100.0, 37.0] for k in range(3)]
    more = bspimport.more_starts(_B(), have, 8, hull=_Hull())
    assert len(more) == 5
    allp = np.array(have + [list(p) for p in more])
    for p in more:
        assert p[0] < 300 - 16 - 24 and p[1] <= 400 - 24 and abs(p[2] - 36.5) < 1.01
    d = np.linalg.norm(allp[:, None, :2] - allp[None, :, :2], axis=2) + np.eye(len(allp)) * 1e9
    assert d.min() >= 56
    assert bspimport.more_starts(_B(), have, 3, hull=_Hull()) == []


def test_crate_bottom_on_the_ground_left_out():
    """de_cbble_csgo: dark patches blinking on the ground by the crates - a func_wall crate's bottom lies on the
    world's floor, face to face; Torrente draws both from both sides.  The bottom goes (pressed on solid), the floor
    stays, so does a crate's side in the open and a crate on a see-through grate."""
    from test_batch13 import write_bsp, _box_faces
    from vtoy import bspfix, bspimport
    from vtoy.bsp import BspMap

    class _Hull0:                                   # the world: solid below z 0; model 1: the crate; 2: the grate's crate
        models = [0, 1, 2, 3]

        def head(self, m):
            return m

        def contents(self, head, P):
            P = np.asarray(P, np.float64).reshape(-1, 3)
            if head == 0:
                s = (P[:, 2] < 0) | ((P[:, 2] < 64) & (P[:, 0] >= 300) & (P[:, 0] <= 400) & (P[:, 1] >= 100)
                                       & (P[:, 1] <= 200) & (P[:, 2] > 60))
            elif head == 1:
                s = (P[:, 0] > 100) & (P[:, 0] < 164) & (P[:, 1] > 100) & (P[:, 1] < 164) & (P[:, 2] > 0) & (P[:, 2] < 64)
            elif head == 2:
                s = (P[:, 0] > 320) & (P[:, 0] < 384) & (P[:, 1] > 120) & (P[:, 1] < 184) & (P[:, 2] > 64) & (P[:, 2] < 128)
            else:
                s = np.zeros(len(P), bool)
            return np.where(s, -2, -1)

    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "crate.bsp")
        room = [(pts[::-1].copy(), -n, 0) for pts, n in _box_faces((0, 0, 0), (512, 512, 256)) if n[2] < 0.5]
        grate = [(pts, n, 3) for pts, n in _box_faces((300, 100, 60), (400, 200, 64)) if n[2] > 0.5]
        crate = [(pts, n, 1) for pts, n in _box_faces((100, 100, 0), (164, 164, 64))]
        crate2 = [(pts, n, 1) for pts, n in _box_faces((320, 120, 64), (384, 184, 128))]
        write_bsp(p, [room + grate, crate, crate2], [("-0Sand", (128, 128)), ("crate", (64, 64)), ("x", (8, 8)),
                                                      ("{grate", (64, 64))],
                  [{"classname": "worldspawn"}, {"classname": "func_wall", "model": "*1"},
                   {"classname": "func_wall", "model": "*2"},
                   {"classname": "info_player_start", "origin": "300 300 40"}])
        b = BspMap.load(p)
        got = bspfix.buried_faces(b, tree=_Hull0())
        assert [(b.faces[i].model, tuple(np.round(b.faces[i].normal, 3))) for i in got] == [(1, (0.0, 0.0, -1.0))]


def test_model_leaves_drawn_once():
    """de_inferno_go: the yuccas, poplars and lamps are two triangles back to back (two-sided cards); Torrente draws
    each from both sides and the pair fights.  One of each pair stays."""
    from vtoy import bspfix
    a = np.array([[0, 0, 0], [10, 0, 0], [0, 10, 0]], float)
    b = np.array([[5, 5, 1], [9, 5, 1], [5, 9, 1]], float)
    P = np.array([a, a[::-1], b, a + 0.001, b[[1, 2, 0]]])
    assert bspfix.twin_triangles(P).tolist() == [False, True, False, True, True]
