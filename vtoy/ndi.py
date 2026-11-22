"""The few image operations the importer needs on boolean / height grids, in plain numpy (no scipy needed):
connected pieces (label, find_objects), growing a mask (binary_dilation), closing a height grid (grey_closing) and
"is this piece narrow everywhere" (narrow).  Connectivity is by faces (4 neighbours in 2D, 6 in 3D), like scipy's
default."""
from __future__ import annotations

from typing import List, Tuple

import numpy as np


def _runs(mask: np.ndarray):
    """Runs of True along the last axis: (row number in the flattened leading axes, start, end) - end excluded."""
    L = mask.shape[-1]
    m = mask.reshape(-1, L)
    pad = np.zeros((m.shape[0], L + 2), np.int8)
    pad[:, 1:-1] = m
    d = np.diff(pad, axis=1)
    r0, s = np.nonzero(d == 1)
    r1, e = np.nonzero(d == -1)
    # np.nonzero is row-major: both lists are in the same order (row, then position)
    return r0.astype(np.int64), s.astype(np.int64), e.astype(np.int64)


def label(mask: np.ndarray) -> Tuple[np.ndarray, int]:
    """Number the connected pieces of ``mask`` 1..n (0 = background).  -> (labels int32, n)."""
    mask = np.asarray(mask, bool)
    shape = mask.shape
    if mask.size == 0 or not mask.any():
        return np.zeros(shape, np.int32), 0
    L = shape[-1]
    lead = shape[:-1] if len(shape) > 1 else ()
    row, s, e = _runs(mask if len(shape) > 1 else mask[None, :])
    n = len(row)
    parent = np.arange(n, dtype=np.int64)
    W = L + 1
    keyS = row * W + s
    keyE = row * W + e
    a_list, b_list = [], []
    strides = []
    acc = 1
    for k in range(len(lead) - 1, -1, -1):
        strides.append((k, acc))
        acc *= lead[k]
    if lead:
        coords = np.array(np.unravel_index(row, lead))
    for k, step in strides:                                  # the next row along each leading axis
        ok = coords[k] + 1 < lead[k]
        idx = np.nonzero(ok)[0]
        if not len(idx):
            continue
        t = row[idx] + step
        lo = np.searchsorted(keyE, t * W + s[idx], side="right")
        hi = np.searchsorted(keyS, t * W + e[idx], side="left")
        cnt = np.maximum(hi - lo, 0)
        if not cnt.sum():
            continue
        a = np.repeat(idx, cnt)
        off = np.arange(int(cnt.sum())) - np.repeat(np.cumsum(cnt) - cnt, cnt)
        b = np.repeat(lo, cnt) + off
        a_list.append(a)
        b_list.append(b)
    if a_list:
        A = np.concatenate(a_list)
        B = np.concatenate(b_list)
        while True:                                          # min-label propagation with pointer jumping
            pa, pb = parent[A], parent[B]
            m = np.minimum(pa, pb)
            changed = np.any(pa != pb)
            np.minimum.at(parent, pa, m)
            np.minimum.at(parent, pb, m)
            while True:
                nxt = parent[parent]
                if np.array_equal(nxt, parent):
                    break
                parent = nxt
            if not changed:
                break
    roots, comp = np.unique(parent, return_inverse=True)
    comp = (comp + 1).astype(np.int32)
    out = np.zeros((int(np.prod(lead)) if lead else 1, L + 1), np.int32)
    np.add.at(out, (row, s), comp)
    np.add.at(out, (row, e), -comp)
    out = np.cumsum(out, axis=1)[:, :L].astype(np.int32)
    return out.reshape(shape), len(roots)


def find_objects(lab: np.ndarray, n: int) -> List[tuple]:
    """For each label 1..n, the tuple of slices of its bounding box (None for a label with no cells)."""
    out: List[tuple] = [None] * n
    if n == 0:
        return out
    idx = np.nonzero(lab)
    v = lab[idx]
    lo = [np.full(n + 1, np.iinfo(np.int64).max, np.int64) for _ in idx]
    hi = [np.full(n + 1, -1, np.int64) for _ in idx]
    for d, c in enumerate(idx):
        np.minimum.at(lo[d], v, c)
        np.maximum.at(hi[d], v, c)
    for k in range(1, n + 1):
        if hi[0][k] >= 0:
            out[k - 1] = tuple(slice(int(lo[d][k]), int(hi[d][k]) + 1) for d in range(len(idx)))
    return out


def _shift_or(m: np.ndarray, full: bool) -> np.ndarray:
    o = m.copy()
    nd = m.ndim
    for ax in range(nd):
        sl_a = [slice(None)] * nd
        sl_b = [slice(None)] * nd
        sl_a[ax], sl_b[ax] = slice(1, None), slice(None, -1)
        o[tuple(sl_a)] |= m[tuple(sl_b)]
        o[tuple(sl_b)] |= m[tuple(sl_a)]
    if full and nd == 2:                                     # the 4 diagonals too (a 3 x 3 square)
        o[1:, 1:] |= m[:-1, :-1]
        o[:-1, :-1] |= m[1:, 1:]
        o[1:, :-1] |= m[:-1, 1:]
        o[:-1, 1:] |= m[1:, :-1]
    return o


def binary_dilation(m: np.ndarray, full: bool = False, iterations: int = 1) -> np.ndarray:
    """``m`` grown by one cell ``iterations`` times: by faces (a cross) or, ``full``, by a 3 x 3 square (2D)."""
    o = np.asarray(m, bool)
    for _ in range(max(1, iterations)):
        o = _shift_or(o, full)
    return o


def _slide(a: np.ndarray, k: int, axis: int, op, fill) -> np.ndarray:
    """max / min over a window of k cells centred on each cell along ``axis`` (outside: ``fill``)."""
    if k <= 1:
        return a
    before = k // 2
    after = k - 1 - before
    pad = [(0, 0)] * a.ndim
    pad[axis] = (before, after)
    p = np.pad(a, pad, constant_values=fill)
    n = a.shape[axis]
    m = p
    w = 1
    while 2 * w <= k:                                        # windows of 1, 2, 4 ... cells
        sl_a = [slice(None)] * a.ndim
        sl_b = [slice(None)] * a.ndim
        sl_a[axis] = slice(0, m.shape[axis] - w)
        sl_b[axis] = slice(w, None)
        m = op(m[tuple(sl_a)], m[tuple(sl_b)])
        w *= 2
    sl_a = [slice(None)] * a.ndim
    sl_b = [slice(None)] * a.ndim
    sl_a[axis] = slice(0, n)
    sl_b[axis] = slice(k - w, k - w + n)
    return op(m[tuple(sl_a)], m[tuple(sl_b)])


def grey_closing(a: np.ndarray, size: int) -> np.ndarray:
    """Grey closing of a 2D grid with a ``size`` x ``size`` square: the max over the square, then the min."""
    lo = np.finfo(a.dtype).min if a.dtype.kind == "f" else np.iinfo(a.dtype).min
    hi = np.finfo(a.dtype).max if a.dtype.kind == "f" else np.iinfo(a.dtype).max
    d = _slide(_slide(a, size, 0, np.maximum, lo), size, 1, np.maximum, lo)
    return _slide(_slide(d, size, 0, np.minimum, hi), size, 1, np.minimum, hi)


def narrow(m: np.ndarray, radius: float) -> bool:
    """Is no cell of the 2D mask ``m`` farther than ``radius`` cells from its outside?  (Eroded alternately by a cross
    and a square - an octagon, close to a disc - ``ceil(radius)`` times: nothing left = narrow.)"""
    e = np.pad(np.asarray(m, bool), 1)
    for i in range(int(np.ceil(radius))):
        inv = ~e
        e = ~_shift_or(inv, full=(i % 2 == 1))
        e[0, :] = e[-1, :] = False
        e[:, 0] = e[:, -1] = False
        if not e.any():
            return True
    return not e.any()
