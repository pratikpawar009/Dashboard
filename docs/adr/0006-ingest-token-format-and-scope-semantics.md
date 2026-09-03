# ADR-0006: Ingest token format, scope semantics, and lifetime

- Status: Accepted
- Date: 2026-08-31
- Deciders: pratik.pawar@apexon.com

## Context

ING-01 introduces the system's **second authentication path**: a machine-facing bearer credential
for ingestion, alongside AUTH-01's Keycloak user JWTs. Seven stories consume the
`ingest-token-auth` contract it produces (ING-02, ING-03, ING-07 directly; ING-04, ING-05, ING-06,
ING-09 transitively), so the shape settled here propagates widely and is expensive to change once
tokens have been minted in any environment.

Research (`docs/research/ING-01.md`, 76/100, GO-WITH-CONDITIONS) left three clarifications open, and
a fourth conflict surfaced while resolving them. All four are settled below.

BED-01 already ships the `ingest_tokens` table (`app/models/ingestion.py`), whose shape constrains
two of these decisions: `allowed_program_ids` is `ARRAY(String) NOT NULL` with no sibling column, and
`expires_at` is nullable. The model also carries an explicit invariant that it must never gain a
column capable of storing a raw token.

## Decision

### 1. Token entropy: 32 random bytes, not 24

`.claude/rules/security-baseline.md` § Auth tokens is binding on `**/*.py` and requires
**CSPRNG ≥ 32 bytes**. The `ingest-token-auth` contract and story AC-1 both specified 24 bytes
(48 hex chars). The rule wins: tokens are `hrn_pat_` + **32** CSPRNG bytes, rendered as **64 hex
characters**, generated via `secrets.token_hex(32)`.

24 bytes (192 bits) is not weak in practice — this change is about complying with the project's own
binding rule rather than carrying a standing exception into every security review. It is free now:
no code exists and no token has been minted. Once ING-02/03/07 ship, it becomes a breaking change to
every issued credential.

**Story `docs/stories/ING-01.md` AC-1 is superseded on the byte count.** The story file is not
edited — it is `Status: Validated`, and re-opening forces re-validation (the same disposition
ADR-0005 applied to AUTH-04's AC-5). This ADR and `docs/requirements/auth.md` are authoritative.

Storage is unchanged: only the SHA-256 hex digest is persisted, in `token_hash` (unique). The raw
token is printed exactly once at mint and never stored or logged.

### 2. Mint surface: stdlib `argparse` in a standalone script

`services/api/scripts/mint_ingest_token.py`, invoked as
`uv run python scripts/mint_ingest_token.py`. AC-1 already fixed the surface as a CLI; this settles
the framework.

Neither `typer` nor `click` is currently a dependency, and the command takes four arguments. Using
the standard library adds **no new dependency** and behaves identically inside and outside the
container image — which matters here, because the Dockerfile builds with `uv sync --no-dev`, the
exact mechanism that broke `httpx` at container boot (flag AF-03) when a needed package sat in the
dev group. This does not preclude ING-06 adopting a richer CLI framework for the manual ingester;
that is that story's decision.

### 3. Program scope: wildcard is `["*"]`; an **empty array means allow-all**

The wildcard lives inside the array as the single element `["*"]` — the schema leaves no
alternative, since `allowed_program_ids` is a non-nullable array with no sibling column.

The authorization check is:

```
if not token.allowed_program_ids:          # empty  -> unscoped, allow-all
    pass
elif "*" in token.allowed_program_ids:      # explicit wildcard
    pass
elif target_program_id in token.allowed_program_ids:
    pass
else:
    raise 403
```

**An empty `allowed_program_ids` grants access to every program.** This was chosen deliberately over
the fail-closed alternative (empty = deny-all).

### 4. Token lifetime: `expires_at` defaults to null — tokens do not expire

Minting without an explicit expiry produces a credential valid until it is revoked via `revoked_at`.
Story AC-3 already contemplates this state (`expires_at is null or in the future`). Revocation, not
expiry, is the primary containment mechanism.

## Consequences

- Positive: the token format now satisfies the project's binding entropy rule with no standing
  exception. The mint path adds no dependency and no Docker-image divergence. Scope and lifetime
  semantics are written down before seven downstream stories build on them, rather than being
  inferred differently by each.
- Negative, and the reason decisions 3 and 4 are recorded here rather than in a research doc:
  **they compound.** The most permissive credential the system can issue — every program, forever —
  is also the one produced by omitting a flag at mint time, and it stays valid until a human notices
  and revokes it. This inverts the fail-closed posture established elsewhere in this codebase:
  AUTH-01's dev-bypass allow-list, AUTH-03's fail-closed persona gating, and AUTH-04's 403 on
  resolver failure all default to denial. Ingest tokens deliberately do not.
  - Nothing in the system currently monitors token age, warns before expiry, or reports unscoped
    tokens. There is no compensating detection control today.
  - `/arh-security-review` is expected to raise both. They are **accepted decisions, not
    oversights** — this ADR is the record.
- Reversible? Mixed. The mint surface (2) and scope logic (3) are mechanical: one script and one
  function, no persisted representation. The lifetime default (4) is a one-line change, though
  already-minted non-expiring tokens would need backfilling. The **token format (1) is the costly
  one** — reversing it after ING-02/03/07 ship invalidates every issued credential, which is
  precisely why it is settled now.

## Flagged gaps

- No operational control exists for token inventory: nothing lists active tokens, flags unscoped
  ones, or reports age. Given decisions 3 and 4, such a control is the natural mitigation and is
  **not** in ING-01's scope — carried forward as a candidate follow-up story.
- `security-baseline.md` § Ownership also says "Return HTTP 404, never 403" for foreign-owned
  resources, while ING-01 AC-5 requires **403** for an out-of-scope program. These do not actually
  conflict: that rule targets IDOR/enumeration on per-resource reads, whereas the ingest caller
  already knows the `program_id` it supplied, so 403 leaks nothing it did not provide. Recorded here
  so security review does not have to re-derive it.
