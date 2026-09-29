import httpx
import pytest

from app.config import get_settings
from app.models.schemas import NotificationResult
from app.services.notifications import (
    MockNotificationService,
    WhatsAppNotificationService,
    get_notification_service,
    notify_alert,
)
from app.storage.database import MonitorStore


def test_whatsapp_disabled_without_credentials(monkeypatch) -> None:
    monkeypatch.setenv("WHATSAPP_ACCESS_TOKEN", "")
    monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "")
    monkeypatch.setenv("WHATSAPP_RECIPIENT_PHONE", "")
    get_settings.cache_clear()
    service = get_notification_service()
    assert isinstance(service, MockNotificationService)
    result = service.send("hello")
    assert result.sent is False
    assert result.mocked is True
    assert result.status == "disabled"
    assert "not configured" in result.message.lower()
    get_settings.cache_clear()


def test_whatsapp_send_uses_cloud_api(monkeypatch) -> None:
    monkeypatch.setenv("WHATSAPP_ACCESS_TOKEN", "token")
    monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "123")
    monkeypatch.setenv("WHATSAPP_RECIPIENT_PHONE", "15551234567")
    get_settings.cache_clear()

    captured: dict = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        return httpx.Response(200, json={"messages": [{"id": "wamid.1"}]})

    monkeypatch.setattr("app.services.notifications.httpx.post", fake_post)
    service = WhatsAppNotificationService()
    assert service.is_configured() is True
    result = service.send("Deadline changed to 15 May.")
    assert result.sent is True
    assert result.status == "sent"
    assert captured["json"]["to"] == "15551234567"
    assert "Bearer token" in captured["headers"]["Authorization"]
    get_settings.cache_clear()


def test_whatsapp_send_failure_is_structured(monkeypatch) -> None:
    monkeypatch.setenv("WHATSAPP_ACCESS_TOKEN", "token")
    monkeypatch.setenv("WHATSAPP_PHONE_NUMBER_ID", "123")
    monkeypatch.setenv("WHATSAPP_RECIPIENT_PHONE", "15551234567")
    get_settings.cache_clear()

    def fake_post(url, json=None, headers=None, timeout=None):
        return httpx.Response(500, text="error")

    monkeypatch.setattr("app.services.notifications.httpx.post", fake_post)
    from app.services.notifications import NotificationError

    with pytest.raises(NotificationError):
        WhatsAppNotificationService().send("hello")
    get_settings.cache_clear()


def test_notify_alert_mock_and_skip_duplicate(tmp_path, monkeypatch) -> None:
    store = MonitorStore(str(tmp_path / "notify.db"))
    store.initialize()
    monitor = store.create_monitor("Watch this.", "https://example.com")
    alert = store.create_alert(
        monitor["id"],
        content_hash="hash-2",
        summary="The deadline changed.",
        reason="The date changed.",
        action_required=True,
        user_notification="Deadline changed to 15 May.",
    )

    class FakeService:
        channel = "whatsapp"

        def send(self, text: str) -> NotificationResult:
            assert "15 May" in text
            return NotificationResult(
                sent=True,
                channel="whatsapp",
                status="sent",
                message="ok",
            )

    first = notify_alert(store, alert["alert_id"], service=FakeService())
    assert first.status == "sent"
    stored = store.get_alert(alert["alert_id"])
    assert stored is not None
    assert stored["notification_status"] == "sent"

    second = notify_alert(store, alert["alert_id"], service=FakeService())
    assert second.status == "skipped"


def test_notify_alert_records_failure(tmp_path) -> None:
    store = MonitorStore(str(tmp_path / "notify.db"))
    store.initialize()
    monitor = store.create_monitor("Watch this.", "https://example.com")
    alert = store.create_alert(
        monitor["id"],
        content_hash="hash-2",
        summary="The deadline changed.",
        reason="The date changed.",
        action_required=True,
    )

    class Boom:
        channel = "whatsapp"

        def send(self, text: str) -> NotificationResult:
            from app.services.notifications import NotificationError

            raise NotificationError("notification_failure", "provider down")

    result = notify_alert(store, alert["alert_id"], service=Boom())
    assert result.status == "failed"
    stored = store.get_alert(alert["alert_id"])
    assert stored is not None
    assert stored["notification_status"] == "failed"
