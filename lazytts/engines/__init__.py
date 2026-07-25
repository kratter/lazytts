"""TTS engine registry."""
from __future__ import annotations

from .base import TTSEngine


def list_cuda_devices() -> list[str]:
    """Return available torch device strings, or ['cpu'] if torch/CUDA absent."""
    try:
        import torch
    except Exception:
        return ["cpu"]
    devices = ["cpu"]
    try:
        if torch.cuda.is_available():
            devices = [
                f"cuda:{i} — {torch.cuda.get_device_name(i)}"
                for i in range(torch.cuda.device_count())
            ] + ["cpu"]
    except Exception:
        pass
    return devices


def device_id(label: str) -> str:
    """Turn a UI label like 'cuda:1 — RTX 5070' back into 'cuda:1'."""
    return label.split(" ")[0] if label else "cpu"


def build_engine(name: str, *, device: str = "auto", **kwargs) -> TTSEngine:
    if name == "kokoro":
        from .kokoro_engine import KokoroEngine
        return KokoroEngine(device=device)
    if name == "piper":
        from .piper_engine import PiperEngine
        return PiperEngine(device=device, **kwargs)
    if name == "mms":
        from .mms_engine import MmsEngine
        return MmsEngine(device=device)
    if name == "xtts":
        from .xtts_engine import XttsEngine
        return XttsEngine(device=device)
    if name == "sapi":
        from .sapi_engine import SapiEngine
        return SapiEngine()
    raise ValueError(f"Unknown engine '{name}'")
