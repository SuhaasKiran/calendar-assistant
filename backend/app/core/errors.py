from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class AppError(Exception):
    """Base app error that can be safely mapped to HTTP/SSE payloads."""

    message: str
    code: str
    status_code: int = 500
    retryable: bool = False
    expose_message: bool = False

    def public_message(self) -> str:
        if self.expose_message:
            return self.message
        return "Something went wrong on our side. Please try again."


class UserSafeError(AppError):
    def __init__(self, message: str, *, code: str, status_code: int = 400) -> None:
        super().__init__(
            message=message,
            code=code,
            status_code=status_code,
            retryable=False,
            expose_message=True,
        )


class RetryableExternalError(AppError):
    def __init__(self, message: str, *, code: str = "EXTERNAL_RETRYABLE") -> None:
        super().__init__(
            message=message,
            code=code,
            status_code=503,
            retryable=True,
            expose_message=False,
        )


class NonRetryableExternalError(AppError):
    def __init__(self, message: str, *, code: str = "EXTERNAL_FAILURE") -> None:
        super().__init__(
            message=message,
            code=code,
            status_code=502,
            retryable=False,
            expose_message=False,
        )


class SafetyBlockedError(AppError):
    def __init__(self, message: str, *, code: str = "SAFETY_BLOCKED") -> None:
        super().__init__(
            message=message,
            code=code,
            status_code=400,
            retryable=False,
            expose_message=True,
        )


def map_exception_code(exc: Exception) -> str:
    if isinstance(exc, AppError):
        return exc.code
    return "INTERNAL_ERROR"
