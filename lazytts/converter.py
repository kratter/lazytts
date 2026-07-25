"""Orchestrate: document -> chapters -> chunks -> synthesis -> audiobook.

`convert` is a generator that yields progress events. Chunk audio is cached by
a hash of (engine, voice, speed, text), so re-runs and crashes resume cheaply.

Two output modes:
  * single  -> one big file (audiobooks/<Book>.<ext>)
  * split   -> one file per chapter, numbered + named, in audiobooks/<Book>/,
               plus a <Book>.m3u playlist (with titles and durations).
"""
from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path

import config

from . import audio, chunker, document
from .engines.base import TTSEngine


@dataclass
class Progress:
    stage: str          # "chunked" | "synth" | "assembling" | "done"
    done: int
    total: int
    message: str
    output: str | None = None   # main artifact (file, or .m3u for split mode)
    preview: str | None = None  # a playable audio file for the UI player

    @property
    def fraction(self) -> float:
        return self.done / self.total if self.total else 0.0


class Converter:
    def __init__(self, engine: TTSEngine, cache_dir, output_dir, max_chunk_chars: int = 1500):
        self.engine = engine
        self.cache_dir = str(cache_dir)
        self.output_dir = str(output_dir)
        self.max_chunk_chars = max_chunk_chars
        os.makedirs(self.cache_dir, exist_ok=True)
        os.makedirs(self.output_dir, exist_ok=True)

    def _chunk_path(self, voice, speed, text) -> str:
        key = f"{self.engine.name}|{voice}|{speed}|{text}"
        digest = hashlib.sha1(key.encode("utf-8")).hexdigest()
        return os.path.join(self.cache_dir, f"{digest}.wav")

    def convert(self, input_path, *, voice, speed, out_fmt="mp3", bitrate="128k",
                gap=0.35, out_name=None, output_mode="single",
                normalize=True, expand=False, lang="en", metadata=None, cover=None,
                audio_filter=None, chapters=None,
                translate_to=None, translate_src="eng_Latn", translate_device="cpu",
                channels=1, two_pass=False, lexicon=None):
        # output_mode: "single" | "split" | "m4b"
        # chapters: optional pre-extracted/-selected list[Chapter]; if None, extract.
        # translate_to: NLLB target code (e.g. "deu_Latn") or None to keep original.
        if chapters is None:
            chapters = document.extract_chapters(
                input_path, normalize=normalize, expand=expand, lang=lang)
        if not chapters:
            raise ValueError("No chapters selected / found.")

        # Optional offline translation step (before chunking/synthesis).
        if translate_to and translate_to != translate_src:
            from . import translate as _translate
            t_total = sum(_translate.count_chunks(ch.text) for ch in chapters) or 1
            t_done = 0
            yield Progress("translating", 0, t_total,
                           f"Loading translator & translating {len(chapters)} chapter(s)…")
            translated: list[document.Chapter] = []
            for ch in chapters:
                counter = {"n": t_done}

                def _tick(_c=counter):
                    _c["n"] += 1

                new_text = _translate.translate_text(
                    ch.text, translate_src, translate_to,
                    device=translate_device, progress=_tick)
                new_title = _translate.translate_text(
                    ch.title, translate_src, translate_to, device=translate_device)
                t_done = counter["n"]
                translated.append(document.Chapter(title=new_title or ch.title,
                                                   text=new_text))
                yield Progress("translating", t_done, t_total,
                               f"Translated {len(translated)}/{len(chapters)} chapter(s)")
            chapters = translated

        # Apply the user's pronunciation lexicon (after translation, so it can
        # fix names/terms in the final spoken language).
        if lexicon:
            from . import lexicon as _lex
            pairs = _lex.parse(lexicon) if isinstance(lexicon, str) else lexicon
            if pairs:
                chapters = [document.Chapter(c.title, _lex.apply(c.text, pairs))
                            for c in chapters]

        # Chunk each chapter; keep chunks grouped by chapter.
        per_chapter_chunks = [
            chunker.chunk_text(ch.text, max_chars=self.max_chunk_chars) for ch in chapters
        ]
        total = sum(len(c) for c in per_chapter_chunks)
        yield Progress("chunked", 0, total,
                       f"{len(chapters)} chapter(s), {total} chunk(s).")

        # Synthesize (with caching), keeping wavs grouped by chapter.
        per_chapter_wavs: list[list[str]] = []
        done = 0
        for chunks in per_chapter_chunks:
            wavs: list[str] = []
            for chunk in chunks:
                wav_path = self._chunk_path(voice, speed, chunk)
                if not os.path.exists(wav_path):
                    self.engine.synthesize_to_file(chunk, wav_path, voice=voice, speed=speed)
                wavs.append(wav_path)
                done += 1
                yield Progress("synth", done, total, f"Synthesized chunk {done}/{total}")
            per_chapter_wavs.append(wavs)

        base = _safe_name(out_name or Path(input_path).stem)
        sr = self.engine.sample_rate

        if output_mode == "split":
            yield Progress("assembling", total, total, "Assembling chapters + playlist…")
            yield self._assemble_split(chapters, per_chapter_wavs, base, out_fmt,
                                       bitrate, gap, sr, metadata, cover, audio_filter,
                                       channels, two_pass)
        elif output_mode == "m4b":
            yield Progress("assembling", total, total, "Assembling M4B (chapters + metadata)…")
            yield self._assemble_m4b(chapters, per_chapter_wavs, base, bitrate, gap, sr,
                                     metadata, cover, audio_filter, channels, two_pass)
        else:
            ext = config.FORMAT_EXT.get(out_fmt, out_fmt)
            out_path = os.path.join(self.output_dir, f"{base}.{ext}")
            yield Progress("assembling", total, total, "Assembling audiobook…")
            all_wavs = [w for wavs in per_chapter_wavs for w in wavs]
            book_title = (metadata or {}).get("title") or base
            author = (metadata or {}).get("author") or ""
            tags = {
                "title": book_title, "album": book_title,
                "artist": author, "album_artist": author, "genre": "Audiobook",
            }
            audio.concat_to_output(all_wavs, out_path, sr, fmt=out_fmt,
                                   bitrate=bitrate, gap=gap, work_dir=self.cache_dir,
                                   metadata=tags, cover=cover, audio_filter=audio_filter,
                                   channels=channels, two_pass=two_pass)
            yield Progress("done", total, total, f"Done → {out_path}",
                           output=out_path, preview=out_path)

    def _assemble_split(self, chapters, per_chapter_wavs, base, out_fmt, bitrate,
                        gap, sr, metadata=None, cover=None, audio_filter=None,
                        channels=1, two_pass=False) -> Progress:
        book_dir = os.path.join(self.output_dir, base)
        os.makedirs(book_dir, exist_ok=True)

        book_title = (metadata or {}).get("title") or base
        author = (metadata or {}).get("author") or ""
        total_tracks = sum(1 for w in per_chapter_wavs if w)

        width = max(2, len(str(len(chapters))))
        entries: list[tuple[str, str, float]] = []
        first_file: str | None = None

        n = 0
        for ch, wavs in zip(chapters, per_chapter_wavs):
            if not wavs:
                continue
            n += 1
            title = ch.title or f"Chapter {n}"
            num = str(n).zfill(width)
            ext = config.FORMAT_EXT.get(out_fmt, out_fmt)
            filename = f"{num} - {_safe_name(title)}.{ext}"
            fpath = os.path.join(book_dir, filename)
            # Per-file ID3: track title = "NN - Chapter title" (title + number).
            tags = {
                "title": f"{num} - {title}", "track": f"{n}/{total_tracks}",
                "album": book_title, "artist": author,
                "album_artist": author, "genre": "Audiobook",
            }
            audio.concat_to_output(wavs, fpath, sr, fmt=out_fmt,
                                   bitrate=bitrate, gap=gap, work_dir=self.cache_dir,
                                   metadata=tags, cover=cover, audio_filter=audio_filter,
                                   channels=channels, two_pass=two_pass)
            entries.append((filename, title, audio.wavs_duration(wavs, sr, gap)))
            if first_file is None:
                first_file = fpath

        m3u_path = os.path.join(book_dir, f"{base}.m3u")
        audio.write_m3u(m3u_path, entries)
        return Progress("done", 1, 1,
                        f"Done → {len(entries)} chapter file(s) + playlist in {book_dir}",
                        output=m3u_path, preview=first_file)

    def _assemble_m4b(self, chapters, per_chapter_wavs, base, bitrate, gap, sr,
                      metadata, cover, audio_filter=None,
                      channels=1, two_pass=False) -> Progress:
        # Flat list for one continuous track, plus chapter boundary times (ms).
        all_wavs: list[str] = []
        chapter_marks: list[tuple[str, float, float]] = []
        cursor_ms = 0.0
        gap_ms = gap * 1000.0
        n = 0
        for ch, wavs in zip(chapters, per_chapter_wavs):
            if not wavs:
                continue
            n += 1
            dur_ms = audio.wavs_duration(wavs, sr, gap) * 1000.0
            start = cursor_ms
            end = cursor_ms + dur_ms
            chapter_marks.append((ch.title or f"Chapter {n}", start, end))
            # concat inserts a gap between every consecutive wav, including the
            # boundary to the next chapter.
            cursor_ms = end + gap_ms
            all_wavs.extend(wavs)

        meta = dict(metadata or {})
        meta.setdefault("title", base)
        meta.setdefault("album", meta.get("title", base))

        out_path = os.path.join(self.output_dir, f"{base}.m4b")
        audio.concat_to_m4b(
            all_wavs, out_path, sr, chapters=chapter_marks, metadata=meta,
            bitrate=bitrate, gap=gap, cover=cover, work_dir=self.cache_dir,
            audio_filter=audio_filter, channels=channels, two_pass=two_pass,
        )
        return Progress("done", 1, 1,
                        f"Done → {out_path} ({len(chapter_marks)} chapters embedded)",
                        output=out_path, preview=None)


def _safe_name(name: str) -> str:
    name = re.sub(r"[^\w\-. ]+", "_", name).strip().strip(".")
    return name or "audiobook"
