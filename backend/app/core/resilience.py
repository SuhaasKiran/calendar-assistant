from __future__ import annotations

import random
import time
from collections.abc import Callable
from typing import TypeVar

from app.core.errors import RetryableExternalError

T = TypeVar("T")


def call_with_retry(
    fn: Callable[[], T],
    *,
    max_attempts: int,
    base_delay_seconds: float,
    max_delay_seconds: float,
    is_retryable_error: Callable[[Exception], bool],
) -> T:
    """
    Execute `fn` with bounded exponential backoff and jitter.
    """
    attempts = max(1, max_attempts)
    for attempt in range(attempts):
        try:
            return fn()
        except Exception as exc:
            if attempt == attempts - 1 or not is_retryable_error(exc):
                raise
            delay = min(max_delay_seconds, base_delay_seconds * (2**attempt))
            time.sleep(delay + random.uniform(0, 0.1))
    raise RetryableExternalError("Call failed after retry budget exhausted")
