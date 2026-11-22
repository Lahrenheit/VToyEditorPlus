"""Plays the map music (.ogg / .wav) and the sounds of the map's modules (.wav) inside the editor.  No audio library is required: the first backend that works is used.

    1. pygame.mixer   (pip install pygame - plays .ogg and .wav)
    2. miniaudio      (pip install miniaudio - plays .ogg and .wav)
    3. Windows MCI    (built in; .wav and .mp3 always, .ogg only when Windows has an Ogg Vorbis codec)
    4. winsound       (built in; .wav only)
``Player.play(path)`` returns ``''`` when it started or a short explanation of what is missing."""
from __future__ import annotations

import os
import sys


def wav_seconds(path: str, default: float = 5.0) -> float:
    """Length of a .wav from its header (data bytes / bytes per second); ``default`` when it cannot be read."""
    import struct
    try:
        with open(path, "rb") as f:
            head = f.read(12)
            if head[:4] != b"RIFF" or head[8:12] != b"WAVE":
                return default
            rate = 0
            while True:
                ck = f.read(8)
                if len(ck) < 8:
                    return default
                tag, size = ck[:4], struct.unpack("<I", ck[4:])[0]
                if tag == b"fmt ":
                    fmt = f.read(size + (size & 1))
                    rate = struct.unpack_from("<I", fmt, 8)[0]
                elif tag == b"data":
                    return size / rate if rate else default
                else:
                    f.seek(size + (size & 1), 1)
    except (OSError, struct.error):
        return default


class Player:
    def __init__(self):
        self.backend = ""
        self.playing = ""
        self.loop = True
        self._mini = None
        self._mini_dev = None
        self._mci = False

    # ------------------------------------------------------------------ backends
    def _pygame(self, path: str) -> str:
        import pygame
        if not pygame.mixer.get_init():
            pygame.mixer.init()
        pygame.mixer.music.load(path)
        pygame.mixer.music.play(-1 if self.loop else 0)
        self.backend = "pygame"
        return ""

    def _miniaudio(self, path: str) -> str:
        import miniaudio
        stream = miniaudio.stream_file(path, loop=self.loop) if hasattr(miniaudio, "stream_file") else None
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
        if self.loop and self._mci_cmd("play vtoymusic repeat") != 0:
            if not kind:                                   # a wave device cannot repeat: let the next backend loop it
                self._mci_cmd("close vtoymusic")
                raise RuntimeError("Windows MCI cannot repeat this file type")
            if self._mci_cmd("play vtoymusic") != 0:
                raise RuntimeError("Windows could not play it")
        elif not self.loop and self._mci_cmd("play vtoymusic") != 0:
            raise RuntimeError("Windows could not play it")
        self._mci = True
        self.backend = "Windows MCI"
        return ""

    def _winsound(self, path: str) -> str:
        import winsound
        if not path.lower().endswith(".wav"):
            raise RuntimeError(".ogg needs pygame: pip install pygame")
        winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC | (winsound.SND_LOOP if self.loop else 0))
        self.backend = "winsound"
        return ""

    # ------------------------------------------------------------------ api
    def play(self, path: str, loop: bool = True) -> str:
        """Start ``path`` (stopping what was playing). ``loop`` False = once (the sounds of a map); True = music."""
        self.stop()
        self.loop = bool(loop)
        if not path or not os.path.isfile(path):
            return "file not found: " + (path or "(no music file)")
        errs = []
        order = [self._pygame, self._miniaudio]
        if sys.platform.startswith("win"):
            # the game's sounds are plain or ADPCM .wav: Windows plays every kind of them, so it goes first for .wav
            # (looping: winsound first - Windows MCI cannot repeat a wave file)
            win = [self._winsound, self._mci_play] if self.loop else [self._mci_play, self._winsound]
            order = (win + order) if path.lower().endswith(".wav") else order + [self._mci_play, self._winsound]
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


def scale_wav(src: str, dst: str, factor: float) -> None:
    """A copy of the .wav ``src`` at ``factor`` of its loudness (0..1): the samples scaled, everything else as it was.
    PCM (8 / 16 / 24 / 32 bit) and float; a compressed .wav (ADPCM...) raises ValueError."""
    import struct
    import numpy as np
    data = bytearray(open(src, "rb").read())
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise ValueError(f"{os.path.basename(src)} is not a .wav")
    fmt = bits = None
    o = 12
    found = False
    while o + 8 <= len(data):
        tag, size = bytes(data[o:o + 4]), struct.unpack_from("<I", data, o + 4)[0]
        body = o + 8
        if tag == b"fmt ":
            fmt, = struct.unpack_from("<H", data, body)
            bits, = struct.unpack_from("<H", data, body + 14)
            if fmt == 0xFFFE and size >= 26:                  # WAVE_FORMAT_EXTENSIBLE: the real format
                fmt, = struct.unpack_from("<H", data, body + 24)
        elif tag == b"data":
            if fmt is None:
                raise ValueError("no format before the sound data")
            end = min(body + size, len(data))
            raw = bytes(data[body:end])
            f = max(0.0, min(1.0, float(factor)))
            if fmt == 1 and bits == 8:
                a = np.frombuffer(raw, np.uint8).astype(np.float64) - 128.0
                out = (np.clip(np.round(a * f), -128, 127) + 128).astype(np.uint8).tobytes()
            elif fmt == 1 and bits == 16:
                a = np.frombuffer(raw[: len(raw) // 2 * 2], "<i2").astype(np.float64)
                out = np.clip(np.round(a * f), -32768, 32767).astype("<i2").tobytes() + raw[len(raw) // 2 * 2:]
            elif fmt == 1 and bits == 24:
                n = len(raw) // 3
                b = np.frombuffer(raw[: n * 3], np.uint8).reshape(-1, 3).astype(np.int32)
                v = b[:, 0] | (b[:, 1] << 8) | (b[:, 2] << 16)
                v = np.where(v & 0x800000, v - 0x1000000, v)
                v = np.clip(np.round(v * f), -0x800000, 0x7FFFFF).astype(np.int32) & 0xFFFFFF
                out = np.stack([v & 0xFF, (v >> 8) & 0xFF, (v >> 16) & 0xFF], 1).astype(np.uint8).tobytes() + raw[n * 3:]
            elif fmt == 1 and bits == 32:
                a = np.frombuffer(raw[: len(raw) // 4 * 4], "<i4").astype(np.float64)
                out = np.clip(np.round(a * f), -2 ** 31, 2 ** 31 - 1).astype("<i4").tobytes() + raw[len(raw) // 4 * 4:]
            elif fmt == 3 and bits in (32, 64):
                dt = "<f4" if bits == 32 else "<f8"
                k = bits // 8
                a = np.frombuffer(raw[: len(raw) // k * k], dt)
                out = (a * f).astype(dt).tobytes() + raw[len(raw) // k * k:]
            else:
                raise ValueError(f"{os.path.basename(src)}: compressed sound (format {fmt}, {bits} bit) - "
                                 f"its volume cannot be changed here")
            data[body:end] = out
            found = True
            break
        o = body + size + (size & 1)
    if not found:
        raise ValueError(f"{os.path.basename(src)}: no sound data")
    open(dst, "wb").write(bytes(data))
