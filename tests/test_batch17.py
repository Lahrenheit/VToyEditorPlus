"""Batch 17: CS maps - invisible walls of the crouching hull, steps without a riser, floors under ramps and under
solid entities, crouch lintels, and small brush faces lit nearly black."""
import numpy as np
import pytest
import _path

UP = np.array([0.0, 1.0, 0.0])


def _floor(x0, x1, z0, z1, y):
    return np.array([[x0, y, z0], [x0, y, z1], [x1, y, z1], [x1, y, z0]], float)


def _wall_z(z, x0, x1, y0, y1, toward=1.0):
    """A wall in the plane z = const facing +z (toward > 0) or -z."""
    return np.array([[x0, y0, z], [x1, y0, z], [x1, y1, z], [x0, y1, z]], float), np.array([0.0, 0.0, toward])


def test_wall_through_a_floor_cut_down():
    """de_inferno's banana: the crouching hull's empty pocket under the street had a wall standing 56 cm out of the
    floor across the whole street - an invisible wall for players and bullets.  A wall with the same floor on both
    sides of its top is cut down to that floor; a step (floors at its top and at its foot) and a wall with no floor
    behind it stay whole."""
    from vtoy import bspimport
    street = (_floor(-200, 200, -200, 200, 290.0), UP)
    w, n = _wall_z(0.0, -100, 100, -1000, 345.0)
    out, cut = bspimport.trim_pierced_walls([(street[0], street[1], 0, False), (w, n, 0, False)])
    assert cut == 1
    walls = [f for f in out if abs(f[1][1]) < 0.5]
    assert walls and max(f[0][:, 1].max() for f in walls) == pytest.approx(290.0)
    # a step: the upper floor behind the wall at its top, the lower one in front at its foot - untouched
    upper = (_floor(-200, 200, -200, 0, 30.0), UP)
    lower = (_floor(-200, 200, 0, 200, 0.0), UP)
    w2, n2 = _wall_z(0.0, -100, 100, 0.0, 30.0)
    out, cut = bspimport.trim_pierced_walls([(upper[0], upper[1], 0, False), (lower[0], lower[1], 0, False),
                                             (w2, n2, 0, False)])
    assert cut == 0


def test_crouch_lintel_dropped():
    """de_inferno's drain: CS players crawl under a lintel 1.3 m over the floor; a Torrente player cannot crouch, the
    lintel stopped him in a pit he had jumped into.  A wall hanging between crouching and standing height over a
    floor on both sides goes; a wall from the floor up, or hanging higher than a standing player, stays."""
    from vtoy import bspimport
    fl = (_floor(-300, 300, -300, 300, 0.0), UP, 0, False)
    lintel = _wall_z(0.0, -50, 50, 130.0, 200.0) + (0, False)
    wall = _wall_z(50.0, -50, 50, 0.0, 250.0) + (0, False)
    high = _wall_z(-50.0, -50, 50, 220.0, 300.0) + (0, False)
    out, n = bspimport.drop_hanging_walls([fl, lintel, wall, high])
    assert n == 1
    assert not any(f is lintel for f in out) and any(f is wall for f in out) and any(f is high for f in out)


def test_step_without_riser_gets_a_ramp():
    """A small step CS's hull left without a wall under its edge (de_inferno's drain: 10 cm; the first step of a
    staircase made as a func_wall: 20 cm) had no ramp and stopped the player.  The edge gets a ramp down onto the
    lower floor; edges with no floor below, or a drop higher than a step, get none."""
    from vtoy import bspimport
    upper = (_floor(-100, 0, -100, 100, 10.0), UP)
    lower = (_floor(-1, 200, -100, 100, 0.0), UP)
    out, made = bspimport.lip_ramps([upper, lower])
    assert made == 1
    ramp = out[-1][0]
    assert ramp[:, 1].max() == pytest.approx(10.0) and ramp[:, 1].min() == pytest.approx(0.0)
    assert ramp[:, 0].max() > 15.0                            # down onto the lower floor, away from the edge
    floors = [(p, p.min(0), p.max(0)) for p, n in out]
    prev = None
    for x in np.arange(100.0, -50.0, -1.0):                   # from the low floor up onto the high one, no lip
        hs = bspimport._floor_heights(floors, x, 0.0, -1, 11)
        assert hs
        h = max(hs)
        assert prev is None or h - prev <= 1.5, (x, h, prev)
        prev = h
    assert prev == pytest.approx(10.0)
    ledge = (_floor(-100, 0, -100, 100, 80.0), UP)
    assert bspimport.lip_ramps([ledge, lower])[1] == 0        # 80 cm: a ledge


def test_floor_under_a_ramp_and_a_solid_dropped():
    """de_cbble: the player sank into a staircase and walked about inside it - under each step's ramp lay the flat
    tread, and under the staircase (a func_wall) the street.  The part of a floor less than 85 cm under another goes;
    under the top of a solid entity, any depth down to the entity's bottom; a floor with room over it stays."""
    from vtoy import bspimport
    r = np.array([[0.0, 30, -50], [0, 30, 50], [60, 0, 50], [60, 0, -50]])
    n = np.cross(r[1] - r[0], r[3] - r[0])
    ramp = (r if n[1] > 0 else r[::-1].copy(), n / np.linalg.norm(n) * np.sign(n[1]))
    tread = (_floor(0, 100, -50, 50, 0.0), UP)
    out, cut = bspimport.drop_buried_floors([ramp, tread])
    assert cut == 1
    floors = [(p, p.min(0), p.max(0)) for p, n in out]
    assert bspimport._floor_heights(floors, 30.0, 0.0, -1, 0.5) == []        # no tread under the ramp
    assert bspimport._floor_heights(floors, 80.0, 0.0, -1, 0.5)              # past it: the floor
    room = [(_floor(0, 100, -50, 50, 0.0), UP), (_floor(0, 100, -50, 50, 250.0), UP)]
    assert bspimport.drop_buried_floors(room)[1] == 0
    street = (_floor(-200, 200, -200, 200, 0.0), UP)
    top = _floor(-50, 50, -50, 50, 150.0)
    out, cut = bspimport.drop_buried_floors([street, (top, UP)], solids=[(top, UP, 0.0)])
    floors = [(p, p.min(0), p.max(0)) for p, n in out]
    assert cut == 1 and bspimport._floor_heights(floors, 0.0, 0.0, -1, 1) == []
    assert bspimport._floor_heights(floors, 100.0, 0.0, -1, 1)
    hanging = [(street[0], UP), (top, UP)]                    # a bridge 1.5 m up (its bottom high): the street stays
    assert bspimport.drop_buried_floors(hanging, solids=[(top, UP, 120.0)])[1] == 0


def test_small_faces_not_black():
    """de_inferno's blue barrels: a side lit by CS nearly black next to a bright one.  A small face takes at least
    0.55 x the usual light of the faces around it; one in a dark corner (all dark) stays dark."""
    from types import SimpleNamespace
    from vtoy import lightmap

    def face(c, size=10.0):
        c = np.asarray(c, float)
        return SimpleNamespace(points=np.array([c, c + [size, 0, 0], c + [size, 0, size], c + [0, 0, size]]))

    def chart(v):
        return SimpleNamespace(rgb=np.full((2, 2, 3), float(v)))
    bsp = SimpleNamespace(faces=[face((0, 0, 0)), face((12, 0, 0)), face((24, 0, 0)), face((36, 0, 0)),
                                 face((500, 0, 0)), face((512, 0, 0)), face((524, 0, 0))])
    charts = {0: chart(20), 1: chart(140), 2: chart(130), 3: chart(150), 4: chart(10), 5: chart(12), 6: chart(14)}
    n = lightmap.lift_small_faces(bsp, charts, list(range(7)))
    assert n == 1
    assert charts[0].rgb.mean() >= 0.55 * 130 - 1 and charts[1].rgb.mean() == 140
    assert charts[4].rgb.mean() == 10                         # dark corner: stays


def test_traps_closed_with_a_wall():
    """de_inferno's drain: a pit one jumps into and CS players crawl out of; Torrente's player stayed in it.  The
    edge where one drops into a place he cannot walk out of gets invisible collision boxes; no trap, no box."""
    import tempfile
    from vtoy import crop, hmcopy
    from vtoy.walk import World
    from test_batch7 import _st
    up = (0.0, 1.0, 0.0)

    def wall(p, toward):
        return hmcopy.make_face(np.asarray(p, float), toward)
    faces = [hmcopy.make_face(_floor(0, 1000, 0, 600, 0.0), up), hmcopy.make_face(_floor(1000, 1300, 0, 600, -200.0), up),
             wall([[1300, -200, 0], [1300, -200, 600], [1300, 300, 600], [1300, 300, 0]], (-1, 0, 0)),
             wall([[1000, -200, 0], [1300, -200, 0], [1300, 300, 0], [1000, 300, 0]], (0, 0, 1)),
             wall([[1000, -200, 600], [1300, -200, 600], [1300, 300, 600], [1000, 300, 600]], (0, 0, -1))]
    with tempfile.TemporaryDirectory() as tmp:
        st = _st(tmp)
        st.walk_world = lambda: World(faces)
        st.spawn_positions = lambda: {0: [("a", np.array([100.0, 5.0, 300.0]))]}
        boxes, msg = st.trap_boxes()
        assert boxes and "1 traps closed" in msg
        xs = np.array([c[0] for c, h, R in boxes])
        assert xs.min() > 960 and xs.max() < 1040                 # on the pit's edge
        n0 = len(crop.read_block(st.opt).boxes)
        st.apply_trap_boxes(boxes, msg)
        assert len(crop.read_block(st.opt).boxes) == n0 + len(boxes)
        flat = [hmcopy.make_face(_floor(0, 1000, 0, 600, 0.0), up)]
        st.walk_world = lambda: World(flat)
        assert st.trap_boxes()[0] == []


def test_decal_over_decal_keeps_its_order():
    """de_cbble's banner: 2 units off the wall over a plaster sheet 1 unit off - both were moved to 4 units, the banner
    blinked.  Each decal ends OVERLAY_GAP off its wall, one laid over another 2 units in front of it: 4 and 6."""
    import os
    import tempfile
    from test_batch13 import write_bsp, _box_faces
    from vtoy import bspfix
    from vtoy.bsp import BspMap
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "dec2.bsp")
        room = [(pts[::-1].copy(), -n, 0) for pts, n in _box_faces((0, 0, 0), (512, 512, 256)) if n[2] > -0.5]
        sheet = [(np.array([[1, 50, 20], [1, 50, 200], [1, 300, 200], [1, 300, 20]], float), np.array([1.0, 0, 0]), 1)]
        banner = [(np.array([[2, 100, 50], [2, 100, 150], [2, 200, 150], [2, 200, 50]], float), np.array([1.0, 0, 0]), 2)]
        write_bsp(p, [room, sheet, banner], [("-0Sand", (128, 128)), ("{sheet", (64, 64)), ("{banner", (64, 64))],
                  [{"classname": "worldspawn"},
                   {"classname": "func_illusionary", "model": "*1", "rendermode": "4", "renderamt": "255"},
                   {"classname": "func_illusionary", "model": "*2", "rendermode": "4", "renderamt": "255"},
                   {"classname": "info_player_start", "origin": "200 200 40"}])
        b = BspMap.load(p)
        si = next(i for i, f in enumerate(b.faces) if f.texture == "{sheet")
        bi = next(i for i, f in enumerate(b.faces) if f.texture == "{banner")
        g = bspfix.OVERLAY_GAP
        sh = bspfix.overlay_shifts(b)
        assert sh[si] + 1 == pytest.approx(g) and sh[bi] + 2 == pytest.approx(g + 2)
        old = bspfix.overlay_shifts(b, layered=False)
        assert old[si] + 1 == pytest.approx(g) and old[bi] + 2 == pytest.approx(g)        # what blinked
        # a decal beside the sheet (not over it), 2 units off the wall: just OVERLAY_GAP off, like before
        p2 = os.path.join(tmp, "dec3.bsp")
        side = [(np.array([[2, 350, 50], [2, 350, 150], [2, 450, 150], [2, 450, 50]], float), np.array([1.0, 0, 0]), 2)]
        write_bsp(p2, [room, sheet, side], [("-0Sand", (128, 128)), ("{sheet", (64, 64)), ("{banner", (64, 64))],
                  [{"classname": "worldspawn"},
                   {"classname": "func_illusionary", "model": "*1", "rendermode": "4", "renderamt": "255"},
                   {"classname": "func_illusionary", "model": "*2", "rendermode": "4", "renderamt": "255"},
                   {"classname": "info_player_start", "origin": "200 200 40"}])
        b2 = BspMap.load(p2)
        bi2 = next(i for i, f in enumerate(b2.faces) if f.texture == "{banner")
        assert bspfix.overlay_shifts(b2)[bi2] + 2 == pytest.approx(g)
