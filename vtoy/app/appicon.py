"""The editor's own icon, drawn here (no file needed): a blue rounded square with a white "V" and an orange "+".
Used when the ``icon`` folder has no .ico / .png of yours, so the window and the taskbar never show a blank icon."""
from __future__ import annotations

import os
import tempfile

SIZES = (256, 128, 64, 48, 32, 24, 16)


def draw(size: int = 256):
    """The icon as a PIL RGBA image of ``size`` x ``size`` (drawn big and scaled down: smooth edges)."""
    from PIL import Image, ImageDraw
    S = 1024
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((24, 24, S - 24, S - 24), radius=200, fill=(32, 78, 150, 255), outline=(14, 36, 72, 255), width=28)
    d.rounded_rectangle((70, 70, S - 70, S / 2), radius=160, fill=(52, 104, 182, 255))          # a soft light on top
    d.rounded_rectangle((70, 300, S - 70, S - 70), radius=160, fill=(32, 78, 150, 255))
    # the V
    d.polygon([(170, 190), (365, 190), (512, 640), (659, 190), (854, 190), (600, 860), (424, 860)], fill=(255, 255, 255, 255))
    # the + (bottom right)
    cx, cy, a, b = 800, 790, 150, 52
    d.ellipse((cx - a - 40, cy - a - 40, cx + a + 40, cy + a + 40), fill=(14, 36, 72, 255))
    d.rectangle((cx - a, cy - b, cx + a, cy + b), fill=(255, 150, 30, 255))
    d.rectangle((cx - b, cy - a, cx + b, cy + a), fill=(255, 150, 30, 255))
    return im.resize((size, size), Image.LANCZOS)


def images():
    """The icon in the usual sizes (biggest first)."""
    big = draw(256)
    from PIL import Image
    return [big] + [big.resize((s, s), Image.LANCZOS) for s in SIZES[1:]]


def write_ico(path: str) -> str:
    """Save the icon as a .ico with every size in it."""
    draw(256).save(path, format="ICO", sizes=[(s, s) for s in SIZES])
    return path


def temp_ico() -> str:
    """A .ico of the drawn icon in the temp folder (made once), for the Windows API that wants a file."""
    p = os.path.join(tempfile.gettempdir(), "vtoy_editor_icon.ico")
    if not os.path.isfile(p):
        write_ico(p)
    return p


def icon_files():
    """(.ico, .png) of the ``icon`` folder: next to the exe first (so it can be changed without rebuilding), then the one
    bundled in the exe, then the source tree.  A .ico always wins over a .png."""
    import sys
    base = getattr(sys, "_MEIPASS", None)
    here = os.path.dirname(os.path.abspath(__file__))
    roots = [os.path.join(b, "icon") for b in (os.path.dirname(os.path.abspath(sys.argv[0])), base,
                                               os.path.dirname(os.path.dirname(here))) if b]
    ico = png = ""
    for r in roots:
        if os.path.isdir(r):
            fs = sorted(os.listdir(r))
            ico = ico or next((os.path.join(r, f) for f in fs if f.lower().endswith(".ico")), "")
            png = png or next((os.path.join(r, f) for f in fs if f.lower().endswith(".png")), "")
    return ico, png


def ico_path() -> str:
    """A .ico to show: yours from the icon folder, else the drawn one (saved in the temp folder)."""
    ico, _png = icon_files()
    if ico:
        return ico
    try:
        return temp_ico()
    except Exception:
        return ""


def tk_root():
    """A hidden Tk root for the file dialogs, with the editor's icon (not Python's feather) on it and on every dialog."""
    import tkinter as tk
    r = tk.Tk()
    r.withdraw()
    try:
        r.attributes("-topmost", True)
    except Exception:
        pass
    try:
        p = ico_path()
        if p:
            r.iconbitmap(default=p)                 # 'default': the dialogs opened from it get it too
    except Exception:
        try:
            from PIL import ImageTk
            ph = ImageTk.PhotoImage(draw(64))
            r.iconphoto(True, ph)
            r._vtoy_icon = ph                       # keep it alive
        except Exception:
            pass
    return r
