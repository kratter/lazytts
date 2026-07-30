"""Kokoro offline neural TTS engine.

Kokoro is an 82M-parameter model that runs comfortably on CPU and very fast
on the RTX 50-series GPUs. Model weights + voices are downloaded from Hugging
Face on first use into the HF cache (set HF_HOME to control the location, or
pre-download for fully offline operation — see README).
"""
from __future__ import annotations

import numpy as np
import soundfile as sf

from .base import TTSEngine, WordSpan


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
        path, _ = self.synthesize_with_words(
            text, out_path, voice=voice, speed=speed
        )
        return path

    def synthesize_with_words(self, text, out_path, *, voice=None, speed=None):
        """Synthesize *text*, keeping Kokoro's per-word timings.

        Kokoro already computes these: KPipeline calls join_timestamps() with the
        model's predicted durations, filling MToken.start_ts/end_ts. They were
        previously discarded by unpacking the Result as a 3-tuple, which only
        exposes (graphemes, phonemes, audio).

        Each Result's timestamps are relative to its own audio segment, so they
        are shifted by the audio already emitted for this file.
        """
        self.load()
        voice = voice or self.voice
        speed = speed if speed is not None else self.speed

        pipeline = self._pipeline_for(voice)
        parts: list[np.ndarray] = []
        spans: list[WordSpan] = []
        offset = 0.0

        for result in pipeline(text, voice=voice, speed=speed):
            audio = result.audio
            if audio is None:
                continue
            if hasattr(audio, "detach"):  # torch tensor
                audio = audio.detach().cpu().numpy()
            chunk = np.asarray(audio, dtype=np.float32).reshape(-1)
            parts.append(chunk)

            for token in result.tokens or ():
                word = (token.text or "").strip()
                if not word or token.start_ts is None or token.end_ts is None:
                    continue
                spans.append(WordSpan(
                    word,
                    offset + float(token.start_ts),
                    offset + float(token.end_ts),
                ))

            offset += len(chunk) / self.sample_rate

        audio = np.concatenate(parts) if parts else np.zeros(1, dtype=np.float32)
        sf.write(out_path, audio, self.sample_rate)
        return out_path, (spans or None)
