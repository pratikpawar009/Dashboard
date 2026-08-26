"""Bounded retry with exponential backoff + jitter for the ingest path.

See ADR-0002 (Operability) and .claude/rules/performance-baseline.md.
"""

import asyncio
import random
from collections.abc import Awaitable, Callable
from typing import TypeVar

T = TypeVar("T")


async def retry_with_backoff(
    fn: Callable[[], Awaitable[T]],
    *,
    max_attempts: int = 3,
    base_delay_s: float = 0.1,
    max_delay_s: float = 2.0,
) -> T:
    """Retry `fn` up to `max_attempts` times with exponential backoff + full jitter.

    Bounded: never retries indefinitely. Caller's `fn` should raise on failure.
    """
    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return await fn()
        except Exception as exc:  # noqa: BLE001 - re-raised after exhausting attempts
            last_exc = exc
            if attempt == max_attempts:
                break
            delay = min(max_delay_s, base_delay_s * (2 ** (attempt - 1)))
            await asyncio.sleep(random.uniform(0, delay))
    assert last_exc is not None
    raise last_exc
