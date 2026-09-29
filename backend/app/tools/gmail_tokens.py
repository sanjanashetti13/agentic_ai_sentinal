from __future__ import annotations

import json

from app.integrations.gmail_client import GmailClient, GmailClientError
from app.integrations.tokens import decrypt_secret
from app.storage.database import MonitorStore


def client_from_store(store: MonitorStore, user_id: str) -> GmailClient:
    connection = store.get_gmail_connection(user_id)
    if connection is None:
        raise GmailClientError("not_connected", "Gmail is not connected.")
    tokens = json.loads(decrypt_secret(connection["token_blob"]))
    access = str(tokens.get("access_token") or "")
    refresh = str(tokens.get("refresh_token") or "") or None
    if not access and not refresh:
        raise GmailClientError("not_connected", "Gmail credentials are missing.")
    return GmailClient(access_token=access, refresh_token=refresh)
