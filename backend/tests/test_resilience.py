"""Tests for generic retry behavior utilities."""

from unittest.mock import patch

from app.core.resilience import call_with_retry


def test_call_with_retry_succeeds_after_retryable_failure() -> None:
    calls = {"n": 0}

    def flaky() -> str:
        calls["n"] += 1
        if calls["n"] < 2:
            raise RuntimeError("transient")
        return "ok"

    out = call_with_retry(
        flaky,
        max_attempts=3,
        base_delay_seconds=0.0,
        max_delay_seconds=0.0,
        is_retryable_error=lambda exc: isinstance(exc, RuntimeError),
    )
    assert out == "ok"
    assert calls["n"] == 2


def test_call_with_retry_stops_on_non_retryable_error() -> None:
    calls = {"n": 0}

    def boom() -> None:
        calls["n"] += 1
        raise ValueError("fatal")

    try:
        call_with_retry(
            boom,
            max_attempts=4,
            base_delay_seconds=0.0,
            max_delay_seconds=0.0,
            is_retryable_error=lambda exc: isinstance(exc, RuntimeError),
        )
        raise AssertionError("Expected ValueError")
    except ValueError:
        pass
    assert calls["n"] == 1


def test_call_with_retry_max_attempts_zero_runs_once() -> None:
    calls = {"n": 0}

    def once() -> str:
        calls["n"] += 1
        return "ok"

    out = call_with_retry(
        once,
        max_attempts=0,
        base_delay_seconds=0.0,
        max_delay_seconds=0.0,
        is_retryable_error=lambda exc: isinstance(exc, RuntimeError),
    )
    assert out == "ok"
    assert calls["n"] == 1


def test_call_with_retry_stops_after_max_retryable_attempts() -> None:
    calls = {"n": 0}

    def always_fail() -> None:
        calls["n"] += 1
        raise RuntimeError("transient")

    with patch("app.core.resilience.time.sleep", lambda *_a, **_k: None):
        try:
            call_with_retry(
                always_fail,
                max_attempts=3,
                base_delay_seconds=0.0,
                max_delay_seconds=0.0,
                is_retryable_error=lambda exc: isinstance(exc, RuntimeError),
            )
            raise AssertionError("Expected RuntimeError")
        except RuntimeError:
            pass
    assert calls["n"] == 3
