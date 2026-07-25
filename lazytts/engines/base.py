"""Abstract TTS engine interface.

Every engine writes a single mono WAV file for a chunk of text. Keeping the
contract at the file level lets engines with wildly different internals
(neural tensors vs. the Windows SAPI COM API) share one pipeline.
"""
from __future__ import annotations

import abc


class TTSEngine(abc.ABC):
    #: Short identifier, also used in cache keys.
    name: str = "base"
    #: Output sample rate in Hz. Constant per engine → chunks are concat-safe.
    sample_rate: int = 24000

    @abc.abstractmethod
    def synthesize_to_file(
        self,
        text: str,
        out_path: str,
        *,
        voice: str | None = None,
        speed: float | None = None,
    ) -> str:
        """Synthesize *text* to a WAV at *out_path*; return *out_path*."""

    def load(self) -> None:  # pragma: no cover - optional warm-up hook
        """Optionally pre-load heavy models. Safe to call more than once."""
