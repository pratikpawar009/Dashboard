"""Unit tests for `app/core/ingest_kind.py` -- ING-02-TC (F-15 / T-10) +
ING-03-FR-1 (T-01).

`accept_envelope_kind()` is the request-tier check the generic
`POST /api/ingest/{kind}` router (ADR-0013) calls before any writes:
a False return aborts the whole request with 400 and zero writes
(ING-02-AC-4 / ING-03-AC-1). ING-03 extended `_ACCEPTED_KINDS` from
`{"activity"}` to `{"activity", "artifacts"}` in the same PR that
introduced the generic router (D-01). Asserting `"artifacts" is True`
here pins today's contract; the parametrised sweep of
`_ACCEPTED_KINDS` exercises both entries and fails loudly on an
accidental revert to the singleton set.
"""

import pytest

from app.core.ingest_kind import _ACCEPTED_KINDS, accept_envelope_kind


def test_accept_envelope_kind_activity_true() -> None:
    assert accept_envelope_kind("activity") is True


def test_accept_envelope_kind_artifacts_true() -> None:
    assert accept_envelope_kind("artifacts") is True


def test_accept_envelope_kind_empty_string_false() -> None:
    assert accept_envelope_kind("") is False


def test_accept_envelope_kind_unknown_false() -> None:
    assert accept_envelope_kind("nonsense") is False


@pytest.mark.parametrize("kind", sorted(_ACCEPTED_KINDS))
def test_accept_envelope_kind_covers_every_accepted_kind(kind: str) -> None:
    assert accept_envelope_kind(kind) is True
