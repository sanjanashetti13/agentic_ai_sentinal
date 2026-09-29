from __future__ import annotations

import httpx

from app.config import Settings, get_settings
from app.models.schemas import NotificationResult
from app.storage.database import MonitorStore


class NotificationError(Exception):
    """Structured notification failure."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


class NotificationService:
    """Channel-agnostic notification interface."""

    channel = "none"

    def is_configured(self) -> bool:
        return False

    def send(self, text: str) -> NotificationResult:
        return NotificationResult(
            sent=False,
            channel=self.channel,
            status="disabled",
            message="No notification channel is configured.",
        )


class DisabledNotificationService(NotificationService):
    channel = "none"


class MockNotificationService(NotificationService):
    """Safe stand-in when WhatsApp credentials are not configured."""

    channel = "mock"

    def send(self, text: str) -> NotificationResult:
        preview = text.strip().replace("\n", " ")[:180]
        return NotificationResult(
            sent=False,
            channel=self.channel,
            status="disabled",
            mocked=True,
            message=(
                "Mock notification only. WhatsApp credentials are not configured, "
                "so no message was sent."
                + (f" Prepared text: {preview}" if preview else "")
            ),
        )


class WhatsAppNotificationService(NotificationService):
    channel = "whatsapp"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def is_configured(self) -> bool:
        settings = self.settings
        return bool(
            settings.whatsapp_access_token.strip()
            and settings.whatsapp_phone_number_id.strip()
            and settings.whatsapp_recipient_phone.strip()
        )

    def send(self, text: str) -> NotificationResult:
        if not self.is_configured():
            return NotificationResult(
                sent=False,
                channel=self.channel,
                status="disabled",
                message="WhatsApp credentials are not configured.",
            )
        settings = self.settings
        url = (
            f"{settings.whatsapp_api_base_url.rstrip('/')}/"
            f"{settings.whatsapp_phone_number_id}/messages"
        )
        payload = {
            "messaging_product": "whatsapp",
            "to": settings.whatsapp_recipient_phone,
            "type": "text",
            "text": {"body": text[:4096]},
        }
        try:
            response = httpx.post(
                url,
                json=payload,
                headers={
                    "Authorization": f"Bearer {settings.whatsapp_access_token}",
                    "Content-Type": "application/json",
                },
                timeout=settings.request_timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise NotificationError(
                "notification_failure",
                "Could not reach the WhatsApp API.",
            ) from exc
        if response.status_code >= 400:
            raise NotificationError(
                "notification_failure",
                f"WhatsApp API returned HTTP {response.status_code}.",
            )
        return NotificationResult(
            sent=True,
            channel=self.channel,
            status="sent",
            mocked=False,
            message="WhatsApp API accepted the message.",
        )


def get_notification_service(settings: Settings | None = None) -> NotificationService:
    settings = settings or get_settings()
    channel = settings.notification_channel.strip().lower() or "whatsapp"
    if channel == "whatsapp":
        service = WhatsAppNotificationService(settings)
        if service.is_configured():
            return service
        return MockNotificationService()
    if channel == "mock":
        return MockNotificationService()
    return MockNotificationService()


def notify_alert(
    store: MonitorStore,
    alert_id: str,
    *,
    service: NotificationService | None = None,
) -> NotificationResult:
    alert = store.get_alert(alert_id)
    if alert is None:
        raise KeyError(alert_id)
    if alert.get("notification_status") == "sent":
        return NotificationResult(
            sent=False,
            channel=(service or get_notification_service()).channel,
            status="skipped",
            message="Alert was already notified.",
        )
    notifier = service if service is not None else get_notification_service()
    text = alert.get("user_notification") or alert.get("summary") or "Sentinel alert"
    try:
        result = notifier.send(str(text))
    except NotificationError as exc:
        store.set_alert_notification_status(alert_id, "failed")
        return NotificationResult(
            sent=False,
            channel=notifier.channel,
            status="failed",
            message=exc.message,
        )
    store.set_alert_notification_status(alert_id, result.status)
    return result
