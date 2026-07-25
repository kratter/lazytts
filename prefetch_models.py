"""Pre-download models into the local HF cache (./hf_cache) so the app — and a
packaged .exe shipped with that folder — can run fully offline.

Importing `config` first pins HF_HOME to ./hf_cache before any model library is
imported.

Usage:
    python prefetch_models.py            # Kokoro model + all voices + Piper voices

Each group is independent: a failure in one (e.g. a package that didn't
install) is reported and skipped, and the others still download.
"""
from __future__ import annotations

import os
import sys

import config  # noqa: F401  (side effect: sets HF_HOME)


def _detect_device() -> str:
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


def _prefetch_kokoro(device: str) -> None:
    print("\n=== Kokoro model + voices ===")
    try:
        from kokoro import KModel, KPipeline
    except Exception as exc:
        print(f"[skip] Kokoro not installed ({exc}); skipping.")
        return

    print(f"Loading Kokoro model on {device} (first run downloads weights)...")
    try:
        model = KModel().to(device).eval()
    except Exception as exc:
        print(f"[WARN] could not load Kokoro model: {exc}")
        return

    voices = list(config.KOKORO_VOICES.keys())
    pipelines: dict[str, object] = {}
    failed: list[str] = []
    for i, voice in enumerate(voices, 1):
        lang = "b" if voice.startswith("b") else "a"
        if lang not in pipelines:
            pipelines[lang] = KPipeline(lang_code=lang, model=model)
        print(f"[{i}/{len(voices)}] caching voice '{voice}' ...", flush=True)
        try:
            # A tiny synthesis forces the voice pack to download and load.
            for _ in pipelines[lang]("Hello.", voice=voice):
                pass
        except Exception as exc:
            print(f"    [WARN] failed for {voice}: {exc}")
            failed.append(voice)
    if failed:
        print("Voices that did NOT cache:", ", ".join(failed))
    else:
        print("Kokoro cached.")


def _prefetch_piper() -> None:
    print("\n=== Piper voices (German & more) ===")
    try:
        from huggingface_hub import hf_hub_download
    except Exception as exc:
        print(f"[skip] huggingface_hub unavailable ({exc}); skipping.")
        return
    for vid, rel in config.PIPER_VOICES.items():
        print(f"caching Piper voice '{vid}' ...", flush=True)
        for ext in (".onnx", ".onnx.json"):
            try:
                hf_hub_download(config.PIPER_HF_REPO, rel + ext)
            except Exception as exc:
                print(f"    [WARN] failed {vid}{ext}: {exc}")
    print("Piper voices cached.")


def _prefetch_translation() -> None:
    print("\n=== Translation model (NLLB-200, ~2.4 GB) ===")
    try:
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
    except Exception as exc:
        print(f"[skip] transformers unavailable ({exc}); skipping.")
        return
    try:
        print(f"caching '{config.NLLB_MODEL}' (first run downloads weights)...", flush=True)
        AutoTokenizer.from_pretrained(config.NLLB_MODEL)
        AutoModelForSeq2SeqLM.from_pretrained(config.NLLB_MODEL)
        print("NLLB-200 cached.")
    except Exception as exc:
        print(f"[WARN] could not cache NLLB-200: {exc}")


def _prefetch_mms(device: str) -> None:
    print("\n=== Meta MMS-TTS voices (EN/DE/HU) ===")
    try:
        from transformers import AutoTokenizer, VitsModel
    except Exception as exc:
        print(f"[skip] transformers unavailable ({exc}); skipping.")
        return
    for vid, model_id in config.MMS_VOICES.items():
        print(f"caching MMS voice '{vid}' ({model_id}) ...", flush=True)
        try:
            VitsModel.from_pretrained(model_id)
            AutoTokenizer.from_pretrained(model_id)
        except Exception as exc:
            print(f"    [WARN] failed {vid}: {exc}")
    print("MMS voices cached.")


def _prefetch_xtts(device: str) -> None:
    print("\n=== Coqui XTTS-v2 (multilingual, ~1.8 GB) ===")
    try:
        from TTS.api import TTS
    except Exception as exc:
        print(f"[skip] coqui-tts not installed ({exc}); skipping.")
        return
    try:
        print("downloading XTTS-v2 (accepts the non-commercial model license) ...", flush=True)
        TTS(config.XTTS_MODEL)
        print("XTTS-v2 cached.")
    except Exception as exc:
        print(f"[WARN] could not cache XTTS-v2: {exc}")


def main() -> int:
    # Flags let the installers split downloads by size/need:
    #   --skip-translation   omit NLLB-200 (~2.4 GB)
    #   --only-translation   ONLY NLLB-200
    #   --skip-xtts          omit Coqui XTTS-v2 (~1.8 GB)
    #   --only-xtts          ONLY XTTS-v2
    # (Kokoro + Piper + the small MMS voices always download in the default run.)
    args = set(sys.argv[1:])

    print("HF cache location:", os.environ.get("HF_HOME"))
    device = _detect_device()

    if "--only-translation" in args:
        _prefetch_translation()
    elif "--only-xtts" in args:
        _prefetch_xtts(device)
    else:
        _prefetch_kokoro(device)
        _prefetch_piper()
        _prefetch_mms(device)
        if "--skip-xtts" not in args:
            _prefetch_xtts(device)
        if "--skip-translation" not in args:
            _prefetch_translation()

    print("\nDone. Cache location:", os.environ.get("HF_HOME"))
    print("For a no-internet run, launch with LAZYTTS_OFFLINE=1 set")
    print("(run_offline.bat does this for you).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
