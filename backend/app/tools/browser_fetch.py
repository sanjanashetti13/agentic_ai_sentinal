from __future__ import annotations

from collections.abc import Callable

from app.tools.errors import WebpageToolError

BrowserRenderFn = Callable[[str, float], tuple[int, str, str]]


def playwright_available() -> bool:
    try:
        import playwright  # noqa: F401
    except ImportError:
        return False
    return True


def render_page_with_playwright(
    url: str,
    timeout_seconds: float,
) -> tuple[int, str, str]:
    """Fetch rendered HTML. Does not click, fill forms, or bypass protections."""
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import TimeoutError as PlaywrightTimeout
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise WebpageToolError(
            "javascript_required",
            "This page appears to need JavaScript rendering. "
            "Install Playwright and Chromium to enable the browser fallback: "
            "pip install playwright && playwright install chromium",
        ) from exc

    timeout_ms = max(1000, int(timeout_seconds * 1000))
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page(
                    user_agent="Sentinel/0.1 (webpage-monitor)",
                )
                page.set_default_timeout(timeout_ms)
                response = page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=timeout_ms,
                )
                try:
                    page.wait_for_load_state(
                        "networkidle",
                        timeout=min(5000, timeout_ms),
                    )
                except PlaywrightTimeout:
                    pass
                status = response.status if response is not None else 200
                html = page.content()
                final_url = page.url
                return status, html, final_url
            finally:
                browser.close()
    except PlaywrightTimeout:
        raise WebpageToolError(
            "timeout",
            "The browser rendering timed out.",
        ) from None
    except PlaywrightError:
        raise WebpageToolError(
            "connection_failure",
            "The browser could not load the webpage.",
        ) from None
