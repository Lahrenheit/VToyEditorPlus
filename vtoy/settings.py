"""User settings in ONE editable JSON file, ``vtoy_editor.json``, next to ``imgui.ini`` (the file that keeps the window layout):
the folder of the .exe when frozen, otherwise the current folder.  Open it with any text editor; the editor re-reads it on start.

    language            "en" | "es" | "pt" | any file added to vtoy/language
    export_dir          where everything is exported ("" = a folder called ``export`` next to demo.vpk); relative paths are
                        relative to the folder that holds demo.vpk
    restore_last_scene  open the map you were working on when the editor starts
    restore_last_view   put the camera where it was when you closed the editor
    last_scene, last_view, last, library   remembered by the editor itself
"""
from __future__ import annotations

import json
import os
import sys

DEFAULTS = {
    "language": "en",
    "export_dir": "",
    "restore_last_scene": True,
    "restore_last_view": True,
}


def path() -> str:
    base = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.getcwd()
    return os.path.join(base, "vtoy_editor.json")


def _legacy() -> dict:
    try:
        with open(os.path.join(os.path.expanduser("~"), ".vtoy_editor.json")) as f:
            return json.load(f)
    except Exception:
        return {}


def load() -> dict:
    d = dict(DEFAULTS)
    p = path()
    try:
        with open(p, encoding="utf-8") as f:
            d.update(json.load(f))
    except FileNotFoundError:
        d.update(_legacy())               # first run with this file: bring over the old hidden settings
        save(d)
    except Exception:
        pass
    return d


def save(d: dict) -> None:
    try:
        with open(path(), "w", encoding="utf-8") as f:
            json.dump(d, f, indent=2, ensure_ascii=False)
    except OSError:
        pass


def get(key: str, default=None):
    return load().get(key, DEFAULTS.get(key, default) if default is None else default)


def set(key: str, value) -> None:                 # noqa: A001 - mirrors dict API
    d = load()
    if d.get(key) != value:
        d[key] = value
        save(d)
