"""User pronunciation lexicon — whole-word text replacements applied before
synthesis. Great for names, jargon, and fixing an engine's mispronunciations
(e.g. "Qwen => Kwen", "GPU => gee pee you").

Stored as lexicon.json (a list of [from, to] pairs) next to the app, and edited
in the UI as simple "from => to" lines.
"""
from __future__ import annotations

import json
import re

import config

_PATH = config.BASE_DIR / "lexicon.json"


def parse(text: str) -> list[tuple[str, str]]:
    """Parse 'from => to' lines (also accepts tab or | separators). '#' = comment."""
    pairs: list[tuple[str, str]] = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        for sep in ("=>", "\t", "|"):
            if sep in line:
                a, b = line.split(sep, 1)
                if a.strip():
                    pairs.append((a.strip(), b.strip()))
                break
    return pairs


def load_text() -> str:
    """Return the saved lexicon as editable 'from => to' lines."""
    try:
        pairs = json.loads(_PATH.read_text(encoding="utf-8"))
        return "\n".join(f"{a} => {b}" for a, b in pairs)
    except Exception:
        return ""


def save_text(text: str) -> None:
    try:
        _PATH.write_text(json.dumps(parse(text), ensure_ascii=False, indent=2),
                         encoding="utf-8")
    except Exception:
        pass


def _compiled(pairs):
    out = []
    for a, b in pairs:
        try:
            out.append((re.compile(rf"\b{re.escape(a)}\b", re.IGNORECASE), b))
        except re.error:
            continue
    return out


def apply(text: str, pairs) -> str:
    """Apply the (from, to) replacements to *text* (whole-word, case-insensitive)."""
    if not text or not pairs:
        return text
    if isinstance(pairs, str):
        pairs = parse(pairs)
    for rx, repl in _compiled(pairs):
        text = rx.sub(repl, text)
    return text
