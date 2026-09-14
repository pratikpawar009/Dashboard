"""Thin sync wrapper over httpx.Client with fixed timeout + retry policy.

Retries ONLY on network-layer errors (``NETWORK_RETRY_EXCEPTIONS``); 4xx / 5xx
HTTP responses are returned to the caller unchanged. Token is redacted in
``__repr__`` (R-07) and never logged.
"""

from __future__ import annotations

import logging
import time
from types import TracebackType
from typing import Any

import httpx

from agentrise_mcp.core.retry import NETWORK_RETRY_EXCEPTIONS, compute_backoff

logger = logging.getLogger(__name__)


class HttpClient:
    """Thin sync wrapper over httpx.Client with fixed timeout + retry policy."""

    def __init__(
        self,
        base_url: str,
        token: str,
        *,
        connect_timeout: float = 5.0,
        total_timeout: float = 30.0,
        max_attempts: int = 3,
    ) -> None:
        self._base_url = base_url
        self._token = token
        self._max_attempts = max_attempts
        self._client = httpx.Client(
            base_url=base_url,
            timeout=httpx.Timeout(total_timeout, connect=connect_timeout),
        )

    def post_json(self, path: str, payload: dict[str, object]) -> httpx.Response:
        """POST ``payload`` as JSON to ``base_url + path``.

        Retries on ``NETWORK_RETRY_EXCEPTIONS`` up to ``max_attempts``, sleeping
        ``compute_backoff(attempt)`` between attempts. Returns the first
        ``httpx.Response`` — including 4xx / 5xx. Raises the last network
        exception when attempts are exhausted.
        """
        headers = {"Authorization": f"Bearer {self._token}"}
        last_exc: Exception | None = None
        for attempt in range(1, self._max_attempts + 1):
            try:
                return self._client.post(path, json=payload, headers=headers)
            except NETWORK_RETRY_EXCEPTIONS as exc:
                last_exc = exc
                logger.warning(
                    "http_client network error: attempt=%d/%d exc=%s",
                    attempt,
                    self._max_attempts,
                    type(exc).__name__,
                )
                if attempt >= self._max_attempts:
                    raise
                time.sleep(compute_backoff(attempt))
        # Unreachable — loop either returns, raises, or sleeps and continues.
        assert last_exc is not None
        raise last_exc

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> HttpClient:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def __repr__(self) -> str:
        return f"HttpClient(base_url={self._base_url!r}, token=<redacted>)"

    def __getstate__(self) -> dict[str, Any]:  # pragma: no cover - defensive
        raise TypeError("HttpClient is not picklable (holds a bearer token)")
