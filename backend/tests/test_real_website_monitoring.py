import httpx
import pytest

from app.models.schemas import ActionDecision, MeaningfulChangeAssessment, SentinelResult
from app.services.monitoring import MonitoringCheckError, run_monitor_check
from app.storage.database import MonitorStore
from app.tools.content_diff import extract_goal_match, ground_meaningful_change
from app.tools.errors import WebpageToolError
from app.tools.page_extract import extract_readable_text, hash_content
from app.tools.web_monitor import check_webpage


PASTE_HTML = """
<html>
  <head><title>Untitled - Pastebin.com</title></head>
  <body>
    <header>Pastebin API tools faq paste Login Sign up 4,591 views</header>
    <aside>Public Pastes Other Title 12 min ago</aside>
    <div class="source"><ol><li class="de1">{body}</li></ol></div>
    <footer>privacy cookies</footer>
  </body>
</html>
"""

DEADLINE_HTML = """
<html><body>
  <nav>Home About</nav>
  <p>Application deadline: {date}</p>
</body></html>
"""


def _page(text: str, content_hash: str) -> SentinelResult:
    return SentinelResult(
        goal="goal",
        url="https://example.com/page",
        summary=text,
        tool_used=True,
        model="test",
        content_hash=content_hash,
        page_text=text,
        relevant_excerpt=text,
    )


def _false_assessment(
    goal: str,
    previous_text: str | None,
    current_text: str | None,
) -> MeaningfulChangeAssessment:
    return MeaningfulChangeAssessment(
        meaningful_change=False,
        summary="The model treated this as noise.",
        reason="The model did not treat the watched value as changed.",
        action_required=False,
    )


def _ignore_action(goal: str, analysis: MeaningfulChangeAssessment) -> ActionDecision:
    return ActionDecision(
        action_type="ignore",
        human_loop_state="no_action",
        summary="ignore",
        reason="ignore",
        requires_approval=False,
    )


def _check(tmp_path, goal: str, previous: str, current: str, **kwargs):
    store = MonitorStore(str(tmp_path / "real.db"))
    store.initialize()
    monitor = store.create_monitor(goal, "https://example.com/page")
    run_monitor_check(
        store,
        monitor["id"],
        run_fn=lambda goal, url: _page(previous, hash_content(previous)),
        assess_fn=_false_assessment,
    )
    kwargs.setdefault("action_fn", _ignore_action)
    result = run_monitor_check(
        store,
        monitor["id"],
        run_fn=lambda goal, url: _page(current, hash_content(current)),
        **kwargs,
    )
    return store, result


def test_first_check_is_baseline_without_alert(tmp_path) -> None:
    store = MonitorStore(str(tmp_path / "baseline.db"))
    store.initialize()
    monitor = store.create_monitor("Watch this page.", "https://example.com/page")
    result = run_monitor_check(
        store,
        monitor["id"],
        run_fn=lambda goal, url: _page("hello", "h1"),
        assess_fn=_false_assessment,
    )
    assert result.change_status == "baseline"
    assert result.alert_id is None
    assert store.list_alerts() == []


def test_same_page_is_unchanged_without_alert(tmp_path) -> None:
    store, result = _check(tmp_path, "Watch this page.", "hello", "hello")
    assert result.change_status == "unchanged"
    assert result.alert_id is None
    assert store.list_alerts() == []


def test_generic_meaningful_text_change_alerts(tmp_path) -> None:
    store, result = _check(
        tmp_path,
        "Tell me whenever this webpage changes.",
        "Office hours are Monday.",
        "Office hours are Tuesday.",
        assess_fn=_false_assessment,
    )
    assert result.change_status == "changed"
    assert result.meaningful_change is True
    assert result.alert_id
    assert store.list_alerts()


def test_keyword_appears_creates_alert(tmp_path) -> None:
    store, result = _check(
        tmp_path,
        "Tell me when the update comes with name 'Sanjana'",
        "Update: sunset",
        "Update: Sanjana",
        assess_fn=_false_assessment,
        action_fn=_ignore_action,
    )
    assert result.meaningful_change is True
    assert result.action_required is True
    assert result.alert_id
    assert "Sanjana" in (result.user_notification or "")


def test_keyword_replaced_creates_alert(tmp_path) -> None:
    store, result = _check(
        tmp_path,
        "Tell me when the update comes with name 'Sanjana'",
        "Update: Sanjana",
        "Update: sunset",
        assess_fn=_false_assessment,
        action_fn=_ignore_action,
    )
    assert result.change_status == "changed"
    assert result.meaningful_change is True
    assert result.alert_id
    match = extract_goal_match(
        "Tell me when the update comes with name 'Sanjana'",
        "Update: Sanjana",
        "Update: sunset",
    )
    assert match.signal == "disappeared"
    assert match.previous_contains["Sanjana"] is True
    assert match.current_contains["Sanjana"] is False


def test_unrelated_counter_does_not_alert(tmp_path) -> None:
    store, result = _check(
        tmp_path,
        "Tell me when a new research paper appears",
        "Paper A — 10 submissions",
        "Paper A — 11 submissions",
        assess_fn=_false_assessment,
    )
    assert result.change_status == "changed"
    assert result.meaningful_change is False
    assert result.alert_id is None


def test_new_research_paper_alerts(tmp_path) -> None:
    store, result = _check(
        tmp_path,
        "Tell me when a new research paper appears",
        "Paper A Paper B",
        "Paper A Paper B Paper C",
        assess_fn=_false_assessment,
    )
    assert result.meaningful_change is True
    assert result.alert_id


def test_deadline_change_alerts(tmp_path) -> None:
    store, result = _check(
        tmp_path,
        "Tell me when the application deadline changes.",
        "Deadline: September 30",
        "Deadline: October 15",
        assess_fn=_false_assessment,
    )
    assert result.meaningful_change is True
    assert result.alert_id


def test_fetch_failure_is_not_unchanged(tmp_path) -> None:
    store = MonitorStore(str(tmp_path / "fetch.db"))
    store.initialize()
    monitor = store.create_monitor("Watch this page.", "https://example.com/page")

    def boom(goal: str, url: str) -> SentinelResult:
        raise WebpageToolError("http_error", "Webpage returned HTTP 404.", status_code=404)

    result = run_monitor_check(store, monitor["id"], run_fn=boom)
    assert result.change_status == "error"
    assert result.result_status == "fetch_error"
    assert result.changed is False
    assert result.alert_id is None


def test_analysis_failure_is_not_unchanged(tmp_path) -> None:
    def boom(goal: str, previous_text: str | None, current_text: str | None):
        raise RuntimeError("model timeout")

    store = MonitorStore(str(tmp_path / "analysis.db"))
    store.initialize()
    monitor = store.create_monitor("Track the supplier catalog.", "https://example.com/page")
    run_monitor_check(
        store,
        monitor["id"],
        run_fn=lambda goal, url: _page("Alpha", "h1"),
        assess_fn=_false_assessment,
    )
    with pytest.raises(MonitoringCheckError) as exc:
        run_monitor_check(
            store,
            monitor["id"],
            run_fn=lambda goal, url: _page("Beta", "h2"),
            assess_fn=boom,
        )
    assert exc.value.code == "analysis_error"
    latest = store.get_latest_observation(monitor["id"])
    assert latest is not None
    assert latest["content_hash"] == "h1"


def test_alert_database_failure_is_not_unchanged(tmp_path) -> None:
    store = MonitorStore(str(tmp_path / "persist.db"))
    store.initialize()
    monitor = store.create_monitor(
        "Tell me whenever this webpage changes.",
        "https://example.com/page",
    )
    run_monitor_check(
        store,
        monitor["id"],
        run_fn=lambda goal, url: _page("Monday", hash_content("Monday")),
        assess_fn=_false_assessment,
    )

    def explode(*args, **kwargs):
        raise RuntimeError("disk full")

    store.create_alert = explode  # type: ignore[method-assign]
    with pytest.raises(MonitoringCheckError) as exc:
        run_monitor_check(
            store,
            monitor["id"],
            run_fn=lambda goal, url: _page("Tuesday", hash_content("Tuesday")),
            assess_fn=_false_assessment,
        )
    assert exc.value.code == "alert_persistence_error"


def test_paste_like_html_extracts_body_not_chrome() -> None:
    _, before = extract_readable_text(PASTE_HTML.format(body="Sanjana"))
    _, after = extract_readable_text(PASTE_HTML.format(body="sunset"))
    assert "Sanjana" in before
    assert "sunset" in after
    assert "4,591" not in before
    assert "Public Pastes" not in before
    assert hash_content(before) != hash_content(after)
    grounded = ground_meaningful_change(
        "Tell me when the update comes with name 'Sanjana'",
        before,
        after,
    )
    assert grounded is not None
    assert grounded.meaningful_change is True


def test_fetcher_reads_textarea_and_source_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = "Sanjana" if request.url.path.endswith("/before") else "sunset"
        return httpx.Response(200, text=PASTE_HTML.format(body=body))

    client = httpx.Client(transport=httpx.MockTransport(handler))
    before = check_webpage("https://example.com/before", client=client)
    after = check_webpage("https://example.com/after", client=client)
    assert "Sanjana" in before.text
    assert "sunset" in after.text
    assert before.content_hash != after.content_hash
    assert before.fetch_method == "http"


def test_plain_text_response_is_hashed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text="Update: Sanjana",
            headers={"content-type": "text/plain; charset=utf-8"},
        )

    result = check_webpage(
        "https://example.com/raw",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert "Sanjana" in result.text
    assert result.content_hash == hash_content(result.text)


def test_deadline_html_fixture_is_readable() -> None:
    _, text = extract_readable_text(DEADLINE_HTML.format(date="September 30"))
    assert "September 30" in text
    assert "Home About" not in text


@pytest.mark.network
def test_live_public_webpage_returns_readable_text() -> None:
    """Fetcher must return the document a browser user can read, not only chrome."""
    try:
        observation = check_webpage("https://example.com/")
    except WebpageToolError as exc:
        pytest.skip(f"example.com unavailable: {exc}")
    assert observation.status_code == 200
    assert observation.content_hash
    assert len(observation.text) > 20
    assert observation.fetch_method in {"http", "browser"}
