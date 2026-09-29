from fastapi.testclient import TestClient

from app.storage.database import MonitorStore


def test_create_and_retrieve_monitor(tmp_path) -> None:
    store = MonitorStore(str(tmp_path / "storage.db"))
    store.initialize()

    created = store.create_monitor(
        goal="Tell me if the application deadline changes.",
        url="https://example.com/admissions",
    )

    assert created["task_id"]
    assert created["goal"] == "Tell me if the application deadline changes."
    assert created["url"] == "https://example.com/admissions"
    assert created["status"] == "created"
    assert created["previous_content"] is None
    assert created["previous_content_hash"] is None
    assert created["initialized"] is False
    assert created["last_checked_at"] is None
    assert created["last_changed_at"] is None

    fetched = store.get_monitor(created["task_id"])
    assert fetched == created
    assert created["id"] == created["task_id"]
    assert created["enabled"] is True
    assert created["updated_at"] is not None


def test_list_monitors_empty_then_populated(tmp_path) -> None:
    store = MonitorStore(str(tmp_path / "storage.db"))
    store.initialize()

    assert store.list_monitors() == []

    store.create_monitor("Watch for fee changes.", "https://example.com/fees")
    monitors = store.list_monitors()
    assert len(monitors) == 1
    assert monitors[0]["goal"] == "Watch for fee changes."


def test_delete_monitor_removes_related_rows(tmp_path) -> None:
    store = MonitorStore(str(tmp_path / "storage.db"))
    store.initialize()
    created = store.create_monitor("Watch announcements.", "https://example.com")
    store.add_observation(
        created["id"],
        content_hash="hash-a",
        summary="Baseline page.",
    )
    store.create_alert(
        monitor_id=created["id"],
        content_hash="hash-a",
        summary="Changed.",
        reason="Deadline moved.",
        action_required=True,
    )

    assert store.delete_monitor(created["id"]) is True
    assert store.get_monitor(created["id"]) is None
    assert store.list_observations(created["id"]) == []
    assert store.list_alerts() == []
    assert store.delete_monitor(created["id"]) is False


def test_update_after_check(tmp_path) -> None:
    store = MonitorStore(str(tmp_path / "storage.db"))
    store.initialize()
    created = store.create_monitor("Watch announcements.", "https://example.com")

    updated = store.update_after_check(
        created["task_id"],
        previous_content="Admissions open",
        previous_content_hash="abc123",
        last_change="baseline",
        status="monitoring",
    )

    assert updated is not None
    assert updated["previous_content"] == "Admissions open"
    assert updated["previous_content_hash"] == "abc123"
    assert updated["initialized"] is True
    assert updated["last_change"] == "baseline"
    assert updated["status"] == "monitoring"
    assert updated["last_checked_at"] is not None
    assert updated["last_changed_at"] is None

    changed = store.update_after_check(
        created["task_id"],
        previous_content="Admissions closed",
        previous_content_hash="def456",
        last_change="changed",
        status="monitoring",
        content_changed=True,
    )
    assert changed is not None
    assert changed["last_changed_at"] is not None
    preserved = store.update_after_check(
        created["task_id"],
        previous_content="Admissions closed",
        previous_content_hash="def456",
        last_change="unchanged",
        status="monitoring",
    )
    assert preserved is not None
    assert preserved["last_changed_at"] == changed["last_changed_at"]


def test_list_monitors_api_starts_empty(client: TestClient) -> None:
    response = client.get("/api/monitors")
    assert response.status_code == 200
    assert response.json() == {"monitors": []}


def test_store_and_retrieve_latest_observation(tmp_path) -> None:
    store = MonitorStore(str(tmp_path / "storage.db"))
    store.initialize()
    created = store.create_monitor("Watch announcements.", "https://example.com")

    assert store.get_latest_observation(created["id"]) is None

    first = store.add_observation(
        created["id"],
        content_hash="hash-a",
        summary="Baseline page.",
    )
    second = store.add_observation(
        created["id"],
        content_hash="hash-b",
        summary="Page changed.",
    )

    latest = store.get_latest_observation(created["id"])
    assert latest is not None
    assert latest["id"] == second["id"]
    assert latest["content_hash"] == "hash-b"
    assert latest["summary"] == "Page changed."
    assert latest["meaningful_change"] is None
    assert first["content_hash"] == "hash-a"
    assert len(store.list_observations(created["id"])) == 2


def test_store_observation_assessment_fields(tmp_path) -> None:
    store = MonitorStore(str(tmp_path / "storage.db"))
    store.initialize()
    created = store.create_monitor("Watch announcements.", "https://example.com")

    stored = store.add_observation(
        created["id"],
        content_hash="hash-c",
        summary="Deadline changed to 15 May.",
        meaningful_change=True,
        reason="The date in the page text changed.",
        action_required=True,
    )
    assert stored["meaningful_change"] is True
    assert stored["reason"] == "The date in the page text changed."
    assert stored["action_required"] is True

    irrelevant = store.add_observation(
        created["id"],
        content_hash="hash-d",
        summary="Footer year changed.",
        meaningful_change=False,
        reason="The goal is about deadlines, not the footer.",
        action_required=False,
    )
    assert irrelevant["meaningful_change"] is False
    assert irrelevant["action_required"] is False


def test_set_enabled(tmp_path) -> None:
    store = MonitorStore(str(tmp_path / "storage.db"))
    store.initialize()
    created = store.create_monitor("Watch this.", "https://example.com")

    updated = store.set_enabled(created["id"], False)
    assert updated is not None
    assert updated["enabled"] is False
    assert store.set_enabled("missing", False) is None


def test_create_and_retrieve_alert(tmp_path) -> None:
    store = MonitorStore(str(tmp_path / "storage.db"))
    store.initialize()
    created = store.create_monitor("Watch this.", "https://example.com")

    assert store.list_alerts() == []

    alert = store.create_alert(
        created["id"],
        content_hash="hash-2",
        summary="The deadline changed to 15 May 2026.",
        reason="The date in the page text changed.",
        action_required=True,
    )
    assert alert["alert_id"]
    assert alert["id"] == alert["alert_id"]
    assert alert["monitor_id"] == created["id"]
    assert alert["status"] == "pending"
    assert alert["action_required"] is True

    fetched = store.get_alert(alert["alert_id"])
    assert fetched == alert
    assert len(store.list_alerts()) == 1


def test_create_alert_is_idempotent_for_same_hash(tmp_path) -> None:
    store = MonitorStore(str(tmp_path / "storage.db"))
    store.initialize()
    created = store.create_monitor("Watch this.", "https://example.com")

    first = store.create_alert(
        created["id"],
        content_hash="hash-2",
        summary="The deadline changed.",
        reason="The date changed.",
        action_required=True,
    )
    second = store.create_alert(
        created["id"],
        content_hash="hash-2",
        summary="The deadline changed again.",
        reason="Same hash should not duplicate.",
        action_required=True,
    )
    assert second["alert_id"] == first["alert_id"]
    assert second["summary"] == first["summary"]
    assert len(store.list_alerts()) == 1

    other = store.create_alert(
        created["id"],
        content_hash="hash-3",
        summary="A later deadline change.",
        reason="A new hash should create a new alert.",
        action_required=True,
    )
    assert other["alert_id"] != first["alert_id"]
    assert len(store.list_alerts()) == 2


def test_set_alert_status(tmp_path) -> None:
    store = MonitorStore(str(tmp_path / "storage.db"))
    store.initialize()
    created = store.create_monitor("Watch this.", "https://example.com")
    alert = store.create_alert(
        created["id"],
        content_hash="hash-2",
        summary="The deadline changed.",
        reason="The date changed.",
        action_required=True,
    )

    updated = store.set_alert_status(alert["alert_id"], "acknowledged")
    assert updated is not None
    assert updated["status"] == "acknowledged"
    assert store.set_alert_status("missing", "dismissed") is None


def test_dismissing_an_alert_deletes_it(tmp_path) -> None:
    store = MonitorStore(str(tmp_path / "storage.db"))
    store.initialize()
    created = store.create_monitor("Watch this.", "https://example.com")
    alert = store.create_alert(
        created["id"],
        content_hash="hash-2",
        summary="The deadline changed.",
        reason="The date changed.",
        action_required=True,
    )
    dismissed = store.set_alert_status(alert["alert_id"], "dismissed")
    assert dismissed is not None
    assert dismissed["status"] == "dismissed"
    assert store.get_alert(alert["alert_id"]) is None
    assert store.list_alerts() == []


def test_pending_alert_can_be_updated_in_place(tmp_path) -> None:
    store = MonitorStore(str(tmp_path / "storage.db"))
    store.initialize()
    created = store.create_monitor("Watch this.", "https://example.com")
    alert = store.create_alert(
        created["id"],
        content_hash="hash-2",
        summary="The deadline changed.",
        reason="The date changed.",
        action_required=True,
    )

    pending = store.get_pending_alert_for_monitor(created["id"])
    assert pending is not None
    assert pending["alert_id"] == alert["alert_id"]

    updated = store.update_alert(
        alert["alert_id"],
        content_hash="hash-3",
        summary="The deadline moved again.",
        reason="Reuse the pending alert instead of stacking another.",
        action_required=True,
        user_notification="Deadline is now 1 June 2026.",
    )
    assert updated is not None
    assert updated["alert_id"] == alert["alert_id"]
    assert updated["content_hash"] == "hash-3"
    assert updated["summary"] == "The deadline moved again."
    assert store.get_pending_alert_for_monitor(created["id"])["alert_id"] == alert["alert_id"]
    assert len(store.list_alerts()) == 1
