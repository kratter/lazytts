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
import shutil
from dataclasses import dataclass
from pathlib import Path

import config

from . import audio, chunker, document, epub3, epubcheck, textnorm
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

    def _synthesize(self, text, voice, speed) -> str:
        """Cache path for *text*, synthesizing it first if it isn't cached.

        The engine gets speech-normalized text (ellipses and dashes turned into
        real pauses); callers keep the original for display. The cache is keyed
        on what's actually spoken, so two spellings of the same utterance share
        one WAV.
        """
        spoken = textnorm.for_speech(text)
        wav_path = self._chunk_path(voice, speed, spoken)
        if not os.path.exists(wav_path):
            self.engine.synthesize_to_file(spoken, wav_path, voice=voice, speed=speed)
        return wav_path

    def convert(self, input_path, *, voice, speed, out_fmt="mp3", bitrate="128k",
                gap=config.CHUNK_GAP_SECONDS, out_name=None, output_mode="single",
                normalize=True, expand=False, lang="en", metadata=None, cover=None,
                audio_filter=None, chapters=None,
                translate_to=None, translate_src="eng_Latn", translate_device="cpu",
                channels=1, two_pass=False, lexicon=None, epub3_profile=None,
                epub3_audio_fmt=None, epub3_layout="per_chapter"):
        # output_mode: "single" | "split" | "m4b" | "epub3"
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

        # Read-along export needs sentence-level synthesis units, so it has its
        # own pipeline from here on.
        if output_mode == "epub3":
            yield from self._convert_epub3(
                chapters, voice=voice, speed=speed, gap=gap,
                out_name=out_name or Path(input_path).stem, lang=lang,
                metadata=metadata, cover=cover, audio_filter=audio_filter,
                bitrate=bitrate, channels=channels, two_pass=two_pass,
                profile=epub3_profile, audio_fmt=epub3_audio_fmt,
                layout=epub3_layout)
            return

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
                wavs.append(self._synthesize(chunk, voice, speed))
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

    def _convert_epub3(self, chapters, *, voice, speed, gap, out_name, lang,
                       metadata, cover, audio_filter, bitrate, channels,
                       two_pass, profile=None, audio_fmt=None, layout="per_chapter"):
        """Synthesize one WAV per sentence and package an EPUB 3 read-along.

        Timings come straight from the generated audio's frame counts, so text
        and speech cannot drift apart — no transcription or forced alignment.
        """
        prof = dict(config.EPUB3_PROFILES[config.DEFAULT_EPUB3_PROFILE])
        if isinstance(profile, str):
            prof.update(config.EPUB3_PROFILES.get(profile, {}))
        elif profile:
            prof.update(profile)

        # Anything that changes the audio's length would desynchronize the
        # overlay, so silence-trimming is dropped here (loudness/gain are fine).
        dropped_filter = False
        if audio_filter and "silenceremove" in audio_filter:
            parts = [p for p in audio_filter.split(",") if "silenceremove" not in p]
            audio_filter = ",".join(parts) or None
            dropped_filter = True

        sr = self.engine.sample_rate
        sentence_gap = config.SENTENCE_GAP_SECONDS
        paragraph_gap = gap

        # Split every chapter into paragraphs -> sentences -> synthesis pieces.
        # A sentence too long for the engine takes several passes but stays one
        # highlightable unit.
        per_chapter: list[list[list[tuple[str, list[str]]]]] = []
        total = 0
        for ch in chapters:
            paragraphs = []
            for sentences in chunker.paragraph_sentences(ch.text):
                units = [(s, chunker.sentence_pieces(s, self.max_chunk_chars))
                         for s in sentences]
                paragraphs.append(units)
                total += sum(len(pieces) for _, pieces in units)
            per_chapter.append(paragraphs)

        if not total:
            raise ValueError("No sentences to synthesize.")

        note = " (silence-trim disabled to keep sync)" if dropped_filter else ""
        yield Progress("chunked", 0, total,
                       f"{len(chapters)} chapter(s), {total} sentence unit(s){note}.")

        base = _safe_name(out_name)
        stage_dir = os.path.join(self.cache_dir, "_epub3", base)
        os.makedirs(stage_dir, exist_ok=True)
        # An explicit choice wins over the profile's default container.
        audio_fmt = audio_fmt or prof["audio_fmt"]
        audio_ext = config.FORMAT_EXT.get(audio_fmt, audio_fmt)
        one_file = layout == "single"
        # In single-file mode every chapter's clips index into one shared track,
        # so timings accumulate across chapters instead of resetting.
        book_timeline: list[str] = []
        book_cursor = 0.0

        ep_chapters: list[epub3.Chapter] = []
        done = 0
        for idx, (ch, paragraphs) in enumerate(zip(chapters, per_chapter), 1):
            timeline: list[str] = []   # chapter audio in order, silence included
            cursor = 0.0               # seconds consumed so far
            ep_paragraphs: list[list[epub3.Sentence]] = []

            for p_idx, units in enumerate(paragraphs):
                ep_sentences: list[epub3.Sentence] = []
                for s_idx, (text, pieces) in enumerate(units):
                    # Silence *before* this sentence: a full gap at paragraph
                    # boundaries, a shorter one between sentences. Never before
                    # the first sound in the chapter.
                    if timeline:
                        pause = sentence_gap if s_idx else paragraph_gap
                        if pause > 0:
                            sil = audio.silence_wav(self.cache_dir, pause, sr)
                            timeline.append(sil)
                            cursor += audio.wav_seconds(sil, sr)

                    begin = cursor
                    for piece in pieces:
                        wav_path = self._synthesize(piece, voice, speed)
                        timeline.append(wav_path)
                        cursor += audio.wav_seconds(wav_path, sr)
                        done += 1
                        yield Progress("synth", done, total,
                                       f"Synthesized {done}/{total} sentence unit(s)")
                    ep_sentences.append(epub3.Sentence(text, begin, cursor))
                if ep_sentences:
                    ep_paragraphs.append(ep_sentences)

            if not timeline:
                continue

            # Hold the highlight across the silence between sentences instead of
            # letting it blank out: each sentence ends where the next begins.
            if prof["gapless"]:
                flat = [s for para in ep_paragraphs for s in para]
                for cur, nxt in zip(flat, flat[1:]):
                    cur.end = nxt.begin
                if flat:
                    flat[-1].end = cursor

            if one_file:
                # Append to the shared track and shift this chapter's timings
                # to where they land in it. A chapter break gets the full gap.
                offset = book_cursor
                if book_timeline and paragraph_gap > 0:
                    sil = audio.silence_wav(self.cache_dir, paragraph_gap, sr)
                    book_timeline.append(sil)
                    offset += audio.wav_seconds(sil, sr)
                for para in ep_paragraphs:
                    for sentence in para:
                        sentence.begin += offset
                        sentence.end += offset
                book_timeline.extend(timeline)
                book_cursor = offset + cursor
                ep_chapters.append(epub3.Chapter(
                    title=ch.title or f"Chapter {idx}",
                    paragraphs=ep_paragraphs, audio_path="",  # set after encoding
                    audio_ext=audio_ext, duration=cursor,
                    audio_name=f"book.{audio_ext}"))
            else:
                ch_audio = os.path.join(stage_dir, f"ch{idx:03d}.{audio_ext}")
                yield Progress("assembling", total, total,
                               f"Encoding chapter {idx}/{len(chapters)} narration…")
                audio.concat_to_output(
                    timeline, ch_audio, sr, fmt=audio_fmt, bitrate=bitrate,
                    gap=0.0, work_dir=self.cache_dir, metadata=None, cover=None,
                    audio_filter=audio_filter, channels=channels, two_pass=two_pass)
                ep_chapters.append(epub3.Chapter(
                    title=ch.title or f"Chapter {idx}",
                    paragraphs=ep_paragraphs, audio_path=ch_audio,
                    audio_ext=audio_ext, duration=cursor))

        if not ep_chapters:
            raise ValueError("Nothing was synthesized.")

        if one_file:
            yield Progress("assembling", total, total,
                           "Encoding whole-book narration…")
            book_audio = os.path.join(stage_dir, f"book.{audio_ext}")
            audio.concat_to_output(
                book_timeline, book_audio, sr, fmt=audio_fmt, bitrate=bitrate,
                gap=0.0, work_dir=self.cache_dir, metadata=None, cover=None,
                audio_filter=audio_filter, channels=channels, two_pass=two_pass)
            for ep_ch in ep_chapters:
                ep_ch.audio_path = book_audio

        out_path = os.path.join(self.output_dir, f"{base}.epub")
        yield Progress("assembling", total, total, "Packaging EPUB 3 read-along…")
        epub3.build(out_path, chapters=ep_chapters, metadata=metadata,
                    profile=prof, lang=lang, narrator=voice, cover_path=cover)

        # The per-chapter encodes are inside the .epub now.
        shutil.rmtree(stage_dir, ignore_errors=True)
        try:  # drop the shared parent too, once the last book is out of it
            os.rmdir(os.path.dirname(stage_dir))
        except OSError:
            pass

        yield Progress("assembling", total, total, "Validating EPUB…")
        issues, ec_ran = epubcheck.validate(out_path)
        verdict = epubcheck.summarize(issues, ec_ran)
        # Surface the first few problems inline; a broken overlay is invisible
        # until you open the book in a reader, so it's worth being loud here.
        detail = ""
        if issues:
            shown = [str(i) for i in issues[:5]]
            if len(issues) > 5:
                shown.append(f"…and {len(issues) - 5} more")
            detail = "\n  " + "\n  ".join(shown)

        sentences = sum(len(p) for c in ep_chapters for p in c.paragraphs)
        yield Progress("done", total, total,
                       f"Done → {out_path} ({len(ep_chapters)} chapter(s), "
                       f"{sentences} synced sentence(s)) — {verdict}{detail}",
                       output=out_path, preview=None)

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
