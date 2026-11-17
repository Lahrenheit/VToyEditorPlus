"""Headless tests of the editor logic using the real game data (copied to a temp dir so nothing is modified)."""
import os, shutil, sys, tempfile
import _path
from _path import DATA
import numpy as np
from vtoy.app.state import EditorState
from vtoy.scn import Scene
from vtoy.opt import OptMap, translate_mesh


def make_game_copy(tmp):
    root = os.path.join(tmp, "game")
    os.makedirs(root)
    for sub in ("scns", "nfos", "texs", "keys"):
        src = os.path.join(DATA, sub, sub)
        if os.path.isdir(src):
            os.symlink(src, os.path.join(root, sub))
    # scenes + maps are edited => real copies
    for sub in ("scns", "nfos"):
        os.remove(os.path.join(root, sub))
        shutil.copytree(os.path.join(DATA, sub, sub), os.path.join(root, sub))
    return root


def test_edit_cycle():
    with tempfile.TemporaryDirectory() as tmp:
        st = EditorState(make_game_copy(tmp))
        st.load("mp_dm_vertigo.scn")
        n0 = len(st.scene.modules)
        # --- pick the first car by shooting a ray at it
        car = next(r for r in st.scene.modules if r.clean_name == "mp_CCar")
        inst = next(i for i in st.geometry.instances if i.ref is car)
        target = (inst.lo + inst.hi) / 2
        origin = target + np.array([0, 3000.0, 0])
        sel = st.pick(origin, np.array([0, -1.0, 0]))
        assert sel is not None and sel.kind in ("module", "prop", "mesh")
        # --- move + duplicate + add + delete
        st.set_position(Selection_for(st, car), st.position_of(Selection_for(st, car)) + [100, 0, 0])
        dup = st.duplicate_module(car)
        st.add_module("mp_salud", "test_pack")
        st.delete_module(dup)
        assert len(st.scene.modules) == n0 + 1
        st.save_scene()
        again = Scene.load(st.scene.path)
        assert len(again.modules) + 1 == n0 + 1 + 1 or len(again.modules) == n0 + 1  # terminator not counted
        assert os.path.exists(st.scene.path + ".bak")
        # --- map: move a prop, a light, translate a mesh, save + reload
        pr = st.opt.props[0]
        old = pr.transform[3, :3].copy()
        st.set_position(type("S", (), {"kind": "prop", "ref": pr})(), old + [5, 6, 7])
        st.add_light(__import__("vtoy.opt", fromlist=["LightType"]).LightType.POINT)
        st.save_map()
        m2 = OptMap.load(st.opt.path)
        assert np.allclose(m2.props[0].transform[3, :3], old + [5, 6, 7])
        assert len(m2.lights) == len(st.opt.lights)
        st.bake()
        return True


def Selection_for(st, rec):
    from vtoy.app.state import Selection
    return Selection("module", rec)


def test_translate_mesh():
    opt = OptMap.load(os.path.join(DATA, "nfos", "nfos", "mp_dm_vertigo.opt")) if os.path.exists(
        os.path.join(DATA, "nfos", "nfos", "mp_dm_vertigo.opt")) else None
    if opt is None:
        import glob
        opt = OptMap.load(next(f for f in glob.glob(os.path.join(DATA, "nfos", "nfos", "*")) if f.lower().endswith("vertigo.opt")))
    me = opt.meshes[0]
    sm = next(s for s in me.render_submeshes() if len(s.vertices))
    before = sm.vertices["pos"][0].copy()
    translate_mesh(me, [10, 20, 30])
    assert np.allclose(sm.vertices["pos"][0], before + [10, 20, 30])
    OptMap.parse(opt.to_bytes())          # still a valid file
    return True


def test_rotate_move():
    from vtoy.app.state import Selection
    with tempfile.TemporaryDirectory() as tmp:
        st = EditorState(make_game_copy(tmp))
        st.load("mp_dm_vertigo.scn")
        car = next(r for r in st.scene.modules if r.clean_name == "mp_CCar")
        sel = Selection("module", car)
        m0 = car.parsed.transform.copy()
        assert st.can_rotate(sel)
        st.rotate_selection(sel, [0, 90, 0])
        m1 = car.parsed.transform
        assert np.allclose(m1[3], m0[3]) and not np.allclose(m1[:3, :3], m0[:3, :3])
        st.rotate_selection(sel, [0, -90, 0])
        assert np.allclose(car.parsed.transform, m0, atol=1e-4)           # rotating back restores the matrix
        pr = Selection("prop", st.opt.props[0]); assert st.can_rotate(pr)
        st.rotate_selection(pr, [10, 20, 30])
    return True


def test_catalog():
    with tempfile.TemporaryDirectory() as tmp:
        st = EditorState(make_game_copy(tmp))
        st.load("mp_dm_vertigo.scn")
        kinds = st.kinds_with_models()
        assert "mp_ccar" in kinds and "rendernfo" in kinds
        cars = st.models_for("mp_ccar")
        assert len(cars) >= 10 and all(src == "game" for _, _, src in cars)
        assert any("corsa" in n.lower() for n, _, _ in cars)
        rec = st.place_model(os.path.relpath(os.path.join(st.fs.root, cars[0][0]), os.path.join(st.fs.root, "nfos")), "mp_ccar")
        assert rec.clean_name.lower() == "mp_ccar" and rec.parsed.model_name == cars[0][0]
    return True


def test_preview_and_names():
    with tempfile.TemporaryDirectory() as tmp:
        st = EditorState(make_game_copy(tmp))
        st.load("mp_dm_vertigo.scn")
        names = st.nfo_names()
        assert names and names[0].startswith("nfos/")
        ok = 0
        for n in names[:25]:
            g, rec = st.preview_geometry(n)
            ok += bool(g.instances)
        assert ok > 10, ok
        # place one
        rel = os.path.relpath(os.path.join(st.fs.root, names[0]), os.path.join(st.fs.root, "nfos"))
        n0 = len(st.scene.modules); st.place_model(rel); assert len(st.scene.modules) == n0 + 1
    return True


def test_game_mode_helpers():
    from vtoy import gamemode as gm
    with tempfile.TemporaryDirectory() as tmp:
        st = EditorState(make_game_copy(tmp))
        st.load("mp_dm_vertigo.scn")
        n0 = len(st.scene.modules)
        assert st.game_mode() == "DM"
        st.set_game_mode("B"); assert st.game_mode() == "B"
        assert st.gm_add_start(1) is not None
        assert st.gm_add_health("small").parsed.health == 25
        assert st.gm_add_flag(0).parsed.team == 0
        st.set_music("plaza.wav")
        assert len(st.scene.modules) == n0 + 3
        assert any("mp_Flag" in l for l in st.gm_check())      # only one flag
        st.gm_add_flag(1)
        assert not any("mp_Flag" in l for l in st.gm_check())
        out = os.path.join(tmp, "x.scn"); st.scene.save(out)   # round trip
        s2 = Scene.load(out)
        assert str(s2.main_module_name).startswith("mp_CaptureTheFlag") and len(s2.modules) == n0 + 4


if __name__ == "__main__":
    for fn in (test_edit_cycle, test_translate_mesh, test_rotate_move, test_catalog, test_preview_and_names,
               test_game_mode_helpers):
        fn(); print(fn.__name__, "OK")
