"""Connector plumbing shared across vendors — Integration Spec §7.1.

Deliberately has zero imports from app.solvers and is never imported by
app.solvers: this package is Maestro's connector logic, kept in-process
with Tempo for now as a disclosed scaffold shortcut (see
services/tempo-api/README.md), not a reason to let vendor-specific code
leak into the optimisation layer (DP-03 / INT-002).
"""
from __future__ import annotations

import random
import time
from typing import Callable, TypeVar

T = TypeVar("T")


class ConnectorError(Exception):
    """Base for connector-level failures."""


class RateLimited(ConnectorError):
    def __init__(self, retry_after_seconds: float | None = None):
        super().__init__(f"rate limited, retry_after={retry_after_seconds}")
        self.retry_after_seconds = retry_after_seconds


class TransientError(ConnectorError):
    """Worth retrying (5xx, network failure)."""


class PermanentError(ConnectorError):
    """Not worth retrying (4xx other than 429)."""


def retry_with_backoff(
    fn: Callable[[], T],
    *,
    max_attempts: int = 5,
    base_delay_seconds: float = 0.5,
    max_delay_seconds: float = 30.0,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> T:
    """§7.1: 'Rate-limit awareness, exponential backoff with jitter and
    connector-specific throttling.' Retries RateLimited/TransientError;
    PermanentError and any other exception propagate immediately.
    """
    attempt = 0
    while True:
        attempt += 1
        try:
            return fn()
        except (RateLimited, TransientError) as exc:
            if attempt >= max_attempts:
                raise
            if isinstance(exc, RateLimited) and exc.retry_after_seconds is not None:
                delay = exc.retry_after_seconds
            else:
                delay = min(max_delay_seconds, base_delay_seconds * (2 ** (attempt - 1)))
            delay += random.uniform(0, delay * 0.1)
            sleep_fn(delay)
