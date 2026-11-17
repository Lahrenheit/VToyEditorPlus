"""Windows taskbar / title-bar icon.

The taskbar shows the icon of the WINDOW (not the one embedded in the .exe), and when the editor runs from Python it groups the
window under python.exe.  So, on Windows:
  * ``set_app_id()`` (before the window exists) gives the process its own taskbar identity;
  * ``apply(hwnd, ico)`` loads the .ico with the Win32 API in the exact sizes Windows wants (big = taskbar / Alt+Tab,
    small = title bar) and sets them on the window and its class.  Without a .ico it uses the icon embedded in the .exe."""
from __future__ import annotations

import ctypes
import os
import sys

APP_ID = "Lahrenheit.VToyEditorPlus.1"


def set_app_id() -> None:
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(ctypes.c_wchar_p(APP_ID))
    except Exception:
        pass


def apply(hwnd, ico_path: str = "") -> bool:
    if sys.platform != "win32" or not hwnd:
        return False
    try:
        from ctypes import wintypes
        user32, shell32 = ctypes.windll.user32, ctypes.windll.shell32
        user32.LoadImageW.restype = wintypes.HANDLE
        user32.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT, ctypes.c_int, ctypes.c_int, wintypes.UINT]
        user32.SendMessageW.restype = ctypes.c_ssize_t
        user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, ctypes.c_size_t, ctypes.c_ssize_t]
        set_class = getattr(user32, "SetClassLongPtrW", None) or user32.SetClassLongW
        set_class.restype = ctypes.c_size_t
        set_class.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
        IMAGE_ICON, LR_LOADFROMFILE = 1, 0x10
        cxb, cyb = user32.GetSystemMetrics(11), user32.GetSystemMetrics(12)      # SM_CXICON / SM_CYICON
        cxs, cys = user32.GetSystemMetrics(49), user32.GetSystemMetrics(50)      # SM_CXSMICON / SM_CYSMICON
        big = small = None
        if ico_path and os.path.isfile(ico_path):
            big = user32.LoadImageW(None, ico_path, IMAGE_ICON, cxb, cyb, LR_LOADFROMFILE)
            small = user32.LoadImageW(None, ico_path, IMAGE_ICON, cxs, cys, LR_LOADFROMFILE)
        if not big and getattr(sys, "frozen", False):                            # the icon embedded in VToyEditor.exe
            lg, sm = wintypes.HICON(), wintypes.HICON()
            if shell32.ExtractIconExW(sys.executable, 0, ctypes.byref(lg), ctypes.byref(sm), 1) > 0:
                big, small = lg.value, sm.value
        if not big:
            return False
        hwnd = int(hwnd)
        WM_SETICON, ICON_SMALL, ICON_BIG = 0x0080, 0, 1
        user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, big)
        user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, small or big)
        set_class(hwnd, -14, big)                    # GCLP_HICON
        set_class(hwnd, -34, small or big)           # GCLP_HICONSM
        return True
    except Exception:
        return False
