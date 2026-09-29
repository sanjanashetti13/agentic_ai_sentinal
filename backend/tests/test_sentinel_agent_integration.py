import os

import pytest

from app.agent.sentinel_agent import run_sentinel
from app.config import get_settings

pytestmark = pytest.mark.integration


def _has_groq_key() -> bool:
    get_settings.cache_clear()
    return bool(os.getenv("GROQ_API_KEY", "").strip() or get_settings().groq_api_key.strip())


@pytest.mark.skipif(not _has_groq_key(), reason="GROQ_API_KEY is not set")
def test_live_agent_uses_check_webpage_and_stays_grounded() -> None:
    html = """
    <html><head><title>Admissions</title></head>
    <body><p>Application deadline: 20 September 2026</p></body></html>
    """

    import httpx

    from app.agent import sentinel_agent

    original = sentinel_agent.fetch_webpage

    def fake_fetch(url: str, **kwargs):
        from app.tools.web_monitor import check_webpage as fetch

        client = httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, text=html)
            )
        )
        try:
            return fetch(url, client=client)
        finally:
            client.close()

    sentinel_agent.fetch_webpage = fake_fetch
    try:
        result = run_sentinel(
            "Tell me if the application deadline is mentioned on this page.",
            "https://example.com/admissions",
        )
    finally:
        sentinel_agent.fetch_webpage = original

    assert result.tool_used is True
    assert result.summary
    assert "invent" not in result.summary.lower()
    assert any(
        token in result.summary.lower()
        for token in ("september", "20", "deadline")
    )


@pytest.mark.skipif(not _has_groq_key(), reason="GROQ_API_KEY is not set")
def test_live_agent_does_not_invent_content_when_tool_fails() -> None:
    result = run_sentinel(
        "What is the application deadline on this webpage?",
        "http://127.0.0.1:1/missing",
    )
    assert result.tool_used is True
    lowered = result.summary.lower()
    assert any(
        token in lowered
        for token in ("could not", "unable", "failed", "error", "connect")
    )
    assert "september 20" not in lowered
