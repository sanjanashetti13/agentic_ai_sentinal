from __future__ import annotations

import logging
import threading
from collections.abc import Callable

from app.agent.action_agent import decide_action
from app.agent.human_loop import apply_human_loop_safety, detect_human_loop_block
from app.agent.sentinel_agent import (
    UNCHANGED_SUMMARY,
    AgentConfigError,
    assess_page_change,
    clip_page_text,
)
from app.models.schemas import (
    ActionDecision,
    AgentTraceEntry,
    MeaningfulChangeAssessment,
    MonitorCheckResponse,
    SentinelResult,
    SystemStatusResponse,
)
from app.storage.database import GMAIL_MONITOR_URL, MonitorStore, derive_monitor_name
from app.tools.content_diff import (
    extract_goal_match,
    ground_meaningful_change,
    observation_texts_equivalent,
    summarize_text_change,
)
from app.tools.web_monitor import (
    WebpageToolError,
    check_webpage,
    hash_content,
    validate_url,
)
from app.tools.errors import is_blocking_error_code

logger = logging.getLogger("sentinel.website_monitor")

SCHEDULER_INTERVAL_SECONDS = 10
SCHEDULER_INTERVAL_MINUTES = 0
SCHEDULER_STALE_SECONDS = 45

_check_locks_guard = threading.Lock()
_check_locks: dict[str, threading.Lock] = {}


class MonitoringCheckError(Exception):
    """Structured failure from a monitor check. Safe for API consumers."""

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int | None = None,
        http_status: int = 502,
    ) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        self.http_status = http_status
        super().__init__(message)

    def to_dict(self) -> dict[str, str | int | None]:
        return {
            "error": self.code,
            "message": self.message,
            "status_code": self.status_code,
        }


def _lock_for(monitor_id: str) -> threading.Lock:
    with _check_locks_guard:
        lock = _check_locks.get(monitor_id)
        if lock is None:
            lock = threading.Lock()
            _check_locks[monitor_id] = lock
        return lock


def _log(event: str, **fields: object) -> None:
    parts = [event]
    for key, value in fields.items():
        if value is None:
            continue
        text = str(value)
        if len(text) > 240:
            text = text[:239] + "…"
        parts.append(f"{key}={text}")
    logger.info(" ".join(parts))


def relevant_observation_text(result: SentinelResult) -> str | None:
    """Normalized page text used for snapshots. LLM facts are never hashed."""
    return clip_page_text(result.page_text) or clip_page_text(result.relevant_excerpt)


def comparison_hash(result: SentinelResult) -> str | None:
    """SHA-256 of the webpage tool's normalized content, not model output."""
    return result.content_hash


def _one_line(value: str) -> str:
    return " ".join(value.split())


def _preview(value: str | None, limit: int = 180) -> str:
    text = _one_line(value or "")
    if not text:
        return "(none)"
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _fallback_alert_action(assessment: MeaningfulChangeAssessment) -> ActionDecision:
    return ActionDecision(
        action_type="create_alert",
        human_loop_state="notification",
        summary=assessment.summary,
        reason=assessment.reason,
        user_notification=assessment.summary,
        requires_approval=False,
    )


def _reconcile_assessment(
    assessment: MeaningfulChangeAssessment,
    grounded: MeaningfulChangeAssessment | None,
) -> MeaningfulChangeAssessment:
    """Keep the model wording unless the snapshots contradict it."""
    if grounded is None:
        return assessment
    if grounded.meaningful_change:
        if assessment.meaningful_change and assessment.action_required:
            return assessment
        return grounded
    return grounded


def _alert_user_notification(
    *,
    url: str,
    previous: str | None,
    current: str | None,
    assessment: MeaningfulChangeAssessment,
) -> str:
    diff = summarize_text_change(previous, current)
    summary = _one_line(assessment.summary) or diff or "Monitored information changed."
    parts = [summary]
    if previous:
        parts.append(f"Previous: {_one_line(previous)}")
    if current:
        parts.append(f"Current: {_one_line(current)}")
    parts.append(f"Source: {url}")
    return " · ".join(parts)


def create_monitor_record(
    store: MonitorStore,
    goal: str,
    url: str | None = None,
    user_id: str | None = None,
    *,
    kind: str = "website",
) -> dict:
    if kind == "gmail":
        return store.create_monitor(
            goal,
            GMAIL_MONITOR_URL,
            user_id=user_id,
            kind="gmail",
            name=derive_monitor_name(goal),
        )
    validated = validate_url(url or "")
    return store.create_monitor(
        goal,
        validated,
        user_id=user_id,
        kind="website",
        name=derive_monitor_name(goal),
    )


def _should_create_alert(
    change_status: str,
    assessment: MeaningfulChangeAssessment | None,
    action: ActionDecision | None,
    *,
    previous: str | None = None,
    current: str | None = None,
) -> bool:
    if change_status != "changed" or assessment is None or action is None:
        return False
    if observation_texts_equivalent(previous, current):
        return False
    if not assessment.meaningful_change:
        return False
    if not assessment.action_required:
        return False
    if action.action_type == "ignore" or action.human_loop_state == "no_action":
        return False
    return action.action_type in {
        "create_alert",
        "notify_user",
        "request_approval",
    }


def _result_status(
    change_status: str,
    meaningful_change: bool | None,
) -> str:
    if change_status == "changed" and meaningful_change:
        return "meaningful_change"
    return change_status


def _tool_status(change_status: str) -> str:
    if change_status == "baseline":
        return "initialized"
    return change_status


def _monitoring_trace_summary(result: SentinelResult) -> str:
    if not result.tool_used:
        return "Did not fetch a source observation."
    if result.observed_facts:
        return "Fetched the source. Observed: " + "; ".join(result.observed_facts[:4])
    return "Fetched the source."


def _check_summary(
    *,
    change_status: str,
    result: SentinelResult,
    assessment: MeaningfulChangeAssessment | None,
    action: ActionDecision | None,
) -> str:
    if change_status == "unchanged":
        return UNCHANGED_SUMMARY
    if action is not None:
        return action.user_notification or action.summary or result.summary
    if assessment is not None:
        return assessment.summary
    if result.observed_facts:
        return "Observed: " + "; ".join(result.observed_facts)
    return result.summary


def _content_for_analysis(result: SentinelResult) -> str | None:
    return clip_page_text(result.relevant_excerpt) or clip_page_text(result.page_text)


def build_agent_trace(
    *,
    change_status: str,
    tool_used: bool,
    assessment: MeaningfulChangeAssessment | None,
    action: ActionDecision | None,
    monitoring_summary: str | None = None,
) -> tuple[list[str], list[AgentTraceEntry]]:
    """Safe, non-reasoning summaries of which specialists participated."""
    traces: list[AgentTraceEntry] = [
        AgentTraceEntry(
            agent="monitoring",
            role="source observation",
            summary=(
                monitoring_summary
                if monitoring_summary
                else (
                    "Fetched the source."
                    if tool_used
                    else "Did not fetch a source observation."
                )
            ),
        )
    ]
    agents = ["supervisor", "monitoring"]
    if change_status == "changed" and assessment is not None:
        agents.append("analysis")
        traces.append(
            AgentTraceEntry(
                agent="analysis",
                role="goal-aware relevance",
                summary=assessment.summary,
            )
        )
    if change_status == "changed" and action is not None:
        agents.append("action")
        traces.append(
            AgentTraceEntry(
                agent="action",
                role="action decision",
                summary=action.action_type,
            )
        )
    if change_status in {"baseline", "unchanged"}:
        supervisor_summary = (
            "Coordinated the workflow. Analysis and Action were skipped because "
            f"the check is {change_status}."
        )
    elif change_status == "blocked":
        supervisor_summary = (
            "Coordinated the workflow. The source is blocked and requires the user. "
            "Analysis and Action were not used to bypass it."
        )
    elif change_status == "error":
        supervisor_summary = (
            "Coordinated the workflow. The source could not be fetched."
        )
    elif action is None:
        supervisor_summary = (
            "Coordinated the workflow. Action was skipped because the change "
            "was not meaningful and no human-loop block was present."
        )
    else:
        supervisor_summary = (
            "Coordinated the workflow and returned the final decision."
        )
    traces.append(
        AgentTraceEntry(
            agent="supervisor",
            role="coordinator",
            summary=supervisor_summary,
        )
    )
    return agents, traces


def system_status(store: MonitorStore) -> SystemStatusResponse:
    monitors = [
        item for item in store.list_monitors() if item.get("kind", "website") != "gmail"
    ]
    enabled = [item for item in monitors if item.get("enabled")]
    last_checked = None
    for item in enabled:
        checked = item.get("last_checked_at")
        if checked is not None and (last_checked is None or checked > last_checked):
            last_checked = checked
    if not enabled:
        scheduler: str = "idle"
        message = "Scheduler idle. No enabled website monitors."
    elif last_checked is None:
        scheduler = "never"
        message = (
            "Scheduler not confirmed. n8n has not checked an enabled website "
            f"monitor yet (expected every {SCHEDULER_INTERVAL_SECONDS} seconds). "
            "Open http://localhost:5678 and confirm the workflow is Active."
        )
    else:
        from datetime import datetime, timezone

        checked_at = last_checked
        if checked_at.tzinfo is None:
            checked_at = checked_at.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - checked_at).total_seconds()
        if age <= SCHEDULER_STALE_SECONDS:
            scheduler = "ok"
            message = (
                f"Scheduler running. Last website check {max(int(age), 0)} "
                f"second(s) ago (n8n every {SCHEDULER_INTERVAL_SECONDS} seconds)."
            )
        else:
            scheduler = "stale"
            message = (
                "Scheduler not running. n8n has not checked recently. "
                "Confirm the workflow is Active and can reach "
                "http://host.docker.internal:8000 from Docker."
            )
    return SystemStatusResponse(
        enabled_monitors=len(enabled),
        total_monitors=len(monitors),
        last_checked_at=last_checked,
        scheduler_interval_seconds=SCHEDULER_INTERVAL_SECONDS,
        scheduler_interval_minutes=SCHEDULER_INTERVAL_MINUTES,
        scheduler=scheduler,  # type: ignore[arg-type]
        message=message,
    )


def _record_failed_check(
    store: MonitorStore,
    monitor: dict,
    *,
    code: str,
    message: str,
    tool_used: bool,
) -> MonitorCheckResponse:
    change_status = "blocked" if is_blocking_error_code(code) else "error"
    human_loop = "blocked_requires_user" if change_status == "blocked" else None
    failure_hash = hash_content(f"{code}:{message}")
    monitoring_summary = (
        "Source requires user intervention."
        if change_status == "blocked"
        else "Could not fetch the source."
    )
    agents, agent_trace = build_agent_trace(
        change_status=change_status,
        tool_used=tool_used,
        assessment=None,
        action=None,
        monitoring_summary=f"{monitoring_summary} {message}",
    )
    observation = store.add_observation(
        monitor["id"],
        content_hash=failure_hash,
        summary=message,
        change_status=change_status,
        agents=agents,
        agent_trace=[item.model_dump() for item in agent_trace],
    )
    store.update_after_check(
        monitor["id"],
        previous_content=monitor.get("previous_content"),
        previous_content_hash=monitor.get("previous_content_hash"),
        last_change=change_status,
        status=change_status,
    )
    _log(
        "[Monitor] Blocked" if change_status == "blocked" else "[Monitor] Fetch failed",
        code=code,
        error=message,
    )
    return MonitorCheckResponse(
        monitor_id=monitor["id"],
        goal=monitor["goal"],
        url=monitor["url"],
        status=_tool_status(change_status),  # type: ignore[arg-type]
        changed=False,
        change_status=change_status,  # type: ignore[arg-type]
        hash_changed=False,
        summary=message,
        message=message,
        previous_checked_at=None,
        checked_at=observation["checked_at"],
        tool_used=tool_used,
        content_hash=failure_hash,
        human_loop_state=human_loop,  # type: ignore[arg-type]
        agents=agents,
        agent_trace=agent_trace,
        result_status="blocked" if change_status == "blocked" else "fetch_error",
    )


def fetch_monitor_page(goal: str, url: str) -> SentinelResult:
    """Fetch a page with the webpage tool. Scheduled checks do not call the model."""
    observation = check_webpage(url)
    page_text = observation.text or ""
    excerpt = clip_page_text(page_text)
    logger.info(
        "[FETCH] status=%s method=%s final_url=%s content_length=%s hash=%s",
        observation.status_code,
        observation.fetch_method,
        observation.final_url or observation.url,
        observation.normalized_chars or len(page_text),
        observation.content_hash,
    )
    logger.info("FETCH_SUCCESS")
    return SentinelResult(
        goal=goal,
        url=observation.final_url or observation.url or url,
        summary=excerpt or "Fetched the webpage.",
        tool_used=True,
        model="webpage-tool",
        content_hash=observation.content_hash,
        page_text=page_text,
        title=observation.title,
        fetch_method=observation.fetch_method,
        observation_status="ok",
        relevant_excerpt=excerpt,
    )


def run_monitor_check(
    store: MonitorStore,
    monitor_id: str,
    *,
    run_fn: Callable[[str, str], SentinelResult] | None = None,
    assess_fn: Callable[
        [str, str | None, str | None], MeaningfulChangeAssessment
    ]
    | None = None,
    action_fn: Callable[[str, MeaningfulChangeAssessment], ActionDecision]
    | None = None,
) -> MonitorCheckResponse:
    monitor = store.get_monitor(monitor_id)
    if monitor is None:
        raise KeyError(monitor_id)
    if not monitor.get("enabled", True):
        raise MonitoringCheckError(
            "disabled",
            "This monitor is disabled. Enable it to check, or wait for n8n "
            "to skip it automatically.",
            http_status=409,
        )
    if monitor.get("kind") == "gmail":
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        return MonitorCheckResponse(
            monitor_id=monitor["id"],
            goal=monitor["goal"],
            url=monitor["url"],
            status="unchanged",
            changed=False,
            change_status="unchanged",
            hash_changed=False,
            summary="Gmail monitors are event-driven and are not checked on a schedule.",
            message="Gmail monitors are event-driven.",
            previous_checked_at=monitor.get("last_checked_at"),
            checked_at=now,
            tool_used=False,
            content_hash=monitor.get("previous_content_hash") or "",
            result_status="unchanged",
        )

    lock = _lock_for(monitor_id)
    if not lock.acquire(blocking=False):
        raise MonitoringCheckError(
            "in_progress",
            "This monitor is already being checked. The scheduler will try again.",
            http_status=409,
        )
    try:
        return _run_monitor_check_locked(
            store,
            monitor,
            run_fn=run_fn,
            assess_fn=assess_fn,
            action_fn=action_fn,
        )
    finally:
        lock.release()


def _run_monitor_check_locked(
    store: MonitorStore,
    monitor: dict,
    *,
    run_fn: Callable[[str, str], SentinelResult] | None,
    assess_fn: Callable[
        [str, str | None, str | None], MeaningfulChangeAssessment
    ]
    | None,
    action_fn: Callable[[str, MeaningfulChangeAssessment], ActionDecision]
    | None,
) -> MonitorCheckResponse:
    monitor_id = monitor["id"]
    previous = store.get_latest_observation(monitor_id)
    previous_hash = monitor.get("previous_content_hash")
    logger.info("[MONITOR CHECK] monitor_id=%s goal=%s url=%s", monitor_id, monitor["goal"], monitor["url"])
    logger.info("CHECK_STARTED")
    _log(f"[Scheduler] Checking monitor {monitor_id}", url=monitor["url"])

    def _default_run(goal: str, url: str) -> SentinelResult:
        _log(f"[Monitor] Fetching {url}")
        return fetch_monitor_page(goal, url)

    execute = run_fn or _default_run

    try:
        result = execute(monitor["goal"], monitor["url"])
    except AgentConfigError as exc:
        raise MonitoringCheckError(
            "agent_config",
            str(exc),
            http_status=503,
        ) from exc
    except WebpageToolError as exc:
        return _record_failed_check(
            store,
            monitor,
            code=exc.code,
            message=exc.message,
            tool_used=True,
        )

    if result.tool_error or not result.content_hash:
        code = "tool_failure"
        if result.observation_status == "blocked_requires_user":
            code = "blocked_requires_user"
        return _record_failed_check(
            store,
            monitor,
            code=code,
            message=result.tool_error
            or "The webpage tool did not return a valid observation.",
            tool_used=result.tool_used,
        )

    current_hash = comparison_hash(result)
    if not current_hash:
        return _record_failed_check(
            store,
            monitor,
            code="tool_failure",
            message="The webpage tool did not return a valid observation.",
            tool_used=result.tool_used,
        )
    current_observation = (
        (result.page_text or "").strip()
        or relevant_observation_text(result)
        or _content_for_analysis(result)
    )
    previous_observation = monitor.get("previous_content")
    hash_changed = previous_hash is not None and previous_hash != current_hash
    texts_match = observation_texts_equivalent(previous_observation, current_observation)
    goal_match = extract_goal_match(
        monitor["goal"], previous_observation, current_observation
    )
    logger.info("[CHANGE] previous_hash=%s current_hash=%s hash_changed=%s", previous_hash or "(none)", current_hash, str(hash_changed and not texts_match).lower())
    logger.info(
        "[GOAL MATCH] targets=%s previous_present=%s current_present=%s previous_excerpt=%s current_excerpt=%s",
        goal_match.targets or "(none)",
        goal_match.previous_contains or "(n/a)",
        goal_match.current_contains or "(n/a)",
        _preview(goal_match.previous_excerpt),
        _preview(goal_match.current_excerpt),
    )
    logger.info("[Monitor] Previous hash: %s", previous_hash or "(none)")
    logger.info("[Monitor] Current hash: %s", current_hash)
    logger.info("[Monitor] Hash changed: %s", str(hash_changed and not texts_match).lower())
    if previous_hash is None:
        changed = False
        change_status = "baseline"
        assessment: MeaningfulChangeAssessment | None = None
        action: ActionDecision | None = None
        _log("[Monitor] Baseline stored")
    elif not hash_changed or texts_match:
        changed = False
        change_status = "unchanged"
        assessment = None
        action = None
        _log("[Monitor] Hash unchanged")
    else:
        changed = True
        change_status = "changed"
        grounded = ground_meaningful_change(
            monitor["goal"],
            previous_observation,
            current_observation,
        )
        assess = assess_fn or assess_page_change
        act = action_fn or decide_action
        try:
            assessment = assess(
                monitor["goal"],
                previous_observation,
                current_observation,
            )
            assessment = _reconcile_assessment(assessment, grounded)
            if not assessment.previous_relevant_content:
                assessment.previous_relevant_content = (
                    (grounded.previous_relevant_content if grounded else None)
                    or goal_match.previous_excerpt
                    or None
                )
            if not assessment.current_relevant_content:
                assessment.current_relevant_content = (
                    (grounded.current_relevant_content if grounded else None)
                    or goal_match.current_excerpt
                    or None
                )
        except AgentConfigError as exc:
            raise MonitoringCheckError(
                "agent_config",
                str(exc),
                http_status=503,
            ) from exc
        except Exception as exc:
            if grounded is None:
                store.mark_checked(monitor_id)
                raise MonitoringCheckError(
                    "analysis_error",
                    "Sentinel could not assess whether the page change is meaningful.",
                ) from exc
            assessment = grounded
            logger.info("[Analysis] Model assessment failed; using the content comparison.")
        if not assessment.previous_relevant_content:
            assessment.previous_relevant_content = goal_match.previous_excerpt or None
        if not assessment.current_relevant_content:
            assessment.current_relevant_content = goal_match.current_excerpt or None
        blocked = detect_human_loop_block(page_text=result.page_text)
        try:
            if assessment.meaningful_change or blocked is not None:
                action = act(monitor["goal"], assessment)
                action = apply_human_loop_safety(
                    action,
                    page_text=result.page_text,
                )
            else:
                action = None
        except AgentConfigError as exc:
            raise MonitoringCheckError(
                "agent_config",
                str(exc),
                http_status=503,
            ) from exc
        except Exception as exc:
            if assessment.meaningful_change and assessment.action_required:
                action = _fallback_alert_action(assessment)
                logger.info("[Action] Model decision failed; creating an alert from the content comparison.")
            else:
                store.mark_checked(monitor_id)
                raise MonitoringCheckError(
                    "action_error",
                    "Sentinel could not decide what to do after a meaningful page change.",
                ) from exc
        if (
            grounded is not None
            and grounded.meaningful_change
            and assessment.meaningful_change
            and (action is None or action.action_type == "ignore")
        ):
            action = _fallback_alert_action(assessment)
        logger.info("[Analysis] Goal: %s", _preview(monitor["goal"]))
        logger.info(
            "[Analysis] Previous relevant content: %s",
            _preview(previous_observation),
        )
        logger.info(
            "[Analysis] Current relevant content: %s",
            _preview(current_observation),
        )
        logger.info(
            "[ANALYSIS] meaningful_change=%s action_required=%s reason=%s",
            str(assessment.meaningful_change).lower(),
            str(assessment.action_required).lower(),
            _preview(assessment.reason),
        )
        logger.info(
            "[ACTION] decision=%s",
            action.action_type if action is not None else "ignore",
        )

    summary = _check_summary(
        change_status=change_status,
        result=result,
        assessment=assessment,
        action=action,
    )
    agents, agent_trace = build_agent_trace(
        change_status=change_status,
        tool_used=result.tool_used,
        assessment=assessment,
        action=action,
        monitoring_summary=_monitoring_trace_summary(result),
    )
    observation = store.add_observation(
        monitor_id,
        content_hash=current_hash,
        summary=summary,
        meaningful_change=assessment.meaningful_change if assessment else None,
        reason=assessment.reason if assessment else None,
        action_required=assessment.action_required if assessment else None,
        change_status=change_status,
        agents=agents,
        agent_trace=[item.model_dump() for item in agent_trace],
        observed_facts=list(result.observed_facts),
        observed_fact_records=[
            item.model_dump() for item in result.observed_fact_records
        ],
        relevant_excerpt=result.relevant_excerpt,
        title=result.title,
        fetch_method=result.fetch_method,
        source_url=result.url,
    )
    stored_content = current_observation
    if stored_content is None:
        stored_content = monitor.get("previous_content")
    store.update_after_check(
        monitor_id,
        previous_content=stored_content,
        previous_content_hash=current_hash,
        last_change=change_status,
        status="monitoring",
        content_changed=change_status == "changed",
    )

    alert_id = None
    notification_status = None
    alert_notification = None
    existing_alert = store.get_alert_by_monitor_and_hash(monitor_id, current_hash)
    if (
        _should_create_alert(
            change_status,
            assessment,
            action,
            previous=monitor.get("previous_content"),
            current=current_observation,
        )
        and assessment
        and action
        and existing_alert is None
    ):
        alert_notification = _alert_user_notification(
            url=monitor["url"],
            previous=assessment.previous_relevant_content
            or monitor.get("previous_content"),
            current=assessment.current_relevant_content or current_observation,
            assessment=assessment,
        )
        try:
            pending = store.get_pending_alert_for_monitor(monitor_id)
            if pending is not None:
                alert = store.update_alert(
                    pending["alert_id"],
                    content_hash=current_hash,
                    summary=summary,
                    reason=assessment.reason,
                    action_required=assessment.action_required,
                    action_type=action.action_type,
                    human_loop_state=action.human_loop_state,
                    user_notification=alert_notification,
                ) or pending
            else:
                alert = store.create_alert(
                    monitor_id,
                    content_hash=current_hash,
                    summary=summary,
                    reason=assessment.reason,
                    action_required=assessment.action_required,
                    action_type=action.action_type,
                    human_loop_state=action.human_loop_state,
                    user_notification=alert_notification,
                )
            if not alert or not alert.get("alert_id"):
                raise RuntimeError("Failed to persist alert.")
            alert_id = alert["alert_id"]
        except MonitoringCheckError:
            raise
        except Exception as exc:
            raise MonitoringCheckError(
                "alert_persistence_error",
                "The page change was meaningful but Sentinel could not save the alert.",
            ) from exc
    if change_status == "changed":
        logger.info(
            "[ALERT] Decision: %s Monitor ID: %s Meaningful change: %s Alert created: %s Alert ID: %s",
            action.action_type if action is not None else "ignore",
            monitor_id,
            str(assessment.meaningful_change).lower() if assessment else "n/a",
            str(alert_id is not None).lower(),
            alert_id or "(none)",
        )
        logger.info("[Alert] Alert created: %s", str(alert_id is not None).lower())
        logger.info("[Alert] Alert ID: %s", alert_id or "(none)")

    if action is not None:
        store.add_action_history(
            monitor_id,
            action_type=action.action_type,
            human_loop_state=action.human_loop_state,
            summary=action.summary,
            alert_id=alert_id,
        )

    return MonitorCheckResponse(
        monitor_id=monitor_id,
        goal=monitor["goal"],
        url=monitor["url"],
        status=_tool_status(change_status),  # type: ignore[arg-type]
        changed=changed,
        change_status=change_status,  # type: ignore[arg-type]
        hash_changed=changed,
        summary=summary,
        message=summary,
        old_content=monitor.get("previous_content") if changed else None,
        new_content=current_observation if changed else None,
        previous_checked_at=previous["checked_at"] if previous else None,
        checked_at=observation["checked_at"],
        tool_used=result.tool_used,
        content_hash=current_hash,
        meaningful_change=assessment.meaningful_change if assessment else None,
        reason=assessment.reason if assessment else None,
        action_required=assessment.action_required if assessment else None,
        alert_id=alert_id,
        action_type=action.action_type if action else None,
        human_loop_state=action.human_loop_state if action else None,
        user_notification=alert_notification
        if alert_notification
        else (action.user_notification if action else None),
        notification_status=notification_status,
        agents=agents,
        agent_trace=agent_trace,
        observed_facts=list(result.observed_facts),
        observed_fact_records=list(result.observed_fact_records),
        relevant_excerpt=result.relevant_excerpt,
        fetch_method=result.fetch_method,
        title=result.title,
        previous_observation=monitor.get("previous_content") if changed else None,
        current_observation=current_observation,
        result_status=_result_status(
            change_status,
            assessment.meaningful_change if assessment else None,
        ),
    )
