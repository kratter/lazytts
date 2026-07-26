"""Optional online update check against the project's GitHub Releases.

Compares config.APP_VERSION to the latest published release tag. Network-only and
best-effort — never required for the app to run, and skipped in offline mode.

Note: for the check to work the repo's releases must be reachable anonymously
(i.e. a public repo, or public releases). A private repo returns 404.
"""
from __future__ import annotations

import json
import os
import urllib.request

import config

_API = f"https://api.github.com/repos/{config.GITHUB_REPO}/releases/latest"
_RELEASES_URL = f"https://github.com/{config.GITHUB_REPO}/releases"


def _parse(version: str) -> tuple[int, ...]:
    """Turn 'v1.2.3' / '1.2' into a comparable tuple, ignoring non-numeric bits."""
    parts: list[int] = []
    for chunk in str(version).lstrip("vV").strip().split("."):
        digits = "".join(ch for ch in chunk if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts) or (0,)


def check(timeout: float = 6.0) -> dict:
    """Return {current, latest, url, update_available}. Raises on network error."""
    if os.environ.get("LAZYTTS_OFFLINE") == "1":
        raise RuntimeError("offline mode")
    req = urllib.request.Request(
        _API, headers={"Accept": "application/vnd.github+json", "User-Agent": "lazyTTS"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    latest = (data.get("tag_name") or "").strip()
    url = data.get("html_url") or _RELEASES_URL
    current = config.APP_VERSION
    return {
        "current": current,
        "latest": latest,
        "url": url,
        "update_available": bool(latest) and _parse(latest) > _parse(current),
    }
