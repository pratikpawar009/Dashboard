"""Tests for `scripts/mint_ingest_token.py` -- ING-01-TC-01, TC-02, TC-03,
TC-04, TC-05, TC-23 (ING-01-FR-1, FR-2; ADR-0006 SS1, SS2).

Every test invokes the mint script as a real subprocess (matching each TC's
own `steps`) rather than importing and calling `_mint`/`_run` in-process --
this exercises the actual CLI entry point (argparse's own usage-error path,
the stdout-exactly-once contract, the process exit code) the way an operator
or CI job would run it.

`DATABASE_URL` is force-set to `test_database_url` (the disposable DB the
`migrated_db`/`test_session` fixtures already point at) in every subprocess
call, regardless of the parent process's own environment. An unset
`DATABASE_URL` resolves to `Settings.database_url`'s default -- the live
native dev database, `localhost:5432/dashboard` -- so never drop this
override (AF-01: a worker minted a real row into it exactly this way while
implementing T-02). `migrated_db` is requested in every test, including
TC-03's argparse-failure path, so the schema is always present for
consistency even where the script never reaches the database.

Invoked via `sys.executable` -- the interpreter of the venv already running
this test session (the same one `uv run python ...` resolves to) -- rather
than shelling out to a bare `uv` binary, which is not reliably on `PATH` in
every environment this suite runs in.

Token format is ADR-0006 SS1's `hrn_pat_` + 64 lowercase hex chars (32 CSPRNG
bytes via `secrets.token_hex(32)`) -- this supersedes story ING-01 AC-1's
48-char/24-byte figure; `TOKEN_RE` below asserts 64, never 48.
"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import IngestToken
from tests.conftest import API_ROOT, AlembicRunner

TOKEN_RE = re.compile(r"^hrn_pat_[0-9a-f]{64}$")
MINT_SCRIPT = API_ROOT / "scripts" / "mint_ingest_token.py"


def _run_mint_argv(argv: list[str], *, test_database_url: str) -> subprocess.CompletedProcess[str]:
    """Run the mint script as a subprocess with the given raw argv.

    See module docstring for the `DATABASE_URL` override and `sys.executable`
    invocation rationale.
    """
    env = {**os.environ, "DATABASE_URL": test_database_url}
    return subprocess.run(
        [sys.executable, str(MINT_SCRIPT), *argv],
        cwd=API_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


def _run_mint(
    *, label: str, user_email: str, program_ids: str, test_database_url: str
) -> subprocess.CompletedProcess[str]:
    """Run the mint script with the standard `--label/--user-email/--program-ids` triple."""
    return _run_mint_argv(
        ["--label", label, "--user-email", user_email, "--program-ids", program_ids],
        test_database_url=test_database_url,
    )


def _token_lines(stdout: str) -> list[str]:
    return [line for line in stdout.splitlines() if TOKEN_RE.match(line)]


async def _row_count_for_label(test_session: AsyncSession, label: str) -> int:
    result = await test_session.execute(
        sa.select(sa.func.count()).select_from(IngestToken).where(IngestToken.label == label)
    )
    return result.scalar_one()


async def _fetch_rows_for_label(test_session: AsyncSession, label: str) -> list[IngestToken]:
    result = await test_session.execute(sa.select(IngestToken).where(IngestToken.label == label))
    return list(result.scalars().all())


# -----------------------------------------------------------------------------
# ING-01-TC-01 (FR-1) -- raw token format, exactly one stdout line, exit 0.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mint_prints_raw_token_matching_format_exactly_once_tc01(
    migrated_db: AlembicRunner, test_database_url: str
) -> None:
    result = _run_mint(
        label="ci-automation-token",
        user_email="ci-bot@example.com",
        program_ids="prog-1,prog-2",
        test_database_url=test_database_url,
    )

    lines = _token_lines(result.stdout)
    assert len(lines) == 1, f"expected exactly one raw token line, got {lines!r}"
    assert result.returncode == 0, result.stderr


# -----------------------------------------------------------------------------
# ING-01-TC-02 (FR-2) -- exactly one new ingest_tokens row, exit 0.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mint_writes_exactly_one_row_and_exits_zero_tc02(
    migrated_db: AlembicRunner, test_session: AsyncSession, test_database_url: str
) -> None:
    label = "ci-row-check"
    assert await _row_count_for_label(test_session, label) == 0

    result = _run_mint(
        label=label,
        user_email="ci-bot@example.com",
        program_ids="prog-3",
        test_database_url=test_database_url,
    )

    assert result.returncode == 0, result.stderr
    assert await _row_count_for_label(test_session, label) == 1


# -----------------------------------------------------------------------------
# ING-01-TC-03 (FR-2) -- missing --label, then missing --user-email: non-zero
# exit, no stdout token, no DB write, across both invocations.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mint_missing_required_argument_exits_nonzero_with_no_side_effects_tc03(
    migrated_db: AlembicRunner, test_session: AsyncSession, test_database_url: str
) -> None:
    label = "ci-arg-fail"

    missing_label = _run_mint_argv(
        ["--user-email", "ci-bot@example.com", "--program-ids", "prog-1"],
        test_database_url=test_database_url,
    )
    missing_user_email = _run_mint_argv(
        ["--label", label, "--program-ids", "prog-1"],
        test_database_url=test_database_url,
    )

    for result in (missing_label, missing_user_email):
        assert result.returncode != 0
        assert not _token_lines(result.stdout)

    assert await _row_count_for_label(test_session, label) == 0


# -----------------------------------------------------------------------------
# ING-01-TC-04 (FR-1) -- persisted row: token_hash, label, user_email,
# allowed_program_ids, expires_at/revoked_at null.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_minted_row_persists_expected_fields_tc04(
    migrated_db: AlembicRunner, test_session: AsyncSession, test_database_url: str
) -> None:
    label = "ci-storage-check"
    result = _run_mint(
        label=label,
        user_email="storage-check@example.com",
        program_ids="prog-4,prog-5",
        test_database_url=test_database_url,
    )
    assert result.returncode == 0, result.stderr
    lines = _token_lines(result.stdout)
    assert len(lines) == 1
    raw_token = lines[0]
    expected_hash = hashlib.sha256(raw_token.encode()).hexdigest()

    rows = await _fetch_rows_for_label(test_session, label)
    assert len(rows) == 1
    row = rows[0]

    assert row.token_hash == expected_hash
    assert row.label == label
    assert row.user_email == "storage-check@example.com"
    assert row.allowed_program_ids == ["prog-4", "prog-5"]
    assert row.expires_at is None
    assert row.revoked_at is None


# -----------------------------------------------------------------------------
# ING-01-TC-05 (AC-2) -- no persisted column and no captured subprocess output
# other than the single designed stdout line carries the raw token.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_column_or_subprocess_output_leaks_raw_token_tc05(
    migrated_db: AlembicRunner, test_session: AsyncSession, test_database_url: str
) -> None:
    """The mint script emits no `logging`-module output on this path (no
    `import logging`, only `print`) -- its subprocess stdout/stderr IS the
    full captured-output surface a log-capture fixture would otherwise
    attach to. `stderr` must be empty (success path) and contain no trace of
    the raw token; `stdout` must contain the raw token in exactly the one
    designed line (TC-01's own assertion), never elsewhere.
    """
    label = "ci-no-leak-check"
    result = _run_mint(
        label=label,
        user_email="no-leak@example.com",
        program_ids="prog-6",
        test_database_url=test_database_url,
    )
    assert result.returncode == 0, result.stderr
    lines = _token_lines(result.stdout)
    assert len(lines) == 1
    raw_token = lines[0]

    assert result.stderr == ""
    assert raw_token not in result.stderr
    assert result.stdout.count(raw_token) == 1

    rows = await _fetch_rows_for_label(test_session, label)
    assert len(rows) == 1
    row = rows[0]

    assert row.token_hash != raw_token
    column_values = [
        row.id,
        row.token_hash,
        row.label,
        row.user_email,
        str(row.allowed_program_ids),
        str(row.expires_at),
        str(row.revoked_at),
    ]
    for value in column_values:
        assert raw_token not in value, f"raw token leaked into column value: {value!r}"


# -----------------------------------------------------------------------------
# ING-01-TC-23 (ADR-0006 SS1, NFR-security) -- two mints, identical args,
# produce distinct raw tokens and distinct token_hash values.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_two_mints_produce_distinct_tokens_and_hashes_tc23(
    migrated_db: AlembicRunner, test_session: AsyncSession, test_database_url: str
) -> None:
    label = "ci-entropy-check"

    first = _run_mint(
        label=label,
        user_email="entropy@example.com",
        program_ids="prog-17",
        test_database_url=test_database_url,
    )
    second = _run_mint(
        label=label,
        user_email="entropy@example.com",
        program_ids="prog-17",
        test_database_url=test_database_url,
    )

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr

    first_lines = _token_lines(first.stdout)
    second_lines = _token_lines(second.stdout)
    assert len(first_lines) == 1
    assert len(second_lines) == 1
    first_token, second_token = first_lines[0], second_lines[0]

    assert first_token != second_token

    rows = await _fetch_rows_for_label(test_session, label)
    assert len(rows) == 2
    hashes = {row.token_hash for row in rows}
    assert len(hashes) == 2
    assert hashes == {
        hashlib.sha256(first_token.encode()).hexdigest(),
        hashlib.sha256(second_token.encode()).hexdigest(),
    }


# -----------------------------------------------------------------------------
# Fix-directive regression (F-1, code-review MEDIUM, not an ING-01-TC id) --
# `--program-ids` trims whitespace around each comma-separated element and
# drops elements left empty after trimming; a *supplied* value collapsing to
# zero usable elements is a usage error, not allow-all (DECISIONS.md D-05).
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mint_trims_whitespace_around_program_ids_regression_f1(
    migrated_db: AlembicRunner, test_session: AsyncSession, test_database_url: str
) -> None:
    """Regression for F-1: `--program-ids "a, b"` previously stored
    `["a", " b"]` -- the untrimmed second element could never match an
    exact-string `program_id` lookup at `_check_program_scope`, silently
    under-permitting the token. Must store `["a", "b"]`.
    """
    label = "f1-trim-whitespace"
    result = _run_mint(
        label=label,
        user_email="f1-trim@example.com",
        program_ids="a, b",
        test_database_url=test_database_url,
    )
    assert result.returncode == 0, result.stderr

    rows = await _fetch_rows_for_label(test_session, label)
    assert len(rows) == 1
    assert rows[0].allowed_program_ids == ["a", "b"]


@pytest.mark.asyncio
async def test_mint_drops_empty_elements_between_commas_regression_f1(
    migrated_db: AlembicRunner, test_session: AsyncSession, test_database_url: str
) -> None:
    """`"a,,b"` drops the empty middle element -> `["a", "b"]`, not
    `["a", "", "b"]`."""
    label = "f1-drop-empty-element"
    result = _run_mint(
        label=label,
        user_email="f1-drop-empty@example.com",
        program_ids="a,,b",
        test_database_url=test_database_url,
    )
    assert result.returncode == 0, result.stderr

    rows = await _fetch_rows_for_label(test_session, label)
    assert len(rows) == 1
    assert rows[0].allowed_program_ids == ["a", "b"]


@pytest.mark.asyncio
async def test_mint_wildcard_still_produces_single_element_list_regression_f1(
    migrated_db: AlembicRunner, test_session: AsyncSession, test_database_url: str
) -> None:
    """`--program-ids "*"` must still produce exactly `["*"]` -- trimming
    must not disturb the literal wildcard."""
    label = "f1-wildcard-unaffected"
    result = _run_mint(
        label=label,
        user_email="f1-wildcard@example.com",
        program_ids="*",
        test_database_url=test_database_url,
    )
    assert result.returncode == 0, result.stderr

    rows = await _fetch_rows_for_label(test_session, label)
    assert len(rows) == 1
    assert rows[0].allowed_program_ids == ["*"]


@pytest.mark.asyncio
async def test_mint_program_ids_collapsing_to_empty_after_trim_is_usage_error_regression_f1(
    migrated_db: AlembicRunner, test_session: AsyncSession, test_database_url: str
) -> None:
    """A *supplied* `--program-ids` that collapses to zero usable elements
    after trimming (whitespace-only, or comma(s) alone) must NOT silently
    become `[]` (allow-all, DECISIONS.md D-04's omission-only meaning) --
    that would be a new fail-open path this fix must not introduce.
    Instead: non-zero exit, no DB row, nothing on stdout -- across both a
    whitespace-only value and a comma-only value.
    """
    for bad_value, label in ((" ", "f1-whitespace-only"), (",", "f1-comma-only")):
        result = _run_mint(
            label=label,
            user_email="f1-usage-error@example.com",
            program_ids=bad_value,
            test_database_url=test_database_url,
        )
        assert result.returncode != 0, (bad_value, result.stdout, result.stderr)
        assert result.stdout == ""
        assert await _row_count_for_label(test_session, label) == 0


# -----------------------------------------------------------------------------
# Fix-directive regression (F-2, validation CRITICAL / code-review CRITICAL,
# not an ING-01-TC id in this suite -- tracked as ING-01-TC-25 in the test-case
# manifest) -- a *supplied* `--program-ids ""` (e.g. via `--program-ids
# "$IDS"` with an unset/empty shell variable) must be treated the same as any
# other supplied-but-unusable value: a usage error, never the allow-all `[]`
# default (DECISIONS.md D-05a). Before this fix, `if not raw:` could not
# distinguish `raw is None` (flag omitted) from `raw == ""` (flag supplied
# empty), so `--program-ids ""` minted a fully unscoped, never-expiring token.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mint_supplied_empty_program_ids_is_usage_error_regression_f2(
    migrated_db: AlembicRunner, test_session: AsyncSession, test_database_url: str
) -> None:
    """Regression for F-2: `--program-ids ""` (explicitly supplied empty
    string) previously fell through the `if not raw: return []` guard and
    minted an allow-all token -- exit 0, token on stdout, a committed row
    with `allowed_program_ids=[]`. Must now behave exactly like `" "` or
    `","`: non-zero exit, no DB row, nothing on stdout.
    """
    label = "f2-supplied-empty-string"
    result = _run_mint(
        label=label,
        user_email="f2-usage-error@example.com",
        program_ids="",
        test_database_url=test_database_url,
    )
    assert result.returncode != 0, (result.stdout, result.stderr)
    assert result.stdout == ""
    assert await _row_count_for_label(test_session, label) == 0
