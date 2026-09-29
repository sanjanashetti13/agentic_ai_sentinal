from __future__ import annotations


class WebpageToolError(Exception):
    """Structured error from check_webpage. Safe to show to API consumers."""

    _BLOCKING_CODES = {
        "captcha_required",
        "otp_required",
        "authentication_required",
        "bot_protection",
        "paywall",
        "blocked_requires_user",
    }

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)

    def is_blocking(self) -> bool:
        return self.code in self._BLOCKING_CODES

    def to_dict(self) -> dict[str, str | int | None]:
        payload: dict[str, str | int | None] = {
            "error": self.code,
            "message": self.message,
            "status_code": self.status_code,
        }
        if self.is_blocking():
            payload["human_loop_state"] = "blocked_requires_user"
        return payload


def is_blocking_error_code(code: str) -> bool:
    return code in WebpageToolError._BLOCKING_CODES
