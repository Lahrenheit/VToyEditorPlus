"""The collision of an object goes with it: the collision boxes of the map and the floor / wall faces of the height map that
lie inside the object's bounds are moved, turned, scaled, copied or deleted together with the drawing.

    collect(opt, hm, lo, hi)                      -> (box indices, faces): what lies completely inside lo..hi (engine)
    apply(opt, hm, boxes, faces, A, copy=False)   transform them with the 4x4 row-vector matrix A (copy: add new ones)
    remove(opt, hm, boxes, faces)                 delete them
    affine_move(off) / affine_about(M3, centre)   the matrices for a move / a turn or scale about a point
"""
from __future__ import annotations

from typing import List, Sequence, Tuple

import numpy as np

from . import crop, hmcopy, regioncopy
from .hm import HMFace


def affine_move(off) -> np.ndarray:
    A = np.eye(4)
    A[3, :3] = np.asarray(off, np.float64)
    return A


def affine_about(M3, centre) -> np.ndarray:
    """p -> (p - centre) @ M3 + centre."""
    c = np.asarray(centre, np.float64)
    A = np.eye(4)
    A[:3, :3] = np.asarray(M3, np.float64)
    A[3, :3] = c - c @ A[:3, :3]
    return A


def collect(opt, hm, lo, hi, pad: float = 3.0) -> Tuple[List[int], List[HMFace]]:
    lo = np.asarray(lo, np.float64) - pad
    hi = np.asarray(hi, np.float64) + pad
    boxes = []
    if opt is not None and not opt.old_format:
        for i, raw in enumerate(crop.read_block(opt).boxes):
            a, b = regioncopy._box_bounds(raw)
            if np.all(a >= lo) and np.all(b <= hi):
                boxes.append(i)
    faces = []
    if hm is not None:
        for f in hmcopy.unique_faces(hm):
            p = np.concatenate(f.contours).astype(np.float64)
            if len(p) and np.all(p.min(0) >= lo) and np.all(p.max(0) <= hi):
                faces.append(f)
    return boxes, faces


def _face(f: HMFace, A: np.ndarray) -> HMFace:
    A3, t = A[:3, :3], A[3, :3]
    cs = [(np.asarray(c, np.float64) @ A3 + t) for c in f.contours]
    n = np.asarray(f.normal, np.float64) @ np.linalg.inv(A3).T
    ln = float(np.linalg.norm(n))
    n = n / ln if ln > 1e-12 else np.asarray(f.normal, np.float64)
    if np.linalg.det(A3) < 0:                                 # a mirror turns the winding round
        cs = [c[::-1] for c in cs]
    p0 = cs[0][0] if cs and len(cs[0]) else np.zeros(3)
    return HMFace(tuple(float(v) for v in n), float(-(n @ p0)), [c.astype(np.float32) for c in cs])


def _box(raw: bytes, A: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    a = np.frombuffer(raw, "<f4", 19).astype(np.float64)
    c, h = a[12:15], np.abs(a[16:19])
    R = a[:16].reshape(4, 4)[:3, :3]
    R2 = R @ A[:3, :3]
    s = np.linalg.norm(R2, axis=1)
    s[s < 1e-9] = 1.0
    return c @ A[:3, :3] + A[3, :3], h * s, R2 / s[:, None]


def apply(opt, hm, boxes: Sequence[int], faces: Sequence[HMFace], A, copy: bool = False) -> Tuple[int, int]:
    """Transform (or, with ``copy``, add transformed copies of) the boxes and faces.  Returns (boxes, faces) done."""
    A = np.asarray(A, np.float64)
    nb = 0
    if boxes and opt is not None:
        blk = crop.read_block(opt)
        new = []
        for i in boxes:
            if 0 <= i < len(blk.boxes):
                new.append((i, _box(blk.boxes[i], A)))
        if copy:
            for _i, (c, h, R) in new:
                regioncopy.add_box(opt, c, np.maximum(h, 0.5), R)
                nb += 1
        else:
            for i, (c, h, R) in new:
                blk.boxes[i] = regioncopy.make_box(c, np.maximum(h, 0.5), R)
                na, nb_ = regioncopy._box_bounds(blk.boxes[i])
                for s in regioncopy._sectors_for(blk, na, nb_):
                    if i not in s.boxes:
                        s.boxes.append(i)
                nb += 1
            crop.write_block(opt, blk)
    nf = 0
    if faces and hm is not None:
        moved = [_face(f, A) for f in faces]
        if not copy:
            ids = {id(f) for f in faces}
            keep = [f for f in hmcopy.unique_faces(hm) if id(f) not in ids]
            hm.root = hmcopy.build_tree(keep, hmcopy.box(hm.root), max(hmcopy.tree_depth(hm.root), 1))
        hmcopy.add_faces(hm, moved)
        nf = len(moved)
    return nb, nf


def remove(opt, hm, boxes: Sequence[int], faces: Sequence[HMFace]) -> Tuple[int, int]:
    nb = 0
    if boxes and opt is not None:
        crop.remove_collision_indices(opt, sorted(set(boxes)))
        nb = len(set(boxes))
    nf = 0
    if faces and hm is not None:
        ids = {id(f) for f in faces}
        keep = [f for f in hmcopy.unique_faces(hm) if id(f) not in ids]
        nf = len(faces)
        hm.root = hmcopy.build_tree(keep, hmcopy.box(hm.root), max(hmcopy.tree_depth(hm.root), 1))
    return nb, nf
