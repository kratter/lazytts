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


def normalize(text: str, *, expand: bool = False, lang: str = "en") -> str:
    text = dehyphenate(text)
    text = strip_page_numbers(text)
    if expand:
        text = expand_abbreviations(text, lang)
        text = expand_numbers(text, lang)
    return text
