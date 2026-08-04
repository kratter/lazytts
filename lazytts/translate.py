"""Offline text translation via NLLB-200 (facebook/nllb-200-distilled-600M).

Fully offline — the model lives in the same HF cache as the TTS voices, so a
packaged .exe shipped with hf_cache + LAZYTTS_OFFLINE=1 translates without network.

Design notes:
  * The model is loaded lazily and cached per device (loading 600M params is
    slow; we do it once).
  * Long chapter text is split into sentence-grouped chunks under the model's
    token limit, translated, then reassembled preserving paragraph breaks.
  * `translate_text` calls an optional `progress` callback once per chunk so the
    converter can show a live translation progress bar / ETA.

Quality caveat: machine translation of a whole book is *serviceable*, not
literary — names, idioms and tone can drift. Good for consuming a foreign book.
"""
from __future__ import annotations

import re

import config

# Loaded models keyed by resolved device string -> (tokenizer, model, device).
_CACHE: dict[str, tuple] = {}

_MAX_CHARS = 400          # sentence-group size fed to the model (well under 512 tok)
_SENT_RE = re.compile(r"\S.*?(?:[.!?…]+[\"»”'’)\]]*|$)", re.S)


def _resolve_device(device) -> str:
    dev = str(device or "cpu")
    if dev.startswith("cuda"):
        try:
            import torch
            if torch.cuda.is_available():
                return dev
        except Exception:
            pass
    return "cpu"


def _load(device: str):
    key = _resolve_device(device)
    if key not in _CACHE:
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer
        tok = AutoTokenizer.from_pretrained(config.NLLB_MODEL)
        model = AutoModelForSeq2SeqLM.from_pretrained(config.NLLB_MODEL)
        try:
            model = model.to(key)
        except Exception:
            key = "cpu"
            model = model.to("cpu")
        model.eval()
        _CACHE[key] = (tok, model, key)
    return _CACHE[key]


def _target_bos(tok, tgt_code: str) -> int:
    """Token id NLLB forces as the first decoded token (selects target lang)."""
    tid = tok.convert_tokens_to_ids(tgt_code)
    if tid is None or tid == getattr(tok, "unk_token_id", -1):
        # Older tokenizers expose the mapping explicitly.
        tid = getattr(tok, "lang_code_to_id", {}).get(tgt_code, tid)
    return tid


def _pack(line: str, max_chars: int = _MAX_CHARS) -> list[str]:
    """Split one paragraph into sentence groups of at most ~max_chars."""
    groups: list[str] = []
    cur = ""
    for sent in (m.group(0).strip() for m in _SENT_RE.finditer(line)):
        if not sent:
            continue
        if cur and len(cur) + 1 + len(sent) > max_chars:
            groups.append(cur)
            cur = sent
        else:
            cur = f"{cur} {sent}".strip()
    if cur:
        groups.append(cur)
    return groups or [line.strip()]


def count_chunks(text: str) -> int:
    """How many model calls `translate_text` will make (for progress totals)."""
    n = 0
    for line in (text or "").split("\n"):
        if line.strip():
            n += len(_pack(line))
    return n


#: Sentences per model call when the caller doesn't say. A GPU has the memory to
#: take a big batch and is where the time is worth saving; on CPU a large batch
#: mostly just inflates peak memory.
_BATCH_FOR_DEVICE = {"cuda": 32, "cpu": 8}


def translate_lines(lines: list[str], src_code: str, tgt_code: str,
                    device="cpu", batch_size: int | None = None,
                    progress=None) -> list[str]:
    """Translate many short strings, batched, returning one result per input.

    Bilingual read-along needs a translation per *sentence* — thousands of tiny
    calls, where one-at-a-time is dominated by per-call overhead. Batching cuts
    that by roughly the batch size. `progress` is called once per input string.

    Sentences are grouped by length before batching, longest first. Padding is
    what a mixed batch wastes: one 250-character sentence makes the model chew
    through 250 characters' worth of tokens for the four-word sentence beside it.
    Grouping measured 29 sentences/second against 18 in document order on the
    same GPU — enough to take a novel from 5.5 minutes to 3.4. Longest first so
    that if a batch is too big for the device it fails on the first one rather
    than most of the way through a book.
    """
    if not lines:
        return []
    if src_code == tgt_code:
        return list(lines)
    import torch

    tok, model, dev = _load(device)
    tok.src_lang = src_code
    bos = _target_bos(tok, tgt_code)
    if batch_size is None:
        batch_size = _BATCH_FOR_DEVICE.get(dev.split(":")[0], 8)

    out: list[str] = [""] * len(lines)
    # Only non-blank lines go to the model; blanks keep their empty result.
    # Results are written back by index, so reordering here is invisible.
    todo = sorted((i for i, line in enumerate(lines) if line and line.strip()),
                  key=lambda i: len(lines[i]), reverse=True)

    for start in range(0, len(todo), batch_size):
        batch = todo[start:start + batch_size]
        enc = tok([lines[i].strip() for i in batch], return_tensors="pt",
                  padding=True, truncation=True, max_length=512).to(dev)
        with torch.no_grad():
            gen = model.generate(
                **enc, forced_bos_token_id=bos,
                max_length=512, num_beams=2, no_repeat_ngram_size=3,
            )
        for i, decoded in zip(batch, tok.batch_decode(gen, skip_special_tokens=True)):
            out[i] = decoded.strip()
        if progress:
            for _ in batch:
                progress()

    return out


def translate_text(text: str, src_code: str, tgt_code: str,
                   device="cpu", progress=None) -> str:
    """Translate `text` from `src_code` to `tgt_code` (NLLB FLORES-200 codes).

    Preserves blank lines / paragraph structure. `progress` (if given) is called
    with no args once per translated chunk.
    """
    if not text or not text.strip() or src_code == tgt_code:
        return text
    import torch

    tok, model, dev = _load(device)
    tok.src_lang = src_code
    bos = _target_bos(tok, tgt_code)

    out_lines: list[str] = []
    for line in text.split("\n"):
        if not line.strip():
            out_lines.append("")
            continue
        pieces: list[str] = []
        for group in _pack(line):
            enc = tok(group, return_tensors="pt", truncation=True,
                      max_length=512).to(dev)
            with torch.no_grad():
                gen = model.generate(
                    **enc, forced_bos_token_id=bos,
                    max_length=512, num_beams=2, no_repeat_ngram_size=3,
                )
            pieces.append(tok.batch_decode(gen, skip_special_tokens=True)[0].strip())
            if progress:
                progress()
        out_lines.append(" ".join(pieces))
    return "\n".join(out_lines)
