"""Piper offline neural TTS engine (ONNX) — German + other languages.

Piper voices are small ONNX models with excellent German narration, run on CPU,
and download once from the Hugging Face repo "rhasspy/piper-voices" into the HF
cache (respects HF_HOME). Handles both the older wave-based API and the newer
SynthesisConfig/AudioChunk API defensively.
"""
from __future__ import annotations

import wave

import numpy as np

import config
from .base import TTSEngine


class PiperEngine(TTSEngine):
    name = "piper"
    sample_rate = 22050  # updated from the loaded voice's config.

    def __init__(self, voice: str = config.DEFAULT_PIPER_VOICE, speed: float = 1.0, device=None):
        self.voice_id = voice
        self.speed = speed
        self._voices: dict[str, object] = {}

    def _load_voice(self, voice_id: str):
        if voice_id in self._voices:
            return self._voices[voice_id]
        from huggingface_hub import hf_hub_download

        rel = config.PIPER_VOICES.get(voice_id, voice_id)
        onnx = hf_hub_download(config.PIPER_HF_REPO, rel + ".onnx")
        try:
            cfg = hf_hub_download(config.PIPER_HF_REPO, rel + ".onnx.json")
        except Exception:
            cfg = None

        try:
            from piper import PiperVoice
        except Exception:
            from piper.voice import PiperVoice  # older layout

        try:
            voice = PiperVoice.load(onnx, config_path=cfg) if cfg else PiperVoice.load(onnx)
        except TypeError:
            voice = PiperVoice.load(onnx, cfg)

        self._voices[voice_id] = voice
        try:
            self.sample_rate = int(voice.config.sample_rate)
        except Exception:
            pass
        return voice

    def synthesize_to_file(self, text, out_path, *, voice=None, speed=None) -> str:
        voice_obj = self._load_voice(voice or self.voice_id)
        spd = float(speed if speed is not None else self.speed) or 1.0
        length_scale = 1.0 / spd  # >1 = slower; Piper uses length_scale

        # Newer API: synthesize(text, syn_config=...) -> iterable of AudioChunk.
        try:
            from piper import SynthesisConfig

            syn = SynthesisConfig(length_scale=length_scale)
            chunks = list(voice_obj.synthesize(text, syn_config=syn))
            pcm = b"".join(getattr(c, "audio_int16_bytes", b"") for c in chunks)
            sr = getattr(chunks[0], "sample_rate", None) if chunks else None
            sr = int(sr or self.sample_rate)
            self.sample_rate = sr
            with wave.open(out_path, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(sr)
                wf.writeframes(pcm)
            return out_path
        except (ImportError, TypeError, AttributeError):
            pass

        # Older API (piper-tts ~1.2): synthesize(text, wave_write, length_scale=...)
        with wave.open(out_path, "wb") as wf:
            voice_obj.synthesize(text, wf, length_scale=length_scale)
        try:
            self.sample_rate = int(voice_obj.config.sample_rate)
        except Exception:
            pass
        return out_path
