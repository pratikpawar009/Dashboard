"""Ingest bearer-token auth dependency (ADR-0006; DECISIONS.md D-01).

`get_ingest_token()` is the machine-facing counterpart to `app/core/auth.py`'s
`get_current_user()` — it resolves a caller-presented
`Authorization: Bearer <token>` header against `ingest_tokens.token_hash`
(a SHA-256 hex digest lookup on the table's unique index) and enforces
ING-01-FR-3's program-scope check inside the dependency call itself,
returning the resolved `IngestToken` row directly as the principal — no
separate DTO (D-01); the model already carries every field a caller needs.

Structural isolation (FR-6): this module never imports `app/core/auth.py`
and shares no code with it — its own `HTTPBearer(auto_error=False)`
instance is separate from `auth.py`'s `_http_bearer`. Ingest routes depend
on `get_ingest_token()` only; user-session routes depend on
`get_current_user()` only — no route declares both.

DELIBERATE, NOT A BUG: an empty `allowed_program_ids` list means allow-all
(ADR-0006 §3 / § Consequences) — the most permissive credential this story
can issue (every program, forever) is also the one produced by omitting
`--program-ids` at mint. This inverts the fail-closed default used
elsewhere in this codebase (AUTH-01's dev-bypass allow-list, AUTH-03's
persona gating, AUTH-04's resolver-failure 403) and is an accepted risk
recorded in ADR-0006 § Consequences, not an oversight to "fix" by flipping
the empty-list default to deny-all.
"""

import hashlib
import logging
from datetime import UTC, datetime

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.models.ingestion import IngestToken

logger = logging.getLogger(__name__)

# Own instance — never import `app.core.auth`'s `_http_bearer` (FR-6).
_http_bearer = HTTPBearer(auto_error=False)


async def get_ingest_token(
    program_id: str,
    credentials: HTTPAuthorizationCredentials | None = Depends(_http_bearer),
    session: AsyncSession = Depends(get_db),
) -> IngestToken:
    """Resolve and authorize a bearer ingest token (ING-01-FR-3/FR-4).

    `program_id` is an ordinary function parameter FastAPI resolves the
    same way it resolves any path/query parameter of that name on the
    route declaring `Depends(get_ingest_token)` (ING-02's concern to wire)
    — never read off the resolved `IngestToken` row.

    `HTTPBearer(auto_error=False)`'s own `__call__` already treats a
    missing `Authorization` header and a non-Bearer scheme identically —
    both resolve `credentials` to `None` — so a single `is None` check
    covers both halves of FR-4's first table row.

    Denial branches (FR-4, exact): 401 `missing` (no header / non-Bearer),
    401 `unknown` (no matching hash), 401 `revoked`, 401 `expired`, 403
    `scope`. Every branch logs once via `_log_ingest_token_auth_failed`
    before raising; a pass logs nothing (FR-5: denial-only event).
    """
    if credentials is None:
        _log_ingest_token_auth_failed(token_id=None, reason="missing", program_id=program_id)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing")

    token_hash = hashlib.sha256(credentials.credentials.encode()).hexdigest()
    result = await session.execute(select(IngestToken).where(IngestToken.token_hash == token_hash))
    token = result.scalar_one_or_none()

    if token is None:
        _log_ingest_token_auth_failed(token_id=None, reason="unknown", program_id=program_id)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unknown")

    if token.revoked_at is not None:
        _log_ingest_token_auth_failed(token_id=token.id, reason="revoked", program_id=program_id)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="revoked")

    if token.expires_at is not None and token.expires_at <= datetime.now(UTC):
        _log_ingest_token_auth_failed(token_id=token.id, reason="expired", program_id=program_id)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="expired")

    if not _check_program_scope(token.allowed_program_ids, program_id):
        _log_ingest_token_auth_failed(token_id=token.id, reason="scope", program_id=program_id)
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="scope")

    return token


# -----------------------------------------------------------------------------
# Private helpers — no downstream contract, internal to this module only.
# -----------------------------------------------------------------------------


def _check_program_scope(allowed_program_ids: list[str], program_id: str) -> bool:
    """ADR-0006 §3 / ING-01-FR-3 check order — stop at first pass.

    1. Empty list -> unscoped, allow-all (deliberate, see module docstring).
    2. `"*"` present -> explicit wildcard, allow-all.
    3. `program_id` in the list -> exact string membership, no UUID parsing.
    4. Else -> deny.
    """
    if not allowed_program_ids:
        return True
    if "*" in allowed_program_ids:
        return True
    return program_id in allowed_program_ids


def _log_ingest_token_auth_failed(*, token_id: str | None, reason: str, program_id: str) -> None:
    """Emit `ingest_token_auth_failed` at INFO, once per denial, never on
    success (FR-5). `token_id` is `IngestToken.id` when a row resolved,
    `None` when it did not (`reason` in `missing|unknown`).

    Payload carries exactly FR-5's four required keys — `timestamp` is
    supplied by `JSONFormatter`'s own first-class payload field
    (`app/core/logging.py`), computed before it merges `extra` and never
    overwritten by an extra value of the same name, so it is not repeated
    here. This helper supplies the other three: `token_id`, `reason`,
    `program_id`. Never `user_email`, the raw token, or `token_hash`
    (`.claude/rules/security-baseline.md`).
    """
    logger.info(
        "ingest_token_auth_failed",
        extra={"token_id": token_id, "reason": reason, "program_id": program_id},
    )
