"""Event-driven ingestion endpoint: receives AI-activity/artifact push events
from `.github/hooks/` and the `agentrise` MCP (ADR-0002: Execution model).

Skeleton only — persistence + retry wiring land in implementation planning.
"""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, status

from app.core.retry import retry_with_backoff
from app.schemas.activity import ActivityEventIn, ActivityEventOut

router = APIRouter(prefix="/ingest", tags=["ingest"])


async def _persist(event: ActivityEventIn) -> ActivityEventOut:
    # TODO(implementation): write-through to Postgres via SQLAlchemy session.
    return ActivityEventOut(
        id=str(uuid.uuid4()),
        source=event.source,
        event_type=event.event_type,
        occurred_at=event.occurred_at,
        received_at=datetime.now(UTC),
    )


@router.post("/events", status_code=status.HTTP_201_CREATED, response_model=ActivityEventOut)
async def ingest_event(event: ActivityEventIn) -> ActivityEventOut:
    return await retry_with_backoff(lambda: _persist(event), max_attempts=3)
