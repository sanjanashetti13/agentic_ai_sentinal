from app.models.schemas import MeaningfulChangeAssessment, SentinelResult
from app.services.monitoring import MonitoringCheckError, run_monitor_check
from app.storage.database import MonitorStore
from app.tools.page_extract import extract_readable_text, hash_content
from app.tools.web_monitor import WebpageToolError, check_webpage
import httpx
import pytest


def _assessment(
    *,
    meaningful_change: bool,
    summary: str,
    reason: str,
    action_required: bool,
) -> MeaningfulChangeAssessment:
    return MeaningfulChangeAssessment(
        meaningful_change=meaningful_change,
        summary=summary,
        reason=reason,
        action_required=action_required,
    )


def _raise_if_assessed(goal: str, previous_text: str | None, current_text: str | None):
    raise AssertionError("Meaningful-change analysis should not run.")


def _result(text: str, content_hash: str) -> SentinelResult:
    return SentinelResult(
        goal="Tell me if the application deadline changes",
        url="https://example.com",
        summary=text,
        tool_used=True,
        model="openai/gpt-oss-20b",
        content_hash=content_hash,
        page_text=text,
    )


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)


def test_first_check_initializes_without_alert(tmp_path) -> None:
    store = MonitorStore(str(tmp_path / "monitor.db"))
    store.initialize()
    monitor = store.create_monitor("Watch this page.", "https://example.com")
    result = run_monitor_check(
        store,
        monitor["id"],
        run_fn=lambda goal, url: _result("Application deadline: September 14", "hash-a"),
        assess_fn=_raise_if_assessed,
    )
    assert result.change_status == "baseline"
    assert result.status == "initialized"
    assert result.changed is False
    assert result.alert_id is None
    assert store.list_alerts() == []
    stored = store.get_monitor(monitor["id"])
    assert stored is not None
    assert stored["previous_content_hash"] == "hash-a"


def test_same_page_checked_twice_is_unchanged(tmp_path) -> None:
    store = MonitorStore(str(tmp_path / "monitor.db"))
    store.initialize()
    monitor = store.create_monitor("Watch this page.", "https://example.com")
    run_monitor_check(
        store,
        monitor["id"],
        run_fn=lambda goal, url: _result("Application deadline: September 14", "hash-a"),
        assess_fn=_raise_if_assessed,
    )
    second = run_monitor_check(
        store,
        monitor["id"],
        run_fn=lambda goal, url: _result("Application deadline: September 14", "hash-a"),
        assess_fn=_raise_if_assessed,
    )
    assert second.change_status == "unchanged"
    assert second.status == "unchanged"
    assert second.alert_id is None
    assert store.list_alerts() == []


def test_same_page_checked_ten_times_has_zero_alerts(tmp_path) -> None:
    store = MonitorStore(str(tmp_path / "monitor.db"))
    store.initialize()
    monitor = store.create_monitor("Watch this page.", "https://example.com")
    for _ in range(10):
        result = run_monitor_check(
            store,
            monitor["id"],
            run_fn=lambda goal, url: _result(
                "Application deadline: September 14",
                "hash-a",
            ),
            assess_fn=_raise_if_assessed,
        )
        assert result.alert_id is None
        assert result.change_status in {"baseline", "unchanged"}
    assert store.list_alerts() == []


def test_meaningful_text_change_creates_one_alert(tmp_path) -> None:
    store = MonitorStore(str(tmp_path / "monitor.db"))
    store.initialize()
    monitor = store.create_monitor("Watch this page.", "https://example.com")
    run_monitor_check(
        store,
        monitor["id"],
        run_fn=lambda goal, url: _result("Application deadline: September 14", "hash-a"),
        assess_fn=_raise_if_assessed,
    )
    changed = run_monitor_check(
        store,
        monitor["id"],
        run_fn=lambda goal, url: _result("Application deadline: September 18", "hash-b"),
        assess_fn=lambda goal, previous_text, current_text: _assessment(
            meaningful_change=True,
            summary="Application deadline changed from September 14 to September 18.",
            reason="The date changed.",
            action_required=True,
        ),
    )
    assert changed.change_status == "changed"
    assert changed.status == "changed"
    assert changed.alert_id is not None
    assert changed.old_content == "Application deadline: September 14"
    assert changed.new_content == "Application deadline: September 18"
    assert len(store.list_alerts()) == 1


def test_changed_page_checked_again_does_not_duplicate_alert(tmp_path) -> None:
    store = MonitorStore(str(tmp_path / "monitor.db"))
    store.initialize()
    monitor = store.create_monitor("Watch this page.", "https://example.com")
    run_monitor_check(
        store,
        monitor["id"],
        run_fn=lambda goal, url: _result("Application deadline: September 14", "hash-a"),
        assess_fn=_raise_if_assessed,
    )
    run_monitor_check(
        store,
        monitor["id"],
        run_fn=lambda goal, url: _result("Application deadline: September 18", "hash-b"),
        assess_fn=lambda goal, previous_text, current_text: _assessment(
            meaningful_change=True,
            summary="Application deadline changed from September 14 to September 18.",
            reason="The date changed.",
            action_required=True,
        ),
    )
    again = run_monitor_check(
        store,
        monitor["id"],
        run_fn=lambda goal, url: _result("Application deadline: September 18", "hash-b"),
        assess_fn=_raise_if_assessed,
    )
    assert again.change_status == "unchanged"
    assert again.alert_id is None
    assert len(store.list_alerts()) == 1


def test_same_text_different_hash_is_unchanged(tmp_path) -> None:
    store = MonitorStore(str(tmp_path / "monitor.db"))
    store.initialize()
    monitor = store.create_monitor("Watch this page.", "https://example.com")
    run_monitor_check(
        store,
        monitor["id"],
        run_fn=lambda goal, url: _result("Application deadline: September 20", "hash-a"),
        assess_fn=_raise_if_assessed,
    )
    again = run_monitor_check(
        store,
        monitor["id"],
        run_fn=lambda goal, url: _result(
            "Application  deadline: September 20",
            "hash-b",
        ),
        assess_fn=_raise_if_assessed,
    )
    assert again.change_status == "unchanged"
    assert again.alert_id is None
    assert store.list_alerts() == []


def test_irrelevant_dynamic_html_is_unchanged() -> None:
    first = """
    <html><body>
      <script>window.t = 1;</script>
      <nav>Home About</nav>
      <p>Application deadline: September 14</p>
    </body></html>
    """
    second = """
    <html><body>
      <script>window.t = 99;</script>
      <nav>Blog Login</nav>
      <p>Application deadline: September 14</p>
    </body></html>
    """
    _, a = extract_readable_text(first)
    _, b = extract_readable_text(second)
    assert hash_content(a) == hash_content(b)


def test_irrelevant_dynamic_html_through_monitor_has_no_alert(tmp_path) -> None:
    first = """
    <html><body>
      <script>window.t = 1;</script>
      <nav>Home About</nav>
      <p>Application deadline: September 14</p>
    </body></html>
    """
    second = """
    <html><body>
      <script>window.t = 99;</script>
      <nav>Blog Login</nav>
      <p>Application deadline: September 14</p>
    </body></html>
    """
    _, a = extract_readable_text(first)
    _, b = extract_readable_text(second)
    content_hash = hash_content(a)
    assert content_hash == hash_content(b)

    store = MonitorStore(str(tmp_path / "monitor.db"))
    store.initialize()
    monitor = store.create_monitor("Watch this page.", "https://example.com")
    run_monitor_check(
        store,
        monitor["id"],
        run_fn=lambda goal, url: _result(a, content_hash),
        assess_fn=_raise_if_assessed,
    )
    again = run_monitor_check(
        store,
        monitor["id"],
        run_fn=lambda goal, url: _result(b, content_hash),
        assess_fn=_raise_if_assessed,
    )
    assert again.change_status == "unchanged"
    assert again.alert_id is None
    assert store.list_alerts() == []


def test_fetch_failure_after_baseline_does_not_alert_or_overwrite(tmp_path) -> None:
    store = MonitorStore(str(tmp_path / "monitor.db"))
    store.initialize()
    monitor = store.create_monitor("Watch this page.", "https://example.com")
    run_monitor_check(
        store,
        monitor["id"],
        run_fn=lambda goal, url: _result("Application deadline: September 14", "hash-a"),
        assess_fn=_raise_if_assessed,
    )

    def boom(goal: str, url: str) -> SentinelResult:
        raise WebpageToolError("timeout", "The webpage request timed out.")

    failed = run_monitor_check(store, monitor["id"], run_fn=boom)
    assert failed.change_status == "error"
    assert failed.status == "error"
    assert failed.alert_id is None
    assert store.list_alerts() == []
    stored = store.get_monitor(monitor["id"])
    assert stored is not None
    assert stored["previous_content_hash"] == "hash-a"
    assert stored["previous_content"] == "Application deadline: September 14"


def test_error_page_is_not_treated_as_new_content() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html><body>502 Bad Gateway</body></html>")

    try:
        check_webpage("https://example.com/down", client=_client(handler))
        raise AssertionError("Expected WebpageToolError")
    except WebpageToolError as exc:
        assert exc.code == "error_page"


def test_redirect_to_same_content_is_unchanged() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/old":
            return httpx.Response(302, headers={"Location": "https://example.com/new"})
        return httpx.Response(
            200,
            text="<html><body><p>Application deadline: September 14</p></body></html>",
        )

    first = check_webpage("https://example.com/new", client=_client(handler))
    redirected = check_webpage("https://example.com/old", client=_client(handler))
    assert first.content_hash == redirected.content_hash
    assert "September 14" in redirected.text


def test_restart_preserves_snapshot(tmp_path) -> None:
    db_path = str(tmp_path / "monitor.db")
    store = MonitorStore(db_path)
    store.initialize()
    monitor = store.create_monitor("Watch this page.", "https://example.com")
    run_monitor_check(
        store,
        monitor["id"],
        run_fn=lambda goal, url: _result("Application deadline: September 14", "hash-a"),
        assess_fn=_raise_if_assessed,
    )

    restarted = MonitorStore(db_path)
    restarted.initialize()
    again = run_monitor_check(
        restarted,
        monitor["id"],
        run_fn=lambda goal, url: _result("Application deadline: September 14", "hash-a"),
        assess_fn=_raise_if_assessed,
    )
    assert again.change_status == "unchanged"
    assert again.alert_id is None
    stored = restarted.get_monitor(monitor["id"])
    assert stored is not None
    assert stored["previous_content_hash"] == "hash-a"


def _n8n_enabled_website_monitors(payload: dict) -> list[dict]:
    """Same filter as n8n/sentinel-scheduled-checks.json Enabled monitors node."""
    monitors = payload.get("monitors") if isinstance(payload, dict) else []
    if not isinstance(monitors, list):
        return []
    return [
        monitor
        for monitor in monitors
        if monitor
        and monitor.get("enabled") is True
        and monitor.get("kind") != "gmail"
    ]


def test_create_monitor_does_not_fabricate_a_check(tmp_path) -> None:
    store = MonitorStore(str(tmp_path / "monitor.db"))
    store.initialize()
    monitor = store.create_monitor("Watch this page.", "https://example.com")
    assert monitor["enabled"] in {True, 1}
    assert monitor["last_checked_at"] is None
    assert monitor["previous_content_hash"] is None
    assert store.get_latest_observation(monitor["id"]) is None
    assert store.list_alerts() == []


def test_irrelevant_hash_change_does_not_create_alert(tmp_path) -> None:
    store = MonitorStore(str(tmp_path / "monitor.db"))
    store.initialize()
    monitor = store.create_monitor(
        "Tell me if the application deadline changes",
        "https://example.com",
    )
    run_monitor_check(
        store,
        monitor["id"],
        run_fn=lambda goal, url: _result(
            "Application deadline: September 14. Copyright 2025.",
            "hash-a",
        ),
        assess_fn=_raise_if_assessed,
    )
    changed = run_monitor_check(
        store,
        monitor["id"],
        run_fn=lambda goal, url: _result(
            "Application deadline: September 14. Copyright 2026.",
            "hash-b",
        ),
        assess_fn=lambda goal, previous_text, current_text: _assessment(
            meaningful_change=False,
            summary="Only the footer year changed.",
            reason="The deadline is still September 14.",
            action_required=False,
        ),
    )
    assert changed.change_status == "changed"
    assert changed.meaningful_change is False
    assert changed.alert_id is None
    assert store.list_alerts() == []


def test_disabled_monitor_is_not_scheduled() -> None:
    payload = {
        "monitors": [
            {"id": "on", "enabled": True, "kind": "website"},
            {"id": "off", "enabled": False, "kind": "website"},
            {"id": "mail", "enabled": True, "kind": "gmail"},
        ]
    }
    scheduled = _n8n_enabled_website_monitors(payload)
    assert [item["id"] for item in scheduled] == ["on"]


def test_disabled_monitor_check_is_rejected(tmp_path) -> None:
    store = MonitorStore(str(tmp_path / "monitor.db"))
    store.initialize()
    monitor = store.create_monitor("Watch this page.", "https://example.com")
    store.set_enabled(monitor["id"], False)
    try:
        run_monitor_check(
            store,
            monitor["id"],
            run_fn=lambda goal, url: _result("should not run", "hash-x"),
        )
        raise AssertionError("Expected MonitoringCheckError")
    except MonitoringCheckError as exc:
        assert exc.code == "disabled"
    assert store.get_latest_observation(monitor["id"]) is None


def test_multiple_enabled_monitors_are_all_checked(tmp_path) -> None:
    store = MonitorStore(str(tmp_path / "monitor.db"))
    store.initialize()
    first = store.create_monitor("Watch page A.", "https://example.com/a")
    second = store.create_monitor("Watch page B.", "https://example.com/b")
    seen: list[str] = []

    def run(goal: str, url: str) -> SentinelResult:
        seen.append(url)
        return _result(f"content for {url}", f"hash-{url[-1]}")

    payload = {"monitors": [store.get_monitor(first["id"]), store.get_monitor(second["id"])]}
    scheduled = _n8n_enabled_website_monitors(payload)
    assert len(scheduled) == 2
    results = [
        run_monitor_check(
            store,
            item["id"],
            run_fn=run,
            assess_fn=_raise_if_assessed,
        )
        for item in scheduled
    ]
    assert {item.change_status for item in results} == {"baseline"}
    assert store.get_monitor(first["id"])["last_checked_at"] is not None
    assert store.get_monitor(second["id"])["last_checked_at"] is not None
    assert len(seen) == 2


def test_one_failing_monitor_does_not_stop_others(tmp_path) -> None:
    store = MonitorStore(str(tmp_path / "monitor.db"))
    store.initialize()
    failing = store.create_monitor("Watch fail.", "https://example.com/fail")
    ok = store.create_monitor("Watch ok.", "https://example.com/ok")

    def run(goal: str, url: str) -> SentinelResult:
        if url.endswith("/fail"):
            raise WebpageToolError("timeout", "The webpage request timed out.")
        return _result("ok page", "hash-ok")

    outcomes: list[str] = []
    for monitor in [failing, ok]:
        result = run_monitor_check(
            store,
            monitor["id"],
            run_fn=run,
            assess_fn=_raise_if_assessed,
        )
        outcomes.append(result.change_status)
    assert outcomes[0] == "error"
    assert outcomes[1] == "baseline"
    stored_ok = store.get_monitor(ok["id"])
    assert stored_ok is not None
    assert stored_ok["last_checked_at"] is not None
    assert stored_ok["last_change"] == "baseline"


def test_real_public_url_can_be_probed() -> None:
    try:
        result = check_webpage("https://example.com")
    except WebpageToolError as exc:
        pytest.skip(f"Could not reach a public URL: {exc}")
    assert result.status_code == 200
    assert result.content_hash
    assert result.fetch_method in {"http", "browser"}
    assert result.text
    assert "example" in result.text.lower() or "iana" in result.text.lower()


def test_captcha_and_login_pages_are_blocked_without_alert(tmp_path) -> None:
    captcha_html = """
    <html><body>
      <div class="g-recaptcha"></div>
      <p>verify you are human</p>
    </body></html>
    """
    login_html = "<html><body><p>Sign in to continue</p><form>password</form></body></html>"

    def captcha_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=captcha_html)

    def login_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=login_html)

    def render(url: str, timeout: float) -> tuple[int, str, str]:
        raise AssertionError("Must not use Playwright to bypass CAPTCHA or login")

    try:
        check_webpage(
            "https://example.com/captcha",
            client=_client(captcha_handler),
            render_page=render,
        )
        raise AssertionError("Expected WebpageToolError")
    except WebpageToolError as exc:
        assert exc.code == "captcha_required"

    try:
        check_webpage(
            "https://example.com/login",
            client=_client(login_handler),
            render_page=render,
        )
        raise AssertionError("Expected WebpageToolError")
    except WebpageToolError as exc:
        assert exc.code == "authentication_required"

    store = MonitorStore(str(tmp_path / "monitor.db"))
    store.initialize()
    monitor = store.create_monitor("Watch a protected page.", "https://example.com/secure")

    def blocked(goal: str, url: str) -> SentinelResult:
        raise WebpageToolError(
            "captcha_required",
            "A CAPTCHA challenge is present. Sentinel will not bypass it.",
        )

    result = run_monitor_check(store, monitor["id"], run_fn=blocked)
    assert result.change_status == "blocked"
    assert result.alert_id is None
    assert store.list_alerts() == []
    stored = store.get_monitor(monitor["id"])
    assert stored is not None
    assert stored["last_checked_at"] is not None

