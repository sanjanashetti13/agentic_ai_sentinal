from fastapi.testclient import TestClient

from app.models.schemas import MeaningfulChangeAssessment, SentinelResult
from app.services import monitoring as monitoring_service


def _result(text: str, content_hash: str) -> SentinelResult:
    return SentinelResult(
        goal="Tell me if the application deadline changes",
        url="https://example.com",
        summary=text,
        tool_used=True,
        model="test",
        content_hash=content_hash,
        page_text=text,
    )


def _create_pending_alert(client: TestClient, monkeypatch) -> dict:
    created = client.post(
        "/api/monitors",
        json={
            "goal": "Tell me if the application deadline changes",
            "url": "https://example.com",
        },
    ).json()

    pages = iter(["Deadline: 1 May 2026", "Deadline: 15 May 2026"])
    hashes = iter(["hash-1", "hash-2"])

    def fake_run(goal: str, url: str) -> SentinelResult:
        return _result(next(pages), next(hashes))

    monkeypatch.setattr(monitoring_service, "fetch_monitor_page", fake_run)
    monkeypatch.setattr(
        monitoring_service,
        "assess_page_change",
        lambda goal, previous_text, current_text: MeaningfulChangeAssessment(
            meaningful_change=True,
            summary="The deadline changed to 15 May 2026.",
            reason="The date in the current excerpt replaced 1 May 2026.",
            action_required=True,
        ),
    )
    baseline = client.post(f"/api/monitors/{created['id']}/check")
    assert baseline.status_code == 200
    assert baseline.json()["change_status"] == "baseline"
    assert baseline.json()["status"] == "initialized"

    checked = client.post(f"/api/monitors/{created['id']}/check")
    assert checked.status_code == 200
    payload = checked.json()
    assert payload["alert_id"]
    return {"monitor": created, "check": payload}


def test_get_alerts_starts_empty(client: TestClient) -> None:
    response = client.get("/api/alerts")
    assert response.status_code == 200
    assert response.json() == {"alerts": []}


def test_get_alerts_and_individual_alert(client: TestClient, monkeypatch) -> None:
    created = _create_pending_alert(client, monkeypatch)
    listed = client.get("/api/alerts")
    assert listed.status_code == 200
    alerts = listed.json()["alerts"]
    assert len(alerts) == 1
    alert = alerts[0]
    assert alert["alert_id"] == created["check"]["alert_id"]
    assert alert["id"] == alert["alert_id"]
    assert alert["monitor_id"] == created["monitor"]["id"]
    assert alert["content_hash"] == "hash-2"
    assert alert["status"] == "pending"
    assert alert["action_required"] is True
    assert "previous_content" not in alert
    assert "Deadline:" not in alert["summary"]
    assert "Deadline:" not in alert["reason"]

    fetched = client.get(f"/api/alerts/{alert['alert_id']}")
    assert fetched.status_code == 200
    assert fetched.json()["alert_id"] == alert["alert_id"]
    assert fetched.json()["summary"] == "The deadline changed to 15 May 2026."


def test_get_missing_alert_is_404(client: TestClient) -> None:
    response = client.get("/api/alerts/missing")
    assert response.status_code == 404
    assert response.json()["detail"]["error"] == "not_found"


def test_patch_alert_status(client: TestClient, monkeypatch) -> None:
    created = _create_pending_alert(client, monkeypatch)
    alert_id = created["check"]["alert_id"]

    acknowledged = client.patch(
        f"/api/alerts/{alert_id}",
        json={"status": "acknowledged"},
    )
    assert acknowledged.status_code == 200
    assert acknowledged.json()["status"] == "acknowledged"
    assert acknowledged.json()["alert_id"] == alert_id

    dismissed = client.patch(
        f"/api/alerts/{alert_id}",
        json={"status": "dismissed"},
    )
    assert dismissed.status_code == 200
    assert dismissed.json()["status"] == "dismissed"
    assert client.get(f"/api/alerts/{alert_id}").status_code == 404
    listed = client.get("/api/alerts")
    assert listed.json()["alerts"] == []


def test_patch_invalid_alert_status(client: TestClient, monkeypatch) -> None:
    created = _create_pending_alert(client, monkeypatch)
    response = client.patch(
        f"/api/alerts/{created['check']['alert_id']}",
        json={"status": "snoozed"},
    )
    assert response.status_code == 422


def test_patch_missing_alert_is_404(client: TestClient) -> None:
    response = client.patch(
        "/api/alerts/missing",
        json={"status": "acknowledged"},
    )
    assert response.status_code == 404
    assert response.json()["detail"]["error"] == "not_found"


def test_get_alerts_can_filter_pending(client: TestClient, monkeypatch) -> None:
    created = _create_pending_alert(client, monkeypatch)
    pending = client.get("/api/alerts?status=pending")
    assert pending.status_code == 200
    assert len(pending.json()["alerts"]) == 1
    invalid = client.get("/api/alerts?status=snoozed")
    assert invalid.status_code == 422
    client.patch(
        f"/api/alerts/{created['check']['alert_id']}",
        json={"status": "acknowledged"},
    )
    still_pending = client.get("/api/alerts?status=pending")
    assert still_pending.json()["alerts"] == []


def test_notify_alert_without_whatsapp_credentials(
    client: TestClient, monkeypatch
) -> None:
    created = _create_pending_alert(client, monkeypatch)
    response = client.post(f"/api/alerts/{created['check']['alert_id']}/notify")
    assert response.status_code == 200
    assert response.json()["sent"] is False
    assert response.json()["status"] in {"disabled", "skipped"}
