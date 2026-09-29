from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.models.schemas import ActionDecision, MeaningfulChangeAssessment


def _default_action(goal: str, analysis: MeaningfulChangeAssessment) -> ActionDecision:
    if analysis.meaningful_change and analysis.action_required:
        return ActionDecision(
            action_type="notify_user",
            human_loop_state="notification",
            summary=analysis.summary,
            reason=analysis.reason,
            user_notification=analysis.summary,
            requires_approval=False,
        )
    return ActionDecision(
        action_type="ignore",
        human_loop_state="no_action",
        summary=analysis.summary,
        reason=analysis.reason,
        requires_approval=False,
    )


@pytest.fixture(autouse=True)
def stub_action_agent(monkeypatch) -> None:
    """Keep monitor-check tests off the live Action Agent / Groq path."""
    monkeypatch.setenv("GMAIL_MAILBOX_SYNC", "false")
    monkeypatch.setattr("app.services.monitoring.decide_action", _default_action)


@pytest.fixture
def client(tmp_path, monkeypatch) -> Generator[TestClient, None, None]:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("WHATSAPP_ACCESS_TOKEN", "")
    monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "")
    monkeypatch.setenv("WHATSAPP_RECIPIENT_PHONE", "")
    get_settings.cache_clear()

    from app.main import app

    with TestClient(app) as test_client:
        yield test_client

    get_settings.cache_clear()


@pytest.fixture
def client(tmp_path, monkeypatch) -> Generator[TestClient, None, None]:
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.db"))
    get_settings.cache_clear()

    from app.main import app

    with TestClient(app) as test_client:
        yield test_client

    get_settings.cache_clear()
