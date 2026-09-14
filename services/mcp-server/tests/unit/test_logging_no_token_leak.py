"""Tests for the structured logger's event allowlist + token suppression (ING-04 · T-05).

Covers NFR-Observability (only allowlisted events emit) and R-07 (the ingest
token never appears in any log surface — happy path, auth-failure path, or
structured extras — across both push_activity and push_artifacts families).
"""

from __future__ import annotations

import io
import json
import logging

from agentrise_mcp.core.logging import get_logger

_TOKEN = "secret-abc-1234"


def _fresh_logger(
    name: str, token: str | None = _TOKEN
) -> tuple[logging.Logger, io.StringIO]:
    """Build a logger under a unique name and redirect its handler to a StringIO."""
    logger = get_logger(name, token=token)
    buf = io.StringIO()
    assert logger.handlers, "get_logger must install exactly one handler"
    # StreamHandler.stream is the write target; swap it so the test can capture.
    logger.handlers[0].stream = buf
    return logger, buf


def _captured_records(buf: io.StringIO) -> list[dict]:
    lines = [ln for ln in buf.getvalue().splitlines() if ln.strip()]
    return [json.loads(ln) for ln in lines]


def test_allowlisted_event_emits() -> None:
    logger, buf = _fresh_logger("t_allowlisted_event_emits")
    logger.info("started", extra={"event": "push_activity_started"})
    records = _captured_records(buf)
    assert len(records) == 1
    assert records[0]["event"] == "push_activity_started"
    assert _TOKEN not in buf.getvalue()


def test_disallowed_event_dropped() -> None:
    logger, buf = _fresh_logger("t_disallowed_event_dropped")
    logger.info("nope", extra={"event": "push_activity.NOT_REAL"})
    assert buf.getvalue() == ""


def test_missing_event_dropped() -> None:
    logger, buf = _fresh_logger("t_missing_event_dropped")
    logger.info("no event field here")
    assert buf.getvalue() == ""


def test_token_in_message_redacted() -> None:
    logger, buf = _fresh_logger("t_token_in_message_redacted")
    logger.info(
        f"Failed with token {_TOKEN}",
        extra={"event": "push_activity_batch_failed"},
    )
    output = buf.getvalue()
    assert _TOKEN not in output
    records = _captured_records(buf)
    assert len(records) == 1
    assert "<redacted>" in records[0]["message"]


def test_token_in_extra_string_redacted() -> None:
    logger, buf = _fresh_logger("t_token_in_extra_string_redacted")
    logger.info(
        "retrying",
        extra={"event": "http.retry", "url": f"http://api/x?tok={_TOKEN}"},
    )
    records = _captured_records(buf)
    assert len(records) == 1
    assert _TOKEN not in buf.getvalue()
    assert "<redacted>" in records[0]["url"]


def test_authorization_extra_key_fully_redacted() -> None:
    logger, buf = _fresh_logger("t_authorization_extra_key_fully_redacted")
    logger.info(
        "sent batch",
        extra={
            "event": "push_activity_completed",
            "Authorization": f"Bearer {_TOKEN}",
        },
    )
    records = _captured_records(buf)
    assert len(records) == 1
    assert records[0]["Authorization"] == "<redacted>"
    assert _TOKEN not in buf.getvalue()


def test_multiple_events_no_token_across_both_tools() -> None:
    logger, buf = _fresh_logger("t_multiple_events_no_token_across_both_tools")
    # push_activity family — happy + auth-failure
    logger.info(
        f"starting with tok={_TOKEN}",
        extra={"event": "push_activity_started", "trace": f"begin {_TOKEN}"},
    )
    logger.info(
        "auth failed",
        extra={"event": "push_activity_auth_failed", "token": _TOKEN},
    )
    # push_artifacts family — happy + auth-failure
    logger.info(
        f"kicking off {_TOKEN}",
        extra={"event": "push_artifacts_started", "bearer_token": _TOKEN},
    )
    logger.info(
        f"done — bearer {_TOKEN} rejected",
        extra={
            "event": "push_artifacts_auth_failed",
            "url": f"https://api/x?t={_TOKEN}",
        },
    )
    stream = buf.getvalue()
    assert stream.count(_TOKEN) == 0
    records = _captured_records(buf)
    assert [r["event"] for r in records] == [
        "push_activity_started",
        "push_activity_auth_failed",
        "push_artifacts_started",
        "push_artifacts_auth_failed",
    ]


def test_get_logger_idempotent() -> None:
    first = get_logger("t_idempotent", token="t")
    second = get_logger("t_idempotent", token="t")
    assert first is second
    assert len(first.handlers) == 1
