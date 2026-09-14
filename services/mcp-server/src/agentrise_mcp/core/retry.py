"""Retry policy primitives for the HTTP client.

Pure functions and constants — no I/O. See PLAN T-04 / NFR-Performance:
max 3 attempts total, exponential backoff with jitter, base 0.5s, cap 4s,
retry ONLY on network-layer errors (never on 4xx/5xx HTTP responses).
"""

from __future__ import annotations

import random

import httpx

NETWORK_RETRY_EXCEPTIONS: tuple[type[Exception], ...] = (
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.ReadTimeout,
    httpx.WriteError,
    httpx.RemoteProtocolError,
)


def compute_backoff(
    attempt: int,
    base: float = 0.5,
    cap: float = 4.0,
    jitter: float = 0.25,
) -> float:
    """Return delay in seconds for a given retry attempt (1-indexed).

    attempt=1 -> base + jitter, attempt=2 -> 2*base + jitter, capped at ``cap``.
    Jitter is drawn uniformly from ``[0, jitter)`` via ``random.random()``.
    """
    if attempt <= 0:
        raise ValueError("attempt must be >= 1")
    delay = base * (2 ** (attempt - 1))
    if delay > cap:
        delay = cap
    return delay + random.random() * jitter
