# ING-10 — Questions

Mid-stream questions workers could not resolve alone. Bundled by `/arh-clarify ING-10`.

### Q-01: `ingest_manifest()` needs a 4th param (`token_label`) — RESOLVED from the contracts, no PO round needed

**Raised by**: T-06 · **status**: resolved 2026-09-08 by the orchestrator

T-06 asked whether T-07 should resolve the ingest token and pass `token.label` through, or whether
log emission should move to the router instead. Three authoritative sources answer it together, so
this did not need a PO clarification round:

1. `REQUIREMENTS.md` **FR-2** pins `ingest_manifest_write`'s Required field set as
   `{program_id, token_label, identity_written, roster_received, roster_valid, roster_created,
   roster_updated, roster_removed, roster_rejected, duration_ms}` — `token_label` is mandatory.
2. `PLAN.md`'s **T-06** title assigns the "PII-safe log event" to the *service*, not the router.
3. Only **T-07**'s router carries `Depends(get_ingest_token)`, so `IngestToken.label` is
   resolvable there and nowhere else.

**Resolution**: T-07 resolves the token and passes `token.label` into `ingest_manifest()`. Moving
emission to the router was rejected because it contradicts PLAN's own task split (2), and dropping
`token_label` was rejected because it contradicts FR-2 (1). The 4th parameter is the only shape
that satisfies all three.

Recorded as a plan deviation in `FLAGS.md` **AF-08**, since PLAN § Module hierarchy pins a
three-parameter signature.
