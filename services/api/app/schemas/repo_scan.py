"""Response schema for `POST /api/admin/scan-repos` (ING-07-FR-1, DECISIONS.md D-01).

The response shape is pinned at the story level by ING-07 D-01 as a PRD-scoped
assumption: `docs/requirements/api.md#admin-scan-api` specifies endpoint / auth /
effect only, no response body. TC-12 asserts the runtime body and the exported
OpenAPI component both match this schema verbatim -- exactly three keys, int /
int / ISO-8601-UTC-with-`Z`-suffix -- and rejects any non-`Z` offset like
`+00:00` or `+05:30`. The field-level serializer converts any tz-aware input to
UTC before formatting, so a value stored with `DateTime(timezone=True)` on
`org_summary_rollup` (F-02 upsert site) round-trips cleanly to the wire format.
"""

from datetime import UTC, datetime

from pydantic import BaseModel, Field, field_serializer


class ScanReposResponse(BaseModel):
    """Response body for `POST /api/admin/scan-repos` (ING-07-FR-1, D-01).

    The three fields mirror the columns the service layer upserts on
    `org_summary_rollup` per request (FR-4). Exported as the OpenAPI component
    `ScanReposResponse` -- TC-12 asserts the component name and property set.
    """

    repos_total: int = Field(
        ..., description="Total repos observed in the org during the scan"
    )
    repos_with_harness_installed: int = Field(
        ...,
        description=(
            "Repos whose default branch carries `.harness/program.yaml` "
            "(GET /contents returned 200, per D-03)"
        ),
    )
    as_of_timestamp: datetime = Field(
        ...,
        description="Scan completion instant, serialised as ISO-8601 UTC with `Z` suffix",
    )

    @field_serializer("as_of_timestamp")
    def _serialize_as_of_timestamp(self, value: datetime) -> str:
        # TC-12 rejects `+00:00` and any non-UTC offset; force UTC + `Z` suffix.
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
