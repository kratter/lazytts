"""Split text into TTS-sized chunks on sentence boundaries."""
from __future__ import annotations

import re

# A sentence terminator (. ! ?) plus optional closing quote/paren, followed by
# whitespace. Python's re has no variable-width lookbehind, so we mark the
# boundary with a NUL and split on it instead.
_BOUNDARY = re.compile(r"([.!?]+[\"'”’)\]]*)(\s+)")


def split_sentences(text: str) -> list[str]:
    sentences: list[str] = []
    for paragraph in text.split("\n"):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        marked = _BOUNDARY.sub(lambda m: m.group(1) + "\x00", paragraph)
        for sent in marked.split("\x00"):
            sent = sent.strip()
            if sent:
                sentences.append(sent)
    return sentences


def chunk_text(text: str, max_chars: int = 1500) -> list[str]:
    """Group whole sentences into chunks of at most *max_chars* characters.

    A single sentence longer than *max_chars* is hard-split on word
    boundaries so nothing is silently dropped.
    """
    chunks: list[str] = []
    current: list[str] = []
    length = 0

    def flush():
        nonlocal current, length
        if current:
            chunks.append(" ".join(current))
            current = []
            length = 0

    for sentence in split_sentences(text):
        if len(sentence) > max_chars:
            flush()
            chunks.extend(_hard_split(sentence, max_chars))
            continue
        # +1 for the joining space.
        if length + len(sentence) + 1 > max_chars:
            flush()
        current.append(sentence)
        length += len(sentence) + 1

    flush()
    return chunks


def _hard_split(sentence: str, max_chars: int) -> list[str]:
    words = sentence.split()
    out: list[str] = []
    buf: list[str] = []
    n = 0
    for word in words:
        if n + len(word) + 1 > max_chars and buf:
            out.append(" ".join(buf))
            buf, n = [], 0
        buf.append(word)
        n += len(word) + 1
    if buf:
        out.append(" ".join(buf))
    return out
