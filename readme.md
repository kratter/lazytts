# 🎧 lazyTTS — eBook → Audiobook Converter

A **standalone, fully-offline** desktop app that turns eBooks into audiobooks
using local neural text-to-speech. Gradio interface, packaged to a Windows
`.exe` with PyInstaller.

Inspired by [Qwen3-Audiobook-Converter](https://github.com/WhiskeyCoder/Qwen3-Audiobook-Converter),
but self-contained (no external Gradio TTS server) with a GUI.

- **Inputs:** `.txt`, `.pdf`, `.epub`, `.docx`
- **Output:** `.mp3` (96–256 kbps) or `.wav`
- **TTS engines (all offline):**
  - **Kokoro** — 82M-param model, fast & light English voices, GPU-accelerated (default)
  - **Piper** — small ONNX voices for **German** (Thorsten, Eva, Kerstin…) and
    more; runs on CPU
  - **Windows SAPI** (`pyttsx3`) — zero-dependency fallback, always works
- Sentence-aware chunking, per-chunk audio **caching** (crash-resume), choose
  which **GPU** to use.
- **Chapter-aware output:** one big file, split into numbered chapter-named
  files + a **`.m3u` playlist**, **or** a single **`.m4b`** with embedded chapter
  navigation, title/author, and cover art.
- **ID3 / metadata tagging:** MP3 output is tagged (title, artist/author,
  album, genre, and per-chapter **track numbers** in split mode) with optional
  **embedded cover art** — so files group correctly in any audiobook player.
- **Loudness normalization:** even, audiobook-level volume (EBU R128 ≈ −16
  LUFS) via ffmpeg `loudnorm`, plus an optional manual gain (dB) boost — fixes
  quiet/inconsistent TTS output. (Without ffmpeg, WAV output gets peak
  normalization instead.)
- **Smart text cleanup:** de-hyphenation, page-number stripping, and optional
  number/abbreviation expansion (`1996 → nineteen ninety-six`, `Dr. → Doctor`).
- **Long-run UX:** live progress with **speed (chunks/min) + ETA**, and a
  **Stop** button (cached chunks persist, so it resumes on the next run).
- **🔊 Preview voice** button — audition the selected engine/voice on a sample
  sentence before converting a whole book. Loaded models are cached, so
  previews and conversions don't reload the model.
- **Chapter selection + per-chapter preview** — load the detected chapters into
  a checklist, untick any you don't want, and preview any chapter's opening
  audio before committing.
- **German (and more)** — Piper provides native German voices; chapter detection
  recognises German headings (Kapitel/Teil/…); a **Text language** selector
  expands numbers/abbreviations in the chosen language (en/de/fr/es/it/pt).
- **Remembers your settings** — last-used options are saved to `settings.json`
  next to the app and restored on launch (runtime — no rebuild needed).

---

## 1. Requirements

- **Python 3.10–3.12** (3.11 recommended)
- **ffmpeg** (for MP3/M4B output, loudness normalization & low-memory assembly)
  - `setup.bat` **installs this automatically** via `winget install Gyan.FFmpeg`
  - or install manually from https://ffmpeg.org
  - after a fresh winget install, open a **new terminal** so it's on `PATH`
- A GPU is optional but recommended. Your **RTX 5070 / 5070 Ti are Blackwell
  (sm_120)** and require the **CUDA 12.8** PyTorch build (see below).

## 2. Setup

**Easiest — one command:**

```powershell
cd lazytts
.\setup.bat
```

`setup.bat` creates the `.venv`, detects your NVIDIA GPU and installs the
matching PyTorch (cu128 for the RTX 50-series), installs all app dependencies,
offers to install ffmpeg via winget, and verifies the result.

**Manual equivalent**, if you prefer:

```powershell
cd lazytts
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 1) Install PyTorch FIRST, matching your GPU.
#    RTX 50-series (Blackwell) -> cu128:
pip install torch --index-url https://download.pytorch.org/whl/cu128

# 2) Then the app dependencies.
pip install -r requirements.txt
```

> If you only want to try the UI without the neural stack, skip torch/kokoro —
> the app falls back to the Windows **SAPI** engine automatically.

### Verify the GPU is seen

```powershell
python -c "import torch; print(torch.__version__, torch.cuda.is_available(), [torch.cuda.get_device_name(i) for i in range(torch.cuda.device_count())])"
```

You should see both cards listed. In the app's **Device** dropdown you can pick
`cuda:0` or `cuda:1` to choose between the 5070 and 5070 Ti.

## 3. Run

```powershell
python app.py       # or: .\run.bat
```

Opens `http://127.0.0.1:7860`. Upload a document, pick a voice, click
**Convert to audiobook**. Output lands in `audiobooks\`.

### Choosing an engine

- **Kokoro** — pick a built-in English voice; fastest, lightest (uses your GPU).
- **Piper** — pick a **German** voice (Thorsten/Eva/Kerstin/Karlsson/Ramona) or
  an English one; small ONNX models download on first use and run on CPU.
- **SAPI** — instant, robotic; good for a quick pipeline test.

### Output modes & chapters

The **Output** control offers:

- **Single file** — one `audiobooks\<Book>.mp3` (or `.wav`).
- **Split by chapter + M3U** — a folder `audiobooks\<Book>\` containing one
  numbered, named file per chapter (`01 - Chapter One.mp3`, `02 - …`) plus
  `<Book>.m3u`, an extended playlist with chapter titles and durations. Open
  the `.m3u` in VLC / any player to get chapter navigation.
- **M4B (chapters + metadata)** — a single `audiobooks\<Book>.m4b` (AAC in an
  MP4 container) with **embedded chapter markers**, title/author tags, and
  optional **cover art** — the standard audiobook format that gives chapter
  navigation in Apple Books, Audiobookshelf, Smart AudioBook Player, etc.
  Title/author auto-fill from the document and are editable; drop in a cover
  image. Requires ffmpeg.

Chapters are detected automatically:

| Format | How chapters are found |
|---|---|
| EPUB | reading-order spine documents; title from the first heading |
| PDF  | PDF bookmarks / table of contents (top level) |
| DOCX | "Heading 1" / "Title" paragraph styles |
| TXT  | lines like `Chapter 3`, `Part II`, `CHAPTER ONE` |

If no structure is found, the book is treated as a single chapter.

---

## 4. Fully-offline model cache (for the .exe)

The app already pins the Hugging Face cache to a local `hf_cache\` folder next
to it (via `config.py`), so nothing is written to your user profile.

To make the app run with **no internet**:

```powershell
.\make_offline.bat      # once, while online — downloads model + ALL voices
.\run_offline.bat       # thereafter — sets LAZYTTS_OFFLINE=1, no network access
```

`make_offline.bat` runs `prefetch_models.py`, which caches the Kokoro model +
every Kokoro voice and downloads all the **Piper** voices. Everything lands in
`hf_cache\`.

For the packaged **.exe**: ship the populated `hf_cache\` folder next to
`lazyTTS.exe` and launch with the `LAZYTTS_OFFLINE=1` environment variable set.

## 5. Build the standalone .exe

```powershell
.\build.bat          # -> dist\lazyTTS\lazyTTS.exe  (one-dir build)
```

Notes / caveats (packaging Gradio + Torch is genuinely fiddly):

- The spec builds **one-dir**, not one-file — torch's CUDA DLLs and Gradio's
  JS frontend don't survive one-file extraction reliably.
- First launch of the built app still needs the HF model cache (see §4).
- If Gradio complains about missing frontend files at runtime, re-run the build
  after `pip install -U gradio` and confirm `collect_all("gradio")` picked up
  the `templates`/`frontend` data in the build log.
- The bundle is large (multiple GB) because of CUDA. That's expected.

---

## 6. Project layout

```
lazyTTS/
├─ app.py                 # Gradio UI + wiring
├─ config.py              # voices, paths, defaults
├─ requirements.txt
├─ run.bat / build.bat
├─ build/lazytts.spec        # PyInstaller spec
└─ lazytts/
   ├─ document.py         # txt/pdf/epub/docx -> text
   ├─ chunker.py          # sentence-aware chunking
   ├─ converter.py        # orchestration + caching + progress
   ├─ audio.py            # ffmpeg concat -> mp3/m4a/opus/flac/wav/m4b
   ├─ textnorm.py         # de-hyphenation, number/abbr expansion (multi-lang)
   ├─ translate.py        # offline NLLB-200 translation
   ├─ lexicon.py          # user pronunciation replacements
   ├─ settings_store.py   # persist last-used settings
   └─ engines/
      ├─ base.py          # TTSEngine interface
      ├─ kokoro_engine.py # English neural (GPU), fast/light
      ├─ piper_engine.py  # German/Hungarian & more (ONNX, CPU)
      ├─ mms_engine.py    # Meta MMS multilingual (VITS)
      ├─ xtts_engine.py   # Coqui XTTS-v2 multilingual (high quality)
      └─ sapi_engine.py   # Windows fallback
```

Engines are swappable via the `TTSEngine` interface — each is a single file.

## Credits & license

lazyTTS stands on a lot of open-source work — see **[CREDITS.md](CREDITS.md)** for
the full list of engines, models, and libraries with their licenses.

**Important:** some bundled models are **non-commercial** (MMS-TTS, NLLB-200
translation, XTTS-v2) and two document parsers are **AGPL** (PyMuPDF, EbookLib).
See the *Licensing implications* section of `CREDITS.md` before distributing or
using lazyTTS commercially. The Kokoro (Apache-2.0) + Piper (MIT) engines form a
commercial-friendly subset.

## 7. Troubleshooting

| Symptom | Fix |
|---|---|
| `torch.cuda.is_available()` is `False` on RTX 50xx | You installed the wrong wheel. Reinstall with the **cu128** index URL. |
| pip `resolution-too-deep` error | Don't `pip install -r requirements.txt` in one shot — use `setup.bat` (installs in stages) or install the groups separately as noted in `requirements.txt`. |
| MP3 export error about ffmpeg | Install ffmpeg and ensure it's on `PATH`, or choose WAV output. |
| Engine dropdown missing kokoro/piper | That package isn't importable — re-run `setup.bat`. |
| Kokoro slow / on CPU | Check the **Device** dropdown shows and selects your GPU; if `torch.cuda.is_available()` is `False`, reinstall the **cu128** torch build (`setup.bat` auto-repairs this). |
