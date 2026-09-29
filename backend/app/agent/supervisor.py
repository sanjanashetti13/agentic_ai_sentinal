from __future__ import annotations

from collections.abc import Callable
from typing import Any

from strands import Agent

from app.agent.action_agent import decide_action
from app.agent.sentinel_agent import (
    ACTION_PROMPT,
    ANALYSIS_PROMPT,
    SUPERVISOR_PROMPT,
    SYSTEM_PROMPT,
    _final_text,
    assess_page_change,
    create_action_agent,
    create_analysis_agent,
    create_model,
    create_monitoring_agent,
    parse_structured_payload,
)
from app.models.schemas import (
    ActionDecision,
    ChangeAnalysis,
    MeaningfulChangeAssessment,
    MonitoringObservation,
    SentinelResult,
    SupervisorResult,
)


def create_supervisor_agent(
    model: Any | None = None,
    *,
    monitoring_agent: Agent | None = None,
    analysis_agent: Agent | None = None,
    action_agent: Agent | None = None,
) -> Agent:
    """Create the Supervisor Agent with specialist agents as tools."""
    shared_model = model or create_model()
    monitoring = monitoring_agent or create_monitoring_agent(model=shared_model)
    analysis = analysis_agent or create_analysis_agent(model=shared_model)
    action = action_agent or create_action_agent(model=shared_model)
    return Agent(
        name="supervisor_agent",
        description="Coordinates Sentinel's specialist monitoring, analysis, and action agents.",
        model=shared_model,
        system_prompt=SUPERVISOR_PROMPT,
        tools=[
            monitoring.as_tool(
                name="monitoring_agent",
                description="Obtain a structured observation from a supported source.",
            ),
            analysis.as_tool(
                name="analysis_agent",
                description=(
                    "Decide whether a hash-detected change is meaningful "
                    "for the user's goal."
                ),
            ),
            action.as_tool(
                name="action_agent",
                description="Decide the next alert, notification, or approval action.",
            ),
        ],
        callback_handler=None,
    )


def coordinate_changed_check(
    goal: str,
    previous_text: str | None,
    current_text: str | None,
    *,
    analyze_fn: Callable[[str, str | None, str | None], MeaningfulChangeAssessment]
    | None = None,
    act_fn: Callable[[str, MeaningfulChangeAssessment], ActionDecision] | None = None,
) -> SupervisorResult:
    """Supervisor workflow for an already-detected content change.

    Hash comparison stays outside the agents. This only coordinates
    Analysis then Action, then synthesizes a structured result.
    """
    analyze = analyze_fn or assess_page_change
    analysis = analyze(goal, previous_text, current_text)
    change_analysis = ChangeAnalysis.model_validate(analysis.model_dump())
    act = act_fn or decide_action
    action = act(goal, change_analysis)
    return SupervisorResult(
        goal=goal,
        change_status="changed",
        observation=MonitoringObservation(
            source_type="webpage",
            summary=change_analysis.summary,
            page_text=current_text,
        ),
        analysis=change_analysis,
        action=action,
        summary=action.user_notification or action.summary or change_analysis.summary,
        agents_invoked=["analysis_agent", "action_agent"],
    )


def run_supervisor(
    goal: str,
    url: str,
    *,
    agent: Agent | None = None,
) -> str:
    """LLM-led Supervisor coordination for an open-ended request."""
    supervisor = agent or create_supervisor_agent()
    prompt = (
        f"User goal: {goal.strip()}\n"
        f"Source URL: {url.strip()}\n\n"
        "Coordinate the specialist agents as needed and return a concise "
        "final result."
    )
    result = supervisor(prompt)
    return _final_text(result)


def specialist_prompts() -> dict[str, str]:
    return {
        "monitoring_agent": SYSTEM_PROMPT,
        "analysis_agent": ANALYSIS_PROMPT,
        "action_agent": ACTION_PROMPT,
        "supervisor_agent": SUPERVISOR_PROMPT,
    }


def observation_from_sentinel_result(result: SentinelResult) -> MonitoringObservation:
    return MonitoringObservation(
        source_type="webpage",
        url=result.url,
        summary=result.summary,
        content_hash=result.content_hash,
        tool_used=result.tool_used,
        tool_error=result.tool_error,
        page_text=result.page_text,
        relevant_excerpt=result.relevant_excerpt,
        observed_facts=list(result.observed_facts),
        observed_fact_records=list(result.observed_fact_records),
        fetch_method=result.fetch_method,
        status=result.observation_status,
        title=result.title,
    )


def parse_supervisor_json(text: str) -> dict:
    return parse_structured_payload(
        text,
        "Sentinel did not return a structured supervisor result.",
    )
