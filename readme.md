# 🎧 lazyTTS — eBook → Audiobook Converter

A **standalone, fully-offline** desktop app that turns eBooks into audiobooks
using local neural text-to-speech. Runs as a **native desktop window** (no
browser), packaged to a Windows `.exe` with PyInstaller.

Inspired by [Qwen3-Audiobook-Converter](https://github.com/WhiskeyCoder/Qwen3-Audiobook-Converter),
but self-contained (no external TTS server), multilingual, and with a real GUI.

- **Inputs:** `.txt`, `.pdf`, `.epub`, `.docx`
- **Outputs:** `.mp3`, `.m4a`, `.opus`, `.flac`, `.wav` (16/24-bit), mono or
  stereo — as one file, **split by chapter + `.m3u`**, or a single **`.m4b`**
  with embedded chapters, metadata & cover art.
- **TTS engines (all offline):**
  - **Kokoro** — 82M English voices, fast & light, GPU-accelerated (default)
  - **Piper** — small ONNX voices for **German, Hungarian** & more (CPU)
  - **Meta MMS** — multilingual VITS, EN/DE/HU *(non-commercial license)*
  - **Coqui XTTS-v2** — highest-quality multilingual, EN/DE/HU; slower *(non-commercial license)*
  - **Windows SAPI** — zero-dependency fallback, always works
- **Offline translation** — translate a book before narration with **NLLB-200**
  (English / German / Hungarian…), then narrate it with a matching voice;
  preview the translation first.
- **Pronunciation lexicon** — custom `word => sound` overrides for names/jargon.
- **Batch queue** — convert many books back-to-back.
- **Text preview / edit** — review and fix the extracted text before synthesis.
- **Audio polish** — loudness presets (audiobook −16, **ACX**, podcast, loud),
  optional **2-pass** loudnorm, voice cleanup (high-pass + denoise), silence
  trimming, and a manual gain boost.
- **Chapter-aware** — auto-detects chapters, pick which to export, per-chapter
  preview; ID3 tags with per-track numbers; embedded cover art.
- **Smart text cleanup** — de-hyphenation, page-number stripping, and
  number/abbreviation expansion (`1996 → nineteen ninety-six`) in the chosen
  language.
- **Nice touches** — 🔊 voice preview, live **speed + ETA**, Stop with
  crash-resume caching, choose which **GPU** to use, duration estimate,
  **📂 open output folder**, a done chime, **closing the window shuts the server
  down**, a **🔄 update check**, and your settings remembered across launches.

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

Opens a **native desktop window** (closing it stops the server). Set
`LAZYTTS_BROWSER=1` to open in your browser instead. Upload a document, pick a
voice, click **Convert to audiobook**. Output lands in `audiobooks\`.

### Choosing an engine

- **Kokoro** — built-in English voices; fastest, lightest (uses your GPU).
- **Piper** — **German / Hungarian** (and English) ONNX voices; download on
  first use, run on CPU.
- **MMS** — Meta's multilingual VITS (English/German/Hungarian); non-commercial.
- **XTTS-v2** — Coqui's highest-quality multilingual voices (EN/DE/HU);
  autoregressive so **much slower** — best for short/high-quality output;
  non-commercial.
- **SAPI** — instant, robotic; good for a quick pipeline test.

> Picking a **Translate to** language auto-selects a matching voice. Kokoro is
> English-only, so translated output routes through Piper/MMS/XTTS.

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

## 8. Releases, CI & updates

- **CI** (`.github/workflows/ci.yml`): byte-compiles all sources on Windows/macOS/Linux on every push — a fast cross-platform sanity check.
- **Releases** (`.github/workflows/release.yml`): push a tag like `v0.2.0` to build the lightweight **`lazyTTS-Net-Setup.exe`** and publish a GitHub Release with it. Keep the tag in sync with `APP_VERSION` in `config.py`.
- **In-app updates**: the footer's **🔄 Check for updates** button compares `APP_VERSION` to the latest release tag and links to the download. Requires the repo's **releases to be public** (a private repo returns 404); skipped in offline mode.

To cut a release:
```bash
# bump APP_VERSION in config.py to match, then:
git tag v0.2.0 && git push origin v0.2.0
```
