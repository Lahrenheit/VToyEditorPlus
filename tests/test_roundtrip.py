"""Round-trip tests: every file we can parse must be written back byte-for-byte.
Run:  python3 tests/test_roundtrip.py   (set VTOY_DATA to the folder holding scns/ nfos/ texs/ keys/)"""
import glob, os, sys, time
import _path
from _path import DATA
from vtoy.scn import Scene
from vtoy.modules import parse_modules
from vtoy.opt import OptMap


def files(sub, *exts):
    out = []
    for f in sorted(glob.glob(os.path.join(DATA, sub, "**", "*"), recursive=True)):
        if os.path.isfile(f) and f.lower().endswith(exts):
            out.append(f)
    return out


def test_scenes():
    bad = []
    fs = files("scns", ".scn")
    for f in fs:
        raw = open(f, "rb").read()
        s = Scene.parse(raw)
        parse_modules(s)
        if s.to_bytes() != raw:
            bad.append(f)
    return len(fs), bad


def test_maps():
    bad = []
    fs = files("nfos", ".opt")
    for f in fs:
        raw = open(f, "rb").read()
        if OptMap.parse(raw).to_bytes() != raw:
            bad.append(f)
    return len(fs), bad


def test_heightmaps():
    from vtoy.hm import HeightMap
    bad = []
    fs = files("nfos", ".hm")
    for f in fs:
        raw = open(f, "rb").read()
        if HeightMap.parse(raw).to_bytes() != raw:
            bad.append(f)
    return len(fs), bad


def test_textures():
    from vtoy.tex import Texture
    bad = []
    fs = [f for f in files("texs", ".tex") if open(f, "rb").read(4) == b"TeX2"]
    for f in fs:
        raw = open(f, "rb").read()
        if Texture.parse(raw).to_bytes() != raw:
            bad.append(f)
    return len(fs), bad


def test_keys():
    from vtoy.keys import KeyFile
    bad = []
    fs = files("keys", ".key")
    for f in fs:
        raw = open(f, "rb").read()
        try:
            if KeyFile.parse(raw).to_bytes() != raw:
                bad.append(f)
        except Exception:
            bad.append(f)
    return len(fs), bad


def test_models():
    """Models are read-only: check that every file parses and its skin weights are consistent."""
    import numpy as np
    from vtoy.nfo import NfoModel
    bad = []
    fs = files("nfos", ".nfo")
    for f in fs:
        try:
            m = NfoModel.load(f)
            for o in m.objects:
                for lod in o.lods:
                    for me in lod.meshes:
                        list(me.build())
                        if me.skin:
                            acc = np.zeros(len(me.positions))
                            for s in me.skin:
                                np.add.at(acc, s.vertex, s.weight)
                            cov = acc > 0
                            assert np.allclose(acc[cov], 1, atol=2e-2)
        except Exception:
            bad.append(f)
    return len(fs), bad


def test_models_write():
    from vtoy.nfo import NfoModel
    bad = []
    fs = files("nfos", ".nfo")
    for f in fs:
        raw = open(f, "rb").read()
        try:
            if NfoModel.parse(raw).to_bytes() != raw:
                bad.append(f)
        except Exception:
            bad.append(f)
    return len(fs), bad


def test_vpk():
    """pack a folder, unpack it again, compare every file."""
    import filecmp, shutil, tempfile
    from vtoy import vpk
    src = os.path.join(DATA, "scns")
    bad = []
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "t.vpk")
        n = vpk.repack(src, out)
        dst = os.path.join(tmp, "out")
        vpk.unpack(out, dst)
        for dp, _, fns in os.walk(src):
            for fn in fns:
                a = os.path.join(dp, fn)
                b = os.path.join(dst, os.path.relpath(a, src))
                if not os.path.exists(b) or not filecmp.cmp(a, b, shallow=False):
                    bad.append(a)
    return n, bad


TESTS = [("scn", test_scenes), ("opt", test_maps), ("hm", test_heightmaps), ("tex", test_textures),
         ("key", test_keys), ("nfo(parse)", test_models), ("nfo(write)", test_models_write), ("vpk", test_vpk)]

if __name__ == "__main__":
    fail = 0
    for name, fn in TESTS:
        t = time.time()
        n, bad = fn()
        print(f"{name}: {n - len(bad)}/{n} identical ({time.time() - t:.1f}s)")
        for b in bad[:5]:
            print("   FAIL", b)
        fail += len(bad)
    sys.exit(1 if fail else 0)
