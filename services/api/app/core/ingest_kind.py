"""Envelope-`kind` allowlist for `/api/ingest/*` (ING-02-FR-7; DECISIONS.md D-03).

One owning module for the envelope-tier `kind` vocabulary, on the same
single-module-owns-vocabulary model as `app.core.role_map`. ING-02 ships
`{"activity"}`; ING-03 will extend the frozenset with `"artifacts"` by
editing this same file rather than declaring its own module -- research
risk #8 (MED) is that four `kind` vocabularies drift apart if each story
ships its own allowlist.

Row-level `usage_events.kind` is stored verbatim per Q-02 and never
touches this module -- this module is envelope-tier only. Callers use
the accept-check at the request tier: a non-accepted kind aborts the
whole request with 400 and zero writes (ING-02-AC-4, FR-7).
"""

# ING-03 extends this to `frozenset({"activity", "artifacts"})` in its own
# scope. Do not add a kind here without a story that owns the downstream
# handling -- an accepted-but-unhandled kind is a silent 500 in the router.
_ACCEPTED_KINDS: frozenset[str] = frozenset({"activity"})


def accept_envelope_kind(kind: str) -> bool:
    """Return True iff `kind` is an accepted envelope kind.

    Empty string and any unknown value return False; the router turns
    False into a 400 abort with zero writes (FR-7 / AC-4). Never raises.
    """
    return kind in _ACCEPTED_KINDS
