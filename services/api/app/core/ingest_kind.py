"""Envelope-`kind` allowlist for `/api/ingest/*` (ING-02-FR-7 / ING-03-FR-1;
DECISIONS.md ING-02 D-03 + ING-03 D-01 / ADR-0013).

One owning module for the envelope-tier `kind` vocabulary, on the same
single-module-owns-vocabulary model as `app.core.role_map`. ING-02 shipped
`{"activity"}`; ING-03 extends the frozenset with `"artifacts"` in this
same file rather than declaring its own module -- research risk #8 (MED)
is that four `kind` vocabularies drift apart if each story ships its own
allowlist.

Under ADR-0013 the generic router `POST /api/ingest/{kind}` validates
this path-param against `_ACCEPTED_KINDS` BEFORE bearer auth: a
non-accepted kind aborts the whole request with 400 and zero writes
(ING-02-AC-4 / ING-03-AC-1). A regex constraint on the router's
`{kind}` path-param would fork the vocabulary from this frozenset and
re-introduce the drift ING-02 D-03 was fighting -- the router therefore
carries no path-param regex.

Row-level `usage_events.kind` is stored verbatim per ING-02 Q-02 and
never touches this module -- this module is envelope-tier only.
"""

# ING-03 extended this to `frozenset({"activity", "artifacts"})`. Do not
# add a kind here without a story that owns the downstream handling --
# an accepted-but-unhandled kind is a silent 500 in the router.
_ACCEPTED_KINDS: frozenset[str] = frozenset({"activity", "artifacts"})


def accept_envelope_kind(kind: str) -> bool:
    """Return True iff `kind` is an accepted envelope kind.

    Empty string and any unknown value return False; the router turns
    False into a 400 abort with zero writes (FR-7 / AC-4). Never raises.
    """
    return kind in _ACCEPTED_KINDS
