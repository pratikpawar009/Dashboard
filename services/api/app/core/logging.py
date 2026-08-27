"""Structured JSON logging (ADR-0002: Operability)."""

import json
import logging
import sys
from datetime import UTC, datetime

from app.core.config import settings

# D-04: hardcoded, not computed from a throwaway LogRecord's vars() — a computed
# set drifts across Python versions (3.12 added taskName) and hides what is
# actually excluded from a payload every log line in the service passes through.
_RESERVED_LOGRECORD_ATTRS = frozenset(
    {
        "name",
        "msg",
        "args",
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
        "message",
        "asctime",
        "taskName",
    }
)


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        # FR-3: merge caller-supplied `extra={...}` fields. Existing keys win —
        # an extra can never overwrite a first-class payload key — and reserved
        # LogRecord attrs are never candidates in the first place.
        for key, value in record.__dict__.items():
            if key not in _RESERVED_LOGRECORD_ATTRS and key not in payload:
                payload[key] = value
        # default=str: an extra value may not be JSON-serialisable (e.g. a
        # Decimal or custom object). Degrade to its str() rather than raise —
        # a log call must never crash the request path it's observing.
        return json.dumps(payload, default=str)


def configure_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(settings.log_level)
