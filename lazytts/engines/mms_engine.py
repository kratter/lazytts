"""Meta MMS-TTS engine — VITS models via `transformers` (no extra dependency).

One small model per language (facebook/mms-tts-<iso3>), cached in the HF cache
like the other neural voices. Fully offline once downloaded.

LICENSE: the MMS-TTS weights are CC-BY-NC 4.0 (non-commercial use only).

MMS uses a stochastic duration predictor, so we fix the RNG seed for
reproducible output across runs (same text → same audio → cache stays valid).
"""
from __future__ import annotations

import numpy as np
import soundfile as sf

import config
from .base import TTSEngine


class MmsEngine(TTSEngine):
    name = "mms"
    sample_rate = 16000  # MMS VITS outputs 16 kHz (overwritten from model config).

    def __init__(self, voice: str = config.DEFAULT_MMS_VOICE, speed: float = 1.0,
                 device: str = "auto"):
        self.voice = voice
        self.speed = speed
        self.device = device
        self._models: dict[str, tuple] = {}

    def _resolve_device(self) -> str:
        try:
            import torch
            if self.device and self.device != "auto":
                return self.device
            return "cuda" if torch.cuda.is_available() else "cpu"
        except Exception:
            return "cpu"

    def _load(self, voice_id: str):
        if voice_id in self._models:
            return self._models[voice_id]
        from transformers import AutoTokenizer, VitsModel

        model_id = config.MMS_VOICES.get(voice_id, voice_id)
        model = VitsModel.from_pretrained(model_id)
        tok = AutoTokenizer.from_pretrained(model_id)
        dev = self._resolve_device()
        try:
            model = model.to(dev)
        except Exception:
            dev = "cpu"
            model = model.to("cpu")
        model.eval()
        self._models[voice_id] = (model, tok, dev)
        try:
            self.sample_rate = int(model.config.sampling_rate)
        except Exception:
            pass
        return self._models[voice_id]

    def synthesize_to_file(self, text, out_path, *, voice=None, speed=None) -> str:
        import torch

        model, tok, dev = self._load(voice or self.voice)
        spd = float(speed if speed is not None else self.speed) or 1.0
        # VITS speaking_rate: >1 speaks faster (shorter predicted durations).
        try:
            model.speaking_rate = spd
        except Exception:
            pass

        inputs = tok(text, return_tensors="pt")
        inputs = {k: v.to(dev) for k, v in inputs.items()}
        torch.manual_seed(0)  # deterministic (stochastic duration predictor)
        with torch.no_grad():
            waveform = model(**inputs).waveform
        audio = waveform.detach().cpu().numpy().reshape(-1).astype(np.float32)
        sf.write(out_path, audio, self.sample_rate)
        return out_path
