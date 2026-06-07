#!/usr/bin/env python3

from __future__ import annotations

import os
import urllib.error
import urllib.parse
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent
DIST_DIR = ROOT_DIR / "dist"
BACKEND_ORIGIN = os.environ.get("LABELSYSTEM_BACKEND_ORIGIN", "http://127.0.0.1:5000").rstrip("/")
PROXY_PREFIXES = (
    "/api/",
    "/demo",
    "/showcase",
    "/_next/",
    "/cvi-api",
    "/cvi-workstation-app",
)
UPSTREAM_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


class LabelSystemProdHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DIST_DIR), **kwargs)

    def do_GET(self) -> None:
        if self._should_proxy():
            self._proxy_request()
            return
        if self._serve_static_fallback():
            return
        super().do_GET()

    def do_HEAD(self) -> None:
        if self._should_proxy():
            self._proxy_request(head_only=True)
            return
        if self._serve_static_fallback(head_only=True):
            return
        super().do_HEAD()

    def do_OPTIONS(self) -> None:
        if self._should_proxy():
            self._proxy_request()
            return
        self.send_response(204)
        self.end_headers()

    def do_POST(self) -> None:
        if self._should_proxy():
            self._proxy_request()
            return
        self.send_error(405, "Method Not Allowed")

    def do_PUT(self) -> None:
        if self._should_proxy():
            self._proxy_request()
            return
        self.send_error(405, "Method Not Allowed")

    def do_PATCH(self) -> None:
        if self._should_proxy():
            self._proxy_request()
            return
        self.send_error(405, "Method Not Allowed")

    def do_DELETE(self) -> None:
        if self._should_proxy():
            self._proxy_request()
            return
        self.send_error(405, "Method Not Allowed")

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def log_message(self, format: str, *args) -> None:
        super().log_message(format, *args)

    def _should_proxy(self) -> bool:
        path = urllib.parse.urlparse(self.path).path
        return any(path == prefix or path.startswith(prefix) for prefix in PROXY_PREFIXES)

    def _serve_static_fallback(self, head_only: bool = False) -> bool:
        parsed = urllib.parse.urlparse(self.path)
        request_path = parsed.path
        if request_path in {"", "/"}:
            return False
        candidate = (DIST_DIR / request_path.lstrip("/")).resolve()
        if candidate.is_file() and DIST_DIR in candidate.parents:
            return False
        if "." in Path(request_path).name:
            return False

        index_path = DIST_DIR / "index.html"
        if not index_path.is_file():
            self.send_error(404, "index.html not found")
            return True

        try:
            body = index_path.read_bytes()
        except OSError:
            self.send_error(500, "Failed to read index.html")
            return True

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if not head_only:
            self.wfile.write(body)
        return True

    def _proxy_request(self, head_only: bool = False) -> None:
        upstream_url = f"{BACKEND_ORIGIN}{self.path}"
        request_headers = {
            key: value
            for key, value in self.headers.items()
            if key.lower() not in {"host", "connection", "content-length"}
        }
        request_headers["Host"] = urllib.parse.urlparse(BACKEND_ORIGIN).netloc
        body = None
        if self.command not in {"GET", "HEAD"}:
            content_length = int(self.headers.get("Content-Length", "0") or "0")
            body = self.rfile.read(content_length) if content_length > 0 else None

        upstream_request = urllib.request.Request(
            upstream_url,
            data=body,
            headers=request_headers,
            method=self.command,
        )
        try:
            with UPSTREAM_OPENER.open(upstream_request, timeout=120) as response:
                payload = b"" if head_only or self.command == "HEAD" else response.read()
                self.send_response(response.status)
                for header, value in response.headers.items():
                    if header.lower() in {"connection", "content-length", "transfer-encoding"}:
                        continue
                    self.send_header(header, value)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                if payload and not head_only:
                    self.wfile.write(payload)
        except urllib.error.HTTPError as exc:
            payload = b"" if head_only or self.command == "HEAD" else exc.read()
            self.send_response(exc.code)
            for header, value in exc.headers.items():
                if header.lower() in {"connection", "content-length", "transfer-encoding"}:
                    continue
                self.send_header(header, value)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            if payload and not head_only:
                self.wfile.write(payload)
        except urllib.error.URLError as exc:
            message = f"Upstream backend unavailable: {exc.reason}".encode("utf-8", errors="ignore")
            self.send_response(502)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(message)))
            self.end_headers()
            if not head_only:
                self.wfile.write(message)


def main() -> None:
    if not DIST_DIR.is_dir():
        raise SystemExit(f"Missing dist directory: {DIST_DIR}")

    port = int(os.environ.get("PORT", "5173"))
    host = os.environ.get("HOST", "0.0.0.0")
    server = ThreadingHTTPServer((host, port), LabelSystemProdHandler)
    print(f"Serving {DIST_DIR} on http://{host}:{port} with backend proxy {BACKEND_ORIGIN}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
