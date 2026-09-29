from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
BACKEND_ENV_FILE = BACKEND_DIR / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(BACKEND_ENV_FILE, ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-20b"
    groq_base_url: str = "https://api.groq.com/openai/v1"
    model_provider: str = "groq"
    ollama_model: str = ""
    ollama_base_url: str = "http://127.0.0.1:11434/v1"
    database_path: str = "sentinel.db"
    request_timeout_seconds: int = 15
    enable_browser_fallback: bool = True
    browser_timeout_seconds: int = 20
    min_readable_chars: int = 80
    max_readable_chars: int = 24000
    whatsapp_access_token: str = ""
    whatsapp_phone_number_id: str = ""
    whatsapp_recipient_phone: str = ""
    whatsapp_api_base_url: str = "https://graph.facebook.com/v21.0"
    notification_channel: str = "whatsapp"
    frontend_url: str = ""
    public_base_url: str = ""
    cors_origins: str = ""
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = ""
    google_pubsub_topic: str = ""
    google_pubsub_verification_token: str = ""
    google_token_encryption_key: str = "sentinel-local-dev-key"
    gmail_webhook_url: str = ""
    gmail_dev_ingest: bool = False
    session_secret: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()


LOCAL_UI_ORIGINS = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
)


def cors_origin_list() -> list[str]:
    settings = get_settings()
    raw = settings.cors_origins.strip()
    if raw:
        origins = [part.strip().rstrip("/") for part in raw.split(",") if part.strip()]
    else:
        frontend = settings.frontend_url.strip().rstrip("/")
        origins = [frontend] if frontend else []
    if not origins:
        return list(LOCAL_UI_ORIGINS)
    merged = list(origins)
    if any(origin in LOCAL_UI_ORIGINS for origin in merged):
        for origin in LOCAL_UI_ORIGINS:
            if origin not in merged:
                merged.append(origin)
    return merged


def resolved_google_redirect_uri() -> str:
    settings = get_settings()
    explicit = settings.google_redirect_uri.strip()
    if explicit:
        return explicit
    base = settings.public_base_url.strip().rstrip("/")
    if not base:
        return ""
    return f"{base}/api/integrations/gmail/callback"


def resolved_gmail_webhook_url() -> str:
    settings = get_settings()
    explicit = settings.gmail_webhook_url.strip()
    if explicit:
        return explicit
    base = settings.public_base_url.strip().rstrip("/")
    if not base:
        return ""
    token = settings.google_pubsub_verification_token.strip()
    url = f"{base}/api/webhooks/gmail"
    if token:
        return f"{url}?token={token}"
    return url


def resolved_frontend_url() -> str:
    settings = get_settings()
    return (
        settings.frontend_url.strip().rstrip("/")
        or settings.public_base_url.strip().rstrip("/")
    )


def cookie_secure() -> bool:
    settings = get_settings()
    hints = (
        settings.public_base_url,
        settings.google_redirect_uri,
        settings.gmail_webhook_url,
        settings.frontend_url,
    )
    return any(value.strip().lower().startswith("https://") for value in hints)
