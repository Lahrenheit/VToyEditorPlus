# fix_shower: what a map wants of Marbella's shower (vtKernel's vtShower, as AddShower returns it), right after it is
# made.  Shared by bombzones.s (the DO copies) and weather.s (any other mode DLL).  In: eax = the shower (not 0),
# ebp = the section's start.  Keeps every register.  Needs (offsets from the section's start): W_CALM (dword: 1 = calm
# rain), W_LOAD / W_REL (IAT slots of LoadSound / ReleaseSound - section; 0: none), W_SND (7 x 64 bytes: strlen + 1, then
# the name of the sound to use instead of the shower's own: +0xB0 the rain, +0xB4..+0xC8 the six thunders; 0: keep),
# W_CS (8 bytes: a CString).
#   calm:   no lightning flashes (+0xE8 = 0) and no thunder: the six thunder sounds released and emptied (every use of a
#           sound in vtShower skips an empty one).
#   sounds: the shower's own sound released and the map's quieter copy loaded instead, as vtShower loads its own
#           (LoadSound(name, false, 0, 1e6)); vtShower releases it at its end as it does its own.
fix_shower:
        pushad
        mov     esi, eax
        cmp     dword ptr [ebp+W_CALM], 0
        je      fs_vol
        mov     byte ptr [esi+0xe8], 0
        mov     ebx, 0xb4
fs_c:
        mov     eax, [esi+ebx]
        mov     dword ptr [esi+ebx], 0
        test    eax, eax
        jz      fs_cn
        cmp     dword ptr [ebp+W_REL], 0
        je      fs_cn
        push    eax
        mov     eax, [ebp+W_REL]
        call    dword ptr [ebp+eax]
        add     esp, 4
fs_cn:
        add     ebx, 4
        cmp     ebx, 0xcc
        jb      fs_c
fs_vol:
        cmp     dword ptr [ebp+W_LOAD], 0
        je      fs_done
        cmp     dword ptr [ebp+W_REL], 0
        je      fs_done
        xor     ebx, ebx
fs_v:
        mov     edi, ebx
        shl     edi, 6
        cmp     dword ptr [ebp+edi+W_SND], 0
        je      fs_vn
        mov     eax, [esi+ebx*4+0xb0]
        test    eax, eax                           # calm: its thunder is gone already - it stays gone
        jz      fs_vn
        push    eax
        mov     eax, [ebp+W_REL]
        call    dword ptr [ebp+eax]
        add     esp, 4
        lea     eax, [ebp+edi+W_SND+4]
        mov     [ebp+W_CS], eax
        mov     eax, [ebp+edi+W_SND]
        mov     [ebp+W_CS+4], eax
        push    0x49742400                         # 1e6
        push    0
        push    0
        lea     eax, [ebp+W_CS]
        push    eax
        mov     eax, [ebp+W_LOAD]
        call    dword ptr [ebp+eax]
        add     esp, 16
        mov     [esi+ebx*4+0xb0], eax
fs_vn:
        inc     ebx
        cmp     ebx, 7
        jb      fs_v
fs_done:
        popad
        ret
