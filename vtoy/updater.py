"""Newer versions of the editor: the releases of its GitHub repository (APP_URL), compared with APP_REV.

* ``Checker`` asks GitHub in the background (the editor never waits for the network) and says whether a release
  newer than this one exists, which one, its page and its files.
* ``Downloader`` gets a release's .zip or .7z and unpacks it next to the program, into a folder of its own
  (``_vtoy_update``); nothing of the running program is touched.
* ``launch_replace`` - once the editor has closed (a running .exe cannot be overwritten): a small script waits for it
  to end, copies the new files over the program's (vtoy_editor.json, imgui.ini and the log are kept), deletes the
  unpacked folder and starts the editor again.  The files of a release that does not look like this program (no
  VToyEditor.exe / run_editor.py at its top) are never copied over it: they stay in their folder.

A .7z is unpacked with py7zr (in requirements.txt, so the .exe has it), else 7-Zip's 7z.exe, else Windows' tar.exe.

The check is on by default; Settings > "Check for newer versions on start" turns it off (``check_updates`` in
vtoy_editor.json).  Help > "Check for newer versions now" checks at any time.
"""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import threading
import urllib.request
import zipfile
from typing import Callable, List, Optional

TIMEOUT = 10.0
ARCHIVES = (".zip", ".7z")
STAGING = "_vtoy_update"                                       # next to the program: the release unpacked
KEEP = ("vtoy_editor.json", "imgui.ini", "vtoy_editor.log")    # never replaced by an update


def repo_of(url: str):
    """(owner, repo) of a GitHub URL, or None."""
    m = re.match(r"https?://github\.com/([^/\s]+)/([^/\s#?]+)", str(url or "").strip())
    if not m:
        return None
    return m.group(1), m.group(2).removesuffix(".git")


def version_tuple(s: str):
    """The numbers of a version ("v1.0.15", "VToyEditor 1.0.16", "1.1") as a tuple, or None."""
    nums = re.findall(r"\d+", str(s or ""))
    if not nums:
        return None
    t = [int(n) for n in nums[:4]]
    while len(t) > 1 and t[-1] == 0:                          # 1.0 == 1.0.0
        t.pop()
    return tuple(t)


def is_newer(tag: str, current: str) -> bool:
    a, b = version_tuple(tag), version_tuple(current)
    return a is not None and b is not None and a > b


def _get(url: str, timeout: float = TIMEOUT) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "VToyEditorPlus-update-check",
                                               "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def releases(url: str, fetch: Optional[Callable[[str], bytes]] = None) -> List[dict]:
    """The published releases of the repository of ``url``: [{'tag', 'name', 'page', 'date', 'notes', 'prerelease',
    'assets': [{'name', 'url', 'size'}], 'zipball'}], newest first as GitHub lists them."""
    ro = repo_of(url)
    if ro is None:
        raise ValueError(f"not a GitHub repository: {url}")
    data = json.loads((fetch or _get)(f"https://api.github.com/repos/{ro[0]}/{ro[1]}/releases?per_page=20"))
    if isinstance(data, dict):
        raise ValueError(str(data.get("message", "unexpected answer from GitHub")))
    out = []
    for r in data:
        if r.get("draft"):
            continue
        out.append({"tag": str(r.get("tag_name", "")), "name": str(r.get("name") or r.get("tag_name", "")),
                    "page": str(r.get("html_url", "")), "date": str(r.get("published_at") or "")[:10],
                    "notes": str(r.get("body") or ""), "prerelease": bool(r.get("prerelease")),
                    "zipball": str(r.get("zipball_url") or ""),
                    "assets": [{"name": str(a.get("name", "")), "url": str(a.get("browser_download_url", "")),
                                "size": int(a.get("size") or 0)} for a in r.get("assets") or []]})
    return out


def newest(url: str, current: str, fetch=None, prerelease: bool = False) -> Optional[dict]:
    """The highest release newer than ``current`` (pre-releases only if ``prerelease``), or None."""
    best = None
    for r in releases(url, fetch):
        if r["prerelease"] and not prerelease:
            continue
        v = version_tuple(r["tag"]) or version_tuple(r["name"])
        if v is None or not is_newer(".".join(map(str, v)), current):
            continue
        if best is None or v > best[0]:
            best = (v, r)
    return best[1] if best else None


def pick_asset(rel: dict) -> Optional[dict]:
    """The file of a release to download: its .zip or .7z (one with 'win' / 'exe' / 'editor' in the name first),
    else the source zip."""
    zips = [a for a in rel.get("assets", []) if a["name"].lower().endswith(ARCHIVES) and a["url"]]
    if zips:
        zips.sort(key=lambda a: (not any(k in a["name"].lower() for k in ("win", "exe", "editor")), a["name"]))
        return zips[0]
    if rel.get("zipball"):
        return {"name": f"source-{rel['tag']}.zip", "url": rel["zipball"], "size": 0}
    return None


def program_dir() -> str:
    """The folder of the program: the .exe's when frozen, else the one with run_editor.py."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def target_dir(base: str, rel: dict, url: str) -> str:
    """A new folder in ``base`` for the release (``VToyEditorPlus-v1.0.16``, ``-2`` ... if that one exists)."""
    ro = repo_of(url)
    stem = re.sub(r'[<>:"/\\|?*\s]+', "_", f"{ro[1] if ro else 'VToyEditorPlus'}-{rel.get('tag') or 'new'}")
    d, k = os.path.join(base, stem), 2
    while os.path.exists(d):
        d, k = os.path.join(base, f"{stem}-{k}"), k + 1
    return d


def staging_dir(base: str) -> str:
    """The folder next to the program a release is unpacked into (emptied first)."""
    import shutil
    d = os.path.join(base, STAGING)
    if os.path.isdir(d):
        shutil.rmtree(d, ignore_errors=True)
    return d


def program_files(folder: str) -> bool:
    """True if ``folder`` holds this program at its top: VToyEditor.exe (the .exe) or run_editor.py + vtoy (source)."""
    return os.path.isfile(os.path.join(folder, "VToyEditor.exe")) or (
        os.path.isfile(os.path.join(folder, "run_editor.py")) and os.path.isdir(os.path.join(folder, "vtoy")))


def _flatten(dest: str) -> None:
    """One top folder that holds everything (GitHub's source zips, "VToyEditor/..." archives): its files moved up."""
    import shutil
    items = os.listdir(dest)
    if len(items) != 1 or not os.path.isdir(os.path.join(dest, items[0])):
        return
    top = os.path.join(dest, items[0])
    tmp = top + "__up"
    os.rename(top, tmp)
    for n in os.listdir(tmp):
        shutil.move(os.path.join(tmp, n), os.path.join(dest, n))
    os.rmdir(tmp)


def _files_in(dest: str) -> List[str]:
    root = os.path.realpath(dest)
    out = []
    for r, _d, fs in os.walk(dest):
        for f in fs:
            p = os.path.realpath(os.path.join(r, f))
            if not p.startswith(root + os.sep):                 # (a link out of the folder: not ours)
                raise ValueError(f"the archive writes outside its folder: {f}")
            out.append(p)
    return sorted(out)


def _extract_zip(path: str, dest: str) -> None:
    root = os.path.realpath(dest)
    with zipfile.ZipFile(path) as z:
        for info in z.infolist():
            n = info.filename.replace("\\", "/")
            if n.endswith("/") or ".." in n.split("/"):
                continue
            p = os.path.realpath(os.path.join(root, *[s for s in n.split("/") if s not in ("", ".")]))
            if not p.startswith(root + os.sep):
                continue
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with z.open(info) as src, open(p, "wb") as dst:
                while True:
                    b = src.read(1 << 16)
                    if not b:
                        break
                    dst.write(b)


def seven_zip_tools() -> List[List[str]]:
    """Commands that unpack a .7z here (``{a}`` the archive, ``{d}`` the folder): 7-Zip's 7z.exe, Windows' tar.exe."""
    import shutil
    out = []
    cands = [shutil.which("7z"), shutil.which("7za")]
    for env in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"):
        if os.environ.get(env):
            cands.append(os.path.join(os.environ[env], "7-Zip", "7z.exe"))
    for c in cands:
        if c and os.path.isfile(c) and [c, "x", "-y", "-o{d}", "{a}"] not in out:
            out.append([c, "x", "-y", "-o{d}", "{a}"])
    if sys.platform == "win32":
        t = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "tar.exe")
        if os.path.isfile(t):
            out.append([t, "-xf", "{a}", "-C", "{d}"])
    return out


def _extract_7z(path: str, dest: str, tools=None) -> None:
    errs = []
    try:
        import py7zr                                          # (requirements.txt)
        with py7zr.SevenZipFile(path, "r") as z:
            z.extractall(dest)
        return
    except ImportError:
        errs.append("py7zr is not installed")
    except Exception as e:
        errs.append(f"py7zr: {e}")
    import shutil
    import subprocess
    for cmd in (seven_zip_tools() if tools is None else tools):
        for n in os.listdir(dest):                            # (what a failed try left)
            q = os.path.join(dest, n)
            shutil.rmtree(q, ignore_errors=True) if os.path.isdir(q) else os.remove(q)
        try:
            r = subprocess.run([c.replace("{a}", path).replace("{d}", dest) for c in cmd], capture_output=True,
                               timeout=600, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if r.returncode == 0 and os.listdir(dest):
                return
            errs.append(f"{os.path.basename(cmd[0])}: exit {r.returncode}")
        except Exception as e:
            errs.append(f"{os.path.basename(cmd[0])}: {e}")
    raise ValueError("could not unpack the .7z (" + "; ".join(errs) + ") - install 7-Zip or publish a .zip")


def extract(path: str, dest: str, kind: str = "", tools=None) -> List[str]:
    """Unpack the archive ``path`` (.zip or .7z, by ``kind`` or its name) into the new folder ``dest`` (made here;
    nothing outside it is written).  One top folder that holds everything is left out.  The files written."""
    os.makedirs(dest, exist_ok=False)
    kind = (kind or os.path.splitext(path)[1]).lower()
    if kind == ".7z":
        _extract_7z(path, dest, tools)
    elif zipfile.is_zipfile(path):
        _extract_zip(path, dest)
    else:
        raise ValueError("the downloaded file is not a .zip or a .7z")
    _flatten(dest)
    return _files_in(dest)


class Checker:
    """Asks GitHub in a thread.  ``state``: 'idle', 'checking', 'newer' (``release``), 'latest', 'error' (``error``)."""

    def __init__(self, url: str, current: str, fetch=None):
        self.url, self.current, self.fetch = url, current, fetch
        self.state, self.release, self.error = "idle", None, ""
        self._t = None

    def start(self) -> "Checker":
        if self.state == "checking":
            return self
        self.state, self.release, self.error = "checking", None, ""

        def work():
            try:
                r = newest(self.url, self.current, self.fetch)
                self.release = r
                self.state = "newer" if r else "latest"
            except Exception as e:                            # (offline, GitHub's rate limit ...)
                self.error = str(e) or e.__class__.__name__
                self.state = "error"
        self._t = threading.Thread(target=work, name="vtoy-update-check", daemon=True)
        self._t.start()
        return self

    def wait(self, timeout: Optional[float] = None) -> str:
        if self._t is not None:
            self._t.join(timeout)
        return self.state


class Downloader:
    """Downloads a release's .zip / .7z and unpacks it into ``_vtoy_update`` next to the program, in a thread.
    ``state``: 'working' (``done`` / ``total`` bytes), 'unpacking', 'done' (``folder``, ``files``, ``replaceable``: it
    is this program - launch_replace can put it in place), 'error' (``error``)."""

    def __init__(self, rel: dict, url: str, base: Optional[str] = None, opener=None, tools=None):
        self.rel, self.url, self.base = rel, url, base or program_dir()
        self.opener = opener or (lambda u: urllib.request.urlopen(
            urllib.request.Request(u, headers={"User-Agent": "VToyEditorPlus-update"}), timeout=60))
        self.state, self.done, self.total = "idle", 0, 0
        self.folder, self.files, self.error = "", [], ""
        self.replaceable, self.tools = False, tools
        self._t = None

    def start(self) -> "Downloader":
        if self.state in ("working", "unpacking"):
            return self
        self.state, self.done, self.error = "working", 0, ""

        def work():
            tmp = None
            try:
                a = pick_asset(self.rel)
                if a is None:
                    raise ValueError("the release has no .zip to download")
                self.total = int(a.get("size") or 0)
                kind = ".7z" if a["name"].lower().endswith(".7z") else ".zip"
                fd, tmp = tempfile.mkstemp(suffix=kind, prefix="vtoy-update-")
                with os.fdopen(fd, "wb") as f, self.opener(a["url"]) as r:
                    try:
                        self.total = self.total or int(r.headers.get("Content-Length") or 0)
                    except Exception:
                        pass
                    while True:
                        b = r.read(1 << 16)
                        if not b:
                            break
                        f.write(b)
                        self.done += len(b)
                self.state = "unpacking"
                dest = staging_dir(self.base)
                self.files = extract(tmp, dest, kind, self.tools)
                self.folder = dest
                self.replaceable = program_files(dest)
                self.state = "done"
            except Exception as e:
                self.error = str(e) or e.__class__.__name__
                self.state = "error"
            finally:
                if tmp and os.path.exists(tmp):
                    try:
                        os.remove(tmp)
                    except OSError:
                        pass
        self._t = threading.Thread(target=work, name="vtoy-update-download", daemon=True)
        self._t.start()
        return self

    def wait(self, timeout: Optional[float] = None) -> str:
        if self._t is not None:
            self._t.join(timeout)
        return self.state


def open_folder(path: str) -> None:
    """Show ``path`` in the file manager."""
    if sys.platform == "win32":
        os.startfile(path)                                     # noqa: (Windows only)
    else:
        import subprocess
        subprocess.Popen(["xdg-open" if sys.platform != "darwin" else "open", path])


def replace_script(staging: str, prog: str, pid: int, restart: List[str]) -> str:
    """The Windows batch file that puts an unpacked update in place once the editor (process ``pid``) has ended: waits
    for it, copies ``staging`` over ``prog`` (robocopy, retrying files still locked; the settings kept), deletes
    ``staging``, starts ``restart`` and deletes itself.  If the copy fails the window stays open and says where the
    new files are."""
    keep = " ".join(f'"{k}"' for k in KEEP)
    run = " ".join(f'"{a}"' for a in restart)
    return "\r\n".join([
        "@echo off",
        "chcp 65001 >nul",
        "title VToyEditor Plus+ update",
        "echo Updating VToyEditor Plus+ - waiting for the editor to close...",
        f'powershell -NoProfile -NonInteractive -Command "Wait-Process -Id {int(pid)} -ErrorAction SilentlyContinue"',
        "timeout /t 2 /nobreak >nul",
        f'robocopy "{staging}" "{prog}" /E /R:10 /W:1 /XF {keep} /NFL /NDL /NJH /NJS /NP >nul',
        "if %ERRORLEVEL% GEQ 8 goto fail",
        f'rmdir /S /Q "{staging}"',
        f'cd /d "{prog}"',
        f'start "" {run}',
        "goto end",
        ":fail",
        "echo.",
        "echo The new files could not be copied over the program (is it still open, or the folder read-only?).",
        f"echo They are in: {staging}",
        "echo Copy them over the program's folder by hand.",
        "pause",
        ":end",
        '(goto) 2>nul & del "%~f0"',
        ""])


def restart_command(prog: str) -> List[str]:
    """How to start the editor again from ``prog``: its .exe, or Python with run_editor.py."""
    if getattr(sys, "frozen", False):
        return [os.path.join(prog, os.path.basename(sys.executable))]
    exe = sys.executable
    if exe.lower().endswith("python.exe") and os.path.isfile(exe[:-10] + "pythonw.exe"):
        exe = exe[:-10] + "pythonw.exe"
    return [exe, os.path.join(prog, "run_editor.py")]


def launch_replace(staging: str, prog: Optional[str] = None, pid: Optional[int] = None) -> str:
    """Start (detached) the script that replaces the program with ``staging`` once this process has ended.  Windows
    only.  The script's path."""
    import subprocess
    prog = prog or program_dir()
    if sys.platform != "win32":
        raise OSError("the program can only replace itself on Windows")
    if not program_files(staging):
        raise ValueError("the release does not hold the program at its top - copy it by hand")
    fd, path = tempfile.mkstemp(suffix=".cmd", prefix="vtoy-update-")
    with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:          # (chcp 65001: paths with accents)
        f.write(replace_script(os.path.abspath(staging), os.path.abspath(prog), pid or os.getpid(), restart_command(prog)))
    subprocess.Popen(["cmd", "/c", path], cwd=os.path.dirname(path), close_fds=True,
                     creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    return path
