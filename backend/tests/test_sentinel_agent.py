from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock
import json

import pytest

from app.agent.sentinel_agent import (
    SYSTEM_PROMPT,
    AgentConfigError,
    assess_page_change,
    build_sentinel_result,
    check_webpage,
    clip_page_text,
    create_groq_model,
    create_sentinel_agent,
    extract_check_webpage_payload,
    ground_observed_facts,
    groq_request_params,
    parse_meaningful_change_assessment,
    run_sentinel,
    used_check_webpage,
)
from app.config import BACKEND_ENV_FILE, get_settings
from app.models.schemas import WebpageObservation
from app.tools.web_monitor import WebpageToolError


def test_groq_params_hide_gpt_oss_reasoning() -> None:
    params = groq_request_params("openai/gpt-oss-20b")
    assert params["extra_body"]["include_reasoning"] is False


def test_groq_params_disable_qwen_reasoning() -> None:
    params = groq_request_params("qwen/qwen3.6-27b")
    assert params["extra_body"]["reasoning_effort"] == "none"


def test_settings_load_backend_env_file() -> None:
    assert BACKEND_ENV_FILE.name == ".env"
    assert BACKEND_ENV_FILE.parent.name == "backend"


def test_create_model_requires_api_key(monkeypatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "")
    get_settings.cache_clear()
    with pytest.raises(AgentConfigError):
        create_groq_model()
    get_settings.cache_clear()


def test_create_model_uses_configured_groq_settings(monkeypatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setenv("GROQ_MODEL", "openai/gpt-oss-20b")
    get_settings.cache_clear()

    model = create_groq_model()
    config = model.get_config()
    assert config["model_id"] == "openai/gpt-oss-20b"
    assert config["params"]["extra_body"]["include_reasoning"] is False

    get_settings.cache_clear()


def test_agent_initializes_with_one_webpage_tool() -> None:
    agent = create_sentinel_agent(model=MagicMock())
    tool_names = set(agent.tool_names)
    assert tool_names == {"check_webpage"}
    assert "deadline" not in SYSTEM_PROMPT.lower()
    assert "fee" not in SYSTEM_PROMPT.lower()
    assert "eligibility" not in SYSTEM_PROMPT.lower()


def test_assessment_mode_does_not_attach_webpage_tool() -> None:
    agent = create_sentinel_agent(model=MagicMock(), tools=[])
    assert agent.tool_names == []


def test_agent_tool_delegates_to_existing_webpage_tool(monkeypatch) -> None:
    observation = WebpageObservation(
        url="https://example.com/admissions",
        status_code=200,
        title="Admissions",
        text="Deadline: 1 May 2026",
        content_hash="abc",
        fetched_at=datetime.now(timezone.utc),
    )
    monkeypatch.setattr(
        "app.agent.sentinel_agent.fetch_webpage",
        lambda url, **kwargs: observation,
    )

    payload = check_webpage("https://example.com/admissions")
    assert payload["url"] == "https://example.com/admissions"
    assert payload["text"] == "Deadline: 1 May 2026"
    assert payload["content_hash"] == "abc"


def test_agent_tool_returns_structured_error_when_fetch_fails(monkeypatch) -> None:
    def boom(url: str, **kwargs):
        raise WebpageToolError(
            "http_error",
            "Webpage returned HTTP 404.",
            status_code=404,
        )

    monkeypatch.setattr("app.agent.sentinel_agent.fetch_webpage", boom)
    payload = check_webpage("https://example.com/missing")
    assert payload["error"] == "http_error"
    assert payload["status_code"] == 404


def test_run_sentinel_uses_tool_observation_in_result() -> None:
    class StubAgent:
        messages = [
            {
                "role": "assistant",
                "content": [
                    {
                        "toolUse": {
                            "name": "check_webpage",
                            "input": {"url": "https://example.com"},
                        }
                    }
                ],
            }
        ]

        def __call__(self, prompt: str):
            assert "Tell me if the application deadline is mentioned" in prompt
            assert "https://example.com" in prompt
            assert "check_webpage" in prompt
            return SimpleNamespace(
                message={
                    "role": "assistant",
                    "content": [
                        {"text": "The page lists an application deadline of 1 May 2026."}
                    ],
                }
            )

    result = run_sentinel(
        "Tell me if the application deadline is mentioned on this page.",
        "https://example.com",
        agent=StubAgent(),
    )
    assert result.tool_used is True
    assert "1 May 2026" in result.summary
    assert result.goal.startswith("Tell me if")


def test_run_sentinel_does_not_treat_missing_tool_use_as_success() -> None:
    class StubAgent:
        messages = [{"role": "assistant", "content": [{"text": "I did not check."}]}]

        def __call__(self, prompt: str):
            return SimpleNamespace(
                message={"role": "assistant", "content": [{"text": "I did not check."}]}
            )

    result = run_sentinel("Watch this page.", "https://example.com", agent=StubAgent())
    assert result.tool_used is False


def _strands_like_agent(payload: dict, summary: str):
    observation_text = json.dumps(payload)

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
                            "content": [{"text": observation_text}],
                        }
                    }
                ],
            },
            {"role": "assistant", "content": [{"text": summary}]},
        ]

        def __call__(self, prompt: str):
            return SimpleNamespace(message=self.messages[-1])

    return StubAgent()


def test_run_sentinel_propagates_content_hash_from_tool_result() -> None:
    payload = {
        "url": "https://example.com",
        "status_code": 200,
        "title": "Example Domain",
        "text": "Example Domain",
        "content_hash": "abc123hash",
        "fetched_at": "2026-09-08T05:00:00+00:00",
    }
    result = run_sentinel(
        "Tell me if an application deadline is mentioned on this webpage.",
        "https://example.com",
        agent=_strands_like_agent(payload, "No deadline is mentioned."),
    )
    assert result.tool_used is True
    assert result.content_hash == "abc123hash"
    assert result.tool_error is None
    assert result.summary == "No deadline is mentioned."
    assert result.page_text == "Example Domain"


def test_run_sentinel_propagates_structured_tool_error_from_tool_result() -> None:
    payload = {
        "error": "http_error",
        "message": "Webpage returned HTTP 404.",
        "status_code": 404,
    }
    result = run_sentinel(
        "Watch this page.",
        "https://example.com",
        agent=_strands_like_agent(payload, "Could not retrieve the page."),
    )
    assert result.tool_used is True
    assert result.content_hash is None
    assert result.tool_error == "Webpage returned HTTP 404."


def test_extract_payload_reads_json_content_block() -> None:
    agent = SimpleNamespace(
        messages=[
            {
                "role": "assistant",
                "content": [{"toolUse": {"name": "check_webpage", "toolUseId": "t1"}}],
            },
            {
                "role": "user",
                "content": [
                    {
                        "toolResult": {
                            "toolUseId": "t1",
                            "content": [{"json": {"content_hash": "from-json"}}],
                        }
                    }
                ],
            },
        ]
    )
    assert extract_check_webpage_payload(agent) == {"content_hash": "from-json"}


def test_used_check_webpage_detects_tool_use() -> None:
    agent = SimpleNamespace(
        messages=[
            {
                "role": "assistant",
                "content": [{"toolUse": {"name": "check_webpage", "input": {}}}],
            }
        ]
    )
    assert used_check_webpage(agent) is True


def test_clip_page_text_bounds_and_drops_empty() -> None:
    assert clip_page_text(None) is None
    assert clip_page_text("   ") is None
    assert clip_page_text("hello") == "hello"
    assert clip_page_text("x" * 9000) == "x" * 8000


def test_parse_meaningful_change_assessment_from_json_and_fence() -> None:
    payload = {
        "meaningful_change": True,
        "summary": "The deadline moved to 15 May 2026.",
        "reason": "The date in the current excerpt differs from the previous excerpt.",
        "action_required": True,
    }
    parsed = parse_meaningful_change_assessment(json.dumps(payload))
    assert parsed.meaningful_change is True
    assert parsed.action_required is True

    fenced = parse_meaningful_change_assessment(
        "```json\n" + json.dumps(payload) + "\n```"
    )
    assert fenced.summary == payload["summary"]


def test_parse_meaningful_change_assessment_rejects_invalid_text() -> None:
    with pytest.raises(ValueError, match="structured change assessment"):
        parse_meaningful_change_assessment("I think this might matter.")


def test_assess_page_change_uses_goal_and_excerpts() -> None:
    class StubAgent:
        def __call__(self, prompt: str):
            assert "Tell me if the application deadline changes" in prompt
            assert "Deadline: 1 May 2026" in prompt
            assert "Deadline: 15 May 2026" in prompt
            assert "check_webpage" not in prompt.lower() or "already detected" in prompt
            return SimpleNamespace(
                message={
                    "role": "assistant",
                    "content": [
                        {
                            "text": json.dumps(
                                {
                                    "meaningful_change": True,
                                    "summary": "The application deadline changed to 15 May 2026.",
                                    "reason": "The date in the current excerpt replaced 1 May 2026.",
                                    "action_required": True,
                                }
                            )
                        }
                    ],
                }
            )

    assessment = assess_page_change(
        "Tell me if the application deadline changes",
        "Deadline: 1 May 2026",
        "Deadline: 15 May 2026",
        agent=StubAgent(),
    )
    assert assessment.meaningful_change is True
    assert assessment.action_required is True
    assert "15 May" in assessment.summary


def test_monitoring_prompt_requires_tool_and_includes_goal() -> None:
    assert "MUST call it" in SYSTEM_PROMPT or "MUST call" in SYSTEM_PROMPT
    assert "check_webpage" in SYSTEM_PROMPT
    assert "SHA-256" in SYSTEM_PROMPT
    assert "deadline" not in SYSTEM_PROMPT.lower()


def test_ground_observed_facts_drops_invented_content() -> None:
    page = "Application deadline: 20 September 2026 Contact admissions@example.com"
    facts = ground_observed_facts(
        [
            "Application deadline: 20 September 2026",
            "Tuition is $50,000",
            "The deadline changed",
        ],
        page,
    )
    assert facts == ["Application deadline: 20 September 2026"]


def test_structured_observation_uses_tool_hash_not_llm_hash() -> None:
    result = build_sentinel_result(
        goal="Tell me when the release information on this page changes.",
        url="https://example.com/releases",
        model="openai/gpt-oss-20b",
        tool_used=True,
        tool_payload={
            "url": "https://example.com/releases",
            "status_code": 200,
            "title": "Releases",
            "text": "Latest release 1.2.3 published 1 May 2026",
            "content_hash": "tool-hash-abc",
            "fetched_at": "2026-09-08T05:00:00+00:00",
            "fetch_method": "http",
        },
        agent_text=json.dumps(
            {
                "url": "https://example.com/releases",
                "title": "Releases",
                "fetch_method": "playwright",
                "status": "ok",
                "readable_content": "Latest release 1.2.3 published 1 May 2026",
                "relevant_excerpt": "Latest release 1.2.3 published 1 May 2026",
                "observed_facts": ["Latest release 1.2.3 published 1 May 2026"],
                "content_hash": "llm-should-not-win",
                "fetched_at": "2026-09-08T05:00:00+00:00",
                "reasoning": "The page currently lists release 1.2.3.",
            }
        ),
    )
    assert result.content_hash == "tool-hash-abc"
    assert result.fetch_method == "http"
    assert result.observation_status == "ok"
    assert result.observed_facts == ["Latest release 1.2.3 published 1 May 2026"]
    assert "1.2.3" in result.summary
    assert "changed" not in result.summary.lower()


def test_run_sentinel_passes_previous_excerpt_and_goal() -> None:
    captured: dict[str, str] = {}

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
                            "content": [
                                {
                                    "text": json.dumps(
                                        {
                                            "url": "https://example.com",
                                            "status_code": 200,
                                            "title": "Admissions",
                                            "text": "Deadline: 20 September 2026",
                                            "content_hash": "hash-now",
                                            "fetched_at": "2026-09-08T05:00:00+00:00",
                                            "fetch_method": "http",
                                        }
                                    )
                                }
                            ],
                        }
                    }
                ],
            },
        ]

        def __call__(self, prompt: str):
            captured["prompt"] = prompt
            return SimpleNamespace(
                message={
                    "role": "assistant",
                    "content": [
                        {
                            "text": json.dumps(
                                {
                                    "observed_facts": [
                                        "Deadline: 20 September 2026"
                                    ],
                                    "relevant_excerpt": "Deadline: 20 September 2026",
                                    "reasoning": "The page currently lists Deadline: 20 September 2026.",
                                    "content_hash": "ignored",
                                }
                            )
                        }
                    ],
                }
            )

    result = run_sentinel(
        "Tell me if the application deadline changes.",
        "https://example.com",
        agent=StubAgent(),
        previous_excerpt="Deadline: 1 May 2026",
    )
    assert "Tell me if the application deadline changes." in captured["prompt"]
    assert "Deadline: 1 May 2026" in captured["prompt"]
    assert "MUST call check_webpage" in captured["prompt"]
    assert "do not decide whether the page changed" in captured["prompt"].lower()
    assert result.content_hash == "hash-now"
    assert result.observed_facts == ["Deadline: 20 September 2026"]
    assert result.relevant_excerpt == "Deadline: 20 September 2026"
    assert result.fetch_method == "http"


def test_structured_output_used_when_agent_returns_prose() -> None:
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
                            "content": [
                                {
                                    "text": json.dumps(
                                        {
                                            "url": "https://example.com",
                                            "status_code": 200,
                                            "title": "Admissions",
                                            "text": "Application deadline: 20 September 2026",
                                            "content_hash": "hash-now",
                                            "fetched_at": "2026-09-08T05:00:00+00:00",
                                            "fetch_method": "http",
                                        }
                                    )
                                }
                            ],
                        }
                    }
                ],
            },
        ]

        def __call__(self, prompt: str):
            return SimpleNamespace(
                message={
                    "role": "assistant",
                    "content": [{"text": "The page currently shows a deadline."}],
                }
            )

        def structured_output(self, output_model, prompt=None):
            return output_model(
                relevant_excerpt="Application deadline: 20 September 2026",
                observed_facts=["Application deadline: 20 September 2026"],
                reasoning="The page currently lists Application deadline: 20 September 2026.",
                content_hash="ignored",
            )

    result = run_sentinel(
        "Tell me if the application deadline changes.",
        "https://example.com",
        agent=StubAgent(),
    )
    assert result.content_hash == "hash-now"
    assert result.observed_facts == ["Application deadline: 20 September 2026"]
    assert result.summary.startswith("Observed:")


def test_blocked_tool_result_sets_blocked_status() -> None:
    result = build_sentinel_result(
        goal="Watch this page.",
        url="https://example.com",
        model="openai/gpt-oss-20b",
        tool_used=True,
        tool_payload={
            "error": "captcha_required",
            "message": "A CAPTCHA is required.",
            "human_loop_state": "blocked_requires_user",
        },
        agent_text="Could not retrieve the page because a CAPTCHA is required.",
    )
    assert result.observation_status == "blocked_requires_user"
    assert result.content_hash is None
    assert result.tool_error == "A CAPTCHA is required."
