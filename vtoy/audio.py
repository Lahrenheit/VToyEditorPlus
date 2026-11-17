"""Plays the map music (.ogg / .wav) inside the editor.  No audio library is required: the first backend that works is used.

    1. pygame.mixer   (pip install pygame - plays .ogg and .wav)
    2. miniaudio      (pip install miniaudio - plays .ogg and .wav)
    3. Windows MCI    (built in; .wav and .mp3 always, .ogg only when Windows has an Ogg Vorbis codec)
    4. winsound       (built in; .wav only)
``Player.play(path)`` returns ``''`` when it started or a short explanation of what is missing."""
from __future__ import annotations

import os
import sys


class Player:
    def __init__(self):
        self.backend = ""
        self.playing = ""
        self._mini = None
        self._mini_dev = None
        self._mci = False

    # ------------------------------------------------------------------ backends
    def _pygame(self, path: str) -> str:
        import pygame
        if not pygame.mixer.get_init():
            pygame.mixer.init()
        pygame.mixer.music.load(path)
        pygame.mixer.music.play(-1)
        self.backend = "pygame"
        return ""

    def _miniaudio(self, path: str) -> str:
        import miniaudio
        stream = miniaudio.stream_file(path, loop=True) if hasattr(miniaudio, "stream_file") else None
        if stream is None:
            raise RuntimeError("old miniaudio")
        self._mini_dev = miniaudio.PlaybackDevice()
        self._mini_dev.start(stream)
        self.backend = "miniaudio"
        return ""

    def _mci_cmd(self, cmd: str) -> int:
        import ctypes
        return ctypes.windll.winmm.mciSendStringW(cmd, None, 0, None)

    def _mci_play(self, path: str) -> str:
        self._mci_cmd("close vtoymusic")
        kind = " type mpegvideo" if path.lower().endswith((".mp3", ".ogg")) else ""
        if self._mci_cmd(f'open "{path}"{kind} alias vtoymusic') != 0:
            raise RuntimeError("Windows cannot open this file type (install pygame for .ogg: pip install pygame)")
        if self._mci_cmd("play vtoymusic repeat") != 0 and self._mci_cmd("play vtoymusic") != 0:
            raise RuntimeError("Windows could not play it")
        self._mci = True
        self.backend = "Windows MCI"
        return ""

    def _winsound(self, path: str) -> str:
        import winsound
        if not path.lower().endswith(".wav"):
            raise RuntimeError(".ogg needs pygame: pip install pygame")
        winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_LOOP)
        self.backend = "winsound"
        return ""

    # ------------------------------------------------------------------ api
    def play(self, path: str) -> str:
        self.stop()
        if not path or not os.path.isfile(path):
            return "file not found: " + (path or "(no music file)")
        errs = []
        order = [self._pygame, self._miniaudio]
        if sys.platform.startswith("win"):
            order += [self._mci_play, self._winsound]
        for fn in order:
            try:
                fn(path)
                self.playing = path
                return ""
            except Exception as e:                   # ImportError, codec missing, no device ...
                errs.append(str(e))
        return "cannot play: install pygame (pip install pygame). " + (errs[-1] if errs else "")

    def stop(self) -> None:
        self.playing = ""
        try:
            import pygame
            if pygame.mixer.get_init():
                pygame.mixer.music.stop()
        except Exception:
            pass
        try:
            if self._mini_dev is not None:
                self._mini_dev.close()
        except Exception:
            pass
        self._mini_dev = None
        if sys.platform.startswith("win"):
            try:
                if self._mci:
                    self._mci_cmd("close vtoymusic")
                    self._mci = False
                import winsound
                winsound.PlaySound(None, winsound.SND_PURGE)
            except Exception:
                pass
