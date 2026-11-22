"""'Torrente, el juego' scenes do not name their level geometry the way the online ones do.

* Main scenes carry the marker ``SCENE`` (and their sub-scenes ``SUBSCENE``) instead of a file name; the level DLL named in
  ``main_module_name`` loads the map itself (found with ``strings`` in the DLLs shipped with the old game, e.g.
  Marbella_f04.dll -> nfos/marbella.opt + nfos/marbella.hm).
* Some scenes name the map as ``nfos/madrid.nfo`` while the file is really ``nfos/madrid.opt``.
Sub-scenes (``..._d01``, ``..._m03``...) share their main scene's DLL, so they resolve to the same level."""
from __future__ import annotations

import os
from typing import Callable, Optional

# level DLL (lower case, no extension) -> map name (without extension) inside nfos/
LEVEL_MAPS = {
    "comercial": "comercial",
    "entrenamiento": "pista",
    "fase_spinelli": "fase_spinelli",
    "fase_cuco": "cuco",
    "madrid_f03": "madrid", "madrid_f04": "madrid", "madrid_franco": "madrid", "madrid_kio": "madrid",
    "marbella_f01": "marbella", "marbella_f03": "marbella", "marbella_f04": "marbella",
    "marbella_f02": "marbella_miss",
    "marbella_chalets": "spinelli_chalets",
    "marbella_malibu": "malibu",
}


def resolve_map(scene, exists: Callable[[str], bool]) -> str:
    """Name to pass to ``GameFS.map`` for ``scene`` (the scene itself is not modified)."""
    name = str(scene.map_name).strip()
    if name and exists(name):
        return name
    stem, ext = os.path.splitext(name.replace("\\", "/"))
    if ext.lower() == ".nfo" and exists(stem + ".opt"):
        return stem + ".opt"
    main = os.path.splitext(str(scene.main_module_name).strip())[0].lower()
    target = LEVEL_MAPS.get(main)
    if target and exists(f"nfos/{target}.opt"):
        return f"nfos/{target}.opt"
    return name
