"""Plays a .KEY on a model (pure numpy, no GL).

Conventions (checked against the shipped files: with frame 0 the result equals the bind pose of the NFO nodes for gramofono,
grua_*, plaza_boton*, porton_*, rotor_industrial, vagones ...):
  * a key pose is ``quaternion (w, x, y, z)`` + position, and it is the INVERSE of the node's matrix relative to its parent;
  * the node matrices of the NFO (row-vector convention) are absolute bind poses; mesh vertices are stored in model space,
    so a vertex of a mesh attached to node ``n`` moves with ``inverse(bind[n]) @ world[n](frame)``.
Skinned meshes (bones) are drawn rigidly with the matrix of the node they hang from."""
from __future__ import annotations

from typing import Dict

import numpy as np

KEY_FPS = 30.0


def _quat_matrix(q) -> np.ndarray:
    w, x, y, z = (float(v) for v in q)
    n = (w * w + x * x + y * y + z * z) ** 0.5 or 1.0
    w, x, y, z = w / n, x / n, y / n, z / n
    r = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y + z * w), 2 * (x * z - y * w)],
                  [2 * (x * y - z * w), 1 - 2 * (x * x + z * z), 2 * (y * z + x * w)],
                  [2 * (x * z + y * w), 2 * (y * z - x * w), 1 - 2 * (x * x + y * y)]])
    return r.T


def local_matrix(key, node: int, frame: float) -> np.ndarray:
    """Matrix of key node ``node`` relative to its parent at a (fractional, looping) frame."""
    n = key.frames
    f0 = int(np.floor(frame)) % n
    f1 = (f0 + 1) % n
    a = float(frame - np.floor(frame))
    q0 = key.poses["rot"][f0, node].astype(np.float64)
    q1 = key.poses["rot"][f1, node].astype(np.float64)
    if np.dot(q0, q1) < 0:
        q1 = -q1
    q = q0 * (1 - a) + q1 * a
    p = key.poses["pos"][f0, node].astype(np.float64) * (1 - a) + key.poses["pos"][f1, node].astype(np.float64) * a
    m = np.eye(4)
    m[:3, :3] = _quat_matrix(q)
    m[3, :3] = p
    try:
        return np.linalg.inv(m)
    except np.linalg.LinAlgError:
        return np.eye(4)


def node_worlds(obj, key, frame: float) -> Dict[int, np.ndarray]:
    """World matrix of every node of an NfoObject at ``frame``; nodes the key does not name keep their bind pose."""
    idx = {nd.name.lower(): i for i, nd in enumerate(obj.nodes)}
    key_of = {idx[nm.lower()]: k for k, nm in enumerate(key.node_names) if nm.lower() in idx}
    bind = [np.asarray(nd.matrix, np.float64) for nd in obj.nodes]
    worlds: Dict[int, np.ndarray] = {}

    def world(i: int) -> np.ndarray:
        if i in worlds:
            return worlds[i]
        par = obj.nodes[i].parent
        if i in key_of:
            loc = local_matrix(key, key_of[i], frame)
        else:                                                         # not animated: its bind pose relative to the parent
            loc = bind[i] if par < 0 else bind[i] @ np.linalg.inv(bind[par])
        w = loc if par < 0 or par == i else loc @ world(par)
        worlds[i] = w
        return w
    for i in range(len(obj.nodes)):
        world(i)
    return worlds


def mesh_matrices(obj, key, frame: float) -> Dict[int, np.ndarray]:
    """node index -> matrix to apply to the (model space) vertices of the meshes attached to that node."""
    worlds = node_worlds(obj, key, frame)
    out = {}
    for i, w in worlds.items():
        try:
            out[i] = np.linalg.inv(np.asarray(obj.nodes[i].matrix, np.float64)) @ w
        except np.linalg.LinAlgError:
            out[i] = np.eye(4)
    return out
