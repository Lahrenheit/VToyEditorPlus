"""CPU preview renderer (numpy + Pillow): quick sanity images of models and maps, no GPU needed.

  python3 tools/preview.py nfo  <game_root> <model.nfo> out.png [yaw_deg] [pitch_deg]
  python3 tools/preview.py map  <game_root> <scene.scn> out.png [top|spawn]
"""
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import numpy as np
from PIL import Image, ImageDraw

from vtoy.gamefs import GameFS

ROOT_Z = np.diag([1, 1, -1, 1]).astype(np.float32)      # the engine is left-handed; flip Z to view it in a right-handed space


def avg_color(fs, tex_name, fallback=(170, 170, 170)):
    t = fs.texture(tex_name) if tex_name else None
    if t is None:
        return np.array(fallback, np.float32)
    img = t.decode(min(2, max(0, t.mip_count - 1)) if t.has_mips else 0)
    a = img[:, :, 3] > 40
    return img[:, :, :3][a].mean(0) if a.any() else np.array(fallback, np.float32)


def look_at(eye, target, up=(0, 1, 0)):
    f = np.asarray(target, float) - eye
    f /= np.linalg.norm(f)
    s = np.cross(f, up); s /= np.linalg.norm(s)
    u = np.cross(s, f)
    return np.array([s, u, -f]), np.asarray(eye, float)


def render(tris, cols, eye, target, size=(1100, 700), fov=60, ortho=None, sun=(0.4, 0.8, 0.5)):
    """tris: (n,3,3) world; cols: (n,3) 0-255. Painter's algorithm, flat shading."""
    W, H = size
    R, e = look_at(np.asarray(eye, float), target, (0, 1, 0) if ortho is None else (0, 0, -1))
    cam = (tris.reshape(-1, 3) - e) @ R.T
    cam = cam.reshape(-1, 3, 3)
    n = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    ln = np.linalg.norm(n, axis=1, keepdims=True); n = n / np.maximum(ln, 1e-9)
    sun = np.asarray(sun, float); sun /= np.linalg.norm(sun)
    shade = 0.45 + 0.55 * np.abs(n @ sun)
    if ortho is None:
        z = -cam[:, :, 2]
        ok = (z > 5).all(1)
        f = (H / 2) / math.tan(math.radians(fov) / 2)
        sx = cam[:, :, 0] / np.maximum(z, 1e-3) * f + W / 2
        sy = -cam[:, :, 1] / np.maximum(z, 1e-3) * f + H / 2
        depth = z.mean(1)
    else:
        ok = np.ones(len(tris), bool)
        sx = cam[:, :, 0] / ortho * (H / 2) + W / 2
        sy = -cam[:, :, 1] / ortho * (H / 2) + H / 2
        depth = -cam[:, :, 2].mean(1)
    vis = ok & (sx.max(1) > 0) & (sx.min(1) < W) & (sy.max(1) > 0) & (sy.min(1) < H)
    idx = np.nonzero(vis)[0]
    idx = idx[np.argsort(-depth[idx])]
    img = Image.new("RGB", (W, H), (60, 75, 95))
    d = ImageDraw.Draw(img)
    for i in idx:
        c = tuple(int(x) for x in np.clip(cols[i] * shade[i], 0, 255))
        d.polygon([(sx[i, 0], sy[i, 0]), (sx[i, 1], sy[i, 1]), (sx[i, 2], sy[i, 2])], fill=c)
    return img, len(idx)


def model_triangles(fs, model, matrix=None):
    tris, cols = [], []
    for obj, me in model.lod0_meshes():
        for mi, v, ind, _ in me.build():
            mat = obj.materials[mi] if mi < len(obj.materials) else None
            col = avg_color(fs, mat.texture if mat else None)
            p = v[:, :3] @ ((np.eye(4) if matrix is None else matrix)[:3, :3]) + (0 if matrix is None else matrix[3, :3])
            t = p[ind.reshape(-1, 3)]
            tris.append(t); cols.append(np.tile(col, (len(t), 1)))
    return np.concatenate(tris), np.concatenate(cols)


def main():
    kind, root, target, out = sys.argv[1:5]
    fs = GameFS(root)
    if kind == "nfo":
        yaw = float(sys.argv[5]) if len(sys.argv) > 5 else 35
        pitch = float(sys.argv[6]) if len(sys.argv) > 6 else 20
        m = fs.model(target)
        tris, cols = model_triangles(fs, m)
        tris = tris @ ROOT_Z[:3, :3]
        c = (tris.reshape(-1, 3).min(0) + tris.reshape(-1, 3).max(0)) / 2
        r = np.linalg.norm(tris.reshape(-1, 3).max(0) - tris.reshape(-1, 3).min(0)) * 0.9
        eye = c + r * np.array([math.sin(math.radians(yaw)) * math.cos(math.radians(pitch)), math.sin(math.radians(pitch)), math.cos(math.radians(yaw)) * math.cos(math.radians(pitch))])
        img, n = render(tris, cols, eye, c)
        img.save(out); print("triangles drawn", n, "of", len(tris))
        return
    mode = sys.argv[5] if len(sys.argv) > 5 else "top"
    scn = fs.scene(target)
    opt = fs.map(scn.map_name)
    colcache, allt, allc = {}, [], []

    def mesh_tris(mesh, matrix):
        for sm in mesh.render_submeshes():
            if len(sm.indices) == 0:
                continue
            mat = mesh.materials[sm.material_index] if sm.material_index < len(mesh.materials) else None
            key = mat.diffuse if mat else ""
            if key not in colcache:
                colcache[key] = avg_color(fs, key)
            p = sm.vertices["pos"].astype(np.float64) @ matrix[:3, :3] + matrix[3, :3]
            t = p[sm.indices.reshape(-1, 3)]
            allt.append(t); allc.append(np.tile(colcache[key], (len(t), 1)))

    for me in opt.meshes:
        mesh_tris(me, np.eye(4))
    for pr in opt.props:
        me = opt.meshes[pr.mesh_index]
        M = np.linalg.inv(me.world_transform.astype(np.float64)) @ pr.transform.astype(np.float64)
        mesh_tris(me, M)
    for rec in scn.modules:
        p = rec.parsed
        if p is not None and hasattr(p, "model_name") and rec.clean_name.lower() in ("rendernfo", "animatedrendernfo", "mp_ccar", "cglass", "mp_door", "mp_cosa"):
            mdl = fs.model(p.model_name)
            if mdl is not None:
                t, c = model_triangles(fs, mdl, p.transform.astype(np.float64))
                allt.append(t); allc.append(c)
    tris = np.concatenate(allt) @ ROOT_Z[:3, :3]
    cols = np.concatenate(allc)
    print("triangles", len(tris))
    pts = tris.reshape(-1, 3)
    lo, hi = np.percentile(pts, 2, axis=0), np.percentile(pts, 98, axis=0)
    c = (lo + hi) / 2
    if mode == "top":
        ext = max(hi[0] - lo[0], hi[2] - lo[2]) / 2
        img, n = render(tris, cols, c + np.array([0, 20000, 0]), c, ortho=ext * 1.05, size=(1100, 1100))
    else:
        sp = [r.parsed for r in scn.modules if r.parsed is not None and r.clean_name.lower() == "mp_cstartpoint"]
        s = sp[0]
        pos = np.array(s.position) * [1, 1, -1] + [0, 170, 0]
        ang = s.angle
        eye = pos
        tgt = pos + np.array([math.sin(ang), -0.05, -math.cos(ang)]) * 1000
        img, n = render(tris, cols, eye, tgt, fov=75)
    img.save(out); print("triangles drawn", n)


if __name__ == "__main__":
    main()
