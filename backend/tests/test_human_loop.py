from app.models.schemas import ActionDecision, MeaningfulChangeAssessment, SentinelResult
from app.services.monitoring import run_monitor_check
from app.storage.database import MonitorStore


def _result(content_hash: str, page_text: str) -> SentinelResult:
    return SentinelResult(
        goal="Tell me if the application deadline changes",
        url="https://example.com",
        summary="Observed the page.",
        tool_used=True,
        model="openai/gpt-oss-20b",
        content_hash=content_hash,
        page_text=page_text,
    )


def test_changed_captcha_page_is_blocked_requires_user(tmp_path) -> None:
    store = MonitorStore(str(tmp_path / "hitl.db"))
    store.initialize()
    monitor = store.create_monitor(
        "Tell me if the application deadline changes",
        "https://example.com",
    )
    run_monitor_check(
        store,
        monitor["id"],
        run_fn=lambda goal, url: _result("hash-1", "Deadline: 1 May 2026"),
    )

    def notify(goal: str, analysis: MeaningfulChangeAssessment) -> ActionDecision:
        return ActionDecision(
            action_type="notify_user",
            human_loop_state="notification",
            summary=analysis.summary,
            reason=analysis.reason,
            user_notification=analysis.summary,
            requires_approval=False,
        )

    result = run_monitor_check(
        store,
        monitor["id"],
        run_fn=lambda goal, url: _result(
            "hash-2",
            "Please complete the CAPTCHA to continue.",
        ),
        assess_fn=lambda goal, previous_text, current_text: MeaningfulChangeAssessment(
            meaningful_change=True,
            summary="The page now shows a CAPTCHA wall.",
            reason="The source is blocked by a CAPTCHA.",
            action_required=True,
        ),
        action_fn=notify,
    )
    assert result.change_status == "changed"
    assert result.human_loop_state == "blocked_requires_user"
    assert result.action_type == "request_approval"


def test_otp_challenge_is_blocked_requires_user(tmp_path) -> None:
    store = MonitorStore(str(tmp_path / "hitl.db"))
    store.initialize()
    monitor = store.create_monitor("Watch this page.", "https://example.com")
    run_monitor_check(
        store,
        monitor["id"],
        run_fn=lambda goal, url: _result("hash-1", "Welcome"),
    )
    result = run_monitor_check(
        store,
        monitor["id"],
        run_fn=lambda goal, url: _result("hash-2", "Enter the OTP sent to your phone."),
        assess_fn=lambda goal, previous_text, current_text: MeaningfulChangeAssessment(
            meaningful_change=False,
            summary="The page is asking for an OTP.",
            reason="This is a security challenge, not a goal-relevant change.",
            action_required=False,
        ),
        action_fn=lambda goal, analysis: ActionDecision(
            action_type="ignore",
            human_loop_state="no_action",
            summary=analysis.summary,
            reason=analysis.reason,
        ),
    )
    assert result.human_loop_state == "blocked_requires_user"


def test_approval_required_is_persisted_in_action_history(tmp_path) -> None:
    store = MonitorStore(str(tmp_path / "hitl.db"))
    store.initialize()
    monitor = store.create_monitor("Watch this page.", "https://example.com")
    run_monitor_check(
        store,
        monitor["id"],
        run_fn=lambda goal, url: _result("hash-1", "Status: closed"),
    )
    result = run_monitor_check(
        store,
        monitor["id"],
        run_fn=lambda goal, url: _result("hash-2", "Status: open. Submit application now."),
        assess_fn=lambda goal, previous_text, current_text: MeaningfulChangeAssessment(
            meaningful_change=True,
            summary="Registration appears to be open.",
            reason="The status changed from closed to open.",
            action_required=True,
        ),
        action_fn=lambda goal, analysis: ActionDecision(
            action_type="request_approval",
            human_loop_state="approval_required",
            summary=analysis.summary,
            reason="Submitting an application requires the user's approval.",
            user_notification="Registration opened. Approve before Sentinel continues.",
            requires_approval=True,
        ),
    )
    assert result.human_loop_state == "approval_required"
    history = store.list_action_history(monitor["id"])
    assert history
    assert history[0]["human_loop_state"] == "approval_required"
