"""Unit tests for `app/schemas/ingest_artifacts.py` (ING-03 T-06 / F-12).

Traces ING-03-AC-4 (non-canonical type key rejected at the request tier
before any DB call) and ING-03-FR-2 (canonical-type enum enforcement,
case-sensitive, closed vocabulary).

`ArtifactCountsIn.model_validate(...)` is the ONLY place the canonical
type-set is enforced against `counts` keys; the service assumes it has
already been called. Any drift here would cause the service to see
non-canonical keys and either fail Postgres constraints or silently
persist them -- neither acceptable.

`_CANONICAL_ARTIFACT_TYPES` is imported and re-exported literally by
this test so an accidental widening of the set flips the parametrised
positive expectations and lands on the negative-case assertions
simultaneously.
"""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.schemas.ingest_artifacts import (
    _CANONICAL_ARTIFACT_TYPES,
    ArtifactCountsIn,
    IngestArtifactsResponse,
)

_VALID_AS_OF = datetime(2026, 9, 13, 10, 0, 0, tzinfo=UTC)


def _envelope(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "program_id": "prog-ing03-a",
        "kind": "artifacts",
        "counts": {"prd": 3},
        "as_of": _VALID_AS_OF.isoformat(),
    }
    body.update(overrides)
    return body


@pytest.mark.parametrize("canonical_type", sorted(_CANONICAL_ARTIFACT_TYPES))
def test_each_canonical_type_alone_is_accepted(canonical_type: str) -> None:
    model = ArtifactCountsIn.model_validate(_envelope(counts={canonical_type: 1}))
    assert model.counts == {canonical_type: 1}


def test_combined_five_canonical_types_accepted() -> None:
    counts = {t: idx + 1 for idx, t in enumerate(sorted(_CANONICAL_ARTIFACT_TYPES))}
    model = ArtifactCountsIn.model_validate(_envelope(counts=counts))
    assert set(model.counts) == _CANONICAL_ARTIFACT_TYPES


def test_unknown_key_rejected_with_400_shape() -> None:
    with pytest.raises(ValidationError) as excinfo:
        ArtifactCountsIn.model_validate(_envelope(counts={"design_doc": 2}))
    assert "unknown_canonical_type" in str(excinfo.value)


def test_case_sensitive_upper_case_rejected() -> None:
    with pytest.raises(ValidationError) as excinfo:
        ArtifactCountsIn.model_validate(_envelope(counts={"PRD": 2}))
    assert "unknown_canonical_type" in str(excinfo.value)


def test_empty_string_key_rejected() -> None:
    with pytest.raises(ValidationError):
        ArtifactCountsIn.model_validate(_envelope(counts={"": 1}))


def test_non_int_value_rejected() -> None:
    with pytest.raises(ValidationError):
        ArtifactCountsIn.model_validate(_envelope(counts={"prd": "three"}))


@pytest.mark.parametrize(
    "missing_field", ["program_id", "kind", "counts", "as_of"]
)
def test_missing_required_field_rejected(missing_field: str) -> None:
    body = _envelope()
    body.pop(missing_field)
    with pytest.raises(ValidationError):
        ArtifactCountsIn.model_validate(body)


def test_kind_must_be_literal_artifacts() -> None:
    with pytest.raises(ValidationError):
        ArtifactCountsIn.model_validate(_envelope(kind="activity"))


def test_empty_program_id_rejected() -> None:
    with pytest.raises(ValidationError):
        ArtifactCountsIn.model_validate(_envelope(program_id=""))


def test_response_shape_defaults() -> None:
    """D-02 / Q-02: `IngestArtifactsResponse` is
    `{rows_received, rows_upserted, rejections: list}`; `rejections`
    defaults to `[]` (symmetric with the ING-02 shape, empty on the
    artifacts happy path)."""
    resp = IngestArtifactsResponse(rows_received=2, rows_upserted=2)
    assert resp.rows_received == 2
    assert resp.rows_upserted == 2
    assert resp.rejections == []
