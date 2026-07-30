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
- **📚 Get a book / article** — search **Project Gutenberg** (public-domain books)
  or paste any **web article URL**; lazyTTS fetches the text and loads it straight
  into the pipeline. No file hunting.
- **🎙 Voice cloning (XTTS)** — clone a voice from a short (10–30 s) reference clip
  and narrate the whole book in it.
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
- **EPUB 3 read-along (synced text)** — a single `audiobooks\<Book>.epub` that
  **highlights each sentence as it is spoken**, like subtitles for an audiobook.
  See below.

Chapters are detected automatically:

| Format | How chapters are found |
|---|---|
| EPUB | reading-order spine documents; title from the first heading |
| PDF  | PDF bookmarks / table of contents (top level) |
| DOCX | "Heading 1" / "Title" paragraph styles |
| TXT  | lines like `Chapter 3`, `Part II`, `CHAPTER ONE` |

If no structure is found, the book is treated as a single chapter.

### EPUB 3 read-along (synced text + audio)

Produces one `.epub` containing both the text and the narration, wired together
with [EPUB 3 Media Overlays](https://www.w3.org/publishing/epub32/epub-mediaoverlays.html)
so a reader highlights each sentence as it's spoken — useful for following along
when a word isn't clear, or for language learning.

Because lazyTTS *generates* the audio, the sentence timings are exact: they come
straight from the synthesized audio's frame counts. There is no transcription and
no forced alignment, so text and speech cannot drift apart.

**Reading it.** Pick your app under **Read-along target reader**:

| Profile | Audio | Notes |
|---|---|---|
| Universal (max compatibility) | m4a | Flat SMIL + EPUB 2 NCX fallback. Start here. |
| Thorium Reader (desktop) | m4a | Per-paragraph `<seq epub:textref>` structure. |
| Storyteller (Android / iOS) | mp3 | For the [Storyteller](https://storyteller-platform.dev/) app. |
| lazyREADER (word-by-word) | mp3 | One `<par>` per **word**, inside a `<seq>` per sentence, so the reader highlights the word being spoken. Needs Kokoro (it reports word timings); falls back to sentence-level for any chapter without them. |

Two more controls sit next to it. **Read-along audio** picks the narration
container (the main **Format** dropdown doesn't apply — this audio lives inside
the `.epub`, so it has to be something readers can decode); *Profile default*
follows the table above. **Narration files** chooses one audio file per chapter
or a single track for the whole book.

Prefer **one file per chapter**. Both are spec-legal, but a single whole-book
track pushes clip offsets hours into one file, where readers seek less
accurately (especially VBR MP3) and have to buffer far more to play any
sentence. Per-chapter also means a damaged file costs you one chapter, not the
book.

### Send it to your phone (same Wi-Fi)

**Send to device** shares the finished read-along `.epub` files with the
[lazyREADER](https://github.com/kratter/lazyREADER) Android app over your local
network. Press **Start sharing**, then scan the QR code in the app's *Sync*
screen (or type the address in). It's read-only and only listens while switched
on: it serves the `.epub` files in your output folder and nothing else.

The profile differences are small — Media Overlays is one standard. **lazyREADER
(word-by-word)** is the default because word-level highlighting is the point of
the read-along export here; pick **Universal** if you're targeting a third-party
reader, since a `<par>` per word is a lot more of them and not every reader
copes gracefully. Readers known to support Media Overlays:
Thorium Reader (Windows/macOS/Linux), Thorium Mobile, Storyteller, BookFusion, Dolphin
EasyReader, and Apple Books. Note that several popular Android readers
(Moon+ Reader, ReadEra, Librera) and Google Play Books do **not** — they'll open
the file as a plain ebook with no sync rather than failing.

Storyteller's app can import a local `.epub` directly; its self-hosted server is
only needed for its own transcribe-and-align pipeline, which lazyTTS replaces.

**Pacing.** The **Gap** slider becomes the pause between *paragraphs*; sentences
within a paragraph use the shorter `SENTENCE_GAP_SECONDS` (0.15 s) from
`config.py`. A full gap after every sentence sounds stilted once the synthesis
unit shrinks from a chunk to a single sentence.

**Limits worth knowing:**

- The ebook is regenerated from extracted plain text, so original formatting
  (italics, images, footnotes) is not carried over.
- Chapter titles are not narrated, so the heading doesn't highlight.
- Silence-trimming is disabled automatically in this mode — it changes audio
  length and would desynchronize the overlay. Loudness and gain are unaffected.
- MP3 has a small constant encoder priming offset (~26 ms); m4a does not, which
  is why the default profiles use it.

**Validation.** Every export is checked automatically: SMIL references must
resolve to real sentence spans, clip ranges must be ordered and non-overlapping,
and the manifest wiring must be complete. The result appears in the status line.

For full spec conformance you can also install the official
[EPUBCheck](https://github.com/w3c/epubcheck) (needs Java). It's optional — when
absent, the built-in structural check still runs. Enable it any of these ways:

- drop `epubcheck.jar` next to the app (same trick as ffmpeg), or
- set `EPUBCHECK_JAR=C:\path\to\epubcheck.jar`, or
- put an `epubcheck` launcher on `PATH`.

---

## 4. Fully-offline model cache (for the .exe)

The app already pins the Hugging Face cache to a local `hf_cache\` folder next
to it (via `config.py`), so nothing is written to your user profile.

To make the app run with **no internet**:

```powershell
.\make_offline.bat      # once, while online — downloads model + ALL voices
.\run_offline.bat       # thereafter — sets LAZYTTS_OFFLINE=1, no network access
```

`make_offline.bat` runs `prefetch_models.py`, which caches every model group
(~5 GB). Everything lands in `hf_cache\`.

To fetch less, name the groups you want — valid ids are `kokoro`, `piper`,
`mms`, `xtts`, `nllb`:

```powershell
.venv\Scripts\python prefetch_models.py --minimal              # Kokoro only, ~0.3 GB
.venv\Scripts\python prefetch_models.py --groups kokoro,piper  # pick exactly these
.venv\Scripts\python prefetch_models.py --skip-xtts --skip-translation
```

You can also do this from inside the app: the **📥 Models** panel at the bottom
lists every group with its size and whether it's downloaded, and downloads only
the ones you tick. On a fresh install just **Kokoro** is pre-selected — enough to
convert English books — and the panel stays collapsed so nothing is fetched
until you ask for it. Add Piper/MMS/XTTS when you need other languages or voice
cloning, and NLLB when you want offline translation.

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
   ├─ epub3.py            # EPUB 3 + Media Overlays writer (read-along)
   ├─ epubcheck.py        # structural validation (+ optional EPUBCheck)
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
