# Credits & Third-Party Licenses

lazyTTS is built entirely on open-source work. Huge thanks to everyone below —
this project is a thin, offline, desktop wrapper around their models and tools.

> ⚠️ **Please read "Licensing implications" at the bottom before distributing or
> using lazyTTS commercially.** Some bundled models are **non-commercial only**,
> and two document parsers are **AGPL** (copyleft).

## TTS engines & voice models

| Component | Role | License | Link |
|---|---|---|---|
| **Kokoro** (kokoro-82M) | English neural TTS (default) | Apache-2.0 | https://github.com/hexgrad/kokoro |
| **Piper** | German/Hungarian & more (ONNX) | MIT | https://github.com/rhasspy/piper |
| **piper-voices** | Piper voice models | per-voice (mostly CC-BY / CC0 / MIT) | https://huggingface.co/rhasspy/piper-voices |
| **Meta MMS-TTS** | Multilingual VITS (EN/DE/HU) | **CC-BY-NC 4.0 (non-commercial)** | https://huggingface.co/facebook/mms-tts-eng |
| **Coqui XTTS-v2** | Multilingual high-quality TTS | **Coqui Public Model License (non-commercial)** | https://huggingface.co/coqui/XTTS-v2 |
| **pyttsx3** | Windows SAPI fallback | see project | https://github.com/nateshmbhat/pyttsx3 |

## Translation

| Component | Role | License | Link |
|---|---|---|---|
| **NLLB-200** (distilled-600M) | Offline translation | **CC-BY-NC 4.0 (non-commercial)** | https://huggingface.co/facebook/nllb-200-distilled-600M |

## Core libraries

| Library | Role | License | Link |
|---|---|---|---|
| Gradio | UI framework | Apache-2.0 | https://github.com/gradio-app/gradio |
| PyTorch | Neural network runtime | BSD-3-Clause | https://github.com/pytorch/pytorch |
| Hugging Face Transformers | NLLB & MMS models | Apache-2.0 | https://github.com/huggingface/transformers |
| Hugging Face Hub | Model download/cache | Apache-2.0 | https://github.com/huggingface/huggingface_hub |
| coqui-tts (idiap fork) | XTTS engine | MPL-2.0 | https://github.com/idiap/coqui-ai-TTS |
| sentencepiece | NLLB tokenizer | Apache-2.0 | https://github.com/google/sentencepiece |
| torchcodec | Audio I/O for coqui | BSD-3-Clause | https://github.com/pytorch/torchcodec |
| soundfile | WAV read/write | BSD-3-Clause | https://github.com/bastibe/python-soundfile |
| NumPy | Arrays | BSD-3-Clause | https://numpy.org |
| num2words | Number → words | LGPL-2.1 | https://github.com/savoirfairelinux/num2words |
| **PyMuPDF** (fitz) | PDF parsing | **AGPL-3.0** / commercial | https://github.com/pymupdf/PyMuPDF |
| **EbookLib** | EPUB parsing | **AGPL-3.0** | https://github.com/aerkalov/ebooklib |
| BeautifulSoup4 | EPUB HTML cleanup | MIT | https://www.crummy.com/software/BeautifulSoup/ |
| lxml | XML/HTML parsing | BSD-3-Clause | https://lxml.de |
| python-docx | DOCX parsing | MIT | https://github.com/python-openxml/python-docx |
| pywebview | Native desktop window | BSD-3-Clause | https://github.com/r0x0r/pywebview |
| pythonnet | pywebview WebView2 backend | MIT | https://github.com/pythonnet/pythonnet |
| spaCy | Kokoro G2P dependency | MIT | https://github.com/explosion/spaCy |

## Tools

| Tool | Role | License | Link |
|---|---|---|---|
| FFmpeg | MP3/M4B/loudness/format conversion | LGPL-2.1+ / GPL (build-dependent) | https://ffmpeg.org |
| PyInstaller | Freezes the app to an .exe | GPL-2.0 **with bundling exception** | https://pyinstaller.org |
| Inno Setup | Windows installer | free (BSD-like) | https://jrsoftware.org/isinfo.php |

## Inspiration

- **WhiskeyCoder — Qwen3-Audiobook-Converter**, the project that inspired lazyTTS.

---

## Licensing implications (read this)

lazyTTS is a **combined work**. Its effective usage terms are the *union* of the
strictest components it ships or invokes:

1. **Non-commercial models.** **MMS-TTS**, **NLLB-200 translation**, and
   **XTTS-v2** are licensed for **non-commercial use only** (CC-BY-NC / Coqui
   CPML). If you distribute lazyTTS for commercial use, you must **exclude** these
   or obtain separate licenses. The **Kokoro** (Apache-2.0) and **Piper** (MIT)
   engines are commercial-friendly and can form a commercial-safe subset.

2. **Copyleft parsers.** **PyMuPDF** and **EbookLib** are **AGPL-3.0**. Shipping a
   binary that links them generally requires offering your corresponding source
   under a compatible (A)GPL license. (Alternatives if you want to relicense
   permissively: swap PyMuPDF → `pypdf`/`pdfplumber`, EbookLib → a custom
   zip+lxml EPUB reader.)

3. **FFmpeg** builds are often GPL (e.g. Gyan builds). lazyTTS calls FFmpeg as an
   external process rather than linking it, but bundling a GPL FFmpeg binary
   still carries GPL obligations.

**Practical guidance:** for a **personal / non-commercial, open-source** release,
publishing lazyTTS under **AGPL-3.0** is the clean, honest choice (it matches the
strongest copyleft dependency and respects the non-commercial models for personal
use). For any **commercial** ambition, first remove the non-commercial models and
the AGPL parsers. This file is documentation, **not legal advice** — verify each
license for your specific use.
