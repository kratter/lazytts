"""Assemble per-chunk WAVs into the final audiobook.

Uses ffmpeg's concat demuxer when ffmpeg is available (streams from disk, so
memory stays flat even for 10-hour books). Falls back to a streaming
soundfile writer for WAV output when ffmpeg is missing (MP3 then requires
ffmpeg and raises a clear error).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf

import config


_COVER_FORMATS = {"mp3", "m4a", "aac", "flac"}


def _encoder_args(fmt: str, bitrate: str) -> tuple[list[str], str | None]:
    """Return (ffmpeg output codec args, container '-f' override or None)."""
    if fmt == "mp3":
        return ["-c:a", "libmp3lame", "-b:a", bitrate, "-id3v2_version", "3"], None
    if fmt in ("m4a", "aac"):
        return ["-c:a", "aac", "-b:a", bitrate], "mp4"
    if fmt == "opus":
        return ["-c:a", "libopus", "-b:a", bitrate], "ogg"
    if fmt == "flac":
        return ["-c:a", "flac"], None
    if fmt == "wav24":
        return ["-c:a", "pcm_s24le"], None
    return ["-c:a", "pcm_s16le"], None  # wav


def _twopass_loudnorm(ff: str, list_path: str, audio_filter: str) -> str:
    """Run a loudnorm analysis pass and fold the measured values back into the
    loudnorm token for a more accurate second (linear) pass."""
    m = re.search(r"loudnorm=[^,]*", audio_filter)
    if not m:
        return audio_filter
    ln = m.group(0)
    proc = subprocess.run(
        [ff, "-hide_banner", "-nostats", "-f", "concat", "-safe", "0",
         "-i", list_path, "-af", ln + ":print_format=json", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    txt = proc.stderr or ""
    start, end = txt.rfind("{"), txt.rfind("}")
    if start == -1 or end == -1 or end < start:
        return audio_filter
    try:
        meas = json.loads(txt[start:end + 1])
        ln2 = (ln + f":measured_I={meas['input_i']}:measured_TP={meas['input_tp']}"
               f":measured_LRA={meas['input_lra']}:measured_thresh={meas['input_thresh']}"
               f":offset={meas['target_offset']}:linear=true")
        return audio_filter.replace(ln, ln2)
    except Exception:
        return audio_filter


def ffmpeg_path() -> str | None:
    # A bundled/dropped-in ffmpeg next to the app wins over PATH.
    try:
        import config
        name = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
        local = os.path.join(str(config.BASE_DIR), name)
        if os.path.exists(local):
            return local
    except Exception:
        pass
    return shutil.which("ffmpeg")


def _write_silence(path: str, seconds: float, sample_rate: int) -> None:
    data = np.zeros(int(seconds * sample_rate), dtype=np.float32)
    sf.write(path, data, sample_rate)


def concat_to_output(
    wav_files: list[str],
    out_path: str,
    sample_rate: int,
    *,
    fmt: str = "mp3",
    bitrate: str = "128k",
    gap: float = 0.35,
    work_dir: str,
    metadata: dict | None = None,
    cover: str | None = None,
    audio_filter: str | None = None,
    channels: int = 1,
    two_pass: bool = False,
) -> str:
    if not wav_files:
        raise ValueError("No audio chunks to assemble.")

    os.makedirs(work_dir, exist_ok=True)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)

    ff = ffmpeg_path()
    if ff:
        return _concat_ffmpeg(ff, wav_files, out_path, sample_rate, fmt, bitrate,
                              gap, work_dir, metadata, cover, audio_filter,
                              channels, two_pass)

    if fmt not in ("wav", "wav24"):
        raise RuntimeError(
            f"ffmpeg is required for {fmt.upper()} output but was not found on PATH. "
            "Install ffmpeg or choose WAV output."
        )
    # No ffmpeg: WAV only, with a simple peak normalization if any filter asked.
    return _concat_soundfile(wav_files, out_path, sample_rate, gap,
                             normalize=bool(audio_filter))


def _concat_ffmpeg(ff, wav_files, out_path, sample_rate, fmt, bitrate, gap,
                   work_dir, metadata=None, cover=None, audio_filter=None,
                   channels=1, two_pass=False) -> str:
    silence = None
    if gap > 0:
        silence = os.path.join(work_dir, "_silence.wav")
        _write_silence(silence, gap, sample_rate)

    list_path = os.path.join(work_dir, "_concat.txt")
    with open(list_path, "w", encoding="utf-8") as fh:
        for i, wav in enumerate(wav_files):
            # concat demuxer wants forward slashes and single-quote escaping.
            safe = os.path.abspath(wav).replace("\\", "/").replace("'", "'\\''")
            fh.write(f"file '{safe}'\n")
            if silence and i < len(wav_files) - 1:
                s = os.path.abspath(silence).replace("\\", "/")
                fh.write(f"file '{s}'\n")

    if two_pass and audio_filter and "loudnorm=" in audio_filter:
        audio_filter = _twopass_loudnorm(ff, list_path, audio_filter)

    tag = fmt in config.TAGGABLE_FORMATS
    use_cover = fmt in _COVER_FORMATS and cover and os.path.exists(str(cover))
    codec, container = _encoder_args(fmt, bitrate)

    cmd = [ff, "-y", "-hide_banner", "-loglevel", "error",
           "-f", "concat", "-safe", "0", "-i", list_path]
    if use_cover:
        cmd += ["-i", str(cover)]
    cmd += ["-map", "0:a"]
    if use_cover:
        cmd += ["-map", "1:v", "-c:v", "mjpeg", "-disposition:v", "attached_pic"]
    if audio_filter:
        cmd += ["-af", audio_filter]
    if channels and channels != 1:
        cmd += ["-ac", str(channels)]
    cmd += codec
    if tag:
        for key, value in (metadata or {}).items():
            if value:
                cmd += ["-metadata", f"{key}={value}"]
    if container:
        cmd += ["-f", container]
    cmd += [out_path]

    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed:\n{proc.stderr}")
    return out_path


def wavs_duration(wav_files: list[str], sample_rate: int, gap: float) -> float:
    """Approximate playback seconds of a chapter (chunk audio + inter-chunk gaps)."""
    frames = 0
    for wav in wav_files:
        try:
            frames += sf.info(wav).frames
        except Exception:
            pass
    seconds = frames / float(sample_rate) if sample_rate else 0.0
    if gap > 0 and len(wav_files) > 1:
        seconds += gap * (len(wav_files) - 1)
    return seconds


def write_m3u(path: str, entries: list[tuple[str, str, float]]) -> str:
    """Write an extended M3U playlist.

    *entries* is a list of (relative_filename, title, seconds). Filenames are
    written relative, so the .m3u must live in the same folder as the tracks.
    """
    lines = ["#EXTM3U"]
    for filename, title, seconds in entries:
        lines.append(f"#EXTINF:{int(round(seconds))},{title}")
        lines.append(filename)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return path


def _ffmeta_escape(value: str) -> str:
    out = str(value)
    for ch in ("\\", "=", ";", "#"):
        out = out.replace(ch, "\\" + ch)
    return out.replace("\n", " ")


def _build_ffmetadata(metadata: dict, chapters: list[tuple[str, float, float]]) -> str:
    """Build an ffmetadata document with global tags + [CHAPTER] blocks.

    chapters: list of (title, start_ms, end_ms).
    """
    lines = [";FFMETADATA1", "genre=Audiobook"]
    if metadata.get("title"):
        lines.append(f"title={_ffmeta_escape(metadata['title'])}")
    if metadata.get("album"):
        lines.append(f"album={_ffmeta_escape(metadata['album'])}")
    if metadata.get("author"):
        lines.append(f"artist={_ffmeta_escape(metadata['author'])}")
        lines.append(f"album_artist={_ffmeta_escape(metadata['author'])}")
    for title, start_ms, end_ms in chapters:
        lines += [
            "[CHAPTER]",
            "TIMEBASE=1/1000",
            f"START={int(start_ms)}",
            f"END={int(end_ms)}",
            f"title={_ffmeta_escape(title)}",
        ]
    return "\n".join(lines) + "\n"


def concat_to_m4b(
    wav_files: list[str],
    out_path: str,
    sample_rate: int,
    *,
    chapters: list[tuple[str, float, float]],
    metadata: dict,
    bitrate: str = "128k",
    gap: float = 0.35,
    cover: str | None = None,
    work_dir: str,
    audio_filter: str | None = None,
    channels: int = 1,
    two_pass: bool = False,
) -> str:
    """Assemble a single .m4b (AAC/MP4) with embedded chapters + metadata."""
    ff = ffmpeg_path()
    if not ff:
        raise RuntimeError("ffmpeg is required for M4B output but was not found on PATH.")
    if not wav_files:
        raise ValueError("No audio chunks to assemble.")

    os.makedirs(work_dir, exist_ok=True)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)

    silence = None
    if gap > 0:
        silence = os.path.join(work_dir, "_silence.wav")
        _write_silence(silence, gap, sample_rate)

    list_path = os.path.join(work_dir, "_concat_m4b.txt")
    with open(list_path, "w", encoding="utf-8") as fh:
        for i, wav in enumerate(wav_files):
            safe = os.path.abspath(wav).replace("\\", "/").replace("'", "'\\''")
            fh.write(f"file '{safe}'\n")
            if silence and i < len(wav_files) - 1:
                s = os.path.abspath(silence).replace("\\", "/")
                fh.write(f"file '{s}'\n")

    meta_path = os.path.join(work_dir, "_ffmeta.txt")
    with open(meta_path, "w", encoding="utf-8") as fh:
        fh.write(_build_ffmetadata(metadata, chapters))

    if two_pass and audio_filter and "loudnorm=" in audio_filter:
        audio_filter = _twopass_loudnorm(ff, list_path, audio_filter)

    cmd = [ff, "-y", "-hide_banner", "-loglevel", "error",
           "-f", "concat", "-safe", "0", "-i", list_path,
           "-i", meta_path]
    if cover:
        cmd += ["-i", cover]
    cmd += ["-map", "0:a"]
    if cover:
        cmd += ["-map", "2:v", "-disposition:v", "attached_pic", "-c:v", "mjpeg"]
    if audio_filter:
        cmd += ["-af", audio_filter]
    if channels and channels != 1:
        cmd += ["-ac", str(channels)]
    cmd += ["-map_metadata", "1", "-c:a", "aac", "-b:a", bitrate, "-f", "mp4", out_path]

    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg (m4b) failed:\n{proc.stderr}")
    return out_path


def _concat_soundfile(wav_files, out_path, sample_rate, gap, normalize=False) -> str:
    # Optional peak normalization (ffmpeg-free fallback): scale so the loudest
    # sample across the whole book hits ~-1.5 dBFS.
    scale = 1.0
    if normalize:
        peak = 0.0
        for wav in wav_files:
            try:
                data, _ = sf.read(wav, dtype="float32")
                if data.size:
                    peak = max(peak, float(np.max(np.abs(data))))
            except Exception:
                pass
        if peak > 1e-6:
            scale = (10 ** (-1.5 / 20)) / peak  # target -1.5 dBFS

    silence = np.zeros(int(gap * sample_rate), dtype=np.float32) if gap > 0 else None
    with sf.SoundFile(out_path, "w", samplerate=sample_rate, channels=1, subtype="FLOAT") as out:
        for i, wav in enumerate(wav_files):
            data, _ = sf.read(wav, dtype="float32")
            if data.ndim > 1:
                data = data.mean(axis=1)
            if scale != 1.0:
                data = data * scale
            out.write(data)
            if silence is not None and i < len(wav_files) - 1:
                out.write(silence)
    return out_path
