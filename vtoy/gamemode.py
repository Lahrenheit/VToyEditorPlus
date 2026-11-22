"""Game modes of Torrente Online and the helpers to make a scene playable in each of them.

Everything here is inferred from the scenes shipped in demo.vpk (mp_dm_*, mp_dmt_*, mp_do_*, mp_b_*): the main module a scene
names in its descriptor decides the mode, and the modules a mode needs are the ones every scene of that mode contains.
Payload layouts of flags / health packs / bomb zones are cloned from a real Online scene (``Templates``)."""
from __future__ import annotations

import copy
import math
import os
from typing import Dict, List, Optional, Tuple

import numpy as np

from .binutil import VStr
from .catalog import load_scenes
from .modules import MPStartPoint, parse_modules
from .scn import ModuleRecord, Scene

# code -> (label, main module of the standard scenes, prefix of the scene files)
MODES: Dict[str, Tuple[str, str, str]] = {
    "DM": ("Deathmatch (single)", "mp_deathMatch.dll", "mp_dm_"),
    "DMT": ("Team deathmatch", "mp_deathMatchTeam.dll", "mp_dmt_"),
    "DO": ("Destroy the target", "mp_DestroyTheTarget.dll", "mp_do_"),
    "B": ("Capture the flag", "mp_CaptureTheFlag.dll", "mp_b_"),
}
MIN_STARTS = {"DM": 8, "DMT": 8, "B": 8, "DO": 16}
MEDIKIT = {"big": ("nfos/ITEM_Medikit.NFO", 50), "small": ("nfos/ITEM_MiniMedikit.NFO", 25)}
FLAG_TEAMS = {0: "bandera_amarilla", 1: "bandera_roja"}

# music names used by Online scenes (the .wav files live in the game's musica/ folder, not in demo.vpk)
KNOWN_MUSIC = ["AQUATICA.wav", "ASALTO.wav", "CONEXION TORRENTE.wav", "LOVE_BOAT.wav", "OPERATION-T.wav",
               "TORRENTE QUE HOSTIAS PASA.wav", "coliseum.wav", "gothic.wav", "industrializer.wav",
               "mision torrente.wav", "museo.wav", "plaza.wav", "rythm'n.wav", "torrente en un tren.wav"]


def mode_of(scene: Scene) -> Optional[str]:
    main = str(scene.main_module_name).rstrip("\0").lower()
    for code, (_, m, _) in MODES.items():
        if main == m.lower():
            return code
    for code, key in (("DMT", "team"), ("DO", "destroy"), ("B", "capture"), ("DM", "death")):
        if key in main:
            return code
    return None


def set_mode(scene: Scene, code: str) -> None:
    scene.main_module_name = VStr((MODES[code][1] + "\0").encode("cp1252"))


def _new_name(scene: Scene, base: str) -> str:
    """Object names must be unique (the game looks modules up by name, ignoring case): base_1, base_2 ..."""
    used = {str(m.object_name).rstrip("\0").lower() for m in scene.modules}
    i = 1
    while f"{base}_{i}".lower() in used:
        i += 1
    return f"{base}_{i}"


def unique_name(scene: Scene, wanted: str) -> str:
    """``wanted`` itself when free, otherwise the next free ``<wanted without trailing number>_N``."""
    used = {str(m.object_name).rstrip("\0").lower() for m in scene.modules}
    if wanted.lower() not in used:
        return wanted
    import re
    return _new_name(scene, re.sub(r"[_ ]?\d+$", "", wanted) or wanted)


class Templates:
    """First module of every kind found in a folder of Online scenes (deep-copied when used)."""

    def __init__(self, scn_folder: Optional[str]):
        self.by_kind: Dict[str, ModuleRecord] = {}
        self.flags: Dict[int, ModuleRecord] = {}
        for sc in load_scenes(scn_folder):
            parse_modules(sc)
            for r in sc.modules:
                k = r.clean_name.lower()
                self.by_kind.setdefault(k, r)
                if k == "mp_flag" and r.parsed is not None:
                    self.flags.setdefault(int(r.parsed.team), r)

    def clone(self, kind: str, scene: Scene, base: str, rec: Optional[ModuleRecord] = None) -> Optional[ModuleRecord]:
        src = rec or self.by_kind.get(kind.lower())
        if src is None:
            return None
        c = copy.copy(src)
        c.parsed = copy.deepcopy(src.parsed)
        c.object_name = VStr((_new_name(scene, base) + "\0").encode("cp1252"))
        scene.modules.append(c)
        return c


def _place(rec: ModuleRecord, pos) -> None:
    pos = tuple(float(x) for x in pos)
    p = rec.parsed
    if hasattr(p, "angle"):
        p.position = pos
    else:
        p.transform[3, :3] = pos


def add_start_point(scene: Scene, pos, angle: float = 0.0, team: int = 0) -> ModuleRecord:
    used = [r.parsed.order for r in scene.modules if isinstance(r.parsed, MPStartPoint) and r.parsed.team == team]
    sp = MPStartPoint(position=tuple(float(x) for x in pos), angle=float(angle), team=int(team),
                      order=(max(used) + 1) if used else 0)
    rec = ModuleRecord(VStr((_new_name(scene, "CStartPoint") + "\0").encode("cp1252")),
                       VStr(b"mp_CStartPoint.dll\0"), b"", sp)
    scene.modules.append(rec)
    return rec


def add_health(scene: Scene, tpl: Templates, pos, size: str = "big") -> Optional[ModuleRecord]:
    rec = tpl.clone("mp_salud", scene, "salud")
    if rec is None:
        return None
    rec.parsed.model_name, rec.parsed.health = MEDIKIT[size]
    _place(rec, pos)
    return rec


def add_flag(scene: Scene, tpl: Templates, pos, team: int) -> Optional[ModuleRecord]:
    src = tpl.flags.get(team)
    if src is None:
        return None
    rec = tpl.clone("mp_flag", scene, FLAG_TEAMS[team], src)
    rec.object_name = VStr((FLAG_TEAMS[team] + "\0").encode("cp1252"))
    _place(rec, pos)
    return rec


def add_simple(scene: Scene, tpl: Templates, kind: str, pos, base: str) -> Optional[ModuleRecord]:
    rec = tpl.clone(kind, scene, base)
    if rec is not None:
        _place(rec, pos)
    return rec


def add_camera(scene: Scene, eye, target) -> ModuleRecord:
    """mp_CameraStartPosition: payload = eye (3 floats) + look-at target (3 floats). Used for the intro/spectator camera."""
    import struct
    rec = ModuleRecord(VStr((_new_name(scene, "CameraStartPoint") + "\0").encode("cp1252")),
                       VStr(b"mp_CameraStartPosition.dll\0"), struct.pack("<6f", *eye, *target), None)
    scene.modules.append(rec)
    return rec


def ring_of_starts(scene: Scene, center, n: int = 14, radius: float = 400.0) -> None:
    for i in range(n):
        a = 2 * math.pi * i / n
        # the engine looks along (sin angle, cos angle) in (x, z) (measured on 1589 official start points): face the centre
        add_start_point(scene, (center[0] + radius * math.cos(a), center[1], center[2] + radius * math.sin(a)),
                        angle=math.atan2(-math.cos(a), -math.sin(a)), team=i % 2)


def check(scene: Scene, code: Optional[str] = None) -> List[str]:
    """Human readable list of problems for the mode (empty list = looks complete)."""
    code = code or mode_of(scene)
    if code is None:
        return ["The scene has no known game mode (main module is %r)." % str(scene.main_module_name).rstrip("\0")]
    out: List[str] = []
    kinds: Dict[str, List[ModuleRecord]] = {}
    for r in scene.modules:
        kinds.setdefault(r.clean_name.lower(), []).append(r)
    starts = [r.parsed for r in kinds.get("mp_cstartpoint", []) if r.parsed is not None]
    need = MIN_STARTS[code]
    if len(starts) < need:
        out.append(f"{len(starts)} start points; {code} scenes usually have at least {need}.")
    if code != "DM" and code != "DO":
        for t in (0, 1):
            if not any(s.team == t for s in starts):
                out.append(f"No start point for team {t}.")
    if code == "B":
        have = sorted(int(r.parsed.team) for r in kinds.get("mp_flag", []) if r.parsed is not None)
        if have != [0, 1]:
            out.append("Capture the flag needs exactly two mp_Flag modules (team 0 yellow, team 1 red).")
    if code == "DO":
        n = len(kinds.get("mp_bombzone", []))
        if n == 2:
            names = sorted(str(r.object_name).rstrip("\0").lower() for r in kinds["mp_bombzone"])
            if "bombzone" not in names:
                out.append("With two bomb zones one must be called 'bombZone' (the other one, e.g. 'bombZone_B', is "
                           "counted by the map's own DLL copy).")
            elif "destroythetarget" not in str(scene.main_module_name).lower() or \
                    str(scene.main_module_name).rstrip("\0").lower() == "mp_destroythetarget.dll":
                out.append("Two bomb zones: the scene needs its own copy of the DO DLL that counts the second one "
                           "(Map tools > Gameplay > Destroy the target: bomb sites and the bomb).")
        elif n != 1:
            out.append(f"Destroy the target needs one mp_BombZone, or two with the map's own DLL copy (found {n}).")
    if not kinds.get("mp_salud"):
        out.append("No health packs (mp_salud).")
    if not kinds.get("mp_camerastartposition"):
        out.append("No mp_CameraStartPosition (the spectator/intro camera).")
    if not str(scene.ambient_music).rstrip("\0"):
        out.append("No ambient music set.")
    return out


def populate(scene: Scene, tpl: "Templates", centre, mode: str) -> List[str]:
    """Fill an empty scene with what a playable ``mode`` scene needs around ``centre`` (engine coordinates):
    start points of both teams, the intro camera, six health packs and, for B / DO, flags / bomb zone.
    Returns notes for the user."""
    import struct
    notes: List[str] = []
    c = [float(x) for x in centre]
    n = 20 if mode == "DO" else 14
    for i in range(n):
        a = 2 * math.pi * i / n
        sp = MPStartPoint(position=(c[0] + 150 * math.cos(a), c[1] + 20, c[2] + 150 * math.sin(a)), angle=a + math.pi,
                          team=i % 2, order=i // 2)
        scene.modules.append(ModuleRecord(VStr((f"StartPoint_{i + 1}\0").encode()), VStr(b"mp_CStartPoint.dll\0"), b"", sp))
    eye = (c[0], c[1] + 100, c[2] + 300)
    scene.modules.append(ModuleRecord(VStr(b"CameraStartPoint\0"), VStr(b"mp_CameraStartPosition.dll\0"),
                                      struct.pack("<6f", *eye, *c), None))
    for j, size in enumerate(("big", "big", "small", "small", "small", "small")):
        a = 2 * math.pi * j / 6
        add_health(scene, tpl, (c[0] + 300 * math.cos(a), c[1] + 20, c[2] + 300 * math.sin(a)), size)
    if mode == "B":
        for team, dx in ((0, -400.0), (1, 400.0)):
            if add_flag(scene, tpl, (c[0] + dx, c[1], c[2] + 500), team) is None:
                notes.append("no mp_Flag template found in the Online scenes: add the flags by hand")
        notes.append("flags put near the player start: move them to each team's base")
    elif mode == "DO":
        if add_simple(scene, tpl, "mp_BombZone", (c[0], c[1], c[2] + 500), "bombzone") is None:
            notes.append("no mp_BombZone template found: add the bomb zone by hand")
        notes.append("bomb zone put near the player start with the model of the template scene: change model_name and move it")
    set_mode(scene, mode)
    notes.append(f"game mode {mode}: main module {MODES[mode][1]}")
    return notes
