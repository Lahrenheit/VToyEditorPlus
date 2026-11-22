"""'Torrente, el juego' compatibility: TeX1 textures, short-descriptor scenes, import without touching Online files."""
import filecmp, os, sys, tempfile
import _path
from _path import DATA
from test_state import make_game_copy
import numpy as np
from vtoy.app.state import EditorState
from vtoy.scn import Scene
from vtoy.tex import Texture, Texture1
from vtoy.nfo import Nfo

TJ = os.environ.get("VTOY_TJ_DATA", os.path.join(os.path.dirname(DATA), "tj"))


def walk(sub, ext):
    for dp, _, fn in os.walk(os.path.join(TJ, sub)):
        for f in sorted(fn):
            if f.lower().endswith(ext):
                yield os.path.join(dp, f)


def test_roundtrip_old_files():
    n = 0
    for p in walk("texs", ".tex"):
        raw = open(p, "rb").read(); t = Texture.parse(raw); assert isinstance(t, Texture1) and t.to_bytes() == raw; n += 1
    for p in walk("scns", ".scn"):
        raw = open(p, "rb").read(); assert Scene.parse(raw).to_bytes() == raw; n += 1
    for p in walk("nfos", ".nfo"):
        raw = open(p, "rb").read(); assert Nfo.parse(raw).to_bytes() == raw; n += 1
    from vtoy.keys import KeyFile
    for p in walk("keys", ".key"):
        raw = open(p, "rb").read(); assert KeyFile.parse(raw).to_bytes() == raw; n += 1
    print("old-format files round-trip:", n)


def test_texture_convert():
    t = Texture1.from_rgba(np.random.randint(0, 255, (16, 16, 4), np.uint8), mipmaps=True)
    assert Texture1.parse(t.to_bytes()).decode().shape == (16, 16, 4) and t.mips == 5
    t2 = t.to_texture2(); assert t2.width == 16 and t2.has_mips


def test_import_flow():
    with tempfile.TemporaryDirectory() as tmp:
        root = make_game_copy(tmp)
        st = EditorState(root)
        st.set_library(TJ)
        st.load("mp_dm_plaza.scn")
        model = next(m for m in st.library.models() if m.lower().startswith("chino"))
        rel, rep = st.import_model(model)
        n0 = len(st.scene.modules)
        rec = st.place_model(rel)
        assert len(st.scene.modules) == n0 + 1 and rec.parsed.model_name.startswith("nfos/")
        st.bake()
        assert st.geometry.stats["missing_models"] == 0, st.geometry.stats
        name = st.new_scene("test_nueva", "pista.opt") if False else None
        opt = next(m for m in st.library.maps() if m.lower() == "pista.opt")
        new_opt, _ = st.import_map(opt)
        name = st.new_scene("test_nueva", new_opt)
        st.load(name)
        assert st.geometry.stats["meshes"] > 100
        starts = [r.parsed for r in st.scene.modules if r.clean_name == "mp_CStartPoint"]
        assert len(starts) >= 14 and {s.team for s in starts} == {0, 1}
        assert any(r.clean_name == "mp_CameraStartPosition" for r in st.scene.modules)
        hint = st.map_start_hint(new_opt)
        assert hint is not None and abs(starts[0].position[0] - hint[0]) < 200
        # Online originals untouched
        for sub in ("nfos", "texs"):
            base = os.path.join(DATA, sub, sub)
            for dp, _, fs in os.walk(base):
                for f in fs:
                    p = os.path.join(dp, f); q = os.path.join(root, sub, os.path.relpath(p, base))
                    assert os.path.exists(q) and filecmp.cmp(p, q, shallow=False), q


def test_legacy_scenes_load():
    """Old-game scenes (map 'SCENE'/'SUBSCENE') resolve their level through the main DLL name."""
    import shutil
    with tempfile.TemporaryDirectory() as tmp:
        root = os.path.join(tmp, "game")
        for sub in ("scns", "nfos", "keys", "texs"):
            shutil.copytree(os.path.join(DATA, sub, sub), os.path.join(root, sub))
            shutil.copytree(os.path.join(TJ, sub, sub), os.path.join(root, sub), dirs_exist_ok=True)
        st = EditorState(root)
        for n in ("Marbella_f04.scn", "Marbella_f04_d02.scn", "madrid_f02.scn", "Entrenamiento.scn", "fasex_f01.scn"):
            st.load(n)
            assert st.geometry.stats["meshes"] > 50, (n, st.geometry.stats)


MODEL_KINDS = ("RenderNFO", "AnimatedRenderNFO", "mp_CCar", "mp_salud", "mp_Flag")


def _online_sizes_check(root, scene):
    """Every converted module of a kind must have a payload layout (key-less tail) that real Online scenes also use."""
    import collections, struct
    from vtoy.scn import Scene as S
    ref = collections.defaultdict(set)
    folder = os.path.join(root, "scns")
    for f in os.listdir(folder):
        if f.lower().startswith("mp_"):
            try:
                for r in S.load(os.path.join(folder, f)).modules:
                    d = r.data
                    if r.clean_name in MODEL_KINDS and len(d) >= 4:
                        d = d[4 + struct.unpack_from("<I", d, 0)[0] + 64:]
                        ref[r.clean_name].add(len(d) if b".key" not in d.lower() else -1)
                    else:
                        ref[r.clean_name].add(len(d))
            except Exception:
                pass
    for r in scene.modules:
        d = r.payload()
        if r.clean_name in MODEL_KINDS:
            d = d[4 + struct.unpack_from("<I", d, 0)[0] + 64:]
            n = len(d) if b".key" not in d.lower() else -1
        else:
            n = len(d)
        assert n in ref[r.clean_name] or r.clean_name.startswith("mp_Camera"), (r.clean_name, n)


def test_opt_to_vto1():
    """Old maps are converted to the Online layout; checked against Online's own conversion of 'comercial'."""
    import numpy as np
    from vtoy.opt import OptMap
    from vtoy import optconv
    online = os.path.join(DATA, "nfos", "nfos", "mp_dm_comercial.opt")
    for name in sorted(os.listdir(os.path.join(TJ, "nfos", "nfos")) if os.path.isdir(os.path.join(TJ, "nfos", "nfos")) else os.listdir(os.path.join(TJ, "nfos"))):
        if not name.lower().endswith(".opt"):
            continue
        path = os.path.join(TJ, "nfos", "nfos", name) if os.path.isdir(os.path.join(TJ, "nfos", "nfos")) else os.path.join(TJ, "nfos", name)
        m = OptMap.load(path)
        n_mesh, n_prop, n_box = len(m.meshes), len(m.props), len(m.all_collision_boxes())
        optconv.convert(m)
        data = m.to_bytes()
        q = OptMap.parse(data)
        assert not q.old_format and len(q.meshes) == n_mesh and len(q.props) == n_prop
        assert q.to_bytes() == data, name
        assert (q.declared_box_count if q.hulls_count else len(q.collision_boxes)) == n_box
        if name.lower() == "comercial.opt" and os.path.exists(online):
            ref = OptMap.load(online)
            for a, b in zip(q.meshes, ref.meshes):
                sa = [s for l in a.lods for p in l.parts for s in p.submeshes]
                sb = [s for l in b.lods for p in l.parts for s in p.submeshes]
                assert all(x.indices.tobytes() == y.indices.tobytes() and x.stride_type == y.stride_type for x, y in zip(sa, sb))
            assert q.hulls_raw[:17096] == ref.hulls_raw[:17096]


def test_import_map_named_like_scene():
    with tempfile.TemporaryDirectory() as tmp:
        root = make_game_copy(tmp)
        st = EditorState(root)
        st.set_library(TJ)
        st.load("mp_dm_plaza.scn")
        src = st.library.maps()[0]
        rel, _ = st.import_map(src, "mi_mapa_nuevo")
        assert os.path.basename(rel.replace("\\", "/")).lower() == "mi_mapa_nuevo.opt", rel


def test_convert_scene():
    with tempfile.TemporaryDirectory() as tmp:
        root = make_game_copy(tmp)
        st = EditorState(root)
        st.set_library(TJ)
        st.load("mp_dm_plaza.scn")
        for old, min_mods in (("fasex_f03.scn", 10), ("Marbella_f04.scn", 20), ("madrid_f02.scn", 20)):
            name, text = st.convert_scene(old, "conv_" + old)
            st.load(name)
            g = st.geometry.stats
            assert g["meshes"] > 100 and g["missing_models"] == 0, (old, g, text)
            assert len(st.scene.modules) >= min_mods, (old, len(st.scene.modules))
            stem = os.path.splitext(name)[0]
            mp = str(st.scene.map_name).rstrip("\0").replace("\\", "/").lower()
            assert mp.endswith("/" + stem.lower() + ".opt") or mp == stem.lower() + ".opt", (stem, mp)   # opt named like the scene
            assert any(f.lower() == stem.lower() + ".opt" for _, _, fs in os.walk(root) for f in fs)
            assert any(r.clean_name == "mp_CStartPoint" for r in st.scene.modules)
        assert "converted" in text
        # every mode gets its main module and its required modules
        from vtoy import gamemode as gm
        for mode in gm.MODES:
            name, _ = st.convert_scene("Marbella_f04.scn", "m_" + mode, mode)
            st.load(name)
            assert st.game_mode() == mode, (mode, st.scene.main_module_name)
            assert str(st.scene.main_module_name).rstrip("\0") == gm.MODES[mode][1]
            _online_sizes_check(root, st.scene)
            problems = [l for l in st.gm_check() if "start" in l.lower() or "Flag" in l or "BombZone" in l]
            assert not problems, (mode, problems)


if __name__ == "__main__":
    for f in (test_roundtrip_old_files, test_texture_convert, test_import_flow, test_legacy_scenes_load, test_opt_to_vto1, test_convert_scene):
        f(); print(f.__name__, "OK")
