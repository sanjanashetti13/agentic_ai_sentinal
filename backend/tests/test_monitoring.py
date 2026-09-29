from types import SimpleNamespace
import json

from app.agent.sentinel_agent import run_sentinel
from app.models.schemas import MeaningfulChangeAssessment, SentinelResult
from app.services.monitoring import MonitoringCheckError, run_monitor_check
from app.storage.database import MonitorStore


def _result(
    summary: str,
    content_hash: str,
    tool_error: str | None = None,
    page_text: str | None = None,
) -> SentinelResult:
    return SentinelResult(
        goal="Tell me if the application deadline changes",
        url="https://example.com",
        summary=summary,
        tool_used=tool_error is None,
        model="openai/gpt-oss-20b",
        content_hash=None if tool_error else content_hash,
        tool_error=tool_error,
        page_text=page_text,
    )


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


def test_first_check_is_baseline(tmp_path) -> None:
    store = MonitorStore(str(tmp_path / "monitoring.db"))
    store.initialize()
    monitor = store.create_monitor(
        "Tell me if the application deadline changes",
        "https://example.com",
    )

    result = run_monitor_check(
        store,
        monitor["id"],
        run_fn=lambda goal, url: _result(
            "Deadline is 1 May 2026.",
            "hash-1",
            page_text="Deadline: 1 May 2026",
        ),
        assess_fn=_raise_if_assessed,
    )

    assert result.change_status == "baseline"
    assert result.changed is False
    assert result.tool_used is True
    assert result.meaningful_change is None
    assert result.reason is None
    assert result.action_required is None
    assert result.agents == ["supervisor", "monitoring"]
    assert [item.agent for item in result.agent_trace] == ["monitoring", "supervisor"]
    latest = store.get_latest_observation(monitor["id"])
    assert latest is not None
    assert latest["content_hash"] == "hash-1"
    assert latest["summary"] == "Deadline is 1 May 2026."
    assert latest["meaningful_change"] is None
    monitor_after = store.get_monitor(monitor["id"])
    assert monitor_after is not None
    assert monitor_after["previous_content"] == "Deadline: 1 May 2026"


def test_second_check_unchanged_hash(tmp_path) -> None:
    store = MonitorStore(str(tmp_path / "monitoring.db"))
    store.initialize()
    monitor = store.create_monitor("Watch this page.", "https://example.com")
    run_monitor_check(
        store,
        monitor["id"],
        run_fn=lambda goal, url: _result("Same page.", "hash-1", page_text="Same page"),
        assess_fn=_raise_if_assessed,
    )

    result = run_monitor_check(
        store,
        monitor["id"],
        run_fn=lambda goal, url: _result(
            "Still the same page.",
            "hash-1",
            page_text="Same page",
        ),
        assess_fn=_raise_if_assessed,
    )

    assert result.change_status == "unchanged"
    assert result.changed is False
    assert result.previous_checked_at is not None
    assert result.meaningful_change is None
    assert result.action_required is None
    assert result.summary == "No meaningful change detected."
    assert result.agents == ["supervisor", "monitoring"]
    assert len(store.list_observations(monitor["id"])) == 2


def test_second_check_changed_hash(tmp_path) -> None:
    store = MonitorStore(str(tmp_path / "monitoring.db"))
    store.initialize()
    monitor = store.create_monitor("Watch this page.", "https://example.com")
    run_monitor_check(
        store,
        monitor["id"],
        run_fn=lambda goal, url: _result(
            "Deadline is 1 May 2026.",
            "hash-1",
            page_text="Deadline: 1 May 2026",
        ),
        assess_fn=_raise_if_assessed,
    )

    result = run_monitor_check(
        store,
        monitor["id"],
        run_fn=lambda goal, url: _result(
            "Deadline is now 15 May 2026.",
            "hash-2",
            page_text="Deadline: 15 May 2026",
        ),
        assess_fn=lambda goal, previous_text, current_text: _assessment(
            meaningful_change=True,
            summary="The deadline changed to 15 May 2026.",
            reason="The date in the current page differs from the previous page.",
            action_required=True,
        ),
    )

    assert result.change_status == "changed"
    assert result.changed is True
    assert result.meaningful_change is True
    assert result.action_required is True
    assert "15 May" in result.summary
    latest = store.get_latest_observation(monitor["id"])
    assert latest is not None
    assert latest["content_hash"] == "hash-2"
    assert latest["meaningful_change"] is True
    assert latest["action_required"] is True
    assert result.agents == ["supervisor", "monitoring", "analysis", "action"]
    assert [item.agent for item in result.agent_trace] == [
        "monitoring",
        "analysis",
        "action",
        "supervisor",
    ]
    assert result.agent_trace[0].summary.startswith("Fetched the source.")
    assert result.agent_trace[2].summary == "notify_user"


def test_tool_failure_records_error_without_replacing_hash(tmp_path) -> None:
    store = MonitorStore(str(tmp_path / "monitoring.db"))
    store.initialize()
    monitor = store.create_monitor("Watch this page.", "https://example.com")
    run_monitor_check(
        store,
        monitor["id"],
        run_fn=lambda goal, url: _result("Deadline is 1 May 2026.", "hash-1"),
    )

    result = run_monitor_check(
        store,
        monitor["id"],
        run_fn=lambda goal, url: _result(
            "Could not retrieve the page.",
            "ignored",
            tool_error="Could not connect to the webpage.",
        ),
    )

    assert result.change_status == "error"
    assert result.alert_id is None
    assert store.list_alerts() == []
    latest = store.get_latest_observation(monitor["id"])
    assert latest is not None
    assert latest["change_status"] == "error"
    assert "connect" in latest["summary"]
    monitor_after = store.get_monitor(monitor["id"])
    assert monitor_after is not None
    assert monitor_after["previous_content_hash"] == "hash-1"
    assert monitor_after["last_change"] == "error"
    assert monitor_after["last_checked_at"] is not None
    assert len(store.list_observations(monitor["id"])) == 2


def test_missing_monitor_raises_key_error(tmp_path) -> None:
    store = MonitorStore(str(tmp_path / "monitoring.db"))
    store.initialize()
    try:
        run_monitor_check(store, "missing")
        raise AssertionError("Expected KeyError")
    except KeyError:
        pass


def _strands_result(
    content_hash: str,
    summary: str,
    text: str = "Example Domain",
) -> SentinelResult:
    payload = {
        "url": "https://example.com",
        "status_code": 200,
        "title": "Example",
        "text": text,
        "content_hash": content_hash,
        "fetched_at": "2026-09-08T05:00:00+00:00",
    }

    class StubAgent:
        messages = [
            {
                "role": "assistant",
                "content": [
                    {
                        "toolUse": {
                            "name": "check_webpage",
                            "toolUseId": "tool-1",
                            "input": {"url": "https://example.com"},
                        }
                    }
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "toolResult": {
                            "toolUseId": "tool-1",
                            "status": "success",
                            "content": [{"text": json.dumps(payload)}],
                        }
                    }
                ],
            },
            {"role": "assistant", "content": [{"text": summary}]},
        ]

        def __call__(self, prompt: str):
            return SimpleNamespace(message=self.messages[-1])

    return run_sentinel(
        "Tell me if an application deadline changes",
        "https://example.com",
        agent=StubAgent(),
    )


def test_run_sentinel_hash_reaches_monitoring_baseline(tmp_path) -> None:
    store = MonitorStore(str(tmp_path / "monitoring.db"))
    store.initialize()
    monitor = store.create_monitor(
        "Tell me if an application deadline changes",
        "https://example.com",
    )

    result = run_monitor_check(
        store,
        monitor["id"],
        run_fn=lambda goal, url: _strands_result("hash-live-1", "No deadline found."),
        assess_fn=_raise_if_assessed,
    )

    assert result.change_status == "baseline"
    assert result.changed is False
    assert result.tool_used is True
    latest = store.get_latest_observation(monitor["id"])
    assert latest is not None
    assert latest["content_hash"] == "hash-live-1"


def test_run_sentinel_hash_reaches_monitoring_unchanged_and_changed(tmp_path) -> None:
    store = MonitorStore(str(tmp_path / "monitoring.db"))
    store.initialize()
    monitor = store.create_monitor("Watch this page.", "https://example.com")

    unchanged = run_monitor_check(
        store,
        monitor["id"],
        run_fn=lambda goal, url: _strands_result("same-hash", "Same page."),
        assess_fn=_raise_if_assessed,
    )
    assert unchanged.change_status == "baseline"
    assert unchanged.meaningful_change is None

    same = run_monitor_check(
        store,
        monitor["id"],
        run_fn=lambda goal, url: _strands_result("same-hash", "Still the same."),
        assess_fn=_raise_if_assessed,
    )
    assert same.change_status == "unchanged"
    assert same.changed is False
    assert same.meaningful_change is None

    different = run_monitor_check(
        store,
        monitor["id"],
        run_fn=lambda goal, url: _strands_result(
            "new-hash",
            "The page changed.",
            text="Deadline: 15 May 2026",
        ),
        assess_fn=lambda goal, previous_text, current_text: _assessment(
            meaningful_change=False,
            summary="The page changed, but not in a way that affects the goal.",
            reason="The excerpts do not show a change related to the monitoring goal.",
            action_required=False,
        ),
    )
    assert different.change_status == "changed"
    assert different.changed is True
    assert different.meaningful_change is False
    latest = store.get_latest_observation(monitor["id"])
    assert latest is not None
    assert latest["content_hash"] == "new-hash"


def test_run_sentinel_tool_error_does_not_store_observation(tmp_path) -> None:
    store = MonitorStore(str(tmp_path / "monitoring.db"))
    store.initialize()
    monitor = store.create_monitor("Watch this page.", "https://example.com")
    run_monitor_check(
        store,
        monitor["id"],
        run_fn=lambda goal, url: _strands_result("good-hash", "Baseline page."),
    )

    error_payload = {
        "error": "connection_failure",
        "message": "Could not connect to the webpage.",
        "status_code": None,
    }

    class FailingAgent:
        messages = [
            {
                "role": "assistant",
                "content": [
                    {
                        "toolUse": {
                            "name": "check_webpage",
                            "toolUseId": "tool-1",
                            "input": {"url": "https://example.com"},
                        }
                    }
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "toolResult": {
                            "toolUseId": "tool-1",
                            "status": "success",
                            "content": [{"text": json.dumps(error_payload)}],
                        }
                    }
                ],
            },
            {"role": "assistant", "content": [{"text": "Could not retrieve the page."}]},
        ]

        def __call__(self, prompt: str):
            return SimpleNamespace(message=self.messages[-1])

    result = run_monitor_check(
        store,
        monitor["id"],
        run_fn=lambda goal, url: run_sentinel(goal, url, agent=FailingAgent()),
    )
    assert result.change_status == "error"
    latest = store.get_latest_observation(monitor["id"])
    assert latest is not None
    assert latest["change_status"] == "error"
    monitor_after = store.get_monitor(monitor["id"])
    assert monitor_after is not None
    assert monitor_after["previous_content_hash"] == "good-hash"
    assert len(store.list_observations(monitor["id"])) == 2


def test_changed_irrelevant_change_is_not_meaningful(tmp_path) -> None:
    store = MonitorStore(str(tmp_path / "monitoring.db"))
    store.initialize()
    monitor = store.create_monitor(
        "Tell me if the application deadline changes",
        "https://example.com",
    )
    run_monitor_check(
        store,
        monitor["id"],
        run_fn=lambda goal, url: _result(
            "Deadline is 1 May 2026. Footer updated 2025.",
            "hash-1",
            page_text="Deadline: 1 May 2026. Copyright 2025.",
        ),
        assess_fn=_raise_if_assessed,
    )

    captured: dict[str, str | None] = {}

    def assess(goal: str, previous_text: str | None, current_text: str | None):
        captured["goal"] = goal
        captured["previous_text"] = previous_text
        captured["current_text"] = current_text
        return _assessment(
            meaningful_change=False,
            summary="Only the copyright year changed; the deadline is unchanged.",
            reason="The monitoring goal is about the deadline, which is still 1 May 2026.",
            action_required=False,
        )

    result = run_monitor_check(
        store,
        monitor["id"],
        run_fn=lambda goal, url: _result(
            "Deadline is 1 May 2026. Footer updated 2026.",
            "hash-2",
            page_text="Deadline: 1 May 2026. Copyright 2026.",
        ),
        assess_fn=assess,
    )

    assert result.change_status == "changed"
    assert result.changed is True
    assert result.meaningful_change is False
    assert result.action_required is False
    assert result.action_type is None
    assert result.agents == ["supervisor", "monitoring", "analysis"]
    assert [item.agent for item in result.agent_trace] == [
        "monitoring",
        "analysis",
        "supervisor",
    ]
    assert captured["goal"] == "Tell me if the application deadline changes"
    assert captured["previous_text"] == "Deadline: 1 May 2026. Copyright 2025."
    assert captured["current_text"] == "Deadline: 1 May 2026. Copyright 2026."
    latest = store.get_latest_observation(monitor["id"])
    assert latest is not None
    assert latest["meaningful_change"] is False
    assert latest["content_hash"] == "hash-2"


def test_agent_failure_does_not_store_changed_observation(tmp_path) -> None:
    store = MonitorStore(str(tmp_path / "monitoring.db"))
    store.initialize()
    monitor = store.create_monitor("Track the supplier catalog.", "https://example.com")
    run_monitor_check(
        store,
        monitor["id"],
        run_fn=lambda goal, url: _result(
            "Alpha component is listed.",
            "hash-1",
            page_text="Alpha component is listed.",
        ),
        assess_fn=_raise_if_assessed,
    )

    def boom(goal: str, previous_text: str | None, current_text: str | None):
        raise RuntimeError("model timeout")

    try:
        run_monitor_check(
            store,
            monitor["id"],
            run_fn=lambda goal, url: _result(
                "Beta component is listed.",
                "hash-2",
                page_text="Beta component is listed.",
            ),
            assess_fn=boom,
        )
        raise AssertionError("Expected MonitoringCheckError")
    except MonitoringCheckError as exc:
        assert exc.code == "analysis_error"

    latest = store.get_latest_observation(monitor["id"])
    assert latest is not None
    assert latest["content_hash"] == "hash-1"
    assert len(store.list_observations(monitor["id"])) == 1
    monitor_after = store.get_monitor(monitor["id"])
    assert monitor_after is not None
    assert monitor_after["previous_content_hash"] == "hash-1"
    assert monitor_after["previous_content"] == "Alpha component is listed."
    assert monitor_after["last_change"] == "baseline"


def test_analysis_receives_relevant_excerpt_not_full_page(tmp_path) -> None:
    store = MonitorStore(str(tmp_path / "monitoring.db"))
    store.initialize()
    monitor = store.create_monitor(
        "Tell me if the application deadline changes",
        "https://example.com",
    )

    def first_run(goal: str, url: str) -> SentinelResult:
        return SentinelResult(
            goal=goal,
            url=url,
            summary="Observed: Application deadline: 1 May 2026",
            tool_used=True,
            model="openai/gpt-oss-20b",
            content_hash="hash-1",
            page_text="Nav Home About Application deadline: 1 May 2026 Footer cookies",
            relevant_excerpt="Application deadline: 1 May 2026",
            observed_facts=["Application deadline: 1 May 2026"],
            fetch_method="http",
        )

    baseline = run_monitor_check(
        store,
        monitor["id"],
        run_fn=first_run,
        assess_fn=_raise_if_assessed,
    )
    assert baseline.change_status == "baseline"
    assert baseline.summary == "Observed: Application deadline: 1 May 2026"
    assert baseline.observed_facts == ["Application deadline: 1 May 2026"]
    stored = store.get_monitor(monitor["id"])
    assert stored is not None
    assert stored["previous_content"] == (
        "Nav Home About Application deadline: 1 May 2026 Footer cookies"
    )
    assert stored["last_checked_at"] is not None
    assert stored["last_change"] == "baseline"

    captured: dict[str, str | None] = {}

    def assess(goal: str, previous_text: str | None, current_text: str | None):
        captured["previous_text"] = previous_text
        captured["current_text"] = current_text
        return _assessment(
            meaningful_change=True,
            summary="The application deadline changed from 1 May 2026 to 15 May 2026.",
            reason="The date in the current excerpt replaced 1 May 2026.",
            action_required=True,
        )

    def second_run(goal: str, url: str) -> SentinelResult:
        return SentinelResult(
            goal=goal,
            url=url,
            summary="Observed: Application deadline: 15 May 2026",
            tool_used=True,
            model="openai/gpt-oss-20b",
            content_hash="hash-2",
            page_text="Nav Home About Application deadline: 15 May 2026 Footer cookies",
            relevant_excerpt="Application deadline: 15 May 2026",
            observed_facts=["Application deadline: 15 May 2026"],
            fetch_method="http",
        )

    result = run_monitor_check(
        store,
        monitor["id"],
        run_fn=second_run,
        assess_fn=assess,
    )
    assert captured["previous_text"] == (
        "Nav Home About Application deadline: 1 May 2026 Footer cookies"
    )
    assert captured["current_text"] == (
        "Nav Home About Application deadline: 15 May 2026 Footer cookies"
    )
    assert result.change_status == "changed"
    assert result.agents == ["supervisor", "monitoring", "analysis", "action"]
    assert "Fetched the source. Observed:" in result.agent_trace[0].summary
    assert result.result_status == "meaningful_change"
    assert result.hash_changed is True


def test_disabled_monitor_is_not_checked(tmp_path) -> None:
    store = MonitorStore(str(tmp_path / "monitoring.db"))
    store.initialize()
    monitor = store.create_monitor("Watch this page.", "https://example.com")
    store.set_enabled(monitor["id"], False)
    try:
        run_monitor_check(
            store,
            monitor["id"],
            run_fn=lambda goal, url: _result("should not run", "hash-1"),
        )
        raise AssertionError("Expected MonitoringCheckError")
    except MonitoringCheckError as exc:
        assert exc.code == "disabled"
        assert exc.http_status == 409
    assert store.get_latest_observation(monitor["id"]) is None


def test_blocked_source_sets_last_checked_not_never(tmp_path) -> None:
    store = MonitorStore(str(tmp_path / "monitoring.db"))
    store.initialize()
    monitor = store.create_monitor("Watch this page.", "https://example.com")
    from app.tools.web_monitor import WebpageToolError

    def boom(goal: str, url: str):
        raise WebpageToolError(
            "captcha_required",
            "A CAPTCHA is required. Sentinel will not bypass it.",
        )

    result = run_monitor_check(store, monitor["id"], run_fn=boom)
    assert result.change_status == "blocked"
    assert result.human_loop_state == "blocked_requires_user"
    assert result.alert_id is None
    assert store.list_alerts() == []
    monitor_after = store.get_monitor(monitor["id"])
    assert monitor_after is not None
    assert monitor_after["last_change"] == "blocked"
    assert monitor_after["last_checked_at"] is not None
    assert monitor_after["previous_content_hash"] is None
    assert [item.agent for item in result.agent_trace] == ["monitoring", "supervisor"]


def test_error_then_success_is_still_baseline(tmp_path) -> None:
    store = MonitorStore(str(tmp_path / "monitoring.db"))
    store.initialize()
    monitor = store.create_monitor("Watch this page.", "https://example.com")
    run_monitor_check(
        store,
        monitor["id"],
        run_fn=lambda goal, url: _result(
            "failed",
            "ignored",
            tool_error="timeout",
        ),
        assess_fn=_raise_if_assessed,
    )
    result = run_monitor_check(
        store,
        monitor["id"],
        run_fn=lambda goal, url: _result(
            "Deadline is 1 May 2026.",
            "hash-1",
            page_text="Deadline: 1 May 2026",
        ),
        assess_fn=_raise_if_assessed,
    )
    assert result.change_status == "baseline"
    monitor_after = store.get_monitor(monitor["id"])
    assert monitor_after is not None
    assert monitor_after["previous_content_hash"] == "hash-1"
    assert monitor_after["last_change"] == "baseline"


def test_llm_fact_wording_does_not_change_hash(tmp_path) -> None:
    store = MonitorStore(str(tmp_path / "monitoring.db"))
    store.initialize()
    monitor = store.create_monitor(
        "Tell me if the application deadline changes",
        "https://example.com",
    )

    def first_run(goal: str, url: str) -> SentinelResult:
        return SentinelResult(
            goal=goal,
            url=url,
            summary="Observed: Application deadline: 1 May 2026",
            tool_used=True,
            model="openai/gpt-oss-20b",
            content_hash="page-hash-1",
            page_text="Application deadline: 1 May 2026 Status: Open",
            relevant_excerpt="Application deadline: 1 May 2026",
            observed_facts=["Application deadline: 1 May 2026"],
            fetch_method="http",
        )

    baseline = run_monitor_check(
        store,
        monitor["id"],
        run_fn=first_run,
        assess_fn=_raise_if_assessed,
    )
    assert baseline.change_status == "baseline"

    def reworded_facts(goal: str, url: str) -> SentinelResult:
        return SentinelResult(
            goal=goal,
            url=url,
            summary="Observed: deadline=1 May 2026",
            tool_used=True,
            model="openai/gpt-oss-20b",
            content_hash="page-hash-1",
            page_text="Application deadline: 1 May 2026 Status: Open",
            relevant_excerpt="deadline 1 May 2026",
            observed_facts=["deadline: May 1 2026", "status: Applications are open"],
            fetch_method="http",
        )

    unchanged = run_monitor_check(
        store,
        monitor["id"],
        run_fn=reworded_facts,
        assess_fn=_raise_if_assessed,
    )
    assert unchanged.change_status == "unchanged"
    assert unchanged.changed is False
    assert unchanged.alert_id is None
    assert store.list_alerts() == []


def test_multiple_enabled_monitors_are_checked_independently(tmp_path) -> None:
    store = MonitorStore(str(tmp_path / "monitoring.db"))
    store.initialize()
    first = store.create_monitor("Watch page A.", "https://example.com/a")
    second = store.create_monitor("Watch page B.", "https://example.com/b")
    store.set_enabled(second["id"], False)

    def run_a(goal: str, url: str) -> SentinelResult:
        assert "a" in url
        return _result("Page A.", "hash-a", page_text="Page A")

    result_a = run_monitor_check(
        store,
        first["id"],
        run_fn=run_a,
        assess_fn=_raise_if_assessed,
    )
    assert result_a.change_status == "baseline"
    assert store.get_latest_observation(second["id"]) is None

    try:
        run_monitor_check(
            store,
            second["id"],
            run_fn=lambda goal, url: _result("should not run", "hash-b"),
        )
        raise AssertionError("Expected MonitoringCheckError")
    except MonitoringCheckError as exc:
        assert exc.code == "disabled"


def test_create_monitor_does_not_check(tmp_path) -> None:
    store = MonitorStore(str(tmp_path / "monitoring.db"))
    store.initialize()
    monitor = store.create_monitor("Watch this page.", "https://example.com")
    assert monitor["last_checked_at"] is None
    assert monitor["last_change"] is None or monitor["status"] == "created"
    assert store.get_latest_observation(monitor["id"]) is None


