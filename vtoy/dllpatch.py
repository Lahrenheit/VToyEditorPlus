"""Rain and storms in Torrente Online are not data: the game-mode DLLs create the rain (``AddShower``) only when the scene's
map name is exactly one of a few hard-coded strings (``nfos\\mp_dm_marb.opt``, ``nfos\\mp_b_marb.opt``, ``nfos\\mp_b_gotico.opt``);
the capture-the-flag DLLs also switch the lightning on (``ShowerSetIlumRayo``).  A new map can only get rain if it carries
*that* name or if the DLL it uses compares with *its* name instead.  This module makes such a copy of a mode DLL:
the comparison string is moved to a new one (written in the unused tail of ``.data``) and every reference to it is redirected.
Nothing else in the DLL changes, and the original file is never touched."""
from __future__ import annotations

import re
import struct
from dataclasses import dataclass
from typing import List, Optional

# strings the stock DLLs compare the map name with, and what each one switches on
WEATHER_STRINGS = {
    b"nfos\\mp_dm_marb.opt": "rain",
    b"nfos\\mp_b_marb.opt": "rain",
    b"nfos\\mp_b_gotico.opt": "rain + lightning",
}

# stock DLL per game mode and the weather it can give (what the shipped DLL does for its own map)
RAIN_DLLS = {
    "DM": [("mp_deathMatch.dll", "rain"), ("mp_deathMatchChalet.dll", "rain")],
    "DMT": [("mp_deathMatchTeam.dll", "rain")],
    "B": [("mp_CaptureTheFlag.dll", "rain (+ lightning calls)"), ("mp_CaptureChucrch.dll", "rain + lightning (storm)"),
          ("mp_CaptureThehall.dll", "rain + lightning (storm)")],
}


@dataclass
class PatchReport:
    source: str
    old_name: str
    new_name: str
    references: int
    weather: str


class _PE:
    def __init__(self, data: bytearray):
        self.d = data
        if data[:2] != b"MZ":
            raise ValueError("not a PE file")
        self.pe = struct.unpack_from("<I", data, 0x3C)[0]
        if data[self.pe:self.pe + 4] != b"PE\0\0":
            raise ValueError("not a PE file")
        n = struct.unpack_from("<H", data, self.pe + 6)[0]
        osz = struct.unpack_from("<H", data, self.pe + 20)[0]
        self.base = struct.unpack_from("<I", data, self.pe + 24 + 28)[0]
        self.secs = []
        for i in range(n):
            o = self.pe + 24 + osz + i * 40
            name = bytes(data[o:o + 8]).rstrip(b"\0")
            vs, va, rs, ro = struct.unpack_from("<IIII", data, o + 8)
            self.secs.append(dict(name=name, vs=vs, va=va, rs=rs, ro=ro, hdr=o))

    def va_of(self, off: int) -> Optional[int]:
        for s in self.secs:
            if s["ro"] <= off < s["ro"] + s["rs"]:
                return self.base + s["va"] + off - s["ro"]
        return None


def find_weather_string(data: bytes) -> Optional[bytes]:
    for s in WEATHER_STRINGS:
        if s in data:
            return s
    return None


def patch_map_name(src: str, dst: str, new_map: str) -> PatchReport:
    """Write ``dst``: a copy of the mode DLL ``src`` whose weather check compares with ``new_map`` (e.g. ``nfos\\mp_dm_mio.opt``)."""
    data = bytearray(open(src, "rb").read())
    old = find_weather_string(bytes(data))
    if old is None:
        raise ValueError(f"{src}: this DLL has no weather check (no rain / storm map name inside)")
    new = new_map.replace("/", "\\").encode("latin-1") + b"\0"
    pe = _PE(data)
    pos = bytes(data).find(old)
    old_va = pe.va_of(pos)
    if old_va is None:
        raise ValueError("cannot place the comparison string")
    # room: the writable data section, after its used part (the file keeps zero padding up to the raw size)
    sec = next(s for s in pe.secs if s["name"] == b".data")
    start = sec["ro"] + ((sec["vs"] + 15) & ~15)
    end = sec["ro"] + sec["rs"]
    if start + len(new) > end or any(data[start:start + len(new)]):
        raise ValueError("no free room in .data for the new name")
    data[start:start + len(new)] = new
    sec["vs_new"] = start - sec["ro"] + len(new)
    struct.pack_into("<I", data, sec["hdr"] + 8, max(sec["vs"], sec["vs_new"]))    # make the new bytes part of the image
    new_va = pe.base + sec["va"] + (start - sec["ro"])
    pat = struct.pack("<I", old_va)
    refs, i = 0, 0
    code_end = sec["ro"]                                   # references live in .text / .rdata before .data's strings or in .data
    raw = bytes(data)
    while True:
        i = raw.find(pat, i)
        if i < 0:
            break
        data[i:i + 4] = struct.pack("<I", new_va)
        refs += 1
        i += 4
    if refs == 0:
        raise ValueError("the comparison string is never referenced")
    with open(dst, "wb") as f:
        f.write(data)
    return PatchReport(src, old.decode(), new_map, refs, WEATHER_STRINGS[old])


# ------------------------------------------------------------------------------------------------ flag return time
# mp_Flag.dll (class Flag, scripts\items\bandera\Flag.cpp).  In Flag::Run, on the server: when the carrier's health is <= 0 the
# flag is dropped where he is (Flag::LoseFlag, which stores GetTime() as the drop time); later, while nobody carries it and it
# is not at its base, ``if (GetTime() - dropTime > RETURN_TIME) { back to the base matrix; "flag returned" chat message }``.
# RETURN_TIME is one float constant in .rdata: 25000 (milliseconds = 25 s), compared with a single ``fcomp dword [const]``.
# A copy with a smaller value brings the flag home sooner; 0 = as soon as its carrier dies.
FLAG_RETURN_MS = 25000.0


@dataclass
class FlagPatchReport:
    source: str
    old_ms: float
    new_ms: float
    constant_va: int


def find_flag_return_constant(data: bytes) -> int:
    """File offset of the return-time float of mp_Flag.dll (checked: 25000.0, used by exactly one 'fcomp' in .text)."""
    pe = _PE(bytearray(data))
    if b"Flag.cpp" not in data or b"?LoseFlag@Flag@@" not in data:
        raise ValueError("this is not mp_Flag.dll (class Flag not found)")
    want = struct.pack("<f", FLAG_RETURN_MS)
    hits = []
    for m in re.finditer(re.escape(want), data):
        va = pe.va_of(m.start())
        if va is None:
            continue
        refs = data.count(b"\xd8\x1d" + struct.pack("<I", va))          # fcomp dword ptr [va]
        if refs == 1:
            hits.append(m.start())
    if len(hits) != 1:
        raise ValueError("the flag return time was not found (unknown mp_Flag.dll version)")
    return hits[0]


def patch_flag_return(src: str, dst: str, seconds: float) -> FlagPatchReport:
    """Copy of mp_Flag.dll whose dropped flag goes back to its base after ``seconds`` (0 = when its carrier dies)."""
    data = bytearray(open(src, "rb").read())
    off = find_flag_return_constant(bytes(data))
    old = struct.unpack_from("<f", data, off)[0]
    new = max(0.0, float(seconds)) * 1000.0
    struct.pack_into("<f", data, off, new)
    with open(dst, "wb") as f:
        f.write(data)
    return FlagPatchReport(src, old, new, _PE(data).va_of(off))


# ---------------------------------------------------------------------------------------------- weapons per map
# Every player owns one weapon per group (keys 1-5 in the game); his choice is kept in his profile as five weapon ids at
# +0x1180 (+4 per group) and five ammo counts at +0x11C0.  A mode DLL (mp_CaptureTheFlag.dll, ...) hands them out in two
# places:
#   A) when the player is created:   player->NewWeapon(id[g], ammo[g])         five virtual calls   push ecx / push eax /
#                                                                               mov ecx,edi / call [edx+0x1C]
#   B) every time he is born again:  player->ClearWeapons();  player->ActiveWeapon(id[g], ammo)  five calls through ebx
#                                                                               push / push / mov ecx,esi / call ebx
#      and then  player->ForceChangeWeapon(id[2])  puts the group-3 weapon in his hands.
# In mp_player.dll a weapon the player "has" is just a flag per weapon id (CTorrente +0x560 + id*8) that ActiveWeapon sets
# and ClearWeapons clears, so not making the call for a group = nobody has that group's weapon on this map.
# The call is not removed but turned into "pop eax / pop eax" (the two arguments pushed for it are thrown away, the stack
# stays balanced, eax is a scratch register there): the same number of bytes, so the choice can be changed back on the copy.
# The weapons themselves are numbered in mp_player.dll (CTorrente::InitWeapon):
WEAPON_IDS = {2: "knife", 5: "pistol", 6: "uzi", 7: "sawn-off shotgun", 8: "rifle", 9: "bazooka", 10: "grenade launcher",
              11: "machine gun", 12: "flame thrower", 13: "flare pistol", 14: "proximity mines", 15: "remote mines",
              16: "cetme", 17: "bomb", 18: "kit"}
# which ids each group can hold (from the ammo tables of the mode DLL)
WEAPON_GROUPS = [(2,), (5,), (6, 7, 8, 16), (9, 10, 11, 12, 13), (14, 15)]
GROUP_NAMES = ["knife", "pistol", "uzi / shotgun / rifle / cetme", "heavy: bazooka, grenades, machine gun, flame thrower, flares",
               "mines"]


def group_of_weapon(weapon_id: int) -> int:
    """0-4: the group a weapon id belongs to; -1 for the others (bomb, kit)."""
    return next((g for g, ids in enumerate(WEAPON_GROUPS) if weapon_id in ids), -1)


def _one(rx: bytes, data: bytes, what: str) -> "re.Match":
    hits = list(re.finditer(rx, data, re.S))
    if len(hits) != 1:
        raise ValueError(f"this DLL does not hand out the weapons the known way ({what}: {len(hits)} places) - unknown mode DLL")
    return hits[0]


def _weapon_sites(data: bytes) -> dict:
    """{'create': [5 x (offset, on bytes, off bytes)], 'respawn': [5 x ...], 'hands': offset of the group byte of the
    ForceChangeWeapon argument}."""
    create, respawn = [], []
    for g in range(5):
        ammo = re.escape(bytes([0x8b, 0x88, 0xc0 + 4 * g, 0x11, 0x00, 0x00]))        # mov ecx,[eax+0x11C0+4g]
        wid = re.escape(bytes([0x8b, 0x80, 0x80 + 4 * g, 0x11, 0x00, 0x00]))         # mov eax,[eax+0x1180+4g]
        m = _one(ammo + wid + rb".{0,8}?\x51\x50\x8b\xcf(\xff\x52\x1c|\x58\x58\x90)", data, f"creation, group {g + 1}")
        create.append((m.start(1), b"\xff\x52\x1c", b"\x58\x58\x90"))
        # mov reg,[reg+0x1180+4g] / (mov ebx,[ActiveWeapon])? / two pushes / mov ecx,esi / call ebx
        m = _one(rb"\x8b[\x80-\x97]" + re.escape(bytes([0x80 + 4 * g])) + rb"\x11\x00\x00(?:\x8b\x1d....)?"
                 rb"(?:\x6a.|[\x50-\x57]){2}\x8b\xce(\xff\xd3|\x58\x58)", data, f"respawn, group {g + 1}")
        respawn.append((m.start(1), b"\xff\xd3", b"\x58\x58"))
    # mov eax,[edi+0x1188] / push eax / mov ecx,esi / call [ForceChangeWeapon]
    m = _one(rb"\x8b[\x80-\x97]([\x80\x84\x88])\x11\x00\x00\x50\x8b\xce\xff\x15", data, "weapon in the hands")
    return {"create": create, "respawn": respawn, "hands": m.start(1)}


def weapon_groups(data: bytes) -> list:
    """[bool x 5]: is each weapon group handed out by this mode DLL (when created AND when born again)?"""
    s = _weapon_sites(data)
    return [all(data[o:o + len(on)] == on for o, on, _off in (s["create"][g], s["respawn"][g])) for g in range(5)]


def patch_weapon_groups(src: str, dst: str, allowed) -> list:
    """Copy of a mode DLL that gives only the weapon groups ticked in ``allowed`` (5 booleans; group 1, the knife, always
    stays: a player with nothing in his hands is not something the game expects).  Returns the new state."""
    allowed = [bool(a) for a in allowed]
    if len(allowed) != 5:
        raise ValueError("five weapon groups are expected")
    allowed[0] = True
    data = bytearray(open(src, "rb").read())
    s = _weapon_sites(bytes(data))
    for g in range(5):
        for o, on, off in (s["create"][g], s["respawn"][g]):
            data[o:o + len(on)] = on if allowed[g] else off
    # what he holds when he is born: his group-3 weapon; without group 3, the pistol; without both, the knife
    data[s["hands"]] = 0x88 if allowed[2] else (0x84 if allowed[1] else 0x80)
    with open(dst, "wb") as f:
        f.write(data)
    return weapon_groups(bytes(data))
