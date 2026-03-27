"""Tests for app error types and public message mapping."""

from app.core.errors import AppError, map_exception_code, UserSafeError


def test_app_error_public_message_hidden_by_default() -> None:
    err = AppError("internal detail", code="X", status_code=500, expose_message=False)
    assert err.public_message() == "Something went wrong on our side. Please try again."


def test_app_error_public_message_exposed_when_flag_true() -> None:
    err = UserSafeError("Visible to user", code="BAD_INPUT", status_code=400)
    assert err.public_message() == "Visible to user"


def test_map_exception_code_app_error_vs_generic() -> None:
    assert map_exception_code(UserSafeError("x", code="E1")) == "E1"
    assert map_exception_code(ValueError("oops")) == "INTERNAL_ERROR"
