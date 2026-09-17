"""Response schema for GET /api/overview/program-detail/{program_id}/session-time-series
(PGD-06-FR-2).
"""

from pydantic import BaseModel, Field


class SessionPoint(BaseModel):
    """One day's point in the program session-time series (PGD-06-FR-2).

    `session_time_seconds` is a raw int (seconds), mirroring
    `ProgramTokenPoint.tokens` (PGD-02 D-02/D-03) -- no pre-formatted duration
    string anywhere in this response (DECISIONS.md D-04).
    """

    date: str
    session_time_seconds: int


class SessionSeriesResponse(BaseModel):
    """Response envelope for GET /api/overview/program-detail/{program_id}/session-time-series
    (PGD-06).

    All three numeric surfaces are raw ints (seconds) -- matches
    `ProgramTokenTrendResponse`, not the pre-formatted-string shape used by
    `/releases` (DECISIONS.md D-04). `avg_seconds_per_day` divides by the
    range's fixed day-count, never the count of days with data (D-04).
    """

    points: list[SessionPoint]
    period_total_seconds: int = Field(
        ..., description="Raw sum of session_time_seconds across the range"
    )
    avg_seconds_per_day: int = Field(
        ...,
        description="Raw average session_time_seconds per day across the range "
        "(fixed day-count divisor)",
    )
