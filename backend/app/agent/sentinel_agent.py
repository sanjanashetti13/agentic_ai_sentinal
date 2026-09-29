from __future__ import annotations

import json
import re
from typing import Any

from strands import Agent, tool
from strands.models.openai import OpenAIModel
from pydantic import BaseModel, Field

from app.config import Settings, get_settings
from app.models.schemas import MeaningfulChangeAssessment, ObservedFact, SentinelResult

# Internal structured output for the Monitoring Agent. Hashes and page
# text in this model are ignored; the tool payload is authoritative.
class MonitoringAgentJSON(BaseModel):
    url: str | None = None
    title: str | None = None
    fetch_method: str | None = None
    status: str | None = None
    readable_content: str | None = None
    relevant_excerpt: str | None = None
    observed_facts: list[Any] = Field(default_factory=list)
    content_hash: str | None = None
    fetched_at: str | None = None
    reasoning: str | None = None
from app.tools.web_monitor import WebpageToolError
from app.tools.web_monitor import check_webpage as fetch_webpage

PAGE_TEXT_CHAR_LIMIT = 8000
FACT_CHAR_LIMIT = 400
REASONING_CHAR_LIMIT = 400
MAX_OBSERVED_FACTS = 8
UNCHANGED_SUMMARY = "No meaningful change detected."
_BLOCKING_TOOL_CODES = {
    "captcha_required",
    "otp_required",
    "authentication_required",
    "bot_protection",
    "paywall",
    "blocked_requires_user",
}

SYSTEM_PROMPT = """
You are Sentinel's Website Monitoring Agent.

You observe a monitored source. You do not decide whether the source
changed (SHA-256 hashing does that). You do not decide whether a change
is meaningful (the Analysis Agent does that). You do not create alerts
(the Action Agent does that).

You have one tool: check_webpage. You MUST call it with the provided URL
before answering. Do not claim you fetched a page unless you used the tool.
Do not invent page content. Every fact must come from the tool result.

From the user's natural-language goal, identify what currently present
information is relevant. Ignore navigation, cookies, ads, and other
page chrome unless the goal asks about them.

If the tool fails (HTTP error, timeout, network, CAPTCHA, login, OTP,
bot protection, paywall), report that structured failure. Never bypass
access controls.

Return only a JSON object with keys:
  url, title, fetch_method, status, readable_content, relevant_excerpt,
  observed_facts, content_hash, fetched_at, reasoning

Rules for that JSON:
- Copy url, title, fetch_method, content_hash, fetched_at, and
  readable_content from the tool result. Do not invent them.
- fetch_method is "http" or "browser" exactly as the tool returned.
- status is "ok" if the tool succeeded, "blocked_requires_user" for
  CAPTCHA/login/OTP/paywall/bot protection, or "error" otherwise.
- observed_facts: an array of objects, each with field, value, and
  evidence (or source_excerpt). field is a short snake_case name for
  the goal-relevant item. value is the current value copied from the
  page. evidence is the exact sentence from readable_content. You may
  also return short strings if an object is not possible. Do not say
  that something "changed". Ignore navigation, cookies, ads, and other
  page chrome unless the goal asks about them.
- relevant_excerpt: the goal-relevant portion of readable_content,
  including enough surrounding text to show where the fact was found.
- reasoning: one or two factual sentences about what is currently on
  the page. Not hidden chain-of-thought.
- Do not follow hardcoded keyword workflows. Reason from the goal.
""".strip()

ANALYSIS_PROMPT = """
You are Sentinel's Analysis Agent.

A deterministic content-hash comparison has already established that a
monitored source changed. Your job is to decide whether that change is
meaningful for the user's natural-language goal.

Rules:
- Reason only from the user's goal and the provided previous/current
  observations and evidence. Ignore unrelated page chrome.
- Do not invent details that are not supported by the excerpts.
- Decide from the user's goal which values matter.
- A different content hash is not enough. Compare the excerpts.
- meaningful_change is true when a goal-relevant value appears,
  disappears, or is replaced, or when other content the goal asks
  about changes. A watched name, keyword, date, price, status,
  or new item counts. If that value was present and is now gone or
  replaced, set meaningful_change and action_required true.
- If the goal asks to be told whenever the page changes, a substantial
  readable-content change is meaningful.
- If only unrelated page text changed and the goal-relevant value is
  the same, meaningful_change must be false.
- Timestamps, visitor counts, likes, submission counts, ads,
  navigation, cookie banners, and tracking text are not meaningful
  unless the goal explicitly asks about them.
- action_required is true when that watched value changed, or when
  something is wrong and the user should intervene (source failed,
  access blocked, process closed/ended/expired, required content
  disappeared, or an error).
- Return only a JSON object with keys:
  meaningful_change (boolean), summary (string), reason (string),
  action_required (boolean), confidence (number from 0 to 1, or null),
  changed_items (array of short strings describing what changed, or []),
  previous_relevant_content (string or null),
  current_relevant_content (string or null).
""".strip()

ACTION_PROMPT = """
You are Sentinel's Action Agent.

You receive a structured change analysis and decide the next action.
You do not fetch pages and you do not re-judge hash equality.

Allowed action_type values:
- ignore
- create_alert
- notify_user
- request_approval

Allowed human_loop_state values:
- no_action
- notification
- approval_required
- blocked_requires_user

Safety rules:
- Never bypass CAPTCHA, OTP, login, or other security controls.
- If the excerpts or analysis indicate a CAPTCHA, OTP, or authentication
  wall, return blocked_requires_user and request_approval.
- For consequential external operations (purchases, applications, sending
  messages, changing accounts), require human approval.
- Do not take dangerous autonomous actions.
- If the change is not meaningful, choose ignore and no_action.
- If meaningful_change and action_required are true, do not return
  ignore. Use create_alert or notify_user.
- Do not notify on every check. Only create_alert or notify_user when
  a goal-relevant value actually changed or the user must intervene.
- If something is wrong and the user must intervene, prefer notify_user
  or create_alert. Use request_approval when a human must authorize more.

Return only a JSON object with keys:
  action_type, human_loop_state, summary, reason, user_notification,
  requires_approval (boolean), blocked_reason (string or null).
""".strip()

SUPERVISOR_PROMPT = """
You are Sentinel's Supervisor Agent.

You coordinate specialist agents. You do not fetch webpages yourself,
you do not replace hash comparison, and you do not skip specialists.

Specialist tools:
- monitoring_agent: obtain a structured source observation.
- analysis_agent: decide whether a hash-detected change is meaningful.
- action_agent: decide the next alert/notification/approval action.

Workflow:
1. Use monitoring_agent when current source information is needed.
2. Use analysis_agent only after a change has already been detected.
3. Use action_agent after analysis, to decide what to do.
4. Synthesize a concise final result from the specialists' structured outputs.

Do not invent observations. Do not bypass human-in-the-loop safety.
n8n is not an agent; you are coordinating the AI specialists only.
""".strip()


class AgentConfigError(Exception):
    """Raised when the Sentinel agent cannot be configured."""


@tool(name="check_webpage")
def check_webpage(url: str) -> dict[str, Any]:
    """Fetch a public webpage and return a normalized observation.

    This is the only way to obtain page content. Default path is HTTPX
    plus BeautifulSoup. Playwright is used only when the HTTP response
    is a JavaScript-heavy empty shell. Do not invent page content.
    Do not bypass CAPTCHA, login, OTP, bot protection, or paywalls.

    Args:
        url: The http:// or https:// URL to inspect.
    """
    try:
        observation = fetch_webpage(url)
        return observation.model_dump(mode="json")
    except WebpageToolError as exc:
        return exc.to_dict()


def groq_request_params(model_id: str) -> dict[str, Any]:
    """Groq Chat Completions parameters that avoid reasoningContent issues.

    GPT-OSS models return a separate reasoning field that Strands' Chat
    Completions provider cannot send back on the next turn. Groq's
    include_reasoning=false keeps that field out of the response.

    Qwen reasoning can be turned off with reasoning_effort=none.
    """
    params: dict[str, Any] = {
        "temperature": 0.2,
        "max_tokens": 2048,
    }
    extra_body: dict[str, Any] = {}
    if model_id.startswith("openai/gpt-oss"):
        extra_body["include_reasoning"] = False
    elif model_id.startswith("qwen/"):
        extra_body["reasoning_effort"] = "none"
    if extra_body:
        params["extra_body"] = extra_body
    return params


def create_groq_model(settings: Settings | None = None) -> OpenAIModel:
    settings = settings or get_settings()
    if not settings.groq_api_key.strip():
        raise AgentConfigError(
            "GROQ_API_KEY is missing. Copy backend/.env.example to "
            "backend/.env and add a Groq API key."
        )

    return OpenAIModel(
        client_args={
            "api_key": settings.groq_api_key,
            "base_url": settings.groq_base_url,
            "timeout": 20.0,
            "max_retries": 0,
        },
        model_id=settings.groq_model,
        params=groq_request_params(settings.groq_model),
    )


def create_ollama_model(settings: Settings | None = None) -> OpenAIModel:
    settings = settings or get_settings()
    if not settings.ollama_model.strip():
        raise AgentConfigError(
            "OLLAMA_MODEL is missing. Set OLLAMA_MODEL to use the local fallback."
        )
    return OpenAIModel(
        client_args={
            "api_key": "ollama",
            "base_url": settings.ollama_base_url,
            "timeout": 20.0,
            "max_retries": 0,
        },
        model_id=settings.ollama_model,
        params={"temperature": 0.2, "max_tokens": 2048},
    )


def create_model(settings: Settings | None = None) -> OpenAIModel:
    settings = settings or get_settings()
    provider = settings.model_provider.strip().lower()
    if provider == "ollama":
        return create_ollama_model(settings)
    return create_groq_model(settings)


def create_sentinel_agent(
    model: Any | None = None,
    tools: list[Any] | None = None,
) -> Agent:
    """Create Sentinel's Monitoring Agent (backward-compatible factory)."""
    return create_monitoring_agent(model=model, tools=tools)


def create_monitoring_agent(
    model: Any | None = None,
    tools: list[Any] | None = None,
) -> Agent:
    """Create the Monitoring Agent. It observes sources; it does not analyze."""
    return Agent(
        name="monitoring_agent",
        description=(
            "Observes a monitored webpage using check_webpage and returns "
            "goal-relevant facts from the actual tool result. Does not "
            "decide whether content changed."
        ),
        model=model or create_model(),
        system_prompt=SYSTEM_PROMPT,
        tools=[check_webpage] if tools is None else tools,
        callback_handler=None,
        retry_strategy=None,
    )


def create_analysis_agent(model: Any | None = None) -> Agent:
    """Create the Analysis Agent. It reasons about already-detected changes."""
    return Agent(
        name="analysis_agent",
        description=(
            "Decides whether a hash-detected change is meaningful for the "
            "user's natural-language goal."
        ),
        model=model or create_model(),
        system_prompt=ANALYSIS_PROMPT,
        tools=[],
        callback_handler=None,
        retry_strategy=None,
    )


def create_action_agent(model: Any | None = None) -> Agent:
    """Create the Action Agent. It decides alerts, notifications, and HITL."""
    return Agent(
        name="action_agent",
        description=(
            "Decides whether to ignore, create an alert, notify the user, "
            "or request approval. Never bypasses CAPTCHA, OTP, or login."
        ),
        model=model or create_model(),
        system_prompt=ACTION_PROMPT,
        tools=[],
        callback_handler=None,
        retry_strategy=None,
    )


def _content_blocks(message: Any) -> list[dict[str, Any]]:
    if isinstance(message, dict):
        content = message.get("content", [])
    else:
        content = getattr(message, "content", [])
    return content if isinstance(content, list) else []


def _parse_json_object(text: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _payload_from_tool_result(tool_result: dict[str, Any]) -> dict[str, Any] | None:
    for item in tool_result.get("content") or []:
        if not isinstance(item, dict):
            continue
        raw_json = item.get("json")
        if isinstance(raw_json, dict):
            return raw_json
        text = item.get("text")
        if isinstance(text, str):
            parsed = _parse_json_object(text)
            if parsed is not None:
                return parsed
    return None


def extract_check_webpage_payload(agent: Any) -> dict[str, Any] | None:
    """Read the structured check_webpage observation from Strands messages.

    Strands runs tools in a worker thread, so thread-local/contextvar capture
    is unreliable. The tool return value is stored on the agent as toolResult.
    """
    latest: dict[str, Any] | None = None
    webpage_tool_ids: set[str] = set()
    for message in getattr(agent, "messages", []):
        for block in _content_blocks(message):
            if not isinstance(block, dict):
                continue
            tool_use = block.get("toolUse")
            if isinstance(tool_use, dict) and tool_use.get("name") == "check_webpage":
                tool_id = tool_use.get("toolUseId")
                if isinstance(tool_id, str):
                    webpage_tool_ids.add(tool_id)
            tool_result = block.get("toolResult")
            if not isinstance(tool_result, dict):
                continue
            result_id = tool_result.get("toolUseId")
            if webpage_tool_ids and isinstance(result_id, str) and result_id not in webpage_tool_ids:
                continue
            parsed = _payload_from_tool_result(tool_result)
            if parsed is not None:
                latest = parsed
    return latest


def used_check_webpage(agent: Agent) -> bool:
    for message in getattr(agent, "messages", []):
        for block in _content_blocks(message):
            if not isinstance(block, dict):
                continue
            tool_use = block.get("toolUse")
            if isinstance(tool_use, dict) and tool_use.get("name") == "check_webpage":
                return True
    return False


def _final_text(result: Any) -> str:
    message = getattr(result, "message", None)
    texts: list[str] = []
    for block in _content_blocks(message):
        if isinstance(block, dict) and block.get("text"):
            texts.append(str(block["text"]))
    if texts:
        return "\n".join(texts).strip()
    return str(result).strip()


def clip_page_text(text: str | None, limit: int = PAGE_TEXT_CHAR_LIMIT) -> str | None:
    """Keep a bounded readable snapshot for later comparison."""
    if text is None:
        return None
    cleaned = text.strip()
    if not cleaned:
        return None
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[:limit]


_TOKEN_RE = re.compile(r"[A-Za-z0-9$%.]+")
_CHANGE_CLAIM_RE = re.compile(
    r"\b(changed|has changed|no longer|used to be|previously was)\b",
    re.IGNORECASE,
)


def _collapsed(text: str) -> str:
    return " ".join(text.lower().split())


def text_is_grounded(candidate: str, source: str) -> bool:
    """True when candidate content is supported by the fetched page text."""
    cleaned = candidate.strip()
    if not cleaned or not source.strip():
        return False
    if _collapsed(cleaned) in _collapsed(source):
        return True
    tokens = [token for token in _TOKEN_RE.findall(cleaned.lower()) if len(token) > 1]
    if len(tokens) < 2:
        return False
    haystack = source.lower()
    hits = sum(1 for token in tokens if token in haystack)
    return (hits / len(tokens)) >= 0.7


def _fact_display(record: ObservedFact) -> str:
    value = " ".join(record.value.split())
    field = (record.field or "").strip()
    if field and value:
        return f"{field}: {value}"[:FACT_CHAR_LIMIT]
    return value[:FACT_CHAR_LIMIT]


def parse_observed_fact(raw: Any) -> ObservedFact | None:
    if isinstance(raw, ObservedFact):
        value = raw.value.strip()
        return raw if value else None
    if isinstance(raw, str):
        fact = " ".join(raw.split())
        if not fact:
            return None
        return ObservedFact(value=fact[:FACT_CHAR_LIMIT], evidence=fact[:FACT_CHAR_LIMIT])
    if isinstance(raw, dict):
        value = " ".join(str(raw.get("value") or "").split())
        if not value and raw.get("field"):
            value = " ".join(str(raw.get("field")).split())
        if not value:
            return None
        evidence = raw.get("evidence") or raw.get("source_excerpt")
        evidence_text = " ".join(str(evidence).split()) if evidence else None
        field = str(raw.get("field")).strip() if raw.get("field") else None
        heading = str(raw.get("heading")).strip() if raw.get("heading") else None
        return ObservedFact(
            field=field,
            value=value[:FACT_CHAR_LIMIT],
            evidence=(evidence_text[:FACT_CHAR_LIMIT] if evidence_text else None),
            source_excerpt=(evidence_text[:FACT_CHAR_LIMIT] if evidence_text else None),
            heading=heading,
        )
    return None


def ground_observed_fact_records(
    facts: list[Any],
    page_text: str,
) -> list[ObservedFact]:
    grounded: list[ObservedFact] = []
    for raw in facts:
        record = parse_observed_fact(raw)
        if record is None:
            continue
        if not text_is_grounded(record.value, page_text):
            continue
        if record.evidence and not text_is_grounded(record.evidence, page_text):
            record = record.model_copy(update={"evidence": None, "source_excerpt": None})
        grounded.append(record)
        if len(grounded) >= MAX_OBSERVED_FACTS:
            break
    return grounded


def ground_observed_facts(facts: list[Any], page_text: str) -> list[str]:
    """Keep only short facts that appear in the fetched page."""
    return [_fact_display(item) for item in ground_observed_fact_records(facts, page_text)]


def ground_relevant_excerpt(excerpt: str | None, page_text: str | None) -> str | None:
    page = clip_page_text(page_text)
    if not page:
        return None
    cleaned = (excerpt or "").strip()
    if cleaned and text_is_grounded(cleaned, page):
        return clip_page_text(cleaned)
    return page


def normalize_fetch_method(value: Any) -> str | None:
    if value == "playwright":
        return "browser"
    if value in {"http", "browser"}:
        return value
    return None


def observation_status_from_tool(
    payload: dict[str, Any] | None,
    *,
    tool_used: bool,
) -> str:
    if not tool_used or payload is None:
        return "error"
    error = payload.get("error")
    if not error:
        return "ok"
    if error in _BLOCKING_TOOL_CODES or payload.get("human_loop_state") == "blocked_requires_user":
        return "blocked_requires_user"
    return "error"


def parse_monitoring_payload(text: str) -> dict[str, Any] | None:
    try:
        return parse_structured_payload(text, "not structured")
    except ValueError:
        return None


def _has_observation_fields(payload: dict[str, Any] | None) -> bool:
    if not payload:
        return False
    facts = payload.get("observed_facts")
    excerpt = payload.get("relevant_excerpt")
    return bool(isinstance(facts, list) and facts) or bool(
        isinstance(excerpt, str) and excerpt.strip()
    )


def _invoke_monitoring_agent(agent: Any, prompt: str) -> Any:
    try:
        return agent(
            prompt,
            structured_output_model=MonitoringAgentJSON,
            structured_output_prompt=(
                "Return only the monitoring JSON object described in your "
                "instructions, using the check_webpage tool result. Do not "
                "invent facts. Do not decide whether the page changed."
            ),
        )
    except TypeError:
        return agent(prompt)


def structured_observation_text(agent: Any, agent_text: str) -> str:
    """Prefer JSON already returned; otherwise ask Strands for structured output."""
    if _has_observation_fields(parse_monitoring_payload(agent_text)):
        return agent_text
    structured_fn = getattr(agent, "structured_output", None)
    if not callable(structured_fn):
        return agent_text
    try:
        parsed = structured_fn(
            MonitoringAgentJSON,
            "Return only the monitoring JSON object from the tool observation. "
            "Do not invent facts. Do not decide whether the page changed.",
        )
    except Exception:
        return agent_text
    if parsed is None:
        return agent_text
    dump = getattr(parsed, "model_dump_json", None)
    if callable(dump):
        return dump()
    if isinstance(parsed, dict):
        return json.dumps(parsed)
    return agent_text


def _agent_text_from_result(agent: Any, result: Any) -> str:
    structured = getattr(result, "structured_output", None)
    dump = getattr(structured, "model_dump_json", None) if structured is not None else None
    if callable(dump):
        return dump()
    return structured_observation_text(agent, _final_text(result))


def format_observation_summary(
    *,
    observed_facts: list[str],
    relevant_excerpt: str | None,
    reasoning: str | None,
    fallback: str,
) -> str:
    if observed_facts:
        return "Observed: " + "; ".join(observed_facts)
    if reasoning:
        return reasoning.strip()
    cleaned = fallback.strip()
    if cleaned.startswith("```"):
        cleaned = ""
    if cleaned.startswith("{"):
        cleaned = ""
    if cleaned:
        return cleaned
    if relevant_excerpt:
        clipped = clip_page_text(relevant_excerpt, limit=500)
        if clipped:
            return clipped
    return "Recorded a source observation."


def monitoring_prompt(goal: str, url: str, previous_excerpt: str | None) -> str:
    previous = clip_page_text(previous_excerpt, limit=2000) or (
        "(none — this is the first observation)"
    )
    return (
        "Observe the monitored webpage. You MUST call check_webpage with the "
        "Page URL below before answering. Do not invent content. Do not decide "
        "whether the page changed; hashing and the Analysis Agent handle that.\n\n"
        f"User monitoring goal:\n{goal}\n\n"
        f"Page URL:\n{url}\n\n"
        "Previous relevant observation (context only; do not judge change):\n"
        f"{previous}\n\n"
        "After the tool returns, extract only facts relevant to the user's goal "
        "and return only the JSON object described in your instructions."
    )


def _tool_string(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if isinstance(value, str) and value.strip():
        return value
    return None


def build_sentinel_result(
    *,
    goal: str,
    url: str,
    model: str,
    tool_used: bool,
    tool_payload: dict[str, Any] | None,
    agent_text: str,
) -> SentinelResult:
    parsed = parse_monitoring_payload(agent_text) or {}
    status = observation_status_from_tool(tool_payload, tool_used=tool_used)

    if not tool_used:
        summary = agent_text.strip() or "The monitoring agent did not fetch the webpage."
        return SentinelResult(
            goal=goal,
            url=url,
            summary=summary,
            tool_used=False,
            model=model,
            tool_error="The monitoring agent did not use the webpage tool.",
            observation_status="error",
            reasoning=clip_page_text(parsed.get("reasoning") if isinstance(parsed.get("reasoning"), str) else None, REASONING_CHAR_LIMIT),
        )

    if tool_payload is None:
        return SentinelResult(
            goal=goal,
            url=url,
            summary=agent_text.strip() or "The webpage tool did not return an observation.",
            tool_used=True,
            model=model,
            tool_error="The webpage tool did not return a valid observation.",
            observation_status="error",
        )

    if tool_payload.get("error"):
        tool_error = str(tool_payload.get("message") or tool_payload.get("error"))
        reasoning = parsed.get("reasoning") if isinstance(parsed.get("reasoning"), str) else None
        return SentinelResult(
            goal=goal,
            url=url,
            summary=agent_text.strip() or tool_error,
            tool_used=True,
            model=model,
            tool_error=tool_error,
            observation_status=status,
            fetch_method=normalize_fetch_method(tool_payload.get("fetch_method")),
            title=_tool_string(tool_payload, "title"),
            reasoning=clip_page_text(reasoning, REASONING_CHAR_LIMIT),
        )

    page_text = _tool_string(tool_payload, "text")
    content_hash = _tool_string(tool_payload, "content_hash")
    title = _tool_string(tool_payload, "title")
    fetch_method = normalize_fetch_method(tool_payload.get("fetch_method")) or "http"
    raw_facts = parsed.get("observed_facts")
    fact_records: list[ObservedFact] = []
    facts: list[str] = []
    if isinstance(raw_facts, list) and page_text:
        fact_records = ground_observed_fact_records(raw_facts, page_text)
        facts = [_fact_display(item) for item in fact_records]
    raw_excerpt = parsed.get("relevant_excerpt")
    excerpt = ground_relevant_excerpt(
        raw_excerpt if isinstance(raw_excerpt, str) else None,
        page_text,
    )
    reasoning = parsed.get("reasoning") if isinstance(parsed.get("reasoning"), str) else None
    reasoning = clip_page_text(reasoning, REASONING_CHAR_LIMIT)
    if reasoning and page_text and not text_is_grounded(reasoning, page_text):
        reasoning = None
    summary = format_observation_summary(
        observed_facts=facts,
        relevant_excerpt=excerpt,
        reasoning=reasoning,
        fallback=agent_text,
    )
    return SentinelResult(
        goal=goal,
        url=_tool_string(tool_payload, "url") or url,
        summary=summary,
        tool_used=True,
        model=model,
        content_hash=content_hash,
        page_text=page_text,
        title=title,
        fetch_method=fetch_method,
        observation_status="ok",
        relevant_excerpt=excerpt,
        observed_facts=facts,
        observed_fact_records=fact_records,
        reasoning=reasoning,
    )


def parse_structured_payload(text: str, error_message: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.removeprefix("```json").removeprefix("```JSON").removeprefix("```")
        cleaned = cleaned.removesuffix("```").strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end <= start:
        raise ValueError(error_message)
    try:
        payload = json.loads(cleaned[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ValueError(error_message) from exc
    if not isinstance(payload, dict):
        raise ValueError(error_message)
    return payload


def parse_meaningful_change_assessment(text: str) -> MeaningfulChangeAssessment:
    """Parse the Analysis Agent's structured change-assessment JSON."""
    payload = parse_structured_payload(
        text,
        "Sentinel did not return a structured change assessment.",
    )
    return MeaningfulChangeAssessment.model_validate(payload)


def assess_page_change(
    goal: str,
    previous_text: str | None,
    current_text: str | None,
    *,
    agent: Agent | None = None,
) -> MeaningfulChangeAssessment:
    """Ask the Analysis Agent whether a detected change is meaningful."""
    cleaned_goal = goal.strip()
    if not cleaned_goal:
        raise ValueError("A monitoring goal is required.")

    from app.tools.content_diff import extract_goal_match
    from app.tools.page_extract import hash_content

    previous_excerpt = clip_page_text(previous_text) or "(not available)"
    current_excerpt = clip_page_text(current_text) or "(not available)"
    match = extract_goal_match(cleaned_goal, previous_text, current_text)
    sentinel = agent or create_analysis_agent()
    prompt = (
        "A SHA-256 comparison already detected that the monitored page changed. "
        "Do not decide whether the hashes differ. Compare the snapshots to the "
        "user's goal.\n\n"
        f"User monitoring goal:\n{cleaned_goal}\n\n"
        f"Previous hash: {hash_content(previous_text or '')}\n"
        f"Current hash: {hash_content(current_text or '')}\n\n"
        f"Previous normalized content:\n{previous_excerpt}\n\n"
        f"Current normalized content:\n{current_excerpt}\n\n"
        f"Goal targets: {', '.join(match.targets) or '(none extracted)'}\n"
        f"Previous target present: {match.previous_contains or '(n/a)'}\n"
        f"Current target present: {match.current_contains or '(n/a)'}\n"
        f"Previous relevant excerpt:\n{match.previous_excerpt or '(none)'}\n"
        f"Current relevant excerpt:\n{match.current_excerpt or '(none)'}\n\n"
        "Assess whether this change is meaningful relative to the user's goal. "
        "If a watched name/value appeared, disappeared, or was replaced, set "
        "meaningful_change and action_required true. If only unrelated chrome "
        "or counters changed, set them false. "
        "Return only the JSON object described in your instructions."
    )
    result = sentinel(prompt)
    assessment = parse_meaningful_change_assessment(_final_text(result))
    if not assessment.previous_relevant_content:
        assessment.previous_relevant_content = match.previous_excerpt or None
    if not assessment.current_relevant_content:
        assessment.current_relevant_content = match.current_excerpt or None
    return assessment


def run_sentinel(
    goal: str,
    url: str,
    *,
    agent: Agent | None = None,
    previous_excerpt: str | None = None,
) -> SentinelResult:
    """Run the Monitoring Agent against one goal and URL.

    The agent must use check_webpage. SHA-256 hashes always come from the
    tool result, never from the model.
    """
    cleaned_goal = goal.strip()
    cleaned_url = url.strip()
    if not cleaned_goal:
        raise ValueError("A monitoring goal is required.")
    if not cleaned_url:
        raise ValueError("A URL is required.")

    settings = get_settings()
    sentinel = agent or create_monitoring_agent()
    result = _invoke_monitoring_agent(
        sentinel,
        monitoring_prompt(cleaned_goal, cleaned_url, previous_excerpt),
    )
    return build_sentinel_result(
        goal=cleaned_goal,
        url=cleaned_url,
        model=settings.groq_model,
        tool_used=used_check_webpage(sentinel),
        tool_payload=extract_check_webpage_payload(sentinel),
        agent_text=_agent_text_from_result(sentinel, result),
    )
