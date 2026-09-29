from __future__ import annotations

import hashlib
import re
from bs4 import BeautifulSoup, Tag

from app.tools.errors import WebpageToolError

_WHITESPACE = re.compile(r"\s+")
_RELATIVE_TIME = re.compile(
    r"\b\d+\s+(?:seconds?|minutes?|hours?|days?|weeks?)\s+ago\b",
    re.IGNORECASE,
)
_LIVE_CLOCK = re.compile(r"\b(?:live|as of now)\s+\d{1,2}:\d{2}:\d{2}\b", re.IGNORECASE)
_ISO_DATETIME = re.compile(
    r"\b\d{4}-\d{2}-\d{2}[tT ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:z|[+-]\d{2}:?\d{2})?\b",
    re.IGNORECASE,
)
_SECONDS_CLOCK = re.compile(r"\b\d{1,2}:\d{2}:\d{2}\b")
_UUID = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)
_LONG_HEX = re.compile(r"\b[0-9a-f]{32,}\b", re.IGNORECASE)
_TRACKING_QUERY = re.compile(
    r"\b(?:utm_[a-z]+|fbclid|gclid|sessionid|session_id|csrf(?:_token)?|request_id)[=:][^\s]+",
    re.IGNORECASE,
)

JUNK_TAGS = ("script", "style", "noscript", "iframe", "template", "svg", "canvas")
JUNK_SELECTORS = (
    "nav",
    "[role='navigation']",
    "#onetrust-banner-sdk",
    "#onetrust-consent-sdk",
    "#CybotCookiebotDialog",
    ".cc-window",
    "#cookie-banner",
    ".cookie-banner",
    "#cookieConsent",
    ".cookie-consent",
    ".cookie-notice",
    "[aria-label='cookie consent']",
    "[aria-label='cookie banner']",
    "[role='advertisement']",
    ".advertisement",
    "#advertisement",
    "#analytics",
    ".analytics",
)
_ERROR_PAGE_MARKERS = (
    "internal server error",
    "502 bad gateway",
    "503 service unavailable",
    "504 gateway time-out",
    "504 gateway timeout",
    "http error 500",
    "http error 502",
    "http error 503",
    "this page isn't working",
    "temporarily unavailable",
)
PAYWALL_SELECTORS = (".paywall", "#paywall", "[data-paywall]", ".subscribe-wall")
SHELL_IDS = ("root", "app", "__next", "__nuxt")


def normalize_whitespace(text: str) -> str:
    return _WHITESPACE.sub(" ", text).strip()


def hash_content(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def normalize_readable_text(text: str, max_chars: int = 24000) -> str:
    """Collapse whitespace and drop obvious ticking noise without removing dates."""
    cleaned = normalize_whitespace(text)
    cleaned = _RELATIVE_TIME.sub(" ", cleaned)
    cleaned = _LIVE_CLOCK.sub(" ", cleaned)
    cleaned = _ISO_DATETIME.sub(" ", cleaned)
    cleaned = _SECONDS_CLOCK.sub(" ", cleaned)
    cleaned = _UUID.sub(" ", cleaned)
    cleaned = _LONG_HEX.sub(" ", cleaned)
    cleaned = _TRACKING_QUERY.sub(" ", cleaned)
    cleaned = normalize_whitespace(cleaned)
    if max_chars > 0 and len(cleaned) > max_chars:
        cleaned = cleaned[:max_chars]
    return cleaned


_STRONG_ERROR_MARKERS = (
    "not found (#404)",
    "this page is no longer available",
)

BODY_SELECTORS = (
    "pre",
    "textarea",
    ".source",
    "[itemprop='articleBody']",
)
LAYOUT_SELECTORS = (
    "article",
    "main",
    "[role='main']",
    ".post-content",
    ".entry-content",
    "#content",
)


def looks_like_error_page(text: str, title: str | None = None) -> bool:
    """True when readable text is an error document, not the monitored page."""
    cleaned = normalize_whitespace(text).lower()
    titled = normalize_whitespace(title or "").lower()
    if not cleaned and not titled:
        return False
    haystack = f"{titled} {cleaned}".strip()
    if any(marker in haystack for marker in _STRONG_ERROR_MARKERS):
        return True
    if "not found" in titled and "no longer available" in cleaned:
        return True
    if len(cleaned) > 280:
        return False
    return any(marker in cleaned for marker in _ERROR_PAGE_MARKERS)


def _decompose_junk(soup: BeautifulSoup) -> None:
    for tag in soup(JUNK_TAGS):
        tag.decompose()
    for selector in JUNK_SELECTORS:
        for node in soup.select(selector):
            node.decompose()


def _text_of(node: Tag | BeautifulSoup) -> str:
    return normalize_whitespace(node.get_text(separator=" "))


def _page_title(soup: BeautifulSoup) -> str | None:
    title: str | None = None
    if soup.title and soup.title.string:
        title = normalize_whitespace(soup.title.string) or None
    if title is None:
        og = soup.find("meta", attrs={"property": "og:title"})
        if og and og.get("content"):
            title = normalize_whitespace(str(og["content"])) or None
    return title


def _document_islands(soup: BeautifulSoup, selectors: tuple[str, ...]) -> list[str]:
    """User-visible document bodies: paste/source/article, not site chrome."""
    islands: list[str] = []
    seen: set[int] = set()
    for selector in selectors:
        for node in soup.select(selector):
            if selector == "textarea":
                raw = node.get("value") or node.string or node.get_text() or ""
                text = normalize_whitespace(str(raw))
            else:
                text = _text_of(node)
            if len(text) < 1 or id(node) in seen:
                continue
            seen.add(id(node))
            islands.append(text)
    unique: list[str] = []
    for item in sorted(set(islands), key=len, reverse=True):
        if any(item in other and item != other for other in unique):
            continue
        unique.append(item)
    return unique


def empty_document_holders(html: str) -> bool:
    """True when the markup has a document body container that is still empty."""
    soup = BeautifulSoup(html, "html.parser")
    holders = soup.select("pre, textarea, .source, [itemprop='articleBody']")
    if not holders:
        return False
    return all(len(_text_of(node)) < 1 for node in holders)


def extract_readable_text(html: str, max_chars: int = 24000) -> tuple[str | None, str]:
    """Extract bounded readable text from HTML. Prefers the document body over chrome."""
    soup = BeautifulSoup(html, "html.parser")
    title = _page_title(soup)
    _decompose_junk(soup)

    islands = _document_islands(soup, BODY_SELECTORS)
    raw = " ".join(islands) if islands else ""
    used_document_body = bool(raw)
    if not raw:
        islands = _document_islands(soup, LAYOUT_SELECTORS)
        raw = " ".join(islands) if islands else ""
    if not used_document_body and len(raw) < 40:
        preferred = (
            soup.find("main")
            or soup.find("article")
            or soup.find(attrs={"role": "main"})
        )
        if isinstance(preferred, Tag):
            raw = _text_of(preferred)
    if not used_document_body and len(raw) < 40:
        body = soup.body or soup
        raw = _text_of(body)

    text = normalize_readable_text(raw, max_chars=max_chars)
    return title, text


def looks_like_client_render(html: str, text: str, min_chars: int = 80) -> bool:
    """True when HTTP HTML is an application shell with little readable text."""
    soup = BeautifulSoup(html, "html.parser")
    if _document_islands(soup, BODY_SELECTORS) and text:
        return False
    if empty_document_holders(html) and len(text) < min_chars:
        return True
    if len(text) >= min_chars:
        return False

    for shell_id in SHELL_IDS:
        if soup.find(id=shell_id):
            return True

    lowered_html = html.lower()
    lowered_text = text.lower()
    if not text:
        if "enable javascript" in lowered_html or "you need to enable javascript" in lowered_html:
            return True
        if soup.find_all("script"):
            return True
        return False

    placeholders = ("loading", "please wait", "enable javascript")
    if lowered_text in placeholders or lowered_text.startswith("loading"):
        return True
    return False


def detect_access_block(
    html: str,
    text: str,
    status_code: int | None = None,
) -> WebpageToolError | None:
    """Detect CAPTCHA, auth walls, bot challenges, and paywalls. Does not bypass them."""
    if status_code in (401, 403):
        return WebpageToolError(
            "authentication_required",
            "Authentication is required to access this webpage.",
            status_code=status_code,
        )

    soup = BeautifulSoup(html, "html.parser")
    for selector in PAYWALL_SELECTORS:
        if soup.select_one(selector):
            return WebpageToolError(
                "paywall",
                "This page is behind a paywall. Sentinel will not bypass it.",
                status_code=status_code,
            )

    combined = f"{html[:8000]}\n{text}".lower()
    if any(
        token in combined
        for token in (
            "g-recaptcha",
            "h-captcha",
            "cf-turnstile",
            'id="captcha"',
            "class=\"captcha\"",
            "class='captcha'",
        )
    ) or "verify you are human" in combined or "are you a robot" in combined:
        return WebpageToolError(
            "captcha_required",
            "A CAPTCHA challenge is present. Sentinel will not bypass it.",
            status_code=status_code,
        )
    if (
        "cf-browser-verification" in combined
        or "checking your browser before accessing" in combined
        or ("just a moment" in combined and "cloudflare" in combined)
    ):
        return WebpageToolError(
            "bot_protection",
            "This page is protected by a bot challenge. Sentinel will not bypass it.",
            status_code=status_code,
        )
    if (
        "sign in to continue" in combined
        or "log in to continue" in combined
        or "login to continue" in combined
    ) and len(text) < 200:
        return WebpageToolError(
            "authentication_required",
            "Authentication is required to access this webpage.",
            status_code=status_code,
        )
    return None
