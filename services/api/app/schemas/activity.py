from datetime import datetime

from pydantic import BaseModel, Field


class ActivityEventIn(BaseModel):
    """Ingest payload for an AI-activity/artifact push event (ADR-0002: Execution model)."""

    source: str = Field(..., description="Producer id, e.g. harness-mcp-push, copilot-activity")
    event_type: str
    occurred_at: datetime
    payload: dict


class ActivityEventOut(BaseModel):
    id: str
    source: str
    event_type: str
    occurred_at: datetime
    received_at: datetime
