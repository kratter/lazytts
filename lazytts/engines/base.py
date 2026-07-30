"""Abstract TTS engine interface.

Every engine writes a single mono WAV file for a chunk of text. Keeping the
contract at the file level lets engines with wildly different internals
(neural tensors vs. the Windows SAPI COM API) share one pipeline.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass


@dataclass
class WordSpan:
    """One word and where it falls inside the WAV the engine just wrote.

    Times are seconds from the start of that file, not from the chapter.
    """
    text: str
    begin: float
    end: float


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

    def synthesize_with_words(
        self,
        text: str,
        out_path: str,
        *,
        voice: str | None = None,
        speed: float | None = None,
    ) -> tuple[str, list[WordSpan] | None]:
        """Same as :meth:`synthesize_to_file`, plus per-word times if known.

        Returns ``(out_path, spans)``. ``spans`` is None for engines that can't
        report word boundaries, and callers fall back to sentence-level timing.
        """
        return self.synthesize_to_file(
            text, out_path, voice=voice, speed=speed
        ), None

    def load(self) -> None:  # pragma: no cover - optional warm-up hook
        """Optionally pre-load heavy models. Safe to call more than once."""
