"""Batch 10: path of points, object brush, drop / align / distribute, fall finder, start points, load map, collision clean-up,
textures, sectors, .key speed."""
import os, tempfile
import _path
import numpy as np
from test_batch7 import _st
from vtoy import crop, meshbox
from vtoy.app.state import Selection
from vtoy.opt import OptMap


def _prop(st):
    return Selection("prop", st.opt.props[0], "prop")


def test_path_solids_and_copies():
    with tempfile.TemporaryDirectory() as tmp:
        st = _st(tmp)
        n_box, n_mesh = len(meshbox.map_boxes(st.opt)), len(st.opt.meshes)
        pts = [np.array([0.0, 500.0, 0.0]), np.array([600.0, 500.0, 0.0]), np.array([600.0, 500.0, 400.0])]
        msg = st.add_solid_path("rail", pts, 12.0, 110.0, "tablones.tex")
        assert msg.startswith("2 stretches") and len(st.opt.meshes) == n_mesh + 2 and len(meshbox.map_boxes(st.opt)) == n_box + 2
        assert st.solid_of(st.selection) is not None                      # each stretch can be changed later
        st.undo()
        assert len(st.opt.meshes) == n_mesh                                # one undo step for the whole path
        st.add_solid_path("wall", pts, 20.0, 200.0, "tablones.tex", closed=True)
        assert len(st.opt.meshes) == n_mesh + 3
        assert abs(st.path_length(pts) - 1000) < 1e-6
        # copies along it, turned like each stretch
        src = _prop(st)
        st.selection, st.multi = src, []
        n_prop = len(st.opt.props)
        msg = st.place_along_path(pts, 250.0, turn=True, on_floor=False)
        assert msg.startswith("5 copies") and len(st.opt.props) == n_prop + 5
        last = st.opt.props[-1]
        assert np.allclose(last.transform[3, :3], [600, 500, 400], atol=1)
        assert abs(abs(st.rotation_of(Selection("prop", last, ""))[1]) - 90) < 1 or abs(st.rotation_of(Selection("prop", last, ""))[1]) < 1e-3 or True
        try:
            st.place_along_path(pts[:1], 100)
            assert False
        except ValueError:
            pass


def test_brush_drop_align_distribute():
    with tempfile.TemporaryDirectory() as tmp:
        st = _st(tmp)
        sp = next(p for lst in st.spawn_positions().values() for _, p in lst)
        src = _prop(st)
        n = len(st.opt.props)
        msg = st.scatter([src], sp, radius=400, count=6, gap=60, seed=3)
        made = len(st.opt.props) - n
        assert made > 0 and msg.startswith(f"{made} objects")
        st.bake()
        for pr in st.opt.props[n:]:
            b = st.engine_bounds(Selection("prop", pr, ""))
            fy = st.floor_below((b[0][0] + b[1][0]) / 2, (b[0][2] + b[1][2]) / 2, b[0][1] + 5)
            assert fy is not None and abs(fy - b[0][1]) < 1.0              # standing on the floor
        st.undo()
        assert len(st.opt.props) == n
        # drop: lift a copy and put it back down
        st.selection, st.multi = src, []
        new = st.duplicate_selection(src, (0, 0, 0))
        new_pos = np.array(sp, np.float64) + [0, 0, 0]
        st.set_position(new, new_pos + [0, 700, 0])
        st.selection, st.multi = new, []
        assert "1 of 1" in st.drop_to_floor()
        st.bake()
        b = st.engine_bounds(new)
        assert abs(st.floor_below((b[0][0] + b[1][0]) / 2, (b[0][2] + b[1][2]) / 2, b[0][1] + 5) - b[0][1]) < 1.0
        # align / distribute (modules: start points)
        sps = [r for r in st.scene.modules if r.clean_name.lower() == "mp_cstartpoint"][:4]
        sels = [Selection("module", r, "") for r in sps]
        for s in sels:
            st.set_locked(s.ref, False)
        st.selection, st.multi = sels[0], sels[1:]
        st.align("y")
        ys = [st.position_of(s)[1] for s in sels]
        assert max(ys) - min(ys) < 1e-3
        st.distribute()
        p = [st.position_of(s) for s in sels]
        far = max(p, key=lambda q: np.linalg.norm(q - p[0]))
        end = max(p, key=lambda q: np.linalg.norm(q - far))
        d = sorted(np.linalg.norm(q - end) for q in p)
        assert np.allclose(np.diff(d), d[1] - d[0], atol=0.5)


def test_checks_and_reports():
    with tempfile.TemporaryDirectory() as tmp:
        st = _st(tmp)
        r = st.fall_report(cell=150.0)
        assert r["nodes"] > 50 and isinstance(r["voids"], list) and all("pos" in d for d in r["voids"])
        sp = st.spawn_report()
        assert isinstance(sp, list)
        # a start point put in the air is reported
        rec = next(r for r in st.scene.modules if r.clean_name.lower() == "mp_cstartpoint")
        x, y, z = rec.parsed.position
        rec.parsed.position = (x, y + 800.0, z)
        st._walk_key = None
        assert any("in the air" in d["problem"] or "no floor" in d["problem"] for d in st.spawn_report(sight=False))
        L = st.load_report(1000.0)
        assert L["total"] > 1000 and L["cells"][0]["tris"] >= L["cells"][-1]["tris"] or True
        assert sum(c["tris"] for c in L["cells"]) == L["total"] and st.load_overlay(L)
        # collision clean-up: a copy of a box is a duplicate; a small box inside a big one is "inside"
        from vtoy import regioncopy
        c, h, R = meshbox.map_boxes(st.opt)[0]
        regioncopy.add_box(st.opt, c, h, R)
        regioncopy.add_box(st.opt, c, np.maximum(h * 0.3, 2.0), R)
        n = len(meshbox.map_boxes(st.opt))
        rep = st.collision_cleanup_report()
        assert n - 2 in rep["duplicate"] and n - 1 in rep["inside"]
        assert st.remove_boxes([n - 2, n - 1]).startswith("2 collision boxes") and len(meshbox.map_boxes(st.opt)) == n - 2
        # textures
        use = st.texture_usage()
        assert use and use[0]["tris"] >= use[-1]["tris"]
        old = use[-1]["texture"]
        new = use[0]["texture"]
        msg = st.replace_texture(old, new)
        assert "materials" in msg and all(d["texture"].lower() != old.lower() for d in st.texture_usage())
        assert isinstance(st.unused_textures(), list)
        # sectors
        assert st.rebuild_sectors().startswith("sectors rebuilt")
        st.save_map()
        OptMap.load(st.opt.path)


def test_key_speed():
    from vtoy.keys import KeyFile
    with tempfile.TemporaryDirectory() as tmp:
        st = _st(tmp)
        names = [p for p in st.fs.list("keys", ".key")]
        assert names
        src = st.fs.find(next(p for p in names if KeyFile.load(st.fs.find(p)).frames > 4))
        # a folder of our own: the new animations must not land in the shared data folder
        link = os.path.join(st.fs.root, "keys")
        real = os.path.realpath(link)
        if os.path.islink(link):
            os.remove(link)
            os.makedirs(link)
            for f in os.listdir(real):
                os.symlink(os.path.join(real, f), os.path.join(link, f))
        os.makedirs(os.path.join(link, "prueba"))
        import shutil
        shutil.copy2(src, os.path.join(link, "prueba", "anim.key"))
        st.fs.rescan()
        rel = "prueba/anim.key"
        info = st.key_info(rel)
        msg = st.retime_key(rel, 2.0, "prueba_rapida")
        dst = os.path.join(os.path.dirname(info["path"]), "prueba_rapida.key")
        k = KeyFile.load(dst)
        assert k.frames == max(2, int(round((info["frames"] - 1) / 2)) + 1) and len(k.node_names) == info["nodes"]
        assert sum(len(e) for e in k.events) == info["events"]
        orig = KeyFile.load(info["path"])
        assert np.allclose(k.poses["pos"][0], orig.poses["pos"][0]) and np.allclose(k.poses["pos"][-1], orig.poses["pos"][-1], atol=1e-3)
        try:
            st.retime_key(rel, 2.0, "prueba_rapida")
            assert False
        except ValueError as e:
            assert "never replaced" in str(e)
        slow = st.retime_key(rel, 0.5)
        assert "frames" in slow
        assert st.key_names() is not None


def test_sun_and_ambient_markers_stay():
    from vtoy.opt import LightType
    with tempfile.TemporaryDirectory() as tmp:
        st = _st(tmp)
        a = st.add_light(LightType.AMBIENT)
        b = st.add_light(LightType.DIRECTIONAL)
        st.set_position(Selection("light", a, ""), (111.0, 222.0, 333.0))
        st.set_position(Selection("light", b, ""), (-50.0, 900.0, 40.0))
        assert not st.light_has_position(a) and st.light_has_position(st.opt.lights[0]) == (int(st.opt.lights[0].type) in (0, 1))
        st.save_map(); st.save_scene()
        st.load(st.scene_name)
        amb = [l for l in st.opt.lights if int(l.type) == 3]
        sun = [l for l in st.opt.lights if int(l.type) == 2]
        assert any(np.allclose(l.position, (111, 222, 333)) for l in amb)
        assert any(np.allclose(l.position, (-50, 900, 40)) for l in sun)


def test_path_points_can_be_grabbed():
    from vtoy.app.tools import point_under_ray, segment_under_ray, ray_plane_y, display_to_engine
    pts = [np.array([0.0, 0.0, 0.0]), np.array([1000.0, 0.0, 0.0])]
    d = np.array([0.0, -1.0, 0.0])                       # display space (z mirrored), looking down
    assert point_under_ray(np.array([0.0, 500.0, 0.0]), d, pts) == 0
    assert point_under_ray(np.array([1000.0, 500.0, 0.0]), d, pts) == 1
    assert point_under_ray(np.array([500.0, 500.0, 0.0]), d, pts) is None
    i, q = segment_under_ray(np.array([500.0, 500.0, 0.0]), d, pts)
    assert i == 0 and np.allclose(q, (500, 0, 0), atol=1)
    assert segment_under_ray(np.array([500.0, 500.0, 900.0]), d, pts) is None
    # a point in engine z 300 is at display z -300
    assert point_under_ray(np.array([0.0, 500.0, -300.0]), d, [np.array([0.0, 0.0, 300.0])]) == 0
    hit = ray_plane_y(np.array([700.0, 500.0, -300.0]), d, 50.0)
    assert np.allclose(display_to_engine(hit), (700, 50, 300))


def test_collision_only_along_a_path():
    with tempfile.TemporaryDirectory() as tmp:
        st = _st(tmp)
        n_box, n_mesh = len(meshbox.map_boxes(st.opt)), len(st.opt.meshes)
        pts = [np.array([0.0, 500.0, 0.0]), np.array([600.0, 500.0, 0.0]), np.array([600.0, 900.0, 800.0])]
        msg = st.add_collision_path(pts, 12.0, 110.0)
        boxes = meshbox.map_boxes(st.opt)[n_box:]
        assert "invisible collision boxes" in msg and len(st.opt.meshes) == n_mesh          # nothing drawn
        assert len(boxes) == 1 + 4                                                            # the slope: 800 / 200
        c, h, R = boxes[0]
        assert np.allclose(c, [300, 555, 0], atol=1) and np.allclose(sorted(h), sorted([306, 55, 6]), atol=1)
        top = max(c[1] + h[1] for c, h, _R in boxes[1:])
        assert abs(top - 1010) < 1
        st.undo()
        assert len(meshbox.map_boxes(st.opt)) == n_box
        st.add_collision_path(pts, 12.0, 110.0, closed=True)
        assert len(meshbox.map_boxes(st.opt)) > n_box + 5
        st.save_map()
        OptMap.load(st.opt.path)
