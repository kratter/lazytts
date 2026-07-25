"""Persist last-used UI settings to settings.json next to the app.

Runtime state — no rebuild needed to change preferences; the .exe reads/writes
settings.json in its own folder.
"""
from __future__ import annotations

import json

import config

_PATH = config.BASE_DIR / "settings.json"


def load() -> dict:
    try:
        return json.loads(_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save(data: dict) -> None:
    try:
        _PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass
