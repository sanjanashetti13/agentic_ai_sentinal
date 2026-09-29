from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.models.schemas import GmailEmail, GmailRelevanceAssessment
from app.services import gmail as gmail_service
from app.storage.database import MonitorStore


def _email() -> GmailEmail:
    return GmailEmail.model_validate(
        {
            "message_id": "msg-goal-1",
            "thread_id": "thread-1",
            "sender": "recruiter@example.com",
            "subject": "Interview Round 2 – Software Engineering",
            "received_at": datetime(2026, 9, 9, 14, 12, tzinfo=timezone.utc),
            "body_text": "Application shortlisted for next round.",
            "labels": ["INBOX"],
            "attachments": [],
        }
    )


def test_create_gmail_monitor_without_url(client: TestClient) -> None:
    response = client.post(
        "/api/monitors",
        json={
            "goal": "Tell me when I receive important emails about internship applications, interviews, or job offers.",
            "kind": "gmail",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["kind"] == "gmail"
    assert payload["url"] == "gmail://inbox"
    assert payload["goal"].startswith("Tell me when I receive")
    assert payload["name"]
    listed = client.get("/api/monitors").json()["monitors"]
    assert listed[0]["kind"] == "gmail"


def test_website_monitor_still_requires_url(client: TestClient) -> None:
    response = client.post(
        "/api/monitors",
        json={"goal": "Watch the admissions page."},
    )
    assert response.status_code == 422


def test_gmail_monitor_check_is_event_driven_noop(client: TestClient) -> None:
    created = client.post(
        "/api/monitors",
        json={"goal": "Watch internship emails.", "kind": "gmail"},
    ).json()
    checked = client.post(f"/api/monitors/{created['id']}/check")
    assert checked.status_code == 200
    body = checked.json()
    assert body["change_status"] == "unchanged"
    assert "event-driven" in (body.get("message") or body["summary"]).lower()
    detail = client.get(f"/api/monitors/{created['id']}").json()
    assert detail["last_checked_at"] is None


def test_relevant_gmail_email_creates_match_and_alert(tmp_path) -> None:
    store = MonitorStore(str(tmp_path / "gmail-goals.db"))
    store.initialize()
    monitor = store.create_monitor(
        "Tell me about internship emails.",
        "gmail://inbox",
        user_id="user-a",
        kind="gmail",
    )
    store.upsert_gmail_connection(
        user_id="user-a",
        google_email="user@gmail.com",
        token_blob="blob",
        last_history_id="1",
        watch_expiration=None,
        status="WATCH_ACTIVE",
    )

    def _relevant(*_args, **_kwargs) -> GmailRelevanceAssessment:
        return GmailRelevanceAssessment(
            relevant=True,
            monitor_id=monitor["id"],
            summary="Interview invitation for an internship.",
            reason="This email concerns an internship application and contains an interview-related action.",
            action_required=True,
        )

    result = gmail_service.process_email(
        store,
        _email(),
        user_id="user-a",
        assess_fn=_relevant,
    )
    assert result == "alerted"
    matches = store.list_gmail_matches(monitor["id"])
    assert len(matches) == 1
    assert matches[0]["subject"].startswith("Interview Round 2")
    assert matches[0]["alert_id"]
    alerts = [item for item in store.list_alerts() if item["source"] == "gmail"]
    assert len(alerts) == 1


def test_website_monitor_is_not_used_for_gmail_goals(tmp_path) -> None:
    store = MonitorStore(str(tmp_path / "gmail-goals.db"))
    store.initialize()
    store.create_monitor(
        "Watch the hackathon page.",
        "https://example.com",
        user_id="user-a",
        kind="website",
    )

    def _relevant(*_args, **_kwargs) -> GmailRelevanceAssessment:
        return GmailRelevanceAssessment(
            relevant=True,
            monitor_id="ignored",
            summary="Deadline changed.",
            reason="Matches a website monitor.",
            action_required=True,
        )

    result = gmail_service.process_email(
        store,
        _email(),
        user_id="user-a",
        assess_fn=_relevant,
    )
    assert result == "ignored"
    assert store.list_alerts() == []
