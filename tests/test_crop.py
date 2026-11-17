"""Outline crop: cross references (sector lists, indices) stay valid; polygon / tool maths."""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _path import DATA                      # noqa: E402
from vtoy import crop                       # noqa: E402
from vtoy.app import tools                  # noqa: E402
from vtoy.opt import OptMap                 # noqa: E402

TJ = os.environ.get("VTOY_TJ_DATA", os.path.join(os.path.dirname(DATA), "tj"))


def check_consistent(m: OptMap):
    q = OptMap.parse(m.to_bytes())
    assert q.to_bytes() == m.to_bytes()
    blk = crop.read_block(q)
    n_obj = len(q.meshes) + len(q.props) + len(q.decals)
    assert q.scene_obj_count == n_obj
    assert all(i < n_obj for s in blk.sectors for i in s.objs)
    assert all(i < len(blk.boxes) for s in blk.sectors for i in s.boxes)
    assert all(i < len(blk.polys) for s in blk.sectors for i in s.hulls)
    assert all(0 <= p.mesh_index < len(q.meshes) for p in q.props)
    assert all(me.lods and all(l.parts for l in me.lods) for me in q.meshes)
    return q


def test_polygon():
    sq = [(0, 0), (10, 0), (10, 10), (0, 10)]
    r = crop.points_in_polygon(np.array([[5, 5], [11, 5], [-1, 3], [9.9, 0.1]]), sq)
    assert r.tolist() == [True, False, False, True]


def test_tools_maths():
    o = np.array([0.0, 100.0, 0.0]); d = np.array([0.0, -1.0, 0.0])
    assert np.allclose(tools.ray_plane_y(o, d, 10.0), [0, 10, 0])
    assert tools.ray_plane_y(o, np.array([1.0, 0, 0]), 10.0) is None
    dl = tools.move_delta("X", [0, 0, 0], [5, 0, 7], 0, 1)
    assert dl.tolist() == [5, 0, 0] and tools.move_delta("Y", [0, 0, 0], [0, 0, 0], -10, 2)[1] == 20
    assert tools.rotate_delta("X", 10, 4)[0] == 2 and tools.rotate_delta("Z", 10, 4)[2] == 5
    g = tools.gizmo([0, 0, 0], [100, 100, 100])
    assert tools.hit_handle(np.array([g["X"][1][0], 500.0, 0]), d, [0, 0, 0], [100, 100, 100]) == "X"
    assert tools.display_to_engine([1, 2, 3]).tolist() == [1, 2, -3]


def test_crop_malibu():
    path = os.path.join(TJ, "nfos", "nfos", "Malibu.opt")
    if not os.path.exists(path):
        path = os.path.join(TJ, "nfos", "Malibu.opt")
    if not os.path.exists(path):
        print("  (no Torrente el juego data: skipped)"); return
    m = OptMap.load(path)
    c = np.concatenate([me.corners for me in m.meshes]); lo, hi = c.min(0), c.max(0)
    cx, cz, w, h = (lo[0] + hi[0]) / 2, (lo[2] + hi[2]) / 2, (hi[0] - lo[0]) / 6, (hi[2] - lo[2]) / 6
    n0 = len(m.meshes) + len(m.props)
    rep = crop.crop_map(m, [(cx - w, cz - h), (cx + w, cz - h), (cx + w, cz + h), (cx - w, cz + h)])
    q = check_consistent(m)
    assert rep.props_removed > 0 and rep.meshes_removed > 0 and len(q.meshes) + len(q.props) < n0
    # inverse crop on a fresh copy removes the other part
    m2 = OptMap.load(path)
    crop.crop_map(m2, [(cx - w, cz - h), (cx + w, cz - h), (cx + w, cz + h), (cx - w, cz + h)], keep_inside=False)
    q2 = check_consistent(m2)
    assert len(q2.props) + len(q.props) >= len(OptMap.load(path).props) - 5
    # removing single props keeps the sector lists valid
    k = len(q.props)
    assert crop.remove_props(q, {0, 1}) == 2 and len(q.props) == k - 2
    check_consistent(q)


def test_crop_online_map():
    path = os.path.join(DATA, "nfos", "nfos", "mp_b_almacen.opt")
    m = OptMap.load(path)
    c = np.concatenate([me.corners for me in m.meshes]); lo, hi = c.min(0), c.max(0)
    cx, cz = (lo[0] + hi[0]) / 2, (lo[2] + hi[2]) / 2
    crop.crop_map(m, [(cx - 3000, cz - 3000), (cx + 3000, cz - 3000), (cx + 3000, cz + 3000), (cx - 3000, cz + 3000)])
    check_consistent(m)


if __name__ == "__main__":
    for fn in (test_polygon, test_tools_maths, test_crop_malibu, test_crop_online_map):
        fn(); print(fn.__name__, "OK")
