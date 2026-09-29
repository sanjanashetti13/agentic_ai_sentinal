from app.tools.page_extract import (
    detect_access_block,
    extract_readable_text,
    hash_content,
    looks_like_client_render,
    looks_like_error_page,
    normalize_readable_text,
)


def test_malformed_html_still_yields_readable_text() -> None:
    _, text = extract_readable_text(
        "<html><body><p>Deadline: 2 June 2026<div>Applications open"
    )
    assert "2 June 2026" in text
    assert "Applications open" in text


def test_navigation_and_cookie_banner_are_ignored() -> None:
    first = """
    <html><body>
      <nav>Home About Contact</nav>
      <div id="cookie-banner">We use cookies Accept Reject</div>
      <p>Deadline: 1 May 2026</p>
      <p>Status: Open</p>
    </body></html>
    """
    second = """
    <html><body>
      <nav>Careers Blog Login</nav>
      <div class="cookie-consent">Cookie policy Allow</div>
      <p>Deadline: 1 May 2026</p>
      <p>Status: Open</p>
    </body></html>
    """
    _, a = extract_readable_text(first)
    _, b = extract_readable_text(second)
    assert "1 May 2026" in a
    assert "Home About" not in a
    assert "cookies" not in a.lower()
    assert hash_content(a) == hash_content(b)


def test_meaningful_date_change_is_preserved() -> None:
    _, a = extract_readable_text("<html><body><p>Deadline: 1 May 2026</p></body></html>")
    _, b = extract_readable_text("<html><body><p>Deadline: 15 May 2026</p></body></html>")
    assert hash_content(a) != hash_content(b)
    assert "15 May 2026" in b


def test_relative_timestamps_do_not_change_hash() -> None:
    a = normalize_readable_text("Deadline: 1 May 2026 Updated 2 minutes ago Price $40")
    b = normalize_readable_text("Deadline: 1 May 2026 Updated 9 minutes ago Price $40")
    assert "1 May 2026" in a
    assert "$40" in a
    assert "minutes ago" not in a
    assert hash_content(a) == hash_content(b)


def test_js_shell_is_detected() -> None:
    html = '<html><body><div id="root"></div><script src="app.js"></script></body></html>'
    _, text = extract_readable_text(html)
    assert looks_like_client_render(html, text)
    static = "<html><body><p>Deadline: 1 May 2026</p></body></html>"
    _, static_text = extract_readable_text(static)
    assert not looks_like_client_render(static, static_text)


def test_dynamic_html_noise_does_not_change_hash() -> None:
    first = """
    <html><body>
      <script>var id = "abc123";</script>
      <nav>Home</nav>
      <p>Deadline: 14 September 2026</p>
      <img class="rand-a1f3" src="/pixel.gif?utm_source=x">
    </body></html>
    """
    second = """
    <html><body>
      <script>var id = "zzz999";</script>
      <nav>Careers</nav>
      <p>Deadline: 14 September 2026</p>
      <img class="rand-b9c0" src="/pixel.gif?utm_source=y">
    </body></html>
    """
    _, a = extract_readable_text(first)
    _, b = extract_readable_text(second)
    assert "14 September 2026" in a
    assert hash_content(a) == hash_content(b)


def test_session_ids_and_clocks_do_not_change_hash() -> None:
    a = normalize_readable_text(
        "Deadline: 14 September 2026 session_id=aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee 12:01:09"
    )
    b = normalize_readable_text(
        "Deadline: 14 September 2026 session_id=ffffffff-bbbb-cccc-dddd-111111111111 12:01:41"
    )
    assert "14 September 2026" in a
    assert hash_content(a) == hash_content(b)


def test_error_page_text_is_detected() -> None:
    assert looks_like_error_page("502 Bad Gateway nginx")
    assert looks_like_error_page("Internal Server Error")
    assert not looks_like_error_page(
        "Application deadline: 14 September 2026. If you see an error, contact support."
    )


def test_captcha_and_paywall_are_blocked() -> None:
    captcha = detect_access_block(
        '<html><body><div class="g-recaptcha"></div><p>verify you are human</p></body></html>',
        "verify you are human",
        status_code=200,
    )
    assert captcha is not None
    assert captcha.code == "captcha_required"
    assert captcha.to_dict()["human_loop_state"] == "blocked_requires_user"

    paywall = detect_access_block(
        '<html><body><div id="paywall">Subscribe</div></body></html>',
        "Subscribe",
        status_code=200,
    )
    assert paywall is not None
    assert paywall.code == "paywall"


def test_error_document_is_detected_from_title() -> None:
    assert looks_like_error_page(
        "Pastebin.com Public Pastes Login Sign Up",
        title="Pastebin.com - Not Found (#404)",
    )
    assert looks_like_error_page("This page is no longer available")
    assert looks_like_error_page("502 Bad Gateway")

