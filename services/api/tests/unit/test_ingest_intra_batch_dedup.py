"""Unit tests for intra-batch dedup in `app/services/activity_ingest.ingest_files`
(ING-02 F-13 / T-09 -- FR-3 / C-2, research risk R-05 HIGH).

Contract (`docs/features/ING-02/DATA-DESIGN.md` § 5, REQUIREMENTS.md FR-3):
rows sharing an `(program_id, session_id, cmd_ts)` key are deduplicated in
Python BEFORE the chunked upsert, last-wins -- matching `ON CONFLICT DO
UPDATE` semantics. The DROPPED indices land in `rejected[]` with reason
`"intra_batch_duplicate"`; the WINNER's index is never rejected. Without this
step Postgres raises `CardinalityViolation: ON CONFLICT DO UPDATE cannot
affect row a second time` and aborts the entire batch (C-4 prevention).

Test slice: T-04 shipped dedup INLINE inside `ingest_files()` rather than
exposing the `_dedup_intra_batch()` helper PLAN.md § 2 sketched (flagged to
the orchestrator as an observation, kind: risky-pattern). With no importable
helper this file drives `ingest_files()` end-to-end but stubs the DB seam:
a fake `AsyncSession` records `execute()`/`commit()` calls without I/O, and
`rebuild_program_rollups` is monkeypatched to a no-op. The dedup loop
executes verbatim; the write path is out of scope (integration T-13/T-14).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest

from app.services import activity_ingest
from app.services.rollup_rebuild import RebuildResult

_PROGRAM_ID = "prog-a"
_TS = "2026-09-11T10:00:00Z"


class _FakeExecuteResult:
    """Stand-in for `sqlalchemy` `Result` -- only the pre-read `tuples().all()`
    path in `ingest_files` reads the return value; the upsert `execute()`
    calls discard it. Returning an empty list means every deduped row is
    counted as `inserted`, which is fine here: the dedup outputs (winners +
    rejections) are what this suite asserts."""

    def tuples(self) -> _FakeExecuteResult:
        return self

    def all(self) -> list[tuple[str, datetime]]:
        return []


class _FakeSession:
    """Minimal `AsyncSession` seam. Records nothing beyond what's needed to
    keep `ingest_files` running past its DB-touching lines."""

    async def execute(self, _stmt: Any) -> _FakeExecuteResult:
        return _FakeExecuteResult()

    async def commit(self) -> None:
        return None


async def _noop_rebuild(_session: Any, program_id: str) -> RebuildResult:
    return RebuildResult(
        scope="program", program_id=program_id, duration_ms=0, event_count=0
    )


@pytest.fixture(autouse=True)
def _stub_program_rebuild(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test here calls `ingest_files`; the program rebuild is not the
    subject under test and is stubbed at the module boundary."""
    monkeypatch.setattr(activity_ingest, "rebuild_program_rollups", _noop_rebuild)


@pytest.fixture
def captured_chunks(monkeypatch: pytest.MonkeyPatch) -> list[list[dict[str, Any]]]:
    """Intercept `pg_insert(UsageEvent).values(chunk)` and record the chunk.
    This is how a test observes what the dedup step FORWARDS to the upsert:
    the response envelope only carries counts + rejections; the survivor's
    payload only becomes observable at the insert boundary."""
    chunks: list[list[dict[str, Any]]] = []

    class _FakeInsert:
        def values(self, chunk: list[dict[str, Any]]) -> _FakeInsert:
            chunks.append(chunk)
            return self

        def on_conflict_do_update(self, **_kwargs: Any) -> _FakeInsert:
            return self

        class _Excluded:
            def __getattr__(self, _name: str) -> None:
                return None

        @property
        def excluded(self) -> _FakeInsert._Excluded:
            return _FakeInsert._Excluded()

    def _fake_pg_insert(_model: Any) -> _FakeInsert:
        return _FakeInsert()

    monkeypatch.setattr(activity_ingest, "pg_insert", _fake_pg_insert)
    return chunks


def _row(
    *,
    session_id: str,
    cmd_ts: str,
    program_id: str = _PROGRAM_ID,
    input_token: int | None = None,
    user: str = "u@example.com",
) -> dict[str, Any]:
    """Build a raw wire-shaped row. Only required fields plus the wire-alias
    `input_token` (mapped to `input_tokens`) so a test can distinguish two
    otherwise-identical rows by payload."""
    row: dict[str, Any] = {
        "program_id": program_id,
        "ts": _TS,
        "cmd_ts": cmd_ts,
        "user": user,
        "session_id": session_id,
        "command": "chat",
        "duration_s": 1,
        "outcome": "success",
        "total": 100,
    }
    if input_token is not None:
        row["input_token"] = input_token
    return row


async def _run(rows: list[dict[str, Any]]) -> tuple[Any, Any]:
    """Drive `ingest_files` and return `(response, on_org_rebuild_calls)`."""
    calls: list[None] = []

    def _on_org_rebuild() -> None:
        calls.append(None)

    response = await activity_ingest.ingest_files(
        db=_FakeSession(),  # type: ignore[arg-type]
        program_id=_PROGRAM_ID,
        payload={"rows": rows},
        token_label="test-token",
        on_org_rebuild=_on_org_rebuild,
    )
    return response, calls


@pytest.mark.asyncio
async def test_no_duplicates_all_kept(
    captured_chunks: list[list[dict[str, Any]]],
) -> None:
    """Happy path: 3 rows with distinct keys -> all 3 kept, zero rejections."""
    rows = [
        _row(session_id="s1", cmd_ts="2026-09-11T10:00:00Z"),
        _row(session_id="s2", cmd_ts="2026-09-11T10:00:01Z"),
        _row(session_id="s3", cmd_ts="2026-09-11T10:00:02Z"),
    ]

    response, _calls = await _run(rows)

    assert response.received == 3
    assert response.valid == 3
    assert response.rejected == []
    assert len(captured_chunks) == 1
    assert [r["session_id"] for r in captured_chunks[0]] == ["s1", "s2", "s3"]


@pytest.mark.asyncio
async def test_two_row_collision_last_wins(
    captured_chunks: list[list[dict[str, Any]]],
) -> None:
    """A(idx=0) and B(idx=1) share a key; B has a different `input_token`.
    After dedup only B survives; A's index lands in `rejected[]` with
    reason `intra_batch_duplicate` (never B's). B's payload -- not A's --
    is what actually reaches the upsert path."""
    rows = [
        _row(session_id="s1", cmd_ts="2026-09-11T10:00:00Z", input_token=10),
        _row(session_id="s1", cmd_ts="2026-09-11T10:00:00Z", input_token=99),
    ]

    response, _calls = await _run(rows)

    assert response.received == 2
    assert response.valid == 1
    assert len(response.rejected) == 1
    dropped = response.rejected[0]
    assert dropped.index == 0
    assert dropped.reason == "intra_batch_duplicate"

    # Winner payload assertion: B's `input_tokens=99` is what got forwarded to
    # the insert, not A's `input_tokens=10`. Column-name (`input_tokens`), not
    # wire-alias (`input_token`), because `model_dump(by_alias=False)` emits
    # column names.
    assert len(captured_chunks) == 1
    assert len(captured_chunks[0]) == 1
    assert captured_chunks[0][0]["input_tokens"] == 99


@pytest.mark.asyncio
async def test_three_way_collision_only_last_survives(
    captured_chunks: list[list[dict[str, Any]]],
) -> None:
    """A(idx=0), B(idx=1), C(idx=2) same key -> only C kept; both 0 and 1
    rejected with `intra_batch_duplicate`. C's payload is what reaches the
    insert."""
    rows = [
        _row(session_id="s1", cmd_ts="2026-09-11T10:00:00Z", input_token=1),
        _row(session_id="s1", cmd_ts="2026-09-11T10:00:00Z", input_token=2),
        _row(session_id="s1", cmd_ts="2026-09-11T10:00:00Z", input_token=3),
    ]

    response, _calls = await _run(rows)

    assert response.received == 3
    assert response.valid == 1
    dropped_indices = sorted(r.index for r in response.rejected)
    assert dropped_indices == [0, 1]
    assert {r.reason for r in response.rejected} == {"intra_batch_duplicate"}
    assert len(captured_chunks[0]) == 1
    assert captured_chunks[0][0]["input_tokens"] == 3


@pytest.mark.asyncio
async def test_mixed_duplicates_and_singletons_preserve_order(
    captured_chunks: list[list[dict[str, Any]]],
) -> None:
    """Mixed batch:
      idx 0: singleton s0
      idx 1: dup key K (first)
      idx 2: singleton s2
      idx 3: dup key K (LAST -- winner)
      idx 4: singleton s4

    Only index 1 is rejected (the earlier dup); idx 3 wins and the three
    singletons survive. The order the pipeline emits them in follows Python
    3.7+ dict insertion order: the winner keeps the position of its key's
    first insertion (idx 1), so the surviving-row order forwarded to the
    upsert is [s0, k-winner, s2, s4]."""
    key_cmd_ts = "2026-09-11T10:00:05Z"
    rows = [
        _row(session_id="s0", cmd_ts="2026-09-11T10:00:00Z"),
        _row(session_id="k",  cmd_ts=key_cmd_ts, input_token=1),
        _row(session_id="s2", cmd_ts="2026-09-11T10:00:02Z"),
        _row(session_id="k",  cmd_ts=key_cmd_ts, input_token=99),
        _row(session_id="s4", cmd_ts="2026-09-11T10:00:04Z"),
    ]

    response, _calls = await _run(rows)

    assert response.received == 5
    assert response.valid == 4
    assert [r.index for r in response.rejected] == [1]
    assert response.rejected[0].reason == "intra_batch_duplicate"

    forwarded = captured_chunks[0]
    assert [r["session_id"] for r in forwarded] == ["s0", "k", "s2", "s4"]
    # The `k` slot carries the LAST-seen payload (input_tokens=99), not the
    # first-seen (input_tokens=1) -- last-wins on collision.
    assert forwarded[1]["input_tokens"] == 99


@pytest.mark.asyncio
async def test_different_program_id_is_not_a_duplicate() -> None:
    """`(session_id, cmd_ts)` alone is NOT the dedup key -- `program_id`
    participates. `ingest_files` filters non-envelope `program_id` rows FIRST
    (as `program_id_mismatch`, DATA-DESIGN.md § 3), which is itself the
    observable proof that rows with a different `program_id` are never merged
    into the dedup map: they never reach it. The alternative -- a
    `(session_id, cmd_ts)`-only key -- would surface here as a mismatched
    row collapsed under the envelope key rather than a separately-classified
    rejection.

    This test pins that behaviour: the second row bears a different
    `program_id`, comes back as `program_id_mismatch` (index preserved,
    row content NOT embedded per FR-8 / C-7), and does NOT displace the
    first row's `(program_id, session_id, cmd_ts)` slot in the dedup map."""
    cmd_ts = "2026-09-11T10:00:00Z"
    rows = [
        _row(session_id="s1", cmd_ts=cmd_ts, program_id=_PROGRAM_ID),
        _row(session_id="s1", cmd_ts=cmd_ts, program_id="prog-other"),
    ]

    response, _calls = await _run(rows)

    assert response.received == 2
    assert response.valid == 1
    assert [r.reason for r in response.rejected] == ["program_id_mismatch"]
    assert response.rejected[0].index == 1
