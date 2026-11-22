"""Batch 9: collision boxes that follow the mesh, finding what has no collision, lock all lights / decals, what a light lights."""
import tempfile
import _path
import numpy as np
from test_batch7 import _st
from vtoy import meshbox
from vtoy.app.state import Selection
from vtoy.opt import LightType, OptMap


def _quad(a, b, y0=0.0, y1=100.0):
    a, b = np.asarray(a, float), np.asarray(b, float)
    p = [np.array([a[0], y0, a[1]]), np.array([b[0], y0, b[1]]), np.array([b[0], y1, b[1]]), np.array([a[0], y1, a[1]])]
    return [np.stack([p[0], p[1], p[2]]), np.stack([p[0], p[2], p[3]])]


def _mesh_of(opt, tris, texture):
    """A one-material mesh made of ``tris`` (engine)."""
    from vtoy import meshlib
    from vtoy.opt import VERTEX_DTYPE
    src = next(i for i, m in enumerate(opt.meshes) if m.lods and m.render_submeshes())
    me = meshlib.extract(opt, "mesh", src)
    me.lods = me.lods[:1]
    me.lods[0].parts = me.lods[0].parts[:1]
    sm = me.lods[0].parts[0].submeshes[0]
    me.lods[0].parts[0].submeshes = [sm]
    v = np.zeros(len(tris) * 3, VERTEX_DTYPE)
    v["pos"] = np.asarray(tris, np.float32).reshape(-1, 3)
    v["nrm"] = (0, 0, 1)
    sm.vertices, sm.indices, sm.unk = v, np.arange(len(v), dtype=np.uint16), 0
    me.materials = me.materials[sm.material_index:sm.material_index + 1]
    me.materials[0].textures = [texture]
    sm.material_index = 0
    return meshlib._finish(me)


def test_fit_follows_the_shape():
    # an L shaped railing: one thin box per side, not one box over the corner
    L = np.array(_quad((0, 0), (1000, 0)) + _quad((1000, 0), (1000, 600)))
    boxes = meshbox.fit(L, thickness=10)
    assert len(boxes) == 2
    sizes = sorted(tuple(np.round(np.sort(b[1] * 2))) for b in boxes)
    assert sizes == [(10.0, 100.0, 600.0), (10.0, 100.0, 1000.0)]
    one = meshbox.oriented_box(L.reshape(-1, 3))
    assert np.prod(one[1][[0, 2]]) > 50 * sum(np.prod(b[1][[0, 2]]) for b in boxes) / 2       # the single box would be huge
    # two railings far apart in the same mesh: two boxes
    far = np.array(_quad((0, 0), (500, 0)) + _quad((5000, 3000), (5000, 3500)))
    assert len(meshbox.fit(far)) == 2
    # a railing at 30 degrees: one box turned like it, as thin as asked
    a = np.radians(30)
    q = np.array(_quad((0, 0), (800 * np.cos(a), 800 * np.sin(a))))
    (c, h, ax), = meshbox.fit(q, thickness=12)
    assert np.isclose(sorted(h * 2)[0], 12) and np.isclose(max(h * 2), 800, atol=1)
    assert abs(abs(ax[0] @ [np.cos(a), 0, np.sin(a)]) - 1) < 1e-6 or abs(abs(ax[2] @ [np.cos(a), 0, np.sin(a)]) - 1) < 1e-6
    assert np.allclose(c, [400 * np.cos(a), 50, 400 * np.sin(a)], atol=1)
    # a solid crate: one box around it
    cube = []
    for (x0, z0), (x1, z1) in (((0, 0), (200, 0)), ((200, 0), (200, 200)), ((200, 200), (0, 200)), ((0, 200), (0, 0))):
        cube += _quad((x0, z0), (x1, z1), 0, 200)
    top = [np.array([[0, 200, 0], [200, 200, 0], [200, 200, 200]], float), np.array([[0, 200, 0], [200, 200, 200], [0, 200, 200]], float)]
    bot = [t - [0, 200, 0] for t in top]
    (c, h, ax), = meshbox.fit(np.array(cube + top + bot))
    assert np.allclose(h, 100) and np.allclose(c, 100)
    # taller than the mesh when asked; a cap on the number of boxes
    (c, h, ax), = meshbox.fit(np.array(_quad((0, 0), (300, 0), 0, 40)), min_height=120)
    assert np.isclose(h[1] * 2, 120) and np.isclose(c[1], 60)
    many = np.array(sum((_quad((i * 1000, 0), (i * 1000 + 100, 0)) for i in range(20)), []))
    assert len(meshbox.fit(many, max_boxes=8)) == 8


def test_coverage():
    q = np.array(_quad((0, 0), (500, 0)))
    box = (np.array([250.0, 50.0, 0.0]), np.array([260.0, 60.0, 10.0]), np.eye(3))
    assert meshbox.coverage(None, None, q, boxes=[box], walls=[]) == 1.0
    assert meshbox.coverage(None, None, q, boxes=[], walls=[]) == 0.0
    half = (np.array([0.0, 50.0, 0.0]), np.array([125.0, 60.0, 10.0]), np.eye(3))
    assert 0.2 < meshbox.coverage(None, None, q, boxes=[half], walls=[]) < 0.7
    wall = (np.array([0.0, 0.0, 1.0]), 0.0, np.array([0.0, 0.0, 0.0]), np.array([500.0, 100.0, 0.0]))
    assert meshbox.coverage(None, None, q, boxes=[], walls=[wall]) == 1.0


def test_collision_from_shape_in_the_editor():
    with tempfile.TemporaryDirectory() as tmp:
        st = _st(tmp)
        n_box = len(meshbox.map_boxes(st.opt))
        # a long railing that turns two corners, added as a mesh: nothing stops people there yet
        from vtoy import crop
        lo, hi = crop.mesh_bounds(st.opt.meshes[0])
        x, y, z = float(lo[0]) - 3000, float(lo[1]), float(lo[2]) - 3000
        tris = np.array(_quad((x, z), (x + 900, z), y, y + 110) + _quad((x + 900, z), (x + 900, z + 700), y, y + 110)
                        + _quad((x + 900, z + 700), (x + 1500, z + 700), y, y + 110))
        me = _mesh_of(st.opt, tris, "barandillas_barcos.tex")
        crop.add_mesh(st.opt, me)
        idx = len(st.opt.meshes) - 1
        found = st.without_collision("barandillas_barcos")
        assert ("mesh", idx) in [(k, i) for k, i, _ in found]
        assert st.select_without_collision("barandillas_barcos").startswith(f"{len(found)} objects")
        st.selection = Selection("mesh", st.opt.meshes[idx], "")
        st.multi = []
        msg = st.collision_from_shape("selection", thickness=8)
        assert msg.startswith("3 collision boxes following the shape of 1 objects")
        new = meshbox.map_boxes(st.opt)[n_box:]
        assert len(new) == 3 and all(np.isclose(sorted(h * 2)[0], 8) for _c, h, _a in new)
        assert ("mesh", idx) not in [(k, i) for k, i, _ in st.without_collision("barandillas_barcos")]
        # whole map, only what has none: the railing now has collision, so nothing more for it
        msg = st.collision_from_shape("map", "barandillas_barcos", only_missing=True)
        assert "already have collision" in msg or "left alone" in msg
        st.undo()
        assert len(meshbox.map_boxes(st.opt)) in (n_box, n_box + 3)
        st.save_map()
        OptMap.load(st.opt.path)
        try:
            st.selection = None
            st.multi = []
            st.collision_from_shape("selection")
            assert False
        except ValueError:
            pass


def test_lock_all_lights_and_decals():
    with tempfile.TemporaryDirectory() as tmp:
        st = _st(tmp)
        st.add_decal("x.tex") if not st.opt.decals else None
        n = len(st.opt.lights)
        assert st.lock_all(True, "light") == n and all(st.is_locked(l, "light") for l in st.opt.lights)
        assert st.lock_all(True, "light") == 0
        assert st.lock_all(True, "decal") == len(st.opt.decals) and all(st.is_locked(d, "decal") for d in st.opt.decals)
        assert not any(st.is_locked(m, "mesh") for m in st.opt.meshes[:5])
        assert "locked" in st.delete_selection(Selection("light", st.opt.lights[0], "light")) and len(st.opt.lights) == n
        assert st.lock_all(False, "light") == n and not any(st.is_locked(l, "light") for l in st.opt.lights)
        assert st.lock_all(False, "decal") == len(st.opt.decals)


def test_what_a_light_lights():
    with tempfile.TemporaryDirectory() as tmp:
        st = _st(tmp)
        sun = st.add_light(LightType.DIRECTIONAL)
        sun.direction = np.array([0.0, -1.0, 0.0], np.float32)
        sun.diffuse = (1.0, 0.9, 0.7, 0.0)
        amb = st.add_light(LightType.AMBIENT)
        amb.diffuse = (0.3, 0.3, 0.35, 0.0)
        t = st.light_impact(sun)
        assert "directional" in t and "90 degrees from above" in t and "% of the surfaces" in t
        share = int(t.split("% of the surfaces")[0].rsplit(" ", 1)[1])
        assert 10 < share < 90                                     # floors and roofs face a sun from above, walls do not
        assert "EVERY face" in st.light_impact(amb) and "35% brightness" in st.light_impact(amb)
        assert "point" in st.light_impact(next(l for l in st.opt.lights if int(l.type) == 0))
        # only one light in the lit view
        full = st.packed_lights()
        st.set_light_solo(sun)
        one = st.packed_lights()
        assert len(one["lights"]) == 1 and one["lights"][0]["type"] == 2 and np.allclose(one["ambient"], 0)
        st.set_light_solo(amb)
        one = st.packed_lights()
        assert one["lights"] == [] and np.allclose(one["ambient"], (0.3, 0.3, 0.35))
        st.delete_selection(Selection("light", amb, "light"))
        back = st.packed_lights()
        assert len(back["lights"]) == len(full["lights"]) and st.light_solo is None
        assert np.allclose(np.minimum(np.asarray(back["ambient"]) + (0.3, 0.3, 0.35), 1.0), full["ambient"])
        st.set_light_solo(None)
        # where it shines: arrows along the direction, rays all round, the reach of a point light
        g = st.light_gizmo(sun, around=(0.0, 0.0, 0.0))
        d = g[:, 1] - g[:, 0]
        assert g.shape[1:] == (2, 3) and len(g) == 125
        assert np.allclose(d[0] / np.linalg.norm(d[0]), [0, -1, 0])
        amb2 = st.add_light(LightType.AMBIENT)
        r = st.light_gizmo(amb2)
        assert len(r) > 26 and r.shape[1:] == (2, 3)
        p = next(l for l in st.opt.lights if int(l.type) == 0)
        assert len(st.light_gizmo(p)) > 10
        spot = st.add_light(LightType.SPOT)
        assert len(st.light_gizmo(spot)) > 10


def test_change_a_solid_and_its_collision():
    with tempfile.TemporaryDirectory() as tmp:
        st = _st(tmp)
        from vtoy import crop, solids
        hm = st.heightmap_edit()
        from vtoy import hmcopy
        nf0 = len(hmcopy.unique_faces(hm))
        n_box = len(meshbox.map_boxes(st.opt))
        a, b = np.array([1000.0, 500.0, 2000.0]), np.array([1600.0, 500.0, 2000.0])
        assert "created" in st.add_solid_between("rail", a, b, 12.0, 110.0, "tablones.tex")
        me = st.selection.ref
        info = st.solid_of(st.selection)
        assert info["shape"] == "rail" and np.isclose(info["length"], 600) and np.isclose(info["height"], 110)
        nf1 = len(hmcopy.unique_faces(st.heightmap_edit()))
        assert nf1 == nf0 + 4 and len(meshbox.map_boxes(st.opt)) == n_box + 1
        n_mesh = len(st.opt.meshes)
        # move it, turn it 90 degrees, make it taller: one box, the same number of faces, the box where the rail is
        msg = st.edit_solid(st.selection, at=[1300.0, 600.0, 2500.0], yaw=90.0, height=200.0)
        assert "changed" in msg and len(st.opt.meshes) == n_mesh and all(m is not me for m in st.opt.meshes)
        boxes = meshbox.map_boxes(st.opt)
        assert len(boxes) == n_box + 1
        c, h, R = boxes[-1]
        assert np.allclose(c, [1300, 700, 2500], atol=0.5) and np.allclose(sorted(h), sorted([300, 100, 6]), atol=0.5)
        assert abs(R[0, 0]) < 1e-3                                               # turned
        assert len(hmcopy.unique_faces(st.heightmap_edit())) == nf1
        lo, hi = crop.mesh_bounds(st.selection.ref)
        assert np.isclose(hi[1] - lo[1], 200, atol=0.5) and np.isclose(hi[2] - lo[2], 600, atol=1)
        assert st.solid_of(st.selection)["height"] == 200.0
        # one undo step gives the first one back
        st.undo()
        assert len(meshbox.map_boxes(st.opt)) == n_box + 1 and np.allclose(meshbox.map_boxes(st.opt)[-1][0], [1300, 555, 2000], atol=0.5)
        # a mesh not made here is not a solid
        assert st.solid_of(Selection("mesh", st.opt.meshes[0], "")) is None
        # turning any collision box
        i = len(meshbox.map_boxes(st.opt)) - 1
        cc, hh = st.collision_box(i)
        st.set_collision_box(i, cc, hh, 30.0)
        assert abs(st.collision_box_yaw(i) - 30.0) < 1e-3


def test_export_takes_every_dll_of_the_modules():
    import os, zipfile
    with tempfile.TemporaryDirectory() as tmp:
        st = _st(tmp)
        names = st.scene_dll_names()
        assert names[0].lower() == str(st.scene.main_module_name).rstrip("\0").lower()
        kinds = {str(r.module_name).rstrip("\0").lower() for r in st.scene.modules}
        assert {n.lower() for n in names} >= kinds and len(names) == len({n.lower() for n in names})
        # the installation keeps them in comun/bin/release (any case); one of them is missing
        inst = os.path.dirname(os.path.abspath(st.fs.root))
        rel = os.path.join(inst, "comun", "bin", "release")
        os.makedirs(rel, exist_ok=True)
        st.game_dir = ""
        for n in names[:-1]:
            open(os.path.join(rel, n.upper()), "wb").write(b"MZ" + n.encode())
        assert st.game_dll_dir() == rel
        st.save_map(); st.save_scene()
        out = os.path.join(tmp, "exp.zip")
        r = st.export_map_zip(out)
        got = {n.lower() for n in zipfile.ZipFile(out).namelist() if n.startswith("dll/")}
        assert {("dll/" + n).lower() for n in names[:-1]} <= got
        assert "dll/" + names[-1] in r["missing"] or ("dll/" + names[-1]).lower() in got
        # installing puts them where the game has its DLLs, never over a different one
        os.remove(os.path.join(rel, names[0].upper()))
        msg = st.install_map_zip(out)
        assert os.path.isfile(os.path.join(rel, names[0].upper())) and "installed" in msg


def test_find_modules():
    with tempfile.TemporaryDirectory() as tmp:
        st = _st(tmp)
        snd = st.find_modules("mp_soundsource")
        assert snd and all(r.clean_name.lower() == "mp_soundsource" for r in snd)
        assert len(st.find_modules("MP_SoundSource")) == len(snd) and st.find_modules("") == list(st.scene.modules)
        gav = st.find_modules("gaviota")                       # a word of the name / the sound
        assert gav and all("gaviota" in st.module_search_text(r) for r in gav)
        assert st.find_modules("gaviota mp_soundsource") and not st.find_modules("gaviota nada_de_esto")
        for r in gav:                                              # (locks and hidden ones are remembered between runs)
            st.set_locked(r, False)
            st.set_hidden(r, False)
        assert st.select_modules(gav) == f"{len(gav)} modules selected" and st.selection.ref is gav[0]
        st.set_locked(gav[0], True)
        assert st.select_modules(gav) == f"{len(gav) - 1} modules selected"
        st.set_locked(gav[0], False)


def test_save_as_and_names_of_the_map_files():
    import os
    from vtoy import dllpatch
    with tempfile.TemporaryDirectory() as tmp:
        st = _st(tmp)
        st.save_map(); st.save_scene()
        nfos = os.path.dirname(st.opt.path)
        # a copy left over by a save that failed half way (no scene uses it): moved aside, not in the way
        open(os.path.join(nfos, "mp_dm_nuevo.opt"), "wb").write(b"half")
        # the weather copy of the mode DLL cannot be made: the save still works and says so
        real = dllpatch.patch_map_name
        st.custom_dll_path = lambda: st.opt.path                # any file: "has a weather string", patching fails

        def boom(*a, **k):
            raise ValueError("the comparison string is never referenced")
        dllpatch.patch_map_name, dllpatch_find = boom, dllpatch.find_weather_string
        dllpatch.find_weather_string = lambda data: b"x"
        try:
            msg = st.rename_map("mp_dm_nuevo")
        finally:
            dllpatch.patch_map_name, dllpatch.find_weather_string = real, dllpatch_find
            del st.custom_dll_path
        assert "WARNING" in msg and "was kept as it is" in msg
        assert st.scene_name == "mp_dm_nuevo.scn" and os.path.basename(st.opt.path) == "mp_dm_nuevo.opt"
        assert open(os.path.join(nfos, "mp_dm_nuevo.opt.old"), "rb").read() == b"half"
        OptMap.load(st.opt.path)
        # the same name again: a clear message, nothing replaced
        try:
            st.save_scene_as("mp_dm_nuevo")
            assert False
        except ValueError as e:
            assert "already" in str(e)
        # a .opt another scene uses is never replaced: a clear message, and nothing half written is left
        st.rename_map("mp_dm_quinto")                           # quinto uses mp_dm_quinto.opt
        st.load("mp_dm_nuevo.scn")
        before = sorted(os.listdir(nfos))
        open(os.path.join(nfos, "mp_dm_sexto.opt"), "wb").write(b"x")
        import shutil as _sh
        _sh.copy2(os.path.join(os.path.dirname(st.scene.path), "mp_dm_quinto.scn"),
                  os.path.join(os.path.dirname(st.scene.path), "mp_dm_usa_sexto.scn"))
        sc = open(os.path.join(os.path.dirname(st.scene.path), "mp_dm_usa_sexto.scn"), "rb").read()
        open(os.path.join(os.path.dirname(st.scene.path), "mp_dm_usa_sexto.scn"), "wb").write(
            sc.replace(b"mp_dm_quinto.opt", b"mp_dm_sexto.opt\0"[:len(b"mp_dm_quinto.opt")]))
        try:
            st.rename_map("mp_dm_sexto")
            assert False
        except ValueError as e:
            assert "uses it" in str(e) and "never replaced" in str(e)
        assert open(os.path.join(nfos, "mp_dm_sexto.opt"), "rb").read() == b"x"
        assert not os.path.exists(os.path.join(os.path.dirname(st.scene.path), "mp_dm_sexto.scn"))
        assert st.scene_name == "mp_dm_nuevo.scn" and os.path.basename(st.opt.path) == "mp_dm_nuevo.opt"
        # .opt / .hm named like the scene
        st.load("mp_dm_nuevo.scn")
        st.rename_map("mp_dm_tercero")                          # tercero.scn -> tercero.opt
        st.scene.map_name = "nfos\\mp_dm_nuevo.opt"             # as if it used other names
        st.opt.path = os.path.join(nfos, "mp_dm_nuevo.opt")
        st.save_scene()
        st.load("mp_dm_tercero.scn")
        assert st.map_file_names()[1] == "mp_dm_nuevo.opt"
        msg = st.name_files_like_scene()
        assert "mp_dm_tercero.opt" in msg and st.map_file_names()[1:] == ("mp_dm_tercero.opt", "mp_dm_tercero.hm")
        st.load("mp_dm_tercero.scn")
        assert os.path.basename(st.opt.path) == "mp_dm_tercero.opt"
        assert os.path.exists(os.path.join(nfos, "mp_dm_nuevo.opt"))      # the old one stays
        assert "already called" in st.name_files_like_scene()
        # refreshing the lists: a scene added on disk shows up, maps are read again
        import shutil
        shutil.copy2(st.scene.path, os.path.join(os.path.dirname(st.scene.path), "mp_dm_cuarto.scn"))
        assert "mp_dm_cuarto.scn" not in st.scene_names()
        assert "scenes" in st.reload_fs() and "mp_dm_cuarto.scn" in st.scene_names() and not st.fs._opt


def test_log_can_be_turned_off_and_on():
    import os, subprocess, sys
    code = ("import sys; sys.path.insert(0, %r)\n"
            "from vtoy.app import outputs\n"
            "outputs.setup(True); print('uno'); outputs.set_log(False); print('dos'); outputs.set_log(True); print('tres')\n"
            "assert outputs.log_on()\n") % os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with tempfile.TemporaryDirectory() as tmp:
        r = subprocess.run([sys.executable, "-c", code], cwd=tmp, capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        log = open(os.path.join(tmp, "vtoy_editor.log"), encoding="utf-8").read()
        assert "uno" in log and "dos" not in log and "tres" in log and "VToyEditor log" in log
        assert "uno" in r.stdout and "dos" in r.stdout                  # the console always gets everything
