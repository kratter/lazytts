"""Windows SAPI fallback engine via pyttsx3.

Requires no GPU, no downloads, no torch — so the app is usable (and the whole
pipeline is testable) before the neural stack is installed. Voice quality is
robotic; use Kokoro for real audiobooks.
"""
from __future__ import annotations

from .base import TTSEngine


class SapiEngine(TTSEngine):
    name = "sapi"
    sample_rate = 22050

    def __init__(self, speed: float = 1.0):
        self.speed = speed

    def synthesize_to_file(self, text, out_path, *, voice=None, speed=None) -> str:
        import pyttsx3

        # pyttsx3 is fussy about reuse across calls; init fresh each time.
        engine = pyttsx3.init()
        base_rate = engine.getProperty("rate")
        engine.setProperty("rate", int(base_rate * (speed if speed is not None else self.speed)))
        engine.save_to_file(text, out_path)
        engine.runAndWait()
        engine.stop()
        return out_path
