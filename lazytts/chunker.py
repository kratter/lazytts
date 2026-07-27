"""Split text into TTS-sized chunks on sentence boundaries."""
from __future__ import annotations

import re

# A sentence terminator (. ! ?) plus optional closing quote/paren, followed by
# whitespace. Python's re has no variable-width lookbehind, so we mark the
# boundary with a NUL and split on it instead.
_BOUNDARY = re.compile(r"([.!?]+[\"'”’)\]]*)(\s+)")

# An ellipsis is a pause, not the end of a sentence, but "..." matches [.!?]+
# and would split one. Hide ellipses behind placeholders while splitting, then
# put them back verbatim.
_ELLIPSIS = re.compile(r"\.{3,}|…")
_ELLIPSIS_MARK = "\x02"


def _hide_ellipses(text: str) -> tuple[str, list[str]]:
    found: list[str] = []

    def stash(match: re.Match) -> str:
        found.append(match.group(0))
        return _ELLIPSIS_MARK

    return _ELLIPSIS.sub(stash, text), found


def _restore_ellipses(parts: list[str], found: list[str]) -> list[str]:
    """Put the originals back, in order — placeholders were stashed in order."""
    if not found:
        return parts
    pending = iter(found)
    return [re.sub(_ELLIPSIS_MARK, lambda _m: next(pending), part)
            for part in parts]


def paragraph_sentences(text: str) -> list[list[str]]:
    """Sentences grouped by source paragraph.

    Same splitting rules as `split_sentences`, but the paragraph structure is
    preserved so callers can rebuild markup (one <p> per paragraph) and pace
    paragraph breaks differently from sentence breaks. Used by the EPUB 3
    read-along export.
    """
    paragraphs: list[list[str]] = []
    for paragraph in text.split("\n"):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        hidden, ellipses = _hide_ellipses(paragraph)
        marked = _BOUNDARY.sub(lambda m: m.group(1) + "\x00", hidden)
        sentences = [s.strip() for s in marked.split("\x00") if s.strip()]
        sentences = _restore_ellipses(sentences, ellipses)
        if sentences:
            paragraphs.append(sentences)
    return paragraphs


def split_sentences(text: str) -> list[str]:
    return [s for paragraph in paragraph_sentences(text) for s in paragraph]


def sentence_pieces(sentence: str, max_chars: int) -> list[str]:
    """Split one sentence into synthesis-sized pieces — usually just itself.

    A sentence longer than the engine's per-call limit has to be synthesized in
    several passes, but it stays *one* highlightable unit, so the caller keeps
    the pieces grouped.
    """
    if len(sentence) <= max_chars:
        return [sentence]
    return _hard_split(sentence, max_chars)


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
