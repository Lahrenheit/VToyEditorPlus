"""Batch 16: newer versions of the editor on GitHub - the notice, download and unpack next to the program."""
import io
import json
import os
import tempfile
import zipfile

import pytest
import _path


def _answer(tags):
    return json.dumps([{"tag_name": t, "name": n, "html_url": f"https://github.com/Lahrenheit/VToyEditorPlus/releases/tag/{t}",
                        "published_at": "2026-11-23T10:00:00Z", "body": "notes", "prerelease": pre, "draft": draft,
                        "zipball_url": f"https://api.github.com/repos/x/y/zipball/{t}",
                        "assets": [{"name": f"VToyEditorPlus-{t}.zip", "browser_download_url": f"https://dl/{t}.zip",
                                    "size": 10}]}
                       for t, n, pre, draft in tags]).encode()


def test_newer_release_found():
    from vtoy import updater
    asked = []

    def fetch(url):
        asked.append(url)
        return _answer([("v1.0.17", "v1.0.17", True, False), ("v1.0.16", "Editor 1.0.16", False, False),
                        ("v1.0.20", "", False, True), ("v1.0.14", "", False, False)])
    r = updater.newest("https://github.com/Lahrenheit/VToyEditorPlus", "v1.0.15", fetch)
    assert asked == ["https://api.github.com/repos/Lahrenheit/VToyEditorPlus/releases?per_page=20"]
    assert r["tag"] == "v1.0.16" and r["page"].endswith("/v1.0.16")            # no draft, no pre-release
    assert updater.newest("https://github.com/Lahrenheit/VToyEditorPlus", "v1.0.16", fetch) is None
    assert updater.is_newer("1.1", "v1.0.15") and not updater.is_newer("v1.0", "1.0.0")
    c = updater.Checker("https://github.com/Lahrenheit/VToyEditorPlus", "v1.0.15", fetch).start()
    assert c.wait(10) == "newer" and c.release["tag"] == "v1.0.16"

    def offline(url):
        raise OSError("no network")
    c = updater.Checker("https://github.com/Lahrenheit/VToyEditorPlus", "v1.0.15", offline).start()
    assert c.wait(10) == "error" and "no network" in c.error


class _R(io.BytesIO):
    headers = {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def _zip(names):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n in names:
            z.writestr(n, b"new")
    return buf.getvalue()


def test_download_unpacked_next_to_the_program():
    """The release's .zip goes into _vtoy_update next to the program (one top folder left out, nothing written outside
    it); it is this program (VToyEditor.exe at its top), so closing the editor can put it in place."""
    from vtoy import updater
    data = _zip(["VToyEditor/VToyEditor.exe", "VToyEditor/_internal/vtoy/__init__.py", "VToyEditor/../../evil.txt"])
    with tempfile.TemporaryDirectory() as base:
        open(os.path.join(base, "VToyEditor.exe"), "wb").write(b"old")
        os.makedirs(os.path.join(base, updater.STAGING, "stale"))                  # what an earlier try left: emptied
        rel = {"tag": "v1.0.17", "assets": [{"name": "VToyEditorPlus-v1.0.17.zip", "url": "https://dl/x.zip", "size": len(data)}]}
        got = []
        d = updater.Downloader(rel, "https://github.com/Lahrenheit/VToyEditorPlus", base,
                               opener=lambda u: got.append(u) or _R(data)).start()
        assert d.wait(10) == "done", d.error
        assert got == ["https://dl/x.zip"] and d.folder == os.path.join(base, updater.STAGING) and d.replaceable
        assert open(os.path.join(d.folder, "VToyEditor.exe"), "rb").read() == b"new"
        assert sorted(os.path.relpath(f, d.folder) for f in d.files) == sorted(["VToyEditor.exe",
                                                                                os.path.join("_internal", "vtoy", "__init__.py")])
        assert open(os.path.join(base, "VToyEditor.exe"), "rb").read() == b"old"     # the program is not touched yet
        assert not os.path.exists(os.path.join(os.path.dirname(base), "evil.txt"))
    assert updater.pick_asset({"tag": "v2", "assets": [], "zipball": "https://z"})["url"] == "https://z"


def test_7z_release():
    """A release uploaded as .7z: picked like a .zip, unpacked with py7zr or, without it, 7-Zip / Windows' tar.exe."""
    import sys
    from vtoy import updater
    rel = {"tag": "v1.0.17", "assets": [{"name": "notes.txt", "url": "u1", "size": 1},
                                        {"name": "VToyEditorPlus-v1.0.17.7z", "url": "https://dl/x.7z", "size": 5}]}
    assert updater.pick_asset(rel)["name"].endswith(".7z")
    fake = [sys.executable, "-c", "import sys, zipfile; zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])", "{a}", "{d}"]
    data = _zip(["VToyEditorPlus/VToyEditor.exe", "VToyEditorPlus/readme.txt"])     # (a stand-in archive)
    with tempfile.TemporaryDirectory() as base:
        d = updater.Downloader(rel, "https://github.com/Lahrenheit/VToyEditorPlus", base, opener=lambda u: _R(data),
                               tools=[[sys.executable, "-c", "import sys; sys.exit(2)"], fake]).start()
        if d.wait(10) == "error":                                     # (py7zr installed: it rejects the stand-in)
            assert "py7zr" in d.error or "7z" in d.error
        else:
            assert d.replaceable and os.path.isfile(os.path.join(d.folder, "readme.txt"))
        d2 = updater.Downloader(rel, "x", base, opener=lambda u: _R(data), tools=[]).start()
        assert d2.wait(10) == "error" and "7-Zip" in d2.error


def test_replace_script():
    """Closing the editor with an update downloaded: a script waits for it to end, copies the new files over the
    program (the settings kept), deletes the unpacked folder and opens the editor again."""
    from vtoy import updater
    t = updater.replace_script(r"C:\Juegos\VToy\_vtoy_update", r"C:\Juegos\VToy", 4321, [r"C:\Juegos\VToy\VToyEditor.exe"])
    lines = t.split("\r\n")
    assert any("Wait-Process -Id 4321" in l for l in lines)
    rc = next(l for l in lines if l.startswith("robocopy"))
    assert '"C:\\Juegos\\VToy\\_vtoy_update" "C:\\Juegos\\VToy" /E' in rc
    assert all(f'"{k}"' in rc for k in ("vtoy_editor.json", "imgui.ini"))
    assert lines.index(rc) < lines.index('rmdir /S /Q "C:\\Juegos\\VToy\\_vtoy_update"') \
        < lines.index('start "" "C:\\Juegos\\VToy\\VToyEditor.exe"')
    assert "if %ERRORLEVEL% GEQ 8 goto fail" in lines
    with tempfile.TemporaryDirectory() as d:
        os.makedirs(os.path.join(d, "x"))
        try:
            updater.launch_replace(os.path.join(d, "x"), d)
            assert False, "must refuse"
        except (OSError, ValueError):
            pass


def test_version_everywhere_the_same():
    """The version is APP_REV (v1.0.18 ...): the About, the update check and the .exe's properties (version_info.txt,
    written from it by tools/make_version_info.py) - no fixed "v1.0" anywhere."""
    import re
    import sys
    import vtoy
    root = os.path.dirname(os.path.dirname(os.path.abspath(vtoy.__file__)))
    sys.path.insert(0, os.path.join(root, "tools"))
    import make_version_info as mvi
    assert vtoy.APP_VERSION == vtoy.APP_REV and re.fullmatch(r"v\d+\.\d+\.\d+", vtoy.APP_REV)
    want = mvi.text(mvi.app_info(root))
    assert open(os.path.join(root, "version_info.txt"), encoding="utf-8").read() == want   # (run the tool after a bump)
    n = tuple(int(x) for x in vtoy.APP_REV[1:].split("."))
    assert f"filevers={n + (0,)}" in want and f"'FileVersion', '{vtoy.APP_REV[1:]}'" in want
    assert "'v1.0'" not in want
    ed = open(os.path.join(root, "vtoy", "app", "editor.py"), encoding="utf-8").read()
    assert "title = APP_NAME" in ed


def test_manual_builds():
    """docs/Manual_VToyEditorPlus_es.pdf: built by tools/make_manual.py with the editor's version, a clickable index
    (links to the chapters' pages) and PDF bookmarks."""
    import sys
    import pytest
    pytest.importorskip("reportlab")
    pypdf = pytest.importorskip("pypdf")
    import vtoy
    root = os.path.dirname(os.path.dirname(os.path.abspath(vtoy.__file__)))
    sys.path.insert(0, os.path.join(root, "tools"))
    import make_manual
    first = {"es": "1. Introducción", "en": "1. Introduction", "pt": "1. Introdução"}
    with tempfile.TemporaryDirectory() as d:
        for lang in make_manual.LANGS:                       # Spanish, English and Portuguese
            out = make_manual.build(os.path.join(d, f"m_{lang}.pdf"), lang)
            r = pypdf.PdfReader(out)
            assert len(r.pages) > 20 and vtoy.APP_REV in r.metadata.subject
            titles = [o.title for o in r.outline if not isinstance(o, list)]
            assert titles[0].startswith(first[lang]) and any("Counter-Strike" in t for t in titles)
            toc_links = [a for a in r.pages[1]["/Annots"] if a.get_object().get("/Subtype") == "/Link"]
            assert len(toc_links) > 30
            assert r.pages[0].images                         # the program's icon on the cover
    for lang in make_manual.LANGS:                           # the ones shipped are there
        assert os.path.isfile(make_manual.manual_path(lang, root))


def test_stairs_one_even_slope():
    """de_inferno_go's banana and de_cbble's stairs: each step became a ramp twice as long as high, longer than the
    tread - its foot hung over the ramp below, a lip at every step that stopped the player.  Now a ramp ends where its
    tread does: the stairs are one even slope, no lip."""
    import numpy as np
    from vtoy import bspimport
    rise, tread, z = 30.0, 40.0, (0.0, 100.0)

    def quad(x0, x1, y):
        return (np.array([[x0, y, z[0]], [x0, y, z[1]], [x1, y, z[1]], [x1, y, z[0]]]), np.array([0.0, 1.0, 0.0]))
    faces = [quad(-300.0, tread, 0.0)]
    for k in range(1, 6):
        faces.append(quad(tread * k, tread * (k + 1) + (200.0 if k == 5 else 0.0), rise * k))       # tread k
        x = tread * k
        faces.append((np.array([[x, rise * (k - 1), z[0]], [x, rise * k, z[0]], [x, rise * k, z[1]], [x, rise * (k - 1), z[1]]]),
                      np.array([-1.0, 0.0, 0.0])))                                                  # riser k
    out, made = bspimport.step_ramps(faces)
    assert made == 5
    floors = [(p, p.min(0), p.max(0)) for p, n in out if n[1] > 0.7 * np.linalg.norm(n)]
    prev = None
    for x in np.arange(-50.0, 260.0, 1.0):                        # the highest floor along the stairs: no jump
        y = max(bspimport._floor_heights(floors, x, 50.0, -10.0, 200.0))
        if prev is not None:
            assert y - prev < 1.5, (x, prev, y)
        prev = y
    ramps = [p for p, n in out if 0.3 < n[1] / np.linalg.norm(n) < 0.99]
    feet = sorted(float(p[:, 0].min()) for p in ramps)
    assert feet[0] == pytest.approx(tread - 2 * rise, abs=0.5)    # the first: on the ground, 2 x as long as high
    for k, f in enumerate(feet[1:], 2):                          # the rest: on their tread, ending at the step below
        assert f == pytest.approx(tread * (k - 1), abs=0.5)


def test_objects_one_light_not_per_triangle():
    """de_cbble / de_inferno: crates and models came out patched with light and dark triangles - each triangle not on
    a face of the .bsp took the light of the floor under its own middle.  Now: a piece of a wall the faces do not quite
    cover takes the light of the face beside it; a model (triangles joined by their corners) one light for all."""
    import numpy as np
    from vtoy import lightmap
    cube = []
    for x0 in (0.0, 300.0):                                   # two cubes 100 wide, each its own object
        q = np.array([[x0, 0, 0], [x0 + 100, 0, 0], [x0 + 100, 100, 0], [x0, 100, 0]], float)
        cube += [[q[0], q[1], q[2]], [q[0], q[2], q[3]], [q[0] + [0, 0, 100], q[1] + [0, 0, 100], q[2] + [0, 0, 100]]]
    tris = np.array(cube)
    groups = sorted(sorted(int(t) for t in g) for g in lightmap.objects_of(tris, range(len(tris))))
    assert groups == [[0, 1], [2], [3, 4], [5]]                # corners shared: one object; a lone triangle: its own
    wall = np.array([[[0, 0, 0], [100, 0, 0], [100, 100, 0]], [[0, 0, 0], [100, 100, 0], [0, 100, 0]],
                     [[100, 0, 0], [130, 0, 0], [130, 100, 0]],           # a piece beside it on the same plane
                     [[500, 0, 50], [520, 0, 50], [520, 20, 50]]], float) # far away, another plane: a model's
    fo = np.array([7, 7, -1, -1])
    near, far = lightmap._beside_faces(wall, fo, [2, 3])
    assert near == {2: 7} and far == [3]


def test_slit_in_a_slope_closed():
    """de_inferno_go: the clip hull's slope over a staircase came out in pieces with a slit 5 units wide all across
    it - nothing to stand on, the player stopped there.  Two pieces of one plane with facing edges a few cm apart get
    the strip between them; pieces further apart, or of another plane, do not."""
    import numpy as np
    from vtoy import bspimport
    k = 0.6                                                   # the slope: up 0.6 per unit along x

    def piece(x0, x1, z0=0.0, z1=200.0):
        p = np.array([[x0, k * x0, z0], [x0, k * x0, z1], [x1, k * x1, z1], [x1, k * x1, z0]])
        n = np.cross(p[1] - p[0], p[3] - p[0])
        return (p if n[1] > 0 else p[::-1].copy(), n / np.linalg.norm(n) * (1 if n[1] > 0 else -1))
    faces = [piece(0, 50), piece(63.7, 66.5), piece(66.5, 90), piece(300, 400)]
    out, made = bspimport.bridge_plane_gaps(faces)
    assert made == 1
    strip = out[-1][0]
    assert strip[:, 0].min() == pytest.approx(50) and strip[:, 0].max() == pytest.approx(63.7)
    assert np.allclose(strip[:, 1], k * strip[:, 0])          # on the slope
    floors = [(p, p.min(0), p.max(0)) for p, n in out]
    for x in np.arange(1.0, 89.0, 0.5):                       # standing ground all the way up
        assert bspimport._floor_heights(floors, x, 100.0, -10, 100), x
    level = [piece(0, 50)[0] * [1, 0, 1], piece(80, 120)[0] * [1, 0, 1]]
    _out, made = bspimport.bridge_plane_gaps([(p, np.array([0.0, 1, 0])) for p in level])
    assert made == 1                                          # 30 cm between two level floors: closed
    far = [(p * [1, 0, 1], np.array([0.0, 1, 0])) for p in (piece(0, 50)[0], piece(120, 160)[0])]
    assert bspimport.bridge_plane_gaps(far)[1] == 0           # 70 cm: a real gap


def test_slit_between_tread_and_ramp_closed():
    """de_cbble's stairs: each tread ended 4 cm short of the next step's ramp (another plane) - the player caught at
    every step.  The strip joins them; past a slit to a floor up to 46 cm lower a step ramp goes down onto it; a
    higher drop (a ledge) is left as it is."""
    import numpy as np
    from vtoy import bspimport
    tread = (np.array([[-100.0, 28, 0], [-100, 28, 200], [0, 28, 200], [0, 28, 0]]), np.array([0.0, 1, 0]))
    r = np.array([[4.0, 27, 0], [4, 27, 200], [40, 14, 200], [40, 14, 0]])
    n = np.cross(r[1] - r[0], r[3] - r[0])
    ramp = (r if n[1] > 0 else r[::-1].copy(), n / np.linalg.norm(n) * np.sign(n[1]))
    out, made = bspimport.bridge_plane_gaps([tread, ramp])
    assert made == 1 and out[-1][0][:, 0].min() == pytest.approx(0) and out[-1][0][:, 0].max() == pytest.approx(4)
    low = (np.array([[4.0, -10, 0], [4, -10, 200], [60, -10, 200], [60, -10, 0]]), np.array([0.0, 1, 0]))
    out, made = bspimport.bridge_plane_gaps([tread, low])               # 38 cm down past a slit: a step ramp
    assert made == 1                                                    # from the tread's edge onto the floor
    r = out[-1][0]
    assert r[:, 0].min() == pytest.approx(0) and r[:, 0].max() == pytest.approx(60)
    assert r[r[:, 0] < 1, 1] == pytest.approx(28) and r[r[:, 0] > 59, 1] == pytest.approx(-10)
    deep = (np.array([[4.0, -40, 0], [4, -40, 200], [60, -40, 200], [60, -40, 0]]), np.array([0.0, 1, 0]))
    assert bspimport.bridge_plane_gaps([tread, deep])[1] == 0           # 68 cm down: a ledge, left alone
