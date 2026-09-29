"""Local demonstration webpage for Sentinel.

This is a normal HTTP source. Monitoring logic does not special-case it.
"""

from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

DEMO_ROOT = Path(__file__).resolve().parent
PAGES = DEMO_ROOT / "pages"
STATE_PATH = DEMO_ROOT / "state.txt"
DEFAULT_PORT = 8765
VALID_STATES = ("initial", "changed")


def demo_url(port: int = DEFAULT_PORT) -> str:
    return f"http://127.0.0.1:{port}/"


def read_state() -> str:
    if not STATE_PATH.exists():
        return "initial"
    value = STATE_PATH.read_text(encoding="utf-8").strip().lower()
    return value if value in VALID_STATES else "initial"


def write_state(state: str) -> str:
    if state not in VALID_STATES:
        raise ValueError(f"State must be one of {VALID_STATES}.")
    STATE_PATH.write_text(state + "\n", encoding="utf-8")
    return state


def page_path(state: str | None = None) -> Path:
    current = state or read_state()
    return PAGES / f"{current}.html"


def page_html(state: str | None = None) -> str:
    return page_path(state).read_text(encoding="utf-8")


class DemoHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html", "/admissions"):
            html = page_html().encode("utf-8")
            self._send(200, html, "text/html; charset=utf-8")
            return
        if path == "/state":
            payload = json.dumps(
                {"state": read_state(), "url": f"http://{self.headers.get('Host', '127.0.0.1')}/"}
            ).encode("utf-8")
            self._send(200, payload, "application/json")
            return
        if path == "/reset":
            write_state("initial")
            self._send(200, b"initial\n", "text/plain; charset=utf-8")
            return
        if path == "/change":
            write_state("changed")
            self._send(200, b"changed\n", "text/plain; charset=utf-8")
            return
        self._send(404, b"Not found\n", "text/plain; charset=utf-8")


def serve(port: int = DEFAULT_PORT) -> None:
    server = ThreadingHTTPServer(("127.0.0.1", port), DemoHandler)
    print(f"Sentinel demo page: {demo_url(port)}")
    print("GET /reset  -> September 20, 2026")
    print("GET /change -> September 30, 2026")
    print("Current state:", read_state())
    server.serve_forever()


def main() -> int:
    parser = argparse.ArgumentParser(description="Serve the Sentinel demo webpage")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--set", dest="set_state", choices=VALID_STATES)
    parser.add_argument(
        "--serve",
        action="store_true",
        help="Start the local HTTP server (default if --set is omitted)",
    )
    args = parser.parse_args()
    if args.set_state:
        write_state(args.set_state)
        print(f"Demo page set to {args.set_state}")
        if not args.serve:
            return 0
    serve(args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
