import httpx
import pytest

from app.tools.web_monitor import (
    WebpageToolError,
    check_webpage,
    hash_content,
    normalize_whitespace,
)

SAMPLE_HTML = """
<html>
  <head>
    <title>Admissions</title>
    <style>body { color: red; }</style>
    <script>alert("ignore me");</script>
  </head>
  <body>
    <h1>Application deadline</h1>
    <p>Deadline: 1 May 2026</p>
    <noscript>enable javascript</noscript>
  </body>
</html>
"""


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)


def test_valid_webpage_returns_observation() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=SAMPLE_HTML)

    result = check_webpage("https://example.com/admissions", client=_client(handler))

    assert result.url == "https://example.com/admissions"
    assert result.status_code == 200
    assert result.title == "Admissions"
    assert "Application deadline" in result.text
    assert "Deadline: 1 May 2026" in result.text
    assert result.content_hash == hash_content(result.text)
    assert result.fetched_at is not None
    assert result.fetch_method == "http"


def test_invalid_url_is_rejected() -> None:
    with pytest.raises(WebpageToolError) as exc:
        check_webpage("ftp://example.com/page")

    assert exc.value.code == "invalid_url"
    assert exc.value.to_dict()["message"]


@pytest.mark.parametrize(
    "url",
    ["", "not-a-url", "example.com", "http://", "javascript:alert(1)"],
)
def test_malformed_urls_are_rejected(url: str) -> None:
    with pytest.raises(WebpageToolError) as exc:
        check_webpage(url)
    assert exc.value.code == "invalid_url"


@pytest.mark.parametrize("status_code", [404, 500])
def test_http_errors_are_not_treated_as_success(status_code: int) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, text="<html><body>Error page</body></html>")

    with pytest.raises(WebpageToolError) as exc:
        check_webpage("https://example.com/missing", client=_client(handler))

    assert exc.value.code == "http_error"
    assert exc.value.status_code == status_code


@pytest.mark.parametrize("status_code", [401, 403])
def test_auth_errors_require_human_login(status_code: int) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, text="<html><body>Sign in</body></html>")

    with pytest.raises(WebpageToolError) as exc:
        check_webpage("https://example.com/private", client=_client(handler))

    assert exc.value.code == "authentication_required"
    assert exc.value.status_code == status_code


def test_timeout_is_handled() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timed out")

    with pytest.raises(WebpageToolError) as exc:
        check_webpage("https://example.com/slow", client=_client(handler))

    assert exc.value.code == "timeout"


def test_connection_failure_is_handled() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    with pytest.raises(WebpageToolError) as exc:
        check_webpage("https://example.com/down", client=_client(handler))

    assert exc.value.code == "connection_failure"


def test_script_and_style_are_excluded() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=SAMPLE_HTML)

    result = check_webpage("https://example.com/admissions", client=_client(handler))

    assert "ignore me" not in result.text
    assert "color: red" not in result.text
    assert "enable javascript" not in result.text


def test_whitespace_normalization_and_stable_hash() -> None:
    messy = "<html><body>Hello    World\n\nNext</body></html>"
    tidy = "<html><body>Hello World Next</body></html>"

    def messy_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=messy)

    def tidy_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=tidy)

    messy_result = check_webpage("https://example.com/a", client=_client(messy_handler))
    tidy_result = check_webpage("https://example.com/b", client=_client(tidy_handler))

    assert messy_result.text == "Hello World Next"
    assert messy_result.text == tidy_result.text
    assert messy_result.content_hash == tidy_result.content_hash
    assert normalize_whitespace("Hello    World") == "Hello World"


def test_content_change_produces_different_hash() -> None:
    first = "<html><body>Deadline: 1 May 2026</body></html>"
    second = "<html><body>Deadline: 15 May 2026</body></html>"

    def first_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=first)

    def second_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=second)

    a = check_webpage("https://example.com/deadline", client=_client(first_handler))
    b = check_webpage("https://example.com/deadline", client=_client(second_handler))

    assert a.content_hash != b.content_hash


def test_redirect_to_success_is_followed() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/old":
            return httpx.Response(302, headers={"Location": "https://example.com/new"})
        return httpx.Response(200, text="<html><body>Redirected content</body></html>")

    result = check_webpage("https://example.com/old", client=_client(handler))
    assert result.status_code == 200
    assert result.text == "Redirected content"
    assert result.fetch_method == "http"
    assert result.final_url is not None


def test_static_page_does_not_invoke_browser() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=SAMPLE_HTML)

    def render(url: str, timeout: float) -> tuple[int, str, str]:
        raise AssertionError("Playwright should not run for usable HTTP pages")

    result = check_webpage(
        "https://example.com/admissions",
        client=_client(handler),
        render_page=render,
    )
    assert result.fetch_method == "http"


def test_js_shell_uses_browser_fallback() -> None:
    shell = """
    <html><body>
      <div id="root"></div>
      <script src="app.js"></script>
    </body></html>
    """
    rendered = """
    <html><body>
      <h1>Admissions</h1>
      <p>Deadline: 1 May 2026</p>
    </body></html>
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=shell)

    calls = {"count": 0}

    def render(url: str, timeout: float) -> tuple[int, str, str]:
        calls["count"] += 1
        return 200, rendered, url

    result = check_webpage(
        "https://example.com/spa",
        client=_client(handler),
        render_page=render,
        allow_browser=True,
    )
    assert calls["count"] == 1
    assert result.fetch_method == "browser"
    assert "1 May 2026" in result.text
    assert result.content_hash == hash_content(result.text)


def test_js_shell_without_browser_stays_structured() -> None:
    shell = '<html><body><div id="root"></div><script src="app.js"></script></body></html>'

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=shell)

    with pytest.raises(WebpageToolError) as exc:
        check_webpage(
            "https://example.com/spa",
            client=_client(handler),
            allow_browser=False,
        )
    assert exc.value.code == "empty_response"


def test_browser_http_error_is_not_an_observation() -> None:
    shell = '<html><body><div id="root"></div><script src="app.js"></script></body></html>'

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=shell)

    def render(url: str, timeout: float) -> tuple[int, str, str]:
        return 500, "<html><body>Error</body></html>", url

    with pytest.raises(WebpageToolError) as exc:
        check_webpage(
            "https://example.com/spa",
            client=_client(handler),
            render_page=render,
            allow_browser=True,
        )
    assert exc.value.code == "http_error"
    assert exc.value.status_code == 500


def test_captcha_page_is_blocked_and_skips_browser() -> None:
    html = """
    <html><body>
      <div class="g-recaptcha"></div>
      <p>verify you are human</p>
    </body></html>
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=html)

    def render(url: str, timeout: float) -> tuple[int, str, str]:
        raise AssertionError("Must not use Playwright to bypass CAPTCHA")

    with pytest.raises(WebpageToolError) as exc:
        check_webpage(
            "https://example.com/secure",
            client=_client(handler),
            render_page=render,
        )
    assert exc.value.code == "captcha_required"
    assert exc.value.to_dict()["human_loop_state"] == "blocked_requires_user"


def test_empty_html_is_empty_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="   ")

    with pytest.raises(WebpageToolError) as exc:
        check_webpage("https://example.com/empty", client=_client(handler))
    assert exc.value.code == "empty_response"
