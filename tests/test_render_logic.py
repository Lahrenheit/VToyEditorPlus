import numpy as np
import _path
from vtoy.render.geometry import SceneGeometry, subdivide_triangles
from vtoy.render.camera import FlyCamera, ray_aabb, compose, decompose


def tri_geo(zs):
    v, t = [], []
    for i, z in enumerate(zs):
        v += [[0, 0, z, 0, 1, 0, 0, 0], [1, 0, z, 0, 1, 0, 1, 0], [0, 1, z, 0, 1, 0, 0, 1]]
        t.append([3 * i, 3 * i + 1, 3 * i + 2])
    n = len(zs)
    return SceneGeometry(tverts=np.array(v, np.float32), ttri=np.array(t, np.uint32), ttex=np.zeros(n, np.int32),
                         ttwo=np.zeros(n, bool), tex_names=["a"])


def test_sort_back_to_front():
    g = tri_geo([10, 50, 30])
    idx, runs = g.sort_transparent([0, 0, 0])
    order = [int(i) // 3 for i in idx[::3]]
    assert order == [1, 2, 0]                       # farthest first
    assert sum(r[3] for r in runs) == 9


def test_subdivide_preserves_area():
    v = np.array([[0, 0, 0, 0, 1, 0, 0, 0], [1000, 0, 0, 0, 1, 0, 1, 0], [0, 1000, 0, 0, 1, 0, 0, 1]], np.float32)
    nv, nt = subdivide_triangles(v, np.array([[0, 1, 2]], np.uint32), 300)
    a = lambda p: 0.5 * np.linalg.norm(np.cross(p[1] - p[0], p[2] - p[0]))
    assert abs(sum(a(nv[t, :3]) for t in nt) - 500000) < 1


def test_camera():
    c = FlyCamera(); c.pos = np.array([0., 0, 0]); c.yaw = -90; c.pitch = 0
    o, d = c.ray(400, 300, 800, 600)
    assert ray_aabb(o, d, np.array([-1., -1, -50]), np.array([1., 1, -40])) is not None
    m = compose([1, 2, 3], [10, 20, 30], [1, 2, 3])
    p, e, s = decompose(m)
    assert np.allclose(compose(p, e, s), m, atol=1e-6)


if __name__ == "__main__":
    for f in (test_sort_back_to_front, test_subdivide_preserves_area, test_camera):
        f(); print(f.__name__, "OK")
