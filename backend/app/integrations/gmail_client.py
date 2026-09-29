from __future__ import annotations

import base64
import email.utils
import json
import re
from datetime import datetime, timezone
from email.header import decode_header
from typing import Any
from urllib.parse import urlencode

import httpx
from bs4 import BeautifulSoup

from app.config import get_settings, resolved_google_redirect_uri
from app.models.schemas import GmailEmail

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"
GMAIL_API = "https://gmail.googleapis.com/gmail/v1"
READONLY_SCOPES = (
    "https://www.googleapis.com/auth/gmail.readonly "
    "https://www.googleapis.com/auth/userinfo.email"
)
SKIP_LABELS = {"SPAM", "TRASH"}
_HTML_SCRIPT = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)


class GmailClientError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


def authorization_url(state: str) -> str:
    settings = get_settings()
    redirect_uri = resolved_google_redirect_uri()
    if not settings.google_client_id.strip() or not redirect_uri:
        raise GmailClientError("not_configured", "Google OAuth is not configured.")
    params = {
        "client_id": settings.google_client_id.strip(),
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": READONLY_SCOPES.strip(),
        "access_type": "offline",
        "include_granted_scopes": "true",
        "prompt": "consent",
        "state": state,
    }
    return f"{AUTH_URL}?{urlencode(params)}"


def exchange_code(code: str) -> dict[str, Any]:
    settings = get_settings()
    payload = {
        "code": code,
        "client_id": settings.google_client_id.strip(),
        "client_secret": settings.google_client_secret.strip(),
        "redirect_uri": resolved_google_redirect_uri(),
        "grant_type": "authorization_code",
    }
    with httpx.Client(timeout=20) as client:
        response = client.post(TOKEN_URL, data=payload)
    if response.status_code >= 400:
        raise GmailClientError("oauth_failed", "Google did not accept the authorization code.")
    data = response.json()
    if not data.get("access_token"):
        raise GmailClientError("oauth_failed", "Google did not return an access token.")
    return data


def refresh_access_token(refresh_token: str) -> dict[str, Any]:
    settings = get_settings()
    payload = {
        "refresh_token": refresh_token,
        "client_id": settings.google_client_id.strip(),
        "client_secret": settings.google_client_secret.strip(),
        "grant_type": "refresh_token",
    }
    with httpx.Client(timeout=20) as client:
        response = client.post(TOKEN_URL, data=payload)
    if response.status_code >= 400:
        raise GmailClientError("token_refresh_failed", "Google could not refresh the Gmail token.")
    data = response.json()
    if not data.get("access_token"):
        raise GmailClientError("token_refresh_failed", "Google did not return a refreshed access token.")
    return data


def fetch_user_email(access_token: str) -> str:
    with httpx.Client(timeout=20) as client:
        response = client.get(
            USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )
    if response.status_code >= 400:
        raise GmailClientError("userinfo_failed", "Could not read the Google account email.")
    email = str(response.json().get("email") or "").strip().lower()
    if not email:
        raise GmailClientError("userinfo_failed", "Google did not return an account email.")
    return email


def extract_readable_text(html: str) -> str:
    cleaned = _HTML_SCRIPT.sub(" ", html or "")
    text = BeautifulSoup(cleaned, "html.parser").get_text(separator=" ")
    return " ".join(text.split()).strip()


def _decode_header(value: str | None) -> str:
    if not value:
        return ""
    parts: list[str] = []
    for chunk, charset in decode_header(value):
        if isinstance(chunk, bytes):
            parts.append(chunk.decode(charset or "utf-8", errors="replace"))
        else:
            parts.append(chunk)
    return " ".join(parts).strip()


def _decode_body(data: str | None) -> str:
    if not data:
        return ""
    padded = data + "=" * (-len(data) % 4)
    raw = base64.urlsafe_b64decode(padded.encode("ascii"))
    return raw.decode("utf-8", errors="replace")


def _walk_parts(payload: dict[str, Any]) -> tuple[str, str]:
    mime = str(payload.get("mimeType") or "")
    body = payload.get("body") or {}
    data = body.get("data")
    if mime.startswith("text/plain") and data:
        return _decode_body(data), ""
    if mime.startswith("text/html") and data:
        return "", _decode_body(data)
    plain = ""
    html = ""
    for part in payload.get("parts") or []:
        child_plain, child_html = _walk_parts(part)
        plain = plain or child_plain
        html = html or child_html
    return plain, html


def parse_gmail_message(payload: dict[str, Any]) -> GmailEmail:
    headers = {
        str(item.get("name") or "").lower(): str(item.get("value") or "")
        for item in (payload.get("payload") or {}).get("headers") or []
    }
    plain, html = _walk_parts(payload.get("payload") or {})
    snippet = str(payload.get("snippet") or "").strip()
    body = (plain or extract_readable_text(html) or snippet)[:8000]
    internal = payload.get("internalDate")
    received = None
    if internal:
        try:
            received = datetime.fromtimestamp(int(internal) / 1000, tz=timezone.utc)
        except (TypeError, ValueError, OSError):
            received = None
    if received is None and headers.get("date"):
        try:
            received = email.utils.parsedate_to_datetime(headers["date"])
        except (TypeError, ValueError):
            received = None
    labels = [str(item) for item in payload.get("labelIds") or []]
    attachments: list[str] = []
    for part in (payload.get("payload") or {}).get("parts") or []:
        filename = str(part.get("filename") or "").strip()
        if filename:
            attachments.append(filename)
    return GmailEmail(
        message_id=str(payload.get("id") or ""),
        thread_id=str(payload.get("threadId") or "") or None,
        sender=_decode_header(headers.get("from")),
        subject=_decode_header(headers.get("subject")),
        received_at=received,
        body_text=body,
        labels=labels,
        attachments=attachments,
    )


def should_skip_message(message: GmailEmail) -> bool:
    labels = {item.upper() for item in message.labels}
    return bool(labels & SKIP_LABELS)


class GmailClient:
    def __init__(self, access_token: str, refresh_token: str | None = None) -> None:
        self.access_token = access_token
        self.refresh_token = refresh_token

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.access_token}"}

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        url = path if path.startswith("http") else f"{GMAIL_API}{path}"
        with httpx.Client(timeout=20) as client:
            response = client.request(method, url, headers=self._headers(), **kwargs)
        if response.status_code == 401 and self.refresh_token:
            try:
                refreshed = refresh_access_token(self.refresh_token)
            except GmailClientError:
                raise
            self.access_token = str(refreshed["access_token"])
            with httpx.Client(timeout=20) as client:
                response = client.request(method, url, headers=self._headers(), **kwargs)
        if response.status_code == 401:
            raise GmailClientError(
                "token_refresh_failed",
                "Gmail rejected the access token and it could not be refreshed.",
            )
        return response

    def profile(self) -> dict[str, Any]:
        response = self._request("GET", "/users/me/profile")
        if response.status_code >= 400:
            raise GmailClientError("gmail_api_failure", "Could not read the Gmail profile.")
        return response.json()

    def start_watch(self, topic_name: str) -> dict[str, Any]:
        response = self._request(
            "POST",
            "/users/me/watch",
            json={"topicName": topic_name, "labelIds": ["INBOX"]},
        )
        if response.status_code >= 400:
            raise GmailClientError(
                "watch_failed",
                "Could not start Gmail push notifications.",
            )
        return response.json()

    def stop_watch(self) -> None:
        response = self._request("POST", "/users/me/stop")
        if response.status_code >= 400:
            raise GmailClientError("watch_failed", "Could not stop Gmail push notifications.")

    def list_history(self, start_history_id: str) -> dict[str, Any]:
        history_items: list[Any] = []
        page_token: str | None = None
        latest_id = start_history_id
        while True:
            params: dict[str, Any] = {
                "startHistoryId": start_history_id,
                "historyTypes": "messageAdded",
                "labelId": "INBOX",
            }
            if page_token:
                params["pageToken"] = page_token
            response = self._request("GET", "/users/me/history", params=params)
            if response.status_code == 404:
                raise GmailClientError(
                    "history_stale",
                    "The stored Gmail history ID is no longer valid.",
                )
            if response.status_code >= 400:
                raise GmailClientError("gmail_api_failure", "Could not read Gmail history.")
            payload = response.json()
            history_items.extend(payload.get("history") or [])
            latest_id = str(payload.get("historyId") or latest_id)
            page_token = payload.get("nextPageToken") or None
            if not page_token:
                return {"historyId": latest_id, "history": history_items}

    def get_message(self, message_id: str) -> dict[str, Any]:
        response = self._request(
            "GET",
            f"/users/me/messages/{message_id}",
            params={"format": "full"},
        )
        if response.status_code >= 400:
            raise GmailClientError("gmail_api_failure", "Could not read the Gmail message.")
        return response.json()

    def list_recent_inbox(self, max_results: int = 10) -> list[str]:
        response = self._request(
            "GET",
            "/users/me/messages",
            params={"labelIds": "INBOX", "maxResults": max_results},
        )
        if response.status_code >= 400:
            raise GmailClientError("gmail_api_failure", "Could not list recent Gmail messages.")
        return [str(item["id"]) for item in response.json().get("messages") or [] if item.get("id")]

    def search_messages(self, query: str, max_results: int = 10) -> list[str]:
        response = self._request(
            "GET",
            "/users/me/messages",
            params={"q": query, "maxResults": max_results},
        )
        if response.status_code >= 400:
            raise GmailClientError("gmail_api_failure", "Could not search Gmail.")
        return [str(item["id"]) for item in response.json().get("messages") or [] if item.get("id")]


def decode_pubsub_data(data: str) -> dict[str, Any]:
    padded = data + "=" * (-len(data) % 4)
    raw = base64.b64decode(padded.encode("ascii"))
    parsed = json.loads(raw.decode("utf-8"))
    if not isinstance(parsed, dict):
        raise GmailClientError("invalid_webhook", "Pub/Sub notification data was not an object.")
    return parsed
