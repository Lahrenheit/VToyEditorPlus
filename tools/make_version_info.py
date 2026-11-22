"""Writes version_info.txt (the version shown in VToyEditor.exe > Properties > Details) from APP_REV in
vtoy/__init__.py, so the .exe always carries the editor's own version (v1.0.18 -> 1.0.18.0).  build_exe.bat runs it
before PyInstaller; it can also be run by hand:  python tools/make_version_info.py"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def app_info(root: str = ROOT) -> dict:
    src = open(os.path.join(root, "vtoy", "__init__.py"), encoding="utf-8").read()
    get = lambda k: re.search(rf'^{k}\s*=\s*"([^"]*)"', src, re.M).group(1)
    return {k: get(k) for k in ("APP_NAME", "APP_REV", "APP_AUTHOR", "APP_URL", "APP_BASED_ON")}


def numbers(rev: str):
    n = [int(x) for x in re.findall(r"\d+", rev)][:4]
    return tuple(n + [0] * (4 - len(n)))


def text(info: dict) -> str:
    v = numbers(info["APP_REV"])
    ver = ".".join(str(x) for x in v[:3])
    q = lambda s: repr(str(s))
    return f"""# UTF-8
# Version resource of VToyEditor.exe (Properties > Details). Written by tools/make_version_info.py from APP_REV in
# vtoy/__init__.py (build_exe.bat runs it) - do not edit by hand.
VSVersionInfo(
  ffi=FixedFileInfo(filevers={v}, prodvers={v}, mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([
      StringTable('040904B0', [
        StringStruct('CompanyName', {q(info["APP_AUTHOR"])}),
        StringStruct('FileDescription', {q(info["APP_NAME"] + " - editor for Virtual Toys / Torrente Online")}),
        StringStruct('FileVersion', {q(ver)}),
        StringStruct('InternalName', 'VToyEditor'),
        StringStruct('LegalCopyright', {q(info["APP_AUTHOR"] + " - " + info["APP_URL"])}),
        StringStruct('OriginalFilename', 'VToyEditor.exe'),
        StringStruct('ProductName', {q(info["APP_NAME"])}),
        StringStruct('ProductVersion', {q(ver)}),
        StringStruct('Comments', {q(info["APP_URL"] + " - " + info["APP_BASED_ON"])})])
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""


def write(root: str = ROOT) -> str:
    p = os.path.join(root, "version_info.txt")
    t = text(app_info(root))
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        f.write(t)
    return p


if __name__ == "__main__":
    print("version_info.txt ->", app_info()["APP_REV"], write(sys.argv[1] if len(sys.argv) > 1 else ROOT))
