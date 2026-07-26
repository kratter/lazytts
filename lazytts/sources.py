"""Fetch books/articles into lazyTTS from legal, free sources.

  * Project Gutenberg (public-domain books) via the Gutendex JSON API.
  * Any web article — readable text extracted with BeautifulSoup.

Everything returns a local file the normal pipeline can ingest.
"""
from __future__ import annotations

import json
import os
import re
import urllib.parse
import urllib.request

_UA = {"User-Agent": "Mozilla/5.0 (lazyTTS)"}
_GUTENDEX = "https://gutendex.com/books?search="


def _safe(name: str) -> str:
    return (re.sub(r"[^\w\- ]+", "_", name).strip()[:60] or "book")


def search_gutenberg(query: str, limit: int = 10) -> list[dict]:
    """Search Project Gutenberg. Returns [{id, title, author, epub, txt}]."""
    if not query or not query.strip():
        return []
    req = urllib.request.Request(_GUTENDEX + urllib.parse.quote(query.strip()), headers=_UA)
    with urllib.request.urlopen(req, timeout=40) as r:  # gutendex can be slow
        data = json.loads(r.read().decode("utf-8"))
    out: list[dict] = []
    for b in data.get("results", [])[:limit]:
        fmts = b.get("formats", {}) or {}
        epub = next((u for m, u in fmts.items() if "epub" in m), None)
        txt = next((u for m, u in fmts.items()
                    if m.startswith("text/plain") and not u.endswith(".zip")), None)
        if not (epub or txt):
            continue
        authors = ", ".join(a.get("name", "") for a in b.get("authors", [])) or "Unknown"
        out.append({"id": b.get("id"), "title": b.get("title", "(untitled)"),
                    "author": authors, "epub": epub, "txt": txt})
    return out


def download_book(item: dict, dest_dir: str) -> str:
    """Download a Gutenberg result (epub preferred) into dest_dir; return path."""
    url = item.get("epub") or item.get("txt")
    if not url:
        raise ValueError("No downloadable format for this book.")
    ext = ".epub" if item.get("epub") else ".txt"
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, f"{_safe(item.get('title', 'book'))}{ext}")
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=60) as r, open(dest, "wb") as fh:
        fh.write(r.read())
    return dest


def fetch_article(url: str, dest_dir: str) -> tuple[str, str]:
    """Extract a web article's readable text and save it as a .txt. Returns
    (title, path)."""
    if not url or not url.strip():
        raise ValueError("Enter a URL first.")
    from bs4 import BeautifulSoup

    req = urllib.request.Request(url.strip(), headers=_UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        html = r.read().decode("utf-8", "ignore")
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "nav", "header", "footer", "aside", "form", "noscript"]):
        tag.decompose()
    title = (soup.title.get_text(strip=True) if soup.title else "") or "Article"
    container = soup.find("article") or soup.find("main") or soup
    paras = [p.get_text(" ", strip=True) for p in container.find_all("p")]
    text = "\n\n".join(p for p in paras if len(p) > 40)
    if not text.strip():
        text = soup.get_text("\n", strip=True)
    if not text.strip():
        raise ValueError("Couldn't extract readable text from that page.")

    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, f"{_safe(title)}.txt")
    with open(dest, "w", encoding="utf-8") as fh:
        fh.write(title + "\n\n" + text)
    return title, dest
