"""Serve finished read-along EPUBs to devices on the local network.

The Android app (lazyREADER) fetches ``/index.json`` to list what's available,
then downloads a book over ``/books/<name>``. Deliberately tiny and read-only:
no auth, no uploads, LAN scope only, and it only ever exposes ``*.epub`` sitting
directly in the output directory — not the whole folder, which also holds plain
audio exports and per-chapter subfolders.

Runs on a daemon thread so it never blocks app shutdown.
"""
from __future__ import annotations

import json
import os
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse

import config

DEFAULT_PORT = 8765


def lan_address() -> str:
    """Best guess at this machine's LAN IP.

    Opening a UDP socket towards a public address doesn't send anything; it just
    makes the OS pick the interface it would route through, which is the one the
    phone can reach. Falls back to hostname resolution, then loopback.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.settimeout(0.4)
            probe.connect(("8.8.8.8", 80))
            return probe.getsockname()[0]
    except OSError:
        pass
    try:
        return socket.gethostbyname(socket.gethostname())
    except OSError:
        return "127.0.0.1"


def _books(root: str) -> list[dict]:
    out = []
    try:
        entries = sorted(os.scandir(root), key=lambda e: e.name.lower())
    except OSError:
        return out
    for entry in entries:
        if not entry.is_file() or not entry.name.lower().endswith(".epub"):
            continue
        try:
            stat = entry.stat()
        except OSError:
            continue
        out.append({
            "name": os.path.splitext(entry.name)[0],
            "file": entry.name,
            "size": stat.st_size,
            "modified": int(stat.st_mtime),
        })
    return out


class _Handler(BaseHTTPRequestHandler):
    server_version = "lazyTTS-sync"
    root = ""

    def log_message(self, *_args):  # noqa: D102 - quiet; Gradio owns the console
        pass

    def _json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        # The app fetches this from a WebView-less client, but keep it permissive
        # so a browser on the phone can hit it too.
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        path = urlparse(self.path).path

        if path in ("/", "/index.json"):
            self._json({
                "app": "lazytts",
                "version": config.APP_VERSION,
                "books": _books(self.root),
            })
            return

        if path.startswith("/books/"):
            self._serve_book(unquote(path[len("/books/"):]))
            return

        self._json({"error": "not found"}, 404)

    def _serve_book(self, name: str) -> None:
        # basename() alone defeats "../" traversal, and the extension check keeps
        # this to the files the index actually advertises.
        safe = os.path.basename(name)
        if not safe.lower().endswith(".epub"):
            self._json({"error": "not an epub"}, 400)
            return

        full = os.path.join(self.root, safe)
        if not os.path.isfile(full):
            self._json({"error": "not found"}, 404)
            return

        size = os.path.getsize(full)
        self.send_response(200)
        self.send_header("Content-Type", "application/epub+zip")
        self.send_header("Content-Length", str(size))
        self.send_header(
            "Content-Disposition", f'attachment; filename="{safe}"')
        self.end_headers()
        with open(full, "rb") as handle:
            while True:
                chunk = handle.read(262144)
                if not chunk:
                    break
                self.wfile.write(chunk)


class LibraryServer:
    """Start/stop wrapper so the UI can toggle sharing."""

    def __init__(self, root: str | None = None, port: int = DEFAULT_PORT):
        self.root = str(root or config.OUTPUT_DIR)
        self.port = port
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self._httpd is not None

    @property
    def url(self) -> str:
        return f"http://{lan_address()}:{self.port}"

    def start(self) -> str:
        if self._httpd is not None:
            return self.url

        handler = type("_BoundHandler", (_Handler,), {"root": self.root})
        # 0.0.0.0 so the phone can reach it; the port is only open while the
        # user has sharing switched on.
        self._httpd = ThreadingHTTPServer(("0.0.0.0", self.port), handler)
        self._thread = threading.Thread(
            target=self._httpd.serve_forever, name="lazytts-sync", daemon=True)
        self._thread.start()
        return self.url

    def stop(self) -> None:
        if self._httpd is None:
            return
        self._httpd.shutdown()
        self._httpd.server_close()
        self._httpd = None
        self._thread = None


def qr_png(data: str) -> bytes | None:
    """QR for *data* as PNG bytes, or None if the encoder isn't installed.

    Optional on purpose: the URL is shown as text as well, so a missing segno
    only costs the convenience of scanning.
    """
    try:
        import io

        import segno
    except ImportError:
        return None

    buffer = io.BytesIO()
    segno.make(data, error="m").save(buffer, kind="png", scale=6, border=2)
    return buffer.getvalue()
