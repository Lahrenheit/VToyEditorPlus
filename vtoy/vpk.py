"""vtPack archives (.vpk): unpack to a folder, repack a folder.

Header (34 bytes): 'vtPack' | u32 major(1) | u32 minor(0) | u32 patch | u32 unknown | u32 header size | u32 entry count | u32 table offset
Entry table (at table offset): per entry
    u32 name size, name (NUL terminated) | u32 dir size, dir path ('a\\b\\', NUL terminated) | u32 parent index (0xFFFFFFFF = root)
    | u32 size | u32 compressed size | u32 data offset | u32 unix timestamp | u32 type (1 = directory, 2 = file)
Files are stored uncompressed (compressed size == size in every archive we know of).
"""
from __future__ import annotations

import os
import struct
import time
from dataclasses import dataclass
from typing import Callable, List, Optional

from .binutil import Reader, Writer

DIRECTORY, FILE = 1, 2


def sane_time(ts: float) -> int:
    """Timestamps stored in a vpk are plain unix seconds; anything in the future (e.g. year 2078 coming from a
    garbled value) is replaced by the current time so the archive never shows impossible dates."""
    now = int(time.time())
    ts = int(ts)
    return now if ts <= 0 or ts > now + 86400 else ts
HEADER_SIZE = 34


@dataclass
class Entry:
    name: str
    directory: str          # parent directory path, backslash separated, with trailing '\\' (or '')
    parent: int
    size: int
    csize: int
    offset: int
    timestamp: int
    type: int

    @property
    def path(self) -> str:
        return (self.directory + self.name).replace("\\", "/")


def read_entries(data: bytes) -> List[Entry]:
    r = Reader(data)
    if r.take(6) != b"vtPack":
        raise ValueError("not a vtPack archive")
    major, minor = r.u32(), r.u32()
    if major != 1 or minor > 0:
        raise NotImplementedError(f"vtPack {major}.{minor} not supported")
    r.u32(); r.u32(); r.u32()                  # patch, unknown, header size
    count, table = r.u32(), r.u32()
    r.o = table
    out = []
    for _ in range(count):
        name = r.sized_string()
        directory = r.sized_string()
        parent, size, csize, offset, ts, typ = (r.u32() for _ in range(6))
        out.append(Entry(str(name), str(directory), parent, size, csize, offset, ts, typ))
    return out


def unpack(vpk_path: str, out_dir: str, progress: Optional[Callable[[int, int], None]] = None) -> int:
    with open(vpk_path, "rb") as f:
        data = f.read()
    entries = read_entries(data)
    n = 0
    for i, e in enumerate(entries):
        base = os.path.join(out_dir, *[p for p in e.directory.replace("\\", "/").split("/") if p])
        if e.type == DIRECTORY:
            os.makedirs(base, exist_ok=True)
            os.makedirs(os.path.join(base, e.name), exist_ok=True)
            continue
        if e.offset == 0 or e.size == 0:
            continue
        if e.csize != e.size:
            raise NotImplementedError(f"{e.path}: compressed entries are not supported")
        os.makedirs(base, exist_ok=True)
        with open(os.path.join(base, e.name), "wb") as fh:
            fh.write(data[e.offset:e.offset + e.size])
        try:
            t = sane_time(e.timestamp)
            os.utime(os.path.join(base, e.name), (t, t))
        except OSError:
            pass
        n += 1
        if progress:
            progress(i + 1, len(entries))
    return n


def repack(in_dir: str, vpk_path: str) -> int:
    """Pack every file/folder below `in_dir` (relative paths are kept, sorted like the original tool)."""
    in_dir = os.path.abspath(in_dir)
    dirs, files = [], []
    for dp, dn, fn in os.walk(in_dir):
        for d in dn:
            dirs.append(os.path.relpath(os.path.join(dp, d), in_dir))
        for f in fn:
            files.append(os.path.relpath(os.path.join(dp, f), in_dir))
    dirs.sort()
    files.sort()
    entries: List[Entry] = []
    dir_index = {}
    for rel in dirs:
        parent = os.path.dirname(rel).replace("/", "\\")
        dir_index[rel.replace("/", "\\").lower()] = len(entries)
        entries.append(Entry(os.path.basename(rel), parent, 0, 0, 0, 0, sane_time(os.path.getmtime(os.path.join(in_dir, rel))), DIRECTORY))
    for rel in files:
        parent = os.path.dirname(rel).replace("/", "\\")
        entries.append(Entry(os.path.basename(rel), parent, 0, 0, 0, 0, sane_time(os.path.getmtime(os.path.join(in_dir, rel))), FILE))
    w = Writer()
    w.raw(b"vtPack").u32(1).u32(0).u32(0).u32(0).u32(HEADER_SIZE).u32(0).u32(0)
    for e in entries:
        if e.type == FILE:
            with open(os.path.join(in_dir, *(e.directory.replace("\\", "/").split("/")), e.name), "rb") as fh:
                b = fh.read()
            e.offset, e.size = w.tell(), len(b)
            w.raw(b)
    table = w.tell()
    for e in entries:
        parent_key = e.directory.rstrip("\\").lower()
        e.parent = dir_index.get(parent_key, 0xFFFFFFFF) if parent_key else 0xFFFFFFFF
        dir_str = e.directory + ("\\" if e.directory and not e.directory.endswith("\\") else "")
        w.sized_string(e.name).sized_string(dir_str).u32(e.parent).u32(e.size).u32(e.size).u32(e.offset).u32(e.timestamp).u32(e.type)
    buf = bytearray(w.bytes())
    struct.pack_into("<II", buf, 26, len(entries), table)
    with open(vpk_path, "wb") as f:
        f.write(buf)
    return len(entries)
