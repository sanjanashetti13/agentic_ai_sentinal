from pathlib import Path
import sys
import threading
import time

import httpx

from app.tools.web_monitor import check_webpage, hash_content, extract_readable_text

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from demo.serve import (  # noqa: E402
    DemoHandler,
    page_html,
    read_state,
    write_state,
)
from http.server import ThreadingHTTPServer


def test_demo_pages_are_distinct_and_not_empty() -> None:
    initial = page_html("initial")
    changed = page_html("changed")
    assert "September 20, 2026" in initial
    assert "September 30, 2026" in changed
    assert "September 30, 2026" not in initial
    assert "September 20, 2026" not in changed
    _, initial_text = extract_readable_text(initial)
    _, changed_text = extract_readable_text(changed)
    assert hash_content(initial_text) != hash_content(changed_text)


def test_demo_state_switch_is_file_based(tmp_path, monkeypatch) -> None:
    from demo import serve as demo_serve

    state_file = tmp_path / "state.txt"
    monkeypatch.setattr(demo_serve, "STATE_PATH", state_file)
    assert demo_serve.write_state("initial") == "initial"
    assert demo_serve.read_state() == "initial"
    assert demo_serve.write_state("changed") == "changed"
    assert demo_serve.read_state() == "changed"


def test_demo_http_server_serves_and_switches() -> None:
    write_state("initial")
    server = ThreadingHTTPServer(("127.0.0.1", 0), DemoHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        time.sleep(0.15)
        url = f"http://127.0.0.1:{port}/"
        first = check_webpage(url)
        assert "September 20, 2026" in first.text
        httpx.get(f"{url}change", timeout=5)
        second = check_webpage(url)
        assert "September 30, 2026" in second.text
        assert first.content_hash != second.content_hash
        httpx.get(f"{url}reset", timeout=5)
        reset = check_webpage(url)
        assert reset.content_hash == first.content_hash
    finally:
        server.shutdown()
        write_state("initial")


def test_demo_is_not_imported_by_monitoring_logic() -> None:
    monitoring = (REPO / "backend/app/services/monitoring.py").read_text(encoding="utf-8")
    agent = (REPO / "backend/app/agent/sentinel_agent.py").read_text(encoding="utf-8")
    assert "September 20" not in monitoring
    assert "September 30" not in monitoring
    assert "demo/pages" not in agent
    assert "Sentinel Demo Application" not in monitoring
