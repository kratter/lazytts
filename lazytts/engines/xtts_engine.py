"""Coqui XTTS-v2 engine — multilingual neural TTS with built-in studio speakers.

Covers English, German, Hungarian (and many more). Requires the `coqui-tts`
package (import name `TTS`); if it isn't installed the engine simply won't be
offered (see app._engine_available). The ~1.8 GB model caches under TTS_HOME
(set to a local folder in config, so it ships next to lazyTTS.exe for offline use).

LICENSE: Coqui Public Model License — non-commercial use. XTTS is autoregressive
(GPT-style) and therefore much slower than Piper/Kokoro; best for short or
highest-quality output rather than very long books.
"""
from __future__ import annotations

import config
from .base import TTSEngine


class XttsEngine(TTSEngine):
    name = "xtts"
    sample_rate = 24000  # XTTS-v2 outputs 24 kHz.

    def __init__(self, voice: str = config.DEFAULT_XTTS_VOICE, speed: float = 1.0,
                 device: str = "auto"):
        self.voice = voice
        self.speed = speed
        self.device = device
        self._tts = None
        self._speakers: list[str] | None = None

    def _resolve_device(self) -> str:
        try:
            import torch
            if self.device and self.device != "auto":
                return self.device
            return "cuda" if torch.cuda.is_available() else "cpu"
        except Exception:
            return "cpu"

    def load(self) -> None:
        if self._tts is not None:
            return
        from TTS.api import TTS

        tts = TTS(config.XTTS_MODEL)
        dev = self._resolve_device()
        try:
            tts.to(dev)
        except Exception:
            tts.to("cpu")
        self._tts = tts
        # Cache valid built-in speaker names to validate/fall back gracefully.
        try:
            mgr = tts.synthesizer.tts_model.speaker_manager
            self._speakers = list(mgr.name_to_id.keys())
        except Exception:
            self._speakers = None

    def _resolve_voice(self, voice_id: str) -> tuple[str, str | None]:
        lang, speaker = config.XTTS_VOICES.get(voice_id, ("en", None))
        if speaker and self._speakers and speaker not in self._speakers:
            speaker = self._speakers[0]  # requested speaker missing → first valid
        return lang, speaker

    def synthesize_to_file(self, text, out_path, *, voice=None, speed=None) -> str:
        self.load()
        lang, speaker = self._resolve_voice(voice or self.voice)
        spd = float(speed if speed is not None else self.speed) or 1.0

        kwargs = dict(text=text, file_path=out_path, language=lang, speed=spd)
        if speaker:
            kwargs["speaker"] = speaker
        self._tts.tts_to_file(**kwargs)
        return out_path
