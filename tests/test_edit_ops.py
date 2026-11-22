"""Editing operations: mesh / prop delete, duplicate, rotate, scale, fill patch, collision, undo / redo, save as, export."""
import os, tempfile, zipfile
import _path
from _path import DATA
import numpy as np
from vtoy import crop
from vtoy.opt import OptMap
from vtoy.app.state import EditorState, Selection
from test_state import make_game_copy
from test_crop import check_consistent


def _state(tmp, scene="mp_dm_almacen.scn"):
    st = EditorState(make_game_copy(tmp))
    st.load(scene)
    return st


def _flat(st):
    n_obj = len(st.opt.meshes) + len(st.opt.props)
    check_consistent(st.opt)
    return n_obj


def test_delete_mesh_and_prop():
    with tempfile.TemporaryDirectory() as tmp:
        st = _state(tmp)
        m0, p0 = len(st.opt.meshes), len(st.opt.props)
        me = st.opt.meshes[1]
        users = sum(1 for p in st.opt.props if p.mesh_index == 1)
        st.delete_selection(Selection("mesh", me, ""))
        assert len(st.opt.meshes) == m0 - 1 and len(st.opt.props) == p0 - users
        _flat(st)
        if st.opt.props:
            st.delete_selection(Selection("prop", st.opt.props[0], ""))
            _flat(st)
        # undo brings the mesh back, redo removes it again
        assert st.can_undo()
        st.undo(); st.undo()
        assert len(st.opt.meshes) == m0 and len(st.opt.props) == p0
        st.redo()
        assert len(st.opt.meshes) == m0 - 1


def test_duplicate_rotate_scale_fill():
    with tempfile.TemporaryDirectory() as tmp:
        st = _state(tmp)
        n = len(st.opt.meshes)
        free = next(i for i in range(n) if not any(p.mesh_index == i for p in st.opt.props))
        sel = Selection("mesh", st.opt.meshes[free], "")
        lo0, hi0 = crop.mesh_bounds(sel.ref)
        new = st.duplicate_selection(sel, (300, 0, 0))
        assert len(st.opt.meshes) == n + 1 and new.ref is st.opt.meshes[-1]
        assert np.allclose(crop.mesh_bounds(new.ref)[0], lo0 + [300, 0, 0], atol=0.01)
        _flat(st)
        st.scale_selection(new, 2.0)
        lo, hi = crop.mesh_bounds(new.ref)
        assert np.allclose(hi - lo, (hi0 - lo0) * 2, atol=0.05)
        st.rotate_any(new, (0, 90, 0))
        lo2, hi2 = crop.mesh_bounds(new.ref)
        assert np.allclose((hi2 - lo2)[[0, 2]], (hi - lo)[[2, 0]], atol=0.5)
        _flat(st)
        prop = st.opt.props[0]
        cp = st.duplicate_selection(Selection("prop", prop, ""), (100, 0, 0))
        assert len(st.opt.props) and cp.ref is st.opt.props[-1]
        _flat(st)
        tex = st.texture_of(sel) or "pared.tex"
        patch = st.add_fill_patch([(0, 0), (500, 0), (500, 400), (250, 200), (0, 400)], 0.0, tex)
        assert patch.ref is st.opt.meshes[-1]
        _flat(st)
        st.bake()
        assert st.geometry.stats["meshes"] == len(st.opt.meshes)


def test_collision_removal():
    with tempfile.TemporaryDirectory() as tmp:
        st = _state(tmp)
        blk = crop.read_block(st.opt)
        nb, nh = len(blk.boxes), len(blk.polys)
        b, h = crop.remove_collision_in_polygon(st.opt, [(-1e6, -1e6), (1e6, -1e6), (1e6, 1e6), (-1e6, 1e6)])
        assert (b, h) == (nb, nh)
        blk2 = crop.read_block(st.opt)
        assert not blk2.boxes and not blk2.polys
        check_consistent(st.opt)


def test_names_camera_save_as_export():
    with tempfile.TemporaryDirectory() as tmp:
        st = _state(tmp)
        a = st.add_module("mp_cstartpoint", "StartPoint_1")
        b = st.add_module("mp_cstartpoint", "StartPoint_1")
        names = [str(r.object_name).rstrip("\0").lower() for r in st.scene.modules]
        assert len(names) == len(set(names))
        d = st.duplicate_module(a)
        names = [str(r.object_name).rstrip("\0").lower() for r in st.scene.modules]
        assert len(names) == len(set(names)) and str(d.object_name) != str(a.object_name)
        # camera module can be added and removed; saving needs one
        cams = [r for r in st.scene.modules if r.clean_name.lower() == "mp_camerastartposition"]
        for r in cams:
            st.delete_module(r)
        assert st.scene_problems()
        rec = st.add_module("mp_camerastartposition", "CameraStartPoint")
        assert rec.parsed is not None and not st.scene_problems()
        # save as: the working file is untouched
        orig = open(st.scene.path, "rb").read()
        old_path = st.scene.path
        out = st.save_scene_as("mi_prueba")
        assert os.path.exists(out) and open(old_path, "rb").read() == orig
        assert Scene_name(out) == "mi_prueba.scn"
        # preview + export
        img = np.zeros((256, 256, 4), np.uint8); img[..., 1] = 200; img[..., 3] = 255
        p = st.save_preview(img, "tex")
        assert p.endswith("mi_prueba-tbn.tex")
        p2 = st.save_preview(img, "dds")
        assert open(p2, "rb").read(4) == b"DDS "
        z = os.path.join(tmp, "out.zip")
        info = st.export_map_zip(z)
        with zipfile.ZipFile(z) as zf:
            nm = zf.namelist()
        assert any(n.endswith("mi_prueba.scn") for n in nm) and any(n.endswith(".opt") for n in nm)
        assert any(n.lower().endswith("mi_prueba-tbn.tex") for n in nm) and any(n.startswith("texs/") for n in nm)


def Scene_name(p):
    return os.path.basename(p)


def test_texture_round_trip():
    with tempfile.TemporaryDirectory() as tmp:
        st = _state(tmp)
        rows = st.map_parts()
        i, tris, tex, *_ = next(r for r in rows if r[2])
        folder = os.path.join(tmp, "ext")
        png = st.extract_texture(tex[0], folder)
        assert os.path.exists(png)
        new = st.import_map_texture(png, replace=tex[0], mesh_index=i)
        assert new.startswith("mi_") or "__" in new
        assert st.opt.meshes[i].materials[0].textures[0] == new or any(new in m.textures for m in st.opt.meshes[i].materials)
        assert os.path.exists(os.path.join(st.fs.root, "texs", new))


if __name__ == "__main__":
    for k, f in list(globals().items()):
        if k.startswith("test_"):
            f(); print("ok", k)


def _decal_ids(m):
    blk = crop.read_block(m)
    base = len(m.meshes) + len(m.props)
    return {i - base for s in blk.sectors for i in s.objs if i >= base}


def test_decals_stay_scene_objects():
    """Online lists decals in the sectors and counts them in scene_obj_count; crop / delete / add must keep that."""
    with tempfile.TemporaryDirectory() as tmp:
        st = _state(tmp, "mp_dm_museo.scn")
        m = st.opt
        assert m.decals and m.scene_obj_count == len(m.meshes) + len(m.props) + len(m.decals)
        n0 = len(_decal_ids(m))
        assert n0 == len(m.decals)
        # crop away a quarter of the map: surviving decals are still referenced and numbered after the props
        xs = np.array([d.position[0] for d in m.decals]); zs = np.array([d.position[2] for d in m.decals])
        poly = [(xs.min() - 10, zs.min() - 10), (np.median(xs), zs.min() - 10), (np.median(xs), zs.max() + 10), (xs.min() - 10, zs.max() + 10)]
        rep = crop.crop_map(m, poly, True)
        q = check_consistent(m)
        assert rep.decals_removed > 0
        assert len(_decal_ids(q)) == len(q.decals) > 0
        # editor add / delete of a decal keeps the bookkeeping
        d = st.add_decal(q.decals[0].name)
        assert len(_decal_ids(check_consistent(st.opt))) == len(st.opt.decals)
        st.delete_decal(d)
        assert len(_decal_ids(check_consistent(st.opt))) == len(st.opt.decals)
        # deleting a mesh renumbers the decal ids too
        st.delete_selection(Selection("mesh", st.opt.meshes[0], ""))
        assert len(_decal_ids(check_consistent(st.opt))) == len(st.opt.decals)
