"""Static configuration for lazyTTS."""
import os
import sys
from pathlib import Path

APP_NAME = "lazyTTS — eBook to Audiobook"
APP_VERSION = "0.9.4"
# owner/repo used for the in-app update check + release links.
GITHUB_REPO = "kratter/lazytts"

# Directories (created on demand). When frozen (PyInstaller .exe) anchor to the
# executable's folder so cache/output/hf_cache sit next to lazyTTS.exe; otherwise
# next to this source file.
if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    BASE_DIR = Path(__file__).resolve().parent
CACHE_DIR = BASE_DIR / "cache" / "audio_chunks"
OUTPUT_DIR = BASE_DIR / "audiobooks"

# Keep the Hugging Face model cache local to the app so downloads land here
# (and can be shipped with the .exe for offline use). Must be set before any
# `import kokoro` / huggingface_hub — this module is imported first, so it is.
# A user-provided HF_HOME still wins (setdefault). See make_offline.bat.
HF_CACHE_DIR = BASE_DIR / "hf_cache"
os.environ.setdefault("HF_HOME", str(HF_CACHE_DIR))
# Windows without Developer Mode can't make symlinks; silence the noisy warning.
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
# Avoid a network call at Gradio launch (faster startup, safe offline).
os.environ.setdefault("GRADIO_ANALYTICS_ENABLED", "False")
# Set LAZYTTS_OFFLINE=1 to forbid any network access (requires a populated cache).
if os.environ.get("LAZYTTS_OFFLINE") == "1":
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
# Coqui XTTS: accept its model license non-interactively (else it prompts and
# would hang the frozen exe), and keep its model cache local to the app so it
# ships next to lazyTTS.exe for offline use.
os.environ.setdefault("COQUI_TOS_AGREED", "1")
os.environ.setdefault("TTS_HOME", str(BASE_DIR / "tts_home"))

# Text chunking. Kokoro handles a few hundred chars per pass comfortably;
# we group whole sentences up to this many characters per chunk.
MAX_CHUNK_CHARS = 1500

# Engine-aware chunk sizes (characters per synthesis call).
CHUNK_CHARS = {
    "kokoro": 1500,
    "piper": 1500,
    "sapi": 2000,
    "mms": 800,     # MMS VITS: keep passages moderate for stable prosody
    "xtts": 220,    # XTTS is autoregressive; ~250-char cap per generation
}

# Silence inserted between chunks (seconds) for natural pacing.
CHUNK_GAP_SECONDS = 0.5

# ── EPUB 3 read-along (Media Overlays) ────────────────────────────
# Silence between sentences *inside* a paragraph. The main `gap` setting is
# used between paragraphs instead, so prose doesn't get a full pause after
# every sentence (which is what a single uniform gap would give us once the
# synthesis unit shrinks from a 1500-char chunk to one sentence).
SENTENCE_GAP_SECONDS = 0.15

# Reader compatibility profiles for the EPUB 3 export. The format is one
# standard; these knobs cover where readers actually differ in practice.
#   active_class  -> value of media:active-class; the reader adds this class to
#                    the current sentence. Readium-based readers (Thorium) use
#                    the "-epub-..." name; we always ship matching CSS.
#   textref_seq   -> wrap each paragraph's <par>s in a <seq epub:textref="...">.
#                    Spec-recommended structure; a flat par list is simpler and
#                    slightly more widely tolerated.
#   gapless       -> stretch each sentence's clipEnd to the next sentence's
#                    clipBegin, so the highlight never blanks out during the
#                    silence between sentences.
#   include_ncx   -> add an EPUB 2 NCX alongside the EPUB 3 nav document, for
#                    readers that still look for it.
#   audio_fmt     -> container for the per-chapter narration track.
#   word_level    -> emit one <par> per *word* (wrapped in a <seq> per sentence)
#                    instead of one per sentence, so a reader can highlight the
#                    word being spoken. Needs an engine that reports word times
#                    — Kokoro does; the export falls back to sentence-level for
#                    any chapter where they're missing. Off by default: it
#                    multiplies the number of <par>s by roughly the words per
#                    sentence, and not every reader handles that gracefully.
EPUB3_PROFILES = {
    "Universal (max compatibility)": {
        "active_class": "-epub-media-overlay-active",
        "textref_seq": False,
        "gapless": True,
        "include_ncx": True,
        "audio_fmt": "m4a",
        "word_level": False,
    },
    "Thorium Reader (desktop)": {
        "active_class": "-epub-media-overlay-active",
        "textref_seq": True,
        "gapless": True,
        "include_ncx": False,
        "audio_fmt": "m4a",
        "word_level": False,
    },
    "Storyteller (Android / iOS)": {
        "active_class": "-epub-media-overlay-active",
        "textref_seq": False,
        "gapless": True,
        "include_ncx": False,
        "audio_fmt": "mp3",
        "word_level": False,
    },
    "lazyREADER (word-by-word)": {
        "active_class": "-epub-media-overlay-active",
        "textref_seq": False,
        "gapless": True,
        "include_ncx": False,
        "audio_fmt": "mp3",
        "word_level": True,
    },
}
DEFAULT_EPUB3_PROFILE = "Universal (max compatibility)"

# Narration container for the read-along. The main Format dropdown doesn't
# apply here: the audio lives inside the .epub, so it has to be something
# ebook readers can decode. "Profile default" follows the table above.
EPUB3_AUDIO_FORMATS = {
    "Profile default": None,
    "m4a (AAC) — most accurate sync": "m4a",
    "mp3 — widest reader support": "mp3",
}
DEFAULT_EPUB3_AUDIO_FORMAT = "Profile default"

# How the narration is split across files.
#   per_chapter -> one audio file per chapter (recommended). Clip offsets stay
#                  small and the reader only loads the chapter it's playing.
#   single      -> one file for the whole book. Offsets run into the hours,
#                  which some readers seek through less accurately.
EPUB3_AUDIO_LAYOUTS = {
    "One file per chapter (recommended)": "per_chapter",
    "Single file for the whole book": "single",
}
DEFAULT_EPUB3_AUDIO_LAYOUT = "One file per chapter (recommended)"

SUPPORTED_EXTENSIONS = [".txt", ".pdf", ".epub", ".docx"]

# Kokoro voices. Prefix a* = American English (lang_code 'a'),
# b* = British English (lang_code 'b'). Value = friendly label.
KOKORO_VOICES = {
    "af_heart":   "Heart — US female (warm)",
    "af_bella":   "Bella — US female",
    "af_nicole":  "Nicole — US female (soft)",
    "af_sarah":   "Sarah — US female",
    "af_sky":     "Sky — US female",
    "am_adam":    "Adam — US male",
    "am_michael": "Michael — US male",
    "am_onyx":    "Onyx — US male (deep)",
    "am_puck":    "Puck — US male",
    "bf_emma":    "Emma — UK female",
    "bf_isabella":"Isabella — UK female",
    "bm_george":  "George — UK male",
    "bm_lewis":   "Lewis — UK male",
}
DEFAULT_VOICE = "af_heart"

# ── Piper voices (offline ONNX; German + a few others) ────────────
# id -> relative path in the Hugging Face repo "rhasspy/piper-voices"
# (without extension; .onnx and .onnx.json are fetched).
PIPER_VOICES = {
    "de_DE-thorsten-medium": "de/de_DE/thorsten/medium/de_DE-thorsten-medium",
    "de_DE-thorsten-high":   "de/de_DE/thorsten/high/de_DE-thorsten-high",
    "de_DE-eva_k-x_low":     "de/de_DE/eva_k/x_low/de_DE-eva_k-x_low",
    "de_DE-kerstin-low":     "de/de_DE/kerstin/low/de_DE-kerstin-low",
    "de_DE-karlsson-low":    "de/de_DE/karlsson/low/de_DE-karlsson-low",
    "de_DE-ramona-low":      "de/de_DE/ramona/low/de_DE-ramona-low",
    "hu_HU-anna-medium":     "hu/hu_HU/anna/medium/hu_HU-anna-medium",
    "hu_HU-berta-medium":    "hu/hu_HU/berta/medium/hu_HU-berta-medium",
    "hu_HU-imre-medium":     "hu/hu_HU/imre/medium/hu_HU-imre-medium",
    "en_US-lessac-medium":   "en/en_US/lessac/medium/en_US-lessac-medium",
    "en_GB-alan-medium":     "en/en_GB/alan/medium/en_GB-alan-medium",
}
PIPER_VOICE_LABELS = {
    "de_DE-thorsten-medium": "Thorsten — DE male (medium) ★",
    "de_DE-thorsten-high":   "Thorsten — DE male (high)",
    "de_DE-eva_k-x_low":     "Eva K. — DE female",
    "de_DE-kerstin-low":     "Kerstin — DE female",
    "de_DE-karlsson-low":    "Karlsson — DE male",
    "de_DE-ramona-low":      "Ramona — DE female",
    "hu_HU-anna-medium":     "Anna — HU female ★",
    "hu_HU-berta-medium":    "Berta — HU female",
    "hu_HU-imre-medium":     "Imre — HU male",
    "en_US-lessac-medium":   "Lessac — US English",
    "en_GB-alan-medium":     "Alan — UK English",
}
DEFAULT_PIPER_VOICE = "de_DE-thorsten-medium"
PIPER_HF_REPO = "rhasspy/piper-voices"

# ── Meta MMS-TTS voices (VITS via transformers; offline) ──────────
# One small model per language (~40M params each). LICENSE: CC-BY-NC 4.0
# (non-commercial). id -> Hugging Face model. Cached in hf_cache like Kokoro.
MMS_VOICES = {
    "mms_eng": "facebook/mms-tts-eng",
    "mms_deu": "facebook/mms-tts-deu",
    "mms_hun": "facebook/mms-tts-hun",
}
MMS_VOICE_LABELS = {
    "mms_eng": "English — MMS (VITS)",
    "mms_deu": "German — MMS (VITS)",
    "mms_hun": "Hungarian — MMS (VITS)",
}
DEFAULT_MMS_VOICE = "mms_eng"
# MMS voice id -> language code (for choosing preview sample text).
MMS_VOICE_LANG = {"mms_eng": "en", "mms_deu": "de", "mms_hun": "hu"}

# ── Coqui XTTS-v2 voices (multilingual + cloning; ~1.8 GB) ────────
# LICENSE: Coqui Public Model License (non-commercial). Autoregressive → much
# slower than Piper/Kokoro; best for short or highest-quality output.
# id -> (xtts language code, built-in studio speaker name).
XTTS_MODEL = "tts_models/multilingual/multi-dataset/xtts_v2"
XTTS_VOICES = {
    "xtts_en_f": ("en", "Claribel Dervla"),
    "xtts_en_m": ("en", "Damien Black"),
    "xtts_de_f": ("de", "Gitta Nikolina"),
    "xtts_de_m": ("de", "Baldur Sanjin"),
    "xtts_hu_f": ("hu", "Szofi Granger"),
    "xtts_hu_m": ("hu", "Viktor Eka"),
}
XTTS_VOICE_LABELS = {
    "xtts_en_f": "English — female (XTTS)",
    "xtts_en_m": "English — male (XTTS)",
    "xtts_de_f": "German — female (XTTS)",
    "xtts_de_m": "German — male (XTTS)",
    "xtts_hu_f": "Hungarian — female (XTTS)",
    "xtts_hu_m": "Hungarian — male (XTTS)",
}
DEFAULT_XTTS_VOICE = "xtts_en_f"

# Text language for number/abbreviation expansion (num2words). Label -> code.
# Also used as the SOURCE language when translating (see NLLB_SOURCE_CODES).
TEXT_LANGUAGES = {
    "English": "en", "German": "de", "Hungarian": "hu", "French": "fr",
    "Spanish": "es", "Italian": "it", "Portuguese": "pt",
}
DEFAULT_TEXT_LANGUAGE = "English"

# ── Offline translation (NLLB-200, runs via transformers on GPU/CPU) ─────
# One ~2.4 GB model covers 200 languages; weights live in hf_cache like voices.
NLLB_MODEL = "facebook/nllb-200-distilled-600M"

# "Translate to" dropdown: UI label -> NLLB FLORES-200 target code (None = off).
TRANSLATE_TARGETS = {
    "Off — keep original language": None,
    "German (Deutsch)": "deu_Latn",
    "Hungarian (Magyar)": "hun_Latn",
    "English": "eng_Latn",
}
DEFAULT_TRANSLATE_TARGET = "Off — keep original language"

# Source language: map the (num2words) text-language code -> NLLB source code.
NLLB_SOURCE_CODES = {
    "en": "eng_Latn", "de": "deu_Latn", "hu": "hun_Latn",
    "fr": "fra_Latn", "es": "spa_Latn", "it": "ita_Latn", "pt": "por_Latn",
}

# When a target language is picked, suggest an engine + voice that speaks it
# (Kokoro is English-only, so translated output routes through Piper).
TRANSLATE_VOICE_HINT = {
    "deu_Latn": ("piper", "de_DE-thorsten-medium"),
    "hun_Latn": ("piper", "hu_HU-anna-medium"),
    "eng_Latn": ("piper", "en_US-lessac-medium"),
}

# Output formats (value = key handled by lazytts/audio.py). Lossy formats use the
# bitrate; flac/wav/wav24 ignore it. m4a = AAC in an MP4 container.
OUTPUT_FORMATS = ["mp3", "m4a", "opus", "flac", "wav", "wav24"]
LOSSY_FORMATS = {"mp3", "m4a", "aac", "opus"}          # bitrate applies
TAGGABLE_FORMATS = {"mp3", "m4a", "aac", "flac", "opus"}  # can carry metadata/cover
MP3_BITRATES = ["96k", "128k", "192k", "256k"]
DEFAULT_BITRATE = "128k"
DEFAULT_FORMAT = "mp3"
# File extension per format key (defaults to the key itself).
FORMAT_EXT = {"wav24": "wav"}

# ── Loudness presets (ffmpeg loudnorm targets: I / TP / LRA). None = raw. ──
LOUDNESS_PRESETS = {
    "Off (raw)": None,
    "Audiobook −16 LUFS": (-16.0, -1.5, 11.0),
    "ACX audiobook (−19, peak −3)": (-19.0, -3.0, 9.0),
    "Podcast −16 LUFS": (-16.0, -1.5, 11.0),
    "Loud −14 LUFS": (-14.0, -1.0, 11.0),
}
DEFAULT_LOUDNESS_PRESET = "Audiobook −16 LUFS"

# Voice cleanup filter chain (applied before loudness): high-pass removes rumble,
# afftdn is a light broadband denoise (helps the more robotic MMS voice).
CLEANUP_FILTER = "highpass=f=70,afftdn=nf=-25"
# Trim silence from the start/end of each assembled file.
TRIM_SILENCE_FILTER = (
    "silenceremove=start_periods=1:start_silence=0.1:start_threshold=-50dB:"
    "stop_periods=1:stop_silence=0.1:stop_threshold=-50dB:detection=peak"
)

# 0.9 reads a touch slower than the engines' native pace — easier to follow for
# long-form listening, and it pairs with the 0.5 s inter-chunk gap above.
SPEED_MIN, SPEED_MAX, SPEED_DEFAULT = 0.5, 2.0, 0.9

# ── Loudness / volume ─────────────────────────────────────────────
# EBU R128 loudness normalization target (ffmpeg loudnorm). ~-16 LUFS is a
# common, comfortably-loud level for spoken-word / audiobooks.
LOUDNORM_FILTER = "loudnorm=I=-16:TP=-1.5:LRA=11"
# Extra manual gain applied after normalization (dB).
GAIN_MIN, GAIN_MAX, GAIN_DEFAULT = -6.0, 12.0, 0.0
