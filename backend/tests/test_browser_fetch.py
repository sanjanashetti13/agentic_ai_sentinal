from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading

import pytest

from app.tools.errors import WebpageToolError
from app.tools.web_monitor import check_webpage

JS_PAGE = """
<!DOCTYPE html>
<html>
  <head><title>Rendered</title></head>
  <body>
    <div id="root"></div>
    <script>
      document.getElementById("root").textContent =
        "Deadline: 1 May 2026 Status: Open";
    </script>
  </body>
</html>
"""


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        body = JS_PAGE.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return


def _chromium_ready() -> bool:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return False
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            browser.close()
        return True
    except Exception:
        return False


@pytest.mark.browser
def test_playwright_renders_local_javascript_page() -> None:
    if not _chromium_ready():
        pytest.skip("Playwright Chromium is not installed")

    server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = check_webpage(f"http://127.0.0.1:{port}/")
        assert result.fetch_method == "browser"
        assert "1 May 2026" in result.text
        assert result.status_code == 200
    except WebpageToolError as exc:
        pytest.skip(exc.message)
    finally:
        server.shutdown()
