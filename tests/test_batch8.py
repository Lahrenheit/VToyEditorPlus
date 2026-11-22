"""Batch 8: shading layer (glow), restoring the far levels of detail, pieces of other maps, crash fixes."""
import os, tempfile
import _path
import numpy as np
from test_batch7 import _st
from vtoy import crop, glowlayer, meshlib
from vtoy.app.state import Selection
from vtoy.opt import OptMap, VERTEX2_DTYPE, VERTEX_DTYPE


def test_objects_compare_by_identity():
    """'light in lights' / '==' on two different objects of the map compared numpy arrays and raised: the editor closed."""
    with tempfile.TemporaryDirectory() as tmp:
        st = _st(tmp)
        a, b = st.opt.lights[0], st.opt.lights[1]
        assert a != b and a in st.opt.lights and not (b == a)
        import copy
        c = copy.deepcopy(a)
        assert c not in st.opt.lights and c != a                       # an equal copy is still another light
        r0, r1 = st.scene.modules[0], st.scene.modules[1]
        assert r0 in st.scene.modules and r0 != r1 and len({id(m) for m in st.scene.modules}) == len(st.scene.modules)
        assert st.opt.meshes[0] in st.opt.meshes and st.opt.props[0] in st.opt.props
        hash(a); hash(r0)                                              # usable as dict keys too


def test_positions_only_modules_do_not_rotate():
    with tempfile.TemporaryDirectory() as tmp:
        st = _st(tmp)
        snd = st.sound_sources()[0]
        sel = Selection("module", snd, "")
        assert not st.can_rotate(sel) and not st.can_scale(sel)
        em = st.add_particles("fountain (mp_dm_plaza)")
        assert not st.can_rotate(Selection("module", em, "")) and not st.can_scale(Selection("module", em, ""))
        car = next(r for r in st.scene.modules if r.parsed is not None and hasattr(r.parsed, "model_name"))
        assert st.can_rotate(Selection("module", car, ""))
        # a selection that points to an object no longer in the scene: a clear message, not StopIteration
        st.undo()
        try:
            st.duplicate_selection(Selection("module", em, ""))
            assert False
        except ValueError as e:
            assert "no longer in the scene" in str(e)


def test_shading_layer():
    with tempfile.TemporaryDirectory() as tmp:
        st = _st(tmp, own_texs=True)
        # what mp_b_garaje does: uv2 a flat projection, x / size (floors from above)
        pos = np.array([[0.0, 0.0, 0.0], [650.0, 0.0, 0.0], [0.0, 0.0, 650.0], [0.0, 300.0, 0.0]])
        nrm = np.array([[0, 1, 0], [0, 1, 0], [0, 1, 0], [1, 0, 0]], float)
        uv = glowlayer.project(pos, nrm, 650.0)
        assert np.allclose(uv[:3], [[0.5, 0.5], [1.5, 0.5], [0.5, -0.5]]) and np.allclose(uv[3], [0.5, 0.5 - 300 / 650])
        assert "glow_galo.tex" in st.glow_textures()
        me = st.opt.meshes[10]
        st.selection = Selection("mesh", me, "")
        n_sub = sum(1 for lod in me.lods for p in lod.parts for s in p.submeshes)
        msg = st.apply_shading("glow_galo.tex", 600.0, centre=(100.0, 0.0, 0.0))
        assert msg.startswith("1 meshes") and "only visible in the game" in msg
        assert glowlayer.layer_of(me) == ("glow_galo.tex", sum(1 for p in me.lods[0].parts for s in p.submeshes))
        for lod in me.lods:
            for p in lod.parts:
                for s in p.submeshes:
                    assert s.stride_type == 1 and s.vertices.dtype == VERTEX2_DTYPE
        assert all(m.textures[1] == "glow_galo.tex" for m in me.materials if m.textures)
        v = me.lods[0].parts[0].submeshes[0].vertices
        top = np.abs(v["nrm"][:, 1]) >= np.abs(v["nrm"][:, [0, 2]]).max(1)
        assert np.allclose(v["uv2"][top, 0], (v["pos"][top, 0] - 100.0) / 600.0 + 0.5, atol=1e-4)
        # it survives saving; removing gives the plain layout back
        st.save_map()
        o = OptMap.load(st.opt.path)
        assert any(glowlayer.layer_of(m)[0] == "glow_galo.tex" for m in o.meshes)
        st.selection = Selection("mesh", me, "")
        assert "removed from" in st.remove_shading()
        assert glowlayer.layer_of(me) == ("", 0) and all(len(m.textures) == 1 for m in me.materials if m.textures)
        assert all(s.vertices.dtype == VERTEX_DTYPE for lod in me.lods for p in lod.parts for s in p.submeshes)
        assert sum(1 for lod in me.lods for p in lod.parts for s in p.submeshes) == n_sub
        # a prop gives its mesh; the whole map
        st.selection = Selection("prop", st.opt.props[0], "")
        assert st.shading_targets() == [st.opt.props[0].mesh_index]
        assert len(st.shading_targets("map")) > 100
        # own spot texture: dark in the middle = a shadow; never over an existing file
        rgba = glowlayer.make_texture(0.2, 1.0)
        assert rgba[32, 32, 0] < 60 and rgba[0, 0, 0] > 240 and rgba.shape == (64, 64, 4)
        t = st.make_shading_texture("sombra", 0.2, 1.0)
        assert t == "glow_sombra.tex" and st.fs.texture(t) is not None
        t2 = st.make_shading_texture("sombra", 1.0, 0.1)
        assert t2 != t and st.fs.texture(t2) is not None
        try:
            st.selection = None
            st.apply_shading("glow_galo.tex")
            assert False
        except ValueError:
            pass


def test_restore_far_detail():
    with tempfile.TemporaryDirectory() as tmp:
        st = _st(tmp)
        before = {id(m): (len(m.lods), m.lods[0].unk) for m in st.opt.meshes}
        n = st.lod_meshes()
        assert n == 15 and st.full_detail_meshes().startswith("15 meshes") and st.lod_meshes() == 0
        assert st.detail_restorable() == 15
        msg = st.restore_detail_meshes()
        assert msg.startswith("15 meshes") and st.lod_meshes() == 15
        assert {id(m): (len(m.lods), m.lods[0].unk) for m in st.opt.meshes} == before          # exactly as it was
        st.save_map()
        # later, after reopening: what the editor kept is still there
        st.full_detail_meshes(); st.save_map(); st.save_scene()
        st.load(st.scene_name)
        assert st.lod_meshes() == 0 and st.detail_restorable() == 15
        assert st.restore_detail_meshes().startswith("15 meshes")
        # a map changed before this version (nothing kept): the game's maps give the far versions, even for moved meshes
        had = [i for i, m in enumerate(st.opt.meshes) if len(m.lods) > 1]
        st.full_detail_meshes()
        st._lods = {}
        from vtoy.opt import translate_mesh
        assert st.restore_detail_meshes(search_game=False).startswith("nothing to restore")
        moved = st.opt.meshes[had[0]]
        translate_mesh(moved, (300.0, 0.0, 0.0))
        assert st.restore_detail_meshes().startswith(("15 meshes", "16 meshes"))
        assert len(moved.lods) > 1
        a = np.concatenate([s.vertices["pos"] for p in moved.lods[0].parts for s in p.submeshes]).min(0)
        b = np.concatenate([s.vertices["pos"] for p in moved.lods[1].parts for s in p.submeshes]).min(0)
        assert abs(a[0] - b[0]) < 200                                    # the far version moved with it
        st.save_map()
        OptMap.load(st.opt.path)


def test_pieces_of_other_maps():
    with tempfile.TemporaryDirectory() as tmp:
        st = _st(tmp, "mp_b_garaje.scn")
        maps = st.library_maps()
        assert "mp_dm_comercial.opt" in maps and "mp_b_garaje.opt" not in maps
        pieces = st.library_pieces("mp_dm_comercial.opt")
        glass = [p for p in pieces if "cc_crist.tex" in p["textures"]]
        assert len(pieces) > 1000 and len(glass) == 15
        used = {p.mesh_index for p in st._lib_map("mp_dm_comercial.opt").props}
        assert not any(p["kind"] == "mesh" and p["index"] in used for p in pieces)       # the hidden prop patterns are not listed
        g = st.library_piece_preview("mp_dm_comercial.opt", "mesh", glass[1]["index"])
        assert len(g.instances) == 1
        n_mesh = len(st.opt.meshes)
        msg = st.import_library_piece("mp_dm_comercial.opt", "mesh", glass[1]["index"], at=(0.0, 1000.0, 0.0), yaw=90.0)
        assert "of mp_dm_comercial.opt added" in msg and "MISSING" not in msg and len(st.opt.meshes) == n_mesh + 1
        me = st.opt.meshes[-1]
        lo, hi = crop.mesh_bounds(me)
        sz = glass[1]["size"]
        assert np.allclose(hi - lo, (sz[2], sz[1], sz[0]), atol=2) and abs(lo[1] - 1000.0) < 0.5      # turned 90, on the point
        assert np.allclose(((lo + hi) / 2)[[0, 2]], (0, 0), atol=1) and st.selection.ref is me
        assert me.materials[0].diffuse == "cc_crist.tex" and me.materials[0].two_sided
        # a prop comes out where it was drawn (its matrix baked), and can be split in its parts
        prop = next(p for p in pieces if p["kind"] == "prop" and p["tris"] > 20)
        src = st._lib_map("mp_dm_comercial.opt")
        whole = meshlib.extract(src, "prop", prop["index"])
        a, b = crop.mesh_bounds(whole)
        assert np.allclose((a + b) / 2, prop["centre"], atol=1) and len(whole.lods) == len(src.meshes[src.props[prop["index"]].mesh_index].lods)
        parts = st.library_parts("mp_dm_comercial.opt", "prop", prop["index"])
        assert parts and sum(q["count"] for q in parts) == prop["tris"]
        one = meshlib.extract(src, "prop", prop["index"], parts[0])
        assert sum(len(s.indices) // 3 for s in one.render_submeshes()) == parts[0]["count"] and len(one.lods) == 1
        assert np.allclose(crop.mesh_bounds(one)[1] - crop.mesh_bounds(one)[0], parts[0]["size"], atol=1)
        msg = st.import_library_piece("mp_dm_comercial.opt", "prop", prop["index"], parts[0], at=(500.0, 1000.0, 0.0), box=True)
        assert "collision" in msg
        # a map made of many separate things splits: the whole thing = the sum of its parts
        big = max((p for p in pieces if p["kind"] == "mesh"), key=lambda p: p["tris"])
        bp = st.library_parts("mp_dm_comercial.opt", "mesh", big["index"])
        assert len(bp) > 1 and sum(q["count"] for q in bp) == big["tris"] or len(bp) == 400
        st.undo()
        assert len(st.opt.meshes) in (n_mesh, n_mesh + 1)                  # (two quick imports may be one undo step)
        st.save_map()
        OptMap.load(st.opt.path)
        # the source map was not touched
        assert len(st._lib_map("mp_dm_comercial.opt").meshes) == len(OptMap.load(st.fs.find("nfos/mp_dm_comercial.opt")).meshes)
