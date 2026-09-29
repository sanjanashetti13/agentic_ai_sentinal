from __future__ import annotations

from strands import Agent

from app.agent.human_loop import apply_human_loop_safety
from app.agent.sentinel_agent import (
    _final_text,
    create_action_agent,
    parse_structured_payload,
)
from app.models.schemas import ActionDecision, MeaningfulChangeAssessment


def parse_action_decision(text: str) -> ActionDecision:
    payload = parse_structured_payload(
        text,
        "Sentinel did not return a structured action decision.",
    )
    return ActionDecision.model_validate(payload)


def decide_action(
    goal: str,
    analysis: MeaningfulChangeAssessment,
    *,
    page_text: str | None = None,
    error_code: str | None = None,
    agent: Agent | None = None,
) -> ActionDecision:
    """Ask the Action Agent what to do with a completed change analysis."""
    cleaned_goal = goal.strip()
    if not cleaned_goal:
        raise ValueError("A monitoring goal is required.")

    sentinel = agent or create_action_agent()
    prompt = (
        "A hash comparison already detected a page change, and the Analysis "
        "Agent produced this structured result.\n\n"
        f"User monitoring goal:\n{cleaned_goal}\n\n"
        f"Analysis JSON:\n{analysis.model_dump_json()}\n\n"
        f"Previous relevant content:\n{analysis.previous_relevant_content or '(none)'}\n\n"
        f"Current relevant content:\n{analysis.current_relevant_content or '(none)'}\n\n"
        f"Error status: {error_code or 'none'}\n\n"
        "If meaningful_change and action_required are true, choose create_alert "
        "unless a genuine safety or human-in-the-loop condition applies. "
        "Do not ignore a clearly meaningful monitoring change.\n"
        "Decide the next action. Return only the JSON object described in "
        "your instructions."
    )
    result = sentinel(prompt)
    decision = parse_action_decision(_final_text(result))
    return apply_human_loop_safety(
        decision,
        error_code=error_code,
        page_text=page_text,
    )
