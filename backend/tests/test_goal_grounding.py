import httpx

from app.models.schemas import ActionDecision, MeaningfulChangeAssessment, SentinelResult
from app.services.monitoring import run_monitor_check
from app.storage.database import MonitorStore
from app.tools.errors import WebpageToolError
from app.tools.web_monitor import check_webpage, hash_content


def _page(text: str, content_hash: str) -> SentinelResult:
    return SentinelResult(
        goal="goal",
        url="https://example.com/page",
        summary=text,
        tool_used=True,
        model="test",
        content_hash=content_hash,
        page_text=text,
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
    name = str(abs(hash((goal, previous, current))))
    store = MonitorStore(str(tmp_path / f"{name}.db"))
    store.initialize()
    monitor = store.create_monitor(goal, "https://example.com/page")
    run_monitor_check(
        store,
        monitor["id"],
        run_fn=lambda goal, url: _page(previous, "hash-1"),
        assess_fn=_false_assessment,
    )
    kwargs.setdefault("action_fn", _ignore_action)
    result = run_monitor_check(
        store,
        monitor["id"],
        run_fn=lambda goal, url: _page(current, "hash-2"),
        **kwargs,
    )
    return store, result


def test_first_check_is_baseline_without_alert(tmp_path) -> None:
    store = MonitorStore(str(tmp_path / "grounding.db"))
    store.initialize()
    monitor = store.create_monitor(
        "Tell me when the update on this website comes with name 'Sanjana'",
        "https://example.com/page",
    )
    result = run_monitor_check(
        store,
        monitor["id"],
        run_fn=lambda goal, url: _page("Sanjana", "hash-1"),
        assess_fn=_false_assessment,
    )
    assert result.change_status == "baseline"
    assert result.alert_id is None
    assert store.list_alerts() == []


def test_same_content_does_not_alert(tmp_path) -> None:
    store, result = _check(tmp_path, "Watch this page.", "Sanjana", "Sanjana")
    assert result.change_status == "unchanged"
    assert result.alert_id is None
    assert store.list_alerts() == []


def test_replaced_watched_name_alerts_even_if_model_says_no(tmp_path) -> None:
    store, result = _check(
        tmp_path,
        "Tell me when the update on this website comes with name 'Sanjana'",
        "Sanjana",
        "sunset",
        assess_fn=_false_assessment,
        action_fn=_ignore_action,
    )
    assert result.change_status == "changed"
    assert result.meaningful_change is True
    assert result.action_required is True
    assert result.alert_id
    assert len(store.list_alerts()) == 1


def test_watched_keyword_appearing_alerts(tmp_path) -> None:
    store, result = _check(
        tmp_path,
        "Tell me when the update contains 'Sanjana'",
        "Status: waiting",
        "Status: Sanjana joined",
        assess_fn=_false_assessment,
    )
    assert result.meaningful_change is True
    assert result.alert_id


def test_model_failure_still_alerts_when_watched_value_is_replaced(tmp_path) -> None:
    def boom(goal: str, previous_text: str | None, current_text: str | None):
        raise RuntimeError("rate limit")

    store, result = _check(
        tmp_path,
        "Tell me when the update on this website comes with name 'Sanjana'",
        "Sanjana",
        "sunset",
        assess_fn=boom,
    )
    assert result.meaningful_change is True
    assert result.action_required is True
    assert result.alert_id
    assert store.list_alerts()[0]["status"] == "pending"


def test_unrelated_counter_does_not_alert(tmp_path) -> None:
    store, result = _check(
        tmp_path,
        "Tell me when a new research paper appears.",
        "Paper: Attention Is All You Need. 12 likes",
        "Paper: Attention Is All You Need. 13 likes",
        assess_fn=_false_assessment,
    )
    assert result.change_status == "changed"
    assert result.meaningful_change is False
    assert result.alert_id is None
    assert store.list_alerts() == []


def test_new_paper_title_alerts(tmp_path) -> None:
    store, result = _check(
        tmp_path,
        "Tell me when a new research paper appears.",
        "Paper: Attention Is All You Need. 12 likes",
        "Paper: Attention Is All You Need. Paper: A New Result. 12 likes",
        assess_fn=_false_assessment,
    )
    assert result.meaningful_change is True
    assert result.alert_id


def test_deadline_change_alerts_and_visitor_count_does_not(tmp_path) -> None:
    store, changed = _check(
        tmp_path,
        "Tell me when the application deadline changes.",
        "Application deadline: September 20, 2026. 40 visitors",
        "Application deadline: September 30, 2026. 40 visitors",
        assess_fn=_false_assessment,
    )
    assert changed.meaningful_change is True
    assert changed.alert_id

    store, noise = _check(
        tmp_path,
        "Tell me when the application deadline changes.",
        "Application deadline: September 20, 2026. 40 visitors",
        "Application deadline: September 20, 2026. 90 visitors",
        assess_fn=_false_assessment,
    )
    assert noise.meaningful_change is False
    assert noise.alert_id is None
    assert store.list_alerts() == []


def test_broad_page_change_alerts_but_counter_only_does_not(tmp_path) -> None:
    store, changed = _check(
        tmp_path,
        "Tell me whenever this webpage changes.",
        "Office hours are Monday.",
        "Office hours are Tuesday.",
        assess_fn=_false_assessment,
    )
    assert changed.meaningful_change is True
    assert changed.alert_id

    store, noise = _check(
        tmp_path,
        "Tell me whenever this webpage changes.",
        "Office hours are Monday. 4 likes",
        "Office hours are Monday. 9 likes",
        assess_fn=_false_assessment,
    )
    assert noise.meaningful_change is False
    assert store.list_alerts() == []


def test_captcha_check_does_not_create_an_alert(tmp_path) -> None:
    store = MonitorStore(str(tmp_path / "grounding.db"))
    store.initialize()
    monitor = store.create_monitor("Watch this page.", "https://example.com/captcha")

    def blocked(goal: str, url: str) -> SentinelResult:
        raise WebpageToolError(
            "captcha_required",
            "A CAPTCHA challenge is present. Sentinel will not bypass it.",
        )

    result = run_monitor_check(store, monitor["id"], run_fn=blocked)
    assert result.change_status == "blocked"
    assert result.alert_id is None
    assert store.list_alerts() == []


def test_readable_page_body_is_what_gets_hashed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = "Sanjana" if request.url.path.endswith("/before") else "sunset"
        html = f"<html><body><textarea>{body}</textarea><p>12 visitors</p></body></html>"
        return httpx.Response(200, text=html)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    before = check_webpage("https://example.com/before", client=client)
    after = check_webpage("https://example.com/after", client=client)
    assert "Sanjana" in before.text
    assert "sunset" in after.text
    assert before.content_hash == hash_content(before.text)
    assert before.content_hash != after.content_hash
