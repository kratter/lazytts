"""Text normalization for more natural narration.

Always-safe cleanups (de-hyphenation, page-number stripping) plus optional,
riskier expansion of numbers and abbreviations into spoken words.
"""
from __future__ import annotations

import re

# Abbreviation -> spoken form. Keys are regex (word-boundary anchored).
_ABBREV = {
    r"\bMrs\.": "Missus",
    r"\bMr\.": "Mister",
    r"\bMs\.": "Miss",
    r"\bDr\.": "Doctor",
    r"\bProf\.": "Professor",
    r"\bSt\.": "Saint",
    r"\bJr\.": "Junior",
    r"\bSr\.": "Senior",
    r"\bvs\.": "versus",
    r"\betc\.": "et cetera",
    r"\be\.g\.": "for example",
    r"\bi\.e\.": "that is",
    r"\bNo\.": "Number",
    r"\bFig\.": "Figure",
}


def dehyphenate(text: str) -> str:
    """Join words split across a line break: 'exam-\\nple' -> 'example'."""
    return re.sub(r"(\w)-\n(\w)", r"\1\2", text)


def strip_page_numbers(text: str) -> str:
    """Drop lines that are just a page number."""
    return "\n".join(
        line for line in text.split("\n")
        if not re.fullmatch(r"\s*\d{1,4}\s*", line)
    )


def expand_abbreviations(text: str) -> str:
    for pattern, replacement in _ABBREV.items():
        text = re.sub(pattern, replacement, text)
    return text


def _num_to_words(n: int, lang: str, to: str = "cardinal") -> str:
    """num2words with graceful fallback (some langs lack 'year'/'ordinal')."""
    try:
        from num2words import num2words
    except Exception:
        return str(n)
    for kind in (to, "cardinal"):
        try:
            return num2words(n, lang=lang, to=kind)
        except Exception:
            continue
    return str(n)


def expand_numbers(text: str, lang: str = "en") -> str:
    """Turn digits into spoken words in *lang*. No-op if num2words is missing."""
    try:
        import num2words  # noqa: F401
    except Exception:
        return text

    # Ordinals: 1st/2nd/3rd/21st (English suffixes).
    text = re.sub(
        r"\b(\d+)(?:st|nd|rd|th)\b",
        lambda m: _num_to_words(int(m.group(1)), lang, to="ordinal"),
        text,
    )
    # Years 1000-2099.
    text = re.sub(
        r"\b(1\d{3}|20\d{2})\b",
        lambda m: _num_to_words(int(m.group(1)), lang, to="year"),
        text,
    )
    # Remaining integers (optional thousands separators).
    text = re.sub(
        r"\b\d{1,3}(?:,\d{3})+\b|\b\d+\b",
        lambda m: _num_to_words(int(m.group(0).replace(",", "")), lang),
        text,
    )
    return text


# German abbreviation expansions (applied when lang == 'de').
_ABBREV_DE = {
    r"\bDr\.": "Doktor",
    r"\bProf\.": "Professor",
    r"\bz\.\s?B\.": "zum Beispiel",
    r"\bu\.\s?a\.": "unter anderem",
    r"\bbzw\.": "beziehungsweise",
    r"\busw\.": "und so weiter",
    r"\bNr\.": "Nummer",
    r"\bStr\.": "Straße",
    r"\bggf\.": "gegebenenfalls",
}


def expand_abbreviations(text: str, lang: str = "en") -> str:
    table = _ABBREV_DE if lang == "de" else _ABBREV
    for pattern, replacement in table.items():
        text = re.sub(pattern, replacement, text)
    return text


def for_speech(text: str) -> str:
    """Rewrite punctuation the engines vocalize badly into plain pauses.

    Applied only to what's handed to the TTS engine, never to the text shown in
    the read-along — an ellipsis should still *look* like an ellipsis. Engines
    tend to either read "..." aloud or emit a glitch, so it becomes real
    punctuation: a sentence break where one is clearly intended, a comma
    (a short pause) otherwise.
    """
    # A whole line of decoration (scene breaks like "* * *", "~~~", "###") has
    # no speech in it at all; left in, voices spell the symbols out one by one.
    text = re.sub(r"^\s*[*~#=•·—–_+°^|]{1,}(?:\s*[*~#=•·—–_+°^|]+)*\s*$", " ", text)

    # Spaced-out ellipses (". . .") are common in typeset prose and were read
    # literally, because the earlier patterns only matched consecutive dots.
    text = re.sub(r"\.\s*\.\s*\.(?:\s*\.)*", "…", text)

    # Ellipsis at the very end, or followed by something that starts a new
    # sentence -> a full stop.
    text = re.sub(r"\s*(?:\.{3,}|…)\s*$", ".", text)
    text = re.sub(r"\s*(?:\.{3,}|…)\s*(?=[\"'”’)\]]*\s*[A-ZÀ-Þ])", ". ", text)
    # Otherwise it's a mid-sentence trailing-off -> a comma.
    text = re.sub(r"\s*(?:\.{3,}|…)\s*", ", ", text)
    # Em/en dashes used as asides are read as "dash" by some voices.
    text = re.sub(r"\s*[—–]\s*", ", ", text)
    # Decorative runs of dashes/underscores carry no speech at all.
    text = re.sub(r"[-_]{2,}", " ", text)

    # Guillemets and low quotes are quotation marks, but several voices announce
    # them by name. Plain quotes are safe: engines treat them as prosody.
    text = re.sub(r"[«»‹›„‚]", '"', text)

    # Ampersand is meaningful, so say it rather than dropping it.
    text = re.sub(r"\s*&\s*", " and ", text)

    # Symbols left mid-sentence that voices vocalize ("bullet", "section",
    # "vertical bar"). A comma keeps the phrasing the punctuation implied.
    text = re.sub(r"\s*[•·‣▪◦]\s*", ", ", text)
    text = re.sub(r"[§¶†‡|¦^~*]+", " ", text)

    # Collapse any doubled-up commas the substitutions above can leave behind
    # ("..., —" -> ", ,").
    text = re.sub(r"(?:,\s*){2,}", ", ", text)
    text = re.sub(r"\s+([,.!?;:])", r"\1", text)
    text = re.sub(r",\s*([.!?])", r"\1", text)
    # A comma straight after other punctuation reads as a stumble ("Items:,").
    text = re.sub(r"([:;,.!?])\s*,", r"\1", text)

    return re.sub(r"[ \t]+", " ", text).strip()


def normalize(text: str, *, expand: bool = False, lang: str = "en") -> str:
    text = dehyphenate(text)
    text = strip_page_numbers(text)
    if expand:
        text = expand_abbreviations(text, lang)
        text = expand_numbers(text, lang)
    return text
