from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx

from app.config import get_settings
from app.models.schemas import WebpageObservation
from app.tools.browser_fetch import render_page_with_playwright
from app.tools.errors import WebpageToolError
from app.tools.page_extract import (
    detect_access_block,
    extract_readable_text,
    hash_content,
    looks_like_client_render,
    looks_like_error_page,
    normalize_readable_text,
    normalize_whitespace,
)

USER_AGENT = "Sentinel/0.1 (webpage-monitor)"
logger = logging.getLogger("sentinel.website_monitor")

BrowserRenderFn = Callable[[str, float], tuple[int, str, str]]

__all__ = [
    "USER_AGENT",
    "WebpageToolError",
    "check_webpage",
    "extract_readable_text",
    "hash_content",
    "normalize_whitespace",
    "validate_url",
]


def validate_url(url: str) -> str:
    if not isinstance(url, str) or not url.strip():
        raise WebpageToolError("invalid_url", "A webpage URL is required.")

    cleaned = url.strip()
    parsed = urlparse(cleaned)
    if parsed.scheme not in ("http", "https"):
        raise WebpageToolError(
            "invalid_url",
            "URL must start with http:// or https://.",
        )
    if not parsed.netloc:
        raise WebpageToolError("invalid_url", "URL is missing a hostname.")
    return cleaned


def _http_error_for_status(status_code: int) -> WebpageToolError:
    if status_code in (401, 403):
        return WebpageToolError(
            "authentication_required",
            "Authentication is required to access this webpage.",
            status_code=status_code,
        )
    return WebpageToolError(
        "http_error",
        f"Webpage returned HTTP {status_code}.",
        status_code=status_code,
    )


def _observation(
    *,
    url: str,
    final_url: str,
    status_code: int,
    title: str | None,
    text: str,
    fetch_method: str,
    raw_bytes: int | None = None,
) -> WebpageObservation:
    normalized = normalize_readable_text(text)
    hashed = hash_content(normalized)
    sample = normalized[:800]
    logger.info(
        "[WEB FETCH] URL: %s Status: %s Method: %s Raw bytes: %s Readable chars: %s Normalized chars: %s Hash: %s",
        final_url or url,
        status_code,
        fetch_method,
        raw_bytes if raw_bytes is not None else "n/a",
        len(text),
        len(normalized),
        hashed,
    )
    if sample:
        logger.info("[WEB CONTENT SAMPLE] %s", sample)
    return WebpageObservation(
        url=url,
        status_code=status_code,
        title=title,
        text=normalized,
        content_hash=hashed,
        fetched_at=datetime.now(timezone.utc),
        final_url=final_url,
        fetch_method=fetch_method,  # type: ignore[arg-type]
        raw_bytes=raw_bytes,
        readable_chars=len(text),
        normalized_chars=len(normalized),
    )


def _looks_like_html(payload: str, content_type: str) -> bool:
    head = payload.lstrip()[:400].lower()
    if (
        head.startswith("<!doctype html")
        or head.startswith("<html")
        or "<html" in head
    ):
        return True
    lowered = content_type.lower()
    return "text/html" in lowered or "application/xhtml" in lowered


def _parse_html(
    html: str,
    status_code: int | None,
    max_chars: int,
) -> tuple[str | None, str]:
    try:
        title, text = extract_readable_text(html, max_chars=max_chars)
    except WebpageToolError:
        raise
    except Exception:
        raise WebpageToolError(
            "parse_failure",
            "Could not read the webpage content.",
        ) from None

    blocked = detect_access_block(html, text, status_code=status_code)
    if blocked is not None:
        raise blocked
    if looks_like_error_page(text, title):
        raise WebpageToolError(
            "error_page",
            "The webpage returned an error document instead of the monitored content.",
            status_code=status_code,
        )
    return title, text


def check_webpage(
    url: str,
    *,
    timeout_seconds: float | None = None,
    client: httpx.Client | None = None,
    render_page: BrowserRenderFn | None = None,
    allow_browser: bool | None = None,
) -> WebpageObservation:
    """Fetch a public webpage and return a normalized observation.

    Uses HTTPX + BeautifulSoup first. Playwright is used only when the HTTP
    response looks like an empty client-rendered shell.
    """
    validated = validate_url(url)
    settings = get_settings()
    timeout = (
        timeout_seconds
        if timeout_seconds is not None
        else settings.request_timeout_seconds
    )
    use_browser = (
        settings.enable_browser_fallback if allow_browser is None else allow_browser
    )

    owns_client = client is None
    http_client = client or httpx.Client(
        timeout=timeout,
        follow_redirects=True,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.8",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        },
    )

    try:
        try:
            response = http_client.get(validated)
        except httpx.TimeoutException:
            raise WebpageToolError(
                "timeout",
                "The webpage request timed out.",
            ) from None
        except httpx.ConnectError:
            raise WebpageToolError(
                "connection_failure",
                "Could not connect to the webpage.",
            ) from None
        except httpx.RequestError:
            raise WebpageToolError(
                "connection_failure",
                "The webpage request failed.",
            ) from None

        if response.status_code in (401, 403):
            raise _http_error_for_status(response.status_code)
        if response.status_code >= 400:
            raise _http_error_for_status(response.status_code)

        html = response.text
        raw_bytes = len(response.content)
        if not html or not html.strip():
            raise WebpageToolError(
                "empty_response",
                "The webpage returned no content.",
            )

        content_type = str(response.headers.get("content-type") or "")
        final_url = str(response.url)
        if not _looks_like_html(html, content_type):
            text = normalize_readable_text(html, max_chars=settings.max_readable_chars)
            if not text:
                raise WebpageToolError(
                    "empty_response",
                    "The webpage had no readable text.",
                )
            return _observation(
                url=validated,
                final_url=final_url,
                status_code=response.status_code,
                title=None,
                text=text,
                fetch_method="http",
                raw_bytes=raw_bytes,
            )

        title, text = _parse_html(
            html,
            response.status_code,
            settings.max_readable_chars,
        )
        min_chars = settings.min_readable_chars
        needs_render = looks_like_client_render(
            html,
            text,
            min_chars=min_chars,
        )

        if text and not needs_render:
            return _observation(
                url=validated,
                final_url=final_url,
                status_code=response.status_code,
                title=title,
                text=text,
                fetch_method="http",
                raw_bytes=raw_bytes,
            )

        if not needs_render:
            raise WebpageToolError(
                "empty_response",
                "The webpage had no readable text.",
            )

        if not use_browser:
            if not text:
                raise WebpageToolError(
                    "empty_response",
                    "The webpage had no readable text.",
                )
            return _observation(
                url=validated,
                final_url=final_url,
                status_code=response.status_code,
                title=title,
                text=text,
                fetch_method="http",
                raw_bytes=raw_bytes,
            )

        renderer = render_page or render_page_with_playwright
        browser_timeout = float(settings.browser_timeout_seconds)
        status, rendered_html, rendered_url = renderer(validated, browser_timeout)
        if status in (401, 403) or status >= 400:
            raise _http_error_for_status(status)
        if not rendered_html or not rendered_html.strip():
            raise WebpageToolError(
                "empty_response",
                "The webpage returned no content.",
            )
        title, text = _parse_html(
            rendered_html,
            status,
            settings.max_readable_chars,
        )
        if not text:
            raise WebpageToolError(
                "empty_response",
                "The webpage had no readable text.",
            )
        return _observation(
            url=validated,
            final_url=rendered_url or final_url,
            status_code=status,
            title=title,
            text=text,
            fetch_method="browser",
            raw_bytes=len(rendered_html.encode("utf-8", errors="replace")),
        )
    finally:
        if owns_client:
            http_client.close()
