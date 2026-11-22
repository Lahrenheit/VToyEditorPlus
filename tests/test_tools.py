"""Batch 6 tools: checker, floor view, groups, snapping, mirror / array, collision editing, pieces, install, history, compare."""
import os, sys, tempfile, zipfile
import _path
import numpy as np
from test_state import make_game_copy
from vtoy.app.state import EditorState, Selection
from vtoy import crop, hmcopy


def _st(tmp, scene="mp_b_loveboat.scn"):
    st = EditorState(make_game_copy(tmp))
    st.load(scene)
    return st


def _spawn(st, k=0):
    recs = [r for r in st.scene.modules if r.clean_name.lower() == "mp_cstartpoint"]
    return recs[k]


def test_checker_and_floor_view():
    with tempfile.TemporaryDirectory() as tmp:
        st = _st(tmp)
        res = st.validate_map()
        assert not [r for r in res if r["level"] == "error"], res        # the shipped map is fine
        sp = _spawn(st)
        sel = Selection("module", sp, "")
        st.set_position(sel, np.array([-4500.0, 300.0, 0.0]))            # over the sea: the sea floor is far below
        st.set_position(sel, np.array([200000.0, 0.0, 0.0]))             # out of everything
        res = st.validate_map()
        assert any("no floor" in r["msg"] for r in res) and any("outside" in r["msg"] for r in res)
        assert any(r["pos"] is not None for r in res)
        floors, walls, slopes = st.hm_wire()
        assert len(floors) > 500 and len(walls) > 100 and len(slopes) > 10 and floors.shape[1:] == (2, 3)
        assert st.hm_wire()[0] is floors                                 # cached


def test_group_snap_mirror_array():
    with tempfile.TemporaryDirectory() as tmp:
        st = _st(tmp)
        a, b = _spawn(st, 0), _spawn(st, 1)
        sa, sb = Selection("module", a, ""), Selection("module", b, "")
        st.toggle_multi(sa); st.toggle_multi(sb)
        pa, pb = st.position_of(sa).copy(), st.position_of(sb).copy()
        st.group_move([100.0, 0.0, -50.0])
        assert np.allclose(st.position_of(sa), pa + [100, 0, -50]) and np.allclose(st.position_of(sb), pb + [100, 0, -50])
        st.undo()
        a = next(r for r in st.scene.modules if str(r.object_name) == str(a.object_name))
        sa = Selection("module", a, "")
        assert np.allclose(st.position_of(sa), pa)
        st.toggle_multi(sa); st.toggle_multi(sa)
        assert not any(s.ref is a for s in st.multi_list())
        # snapping: grid + floor (a start point stands 18 above the floor)
        st.multi = []
        st.selection = sa
        st.set_position(sa, np.array([1955.0, 40.0, 4329.0]))
        st.snap_selection(grid=50.0, floor=True)
        p = st.position_of(sa)
        assert p[0] % 50 == 0 and p[2] % 50 == 0
        g = st.floor_below(p[0], p[2], p[1] + 5)
        assert g is not None and abs(p[1] - g - 18.0) < 0.01
        # mirror copy across x = 0 with team swap
        n = len(st.scene.modules)
        team, ang = a.parsed.team, a.parsed.angle
        st.mirror_copy("x", 0.0, True)
        assert len(st.scene.modules) == n + 1
        m = st.multi[0].ref
        assert np.allclose(st.position_of(st.multi[0]), p * [-1, 1, 1]) and m.parsed.team == 1 - team
        assert abs(m.parsed.angle + ang) < 1e-6
        assert ("ROJO" in str(m.object_name)) != ("ROJO" in str(a.object_name))
        # array
        st.multi = []; st.selection = sa
        n = len(st.scene.modules)
        st.array_copy(3, [100.0, 0.0, 0.0])
        assert len(st.scene.modules) == n + 3
        # group box select + lock
        st.multi = []; st.selection = None
        k = st.select_in_box(p - 60, p + 60, kinds=("module",))
        assert k >= 1
        st.group_lock(True)
        assert st.is_locked(a)
        st.lock_all(False)


def test_collision_editing():
    with tempfile.TemporaryDirectory() as tmp:
        st = _st(tmp)
        n = len(crop.read_block(st.opt).boxes)
        i = st.add_collision_box([-4000.0, 0.0, 500.0], [50.0, 100.0, 50.0])
        near = st.boxes_near([-4000.0, 0.0, 500.0], 100.0)
        assert near and near[0][0] == i
        st.delete_collision_box(i)
        assert len(crop.read_block(st.opt).boxes) == n
        assert st.floor_below(-4000.0, 500.0, 0.0) is not None and st.floor_below(-4000.0, 500.0, 0.0) < -1000
        st.add_floor_quad([-4000.0, -100.0, 500.0], 400.0, 400.0)
        assert abs(st.floor_below(-4000.0, 500.0, 0.0) + 100.0) < 0.01
        st.add_wall([-4200.0, -100.0, 300.0], [-3800.0, -100.0, 300.0], 200.0)
        assert len(crop.read_block(st.opt).boxes) == n + 1
        walls = [f for f in hmcopy.unique_faces(st.hm_edit) if abs(f.normal[2]) > 0.99 and abs(f.distance) == 300.0]
        assert len(walls) >= 2
        st.undo(); st.undo()                                             # wall, floor -> as after deleting the box
        assert len(crop.read_block(st.opt).boxes) == n


def test_prefab_save_and_place():
    with tempfile.TemporaryDirectory() as tmp:
        cwd = os.getcwd()
        os.chdir(tmp)                                                    # prefabs/ lives next to the settings file
        try:
            st = _st(tmp)
            pr = st.opt.props[41]                                        # one of the crates by the gangway
            st.selection = Selection("prop", pr, "prop 41")
            sp = Selection("module", _spawn(st), "")
            st.set_position(sp, np.asarray(pr.transform, np.float64)[3, :3] + [120.0, 0.0, 0.0])   # a spawn next to the crate
            st.toggle_multi(sp)
            msg = st.save_prefab("crate_spawn")
            assert "1 modules" in msg and "1 meshes" in msg and "crate_spawn" in st.prefab_names()
            nm, nmod, nb = len(st.opt.meshes), len(st.scene.modules), len(crop.read_block(st.opt).boxes)
            st.place_prefab("crate_spawn", [-4000.0, -100.0, 500.0], yaw=90.0)
            assert len(st.opt.meshes) == nm + 1 and len(st.scene.modules) == nmod + 1
            assert len(crop.read_block(st.opt).boxes) >= nb
            a, b = crop.mesh_bounds(st.opt.meshes[-1])
            assert abs((a[0] + b[0]) / 2 + 4000) < 400 and abs((a[2] + b[2]) / 2 - 500) < 400
            from vtoy.opt import OptMap
            OptMap.parse(st.opt.to_bytes())
            st.undo()
            assert len(st.opt.meshes) == nm
            st.delete_prefab("crate_spawn")
        finally:
            os.chdir(cwd)


def test_export_install_uninstall():
    with tempfile.TemporaryDirectory() as tmp:
        st = _st(tmp)
        st.save_scene_as("zz_inst")
        z = os.path.join(tmp, "zz_inst.zip")
        st.export_map_zip(z)
        with zipfile.ZipFile(z) as f:
            names = f.namelist()
            assert "vtoy_manifest.json" in names and any(n.endswith("zz_inst.scn") for n in names)
        scn, opt = st.scene.path, st.opt.path
        st.load("mp_b_loveboat.scn")
        os.remove(scn); os.remove(opt); os.remove(opt[:-4] + ".hm")
        st.fs.rescan()
        msg = st.install_map_zip(z)
        assert os.path.exists(scn) and os.path.exists(opt) and "zz_inst" in st.installed_maps(), msg
        st.load("zz_inst.scn")
        st.load("mp_b_loveboat.scn")
        st.uninstall_map("zz_inst")
        assert not os.path.exists(scn) and not os.path.exists(opt) and "zz_inst" not in st.installed_maps()


def test_history_and_compare():
    with tempfile.TemporaryDirectory() as tmp:
        st = _st(tmp)
        st.save_scene_as("zz_hist")
        st.save_scene()
        h0 = st.history()
        assert h0 and "scene" in h0[0][1]["files"] and "opt" in h0[0][1]["files"]
        first = h0[-1][0]
        sp = _spawn(st)
        name = str(sp.object_name).rstrip("\0")
        st.set_position(Selection("module", sp, ""), st.position_of(Selection("module", sp, "")) + [300, 0, 0])
        st.delete_module(_spawn(st, 1))
        st.save_scene()
        diff = st.compare_versions(first)
        assert any(name in d and "moved" in d for d in diff) and any(d.startswith("- module") for d in diff), diff
        n = len(st.scene.modules)
        st.restore_history(first)
        assert len(st.scene.modules) == n + 1
        assert st.compare_versions(first) == ["no differences"]
        for _ in range(14):                                              # only the last 10 are kept
            st.dirty_scene = True
            st.save_scene()
        assert len(st.history()) == 10


def test_collision_box_edit_ramp_faces_plan():
    with tempfile.TemporaryDirectory() as tmp:
        st = _st(tmp)
        i = st.add_collision_box([-4000.0, 0.0, 500.0], [50.0, 100.0, 50.0])
        st.set_collision_box(i, [-4100.0, 10.0, 520.0], [80.0, 100.0, 40.0])
        c, h = st.collision_box(i)
        assert np.allclose(c, [-4100, 10, 520]) and np.allclose(h, [80, 100, 40])
        # a ray straight down on it (display space mirrors z)
        hit = st.pick_collision_box(np.array([-4100.0, 2000.0, -520.0]), np.array([0.0, -1.0, 0.0]))
        assert hit == i
        msg = st.add_ramp([-4000.0, -100.0, 1000.0], [-3700.0, 50.0, 1000.0], 200.0)
        assert "ramp added" in msg
        y = st.floor_below(-3850.0, 1000.0, 200.0)
        assert y is not None and abs(y - (-25.0)) < 1.0                  # half way up
        near = st.floor_faces_near([-3850.0, -25.0, 1000.0], 100.0)
        assert near and near[0][1] == "slope"
        st.delete_floor_face(near[0][0])
        assert st.floor_below(-3850.0, 1000.0, 200.0) < -1000
        c, half = st.plan_area()
        items = st.plan_items()
        assert half > 1000 and sum(1 for k, *_ in items if k == "mp_cstartpoint") == 12
        assert {t for k, t, *_ in items if k == "mp_flag"} == {0, 1}


def test_solids():
    from vtoy import solids
    from vtoy.opt import OptMap
    from vtoy.hm import HeightMap
    with tempfile.TemporaryDirectory() as tmp:
        st = _st(tmp)
        nm, nb = len(st.opt.meshes), len(crop.read_block(st.opt).boxes)
        base_faces = len(hmcopy.unique_faces(st.heightmap_edit()))
        st.hm_edit = None
        at = np.array([-4000.0, -100.0, 500.0])                                 # over the sea, nothing there
        msg = st.add_solid("block", at, 200.0, 100.0, 150.0, 0.0)
        assert "block created" in msg and len(st.opt.meshes) == nm + 1 and len(crop.read_block(st.opt).boxes) == nb + 1
        assert abs(st.floor_below(-4000.0, 500.0, 200.0) - 50.0) < 0.01         # you stand on its top
        assert st.floor_below(-4150.0, 500.0, 200.0) < -1000                    # not beside it
        lo, hi = crop.mesh_bounds(st.opt.meshes[-1])
        assert np.allclose(lo, [-4100, -100, 450], atol=0.1) and np.allclose(hi, [-3900, 50, 550], atol=0.1)
        # every new face follows the winding rule of the shipped maps
        for f in hmcopy.unique_faces(st.hm_edit):
            p = np.asarray(f.contours[0], float); w = np.zeros(3)
            for i in range(len(p)):
                w += np.cross(p[i], p[(i + 1) % len(p)])
            assert np.linalg.norm(w) < 1e-6 or w @ np.asarray(f.normal, float) < 0     # (a few shipped faces are degenerate)
        # turned 90 degrees: length runs along z now, the collision box is turned with it
        st.add_solid("wall", [-4000.0, -100.0, 1500.0], 400.0, 20.0, 250.0, 90.0)
        lo, hi = crop.mesh_bounds(st.opt.meshes[-1])
        assert abs((hi[2] - lo[2]) - 400.0) < 0.5 and abs((hi[0] - lo[0]) - 20.0) < 0.5
        from vtoy import regioncopy
        blo, bhi = regioncopy._box_bounds(crop.read_block(st.opt).boxes[-1])
        assert np.allclose(blo, lo, atol=0.5) and np.allclose(bhi, hi, atol=0.5)
        # ramp between two points: rises from the low one to the high one, no collision box
        nb2 = len(crop.read_block(st.opt).boxes)
        st.add_solid_between("ramp", [-4500.0, 50.0, 3000.0], [-4900.0, -100.0, 3000.0], 200.0, 0.0)
        assert len(crop.read_block(st.opt).boxes) == nb2
        assert abs(st.floor_below(-4700.0, 3000.0, 300.0) - (-25.0)) < 0.5      # half way: half the height
        assert abs(st.floor_below(-4510.0, 3000.0, 300.0) - 46.25) < 0.5        # near the top
        # plank between two points: its top is level with them; rail: a wall you cannot cross, nothing to stand on
        st.add_solid_between("plank", [-4000.0, 0.0, 4000.0], [-3400.0, 0.0, 4300.0], 200.0, 12.0)
        assert abs(st.floor_below(-3700.0, 4150.0, 100.0) - 0.0) < 0.01
        nf = len(hmcopy.unique_faces(st.hm_edit))
        st.add_solid("rail", [-4000.0, -100.0, 6000.0], 600.0, 12.0, 110.0, 0.0)
        assert len(hmcopy.unique_faces(st.hm_edit)) == nf + 4 and st.floor_below(-4000.0, 6000.0, 200.0) < -1000
        # files still load; deleting a solid takes its collision along; undo brings everything back
        OptMap.parse(st.opt.to_bytes()); HeightMap.parse(st.hm_edit.to_bytes())
        st.bake()
        from vtoy.app.state import Selection
        blk_mesh = st.opt.meshes[nm]
        msg = st.delete_with_collision(Selection("mesh", blk_mesh, ""))
        assert "1 collision boxes" in msg and "5 floor" in msg
        assert st.floor_below(-4000.0, 500.0, 200.0) < -1000
        for _ in range(6):
            st.undo()
        assert len(st.opt.meshes) == nm and len(crop.read_block(st.opt).boxes) == nb
        assert st.hm_edit is None or len(hmcopy.unique_faces(st.hm_edit)) == base_faces


from test_state import DATA
TJ = os.environ.get("VTOY_TJ_DATA", os.path.join(os.path.dirname(DATA), "tj"))


def test_game_folder_library_and_preview():
    from vtoy.app.state_tools import PreviewFS, LIB_MODES
    if not os.path.isdir(TJ):
        return
    with tempfile.TemporaryDirectory() as tmp:
        st = _st(tmp)
        # the user picks a folder that only CONTAINS the unpacked data somewhere inside
        outer = os.path.join(tmp, "Torrente el juego"); os.makedirs(outer)
        os.symlink(TJ, os.path.join(outer, "data"))
        os.makedirs(os.path.join(outer, "musica"))
        open(os.path.join(outer, "musica", "tema_tj.ogg"), "wb").write(b"OggS")
        msg = st.open_game_folder(outer)
        assert st.library is not None and "new models" in msg
        all_m, new_m = st.library_items("models", False), st.library_items("models", True)
        have = {os.path.basename(p).lower() for p in st.fs.list("nfos", ".nfo")}
        assert len(new_m) <= len(all_m) and all(os.path.basename(n).lower() not in have for n in new_m)
        assert any(os.path.basename(n).lower() in have for n in all_m) or len(new_m) == len(all_m)
        tex_new = st.library_items("textures", True)
        have_t = {os.path.splitext(os.path.basename(p))[0].lower() for p in st.fs.list("texs", ".tex")}
        assert all(t.lower() not in have_t for t in tex_new)
        mus = st.library_items("music", True)
        assert [os.path.basename(m) for m in mus] == ["tema_tj.ogg"]
        for m in LIB_MODES:
            st.library_items(m, True)
        # hover preview of a library model, read from the library (nothing imported)
        pfs = PreviewFS(st.fs); pfs.lib = st.library
        before = set(st.fs.list("nfos", ".nfo"))
        shown = 0
        for rel in (new_m or all_m)[:6]:
            g, rec = st.preview_library_model(rel, pfs)
            shown += bool(g.instances)
        assert shown >= 1 and set(st.fs.list("nfos", ".nfo")) == before
        assert not os.path.exists(os.path.join(tmp, "game", "tj_unpacked"))
