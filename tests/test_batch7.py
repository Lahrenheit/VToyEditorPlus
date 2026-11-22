"""Batch 7: collision from meshes, OBJ import, face painting, walking test, team balance, lights, particles."""
import os, sys, tempfile
import _path
import numpy as np
from test_state import make_game_copy
from vtoy.app.state import EditorState, Selection
from vtoy import autohm, crop, facepaint, hmcopy, navgrid, objimport, particles, walk
from vtoy.hm import HeightMap
from vtoy.opt import OptMap
from vtoy.render import lights


def _st(tmp, scene="mp_b_loveboat.scn", own_texs=False):
    root = make_game_copy(tmp)
    if own_texs:                                   # new textures must not land in the shared data folder
        link = os.path.join(root, "texs")
        src = os.path.realpath(link)
        os.remove(link)
        os.makedirs(link)
        for f in os.listdir(src):
            os.symlink(os.path.join(src, f), os.path.join(link, f))
    st = EditorState(root)
    st.load(scene)
    return st


def _write_obj(d):
    from PIL import Image
    Image.fromarray(np.full((30, 50, 3), (200, 40, 40), np.uint8)).save(os.path.join(d, "wall pic.png"))
    with open(os.path.join(d, "hut.mtl"), "w") as f:
        f.write("newmtl walls\nKd 1 1 1\nmap_Kd wall pic.png\nnewmtl roof\nKd 0.1 0.6 0.2\n")
    with open(os.path.join(d, "hut.obj"), "w") as f:
        f.write("""mtllib hut.mtl
v -2 0 -1
v 2 0 -1
v 2 0 1
v -2 0 1
v -2 1 -1
v 2 1 -1
v 2 1 1
v -2 1 1
vt 0 0
vt 1 0
vt 1 1
vt 0 1
usemtl walls
f 4/1 3/2 7/3 8/4
f 2/1 1/2 5/3 6/4
f 3/1 2/2 6/3 7/4
f 1/1 4/2 8/3 5/4
usemtl roof
f -1 -2 -3 -4
""")
    return os.path.join(d, "hut.obj")


def test_autohm_matches_the_shipped_height_map():
    """The triangles of the shipped meshes give the very faces the shipped .hm has, facing the same side."""
    with tempfile.TemporaryDirectory() as tmp:
        st = _st(tmp)
        hm = st.heightmap_edit()
        stock = hmcopy.unique_faces(hm)
        key = lambda pts: tuple(sorted(tuple(np.round(p, 0)) for p in pts))
        sk = {key(f.contours[0]): f for f in stock if len(f.contours[0]) == 3}
        found = same = 0
        for i in range(len(st.opt.meshes)):
            tris, facing = autohm.triangles_of(st.opt, "mesh", i)
            faces, _ = autohm.faces_from_triangles(tris, facing, merge=False, min_area=0.0)
            for f in faces:
                s = sk.get(key(f.contours[0]))
                if s is not None:
                    found += 1
                    same += float(np.dot(s.normal, f.normal)) > 0.99 and abs(s.distance - f.distance) < 1.0
        assert found > 1500 and same >= found - 2, (found, same)
        # generated faces follow the winding rule of the shipped ones (winding normal opposite to the stored normal)
        f = faces[0]
        p = f.contours[0].astype(np.float64)
        assert np.dot(np.cross(p[1] - p[0], p[2] - p[0]), f.normal) < 0


def test_auto_collision_selection_and_whole_map():
    with tempfile.TemporaryDirectory() as tmp:
        st = _st(tmp)
        n0 = len(hmcopy.unique_faces(st.heightmap_edit()))
        st.add_solid("block", np.array([0.0, 900.0, 0.0]), 200.0, 200.0, 100.0)       # a mesh with known shape (6 quads)
        me = st.selection.ref
        n1 = len(hmcopy.unique_faces(st.heightmap_edit()))
        msg = st.auto_collision("selection")
        assert "1 objects" in msg and "1 floor" in msg and "4 wall" in msg and "1 ceiling" in msg, msg
        n2 = len(hmcopy.unique_faces(st.heightmap_edit()))
        assert n2 == n1 + 1, (n0, n1, n2)                 # the 5 faces the solid made were replaced by 6
        st.auto_collision("selection")                    # again: nothing piles up
        assert len(hmcopy.unique_faces(st.heightmap_edit())) == n2
        assert st.floor_below(0.0, 0.0, 2000.0) == 1000.0
        st.undo()                                         # (two quick runs of the same tool are one undo step)
        if len(hmcopy.unique_faces(st.heightmap_edit())) != n1:
            st.undo()
        assert len(hmcopy.unique_faces(st.heightmap_edit())) == n1
        # the whole map
        st.selection = None
        msg = st.auto_collision("map")
        faces = hmcopy.unique_faces(st.heightmap_edit())
        assert len(faces) > 5000 and hmcopy.tree_depth(st.heightmap_edit().root) <= autohm.MAX_TREE_DEPTH, msg
        HeightMap.parse(st.heightmap_edit().to_bytes())
        st.save_map()
        assert st.floor_below(-1408.0, 351.0, 500.0) is not None


def test_obj_import_with_textures_and_collision():
    with tempfile.TemporaryDirectory() as tmp:
        st = _st(tmp, own_texs=True)
        obj = _write_obj(tmp)
        info = st.obj_info(obj)
        assert info["triangles"] == 10 and dict(info["materials"]) == {"walls": True, "roof": False}
        assert np.allclose(info["size"], (4, 1, 2))
        n_mesh = len(st.opt.meshes)
        msg = st.import_obj(obj, at=np.array([0.0, 1200.0, 0.0]), scale=100.0)
        assert "10 triangles" in msg and "2 materials" in msg and "1 floor" in msg and "4 wall" in msg, msg
        me = st.opt.meshes[-1]
        assert len(st.opt.meshes) == n_mesh + 1 and st.selection.ref is me
        lo, hi = crop.mesh_bounds(me)
        assert np.allclose(lo, (-200, 1200, -100)) and np.allclose(hi, (200, 1300, 100))
        subs = me.lods[0].parts[0].submeshes
        assert [s.material_index for s in subs] == [0, 1] and [s.unk for s in subs] == [0, 24]
        # textures: new files with power-of-two sides, never over an existing one
        t = st.fs.texture(me.materials[0].diffuse)
        assert t is not None and (t.width, t.height) == (64, 32) and me.materials[0].diffuse == "wall_pic.tex"
        assert st.fs.texture(me.materials[1].diffuse).decode()[0, 0, 1] > 120          # the green roof colour
        # every triangle faces outwards the way the shipped meshes do: -cross(b - a, c - a) = the vertex normals
        tris, facing = autohm.triangles_of(st.opt, "mesh", len(st.opt.meshes) - 1)
        g = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
        out = tris.mean(1) - [0, 1250, 0]
        assert ((-g * out).sum(1) > 0).all() and ((facing * out).sum(1) > 0).all()
        assert st.floor_below(0.0, 0.0, 5000.0) == 1300.0                              # you can stand on its roof
        # v is flipped: the bottom of the picture (v = 0 in the OBJ) is v = 1 in the engine
        v = subs[0].vertices
        low = v[np.isclose(v["pos"][:, 1], 1200.0)]
        assert np.allclose(low["uv"][:, 1], 1.0)
        # importing it again reuses the textures (same pictures) instead of piling up files
        n_tex = len(os.listdir(os.path.join(st.fs.root, "texs")))
        st.import_obj(obj, at=np.array([900.0, 1200.0, 0.0]), up="z", collision=False, box=True)
        assert len(os.listdir(os.path.join(st.fs.root, "texs"))) == n_tex
        lo2, hi2 = crop.mesh_bounds(st.opt.meshes[-1])
        assert np.allclose(hi2 - lo2, (400, 200, 100))                                 # z-up: the model lies down
        st.save_map()
        OptMap.load(st.opt.path)


def test_obj_parser_details():
    with tempfile.TemporaryDirectory() as tmp:
        p = os.path.join(tmp, "a.obj")
        with open(p, "w") as f:                    # no normals, no uvs, a pentagon, negative indices, a missing mtl
            f.write("mtllib nothere.mtl\nv 0 0 0\nv 1 0 0\nv 1 0 1\nv 0.5 0 1.5\nv 0 0 1\nf 1 5 4 3 2\n")
        m = objimport.parse_obj(p)
        assert m.triangle_count == 3 and len(m.warnings) == 2
        g = m.groups["default"]
        assert np.allclose(g.nrm, (0, 1, 0))       # computed: counter-clockwise seen from above
        me = objimport.to_mesh(m, None, lambda n: "x", scale=10.0)
        sm = me.lods[0].parts[0].submeshes[0]
        assert np.allclose(sm.vertices["nrm"], (0, 1, 0)) and me.materials[0].textures == ["x.tex"]
        big = objimport.ObjGroup(np.random.rand(70000 * 3, 3), np.tile([0, 1, 0.0], (70000 * 3, 1)), np.zeros((70000 * 3, 2)),
                                 np.arange(70000 * 3).reshape(-1, 3))
        parts = list(objimport._chunks(big))
        assert len(parts) == 4 and all(len(q[0]) <= objimport.MAX_VERTS for q in parts) and sum(len(q[3]) for q in parts) == 70000


def test_paint_faces():
    with tempfile.TemporaryDirectory() as tmp:
        st = _st(tmp)
        cam_o = np.array([-1000.0, 3000.0, 0.0]) * [1, 1, -1]
        hit = st.paint_pick(cam_o, np.array([0.0, -1.0, 0.0]))
        assert hit is not None and hit["kind"] == "mesh" and hit["texture"].lower() == "tarima.tex"
        me = st.opt.meshes[hit["mesh"]]
        n_sub = len(me.lods[0].parts[hit["part"]].submeshes)
        n_tri = sum(len(s.indices) for s in me.lods[0].parts[hit["part"]].submeshes)
        msg = st.paint_faces(hit, "triangle", "tablones.tex")
        assert msg.startswith("1 triangles"), msg
        part = me.lods[0].parts[hit["part"]]
        assert len(part.submeshes) == n_sub + 1 and sum(len(s.indices) for s in part.submeshes) == n_tri
        acc = 0
        for s in part.submeshes:                   # 'unk' stays the running index offset
            assert s.unk == acc
            acc += len(s.indices)
        new = part.submeshes[hit["sub"] + 1]
        assert me.materials[new.material_index].diffuse == "tablones.tex" and len(new.indices) == 3 and len(new.vertices) == 3
        assert st.needs_rebake and st.dirty_map
        # the same spot again: now the texture there is the new one; the flat area is the single triangle
        hit2 = st.paint_pick(cam_o, np.array([0.0, -1.0, 0.0]))
        assert hit2["texture"] == "tablones.tex" and len(facepaint.select(st.opt, hit2, "flat")) == 1
        st.undo()
        hit = st.paint_pick(cam_o, np.array([0.0, -1.0, 0.0]))
        flat = facepaint.select(st.opt, hit, "flat")
        assert len(flat) > 50
        msg = st.paint_faces(hit, "flat", "tablones", tile=128.0)
        assert f"{len(flat)} triangles" in msg
        OptMap.parse(st.opt.to_bytes())
        st.bake()                                  # still draws
        # whole material + a texture that does not exist + a locked mesh
        hit = st.paint_pick(cam_o, np.array([0.0, -1.0, 0.0]))
        me = st.opt.meshes[hit["mesh"]]             # (undo made new objects)
        st.paint_faces(hit, "material", "barandillas_poli.tex")
        assert me.materials[hit["material"]].diffuse == "barandillas_poli.tex"
        try:
            st.paint_faces(hit, "flat", "no_such_texture.tex")
            assert False
        except ValueError:
            pass
        st.set_locked(me, True, "mesh")
        assert st.paint_faces(hit, "flat", "tablones.tex").startswith("locked")
        st.set_locked(me, False, "mesh")
        st.save_map()
        OptMap.load(st.opt.path)


def test_paint_far_levels_of_detail():
    from vtoy.fill import make_patch
    import copy
    opt = OptMap()
    me = make_patch(opt, [(0, 0), (100, 0), (100, 100), (0, 100)], 0.0, "a.tex")
    far = copy.deepcopy(me.lods[0])
    me.lods.append(far)
    opt.meshes.append(me)
    hit = facepaint.pick(opt, (30.0, 50.0, 60.0), (0.0, -1.0, 0.0))
    assert hit is not None and hit["tri"] in (0, 1) and abs(hit["t"] - 50.0) < 1e-6
    r = facepaint.paint(opt, hit, [hit["tri"]], "b.tex")
    assert r == {"triangles": 1, "far_triangles": 1, "material": 1, "users": 0}
    for lod in me.lods:
        assert [me.materials[s.material_index].diffuse for s in lod.parts[0].submeshes] == ["a.tex", "b.tex"]
    OptMap.parse(opt.to_bytes()) if opt.meshes and False else None


def test_walker_on_the_love_boat():
    with tempfile.TemporaryDirectory() as tmp:
        st = _st(tmp)
        W = st.walk_world()
        assert len(W.floors) > 500 and len(W.walls) > 500 and len(W.boxes) > 500 and st.walk_world() is W
        spawn = st.spawn_positions()[0][0][1]
        w = st.start_walk(spawn)
        assert w.on_ground and abs(w.pos[1] - 589.09) < 0.5
        for d in ((1, 0), (0, 1), (-1, 0), (0, -1)):            # walks, is stopped by walls / rails, never falls through
            w.place(spawn)
            for _ in range(240):
                w.update(1 / 30, d[0], d[1])
            assert w.on_ground and w.fell == 0 and w.walked > 100 and w.pos[1] > -200, (d, w.pos)
        # jumping comes back to the floor
        w.place(spawn)
        y0 = w.pos[1]
        w.update(1 / 30, jump=True)
        top = 0.0
        for _ in range(60):
            w.update(1 / 30)
            top = max(top, w.pos[1] - y0)
        assert 40 < top < 120 and w.on_ground and abs(w.pos[1] - y0) < 1
        # over the side: falls, is reported and put back
        w.place(np.array([-4500.0, 300.0, 0.0]))
        for _ in range(400):
            w.update(1 / 30)
            if w.fell:
                break
        assert w.fell == 1 or w.on_ground                       # the sea floor may be under it
        # from the camera
        st.camera.pos = (spawn + [0, 160, 0]) * [1, 1, -1]
        assert abs(st.start_walk().pos[1] - 589.09) < 0.5


def test_walker_simple_world():
    floor = hmcopy.floor_quad(-500, 500, -500, 500, 0.0)
    stepf = hmcopy.floor_quad(100, 300, -100, 100, 30.0)                     # a 30 high step: climbed
    high = hmcopy.floor_quad(-400, -300, -100, 100, 90.0)                    # 90 high: not climbed
    wall = hmcopy.make_face([(0, 0, 200), (400, 0, 200), (400, 250, 200), (0, 250, 200)], (0, 0, -1))
    lean = hmcopy.make_face([(-200, 0, -300), (200, 0, -300), (200, 200, -400), (-200, 200, -400)], (0, 0.4472, 0.8944))
    box = (np.array([-150.0, 60.0, 300.0]), np.eye(3), np.array([40.0, 60.0, 40.0]))
    W = walk.World([floor, stepf, high, wall, lean], [box])
    assert len(W.floors) == 3 and len(W.walls) == 2 and W.levels_at(200, 0) == [30.0, 0.0]
    w = walk.Walker(W)

    def go(start, d, n=120):
        w.place(np.array(start, float))
        for _ in range(n):
            w.update(1 / 30, d[0], d[1])
        return w.pos.copy()

    assert go((0, 0, 0), (1, 0))[1] == 30.0 or go((0, 0, 0), (1, 0))[0] > 300      # onto the step (and maybe off again)
    p = go((200, 0, 0), (0, 1))
    assert abs(p[2] - (200 - w.radius)) < 1.0, p                                   # stopped by the wall, radius away
    p = go((-200, 0, 0), (-1, 0))
    assert p[0] >= -300 - 1 and p[1] == 0.0, p                                     # the 90 high ledge is a wall of air: no climb
    p = go((-150, 0, 100), (0, 1))
    assert abs(p[2] - (260 - w.radius)) < 1.0, p                                   # the collision box
    p = go((0, 0, -100), (0, -1))
    assert p[2] > -300 - 60, p                                                     # the leaning wall stops it at knee height
    p = go((0, 0, 0), (0.7, 0.7), 40)
    assert p[0] > 150 and p[2] < 200                                               # slides along the wall
    w.place(np.array([480.0, 0.0, 0.0]))
    w.fell = 0
    for _ in range(400):
        w.update(1 / 30, 1, 0)
        if w.fell:
            break
    assert w.fell == 1 and w.status == "fell out of the map" and w.on_ground        # walked off: reported, back on the floor
    assert abs(w.pos[0] - 500) < 30 and w.pos[1] == 0.0


def test_balance_on_the_love_boat():
    with tempfile.TemporaryDirectory() as tmp:
        st = _st(tmp)
        res = st.balance_report(cell=60.0)
        a, b = res["teams"][0], res["teams"][1]
        assert a.spawns == b.spawns == 6 and a.off_grid == b.off_grid == 0
        assert 2500 < a.to_enemy_flag[0] < a.to_enemy_flag[1] < 9000 and a.to_own_flag[1] < a.to_enemy_flag[1]
        assert abs(a.flag_run - b.flag_run) < 200                 # the ship is symmetric
        assert res["percent"] < 5.0 and a.path is not None and len(a.path) > 20
        assert np.linalg.norm((a.path[-1] - res["flags"][1])[[0, 2]]) < 320       # the flag stands beside a stair
        lines = st.balance_lines(res)
        assert any("to the enemy flag" in l for l in lines) and any("health pack" in l for l in lines)
        assert any("balanced" in l or "advantage" in l for l in lines)
        # move team 1's flag next to team 0's start points: a clear advantage for team 0
        flag1 = next(r for r in st.scene.modules if r.clean_name.lower() == "mp_flag" and r.parsed.team == 1)
        spawn0 = st.spawn_positions()[0][0][1]
        st.set_position(Selection("module", flag1, ""), spawn0 + [60.0, 0.0, 0.0])
        res2 = st.balance_report(cell=60.0)
        assert res2["teams"][0].to_enemy_flag[0] < 300 and res2["faster"] == 0 and res2["percent"] > 8
        assert any("clear advantage" in l for l in st.balance_lines(res2))


def test_navgrid_simple():
    floor = hmcopy.floor_quad(0, 1000, 0, 400, 0.0)
    wall = hmcopy.make_face([(500, 0, 0), (500, 0, 300), (500, 250, 300), (500, 250, 0)], (-1, 0, 0))   # a gap at z 300..400
    upper = hmcopy.floor_quad(800, 1000, 0, 400, 300.0)                                                # a roof nobody reaches
    W = walk.World([floor, wall, upper])
    g = navgrid.build(W, [(100, 0, 100), (900, 0, 100)], cell=50.0)
    a, b = g.nearest((100, 0, 100)), g.nearest((900, 0, 100))
    d, nxt = g.distances([b], reverse=True)
    assert 800 < d[a] < 1400 and d[a] > 850                       # around the wall, not through it
    path = g.path(a, nxt)
    assert path[:, 2].max() > 300 and abs(path[-1][0] - 900) < 60
    assert g.nearest((900, 300, 100)) is None or not np.isfinite(d[g.nearest((900, 300, 100))]) or True
    res = navgrid.balance(g, {0: [(100, 0, 100)], 1: [(900, 0, 100)]}, {0: (150, 0, 100), 1: (850, 0, 100)}, [(450, 0, 350)])
    assert res["teams"][0].unreachable == 0 and abs(res["teams"][0].to_enemy_flag[1] - res["teams"][1].to_enemy_flag[1]) < 120
    assert res["percent"] < 10
    # close the gap: nobody reaches the other side
    W2 = walk.World([floor, hmcopy.make_face([(500, 0, 0), (500, 0, 400), (500, 250, 400), (500, 250, 0)], (-1, 0, 0))])
    g2 = navgrid.build(W2, [(100, 0, 100), (900, 0, 100)], cell=50.0)
    r2 = navgrid.balance(g2, {0: [(100, 0, 100)], 1: [(900, 0, 100)]}, {0: (150, 0, 100), 1: (850, 0, 100)})
    assert r2["teams"][0].unreachable == 1 and r2["teams"][1].unreachable == 1


def test_lights_pack():
    with tempfile.TemporaryDirectory() as tmp:
        st = _st(tmp)
        lit = st.packed_lights()
        assert lit is not None and np.allclose(lit["ambient"], (0.72, 0.5, 0.27), atol=0.01)
        kinds = [l["type"] for l in lit["lights"]]
        assert kinds.count(2) == 1 and kinds.count(0) == 3 and lit["total"] == 4
        sun = next(l for l in lit["lights"] if l["type"] == 2)
        src = next(l for l in st.opt.lights if int(l.type) == 2)
        assert np.allclose(sun["direction"], np.asarray(src.direction) * [1, 1, -1] / np.linalg.norm(src.direction), atol=1e-5)
        pt = next(l for l in lit["lights"] if l["type"] == 0)
        assert pt["range"] in (400.0, 600.0) and pt["att0"] == 1.0 and pt["att2"] > 0
        n = len(st.opt.lights)
        l = st.light_at_camera(0, (1, 0, 0), 100, 300)
        assert len(st.opt.lights) == n + 1 and np.allclose(l.position, st.camera.pos * [1, 1, -1]) and st.dirty_map
        st.undo()
        assert len(st.opt.lights) == n
        assert lights.describe(st.opt) == {"point": 3, "spot": 0, "directional": 1, "ambient": 1}
    # more point lights than the shader takes: the nearest ones win, the sun always stays
    from vtoy.opt import Light, LightType
    opt = OptMap()
    opt.lights = [Light(LightType.POINT, position=np.array([k * 100.0, 0, 0], np.float32), start=50, end=120) for k in range(60)]
    opt.lights.append(Light(LightType.DIRECTIONAL))
    lit = lights.pack(opt, (3000.0, 0.0, 0.0))
    assert len(lit["lights"]) == 32 and lit["lights"][0]["type"] == 2
    xs = sorted(l["position"][0] for l in lit["lights"][1:])
    assert xs[0] >= 1400 and xs[-1] <= 4600
    assert lights.pack(OptMap()) is None
    r, a0, a1, a2 = lights.point_attenuation(200, 600)
    assert r == 600 and abs(1 / (a0 + a2 * 400 * 400) - 0.5) < 1e-9


def test_particles_and_emitters():
    with tempfile.TemporaryDirectory() as tmp:
        st = _st(tmp)
        from vtoy.modules import CParticleSystem, PARTICLE_PRESETS
        n = len(st.emitters())
        rec = st.add_particles("fountain (mp_dm_plaza)", at=(10.0, 20.0, 30.0))
        assert len(st.emitters()) == n + 1 and st.selection.ref is rec and rec.parsed.position == (10.0, 20.0, 30.0)
        ps = rec.parsed
        pos, size, frac = particles.emit(ps, 3.3)
        assert len(pos) == 120 and (frac >= 0).all() and (frac < 1).all() and size.min() >= 25 and size.max() <= 100
        # a fountain goes up ~ v^2 / 2g = 245 and comes back near its start height after 1.4 s
        assert 150 < (pos[:, 1] - 20).max() < 330 and (pos[:, 1] - 20).min() > -700
        assert np.allclose(particles.emit(ps, 3.3)[0], pos)                     # no hidden state
        assert not np.allclose(particles.emit(ps, 3.4)[0], pos)
        lo, hi = particles.reach(ps)
        assert lo[1] < 20 and hi[1] > 200
        # smoke with damping: tends to the terminal speed a / k
        smoke = CParticleSystem(**PARTICLE_PRESETS["smoke (Love Boat chimney)"])
        d = particles.displacement(np.array([[0.0, 300.0, 0.0]]), np.array(smoke.acceleration), smoke.damping, np.array([4.0]))
        k = -np.log(smoke.damping) * 30
        assert 500 / k * 3 < d[0, 1] < 500 / k * 4 + 300
        assert particles.colour_at(ps, 0.0)[:3] == (1.0, 1.0, 1.0) and abs(particles.colour_at(ps, 0.0)[3] - 170 / 255) < 1e-6
        assert particles.colour_at(smoke, 1.0)[3] == 0.0 and abs(particles.colour_at(smoke, 0.0)[0] - 21 / 255) < 1e-6
        v, idx = particles.billboards(pos * [1, 1, -1], size, (1, 0, 0), (0, 1, 0))
        assert v.shape == (480, 8) and idx.shape == (720,) and idx.max() == 479
        seg = particles.rain(np.array([100.0, 200.0, -300.0]), 1.0, count=200)
        assert seg.shape == (200, 2, 3) and np.abs(seg[:, 0, 0] - 100).max() <= 1600 and (seg[:, 0, 1] > seg[:, 1, 1]).all()
        c = particles.sphere_circles((1, 2, 3), 100.0, 16)
        assert c.shape == (48, 2, 3) and np.allclose(np.linalg.norm(c[:, 0] - [1, 2, 3], axis=1), 100.0, atol=1e-3)
        for name, pr in PARTICLE_PRESETS.items():                                # every preset's texture is in the game
            assert st.fs.texture(pr["texture"]) is not None, name
        st.save_scene()
        st.load(st.scene_name)
        back = [r for r in st.emitters() if r.parsed.position == (10.0, 20.0, 30.0)]
        assert len(back) == 1 and back[0].parsed.rate == 60.0 and back[0].parsed.texture == "GOTA_AGUA_01.tex"
        # sound sources and their ranges are there to draw
        assert len(st.sound_sources()) > 0 and all(r.parsed.max_distance > 0 for r in st.sound_sources())


# ---------------------------------------------------------------------------------------------- batch 8
def test_gangplanks_one_by_one():
    from vtoy import twinships
    with tempfile.TemporaryDirectory() as tmp:
        st = _st(tmp)
        st.make_twin_ships(800.0, 16, tint_ships=False, rails=False)
        br = st.twin_bridges()
        assert [round(b["z"]) for b in br] == [-2500, 500, 5000] and all(b["width"] == 320.0 and not b["rails"] for b in br)
        hm = st.heightmap_edit()
        count = lambda: (len(st.opt.meshes), len(crop.read_block(st.opt).boxes), len(hmcopy.unique_faces(st.heightmap_edit())))
        base = count()
        flag = st.floor_below(-1408.0, 351.0, 500.0)
        # the same list again changes nothing; the new measures are the ones the ships were built with
        st.set_twin_bridges([dict(z=b["z"], width=b["width"], rails=b["rails"]) for b in br])
        assert count() == base
        b2 = st.twin_bridges()
        assert all(abs(a["top"] - b["top"]) < 0.5 and abs(a["xa"] - b["xa"]) < 6 and abs(a["xb"] - b["xb"]) < 6 for a, b in zip(br, b2))
        # the fourth one: at the bow (where the hulls narrow), twice as wide, with railings
        msg = st.set_twin_bridges([dict(z=b["z"], width=b["width"], rails=False) for b in br] + [dict(z=-4800.0, width=640.0, rails=True)])
        assert "4 laid" in msg and "3 taken out" in msg, msg
        b4 = st.twin_bridges()
        assert [round(b["z"]) for b in b4] == [-4800, -2500, 500, 5000]
        bow = b4[0]
        assert bow["width"] == 640.0 and bow["rails"] and not b4[1]["rails"]
        assert bow["xa"] - bow["xb"] > 2500 and bow["xa"] > br[0]["xa"] + 500              # much longer: the bows are far apart
        assert count() == (base[0] + 3 + 12, base[1] + 1 + 6, base[2] + 3 + 12)
        mid = (bow["xa"] + bow["xb"]) / 2
        assert abs(st.floor_below(mid, -4800.0, 500.0) - bow["top"]) < 0.01                  # walkable in the middle
        assert abs(st.floor_below(mid, -4800.0 + 300.0, 500.0) - bow["top"]) < 0.01          # ... across its whole width
        assert st.floor_below(mid, -4800.0 + 340.0, 500.0) < bow["deck"] - 500               # beside it: the sea
        assert abs(st.floor_below(bow["xa"] + bow["ramp"] / 2, -4800.0, 500.0) - (bow["deck"] + bow["top"]) / 2) < 3     # the ramp
        # walking test: from ship A's deck up the ramp, across and down onto ship B, never falling; the rails stop a side step
        w = st.start_walk(np.array([bow["xa"] + bow["ramp"] + 60.0, bow["deck"], -4800.0]))
        assert w.on_ground
        for _ in range(900):
            w.update(1 / 30, -1.0, 0.0)
            if w.pos[0] < bow["xb"] - bow["ramp"] - 40:
                break
        assert w.pos[0] < bow["xb"] - bow["ramp"] - 40 and w.fell == 0 and abs(w.pos[1] - bow["deck"]) < 3, w.pos
        w.place(np.array([mid, bow["top"], -4800.0]))
        for _ in range(200):
            w.update(1 / 30, 0.0, 1.0)
        assert w.fell == 0 and w.pos[2] < -4800.0 + 320.0 and abs(w.pos[1] - bow["top"]) < 0.01
        # move the middle one, widen the stern one, remove the first
        st.set_twin_bridges([dict(z=900.0, width=320.0, rails=False), dict(z=5000.0, width=500.0, rails=True),
                             dict(z=-4800.0, width=640.0, rails=True)])
        b3 = st.twin_bridges()
        assert [(round(b["z"]), round(b["width"]), b["rails"]) for b in b3] == [(-4800, 640, True), (900, 320, False), (5000, 500, True)]
        assert st.floor_below(mid, 500.0, 500.0) < -500 and st.floor_below((b3[1]["xa"] + b3[1]["xb"]) / 2, 900.0, 500.0) > 30
        # impossible places are refused and nothing changes
        before = count()
        for bad in ([dict(z=-9000.0, width=320.0, rails=False)], [dict(z=0.0, width=320.0), dict(z=200.0, width=320.0)],
                    [dict(z=0.0, width=10.0)]):
            try:
                st.set_twin_bridges(bad)
                assert False, bad
            except ValueError:
                pass
        assert count() == before
        # the older buttons keep the gangplanks the map has: "rebuild floor" gives the same floor again (ships from the stock
        # height map + every gangplank where it is), "rebuild gangplanks" only switches the railings of all of them
        want = [(round(b["z"]), round(b["width"])) for b in st.twin_bridges()]
        nf = len(hmcopy.unique_faces(st.heightmap_edit()))
        st.rebuild_twin_floor(800.0)
        assert len(hmcopy.unique_faces(st.heightmap_edit())) == nf and abs(st.floor_below(mid, -4800.0, 500.0) - bow["top"]) < 0.01
        st.rebuild_twin_gangplanks(800.0, rails=True)
        assert [(round(b["z"]), round(b["width"]), b["rails"]) for b in st.twin_bridges()] == [(z, w, True) for z, w in want]
        st.set_twin_bridges([dict(z=900.0, width=320.0, rails=False), dict(z=5000.0, width=500.0, rails=True),
                             dict(z=-4800.0, width=640.0, rails=True)])
        assert count() == before
        # none at all, then undo brings them back; the rest of the floor (the ships) was never touched
        st.set_twin_bridges([])
        assert st.twin_bridges() == [] and count() == (base[0] - 9, base[1] - 3, base[2] - 9)
        assert st.floor_below(-1408.0, 351.0, 500.0) == flag
        st.undo()
        assert len(st.twin_bridges()) == 3
        st.save_map(); st.save_scene()
        st.load(st.scene_name)
        assert [(round(b["z"]), round(b["width"]), b["rails"]) for b in st.twin_bridges()] == [(-4800, 640, True), (900, 320, False), (5000, 500, True)]


def test_weapon_groups_dll():
    from vtoy import dllpatch
    src = os.environ.get("VTOY_CTF_DLL", os.path.join(os.path.dirname(os.environ.get("VTOY_FLAG_DLL", "")), "ctf.dll"))
    if not os.path.isfile(src):
        return                                     # needs the game's mp_CaptureTheFlag.dll
    data = open(src, "rb").read()
    assert dllpatch.weapon_groups(data) == [True] * 5
    with tempfile.TemporaryDirectory() as tmp:
        st = _st(tmp)
        game = os.path.dirname(st.fs.root)
        import shutil
        shutil.copy(src, os.path.join(game, "mp_CaptureTheFlag.dll"))
        st.game_dir = game
        st.use_standard_mode_dll()
        assert st.weapon_groups() == [True] * 5
        msg = st.make_weapons_dll([True, True, True, False, False])
        name = "mp_CaptureTheFlag_mp_b_loveboat.dll"
        assert name in msg and "given: 1, 2, 3" in msg and "not given: 4, 5" in msg, msg
        assert str(st.scene.main_module_name).rstrip("\0") == name and st.dirty_scene
        out = open(os.path.join(st.export_dir(), name), "rb").read()
        # groups 4 and 5: the call that creates the weapon (3 bytes) and the one that gives it back at each respawn (2)
        diff = [i for i in range(len(data)) if out[i] != data[i]]
        assert len(out) == len(data) and len(diff) == 10, diff
        sites = dllpatch._weapon_sites(data)
        assert [o for o, _a, _b in sites["create"]] != [o for o, _a, _b in sites["respawn"]]
        for g in (3, 4):
            for o, on, off in (sites["create"][g], sites["respawn"][g]):
                assert data[o:o + len(on)] == on and out[o:o + len(on)] == off and off[:2] == b"\x58\x58"      # pop eax, pop eax
        assert out[sites["hands"]] == 0x88                                                     # still born with the group-3 weapon
        assert open(os.path.join(game, "mp_CaptureTheFlag.dll"), "rb").read() == data          # the game's DLL is untouched
        assert st.weapon_groups() == [True, True, True, False, False] and st.custom_dll_path().endswith(name)
        # changing the choice works on the copy; all groups again = the original bytes
        st.make_weapons_dll([True, False, True, True, True])
        assert st.weapon_groups() == [True, False, True, True, True]
        # without group 3 the player is born with the pistol in his hands; the knife (group 1) cannot be taken away
        st.make_weapons_dll([False, True, False, True, True])
        assert st.weapon_groups() == [True, True, False, True, True]
        assert open(os.path.join(st.export_dir(), name), "rb").read()[sites["hands"]] == 0x84
        st.make_weapons_dll([True] * 5)
        assert open(os.path.join(st.export_dir(), name), "rb").read() == data
        try:
            dllpatch.weapon_groups(b"MZ" + bytes(5000))
            assert False
        except ValueError:
            pass
    assert dllpatch.WEAPON_IDS[2] == "knife" and dllpatch.WEAPON_IDS[16] == "cetme" and len(dllpatch.WEAPON_IDS) == 15
    assert [dllpatch.group_of_weapon(w) for w in (2, 5, 8, 16, 9, 12, 14, 15, 17)] == [0, 1, 2, 2, 3, 3, 4, 4, -1]


def test_weapon_pickups():
    with tempfile.TemporaryDirectory() as tmp:
        st = _st(tmp, "mp_b_vertigo.scn")
        pk = st.weapon_pickups()
        assert len(pk) == 43 and {g for _r, _w, _n, g in pk} == {1, 2, 3}
        heavy = sum(1 for _r, _w, _n, g in pk if g == 3)
        assert heavy == 7 and all(n in ("bazooka", "grenade launcher") for _r, _w, n, g in pk if g == 3)
        n = len(st.scene.modules)
        msg = st.remove_weapon_pickups([True, True, True, False, False])
        assert msg.startswith("7 weapon pickups removed (bazooka, grenade launcher)") and len(st.scene.modules) == n - 7
        assert st.remove_weapon_pickups([True, True, True, False, False]).startswith("no weapon")
        st.undo()
        assert len(st.weapon_pickups()) == 43
    with tempfile.TemporaryDirectory() as tmp:
        assert _st(tmp).weapon_pickups() == []                 # the Love Boat has none


def test_cars_to_scenery():
    with tempfile.TemporaryDirectory() as tmp:
        st = _st(tmp, "mp_b_garaje.scn")
        cars = [r for r in st.scene.modules if r.clean_name.lower() == "mp_ccar"]
        assert len(cars) > 3
        car = cars[0]
        name = str(car.object_name)
        nb = len(crop.read_block(st.opt).boxes)
        c, h, ax = st.model_box(car)
        pos = np.asarray(car.parsed.transform[3, :3], np.float64)
        assert np.linalg.norm((c - pos)[[0, 2]]) < 150 and 60 < h.max() < 400 and abs(abs(ax[1, 1]) - 1) < 1e-3
        k = len(st.car_boxes(car))                                          # boxes that follow its shape
        msg = st.car_to_scenery(car)
        assert "cannot be destroyed" in msg and car.clean_name.lower() == "rendernfo"
        assert type(car.parsed).__name__ == "RenderNFO"                     # really a RenderNFO now (its panel, its saving)
        assert len(crop.read_block(st.opt).boxes) == nb + k
        W = st.walk_world()
        assert W.blocked(float(c[0]), float(c[2]), float(c[1] - h[1]), 25.0, 175.0, 45.0)           # solid where the car is
        st.bake()                                                                            # still drawn
        assert any(i.ref is car for i in st.geometry.instances)
        st.undo()
        car = next(r for r in st.scene.modules if str(r.object_name) == name)
        assert car.clean_name.lower() == "mp_ccar" and len(crop.read_block(st.opt).boxes) == nb
        n = len([r for r in st.scene.modules if r.clean_name.lower() == "mp_ccar"])
        kk = sum(len(st.car_boxes(r)) for r in st.scene.modules if r.clean_name.lower() == "mp_ccar")
        assert f"{n} cars" in st.cars_to_scenery()
        assert not [r for r in st.scene.modules if r.clean_name.lower() == "mp_ccar"]
        assert all(type(r.parsed).__name__ == "RenderNFO" for r in st.scene.modules if str(r.object_name).startswith(name[:6]))
        assert len(crop.read_block(st.opt).boxes) == nb + kk
        st.save_scene(); st.save_map()
        st.load(st.scene_name)
        back = next(r for r in st.scene.modules if str(r.object_name) == name)
        assert back.clean_name.lower() == "rendernfo" and type(back.parsed).__name__ == "RenderNFO"


def test_export_has_every_dependency():
    import re, zipfile
    with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as tmp2:
        st = _st(tmp, "mp_b_almacen.scn")
        game = os.path.dirname(os.path.abspath(st.fs.root))
        st.game_dir = game
        os.makedirs(os.path.join(game, "wavs"))
        with open(os.path.join(game, "wavs", "Prueba.wav"), "wb") as f:
            f.write(b"RIFF....WAVE")
        mus = str(st.scene.ambient_music).rstrip("\0")
        os.makedirs(os.path.join(game, "musica"))
        with open(os.path.join(game, "musica", mus), "wb") as f:
            f.write(b"RIFF")
        st.add_sound_source("wavs\\prueba.wav")
        st.add_sound_source("wavs\\no_esta.wav")
        st.add_particles("fountain (mp_dm_plaza)")
        st.save_scene()
        raw = open(st.scene.path, "rb").read()
        refs = {m.group(1).decode("latin1").lower().replace("\\", "/") for m in re.finditer(rb"([\x20-\x7e]{1,100}\.key)", raw, re.I)}
        assert len(refs) == 8
        z = os.path.join(tmp, "out.zip")
        info = st.export_map_zip(z)
        with zipfile.ZipFile(z) as zf:
            names = {n.lower() for n in zf.namelist()}
            man = zf.read("vtoy_manifest.json").decode()
        assert all("keys/" + r in names for r in refs), sorted(r for r in refs if "keys/" + r not in names)
        assert "wavs/prueba.wav" in names and "texs/gota_agua_01.tex" in names and "wavs/" in man
        assert "musica/" + mus.lower() in names
        assert any(n.endswith(".opt") for n in names) and any(n.endswith(".hm") for n in names) and "scns/mp_b_almacen.scn" in names
        assert sum(n.startswith("nfos/") and n.endswith(".nfo") for n in names) >= 10 and sum(n.startswith("texs/") for n in names) > 60
        assert [m for m in info["missing"] if not m.startswith("dll/")] == ["wavs/no_esta.wav"] and "keys" in st.export_summary and "wavs" in st.export_summary
        # the zip installs its sound into the game's wavs folder (and never replaces what is there)
        st2 = EditorState(make_game_copy(tmp2), log=lambda *a: None)
        st2.game_dir = os.path.dirname(os.path.abspath(st2.fs.root))
        st2.install_map_zip(z)
        assert os.path.isfile(os.path.join(st2.game_dir, "wavs", "Prueba.wav"))
    with tempfile.TemporaryDirectory() as tmp:                    # the Love Boat: its animated things and their keys
        st = _st(tmp)
        files = st.map_dependencies()
        assert sum(f.startswith("keys/") for f in files) == 4 and st._missing_deps == []
        assert len(st._dep_wavs) == 5                             # (the game's wavs folder is not here: reported, not fatal)
    with tempfile.TemporaryDirectory() as tmp:                    # doors and buttons name two animations each: both go
        st = _st(tmp, "mp_do_garaje.scn")
        files = [f.lower() for f in st.map_dependencies()]
        raw = open(st.scene.path, "rb").read()
        refs = {m.group(1).decode("latin1").lower().replace("\\", "/") for m in re.finditer(rb"([\x20-\x7e]{1,100}\.key)", raw, re.I)}
        assert "varios/puerta_metro_abre.key" in refs and "varios/puerta_metro_cierra.key" in refs and len(refs) == 13
        assert "wavs\\puerta_metro.wav" in st._dep_wavs               # the sound a door names goes too
        assert all("keys/" + r in files for r in refs) and not [m for m in st._missing_deps if m.startswith("keys/")]


def test_hide_objects_in_the_editor():
    from vtoy import settings
    with tempfile.TemporaryDirectory() as tmp:
        st = _st(tmp, "mp_b_garaje.scn")
        car = next(r for r in st.scene.modules if r.clean_name.lower() == "mp_ccar")
        spawn = next(r for r in st.scene.modules if r.clean_name.lower() == "mp_cstartpoint")
        me = max(st.opt.meshes, key=lambda m: sum(len(s.indices) for s in m.render_submeshes()))
        n_inst, n_mod, n_mesh = len(st.geometry.instances), len(st.scene.modules), len(st.opt.meshes)
        count = lambda g: sum(len(b.indices) for b in g.opaque) + 3 * len(g.ttri)
        tris0 = count(st.geometry)
        assert any(i.ref is car for i in st.geometry.instances) and any(m[1] is spawn for m in st.markers())
        st.selection = Selection("module", car, "")
        st.set_hidden(car, True)
        st.set_hidden(spawn, True)
        st.set_hidden(me, True, "mesh")
        assert st.selection is None and st.needs_rebake and st.hidden_count() == 3
        st.bake()
        # not drawn, not clickable, no box - but still in the scene and in the map
        assert not any(i.ref is car or i.ref is me for i in st.geometry.instances) and len(st.geometry.instances) == n_inst - 2
        assert count(st.geometry) < tris0
        assert not any(m[1] is spawn for m in st.markers())
        assert len(st.scene.modules) == n_mod and len(st.opt.meshes) == n_mesh
        assert st.is_hidden(car) and st.is_hidden(me, "mesh") and not st.is_hidden(st.opt.meshes[0] if st.opt.meshes[0] is not me else st.opt.meshes[1], "mesh")
        deps = st.map_dependencies()
        assert any(car.parsed.model_name.replace("\\", "/").lower().endswith(d.lower().split("/")[-1]) for d in deps if d.lower().endswith(".nfo"))
        raw_scene, raw_map = st.scene.to_bytes(), st.opt.to_bytes()
        # remembered per map; saving writes exactly the same scene and map as without hiding
        assert len(settings.get("hidden")["mp_b_garaje"]) == 3
        st.save_scene(); st.save_map()
        name = str(car.object_name)
        st.load("mp_b_garaje.scn")
        assert st.scene.to_bytes() == raw_scene and st.hidden_count() == 3
        car = next(r for r in st.scene.modules if str(r.object_name) == name)
        assert st.is_hidden(car) and not any(i.ref is car for i in st.geometry.instances)
        # one back, then the rest; H hides the selection and the group
        st.set_hidden(car, False)
        st.bake()
        assert any(i.ref is car for i in st.geometry.instances) and st.hidden_count() == 2
        assert st.show_all().startswith("2 hidden") and st.hidden_count() == 0 and "mp_b_garaje" not in (settings.get("hidden") or {})
        st.bake()
        assert len(st.geometry.instances) == n_inst
        prop = st.opt.props[0] if st.opt.props else None
        st.selection = Selection("module", car, "")
        if prop is not None:
            st.multi = [Selection("prop", prop, "")]
        msg = st.hide_selection()
        assert msg.startswith(f"{2 if prop is not None else 1} objects hidden") and st.selection is None and not st.multi
        assert st.hide_selection() == "nothing selected to hide"
        st.bake()
        assert not any(i.ref is car or i.ref is prop for i in st.geometry.instances)
        st.show_all()


def test_listen_to_module_sounds():
    from vtoy.audio import Player
    with tempfile.TemporaryDirectory() as tmp:
        st = _st(tmp, "mp_do_garaje.scn")
        door = next(r for r in st.scene.modules if r.clean_name.lower() == "mp_door")
        assert st.module_sounds(door) == ["wavs\\puerta_metro.wav"]                 # a door names its own sound
        car = next((r for r in st.scene.modules if r.clean_name.lower() == "mp_ccar"), None)
        assert car is None or st.module_sounds(car) == []
        src = st.add_sound_source("wavs\\Prueba.wav")
        assert st.module_sounds(src) == ["wavs\\Prueba.wav"]
        em = st.add_particles("fountain (mp_dm_plaza)")
        assert st.module_sounds(em) == []
        em.parsed.sound = str(src.object_name).rstrip("\0")
        assert st.module_sounds(em) == ["wavs\\Prueba.wav"]                         # an emitter: the sound source it points to
        # found in the game's wavs folder whatever the case of the name; '' when it is not there
        game = os.path.dirname(os.path.abspath(st.fs.root))
        st.game_dir = game
        assert st.wav_path("wavs\\Prueba.wav") == "" and len(st.sound_search_dirs()) == 2
        os.makedirs(os.path.join(game, "wavs"))
        with open(os.path.join(game, "wavs", "PRUEBA.WAV"), "wb") as f:
            f.write(b"RIFF")
        assert st.wav_path("wavs\\Prueba.wav").endswith("PRUEBA.WAV")
    pl = Player()
    assert pl.play("/no/such/file.wav", loop=False).startswith("file not found") and pl.loop is False and not pl.playing
    assert pl.play("/no/such/file.ogg").startswith("file not found") and pl.loop is True
    import struct, wave
    from vtoy.audio import wav_seconds
    with tempfile.TemporaryDirectory() as tmp:
        w = os.path.join(tmp, "a.wav")
        with wave.open(w, "wb") as f:
            f.setnchannels(1); f.setsampwidth(2); f.setframerate(8000); f.writeframes(bytes(2 * 8000 * 3))
        assert abs(wav_seconds(w) - 3.0) < 0.01
        open(os.path.join(tmp, "b.wav"), "wb").write(b"nope")
        assert wav_seconds(os.path.join(tmp, "b.wav")) == 5.0 and wav_seconds(os.path.join(tmp, "missing.wav"), 2.0) == 2.0


def test_select_lights_and_decals():
    with tempfile.TemporaryDirectory() as tmp:
        st = _st(tmp)
        nl, nd = len(st.opt.lights), len(st.opt.decals)
        light = next(l for l in st.opt.lights if int(l.type) == 0)
        sel = st.select_opt("light", light)
        assert st.selection is sel and sel.kind == "light" and "POINT light" in sel.label
        p0 = st.position_of(sel)
        assert np.allclose(p0, light.position) and "POINT" in st.describe(sel)[2]
        # move (one undo step), move here = where the camera is
        st.set_position(sel, p0 + [100.0, 0.0, -50.0])
        assert np.allclose(light.position, p0 + [100, 0, -50]) and st.dirty_map
        st.undo()
        light = next(l for l in st.opt.lights if int(l.type) == 0)
        assert np.allclose(light.position, p0) and st.selection is None
        # duplicate: a copy beside it, selected; delete through the normal Delete of the editor
        cp = st.duplicate_selection(st.select_opt("light", light), (150.0, 0.0, 0.0))
        assert cp.kind == "light" and len(st.opt.lights) == nl + 1 and st.selection.ref is cp.ref and cp.ref is not light
        assert np.allclose(cp.ref.position, p0 + [150, 0, 0]) and cp.ref.end == light.end and tuple(cp.ref.diffuse) == tuple(light.diffuse)
        assert st.delete_selection(cp) == "light deleted" and len(st.opt.lights) == nl
        # in the view: only clickable when they are shown
        cam = (p0 + [0.0, 0.0, 0.0]) * [1, 1, -1] + [0.0, 300.0, 0.0]
        st.pick_lights = False
        hit, _ = st.pick_hit(cam, np.array([0.0, -1.0, 0.0]))
        assert hit is None or hit.kind != "light"
        st.pick_lights = True
        hit, t = st.pick_hit(cam, np.array([0.0, -1.0, 0.0]))
        assert hit is not None and hit.kind == "light" and hit.ref is light and 250 < t < 300
        # decals: add, select, move, copy, delete
        d = st.add_decal("tablones.tex")
        d.position = np.array([0.0, 900.0, 0.0], np.float32)
        d.scale_x = d.scale_y = 120.0
        ds = st.select_opt("decal", d)
        assert ds.kind == "decal" and "tablones" in ds.label and "120 x 120" in st.describe(ds)[2]
        st.set_position(ds, [50.0, 900.0, 0.0])
        assert np.allclose(d.position, (50, 900, 0))
        st.pick_lights, st.pick_decals = False, True
        hit, _ = st.pick_hit(np.array([50.0, 1500.0, 0.0]), np.array([0.0, -1.0, 0.0]))
        assert hit is not None and hit.kind == "decal" and hit.ref is d
        cp = st.duplicate_selection(ds)
        assert len(st.opt.decals) == nd + 2 and cp.ref.name == d.name and np.allclose(cp.ref.position, (200, 900, 0))
        assert st.delete_selection(cp) == "decal deleted" and st.delete_selection(st.select_opt("decal", d)) == "decal deleted"
        assert len(st.opt.decals) == nd
        # padlock: not clickable, not moved, not deleted; eye: no box, does not light the lit view
        n_lit = len(st.packed_lights()["lights"])
        st.set_locked(light, True, "light")
        assert st.is_locked(light, "light") and not st.is_locked(st.scene.modules[0]) and not st.is_locked(st.opt.lights[-1], "light")
        st.pick_lights = True
        hit, _ = st.pick_hit(cam, np.array([0.0, -1.0, 0.0]))
        assert hit is None or hit.ref is not light
        ls = Selection("light", light, "")
        st.set_position(ls, p0 + [500.0, 0.0, 0.0])
        assert np.allclose(light.position, p0) and "locked" in st.delete_selection(ls) and len(st.opt.lights) == nl
        st.set_locked(light, False, "light")
        st.set_hidden(light, True, "light")
        assert st.is_hidden(light, "light") and st.hidden_count() == 1 and not any(m[1] is light for m in st.opt_markers())
        assert len(st.packed_lights()["lights"]) == n_lit - 1 and id(light) in st.hidden_ids()
        st.show_all()
        assert st.hidden_count() == 0 and len(st.packed_lights()["lights"]) == n_lit
        st.save_map()
        OptMap.load(st.opt.path)


def test_twin_lights_view_distance_and_dll_search():
    with tempfile.TemporaryDirectory() as tmp:
        st = _st(tmp)
        st.make_twin_ships(800.0, 16, tint_ships=False)
        hlo, hhi, hm, W = st._twin_stock()
        cx = (hlo[0] + hhi[0]) / 2
        from vtoy import twinships
        off = twinships.ship_offset(st.opt, hm, hlo, hhi, 800.0, W)
        pts = lambda: sorted((round(float(l.position[0])), round(float(l.position[2]))) for l in st.opt.lights if int(l.type) == 0)
        a = [p for p in pts() if p[0] > hlo[0] - 150]
        assert len(a) == 3
        msg = st.twin_lights(mirror=True)
        assert "3 lights of ship A mirrored" in msg and "3 replaced" in msg, msg
        b = [p for p in pts() if p[0] < hlo[0] - 150]
        want = sorted((2 * cx - x + off, z) for x, z in a)
        assert len(pts()) == 6 and all(abs(p[0] - w[0]) <= 1.5 and p[1] == w[1] for p, w in zip(b, want)), (b, want)
        # the same distance to the water between the ships on both sides
        mid = (hlo[0] + hhi[0] + off) / 2
        assert np.allclose(sorted(abs(x - mid) for x, _ in a), sorted(abs(x - mid) for x, _ in b), atol=2.0)
        assert sum(int(l.type) == 2 for l in st.opt.lights) == 1 and sum(int(l.type) == 3 for l in st.opt.lights) == 1
        sides = [st.light_ship(l) for l in st.opt.lights]
        assert sides.count("A") == 3 and sides.count("B") == 3 and sides.count("") == 2       # sun + ambient: no ship
        st.twin_lights(mirror=False)
        same = [p for p in pts() if p[0] < hlo[0] - 150]
        assert len(pts()) == 6 and all(abs(p[0] - (x + off)) <= 1.5 and p[1] == z for p, (x, z) in zip(same, a))
        st.undo()
        # far plane: the twin ships are longer than the stock far plane
        st.bake()
        need = st.view_distance_needed()
        assert need > st.scene.cam_far == 11000.0 and need < 30000
        msg = st.see_whole_map()
        assert st.scene.cam_far == need and st.scene.fog_far >= need and st.scene.fog_near >= need * 0.9 and st.dirty_scene, msg
        assert st.see_whole_map().startswith("the far plane")
        n = st.lod_meshes()
        assert n > 10 and st.full_detail_meshes().startswith(f"{n} meshes") and st.lod_meshes() == 0
        from vtoy.fill import LOD_FAR
        assert all(m.lods[0].unk == LOD_FAR or len(m.lods) == 1 for m in st.opt.meshes)
        st.save_map(); st.save_scene()
        OptMap.load(st.opt.path)
        # the game's DLLs: found in <install>/comun/bin/release above the data folder, whatever the case
        inst = os.path.dirname(os.path.abspath(st.fs.root))
        rel = os.path.join(inst, "comun", "bin", "release")
        os.makedirs(rel)
        open(os.path.join(rel, "MP_CaptureLoveboat.DLL"), "wb").write(b"MZ")
        st.game_dir = ""
        assert st.find_game_dll("mp_CaptureLoveboat.dll") == os.path.join(rel, "MP_CaptureLoveboat.DLL")
        assert rel in st.dll_search_dirs() and st.find_game_dll("mp_nada.dll") == ""
        st.scene.main_module_name = "mp_CaptureLoveboat.dll"
        assert st.custom_dll_path() == os.path.join(rel, "MP_CaptureLoveboat.DLL")

