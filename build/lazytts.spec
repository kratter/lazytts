# PyInstaller spec for lazyTTS.  Build:  python -m PyInstaller --noconfirm --clean build/lazytts.spec
#
# Bundling Gradio + PyTorch(CUDA) is heavy and finicky. Notes:
#   * Build ONE-DIR (not one-file): torch's CUDA DLLs + gradio's frontend
#     assets do not survive one-file extraction reliably.
#   * Gradio reads package METADATA at import (importlib.metadata.version), so
#     we copy_metadata() for it and its ecosystem, or the app crashes on launch.
#   * Model weights are NOT bundled; they load from the HF cache at runtime.
#     For a fully offline .exe, ship the hf_cache folder next to lazyTTS.exe and set
#     LAZYTTS_OFFLINE=1 (see README).
import os

from PyInstaller.utils.hooks import collect_all, copy_metadata

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))  # repo root (SPECPATH = build/)
ENTRY = os.path.join(ROOT, "app.py")

datas, binaries, hiddenimports = [], [], []

# Data files + dynamic submodules.
for pkg in [
    "gradio", "gradio_client", "safehttpx", "groovy",
    "kokoro", "misaki", "transformers",
    # Kokoro's English G2P (misaki.en) needs spaCy + the en_core_web_sm model;
    # misaki.espeak needs phonemizer + espeakng_loader. Bundle the whole chain.
    "spacy", "en_core_web_sm", "thinc", "blis", "cymem", "preshed",
    "murmurhash", "catalogue", "srsly", "wasabi", "spacy_legacy",
    "spacy_loggers", "langcodes", "language_tags", "weasel", "confection",
    "phonemizer", "espeakng_loader",
    "piper", "onnxruntime", "num2words",
    "sentencepiece",  # NLLB-200 translation tokenizer
    # Coqui XTTS-v2 (optional). collect_all pulls its data files (.models.json,
    # speaker tables, configs). MMS-TTS needs nothing beyond transformers.
    "TTS", "trainer", "coqpit", "pysbd", "anyascii", "inflect", "torchcodec",
    "ko_speech_tools",  # coqui-tts split-out (ships a .data subpackage XTTS needs)
    "webview",  # pywebview native window (best-effort; app falls back to browser)
    "ebooklib", "fitz", "docx", "soundfile",
    "segno",  # QR codes for "Send to device"
]:
    try:
        d, b, h = collect_all(pkg)
        datas += d
        binaries += b
        hiddenimports += h
    except Exception as exc:  # a missing optional package shouldn't kill the build
        print(f"[lazytts.spec] collect_all skipped {pkg}: {exc}")

# Package metadata required at runtime (mostly for gradio's version probes).
for dist in [
    "gradio", "gradio_client", "safehttpx", "groovy", "torch", "transformers",
    "tokenizers", "safetensors", "huggingface-hub", "numpy", "tqdm", "regex",
    "requests", "packaging", "filelock", "pyyaml", "kokoro",
    "piper-tts", "num2words", "sentencepiece",
    "coqui-tts", "coqui-tts-trainer", "coqpit-config",
    # spaCy resolves language/model factories via entry-point metadata.
    "spacy", "en_core_web_sm", "thinc", "catalogue", "srsly", "wasabi",
    "spacy_legacy", "spacy_loggers", "langcodes", "weasel", "confection",
    "phonemizer",
]:
    try:
        datas += copy_metadata(dist)
    except Exception as exc:
        print(f"[lazytts.spec] copy_metadata skipped {dist}: {exc}")

hiddenimports += ["pyttsx3.drivers", "pyttsx3.drivers.sapi5",
                  "prefetch_models", "config",
                  # pywebview Windows backend (WebView2 via pythonnet)
                  "webview.platforms.edgechromium", "webview.platforms.winforms",
                  "clr_loader", "clr"]

block_cipher = None

a = Analysis(
    [ENTRY],
    pathex=[ROOT],          # so `import config` and `import lazytts` resolve
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter"],  # NOTE: matplotlib kept — coqui-tts (XTTS) imports it.
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="lazyTTS",
    console=True,          # keep the console so progress/errors are visible
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe, a.binaries, a.zipfiles, a.datas,
    strip=False, upx=False, name="lazyTTS",
)
