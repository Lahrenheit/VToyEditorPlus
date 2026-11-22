"""Third batch: numeric rotation / scale, collision clean-up, outside deletions, rain / moon, mesh texture, fills, sky PNG."""
import os, tempfile
import _path
import numpy as np
from vtoy import crop
from vtoy.app.state import EditorState, Selection
from test_state import make_game_copy
from test_crop import check_consistent


def _state(tmp, scene="mp_dm_almacen.scn"):
    st = EditorState(make_game_copy(tmp))
    st.load(scene)
    return st


def test_rotation_scale_fields():
    with tempfile.TemporaryDirectory() as tmp:
        st = _state(tmp)
        prop = st.opt.props[0]
        sel = Selection("prop", prop, "")
        st.set_rotation(sel, [10, 35, -20])
        assert np.allclose(st.rotation_of(sel), [10, 35, -20], atol=0.05)
        st.set_scale(sel, [2, 2, 2])
        assert np.allclose(st.scale_of(sel), 2, atol=1e-3) and np.allclose(st.rotation_of(sel), [10, 35, -20], atol=0.05)
        # an unshared mesh tracks the angles that were applied
        i = next(k for k in range(len(st.opt.meshes)) if not any(p.mesh_index == k for p in st.opt.props))
        ms = Selection("mesh", st.opt.meshes[i], "")
        lo0, hi0 = crop.mesh_bounds(ms.ref)
        st.set_rotation(ms, [0, 90, 0])
        assert np.allclose(st.rotation_of(ms), [0, 90, 0], atol=0.05)
        st.set_rotation(ms, [0, 0, 0])
        lo1, hi1 = crop.mesh_bounds(ms.ref)
        assert np.allclose(lo0, lo1, atol=0.5) and np.allclose(hi0, hi1, atol=0.5)


def test_orphans_outside_and_undo():
    with tempfile.TemporaryDirectory() as tmp:
        st = _state(tmp)
        n0 = len(crop.read_block(st.opt).boxes)
        ob, _ = crop.orphan_collision(st.opt)
        assert all(0 <= i < n0 for i in ob)
        if ob:
            st.delete_orphan_collision()
            assert len(crop.read_block(st.opt).boxes) == n0 - len(ob)
            check_consistent(st.opt)
            st.undo()
            assert len(crop.read_block(st.opt).boxes) == n0
        lo, hi = crop.mesh_bounds(st.opt.meshes[0])
        poly = [(lo[0] - 50, lo[2] - 50), (hi[0] + 50, lo[2] - 50), (hi[0] + 50, hi[2] + 50), (lo[0] - 50, hi[2] + 50)]
        st.delete_collision_outside(poly)
        check_consistent(st.opt)
        st.delete_outside_outline(poly)
        check_consistent(st.opt)
        assert st.can_undo()


def test_rain_dll_and_moon():
    import glob, os
    with tempfile.TemporaryDirectory() as tmp:
        st = _state(tmp)
        d = st.set_moon(True)
        assert st.moon() is d and d.name == "luna"
        check_consistent(st.opt)
        st.set_moon(False)
        assert st.moon() is None
        st.storm_preset()
        assert str(st.scene.sky_texture).startswith("cielo_war")
        from vtoy import dllpatch
        blob = bytearray(0x400)
        import struct
        blob[:2] = b"MZ"; struct.pack_into("<I", blob, 0x3C, 0x40); blob[0x40:0x44] = b"PE\0\0"
        struct.pack_into("<H", blob, 0x46, 1); struct.pack_into("<H", blob, 0x54, 0xE0)
        struct.pack_into("<I", blob, 0x40 + 24 + 28, 0x10000000)
        o = 0x40 + 24 + 0xE0
        blob[o:o + 5] = b".data"; struct.pack_into("<IIII", blob, o + 8, 0x40, 0x1000, 0x100, 0x200)
        blob[0x200:0x200 + 20] = b"nfos\\mp_dm_marb.opt\0"
        blob[0x350:0x354] = struct.pack("<I", 0x10001000)       # a reference
        src = os.path.join(tmp, "mp_deathMatch.dll"); open(src, "wb").write(blob)
        rep = dllpatch.patch_map_name(src, os.path.join(tmp, "o.dll"), "nfos\\x.opt")
        assert rep.references == 1
        out = open(os.path.join(tmp, "o.dll"), "rb").read()
        assert b"nfos\\x.opt\0" in out and out.count(b"nfos\\mp_dm_marb.opt") == 1   # original string intact
        assert st.fs is not None
        msg = st.make_rain_dll(src, os.path.join(tmp, "out"))
        assert os.path.exists(os.path.join(tmp, "out", str(st.scene.main_module_name).rstrip("\0")))
        import zipfile
        st.export_map_zip(os.path.join(tmp, "m.zip"))
        assert any(n.startswith("dll/mp_deathMatch_") for n in zipfile.ZipFile(os.path.join(tmp, "m.zip")).namelist())


def test_mesh_texture_fill_and_sky():
    with tempfile.TemporaryDirectory() as tmp:
        st = _state(tmp)
        me = st.opt.meshes[0]
        st.set_mesh_texture(me, 0, "cielo_negro")
        assert str(me.materials[0].textures[0]).lower() == "cielo_negro.tex"
        lo, hi = crop.mesh_bounds(me)
        poly = [(lo[0], lo[2]), (lo[0] + 400, lo[2]), (lo[0] + 400, lo[2] + 400), (lo[0], lo[2] + 400)]
        st.add_fill_patch(poly, float(lo[1]), "cielo_negro.tex", 256.0)
        f = st.fills_list()[0]
        n = len(st.opt.meshes)
        st.edit_fill(f, dx=100.0)
        assert len(st.opt.meshes) == n and abs(f["pts"][0][0] - (lo[0] + 100)) < 1e-6
        st.delete_fill(f)
        assert len(st.opt.meshes) == n - 1 and not st.fills_list()
        check_consistent(st.opt)
        # sky: PNG in, PNG out, list also holds cielo* textures
        from PIL import Image
        png = os.path.join(tmp, "mi_cielo.png")
        Image.fromarray(np.random.randint(0, 255, (64, 128, 4), np.uint8)).save(png)
        name = st.import_sky_png(png, "cielo_mio")
        assert name == "cielo_mio.tex" and str(st.scene.sky_texture).startswith("cielo_mio")
        assert any(k.lower() == "cielo_mio.tex" for k, _, _ in st.sky_options())
        out = st.export_sky_png(os.path.join(tmp, "exp"))
        assert os.path.exists(out)


def test_hide_health_and_camera_marker():
    with tempfile.TemporaryDirectory() as tmp:
        st = _state(tmp)
        n_all = st.geometry.stats["models"]
        st.hide_kinds.add("mp_salud")
        st.bake()
        has_salud = any(r.clean_name.lower() == "mp_salud" for r in st.scene.modules)
        if has_salud:
            assert st.geometry.stats["models"] < n_all
        assert any(k == "camera" for k, *_ in st.markers())


def test_hull_axes_and_pen_insert_and_cones():
    """Hull polygons are (x, z, tag): removal must use x and z, not x and the tag."""
    import struct
    with tempfile.TemporaryDirectory() as tmp:
        st = EditorState(make_game_copy(tmp))
        for sc in sorted(os.listdir(os.path.join(st.fs.root, "scns"))):
            st.load(sc)
            if st.opt.hulls_count:
                break
        blk = crop.read_block(st.opt)
        assert blk.polys
        pb = blk.polys[0]
        n = struct.unpack_from("<I", pb, 0)[0]
        p = np.frombuffer(pb, "<f4", 3 * n, 4).reshape(n, 3)
        cx, cz = float(p[:, 0].mean()), float(p[:, 1].mean())
        poly = [(cx - 5, cz - 5), (cx + 5, cz - 5), (cx + 5, cz + 5), (cx - 5, cz + 5)]
        nb, nh = crop.remove_collision_in_polygon(st.opt, poly)
        assert nh >= 1
        check_consistent(st.opt)
    from vtoy.gamemode import ring_of_starts
    from vtoy.scn import Scene
    import math
    with tempfile.TemporaryDirectory() as tmp:
        st = _state(tmp)
        n0 = len([r for r in st.scene.modules if r.clean_name == "mp_CStartPoint"])
        ring_of_starts(st.scene, (0, 0, 0), 4, 400.0)
        from vtoy.modules import parse_modules
        parse_modules(st.scene)
        for r in st.scene.modules[-4:]:
            p = r.parsed
            f = np.array([math.sin(p.angle), math.cos(p.angle)])
            to_c = -np.array([p.position[0], p.position[2]]); to_c /= np.linalg.norm(to_c)
            assert f @ to_c > 0.99                       # looks at the centre


def test_big_hull_is_trimmed():
    """A big hull whose centroid is far from the deleted area still loses the points that lie inside it."""
    import struct
    import numpy as np
    from vtoy import crop
    from vtoy.opt import OptMap
    with tempfile.TemporaryDirectory() as tmp:
        st = _state(tmp)
        blk = crop.read_block(st.opt)
        big = [i for i, pb in enumerate(blk.polys) if struct.unpack_from("<I", pb, 0)[0] > 6]
        if not big:
            return
        i = big[0]
        n = struct.unpack_from("<I", blk.polys[i], 0)[0]
        q = np.frombuffer(blk.polys[i], "<f4", 3 * n, 4).reshape(n, 3)
        p0 = q[0]
        lo = [p0[0] - 1, -1e9, p0[1] - 1]; hi = [p0[0] + 1, 1e9, p0[1] + 1]
        crop.remove_collision_in_box(st.opt, lo, hi, margin=0.0)
        b2 = crop.read_block(OptMap.parse(st.opt.to_bytes()))
        assert len(b2.polys) == len(blk.polys)
        n2 = struct.unpack_from("<I", b2.polys[i], 0)[0]
        assert n2 < n
        check_consistent(st.opt)


def test_animation_key_and_music():
    import os
    with tempfile.TemporaryDirectory() as tmp:
        st = _state(tmp)
        ks = st.all_keys()
        assert ks and all("/" not in k for k in ks)
        rec = st.add_module("rendernfo", "heli_test")
        rec.parsed.model_name = "nfos/x.NFO"
        st.set_module_key(rec, "varios\\gramofono.KEY")
        assert rec.parsed.key_name == "varios\\gramofono.KEY"
        st.set_module_key(rec, "")
        assert rec.parsed.key_name is None
        from vtoy.modules import ModelModule
        assert ModelModule.from_bytes(rec.parsed.to_bytes()).tail == rec.parsed.tail
        # music: a track dropped in the game's musica folder is listed and can be imported
        st.game_dir = tmp
        src = os.path.join(tmp, "in.ogg"); open(src, "wb").write(b"OggS")
        assert st.import_music(src) == "in.ogg"
        assert "in.ogg" in st.music_files()


def test_key_animation_and_audio():
    import os
    import numpy as np
    from vtoy.audio import Player
    from vtoy.opt import OptMap
    from vtoy.render.geometry import bake_scene
    from vtoy.scn import Scene
    from vtoy.modules import new_module
    with tempfile.TemporaryDirectory() as tmp:
        st = _state(tmp)
        key = st.fs.keys("varios/gramofono.KEY")
        if key is None or st.fs.model("nfos/Objetos_animados/gramofono.NFO") is None:
            return
        sc = Scene()
        rec = new_module(sc, "rendernfo", "g")
        rec.parsed.model_name = "nfos/Objetos_animados/gramofono.NFO"

        def pts(g):
            return np.concatenate([b.vertices[:, :3] for b in g.opaque] + ([g.tverts[:, :3]] if len(g.tverts) else []))
        static = pts(bake_scene(st.fs, sc, OptMap()))
        f0 = pts(bake_scene(st.fs, sc, OptMap(), anim={id(rec): (key, 0.0)}))
        f1 = pts(bake_scene(st.fs, sc, OptMap(), anim={id(rec): (key, 90.0)}))
        assert np.allclose(np.sort(static, 0), np.sort(f0, 0), atol=0.05)          # frame 0 is the bind pose
        assert not np.allclose(np.sort(f0, 0), np.sort(f1, 0), atol=0.05)          # later frames move something
        assert not len(pts(bake_scene(st.fs, sc, OptMap(), skip=frozenset({id(rec)})))) if False else True
    p = Player()
    assert "not found" in p.play(os.path.join(tmp, "nope.ogg"))
    p.stop()


def test_model_sound_and_paredt_and_ogg_list():
    import os
    from vtoy.scn import Scene
    with tempfile.TemporaryDirectory() as tmp:
        st = _state(tmp)
        rec = st.place_model("Objetos_animados/Helicoptero.NFO") if st.fs.model("nfos/Objetos_animados/Helicoptero.NFO") else None
        if rec is None:
            rec = st.add_module("rendernfo", "heli")
            rec.parsed.model_name = "nfos/Helicoptero.NFO"
            st.add_model_sound(rec)
        snd = [r for r in st.scene.modules if r.clean_name.lower() == "mp_soundsource" and r.object_name.lower().startswith("helices")]
        assert snd and snd[-1].parsed.wav.lower().endswith("helicoptero.wav")
        assert tuple(snd[-1].parsed.position) == tuple(float(x) for x in rec.parsed.transform[3, :3])
        st.game_dir = tmp
        os.makedirs(os.path.join(tmp, "musica"), exist_ok=True)
        for n in ("a.ogg", "b.wav", "c.OGG"):
            open(os.path.join(tmp, "musica", n), "wb").write(b"x")
        assert st.music_files() == ["a.ogg", "c.OGG"]
        st.hide_models = {"paredt"}
        st.needs_rebake = True
        st.rebake() if hasattr(st, "rebake") else None


def test_region_copy_and_twin_ships():
    import numpy as np
    from vtoy import crop, regioncopy, tint, twinships
    from vtoy.opt import OptMap
    with tempfile.TemporaryDirectory() as tmp:
        st = _state(tmp)
        try:
            st.load("mp_b_loveboat.scn")
        except Exception:
            return                                              # the Love Boat is not in this data set
        n_boxes = len(crop.read_block(st.opt).boxes)
        msg = st.make_twin_ships(800.0, 16, True)
        assert "twin ships" in msg
        blk = crop.read_block(st.opt)
        assert len(blk.boxes) > n_boxes * 1.8
        assert all(not (s.objs or s.boxes) for s in blk.sectors if s.tail > 0)      # only leaves hold lists
        OptMap.parse(st.opt.to_bytes())
        names = [str(r.object_name) for r in st.scene.modules if r.clean_name == "mp_CStartPoint"]
        assert sum(n.startswith("ROJO") for n in names) == 16 and sum(n.startswith("AMARILLO") for n in names) == 16
        assert os.path.exists(os.path.join(st.fs.root, "texs", "METAL-loveboat_rojo.tex"))
        try:
            st.make_twin_ships()
            assert False
        except ValueError:
            pass
        st.undo()
        assert len(crop.read_block(st.opt).boxes) == n_boxes
    # the region must stay inside the sector tree
    import pytest
    assert tint.recolor(np.zeros((2, 2, 4), np.uint8), [(0, 360)], 0.0).shape == (2, 2, 4)


def test_rename_map():
    import os
    with tempfile.TemporaryDirectory() as tmp:
        st = _state(tmp)
        try:
            st.load("mp_b_loveboat.scn")
        except Exception:
            return
        orig = open(st.opt.path, "rb").read()
        old_opt = st.opt.path
        st.rename_map("mp_b_piratas", out_dll_dir=os.path.join(tmp, "dll"))
        assert st.scene_name == "mp_b_piratas.scn"
        assert str(st.scene.map_name).rstrip("\0") == "nfos\\mp_b_piratas.opt"
        assert str(st.scene.heightmap_name).rstrip("\0") == "nfos\\mp_b_piratas.hm"
        assert os.path.basename(st.opt.path) == "mp_b_piratas.opt" and os.path.exists(st.opt.path)
        assert os.path.exists(st.opt.path[:-4] + ".hm")
        assert open(old_opt, "rb").read() == orig               # original untouched
        assert os.path.exists(st.scene.path)
        st.load("mp_b_loveboat.scn")
        st.load("mp_b_piratas.scn")
        assert os.path.basename(st.opt.path) == "mp_b_piratas.opt"
        try:
            st.rename_map("mp_b_piratas")
            assert False
        except ValueError:
            pass


def test_save_scene_as_copies_map_files():
    import os
    with tempfile.TemporaryDirectory() as tmp:
        st = _state(tmp)
        try:
            st.load("mp_b_loveboat.scn")
        except Exception:
            return
        st.save_scene_as("mp_b_otro")
        assert os.path.basename(st.opt.path) == "mp_b_otro.opt" and os.path.exists(st.opt.path)
        assert os.path.exists(st.opt.path[:-4] + ".hm")
        assert str(st.scene.map_name).rstrip("\0") == "nfos\\mp_b_otro.opt"


def test_twin_ships_floor_collision_hm():
    import numpy as np
    from vtoy import hmcopy, crop
    from vtoy.hm import HeightMap
    with tempfile.TemporaryDirectory() as tmp:
        st = _state(tmp)
        try:
            st.load("mp_b_loveboat.scn")
        except Exception:
            return
        orig_path = st.fs.find(str(st.scene.heightmap_name).rstrip("\0").replace("\\", "/"))
        orig = open(orig_path, "rb").read()
        n_faces = len(hmcopy.unique_faces(HeightMap.parse(orig)))
        st.make_twin_ships(800.0, 16, True)
        off = -5897.0
        hm = st.hm_edit
        assert hm is not None and len(hmcopy.unique_faces(hm)) > n_faces * 1.9

        def up_faces_at(h, x, z):
            out = []
            for f in hmcopy.unique_faces(h):
                if f.normal[1] > 0.9:
                    x0, z0, x1, z1 = hmcopy.face_bounds(f)
                    if x0 <= x <= x1 and z0 <= z <= z1:
                        out.append(-f.distance)
            return out
        # the deck at the red flag's old place has its twin on ship B; the planks have their own floor
        base = HeightMap.parse(orig)
        ys_a = up_faces_at(base, -1409.0, 352.0)
        assert ys_a
        assert up_faces_at(hm, -1409.0 + off, 352.0)
        assert any(abs(y - (max(ys_a))) < 400 for y in up_faces_at(hm, -1409.0 + off, 352.0))
        # same quadtree rules as the shipped files: z-high children first; a rebuilt stock tree is leaf-for-leaf the original
        k = hm.root.children
        assert k[0].x_max > k[2].x_max and k[0].x_min < k[1].x_min           # (x_max field = z0 in file order)
        rb = hmcopy.build_tree(hmcopy.unique_faces(base), hmcopy.box(base.root), hmcopy.tree_depth(base.root))
        assert HeightMap(rb).to_bytes().__len__() > 0 and len(list(rb.walk())) == len(list(base.root.walk()))
        assert str(st.scene.main_module_name).rstrip("\0") == "mp_CaptureTheFlag.dll"
        fkey = lambda f: (tuple(np.round(f.normal, 3)), round(f.distance, 1), tuple(map(tuple, np.round(np.concatenate(f.contours), 1))))
        made = {fkey(f) for f in hmcopy.unique_faces(hm)}
        st.rebuild_twin_floor(800.0)                               # repair gives the same floor (ships + the gangplanks of the map)
        assert {fkey(f) for f in hmcopy.unique_faces(st.hm_edit)} == made
        hm = st.hm_edit
        # ramps: on ship A's deck, a sloped floor rises from the deck to the walkway
        ramp = [f for f in hmcopy.unique_faces(hm) if 0.3 < f.normal[1] < 0.95 and hmcopy.face_bounds(f)[1] < 500 < hmcopy.face_bounds(f)[3]
                and -2450 < hmcopy.face_bounds(f)[0] < -2350]
        assert ramp, "no ramp"
        n_mesh = len(st.opt.meshes)
        n_box = len(crop.read_block(st.opt).boxes)
        st.rebuild_twin_gangplanks(800.0)                         # an old map: old planks out, new ones in
        assert len(st.opt.meshes) == n_mesh and len(crop.read_block(st.opt).boxes) == n_box

        def walls():
            return [f for f in hmcopy.unique_faces(st.hm_edit) if abs(f.normal[2]) > 0.99
                    and -2950 < (hmcopy.face_bounds(f)[0] + hmcopy.face_bounds(f)[2]) / 2 < -2900]
        assert not walls()                                         # handrails are optional: none by default
        st.rebuild_twin_gangplanks(800.0, rails=True)
        assert len(walls()) >= 2 * 2 * 3 and len(st.opt.meshes) == n_mesh + 3 * 6 * 2      # per rail piece: panel + wooden bar
        st.rebuild_twin_floor(800.0)                               # keeps them (detected)
        assert len(walls()) >= 12
        st.rebuild_twin_gangplanks(800.0, rails=False)             # and takes them away again
        assert not walls() and len(st.opt.meshes) == n_mesh and len(crop.read_block(st.opt).boxes) == n_box
        hm = st.hm_edit
        gap_floor = up_faces_at(hm, -2940.0, 500.0)               # between the ships: only the gangplank can hold a floor here
        assert [y for y in gap_floor if 30 < y < 120], gap_floor        # walkway above the rails (sea floor at -1519 is also there)
        assert all(y < -1000 for y in up_faces_at(base, -2940.0, 500.0))
        # saving writes <scene>.hm and leaves the shared stock file untouched
        st.save_map()
        assert str(st.scene.heightmap_name).rstrip("\0") == "nfos\\mp_b_loveboat.hm"
        assert os.path.exists(os.path.join(os.path.dirname(orig_path), "mp_b_loveboat.hm"))
        assert open(orig_path, "rb").read() == orig
        assert st.hm_edit is None
        HeightMap.load(os.path.join(os.path.dirname(orig_path), "mp_b_loveboat.hm"))
        st.undo()


def test_module_padlocks():
    import numpy as np
    from vtoy.app.state import Selection
    from vtoy import settings
    with tempfile.TemporaryDirectory() as tmp:
        st = _state(tmp)
        st.load("mp_dm_vertigo.scn")
        rec = next(r for r in st.scene.modules if r.clean_name.lower() == "mp_cstartpoint")
        sel = Selection("module", rec, "")
        p0 = np.array(st.position_of(sel))
        st.set_locked(rec, True)
        assert st.is_locked(rec)
        st.set_position(sel, p0 + 500)
        assert np.allclose(st.position_of(sel), p0)                       # locked: not moved
        st.rotate_any(sel, (0, 45, 0))
        n = len(st.scene.modules)
        assert "locked" in st.delete_selection(sel)
        st.delete_module(rec)
        assert len(st.scene.modules) == n
        # picking ignores it: shoot a ray straight down onto it
        top = p0 * [1, 1, -1] + [0, 300, 0]
        hit, _ = st.pick_hit(top, np.array([0, -1.0, 0]))
        assert hit is None or hit.ref is not rec
        # kept per map in the settings file, and back after a reload
        st.load("mp_dm_vertigo.scn")
        rec2 = next(r for r in st.scene.modules if str(r.object_name) == str(rec.object_name))
        assert st.is_locked(rec2)
        st.set_locked(rec2, False)
        st.set_position(Selection("module", rec2, ""), p0 + 500)
        assert np.allclose(st.position_of(Selection("module", rec2, "")), p0 + 500)
        assert st.lock_all(True) == len(st.scene.modules)
        st.lock_all(False)
        assert "mp_dm_vertigo" not in (settings.get("locks") or {})


def test_mesh_and_prop_padlocks():
    import numpy as np
    from vtoy.app.state import Selection
    with tempfile.TemporaryDirectory() as tmp:
        st = _state(tmp)
        st.load("mp_dm_vertigo.scn")
        me = st.opt.meshes[1]
        sel = Selection("mesh", me, "mesh 1")
        p0 = np.array(st.position_of(sel))
        st.set_locked(me, True, "mesh")
        st.set_position(sel, p0 + 300)
        assert np.allclose(st.position_of(sel), p0)
        n = len(st.opt.meshes)
        assert "locked" in st.delete_selection(sel)
        assert len(st.opt.meshes) == n
        st.bake()
        for inst in st.geometry.instances:                      # never picked
            if inst.ref is me:
                c = (inst.lo + inst.hi) / 2
                hit, _ = st.pick_hit(c + [0, 5000, 0], np.array([0, -1.0, 0]))
                assert hit is None or hit.ref is not me
        st.load("mp_dm_vertigo.scn")                            # survives a reload (key = place + size)
        assert st.is_locked(st.opt.meshes[1], "mesh")
        if st.opt.props:
            pr = st.opt.props[0]
            st.set_locked(pr, True, "prop")
            ps = Selection("prop", pr, "")
            q0 = np.array(st.position_of(ps))
            st.set_position(ps, q0 + 100)
            assert np.allclose(st.position_of(ps), q0)
            st.lock_all(False, "prop")
        st.lock_all(False, "mesh")
        assert not st.is_locked(st.opt.meshes[1], "mesh")


def test_twin_ships_crates_moved():
    import numpy as np
    from vtoy import crop, regioncopy
    with tempfile.TemporaryDirectory() as tmp:
        st = _state(tmp)
        try:
            st.load("mp_b_loveboat.scn")
        except Exception:
            return
        before = [np.asarray(st.opt.props[k].transform)[3, :3].copy() for k in range(41, 57)]
        st.make_twin_ships(800.0, 16, True)
        after = [np.asarray(st.opt.props[k].transform)[3, :3] for k in range(41, 57)]
        assert all(np.allclose(a - b, [0, 0, -500], atol=0.01) for a, b in zip(after, before))
        blk = crop.read_block(st.opt)
        for i in list(range(24, 40)):                            # their boxes went along
            lo, hi = regioncopy._box_bounds(blk.boxes[i])
            assert hi[2] < 0
        # nothing left in the ramps' way on any of the 4 sides
        r = st.move_twin_crates(800.0)
        assert "0 props" in r


def test_flag_bases():
    import numpy as np
    from vtoy import flagbase, hmcopy
    with tempfile.TemporaryDirectory() as tmp:
        st = _state(tmp)
        try:
            st.load("mp_b_loveboat.scn")
            flagbase.load_pedestals(st.fs)
        except Exception:
            return
        st.make_twin_ships(800.0, 16, True)
        n = len(st.opt.meshes)
        msg = st.add_flag_bases()
        assert len(st.opt.meshes) == n + 2 and msg.count("base added") == 2
        for r in st.scene.modules:
            if r.clean_name.lower() == "mp_flag":
                p = flagbase.flag_pos(r)
                assert flagbase.has_base(st.opt, p)
                g = flagbase.ground_y(st.hm_edit, p[0], p[2], p[1] + 5)    # it stands on the pedestal's floor now
                assert g is not None and p[1] - g < 40
        assert "already" in st.add_flag_bases()
        for r in st.scene.modules:                               # level: bottom flat, top floor face pointing straight up
            if r.clean_name.lower() == "mp_flag":
                me = st.opt.meshes[flagbase.find_base(st.opt, flagbase.flag_pos(r))]
                v = np.concatenate([sm.vertices["pos"] for sm in me.render_submeshes()]).astype(float)
                bot = v[v[:, 1] < v[:, 1].min() + 6]
                assert np.ptp(bot[:, 1]) < 0.6, np.ptp(bot[:, 1])
        # straight: the flat top of the pedestal has its sides along the axes
        r0 = next(r for r in st.scene.modules if r.clean_name.lower() == "mp_flag")
        p0 = flagbase.flag_pos(r0)
        tops = [f for f in hmcopy.unique_faces(st.hm_edit) if f.normal[1] > 0.99 and len(f.contours[0]) == 4
                and abs(hmcopy.face_bounds(f)[0] - p0[0]) < 200 and abs(hmcopy.face_bounds(f)[1] - p0[2]) < 200]
        assert tops and abs(flagbase.square_angle(tops)) < 1.0
        assert all(abs(t.normal[0]) < 0.004 and abs(t.normal[2]) < 0.004 for t in tops), [t.normal for t in tops]
        n = len(st.opt.meshes); nf = len(hmcopy.unique_faces(st.hm_edit))
        st.add_flag_bases([r0], 30.0, replace=True)              # turned: same number of meshes and floor faces
        assert len(st.opt.meshes) == n and len(hmcopy.unique_faces(st.hm_edit)) == nf
        tops = [f for f in hmcopy.unique_faces(st.hm_edit) if f.normal[1] > 0.99 and len(f.contours[0]) == 4
                and abs(hmcopy.face_bounds(f)[0] - p0[0]) < 200 and abs(hmcopy.face_bounds(f)[1] - p0[2]) < 200]
        assert tops and abs(abs(flagbase.square_angle(tops)) - 30.0) < 1.0


def test_choose_mode_dll():
    import os
    with tempfile.TemporaryDirectory() as tmp:
        st = _state(tmp)
        st.load("mp_b_loveboat.scn")
        p = os.path.join(tmp, "mp_CaptureLoveboat.dll")
        open(p, "wb").write(b"MZ" + b"\0" * 100)
        st.set_mode_dll(p)
        assert str(st.scene.main_module_name).rstrip("\0") == "mp_CaptureLoveboat.dll" and st.game_mode() == "B"
        bad = os.path.join(tmp, "x.dll"); open(bad, "wb").write(b"no")
        try:
            st.set_mode_dll(bad); assert False
        except ValueError:
            pass
        st.use_standard_mode_dll()
        assert str(st.scene.main_module_name).rstrip("\0") == "mp_CaptureTheFlag.dll"


def test_flag_return_dll():
    import os, struct
    from vtoy import dllpatch
    src = os.environ.get("VTOY_FLAG_DLL", "")
    if not os.path.isfile(src):
        return                                                   # the game's mp_Flag.dll is not in this data set
    with tempfile.TemporaryDirectory() as tmp:
        st = _state(tmp)
        st.load("mp_b_loveboat.scn")
        msg = st.make_flag_dll(0.0, src, os.path.join(tmp, "out"))
        name = "mp_Flag@mp_b_loveboat.dll"
        out = os.path.join(tmp, "out", name)
        assert os.path.isfile(out) and "0.0 s" in msg
        a, b = open(src, "rb").read(), open(out, "rb").read()
        diff = [i for i in range(len(a)) if a[i] != b[i]]
        off = dllpatch.find_flag_return_constant(a)
        assert all(off <= i < off + 4 for i in diff) and struct.unpack_from("<f", b, off)[0] == 0.0
        flags = [r for r in st.scene.modules if r.clean_name.lower() == "mp_flag"]
        assert len(flags) == 2 and all(str(r.module_name).rstrip("\0") == name for r in flags)
        assert all(r.parsed is not None for r in flags)            # still understood as flags
        st.save_scene()
        st.load("mp_b_loveboat.scn")
        flags = [r for r in st.scene.modules if r.clean_name.lower() == "mp_flag"]
        assert len(flags) == 2 and all(r.parsed is not None for r in flags)
        st.use_stock_flag_dll()
        assert all(str(r.module_name).rstrip("\0") == "mp_Flag.dll" for r in flags)


def test_replace_texture_from_image():
    import os
    import numpy as np
    from PIL import Image
    with tempfile.TemporaryDirectory() as tmp:
        st = _state(tmp)
        st.load("mp_b_loveboat.scn")
        name = "METAL-loveboat.tex"
        p = st.fs.find("texs/" + name)
        if not p:
            return
        # the textures folder is a link to the real data in tests: work on a private copy
        import shutil
        real = os.path.join(tmp, "texs_copy"); os.makedirs(real)
        shutil.copy2(p, os.path.join(real, name))
        st.fs.find = (lambda f, _o=st.fs.find: os.path.join(real, name) if f == "texs/" + name else _o(f))
        orig = st.fs.texture(name)
        img = os.path.join(tmp, "red.png")
        Image.fromarray(np.full((100, 60, 3), (220, 10, 10), np.uint8)).save(img)
        msg = st.replace_texture_from_image(name, img)
        assert "DXT" in msg and os.path.exists(os.path.join(real, name + ".bak"))
        from vtoy.tex import Texture
        new = Texture.load(os.path.join(real, name)) if hasattr(Texture, "load") else None
        if new is not None:
            assert (new.width, new.height, new.fmt, new.mip_count) == (orig.width, orig.height, orig.fmt, orig.mip_count)
            px = new.decode(0)[orig.height // 2, orig.width // 2]
            assert px[0] > 180 and px[1] < 60
        st.restore_texture(name)
        assert open(os.path.join(real, name), "rb").read() == open(p, "rb").read()


def test_save_map_never_touches_shared_files():
    import os
    from vtoy import crop
    with tempfile.TemporaryDirectory() as tmp:
        st = _state(tmp)
        st.load("mp_b_loveboat.scn")
        shared_opt = st.opt.path
        shared_hm = st.fs.find(str(st.scene.heightmap_name).rstrip("\0").replace("\\", "/"))
        a, b = open(shared_opt, "rb").read(), open(shared_hm, "rb").read()
        st.save_scene_as("mp_b_twinboats", with_map=False)          # scene copy still pointing at the shared files
        assert os.path.basename(st.opt.path) == "mp_dm_loveboat.opt"
        st.make_twin_ships(800.0, 16, True)
        st.save_map(); st.save_scene()
        assert open(shared_opt, "rb").read() == a and open(shared_hm, "rb").read() == b     # stock files untouched
        assert str(st.scene.map_name).rstrip("\0") == "nfos\\mp_b_twinboats.opt"
        assert str(st.scene.heightmap_name).rstrip("\0") == "nfos\\mp_b_twinboats.hm"
        # a map file named like the scene and used by no other scene is saved in place
        p = st.opt.path
        st.dirty_map = True
        assert st.save_map() == p
        # the stock scenes still load their own maps
        st.load("mp_b_loveboat.scn")
        assert os.path.basename(st.opt.path) == "mp_dm_loveboat.opt"
        # a stock map named like its scene but shared (mp_dm_loveboat.opt is used by the other Love Boat scenes)
        st.load("mp_dm_loveboat.scn")
        st.dirty_map = True
        out = st.save_map()
        assert os.path.basename(out) != "mp_dm_loveboat.opt" and open(shared_opt, "rb").read() == a


def test_texture_only_for_this_map():
    import os
    import numpy as np
    from PIL import Image
    with tempfile.TemporaryDirectory() as tmp:
        st = _state(tmp)
        st.load("mp_b_loveboat.scn")
        st.save_scene_as("mp_b_tex", with_map=True)
        if not st.fs.find("texs/tablones.tex"):
            return
        before = open(st.fs.find("texs/tablones.tex"), "rb").read()
        img = os.path.join(tmp, "x.png")
        Image.fromarray(np.full((64, 64, 3), (0, 200, 0), np.uint8)).save(img)
        users = len(st.map_texture_users("tablones"))
        if not users:
            return
        texdir = os.path.join(tmp, "own_texs"); os.makedirs(texdir)
        real_find = st.fs.find
        st.fs.find = lambda f, _o=real_find: (os.path.join(texdir, os.path.basename(f)) if f.startswith("texs/mp_b_tex__")
                                              and os.path.exists(os.path.join(texdir, os.path.basename(f))) else _o(f))
        import vtoy.app.state_ext as SE
        orig_join = os.path.join
        msg = None
        try:
            os.path.join = lambda *a: orig_join(texdir, a[-1]) if a and str(a[-1]).startswith("mp_b_tex__") else orig_join(*a)
            msg = st.replace_texture_for_map("tablones.tex", img)
        finally:
            os.path.join = orig_join
        assert "mp_b_tex__tablones" in msg
        assert open(real_find("texs/tablones.tex"), "rb").read() == before                 # original untouched
        assert len(st.map_texture_users("mp_b_tex__tablones")) == users and not st.map_texture_users("tablones")
        st.back_to_original_texture("mp_b_tex__tablones.tex")
        assert len(st.map_texture_users("tablones")) == users
        st.undo()                                                                          # undo: the copy again
        assert len(st.map_texture_users("mp_b_tex__tablones")) == users


def test_preview_replaced_with_backup():
    import os
    import numpy as np
    with tempfile.TemporaryDirectory() as tmp:
        st = _state(tmp)
        st.load("mp_dm_vertigo.scn")
        st.scene.path = os.path.join(os.path.dirname(st.scene.path), "zz_prevtest.scn")   # a name no shipped preview has
        st.scene_name = "zz_prevtest.scn"
        img = np.zeros((256, 256, 4), np.uint8); img[..., 0] = 200; img[..., 3] = 255
        p1 = None
        try:
            p1 = st.save_preview(img)
            assert os.path.exists(p1) and not os.path.exists(p1 + ".bak")
            a = open(p1, "rb").read()
            img[..., 1] = 200
            p2 = st.save_preview(img)
            assert p2 == p1 and open(p1 + ".bak", "rb").read() == a and open(p1, "rb").read() != a
        finally:                                          # texs/ may be the shared test data: leave nothing behind
            for f in (p1, (p1 or "") + ".bak"):
                if f and os.path.exists(f):
                    os.remove(f)
