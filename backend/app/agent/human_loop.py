from __future__ import annotations

from app.models.schemas import ActionDecision, HumanLoopState


_BLOCKING_ERROR_CODES = {
    "captcha_required": (
        "blocked_requires_user",
        "CAPTCHA is required. Sentinel will not bypass it.",
    ),
    "otp_required": (
        "blocked_requires_user",
        "An OTP or verification code is required. Sentinel will not bypass it.",
    ),
    "authentication_required": (
        "blocked_requires_user",
        "Authentication is required. The user must sign in.",
    ),
    "bot_protection": (
        "blocked_requires_user",
        "A bot-protection challenge is present. Sentinel will not bypass it.",
    ),
    "paywall": (
        "blocked_requires_user",
        "This page is behind a paywall. Sentinel will not bypass it.",
    ),
    "blocked_requires_user": (
        "blocked_requires_user",
        "User intervention is required. Sentinel will not bypass security controls.",
    ),
}


def detect_human_loop_block(
    *,
    error_code: str | None = None,
    page_text: str | None = None,
) -> tuple[HumanLoopState, str] | None:
    """Return a forced HITL state for security walls.

    This inspects structured tool errors and obvious security-control pages.
    It does not branch on the user's monitoring goal.
    """
    if error_code in _BLOCKING_ERROR_CODES:
        state, reason = _BLOCKING_ERROR_CODES[error_code]
        return state, reason  # type: ignore[return-value]

    text = (page_text or "").lower()
    if not text:
        return None
    if "captcha" in text or "recaptcha" in text or "h-captcha" in text:
        return (
            "blocked_requires_user",
            "A CAPTCHA challenge is present. Sentinel will not bypass it.",
        )
    if "enter the otp" in text or "one-time password" in text:
        return (
            "blocked_requires_user",
            "An OTP challenge is present. Sentinel will not bypass it.",
        )
    return None


def apply_human_loop_safety(
    decision: ActionDecision,
    *,
    error_code: str | None = None,
    page_text: str | None = None,
) -> ActionDecision:
    blocked = detect_human_loop_block(error_code=error_code, page_text=page_text)
    if blocked is None:
        return decision
    state, reason = blocked
    return decision.model_copy(
        update={
            "action_type": "request_approval",
            "human_loop_state": state,
            "requires_approval": True,
            "blocked_reason": reason,
            "reason": reason,
            "user_notification": reason,
        }
    )
