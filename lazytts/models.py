"""Local model inventory + on-demand download.

Lets the app act as its own model downloader: report which model groups are
already cached and fetch only the missing ones. Hugging Face downloads are
incremental (already-present files are skipped), so re-running a download only
pulls what's actually needed.
"""
from __future__ import annotations

import os

import config

# group id -> (label, approx download size)
_GROUPS = [
    ("kokoro", "Kokoro — English voices", "~0.3 GB"),
    ("piper", "Piper — German/Hungarian & more", "~0.2 GB"),
    ("mms", "MMS — English/German/Hungarian", "~0.4 GB"),
    ("xtts", "Coqui XTTS-v2 — multilingual", "~1.8 GB"),
    ("nllb", "NLLB-200 — offline translation", "~2.4 GB"),
]


def _default_device() -> str:
    try:
        import torch
        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


def _hf_repo_cached(repo_id: str) -> bool:
    """True if a Hugging Face repo has anything in the local cache."""
    try:
        from huggingface_hub import scan_cache_dir
        return any(r.repo_id == repo_id for r in scan_cache_dir().repos)
    except Exception:
        base = os.path.join(os.environ.get("HF_HOME", ""), "hub",
                            "models--" + repo_id.replace("/", "--"))
        return os.path.isdir(base) and bool(os.listdir(base))


def _xtts_cached() -> bool:
    base = os.path.join(os.environ.get("TTS_HOME", ""), "tts",
                        config.XTTS_MODEL.replace("/", "--"))
    return os.path.isfile(os.path.join(base, "model.pth"))


def present(group_id: str) -> bool:
    if group_id == "kokoro":
        return _hf_repo_cached("hexgrad/Kokoro-82M")
    if group_id == "piper":
        return _hf_repo_cached(config.PIPER_HF_REPO)
    if group_id == "mms":
        return all(_hf_repo_cached(m) for m in config.MMS_VOICES.values())
    if group_id == "xtts":
        return _xtts_cached()
    if group_id == "nllb":
        return _hf_repo_cached(config.NLLB_MODEL)
    return False


def status() -> list[dict]:
    """List every model group with its label, size, and whether it's cached."""
    return [{"id": gid, "label": label, "size": size, "present": present(gid)}
            for gid, label, size in _GROUPS]


def label_of(group_id: str) -> str:
    for gid, label, _ in _GROUPS:
        if gid == group_id:
            return label
    return group_id


def download(group_id: str, device: str | None = None) -> None:
    """Download one group (only missing files are fetched). Raises on failure."""
    import prefetch_models as pf
    dev = device or _default_device()
    if group_id == "kokoro":
        pf._prefetch_kokoro(dev)
    elif group_id == "piper":
        pf._prefetch_piper()
    elif group_id == "mms":
        pf._prefetch_mms(dev)
    elif group_id == "xtts":
        pf._prefetch_xtts(dev)
    elif group_id == "nllb":
        pf._prefetch_translation()
    else:
        raise ValueError(f"unknown model group '{group_id}'")
