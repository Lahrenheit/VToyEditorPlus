"""Batch 11: fair light on twin ships, weather presets, animation routes, match simulation (every mode), changes since a
version, floor gaps / buried objects, OBJ export + import with collision, symmetric layouts."""
import os, tempfile
import _path
import numpy as np
from test_batch7 import _st
from vtoy import gamemode, meshbox
from vtoy.app.state import Selection
from vtoy.opt import OptMap, LightType


def test_fair_light_on_twin_ships():
    with tempfile.TemporaryDirectory() as tmp:
        st = _st(tmp)
        st.make_twin_ships(800.0, 16, tint_ships=False)
        st.twin_lights(mirror=True)                       # the old default: lit like a reflection - not the same per ship
        bad = st.ship_light_report()
        msg = st.fair_ship_lights()
        assert "brightness A" in msg
        good = st.ship_light_report()
        assert good["diff"] < 2.0 and good["diff"] <= bad["diff"] + 1e-6
        assert len(good["spots"]) <= len(bad["spots"])
        # a light only on ship A makes them different; fair again afterwards
        l = next(l for l in st.opt.lights if int(l.type) == 0)
        l.diffuse = (1.0, 1.0, 1.0, 1.0)
        l.end = 3000.0
        assert st.ship_light_report()["diff"] > good["diff"]
        st.fair_ship_lights()
        assert st.ship_light_report()["diff"] < 2.0


def test_weather_and_routes():
    from vtoy.keys import KeyFile
    with tempfile.TemporaryDirectory() as tmp:
        st = _st(tmp)
        msg = st.weather_preset("night")
        assert msg.startswith("night") and st.scene.fog_far > st.scene.fog_near > 0
        amb = [l for l in st.opt.lights if int(l.type) == 3]
        assert amb and np.allclose(amb[0].diffuse[:3], (0.18, 0.2, 0.3))
        st.undo()
        for k in ("day", "sunset", "storm", "fog"):
            st.weather_preset(k, lights=False)
        try:
            st.weather_preset("lluvia de ranas")
            assert False
        except ValueError:
            pass
        # a moving model: a key with a node that moves
        src = next(p for p in st.fs.list("keys", ".key") if KeyFile.load(st.fs.find(p)).frames > 4
                   and np.ptp(KeyFile.load(st.fs.find(p)).poses["pos"], axis=0).max() > 50)
        link = os.path.join(st.fs.root, "keys")
        real = os.path.realpath(link)
        if os.path.islink(link):
            os.remove(link); os.makedirs(link)
            for f in os.listdir(real):
                os.symlink(os.path.join(real, f), os.path.join(link, f))
        os.makedirs(os.path.join(link, "prueba"))
        import shutil
        shutil.copy2(st.fs.find(src), os.path.join(link, "prueba", "vuelo.key"))
        st.fs.rescan()
        rec = st.add_module("AnimatedRenderNFO", "avion_prueba")
        name = b"prueba\\vuelo.key"
        rec.parsed.tail = b"\0" * 4 + len(name + b"\0").to_bytes(4, "little") + name + b"\0" + b"\1\2"
        assert rec.parsed.key_name == "prueba\\vuelo.key"
        paths = st.animation_paths()
        mine = [p for p in paths if p[0] is rec]
        assert mine and len(mine[0][1]) > 2
        before = mine[0][1]
        msg = st.transform_key("prueba\\vuelo.key", 2.0, (0.0, 100.0, 0.0), "vuelo_grande", rec)
        assert "uses it now" in msg and rec.parsed.key_name == "prueba\\vuelo_grande.key"
        assert rec.parsed.tail.endswith(b"\1\2") and int.from_bytes(rec.parsed.tail[4:8], "little") == len(b"prueba\\vuelo_grande.key") + 1
        after = [p for p in st.animation_paths() if p[0] is rec][0][1]
        assert np.ptp(after, axis=0).max() > 1.9 * np.ptp(before, axis=0).max()
        # speed copy also points the module to it (name stored in the tail)
        m2 = st.retime_key("prueba\\vuelo_grande.key", 2.0, "vuelo_rapido", rec)
        assert "the module now uses" in m2 and rec.parsed.key_name.endswith("vuelo_rapido.key")


def test_match_simulation_every_mode():
    with tempfile.TemporaryDirectory() as tmp:
        st = _st(tmp)
        for mode in ("B", "DMT", "DM", "DO"):
            gamemode.set_mode(st.scene, mode)
            r = st.simulate_match(cell=150.0)
            assert r["mode"] == mode and r["routes"] and r["busy"]
            assert all(len(x["points"]) >= 2 for x in r["routes"])
            if mode != "DM":
                assert all(st_ is not None for st_ in [r["first"]]) or r["meets"] == []


def test_changes_gaps_buried_obj_and_layout():
    with tempfile.TemporaryDirectory() as tmp:
        st = _st(tmp)
        st.save_map(); st.save_scene()
        stamp = st.snapshot_history("before")
        stamp = stamp if isinstance(stamp, str) and stamp else st.history()[0][0]
        # move a module, add a prop copy
        sp = next(r for r in st.scene.modules if r.clean_name.lower() == "mp_cstartpoint")
        x, y, z = sp.parsed.position
        sp.parsed.position = (x + 300.0, y, z)
        st.duplicate_selection(Selection("prop", st.opt.props[0], ""), (500.0, 0.0, 0.0))
        marks = st.version_marks(stamp)
        assert any(k == "module" and s == "~" for k, s, _p in marks)
        assert any(k == "prop" and s == "+" for k, s, _p in marks)
        assert isinstance(st.floor_gaps(), list)
        # a copy of a mesh pushed deep under the floor is found
        from vtoy.opt import translate_mesh
        i = next(i for i, m in enumerate(st.opt.meshes) if i not in {p.mesh_index for p in st.opt.props}
                 and 50 < (lambda b: (b[1] - b[0]).max())(__import__("vtoy.crop", fromlist=["x"]).mesh_bounds(m)) < 800)
        new = st.duplicate_selection(Selection("mesh", st.opt.meshes[i], ""), (0, 0, 0), carry=False)
        from vtoy import crop
        lo, hi = crop.mesh_bounds(new.ref)
        levels = st.walk_world().levels_at((lo[0] + hi[0]) / 2, (lo[2] + hi[2]) / 2)
        if levels:
            floor = min(levels)                                    # under every floor there (a basement would be fine)
            translate_mesh(new.ref, (0.0, floor - hi[1] - 400.0, 0.0))
            found = st.buried_objects()
            assert any(d["kind"] == "mesh" and st.opt.meshes[d["index"]] is new.ref for d in found)
        # OBJ: out and back in, with its collision boxes
        st.selection, st.multi = Selection("mesh", st.opt.meshes[i], ""), []
        out = os.path.join(tmp, "exp", "pieza.obj")
        msg = st.export_obj(out, True, True)
        assert os.path.exists(out) and os.path.exists(out[:-4] + ".mtl") and "collision boxes" in msg
        n_boxes = int(msg.split(" textures, ")[1].split(" collision")[0])
        nb0, nm0 = len(meshbox.map_boxes(st.opt)), len(st.opt.meshes)
        lo0, hi0 = crop.mesh_bounds(st.opt.meshes[i])
        msg2 = st.import_obj(out, None, 100.0, 0.0, "y", False, False, False, True)
        assert len(st.opt.meshes) == nm0 + 1 and len(meshbox.map_boxes(st.opt)) == nb0 + n_boxes
        lo1, hi1 = crop.mesh_bounds(st.opt.meshes[-1])
        assert np.allclose(lo0, lo1, atol=1.0) and np.allclose(hi0, hi1, atol=1.0)          # back where it was
        # fair layouts
        a, b = np.array(st.spawn_positions()[0][0][1]), np.array(st.spawn_positions()[1][0][1])
        for mode in ("B", "DMT", "DO", "DM"):
            msg = st.symmetric_layout(mode, a, b, per_team=4, radius=200.0)
            sp = st.spawn_positions()
            assert sum(len(v) for v in sp.values()) == 8 and set(sp) == {0, 1}, (mode, msg)
            if mode != "DM":
                da = sorted(np.linalg.norm((p - a)[[0, 2]]) for _n, p in sp[0])
                db = sorted(np.linalg.norm((p - b)[[0, 2]]) for _n, p in sp[1])
                assert np.allclose([d for d in da], [d for d in db], atol=60)              # the same round each base
            assert gamemode.mode_of(st.scene) == mode
        st.save_scene(); st.save_map()
        OptMap.load(st.opt.path)


def test_model_full_detail():
    import glob
    from vtoy.nfo import Nfo
    with tempfile.TemporaryDirectory() as tmp:
        st = _st(tmp)
        # a model of the game with far versions, put in a folder of our own (nothing written into the shared data)
        src = None
        for rel in st.fs.list("nfos", ".nfo"):
            try:
                n = Nfo.parse(open(st.fs.find(rel), "rb").read())
            except Exception:
                continue
            if n.objects and len(n.objects[0].lods) > 1:
                src = st.fs.find(rel)
                break
        assert src
        link = os.path.join(st.fs.root, "nfos")
        real = os.path.realpath(link)
        if os.path.islink(link):
            os.remove(link); os.makedirs(link)
            for f in os.listdir(real):
                os.symlink(os.path.join(real, f), os.path.join(link, f))
        os.makedirs(os.path.join(link, "prueba"))
        import shutil
        shutil.copy2(src, os.path.join(link, "prueba", "barco.NFO"))
        st.fs.rescan()
        rec = st.add_module("RenderNFO", "barco_prueba")
        rec.parsed.model_name = "prueba\\barco.NFO"
        rec2 = st.add_module("RenderNFO", "barco_prueba2")
        rec2.parsed.model_name = "prueba\\barco.NFO"
        lods = st.model_lods("prueba\\barco.NFO")[0]
        assert len(lods) > 1
        msg = st.full_detail_model(rec)
        assert "always the detailed version" in msg and "2 modules" in msg
        assert rec.parsed.model_name == "prueba\\barco_hd.NFO" == rec2.parsed.model_name
        new = st.model_lods("prueba\\barco_hd.NFO")[0]
        assert all(d >= 1e7 - 1 for d, _t in new[1:]) and [t for _d, t in new] == [t for _d, t in lods]
        assert open(os.path.join(link, "prueba", "barco.NFO"), "rb").read() == open(src, "rb").read()   # original as it was
        assert "already the full-detail copy" in st.full_detail_model(rec)
        assert "the game's model again" in st.normal_detail_model(rec)            # and back (HD off)
        assert rec.parsed.model_name == "prueba\\barco.NFO" == rec2.parsed.model_name
        st.full_detail_model(rec)
        st.bake()
