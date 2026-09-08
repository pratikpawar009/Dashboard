"""Response schemas for GET /api/personal-usage/{user_id} (ADR-0009, SHP-02-FR-1..FR-6).

`PersonalUsageResponse` is the sealed `personal-usage-api` envelope ADR-0009 locks for four
not-yet-built consumers (ARC-01, DEV-01, PMD-01, PGD-05). See that ADR for the full field
inventory, the cards-are-to-date-vs-daily_tokens/commands-are-ranged split, and the
`count / max(counts) * 100` bar formula this module's field descriptions summarize.
"""

from pydantic import BaseModel, ConfigDict, Field


class PersonalUsageCard(BaseModel):
    """One of the 4 order-locked summary cards (ADR-0009, SHP-02-FR-1).

    Exactly 5 keys -- `glyph`/`label`/`iconBg`/`iconColor` are fixed presentation constants
    owned by the producer, zipped against the one varying `value` per card. No `delta` field
    ships, ever: it exists only in the mockup's mock-data generator, bound in zero templates
    across all three decoded mockups (ADR-0009 Context point 1).
    """

    model_config = ConfigDict(populate_by_name=True)

    glyph: str = Field(..., description="Fixed presentation glyph for this card")
    value: str = Field(..., description="Pre-formatted display value for this card")
    label: str = Field(..., description="Fixed presentation label for this card")
    icon_bg: str = Field(
        ..., alias="iconBg", description="Pre-formatted CSS for the card's icon background"
    )
    icon_color: str = Field(
        ..., alias="iconColor", description="Pre-formatted CSS for the card's icon color"
    )


class DailyTokenPoint(BaseModel):
    """One day's point in the daily token series (ADR-0009, SHP-02-FR-2)."""

    date: str = Field(..., description="ISO calendar date for this point")
    value: str = Field(..., description="Pre-formatted token total for this day")


class DailyTokenSeries(BaseModel):
    """Range-scoped daily token chart data (ADR-0009, SHP-02-FR-2).

    `points` is one entry per day in the selected range, zero-padded for a day with no
    sessions, oldest-to-newest. `period_total`/`avg_per_day` are the PRD's own literal field
    names (FR-2), both pre-formatted.
    """

    points: list[DailyTokenPoint]
    period_total: str = Field(..., description="Pre-formatted sum of tokens across the range")
    avg_per_day: str = Field(
        ..., description="Pre-formatted average tokens per day across the range"
    )


class CommandEntry(BaseModel):
    """One distinct command seen in the selected range (ADR-0009, SHP-02-FR-3).

    `count` is a raw int -- the one deliberate, documented exception to this response's
    "everything pre-formatted" convention, since it is the bar formula's own numerator/
    denominator input (ADR-0009 Consequences). `barStyle` is a ready-to-bind CSS width
    string, max-of-range not share-of-total (ADR-0009 Context point 3).
    """

    model_config = ConfigDict(populate_by_name=True)

    command: str = Field(..., description="Command name")
    count: int = Field(..., description="Raw run count for this command in the selected range")
    bar_style: str = Field(
        ..., alias="barStyle", description="Pre-formatted CSS width for this command's bar"
    )


class CommandsPanel(BaseModel):
    """Range-scoped commands breakdown (ADR-0009, SHP-02-FR-3)."""

    total_runs: str = Field(..., description="Pre-formatted sum of in-range command counts")
    items: list[CommandEntry]


class PersonalUsageResponse(BaseModel):
    """Response envelope for GET /api/personal-usage/{user_id} (ADR-0009, SHP-02-FR-1..FR-6).

    `cards` is exactly 4 entries, order-locked: Sessions, Total time, Total tokens, Avg
    tokens/session -- a to-date aggregate, unbounded by `range`. `daily_tokens` and
    `commands` are range-scoped. No `program_id` anywhere -- "my usage" is a cross-program
    aggregate by contract (`docs/requirements/api.md#personal-usage-api`).
    """

    cards: list[PersonalUsageCard]
    daily_tokens: DailyTokenSeries
    commands: CommandsPanel
