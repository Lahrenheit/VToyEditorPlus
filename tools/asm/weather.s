# Code of the ".vtoyw" section that patch_weather (vtoy/dllpatch.py) adds to a copy of a mode DLL that makes Marbella's
# rain (mp_deathMatch, mp_deathMatchTeam, mp_CaptureTheFlag ...: AddShower when the map is its rain map - the copy's
# map name is this map's, patch_map_name).  Its one "call [AddShower]" calls wstub instead: AddShower as before, then
# fix_shower (shower.inc) on the shower it made - calm rain, the map's quieter sounds.  Position independent (call/pop),
# addresses of the DLL kept as distances from the section (PARAMS, written by the patcher).
        .intel_syntax noprefix
        .code32
        .text
        .set P,       0x800
        .set P_SHOW,  P+0x00         # IAT slot of AddShower - section
        .set W_CALM,  P+0x04         # 1 = calm rain
        .set W_LOAD,  P+0x08         # IAT slot of LoadSound (new import) - section; 0: none
        .set W_REL,   P+0x0c         # IAT slot of ReleaseSound (new import) - section; 0: none
        .set V,       0xa00
        .set V_RET,   V+0x00         # the caller's return address
        .set W_CS,    V+0x08         # a CString {ptr, len}
        .set W_SND,   0xc00          # 7 x 64 bytes: the shower's sounds this map changes
wbase:
wstub:                                             # instead of "call [AddShower]": its arguments are on the stack
        call    1f
1:      pop     eax
        sub     eax, offset 1b - wbase
        pop     ecx                                # the caller's return address, kept aside
        mov     [eax+V_RET], ecx
        mov     ecx, [eax+P_SHOW]
        call    dword ptr [eax+ecx]                # AddShower(scene, &pos, w, d, &speed) -> eax = the shower
        pushad
        call    2f
2:      pop     ebp
        sub     ebp, offset 2b - wbase
        test    eax, eax
        jz      3f
        call    fix_shower
3:      mov     ecx, [ebp+V_RET]
        mov     [esp+24], ecx                      # popad gives it back in ecx (caller-saved)
        popad
        jmp     ecx                                # the caller takes its arguments off, as after the real call
        .include "shower.inc"
wend:
        .org    0x7f0
        .long   wend - wbase                       # how long the code is
