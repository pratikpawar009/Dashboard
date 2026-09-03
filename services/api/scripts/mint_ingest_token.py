"""Mint a bearer credential for the `ingest-token-auth` contract (ING-01-FR-1/FR-2).

Standalone CLI, stdlib `argparse` only (ADR-0006 §2) — run as:

    uv run python scripts/mint_ingest_token.py --label X --user-email Y [--program-ids a,b]

from `services/api/`. Not a route: this script's authority model is local shell
access plus `DATABASE_URL` credentials (ADR-0006 §2); no HTTP mint surface exists.

Token format (ADR-0006 §1): `hrn_pat_` + `secrets.token_hex(32)` — 32 CSPRNG
bytes rendered as 64 lowercase hex characters. Only `hashlib.sha256(raw).hexdigest()`
is ever persisted, into `IngestToken.token_hash` (see the SECURITY CRITICAL
invariant on that model, `app/models/ingestion.py`) — the raw token is printed
to stdout exactly once and is never stored, logged, or written anywhere else.

Session lifecycle (DECISIONS.md D-02): this script runs outside any HTTP
request, so it cannot use the `get_db()` FastAPI dependency. It opens its own
`SessionLocal` session per invocation, commits first, and prints the raw token
only after that commit succeeds — any failure (bad argument, unreachable
database, commit error) leaves nothing on stdout and no row committed.

`--program-ids` is optional (DECISIONS.md D-04): omitted entirely produces
`allowed_program_ids=[]`, which per ADR-0006 §3 is allow-all, not deny-all.
This permissiveness-by-omission is a deliberate, accepted decision (ADR-0006
§ Consequences) — not a bug to special-case away.

When `--program-ids` IS supplied, each comma-separated element is
whitespace-trimmed and empty elements are dropped (DECISIONS.md D-05), so
`"a, b"` stores `["a", "b"]`, not `["a", " b"]`. A supplied value that has
no usable elements left after trimming (`" "`, `","`) is a **usage error**,
not allow-all — see `_parse_program_ids` docstring for why the empty-list
result must stay reachable only by omitting the flag.
"""

import argparse
import asyncio
import hashlib
import secrets
import sys

from app.core.db import SessionLocal
from app.models import IngestToken


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="mint_ingest_token.py",
        description="Mint an ingest bearer token and print it once to stdout.",
    )
    parser.add_argument("--label", required=True, help="Human-readable label for this token.")
    parser.add_argument(
        "--user-email", required=True, help="Email of the operator this token is issued to."
    )
    parser.add_argument(
        "--program-ids",
        required=False,
        default=None,
        help=(
            "Comma-separated program ids (whitespace around each id is trimmed, "
            "empty elements dropped), or the literal '*' for wildcard scope. "
            "Omitted entirely means allow-all (ADR-0006 §3); a supplied value "
            "with no usable ids left after trimming is a usage error."
        ),
    )
    return parser.parse_args(argv)


def _parse_program_ids(raw: str | None) -> list[str]:
    """Parse `--program-ids` into the stored list (DECISIONS.md D-05, amended by D-05a).

    Splits on `,`, trims surrounding whitespace from each element, and
    drops elements that are empty after trimming — `"a, ,b"` -> `["a", "b"]`;
    `"*"` -> `["*"]` (the literal wildcard, unaffected by trimming).

    Two empty-result cases are deliberately NOT the same:

    - `raw is None` (flag omitted entirely) -> returns `[]`, ADR-0006 §3 /
      DECISIONS.md D-04's allow-all default.
    - `raw` is supplied — including `""` — but collapses to zero usable
      elements after trimming (e.g. `""`, `" "`, or `","`) -> raises
      `ValueError`. D-05a: a *supplied* empty string is a usage error on
      the same terms as a whitespace/punctuation-only value, not allow-all
      — the realistic trigger is `--program-ids "$IDS"` with an unset or
      empty shell variable. Silently returning `[]` for any of these would
      let that typo/unset-var case produce the same unscoped,
      never-expiring, allow-all credential as the deliberate omission case
      — the fail-open path D-05a closes. The caller surfaces this as a
      usage error: non-zero exit, message on stderr, no DB write, no token
      printed.
    """
    if raw is None:
        return []
    parsed = [item.strip() for item in raw.split(",") if item.strip()]
    if not parsed:
        raise ValueError(
            "--program-ids was supplied but had no usable ids after trimming "
            'whitespace (e.g. "", " ", or ","); omit the flag entirely for '
            'allow-all, or supply at least one id or "*"'
        )
    return parsed


async def _mint(label: str, user_email: str, allowed_program_ids: list[str]) -> str:
    raw_token = "hrn_pat_" + secrets.token_hex(32)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()

    async with SessionLocal() as session:
        session.add(
            IngestToken(
                token_hash=token_hash,
                label=label,
                user_email=user_email,
                allowed_program_ids=allowed_program_ids,
                expires_at=None,
                revoked_at=None,
            )
        )
        await session.commit()

    return raw_token


async def _run(argv: list[str]) -> int:
    args = _parse_args(argv)

    try:
        allowed_program_ids = _parse_program_ids(args.program_ids)
        raw_token = await _mint(args.label, args.user_email, allowed_program_ids)
    except Exception as exc:  # noqa: BLE001 — CLI boundary: any mint/usage failure must exit 1, print nothing to stdout
        print(str(exc), file=sys.stderr)
        return 1

    print(raw_token)
    return 0


def main() -> int:
    return asyncio.run(_run(sys.argv[1:]))


if __name__ == "__main__":
    sys.exit(main())
