"""Structured JSON logger with event allowlist + token-suppression (ING-04 · T-05).

Covers NFR-Observability (bounded event vocabulary) and R-07 (token secret
leakage HIGH risk). `get_logger` is the sole entry point — no handlers are
installed at import time. Emits one-line JSON to stdout only.

Design notes:
- Event allowlist is enforced by a `logging.Filter` on the handler. Records
  without an allowlisted `event` extra are dropped silently, preventing the
  allowlist itself from becoming a covert channel to grow the event set.
- Token redaction runs as a second filter, after allowlist, so out-of-band
  records never touch the redactor. Redaction is substring-based on `msg`,
  `args`, and every non-standard field in `record.__dict__`; known secret
  keys have their entire value replaced.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

_ALLOWED_EVENTS: frozenset[str] = frozenset(
    {
        # PRD NFR-Observability push_activity_* / push_artifacts_* vocabulary.
        "push_activity_started",
        "push_activity_completed",
        "push_activity_batch_failed",
        "push_activity_auth_failed",
        "push_activity_missing_token",
        "push_artifacts_started",
        "push_artifacts_completed",
        "push_artifacts_batch_failed",
        "push_artifacts_auth_failed",
        "push_artifacts_missing_token",
        "push_manifest_started",
        "push_manifest_completed",
        "push_manifest_failed",
        "push_manifest_auth_failed",
        "push_manifest_missing_token",
        # Boot + retry surfaces, outside the push_* families.
        "http.retry",
        "http.give_up",
        "config.loaded",
    }
)

# Standard LogRecord attributes the token filter must not scan (per spec).
_STD_LOGRECORD_FIELDS: frozenset[str] = frozenset(
    {
        "msg",
        "args",
        "name",
        "levelname",
        "levelno",
        "pathname",
        "filename",
        "module",
        "exc_info",
        "exc_text",
        "stack_info",
        "lineno",
        "funcName",
        "created",
        "msecs",
        "relativeCreated",
        "thread",
        "threadName",
        "processName",
        "process",
    }
)

# Extra keys skipped by the JSON formatter (standard fields + fields we
# already emit at the top level, plus 3.12's taskName).
_FORMATTER_SKIP: frozenset[str] = _STD_LOGRECORD_FIELDS | {
    "message",
    "taskName",
    "event",
}

# Structured extra keys whose entire value is replaced regardless of contents.
_SECRET_KEYS: frozenset[str] = frozenset(
    {
        "Authorization",
        "authorization",
        "bearer_token",
        "token",
        "AGENTRISE_INGEST_TOKEN",
    }
)

_REDACTED = "<redacted>"

# Sentinel attribute so repeat calls to get_logger don't stack handlers.
_CONFIGURED_ATTR = "_agentrise_configured"


class EventAllowlistFilter(logging.Filter):
    """Drops records whose `event` extra is missing or not on the allowlist."""

    def filter(self, record: logging.LogRecord) -> bool:
        event = getattr(record, "event", None)
        if not isinstance(event, str):
            return False
        return event in _ALLOWED_EVENTS


class TokenSuppressionFilter(logging.Filter):
    """Redacts occurrences of `token_value` on the record, in-place.

    Substring-redacts `msg`, `args`, and non-standard fields. Also fully
    redacts any field whose key is a known secret key (`Authorization`,
    `token`, …) even when the value does not contain the token.
    """

    def __init__(self, token_value: str) -> None:
        super().__init__()
        self._token = token_value

    def filter(self, record: logging.LogRecord) -> bool:
        token = self._token

        if isinstance(record.msg, str) and token in record.msg:
            record.msg = record.msg.replace(token, _REDACTED)

        if record.args:
            if isinstance(record.args, tuple):
                record.args = tuple(
                    a.replace(token, _REDACTED)
                    if isinstance(a, str) and token in a
                    else a
                    for a in record.args
                )
            elif isinstance(record.args, dict):
                record.args = {
                    k: (
                        v.replace(token, _REDACTED)
                        if isinstance(v, str) and token in v
                        else v
                    )
                    for k, v in record.args.items()
                }

        for key, value in list(record.__dict__.items()):
            if key in _STD_LOGRECORD_FIELDS:
                continue
            if key in _SECRET_KEYS:
                record.__dict__[key] = _REDACTED
                continue
            if isinstance(value, str) and token in value:
                record.__dict__[key] = value.replace(token, _REDACTED)

        return True


class _JsonFormatter(logging.Formatter):
    """One-line JSON formatter for LogRecords."""

    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created, tz=UTC).isoformat()
        payload: dict[str, Any] = {
            "ts": ts,
            "level": record.levelname,
            "event": getattr(record, "event", None),
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key in _FORMATTER_SKIP:
                continue
            if key in payload:
                continue
            payload[key] = value
        return json.dumps(payload, default=str)


def get_logger(
    name: str = "agentrise_mcp", *, token: str | None = None
) -> logging.Logger:
    """Return a JSON-formatted logger with the allowlist + token filter installed.

    When `token` is None, the token filter is not installed (test-only path).
    Idempotent — repeated calls with the same name do not double-install handlers.
    """
    logger = logging.getLogger(name)
    if getattr(logger, _CONFIGURED_ATTR, False):
        return logger

    logger.setLevel(logging.INFO)
    logger.propagate = False

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_JsonFormatter())
    handler.addFilter(EventAllowlistFilter())
    if token is not None:
        handler.addFilter(TokenSuppressionFilter(token))
    logger.addHandler(handler)
    setattr(logger, _CONFIGURED_ATTR, True)

    if token is not None and len(token) < 8:
        logger.warning(
            "token shorter than 8 chars — substring redaction may over-redact",
            extra={"event": "config.loaded"},
        )
    return logger
