"""Optional online update check against the project's GitHub Releases.

Compares config.APP_VERSION to the latest published release tag. Network-only and
best-effort — never required for the app to run, and skipped in offline mode.

Note: for the check to work the repo's releases must be reachable anonymously
(i.e. a public repo, or public releases). A private repo returns 404.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

import config

_API = f"https://api.github.com/repos/{config.GITHUB_REPO}/releases/latest"
_RELEASES_URL = f"https://github.com/{config.GITHUB_REPO}/releases"


class RateLimited(RuntimeError):
    """GitHub's anonymous API allowance for this IP is used up.

    Unauthenticated callers get 60 requests an hour per address, shared by
    everything on the network. Worth telling apart from a real failure: nothing
    is broken and it clears by itself.
    """

    def __init__(self, reset_at: float | None = None):
        self.reset_at = reset_at
        when = ""
        if reset_at:
            import time as _time
            when = f" Try again after {_time.strftime('%H:%M', _time.localtime(reset_at))}."
        super().__init__(
            "GitHub is rate-limiting update checks from this network." + when)


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
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        # 403 with no remaining allowance is throttling, not a broken check.
        # 429 is the newer spelling of the same thing.
        remaining = exc.headers.get("X-RateLimit-Remaining")
        if exc.code == 429 or (exc.code == 403 and remaining == "0"):
            reset = exc.headers.get("X-RateLimit-Reset")
            raise RateLimited(float(reset) if reset else None) from exc
        raise
    latest = (data.get("tag_name") or "").strip()
    url = data.get("html_url") or _RELEASES_URL
    current = config.APP_VERSION
    assets = data.get("assets") or []
    exe = next((a for a in assets if str(a.get("name", "")).lower().endswith(".exe")), None)
    if exe is None and assets:
        exe = assets[0]
    return {
        "current": current,
        "latest": latest,
        "url": url,
        "update_available": bool(latest) and _parse(latest) > _parse(current),
        "asset_url": exe.get("browser_download_url") if exe else None,
        "asset_name": exe.get("name") if exe else None,
    }


def download_asset(url: str, dest_path: str, timeout: float = 30.0) -> str:
    """Download a release asset to *dest_path* with a tqdm bar (so the UI can
    show progress via gr.Progress(track_tqdm=True))."""
    import urllib.request
    from tqdm.auto import tqdm

    req = urllib.request.Request(url, headers={"User-Agent": "lazyTTS"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        total = int(resp.headers.get("Content-Length") or 0)
        with open(dest_path, "wb") as fh, tqdm(
                total=total, unit="B", unit_scale=True, desc="Downloading update") as bar:
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                fh.write(chunk)
                bar.update(len(chunk))
    return dest_path
