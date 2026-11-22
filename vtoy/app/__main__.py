import argparse
import json
import os
import sys

from .. import vpk

def setup_logging(log: bool = True) -> str:
    """print() and crash reports go to vtoy_editor.log next to the .exe / project (and to the console, when there is one).
    Both can be turned on / off in the Settings menu (see outputs.py). --no-log starts without the log."""
    from . import outputs
    return outputs.setup(log)


from .. import settings
from ..language import tr


def _load_cfg() -> dict:
    return settings.load()


def _save_cfg(d: dict) -> None:
    cur = settings.load()
    cur.update(d)
    settings.save(cur)


def ask_path(initial: str = "") -> str:
    """Dialog: pick demo.vpk (or Cancel -> pick an already unpacked folder)."""
    try:
        from tkinter import filedialog, messagebox
        from .appicon import tk_root
        r = tk_root()
        start = os.path.dirname(initial) if initial else ""
        p = filedialog.askopenfilename(title=tr("Choose demo.vpk (Cancel = choose an already unpacked folder)"),
                                       initialdir=start or None, filetypes=[("Virtual Toys pack", "*.vpk"), ("All files", "*.*")])
        if not p:
            p = filedialog.askdirectory(title=tr("Unpacked folder (with scns/ nfos/ texs/ keys/)"), initialdir=start or None)
        r.destroy()
        return p
    except Exception:
        return input(tr("Path to demo.vpk or to the unpacked folder: ")).strip().strip('"')


def resolve(path: str):
    """Returns (game_root_folder, vpk_path_or_None). A .vpk is unpacked next to itself the first time."""
    path = os.path.abspath(path)
    if os.path.isdir(path):
        return path, None
    if not os.path.isfile(path):
        raise SystemExit(tr(f"Not found: {path}"))
    out = os.path.join(os.path.dirname(path), os.path.splitext(os.path.basename(path))[0] + "_unpacked")
    if not os.path.isdir(out) or not os.listdir(out):
        print(tr(f"Unpacking {path} -> {out} ..."))
        print(vpk.unpack(path, out), "archivos")
    return out, path


def main() -> None:
    ap = argparse.ArgumentParser(prog="python -m vtoy.app", description="Virtual Toys scene viewer / editor")
    ap.add_argument("source", nargs="?", help="demo.vpk or an unpacked folder (a file dialog opens when omitted)")
    ap.add_argument("scene", nargs="?", help="scene to open (e.g. mp_dm_plaza.scn)")
    ap.add_argument("--library", help="unpacked folder of 'Torrente, el juego' (nfos/ texs/ keys/ scns/)")
    ap.add_argument("--no-log", action="store_true", help="do not write vtoy_editor.log")
    ap.add_argument("--vpk-out", help="where File > Pack writes (default: the demo.vpk that was chosen)")
    a = ap.parse_args()
    # the taskbar identity must be set before ANY window (even the file dialog), or Windows keeps Python's for the process
    try:
        from .winicon import set_app_id
        set_app_id()
    except Exception:
        pass
    cfg = _load_cfg()
    want_log = (not a.no_log) and bool(cfg.get("log", True))
    p = setup_logging(want_log)
    if p:
        print("log:", p)
    if cfg.get("console") is not None:                  # the console as you left it (Settings > Show the console window)
        from . import outputs
        outputs.set_console(bool(cfg.get("console")))
    from .. import language
    language.set_language(cfg.get("language", "en"))
    src = a.source or ask_path(cfg.get("last", ""))
    if not src:
        sys.exit("Nothing chosen.")
    root, vpk_path = resolve(src)
    lib = a.library or cfg.get("library", "")
    _save_cfg({"last": src, "library": lib})
    from .editor import Editor          # imported late so the dialog appears before heavy GL imports
    Editor(root, a.scene, a.vpk_out or vpk_path, lib).run()


if __name__ == "__main__":
    main()
