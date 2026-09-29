from app.models.schemas import MeaningfulChangeAssessment, SentinelResult
from app.services.monitoring import run_monitor_check
from app.storage.database import MonitorStore


def _result(
    summary: str,
    content_hash: str,
    page_text: str | None = None,
) -> SentinelResult:
    return SentinelResult(
        goal="Tell me if the application deadline changes",
        url="https://example.com",
        summary=summary,
        tool_used=True,
        model="openai/gpt-oss-20b",
        content_hash=content_hash,
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


def _store(tmp_path) -> tuple[MonitorStore, dict]:
    store = MonitorStore(str(tmp_path / "alerts.db"))
    store.initialize()
    monitor = store.create_monitor(
        "Tell me if the application deadline changes",
        "https://example.com",
    )
    return store, monitor


def _baseline(store: MonitorStore, monitor_id: str) -> None:
    run_monitor_check(
        store,
        monitor_id,
        run_fn=lambda goal, url: _result(
            "Deadline is 1 May 2026.",
            "hash-1",
            page_text="Deadline: 1 May 2026",
        ),
        assess_fn=_raise_if_assessed,
    )


def test_baseline_does_not_create_an_alert(tmp_path) -> None:
    store, monitor = _store(tmp_path)
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
    assert result.alert_id is None
    assert store.list_alerts() == []


def test_unchanged_does_not_create_an_alert(tmp_path) -> None:
    store, monitor = _store(tmp_path)
    _baseline(store, monitor["id"])

    result = run_monitor_check(
        store,
        monitor["id"],
        run_fn=lambda goal, url: _result(
            "Deadline is still 1 May 2026.",
            "hash-1",
            page_text="Deadline: 1 May 2026",
        ),
        assess_fn=_raise_if_assessed,
    )

    assert result.change_status == "unchanged"
    assert result.alert_id is None
    assert store.list_alerts() == []


def test_meaningful_changed_check_creates_an_alert(tmp_path) -> None:
    store, monitor = _store(tmp_path)
    _baseline(store, monitor["id"])

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
    assert result.alert_id is not None
    alerts = store.list_alerts()
    assert len(alerts) == 1
    alert = alerts[0]
    assert alert["alert_id"] == result.alert_id
    assert alert["id"] == result.alert_id
    assert alert["monitor_id"] == monitor["id"]
    assert alert["content_hash"] == "hash-2"
    assert alert["summary"] == "The deadline changed to 15 May 2026."
    assert alert["reason"] == "The date in the current page differs from the previous page."
    assert alert["action_required"] is True
    assert alert["status"] == "pending"
    assert "Deadline:" not in alert["summary"]


def test_irrelevant_changed_check_does_not_create_an_alert(tmp_path) -> None:
    store, monitor = _store(tmp_path)
    _baseline(store, monitor["id"])

    result = run_monitor_check(
        store,
        monitor["id"],
        run_fn=lambda goal, url: _result(
            "Footer year changed.",
            "hash-2",
            page_text="Deadline: 1 May 2026. Copyright 2026.",
        ),
        assess_fn=lambda goal, previous_text, current_text: _assessment(
            meaningful_change=False,
            summary="Only the copyright year changed.",
            reason="The deadline is unchanged.",
            action_required=False,
        ),
    )

    assert result.change_status == "changed"
    assert result.meaningful_change is False
    assert result.alert_id is None
    assert store.list_alerts() == []


def test_action_required_false_does_not_create_an_alert(tmp_path) -> None:
    store, monitor = _store(tmp_path)
    _baseline(store, monitor["id"])

    result = run_monitor_check(
        store,
        monitor["id"],
        run_fn=lambda goal, url: _result(
            "A related note was added.",
            "hash-2",
            page_text="Deadline: 1 May 2026. See FAQ.",
        ),
        assess_fn=lambda goal, previous_text, current_text: _assessment(
            meaningful_change=True,
            summary="A related note was added, but no action is needed yet.",
            reason="The deadline itself did not change.",
            action_required=False,
        ),
    )

    assert result.change_status == "changed"
    assert result.meaningful_change is False
    assert result.action_required is False
    assert result.alert_id is None
    assert store.list_alerts() == []


def test_duplicate_check_does_not_create_duplicate_alerts(tmp_path) -> None:
    store, monitor = _store(tmp_path)
    _baseline(store, monitor["id"])

    first = run_monitor_check(
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
            reason="The date changed.",
            action_required=True,
        ),
    )
    assert first.alert_id is not None
    assert len(store.list_alerts()) == 1

    unchanged = run_monitor_check(
        store,
        monitor["id"],
        run_fn=lambda goal, url: _result(
            "Deadline is still 15 May 2026.",
            "hash-2",
            page_text="Deadline: 15 May 2026",
        ),
        assess_fn=_raise_if_assessed,
    )
    assert unchanged.change_status == "unchanged"
    assert unchanged.alert_id is None
    assert len(store.list_alerts()) == 1

    later = run_monitor_check(
        store,
        monitor["id"],
        run_fn=lambda goal, url: _result(
            "Deadline is now 1 June 2026.",
            "hash-3",
            page_text="Deadline: 1 June 2026",
        ),
        assess_fn=lambda goal, previous_text, current_text: _assessment(
            meaningful_change=True,
            summary="The deadline changed to 1 June 2026.",
            reason="The date changed again.",
            action_required=True,
        ),
    )
    assert later.alert_id == first.alert_id
    assert len(store.list_alerts()) == 1
    pending = store.get_alert(first.alert_id)
    assert pending is not None
    assert pending["content_hash"] == "hash-3"
    assert "1 June" in pending["summary"]

    acknowledged = store.set_alert_status(first.alert_id, "acknowledged")
    assert acknowledged is not None
    assert acknowledged["status"] == "acknowledged"

    after_ack = run_monitor_check(
        store,
        monitor["id"],
        run_fn=lambda goal, url: _result(
            "Applications are now closed.",
            "hash-4",
            page_text="Applications closed",
        ),
        assess_fn=lambda goal, previous_text, current_text: _assessment(
            meaningful_change=True,
            summary="Applications closed.",
            reason="The process ended.",
            action_required=True,
        ),
    )
    assert after_ack.alert_id is not None
    assert after_ack.alert_id != first.alert_id
    assert len(store.list_alerts()) == 2
