"""Unit tests for `app/core/ingest_kind.py` -- ING-02-TC (F-15 / T-10),
FR-7 envelope-kind allowlist.

`accept_envelope_kind()` is the request-tier check the ING-02 router calls
before any writes: a False return aborts the whole request with 400 and
zero writes (ING-02-AC-4). ING-02 ships `_ACCEPTED_KINDS = {"activity"}`;
ING-03 will extend the frozenset with `"artifacts"` by editing the same
module (DECISIONS.md D-03 / research C-6). Asserting `"artifacts" is
False` here pins today's contract and will visibly fail when ING-03 lands,
which is the intended cross-story handshake.
"""

import pytest

from app.core.ingest_kind import _ACCEPTED_KINDS, accept_envelope_kind


def test_accept_envelope_kind_activity_true() -> None:
    assert accept_envelope_kind("activity") is True


def test_accept_envelope_kind_artifacts_false_until_ing03() -> None:
    assert accept_envelope_kind("artifacts") is False


def test_accept_envelope_kind_empty_string_false() -> None:
    assert accept_envelope_kind("") is False


def test_accept_envelope_kind_unknown_false() -> None:
    assert accept_envelope_kind("nonsense") is False


@pytest.mark.parametrize("kind", sorted(_ACCEPTED_KINDS))
def test_accept_envelope_kind_covers_every_accepted_kind(kind: str) -> None:
    assert accept_envelope_kind(kind) is True
