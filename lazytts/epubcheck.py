"""Validate a generated EPUB, in two layers.

`check_structure` is pure Python and always runs. It verifies the things a
read-along actually depends on: that every SMIL text reference resolves to a
real span, that clip ranges are sane and ordered, and that the manifest wiring
between XHTML, SMIL and audio is complete. A dangling reference here is the
difference between "highlighting works" and "reader silently ignores the
overlay", and it is exactly what a hand-rolled writer gets wrong.

`run_epubcheck` shells out to the official EPUBCheck for full spec conformance.
That is a Java tool, which this app can't assume is installed, so it is used
when present and skipped otherwise. To enable it, drop `epubcheck.jar` next to
the app (like ffmpeg), set EPUBCHECK_JAR, or put `epubcheck` on PATH.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import zipfile
from dataclasses import dataclass
from xml.etree import ElementTree as ET

import config

_NS = {
    "opf": "http://www.idpf.org/2007/opf",
    "smil": "http://www.w3.org/ns/SMIL",
    "xhtml": "http://www.w3.org/1999/xhtml",
    "container": "urn:oasis:names:tc:opendocument:xmlns:container",
}

# Tolerated drift between a chapter's declared media:duration and the last
# clipEnd in its SMIL. They're derived from the same frame counts, so this is
# only a guard against arithmetic mistakes, not encoder padding.
_DURATION_TOLERANCE = 1.0


@dataclass
class Issue:
    level: str      # "error" | "warning"
    message: str

    def __str__(self) -> str:
        return f"{self.level.upper()}: {self.message}"


def validate(epub_path: str) -> tuple[list[Issue], bool | None]:
    """Structural check, plus EPUBCheck when available.

    Returns (issues, epubcheck_ran) where epubcheck_ran is None if the official
    validator wasn't found.
    """
    issues = check_structure(epub_path)
    ran, ec_issues = run_epubcheck(epub_path)
    return issues + ec_issues, ran


# ── built-in structural validation ────────────────────────────────

def check_structure(epub_path: str) -> list[Issue]:
    issues: list[Issue] = []
    err = lambda m: issues.append(Issue("error", m))       # noqa: E731
    warn = lambda m: issues.append(Issue("warning", m))    # noqa: E731

    try:
        zf = zipfile.ZipFile(epub_path)
    except (OSError, zipfile.BadZipFile) as exc:
        return [Issue("error", f"not a readable zip: {exc}")]

    with zf:
        names = zf.namelist()

        # 1. mimetype: first entry, uncompressed, exact content.
        if not names or names[0] != "mimetype":
            err("'mimetype' must be the first entry in the archive")
        else:
            if zf.getinfo("mimetype").compress_type != zipfile.ZIP_STORED:
                err("'mimetype' must be stored uncompressed")
            if zf.read("mimetype") != b"application/epub+zip":
                err("'mimetype' content must be exactly 'application/epub+zip'")

        # 2. every XML file must parse.
        trees: dict[str, ET.Element] = {}
        for name in names:
            if name.endswith((".xhtml", ".opf", ".smil", ".ncx", ".xml")):
                try:
                    trees[name] = ET.fromstring(zf.read(name))
                except ET.ParseError as exc:
                    err(f"{name}: malformed XML ({exc})")

        # 3. container -> rootfile -> OPF.
        opf_name = None
        container = trees.get("META-INF/container.xml")
        if container is None:
            err("missing META-INF/container.xml")
        else:
            rootfile = container.find(".//container:rootfile", _NS)
            if rootfile is None:
                err("container.xml has no <rootfile>")
            else:
                opf_name = rootfile.get("full-path")
                if opf_name not in names:
                    err(f"container.xml points at missing rootfile '{opf_name}'")
                    opf_name = None

        if opf_name is None or opf_name not in trees:
            return issues  # nothing further is checkable

        opf = trees[opf_name]
        opf_dir = os.path.dirname(opf_name)

        def resolve(href: str, base_dir: str) -> str:
            """Zip path for an href relative to base_dir."""
            joined = os.path.normpath(os.path.join(base_dir, href.split("#")[0]))
            return joined.replace("\\", "/")

        # 4. manifest hrefs exist; collect id -> (href, zip path, media-overlay).
        manifest: dict[str, dict] = {}
        for item in opf.findall(".//opf:manifest/opf:item", _NS):
            item_id = item.get("id") or ""
            href = item.get("href") or ""
            path = resolve(href, opf_dir)
            if path not in names:
                err(f"manifest item '{item_id}' points at missing file '{href}'")
            manifest[item_id] = {
                "href": href, "path": path,
                "overlay": item.get("media-overlay"),
                "type": item.get("media-type") or "",
            }

        # 5. spine idrefs exist in the manifest.
        spine_ids = []
        for ref in opf.findall(".//opf:spine/opf:itemref", _NS):
            idref = ref.get("idref") or ""
            spine_ids.append(idref)
            if idref not in manifest:
                err(f"spine references unknown manifest id '{idref}'")
        if not spine_ids:
            err("spine is empty")

        # 6. media:duration metadata (total + one refinement per overlay).
        durations: dict[str, float] = {}
        total_declared = None
        for meta in opf.findall(".//opf:metadata/opf:meta", _NS):
            if meta.get("property") != "media:duration":
                continue
            value = parse_clock((meta.text or "").strip())
            refines = meta.get("refines")
            if refines:
                durations[refines.lstrip("#")] = value
            else:
                total_declared = value
        overlay_ids = {m["overlay"] for m in manifest.values() if m["overlay"]}
        if overlay_ids and total_declared is None:
            err("missing total <meta property=\"media:duration\">")
        for smil_id in sorted(overlay_ids):
            if smil_id not in durations:
                err(f"missing media:duration refinement for overlay '{smil_id}'")

        if not overlay_ids:
            warn("no media-overlay declared — this EPUB will not read along")

        # 7. the overlay chain: XHTML -> SMIL -> spans + audio.
        for doc_id in spine_ids:
            item = manifest.get(doc_id)
            if not item or not item["overlay"]:
                continue
            smil_id = item["overlay"]
            smil_item = manifest.get(smil_id)
            if not smil_item:
                err(f"'{doc_id}' declares media-overlay '{smil_id}' "
                    "which is not in the manifest")
                continue
            smil_path = smil_item["path"]
            smil_tree = trees.get(smil_path)
            if smil_tree is None:
                continue  # already reported as missing/malformed

            # ids available in the narrated document
            doc_tree = trees.get(item["path"])
            doc_ids: set[str] = set()
            if doc_tree is not None:
                doc_ids = {el.get("id") for el in doc_tree.iter() if el.get("id")}

            smil_dir = os.path.dirname(smil_path)
            last_end = -1.0
            pars = smil_tree.findall(".//smil:par", _NS)
            if not pars:
                err(f"{smil_path}: contains no <par> elements")

            for par in pars:
                text_el = par.find("smil:text", _NS)
                audio_el = par.find("smil:audio", _NS)
                par_id = par.get("id") or "<unnamed par>"

                if text_el is None:
                    err(f"{smil_path}: <par {par_id}> has no <text>")
                else:
                    src = text_el.get("src") or ""
                    target, _, frag = src.partition("#")
                    target_path = resolve(target, smil_dir)
                    if target_path not in names:
                        err(f"{smil_path}: <par {par_id}> text points at "
                            f"missing file '{target}'")
                    elif target_path != item["path"]:
                        warn(f"{smil_path}: <par {par_id}> text points outside "
                             f"its own document ('{target}')")
                    elif not frag:
                        err(f"{smil_path}: <par {par_id}> text src has no fragment id")
                    elif frag not in doc_ids:
                        err(f"{smil_path}: <par {par_id}> references id '{frag}' "
                            f"which does not exist in {item['href']}")

                if audio_el is None:
                    err(f"{smil_path}: <par {par_id}> has no <audio>")
                    continue
                audio_src = audio_el.get("src") or ""
                audio_path = resolve(audio_src, smil_dir)
                if audio_path not in names:
                    err(f"{smil_path}: <par {par_id}> audio points at missing "
                        f"file '{audio_src}'")
                begin = parse_clock(audio_el.get("clipBegin"))
                end = parse_clock(audio_el.get("clipEnd"))
                if end <= begin:
                    err(f"{smil_path}: <par {par_id}> has empty or reversed clip "
                        f"({audio_el.get('clipBegin')} -> {audio_el.get('clipEnd')})")
                elif begin < last_end - 1e-6:
                    err(f"{smil_path}: <par {par_id}> clip overlaps the previous "
                        f"one (starts {begin:.3f}s, previous ended {last_end:.3f}s)")
                last_end = max(last_end, end)

            declared = durations.get(smil_id)
            if declared is not None and last_end > 0:
                if abs(declared - last_end) > _DURATION_TOLERANCE:
                    warn(f"{smil_path}: media:duration is {declared:.3f}s but the "
                         f"last clip ends at {last_end:.3f}s")

    return issues


def parse_clock(value: str | None) -> float:
    """Parse a SMIL clock value into seconds. Returns 0.0 if unparseable.

    Accepts the forms Media Overlays allows: 'H:MM:SS.mmm', 'MM:SS', '12.5s',
    '500ms', '1.5min', '1h' and a bare number of seconds.
    """
    if not value:
        return 0.0
    text = value.strip()
    if ":" in text:
        parts = text.split(":")
        try:
            nums = [float(p) for p in parts]
        except ValueError:
            return 0.0
        seconds = 0.0
        for num in nums:
            seconds = seconds * 60 + num
        return seconds
    match = re.fullmatch(r"([0-9]*\.?[0-9]+)\s*(ms|s|min|h)?", text)
    if not match:
        return 0.0
    amount = float(match.group(1))
    unit = match.group(2) or "s"
    return amount * {"ms": 0.001, "s": 1.0, "min": 60.0, "h": 3600.0}[unit]


# ── official EPUBCheck (optional, needs Java) ─────────────────────

def epubcheck_command() -> list[str] | None:
    """Command prefix to invoke EPUBCheck, or None if it isn't available.

    Mirrors how ffmpeg is located: something dropped in next to the app wins
    over PATH, so an offline install can ship its own copy.
    """
    base = str(config.BASE_DIR)

    # A launcher script/binary next to the app.
    for name in ("epubcheck.bat", "epubcheck.cmd", "epubcheck.exe", "epubcheck"):
        local = os.path.join(base, name)
        if os.path.isfile(local):
            return [local]

    # A jar next to the app, or pointed at by EPUBCHECK_JAR.
    jars = [os.path.join(base, "epubcheck.jar")]
    env_jar = os.environ.get("EPUBCHECK_JAR")
    if env_jar:
        jars.insert(0, env_jar)
    java = shutil.which("java")
    for jar in jars:
        if os.path.isfile(jar):
            if not java:
                return None  # jar present but no Java to run it
            return [java, "-jar", jar]

    # A launcher already on PATH.
    found = shutil.which("epubcheck")
    if found:
        return [found]
    return None


# EPUBCheck writes lines like:
#   ERROR(RSC-005): book.epub/OEBPS/content.opf(2,58): error detail
_EC_LINE = re.compile(r"^(FATAL|ERROR|WARNING)\b[^:]*:\s*(.*)$")


def run_epubcheck(epub_path: str, timeout: float = 180.0) -> tuple[bool | None, list[Issue]]:
    """Run EPUBCheck if installed.

    Returns (ran, issues). `ran` is None when EPUBCheck isn't available, True
    when it completed, False when it was found but failed to execute.
    """
    cmd = epubcheck_command()
    if not cmd:
        return None, []
    try:
        proc = subprocess.run(cmd + [epub_path], capture_output=True,
                              text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, [Issue("warning", f"EPUBCheck could not be run: {exc}")]

    issues: list[Issue] = []
    for line in (proc.stderr or "").splitlines() + (proc.stdout or "").splitlines():
        match = _EC_LINE.match(line.strip())
        if not match:
            continue
        level = "error" if match.group(1) in ("FATAL", "ERROR") else "warning"
        issues.append(Issue(level, f"EPUBCheck {match.group(1)}: {match.group(2)}"))

    # Non-zero exit with nothing parsed still means something went wrong.
    if proc.returncode != 0 and not issues:
        detail = ((proc.stderr or proc.stdout or "").strip().splitlines() or [""])[-1]
        issues.append(Issue("error",
                            f"EPUBCheck exited {proc.returncode}: {detail}"))
    return True, issues


def summarize(issues: list[Issue], epubcheck_ran: bool | None) -> str:
    """One-line result suitable for the progress/status area."""
    errors = [i for i in issues if i.level == "error"]
    warnings = [i for i in issues if i.level == "warning"]
    if epubcheck_ran:
        who = "EPUBCheck + structure"
    elif epubcheck_ran is False:
        who = "structure (EPUBCheck failed to run)"
    else:
        who = "structure (EPUBCheck not installed)"
    if not issues:
        return f"validation passed [{who}]"
    parts = []
    if errors:
        parts.append(f"{len(errors)} error(s)")
    if warnings:
        parts.append(f"{len(warnings)} warning(s)")
    return f"validation found {' and '.join(parts)} [{who}]"
