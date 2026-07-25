"""Kokoro offline neural TTS engine.

Kokoro is an 82M-parameter model that runs comfortably on CPU and very fast
on the RTX 50-series GPUs. Model weights + voices are downloaded from Hugging
Face on first use into the HF cache (set HF_HOME to control the location, or
pre-download for fully offline operation — see README).
"""
from __future__ import annotations

import numpy as np
import soundfile as sf

from .base import TTSEngine


class KokoroEngine(TTSEngine):
    name = "kokoro"
    sample_rate = 24000  # Kokoro always outputs 24 kHz.

    def __init__(self, voice: str = "af_heart", speed: float = 1.0, device: str = "auto"):
        self.voice = voice
        self.speed = speed
        self.device = device
        self._model = None
        self._pipelines: dict[str, object] = {}
        self._resolved_device: str | None = None

    def _resolve_device(self) -> str:
        import torch

        if self.device and self.device != "auto":
            return self.device
        return "cuda" if torch.cuda.is_available() else "cpu"

    def load(self) -> None:
        if self._model is not None:
            return
        from kokoro import KModel

        self._resolved_device = self._resolve_device()
        self._model = KModel().to(self._resolved_device).eval()

    def _pipeline_for(self, voice: str):
        # Voice prefix selects the language / G2P: 'b' = British, else American.
        lang = "b" if voice.startswith("b") else "a"
        if lang not in self._pipelines:
            from kokoro import KPipeline

            self._pipelines[lang] = KPipeline(lang_code=lang, model=self._model)
        return self._pipelines[lang]

    def synthesize_to_file(self, text, out_path, *, voice=None, speed=None) -> str:
        self.load()
        voice = voice or self.voice
        speed = speed if speed is not None else self.speed

        pipeline = self._pipeline_for(voice)
        parts: list[np.ndarray] = []
        for _, _, audio in pipeline(text, voice=voice, speed=speed):
            if hasattr(audio, "detach"):  # torch tensor
                audio = audio.detach().cpu().numpy()
            parts.append(np.asarray(audio, dtype=np.float32).reshape(-1))

        audio = np.concatenate(parts) if parts else np.zeros(1, dtype=np.float32)
        sf.write(out_path, audio, self.sample_rate)
        return out_path
