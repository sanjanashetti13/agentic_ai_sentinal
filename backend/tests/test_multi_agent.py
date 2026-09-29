from types import SimpleNamespace
from unittest.mock import MagicMock
import json

import pytest

from app.agent.action_agent import decide_action, parse_action_decision
from app.agent.human_loop import apply_human_loop_safety, detect_human_loop_block
from app.agent.sentinel_agent import (
    ACTION_PROMPT,
    ANALYSIS_PROMPT,
    SUPERVISOR_PROMPT,
    SYSTEM_PROMPT,
    create_action_agent,
    create_analysis_agent,
    create_monitoring_agent,
    create_sentinel_agent,
)
from app.agent.supervisor import coordinate_changed_check, create_supervisor_agent
from app.models.schemas import ActionDecision, MeaningfulChangeAssessment


def test_specialist_agents_have_distinct_roles() -> None:
    monitoring = create_monitoring_agent(model=MagicMock())
    analysis = create_analysis_agent(model=MagicMock())
    action = create_action_agent(model=MagicMock())
    assert set(monitoring.tool_names) == {"check_webpage"}
    assert analysis.tool_names == []
    assert action.tool_names == []
    assert "check_webpage" in SYSTEM_PROMPT
    assert "hash" in ANALYSIS_PROMPT.lower()
    assert "captcha" in ACTION_PROMPT.lower()
    assert "otp" in ACTION_PROMPT.lower()
    assert "deadline" not in SYSTEM_PROMPT.lower()
    assert "deadline" not in ANALYSIS_PROMPT.lower()
    assert "deadline" not in ACTION_PROMPT.lower()
    assert "deadline" not in SUPERVISOR_PROMPT.lower()


def test_supervisor_coordinates_specialist_tools() -> None:
    supervisor = create_supervisor_agent(model=MagicMock())
    names = set(supervisor.tool_names)
    assert "monitoring_agent" in names
    assert "analysis_agent" in names
    assert "action_agent" in names
    assert names != {"check_webpage"}


def test_create_sentinel_agent_remains_the_monitoring_agent() -> None:
    agent = create_sentinel_agent(model=MagicMock())
    assert set(agent.tool_names) == {"check_webpage"}


def test_analysis_agent_structured_output() -> None:
    class StubAgent:
        def __call__(self, prompt: str):
            assert "Tell me if the application deadline changes" in prompt
            return SimpleNamespace(
                message={
                    "role": "assistant",
                    "content": [
                        {
                            "text": json.dumps(
                                {
                                    "meaningful_change": True,
                                    "summary": "The deadline moved to 15 May 2026.",
                                    "reason": "The date in the current excerpt changed.",
                                    "action_required": True,
                                    "confidence": 0.91,
                                }
                            )
                        }
                    ],
                }
            )

    from app.agent.sentinel_agent import assess_page_change

    result = assess_page_change(
        "Tell me if the application deadline changes",
        "Deadline: 1 May 2026",
        "Deadline: 15 May 2026",
        agent=StubAgent(),
    )
    assert result.meaningful_change is True
    assert result.confidence == 0.91


def test_action_agent_structured_output() -> None:
    class StubAgent:
        def __call__(self, prompt: str):
            assert "Analysis JSON" in prompt
            return SimpleNamespace(
                message={
                    "role": "assistant",
                    "content": [
                        {
                            "text": json.dumps(
                                {
                                    "action_type": "notify_user",
                                    "human_loop_state": "notification",
                                    "summary": "Notify the user about the deadline change.",
                                    "reason": "The analysis marked this as requiring action.",
                                    "user_notification": "Application deadline changed to 15 May 2026.",
                                    "requires_approval": False,
                                    "blocked_reason": None,
                                }
                            )
                        }
                    ],
                }
            )

    analysis = MeaningfulChangeAssessment(
        meaningful_change=True,
        summary="The deadline changed to 15 May 2026.",
        reason="The date changed.",
        action_required=True,
    )
    decision = decide_action(
        "Tell me if the application deadline changes",
        analysis,
        agent=StubAgent(),
    )
    assert decision.action_type == "notify_user"
    assert decision.human_loop_state == "notification"
    assert "15 May" in (decision.user_notification or "")


def test_action_agent_invalid_output_raises() -> None:
    class StubAgent:
        def __call__(self, prompt: str):
            return SimpleNamespace(
                message={"role": "assistant", "content": [{"text": "I will think about it."}]}
            )

    with pytest.raises(ValueError, match="structured action decision"):
        decide_action(
            "Watch this page.",
            MeaningfulChangeAssessment(
                meaningful_change=True,
                summary="Changed.",
                reason="Hash differed.",
                action_required=True,
            ),
            agent=StubAgent(),
        )


def test_parse_action_decision_rejects_unknown_type() -> None:
    with pytest.raises(Exception):
        parse_action_decision(
            json.dumps(
                {
                    "action_type": "delete_account",
                    "human_loop_state": "notification",
                    "summary": "No",
                    "reason": "No",
                }
            )
        )


def test_supervisor_changed_workflow_calls_analysis_then_action() -> None:
    order: list[str] = []

    def analyze(goal: str, previous_text: str | None, current_text: str | None):
        order.append("analysis")
        return MeaningfulChangeAssessment(
            meaningful_change=True,
            summary="The deadline changed.",
            reason="The date changed.",
            action_required=True,
            confidence=0.9,
        )

    def act(goal: str, analysis: MeaningfulChangeAssessment):
        order.append("action")
        return ActionDecision(
            action_type="notify_user",
            human_loop_state="notification",
            summary=analysis.summary,
            reason=analysis.reason,
            user_notification=analysis.summary,
            requires_approval=False,
        )

    result = coordinate_changed_check(
        "Tell me if the application deadline changes",
        "old",
        "new",
        analyze_fn=analyze,
        act_fn=act,
    )
    assert order == ["analysis", "action"]
    assert result.agents_invoked == ["analysis_agent", "action_agent"]
    assert result.analysis is not None
    assert result.action is not None
    assert result.action.action_type == "notify_user"


def test_captcha_forces_blocked_requires_user() -> None:
    blocked = detect_human_loop_block(page_text="Please complete the CAPTCHA to continue.")
    assert blocked is not None
    assert blocked[0] == "blocked_requires_user"

    decision = apply_human_loop_safety(
        ActionDecision(
            action_type="notify_user",
            human_loop_state="notification",
            summary="Notify",
            reason="Change detected",
            requires_approval=False,
        ),
        page_text="Please complete the reCAPTCHA challenge.",
    )
    assert decision.human_loop_state == "blocked_requires_user"
    assert decision.action_type == "request_approval"
    assert decision.requires_approval is True


def test_otp_error_code_forces_blocked_requires_user() -> None:
    blocked = detect_human_loop_block(error_code="otp_required")
    assert blocked is not None
    assert "OTP" in blocked[1]


def test_approval_required_decision_shape() -> None:
    decision = ActionDecision(
        action_type="request_approval",
        human_loop_state="approval_required",
        summary="Submit the application?",
        reason="This would send an application on the user's behalf.",
        user_notification="Approval is required before continuing.",
        requires_approval=True,
    )
    assert decision.human_loop_state == "approval_required"
    assert decision.requires_approval is True
