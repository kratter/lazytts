"""lazyTTS — Gradio UI for the offline eBook → audiobook converter.

Run:  python app.py   (or run.bat)
Engines: Kokoro (English, fast) · Piper (German + others) · Windows SAPI.
"""
from __future__ import annotations

import atexit
import os
import re
import sys
import threading
import time
from pathlib import Path

# Import config FIRST so HF_HOME / offline / analytics env is set before gradio.
import config
import gradio as gr

from lazytts import document, lanserver, lexicon, settings_store
from lazytts.converter import Converter
from lazytts.engines import build_engine, device_id, list_cuda_devices


def _engine_available(name: str) -> bool:
    try:
        if name == "kokoro":
            import kokoro, torch  # noqa: F401
            return True
        if name == "piper":
            import piper  # noqa: F401
            return True
        if name == "mms":
            import torch, transformers  # noqa: F401
            from transformers import VitsModel  # noqa: F401
            return True
        if name == "xtts":
            import TTS  # noqa: F401  (coqui-tts)
            return True
        if name == "sapi":
            import pyttsx3  # noqa: F401
            return True
    except Exception as exc:
        # Record why an engine is unavailable (helps diagnose the packaged .exe).
        try:
            import traceback
            with open(os.path.join(str(config.BASE_DIR), "engine_errors.log"), "a", encoding="utf-8") as fh:
                fh.write(f"[{name}] {type(exc).__name__}: {exc}\n{traceback.format_exc()}\n")
        except Exception:
            pass
        return False
    return False


def available_engines() -> list[str]:
    engines = [n for n in ("kokoro", "piper", "mms", "xtts", "sapi") if _engine_available(n)]
    return engines or ["sapi"]


SAMPLE_TEXT = (
    "The quick brown fox jumps over the lazy dog. "
    "This is a short preview of the selected voice."
)
SAMPLE_TEXT_DE = (
    "Franz jagt im komplett verwahrlosten Taxi quer durch Bayern. "
    "Dies ist eine kurze Hörprobe der gewählten Stimme."
)
SAMPLE_TEXT_HU = (
    "A gyors barna róka átugorja a lusta kutyát. "
    "Ez egy rövid hangminta a kiválasztott hangról."
)
_SAMPLE_BY_LANG = {"en": SAMPLE_TEXT, "de": SAMPLE_TEXT_DE, "hu": SAMPLE_TEXT_HU}

OUTPUT_MODES = {
    "Single file": "single",
    "Split by chapter + M3U": "split",
    "M4B (chapters + metadata)": "m4b",
    "EPUB 3 read-along (synced text)": "epub3",
}


def _fmt_eta(seconds: float) -> str:
    seconds = int(max(0, seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h{m:02d}m"
    if m:
        return f"{m}m{s:02d}s"
    return f"{s}s"


# ── Antigravity-inspired dark theme (self-contained, no external fonts) ──
THEME_CSS = """
.gradio-container { max-width: 100% !important; margin: 0 !important;
  padding-left: 22px !important; padding-right: 22px !important;
  font-family: 'Inter', system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif; }
/* Gradio's inner wrap also caps width in some themes — let it fill. */
.gradio-container .main, .gradio-container > .wrap, .app { max-width: 100% !important; }

:root {
  --qa-violet:#8b5cf6; --qa-cyan:#22d3ee;
  --qa-bg:#0a0b0f; --qa-surface:#14161d; --qa-surface-2:#1b1e27;
  --qa-border:#272b36; --qa-text:#edeff5; --qa-muted:#9aa3b2;

  --body-background-fill: radial-gradient(1200px 640px at 16% -14%, #191d2e 0%, #0a0b0f 60%) fixed;
  --body-text-color: var(--qa-text);
  --body-text-color-subdued: var(--qa-muted);
  --background-fill-primary: var(--qa-surface);
  --background-fill-secondary: var(--qa-surface-2);
  --block-background-fill: var(--qa-surface);
  --block-border-color: var(--qa-border);
  --block-border-width: 1px;
  --block-label-background-fill: transparent;
  --block-label-text-color: var(--qa-muted);
  --block-title-text-color: var(--qa-text);
  --border-color-primary: var(--qa-border);
  --panel-background-fill: var(--qa-surface);
  --input-background-fill: #10121a;
  --input-border-color: #2a2f3c;
  --input-border-color-focus: var(--qa-violet);
  --checkbox-background-color-selected: var(--qa-violet);
  --checkbox-border-color-selected: var(--qa-violet);
  --slider-color: var(--qa-violet);
  --color-accent: var(--qa-violet);
  --color-accent-soft: rgba(139,92,246,.16);
  --link-text-color: var(--qa-cyan);
  --block-radius: 16px;
  --button-large-radius: 12px;
  --button-small-radius: 10px;
  --input-radius: 10px;
  --button-primary-background-fill: linear-gradient(100deg,#8b5cf6,#22d3ee);
  --button-primary-background-fill-hover: linear-gradient(100deg,#7b4ef2,#14c8e4);
  --button-primary-text-color: #08090d;
  --button-primary-border-color: transparent;
  --button-secondary-background-fill: #1b1e27;
  --button-secondary-text-color: var(--qa-text);
  --button-secondary-border-color: var(--qa-border);
}

#lazytts-header { display:flex; align-items:center; gap:16px; padding:8px 2px 16px; }
#lazytts-header .badge { width:52px; height:52px; border-radius:15px; display:grid;
  place-items:center; font-size:26px;
  background:linear-gradient(135deg, rgba(139,92,246,.95), rgba(34,211,238,.95));
  box-shadow:0 10px 30px rgba(139,92,246,.35); }
#lazytts-header .title { font-size:1.75rem; font-weight:750; letter-spacing:.3px;
  line-height:1.1; background:linear-gradient(100deg,#c4b5fd,#67e8f9);
  -webkit-background-clip:text; background-clip:text; color:transparent; }
#lazytts-header .sub { color:var(--qa-muted); font-size:.92rem; margin-top:3px; }

button.primary { font-weight:600 !important; box-shadow:0 8px 24px rgba(139,92,246,.28); }
button:hover { filter:brightness(1.04); }
#stop-btn button { background:#2a1416 !important; color:#ff8a93 !important;
  border-color:#5a2a2f !important; box-shadow:none !important; }
.block { border-radius: var(--block-radius); }

/* ── Responsive card grid: reflows 1 → 2 → 3 → 4 columns by window width ── */
#lazytts-grid { display:grid !important; gap:18px; align-items:start;
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); }
#lazytts-grid > * { min-width:0 !important; }   /* let cards shrink instead of overflow */

.lazytts-card { background:var(--qa-surface) !important;
  border:1px solid var(--qa-border) !important; border-radius:var(--block-radius) !important;
  padding:14px 16px 18px !important; box-shadow:0 6px 22px rgba(0,0,0,.25); }
.lazytts-card > .block, .lazytts-card .form { background:transparent !important; }
.lazytts-card .sect { display:flex; align-items:center; gap:9px; margin:2px 0 10px;
  font-weight:700; font-size:1.02rem; color:var(--qa-text); }
.lazytts-card .sect .n { flex:0 0 auto; width:24px; height:24px; border-radius:8px;
  display:grid; place-items:center; font-size:.8rem; font-weight:700; color:#08090d;
  background:linear-gradient(135deg,#8b5cf6,#22d3ee); }
.lazytts-card.run-card { background:linear-gradient(180deg,#191c2b,#111219) !important;
  border-color:#33304d !important; }

/* Header shrinks gracefully on narrow windows */
@media (max-width: 560px) {
  #lazytts-header { padding-bottom:10px; }
  #lazytts-header .title { font-size:1.4rem; }
  #lazytts-header .sub { font-size:.82rem; }
  #lazytts-header .badge { width:44px; height:44px; font-size:22px; border-radius:13px; }
}
"""

HEADER_HTML = """
<div id="lazytts-header">
  <div class="badge">🎧</div>
  <div>
    <div class="title">lazyTTS</div>
    <div class="sub">eBook → Audiobook · fully offline neural TTS · Kokoro · Piper · MMS · XTTS · translate</div>
  </div>
</div>
"""


# ── Engine cache (avoid reloading models on every click) ─────────
_ENGINE_CACHE: dict[tuple, object] = {}


def get_engine(engine_name, dev):
    key = (engine_name, dev)
    if key not in _ENGINE_CACHE:
        _ENGINE_CACHE[key] = build_engine(engine_name, device=dev)
    return _ENGINE_CACHE[key]


def _effective_voice(engine_name, kokoro_voice, piper_voice, mms_voice, xtts_voice,
                     clone_wav=None, lang="en"):
    # XTTS voice cloning: encode the reference clip + language into the voice id.
    if engine_name == "xtts" and xtts_voice == "__clone__" and clone_wav:
        return f"clone::{lang}::{clone_wav}"
    return {
        "kokoro": kokoro_voice, "piper": piper_voice,
        "mms": mms_voice, "xtts": xtts_voice,
    }.get(engine_name)  # sapi -> None


def _voice_lang(engine_name, piper_voice, mms_voice, xtts_voice) -> str:
    if engine_name == "piper":
        v = str(piper_voice)
        if v.startswith("de"):
            return "de"
        if v.startswith("hu"):
            return "hu"
        return "en"
    if engine_name == "mms":
        return config.MMS_VOICE_LANG.get(mms_voice, "en")
    if engine_name == "xtts":
        return config.XTTS_VOICES.get(xtts_voice, ("en",))[0]
    return "en"  # kokoro / sapi


def _sample_for(engine_name, piper_voice, mms_voice, xtts_voice) -> str:
    lang = _voice_lang(engine_name, piper_voice, mms_voice, xtts_voice)
    return _SAMPLE_BY_LANG.get(lang, SAMPLE_TEXT)


def preview_voice(engine_name, kokoro_voice, piper_voice, mms_voice, xtts_voice,
                  xtts_clone, speed, device_label):
    dev = device_id(device_label)
    voice = _effective_voice(engine_name, kokoro_voice, piper_voice, mms_voice, xtts_voice,
                             clone_wav=xtts_clone, lang="en")
    try:
        engine = get_engine(engine_name, dev)
        os.makedirs(str(config.CACHE_DIR), exist_ok=True)
        tag = re.sub(r"[^\w\-]+", "_", str(voice or engine_name))[:40] or "voice"
        out = os.path.join(str(config.CACHE_DIR), f"_preview_{engine_name}_{tag}.wav")
        engine.synthesize_to_file(
            _sample_for(engine_name, piper_voice, mms_voice, xtts_voice), out,
            voice=voice, speed=float(speed))
        return out
    except Exception as exc:
        raise gr.Error(f"Preview failed ({type(exc).__name__}): {exc}")


# ── Settings persistence ─────────────────────────────────────────
_SETTINGS_KEYS = [
    "engine", "kokoro_voice", "piper_voice", "mms_voice", "xtts_voice",
    "device", "speed", "gap",
    "loudness", "gain", "cleanup", "trim_silence", "two_pass", "stereo",
    "out_mode", "fmt", "bitrate", "normalize", "expand",
    "text_lang", "translate_to", "epub3_profile", "epub3_audio_fmt", "epub3_layout",
]


def _save_settings(**kw) -> None:
    # Merge into existing settings so keys persisted elsewhere (e.g. clear_on_exit)
    # survive a convert-time save.
    data = settings_store.load()
    data.update({k: kw.get(k) for k in _SETTINGS_KEYS if k in kw})
    settings_store.save(data)


# ── Chapter selection helpers ────────────────────────────────────
def _chapter_labels(state) -> list[str]:
    return [f"{i + 1:02d} · {c['title']}" for i, c in enumerate(state or [])]


def _selected_chapters(state, selected_labels):
    labels = _chapter_labels(state)
    index_of = {lbl: i for i, lbl in enumerate(labels)}
    chosen = sorted(index_of[l] for l in (selected_labels or []) if l in index_of)
    if not chosen:  # nothing picked -> whole book
        chosen = list(range(len(state or [])))
    return [document.Chapter(state[i]["title"], state[i]["text"]) for i in chosen]


def load_chapters(file, normalize_flag, expand_flag, text_lang):
    empty = ([], gr.update(choices=[], value=[]), gr.update(choices=[], value=None))
    if not file:
        return (*empty, "Upload a document, then load chapters.")
    try:
        chs = document.extract_chapters(
            file, normalize=bool(normalize_flag), expand=bool(expand_flag),
            lang=config.TEXT_LANGUAGES.get(text_lang, "en"),
        )
    except Exception as exc:
        return (*empty, f"Could not read chapters: {exc}")
    state = [{"title": c.title, "text": c.text} for c in chs]
    labels = _chapter_labels(state)
    info = (f"**{len(labels)} chapter(s)** — all selected. Untick any to skip."
            f"{_estimate_text(state)}")
    return (state,
            gr.update(choices=labels, value=labels),
            gr.update(choices=labels, value=(labels[0] if labels else None)),
            info)


# ── Content sources (Gutenberg + web articles) ──────────────────
def _sources_dir() -> str:
    d = os.path.join(str(config.CACHE_DIR), "sources")
    os.makedirs(d, exist_ok=True)
    return d


def _ingest(path, normalize, expand, text_lang):
    """Load a downloaded file into the pipeline exactly like an upload would:
    fill title/author + detect chapters. Returns the 7 pipeline outputs."""
    try:
        meta = document.extract_metadata(path)
        t, a = meta.get("title", ""), meta.get("author", "")
    except Exception:
        t, a = "", ""
    state, chsel, chprev, info = load_chapters(path, bool(normalize), bool(expand), text_lang)
    return (gr.update(value=path), gr.update(value=t), gr.update(value=a),
            state, chsel, chprev, info)


def gb_search(query):
    from lazytts import sources
    try:
        res = sources.search_gutenberg(query)
    except Exception as exc:
        return gr.update(choices=[], value=None), [], f"⚠️ Search failed ({type(exc).__name__})."
    if not res:
        return gr.update(choices=[], value=None), [], "No results found."
    choices = [(f"{r['title']} — {r['author']}", i) for i, r in enumerate(res)]
    return gr.update(choices=choices, value=0), res, f"{len(res)} result(s) — pick one, then Load."


def gb_load(idx, results, normalize, expand, text_lang):
    from lazytts import sources
    if idx is None or not results:
        raise gr.Error("Search and pick a book first.")
    item = results[int(idx)]
    try:
        path = sources.download_book(item, _sources_dir())
    except Exception as exc:
        raise gr.Error(f"Download failed ({type(exc).__name__}): {exc}")
    return (*_ingest(path, normalize, expand, text_lang), f"✅ Loaded **{item['title']}**.")


def fetch_url(url, normalize, expand, text_lang):
    from lazytts import sources
    try:
        title, path = sources.fetch_article(url, _sources_dir())
    except Exception as exc:
        raise gr.Error(f"Couldn't fetch article ({type(exc).__name__}): {exc}")
    return (*_ingest(path, normalize, expand, text_lang), f"✅ Loaded **{title}**.")


def preview_chapter(chapter_label, chapters_state, engine_name, kokoro_voice,
                    piper_voice, mms_voice, xtts_voice, speed, device_label):
    if not chapters_state or not chapter_label:
        raise gr.Error("Load chapters and pick one to preview.")
    labels = _chapter_labels(chapters_state)
    if chapter_label not in labels:
        raise gr.Error("Pick a chapter to preview.")
    idx = labels.index(chapter_label)
    from lazytts import chunker
    chunks = chunker.chunk_text(chapters_state[idx]["text"], max_chars=280)
    sample = chunks[0] if chunks else chapters_state[idx]["text"][:280]

    dev = device_id(device_label)
    voice = _effective_voice(engine_name, kokoro_voice, piper_voice, mms_voice, xtts_voice)
    try:
        engine = get_engine(engine_name, dev)
        os.makedirs(str(config.CACHE_DIR), exist_ok=True)
        out = os.path.join(str(config.CACHE_DIR), f"_chprev_{idx}.wav")
        engine.synthesize_to_file(sample, out, voice=voice, speed=float(speed))
        return out
    except Exception as exc:
        raise gr.Error(f"Preview failed ({type(exc).__name__}): {exc}")


def preview_translation(translate_label, text_lang, engine_name, kokoro_voice,
                        piper_voice, mms_voice, xtts_voice, speed, device_label,
                        chapters_state):
    """Translate a short sample (first loaded chapter) and speak it, so the user
    can spot-check MT quality + voice before committing to a whole book.
    Returns (translated_text, audio_path)."""
    target = config.TRANSLATE_TARGETS.get(translate_label)
    if not target:
        raise gr.Error("Pick a 'Translate to' language first.")

    src_text = chapters_state[0]["text"] if chapters_state else SAMPLE_TEXT
    from lazytts import chunker
    chunks = chunker.chunk_text(src_text, max_chars=320)
    sample = chunks[0] if chunks else src_text[:320]

    lang_code = config.TEXT_LANGUAGES.get(text_lang, "en")
    src_code = config.NLLB_SOURCE_CODES.get(lang_code, "eng_Latn")
    dev = device_id(device_label)

    from lazytts import translate as _translate
    try:
        translated = _translate.translate_text(sample, src_code, target, device=dev)
    except Exception as exc:
        raise gr.Error(f"Translation failed ({type(exc).__name__}): {exc}")

    # Kokoro speaks English only — fall back to the hinted Piper voice if needed.
    voice = _effective_voice(engine_name, kokoro_voice, piper_voice, mms_voice, xtts_voice)
    if engine_name == "kokoro" and target != "eng_Latn":
        hint = config.TRANSLATE_VOICE_HINT.get(target)
        if hint:
            engine_name, voice = hint

    try:
        engine = get_engine(engine_name, dev)
        os.makedirs(str(config.CACHE_DIR), exist_ok=True)
        out = os.path.join(str(config.CACHE_DIR), f"_transprev_{target}.wav")
        engine.synthesize_to_file(translated, out, voice=voice, speed=float(speed))
        return (gr.update(value=translated, visible=True),
                gr.update(value=out, visible=True))
    except Exception as exc:
        raise gr.Error(f"Preview failed ({type(exc).__name__}): {exc}")


def _build_audio_filter(loudness_label, gain, cleanup=False, trim_silence=False) -> str | None:
    parts = []
    if cleanup:
        parts.append(config.CLEANUP_FILTER)          # high-pass + light denoise
    if trim_silence:
        parts.append(config.TRIM_SILENCE_FILTER)     # trim edge silence
    preset = config.LOUDNESS_PRESETS.get(loudness_label)
    if preset:
        I, TP, LRA = preset
        parts.append(f"loudnorm=I={I}:TP={TP}:LRA={LRA}")
    try:
        g = float(gain)
    except (TypeError, ValueError):
        g = 0.0
    if abs(g) > 0.01:
        parts.append(f"volume={g}dB")               # manual gain, after loudness
    return ",".join(parts) or None


# ── Estimates + niceties ─────────────────────────────────────────
def _estimate_text(state, speed=1.0) -> str:
    chars = sum(len(c.get("text", "")) for c in (state or []))
    if not chars:
        return ""
    words = chars / 5.6                       # ~5.6 chars/word incl. spaces
    minutes = words / (150.0 * max(0.5, float(speed or 1.0)))  # ~150 wpm
    return f" · ~{chars:,} chars, ≈{_fmt_eta(minutes * 60)} of audio"


def open_output_folder():
    try:
        os.makedirs(str(config.OUTPUT_DIR), exist_ok=True)
        if hasattr(os, "startfile"):
            os.startfile(str(config.OUTPUT_DIR))  # Windows
    except Exception:
        pass


# ── Cache management ─────────────────────────────────────────────
# The chunk/preview cache (config.CACHE_DIR) is regenerable — clearing it only
# loses the crash-resume speedup, never the finished audiobooks or the models.
_clear_on_exit = {"v": False}


def clear_cache() -> tuple[int, int]:
    """Delete cached chunk/preview WAVs. Returns (files_removed, bytes_freed)."""
    removed = freed = 0
    d = str(config.CACHE_DIR)
    if os.path.isdir(d):
        for root, _dirs, files in os.walk(d):
            for f in files:
                p = os.path.join(root, f)
                try:
                    freed += os.path.getsize(p)
                    os.remove(p)
                    removed += 1
                except OSError:
                    pass  # skip anything locked (e.g. a preview still playing)
    return removed, freed


def clear_cache_now():
    removed, freed = clear_cache()
    os.makedirs(str(config.CACHE_DIR), exist_ok=True)
    gr.Info(f"Cleared {removed} cached file(s) — freed {freed / 1e6:.0f} MB.")


def set_clear_on_exit(value):
    _clear_on_exit["v"] = bool(value)
    try:  # persist immediately (survives without needing a convert)
        s = settings_store.load()
        s["clear_on_exit"] = bool(value)
        settings_store.save(s)
    except Exception:
        pass


def _clear_cache_if_enabled():
    if _clear_on_exit["v"]:
        try:
            clear_cache()
        except Exception:
            pass


def _notify_done():
    try:
        import winsound
        winsound.MessageBeep()
    except Exception:
        pass


def edit_text_from_chapters(state, selected_labels):
    chs = _selected_chapters(state, selected_labels) if state else []
    return "\n\n".join(c.text for c in chs)


def save_lexicon(text):
    lexicon.save_text(text)
    gr.Info("Pronunciation lexicon saved.")


def check_updates():
    if os.environ.get("LAZYTTS_OFFLINE") == "1":
        return "Offline mode — update check skipped."
    from lazytts import updater
    try:
        info = updater.check()
    except updater.RateLimited as exc:
        return (f"⏳ {exc} Meanwhile you can "
                f"[see the releases]({updater._RELEASES_URL}) in your browser.")
    except Exception as exc:
        return f"⚠️ Couldn't check for updates ({type(exc).__name__})."
    if info.get("update_available"):
        return (f"🎉 **{info['latest']}** is available — you have v{info['current']}. "
                f"Click **⬇️ Download & install update**, or "
                f"[view the release]({info['url']}).")
    return f"✅ You're up to date (v{info['current']})."


def _downloads_dir() -> str:
    d = Path.home() / "Downloads"
    return str(d if d.is_dir() else config.BASE_DIR)


def download_and_install_update(progress=gr.Progress(track_tqdm=True)):
    """Download the latest release installer inside the app and launch it."""
    if os.environ.get("LAZYTTS_OFFLINE") == "1":
        return "Offline mode — update download is disabled."
    try:
        from lazytts import updater
        info = updater.check()
    except Exception as exc:
        return f"⚠️ Couldn't reach the update server ({type(exc).__name__})."
    if not info.get("update_available"):
        return f"✅ Already up to date (v{info['current']})."
    if not info.get("asset_url"):
        return (f"No installer attached to **{info['latest']}** — "
                f"[open the release page]({info['url']}) to download manually.")
    dest = os.path.join(_downloads_dir(), info["asset_name"])
    try:
        updater.download_asset(info["asset_url"], dest)
    except Exception as exc:
        return f"⚠️ Download failed ({type(exc).__name__}: {exc}). [Release page]({info['url']})"
    launched = False
    try:
        if hasattr(os, "startfile"):
            os.startfile(dest)  # opens the installer wizard
            launched = True
    except Exception:
        pass
    if not launched:
        return (f"⬇️ Downloaded **{info['asset_name']}** — run it from:\n"
                f"`{dest}`")

    # The installer replaces files under {app}, including the .venv this process
    # is running from, so lazyTTS has to be gone before it gets that far. Quit
    # ourselves rather than asking the user to: a few seconds is long enough for
    # Gradio to deliver this message and for the wizard to take focus. The
    # installer offers to relaunch lazyTTS on its final page.
    def _exit_for_installer():
        time.sleep(4)
        print("lazyTTS: quitting so the updater can replace files.", flush=True)
        _clear_cache_if_enabled()  # os._exit skips atexit, so clear here
        os._exit(0)

    threading.Thread(target=_exit_for_installer,
                     name="lazytts-update-exit", daemon=True).start()

    return (f"⬇️ Downloaded **{info['asset_name']}** — the installer is opening "
            "and lazyTTS will close itself in a few seconds. Tick "
            "**Launch lazyTTS** on the installer's last page to come back.")


# ── Model manager (built-in downloader) ──────────────────────────
# ── Send to device (LAN sharing) ─────────────────────────────────
_sync_server = lanserver.LibraryServer()


def _sync_start():
    """Start sharing and hand back status text plus a QR of the address."""
    try:
        url = _sync_server.start()
    except OSError as exc:
        return (f"Could not start sharing on port {lanserver.DEFAULT_PORT}: "
                f"{exc}"), gr.update(visible=False)

    png = lanserver.qr_png(url)
    if png is None:
        return (f"**Sharing at `{url}`** — enter that in lazyREADER. "
                "(Install `segno` for a scannable QR code.)"), gr.update(visible=False)

    path = os.path.join(str(config.CACHE_DIR), "sync_qr.png")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(png)
    return (f"**Sharing at `{url}`** — scan the code in lazyREADER, "
            "or type the address in."), gr.update(value=path, visible=True)


def _sync_stop():
    _sync_server.stop()
    return "Not sharing.", gr.update(visible=False)


def _models_status_md():
    from lazytts import models
    rows = ["| Model | Size | Needed | Status |", "|---|---|---|---|"]
    for m in models.status():
        state = "✅ downloaded" if m["present"] else "⬇️ not downloaded"
        need = "required" if m["essential"] else "optional"
        rows.append(f"| {m['label']} | {m['size']} | {need} | {state} |")
    return "\n".join(rows)


def _model_choices():
    from lazytts import models
    return [(f"{m['label']} ({m['size']})"
             + ("" if m["essential"] else " — optional"), m["id"])
            for m in models.status()]


def _default_model_ids():
    """Models to pre-tick: only what's essential and still missing."""
    from lazytts import models
    return models.recommended_missing()


def download_models(selected_ids, device_label, progress=gr.Progress(track_tqdm=True)):
    """Download the selected model groups — only missing files are fetched.
    `track_tqdm` surfaces Hugging Face's per-file download bars as a live
    progress bar in the UI."""
    from lazytts import models
    if os.environ.get("LAZYTTS_OFFLINE") == "1":
        yield "Offline mode — model downloads are disabled.", _models_status_md()
        return
    if not selected_ids:
        yield "Nothing selected — tick the models you want, then Download.", _models_status_md()
        return
    dev = device_id(device_label)
    log: list[str] = []
    total = len(selected_ids)
    for i, gid in enumerate(selected_ids, 1):
        label = models.label_of(gid)
        progress((i - 1, total), desc=f"Downloading {label} ({i}/{total})")
        log.append(f"⬇️ [{i}/{total}] {label}: downloading (only missing files)…")
        yield "\n".join(log), _models_status_md()
        try:
            models.download(gid, dev)
            log[-1] = f"✅ [{i}/{total}] {label}: ready"
        except Exception as exc:
            log[-1] = f"⚠️ [{i}/{total}] {label}: {type(exc).__name__}: {exc}"
        yield "\n".join(log), _models_status_md()
    progress((total, total), desc="Done")
    log.append(f"Done — {total} group(s) processed.")
    yield "\n".join(log), _models_status_md()


def convert_action(
    file, engine_name, kokoro_voice, piper_voice, mms_voice, xtts_voice, xtts_clone, speed, device_label,
    out_fmt, bitrate, gap, loudness_label, gain, cleanup_flag, trim_flag, two_pass_flag, stereo_flag,
    output_mode, epub3_profile, epub3_audio_label, epub3_layout_label,
    normalize_flag, expand_flag, text_lang, translate_label,
    title, author, cover,
    chapters_state, selected_labels, edited_text, use_edited, lexicon_text,
):
    """Generator wired to the Convert button; yields (status, audio, download)."""
    if file is None:
        raise gr.Error("Please upload a .txt, .pdf, .epub, or .docx file first.")
    ext = Path(file).suffix.lower()
    if ext not in config.SUPPORTED_EXTENSIONS:
        raise gr.Error(f"Unsupported file type '{ext}'.")

    # Translation target (NLLB code or None) + guard against a voiceless pairing.
    translate_to = config.TRANSLATE_TARGETS.get(translate_label)
    if translate_to and engine_name == "kokoro" and translate_to != "eng_Latn":
        hint = config.TRANSLATE_VOICE_HINT.get(translate_to)
        voice_lbl = config.PIPER_VOICE_LABELS.get(hint[1], hint[1]) if hint else "a Piper voice"
        raise gr.Error(
            f"Kokoro only narrates English. To narrate the translation, switch the "
            f"TTS engine to Piper and pick {voice_lbl}."
        )

    dev = device_id(device_label)
    voice = _effective_voice(engine_name, kokoro_voice, piper_voice, mms_voice, xtts_voice,
                             clone_wav=xtts_clone, lang=config.TEXT_LANGUAGES.get(text_lang, "en"))
    cache_voice = voice or engine_name
    engine = get_engine(engine_name, dev)
    chunk_chars = config.CHUNK_CHARS.get(engine_name, config.MAX_CHUNK_CHARS)
    converter = Converter(engine, config.CACHE_DIR, config.OUTPUT_DIR, chunk_chars)

    _save_settings(
        engine=engine_name, kokoro_voice=kokoro_voice, piper_voice=piper_voice,
        mms_voice=mms_voice, xtts_voice=xtts_voice,
        device=device_label, speed=speed, gap=gap, loudness=loudness_label, gain=gain,
        cleanup=cleanup_flag, trim_silence=trim_flag, two_pass=two_pass_flag, stereo=stereo_flag,
        out_mode=output_mode, fmt=out_fmt, bitrate=bitrate, normalize=normalize_flag,
        expand=expand_flag, text_lang=text_lang, translate_to=translate_label,
        epub3_profile=epub3_profile, epub3_audio_fmt=epub3_audio_label,
        epub3_layout=epub3_layout_label,
    )

    mode = OUTPUT_MODES.get(output_mode, "single")
    metadata = {"title": (title or "").strip() or Path(file).stem,
                "author": (author or "").strip()}
    cover_path = str(cover) if cover else None
    audio_filter = _build_audio_filter(loudness_label, gain, cleanup_flag, trim_flag)
    channels = 2 if stereo_flag else 1
    lang_code = config.TEXT_LANGUAGES.get(text_lang, "en")
    translate_src = config.NLLB_SOURCE_CODES.get(lang_code, "eng_Latn")
    if use_edited and (edited_text or "").strip():
        chapters = [document.Chapter(metadata["title"], edited_text)]
    else:
        chapters = _selected_chapters(chapters_state, selected_labels) if chapters_state else None

    yield "Reading document…", None, None
    final = None
    start = time.monotonic()
    try:
        for ev in converter.convert(
            file, voice=cache_voice, speed=float(speed),
            out_fmt=out_fmt, bitrate=bitrate, gap=float(gap),
            output_mode=mode, normalize=bool(normalize_flag), expand=bool(expand_flag),
            lang=lang_code, metadata=metadata, cover=cover_path,
            audio_filter=audio_filter, chapters=chapters,
            translate_to=translate_to, translate_src=translate_src, translate_device=dev,
            channels=channels, two_pass=bool(two_pass_flag), lexicon=lexicon_text,
            epub3_profile=epub3_profile,
            epub3_audio_fmt=config.EPUB3_AUDIO_FORMATS.get(epub3_audio_label),
            epub3_layout=config.EPUB3_AUDIO_LAYOUTS.get(
                epub3_layout_label, "per_chapter"),
        ):
            pct = int(ev.fraction * 100)
            extra = ""
            elapsed = time.monotonic() - start
            if ev.stage in ("synth", "translating") and ev.fraction > 0 and elapsed > 1:
                unit = "chunks" if ev.stage == "synth" else "segments"
                rate = ev.done / elapsed * 60
                eta = elapsed / ev.fraction - elapsed
                extra = f" • {rate:.1f} {unit}/min • ETA {_fmt_eta(eta)}"
            yield f"[{pct:3d}%] {ev.message}{extra}", None, None
            final = ev
    except Exception as exc:
        raise gr.Error(f"{type(exc).__name__}: {exc}")

    out = final.output if final else None
    # The player only accepts an audio file. m4b isn't previewable, and the EPUB
    # read-along keeps its audio *inside* the .epub — handing either to gr.Audio
    # would just break the component.
    preview = (final.preview if final else None) or (
        out if mode not in ("m4b", "epub3") else None)
    _notify_done()
    yield f"✅ {final.message if final else 'Finished'}", preview, out


def batch_convert(
    files, engine_name, kokoro_voice, piper_voice, mms_voice, xtts_voice, xtts_clone, speed, device_label,
    out_fmt, bitrate, gap, loudness_label, gain, cleanup_flag, trim_flag, two_pass_flag, stereo_flag,
    output_mode, epub3_profile, epub3_audio_label, epub3_layout_label,
    normalize_flag, expand_flag, text_lang, translate_label,
    lexicon_text,
):
    """Convert several whole books in sequence with the current settings."""
    if not files:
        raise gr.Error("Add one or more documents to the batch first.")
    dev = device_id(device_label)
    voice = _effective_voice(engine_name, kokoro_voice, piper_voice, mms_voice, xtts_voice,
                             clone_wav=xtts_clone, lang=config.TEXT_LANGUAGES.get(text_lang, "en"))
    cache_voice = voice or engine_name
    engine = get_engine(engine_name, dev)
    chunk_chars = config.CHUNK_CHARS.get(engine_name, config.MAX_CHUNK_CHARS)
    converter = Converter(engine, config.CACHE_DIR, config.OUTPUT_DIR, chunk_chars)

    mode = OUTPUT_MODES.get(output_mode, "single")
    audio_filter = _build_audio_filter(loudness_label, gain, cleanup_flag, trim_flag)
    channels = 2 if stereo_flag else 1
    lang_code = config.TEXT_LANGUAGES.get(text_lang, "en")
    translate_to = config.TRANSLATE_TARGETS.get(translate_label)
    translate_src = config.NLLB_SOURCE_CODES.get(lang_code, "eng_Latn")
    if translate_to and engine_name == "kokoro" and translate_to != "eng_Latn":
        raise gr.Error("Kokoro only narrates English — pick Piper/MMS/XTTS for a translated batch.")

    outputs: list[str] = []
    lines: list[str] = []
    n = len(files)
    for idx, f in enumerate(files, 1):
        name = Path(f).stem
        if Path(f).suffix.lower() not in config.SUPPORTED_EXTENSIONS:
            lines.append(f"[{idx}/{n}] {name}: skipped (unsupported type)")
            yield "\n".join(lines), outputs
            continue
        lines.append(f"[{idx}/{n}] {name}: starting…")
        yield "\n".join(lines), outputs
        final = None
        try:
            for ev in converter.convert(
                f, voice=cache_voice, speed=float(speed), out_fmt=out_fmt, bitrate=bitrate,
                gap=float(gap), output_mode=mode, normalize=bool(normalize_flag),
                expand=bool(expand_flag), lang=lang_code, metadata={"title": name, "author": ""},
                cover=None, audio_filter=audio_filter, chapters=None, translate_to=translate_to,
                translate_src=translate_src, translate_device=dev, channels=channels,
                two_pass=bool(two_pass_flag), lexicon=lexicon_text,
                epub3_profile=epub3_profile,
                epub3_audio_fmt=config.EPUB3_AUDIO_FORMATS.get(epub3_audio_label),
                epub3_layout=config.EPUB3_AUDIO_LAYOUTS.get(
                    epub3_layout_label, "per_chapter"),
            ):
                final = ev
                lines[-1] = f"[{idx}/{n}] {name}: [{int(ev.fraction * 100):3d}%] {ev.message}"
                yield "\n".join(lines), outputs
        except Exception as exc:
            lines[-1] = f"[{idx}/{n}] {name}: ERROR {type(exc).__name__}: {exc}"
            yield "\n".join(lines), outputs
            continue
        if final and final.output:
            outputs.append(final.output)
        lines[-1] = f"[{idx}/{n}] {name}: ✅ done"
        yield "\n".join(lines), outputs

    _notify_done()
    lines.append(f"Batch complete — {len(outputs)} file(s) in {config.OUTPUT_DIR}.")
    yield "\n".join(lines), outputs


# ── Auto-shutdown: quit the server (and its console) when the last tab closes ──
# A browser refresh briefly drops to zero sessions, so we wait out a short grace
# period before exiting; a reconnect within that window cancels the shutdown.
# Set LAZYTTS_KEEP_ALIVE=1 to disable (e.g. while developing).
_session_lock = threading.Lock()
_session_count = {"n": 0}
_pending_timer: dict = {"t": None}
_SHUTDOWN_GRACE = 6.0


def _cancel_pending_shutdown():
    t = _pending_timer["t"]
    if t is not None:
        t.cancel()
        _pending_timer["t"] = None


def _on_session_start():
    with _session_lock:
        _session_count["n"] += 1
        _cancel_pending_shutdown()


def _maybe_shutdown():
    with _session_lock:
        if _session_count["n"] <= 0:
            print("lazyTTS: browser window closed — shutting down server.", flush=True)
            _clear_cache_if_enabled()  # os._exit skips atexit, so clear here
            os._exit(0)


def _on_session_end():
    with _session_lock:
        _session_count["n"] = max(0, _session_count["n"] - 1)
        if _session_count["n"] <= 0:
            _cancel_pending_shutdown()
            timer = threading.Timer(_SHUTDOWN_GRACE, _maybe_shutdown)
            timer.daemon = True
            _pending_timer["t"] = timer
            timer.start()


def _wire_auto_shutdown(demo: gr.Blocks) -> None:
    if os.environ.get("LAZYTTS_KEEP_ALIVE"):
        return
    # demo.unload requires Gradio ≥4.36; degrade gracefully if unavailable.
    try:
        demo.load(_on_session_start)
        demo.unload(_on_session_end)
    except Exception as exc:  # pragma: no cover
        print(f"lazyTTS: auto-shutdown not enabled ({exc}).", flush=True)


def build_ui() -> gr.Blocks:
    engines = available_engines()
    default_engine = engines[0]
    devices = list_cuda_devices()

    S = settings_store.load()

    def sv(key, default):
        v = S.get(key)
        return default if v is None else v

    def sv_in(key, choices, default):
        v = S.get(key)
        return v if v in choices else default

    clear_exit_val = bool(sv("clear_on_exit", True))
    _clear_on_exit["v"] = clear_exit_val

    eng_val = sv_in("engine", engines, default_engine)
    kokoro_voice_val = sv_in("kokoro_voice", list(config.KOKORO_VOICES.keys()), config.DEFAULT_VOICE)
    piper_voice_val = sv_in("piper_voice", list(config.PIPER_VOICES.keys()), config.DEFAULT_PIPER_VOICE)
    mms_voice_val = sv_in("mms_voice", list(config.MMS_VOICES.keys()), config.DEFAULT_MMS_VOICE)
    xtts_voice_val = sv_in("xtts_voice", list(config.XTTS_VOICES.keys()), config.DEFAULT_XTTS_VOICE)
    dev_val = sv_in("device", devices, devices[0])
    mode_val = sv_in("out_mode", list(OUTPUT_MODES.keys()), "Single file")
    fmt_val = sv_in("fmt", config.OUTPUT_FORMATS, config.DEFAULT_FORMAT)
    br_val = sv_in("bitrate", config.MP3_BITRATES, config.DEFAULT_BITRATE)
    loud_val = sv_in("loudness", list(config.LOUDNESS_PRESETS.keys()), config.DEFAULT_LOUDNESS_PRESET)
    tlang_val = sv_in("text_lang", list(config.TEXT_LANGUAGES.keys()), config.DEFAULT_TEXT_LANGUAGE)
    translate_val = sv_in("translate_to", list(config.TRANSLATE_TARGETS.keys()), config.DEFAULT_TRANSLATE_TARGET)

    with gr.Blocks(title=config.APP_NAME, fill_width=True) as demo:
        gr.HTML(HEADER_HTML)
        chapters_state = gr.State([])

        with gr.Row(equal_height=False, elem_id="lazytts-grid"):
            # ── Column 1: source, voice & chapters ───────────────
            with gr.Column(scale=3, min_width=300, elem_classes=["lazytts-card"]):
                gr.HTML('<div class="sect"><span class="n">1</span>Source &amp; voice</div>')
                file_in = gr.File(label="Document",
                                  file_types=config.SUPPORTED_EXTENSIONS, type="filepath")

                with gr.Accordion("📚 Get a book / article (free & legal)", open=False):
                    gb_results_state = gr.State([])
                    with gr.Tab("Project Gutenberg"):
                        gb_query = gr.Textbox(label="Search public-domain books",
                                              placeholder="title or author, e.g. Sherlock Holmes")
                        gb_search_btn = gr.Button("🔎 Search", size="sm")
                        gb_results = gr.Dropdown([], label="Results")
                        gb_load_btn = gr.Button("⬇️ Load selected book", variant="primary", size="sm")
                    with gr.Tab("Web article"):
                        url_in = gr.Textbox(label="Article URL", placeholder="https://…")
                        url_fetch_btn = gr.Button("📄 Fetch & load", variant="primary", size="sm")
                    source_status = gr.Markdown("")

                engine_dd = gr.Dropdown(
                    engines, value=eng_val, label="TTS engine",
                    info=("kokoro = English (fast) · piper = German/Hungarian & more · "
                          "mms = multilingual (VITS) · xtts = multilingual, high-quality but slow · "
                          "sapi = fallback"),
                )
                with gr.Group(visible=eng_val == "kokoro") as kokoro_group:
                    kokoro_voice_dd = gr.Dropdown(
                        choices=[(v, k) for k, v in config.KOKORO_VOICES.items()],
                        value=kokoro_voice_val, label="Voice (Kokoro · English)",
                    )
                with gr.Group(visible=eng_val == "piper") as piper_group:
                    piper_voice_dd = gr.Dropdown(
                        choices=[(config.PIPER_VOICE_LABELS.get(k, k), k) for k in config.PIPER_VOICES],
                        value=piper_voice_val, label="Voice (Piper · German/Hungarian & more)",
                    )
                with gr.Group(visible=eng_val == "mms") as mms_group:
                    mms_voice_dd = gr.Dropdown(
                        choices=[(config.MMS_VOICE_LABELS.get(k, k), k) for k in config.MMS_VOICES],
                        value=mms_voice_val, label="Voice (MMS · EN/DE/HU)",
                        info="Meta MMS-TTS · non-commercial license.",
                    )
                with gr.Group(visible=eng_val == "xtts") as xtts_group:
                    xtts_voice_dd = gr.Dropdown(
                        choices=[(config.XTTS_VOICE_LABELS.get(k, k), k) for k in config.XTTS_VOICES]
                                + [("🎙 Clone from a sample", "__clone__")],
                        value=xtts_voice_val, label="Voice (XTTS-v2 · EN/DE/HU)",
                        info="Coqui XTTS · highest quality but slow · non-commercial license.",
                    )
                    xtts_clone_audio = gr.Audio(
                        label="Reference voice for cloning (10–30 s clip)", type="filepath",
                        visible=(xtts_voice_val == "__clone__"))

                preview_btn = gr.Button("🔊 Preview voice", size="sm")
                preview_audio = gr.Audio(label="Voice preview", type="filepath", autoplay=True)

                gr.Markdown("#### Chapters")
                load_btn = gr.Button("📖 Load / refresh chapters", size="sm")
                chapters_info = gr.Markdown("Upload a document, then load chapters.")
                chapter_select = gr.CheckboxGroup([], label="Export these chapters")
                with gr.Row():
                    select_all_btn = gr.Button("☑ Select all", size="sm", variant="secondary")
                    select_none_btn = gr.Button("☐ Deselect all", size="sm", variant="secondary")
                with gr.Row():
                    chapter_preview_dd = gr.Dropdown([], label="Preview chapter", scale=3)
                    preview_chapter_btn = gr.Button("🔊", scale=1, min_width=48)
                chapter_preview_audio = gr.Audio(label="Chapter preview", type="filepath", autoplay=True)

                with gr.Accordion("📝 Preview / edit text", open=False):
                    edit_load_btn = gr.Button("Load selected chapters into editor", size="sm")
                    edit_text = gr.Textbox(label="Editable text", lines=8,
                                           info="Fix OCR errors, remove front matter, etc.")
                    use_edited_cb = gr.Checkbox(value=False,
                                                label="Use edited text (as a single chapter)")

            # ── Column 2: settings & output ──────────────────────
            with gr.Column(scale=3, min_width=300, elem_classes=["lazytts-card"]):
                gr.HTML('<div class="sect"><span class="n">2</span>Settings</div>')
                device_dd = gr.Dropdown(devices, value=dev_val, label="Device",
                                        info="Pick which GPU to run on (Kokoro).")
                with gr.Row():
                    speed_sl = gr.Slider(config.SPEED_MIN, config.SPEED_MAX,
                                         value=sv("speed", config.SPEED_DEFAULT),
                                         step=0.05, label="Speed")
                    gap_sl = gr.Slider(0.0, 1.5, value=sv("gap", config.CHUNK_GAP_SECONDS),
                                       step=0.05, label="Gap (s)")
                with gr.Row():
                    loudness_dd = gr.Dropdown(list(config.LOUDNESS_PRESETS.keys()), value=loud_val,
                                              label="Loudness preset",
                                              info="Even, consistent volume (ACX = audiobook spec).")
                    gain_sl = gr.Slider(config.GAIN_MIN, config.GAIN_MAX,
                                        value=sv("gain", config.GAIN_DEFAULT),
                                        step=0.5, label="Extra gain (dB)")
                with gr.Row():
                    two_pass_cb = gr.Checkbox(value=sv("two_pass", False), label="2-pass loudness",
                                              info="Slower, more accurate normalization.")
                    stereo_cb = gr.Checkbox(value=sv("stereo", False), label="Stereo",
                                            info="Duplicate mono voice to 2 channels.")
                with gr.Row():
                    cleanup_cb = gr.Checkbox(value=sv("cleanup", False), label="Voice cleanup",
                                             info="High-pass + light denoise.")
                    trim_cb = gr.Checkbox(value=sv("trim_silence", False), label="Trim silence",
                                          info="Remove dead air at start/end.")
                with gr.Row():
                    normalize_cb = gr.Checkbox(value=sv("normalize", True), label="Clean text",
                                               info="De-hyphenate, drop page numbers.")
                    expand_cb = gr.Checkbox(value=sv("expand", True), label="Expand numbers/abbr.",
                                            info="1996 → nineteen ninety-six.")
                text_lang_dd = gr.Dropdown(list(config.TEXT_LANGUAGES.keys()), value=tlang_val,
                                           label="Text/source language (numbers/abbr.)")
                translate_dd = gr.Dropdown(
                    list(config.TRANSLATE_TARGETS.keys()), value=translate_val,
                    label="Translate to (offline · NLLB-200)",
                    info="Translates the book before narration. Picks a matching voice.",
                )
                preview_trans_btn = gr.Button("🔊 Preview translation", size="sm")
                trans_preview_text = gr.Textbox(label="Translated sample", lines=3,
                                                interactive=False, visible=False)
                trans_preview_audio = gr.Audio(label="Translation preview",
                                               type="filepath", autoplay=True, visible=False)
                output_mode = gr.Radio(list(OUTPUT_MODES.keys()), value=mode_val, label="Output",
                                       info="Split = files + .m3u · M4B = one file w/ chapters · "
                                            "EPUB 3 = ebook that highlights each sentence as it's read.")
                epub3_profile_dd = gr.Dropdown(
                    list(config.EPUB3_PROFILES.keys()),
                    value=sv_in("epub3_profile", list(config.EPUB3_PROFILES.keys()),
                                config.DEFAULT_EPUB3_PROFILE),
                    label="Read-along target reader",
                    info="Which app you'll read it in. Universal works everywhere; "
                         "the others tune audio format and SMIL structure.",
                    visible=OUTPUT_MODES.get(mode_val) == "epub3")
                with gr.Row(visible=OUTPUT_MODES.get(mode_val) == "epub3") as epub3_audio_row:
                    epub3_audio_dd = gr.Dropdown(
                        list(config.EPUB3_AUDIO_FORMATS.keys()),
                        value=sv_in("epub3_audio_fmt",
                                    list(config.EPUB3_AUDIO_FORMATS.keys()),
                                    config.DEFAULT_EPUB3_AUDIO_FORMAT),
                        label="Read-along audio",
                        info="The Format dropdown doesn't apply here — this audio "
                             "lives inside the .epub.")
                    epub3_layout_dd = gr.Dropdown(
                        list(config.EPUB3_AUDIO_LAYOUTS.keys()),
                        value=sv_in("epub3_layout",
                                    list(config.EPUB3_AUDIO_LAYOUTS.keys()),
                                    config.DEFAULT_EPUB3_AUDIO_LAYOUT),
                        label="Narration files",
                        info="Per chapter keeps clip offsets small and seeks "
                             "more accurately than one long track.")
                with gr.Row():
                    fmt_dd = gr.Dropdown(config.OUTPUT_FORMATS, value=fmt_val, label="Format")
                    bitrate_dd = gr.Dropdown(config.MP3_BITRATES, value=br_val, label="Bitrate",
                                             visible=fmt_val in config.LOSSY_FORMATS)

            # ── Column 3: metadata & cover (open) ────────────────
            with gr.Column(scale=3, min_width=300, elem_classes=["lazytts-card"]):
                gr.HTML('<div class="sect"><span class="n">3</span>Metadata &amp; cover</div>')
                title_tb = gr.Textbox(label="Title", placeholder="(defaults to file name)")
                author_tb = gr.Textbox(label="Author")
                cover_img = gr.Image(label="Cover art (optional)", type="filepath")

                with gr.Accordion("🗣 Pronunciation lexicon", open=False):
                    lexicon_tb = gr.Textbox(
                        value=lexicon.load_text(), lines=6,
                        label="Replacements — one per line: from => to",
                        placeholder="Qwen => Kwen\nGPU => gee pee you\nSiobhan => Shivawn",
                    )
                    lexicon_save_btn = gr.Button("Save lexicon", size="sm")

            # ── Column 4: run + result ───────────────────────────
            with gr.Column(scale=3, min_width=300, elem_classes=["lazytts-card", "run-card"]):
                gr.HTML('<div class="sect"><span class="n">4</span>Convert</div>')
                convert_btn = gr.Button("Convert to audiobook", variant="primary",
                                        elem_id="convert-btn")
                stop_btn = gr.Button("⏹ Stop", variant="stop", elem_id="stop-btn")
                status = gr.Textbox(label="Status", lines=4, interactive=False)
                player = gr.Audio(label="Result", type="filepath")
                download = gr.File(label="Download audiobook")
                with gr.Row():
                    open_folder_btn = gr.Button("📂 Open output folder", size="sm")
                    clear_cache_btn = gr.Button("🧹 Clear cache", size="sm")
                clear_exit_cb = gr.Checkbox(value=clear_exit_val, label="Clear cache on exit",
                                            info="Delete the chunk cache when the app closes "
                                                 "(finished audiobooks are kept).")

                with gr.Accordion("📚 Batch — convert multiple books", open=False):
                    gr.Markdown("Converts each **whole book** with the current settings above.")
                    batch_files = gr.File(label="Books", file_count="multiple",
                                          file_types=config.SUPPORTED_EXTENSIONS, type="filepath")
                    batch_btn = gr.Button("Convert all", variant="primary", size="sm")
                    batch_status = gr.Textbox(label="Batch status", lines=5, interactive=False)
                    batch_out = gr.File(label="Batch results", file_count="multiple")

        # ── Models: built-in downloader (fetches only what's missing) ────
        # Only the essential group is pre-ticked, and the panel stays closed:
        # pre-selecting everything missing would mean ~5 GB before a first-time
        # user can convert one English book. The rest are one click away.
        from lazytts import models as _models
        _default_dl = _default_model_ids()
        _optional_missing = [g for g in _models.missing() if g not in _default_dl]
        _panel_intro = ("Download models on demand — **only missing files are fetched** "
                        "(anything already downloaded is skipped). Needs internet; "
                        "disabled in offline mode.\n\n"
                        "**Kokoro** is all you need for English. The others are optional: "
                        "Piper/MMS/XTTS add more languages and voice cloning, NLLB adds "
                        "offline translation. Tick whichever you want.")
        if _optional_missing:
            _panel_intro += (f"\n\n{len(_optional_missing)} optional group(s) "
                             "not downloaded — nothing is fetched until you tick it.")
        if _default_dl:
            _panel_intro = ("⚠️ **Kokoro isn't downloaded yet** — it's pre-selected below; "
                            "click **Download selected** to fetch just that "
                            "(~0.3 GB, progress shows above the button).\n\n") + _panel_intro
        with gr.Accordion("📥 Models — status & download", open=False):
            gr.Markdown(_panel_intro)
            models_status_md = gr.Markdown(_models_status_md())
            models_group = gr.CheckboxGroup(choices=_model_choices(), value=_default_dl,
                                            label="Select models to download")
            with gr.Row():
                dl_models_btn = gr.Button("📥 Download selected", variant="primary", size="sm")
                refresh_models_btn = gr.Button("🔄 Refresh status", size="sm")
            models_log = gr.Textbox(label="Download progress", lines=4, interactive=False)

        with gr.Accordion("📲 Send to device (same Wi-Fi)", open=False):
            gr.Markdown(
                "Share finished **read-along .epub** files with the lazyREADER "
                "Android app over your local network. Scan the QR code in the "
                "app's *Sync* screen, or type the address in by hand.\n\n"
                "Read-only, and only while switched on: it serves the `.epub` "
                "files in your output folder and nothing else."
            )
            with gr.Row():
                sync_start_btn = gr.Button("▶ Start sharing", variant="primary", size="sm")
                sync_stop_btn = gr.Button("⏹ Stop", size="sm")
            sync_status_md = gr.Markdown("Not sharing.")
            sync_qr_img = gr.Image(label="Scan in lazyREADER", type="filepath",
                                   visible=False, height=240)

        # ── Footer: version + update check ───────────────────────
        with gr.Row():
            gr.Markdown(f"**lazyTTS** v{config.APP_VERSION} · fully offline")
            update_btn = gr.Button("🔄 Check for updates", size="sm", scale=0)
            get_update_btn = gr.Button("⬇️ Download & install update", size="sm", scale=0)
        update_info = gr.Markdown("")

        # ── Wiring ──
        _voice_groups = [kokoro_group, piper_group, mms_group, xtts_group]

        def _group_visibility(name):
            return tuple(gr.update(visible=name == g) for g in ("kokoro", "piper", "mms", "xtts"))

        engine_dd.change(_group_visibility, inputs=engine_dd, outputs=_voice_groups)
        fmt_dd.change(lambda f: gr.update(visible=(f in config.LOSSY_FORMATS)),
                      inputs=fmt_dd, outputs=bitrate_dd)

        def on_translate_change(label):
            """When a target language is picked, auto-route to a voice that speaks it."""
            noop = (gr.update(), *(gr.update() for _ in _voice_groups), gr.update())
            code = config.TRANSLATE_TARGETS.get(label)
            hint = config.TRANSLATE_VOICE_HINT.get(code) if code else None
            if not hint:
                return noop
            eng, voice = hint
            if eng not in engines:  # engine not installed -> leave the user's choice
                return noop
            return (gr.update(value=eng), *_group_visibility(eng), gr.update(value=voice))

        translate_dd.change(
            on_translate_change, inputs=translate_dd,
            outputs=[engine_dd, *_voice_groups, piper_voice_dd],
        )

        preview_trans_btn.click(
            preview_translation,
            inputs=[translate_dd, text_lang_dd, engine_dd, kokoro_voice_dd,
                    piper_voice_dd, mms_voice_dd, xtts_voice_dd, speed_sl, device_dd, chapters_state],
            outputs=[trans_preview_text, trans_preview_audio],
        )

        def on_file(path):
            if not path:
                return gr.update(), gr.update()
            try:
                meta = document.extract_metadata(path)
                return gr.update(value=meta.get("title", "")), gr.update(value=meta.get("author", ""))
            except Exception:
                return gr.update(), gr.update()

        file_in.change(on_file, inputs=file_in, outputs=[title_tb, author_tb])

        _chap_out = [chapters_state, chapter_select, chapter_preview_dd, chapters_info]
        file_in.change(load_chapters, inputs=[file_in, normalize_cb, expand_cb, text_lang_dd], outputs=_chap_out)
        load_btn.click(load_chapters, inputs=[file_in, normalize_cb, expand_cb, text_lang_dd], outputs=_chap_out)

        # Labels are rebuilt from state rather than read back off the widget, so
        # "select all" still works if the choices were refreshed in between.
        sync_start_btn.click(_sync_start, outputs=[sync_status_md, sync_qr_img])
        sync_stop_btn.click(_sync_stop, outputs=[sync_status_md, sync_qr_img])

        select_all_btn.click(
            lambda state: gr.update(value=_chapter_labels(state or [])),
            inputs=chapters_state, outputs=chapter_select)
        select_none_btn.click(
            lambda: gr.update(value=[]), outputs=chapter_select)

        preview_btn.click(
            preview_voice,
            inputs=[engine_dd, kokoro_voice_dd, piper_voice_dd, mms_voice_dd, xtts_voice_dd,
                    xtts_clone_audio, speed_sl, device_dd],
            outputs=preview_audio,
        )
        xtts_voice_dd.change(lambda v: gr.update(visible=v == "__clone__"),
                             inputs=xtts_voice_dd, outputs=xtts_clone_audio)

        # Content sources → load a book/article into the pipeline
        _ingest_out = [file_in, title_tb, author_tb, chapters_state, chapter_select,
                       chapter_preview_dd, chapters_info, source_status]
        gb_search_btn.click(gb_search, inputs=gb_query,
                            outputs=[gb_results, gb_results_state, source_status])
        gb_load_btn.click(gb_load, inputs=[gb_results, gb_results_state, normalize_cb, expand_cb, text_lang_dd],
                          outputs=_ingest_out)
        url_fetch_btn.click(fetch_url, inputs=[url_in, normalize_cb, expand_cb, text_lang_dd],
                            outputs=_ingest_out)
        preview_chapter_btn.click(
            preview_chapter,
            inputs=[chapter_preview_dd, chapters_state, engine_dd, kokoro_voice_dd,
                    piper_voice_dd, mms_voice_dd, xtts_voice_dd, speed_sl, device_dd],
            outputs=chapter_preview_audio,
        )

        edit_load_btn.click(edit_text_from_chapters,
                            inputs=[chapters_state, chapter_select], outputs=edit_text)
        lexicon_save_btn.click(save_lexicon, inputs=lexicon_tb, outputs=None)
        open_folder_btn.click(lambda: open_output_folder(), inputs=None, outputs=None)
        clear_cache_btn.click(lambda: clear_cache_now(), inputs=None, outputs=None)
        clear_exit_cb.change(set_clear_on_exit, inputs=clear_exit_cb, outputs=None)
        update_btn.click(check_updates, inputs=None, outputs=update_info)
        get_update_btn.click(download_and_install_update, inputs=None, outputs=update_info)

        dl_models_btn.click(download_models, inputs=[models_group, device_dd],
                            outputs=[models_log, models_status_md])
        refresh_models_btn.click(
            lambda: (_models_status_md(),
                     gr.update(choices=_model_choices(), value=_default_model_ids())),
            inputs=None, outputs=[models_status_md, models_group])

        _core_settings = [
            engine_dd, kokoro_voice_dd, piper_voice_dd, mms_voice_dd, xtts_voice_dd, xtts_clone_audio,
            speed_sl, device_dd,
            fmt_dd, bitrate_dd, gap_sl, loudness_dd, gain_sl,
            cleanup_cb, trim_cb, two_pass_cb, stereo_cb,
            output_mode, epub3_profile_dd, epub3_audio_dd, epub3_layout_dd,
            normalize_cb, expand_cb, text_lang_dd, translate_dd,
        ]

        # The read-along controls only matter for the EPUB 3 mode.
        output_mode.change(
            lambda m: (gr.update(visible=OUTPUT_MODES.get(m) == "epub3"),
                       gr.update(visible=OUTPUT_MODES.get(m) == "epub3")),
            inputs=output_mode, outputs=[epub3_profile_dd, epub3_audio_row])

        run_event = convert_btn.click(
            convert_action,
            inputs=[
                file_in, *_core_settings,
                title_tb, author_tb, cover_img,
                chapters_state, chapter_select, edit_text, use_edited_cb, lexicon_tb,
            ],
            outputs=[status, player, download],
        )
        stop_btn.click(fn=None, inputs=None, outputs=None, cancels=[run_event])

        batch_event = batch_btn.click(
            batch_convert,
            inputs=[batch_files, *_core_settings, lexicon_tb],
            outputs=[batch_status, batch_out],
        )

        _wire_auto_shutdown(demo)

    return demo


def _launch(demo, *, inbrowser: bool, block: bool):
    """Launch the Gradio server; return (local_url) when non-blocking."""
    theme = gr.themes.Base(primary_hue="violet", secondary_hue="cyan", neutral_hue="slate")
    launch_kwargs = dict(server_name="127.0.0.1", inbrowser=inbrowser,
                         theme=theme, css=THEME_CSS, prevent_thread_lock=not block)
    try:
        res = demo.launch(**launch_kwargs)
    except TypeError:
        for k in ("theme", "css"):
            launch_kwargs.pop(k, None)
        res = demo.launch(**launch_kwargs)
    # When non-blocking, launch() returns (app, local_url, share_url).
    if not block and isinstance(res, tuple) and len(res) >= 2:
        return res[1]
    return None


def _run_windowed(demo) -> bool:
    """Open the app in a native desktop window (no browser) via pywebview.
    Returns False if pywebview/WebView2 is unavailable so we can fall back."""
    try:
        import webview  # pywebview
    except Exception as exc:
        print(f"lazyTTS: pywebview unavailable ({exc}); opening in browser instead.", flush=True)
        return False
    try:
        url = _launch(demo, inbrowser=False, block=False)
        if not url:
            return False
        webview.create_window(config.APP_NAME, url, width=1440, height=920,
                              min_size=(900, 640))
        # Blocks until the window is closed.
        webview.start()
        # Force the whole process (incl. Gradio's server thread) to exit so the
        # launching console/cmd window closes too — a plain return can hang on
        # the non-daemon server thread.
        print("lazyTTS: window closed — shutting down.", flush=True)
        _clear_cache_if_enabled()
        os._exit(0)
    except Exception as exc:
        print(f"lazyTTS: could not open desktop window ({exc}); using browser.", flush=True)
        return False


def main() -> int:
    # Headless model download (used by the installers): lazyTTS.exe --prefetch
    if "--prefetch" in sys.argv:
        import prefetch_models
        return prefetch_models.main()

    config.CACHE_DIR.mkdir(parents=True, exist_ok=True)
    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    # Clean exit (e.g. pywebview window close) runs atexit; the browser-mode
    # os._exit path clears explicitly in _maybe_shutdown.
    atexit.register(_clear_cache_if_enabled)
    demo = build_ui().queue()

    # Default: native desktop window (pywebview). Set LAZYTTS_BROWSER=1 to force the
    # old browser-tab behavior; "--browser" on the CLI does the same.
    want_browser = os.environ.get("LAZYTTS_BROWSER") == "1" or "--browser" in sys.argv
    if not want_browser and _run_windowed(demo):
        return 0  # window opened and has since been closed

    _launch(demo, inbrowser=True, block=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
