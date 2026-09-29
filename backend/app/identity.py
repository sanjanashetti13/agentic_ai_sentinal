from __future__ import annotations

import hashlib
import hmac
import uuid

from fastapi import Request, Response

from app.config import cookie_secure, get_settings

COOKIE_NAME = "sentinel_user"


def _signing_key() -> bytes:
    settings = get_settings()
    secret = (
        settings.session_secret.strip()
        or settings.google_token_encryption_key.strip()
        or "sentinel-dev-session"
    )
    return hashlib.sha256(secret.encode("utf-8")).digest()


def sign_user_id(user_id: str) -> str:
    digest = hmac.new(_signing_key(), user_id.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{user_id}.{digest}"


def verify_user_id(value: str | None) -> str | None:
    if not value or "." not in value:
        return None
    user_id, digest = value.rsplit(".", 1)
    if not user_id or not digest:
        return None
    expected = hmac.new(_signing_key(), user_id.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(digest, expected):
        return None
    return user_id


def read_user_id(request: Request) -> str | None:
    return verify_user_id(request.cookies.get(COOKIE_NAME))


def resolve_user_id(request: Request) -> str:
    return read_user_id(request) or str(uuid.uuid4())


def attach_user_cookie(response: Response, user_id: str, *, request: Request | None = None) -> None:
    secure = request.url.scheme == "https" if request is not None else cookie_secure()
    response.set_cookie(
        COOKIE_NAME,
        sign_user_id(user_id),
        httponly=True,
        samesite="none" if secure else "lax",
        secure=secure,
        path="/",
        max_age=60 * 60 * 24 * 400,
    )
