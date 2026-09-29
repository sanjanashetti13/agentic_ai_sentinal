from fastapi.testclient import TestClient

from app.models.schemas import MeaningfulChangeAssessment, SentinelResult
from app.services import monitoring as monitoring_service
from app.tools.web_monitor import WebpageToolError


def test_create_monitor(client: TestClient) -> None:
    response = client.post(
        "/api/monitors",
        json={
            "goal": "Tell me if the application deadline changes",
            "url": "https://example.com",
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["goal"] == "Tell me if the application deadline changes"
    assert payload["url"] == "https://example.com"
    assert payload["enabled"] is True
    assert payload["id"]
    assert payload["id"] == payload["task_id"]
    assert payload["last_checked_at"] is None
    assert payload["previous_content_hash"] is None
    listed = client.get("/api/monitors").json()["monitors"]
    assert listed[0]["last_checked_at"] is None
    detail = client.get(f"/api/monitors/{payload['id']}").json()
    assert detail["last_checked_at"] is None
    assert detail["latest_observation"] is None
    assert detail["observations"] == []


def test_create_monitor_rejects_invalid_url(client: TestClient) -> None:
    response = client.post(
        "/api/monitors",
        json={"goal": "Watch this", "url": "not-a-url"},
    )
    assert response.status_code == 422
    assert response.json()["detail"]["error"] == "invalid_url"


def test_create_monitor_rejects_empty_goal(client: TestClient) -> None:
    response = client.post(
        "/api/monitors",
        json={"goal": "", "url": "https://example.com"},
    )
    assert response.status_code == 422


def test_list_and_get_monitor(client: TestClient) -> None:
    created = client.post(
        "/api/monitors",
        json={"goal": "Watch announcements.", "url": "https://example.com/news"},
    ).json()

    listed = client.get("/api/monitors")
    assert listed.status_code == 200
    assert len(listed.json()["monitors"]) == 1
    assert listed.json()["monitors"][0]["id"] == created["id"]

    detail = client.get(f"/api/monitors/{created['id']}")
    assert detail.status_code == 200
    assert detail.json()["goal"] == "Watch announcements."
    assert detail.json()["latest_observation"] is None


def test_get_missing_monitor_is_404(client: TestClient) -> None:
    response = client.get("/api/monitors/missing")
    assert response.status_code == 404
    assert response.json()["detail"]["error"] == "not_found"


def test_delete_monitor_via_api(client: TestClient) -> None:
    created = client.post(
        "/api/monitors",
        json={"goal": "Watch announcements.", "url": "https://example.com/news"},
    ).json()
    deleted = client.delete(f"/api/monitors/{created['id']}")
    assert deleted.status_code == 204
    assert client.get(f"/api/monitors/{created['id']}").status_code == 404
    assert client.get("/api/monitors").json() == {"monitors": []}


def test_delete_missing_monitor_is_404(client: TestClient) -> None:
    response = client.delete("/api/monitors/missing")
    assert response.status_code == 404


def test_check_missing_monitor_is_404(client: TestClient) -> None:
    response = client.post("/api/monitors/missing/check")
    assert response.status_code == 404


def test_check_lifecycle_via_api(client: TestClient, monkeypatch) -> None:
    created = client.post(
        "/api/monitors",
        json={
            "goal": "Tell me if the application deadline changes",
            "url": "https://example.com",
        },
    ).json()

    pages = iter(
        [
            "Deadline: 1 May 2026",
            "Deadline: 1 May 2026",
            "Deadline: 15 May 2026",
        ]
    )
    hashes = iter(["hash-1", "hash-1", "hash-2"])

    def fake_run(goal: str, url: str) -> SentinelResult:
        text = next(pages)
        return SentinelResult(
            goal=goal,
            url=url,
            summary=text,
            tool_used=True,
            model="test",
            content_hash=next(hashes),
            page_text=text,
        )

    def fake_assess(goal: str, previous_text: str | None, current_text: str | None):
        return MeaningfulChangeAssessment(
            meaningful_change=True,
            summary="The deadline changed to 15 May 2026.",
            reason="The date in the current excerpt replaced 1 May 2026.",
            action_required=True,
        )

    monkeypatch.setattr(monitoring_service, "fetch_monitor_page", fake_run)
    monkeypatch.setattr(monitoring_service, "assess_page_change", fake_assess)

    first = client.post(f"/api/monitors/{created['id']}/check")
    assert first.status_code == 200
    assert first.json()["change_status"] == "baseline"
    assert first.json()["status"] == "initialized"
    assert first.json()["changed"] is False
    assert first.json()["meaningful_change"] is None
    assert first.json()["agents"] == ["supervisor", "monitoring"]
    assert "previous_content" not in first.json()

    second = client.post(f"/api/monitors/{created['id']}/check")
    assert second.json()["change_status"] == "unchanged"
    assert second.json()["status"] == "unchanged"
    assert second.json()["changed"] is False
    assert second.json()["meaningful_change"] is None

    third = client.post(f"/api/monitors/{created['id']}/check")
    assert third.json()["change_status"] == "changed"
    assert third.json()["status"] == "changed"
    assert third.json()["changed"] is True
    assert third.json()["meaningful_change"] is True
    assert third.json()["action_required"] is True
    assert third.json()["agents"] == ["supervisor", "monitoring", "analysis", "action"]
    assert "15 May" in third.json()["summary"]
    assert "previous_content" not in third.json()

    detail = client.get(f"/api/monitors/{created['id']}")
    assert detail.json()["latest_observation"]["content_hash"] == "hash-2"
    assert "15 May" in detail.json()["latest_observation"]["summary"]
    assert detail.json()["latest_observation"]["meaningful_change"] is True
    assert "previous_content" not in detail.json()


def test_check_tool_failure_keeps_previous_state(client: TestClient, monkeypatch) -> None:
    created = client.post(
        "/api/monitors",
        json={"goal": "Watch this page.", "url": "https://example.com"},
    ).json()

    calls = {"n": 0}

    def fake_run(goal: str, url: str) -> SentinelResult:
        calls["n"] += 1
        if calls["n"] == 1:
            return SentinelResult(
                goal=goal,
                url=url,
                summary="Deadline is 1 May.",
                tool_used=True,
                model="test",
                content_hash="hash-1",
                page_text="Deadline is 1 May.",
            )
        raise WebpageToolError(
            "http_error",
            "Webpage returned HTTP 404.",
            status_code=404,
        )

    monkeypatch.setattr(monitoring_service, "fetch_monitor_page", fake_run)
    assert client.post(f"/api/monitors/{created['id']}/check").status_code == 200
    failed = client.post(f"/api/monitors/{created['id']}/check")
    assert failed.status_code == 200
    payload = failed.json()
    assert payload["change_status"] == "error"
    assert "404" in payload["summary"]

    detail = client.get(f"/api/monitors/{created['id']}")
    assert detail.json()["last_change"] == "error"
    assert detail.json()["previous_content_hash"] == "hash-1"
    assert detail.json()["last_checked_at"] is not None


def test_check_agent_failure_keeps_previous_state(client: TestClient, monkeypatch) -> None:
    created = client.post(
        "/api/monitors",
        json={"goal": "Track the supplier catalog.", "url": "https://example.com"},
    ).json()

    pages = iter(["Alpha component is listed.", "Beta component is listed."])
    hashes = iter(["hash-1", "hash-2"])

    def fake_run(goal: str, url: str) -> SentinelResult:
        text = next(pages)
        return SentinelResult(
            goal=goal,
            url=url,
            summary=text,
            tool_used=True,
            model="test",
            content_hash=next(hashes),
            page_text=text,
        )

    monkeypatch.setattr(monitoring_service, "fetch_monitor_page", fake_run)

    def boom(goal: str, previous_text: str | None, current_text: str | None):
        raise RuntimeError("model timeout")

    monkeypatch.setattr(monitoring_service, "assess_page_change", boom)
    assert client.post(f"/api/monitors/{created['id']}/check").status_code == 200
    failed = client.post(f"/api/monitors/{created['id']}/check")
    assert failed.status_code == 502
    assert failed.json()["detail"]["error"] == "analysis_error"

    detail = client.get(f"/api/monitors/{created['id']}")
    assert detail.json()["latest_observation"]["content_hash"] == "hash-1"
    assert detail.json()["previous_content_hash"] == "hash-1"
    assert "previous_content" not in detail.json()


def test_patch_enabled(client: TestClient) -> None:
    created = client.post(
        "/api/monitors",
        json={"goal": "Watch this page.", "url": "https://example.com"},
    ).json()

    response = client.patch(
        f"/api/monitors/{created['id']}",
        json={"enabled": False},
    )
    assert response.status_code == 200
    assert response.json()["enabled"] is False

    missing = client.patch("/api/monitors/missing", json={"enabled": True})
    assert missing.status_code == 404


def test_disabled_monitor_check_is_409(client: TestClient) -> None:
    created = client.post(
        "/api/monitors",
        json={"goal": "Watch this page.", "url": "https://example.com"},
    ).json()
    client.patch(f"/api/monitors/{created['id']}", json={"enabled": False})
    response = client.post(f"/api/monitors/{created['id']}/check")
    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "disabled"


def test_system_status_endpoint(client: TestClient, monkeypatch) -> None:
    empty = client.get("/api/status")
    assert empty.status_code == 200
    payload = empty.json()
    assert payload["backend"] == "ok"
    assert payload["scheduler"] == "idle"
    assert payload["scheduler_interval_seconds"] == 10

    created = client.post(
        "/api/monitors",
        json={"goal": "Watch this page.", "url": "https://example.com"},
    ).json()
    pending = client.get("/api/status").json()
    assert pending["enabled_monitors"] == 1
    assert pending["scheduler"] == "never"
    assert "not confirmed" in pending["message"].lower() or "has not checked" in pending["message"].lower()
    assert created["id"]

    def fake_run(goal: str, url: str) -> SentinelResult:
        return SentinelResult(
            goal=goal,
            url=url,
            summary="Example Domain",
            tool_used=True,
            model="test",
            content_hash="hash-baseline",
            page_text="Example Domain",
        )

    monkeypatch.setattr(monitoring_service, "fetch_monitor_page", fake_run)
    checked = client.post(f"/api/monitors/{created['id']}/check")
    assert checked.status_code == 200
    running = client.get("/api/status").json()
    assert running["scheduler"] == "ok"
    assert "running" in running["message"].lower()
