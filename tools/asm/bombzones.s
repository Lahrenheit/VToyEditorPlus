# Code of the ".vtoyz" section that patch_bomb_zones (vtoy/dllpatch.py) adds to a copy of the DO mode DLL
# (mp_DestroyTheTarget.dll and its per-map twins).  Assembled with GNU as (tools/asm/build.sh); the bytes are pasted
# into dllpatch.py (_BZ_CODE).  Position independent: ebp = start of the section (call/pop); every address of the DLL
# is kept as a distance from the section (the PARAMS block, filled by the patcher), so a rebased DLL works too.
#
#   check:  the round's "is bombZone destroyed?" test of SceneDestroyTheTarget::Run (edi = ObjectByName("bombZone"),
#           esi = the scene).  A zone counts as destroyed while it explodes (BombZone +0x178, set ~60 frames) or after
#           (its destroyed model is shown: [zone+0x164] actor, visible byte +0x64 - ActorGetVisible).  "any": one
#           destroyed zone wins the round; "all": every zone of the list that is in the scene, bombZone too.
#           HUD: the icon pair of each zone (made in init) shows intact / destroyed.
#           Minimap: it points at the zone nearest to the local player (CGame::mainCharacter) that is not destroyed
#           yet (Radar::SetTargetName(0, name), only when it changes; ClearTarget(0) when none is left).
#   init:   end of the scene's constructor: the rain (if on), then one icon pair per zone (the objective icons of mp_do_plaza, from
#           armas_grupo_345.tex, at the same place on screen), only for the plain DO mode ([scene+0x630] = 2).
        .intel_syntax noprefix
        .code32
        .text
        .set P,       0x800          # PARAMS (written by the patcher)
        .set P_WIN,   P+0x00         # win  - section
        .set P_NOWIN, P+0x04         # nowin - section
        .set P_BACK,  P+0x08         # constructor: the line after the hook - section
        .set P_OBN,   P+0x0c         # IAT slot of ObjectByName - section
        .set P_ADD,   P+0x10         # IAT slot of AddSprite - section
        .set P_SSV,   P+0x14         # IAT slot of SpriteSetVisible - section
        .set P_CONV,  P+0x18         # IAT slot of ConvertPixelToRender - section
        .set P_TEX,   P+0x1c         # "armas_grupo_345.tex" - section
        .set P_ALL,   P+0x20         # 1 = all zones must blow up
        .set P_HUD,   P+0x24         # 1 = icons on the HUD
        .set P_N,     P+0x28         # number of zones (bombZone first)
        .set P_TEXLEN,P+0x2c         # strlen + 1
        .set P_LENS,  P+0x30         # 6 x (strlen + 1) of the names
        .set P_RADAR, P+0x48         # 1 = the minimap points at the nearest zone not destroyed yet
        .set P_MAIN,  P+0x4c         # IAT slot of CGame::mainCharacter (a variable: the local player) - section
        .set P_AGP,   P+0x50         # IAT slot of ActorGetPosition - section
        .set P_DIST,  P+0x54         # IAT slot of Distance2 - section
        .set P_STN,   P+0x58         # IAT slot of Radar::SetTargetName - section
        .set P_CLR,   P+0x5c         # IAT slot of Radar::ClearTarget - section
        .set P_NAMES, P+0x60         # 6 x 32 bytes: the names (0: bombZone, not used)
        .set P_RAIN,  P+0x120        # 1 = rain (Marbella's shower, AddShower) for the whole scene
        .set P_SHOW,  P+0x124        # IAT slot of AddShower (a new import of the copy) - section
        .set P_RRO,   P+0x128        # IAT slot of RemoveRenderObject (new import) - section
        .set P_GAME,  P+0x12c        # IAT slot of CGame::main (a variable: the game) - section
        .set P_DBACK, P+0x130        # end of the scene: the line after the hook - section
        .set P_RW,    P+0x134        # the shower's width and depth (float, Marbella: 30000)
        .set P_CALM,  P+0x138        # 1 = rain without the storm: no lightning flashes, no thunder (see below)
        .set P_ILUM,  P+0x13c        # IAT slot of ShowerSetIlumRayo (new import) - section
        .set P_RPOS,  P+0x140        # 3 floats: where the shower is (Marbella: 0, 5000, 0)
        .set P_RDIR,  P+0x150        # 3 floats: the drops' speed (Marbella: 0, -1500, 0)
        .set P_SPLASH,P+0x160        # 1 = drops splash on the floor round the camera (mp_deathMatch on Marbella)
        .set P_CAM,   P+0x164        # IAT slot of CGame::camera (a variable: the camera object) - section
        .set P_VMTX,  P+0x168        # IAT slot of CameraGetViewMatrix (new import) - section
        .set P_GCOL,  P+0x16c        # IAT slot of vtMatrix::GetColumn (new import) - section
        .set P_CPOS,  P+0x170        # IAT slot of CameraGetPosition (new import) - section
        .set P_SINT,  P+0x174        # IAT slot of ShowerGetIntensidad (new import) - section
        .set P_RAND,  P+0x178        # IAT slot of Random (new import) - section
        .set P_GH,    P+0x17c        # IAT slot of GetHeight (new import) - section
        .set P_APS,   P+0x180        # IAT slot of AddParticleSystem (new import) - section
        .set P_SPCD,  P+0x184        # IAT slot of SetParticleCountDown (new import) - section
        .set P_TEX2,  P+0x190        # "gota_salpica.tex"
        .set P_TEX2L, P+0x1a4        # its strlen + 1
        .set P_AHEAD, P+0x1a8        # float: the square of drops is this far ahead of the camera (2000)
        .set P_SQ,    P+0x1ac        # float: its side (4000)
        .set P_HALF,  P+0x1b0        # float 0.5
        .set P_PER,   P+0x1b4        # float: drops a frame = the rain's intensity x this (20)
        .set P_UP,    P+0x1c0        # 3 floats: a splash's first speed (0, 300, 0)
        .set P_GRAV,  P+0x1d0        # 3 floats: its gravity (0, -1700, 0)
        .set P_RSPR,  P+0x1e0        # IAT slot of RemoveRenderObject (the game's own import) - section; 0: none
        .set P_LOADS, P+0x1e4        # IAT slot of LoadSound (new import) - section; 0: none
        .set P_RELS,  P+0x1e8        # IAT slot of ReleaseSound (new import) - section; 0: none
        .set P_SNDS,  0xc00          # 7 x 64 bytes: the shower's sounds a map changes (fix_shower, shower.inc)
        .set V,       0xa00          # VARS
        .set V_IDS,   V+0x00         # 6 x (intact sprite, destroyed sprite)
        .set V_TMP,   V+0x40         # W, H, X, Y
        .set V_CSTR,  V+0x50         # a CString {ptr, len}
        .set V_STATE, V+0x60         # 6 bytes: 0 intact, 1 destroyed, 2 not in the scene
        .set V_OBJ,   V+0x80         # 6 x the zone objects of this frame
        .set V_PPOS,  V+0xa0         # the local player's position
        .set V_BEST,  V+0xb0         # nearest zone not destroyed (-1: none)
        .set V_BESTD, V+0xb4         # its distance squared (a positive float: compared as an int)
        .set V_TMPF,  V+0xb8
        .set V_LAST,  V+0xbc         # the zone the minimap shows + 1 (0: the game's own: bombZone)
        .set V_SCN,   V+0xc0         # splashes: the scene
        .set V_CAM,   V+0xc4         # the camera's id
        .set V_SHW,   V+0xc8         # the shower
        .set V_N,     V+0xcc         # drops this frame
        .set V_CX,    V+0xd0         # middle of the square of drops (3 floats)
        .set V_PT,    V+0xe0         # a drop: up in the air (3 floats)
        .set V_OUT,   V+0xf0         # where it meets the floor (3 floats)
        .set V_FWD,   V+0x100        # the camera's forward (3 floats)
        .set V_CPOS,  V+0x110        # the camera's position (3 floats)
        .set V_MTX,   V+0x120        # the camera's view matrix (16 floats)
        .set V_CS2,   V+0x160        # a CString {ptr, len}: the splash texture
        .set V_NSPR,  V+0x170        # icon pairs made by init (taken off the screen by dtor)
        .set V_CSW,   V+0x178        # a CString {ptr, len}: a sound's name (fix_shower)
        .set V_RAD,   V+0x180        # 6 x the radius of a destroyed zone (put back when it stands again)
        .set V_RADO,  V+0x1a0        # 6 x the zone it belongs to (0: none taken)
        .set W_CALM,  P_CALM
        .set W_LOAD,  P_LOADS
        .set W_REL,   P_RELS
        .set W_SND,   P_SNDS
        .set W_CS,    V_CSW

check:
        pushad
        call    1f
1:      pop     ebp
        sub     ebp, offset 1b - check
        xor     ebx, ebx
cl_loop:
        cmp     ebx, [ebp+P_N]
        jge     cl_done
        test    ebx, ebx
        jnz     cl_byname
        mov     eax, [esp]                    # the saved edi: the DLL's own ObjectByName("bombZone")
        jmp     cl_got
cl_byname:
        mov     eax, ebx
        shl     eax, 5
        lea     ecx, [ebp+eax+P_NAMES]
        mov     edx, [ebp+ebx*4+P_LENS]
        mov     [ebp+V_CSTR], ecx
        mov     [ebp+V_CSTR+4], edx
        lea     ecx, [ebp+V_CSTR]
        push    ecx
        mov     eax, [ebp+P_OBN]
        call    dword ptr [ebp+eax]
        add     esp, 4
cl_got:
        mov     [ebp+ebx*4+V_OBJ], eax
        mov     byte ptr [ebp+ebx+V_STATE], 2
        test    eax, eax
        jz      cl_next
        mov     byte ptr [ebp+ebx+V_STATE], 1
        cmp     byte ptr [eax+0x178], 0
        jne     cl_next
        mov     ecx, [eax+0x164]
        test    ecx, ecx
        jz      cl_intact
        cmp     byte ptr [ecx+0x64], 0
        jne     cl_next
cl_intact:
        mov     byte ptr [ebp+ebx+V_STATE], 0
cl_next:
        inc     ebx
        jmp     cl_loop
cl_done:
        call    rzero                                # (in the second piece: no room here)
        cmp     dword ptr [ebp+P_RADAR], 0           # the minimap: the nearest zone still standing
        je      cl_hud
        mov     esi, [esp+4]                         # the saved esi: the scene
        cmp     dword ptr [esi+0x630], 2             # the plain DO mode only
        jne     cl_hud
        mov     eax, [ebp+P_MAIN]
        mov     eax, [ebp+eax]                       # &CGame::mainCharacter
        mov     eax, [eax]                           # the local player (none on a dedicated server)
        test    eax, eax
        jz      cl_hud
        push    dword ptr [eax+0xa0]
        mov     eax, [ebp+P_AGP]
        call    dword ptr [ebp+eax]
        add     esp, 4
        mov     ecx, [eax]
        mov     [ebp+V_PPOS], ecx
        mov     ecx, [eax+4]
        mov     [ebp+V_PPOS+4], ecx
        mov     ecx, [eax+8]
        mov     [ebp+V_PPOS+8], ecx
        mov     dword ptr [ebp+V_BEST], -1
        mov     dword ptr [ebp+V_BESTD], 0x7f7fffff
        xor     ebx, ebx
rd_loop:
        cmp     ebx, [ebp+P_N]
        jge     rd_done
        cmp     byte ptr [ebp+ebx+V_STATE], 0
        jne     rd_next
        mov     eax, [ebp+ebx*4+V_OBJ]
        push    dword ptr [eax+0xa0]
        mov     eax, [ebp+P_AGP]
        call    dword ptr [ebp+eax]
        add     esp, 4
        lea     ecx, [ebp+V_PPOS]
        push    ecx
        push    eax
        mov     eax, [ebp+P_DIST]
        call    dword ptr [ebp+eax]
        add     esp, 8
        fstp    dword ptr [ebp+V_TMPF]
        mov     eax, [ebp+V_TMPF]
        cmp     eax, [ebp+V_BESTD]
        jge     rd_next
        mov     [ebp+V_BESTD], eax
        mov     [ebp+V_BEST], ebx
rd_next:
        inc     ebx
        jmp     rd_loop
rd_done:
        mov     eax, [ebp+V_BEST]
        inc     eax
        cmp     eax, [ebp+V_LAST]
        je      cl_hud
        mov     ecx, [esi+0x268]                     # the scene's minimap (Radar)
        test    ecx, ecx
        jz      cl_hud
        mov     [ebp+V_LAST], eax
        dec     eax
        js      rd_clear
        mov     edx, eax
        shl     edx, 5
        lea     edx, [ebp+edx+P_NAMES]
        mov     [ebp+V_CSTR], edx
        mov     edx, [ebp+eax*4+P_LENS]
        mov     [ebp+V_CSTR+4], edx
        lea     edx, [ebp+V_CSTR]
        push    edx
        push    0
        mov     eax, [ebp+P_STN]
        call    dword ptr [ebp+eax]                  # Radar::SetTargetName(0, name) (thiscall)
        jmp     cl_hud
rd_clear:
        push    0
        mov     eax, [ebp+P_CLR]
        call    dword ptr [ebp+eax]                  # Radar::ClearTarget(0)
cl_hud:
        cmp     dword ptr [ebp+P_HUD], 0
        je      decide
        xor     ebx, ebx
hud_loop:
        cmp     ebx, [ebp+P_N]
        jge     decide
        mov     eax, [ebp+ebx*8+V_IDS]
        test    eax, eax
        jz      hud_next
        xor     edx, edx
        cmp     byte ptr [ebp+ebx+V_STATE], 0
        sete    dl
        push    edx
        push    eax
        mov     eax, [ebp+P_SSV]
        call    dword ptr [ebp+eax]
        add     esp, 8
        xor     edx, edx
        cmp     byte ptr [ebp+ebx+V_STATE], 1
        sete    dl
        push    edx
        push    dword ptr [ebp+ebx*8+V_IDS+4]
        mov     eax, [ebp+P_SSV]
        call    dword ptr [ebp+eax]
        add     esp, 8
hud_next:
        inc     ebx
        jmp     hud_loop
decide:
        xor     ebx, ebx
        cmp     dword ptr [ebp+P_ALL], 0
        jne     all_mode
any_loop:
        cmp     ebx, [ebp+P_N]
        jge     nowin
        cmp     byte ptr [ebp+ebx+V_STATE], 1
        je      win
        inc     ebx
        jmp     any_loop
all_mode:
        cmp     byte ptr [ebp+V_STATE], 2         # no bombZone: never
        je      nowin
all_loop:
        cmp     ebx, [ebp+P_N]
        jge     win
        cmp     byte ptr [ebp+ebx+V_STATE], 0
        je      nowin
        inc     ebx
        jmp     all_loop
win:
        mov     eax, [ebp+P_WIN]
        jmp     leave
nowin:
        mov     eax, [ebp+P_NOWIN]
leave:
        add     eax, ebp
        mov     [esp+28], eax                     # popad gives it back in eax
        popad
        jmp     eax

init:
        lea     ecx, [esp+0x4c]                   # the two lines the hook took
        mov     byte ptr [esp+0x10c], 2
        pushad
        call    2f
2:      pop     ebp
        sub     ebp, offset 2b - check
        mov     dword ptr [ebp+V_LAST], 0            # a new scene: its minimap shows bombZone (the game's own)
        cmp     dword ptr [ebp+P_RAIN], 0
        je      in_norain
        lea     eax, [ebp+P_RDIR]                    # AddShower(scene, &pos, w, d, &speed), as mp_deathMatch on Marbella
        push    eax
        push    dword ptr [ebp+P_RW]
        push    dword ptr [ebp+P_RW]
        lea     eax, [ebp+P_RPOS]
        push    eax
        push    esi
        mov     eax, [ebp+P_SHOW]
        call    dword ptr [ebp+eax]
        add     esp, 20
        test    eax, eax
        jz      in_norain
        call    fix_shower                         # calm rain / the map's quieter sounds (shower.inc)
in_kept:
        mov     ecx, [ebp+P_GAME]
        mov     ecx, [ebp+ecx]
        mov     ecx, [ecx]
        test    ecx, ecx
        jz      in_norain
        mov     [ecx+0x1334], eax                    # the game keeps the shower there (CGame +0x1334, like the game)
in_norain:
        mov     dword ptr [ebp+V_NSPR], 0
        cmp     dword ptr [ebp+P_HUD], 0
        je      in_done
        cmp     dword ptr [esi+0x630], 2          # the plain DO mode only (not plaza / asalto)
        jne     in_done
        xor     ebx, ebx
in_loop:
        cmp     ebx, [ebp+P_N]
        jge     in_done
        push    0x300
        push    0x400
        lea     eax, [ebp+V_TMP+4]
        push    eax
        lea     eax, [ebp+V_TMP]
        push    eax
        push    0x1f
        push    0x1f
        mov     eax, [ebp+P_CONV]
        call    dword ptr [ebp+eax]
        add     esp, 24
        push    0x300
        push    0x400
        lea     eax, [ebp+V_TMP+12]
        push    eax
        lea     eax, [ebp+V_TMP+8]
        push    eax
        push    0x53
        imul    eax, ebx, 36
        add     eax, 0x35d
        push    eax
        mov     eax, [ebp+P_CONV]
        call    dword ptr [ebp+eax]
        add     esp, 24
        mov     eax, [ebp+P_TEX]
        add     eax, ebp
        mov     [ebp+V_CSTR], eax
        mov     eax, [ebp+P_TEXLEN]
        mov     [ebp+V_CSTR+4], eax
        push    0x3f5f0000                         # v1  the intact icon
        push    0x3df80000                         # u1
        push    0x3f400000                         # v0
        push    0                                  # u0
        call    in_sprite
        mov     [ebp+ebx*8+V_IDS], eax
        push    0x3f5f0000                         # the destroyed icon
        push    0x3e7c0000
        push    0x3f400000
        push    0x3e000000
        call    in_sprite
        mov     [ebp+ebx*8+V_IDS+4], eax
        push    0
        push    eax
        mov     eax, [ebp+P_SSV]
        call    dword ptr [ebp+eax]
        add     esp, 8
        inc     ebx
        mov     [ebp+V_NSPR], ebx
        jmp     in_loop
in_done:
        mov     eax, [ebp+P_BACK]
        add     eax, ebp
        mov     [esp+28], eax
        popad
        jmp     eax
in_sprite:                                         # AddSprite(&tex, X, Y, W, H, 8, u0, v0, u1, v1); 4 floats pushed
        pop     ecx                                # by the caller before the call, taken off here
        push    8
        push    dword ptr [ebp+V_TMP+4]
        push    dword ptr [ebp+V_TMP]
        push    dword ptr [ebp+V_TMP+12]
        push    dword ptr [ebp+V_TMP+8]
        lea     eax, [ebp+V_CSTR]
        push    eax
        mov     [ebp+V+0x70], ecx                  # the return address, kept aside
        mov     eax, [ebp+P_ADD]
        call    dword ptr [ebp+eax]
        add     esp, 40
        jmp     dword ptr [ebp+V+0x70]

dtor:                                              # the scene's end, at its start (where mp_deathMatch takes its
                                                   # shower off, before RemoveSceneObjects / DeleteSky free the
                                                   # scene's things - after them, de_aztec closed the game on
                                                   # leaving): the shower goes
        pushad                                     # too (RemoveRenderObject, as mp_deathMatch does), and the icons
        call    3f                                 # (RemoveSprite: they stayed on the screen in the next map)
3:      pop     ebp
        sub     ebp, offset 3b - check
        cmp     dword ptr [ebp+P_RSPR], 0
        je      dt_rain
dt_sp:
        mov     ebx, [ebp+V_NSPR]
        test    ebx, ebx
        jle     dt_rain
        dec     ebx
        mov     [ebp+V_NSPR], ebx
        push    dword ptr [ebp+ebx*8+V_IDS]
        mov     eax, [ebp+P_RSPR]
        call    dword ptr [ebp+eax]
        add     esp, 4
        push    dword ptr [ebp+ebx*8+V_IDS+4]
        mov     eax, [ebp+P_RSPR]
        call    dword ptr [ebp+eax]
        add     esp, 4
        jmp     dt_sp
dt_rain:
        cmp     dword ptr [ebp+P_RAIN], 0
        je      dt_done
        mov     ecx, [ebp+P_GAME]
        mov     ecx, [ebp+ecx]
        mov     ecx, [ecx]
        test    ecx, ecx
        jz      dt_done
        mov     eax, [ecx+0x1334]
        test    eax, eax
        jz      dt_done
        mov     dword ptr [ecx+0x1334], 0
        push    eax
        mov     eax, [ebp+P_RRO]
        call    dword ptr [ebp+eax]
        add     esp, 4
dt_done:
        mov     eax, [ebp+P_DBACK]
        add     eax, ebp
        mov     [esp+28], eax
        popad
        push    eax                                # back to the game, after
        mov     eax, [esi+0x604]                   # the two lines the hook took (its test's flags go back too:
        test    eax, eax                           # ret keeps them)
        ret

splash:                                            # the scene's Run, every frame on every PC: the 4 pushes and 2
        push    ebx                                # lines the hook took, then the splashes of mp_deathMatch on
        push    ebp                                # Marbella: drops in a 4000 x 4000 square 2000 ahead of the
        push    esi                                # camera, each one a short particle burst where it meets the floor
        push    edi
        mov     esi, ecx
        mov     [esp+0x4c], eax
        pushfd                                     # the game tests eax (the local player) before the hook: its
        pushad                                     # flags are kept for the jump after it
        call    4f
4:      pop     ebp
        sub     ebp, offset 4b - check
        cmp     dword ptr [ebp+P_SPLASH], 0
        je      sp_done
        test    eax, eax                           # no local player (a server): nothing to see
        jz      sp_done
        mov     [ebp+V_SCN], esi
        mov     ecx, [ebp+P_GAME]
        mov     ecx, [ebp+ecx]
        mov     ecx, [ecx]
        test    ecx, ecx
        jz      sp_done
        mov     eax, [ecx+0x1334]                  # the shower (no rain: no splashes)
        test    eax, eax
        jz      sp_done
        mov     [ebp+V_SHW], eax
        mov     ecx, [ebp+P_CAM]
        mov     ecx, [ebp+ecx]
        mov     ecx, [ecx]
        test    ecx, ecx
        jz      sp_done
        mov     ecx, [ecx+0x38]
        mov     [ebp+V_CAM], ecx
        push    ecx                                # CameraGetViewMatrix(&mtx, camera)
        lea     eax, [ebp+V_MTX]
        push    eax
        mov     eax, [ebp+P_VMTX]
        call    dword ptr [ebp+eax]
        add     esp, 8
        push    2                                  # mtx.GetColumn(&fwd, 2)  (thiscall)
        lea     eax, [ebp+V_FWD]
        push    eax
        lea     ecx, [ebp+V_MTX]
        mov     eax, [ebp+P_GCOL]
        call    dword ptr [ebp+eax]
        push    dword ptr [ebp+V_CAM]              # CameraGetPosition(&pos, camera)
        lea     eax, [ebp+V_CPOS]
        push    eax
        mov     eax, [ebp+P_CPOS]
        call    dword ptr [ebp+eax]
        add     esp, 8
        fld     dword ptr [ebp+V_FWD]              # forward on the ground, length 1 (none: +z)
        fmul    st, st(0)
        fld     dword ptr [ebp+V_FWD+8]
        fmul    st, st(0)
        faddp   st(1), st
        fsqrt
        fldz
        fcomip  st, st(1)
        jne     5f
        fstp    st(0)
        fldz
        fstp    dword ptr [ebp+V_FWD]
        fld1
        fstp    dword ptr [ebp+V_FWD+8]
        jmp     6f
5:      fld1
        fdiv    st, st(1)
        fstp    st(1)
        fld     st(0)
        fmul    dword ptr [ebp+V_FWD]
        fstp    dword ptr [ebp+V_FWD]
        fmul    dword ptr [ebp+V_FWD+8]
        fstp    dword ptr [ebp+V_FWD+8]
6:      fld     dword ptr [ebp+P_AHEAD]            # the middle of the square, 2000 up
        fmul    dword ptr [ebp+V_FWD]
        fadd    dword ptr [ebp+V_CPOS]
        fstp    dword ptr [ebp+V_CX]
        fld     dword ptr [ebp+P_AHEAD]
        fadd    dword ptr [ebp+V_CPOS+4]
        fstp    dword ptr [ebp+V_CX+4]
        fld     dword ptr [ebp+P_AHEAD]
        fmul    dword ptr [ebp+V_FWD+8]
        fadd    dword ptr [ebp+V_CPOS+8]
        fstp    dword ptr [ebp+V_CX+8]
        push    dword ptr [ebp+V_SHW]              # drops = ShowerGetIntensidad(shower) x 20
        mov     eax, [ebp+P_SINT]
        call    dword ptr [ebp+eax]
        add     esp, 4
        fmul    dword ptr [ebp+P_PER]
        fistp   dword ptr [ebp+V_N]
        mov     ebx, [ebp+V_N]
        test    ebx, ebx
        jle     sp_done
        cmp     ebx, 200
        jle     sp_loop
        mov     ebx, 200
sp_loop:
        mov     eax, [ebp+P_RAND]                  # z: the middle + 4000 x (Random() - 0.5)
        call    dword ptr [ebp+eax]
        fsub    dword ptr [ebp+P_HALF]
        fmul    dword ptr [ebp+P_SQ]
        fadd    dword ptr [ebp+V_CX+8]
        fstp    dword ptr [ebp+V_PT+8]
        mov     eax, [ebp+P_RAND]                  # x: the same
        call    dword ptr [ebp+eax]
        fsub    dword ptr [ebp+P_HALF]
        fmul    dword ptr [ebp+P_SQ]
        fadd    dword ptr [ebp+V_CX]
        fstp    dword ptr [ebp+V_PT]
        mov     eax, [ebp+V_CX+4]
        mov     [ebp+V_PT+4], eax
        lea     eax, [ebp+V_OUT]                   # GetHeight(&pt, &floor)
        push    eax
        lea     eax, [ebp+V_PT]
        push    eax
        mov     eax, [ebp+P_GH]
        call    dword ptr [ebp+eax]
        add     esp, 8
        test    al, al
        jz      sp_next
        lea     eax, [ebp+P_TEX2]
        mov     [ebp+V_CS2], eax
        mov     eax, [ebp+P_TEX2L]
        mov     [ebp+V_CS2+4], eax
        push    0                                  # AddParticleSystem(scene, "gota_salpica.tex", floor, up,
        push    0x91000004                         #   -0.5, 0.6, 0, 3, 20, 0.2, gravity, 0.97, ff000000,
        push    0x47c35000                         #   b7000000, 10, 10, 1, 100000, 91000004, 0): mp_deathMatch's
        push    0x3f800000
        push    0x41200000
        push    0x41200000
        push    0xb7000000
        push    0xff000000
        push    0x3f7851ec
        lea     eax, [ebp+P_GRAV]
        push    eax
        push    0x3e4ccccd
        push    0x41a00000
        push    0x40400000
        push    0
        push    0x3f19999a
        push    0xbf000000
        lea     eax, [ebp+P_UP]
        push    eax
        lea     eax, [ebp+V_OUT]
        push    eax
        lea     eax, [ebp+V_CS2]
        push    eax
        push    dword ptr [ebp+V_SCN]
        mov     eax, [ebp+P_APS]
        call    dword ptr [ebp+eax]
        add     esp, 0x50
        push    7                                  # SetParticleCountDown(particles, 7)
        push    eax
        mov     eax, [ebp+P_SPCD]
        call    dword ptr [ebp+eax]
        add     esp, 8
sp_next:
        dec     ebx
        jnz     sp_loop
sp_done:
        popad
        popfd
sp_ret: .byte   0xe9                               # jmp back to the game's Run (the patcher writes where)
        .long   0
code_end:
        .org    0x7e0
        .long   splash - check                     # where splash starts
        .long   sp_ret - check                     # its jump back (rel32 at +1)
        .org    0x7f0
        .long   init - check                       # where init starts (read by the patcher)
        .long   code_end - check                   # how long the code is
        .long   dtor - check                       # where dtor starts
        .long   code2_end - check                  # the end of the second piece (from 0x1c00: fix_shower)
        .org    0x1c00
        .include "shower.inc"
rzero:
        xor     ebx, ebx                             # a destroyed zone takes no second bomb: its radius 0 (nobody
rz_loop:                                             # "enters" it: no "Pon la bomba"), the radius back once the
        cmp     ebx, [ebp+P_N]                       # round's reset shows it standing again
        jge     rz_done
        mov     eax, [ebp+ebx*4+V_OBJ]
        test    eax, eax
        jz      rz_next
        cmp     [ebp+ebx*4+V_RADO], eax              # taken from another object (an earlier round / map): forget it
        je      rz_same
        mov     dword ptr [ebp+ebx*4+V_RADO], 0
rz_same:
        cmp     byte ptr [ebp+ebx+V_STATE], 1
        jne     rz_up
        cmp     dword ptr [ebp+ebx*4+V_RADO], 0
        jne     rz_next
        mov     ecx, [eax+0x160]
        mov     [ebp+ebx*4+V_RAD], ecx
        mov     [ebp+ebx*4+V_RADO], eax
        mov     dword ptr [eax+0x160], 0
        jmp     rz_next
rz_up:
        cmp     dword ptr [ebp+ebx*4+V_RADO], 0
        je      rz_next
        mov     ecx, [ebp+ebx*4+V_RAD]
        mov     [eax+0x160], ecx
        mov     dword ptr [ebp+ebx*4+V_RADO], 0
rz_next:
        inc     ebx
        jmp     rz_loop
rz_done:
        ret
code2_end:
