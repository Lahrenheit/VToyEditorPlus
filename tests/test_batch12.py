"""Batch 12: collision goes with its object, copies of a whole group, weapons one by one, start points on the floor,
shapes, meshes turned / scaled along their own axes."""
import os, tempfile
import _path
import numpy as np
from test_batch7 import _st
from vtoy import carry, hmcopy, meshbox, shapes
from vtoy.app.state import Selection
from vtoy.opt import OptMap


def _solid_mesh(st):
    """A box made with the shapes tool: a mesh with its own boxes and .hm faces."""
    sp = np.array(next(p for lst in st.spawn_positions().values() for _n, p in lst), np.float64)
    at = sp + [2000.0, 0.0, 2000.0]
    st.add_shape("box", (200.0, 150.0, 300.0), at, 0.0, "tablones.tex", 128.0, True)
    return st.selection, at


def _count(st, lo, hi):
    hm = st.heightmap_edit()
    b, f = carry.collect(st.opt, hm, lo, hi)
    return len(b), len(f)


def test_collision_goes_with_the_object():
    with tempfile.TemporaryDirectory() as tmp:
        st = _st(tmp)
        sel, at = _solid_mesh(st)
        lo, hi = st.fresh_bounds(sel)
        nb, nf = _count(st, lo, hi)
        assert nb >= 1 and nf >= 5
        total_b = len(meshbox.map_boxes(st.opt))
        # move
        st.set_position(sel, st.position_of(sel) + [500.0, 0.0, 0.0])
        assert _count(st, lo, hi) == (0, 0)
        lo2, hi2 = st.fresh_bounds(sel)
        assert _count(st, lo2, hi2) == (nb, nf) and len(meshbox.map_boxes(st.opt)) == total_b
        # turn 90 degrees: the box turns with it
        st.set_rotation(sel, (0.0, 90.0, 0.0))
        lo3, hi3 = st.fresh_bounds(sel)
        assert np.allclose(hi3 - lo3, [300, 150, 200], atol=1) and _count(st, lo3, hi3) == (nb, nf)
        # scale along its own axes (not the same in each)
        st.set_scale(sel, (2.0, 1.0, 1.0))
        lo4, hi4 = st.fresh_bounds(sel)
        assert np.allclose(hi4 - lo4, [300, 150, 400], atol=1) and _count(st, lo4, hi4) == (nb, nf)
        assert np.allclose(st.scale_of(sel), (2, 1, 1))
        # copy: the copy has its own collision
        new = st.duplicate_selection(sel, (0.0, 0.0, 1500.0))
        lo5, hi5 = st.fresh_bounds(new)
        assert _count(st, lo5, hi5) == (nb, nf) and len(meshbox.map_boxes(st.opt)) == total_b + nb
        # delete: its boxes and its .hm faces go too
        st.delete_selection(new)
        assert _count(st, lo5, hi5) == (0, 0) and len(meshbox.map_boxes(st.opt)) == total_b
        # switched off: only the drawing moves
        st.set_carry(False)
        st.set_position(sel, st.position_of(sel) + [0.0, 0.0, 800.0])
        assert _count(st, lo4, hi4) == (nb, nf)
        st.set_carry(True)
        st.save_map()
        OptMap.load(st.opt.path)


def test_group_move_moves_each_collision_once():
    with tempfile.TemporaryDirectory() as tmp:
        st = _st(tmp)
        a, at = _solid_mesh(st)
        st.add_shape("box", (60.0, 60.0, 60.0), at + [0.0, 150.0, 0.0], 0.0, "tablones.tex", 128.0, True)   # on top, inside
        b = st.selection
        lo, hi = st.fresh_bounds(a)
        lo = np.minimum(lo, st.fresh_bounds(b)[0]); hi = np.maximum(hi, st.fresh_bounds(b)[1])
        n = _count(st, lo, hi)
        st.selection, st.multi = a, [a, b]
        st.group_move((0.0, 0.0, 1000.0), True)
        assert _count(st, lo + [0, 0, 1000], hi + [0, 0, 1000]) == n and _count(st, lo, hi) == (0, 0)


def test_start_points_on_the_floor_and_shapes():
    with tempfile.TemporaryDirectory() as tmp:
        st = _st(tmp)
        rec = next(r for r in st.scene.modules if r.clean_name.lower() == "mp_cstartpoint")
        st.set_locked(rec, False)
        x, y, z = rec.parsed.position
        floor = st.floor_below(x, z, y + 60)
        rec.parsed.position = (x, y + 300.0, z)
        assert "1 of 1" in st.spawns_to_floor([rec])
        assert abs(rec.parsed.position[1] - (st.floor_below(x, z, y + 400) + 20.0)) < 0.5
        assert "start points put on the floor" in st.spawns_to_floor()
        # shapes: every kind, and by points
        sp = np.array(rec.parsed.position)
        for k in shapes.KINDS:
            msg = st.add_shape(k, None, sp + [3000.0, 0, 0], 30.0, "tablones.tex", 128.0, True)
            assert k in msg and "triangles" in msg
        pts = [sp + d for d in ([0, 0, 0], [400, 0, 0], [400, 0, 400], [200, 0, 150], [0, 0, 400])]      # concave
        msg = st.add_shape("polygon", points=pts, height=120.0, texture="tablones.tex")
        assert "polygon" in msg
        tris = shapes.triangles(shapes.from_points("polygon", pts, 120.0))
        area = sum(0.5 * abs(np.cross(t[1] - t[0], t[2] - t[0])[1]) for t in tris if np.ptp(t[:, 1]) < 1e-6 and t[0, 1] > sp[1] + 1)
        assert abs(area - (400 * 400 - 0.5 * 400 * 250)) < 1.0                       # the notch is left out
        assert "rect" in st.add_shape("rect", points=pts[:3:2], height=50.0, texture="tablones.tex")
        st.add_shape("circle", points=[pts[0], pts[1]], height=30.0, texture="tablones.tex", sides=12)
        try:
            st.add_shape("polygon", points=pts[:2], height=50.0, texture="tablones.tex")
            assert False
        except ValueError:
            pass
        st.save_map()
        OptMap.load(st.opt.path)


def test_weapons_one_by_one():
    from vtoy import dllpatch
    src = os.path.join(os.path.dirname(os.environ.get("VTOY_FLAG_DLL", "")), "ctf.dll")
    if not os.path.isfile(src):
        return
    with tempfile.TemporaryDirectory() as tmp:
        a = os.path.join(tmp, "a.dll")
        # knife, pistol and the rifle only
        assert dllpatch.patch_weapon_groups(src, a, [1, 1, 1, 0, 0], [0, 0, 8, 0, 0]) == [True, True, True, False, False]
        data = open(a, "rb").read()
        assert dllpatch.weapon_choice(data) == [0, 0, 8, 0, 0]
        s = dllpatch._weapon_sites(data)
        assert data[s["hands_id"]] == 0xb8 and data[s["hands_id"] + 1] == 8                 # the rifle in his hands
        # knife, pistol and the machine gun
        b = os.path.join(tmp, "b.dll")
        dllpatch.patch_weapon_groups(src, b, [1, 1, 0, 1, 0], [0, 0, 0, 11, 0])
        assert dllpatch.weapon_choice(open(b, "rb").read()) == [0, 0, 0, 11, 0]
        # from a fixed copy to another choice; back to everything from the game's DLL = the same bytes
        c = os.path.join(tmp, "c.dll")
        dllpatch.patch_weapon_groups(a, c, [1, 1, 1, 0, 0], [0, 0, 16, 0, 0])
        assert dllpatch.weapon_choice(open(c, "rb").read())[2] == 16
        d = os.path.join(tmp, "d.dll")
        dllpatch.patch_weapon_groups(src, d, [1] * 5)
        assert open(d, "rb").read() == open(src, "rb").read()
        try:
            dllpatch.patch_weapon_groups(src, d, [1] * 5, [0, 0, 11, 0, 0])            # the machine gun is not of group 3
            assert False
        except ValueError:
            pass
