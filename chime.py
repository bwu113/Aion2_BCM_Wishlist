"""The "item found" chime with an adjustable volume (Windows plays it from memory; no temporary files)."""
from __future__ import annotations

import array
import io
import sys
import threading
import wave

DEFAULT_VOLUME = 50                  # percent
LOUDEST_PEAK = 0.9                   # 100 % = the sound's loudest moment at 90 % of full scale


def clamp_volume(value) -> int:
    try:
        return max(0, min(100, int(round(float(value)))))
    except (TypeError, ValueError):
        return DEFAULT_VOLUME


def gain_for(volume: int) -> float:
    """Perceptual curve: the slider is closer to loudness than to raw amplitude (50 % is about -9 dB)."""
    v = clamp_volume(volume) / 100.0
    return v ** 1.5


def scaled_wav(path: str, volume: int) -> bytes | None:
    """The chime file at the given volume as WAV bytes, or None if it cannot be read (or volume is 0)."""
    gain = gain_for(volume)
    if gain <= 0:
        return None
    try:
        with wave.open(path, "rb") as src:
            channels, width, rate = src.getnchannels(), src.getsampwidth(), src.getframerate()
            frames = src.readframes(src.getnframes())
        if width != 2:
            return None
        samples = array.array("h")
        samples.frombytes(frames)
        if sys.byteorder == "big":
            samples.byteswap()
        peak = max((abs(s) for s in samples), default=0)
        if peak == 0:
            return None
        factor = gain * LOUDEST_PEAK * 32767.0 / peak
        out = array.array("h", (max(-32768, min(32767, int(s * factor))) for s in samples))
        if sys.byteorder == "big":
            out.byteswap()
        buf = io.BytesIO()
        with wave.open(buf, "wb") as dst:
            dst.setnchannels(channels)
            dst.setsampwidth(2)
            dst.setframerate(rate)
            dst.writeframes(out.tobytes())
        return buf.getvalue()
    except Exception:
        return None


class Chime:
    """Caches the scaled sound for the current volume and plays it on a background thread."""

    def __init__(self, path: str) -> None:
        self.path = path
        self._cache: tuple[int, bytes | None] | None = None

    def data(self, volume: int) -> bytes | None:
        volume = clamp_volume(volume)
        if self._cache is None or self._cache[0] != volume:
            self._cache = (volume, scaled_wav(self.path, volume))
        return self._cache[1]

    def play(self, volume: int) -> str:
        """Returns 'played', 'muted' (volume 0) or 'unavailable' (caller may fall back to the system beep)."""
        if clamp_volume(volume) == 0:
            return "muted"
        if not sys.platform.startswith("win"):
            return "unavailable"
        data = self.data(volume)
        if data is None:
            return "unavailable"
        try:
            import winsound
        except ImportError:
            return "unavailable"

        def run() -> None:
            try:
                winsound.PlaySound(data, winsound.SND_MEMORY | winsound.SND_NODEFAULT)
            except Exception:
                pass

        threading.Thread(target=run, daemon=True).start()
        return "played"
