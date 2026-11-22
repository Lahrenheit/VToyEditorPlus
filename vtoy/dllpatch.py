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


_MAP_TAG = b"VTOYMAP\0"


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
    tag = _MAP_TAG
    if start + len(tag) + len(new) > end or any(data[start:start + len(tag) + len(new)]):
        raise ValueError("no free room in .data for the new name")
    data[start:start + len(tag)] = tag                    # (weather_rain_map finds the new name by it)
    start += len(tag)
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


# ---------------------------------------------------------------------------------------------- health packs
# mp_salud.dll (the health packs): when a player picks one up it hides and keeps the time (GetTime, ms) at +0x184; every
# frame  "GetTime() - [+0x184] > 5000.0"  shows it again.  The 5000.0 is a constant of .rdata read only there: a copy of
# the DLL with another value there = another time on the maps whose packs use the copy.
_SALUD_SITE = rb"\xd8\xa6\x84\x01\x00\x00\xd8\x1d(....)"        # fsub [esi+0x184] / fcomp [time]
HEALTH_RESPAWN_S = 5.0


def _salud_const(data: bytes):
    """(file offset of the respawn time constant, VA) of mp_salud.dll, or raise."""
    hits = list(re.finditer(_SALUD_SITE, data, re.S))
    if len(hits) != 1:
        raise ValueError("this is not the health pack DLL (mp_salud.dll)")
    va = struct.unpack_from("<I", hits[0].group(1))[0]
    pe = _PE(bytearray(data))
    for s_ in pe.secs:
        if s_["va"] <= va - pe.base < s_["va"] + s_["rs"]:
            off = s_["ro"] + va - pe.base - s_["va"]
            if data.count(struct.pack("<I", va)) != 1:
                raise ValueError("the health packs' time is shared in this DLL: not changed")
            return off, va
    raise ValueError("this is not the health pack DLL (mp_salud.dll)")


def health_respawn(data: bytes) -> float:
    """Seconds a health pack of this mp_salud.dll takes to come back after it is picked up (the game: 5)."""
    off, _va = _salud_const(data)
    return struct.unpack_from("<f", data, off)[0] / 1000.0


def patch_health_respawn(src: str, dst: str, seconds: float) -> tuple:
    """Copy of mp_salud.dll whose packs come back ``seconds`` (1 - 600) after they are picked up.  -> (old, new) s."""
    seconds = float(seconds)
    if not 1.0 <= seconds <= 600.0:
        raise ValueError("the health packs' time must be between 1 and 600 seconds")
    data = bytearray(open(src, "rb").read())
    off, _va = _salud_const(bytes(data))
    old = struct.unpack_from("<f", data, off)[0] / 1000.0
    struct.pack_into("<f", data, off, seconds * 1000.0)
    with open(dst, "wb") as f:
        f.write(data)
    return old, seconds


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


_ID_FORCED = rb"[\xb8-\xbf]....\x90"                    # mov reg, imm32 / nop: a weapon chosen here (see force below)


def _weapon_sites(data: bytes) -> dict:
    """{'create': [5 x (offset, on bytes, off bytes)], 'respawn': [5 x ...], 'hands': offset of the group byte of the
    ForceChangeWeapon argument (-1 when that weapon is fixed), and where each group's weapon id is read from the player's
    profile: 'create_id' / 'respawn_id' [5 x offset], 'hands_id' offset; 'style': 'ctf' (the flag DLLs: the creation
    rounds come from the profile, +0x11C0) or 'dm' (deathmatch, team deathmatch, destroy the target: the rounds come from
    the DLL's own table, both when created and when born again); 'hands_modrm': the ModRM byte of the hands' load."""
    try:
        return _weapon_sites_ctf(data)
    except ValueError as e1:
        for f in (_weapon_sites_dm, _weapon_sites_dm1):
            try:
                return f(data)
            except ValueError:
                pass
        raise e1


def _weapon_sites_ctf(data: bytes) -> dict:
    create, respawn, create_id = [], [], []
    for g in range(5):
        ammo = re.escape(bytes([0x8b, 0x88, 0xc0 + 4 * g, 0x11, 0x00, 0x00]))        # mov ecx,[eax+0x11C0+4g]
        wid = re.escape(bytes([0x8b, 0x80, 0x80 + 4 * g, 0x11, 0x00, 0x00]))         # mov eax,[eax+0x1180+4g]
        tail = rb").{0,8}?\x51\x50\x8b\xcf(\xff\x52\x1c|\x58\x58\x90)"
        # the game's ammo load + its id load (or a fixed id); or, in a copy with a fixed weapon, fixed ammo + fixed id
        hits = list(re.finditer(ammo + b"(" + wid + b"|" + _ID_FORCED + tail, data, re.S))
        if not hits:
            hits = [h for h in re.finditer(_ID_FORCED + b"(" + _ID_FORCED + tail, data, re.S)
                    if h.start() >= 0 and data[h.start(1) + 1:h.start(1) + 5] and
                    group_of_weapon(struct.unpack_from("<I", data, h.start(1) + 1)[0]) == g]
        if len(hits) != 1:
            raise ValueError(f"this DLL does not hand out the weapons the known way (creation, group {g + 1}: "
                             f"{len(hits)} places) - unknown mode DLL")
        m = hits[0]
        create.append((m.start(2), b"\xff\x52\x1c", b"\x58\x58\x90"))
        create_id.append(m.start(1))
    # born again: five times  mov reg,[reg+0x1180+4g] (or a fixed weapon) / (mov ebx,[ActiveWeapon])? / 2 pushes /
    # mov ecx,esi / call ebx  - in the order of the groups
    rx = (rb"(\x8b[\x80-\x97][\x80\x84\x88\x8c\x90]\x11\x00\x00|" + _ID_FORCED + rb")(?:\x8b\x1d....)?"
          rb"(?:\x6a.|[\x50-\x57]){2}\x8b\xce(\xff\xd3|\x58\x58)")
    hits = list(re.finditer(rx, data, re.S))
    if len(hits) != 5:
        raise ValueError(f"this DLL does not hand out the weapons the known way (respawn: {len(hits)} places) - unknown mode DLL")
    respawn_id = []
    for g, m in enumerate(hits):
        if data[m.start(1)] == 0x8b and data[m.start(1) + 2] != 0x80 + 4 * g:
            raise ValueError("this DLL does not hand out the weapons the known way (respawn order) - unknown mode DLL")
        respawn.append((m.start(2), b"\xff\xd3", b"\x58\x58"))
        respawn_id.append(m.start(1))
    # mov eax,[edi+0x1188] (or a fixed weapon) / push eax / mov ecx,esi / call [ForceChangeWeapon]
    m = _one(rb"(\x8b[\x80-\x97][\x80\x84\x88]\x11\x00\x00|" + _ID_FORCED + rb")\x50\x8b\xce\xff\x15", data, "weapon in the hands")
    hid = m.start(1)
    return {"create": create, "respawn": respawn, "hands": hid + 2 if data[hid] == 0x8b else -1,
            "create_id": create_id, "respawn_id": respawn_id, "hands_id": hid, "style": "ctf",
            "hands_modrm": data[hid + 1] if data[hid] == 0x8b else 0x87}


# The deathmatch DLLs (mp_deathMatch, mp_deathMatchTeam, mp_deathMarb, mp_deathMatchChalet) and the destroy-the-target
# ones hand the weapons out the same way with other registers and the rounds of groups 3-5 from their own table (a jump
# table on the weapon id, both when created and when born again):
#   created:     mov reg,[reg+0x1180+4g] / mov edx,[edi] / 2 pushes / mov ecx,edi / call [edx+0x1C]
#   born again:  mov reg,[reg+0x1180+4g] / (mov esi,[ActiveWeapon])? / 2 pushes / mov ecx,edi / call esi
#   hands:       mov eax,[ebx+0x1188] / push eax / mov ecx,edi / call [ForceChangeWeapon]
_ID_LOAD = rb"\x8b[\x80-\xbf]"


def _weapon_sites_dm(data: bytes) -> dict:
    create, create_id = [], []
    tail = rb")(?:\x8b\x17)?(?:\x6a.|[\x50-\x57]){2}\x8b\xcf(\xff\x52\x1c|\x58\x58\x90)"
    for g in range(5):
        wid = _ID_LOAD + re.escape(bytes([0x80 + 4 * g, 0x11, 0x00, 0x00]))
        hits = list(re.finditer(b"(" + wid + tail, data, re.S))
        if not hits:
            hits = [h for h in re.finditer(b"(" + _ID_FORCED + tail, data, re.S)
                    if group_of_weapon(struct.unpack_from("<I", data, h.start(1) + 1)[0]) == g]
        if len(hits) != 1:
            raise ValueError(f"this DLL does not hand out the weapons the known way (creation, group {g + 1}: "
                             f"{len(hits)} places) - unknown mode DLL")
        m = hits[0]
        create.append((m.start(2), b"\xff\x52\x1c", b"\x58\x58\x90"))
        create_id.append(m.start(1))
    rx = (rb"(" + _ID_LOAD + rb"[\x80\x84\x88\x8c\x90]\x11\x00\x00|" + _ID_FORCED + rb")(?:\x8b\x35....)?"
          rb"(?:\x6a.|[\x50-\x57]){2}\x8b\xcf(\xff\xd6|\x58\x58)")
    hits = [m for m in re.finditer(rx, data, re.S) if m.start(1) not in create_id]
    if len(hits) != 5:
        raise ValueError(f"this DLL does not hand out the weapons the known way (respawn: {len(hits)} places) - unknown mode DLL")
    respawn, respawn_id = [], []
    for g, m in enumerate(hits):
        if data[m.start(1)] == 0x8b and data[m.start(1) + 2] != 0x80 + 4 * g:
            raise ValueError("this DLL does not hand out the weapons the known way (respawn order) - unknown mode DLL")
        if data[m.start(1)] != 0x8b and group_of_weapon(struct.unpack_from("<I", data, m.start(1) + 1)[0]) != g:
            raise ValueError("this DLL does not hand out the weapons the known way (respawn order) - unknown mode DLL")
        respawn.append((m.start(2), b"\xff\xd6", b"\x58\x58"))
        respawn_id.append(m.start(1))
    m = _one(rb"(" + _ID_LOAD + rb"[\x80\x84\x88]\x11\x00\x00|" + _ID_FORCED + rb")\x50\x8b\xcf\xff\x15", data,
             "weapon in the hands")
    hid = m.start(1)
    return {"create": create, "respawn": respawn, "hands": hid + 2 if data[hid] == 0x8b else -1,
            "create_id": create_id, "respawn_id": respawn_id, "hands_id": hid, "style": "dm",
            "hands_modrm": data[hid + 1] if data[hid] == 0x8b else 0x83}


def _weapon_sites_dm1(data: bytes) -> dict:
    """mp_deathMatch / mp_deathMarb: one place only (every time a player is born, the first time too):
    mov reg,[reg+0x1180+4g] / (mov esi,[esp+x])? / (mov edi,[ActiveWeapon])? / 2 pushes / mov ecx,esi / call edi."""
    rx = (rb"(" + _ID_LOAD + rb"[\x80\x84\x88\x8c\x90]\x11\x00\x00|" + _ID_FORCED + rb")(?:\x8b\x74\x24.)?(?:\x8b\x3d....)?"
          rb"(?:\x6a.|[\x50-\x57]){2}\x8b\xce(\xff\xd7|\x58\x58)")
    hits = list(re.finditer(rx, data, re.S))
    if len(hits) != 5:
        raise ValueError(f"this DLL does not hand out the weapons the known way (born: {len(hits)} places) - unknown mode DLL")
    respawn, respawn_id = [], []
    for g, m in enumerate(hits):
        if data[m.start(1)] == 0x8b and data[m.start(1) + 2] != 0x80 + 4 * g:
            raise ValueError("this DLL does not hand out the weapons the known way (order) - unknown mode DLL")
        if data[m.start(1)] != 0x8b and group_of_weapon(struct.unpack_from("<I", data, m.start(1) + 1)[0]) != g:
            raise ValueError("this DLL does not hand out the weapons the known way (order) - unknown mode DLL")
        respawn.append((m.start(2), b"\xff\xd7", b"\x58\x58"))
        respawn_id.append(m.start(1))
    m = _one(rb"(" + _ID_LOAD + rb"[\x80\x84\x88]\x11\x00\x00|" + _ID_FORCED + rb")\x50\x8b\xce\xff\x15", data,
             "weapon in the hands")
    hid = m.start(1)
    return {"create": list(respawn), "respawn": respawn, "hands": hid + 2 if data[hid] == 0x8b else -1,
            "create_id": list(respawn_id), "respawn_id": respawn_id, "hands_id": hid, "style": "dm1",
            "hands_modrm": data[hid + 1] if data[hid] == 0x8b else 0x83}


def _create_ammo_at(data: bytes, s: dict, g: int):
    """Offset of the creation's rounds load of group ``g`` (the flag DLLs: mov reg,[reg+0x11C0+4g] just before the id
    load, or the fixed rounds a copy wrote there), or None (the deathmatch DLLs: their own table)."""
    if s.get("style") != "ctf":
        return None
    o = s["create_id"][g] - 6
    cur = data[o:o + 6]
    if cur[0] == 0x8B and cur[2:6] == struct.pack("<I", 0x11C0 + 4 * g):
        return o
    if re.fullmatch(_FORCED_AT, bytes(cur), re.S):
        return o
    return None


def _forced_at(data: bytes, off: int) -> int:
    """The weapon id a 'mov reg, imm32' there fixes (0 when the player's own choice is read)."""
    return struct.unpack_from("<I", data, off + 1)[0] if 0xb8 <= data[off] <= 0xbf else 0


def weapon_choice(data: bytes) -> list:
    """[5 x weapon id or 0]: the weapon each group is fixed to in this DLL (0 = each player's own choice)."""
    data = _stock_view(data)
    s = _weapon_sites(data)
    return [_forced_at(data, s["create_id"][g]) for g in range(5)]


def weapon_groups(data: bytes) -> list:
    """[bool x 5]: is each weapon group handed out by this mode DLL (when created AND when born again)?"""
    data = _stock_view(data)
    s = _weapon_sites(data)
    return [all(data[o:o + len(on)] == on for o, on, _off in (s["create"][g], s["respawn"][g])) for g in range(5)]


def _set_id(data: bytearray, off: int, orig: bytes, weapon: int) -> None:
    """Weapon id read at ``off``: the player's choice (``orig``, the 6 original bytes) or always ``weapon``."""
    if weapon:
        reg = (orig[1] >> 3) & 7                      # the register the original 'mov reg,[reg+disp32]' loads
        data[off:off + 6] = bytes([0xb8 + reg]) + struct.pack("<I", int(weapon)) + b"\x90"
    else:
        data[off:off + 6] = orig


# ------------------------------------------------------------------ several weapons of a group (not all of them)
# The game's menu still offers every weapon of the group: the copy checks the player's choice wherever the mode DLL reads
# it from his profile (creation: rounds + weapon; born again: the ammunition table and the weapon; the one in his hands).
# Each of those 6-byte loads becomes "call stub / nop"; the stub calls the group's check, then does the original load:
#     check: is profile[+0x1180+4g] one of the weapons ticked?  no -> it becomes the first one ticked, with that weapon's
#            rounds (+0x11C0+4g, the DLL's own table) - so every later read sees a weapon of the map and its own rounds.
# Position independent (relative calls only), in the unused tail of .text, with a tag that keeps the original bytes.
_WS_TAG = b"VTOYWSET"


def _stock_view(data: bytes) -> bytes:
    """``data`` with the original loads back and the check code gone (a copy with several weapons per group); the same
    bytes for any other DLL."""
    i = data.find(_WS_TAG)
    if i < 0:
        return data
    d = bytearray(data)
    o = i + len(_WS_TAG)
    cave, n = struct.unpack_from("<IB", d, o)
    o += 5
    for _ in range(n):
        off = struct.unpack_from("<I", d, o)[0]
        d[off:off + 6] = d[o + 4:o + 10]
        o += 10
    for _g in range(5):
        o += 1 + d[o]
    d[cave:o] = b"\0" * (o - cave)
    return bytes(d)


def weapon_sets(data: bytes) -> list:
    """[5 x list of weapon ids or None]: the weapons each group is limited to by a several-weapon check (None: no check;
    see weapon_choice for one fixed weapon)."""
    i = data.find(_WS_TAG)
    out = [None] * 5
    if i < 0:
        return out
    o = i + len(_WS_TAG)
    n = data[o + 4]
    o += 5 + 10 * n
    for g in range(5):
        k = data[o]
        if k:
            out[g] = list(data[o + 1:o + 1 + k])
        o += 1 + k
    return out


def _put_subsets(data: bytearray, s: dict, subsets: dict, ammo: dict, hold: int) -> None:
    pe = _PE(data)
    text = next(x for x in pe.secs if x["name"] == b".text")
    tsites = _table_sites(bytes(data))
    sites = []                                         # (offset, group)
    for g in subsets:
        a = _create_ammo_at(bytes(data), s, g)
        sites += ([(a, g)] if a is not None else []) + [(s["create_id"][g], g), (s["respawn_id"][g], g)]
        sites += [(t, g) for t in tsites.get(g, [])]
        if hold == g:
            sites.append((s["hands_id"], g))
    sites = list(dict.fromkeys(sites))
    for off, g in sites:
        b = data[off:off + 6]
        if b[0] != 0x8B or (b[1] & 0xC0) != 0x80 or (b[1] & 7) == 4 or not 0x1180 <= struct.unpack_from("<I", b, 2)[0] < 0x11E0:
            raise ValueError("this DLL does not read the weapons the known way (several weapons per group)")
    cave = (text["ro"] + text["vs"] + 0x20) & ~0xF
    cave_va = pe.base + text["va"] + cave - text["ro"]
    code = bytearray()
    check_at = {}
    for g, ids in subsets.items():                    # the check of each group: profile in eax
        check_at[g] = len(code)
        disp_w, disp_a = 0x1180 + 4 * g, 0x11C0 + 4 * g
        jes = []
        for w in ids:
            code += b"\x81\xb8" + struct.pack("<II", disp_w, w)          # cmp dword [eax+disp],w
            code += b"\x0f\x84" + struct.pack("<i", 0)                    # je ok
            jes.append(len(code) - 4)
        d0 = ids[0]
        code += b"\xc7\x80" + struct.pack("<II", disp_w, d0)              # mov dword [eax+weapon], first ticked
        code += b"\xc7\x80" + struct.pack("<Ii", disp_a, int(ammo.get(d0, AMMO_FALLBACK.get(d0, 0))))   # its rounds
        ok = len(code)
        code += b"\xc3"
        for j in jes:
            struct.pack_into("<i", code, j, ok - (j + 4))
    stubs = []
    for off, g in sites:                              # each read: save, check, then the original load
        at = len(code)
        orig = bytes(data[off:off + 6])
        base = orig[1] & 7
        code += b"\x9c\x50"                                               # pushfd / push eax
        if base != 0:
            code += bytes([0x89, 0xC0 | (base << 3)])                     # mov eax, base
        code += b"\xe8" + struct.pack("<i", check_at[g] - (len(code) + 5))   # call check
        code += b"\x58\x9d" + orig + b"\xc3"                              # pop eax / popfd / load / ret
        stubs.append((off, at, orig))
    tag = _WS_TAG + struct.pack("<IB", cave, len(sites))
    for off, _at, orig in stubs:
        tag += struct.pack("<I", off) + orig
    for g in range(5):
        ids = subsets.get(g, [])
        tag += bytes([len(ids)] + list(ids))
    blob = bytes(code) + tag
    if cave + len(blob) > text["ro"] + text["rs"] or any(data[cave:cave + len(blob)]):
        raise ValueError("no room for the weapon check in this DLL")
    data[cave:cave + len(blob)] = blob
    for off, at, _orig in stubs:
        site_va = pe.base + text["va"] + off - text["ro"]
        data[off:off + 6] = b"\xe8" + struct.pack("<i", (cave_va + at) - (site_va + 5)) + b"\x90"
    need = cave + len(blob) - text["ro"]
    if text["vs"] < need:
        struct.pack_into("<I", data, text["hdr"] + 8, need)


# ------------------------------------------------------------------ ammunition of a weapon chosen by the map
# The game gives a weapon its ammunition from two places: when the player is created, the rounds his PROFILE has for the
# weapon he chose in the menu (+0x11C0 + 4 x group); when he is born again, a table in the mode DLL indexed by the weapon
# id of his profile (+0x1188 group 3, +0x118C group 4, +0x1190 group 5).  With a weapon fixed by the map both still read
# the player's own choice, so a cetme (120 rounds = 3 magazines) given to somebody who chose the uzi got the uzi's 210.
# The patch makes both use the fixed weapon: the creation gets the table's rounds for it, the table is indexed by it.
AMMO_FALLBACK = {6: 210, 7: 30, 8: 20, 16: 120, 9: 2, 10: 4, 11: 50, 12: 200, 13: 10, 14: 4, 15: 4}
_G_TABLE = {2: rb"\x8b([\x80-\xbf])\x88\x11\x00\x00(?=\x83[\xc0-\xc7]\xfa(?:\x83\xc4.)?\x83[\xf8-\xff]\x0a\x77.\x0f\xb6)",
            3: rb"\x8b([\x80-\xbf])\x8c\x11\x00\x00(?=\x83[\xc0-\xc7]\xf7)",
            4: rb"\x8b([\x80-\xbf])\x90\x11\x00\x00(?=\x83[\xe8-\xef]\x0e)"}
_FORCED_AT = rb"([\xb8-\xbf])(....)\x90"


def _table_sites(data: bytes) -> dict:
    """{group: [offsets]} of the loads of the profile's weapon id that index an ammunition table (groups 3-5; the stock
    load or a fixed id written there): the flag DLLs have one (born again), the deathmatch ones two (created too)."""
    out = {}
    for g, rx in _G_TABLE.items():
        tail = rx.split(b"(?=")[1]
        hits = [m.start() for m in re.finditer(rx, data, re.S)]
        hits += [m.start() for m in re.finditer(_FORCED_AT + b"(?=" + tail, data, re.S)]   # fixed in this copy
        if 1 <= len(hits) <= 2:
            out[g] = sorted(hits)
    return out


def ammo_table(data: bytes) -> dict:
    """{weapon id: rounds} the mode DLL gives each weapon of groups 3-5 when a player is born again (read from its code:
    the jump tables after the loads of _table_sites); the known values of the stock DLLs when the code is not the known one."""
    out = dict(AMMO_FALLBACK)
    try:
        pe = _PE(bytearray(data))
        text = next(s for s in pe.secs if s["name"] == b".text")

        def off(va):
            return va - pe.base - text["va"] + text["ro"]

        def case_value(at, edx):
            if data[at:at + 3] == b"\xc7\x44\x24":
                return struct.unpack_from("<i", data, at + 4)[0]
            if data[at:at + 3] == b"\x89\x54\x24":
                return edx
            return None
        sites = {g: v[-1] for g, v in _table_sites(data).items()}   # the born-again one (no add esp in between)
        if 2 in sites:                                 # add reg,-6 / cmp reg,10 / ja / movzx edx,[reg+bytes] / jmp [edx*4+jt]
            o = sites[2] + 6
            byt = struct.unpack_from("<I", data, o + 3 + 3 + 2 + 3)[0]
            jt = struct.unpack_from("<I", data, o + 3 + 3 + 2 + 7 + 3)[0]
            for wid in (6, 7, 8, 16):
                k = data[off(byt) + wid - 6]
                v = case_value(off(struct.unpack_from("<I", data, off(jt) + 4 * k)[0]), None)
                if v is not None:
                    out[wid] = v
        edx = None
        if 3 in sites:                                 # add reg,-9 / mov edx,4 / cmp / ja / jmp [reg*4+jt]
            o = sites[3] + 6
            if data[o + 3] == 0xBA:
                edx = struct.unpack_from("<i", data, o + 4)[0]
            m = re.compile(rb"\xff\x24[\x85-\x8f\x8d](....)", re.S).search(data, o, o + 24)
            if m:
                jt = struct.unpack_from("<I", m.group(1))[0]
                for k, wid in enumerate((9, 10, 11, 12, 13)):
                    v = case_value(off(struct.unpack_from("<I", data, off(jt) + 4 * k)[0]), edx)
                    if v is not None:
                        out[wid] = v
        if 4 in sites and edx is not None:             # sub reg,14 / je / dec / jne / mov [esp+x],edx: both mines
            out[14] = out[15] = edx
    except Exception:
        pass
    return out


def _fix_ammo(data: bytearray, sites: dict, ammo: dict, forced: list) -> None:
    """Creation: the rounds of the fixed weapon instead of the profile's; born again: the table indexed by the fixed
    weapon.  Groups without a fixed weapon keep (or get back) the game's own loads."""
    tsites = _table_sites(bytes(data))
    for g in range(2, 5):
        w = forced[g]
        # creation ammunition (flag DLLs): mov reg,[reg+0x11C0+4g] (6 bytes, just before the id load)
        o = _create_ammo_at(bytes(data), sites, g)
        if o is not None:
            cur = bytes(data[o:o + 6])
            reg = ((cur[1] >> 3) & 7) if cur[0] == 0x8B else cur[0] - 0xB8
            if w:
                data[o:o + 6] = bytes([0xB8 + reg]) + struct.pack("<i", int(ammo.get(w, AMMO_FALLBACK.get(w, 0)))) + b"\x90"
            elif cur[0] != 0x8B:
                data[o:o + 6] = bytes([0x8B, 0x80 | (reg << 3), 0xC0 + 4 * g, 0x11, 0x00, 0x00])
        # the tables (born again; deathmatch DLLs: created too) are indexed by the fixed weapon
        for t in tsites.get(g, []):
            cur = bytes(data[t:t + 6])
            reg = ((cur[1] >> 3) & 7) if cur[0] == 0x8B else cur[0] - 0xB8
            if w:
                data[t:t + 6] = bytes([0xB8 + reg]) + struct.pack("<I", int(w)) + b"\x90"
            elif cur[0] != 0x8B:
                data[t:t + 6] = bytes([0x8B, 0x80 | (reg << 3), 0x80 + 4 * g, 0x11, 0x00, 0x00])


def weapon_ammo(data: bytes) -> dict:
    """{group: rounds} the creation gives a fixed weapon in this DLL (only groups with a fixed weapon)."""
    data = _stock_view(data)
    s = _weapon_sites(data)
    out = {}
    for g in range(2, 5):
        o = _create_ammo_at(data, s, g)
        if o is not None and 0xB8 <= data[o] <= 0xBF:
            out[g] = struct.unpack_from("<i", data, o + 1)[0]
    return out


def patch_weapon_groups(src: str, dst: str, allowed, forced=None) -> list:
    """Copy of a mode DLL that gives only the weapon groups ticked in ``allowed`` (5 booleans; group 1, the knife, always
    stays: a player with nothing in his hands is not something the game expects).  ``forced`` (5 weapon ids or 0): a group
    with an id gives everybody THAT weapon instead of the one each player chose (e.g. group 3 = the rifle only).
    Returns the new state.  The source should be the game's own DLL (its original bytes are needed to undo a choice)."""
    allowed = [bool(a) for a in allowed]
    if len(allowed) != 5:
        raise ValueError("five weapon groups are expected")
    forced = list(forced or [0] * 5)
    if len(forced) != 5:
        raise ValueError("five weapon groups are expected")
    subsets: dict = {}
    for g, w in enumerate(forced):                    # a list of weapons: only those of the group (one = fixed)
        if isinstance(w, (list, tuple, set, frozenset)):
            ids = [int(x) for x in w]
            ids = [x for k, x in enumerate(ids) if x not in ids[:k]]
            for x in ids:
                if x not in WEAPON_GROUPS[g]:
                    raise ValueError(f"weapon {x} is not of group {g + 1}")
            if not ids or set(ids) == set(WEAPON_GROUPS[g]):
                forced[g] = 0
            elif len(ids) == 1:
                forced[g] = ids[0]
            else:
                forced[g] = 0
                subsets[g] = ids
    forced = [int(f or 0) for f in forced]
    for g, w in enumerate(forced):
        if w and w not in WEAPON_GROUPS[g]:
            raise ValueError(f"weapon {w} is not of group {g + 1}")
    allowed[0] = True
    data = bytearray(_stock_view(open(src, "rb").read()))
    s = _weapon_sites(bytes(data))
    for g in range(5):
        for o, on, off in (s["create"][g], s["respawn"][g]):
            data[o:o + len(on)] = on if allowed[g] else off
    for g in range(5):
        for o in dict.fromkeys((s["create_id"][g], s["respawn_id"][g])):
            if data[o] == 0x8b:                       # the game's own load of the player's choice
                if forced[g]:
                    _set_id(data, o, bytes(data[o:o + 6]), forced[g])
            elif forced[g]:                           # fixed already in this copy: another weapon
                data[o + 1:o + 5] = struct.pack("<I", forced[g])
            else:
                raise ValueError("this copy has a fixed weapon in group %d: make it again from the game's own DLL" % (g + 1))
    _fix_ammo(data, s, ammo_table(bytes(data)), forced)
    # what he holds when he is born: his group-3 weapon; without group 3, the pistol; without both, the knife
    hold = 2 if allowed[2] else (1 if allowed[1] else 0)
    h = s["hands_id"]
    mr = s.get("hands_modrm", 0x87)
    if forced[hold]:
        _set_id(data, h, bytes(data[h:h + 6]) if data[h] == 0x8b else bytes([0x8b, mr, 0x88, 0x11, 0x00, 0x00]), forced[hold])
    else:
        data[h:h + 6] = bytes([0x8b, mr, 0x80 + 4 * hold, 0x11, 0x00, 0x00])
    subsets = {g: ids for g, ids in subsets.items() if allowed[g]}
    if subsets:
        _put_subsets(data, s, subsets, ammo_table(bytes(data)), hold)
    with open(dst, "wb") as f:
        f.write(data)
    return weapon_groups(bytes(data))


# ============================================================================== destroy the target: a second bomb zone
# The DO mode DLL (mp_DestroyTheTarget.dll) ends the round when ObjectByName("bombZone") is destroyed (byte +0x178 of the
# BombZone object).  The bomb (mp_Bomba) already works on every bomb zone of the scene (the scene's target list), so a
# second zone can be blown up, but the mode never notices.  The patch: where the DLL tests "bombZone", jump to a few new
# instructions in the unused tail of .text that also test a second object by name ("bombZone_B").  Position independent
# (no new relocations): the string is pushed on the stack and the ObjectByName import is read relative to the code.
_DZ_SITE = rb"\x3b\xfb\x74(.)\x8a\x87\x78\x01\x00\x00\x84\xc0\x74(.)\x8b\x86\x60\x02\x00\x00"
_DZ_TAG = b"VTOY2BZ\0"                                   # marks the new code (after it, the second name)


def _import_slot(data: bytes, pe: "_PE", func: bytes) -> int:
    """VA of the import address table slot of ``func`` (by name), or raise."""
    imp_rva = struct.unpack_from("<I", data, pe.pe + 24 + 104)[0]

    def off_of(rva):
        for s in pe.secs:
            if s["va"] <= rva < s["va"] + max(s["vs"], s["rs"]):
                return s["ro"] + rva - s["va"]
        raise ValueError("bad import table")
    o = off_of(imp_rva)
    while True:
        lookup, _t, _f, name_rva, thunk = struct.unpack_from("<IIIII", data, o)
        if not name_rva:
            break
        lo = off_of(lookup or thunk)
        k = 0
        while True:
            e = struct.unpack_from("<I", data, lo + 4 * k)[0]
            if not e:
                break
            if not e & 0x80000000:
                no = off_of(e) + 2
                if data[no:no + len(func) + 1] == func + b"\0":
                    return pe.base + thunk + 4 * k
            k += 1
        o += 20
    raise ValueError(f"{func.decode()} is not imported by this DLL")


# Version 2 (in its own section, ".vtoyz"): the stock test is only true while a zone EXPLODES (BombZone +0x178 is set for
# about 60 frames, then cleared), so "all the zones" could never be true at once (the first one was over when the
# second blew up).  A zone now counts as destroyed while it explodes or once its destroyed model is shown (the actor
# [zone+0x164], visible byte +0x64: ActorGetVisible) - until the round's reset.  The same code shows the zones on the
# HUD: an icon pair per zone (mp_do_plaza's objective icons), intact or destroyed.  Source: tools/asm/bombzones.s.
_DZ2_TAG = b"VTOYBZ2\0"
_BZ_SEC = b".vtoyz"
_BZ_INIT_SITE = rb"\x8d\x4c\x24\x4c\xc6\x84\x24\x0c\x01\x00\x00\x02\xff\x15"   # end of the scene's constructor
_BZ_DTOR_SITE = rb"\x8d\xbe\x88\x05\x00\x00\xc7\x44\x24\x10\x07\x00\x00\x00\xbd\x02\x00\x00\x00"  # the scene's end
_BZ_DTOR_ORIG = bytes.fromhex("8dbe88050000c744241007000000")           # its two lines (lea edi / mov [esp+10h], 7)
# Copies made before took the shower / icons off there, after RemoveSceneObjects / DeleteSky had freed the scene's
# things (de_aztec closed the game a few seconds after leaving it).  Now the hook is at the destructor's start, where
# mp_deathMatch takes its own shower off: after the +0x600 sprite, at the +0x604 one (mov eax,[esi+604h] / test eax,eax).
_BZ_DTOR_SITE2 = rb"\x8b\x86\x04\x06\x00\x00\x85\xc0\x74\x06\x50\xff\xd3\x83\xc4\x04\xa1"
_BZ_DTOR_ORIG2 = bytes.fromhex("8b860406000085c0")
_BZ_DTOR_LEN2 = 8
_BZ_RUN_AT = 0x24                                                      # the scene's Run + this: 4 pushes and 2 lines
_BZ_RUN_ORIG = bytes.fromhex("535556578bf18944244c")                     # (the splashes hook them)
_BZ_SIZE = 0x2000                                                      # the section: code, params, vars, tail; imports
MAX_EXTRA_ZONES = 4
_BZ_INIT = 0x289
_BZ_SPLASH = 0x4e7
_BZ_SPRET = 0x789
_BZ_DTOR = 0x444
_BZ_CODE = bytes.fromhex(
    "60e8000000005d81ed0600000031db3b9d280800007d7e85db75058b0424eb3389d8c1e0058d8c05600800008b949d300800"
    "00898d500a00008995540a00008d8d500a0000518b850c080000ff54050083c40489849d800a0000c6841d600a00000285c0"
    "7429c6841d600a00000180b8780100000075188b886401000085c97406807964007508c6841d600a00000043e97affffffe8"
    "301c000083bd48080000000f842e0100008b74240483be30060000020f851d0100008b854c0800008b4405008b0085c00f84"
    "09010000ffb0a00000008b8550080000ff54050083c4048b08898da00a00008b4804898da40a00008b4808898da80a0000c7"
    "85b00a0000ffffffffc785b40a0000ffff7f7f31db3b9d280800007d5c80bc1d600a000000754f8b849d800a0000ffb0a000"
    "00008b8550080000ff54050083c4048d8da00a000051508b8554080000ff54050083c408d99db80a00008b85b80a00003b85"
    "b40a00007d0c8985b40a0000899db00a000043eb9c8b85b00a0000403b85bc0a000074538b8e6802000085c974498985bc0a"
    "000048783489c2c1e2058d9415600800008995500a00008b9485300800008995540a00008d95500a0000526a008b85580800"
    "00ff540500eb0c6a008b855c080000ff54050083bd2408000000745631db3b9d280800007d4c8b84dd000a000085c0743e31"
    "d280bc1d600a0000000f94c252508b8514080000ff54050083c40831d280bc1d600a0000010f94c252ffb4dd040a00008b85"
    "14080000ff54050083c40843ebac31db83bd200800000075153b9d280800007d3380bc1d600a000001742143ebeb80bd600a"
    "000002741d3b9d280800007d0d80bc1d600a000000740b43ebeb8b8500080000eb068b850408000001e88944241c61ffe08d"
    "4c244cc684240c0100000260e8000000005d81ed9b020000c785bc0a00000000000083bd200900000074478d855009000050"
    "ffb534090000ffb5340900008d854009000050568b8524090000ff54050083c41485c0741be81a1900008b8d2c0900008b4c"
    "0d008b0985c97406898134130000c785700b00000000000083bd24080000000f84e700000083be30060000020f85da000000"
    "31db3b9d280800000f8dcc000000680003000068000400008d85440a0000508d85400a0000506a1f6a1f8b8518080000ff54"
    "050083c418680003000068000400008d854c0a0000508d85480a0000506a536bc324055d030000508b8518080000ff540500"
    "83c4188b851c08000001e88985500a00008b852c0800008985540a00006800005f3f680000f83d680000403f6a00e8520000"
    "008984dd000a00006800005f3f6800007c3e680000403f680000003ee8320000008984dd040a00006a00508b8514080000ff"
    "54050083c40843899d700b0000e928ffffff8b850808000001e88944241c61ffe0596a08ffb5440a0000ffb5400a0000ffb5"
    "4c0a0000ffb5480a00008d85500a000050898d700a00008b8510080000ff54050083c428ffa5700a000060e8000000005d81"
    "ed4a04000083bde009000000743b8b9d700b000085db7e314b899d700b0000ffb4dd000a00008b85e0090000ff54050083c4"
    "04ffb4dd040a00008b85e0090000ff54050083c404ebc583bd200900000074328b8d2c0900008b4c0d008b0985c974228b81"
    "3413000085c07418c7813413000000000000508b8528090000ff54050083c4048b853009000001e88944241c61508b860406"
    "000085c0c35355565789ce8944244c9c60e8000000005d81edf804000083bd60090000000f847b02000085c00f8473020000"
    "89b5c00a00008b8d2c0900008b4c0d008b0985c90f84590200008b813413000085c00f844b0200008985c80a00008b8d6409"
    "00008b4c0d008b0985c90f84310200008b4938898dc40a0000518d85200b0000508b8568090000ff54050083c4086a028d85"
    "000b0000508d8d200b00008b856c090000ff540500ffb5c40a00008d85100b0000508b8570090000ff54050083c408d98500"
    "0b0000d8c8d985080b0000d8c8dec1d9fad9eedff17514ddd8d9eed99d000b0000d9e8d99d080b0000eb20d9e8d8f1ddd9d9"
    "c0d88d000b0000d99d000b0000d88d080b0000d99d080b0000d985a8090000d88d000b0000d885100b0000d99dd00a0000d9"
    "85a8090000d885140b0000d99dd40a0000d985a8090000d88d080b0000d885180b0000d99dd80a0000ffb5c80a00008b8574"
    "090000ff54050083c404d88db4090000db9dcc0a00008b9dcc0a000085db0f8e2301000081fbc80000007e05bbc80000008b"
    "8578090000ff540500d8a5b0090000d88dac090000d885d80a0000d99de80a00008b8578090000ff540500d8a5b0090000d8"
    "8dac090000d885d00a0000d99de00a00008b85d40a00008985e40a00008d85f00a0000508d85e00a0000508b857c090000ff"
    "54050083c40884c00f849c0000008d85900900008985600b00008b85a40900008985640b00006a006804000091680050c347"
    "680000803f6800002041680000204168000000b768000000ff68ec51783f8d85d00900005068cdcc4c3e680000a041680000"
    "40406a00689a99193f68000000bf8d85c0090000508d85f00a0000508d85600b000050ffb5c00a00008b8580090000ff5405"
    "0083c4506a07508b8584090000ff54050083c4084b0f85eafeffff619de900000000"
)
_BZ_CODE2 = bytes.fromhex(
    "6089c683bd3809000000743cc686e800000000bbb40000008b041ec7041e0000000085c0741783bde809000000740e508b85"
    "e8090000ff54050083c40483c30481fbcc00000072d083bde409000000747783bde809000000746e31db89dfc1e70683bc3d"
    "000c00000074578b849eb000000085c0744c508b85e8090000ff54050083c4048d843d040c00008985780b00008b843d000c"
    "000089857c0b000068002474496a006a008d85780b0000508b85e4090000ff54050083c41089849eb00000004383fb077294"
    "61c331db3b9d280800007d788b849d800a000085c0746a39849da00b0000740bc7849da00b00000000000080bc1d600a0000"
    "01752a83bc9da00b00000075428b8860010000898c9d800b000089849da00b0000c7806001000000000000eb2283bc9da00b"
    "00000074188b8c9d800b0000898860010000c7849da00b00000000000043eb80c3"
)


def _zone_tag(data: bytes):
    """(tag offset, version) of the bomb zones patch, or (-1, 0)."""
    i = data.find(_DZ2_TAG)
    if i >= 0:
        return i, 2
    i = data.find(_DZ_TAG)
    return (i, 1) if i >= 0 else (-1, 0)


_ZONE_FLAGS = "&#@~!%^"        # all / hud / radar / rain / (old: lightning) / splashes / calm rain (no storm)


def _zone_payload(data: bytes):
    """(flags, names) of a version 2 bomb zones copy, or None."""
    i, ver = _zone_tag(data)
    if i < 0:
        return None
    tag = _DZ2_TAG if ver == 2 else _DZ_TAG
    j = data.find(b"\0", i + len(tag))
    s = data[i + len(tag):j].decode("latin-1")
    k = 0
    while k < len(s) and s[k] in _ZONE_FLAGS:
        k += 1
    return s[:k], [n for n in s[k:].split(",") if n]


def bomb_zones(data: bytes) -> Optional[tuple]:
    """(the other bomb zones this DLL also checks, all) or None (stock DLL: only "bombZone").  ``all`` True: the round
    is won only when "bombZone" AND all of them are destroyed; False: any one of them wins it.  A copy made only for
    the rain has no other zones: ([], False)."""
    p = _zone_payload(data)
    return None if p is None else (p[1], "&" in p[0])


def bomb_zones_hud(data: bytes) -> bool:
    """Does this DLL show the bomb zones on the HUD (icons)?"""
    p = _zone_payload(data)
    return bool(p) and "#" in p[0]


def bomb_zones_icons_off(data: bytes) -> bool:
    """Does this copy take its zone icons off the screen at the scene's end (they stayed in the next map before)?"""
    try:
        sec = _section(_PE(bytearray(data)), _BZ_SEC)
    except (ValueError, struct.error):
        return False
    return bool(sec) and sec["vs"] >= _BZ_SIZE and struct.unpack_from("<i", data, sec["ro"] + 0x800 + 0x1e0)[0] != 0


_BZ_NO_REPLANT = b"\xc7\x80\x60\x01\x00\x00\x00\x00\x00\x00"     # mov dword [zone+0x160],0 (its radius)


def bomb_zones_late_end(data: bytes) -> bool:
    """A copy made before whose scene's end (the shower, the icons off) comes after the scene's things were freed: the
    game could close a few seconds after leaving the map (de_aztec)."""
    try:
        pe = _PE(bytearray(data))
        sec = _section(pe, _BZ_SEC)
        if not sec or sec["vs"] < _BZ_SIZE:
            return False
        dtor_va = struct.unpack_from("<I", data, sec["ro"] + 0xFF8)[0]
        if not dtor_va:
            return False
        rva = dtor_va - pe.base
        for s_ in pe.secs:
            if s_["va"] <= rva < s_["va"] + max(s_["vs"], s_["rs"]):
                o = s_["ro"] + rva - s_["va"]
                return data[o + 8:o + 13] != b"\x74\x06\x50\xff\xd3"
    except (ValueError, struct.error):
        return False
    return False


def bomb_zones_no_replant(data: bytes) -> bool:
    """Does this copy keep a second bomb off a zone already destroyed (its radius 0 until the round's reset)?"""
    try:
        sec = _section(_PE(bytearray(data)), _BZ_SEC)
    except (ValueError, struct.error):
        return False
    return bool(sec) and _BZ_NO_REPLANT in data[sec["ro"]:sec["ro"] + _BZ_SIZE]


def bomb_zones_radar(data: bytes) -> bool:
    """Does this DLL point the minimap at the nearest zone still standing?"""
    p = _zone_payload(data)
    return bool(p) and "@" in p[0]


def bomb_rain(data: bytes) -> tuple:
    """(rain, storm) of a destroy-the-target copy: Marbella's rain on the whole map, with its storm (lightning flashes and
    thunder, what vtKernel's shower does by itself) or calm (the copy switches the storm off)."""
    p = _zone_payload(data)
    rain = bool(p) and "~" in p[0]
    return rain, rain and "^" not in p[0]


def bomb_splash(data: bytes) -> bool:
    """Do the drops of this copy's rain splash on the floor round the camera (like Marbella)?"""
    p = _zone_payload(data)
    return bool(p) and "%" in p[0]


def _drop_section(data: bytearray, name: bytes) -> bool:
    """Take the section ``name`` out of the DLL when it is the last one, at the end of the file.  -> done?"""
    pe = _PE(data)
    s = _section(pe, name)
    if s is None or s is not pe.secs[-1] or s["ro"] + s["rs"] != len(data):
        return False
    p = pe.pe
    n = struct.unpack_from("<H", data, p + 6)[0]
    data[s["hdr"]:s["hdr"] + 40] = b"\0" * 40
    struct.pack_into("<H", data, p + 6, n - 1)
    struct.pack_into("<I", data, p + 24 + 56, s["va"])
    del data[s["ro"]:]
    return True


def can_have_bomb_rain(data: bytes) -> bool:
    """Is this the destroy-the-target DLL with the places the rain needs (the scene's start and end)?"""
    if _zone_tag(data)[1] == 2:
        return True
    return (len(re.findall(_DZ_SITE, data, re.S)) == 1 and len(re.findall(_BZ_INIT_SITE, data, re.S)) == 1
            and len(re.findall(_BZ_DTOR_SITE2, data, re.S)) == 1)


def second_bomb_zone(data: bytes) -> Optional[str]:
    """Name of the (first) other bomb zone this DLL also checks ("bombZone_B"), or None (stock DLL: only "bombZone")."""
    z = bomb_zones(data)
    return z[0][0] if z and z[0] else None


def can_have_second_bomb_zone(data: bytes) -> bool:
    return bomb_zones(data) is not None or len(re.findall(_DZ_SITE, data, re.S)) == 1


def patch_second_bomb_zone(src: str, dst: str, name: str = "bombZone_B", all_sites: bool = False) -> str:
    """Copy of the DO mode DLL that also counts the bomb zone called ``name`` (see patch_bomb_zones).  Returns ``name``."""
    patch_bomb_zones(src, dst, [name], all_sites)
    return name


def _section(pe: "_PE", name: bytes):
    return next((s for s in pe.secs if s["name"] == name), None)


def _add_section(data: bytearray, name: bytes, size: int) -> None:
    """A new section (read, write, run) of ``size`` zero bytes at the end of the DLL."""
    pe = _PE(data)
    p = pe.pe
    n = struct.unpack_from("<H", data, p + 6)[0]
    osz = struct.unpack_from("<H", data, p + 20)[0]
    salign, falign = struct.unpack_from("<II", data, p + 24 + 32)
    hdr_size = struct.unpack_from("<I", data, p + 24 + 60)[0]
    o = p + 24 + osz + n * 40
    if o + 40 > min(hdr_size, min(s["ro"] for s in pe.secs if s["rs"]) or hdr_size) or any(data[o:o + 40]):
        raise ValueError("no room for a new section in this DLL")
    va = max(s["va"] + max(s["vs"], s["rs"]) for s in pe.secs)
    va = (va + salign - 1) // salign * salign
    ro = (len(data) + falign - 1) // falign * falign
    data.extend(b"\0" * (ro - len(data)))
    data.extend(b"\0" * size)
    data[o:o + 40] = struct.pack("<8sIIIIIIHHI", name, size, va, size, ro, 0, 0, 0, 0, 0xE0000020)
    struct.pack_into("<H", data, p + 6, n + 1)
    struct.pack_into("<I", data, p + 24 + 56, va + (size + salign - 1) // salign * salign)


_RAIN_IMPORTS = (b"?AddShower@@YAHPAVCObject@@ABUvtVector@@MM1@Z", b"?RemoveRenderObject@@YAXH@Z",
                 b"?ShowerSetIlumRayo@@YAXH_N@Z",                  # vtKernel; mp_deathMatch / mp_CaptureChucrch
                 b"?CameraGetViewMatrix@@YA?AUvtMatrix@@H@Z", b"?GetColumn@vtMatrix@@QBE?AUvtVector@@E@Z",
                 b"?CameraGetPosition@@YA?AUvtVector@@H@Z", b"?ShowerGetIntensidad@@YAMH@Z", b"?Random@@YAMXZ",
                 b"?GetHeight@@YA_NABUvtVector@@AAU1@@Z",
                 b"?AddParticleSystem@@YAHPAVCObject@@ABVCString@@ABUvtVector@@2MMMMMM2MIIMMMMIH@Z",
                 b"?SetParticleCountDown@@YAXHH@Z",               # the splashes (mp_deathMatch on Marbella)
                 b"?LoadSound@@YAHABVCString@@_NMM@Z", b"?ReleaseSound@@YAXH@Z")  # the map's quieter storm
_SOUND_IMPORTS = _RAIN_IMPORTS[-2:]
# the shower's sounds (vtShower +0xB0 the rain, +0xB4..+0xC8 the thunders), the files vtKernel loads for them
SHOWER_SOUNDS = ("wavs/LLUVIA_2.wav", "wavs/trueno.wav", "wavs/trueno_2.wav", "wavs/trueno_3.wav",
                 "wavs/trueno bajo_1.wav", "wavs/trueno bajo_2.wav", "wavs/trueno bajo_3.wav")
_SND_AT, _VOL_AT = 0xC00, 0xEF0
_RSPR_IMPORT = b"?RemoveRenderObject@@YAXH@Z"                         # the zones' icons off the screen at the end
RAIN_WIDTH = 30000.0                                                  # Marbella's shower (mp_deathMatch)
RAIN_POS = (0.0, 5000.0, 0.0)
RAIN_SPEED = (0.0, -1500.0, 0.0)
_IMP_AT = 0x1000                                                      # the new import table, in the section


def _imports_with(data: bytearray, pe: "_PE", sec: dict, blob: bytearray, funcs) -> dict:
    """Write in ``blob`` (the section, at _IMP_AT) the DLL's import table plus one more entry: ``funcs`` of vtKernel,
    and point the DLL at it (the old table stays where it is, unused).  -> {func: VA of its IAT slot}."""
    imp_rva, imp_size = struct.unpack_from("<II", data, pe.pe + 24 + 104)

    def off_of(rva):
        for s_ in pe.secs:
            if s_["va"] <= rva < s_["va"] + max(s_["vs"], s_["rs"]):
                return s_["ro"] + rva - s_["va"]
        raise ValueError("bad import table")
    o = off_of(imp_rva)
    descs, vt_name = [], None
    while True:
        d = bytes(data[o:o + 20])
        name_rva = struct.unpack_from("<I", d, 12)[0]
        if not name_rva:
            break
        no = off_of(name_rva)
        if data[no:data.index(b"\0", no)].decode("latin-1").lower().split(".")[0] == "vtkernel":
            vt_name = name_rva
        descs.append(d)
        o += 20
    if vt_name is None:
        raise ValueError("this DLL does not use vtKernel")
    rva0 = sec["va"] + _IMP_AT
    n = len(descs) + 2
    ilt = _IMP_AT + 20 * n
    ilt = (ilt + 15) // 16 * 16
    iat = ilt + 4 * (len(funcs) + 1)
    names = iat + 4 * (len(funcs) + 1)
    out = {}
    q = names
    for k, f in enumerate(funcs):
        struct.pack_into("<I", blob, ilt + 4 * k, sec["va"] + q)
        struct.pack_into("<I", blob, iat + 4 * k, sec["va"] + q)
        blob[q:q + 2 + len(f) + 1] = b"\0\0" + f + b"\0"
        q += (2 + len(f) + 1 + 1) // 2 * 2
        out[f] = pe.base + sec["va"] + iat + 4 * k
    if q > _BZ_SIZE:
        raise ValueError("no room for the import table")
    t = _IMP_AT
    for d in descs:
        blob[t:t + 20] = d
        t += 20
    blob[t:t + 20] = struct.pack("<IIIII", sec["va"] + ilt, 0, 0, vt_name, sec["va"] + iat)
    struct.pack_into("<II", data, pe.pe + 24 + 104, rva0, 20 * n)
    return out


def _put_sounds(blob: bytearray, sounds, volumes) -> None:
    """The shower's sounds a map loads instead of its own (7 names or ''), and the volumes they were made at."""
    for k, nm in enumerate(list(sounds or [])[:len(SHOWER_SOUNDS)]):
        if not nm:
            continue
        e = nm.replace("\\", "/").encode("latin-1")
        if len(e) > 58:
            raise ValueError(f"sound name too long: {nm}")
        struct.pack_into("<I", blob, _SND_AT + 64 * k, len(e) + 1)
        blob[_SND_AT + 64 * k + 4:_SND_AT + 64 * k + 4 + len(e)] = e
    blob[_VOL_AT:_VOL_AT + 6] = b"VOL1" + bytes([max(0, min(100, int(volumes[0]))), max(0, min(100, int(volumes[1])))])


def shower_volumes(data: bytes) -> tuple:
    """(thunder %, rain %) of the storm in a copy patched here (100, 100: the game's own sounds)."""
    for name in (_BZ_SEC, _W_SEC):
        try:
            sec = _section(_PE(bytearray(data)), name)
        except (ValueError, struct.error):
            return 100, 100
        if sec and data[sec["ro"] + _VOL_AT:sec["ro"] + _VOL_AT + 4] == b"VOL1":
            return data[sec["ro"] + _VOL_AT + 4], data[sec["ro"] + _VOL_AT + 5]
    return 100, 100


def shower_sounds(data: bytes) -> list:
    """The 7 sounds (rain, six thunders) a patched copy loads for its shower instead of the game's ('' = the game's)."""
    out = [""] * len(SHOWER_SOUNDS)
    for name in (_BZ_SEC, _W_SEC):
        try:
            sec = _section(_PE(bytearray(data)), name)
        except (ValueError, struct.error):
            return out
        if not sec:
            continue
        for k in range(len(SHOWER_SOUNDS)):
            o = sec["ro"] + _SND_AT + 64 * k
            n = struct.unpack_from("<I", data, o)[0]
            if 1 < n <= 59:
                out[k] = bytes(data[o + 4:o + 3 + n]).decode("latin-1")
    return out


def shower_sound_names(data: bytes) -> list:
    """The sound files a patched copy loads for its shower instead of the game's (they go with the map)."""
    return [n for n in shower_sounds(data) if n]


# ============================================================================== the storm of any other mode DLL
# The DM / DMT / CTF DLLs make Marbella's shower themselves (AddShower, when the map is their rain map: patch_map_name
# makes a copy whose rain map is THIS map).  vtKernel's vtShower is a storm by itself (lightning flashes, six thunder
# sounds).  patch_weather gives such a copy a ".vtoyw" section (tools/asm/weather.s): its one "call [AddShower]" calls
# the section's code instead, which calls AddShower and then fix_shower (tools/asm/shower.inc): calm rain (no flashes, no
# thunder) and / or the map's quieter copies of the sounds.  LoadSound / ReleaseSound are a new import of vtKernel.
_W_SEC = b".vtoyw"
_W_TAG = b"VTOYW1\0"
_W_CODE = bytes.fromhex(
    "e800000000582d05000000598988000a00008b8800080000ff140860e8000000005d81ed2100000085c07405e80d0000008b"
    "8d000a0000894c241861ffe16089c683bd0408000000743cc686e800000000bbb40000008b041ec7041e0000000085c07417"
    "83bd0c08000000740e508b850c080000ff54050083c40483c30481fbcc00000072d083bd0808000000747783bd0c08000000"
    "746e31db89dfc1e70683bc3d000c00000074578b849eb000000085c0744c508b850c080000ff54050083c4048d843d040c00"
    "008985080a00008b843d000c000089850c0a000068002474496a006a008d85080a0000508b8508080000ff54050083c41089"
    "849eb00000004383fb07729461c3"
)


def _addshower_site(data: bytes, pe: "_PE"):
    slot = _import_slot(data, pe, _RAIN_IMPORTS[0])
    m = [x.start() for x in re.finditer(re.escape(b"\xff\x15" + struct.pack("<I", slot)), data)]
    if len(m) != 1:
        raise ValueError("this mode DLL does not make Marbella's rain (no AddShower call)")
    return slot, m[0]


def can_have_weather(data: bytes) -> bool:
    """Does this mode DLL make Marbella's rain (a map name it rains on, one AddShower call)?"""
    try:
        if _section(_PE(bytearray(data)), _W_SEC) is not None:
            return True
        _addshower_site(data, _PE(bytearray(data)))
        return find_weather_string(data) is not None
    except (ValueError, struct.error, StopIteration):
        return False


def weather_rain_map(data: bytes) -> Optional[str]:
    """The map a weather DLL (or a copy) rains on: its own (``nfos\\mp_dm_marb.opt``) or the one patch_map_name put."""
    old = find_weather_string(data)
    if old is None:
        return None
    i = data.find(_MAP_TAG)
    if i >= 0:
        return bytes(data[i + len(_MAP_TAG):data.index(b"\0", i + len(_MAP_TAG))]).decode("latin-1")
    pe = _PE(bytearray(data))
    va = pe.va_of(data.find(old))
    if va is not None and not data.count(struct.pack("<I", va)):
        return "?"                                        # a copy made by an older editor: another map (this one)
    return old.decode("latin-1")


def weather_calm(data: bytes) -> bool:
    try:
        sec = _section(_PE(bytearray(data)), _W_SEC)
    except (ValueError, struct.error):
        return False
    return bool(sec) and struct.unpack_from("<I", data, sec["ro"] + 0x804)[0] == 1


def patch_weather(src: str, dst: str, calm: bool = False, sounds=None, volumes=(100, 100)) -> bool:
    """Copy of a rain-making mode DLL (see above) whose shower is ``calm`` (no lightning, no thunder) and / or loads
    ``sounds`` (7 names or '': the rain, the six thunders) instead of the game's.  A copy patched before gets its
    old code out first; nothing to do: the plain DLL.  -> is the stub there."""
    data = bytearray(open(src, "rb").read())
    pe = _PE(data)
    sec = _section(pe, _W_SEC)
    if sec is not None:                                   # the earlier patch out: the call, the import table back
        t = sec["ro"]
        orig = bytes(data[t + 0xFE0:t + 0xFE6])
        imp_rva, imp_size, site_va = struct.unpack_from("<III", data, t + 0xFF0)
        site = next(s_["ro"] + site_va - pe.base - s_["va"] for s_ in pe.secs
                    if s_["va"] <= site_va - pe.base < s_["va"] + max(s_["vs"], s_["rs"]))
        data[site:site + 6] = orig
        struct.pack_into("<II", data, pe.pe + 24 + 104, imp_rva, imp_size)
        data[t:t + sec["rs"]] = b"\0" * sec["rs"]
        if not _drop_section(data, _W_SEC):
            raise ValueError("this copy was made by an older editor: make it again from the game's DLL")
        pe = _PE(data)
    want = bool(calm) or any(sounds or [])
    if not want:
        open(dst, "wb").write(bytes(data))
        return False
    slot, site = _addshower_site(bytes(data), pe)
    site_va = pe.va_of(site)
    imp_old = struct.unpack_from("<II", data, pe.pe + 24 + 104)
    _add_section(data, _W_SEC, _BZ_SIZE)
    pe = _PE(data)
    sec = _section(pe, _W_SEC)
    base_va = pe.base + sec["va"]
    blob = bytearray(_BZ_SIZE)
    blob[:len(_W_CODE)] = _W_CODE
    struct.pack_into("<i", blob, 0x800, slot - base_va)
    struct.pack_into("<I", blob, 0x804, 1 if calm else 0)
    slots = _imports_with(data, pe, sec, blob, _SOUND_IMPORTS)
    struct.pack_into("<i", blob, 0x808, slots[_SOUND_IMPORTS[0]] - base_va)
    struct.pack_into("<i", blob, 0x80c, slots[_SOUND_IMPORTS[1]] - base_va)
    _put_sounds(blob, sounds, volumes)
    blob[0xF00:0xF00 + len(_W_TAG)] = _W_TAG
    blob[0xFE0:0xFE6] = data[site:site + 6]
    struct.pack_into("<III", blob, 0xFF0, imp_old[0], imp_old[1], site_va)
    data[sec["ro"]:sec["ro"] + _BZ_SIZE] = blob
    data[site:site + 6] = b"\xe8" + struct.pack("<i", base_va - (site_va + 5)) + b"\x90"
    open(dst, "wb").write(bytes(data))
    return True


def patch_bomb_zones(src: str, dst: str, names, all_sites: bool = False, hud: bool = True, radar: bool = True,
                     rain: bool = False, storm: bool = True, splash: bool = False, sounds=None, volumes=(100, 100)) -> tuple:
    """Copy of the DO mode DLL that also counts the bomb zones ``names`` (besides "bombZone", up to MAX_EXTRA_ZONES).
    ``all_sites`` False: the round ends (attackers win) when ANY zone is destroyed (like the game with one zone);
    True: only when "bombZone" and every one of ``names`` that is in the scene are destroyed - until then the round goes
    on and, if the clock runs out, the defenders win.  ``hud``: an icon per zone on the screen (the plain DO mode).
    ``radar``: the minimap points at the zone nearest to the player that is not destroyed yet (the game: bombZone).
    ``rain``: Marbella's rain on the whole map (the shower mp_deathMatch makes for mp_dm_marb: AddShower at the
    scene's start, RemoveRenderObject at its end; the DO DLLs have no rain at all, so the copy gets those two - and
    ShowerSetIlumRayo - as a new import of vtKernel); ``storm``: the shower's own storm stays (lightning flashes, thunder:
    vtKernel's vtShower does both by itself); False: calm rain - the copy clears its flash flag (+0xE8) and its thunder
    sounds (+0xB4..+0xC8) right after AddShower; ``splash``: the drops splash on the floor round the camera, every frame (mp_deathMatch's code on
    Marbella: a hook at the start of the scene's Run).  With ``rain`` the zones may be none (only "bombZone": the
    game's own test is left as it is).
    A DLL already patched (either version) gets its names / mode changed.  Returns (names, all_sites)."""
    names = [n for n in names if n]
    if len(names) > MAX_EXTRA_ZONES or (not names and not rain):
        raise ValueError(f"1 to {MAX_EXTRA_ZONES} other bomb zones")
    for name in names:
        if not re.fullmatch(r"[A-Za-z0-9_]{1,30}", name) or name.lower() == "bombzone":
            raise ValueError("every other bomb zone needs its own name (letters, digits, _)")
    if len({n.lower() for n in names}) != len(names):
        raise ValueError("the bomb zones need different names")
    data = bytearray(open(src, "rb").read())
    pe = _PE(data)
    text = _section(pe, b".text")
    if text is None:
        raise ValueError("no .text section")

    def off_of_va(va):
        rva = va - pe.base
        for s_ in pe.secs:
            if s_["va"] <= rva < s_["va"] + max(s_["vs"], s_["rs"]):
                return s_["ro"] + rva - s_["va"]
        raise ValueError("address outside the DLL")
    sec = _section(pe, _BZ_SEC)
    i, ver = _zone_tag(bytes(data))
    if ver == 1:                                          # version 1 in .text: its code out, the test site kept
        win, nowin, site_va = struct.unpack_from("<III", data, i - 12)
        j = data.find(b"\0", i + len(_DZ_TAG))
        data[i - 0x200:j + 1] = b"\0" * (j + 1 - (i - 0x200))
        site_off = off_of_va(site_va)                     # its jump over the game's test: the test again
        data[site_off:site_off + 14] = (b"\x3b\xfb\x74" + bytes([(nowin - (site_va + 4)) & 0xFF])
                                        + b"\x8a\x87\x78\x01\x00\x00\x84\xc0\x74" + bytes([(nowin - (site_va + 14)) & 0xFF]))
    elif ver == 2 and sec is not None:                    # an earlier copy: the game's lines back, then as the game's
        t = sec["ro"] + 0xF00
        win, nowin, site_va, init_va = struct.unpack_from("<IIII", data, t)
        if site_va:
            data[off_of_va(site_va):off_of_va(site_va) + 14] = data[t + 0x10:t + 0x1E]
        data[off_of_va(init_va):off_of_va(init_va) + 12] = data[t + 0x1E:t + 0x2A]
        imp_rva, imp_size, dtor_va, run_va = struct.unpack_from("<IIII", data, sec["ro"] + 0xFF0)
        if imp_rva:
            struct.pack_into("<II", data, pe.pe + 24 + 104, imp_rva, imp_size)
        if dtor_va:
            o = off_of_va(dtor_va)
            if data[o + 8:o + 13] == b"\x74\x06\x50\xff\xd3":     # (the hook at the destructor's start)
                data[o:o + _BZ_DTOR_LEN2] = _BZ_DTOR_ORIG2
            else:                                         # (an older copy: at the scene's end)
                data[o:o + 14] = _BZ_DTOR_ORIG
        if run_va:
            data[off_of_va(run_va):off_of_va(run_va) + 10] = _BZ_RUN_ORIG
        if sec["vs"] < _BZ_SIZE:                          # an older, smaller section: made again at the end
            data[sec["ro"]:sec["ro"] + sec["rs"]] = b"\0" * sec["rs"]
            if not _drop_section(data, _BZ_SEC):
                raise ValueError("this copy was made by an older editor: make it again from the game's DLL")
            pe = _PE(data)
            text = _section(pe, b".text")
            sec = None
    m = list(re.finditer(_DZ_SITE, data, re.S))
    if len(m) != 1:
        raise ValueError("this is not the destroy-the-target DLL (the bomb zone test was not found)")
    site = m[0].start()
    site_va = pe.base + text["va"] + site - text["ro"]
    nowin = site_va + 4 + m[0].group(1)[0]
    win = site_va + 14
    if data[site + 12:site + 14] != bytes([0x74, (nowin - (site_va + 14)) & 0xFF]):
        raise ValueError("unexpected code at the bomb zone test")
    m = list(re.finditer(_BZ_INIT_SITE, data, re.S))
    if len(m) != 1:
        raise ValueError("unexpected code in the mode DLL (the end of the scene's start was not found)")
    init_va = pe.base + text["va"] + m[0].start() - text["ro"]
    dtor_va = 0
    if rain or (hud and names):
        m = list(re.finditer(_BZ_DTOR_SITE2, data, re.S))
        if len(m) != 1:
            if rain:
                raise ValueError("unexpected code in the mode DLL (the end of the scene was not found): no rain")
        else:
            dtor_va = pe.base + text["va"] + m[0].start() - text["ro"]
    run_va = 0
    if rain and splash:
        r_off = _scene_run(bytes(data), pe) + _BZ_RUN_AT
        if data[r_off:r_off + 10] != _BZ_RUN_ORIG:
            raise ValueError("unexpected code in the mode DLL (the scene's Run): no splashes")
        run_va = pe.va_of(r_off)
    else:
        splash = False
    if sec is None:
        _add_section(data, _BZ_SEC, _BZ_SIZE)
        pe = _PE(data)
        sec = _section(pe, _BZ_SEC)
    base_va = pe.base + sec["va"]
    blob = bytearray(_BZ_SIZE)
    blob[:len(_BZ_CODE)] = _BZ_CODE
    blob[0x1c00:0x1c00 + len(_BZ_CODE2)] = _BZ_CODE2

    def put(off, v):
        struct.pack_into("<i", blob, 0x800 + off, int(v))
    put(0x00, win - base_va)
    put(0x04, nowin - base_va)
    put(0x08, init_va + 12 - base_va)
    put(0x0c, _import_slot(bytes(data), pe, b"?ObjectByName@@YAPBVCObject@@AAVCString@@@Z") - base_va)
    tex = bytes(data).find(b"armas_grupo_345.tex\0")
    try:
        put(0x10, _import_slot(bytes(data), pe, b"?AddSprite@@YAHABVCString@@HHHHHMMMM@Z") - base_va)
        put(0x14, _import_slot(bytes(data), pe, b"?SpriteSetVisible@@YAXH_N@Z") - base_va)
        put(0x18, _import_slot(bytes(data), pe, b"?ConvertPixelToRender@@YAXHHAAH0HH@Z") - base_va)
        if tex < 0 or pe.va_of(tex) is None:
            raise ValueError("no icon texture")
        put(0x1c, pe.va_of(tex) - base_va)
        put(0x2c, len("armas_grupo_345.tex") + 1)
    except ValueError:
        hud = False
    try:                                                  # the minimap: the nearest zone still standing
        put(0x4c, _import_slot(bytes(data), pe, b"?mainCharacter@CGame@@0HA") - base_va)
        put(0x50, _import_slot(bytes(data), pe, b"?ActorGetPosition@@YAAAUvtVector@@H@Z") - base_va)
        put(0x54, _import_slot(bytes(data), pe, b"?Distance2@@YAMABUvtVector@@0@Z") - base_va)
        put(0x58, _import_slot(bytes(data), pe, b"?SetTargetName@Radar@@QAEXHAAVCString@@@Z") - base_va)
        put(0x5c, _import_slot(bytes(data), pe, b"?ClearTarget@Radar@@QAEXH@Z") - base_va)
        radar = bool(radar)
    except ValueError:
        radar = False
    if not names:                                         # rain only: the game's own test, no icons, its minimap
        hud = radar = all_sites = False
    put(0x48, 1 if radar else 0)
    put(0x20, 1 if all_sites else 0)
    put(0x24, 1 if hud else 0)
    zones = ["bombZone"] + names
    put(0x28, len(zones))
    for k, nm in enumerate(zones):
        put(0x30 + 4 * k, len(nm) + 1)
        e = nm.encode("latin-1")
        blob[0x860 + 32 * k:0x860 + 32 * k + len(e)] = e
    imp_old = struct.unpack_from("<II", data, pe.pe + 24 + 104)
    icons_off = bool(hud and dtor_va)                     # the icons are taken off the screen at the scene's end
    if not rain and not icons_off:
        dtor_va = 0
    if icons_off:                                         # the game's own way (its scene's end does the same
        try:                                              # with its icons): RemoveRenderObject, imported already
            put(0x1e0, _import_slot(bytes(data), pe, _RSPR_IMPORT) - base_va)
        except ValueError:
            icons_off = False
    if not rain and not icons_off:
        dtor_va = 0
    if rain or icons_off:
        put(0x130, dtor_va + _BZ_DTOR_LEN2 - base_va)
    if rain:
        put(0x12c, _import_slot(bytes(data), pe, b"?main@CGame@@0HA") - base_va)
        cam_slot = _import_slot(bytes(data), pe, b"?camera@CGame@@0HA") if splash else 0
        slots = _imports_with(data, pe, sec, blob, _RAIN_IMPORTS)
        put(0x120, 1)
        put(0x124, slots[_RAIN_IMPORTS[0]] - base_va)
        put(0x128, slots[_RAIN_IMPORTS[1]] - base_va)
        put(0x13c, slots[_RAIN_IMPORTS[2]] - base_va)
        put(0x1e4, slots[_SOUND_IMPORTS[0]] - base_va)
        put(0x1e8, slots[_SOUND_IMPORTS[1]] - base_va)
        _put_sounds(blob, sounds, volumes)
        put(0x138, 0 if storm else 1)
        struct.pack_into("<f", blob, 0x800 + 0x134, RAIN_WIDTH)
        struct.pack_into("<3f", blob, 0x800 + 0x140, *RAIN_POS)
        struct.pack_into("<3f", blob, 0x800 + 0x150, *RAIN_SPEED)
        if splash:
            put(0x160, 1)
            put(0x164, cam_slot - base_va)
            for k, o in enumerate(range(0x168, 0x188, 4)):
                put(o, slots[_RAIN_IMPORTS[3 + k]] - base_va)
            tex2 = b"gota_salpica.tex"
            blob[0x800 + 0x190:0x800 + 0x190 + len(tex2)] = tex2
            put(0x1a4, len(tex2) + 1)
            struct.pack_into("<4f", blob, 0x800 + 0x1a8, 2000.0, 4000.0, 0.5, 20.0)
            struct.pack_into("<3f", blob, 0x800 + 0x1c0, 0.0, 300.0, 0.0)
            struct.pack_into("<3f", blob, 0x800 + 0x1d0, 0.0, -1700.0, 0.0)
            struct.pack_into("<i", blob, _BZ_SPRET + 1, (run_va + 10) - (base_va + _BZ_SPRET + 5))
    else:
        storm, splash = True, False
    site_off, init_off = off_of_va(site_va), off_of_va(init_va)
    orig_site = bytes(data[site_off:site_off + 14])
    orig_init = bytes(data[init_off:init_off + 12])
    payload = (("&" if all_sites else "") + ("#" if hud else "") + ("@" if radar else "") + ("~" if rain else "")
               + ("^" if rain and not storm else "") + ("%" if splash else "") + ",".join(names))
    tail = (struct.pack("<IIII", win, nowin, site_va if names else 0, init_va) + orig_site + orig_init + _DZ2_TAG
            + payload.encode("latin-1") + b"\0")
    blob[0xF00:0xF00 + len(tail)] = tail
    if rain or icons_off:
        struct.pack_into("<IIII", blob, 0xFF0, imp_old[0], imp_old[1], dtor_va, run_va)
    data[sec["ro"]:sec["ro"] + _BZ_SIZE] = blob
    if names:
        data[site_off:site_off + 14] = b"\xe9" + struct.pack("<i", base_va - (site_va + 5)) + b"\x90" * 9
    data[init_off:init_off + 12] = b"\xe9" + struct.pack("<i", base_va + _BZ_INIT - (init_va + 5)) + b"\x90" * 7
    if dtor_va:
        d_off = off_of_va(dtor_va)
        data[d_off:d_off + _BZ_DTOR_LEN2] = (b"\xe9" + struct.pack("<i", base_va + _BZ_DTOR - (dtor_va + 5))
                                            + b"\x90" * (_BZ_DTOR_LEN2 - 5))
    if splash:
        r_off = off_of_va(run_va)
        data[r_off:r_off + 10] = b"\xe9" + struct.pack("<i", base_va + _BZ_SPLASH - (run_va + 5)) + b"\x90" * 5
    open(dst, "wb").write(bytes(data))
    return names, all_sites


def _code_size(data: bytes, text: dict) -> int:
    """The size of the DLL's own code in .text (a copy with the bomb overtime code keeps the original one in its tag)."""
    i = data.find(_OT_TAG)
    if i >= 0:
        return struct.unpack_from("<I", data, i + len(_OT_TAG))[0]
    return text["vs"]


# ============================================================================== destroy the target: the bomb's time
# What the game does (read in its DLLs): the bomb a player plants is NOT the bomb lying on the map (the scene's mp_Bomba,
# a pick-up).  The bomb weapon (mp_bomb.dll) makes a new object from the game's own "mp_bomba.dll" when it is planted
# (NewObject), puts it in the scene's list of bombs (Scene +0xFC: array of objects, +0x104: how many) and calls
# Bomba::PlaceBomb: state +0x1B0 = 1 (ticking), +0x194 = GetTime() (ms), +0x1D8 = the same.  On the server Bomba::Run
# explodes it when GetTime() - [+0x194] > 20000 (20 s); on every PC the object is thrown away 80000 ms after [+0x1D8].
# When the round's clock (mp_ContadorTiempo) reaches 0:00 it signals "__timeout__" and the DO mode DLL ends the round at
# once - the defenders win (Servidor::DestroyPoint(0)), even with a bomb ticking: its time is not added to the clock.
#
# The patch, in a copy of the map's DO mode DLL (the game's DLLs stay as they are), two hooks in the unused tail of .text:
#   * the scene's Run (every frame, on every PC): a bomb of the list that is ticking and not seen yet gets its planting
#     time moved by (fuse - 20 s) - it explodes after ``fuse`` seconds; the pairs (bomb, time) already moved are kept in
#     the unused tail of .data;
#   * "__timeout__": if a bomb of the list is ticking, the clock is set to the seconds it has left (it blows up as the
#     clock shows 0:00) and the round goes on: it explodes (attackers win) or is defused and the clock runs out again
#     (defenders win).  A 0:00 that is not one of this round (the round already won; or the clock of the round before,
#     frozen during the scores, running out after the restart) is let go.
# Position independent (call/pop + relative addresses), no new relocations.
BOMB_FUSE_MS = 20000.0
_OT_TAG = b"VTOYBOMB"
_LIST_PTR, _LIST_N, _STATE, _PLANTED, _SEEN_AT = 0xFC, 0x104, 0x1B0, 0x194, 0x1D8
_BLOWN_AT = 0x1BC                                         # mp_bomba: when it blew up (state 2; gone 3 s later)


def _exports(data: bytes, pe: "_PE") -> dict:
    exp_rva, exp_sz = struct.unpack_from("<II", data, pe.pe + 24 + 96)
    if not exp_rva:
        return {}

    def off(rva):
        for s_ in pe.secs:
            if s_["va"] <= rva < s_["va"] + max(s_["vs"], s_["rs"]):
                return s_["ro"] + rva - s_["va"]
        return None
    o = off(exp_rva)
    n_fn, n_nm, a_fn, a_nm, a_ord = struct.unpack_from("<IIIII", data, o + 20)
    out = {}
    for i in range(n_nm):
        nm_rva = struct.unpack_from("<I", data, off(a_nm) + 4 * i)[0]
        ordi = struct.unpack_from("<H", data, off(a_ord) + 2 * i)[0]
        rva = struct.unpack_from("<I", data, off(a_fn) + 4 * ordi)[0]
        out[data[off(nm_rva):].split(b"\0")[0].decode("latin-1")] = rva
    return out


def _timeout_handler(data: bytes, pe: "_PE") -> int:
    """File offset of the "__timeout__" event handler of a mode DLL (from its GetEvents table)."""
    i = data.find(b"__timeout__\0")
    if i < 0:
        raise ValueError("this mode DLL has no round clock event (__timeout__)")
    va = pe.va_of(i)
    text = next(s_ for s_ in pe.secs if s_["name"] == b".text")
    for m in re.finditer(re.escape(struct.pack("<I", va)), data):
        h = struct.unpack_from("<I", data, m.end())[0]
        if pe.base + text["va"] <= h < pe.base + text["va"] + text["vs"]:
            return h - pe.base - text["va"] + text["ro"]
    raise ValueError("the round clock event handler was not found")


def _scene_run(data: bytes, pe: "_PE") -> int:
    """File offset of the scene's Run (exported ?Run@Scene...@@UAEXXZ) of a mode DLL."""
    text = next(s_ for s_ in pe.secs if s_["name"] == b".text")
    for name, rva in _exports(data, pe).items():
        if re.fullmatch(r"\?Run@Scene\w+@@UAEXXZ", name):
            return rva - text["va"] + text["ro"]
    raise ValueError("the scene's Run was not found in this mode DLL")


_FS0 = b"\x64\xa1\x00\x00\x00\x00"                         # mov eax, fs:[0]  (both hooks replace this line)


def _hook_sites(data: bytes, pe: "_PE"):
    h = _timeout_handler(data, pe)
    r = _scene_run(data, pe) + 7                           # push -1 / push handler / mov eax,fs:[0]
    for at in (h, r):
        if data[at:at + 6] != _FS0 and data[at] != 0xE9:
            raise ValueError("unexpected code in the mode DLL (not the destroy-the-target one)")
    return h, r


def bomb_rules(data: bytes) -> Optional[tuple]:
    """(fuse in seconds, overtime: bool) of a DO mode DLL patched here, or None (the game's: 20 s, no overtime)."""
    i = data.find(_OT_TAG)
    if i < 0:
        return None
    _vs, fuse, ot = struct.unpack_from("<IfB", data, i + len(_OT_TAG))
    return fuse / 1000.0, bool(ot)


BOMB_CODE_VERSION = 3       # 2: 0:00 also waits for a bomb that blew up and already left the scene's list
#                             3: the clock shows the bomb's own seconds (it blows up at 0:00, not at 0:02); a 0:00
#                                of the round already over (or of the round before, handled after the restart: the
#                                clock froze during the scores and ran out at once) is let go - it gave the next round
#                                0:03 and the defenders' win
_ROUND_OVER_RE = rb"\x8a\x86(....)\x84\xc0\x89\x4c\x24\x18\x0f\x84"   # Run: mov al,[esi+over] / test / ... je


def bomb_rules_outdated(data: bytes) -> bool:
    """A copy with the overtime code of an earlier version (re-apply the bomb time to update it)."""
    i = data.find(_OT_TAG)
    if i < 0:
        return False
    _vs, _fuse, ot, ver = struct.unpack_from("<IfBB", data, i + len(_OT_TAG))
    return bool(ot) and ver < BOMB_CODE_VERSION


def can_have_bomb_rules(data: bytes) -> bool:
    try:
        pe = _PE(bytearray(data))
        _hook_sites(data, pe)
        return b"?SetTime@ContadorTiempo@@" in data
    except (ValueError, struct.error, StopIteration):
        return False


def patch_bomb_rules(src: str, dst: str, fuse_seconds: float = 20.0, overtime: bool = False) -> tuple:
    """Copy of the DO mode DLL whose planted bombs explode ``fuse_seconds`` after they are planted (5 - 600; the game:
    20) and, with ``overtime``, whose round does not end at 0:00 while a bomb ticks (the clock shows its seconds).
    20 s without overtime = the game's own code again.  Returns (fuse, overtime)."""
    fuse_seconds = float(fuse_seconds)
    if not 5.0 <= fuse_seconds <= 600.0:
        raise ValueError("the bomb's time must be between 5 and 600 seconds")
    data = bytearray(open(src, "rb").read())
    pe = _PE(data)
    text = next((s_ for s_ in pe.secs if s_["name"] == b".text"), None)
    dsec = next((s_ for s_ in pe.secs if s_["name"] == b".data"), None)
    if text is None or dsec is None:
        raise ValueError("no .text / .data section")
    h, r = _hook_sites(bytes(data), pe)
    raw_end = text["ro"] + text["rs"]
    old = data.find(_OT_TAG)
    if old >= 0:                                          # the previous bomb code out first
        cave0 = struct.unpack_from("<I", data, old - 4)[0]
        code_vs = struct.unpack_from("<I", data, old + len(_OT_TAG))[0]
        data[cave0:raw_end] = b"\0" * (raw_end - cave0)
    else:
        code_vs = text["vs"]
    data[h:h + 6] = _FS0
    data[r:r + 6] = _FS0
    dz = data.find(_DZ_TAG)                               # version 1 of the zones' code (in .text's tail)
    if not text["ro"] <= dz < raw_end:
        dz = -1
    if old < 0:                                           # the code really there (a size grown by an earlier version
        k = raw_end                                       # of this patch, since taken out, does not count)
        while k > text["ro"] and data[k - 1] == 0:
            k -= 1
        code_vs = k - text["ro"]
    if abs(fuse_seconds * 1000.0 - BOMB_FUSE_MS) < 1.0 and not overtime:
        open(dst, "wb").write(bytes(data))
        return 20.0, False
    slot_time = _import_slot(bytes(data), pe, b"?GetTime@@YAMXZ")
    slot_set = _import_slot(bytes(data), pe, b"?SetTime@ContadorTiempo@@QAEXHH@Z")
    m = re.search(rb"\x8b[\x88-\x8f](....)\x6a\x00\x50\xff\x15" + re.escape(struct.pack("<I", slot_set)), bytes(data), re.S)
    if m is None:
        raise ValueError("the round clock of this mode DLL was not found")
    clock = struct.unpack_from("<I", m.group(1))[0]
    mo = re.search(_ROUND_OVER_RE, bytes(data), re.S)
    over = struct.unpack_from("<I", mo.group(1))[0] if mo else None   # the scene: the round is over, restart pending
    cave = (raw_end - 0x280) & ~0xF
    if cave < text["ro"] + code_vs + 0x20 or (dz >= 0 and cave < data.find(b"\0", dz + len(_DZ_TAG)) + 1):
        raise ValueError("no room for the new code in this DLL")
    if any(data[cave:raw_end]):
        raise ValueError("no room for the new code in this DLL")
    # 64 zero bytes at the end of .data's last page (mapped, never used by the DLL): 4 x (bomb, moved time), next slot
    page_end = (dsec["vs"] + 0xFFF) & ~0xFFF
    if page_end - dsec["vs"] < 0x80:
        raise ValueError("no room for the bomb table in this DLL")
    table = dsec["ro"] + page_end - 0x40
    if table + 0x40 <= dsec["ro"] + dsec["rs"] and any(data[table:table + 0x40]):
        raise ValueError("no room for the bomb table in this DLL")
    cave_va = pe.base + text["va"] + cave - text["ro"]
    table_va = pe.base + dsec["va"] + page_end - 0x40
    h_va = pe.base + text["va"] + h - text["ro"]
    r_va = pe.base + text["va"] + r - text["ro"]
    code = bytearray()
    fix_rel = []                                          # (offset of disp32, target offset in the cave) for [ebx+...]

    def rel_ebx(target_off_or_va, here_va, is_va=False):
        return struct.pack("<i", (target_off_or_va if is_va else cave_va + target_off_or_va) - here_va)
    # ---------------------------------------------------------------- 1) the scene's Run: move the planting times
    run_entry = len(code)
    code += b"\x60"                                                   # pushad
    code += b"\xe8\x00\x00\x00\x00\x5b"                               # call $+5 / pop ebx
    here1 = cave_va + len(code) - 1
    flag_va = table_va + 0x24
    seen_va = table_va + 0x28                             # float: GetTime() when a bomb was last ticking / blown up
    if overtime:                                          # the clock stopped itself after "__timeout__": run it again
        code += b"\x8b\xe9"                                           # mov ebp,ecx   (the scene)
        code += b"\x80\xbb" + rel_ebx(flag_va, here1, True) + b"\x00"  # cmp byte [ebx+flag],0
        code += b"\x74\x00"                                           # je skip
        je_skip = len(code) - 1
        code += b"\xc6\x83" + rel_ebx(flag_va, here1, True) + b"\x00"  # mov byte [ebx+flag],0
        code += b"\x8b\xb5" + struct.pack("<I", clock)                # mov esi,[ebp+clock]
        code += b"\x85\xf6\x74\x00"                                   # test esi,esi / jz skip
        jz_skip = len(code) - 1
        code += b"\xff\x93" + struct.pack("<i", slot_time - here1)    # call [GetTime]
        code += b"\xd9\x5e\x38"                                       # fstp dword [esi+0x38]
        code += b"\xc6\x46\x34\x00"                                   # mov byte [esi+0x34],0
        skip = len(code)
        code[je_skip] = skip - (je_skip + 1)
        code[jz_skip] = skip - (jz_skip + 1)
        # a bomb ticking or just blown up (state 1 / 2): remember when (the "__timeout__" below waits for its win even
        # when the object has already left the scene's list - it did: "fuera de tiempo, gana el rojo" at the boom)
        code += b"\x8b\x95" + struct.pack("<I", _LIST_N)              # mov edx,[ebp+count]
        code += b"\x8b\xbd" + struct.pack("<I", _LIST_PTR)            # mov edi,[ebp+array]
        code += b"\x85\xd2\x74\x00"                                   # test edx,edx / jz seen_end
        jz_se1 = len(code) - 1
        code += b"\x85\xff\x74\x00"                                   # test edi,edi / jz seen_end
        jz_se2 = len(code) - 1
        loop_s = len(code)
        code += b"\x8b\x07\x85\xc0\x74\x00"                           # mov eax,[edi] / test eax,eax / jz next_s
        jz_ns = len(code) - 1
        code += b"\x8b\x80" + struct.pack("<I", _STATE)              # mov eax,[eax+state]
        code += b"\x48\x83\xf8\x01\x77\x00"                           # dec eax / cmp eax,1 / ja next_s
        ja_ns = len(code) - 1
        code += b"\xff\x93" + struct.pack("<i", slot_time - here1)    # call [GetTime]
        code += b"\xd9\x9b" + rel_ebx(seen_va, here1, True)          # fstp dword [ebx+seen]
        code += b"\xeb\x00"                                           # jmp seen_end
        jmp_se = len(code) - 1
        next_s = len(code)
        code[jz_ns] = next_s - (jz_ns + 1)
        code[ja_ns] = next_s - (ja_ns + 1)
        code += b"\x83\xc7\x04\x4a\x75" + bytes([(loop_s - (len(code) + 6)) & 0xFF])  # add edi,4 / dec edx / jnz
        seen_end = len(code)
        for at in (jz_se1, jz_se2, jmp_se):
            code[at] = seen_end - (at + 1)
        code += b"\x8b\xcd"                                           # mov ecx,ebp
    if abs(fuse_seconds * 1000.0 - BOMB_FUSE_MS) >= 1.0:
        code += b"\x8b\x91" + struct.pack("<I", _LIST_N)              # mov edx,[ecx+count]
        code += b"\x8b\xb9" + struct.pack("<I", _LIST_PTR)            # mov edi,[ecx+array]
        code += b"\x85\xd2\x0f\x84" + struct.pack("<i", 0)            # test edx,edx / jz run_done
        jz_r1 = len(code) - 4
        code += b"\x85\xff\x0f\x84" + struct.pack("<i", 0)            # test edi,edi / jz run_done
        jz_r2 = len(code) - 4
        loop = len(code)
        code += b"\x8b\x07"                                           # mov eax,[edi]
        code += b"\x85\xc0\x0f\x84" + struct.pack("<i", 0)            # test eax,eax / jz next
        jz_n1 = len(code) - 4
        code += b"\x83\xb8" + struct.pack("<I", _STATE) + b"\x01"     # cmp dword [eax+state],1
        code += b"\x0f\x85" + struct.pack("<i", 0)                    # jne next
        jz_n2 = len(code) - 4
        code += b"\x8b\xb0" + struct.pack("<I", _PLANTED)             # mov esi,[eax+planted]
        code += b"\x8d\x8b" + rel_ebx(table_va, here1, True)          # lea ecx,[ebx+table]
        code += b"\x55\x6a\x04\x5d"                                   # push ebp / push 4 / pop ebp  (ebp = 4)
        seek = len(code)
        code += b"\x39\x01\x75\x05\x39\x71\x04\x74" + b"\x00"         # cmp [ecx],eax / jne +5 / cmp [ecx+4],esi / je seen
        je_seen = len(code) - 1
        code += b"\x83\xc1\x08\x4d\x75" + bytes([(seek - (len(code) + 6)) & 0xFF])   # add ecx,8 / dec ebp / jnz seek
        # not seen: move it, then remember it in the next slot
        code += b"\xd9\x80" + struct.pack("<I", _PLANTED)             # fld dword [eax+planted]
        k_d1 = len(code) + 2
        code += b"\xd8\x83\x00\x00\x00\x00"                           # fadd dword [ebx+delta]
        code += b"\xd9\x98" + struct.pack("<I", _PLANTED)             # fstp dword [eax+planted]
        code += b"\xd9\x80" + struct.pack("<I", _SEEN_AT)             # fld dword [eax+seen]
        k_d2 = len(code) + 2
        code += b"\xd8\x83\x00\x00\x00\x00"                           # fadd dword [ebx+delta]
        code += b"\xd9\x98" + struct.pack("<I", _SEEN_AT)             # fstp dword [eax+seen]
        code += b"\x8b\xb0" + struct.pack("<I", _PLANTED)             # mov esi,[eax+planted]   (the moved time)
        code += b"\x8b\x8b" + rel_ebx(table_va + 0x20, here1, True)   # mov ecx,[ebx+next]
        code += b"\x83\xe1\x03"                                       # and ecx,3
        code += b"\x8d\x8c\xcb" + rel_ebx(table_va, here1, True)      # lea ecx,[ebx+ecx*8+table]
        code += b"\x89\x01\x89\x71\x04"                               # mov [ecx],eax / mov [ecx+4],esi
        code += b"\xff\x83" + rel_ebx(table_va + 0x20, here1, True)   # inc dword [ebx+next]
        seen = len(code)
        code[je_seen] = (seen - (je_seen + 1)) & 0xFF
        code += b"\x5d"                                               # pop ebp
        nxt = len(code)
        code += b"\x83\xc7\x04\x4a\x0f\x85" + struct.pack("<i", loop - (len(code) + 10))   # add edi,4 / dec edx / jnz loop
        run_done = len(code)
        for at in (jz_r1, jz_r2):
            struct.pack_into("<i", code, at, run_done - (at + 4))
        for at in (jz_n1, jz_n2):
            struct.pack_into("<i", code, at, nxt - (at + 4))
        if code[je_seen] >= 0x80:
            raise ValueError("bomb code too long")
    code += b"\x61" + _FS0                                            # popad / the Run's own line
    code += b"\xe9" + struct.pack("<i", (r_va + 6) - (cave_va + len(code) + 5))
    # ---------------------------------------------------------------- 2) "__timeout__": wait for a ticking bomb
    to_entry = len(code)
    code += b"\x60\xe8\x00\x00\x00\x00\x5b"                           # pushad / call $+5 / pop ebx
    here2 = cave_va + len(code) - 1
    jz_done = []
    k_fuse = k_ms = k_one = k_min = k_min2 = k_recent = k_wait = k_half = None
    if overtime:
        code += b"\x8b\x6c\x24\x24"                                   # mov ebp,[esp+0x24]   (the scene)
        code += b"\x8b\xb5" + struct.pack("<I", clock)                # mov esi,[ebp+clock]
        code += b"\x85\xf6\x0f\x84" + struct.pack("<i", 0)            # test esi,esi / jz done
        jz_done.append(len(code) - 4)
        jx_let = []
        if over is not None:                                          # the round is already won: nothing to do
            code += b"\x80\xbd" + struct.pack("<I", over) + b"\x00"     # cmp byte [ebp+over],0
            code += b"\x0f\x85" + struct.pack("<i", 0)                # jne let_go
            jx_let.append(len(code) - 4)
        code += b"\x83\x7e\x2c\x00"                                   # cmp dword [esi+0x2C],0   minutes
        code += b"\x0f\x85" + struct.pack("<i", 0)                    # jne let_go   (a new round's clock)
        jx_let.append(len(code) - 4)
        code += b"\xd9\x46\x30"                                       # fld dword [esi+0x30]     seconds
        k_half = len(code) + 2
        code += b"\xd8\x9b\x00\x00\x00\x00"                           # fcomp dword [ebx+0.5]
        code += b"\xdf\xe0\xf6\xc4\x41"                               # fnstsw ax / test ah,0x41
        code += b"\x0f\x84" + struct.pack("<i", 0)                    # jz let_go    (> 0.5 s left: not 0:00)
        jx_let.append(len(code) - 4)
        code += b"\x8b\x95" + struct.pack("<I", _LIST_N)              # mov edx,[ebp+count]
        code += b"\x8b\xbd" + struct.pack("<I", _LIST_PTR)            # mov edi,[ebp+array]
        code += b"\x85\xd2\x0f\x84" + struct.pack("<i", 0)            # test edx,edx / jz none
        jz_none = [len(code) - 4]
        code += b"\x85\xff\x0f\x84" + struct.pack("<i", 0)            # test edi,edi / jz none
        jz_none.append(len(code) - 4)
        loop2 = len(code)
        code += b"\x8b\x07\x85\xc0\x74\x0d"                           # mov eax,[edi] / test eax,eax / jz +13
        code += b"\x83\xb8" + struct.pack("<I", _STATE) + b"\x01"     # cmp dword [eax+state],1
        code += b"\x0f\x84" + struct.pack("<i", 0)                    # je overtime
        je_ot = len(code) - 4
        code += b"\x83\xc7\x04\x4a\x75" + bytes([(loop2 - (len(code) + 6)) & 0xFF])   # add edi,4 / dec edx / jnz loop2
        for at in jz_none:
            struct.pack_into("<i", code, at, len(code) - (at + 4))
        # none ticking: a bomb ticking or blown up a moment ago (seen by the scene's Run, even if it already left the
        # list) still wins the round - its zone needs a few frames to count as destroyed, 0:00 must not come first
        code += b"\xff\x93" + struct.pack("<i", slot_time - here2)    # call [GetTime]              now
        code += b"\xd8\xa3" + rel_ebx(seen_va, here2, True)          # fsub dword [ebx+seen]       now - seen
        k_recent = len(code) + 2
        code += b"\xd8\x9b\x00\x00\x00\x00"                           # fcomp dword [ebx+3000]
        code += b"\xdf\xe0\xf6\xc4\x41"                               # fnstsw ax / test ah,0x41
        code += b"\x0f\x85" + struct.pack("<i", 0)                    # jnz wait   (now - seen <= 3 s)
        jnz_wait = len(code) - 4
        code += b"\xe9" + struct.pack("<i", 0)                        # jmp done
        jz_done.append(len(code) - 4)
        wait = len(code)
        struct.pack_into("<i", code, jnz_wait, wait - (jnz_wait + 4))
        k_wait = len(code) + 2
        code += b"\xd9\x83\x00\x00\x00\x00"                           # fld dword [ebx+0.9]   (0:00 on the clock)
        code += b"\xeb\x00"                                           # jmp set_clock
        jmp_set = len(code) - 1
        ot = len(code)
        struct.pack_into("<i", code, je_ot, ot - (je_ot + 4))
        code += b"\x8b\xf8"                                           # mov edi,eax
        code += b"\xff\x93" + struct.pack("<i", slot_time - here2)    # call [GetTime]              now
        code += b"\xd8\xa7" + struct.pack("<I", _PLANTED)             # fsub dword [edi+planted]    now - planted
        k_fuse = len(code) + 2
        code += b"\xd8\xab\x00\x00\x00\x00"                           # fsubr dword [ebx+20000]     ms left
        k_ms = len(code) + 2
        code += b"\xd8\x8b\x00\x00\x00\x00"                           # fmul dword [ebx+0.001]
        k_one = len(code) + 2
        code += b"\xd8\x83\x00\x00\x00\x00"                           # fadd dword [ebx+0.05]  (the clock shows
        k_min = len(code) + 2                                         # whole seconds: 0:00 as it blows up)
        code += b"\xd8\x93\x00\x00\x00\x00"                           # fcom dword [ebx+0.25]
        code += b"\xdf\xe0\xf6\xc4\x01\x74\x00"                       # fnstsw ax / test ah,1 / jz keep
        jz_keep = len(code) - 1
        code += b"\xdd\xd8"                                           # fstp st0    (late: 0.25 s, then again)
        k_min2 = len(code) + 2
        code += b"\xd9\x83\x00\x00\x00\x00"                           # fld dword [ebx+0.25]
        code[jz_keep] = len(code) - (jz_keep + 1)
        set_clock = len(code)
        code[jmp_set] = set_clock - (jmp_set + 1)
        code += b"\xd9\x5e\x30"                                       # fstp dword [esi+0x30]       clock seconds
        code += b"\xc7\x46\x2c\x00\x00\x00\x00"                       # mov dword [esi+0x2C],0      minutes
        code += b"\xff\x93" + struct.pack("<i", slot_time - here2)    # call [GetTime]
        code += b"\xd9\x5e\x38"                                       # fstp dword [esi+0x38]
        code += b"\xc6\x46\x34\x00"                                   # mov byte [esi+0x34],0       running again
        code += b"\xc6\x83" + struct.pack("<i", flag_va - here2) + b"\x01"   # mov byte [ebx+flag],1 (the clock
        code += b"\x61\xc3"                                           # popad / ret   stops itself after this: the
        #                                                               scene's next Run starts it again)
        let_go = len(code)                                            # not a 0:00 of this round: the game's
        for at in jx_let:                                             # handler would end the new round at once
            struct.pack_into("<i", code, at, let_go - (at + 4))
        code += b"\x61\xc3"                                           # popad / ret   (the clock as it is)
    done = len(code)
    for at in jz_done:
        struct.pack_into("<i", code, at, done - (at + 4))
    code += b"\x61" + _FS0
    code += b"\xe9" + struct.pack("<i", (h_va + 6) - (cave_va + len(code) + 5))
    while len(code) % 4:
        code += b"\xcc"
    consts = len(code)
    code += struct.pack("<ffffffff", fuse_seconds * 1000.0 - BOMB_FUSE_MS, BOMB_FUSE_MS, 0.001, 0.05, 0.25, 3000.0,
                        0.9, 0.5)
    if abs(fuse_seconds * 1000.0 - BOMB_FUSE_MS) >= 1.0:
        for at in (k_d1, k_d2):
            struct.pack_into("<i", code, at, (cave_va + consts) - here1)
    for at, k in ((k_fuse, 4), (k_ms, 8), (k_one, 12), (k_min, 16), (k_min2, 16), (k_recent, 20), (k_wait, 24),
                  (k_half, 28)):
        if at is not None:
            struct.pack_into("<i", code, at, (cave_va + consts + k) - here2)
    tail = struct.pack("<I", cave) + _OT_TAG + struct.pack("<IfBB", code_vs, fuse_seconds * 1000.0, int(bool(overtime)),
                                                           BOMB_CODE_VERSION)
    blob = bytes(code) + tail
    if len(blob) > raw_end - cave:
        raise ValueError("no room for the new code in this DLL")
    data[cave:cave + len(blob)] = blob
    data[r:r + 6] = b"\xe9" + struct.pack("<i", (cave_va + run_entry) - (r_va + 5)) + b"\x90"
    data[h:h + 6] = b"\xe9" + struct.pack("<i", (cave_va + to_entry) - (h_va + 5)) + b"\x90"
    need = cave + len(blob) - text["ro"]
    if text["vs"] < need:
        struct.pack_into("<I", data, text["hdr"] + 8, need)
    open(dst, "wb").write(bytes(data))
    return fuse_seconds, bool(overtime)


def bomb_fuse(data: bytes) -> float:
    """Seconds from planting to the explosion with this DO mode DLL (the game's: 20)."""
    got = bomb_rules(data)
    return got[0] if got else BOMB_FUSE_MS / 1000.0
