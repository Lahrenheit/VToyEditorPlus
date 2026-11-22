"""Where the editor's messages go: the console window and / or ``vtoy_editor.log`` - both can be turned on and off while the
editor runs (Settings menu) and are remembered in vtoy_editor.json ("console", "log").

    setup(log)          take over print() and the error reports (call once, first thing)
    set_log(on)         write vtoy_editor.log or not
    set_console(on)     show the console window or not (Windows; a build without console gets one when asked)
"""
from __future__ import annotations

import os
import sys

_state = {"file": None, "path": "", "con": None, "setup": False}


def log_path() -> str:
    base = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.getcwd()
    return os.path.join(base, "vtoy_editor.log")


class _Tee:
    def __init__(self, which: str):
        self.which = which

    def _console(self):
        c = _state["con"]
        if c is not None:
            return c
        return sys.__stdout__ if self.which == "out" else sys.__stderr__

    def write(self, t):
        f = _state["file"]
        if f is not None:
            try:
                f.write(t)
            except Exception:
                pass
        c = self._console()
        if c is not None:
            try:
                c.write(t)
            except Exception:
                pass
        return len(t)

    def flush(self):
        for s in (_state["file"], self._console()):
            if s is not None:
                try:
                    s.flush()
                except Exception:
                    pass

    def isatty(self):
        return False


def _open_log(first: bool) -> str:
    path = log_path()
    mode = "w" if first else "a"
    try:
        f = open(path, mode, encoding="utf-8", buffering=1)
    except OSError:
        path = os.path.join(os.path.expanduser("~"), "vtoy_editor.log")
        f = open(path, mode, encoding="utf-8", buffering=1)
    _state["file"], _state["path"] = f, path
    try:
        import faulthandler
        faulthandler.enable(f)                     # even a hard crash leaves its trace in the log
    except Exception:
        pass
    return path


def setup(log: bool = True) -> str:
    """print() and errors go through here from now on.  Returns the log path ('' with the log off)."""
    import traceback
    if not _state["setup"]:
        sys.stdout, sys.stderr = _Tee("out"), _Tee("err")
        sys.excepthook = lambda et, ev, tb: traceback.print_exception(et, ev, tb)
        _state["setup"] = True
    path = _open_log(True) if log and _state["file"] is None else _state["path"]
    if log:
        import platform
        import time
        print(f"VToyEditor log {time.strftime('%Y-%m-%d %H:%M:%S')} | python {platform.python_version()} | {platform.platform()}")
    return path if log else ""


def log_on() -> bool:
    return _state["file"] is not None


def set_log(on: bool) -> str:
    if on and _state["file"] is None:
        first = not _state["path"]
        p = _open_log(first)
        print(f"log on: {p}")
        return p
    if not on and _state["file"] is not None:
        print("log off")
        try:
            import faulthandler
            faulthandler.disable()
            _state["file"].close()
        except Exception:
            pass
        _state["file"] = None
    return _state["path"]


# ------------------------------------------------------------------------------ the console window (Windows)
def _k32():
    import ctypes
    return ctypes.windll.kernel32


def console_visible() -> bool:
    if sys.platform != "win32":
        return sys.__stdout__ is not None
    try:
        import ctypes
        hwnd = _k32().GetConsoleWindow()
        return bool(hwnd) and bool(ctypes.windll.user32.IsWindowVisible(hwnd))
    except Exception:
        return False


def set_console(on: bool) -> bool:
    """Show / hide the console window.  Without one (a build without console), one is made and the messages go to it.
    Its X button is taken away: closing a console closes the program with it."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        k32, user32 = _k32(), ctypes.windll.user32
        hwnd = k32.GetConsoleWindow()
        if on and not hwnd:
            if not k32.AllocConsole():
                return False
            hwnd = k32.GetConsoleWindow()
            try:
                _state["con"] = open("CONOUT$", "w", encoding="utf-8", errors="replace", buffering=1)
            except OSError:
                _state["con"] = None
            try:
                k32.SetConsoleTitleW("VToyEditor Plus+ - console")
            except Exception:
                pass
        if not hwnd:
            return False
        if on:
            try:
                menu = user32.GetSystemMenu(hwnd, False)
                if menu:
                    user32.DeleteMenu(menu, 0xF060, 0x0)     # SC_CLOSE, MF_BYCOMMAND
            except Exception:
                pass
        user32.ShowWindow(hwnd, 5 if on else 0)             # SW_SHOW / SW_HIDE
        return True
    except Exception:
        return False
