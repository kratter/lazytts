"""Write an EPUB 3 with Media Overlays — a read-along ("karaoke") ebook.

The audio is *generated*, so exact sentence timings are already known: no
transcription and no forced alignment, and therefore no drift. Each sentence
becomes a <span id> in the XHTML and a <par> in a per-chapter SMIL file that
points at a time range of that chapter's audio track.

Layout inside the .epub:

    mimetype                     (stored, must be first)
    META-INF/container.xml
    OEBPS/content.opf
    OEBPS/nav.xhtml              EPUB 3 navigation
    OEBPS/toc.ncx                EPUB 2 fallback (profile-dependent)
    OEBPS/style.css              highlight styling for the active sentence
    OEBPS/text/ch001.xhtml
    OEBPS/smil/ch001.smil
    OEBPS/audio/ch001.m4a
"""
from __future__ import annotations

import re
import uuid
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from xml.sax.saxutils import escape, quoteattr

import config

# Audio file extension -> OPF media type.
_AUDIO_TYPES = {
    "mp3": "audio/mpeg",
    "m4a": "audio/mp4",
    "aac": "audio/mp4",
    "opus": "audio/ogg",
    "flac": "audio/flac",
    "wav": "audio/wav",
}

_NS_OPF = "http://www.idpf.org/2007/opf"
_NS_XHTML = "http://www.w3.org/1999/xhtml"
_NS_EPUB = "http://www.idpf.org/2007/ops"
_NS_SMIL = "http://www.w3.org/ns/SMIL"
_NS_NCX = "http://www.daisy.org/z3986/2005/ncx/"


@dataclass
class Word:
    """One word and where it sits in the chapter audio."""
    text: str
    begin: float
    end: float


@dataclass
class Sentence:
    """One highlightable unit: its text and where it sits in the chapter audio."""
    text: str
    begin: float
    end: float
    #: Per-word timings when the engine could report them (Kokoro can). Empty
    #: means sentence-level only, and the export falls back to one <par> per
    #: sentence.
    words: list[Word] = field(default_factory=list)
    #: Optional translation, shown under the sentence in bilingual exports. It
    #: is never narrated and never part of the overlay — the audio stays in the
    #: book's own language.
    translation: str = ""


@dataclass
class Chapter:
    title: str
    paragraphs: list[list[Sentence]] = field(default_factory=list)
    audio_path: str = ""      # absolute path to the assembled audio on disk
    audio_ext: str = "m4a"
    duration: float = 0.0     # narration seconds belonging to this chapter
    # Filename inside OEBPS/audio/. Chapters that share one whole-book track
    # give the same name here; blank means "one file per chapter".
    audio_name: str = ""


def build(out_path: str, *, chapters: list[Chapter], metadata: dict | None = None,
          profile: dict | None = None, lang: str = "en", narrator: str = "",
          cover_path: str | None = None, gloss_lang: str = "") -> str:
    """Package *chapters* into an EPUB 3 with Media Overlays at *out_path*."""
    if not chapters:
        raise ValueError("No chapters to write.")

    prof = dict(config.EPUB3_PROFILES[config.DEFAULT_EPUB3_PROFILE])
    prof.update(profile or {})

    meta = dict(metadata or {})
    title = meta.get("title") or "Audiobook"
    author = meta.get("author") or ""
    book_id = f"urn:uuid:{uuid.uuid4()}"
    modified = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    docs: list[_ChapterFiles] = []
    for i, ch in enumerate(chapters, 1):
        docs.append(_ChapterFiles(ch, i, prof, gloss_lang=gloss_lang))

    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        # "mimetype" must be the first entry and stored uncompressed.
        info = zipfile.ZipInfo("mimetype")
        info.compress_type = zipfile.ZIP_STORED
        zf.writestr(info, "application/epub+zip")

        zf.writestr("META-INF/container.xml", _container_xml())
        zf.writestr("OEBPS/style.css", _stylesheet(prof["active_class"]))
        zf.writestr("OEBPS/nav.xhtml", _nav_xhtml(docs, title, lang))
        if prof["include_ncx"]:
            zf.writestr("OEBPS/toc.ncx", _toc_ncx(docs, title, book_id))

        cover_name = cover_type = None
        if cover_path:
            ext = str(cover_path).rsplit(".", 1)[-1].lower()
            cover_type = {"png": "image/png", "gif": "image/gif",
                          "webp": "image/webp"}.get(ext, "image/jpeg")
            try:
                with open(cover_path, "rb") as fh:
                    data = fh.read()
                cover_name = f"cover.{ext if ext in ('png', 'gif', 'webp') else 'jpg'}"
                zf.writestr(f"OEBPS/{cover_name}", data)
            except OSError:
                cover_name = cover_type = None

        written_audio: set[str] = set()
        for doc in docs:
            zf.writestr(f"OEBPS/{doc.xhtml_href}", doc.xhtml(title, lang))
            zf.writestr(f"OEBPS/{doc.smil_href}", doc.smil())
            # Chapters may share one whole-book track — only store it once.
            if doc.chapter.audio_path and doc.audio_href not in written_audio:
                zf.write(doc.chapter.audio_path, f"OEBPS/{doc.audio_href}")
                written_audio.add(doc.audio_href)

        zf.writestr("OEBPS/content.opf", _opf(
            docs, book_id=book_id, title=title, author=author, lang=lang,
            modified=modified, narrator=narrator, profile=prof,
            cover_name=cover_name, cover_type=cover_type,
        ))

    return out_path


# ── per-chapter file generation ───────────────────────────────────

class _ChapterFiles:
    """Filenames, ids and serialization for one chapter."""

    def __init__(self, chapter: Chapter, index: int, profile: dict,
                 gloss_lang: str = ""):
        self.chapter = chapter
        self.index = index
        self.profile = profile
        self.gloss_lang = gloss_lang
        self.stem = f"ch{index:03d}"
        self.xhtml_href = f"text/{self.stem}.xhtml"
        self.smil_href = f"smil/{self.stem}.smil"
        # A shared whole-book track names itself; otherwise it's per chapter.
        audio_name = chapter.audio_name or f"{self.stem}.{chapter.audio_ext}"
        self.audio_href = f"audio/{audio_name}"
        self.doc_id = f"doc_{self.stem}"
        self.smil_id = f"smil_{self.stem}"
        self.audio_id = "aud_" + re.sub(r"\W+", "_", audio_name.rsplit(".", 1)[0])

    @property
    def title(self) -> str:
        return self.chapter.title or f"Chapter {self.index}"

    def span_id(self, para: int, sent: int) -> str:
        return f"c{self.index}p{para}s{sent}"

    def word_id(self, para: int, sent: int, word: int) -> str:
        return f"{self.span_id(para, sent)}w{word}"

    def _words_enabled(self, sentences: list[Sentence]) -> bool:
        # All or nothing per chapter: mixing word-level and sentence-level <par>s
        # would make some sentences highlight a word at a time and others a whole
        # sentence, which reads as a bug.
        return bool(self.profile.get("word_level")) and all(
            sent.words for sent in sentences
        )

    def xhtml(self, book_title: str, lang: str) -> str:
        lines = [
            '<?xml version="1.0" encoding="utf-8"?>',
            f'<html xmlns="{_NS_XHTML}" xmlns:epub="{_NS_EPUB}" '
            f'xml:lang={quoteattr(lang)} lang={quoteattr(lang)}>',
            "<head>",
            f"  <title>{escape(self.title)}</title>",
            '  <meta charset="utf-8"/>',
            '  <link rel="stylesheet" type="text/css" href="../style.css"/>',
            "</head>",
            "<body>",
            f'<section epub:type="chapter" id="{self.stem}">',
            f'  <h1 class="chapter-title">{escape(self.title)}</h1>',
        ]
        for p, sentences in enumerate(self.chapter.paragraphs, 1):
            words_on = self._words_enabled(sentences)
            spans = " ".join(
                self._sentence_html(p, s, sent, words_on)
                for s, sent in enumerate(sentences, 1)
            )
            lines.append(f'  <p id="{self._para_id(p)}">{spans}</p>')
        lines += ["</section>", "</body>", "</html>", ""]
        return "\n".join(lines)

    def _sentence_html(self, p: int, s: int, sent: Sentence, words_on: bool) -> str:
        """One sentence span, followed by its gloss in a bilingual export."""
        if words_on:
            # Nest a span per word so word-level <par>s have something to point
            # at. The sentence span stays, so readers (and our own app) can
            # still find the whole sentence around a word.
            inner = " ".join(
                f'<span id="{self.word_id(p, s, w)}">{escape(word.text)}</span>'
                for w, word in enumerate(sent.words, 1)
            )
        else:
            inner = escape(sent.text)

        html = f'<span id="{self.span_id(p, s)}">{inner}</span>'
        if sent.translation:
            # Deliberately *outside* the sentence span: inside it, a reader's
            # sentence highlight would cover the translation too, and our own
            # player would take the gloss for part of the narrated text.
            html += (f'<span class="gloss"{self._gloss_lang_attr()}>'
                     f"{escape(sent.translation)}</span>")
        return html

    def _gloss_lang_attr(self) -> str:
        if not self.gloss_lang:
            return ""
        code = quoteattr(self.gloss_lang)
        return f" xml:lang={code} lang={code}"

    def _para_id(self, para: int) -> str:
        return f"c{self.index}p{para}"

    def smil(self) -> str:
        audio_rel = f"../{self.audio_href}"
        text_rel = f"../{self.xhtml_href}"
        use_seq = self.profile["textref_seq"]

        lines = [
            '<?xml version="1.0" encoding="utf-8"?>',
            f'<smil xmlns="{_NS_SMIL}" xmlns:epub="{_NS_EPUB}" version="3.0">',
            "<body>",
        ]
        for p, sentences in enumerate(self.chapter.paragraphs, 1):
            indent = "  "
            if use_seq:
                lines.append(
                    f'  <seq id="seq_{self._para_id(p)}" '
                    f'epub:textref="{text_rel}#{self._para_id(p)}" '
                    f'epub:type="paragraph">'
                )
                indent = "    "
            words_on = self._words_enabled(sentences)
            for s, sent in enumerate(sentences, 1):
                sid = self.span_id(p, s)
                if words_on:
                    # A <seq> per sentence around word-level <par>s: the textref
                    # keeps the sentence addressable, so a reader that wants to
                    # highlight sentences still can, while readers that follow
                    # the <par>s highlight one word at a time.
                    lines.append(
                        f'{indent}<seq id="seq_{sid}" '
                        f'epub:textref="{text_rel}#{sid}" '
                        f'epub:type="sentence">'
                    )
                    for w, word in enumerate(sent.words, 1):
                        wid = self.word_id(p, s, w)
                        lines.append(f'{indent}  <par id="par_{wid}">')
                        lines.append(
                            f'{indent}    <text src="{text_rel}#{wid}"/>'
                        )
                        lines.append(
                            f'{indent}    <audio src="{audio_rel}" '
                            f'clipBegin="{clock(word.begin)}" '
                            f'clipEnd="{clock(word.end)}"/>'
                        )
                        lines.append(f"{indent}  </par>")
                    lines.append(f"{indent}</seq>")
                    continue

                lines.append(f'{indent}<par id="par_{sid}">')
                lines.append(f'{indent}  <text src="{text_rel}#{sid}"/>')
                lines.append(
                    f'{indent}  <audio src="{audio_rel}" '
                    f'clipBegin="{clock(sent.begin)}" clipEnd="{clock(sent.end)}"/>'
                )
                lines.append(f"{indent}</par>")
            if use_seq:
                lines.append("  </seq>")
        lines += ["</body>", "</smil>", ""]
        return "\n".join(lines)


# ── package-level files ───────────────────────────────────────────

def _container_xml() -> str:
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" '
        'version="1.0">\n'
        '  <rootfiles>\n'
        '    <rootfile full-path="OEBPS/content.opf" '
        'media-type="application/oebps-package+xml"/>\n'
        '  </rootfiles>\n'
        '</container>\n'
    )


def _stylesheet(active_class: str) -> str:
    # The reader adds `active_class` to the sentence currently being spoken.
    # Class names are emitted twice (bare + escaped leading dash) because the
    # Readium convention starts with "-", which some engines are picky about.
    cls = active_class.lstrip(".")
    return (
        "body { line-height: 1.6; margin: 1em; }\n"
        ".chapter-title { font-size: 1.4em; margin: 1em 0 0.8em; }\n"
        "p { margin: 0 0 0.9em; text-indent: 0; }\n"
        # The translation reads as an aside, not as part of the prose: set apart
        # on its own line, lighter and a little smaller.
        ".gloss {\n"
        "  display: block;\n"
        "  font-style: italic;\n"
        "  font-size: 0.9em;\n"
        "  opacity: 0.66;\n"
        "  margin: 0.1em 0 0.6em;\n"
        "}\n"
        f".{cls}, span.{cls} {{\n"
        "  background-color: #ffe9a8;\n"
        "  color: inherit;\n"
        "  border-radius: 2px;\n"
        "}\n"
        "@media (prefers-color-scheme: dark) {\n"
        f"  .{cls}, span.{cls} {{ background-color: #5a4a1f; }}\n"
        "}\n"
    )


def _nav_xhtml(docs: list[_ChapterFiles], title: str, lang: str) -> str:
    items = "\n".join(
        f'      <li><a href="{d.xhtml_href}">{escape(d.title)}</a></li>'
        for d in docs
    )
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        f'<html xmlns="{_NS_XHTML}" xmlns:epub="{_NS_EPUB}" '
        f'xml:lang={quoteattr(lang)}>\n'
        "<head>\n"
        f"  <title>{escape(title)}</title>\n"
        '  <meta charset="utf-8"/>\n'
        "</head>\n"
        "<body>\n"
        '  <nav epub:type="toc" id="toc">\n'
        "    <h1>Contents</h1>\n"
        "    <ol>\n"
        f"{items}\n"
        "    </ol>\n"
        "  </nav>\n"
        "</body>\n"
        "</html>\n"
    )


def _toc_ncx(docs: list[_ChapterFiles], title: str, book_id: str) -> str:
    points = []
    for i, d in enumerate(docs, 1):
        points.append(
            f'    <navPoint id="navpoint-{i}" playOrder="{i}">\n'
            f"      <navLabel><text>{escape(d.title)}</text></navLabel>\n"
            f'      <content src="{d.xhtml_href}"/>\n'
            "    </navPoint>"
        )
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        f'<ncx xmlns="{_NS_NCX}" version="2005-1">\n'
        "  <head>\n"
        f'    <meta name="dtb:uid" content="{escape(book_id)}"/>\n'
        '    <meta name="dtb:depth" content="1"/>\n'
        "  </head>\n"
        f"  <docTitle><text>{escape(title)}</text></docTitle>\n"
        "  <navMap>\n"
        + "\n".join(points)
        + "\n  </navMap>\n</ncx>\n"
    )


def _opf(docs: list[_ChapterFiles], *, book_id: str, title: str, author: str,
         lang: str, modified: str, narrator: str, profile: dict,
         cover_name: str | None, cover_type: str | None = None) -> str:
    total = sum(d.chapter.duration for d in docs)

    meta_lines = [
        f'    <dc:identifier id="bookid">{escape(book_id)}</dc:identifier>',
        f"    <dc:title>{escape(title)}</dc:title>",
        f"    <dc:language>{escape(lang)}</dc:language>",
        f'    <meta property="dcterms:modified">{modified}</meta>',
    ]
    if author:
        meta_lines.append(f'    <dc:creator id="author">{escape(author)}</dc:creator>')
    # Total playback time, then one refinement per SMIL document. Both are
    # required by the Media Overlays spec and Readium-based readers use them to
    # show progress before any SMIL is parsed.
    meta_lines.append(f'    <meta property="media:duration">{clock(total)}</meta>')
    for d in docs:
        meta_lines.append(
            f'    <meta refines="#{d.smil_id}" property="media:duration">'
            f"{clock(d.chapter.duration)}</meta>"
        )
    meta_lines.append(
        f'    <meta property="media:active-class">{escape(profile["active_class"])}</meta>'
    )
    if narrator:
        meta_lines.append(
            f'    <meta property="media:narrator">{escape(narrator)}</meta>'
        )
    if cover_name:
        meta_lines.append('    <meta name="cover" content="cover-image"/>')

    manifest = [
        '    <item id="nav" href="nav.xhtml" '
        'media-type="application/xhtml+xml" properties="nav"/>',
        '    <item id="css" href="style.css" media-type="text/css"/>',
    ]
    if profile["include_ncx"]:
        manifest.append(
            '    <item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>'
        )
    if cover_name:
        manifest.append(
            f'    <item id="cover-image" href="{cover_name}" '
            f'media-type="{cover_type or "image/jpeg"}" properties="cover-image"/>'
        )
    seen_audio: set[str] = set()
    for d in docs:
        manifest += [
            f'    <item id="{d.doc_id}" href="{d.xhtml_href}" '
            f'media-type="application/xhtml+xml" media-overlay="{d.smil_id}"/>',
            f'    <item id="{d.smil_id}" href="{d.smil_href}" '
            'media-type="application/smil+xml"/>',
        ]
        # One manifest entry per audio file, even when chapters share a track.
        if d.audio_href not in seen_audio:
            audio_type = _AUDIO_TYPES.get(d.chapter.audio_ext, "audio/mpeg")
            manifest.append(f'    <item id="{d.audio_id}" href="{d.audio_href}" '
                            f'media-type="{audio_type}"/>')
            seen_audio.add(d.audio_href)

    spine_attr = ' toc="ncx"' if profile["include_ncx"] else ""
    spine = "\n".join(f'    <itemref idref="{d.doc_id}"/>' for d in docs)

    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        f'<package xmlns="{_NS_OPF}" version="3.0" unique-identifier="bookid" '
        f'xml:lang={quoteattr(lang)}>\n'
        '  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
        + "\n".join(meta_lines)
        + "\n  </metadata>\n"
        "  <manifest>\n"
        + "\n".join(manifest)
        + "\n  </manifest>\n"
        f"  <spine{spine_attr}>\n"
        + spine
        + "\n  </spine>\n"
        "</package>\n"
    )


def clock(seconds: float) -> str:
    """Format seconds as SMIL/Media-Overlays clock time: H:MM:SS.mmm."""
    ms = max(0, int(round(float(seconds) * 1000)))
    hours, rem = divmod(ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, millis = divmod(rem, 1000)
    return f"{hours}:{minutes:02d}:{secs:02d}.{millis:03d}"
