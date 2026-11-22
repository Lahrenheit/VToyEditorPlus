"""Editing operations of the editor state that do not need a GUI: undo / redo, mesh and prop editing, fill patches,
collision clean-up, texture round trip, map preview and map export."""
from __future__ import annotations

import copy
import functools
import io
import os
import shutil
import time
import zipfile
from typing import List, Optional

import numpy as np

from .. import crop as cropmod
from .. import fill as fillmod
from ..modules import parse_modules
from ..opt import OptMap, transform_mesh, translate_mesh
from ..render.camera import compose
from ..scn import Scene, VStr
from ..tex import Texture

UNDO_LIMIT = 30


def undoable(opt: bool = False, label: str = ""):
    """Method decorator: snapshot the state before the call so Undo can bring it back."""
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(self, *a, **k):
            undo = self._undo_lists()[0]
            n = len(undo)
            self.push_undo(opt, label or fn.__name__.replace("_", " "))
            try:
                return fn(self, *a, **k)
            except Exception:
                if len(undo) > n:                    # a failed edit must not leave a do-nothing undo step behind
                    undo.pop()
                raise
        return wrapper
    return deco


class EditOps:
    # ---------------------------------------------------------------------------------- undo / redo
    def _undo_lists(self):
        if not hasattr(self, "_undo"):
            self._undo, self._redo = [], []
        return self._undo, self._redo

    def _snapshot(self, with_opt: bool, label: str) -> dict:
        return {"label": label, "scene": self.scene.to_bytes(),
                "opt": self.opt.to_bytes() if (with_opt and self.opt is not None and self.opt.meshes) else None,
                "lights": copy.deepcopy(self.opt.lights) if self.opt else [],
                "decals": copy.deepcopy(self.opt.decals) if self.opt else [],
                # the height map being edited (twin ships); None = the file on disk is used
                "hm": (getattr(self, "hm_edit", None).to_bytes() if getattr(self, "hm_edit", None) is not None else None)
                      if with_opt else False}

    def push_undo(self, with_opt: bool = False, label: str = "edit") -> None:
        if self.scene is None or getattr(self, "_undo_off", False):          # off while a macro runs: it is one undo step
            return
        undo, redo = self._undo_lists()
        snap = self._snapshot(with_opt, label)
        if undo:
            top = undo[-1]
            now = time.monotonic()
            if top["label"] == label and now - top.get("t", 0) < 0.7:       # one drag = one undo step
                top["t"] = now
                return
            if top["scene"] == snap["scene"] and len(top["lights"]) == len(snap["lights"]) \
                    and len(top["decals"]) == len(snap["decals"]) and (top["opt"] is None or snap["opt"] is None):
                if top["opt"] is None and snap["opt"] is not None:      # nothing changed in between: upgrade the entry
                    top["opt"] = snap["opt"]; top["label"] = label
                return
        snap["t"] = time.monotonic()
        undo.append(snap)
        del undo[:-UNDO_LIMIT]
        redo.clear()

    def can_undo(self) -> bool:
        return bool(self._undo_lists()[0])

    def can_redo(self) -> bool:
        return bool(self._undo_lists()[1])

    def undo_label(self) -> str:
        u = self._undo_lists()[0]
        return u[-1]["label"] if u else ""

    def redo_label(self) -> str:
        r = self._undo_lists()[1]
        return r[-1]["label"] if r else ""

    def _restore(self, snap: dict) -> None:
        self.__dict__.pop("_mesh_track_d", None)
        sc = Scene.parse(snap["scene"], self.scene.path)
        parse_modules(sc)
        self.scene = sc
        if snap["opt"] is not None:
            path = self.opt.path
            self.opt = OptMap.parse(snap["opt"])
            self.opt.path = path
            self._forget_lock_keys()
            if snap.get("hm") is not False:
                from ..hm import HeightMap
                self.hm_edit = HeightMap.parse(snap["hm"]) if snap.get("hm") is not None else None
        else:
            self.opt.lights = copy.deepcopy(snap["lights"])
            self.opt.decals = copy.deepcopy(snap["decals"])
        self.selection = None
        self.dirty_scene = self.dirty_map = self.needs_rebake = True

    def undo(self) -> str:
        undo, redo = self._undo_lists()
        if not undo:
            return ""
        snap = undo.pop()
        redo.append(self._snapshot(snap["opt"] is not None, snap["label"]))
        self._restore(snap)
        self.log(f"undo: {snap['label']}")
        return snap["label"]

    def redo(self) -> str:
        undo, redo = self._undo_lists()
        if not redo:
            return ""
        snap = redo.pop()
        undo.append(self._snapshot(snap["opt"] is not None, snap["label"]))
        self._restore(snap)
        self.log(f"redo: {snap['label']}")
        return snap["label"]

    def clear_undo(self) -> None:
        self.__dict__.pop("_mesh_track_d", None)
        self._undo, self._redo = [], []

    # ---------------------------------------------------------------------------------- scene checks / save as
    def scene_problems(self) -> List[str]:
        out = []
        if not any(r.clean_name.lower() == "mp_camerastartposition" for r in self.scene.modules):
            out.append("The scene has no mp_CameraStartPosition module: add one (Add new module > mp_CameraStartPosition) "
                       "before saving, the game needs it.")
        names = {}
        for r in self.scene.modules:
            k = str(r.object_name).rstrip("\0").lower()
            names.setdefault(k, 0)
            names[k] += 1
        dup = sorted(k for k, n in names.items() if n > 1)
        if dup:
            out.append("Duplicate object names (the game crashes on load): " + ", ".join(dup[:6]))
        return out

    def save_scene_as(self, name: str, with_map: bool = True) -> str:
        """Write the scene under a new name in scns/ (the working scene file is not touched) and keep working on the copy.
        With ``with_map`` the .opt, .hm and preview thumbnail are copied under the same new name too (see rename_map)."""
        stem = os.path.splitext(os.path.basename(name.strip()))[0]
        if not stem:
            raise ValueError("empty name")
        if with_map:
            # scene, .opt, .hm and preview thumbnail all get the new name (see rename_map)
            self.rename_map(stem)
            return self.scene.path
        path = os.path.join(os.path.dirname(self.scene.path), stem + ".scn")
        other = self._file_named("scns", stem + ".scn")
        if other:
            raise ValueError(f"there is already a scene called {stem}.scn ({other}) - pick another name")
        bad = self.scene_problems()
        if bad:
            raise ValueError(bad[0])
        self.scene.path = path
        self.scene.save(path)
        self.scene_name = stem + ".scn"
        self.dirty_scene = False
        self.fs.rescan()
        self.log(f"saved scene as {path}")
        return path

    # ---------------------------------------------------------------------------------- new names for the map files
    def _file_named(self, folder: str, base: str) -> str:
        """Path of a file called ``base`` anywhere under ``folder`` of the game data (any case, nested folders too), or ''."""
        self.fs.rescan()
        low = base.lower()
        for rel in self.fs.list(folder):
            if rel.split("/")[-1] == low:
                return self.fs.find(rel) or ""
        return ""

    def _scenes_naming(self, file_name: str, but: str = "") -> list:
        """Scenes (other than ``but``, a path) whose map / height map field is ``file_name``."""
        key = ("nfos\\" + os.path.basename(file_name)).lower().encode("cp1252")
        out = []
        for rel in self.fs.list("scns", ".scn"):
            full = self.fs.find(rel) or ""
            if not full or (but and os.path.abspath(full).lower() == os.path.abspath(but).lower()):
                continue
            try:
                with open(full, "rb") as f:
                    if key in f.read().lower():
                        out.append(os.path.basename(full))
            except OSError:
                pass
        return out

    def _make_room(self, path: str, what: str, moved: list) -> None:
        """``path`` is where a new map file goes.  Free: nothing to do.  Used by a scene: refuse (never replaced).  Used by
        no scene at all (e.g. left over by a save that failed half way): moved aside to ``<name>.old`` (kept, not deleted)."""
        if not os.path.exists(path):
            return
        users = self._scenes_naming(os.path.basename(path), but=self.scene.path)
        if users:
            raise ValueError(f"{os.path.basename(path)} already exists and the scene {', '.join(users[:3])} uses it - "
                             f"pick another name (it is never replaced)")
        k, aside = 0, path + ".old"
        while os.path.exists(aside):
            k += 1
            aside = f"{path}.old{k}"
        os.replace(path, aside)
        moved.append((path, aside))
        self.log(f"{os.path.basename(path)} was not used by any scene ({what}): kept as {os.path.basename(aside)}")

    def _write_map_files(self, stem: str, folder: str, hm_src: str, rep: list, written: list, moved: list) -> None:
        """Save the .opt and .hm being edited as nfos/<stem>.opt / .hm and point the scene to them."""
        opt_t, hm_t = os.path.join(folder, stem + ".opt"), os.path.join(folder, stem + ".hm")
        if self.opt is not None and getattr(self.opt, "path", ""):
            if os.path.abspath(self.opt.path).lower() != os.path.abspath(opt_t).lower():
                self._make_room(opt_t, "left over", moved)
            new_file = not os.path.exists(opt_t)
            self.opt.save(opt_t)
            if new_file:
                written.append(opt_t)
            self.opt.path = opt_t
            self.scene.map_name = VStr(("nfos\\" + stem + ".opt\0").encode("cp1252"))
            rep.append(f"nfos/{stem}.opt")
        if getattr(self, "hm_edit", None) is not None or (hm_src and os.path.exists(hm_src)):
            same = hm_src and os.path.abspath(hm_src).lower() == os.path.abspath(hm_t).lower()
            if not same:
                self._make_room(hm_t, "left over", moved)
            new_file = not os.path.exists(hm_t)
            if getattr(self, "hm_edit", None) is not None:
                self.hm_edit.save(hm_t)
                self.hm_edit = None
                rep.append(f"nfos/{stem}.hm (with the new floor collision)")
            elif not same:
                shutil.copy2(hm_src, hm_t)
                rep.append(f"nfos/{stem}.hm")
            if new_file:
                written.append(hm_t)
            self.scene.heightmap_name = VStr(("nfos\\" + stem + ".hm\0").encode("cp1252"))

    def _undo_write(self, written: list, moved: list, before: dict) -> None:
        """A rename that failed half way: take away the files it wrote and put back what it moved aside."""
        for p in written:
            try:
                if os.path.exists(p) and p not in before.get("keep", ()):
                    os.remove(p)
            except OSError:
                pass
        for path, aside in moved:
            try:
                if not os.path.exists(path):
                    os.replace(aside, path)
            except OSError:
                pass
        self.scene.path, self.scene.map_name, self.scene.heightmap_name = before["scn"], before["map"], before["hm"]
        self.scene.main_module_name = before["dll"]
        if self.opt is not None:
            self.opt.path = before["opt"]

    # ---------------------------------------------------------------------------------- locks (padlock in the module list)
    # A locked module cannot be picked in the 3D view, moved, rotated, scaled, edited or deleted: it protects finished work
    # when many objects are close together.  Locks are kept per map in vtoy_editor.json ("locks": {map: [object names]}),
    # never in the game files.
    @staticmethod
    def lock_key(rec) -> str:
        return str(rec.object_name).rstrip("\0").lower()

    def obj_key(self, kind: str, ref) -> str:
        """Lock key of a module (its object name), a static mesh or a prop.  Meshes and props have no names: they are told
        apart by where they are (rounded centre / position) and their size, which survives reloads and index changes."""
        if kind == "module":
            return self.lock_key(ref)
        cache = self.__dict__.setdefault("_lock_key_cache", {})
        k = cache.get(id(ref))
        if k is not None and k[0] is ref:
            return k[1]
        if kind == "mesh":
            lo, hi = cropmod.mesh_bounds(ref)
            nv = sum(len(sm.vertices) for sm in ref.render_submeshes())
            key = "mesh:" + ",".join(str(int(round(v))) for v in np.concatenate([lo, hi])) + f":{nv}"
        elif kind == "prop":
            t = np.asarray(ref.transform, np.float64)[3, :3]
            key = f"prop:{ref.mesh_index}:" + ",".join(str(int(round(v))) for v in t)
        elif kind == "light":
            key = f"light:{int(ref.type)}:" + ",".join(str(int(round(float(v)))) for v in ref.position) + f":{int(round(float(ref.end)))}"
        elif kind == "decal":
            key = f"decal:{str(ref.name).rstrip(chr(0)).lower()}:" + ",".join(str(int(round(float(v)))) for v in ref.position)
        else:
            return ""
        cache[id(ref)] = (ref, key)
        return key

    def _forget_lock_keys(self) -> None:
        self.__dict__.pop("_lock_key_cache", None)

    def _locks(self) -> set:
        if getattr(self, "locks", None) is None:
            self.load_locks()
        return self.locks

    def load_locks(self) -> None:
        from .. import settings
        self._forget_lock_keys()
        try:
            self.locks = {str(n).lower() for n in (settings.get("locks") or {}).get(self.map_stem().lower(), [])}
        except Exception:
            self.locks = set()

    def _save_locks(self) -> None:
        from .. import settings
        d = dict(settings.get("locks") or {})
        live = {self.lock_key(r) for r in self.scene.modules}
        if self.opt is not None:
            live |= {self.obj_key("mesh", m) for m in self.opt.meshes}
            live |= {self.obj_key("prop", p) for p in self.opt.props}
        keep = sorted(n for n in self.locks if n in live)
        if keep:
            d[self.map_stem().lower()] = keep
        else:
            d.pop(self.map_stem().lower(), None)
        settings.set("locks", d)

    def is_locked(self, rec, kind: str = "module") -> bool:
        if rec is None:
            return False
        if kind == "module" and not hasattr(rec, "object_name"):
            return False
        locks = self._locks()
        if not locks:
            return False
        return self.obj_key(kind, rec) in locks

    def set_locked(self, rec, on: bool, kind: str = "module") -> None:
        k = self.obj_key(kind, rec)
        if not k:
            return
        if on:
            self._locks().add(k)
        else:
            self._locks().discard(k)
        if on and self.selection is not None and self.selection.ref is rec:
            self.selection = None
        self._save_locks()

    # ---------------------------------------------------------------------------------- hidden objects (the eye in the lists)
    # Hiding is only for the editor's view: the object stays in the scene / map, is saved, exported, collides and is counted
    # by every tool; it is just not drawn (and so cannot be clicked) until it is shown again.  Like the padlocks, the list is
    # kept per map in vtoy_editor.json ("hidden": {map: [keys]}).
    def _hidden(self) -> set:
        if getattr(self, "hidden", None) is None:
            self.load_hidden()
        return self.hidden

    def load_hidden(self) -> None:
        from .. import settings
        try:
            self.hidden = {str(n).lower() for n in (settings.get("hidden") or {}).get(self.map_stem().lower(), [])}
        except Exception:
            self.hidden = set()

    def _save_hidden(self) -> None:
        from .. import settings
        d = dict(settings.get("hidden") or {})
        if self.hidden:
            d[self.map_stem().lower()] = sorted(self.hidden)
        else:
            d.pop(self.map_stem().lower(), None)
        settings.set("hidden", d)

    def _hideable(self):
        """(kind, object) of everything that can be hidden."""
        for r in (self.scene.modules if self.scene is not None else []):
            yield "module", r
        if self.opt is not None:
            for m in self.opt.meshes:
                yield "mesh", m
            for p in self.opt.props:
                yield "prop", p
            for l in self.opt.lights:
                yield "light", l
            for d in self.opt.decals:
                yield "decal", d

    def is_hidden(self, rec, kind: str = "module") -> bool:
        h = self._hidden()
        if not h or rec is None or (kind == "module" and not hasattr(rec, "object_name")):
            return False
        return self.obj_key(kind, rec) in h

    def hidden_ids(self) -> frozenset:
        """ids of the hidden objects, for the baker."""
        h = self._hidden()
        if not h:
            return frozenset()
        return frozenset(id(o) for k, o in self._hideable() if self.obj_key(k, o) in h)

    def hidden_count(self) -> int:
        h = self._hidden()
        return sum(1 for k, o in self._hideable() if self.obj_key(k, o) in h) if h else 0

    def set_hidden(self, rec, on: bool, kind: str = "module") -> None:
        k = self.obj_key(kind, rec)
        if not k:
            return
        if on:
            self._hidden().add(k)
            if self.selection is not None and self.selection.ref is rec:
                self.selection = None
            if getattr(self, "multi", None):
                self.multi = [s for s in self.multi if s.ref is not rec]
        else:
            self._hidden().discard(k)
        self._save_hidden()
        self.needs_rebake = True

    def hide_selection(self) -> str:
        """Hide the selected object and the group (H)."""
        g = ([self.selection] if self.selection is not None else []) + list(getattr(self, "multi", None) or [])
        g = [s for s in g if s.kind in ("module", "mesh", "prop", "light", "decal")]
        if not g:
            return "nothing selected to hide"
        for s in g:
            k = self.obj_key(s.kind, s.ref)
            if k:
                self._hidden().add(k)
        self.selection = None
        self.multi = []
        self._save_hidden()
        self.needs_rebake = True
        return f"{len(g)} objects hidden (still in the map) - Shift+H shows everything again"

    def show_all(self) -> str:
        n = self.hidden_count()
        self._hidden().clear()
        self._save_hidden()
        self.needs_rebake = True
        return f"{n} hidden objects shown again"

    def lock_all(self, on: bool, kind: str = "module") -> int:
        if kind == "module":
            items = list(self.scene.modules)
        elif self.opt is None:
            items = []
        else:
            items = list({"mesh": self.opt.meshes, "prop": self.opt.props, "light": self.opt.lights,
                          "decal": self.opt.decals}.get(kind, []))
        n = 0
        for r in items:
            k = self.obj_key(kind, r)
            if (k in self._locks()) != on:
                n += 1
            (self._locks().add if on else self._locks().discard)(k)
        if on and self.selection is not None and self.selection.kind == kind:
            self.selection = None
        self._save_locks()
        return n

    def blocked_by_lock(self, sel) -> bool:
        """True (and a log line) when ``sel`` is locked: the edit is skipped."""
        if sel is None or sel.kind not in ("module", "mesh", "prop", "light", "decal") or not self.is_locked(sel.ref, sel.kind):
            return False
        import time as _t
        now = _t.monotonic()
        if now - getattr(self, "_lock_msg_t", 0.0) > 1.5:
            self._lock_msg_t = now
            what = str(sel.ref.object_name).rstrip(chr(0)) if sel.kind == "module" else sel.kind
            self.log(f"'{what}' is locked - open its padlock to edit it")
        return True

    # ---------------------------------------------------------------------------------- height map (.hm = floor collision)
    def heightmap_edit(self):
        """The scene's height map as an editable in-memory object (loaded once; written by ``flush_heightmap``)."""
        from ..hm import HeightMap
        if getattr(self, "hm_edit", None) is None:
            name = str(self.scene.heightmap_name).rstrip("\0").replace("\\", "/")
            p = self.fs.find(name) if name else None
            if not p:
                raise ValueError("this scene has no height map (.hm): the floor collision comes from it")
            self.hm_edit = HeightMap.load(p)
        return self.hm_edit

    def scenes_using(self, file_name: str) -> list:
        """Other scenes (not the one being edited) whose map / height map field names ``file_name`` (e.g. mp_dm_loveboat.hm)."""
        key = ("nfos\\" + os.path.basename(file_name)).lower().encode("cp1252")
        mine = os.path.basename(self.scene.path or "").lower()
        out = []
        for p in self.fs.list("scns", ".scn"):
            if os.path.basename(p).lower() == mine:
                continue
            full = self.fs.find(p) or os.path.join(self.fs.root, p)
            try:
                with open(full, "rb") as f:
                    if key in f.read().lower():
                        out.append(os.path.basename(p))
            except OSError:
                pass
        return out

    def own_file(self, current: str, ext: str) -> str:
        """Where this map's .opt / .hm is written: the current file only if it is named like this map and no other scene uses
        it; otherwise ``<map>.<ext>`` (or ``<map>_2.<ext>``... if that name is taken by a file other scenes use).  Files of other
        maps are never overwritten."""
        stem = self.map_stem()
        folder = os.path.dirname(current) if current else (os.path.dirname(self.opt.path) if (self.opt is not None and self.opt.path)
                                                           else os.path.join(self.fs.root, "nfos", "nfos"))
        if current and os.path.splitext(os.path.basename(current))[0].lower() == stem.lower() \
                and not self.scenes_using(os.path.basename(current)):
            return current
        k = 1
        while True:
            name = f"{stem}{'' if k == 1 else '_' + str(k)}.{ext}"
            cand = os.path.join(folder, name)
            if not os.path.exists(cand) or not self.scenes_using(name):
                return cand
            k += 1

    def map_backups(self) -> list:
        """(file, backup) of every .opt / .hm in nfos that has a .bak (the first version the editor ever overwrote)."""
        out = []
        folder = os.path.dirname(self.opt.path) if (self.opt is not None and self.opt.path) else os.path.join(self.fs.root, "nfos", "nfos")
        try:
            names = sorted(os.listdir(folder))
        except OSError:
            return out
        for n in names:
            if n.lower().endswith((".opt.bak", ".hm.bak")):
                out.append((os.path.join(folder, n[:-4]), os.path.join(folder, n)))
        return out

    def restore_backup(self, path: str) -> str:
        """Put back the .bak of a map file (e.g. a shared stock .opt / .hm changed by an older version of the editor)."""
        if not os.path.exists(path + ".bak"):
            raise ValueError("no backup")
        shutil.copy2(path + ".bak", path)
        self.fs.rescan(); self.fs._opt.clear()
        return f"{os.path.basename(path)} restored from its backup (used by: {', '.join(self.scenes_using(os.path.basename(path))) or '-'})"

    def hm_target_path(self) -> str:
        """Where an edited height map is written (see own_file: never a file other maps use)."""
        name = str(self.scene.heightmap_name).rstrip("\0").replace("\\", "/")
        cur = self.fs.find(name) if name else None
        return self.own_file(cur or "", "hm")

    def flush_heightmap(self) -> str:
        """Write the edited height map (if any) and point the scene at it. Returns the path or ''."""
        hm = getattr(self, "hm_edit", None)
        if hm is None:
            return ""
        path = self.hm_target_path()
        if os.path.exists(path) and not os.path.exists(path + ".bak"):
            shutil.copy2(path, path + ".bak")
        hm.save(path)
        want = "nfos\\" + os.path.basename(path)
        if str(self.scene.heightmap_name).rstrip("\0") != want:
            self.scene.heightmap_name = VStr((want + "\0").encode("cp1252"))
            self.dirty_scene = True
        self.hm_edit = None
        self.fs.rescan()
        self.log(f"saved {path}")
        return path

    def rename_map(self, new_stem: str, out_dll_dir: str = "") -> str:
        """Make a complete copy of the working map under a new name (scene, .opt, .hm, preview) and keep working on it.
        Everything that depends on the name is updated: the scene's map / heightmap fields, ``texs/<name>-tbn``, the exported
        zip name and a weather DLL copy. The originals (which other scenes may share) are never touched.  If anything fails
        half way, the files it wrote are taken away again (no half saved copy is left behind)."""
        import re
        from .. import dllpatch
        stem = os.path.splitext(os.path.basename(new_stem.strip()))[0]
        if not re.fullmatch(r"[A-Za-z0-9_\-]+", stem):
            raise ValueError("the name may only contain letters, digits, _ and -")
        old = self.map_stem()
        if stem.lower() == old.lower():
            raise ValueError("that is already the name of this scene")
        other = self._file_named("scns", stem + ".scn")
        if other:
            raise ValueError(f"there is already a scene called {stem}.scn - pick another name (it is never replaced)")
        bad = self.scene_problems()
        if bad:
            raise ValueError(bad[0])
        scn_dir = os.path.dirname(self.scene.path)
        scn_path = os.path.join(scn_dir, stem + ".scn")
        src_opt = self.opt.path if self.opt is not None else ""
        folder = os.path.dirname(src_opt) if src_opt else os.path.join(self.fs.root, "nfos")
        hm_old = str(self.scene.heightmap_name).rstrip("\0").replace("\\", "/")
        hm_src = (self.fs.find(hm_old) if hm_old else None) or (os.path.splitext(src_opt)[0] + ".hm" if src_opt else "")
        before = {"scn": self.scene.path, "map": self.scene.map_name, "hm": self.scene.heightmap_name,
                  "dll": self.scene.main_module_name, "opt": src_opt}
        rep, warn, written, moved = [], [], [], []
        try:
            self._write_map_files(stem, folder, hm_src, rep, written, moved)
            tdir = os.path.join(self.fs.root, "texs")
            for ext in ("tex", "dds"):
                for cand in (os.path.join(tdir, old + "-tbn." + ext), os.path.join(tdir, "texs", old + "-tbn." + ext)):
                    dst = os.path.join(os.path.dirname(cand), stem + "-tbn." + ext)
                    if os.path.exists(cand) and not os.path.exists(dst):
                        shutil.copy2(cand, dst)
                        written.append(dst)
                        rep.append(f"texs/{stem}-tbn.{ext}")
                        break
            # the mode DLL: a weather copy is re-made for the new name; if that cannot be done the scene keeps its DLL
            dll = self.custom_dll_path()
            if dll:
                try:
                    data = open(dll, "rb").read()
                    low = data.lower()
                    names = {old.lower().encode(), (old + ".opt").lower().encode(), (old + ".hm").lower().encode()}
                    hits = sorted(n.decode() for n in names if n in low)
                    if dllpatch.find_weather_string(data):
                        odir = out_dll_dir or self.export_dir()
                        base = os.path.splitext(os.path.basename(dll))[0]
                        base = re.sub("_" + re.escape(old) + "$", "", base, flags=re.I)
                        os.makedirs(odir, exist_ok=True)
                        dname = f"{base}_{stem}.dll"
                        r = dllpatch.patch_map_name(dll, os.path.join(odir, dname), "nfos\\" + stem + ".opt")
                        self.scene.main_module_name = VStr((dname + "\0").encode("cp1252"))
                        self.custom_dlls = dict(getattr(self, "custom_dlls", {}), **{dname.lower(): os.path.join(odir, dname)})
                        rep.append(f"dll/{dname} ({r.references} refs)")
                    elif hits:
                        warn.append(f"{os.path.basename(dll)} contains the old name ({', '.join(hits)}): it may expect the old map")
                except Exception as e:                       # e.g. 'the comparison string is never referenced'
                    warn.append(f"the mode DLL {os.path.basename(dll)} was kept as it is (its copy for the new name could "
                                f"not be made: {e}); the map works, the rain / weather may not")
            locks = set(self._locks())
            self.scene.path = scn_path
            self.scene.save(scn_path)
            written.append(scn_path)                         # (checked above: it did not exist)
        except Exception:
            self._undo_write(written, moved, before)
            self.fs.rescan()
            raise
        self._last_rename_written = list(written)            # (a new map that fails half way takes them away)
        self.scene_name = stem + ".scn"
        self.locks = locks                                   # the copy keeps the padlocks
        if getattr(self, "hidden", None):                    # ... and what was hidden
            self._save_hidden()
        self._save_locks()
        self.dirty_scene = False
        self.dirty_map = False
        self.fs.rescan(); self.fs._tex.clear()
        msg = f"map renamed {old} -> {stem}: " + ", ".join([f"scns/{stem}.scn"] + rep) + ("".join("\nWARNING: " + w for w in warn))
        self.log(msg)
        return msg

    def map_file_names(self) -> tuple:
        """(scene stem, .opt file name, .hm file name) of what is being edited."""
        stem = os.path.splitext(os.path.basename(self.scene.path or self.scene_name or ""))[0]
        opt = os.path.basename(str(self.scene.map_name).rstrip("\0").replace("\\", "/"))
        hm = os.path.basename(str(self.scene.heightmap_name).rstrip("\0").replace("\\", "/"))
        return stem, opt, hm

    def name_files_like_scene(self) -> str:
        """Save the .opt and .hm of this scene with the scene's own name (mp_x.scn -> nfos/mp_x.opt, nfos/mp_x.hm) and
        point the scene to them.  The old files stay as they were (other scenes may use them)."""
        stem, opt, hm = self.map_file_names()
        if not stem:
            raise ValueError("save the scene first")
        if opt.lower() == stem.lower() + ".opt" and (not hm or hm.lower() == stem.lower() + ".hm"):
            return f"the map files are already called {stem}.opt / {stem}.hm"
        bad = self.scene_problems()
        if bad:
            raise ValueError(bad[0])
        src_opt = self.opt.path if self.opt is not None else ""
        folder = os.path.dirname(src_opt) if src_opt else os.path.join(self.fs.root, "nfos")
        hm_old = str(self.scene.heightmap_name).rstrip("\0").replace("\\", "/")
        hm_src = (self.fs.find(hm_old) if hm_old else None) or ""
        before = {"scn": self.scene.path, "map": self.scene.map_name, "hm": self.scene.heightmap_name,
                  "dll": self.scene.main_module_name, "opt": src_opt}
        rep, written, moved = [], [], []
        try:
            self._write_map_files(stem, folder, hm_src, rep, written, moved)
            self.scene.save(self.scene.path)
        except Exception:
            self._undo_write(written, moved, before)
            self.fs.rescan()
            raise
        self.dirty_scene = False
        self.dirty_map = False
        self.fs.rescan()
        msg = f"{stem}.scn now uses " + ", ".join(rep) + f" (the old {opt}" + (f" / {hm}" if hm else "") + " stay as they were)"
        self.log(msg)
        return msg

    # ---------------------------------------------------------------------------------- bounds helpers
    def engine_bounds(self, sel):
        """(lo, hi) in engine coordinates of a selected mesh / prop / model module, or None."""
        for inst in (self.geometry.instances if self.geometry else []):
            if inst.ref is sel.ref:
                return (np.array([inst.lo[0], inst.lo[1], -inst.hi[2]], np.float64),
                        np.array([inst.hi[0], inst.hi[1], -inst.lo[2]], np.float64))
        return None

    # ---------------------------------------------------------------------------------- deleting
    def delete_selection(self, sel, collision: bool = True) -> str:
        if sel is None:
            return "nothing selected"
        if sel.kind == "module":
            if self.blocked_by_lock(sel):
                return "module locked: not deleted"
            self.delete_module(sel.ref)
            return "module deleted"
        if sel.kind in ("prop", "mesh") and self.blocked_by_lock(sel):
            return f"{sel.kind} locked: not deleted"
        if sel.kind in ("prop", "mesh"):
            parts = self.carry_parts(sel) if collision else None
            if parts:
                self.push_undo(True, f"delete {sel.kind}")
            was = getattr(self, "_undo_off", False)
            self._undo_off = was or bool(parts)
            try:
                msg = self.delete_prop(sel.ref, collision) if sel.kind == "prop" else self.delete_mesh(sel.ref, collision)
                if parts:
                    # the boxes the deletion already took are gone: only the floor / wall faces of the .hm are left to take
                    nb, nf = self.carry_remove((([], parts[1], parts[2])))
                    if nf:
                        msg += f" + {nf} floor / wall faces"
            finally:
                self._undo_off = was
            return msg
        if sel.kind in ("light", "decal") and self.blocked_by_lock(sel):
            return f"{sel.kind} locked: not deleted"
        if sel.kind == "light":
            self.delete_light(sel.ref)
            return "light deleted"
        if sel.kind == "decal":
            self.delete_decal(sel.ref)
            return "decal deleted"
        return "this cannot be deleted"

    @undoable(True, "delete mesh")
    def delete_mesh(self, mesh, collision: bool = True) -> str:
        i = next((k for k, m in enumerate(self.opt.meshes) if m is mesh), None)
        if i is None:
            return "mesh not found"
        n, p, c = cropmod.remove_meshes(self.opt, {i}, collision)
        self.dirty_map = self.needs_rebake = True
        self.selection = None
        msg = f"deleted mesh {i}" + (f" + {p} props" if p else "") + (f" + {c} collision pieces" if c else "")
        self.log(msg)
        return msg

    @undoable(True, "delete prop")
    def delete_prop(self, prop, collision: bool = True) -> str:
        i = next((k for k, p in enumerate(self.opt.props) if p is prop), None)
        if i is None:
            return "prop not found"
        bounds = self.engine_bounds(self.selection) if self.selection and self.selection.ref is prop else None
        cropmod.remove_props(self.opt, {i})
        removed = 0
        if collision and bounds is not None:
            b, h = cropmod.remove_collision_in_box(self.opt, bounds[0], bounds[1], margin=1.0)
            removed = b + h + cropmod.remove_orphans_in(self.opt, [(np.asarray(bounds[0]) - 25.0, np.asarray(bounds[1]) + 25.0)])
        self.dirty_map = self.needs_rebake = True
        self.selection = None
        msg = f"deleted prop {i}" + (f" + {removed} collision pieces" if removed else "")
        self.log(msg)
        return msg

    @undoable(True, "delete orphan collision")
    def delete_orphan_collision(self) -> str:
        """Every collision box with no drawing near it (a leftover of deleted objects)."""
        ob, _ = cropmod.orphan_collision(self.opt)
        b, h = cropmod.remove_collision_indices(self.opt, ob)
        self.dirty_map = True
        msg = f"removed {b} collision boxes that had no geometry near them"
        self.log(msg)
        return msg

    @undoable(True, "delete collision box")
    def delete_collision_boxes(self, idx) -> str:
        b, h = cropmod.remove_collision_indices(self.opt, list(idx))
        self.dirty_map = True
        return f"removed {b} collision boxes"

    def collision_box_info(self, i: int):
        """(centre, half extents) of collision box ``i`` in engine coordinates."""
        a = np.frombuffer(cropmod.read_block(self.opt).boxes[i], "<f4", 19).astype(np.float64)
        return a[12:15], np.abs(a[16:19])

    def find_orphan_collision(self):
        return cropmod.orphan_collision(self.opt)[0]

    def count_orphan_collision(self) -> int:
        return len(cropmod.orphan_collision(self.opt)[0])

    @undoable(True, "delete collision")
    def delete_collision_in_polygon(self, poly_engine_xz, y_range=None) -> str:
        b, h = cropmod.remove_collision_in_polygon(self.opt, poly_engine_xz, y_range)
        self.dirty_map = True
        msg = f"removed {b} collision boxes and {h} collision hulls inside the outline"
        self.log(msg)
        return msg

    @undoable(True, "delete collision outside")
    def delete_collision_outside(self, poly_engine_xz) -> str:
        b, h = cropmod.remove_collision_in_polygon(self.opt, poly_engine_xz, None, outside=True)
        self.dirty_map = True
        msg = f"removed {b} collision boxes and {h} collision hulls outside the outline"
        self.log(msg)
        return msg

    @undoable(True, "delete geometry outside outline")
    def delete_outside_outline(self, poly_engine_xz) -> str:
        """Geometry only: scene modules (spawns, items...) are left alone."""
        rep = cropmod.crop_map(self.opt, poly_engine_xz, keep_inside=True)
        self.selection = None
        self.dirty_map = self.needs_rebake = True
        self.log("delete outside: " + rep.summary())
        return rep.summary()

    @undoable(True, "delete geometry inside outline")
    def delete_inside_outline(self, poly_engine_xz) -> str:
        rep = cropmod.crop_map(self.opt, poly_engine_xz, keep_inside=False)
        self.selection = None
        self.dirty_map = self.needs_rebake = True
        self.log("delete inside: " + rep.summary())
        return rep.summary()

    # ---------------------------------------------------------------------------------- transforming
    def can_scale(self, sel) -> bool:
        if sel.kind == "mesh":
            return not any(p.mesh_index == next((i for i, m in enumerate(self.opt.meshes) if m is sel.ref), -1)
                           for p in self.opt.props)
        from .state import _has_matrix
        return sel.kind == "prop" or (sel.kind == "module" and _has_matrix(sel.ref.parsed)
                                      and isinstance(getattr(sel.ref.parsed, "transform", None), np.ndarray)
                                      and not hasattr(sel.ref.parsed, "angle"))

    def can_rotate_any(self, sel) -> bool:
        return self.can_scale(sel) if sel.kind == "mesh" else self.can_rotate(sel)

    def _mesh_centre(self, mesh) -> np.ndarray:
        lo, hi = cropmod.mesh_bounds(mesh)
        return (lo + hi) / 2

    def _mesh_transform(self, mesh, M3) -> None:
        """Turn / scale a static mesh about its centre; its collision goes with it (Settings)."""
        from .state import Selection
        from ..carry import affine_about
        c = self._mesh_centre(mesh)
        parts = self.carry_parts(Selection("mesh", mesh, ""))
        transform_mesh(mesh, M3, c)
        if parts:
            self.carry_apply(parts, affine_about(M3, c))

    def rotate_mesh(self, mesh, euler_deg) -> None:
        m3 = compose([0, 0, 0], euler_deg, [1, 1, 1])[:3, :3]
        self._mesh_transform(mesh, m3)
        tr = self._mesh_track().setdefault(id(mesh), [np.eye(3), 1.0])
        tr[0] = tr[0] @ m3.astype(np.float64)
        self.dirty_map = self.needs_rebake = True

    def scale_mesh(self, mesh, factor: float) -> None:
        self._mesh_transform(mesh, np.eye(3) * float(factor))
        tr = self._mesh_track().setdefault(id(mesh), [np.eye(3), 1.0])
        tr[1] = np.asarray(tr[1], np.float64) * float(factor)
        self.dirty_map = self.needs_rebake = True

    def rotate_any(self, sel, euler_deg) -> None:
        if self.blocked_by_lock(sel):
            return
        self.push_undo(sel.kind != "module", "rotate")
        if sel.kind == "mesh":
            if not self.can_scale(sel):
                raise ValueError("this mesh is shared by props: rotate those instead")
            self.rotate_mesh(sel.ref, euler_deg)
        else:
            self.rotate_selection(sel, euler_deg)

    def scale_selection(self, sel, factor: float) -> None:
        """Uniform scale about the object's own centre (props / modules with a matrix: about their origin)."""
        factor = float(factor)
        if factor <= 0:
            raise ValueError("scale must be > 0")
        if self.blocked_by_lock(sel):
            return
        self.push_undo(sel.kind != "module", "scale")
        if sel.kind == "mesh":
            if not self.can_scale(sel):
                raise ValueError("this mesh is shared by props: scale those instead")
            self.scale_mesh(sel.ref, factor)
        elif sel.kind == "prop" or (sel.kind == "module" and isinstance(getattr(sel.ref.parsed, "transform", None), np.ndarray)):
            obj = sel.ref if sel.kind == "prop" else sel.ref.parsed
            m0 = np.asarray(obj.transform, np.float64).copy()
            m = m0.copy()
            m[:3, :3] *= factor
            parts = self.carry_parts(sel) if sel.kind == "prop" else None
            obj.transform = m.astype(np.float32)
            if parts:
                self.carry_apply(parts, np.linalg.inv(m0) @ m)
            self.dirty_map = self.dirty_map or sel.kind == "prop"
            self.dirty_scene = self.dirty_scene or sel.kind == "module"
            self.needs_rebake = True
        else:
            raise ValueError("this object cannot be scaled")

    # ---------------------------------------------------------------------------------- numeric rotation / scale fields
    def _mesh_track(self):
        return self.__dict__.setdefault("_mesh_track_d", {})        # id(mesh) -> [euler(3), scale]

    def has_matrix(self, sel) -> bool:
        if sel.kind == "prop":
            return True
        p = getattr(sel.ref, "parsed", None) if sel.kind == "module" else None
        return p is not None and (hasattr(p, "angle") or isinstance(getattr(p, "transform", None), np.ndarray))

    def rotation_of(self, sel) -> np.ndarray:
        """Euler XYZ in degrees (start points: yaw only; static meshes: what the editor applied this session)."""
        from ..render.camera import decompose
        if sel.kind == "mesh":
            R = self._mesh_track().get(id(sel.ref), [np.eye(3), 1.0])[0]
            m = np.eye(4); m[:3, :3] = R
            return np.asarray(decompose(m)[1], np.float64)
        if sel.kind == "module" and hasattr(sel.ref.parsed, "angle"):
            return np.array([0.0, float(np.degrees(sel.ref.parsed.angle)), 0.0])
        obj = sel.ref if sel.kind == "prop" else sel.ref.parsed
        return np.asarray(decompose(obj.transform)[1], np.float64)

    def scale_of(self, sel) -> np.ndarray:
        from ..render.camera import decompose
        if sel.kind == "mesh":
            f = np.asarray(self._mesh_track().get(id(sel.ref), [None, 1.0])[1], np.float64)
            return np.broadcast_to(f, (3,)).astype(np.float64).copy()
        if sel.kind == "module" and hasattr(sel.ref.parsed, "angle"):
            return np.ones(3)
        obj = sel.ref if sel.kind == "prop" else sel.ref.parsed
        return np.asarray(decompose(obj.transform)[2], np.float64)

    def set_rotation(self, sel, euler_deg) -> None:
        """Absolute rotation (degrees XYZ).  Meshes are baked, so the difference to the tracked angles is applied."""
        if self.blocked_by_lock(sel):
            return
        e = np.asarray(euler_deg, np.float64)
        if sel.kind == "mesh":
            if not self.can_scale(sel):
                raise ValueError("this mesh is shared by props: rotate those instead")
            tr = self._mesh_track().setdefault(id(sel.ref), [np.eye(3), 1.0])
            Rn = compose([0, 0, 0], e, [1, 1, 1])[:3, :3].astype(np.float64)
            self._mesh_transform(sel.ref, np.linalg.inv(tr[0]) @ Rn)
            tr[0] = Rn
            self.dirty_map = self.needs_rebake = True
            return
        if sel.kind == "module" and hasattr(sel.ref.parsed, "angle"):
            sel.ref.parsed.angle = float(np.radians(e[1]))
            self.dirty_scene = self.needs_rebake = True
            return
        obj = sel.ref if sel.kind == "prop" else sel.ref.parsed
        m = np.asarray(obj.transform, np.float64)
        sc = self.scale_of(sel)
        new = compose(m[3, :3], e, sc)
        parts = self.carry_parts(sel) if sel.kind == "prop" else None
        obj.transform = new.astype(np.float32)
        if parts:
            self.carry_apply(parts, np.linalg.inv(m) @ np.asarray(new, np.float64))
        if sel.kind == "prop":
            self.dirty_map = True
        else:
            self.dirty_scene = True
        self.needs_rebake = True

    def set_scale(self, sel, scale) -> None:
        if self.blocked_by_lock(sel):
            return
        s = np.asarray(scale, np.float64)
        if np.any(s <= 1e-6):
            raise ValueError("scale must be > 0")
        if sel.kind == "mesh":
            if not self.can_scale(sel):
                raise ValueError("this mesh is shared by props: scale those instead")
            tr = self._mesh_track().setdefault(id(sel.ref), [np.eye(3), 1.0])
            old = np.broadcast_to(np.asarray(tr[1], np.float64), (3,))
            f = s / old
            if np.any(np.abs(f - 1.0) > 1e-9):
                R = np.asarray(tr[0], np.float64)
                self._mesh_transform(sel.ref, R.T @ np.diag(f) @ R)     # along the mesh's own (turned) axes
                tr[1] = s.copy()
                self.dirty_map = self.needs_rebake = True
            return
        if sel.kind == "module" and hasattr(sel.ref.parsed, "angle"):
            return
        obj = sel.ref if sel.kind == "prop" else sel.ref.parsed
        m = np.asarray(obj.transform, np.float64)
        new = compose(m[3, :3], self.rotation_of(sel), s)
        parts = self.carry_parts(sel) if sel.kind == "prop" else None
        obj.transform = new.astype(np.float32)
        if parts:
            self.carry_apply(parts, np.linalg.inv(m) @ np.asarray(new, np.float64))
        if sel.kind == "prop":
            self.dirty_map = True
        else:
            self.dirty_scene = True
        self.needs_rebake = True

    def duplicate_selection(self, sel, offset=(150.0, 0.0, 0.0), carry: bool = True):
        """Copy the selected object (module, prop or static mesh) next to the original; returns the new selection.
        A mesh / prop takes a copy of its collision along (Settings), unless ``carry`` is False."""
        from .state import Selection
        off = np.asarray(offset, np.float64)
        if carry and sel.kind in ("mesh", "prop"):
            from ..carry import affine_move
            parts = self.carry_parts(sel)
            new = self._duplicate(sel, off)
            if parts:
                self.carry_apply(parts, affine_move(off), copy=True)
            return new
        return self._duplicate(sel, off)

    def _duplicate(self, sel, off):
        from .state import Selection
        if sel.kind in ("light", "decal"):
            return self.duplicate_opt(sel.kind, sel.ref, off)
        if sel.kind == "module":
            rec = self.duplicate_module(sel.ref)
            try:
                self.set_position(Selection("module", rec, ""), self.position_of(Selection("module", rec, "")) + off)
            except Exception:
                pass
            return Selection("module", rec, rec.object_name)
        self.push_undo(True, "duplicate")
        bounds = self.engine_bounds(sel)
        if sel.kind == "prop":
            new = copy.deepcopy(sel.ref)
            new.transform = new.transform.copy()
            new.transform[3, :3] += off
            lo, hi = bounds if bounds else (new.transform[3, :3] - 50, new.transform[3, :3] + 50)
            cropmod.add_prop(self.opt, new, lo + off, hi + off)
            self.dirty_map = self.needs_rebake = True
            return Selection("prop", new, "prop (copy)")
        if sel.kind == "mesh":
            new = copy.deepcopy(sel.ref)
            translate_mesh(new, off)
            cropmod.add_mesh(self.opt, new)
            self.dirty_map = self.needs_rebake = True
            return Selection("mesh", new, "mesh (copy)")
        raise ValueError("this object cannot be duplicated")

    # ---------------------------------------------------------------------------------- fill patches
    def texture_of(self, sel) -> Optional[str]:
        """First texture a selected mesh / prop uses (the 'eyedropper' of the fill tool)."""
        ref = sel.ref if sel else None
        if sel and sel.kind == "prop":
            ref = self.opt.meshes[sel.ref.mesh_index]
        if hasattr(ref, "materials"):
            for mat in ref.materials:
                if mat.textures and mat.textures[0]:
                    return str(mat.textures[0])
        return None

    @undoable(True, "fill patch")
    def add_fill_patch(self, poly_engine_xz, y: float, texture: str, tile: float = 256.0):
        from .state import Selection
        me = fillmod.make_patch(self.opt, poly_engine_xz, y, texture, tile)
        cropmod.add_mesh(self.opt, me)
        self.fills_list().append(dict(mesh=me, pts=[tuple(map(float, p)) for p in poly_engine_xz], y=float(y),
                                      tex=texture, tile=float(tile)))
        self.dirty_map = self.needs_rebake = True
        self.log(f"fill patch: {len(poly_engine_xz)} points, texture {texture}, y={y:.0f}")
        return Selection("mesh", me, "fill patch")

    # ---- fills made in this session stay editable: delete, move all points, edit one point
    def fills_list(self):
        lst = self.__dict__.setdefault("_fills", [])
        lst[:] = [f for f in lst if self.opt is not None and any(m is f["mesh"] for m in self.opt.meshes)]   # undo / delete drops them
        return lst

    def _fill_index(self, f) -> int:
        return next(k for k, m in enumerate(self.opt.meshes) if m is f["mesh"])

    @undoable(True, "delete fill")
    def delete_fill(self, f) -> str:
        i = self._fill_index(f)
        cropmod.remove_meshes(self.opt, {i}, False)
        self.fills_list()
        self.selection = None
        self.dirty_map = self.needs_rebake = True
        return "fill deleted"

    @undoable(True, "edit fill")
    def edit_fill(self, f, pts=None, y=None, dx: float = 0.0, dz: float = 0.0) -> None:
        """Rebuild the patch with new points / height (``dx``, ``dz`` shift every point)."""
        i = self._fill_index(f)
        new_pts = [tuple(p) for p in (pts if pts is not None else f["pts"])]
        new_pts = [(x + dx, z + dz) for x, z in new_pts]
        ny = f["y"] if y is None else float(y)
        cropmod.remove_meshes(self.opt, {i}, False)
        me = fillmod.make_patch(self.opt, new_pts, ny, f["tex"], f["tile"])
        cropmod.add_mesh(self.opt, me)
        f.update(mesh=me, pts=[tuple(map(float, p)) for p in new_pts], y=ny)
        self.dirty_map = self.needs_rebake = True

    # ---------------------------------------------------------------------------------- map parts / textures
    def map_parts(self):
        """Rows describing every static mesh: (index, triangles, [textures], lo, hi, props using it)."""
        users = {}
        for p in self.opt.props:
            users[p.mesh_index] = users.get(p.mesh_index, 0) + 1
        rows = []
        for i, me in enumerate(self.opt.meshes):
            tris = sum(len(sm.indices) // 3 for sm in me.render_submeshes())
            tex = []
            for mat in me.materials:
                for t in mat.textures[:1]:
                    if t and str(t) not in tex:
                        tex.append(str(t))
            lo, hi = cropmod.mesh_bounds(me)
            rows.append((i, tris, tex, lo, hi, users.get(i, 0)))
        return rows

    def map_stem(self) -> str:
        return os.path.splitext(os.path.basename(self.scene.path or self.scene_name))[0]

    def local_texture_name(self, tex: str) -> str:
        """Name for a texture that is only used by this map: <map>__<texture>."""
        base = os.path.splitext(os.path.basename(str(tex).replace("\\", "/")))[0]
        pre = self.map_stem() + "__"
        return base if base.lower().startswith(pre.lower()) else pre + base

    def extract_texture(self, name: str, folder: str, fmt: str = "png") -> str:
        t = self.fs.texture(name)
        if t is None:
            raise FileNotFoundError(name)
        os.makedirs(folder, exist_ok=True)
        base = os.path.splitext(os.path.basename(str(name).replace("\\", "/")))[0]
        if hasattr(t, "to_texture2") and getattr(t, "legacy", False):
            t = t.to_texture2()
        out = os.path.join(folder, base + "." + fmt)
        if fmt == "png":
            t.to_png(out)
        elif fmt == "dds":
            t.save_dds(out)
        else:
            t.save(out)
        return out

    @undoable(True, "replace texture")
    def import_map_texture(self, path: str, replace: Optional[str] = None, mesh_index: Optional[int] = None) -> str:
        """Bring an image (PNG/JPG/BMP/TGA, DDS or .tex) into texs/ under a map-specific name and point the map at it.
        ``replace``: texture name to replace (all meshes of the map that use it, or only ``mesh_index``)."""
        ext = os.path.splitext(path)[1].lower()
        if ext == ".dds":
            t = Texture.from_dds(path)
        elif ext == ".tex":
            t = Texture.load(path)
        else:
            t = Texture.from_png(path, mipmaps=True)
        src = replace or os.path.basename(path)
        name = self.local_texture_name(src if replace else os.path.splitext(os.path.basename(path))[0])
        dst = os.path.join(self.fs.root, "texs", name + ".tex")
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        t.save(dst)
        self.fs.rescan(); self.fs._tex.clear()
        if replace:
            key = os.path.splitext(os.path.basename(str(replace).replace("\\", "/")))[0].lower()
            for i, me in enumerate(self.opt.meshes):
                if mesh_index is not None and i != mesh_index:
                    continue
                for mat in me.materials:
                    for j, tx in enumerate(mat.textures):
                        if os.path.splitext(os.path.basename(str(tx).replace("\\", "/")))[0].lower() == key:
                            mat.textures[j] = name + ".tex"
            self.dirty_map = self.needs_rebake = True
        self.log(f"texture imported as {name}.tex")
        return name + ".tex"

    # ---------------------------------------------------------------------------------- mesh texture
    def mesh_of(self, sel):
        if sel is None:
            return None
        if sel.kind == "mesh":
            return sel.ref
        if sel.kind == "prop" and 0 <= sel.ref.mesh_index < len(self.opt.meshes):
            return self.opt.meshes[sel.ref.mesh_index]
        return None

    @undoable(True, "change texture")
    def set_mesh_texture(self, mesh, material_index: int, name: str) -> str:
        """Point one material of a mesh at another texture (a prop shares its mesh with its siblings)."""
        mat = mesh.materials[material_index]
        old = str(mat.textures[0]) if mat.textures else "(none)"
        if not name.lower().endswith(".tex"):
            name += ".tex"
        if mat.textures:
            mat.textures[0] = name
        else:
            mat.textures = [name]
        if hasattr(mat, "diffuse"):
            try:
                mat.diffuse = name
            except Exception:
                pass
        self.dirty_map = self.needs_rebake = True
        self.log(f"texture {old} -> {name}")
        return name

    # ---------------------------------------------------------------------------------- weather: rain, storm, moon
    # ---------------------------------------------------------------------------------- music (game's musica folder)
    def music_folder(self, create: bool = False) -> str:
        """The ``musica`` folder of the Torrente Online installation (next to demo.vpk); '' when it cannot be found."""
        base = getattr(self, "game_dir", "") or os.path.dirname(os.path.abspath(self.fs.root))
        for d in (base, os.path.dirname(base), self.fs.root):
            for n in ("musica", "Musica", "music"):
                p = os.path.join(d, n)
                if os.path.isdir(p):
                    return p
        if create and base:
            p = os.path.join(base, "musica")
            os.makedirs(p, exist_ok=True)
            return p
        return ""

    def music_files(self) -> List[str]:
        """.ogg and .wav tracks found in the game's musica folder."""
        d = self.music_folder()
        try:
            return sorted((f for f in os.listdir(d) if f.lower().endswith(".ogg")), key=str.lower) if d else []
        except OSError:
            return []

    def import_music(self, src: str) -> str:
        """Copy a .ogg / .wav into the game's musica folder (like the music of the other maps) and return its file name."""
        import shutil
        if not src.lower().endswith((".ogg", ".wav")):
            raise ValueError("only .ogg and .wav music can be imported")
        d = self.music_folder(create=True)
        if not d:
            raise ValueError("musica folder not found")
        dst = os.path.join(d, os.path.basename(src))
        if os.path.abspath(src) != os.path.abspath(dst):
            shutil.copyfile(src, dst)
        self.log(f"music copied to {dst}")
        return os.path.basename(src)

    # ---------------------------------------------------------------------------------- animation keys of animated objects
    def all_keys(self) -> List[str]:
        """Every .KEY of the game as the scenes write it: path inside keys/ with backslashes (``varios\\gramofono.KEY``)."""
        cache = getattr(self, "_all_keys", None)
        if cache is None or cache[0] != len(self.fs.index):          # the index only changes on rescan: do not walk it every frame
            cache = (len(self.fs.index), [p[5:].replace("/", "\\") for p in self.fs.list("keys", ".key")])
            self._all_keys = cache
        return cache[1]

    def key_candidates(self, nfo_rel: str) -> List[str]:
        """Keys that belong to a model: same name, ``Reposo_<name>``, ``<name>_anim`` ... (best first)."""
        stem = os.path.splitext(os.path.basename(nfo_rel.replace("\\", "/")))[0].lower()
        if not stem:
            return []
        score = []
        for k in self.all_keys():
            ks = os.path.splitext(k.split("\\")[-1])[0].lower()
            if ks == stem:
                score.append((0, k))
            elif ks in ("reposo_" + stem, stem + "anim", stem + "_anim", "anim_" + stem):
                score.append((1, k))
            elif len(stem) >= 4 and stem in ks:
                score.append((2, k))
        return [k for _, k in sorted(score)]

    def set_module_key(self, rec, key: str) -> None:
        """Make a (Animated)RenderNFO module play ``key`` (empty = no animation): its tail is ``01 00 00 00 00 01 00 00 00 00`` + key name."""
        from ..binutil import Writer
        p = rec.parsed
        head = bytes(p.tail[:10]) if len(p.tail) >= 10 else bytes.fromhex("01000000000100000000")
        if key:
            w = Writer(); w.sized_string(key)
            p.tail = head + w.bytes()
        else:
            p.tail = head + bytes(12)
        self.dirty_scene = True

    def anim_geometry(self, rec, key, frame: float):
        """Bake only the module ``rec`` posed with ``key`` at ``frame`` (the animation preview)."""
        from ..opt import OptMap
        from ..scn import Scene
        from ..render.geometry import bake_scene
        sc = Scene()
        sc.modules.append(rec)
        return bake_scene(self.fs, sc, OptMap(), anim={id(rec): (key, frame)})

    def music_path(self, name: str = "") -> str:
        name = name or str(self.scene.ambient_music).rstrip("\0")
        d = self.music_folder()
        for cand in (os.path.join(d, name) if d else "", self.fs.find("musica/" + name) or "", self.fs.find(name) or ""):
            if cand and os.path.isfile(cand):
                return cand
        return ""

    # ---------------------------------------------------------------------------------- sound sources (mp_SoundSource)
    def sound_names(self) -> List[str]:
        """Sounds a scene can play: the wavs the Online scenes already use plus the files of the game's ``wavs`` folder."""
        if getattr(self, "_sound_names", None) is None:
            from ..modules import MPSoundSource
            found = set()
            for n in self.scene_names():
                try:
                    sc = self.fs.scene(n)
                except Exception:
                    continue
                for rec in sc.modules:
                    if rec.clean_name.lower() == "mp_soundsource":
                        try:
                            found.add(MPSoundSource.from_bytes(rec.data).wav.replace("/", "\\"))
                        except Exception:
                            pass
            for d in (os.path.join(getattr(self, "game_dir", "") or "", "wavs"), os.path.join(self.fs.root, "wavs")):
                if os.path.isdir(d):
                    found.update("wavs\\" + f for f in os.listdir(d) if f.lower().endswith(".wav"))
            self._sound_names = sorted(found, key=str.lower)
        return self._sound_names

    def add_sound_source(self, wav: str, pos=None, **kw):
        """New looping-style sound at ``pos`` (engine coordinates; default: in front of the camera)."""
        from .. import gamemode
        from .state import Selection
        if pos is None:
            pos = self._here()
        rec = self.add_module("mp_SoundSource", gamemode._new_name(self.scene, "SoundSource"))
        p = rec.parsed
        p.wav = wav if "\\" in wav or "/" in wav else "wavs\\" + wav
        p.position = tuple(float(x) for x in pos)
        for k, v in kw.items():
            setattr(p, k, v)
        self.dirty_scene = True
        self.selection = Selection("module", rec, rec.object_name)
        return rec

    # sound that goes with a model in the shipped maps (mp_dm_asalto: helicoptero_N + Helices_N = HELICOPTERO.wav at the same place)
    MODEL_SOUNDS = {"helicoptero": ("wavs\\HELICOPTERO.wav", "Helices")}

    def default_sound_for(self, model_name: str) -> str:
        stem = os.path.splitext(os.path.basename(str(model_name).replace("\\", "/")))[0].lower()
        return self.MODEL_SOUNDS.get(stem, ("", ""))[0]

    def add_model_sound(self, rec, wav: str = ""):
        """A mp_SoundSource at the position of the module ``rec`` (its sound follows nothing: move both together)."""
        from .. import gamemode
        from .state import Selection
        stem = os.path.splitext(os.path.basename(str(rec.parsed.model_name).replace("\\", "/")))[0].lower()
        default, prefix = self.MODEL_SOUNDS.get(stem, ("", "SoundSource"))
        wav = wav or default
        if not wav:
            names = self.sound_names()
            wav = names[0] if names else "wavs\\HELICOPTERO.wav"
        keep = self.selection
        s = self.add_sound_source(wav, tuple(float(x) for x in rec.parsed.transform[3, :3]), loop=0, interval=0,
                                  max_distance=4448.0, min_distance=25.0)
        s.object_name = gamemode.unique_name(self.scene, prefix + "_1") if prefix != "SoundSource" else s.object_name
        self.log(f"sound {wav} added at the position of {rec.object_name}")
        self.selection = keep
        return s

    @undoable(True, "rebuild floor")
    def rebuild_twin_floor(self, gap: float = 800.0) -> str:
        """For a map made with an older version of the twin ships: build its .hm again from the stock Love Boat one."""
        from .. import twinships
        from ..hm import HeightMap
        from ..opt import OptMap
        hm_p = self.fs.find("nfos/mp_dm_loveboat.hm")
        opt_p = self.fs.find("nfos/mp_dm_loveboat.opt")
        if not hm_p or not opt_p:
            raise ValueError("the stock nfos/mp_dm_loveboat.opt / .hm were not found")
        cur = self._modern_bridges()
        if not cur:                                         # a map from before the ramps: the three default gangplanks
            info = twinships.rebuild_floor(self, OptMap.load(opt_p), HeightMap.load(hm_p), gap, log=self.log)
            return f"floor (.hm) rebuilt: {info['copied']} faces copied - save the map"
        # the ships from the stock floor, then the floor of every gangplank the map really has (added, moved, widened ones too)
        from .. import hmcopy
        info = twinships.rebuild_floor(self, OptMap.load(opt_p), HeightMap.load(hm_p), gap, bridges=(), log=self.log, rails=False)
        panel = self.fs.texture("barandillas_poli.tex") is not None
        for b in cur:
            hmcopy.add_faces(self.hm_edit, twinships.bridge_faces(twinships._lay_of(b, panel), b["z"], b["width"]))
        self._ff_key = self._walk_key = None
        return f"floor (.hm) rebuilt: {info['copied']} faces copied, {len(cur)} gangplanks - save the map"

    def _modern_bridges(self) -> list:
        """The gangplanks with ramps this map has (empty for maps made before the ramps, or not twin ships)."""
        try:
            return [b for b in self.twin_bridges() if b["top"] > b["deck"] + 50.0]
        except Exception:
            return []

    @undoable(True, "rebuild gangplanks")
    def rebuild_twin_gangplanks(self, gap: float = 800.0, rails: bool = False) -> str:
        """For a map made before the ramps: new gangplanks (ramp up, walkway over the rails, ramp down) + floor collision."""
        from .. import twinships
        from ..hm import HeightMap
        from ..opt import OptMap
        hm_p = self.fs.find("nfos/mp_dm_loveboat.hm")
        opt_p = self.fs.find("nfos/mp_dm_loveboat.opt")
        if not hm_p or not opt_p:
            raise ValueError("the stock nfos/mp_dm_loveboat.opt / .hm were not found")
        cur = self._modern_bridges()
        self._undo_off = True
        try:
            if cur:                                          # keep every gangplank where it is (added / moved ones too)
                return self.set_twin_bridges([dict(z=b["z"], width=b["width"], rails=bool(rails)) for b in cur], gap)
            r = twinships.rebuild_gangplanks(self, OptMap.load(opt_p), HeightMap.load(hm_p), gap, log=self.log,
                                             rails=rails)
        finally:
            self._undo_off = False
        return f"gangplanks rebuilt ({r['removed_meshes']} old planks removed) - save the map"

    @undoable(True, "move crates")
    def move_twin_crates(self, gap: float = 800.0, dz: float = -500.0) -> str:
        """The crates at the foot of the middle gangplank, on both ships, ``dz`` along z (-500 = 5 m towards the bow)."""
        from .. import twinships
        from ..opt import OptMap
        opt_p = self.fs.find("nfos/mp_dm_loveboat.opt")
        if not opt_p:
            raise ValueError("the stock nfos/mp_dm_loveboat.opt was not found")
        r = twinships.move_crates(self, OptMap.load(opt_p), gap, dz, log=self.log)
        return f"crates moved: {r['props']} props, {r['boxes']} collision boxes - save the map"

    @undoable(True, "flag base")
    def add_flag_bases(self, recs=None, angle: float = 0.0, replace: bool = False) -> str:
        """Pedestals of mp_b_anderguater under the flags (all mp_Flag modules, or ``recs``), with their floor collision."""
        from .. import flagbase
        peds = flagbase.load_pedestals(self.fs)
        try:
            hm = self.heightmap_edit()
        except ValueError:
            hm = None
        flags = recs or [r for r in self.scene.modules if r.clean_name.lower() == "mp_flag" and r.parsed is not None]
        if not flags:
            raise ValueError("this scene has no mp_Flag")
        msgs = [flagbase.add_base(self.opt, hm, r, peds, angle, replace) for r in flags]
        self.dirty_map = self.dirty_scene = self.needs_rebake = True
        for m in msgs:
            self.log(m)
        return "; ".join(msgs)

    @undoable(False, "mode DLL")
    def set_mode_dll(self, path: str) -> str:
        """Main module = any DLL the user picks (only its file name goes into the scene; the game loads it from its own
        folder).  The file is remembered so 'Export map' packs it, unless it is one of the game's own DLLs."""
        name = os.path.basename(path.strip().strip('"'))
        if not name.lower().endswith(".dll"):
            raise ValueError("pick a .dll file")
        data = open(path, "rb").read(2)
        if data != b"MZ":
            raise ValueError(f"{name} is not a Windows DLL")
        self.scene.main_module_name = VStr((name + "\0").encode("cp1252"))
        self.custom_dlls = dict(getattr(self, "custom_dlls", {}), **{name.lower(): path})
        self.dirty_scene = True
        return f"mode DLL: {name} (it must be in the game folder with the other DLLs)"

    def flag_dll_source(self) -> str:
        """The game's own mp_Flag.dll (next to demo.vpk), or ''."""
        for d in self.dll_search_dirs():
            p = os.path.join(d, "mp_Flag.dll")
            if os.path.isfile(p):
                return p
        return ""

    @undoable(False, "flag DLL")
    def make_flag_dll(self, seconds: float = 0.0, src: str = "", out_dir: str = "") -> str:
        """Dropped flags go back to their base after ``seconds`` (0 = as soon as the carrier dies), on THIS map only:
        a copy ``mp_Flag@<map>.dll`` of the game's mp_Flag.dll with that time (the stock one waits 25 s) is written to the
        export folder and the scene's flags use it.  The original DLL is never modified."""
        from .. import dllpatch
        src = src or self.flag_dll_source()
        if not src or not os.path.isfile(src):
            raise ValueError("mp_Flag.dll not found: pick it in the game folder")
        name = f"mp_Flag@{self.map_stem()}.dll"
        out_dir = out_dir or self.export_dir()
        os.makedirs(out_dir, exist_ok=True)
        dst = os.path.join(out_dir, name)
        rep = dllpatch.patch_flag_return(src, dst, seconds)
        n = 0
        for r in self.scene.modules:
            if r.clean_name.lower() == "mp_flag":
                r.module_name = VStr((name + "\0").encode("cp1252"))
                n += 1
        if not n:
            raise ValueError("this scene has no mp_Flag")
        self.custom_dlls = dict(getattr(self, "custom_dlls", {}), **{name.lower(): dst})
        self.dirty_scene = True
        return (f"{name}: dropped flags return after {rep.new_ms / 1000:.1f} s (was {rep.old_ms / 1000:.0f} s); {n} flags use it. "
                f"Copy it into the game folder (next to mp_Flag.dll) on the server and on every player's PC")

    @undoable(False, "flag DLL")
    def use_stock_flag_dll(self) -> str:
        n = 0
        for r in self.scene.modules:
            if r.clean_name.lower() == "mp_flag" and str(r.module_name).rstrip("\0").lower() != "mp_flag.dll":
                r.module_name = VStr(b"mp_Flag.dll\0")
                n += 1
        self.dirty_scene = True
        return f"{n} flags back to mp_Flag.dll"

    # ---------------------------------------------------------------------------------- health packs: their time
    def health_packs(self) -> list:
        return [r for r in (self.scene.modules if self.scene is not None else []) if r.clean_name.lower() == "mp_salud"]

    def health_settings(self) -> dict:
        """{'packs': how many, 'dll': the DLL they use, 'seconds': how long a picked pack takes to come back with it
        (None when that DLL is not found)}."""
        from .. import dllpatch
        packs = self.health_packs()
        dll = str(packs[0].module_name).rstrip("\0") if packs else "mp_salud.dll"
        sec = None
        src = self.find_game_dll(dll)
        if src:
            try:
                sec = dllpatch.health_respawn(open(src, "rb").read())
            except (OSError, ValueError):
                sec = None
        return {"packs": len(packs), "dll": dll, "seconds": sec}

    def make_health_dll(self, seconds: float, src: str = "", out_dir: str = "") -> str:
        """The health packs of THIS map come back ``seconds`` after they are picked up (the game: 5 s, in mp_salud.dll):
        a copy ``mp_salud@<map>.dll`` with that time is written to the export folder and the scene's packs use it.
        The game's DLL is never modified."""
        from .. import dllpatch
        packs = self.health_packs()
        if not packs:
            raise ValueError("this scene has no health packs (mp_salud)")
        src = src or self.find_game_dll("mp_salud.dll")
        if not src or not os.path.isfile(src):
            raise ValueError("mp_salud.dll not found: pick it in the game folder")
        name = f"mp_salud@{self.map_stem()}.dll"
        out_dir = out_dir or self.export_dir()
        os.makedirs(out_dir, exist_ok=True)
        dst = os.path.join(out_dir, name)
        if os.path.abspath(dst).lower() == os.path.abspath(src).lower():
            raise ValueError("the copy would be written over its source")
        old, new = dllpatch.patch_health_respawn(src, dst, seconds)
        self.push_undo(False, "health DLL")
        for r in packs:
            r.module_name = VStr((name + "\0").encode("cp1252"))
        self.custom_dlls = dict(getattr(self, "custom_dlls", {}), **{name.lower(): dst})
        self.dirty_scene = True
        return (f"{name}: a health pack comes back {new:g} s after it is picked up (the game: {old:g} s); {len(packs)} packs "
                f"use it. Copy it into the game folder (next to mp_salud.dll) on the server and on every player's PC")

    def use_stock_health_dll(self) -> str:
        self.push_undo(False, "health DLL")
        n = 0
        for r in self.health_packs():
            if str(r.module_name).rstrip("\0").lower() != "mp_salud.dll":
                r.module_name = VStr(b"mp_salud.dll\0")
                n += 1
        self.dirty_scene = True
        return f"{n} health packs back to mp_salud.dll (5 s)"

    def module_search_text(self, rec) -> str:
        """Everything a module can be found by: its kind (mp_Door), its object name and the text it holds (model, sounds,
        animations, texture, ...), in lower case."""
        parts = [rec.clean_name, str(rec.module_name), str(rec.object_name)]
        obj = rec.parsed
        if obj is not None:
            for k, v in (vars(obj).items() if hasattr(obj, "__dict__") else []):
                if isinstance(v, (str, bytes)):
                    parts.append(v.decode("cp1252", "replace") if isinstance(v, bytes) else v)
                elif isinstance(v, (list, tuple)):
                    parts += [x.decode("cp1252", "replace") if isinstance(x, bytes) else x for x in v if isinstance(x, (str, bytes))]
            kind = getattr(obj, "KIND", "")
            if kind:
                parts.append(str(kind))
        return " ".join(p.replace("\0", " ") for p in parts).lower()

    def find_modules(self, query: str) -> list:
        """The modules whose kind, name or text has every word of ``query`` (any case; empty = all)."""
        words = [w for w in str(query).lower().split() if w]
        mods = list(self.scene.modules) if self.scene is not None else []
        if not words:
            return mods
        return [r for r in mods if all(w in self.module_search_text(r) for w in words)]

    def select_modules(self, recs) -> str:
        """Select these modules together (locked / hidden ones are left out)."""
        from .state import Selection
        sels = [Selection("module", r, str(r.object_name).rstrip("\0")) for r in recs
                if not self.is_locked(r) and not self.is_hidden(r)]
        self.selection = sels[0] if sels else None
        self.multi = sels[1:]
        return f"{len(sels)} modules selected"

    def scene_dll_names(self) -> List[str]:
        """Names of every DLL the scene uses: its main (mode) DLL and the DLL of each kind of module, once each."""
        out, seen = [], set()
        names = [str(self.scene.main_module_name).rstrip("\0")] + [str(r.module_name).rstrip("\0") for r in self.scene.modules]
        for n in names:
            if n and n.lower().endswith(".dll") and n.lower() not in seen:
                seen.add(n.lower())
                out.append(n)
        return out

    def game_dll_dir(self) -> str:
        """The folder where the game keeps its DLLs (comun/bin/release of the installation when found), for installing."""
        best = ""
        for d in self.dll_search_dirs():
            try:
                n = sum(1 for f in os.listdir(d) if f.lower().startswith("mp_") and f.lower().endswith(".dll"))
            except OSError:
                continue
            if n and (not best or "release" in d.lower() and "release" not in best.lower()):
                best = d
        return best

    def custom_module_dlls(self) -> list:
        """Paths of patched module DLLs (``type@tag.dll``) the scene uses, for the export."""
        out = []
        for r in self.scene.modules:
            nm = str(r.module_name).rstrip("\0")
            if "@" in nm:
                p = getattr(self, "custom_dlls", {}).get(nm.lower()) or os.path.join(self.export_dir(), nm)
                if os.path.isfile(p) and p not in out:
                    out.append(p)
        return out

    @undoable(False, "mode DLL")
    def use_standard_mode_dll(self) -> str:
        """Main module = the generic DLL of the scene's game mode (mp_b_* -> mp_CaptureTheFlag.dll).  The Love Boat's own
        mp_CaptureLoveboat.dll is made for the stock ship and may expect its flags / bases where they were."""
        from .. import gamemode
        mode = self.game_mode() or "B"
        dll = gamemode.MODES[mode][1]
        self.scene.main_module_name = VStr((dll + "\0").encode("cp1252"))
        self.dirty_scene = True
        return f"mode DLL: {dll}"

    @undoable(True, "twin ships")
    def make_twin_ships(self, gap: float = 800.0, per_team: int = 16, tint_ships: bool = True, standard_dll: bool = True,
                        rails: bool = False) -> str:
        """Capture the flag on two Love Boat ships side by side, joined by gangplanks (see vtoy.twinships)."""
        from .. import twinships
        self._undo_off = True
        try:
            r = twinships.build(self, gap=gap, per_team=per_team, tint_ships=tint_ships, rails=rails, log=self.log)
            if standard_dll:
                self.log(self.use_standard_mode_dll())
        finally:
            self._undo_off = False
        return (f"twin ships: {r['copied']}; {r['modules']} modules; spawns {r['spawns']}; {r['bridges']} gangplanks; "
                f"bulwark pieces opened {r['bulwark_cuts']}; floor (.hm) {r['hm']}; tinted {r['tinted_materials']}")

    def rain_dll_sources(self):
        """Stock mode DLLs that can rain, found next to the game data (``dll`` folders of the installation) or given by the user."""
        from .. import dllpatch
        return dllpatch.RAIN_DLLS.get(self.game_mode() or "DM", [])

    def make_rain_dll(self, src_dll: str, out_dir: str) -> str:
        """Rain / storm: write a copy of the mode DLL ``src_dll`` whose weather check matches THIS map, and make the scene use it.
        The original DLL is never modified; the copy is named ``<DLL>_<map>.dll`` and must be placed where the game loads its DLLs."""
        import os
        from .. import dllpatch
        stem = os.path.splitext(os.path.basename(str(self.scene.map_name).rstrip("\0").replace("\\", "/")))[0]
        base = os.path.splitext(os.path.basename(src_dll))[0]
        name = f"{base}_{stem}.dll"
        os.makedirs(out_dir, exist_ok=True)
        rep = dllpatch.patch_map_name(src_dll, os.path.join(out_dir, name), "nfos\\" + stem + ".opt")
        self.scene.main_module_name = VStr((name + "\0").encode("cp1252"))
        self.custom_dlls = dict(getattr(self, "custom_dlls", {}), **{name.lower(): os.path.join(out_dir, name)})
        self.dirty_scene = True
        msg = f"{name}: {rep.references} references patched ({rep.weather}); copy it next to the original DLLs of the game"
        self.log(msg)
        return msg

    @undoable(False, "storm sky")
    def storm_preset(self) -> str:
        """Marbella's look: sky cielo_war + its dark fog (the rain itself comes from the patched DLL)."""
        self.set_sky("cielo_war.tex", True)
        self.dirty_scene = self.dirty_map = True
        return "storm: cielo_war sky + dark fog (Marbella)"

    def moon(self):
        return cropmod.moon_decal(self.opt)

    @undoable(True, "moon")
    def set_moon(self, on: bool, pos=None, size: float = 2000.0):
        """The moon of the Moonlight maps is a decal called 'luna' placed high in the sky."""
        from ..opt import Decal
        cur = cropmod.moon_decal(self.opt)
        if not on:
            if cur is not None:
                cropmod.remove_decal(self.opt, cur)
            self.dirty_map = self.needs_rebake = True
            return None
        if cur is not None:
            return cur
        if pos is None:
            f = self.camera.front
            pos = (self.camera.pos + f * 6000.0) * [1, 1, -1]
            pos[1] = max(pos[1], 4000.0)
        d = Decal(name="luna", position=np.array(pos, np.float32), scale_x=size, scale_y=size, z_offset=1.0)
        cropmod.add_decal(self.opt, d)
        self.dirty_map = self.needs_rebake = True
        self.log("moon added (decal 'luna'); move it with the decal fields")
        return d

    # ---------------------------------------------------------------------------------- custom sky
    def import_sky_png(self, png: str, name: str) -> str:
        """PNG -> texs/<name>.tex (DXT with mips) and make it the scene's sky."""
        name = os.path.splitext(os.path.basename(name))[0] or "cielo_nuevo"
        t = Texture.from_png(png, mipmaps=True)
        dst = os.path.join(self.fs.root, "texs", name + ".tex")
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        t.save(dst)
        self.fs.rescan(); self.fs._tex.clear()
        self._skies = None
        self.set_sky(name + ".tex", False)
        self.needs_rebake = True
        self.log(f"sky imported: {name}.tex ({t.width}x{t.height})")
        return name + ".tex"

    def export_sky_png(self, folder: str) -> str:
        cur = str(self.scene.sky_texture).rstrip("\0")
        return self.extract_texture(cur, folder, "png")

    # ---------------------------------------------------------------------------------- replace a texture with an image
    def replace_texture_from_image(self, tex_name: str, image_path: str, keep_size: bool = True) -> str:
        """Any image (PNG / JPG / BMP / TGA) -> the .tex ``tex_name`` in the SAME format as the one it replaces (DXT1 or
        DXT5, same mip levels, same size unless ``keep_size`` is off: then it is rounded to multiples of 4).
        The old file is kept once as ``.tex.bak``."""
        from PIL import Image
        t = self.fs.texture(tex_name)
        if t is None:
            raise ValueError(f"texture {tex_name} not found")
        base = os.path.splitext(os.path.basename(tex_name.replace("\\", "/")))[0]
        dst = self.fs.find(f"texs/{base}.tex")
        if not dst:
            raise ValueError(f"texs/{base}.tex not found")
        im = Image.open(image_path).convert("RGBA")
        if keep_size:
            w, h = t.width, t.height
        else:
            w, h = max(4, im.width // 4 * 4), max(4, im.height // 4 * 4)
        if im.size != (w, h):
            im = im.resize((w, h), Image.LANCZOS)
        rgba = np.array(im, np.uint8)
        new = type(t).from_rgba(rgba, t.fmt, mipmaps=t.mip_count > 1)
        if not os.path.exists(dst + ".bak"):
            shutil.copy2(dst, dst + ".bak")
        with open(dst, "wb") as f:
            f.write(new.to_bytes())
        self.fs._tex.clear()
        kind = ("DXT5" if t.fmt else "DXT1") if type(t).__name__ == "Texture" else "TeX1"
        return f"{base}.tex replaced from {os.path.basename(image_path)}: {w}x{h} {kind}, mips={new.mip_count} (backup .tex.bak)"

    # --- per-map textures: the map's own copy, the shared file stays as it is
    @staticmethod
    def _tex_base(n) -> str:
        return os.path.splitext(os.path.basename(str(n).rstrip("\0").replace("\\", "/")))[0]

    @staticmethod
    def _swap_base(name: str, old_base: str, new_base: str) -> str:
        """Same string (folder, extension, case of the extension) with the file name ``old_base`` changed to ``new_base``."""
        s = str(name).rstrip("\0")
        head, tail = os.path.split(s.replace("\\", "/"))
        root, ext = os.path.splitext(tail)
        out = (head + "/" if head else "") + new_base + ext
        return out.replace("/", "\\") if "\\" in s else out

    def map_texture_users(self, base: str) -> list:
        """Where THIS map uses the texture ``base``: ('mat', material) of its meshes and ('decal', decal)."""
        key = base.lower()
        out = []
        for me in (self.opt.meshes if self.opt else []):
            for mat in me.materials:
                if mat.textures and self._tex_base(mat.textures[0]).lower() == key:
                    out.append(("mat", mat))
        for d in (self.opt.decals if self.opt else []):
            if self._tex_base(d.name).lower() == key:
                out.append(("decal", d))
        return out

    def _retarget(self, users, old_base: str, new_base: str) -> int:
        for kind, o in users:
            if kind == "mat":
                o.textures[0] = self._swap_base(o.textures[0], old_base, new_base)
            else:
                o.name = self._swap_base(o.name, old_base, new_base)
        self.dirty_map = self.needs_rebake = True
        return len(users)

    @undoable(True, "map texture")
    def replace_texture_for_map(self, tex_name: str, image_path: str, keep_size: bool = True) -> str:
        """The image becomes a NEW texture ``<map>__<texture>.tex`` (same DXT format / mips / size as the original) and only
        this map's meshes and decals use it.  The original .tex, and every other map, stay as they were."""
        from PIL import Image
        base = self._tex_base(tex_name)
        orig_base = base[len(self.map_stem()) + 2:] if base.lower().startswith(self.map_stem().lower() + "__") else base
        t = self.fs.texture(base) or self.fs.texture(orig_base)
        if t is None:
            raise ValueError(f"texture {tex_name} not found")
        users = self.map_texture_users(base)
        if not users:
            raise ValueError(f"{base} is not used by the map's meshes or decals (it belongs to a model .nfo): "
                             "use 'for all maps' to change it")
        new_base = self.local_texture_name(orig_base)
        src_file = self.fs.find(f"texs/{orig_base}.tex") or self.fs.find(f"texs/{base}.tex")
        folder = os.path.dirname(src_file) if src_file else os.path.join(self.fs.root, "texs")
        im = Image.open(image_path).convert("RGBA")
        w, h = (t.width, t.height) if keep_size else (max(4, im.width // 4 * 4), max(4, im.height // 4 * 4))
        if im.size != (w, h):
            im = im.resize((w, h), Image.LANCZOS)
        new = type(t).from_rgba(np.array(im, np.uint8), t.fmt, mipmaps=t.mip_count > 1)
        dst = os.path.join(folder, new_base + ".tex")
        with open(dst, "wb") as f:
            f.write(new.to_bytes())
        n = self._retarget(users, base, new_base)
        self.fs.rescan(); self.fs._tex.clear()
        return (f"{new_base}.tex made from {os.path.basename(image_path)} ({w}x{h}); {n} uses in this map point at it. "
                f"{orig_base}.tex is unchanged for the other maps - save the map")

    @undoable(True, "original texture")
    def back_to_original_texture(self, tex_name: str) -> str:
        """This map's own copy (<map>__X) -> the original texture X again (the copy file is kept)."""
        base = self._tex_base(tex_name)
        pre = self.map_stem() + "__"
        if not base.lower().startswith(pre.lower()):
            raise ValueError("this is already the original texture")
        orig = base[len(pre):]
        n = self._retarget(self.map_texture_users(base), base, orig)
        return f"{n} uses back to {orig}.tex - save the map"

    def restore_texture(self, tex_name: str) -> str:
        base = os.path.splitext(os.path.basename(tex_name.replace("\\", "/")))[0]
        dst = self.fs.find(f"texs/{base}.tex")
        if not dst or not os.path.exists(dst + ".bak"):
            raise ValueError("no backup of this texture")
        shutil.copy2(dst + ".bak", dst)
        self.fs._tex.clear()
        return f"{base}.tex restored from its backup"

    # ---------------------------------------------------------------------------------- map preview (<map>-tbn.tex)
    def preview_name(self) -> str:
        return self.map_stem() + "-tbn"

    def load_preview_image(self, path: str) -> np.ndarray:
        """Any image file -> 256x256 RGBA (centre square, resized) ready for ``save_preview``."""
        from PIL import Image
        im = Image.open(path).convert("RGBA")
        w, h = im.size
        side = min(w, h)
        im = im.crop(((w - side) // 2, (h - side) // 2, (w - side) // 2 + side, (h - side) // 2 + side)).resize((256, 256), Image.LANCZOS)
        out = np.array(im, np.uint8)
        out[..., 3] = 255
        return out

    def save_preview(self, rgba: np.ndarray, fmt: str = "tex") -> str:
        """256x256 map thumbnail. fmt 'tex' -> texs/<map>-tbn.tex (what the game's map menu reads), 'dds' -> same name .dds."""
        t = Texture.from_rgba(rgba, mipmaps=True)
        folder = os.path.join(self.fs.root, "texs")
        os.makedirs(folder, exist_ok=True)
        out = os.path.join(folder, self.preview_name() + "." + fmt)
        found = self.fs.find(f"texs/{self.preview_name()}.{fmt}")
        if found and os.path.abspath(found) != os.path.abspath(out):
            out = found                                  # the preview lives in a sub-folder: replace it there
        if os.path.exists(out):                          # always replaced; the one it had becomes <name>.tex.bak
            if os.path.exists(out + ".bak"):
                os.remove(out + ".bak")
            os.replace(out, out + ".bak")
        if fmt == "dds":
            t.save_dds(out)
        else:
            t.save(out)
        self.fs.rescan(); self.fs._tex.clear()
        self.log(f"preview saved: {out}")
        return out

    # ---------------------------------------------------------------------------------- export one map as a zip
    def map_dependencies(self) -> List[str]:
        """Relative paths (inside the game folder) of every file this scene needs."""
        fs, sc = self.fs, self.scene
        files, missing = [], []

        def add(rel, quiet=False):
            p = fs.find(rel)
            if p is None:
                if not quiet and rel not in missing:
                    missing.append(rel)
                return None
            r = os.path.relpath(p, fs.root).replace("\\", "/")
            if r not in files:
                files.append(r)
            return r

        def add_tex(name):
            base = os.path.splitext(os.path.basename(str(name).replace("\\", "/").rstrip("\0")))[0]
            if base and base != "<null>":
                add(f"texs/{base}.tex")

        add(f"scns/{os.path.basename(sc.path)}") if sc.path else None
        if sc.path and not files:
            files.append("scns/" + os.path.basename(sc.path))
        mp = str(sc.map_name).rstrip("\0")
        if mp:
            add(mp)
            hm = os.path.splitext(mp)[0] + ".hm"
            add(hm)
        if str(sc.heightmap_name).rstrip("\0"):
            add(str(sc.heightmap_name).rstrip("\0"))
        add_tex(sc.sky_texture)
        for me in self.opt.meshes:                 # only materials a triangle uses (unused ones are not exported)
            used_mats = {sm.material_index for lod in me.lods for part in lod.parts for sm in part.submeshes}
            for mi, mat in enumerate(me.materials):
                if mi not in used_mats and used_mats:
                    continue
                for t in mat.textures:
                    add_tex(t)
        for d in self.opt.decals:
            add_tex(d.name)
        def add_model(mn):
            mn = mn.replace("\\", "/")
            rel = mn if mn.lower().startswith("nfos/") else "nfos/" + mn
            if add(rel):
                try:
                    model = fs.model(rel)
                except Exception:
                    model = None
                for obj in (model.objects if model else []):
                    for mat in getattr(obj, "materials", []):
                        add_tex(mat.texture)
                # animations the game's DLLs load by the model's name (not written in the scene): <name>.KEY, Reposo_<name>.KEY ...
                stem = os.path.splitext(os.path.basename(rel))[0].lower()
                for k in self.all_keys():
                    ks = os.path.splitext(k.split("\\")[-1])[0].lower()
                    if stem and ks in (stem, "reposo_" + stem, stem + "anim", stem + "_anim", "anim_" + stem):
                        add("keys/" + k.replace("\\", "/"), quiet=True)

        def add_key(kn):
            kn = kn.replace("\\", "/").lstrip("/")
            add(kn if kn.lower().startswith("keys/") else "keys/" + kn)          # scenes write them relative to keys/

        import re as _re
        name_rx = _re.compile(rb"([\x20-\x7e\x80-\xff]{1,150}?\.(nfo|key|tex|wav))\x00", _re.I)
        wavs = []
        for rec in sc.modules:
            p = rec.parsed
            mn = str(getattr(p, "model_name", "") or "").rstrip("\0")
            if mn:
                add_model(mn)
            # everything else a module names: every animation of its tail (doors and buttons have two), particle textures,
            # the models / keys of module kinds the editor does not take apart, the sound of a sound source
            try:
                raw = bytes(rec.data) if p is None else p.to_bytes()
            except Exception:
                raw = bytes(rec.data or b"")
            for m in name_rx.finditer(raw):
                name, ext = m.group(1).decode("cp1252", "replace").strip(), m.group(2).lower()
                if ext == b"key":
                    add_key(name)
                elif ext == b"nfo":
                    if name.replace("\\", "/").lower() != mn.replace("\\", "/").lower():
                        add_model(name)
                elif ext == b"tex":
                    add_tex(name)
                elif name not in wavs:
                    wavs.append(name)
        self._dep_wavs = wavs
        prev = fs.find(f"texs/{self.preview_name()}.tex")
        if prev:
            add(f"texs/{self.preview_name()}.tex")
        self._missing_deps = missing
        return files

    def export_dir(self) -> str:
        """The one folder everything is exported to: ``export`` next to demo.vpk, or ``export_dir`` of vtoy_editor.json."""
        from .. import settings
        base = os.path.dirname(os.path.abspath(self.fs.root))
        custom = str(settings.load().get("export_dir", "") or "").strip()
        if custom:
            return custom if os.path.isabs(custom) else os.path.join(base, custom)
        return os.path.join(base, "export")

    def wav_folders(self) -> List[str]:
        """Where the game keeps its sounds: ``wavs`` next to demo.vpk and / or inside the unpacked data."""
        base = getattr(self, "game_dir", "") or os.path.dirname(os.path.abspath(self.fs.root))
        return [d for d in (os.path.join(base, "wavs"), os.path.join(self.fs.root, "wavs")) if os.path.isdir(d)]

    def wav_path(self, name: str) -> str:
        """Full path of a sound a scene names (``wavs\\x.wav``), or ''."""
        rel = name.replace("\\", "/").lstrip("/")
        found = self.fs.find(rel) or self.fs.find("wavs/" + os.path.basename(rel))
        if found:
            return found
        want = os.path.basename(rel).lower()
        for d in self.wav_folders():
            for f in os.listdir(d):
                if f.lower() == want:
                    return os.path.join(d, f)
        return ""

    def dll_search_dirs(self) -> List[str]:
        """Folders where the game's DLLs can be: next to demo.vpk, and ``comun/bin/release`` (or ``bin/release``) of the
        installation - looked for from the data folder upwards."""
        out = []
        start = [getattr(self, "game_dir", "") or "", os.path.abspath(self.fs.root)]
        for d in start:
            for _ in range(5):
                if not d:
                    break
                for sub in ("", "dll", os.path.join("comun", "bin", "release"), os.path.join("bin", "release"), "release"):
                    c = os.path.join(d, sub) if sub else d
                    if os.path.isdir(c) and c not in out:
                        out.append(c)
                nd = os.path.dirname(d)
                if nd == d:
                    break
                d = nd
        return out

    def find_game_dll(self, name: str) -> str:
        """Full path of a DLL a scene names: the copy this session made / loaded, the export folder, then the game's folders
        (see dll_search_dirs). '' when it is nowhere."""
        name = str(name).rstrip("\0")
        if not name:
            return ""
        cands = [getattr(self, "custom_dlls", {}).get(name.lower()), os.path.join(self.export_dir(), name),
                 self.fs.find("dll/" + name), self.fs.find(name)]
        for c in cands:
            if c and os.path.isfile(c):
                return c
        low = name.lower()
        for d in self.dll_search_dirs():
            try:
                for f in os.listdir(d):
                    if f.lower() == low and os.path.isfile(os.path.join(d, f)):
                        return os.path.join(d, f)
            except OSError:
                continue
        return ""

    def custom_dll_path(self):
        """Path of the scene's main DLL when it is not one of the 4 stock mode DLLs (e.g. the rain copy), else None."""
        from .. import gamemode
        name = str(self.scene.main_module_name).rstrip("\0")
        if name.lower() in {m[1].lower() for m in gamemode.MODES.values()}:
            return None
        c = self.find_game_dll(name)
        if c:
            return c
        self.log(f"WARNING: the scene uses the DLL '{name}' and it was not found to export it with the map (looked in: "
                 + " | ".join(self.dll_search_dirs()[:6]) + ")")
        return None

    def export_map_zip(self, out_zip: str) -> dict:
        """Save the working files first (the caller does), then zip scene + map + hm + textures + models + keys + preview."""
        files = self.map_dependencies()
        os.makedirs(os.path.dirname(os.path.abspath(out_zip)), exist_ok=True)
        with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as z:
            for rel in files:
                p = self.fs.find(rel) or os.path.join(self.fs.root, rel)
                if os.path.exists(p):
                    z.write(p, rel)
            # every DLL the scene uses: the mode DLL and the DLL of each kind of module (stock ones from comun/bin/release
            # too), and the patched copies (e.g. mp_Flag@<map>.dll)
            dlls = [d for d in [self.custom_dll_path()] + self.custom_module_dlls() if d]
            for name in self.scene_dll_names():
                p = self.find_game_dll(name)
                if p:
                    dlls.append(p)
                elif "dll/" + name not in self._missing_deps:
                    self._missing_deps.append("dll/" + name)
            seen = set()
            from .. import dllpatch as _dp
            for d in dlls:
                rel = "dll/" + os.path.basename(d)
                if rel.lower() in seen:
                    continue
                seen.add(rel.lower())
                z.write(d, rel)
                files = files + [rel]
                try:                                         # the map's quieter storm sounds its DLL copy loads
                    snds = _dp.shower_sound_names(open(d, "rb").read())
                except (OSError, ValueError):
                    snds = []
                for nm in snds:
                    srel = "wavs/" + os.path.basename(nm.replace("\\", "/"))
                    if srel in files:
                        continue
                    cands = [getattr(self, "custom_wavs", {}).get(nm.lower()),
                             os.path.join(self.export_dir(), "wavs", os.path.basename(srel)), self.wav_path(nm)]
                    wp = next((c for c in cands if c and os.path.isfile(c)), "")
                    if wp:
                        z.write(wp, srel)
                        files = files + [srel]
                    elif srel not in self._missing_deps:
                        self._missing_deps.append(srel)
            mus = str(self.scene.ambient_music).rstrip("\0")
            mf = os.path.join(self.music_folder(), mus) if mus and self.music_folder() else ""
            if mf and os.path.isfile(mf):                    # music the map uses that lives in the game's musica folder
                z.write(mf, "musica/" + mus)
                files = files + ["musica/" + mus]
            elif mus:
                self._missing_deps.append("musica/" + mus)
            for wav in getattr(self, "_dep_wavs", []):       # sounds of the sound sources (the game keeps them outside the VPK)
                wp = self.wav_path(wav)
                rel = "wavs/" + os.path.basename(wp or wav.replace("\\", "/"))
                if wp and rel not in files:
                    z.write(wp, rel)
                    files = files + [rel]
                elif not wp and rel not in self._missing_deps:
                    self._missing_deps.append(rel)
            import json as _json
            z.writestr("vtoy_manifest.json", _json.dumps({
                "map": self.map_stem(), "editor": "VToyEditor Plus+", "files": files,
                "note": "scns/ nfos/ texs/ keys/ go into the unpacked game data (then repack demo.vpk); dll/ into the game "
                        "folder; musica/ and wavs/ into the game's music and sound folders. The editor does it: File > Install "
                        "map from zip."},
                indent=1))
        kinds = {}
        for f in files:
            kinds[f.split("/")[0]] = kinds.get(f.split("/")[0], 0) + 1
        self.export_summary = ", ".join(f"{n} {k}" for k, n in sorted(kinds.items()))
        self.log(f"exported {len(files)} files to {out_zip} ({self.export_summary})")
        return {"files": files, "missing": list(getattr(self, "_missing_deps", []))}
