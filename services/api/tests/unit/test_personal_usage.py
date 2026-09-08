"""Contract + coverage-gap tests for `GET /api/personal-usage/{user_id}`
(`app/api/personal_usage.py`) -- SHP-02-TC-01 (`docs/test-cases/SHP-02.json`)
plus the disclosed SHP-02-FR-5 coverage gap (zero-session average).

Mirrors `tests/unit/test_overview.py`'s scaffold (`build_app`/
`async_client_for`/`migrated_db`/`test_session` from `tests/conftest.py`,
`get_db` dependency override) and `tests/perf/test_overview_perf.py`'s
`POST /auth/dev-bypass` token-minting pattern. This endpoint's only RBAC
call on a self-view request is `individual_usage_visibility`'s self path
(`app/core/rbac.py`), which short-circuits before any persona resolution --
so, like `test_overview.py`, no persona-resolver stub is installed.

Dev-bypass gotcha this file works around: `POST /auth/dev-bypass` always
mints a fresh `uuid4()` as the token's `sub` claim (`app/auth/dev_bypass.py`)
-- `DevBypassRequest` has no field to override it. Since
`individual_usage_visibility`'s self path requires the path's `user_id` to
equal the token's own `sub`, this file mints the token FIRST, decodes its
`sub` back out (without verifying the signature -- the token was just minted
in-process, there is nothing to distrust), and seeds every row under that
actual id rather than the SHP-02-TC-01 fixture's illustrative
`usr-shp02-tc01` label.

T-08 owns this file's scaffold and covers TC-01 (full envelope contract) plus
the zero-session `compute_average` branch. T-09 (RBAC 403 / range
default-invalid) reuses this same file's scaffold, per tasks.json's shared-
file predecessor edge.
"""

from __future__ import annotations

import base64
import json
import logging
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import AbstractAsyncContextManager, contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import rbac
from app.core.db import get_db
from app.core.logging import JSONFormatter
from app.core.persona_resolver import PersonaResolver
from app.models.ingestion import UsageEvent
from app.models.rollup import UserSessions
from app.services import personal_usage as personal_usage_module
from tests.conftest import AlembicRunner

AsyncClientFactory = Callable[..., AbstractAsyncContextManager[AsyncClient]]

# Shared fixture program id -- personal-usage is a cross-program aggregate by
# contract (ADR-0009), so its value is never asserted on; it only needs to
# satisfy the NOT NULL columns below.
_FIXTURE_PROGRAM_ID = "prog-shp02-tc-fixture"


# -----------------------------------------------------------------------------
# App + DB-override scaffold. See module docstring for why no persona-resolver
# override is needed here (mirrors test_overview.py).
# -----------------------------------------------------------------------------


def _db_override(session: AsyncSession) -> Callable[[], AsyncIterator[AsyncSession]]:
    async def _get_db() -> AsyncIterator[AsyncSession]:
        yield session

    return _get_db


def _build_personal_usage_app(
    build_app: Callable[..., FastAPI], test_session: AsyncSession, **settings_overrides: Any
) -> FastAPI:
    """Real `create_app()` (`build_app` fixture, D-07) wired for HTTP-level
    testing against a live DB. Hermetic default settings already set
    `environment="test"`, which is in `NON_PRODUCTION_ENVIRONMENTS` -- so
    `/auth/dev-bypass` is registered and its tokens verify without any OIDC
    config (`app/auth/jwks.py::JwksCache.get_signing_key`'s dev-bypass
    branch is fully independent of `settings.oidc_issuer`/`oidc_client_id`)."""
    app = build_app(**settings_overrides)
    app.dependency_overrides[get_db] = _db_override(test_session)
    return app


def _decode_unverified_claims(token: str) -> dict[str, Any]:
    """Read a JWT's payload claims WITHOUT verifying its signature.

    Mirrors `app.core.auth._peek_kid`'s own decode-without-verify technique
    (same base64/JSON segment decode), applied to the payload segment
    instead of the header -- see module docstring for why this file needs
    to read a dev-bypass token's `sub` back out.
    """
    payload_segment = token.split(".")[1]
    padding = "=" * (-len(payload_segment) % 4)
    return json.loads(base64.urlsafe_b64decode(payload_segment + padding))


async def _mint_dev_bypass_token(client: AsyncClient, *, role: str) -> tuple[str, str]:
    """`POST /auth/dev-bypass` and return `(access_token, user_id)`, where
    `user_id` is the token's own `sub` claim (see module docstring)."""
    resp = await client.post("/auth/dev-bypass", json={"role": role})
    assert resp.status_code == 200, resp.text
    token = str(resp.json()["access_token"])
    return token, str(_decode_unverified_claims(token)["sub"])


# -----------------------------------------------------------------------------
# Seeding helpers.
# -----------------------------------------------------------------------------


def _user_session_row(
    *, user_id: str, days_ago: int, tokens: int, duration_seconds: int, now: datetime
) -> dict[str, Any]:
    """One `user_sessions` row with every NOT NULL column
    (`app/models/rollup.py::UserSessions`) explicitly set."""
    return {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "program_id": _FIXTURE_PROGRAM_ID,
        "session_identifier": f"sess-{user_id}-{days_ago}-{uuid.uuid4()}",
        "name": f"session {days_ago}d ago",
        "started_at": now - timedelta(days=days_ago),
        "duration_seconds": duration_seconds,
        "tokens": tokens,
    }


def _usage_event_row(*, user_id: str, command: str, ts: datetime, idx: int) -> dict[str, Any]:
    """One `usage_events` row with every NOT NULL column
    (`app/models/ingestion.py::UsageEvent`) explicitly set. `session_id` is
    unique per row so the `(program_id, session_id, cmd_ts)` unique
    constraint can never collide across this fixture's rows."""
    return {
        "id": str(uuid.uuid4()),
        "program_id": _FIXTURE_PROGRAM_ID,
        "ts": ts,
        "cmd_ts": ts,
        "user": user_id,
        "session_id": f"sess-evt-{user_id}-{idx}",
        "command": command,
        "duration_seconds": 1,
        "outcome": "success",
        "total": 0,
    }


def _assert_no_key_recursive(obj: Any, forbidden_key: str, path: str = "$") -> None:
    """Recursively assert `forbidden_key` never appears at any level of
    `obj` -- a shallow, cards-only check would miss a leak nested inside
    `daily_tokens`/`commands`."""
    if isinstance(obj, dict):
        assert forbidden_key not in obj, f"found forbidden key {forbidden_key!r} at {path}"
        for key, value in obj.items():
            _assert_no_key_recursive(value, forbidden_key, f"{path}.{key}")
    elif isinstance(obj, list):
        for index, item in enumerate(obj):
            _assert_no_key_recursive(item, forbidden_key, f"{path}[{index}]")


# -----------------------------------------------------------------------------
# SHP-02-TC-01 -- full envelope contract: to-date cards + ranged daily token
# series + ranged commands panel.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_personal_usage_full_envelope_contract_tc01(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """SHP-02-TC-01: 7 seeded `user_sessions` rows (6 within the last 30
    days, 1 forty days old) and `usage_events` rows ({plan: 40, implement:
    10, review: 10} in-range, {deploy: 5} forty days old); a self-view GET
    with `range=30d` returns exactly 4 order-locked cards (5 keys each, no
    `delta` anywhere) computed to-date across all 7 sessions, a 30-point
    zero-padded daily token series scoped to the 6 in-range sessions, and a
    commands panel (`total_runs=60`) whose `barStyle` is max-of-range and
    excludes the out-of-range `deploy` events. No `program_id` anywhere."""
    app = _build_personal_usage_app(build_app, test_session)

    async with async_client_for(app) as client:
        token, user_id = await _mint_dev_bypass_token(client, role="developer")

        now = datetime.now(UTC)
        session_specs = [
            (40, 6000, 7200),
            (29, 3000, 3000),
            (20, 3000, 3600),
            (10, 2000, 1200),
            (5, 2000, 2400),
            (1, 1500, 1800),
            (0, 500, 600),
        ]
        session_rows = [
            _user_session_row(
                user_id=user_id, days_ago=d, tokens=tokens, duration_seconds=dur, now=now
            )
            for d, tokens, dur in session_specs
        ]
        await test_session.execute(sa.insert(UserSessions), session_rows)

        event_rows: list[dict[str, Any]] = []
        idx = 0
        in_range_ts = now - timedelta(days=2)
        for command, count in (("plan", 40), ("implement", 10), ("review", 10)):
            for _ in range(count):
                event_rows.append(
                    _usage_event_row(user_id=user_id, command=command, ts=in_range_ts, idx=idx)
                )
                idx += 1
        out_of_range_ts = now - timedelta(days=40)
        for _ in range(5):
            event_rows.append(
                _usage_event_row(user_id=user_id, command="deploy", ts=out_of_range_ts, idx=idx)
            )
            idx += 1
        await test_session.execute(sa.insert(UsageEvent), event_rows)
        await test_session.commit()

        resp = await client.get(
            f"/api/personal-usage/{user_id}?range=30d",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()

    # Full envelope shape -- no program_id anywhere (cross-program aggregate).
    assert set(body.keys()) == {"cards", "daily_tokens", "commands"}
    _assert_no_key_recursive(body, "program_id")
    _assert_no_key_recursive(body, "delta")

    # Cards: exactly 4, order-locked, exactly 5 keys each. Labels are read
    # back from the producer's own presentation constant, not retyped here
    # (ADR-0009's "Avg tokens / session" spacing is deliberate, FLAGS.md AF-04).
    cards = body["cards"]
    assert len(cards) == 4
    expected_labels = [label for (_, label, _, _) in personal_usage_module._CARD_PRESENTATION]
    for card, expected_label in zip(cards, expected_labels, strict=True):
        assert set(card.keys()) == {"glyph", "value", "label", "iconBg", "iconColor"}
        assert card["label"] == expected_label
        for key in ("glyph", "iconBg", "iconColor"):
            assert isinstance(card[key], str) and card[key] != "", f"{key} must be non-empty"

    # To-date aggregate over all 7 sessions (including the 40-day-old one),
    # NOT scoped to range=30d.
    values_by_label = {card["label"]: card["value"] for card in cards}
    assert values_by_label[expected_labels[0]] == "7"  # Sessions
    assert values_by_label[expected_labels[1]] == "5h 30m"  # Total time
    assert values_by_label[expected_labels[2]] == "18.0K"  # Total tokens
    assert values_by_label[expected_labels[3]] == "2.6K"  # Avg tokens/session

    # Daily token series: exactly 30 zero-padded points, oldest-to-newest.
    points = body["daily_tokens"]["points"]
    assert len(points) == 30
    expected_by_days_ago = {0: "500", 1: "1.5K", 5: "2.0K", 10: "2.0K", 20: "3.0K", 29: "3.0K"}
    for days_ago, point in enumerate(reversed(points)):
        expected_value = expected_by_days_ago.get(days_ago, "0")
        assert point["value"] == expected_value, (
            f"days_ago={days_ago}: expected {expected_value!r}, got {point['value']!r} "
            f"(date={point['date']!r})"
        )

    # The 40-day-old session's 6000 tokens are excluded from both the daily
    # points above and these range-scoped totals.
    assert body["daily_tokens"]["period_total"] == "12.0K"
    assert body["daily_tokens"]["avg_per_day"] == "400"

    # Commands panel: range-scoped, excludes the out-of-range 'deploy' events.
    # Order is not asserted -- ADR-0009 does not lock commands[] order the
    # way it locks cards[] order, and GROUP BY gives no ordering guarantee.
    commands = body["commands"]
    assert commands["total_runs"] == "60"
    items = commands["items"]
    assert len(items) == 3
    items_by_command = {item["command"]: item for item in items}
    assert set(items_by_command) == {"plan", "implement", "review"}
    assert items_by_command["plan"]["count"] == 40
    assert items_by_command["plan"]["barStyle"] == "width: 100%;"
    assert items_by_command["implement"]["count"] == 10
    assert items_by_command["implement"]["barStyle"] == "width: 25%;"
    assert items_by_command["review"]["count"] == 10
    assert items_by_command["review"]["barStyle"] == "width: 25%;"


# -----------------------------------------------------------------------------
# SHP-02-FR-5 coverage gap -- a zero-session user gets a well-formed 200, not
# null/error/missing, with the Avg tokens/session card at "0".
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_personal_usage_zero_sessions_average_is_zero_not_none(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """Closes the disclosed SHP-02-FR-5 coverage gap
    (`docs/test-cases/SHP-02.json` `coverage_audit`): a user with ZERO
    `user_sessions` rows gets HTTP 200 with a fully-shaped envelope and the
    Avg tokens/session card at `"0"` (`format_number(0.0)`) -- proving
    `compute_average`'s `0.0`-never-`None` branch end-to-end, not a null,
    missing-card, or error response."""
    app = _build_personal_usage_app(build_app, test_session)

    async with async_client_for(app) as client:
        token, user_id = await _mint_dev_bypass_token(client, role="developer")
        # No `user_sessions` rows seeded for this user_id -- sessions == 0.
        resp = await client.get(
            f"/api/personal-usage/{user_id}?range=30d",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body.keys()) == {"cards", "daily_tokens", "commands"}

    cards = body["cards"]
    assert len(cards) == 4
    avg_label = personal_usage_module._CARD_PRESENTATION[3][1]
    avg_card = next((card for card in cards if card["label"] == avg_label), None)
    assert avg_card is not None, f"no card labeled {avg_label!r} found in {cards}"
    assert avg_card["value"] == "0"


# -----------------------------------------------------------------------------
# Stub persona resolver (D-06's `rbac.configure()` seam) -- mirrors
# `test_rbac.py`/`test_programs.py`'s own stub, duplicated locally per each
# file's independent-ownership precedent (see those files' module
# docstrings). `individual_usage_visibility`'s non-self path resolves
# persona through `app.core.rbac`'s own module-global seam (`rbac.
# configure()`), NOT `request.app.state.persona_resolver` (a separate,
# router-local seam `test_programs.py`'s `/api/programs` reads directly) --
# so TC-02's cross-user denial needs `rbac.configure()`, not an `app.state`
# swap.
# -----------------------------------------------------------------------------


class _StubPersonaResolver:
    def __init__(self, *, mapping: dict[str, str]) -> None:
        self._mapping = mapping

    async def resolve(self, role: str) -> str:
        return self._mapping[role]


# -----------------------------------------------------------------------------
# Log capture -- mirrors `test_rbac.py`'s own `_RecordCapturingHandler`/
# `_capture_logger` idiom, duplicated locally (each test file is
# independently owned, per that file's own precedent). `individual_usage_
# visibility` logs `individual_view_denied` through the real, named
# `app.core.rbac` logger on every denial (`app/core/rbac.py`).
# -----------------------------------------------------------------------------


class _RecordCapturingHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@contextmanager
def _capture_rbac_logger(level: int = logging.INFO) -> Iterator[list[logging.LogRecord]]:
    logger = logging.getLogger("app.core.rbac")
    original_disabled = logger.disabled
    original_propagate = logger.propagate
    original_level = logger.level
    logger.disabled = False
    logger.propagate = False
    logger.setLevel(level)
    handler = _RecordCapturingHandler()
    logger.addHandler(handler)
    try:
        yield handler.records
    finally:
        logger.removeHandler(handler)
        logger.disabled = original_disabled
        logger.propagate = original_propagate
        logger.setLevel(original_level)


# -----------------------------------------------------------------------------
# SHP-02-TC-02 -- cross-user request denied with a bare 403 and a PII-free,
# usage-data-free individual_view_denied log record.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_personal_usage_cross_user_denied_bare_403_tc02(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """SHP-02-TC-02: a signed-in non-cio developer persona requesting a
    DIFFERENT user's personal usage gets a bare HTTP 403 (no data body) and
    exactly one `individual_view_denied` log record carrying no PII and no
    usage-data field.

    Stubs `rbac.configure()` with an identity `developer` mapping (D-06
    seam) so `individual_usage_visibility`'s non-self path denies via its
    persona-comparison branch -- restored in a `finally` so this test can
    never leak a stub persona resolver into a later test/file.
    """
    app = _build_personal_usage_app(build_app, test_session)

    original_persona_resolver = rbac._persona_resolver
    rbac.configure(cast(PersonaResolver, _StubPersonaResolver(mapping={"developer": "developer"})))
    try:
        async with async_client_for(app) as client:
            token, _requester_user_id = await _mint_dev_bypass_token(client, role="developer")
            target_user_id = f"usr-shp02-tc02-target-{uuid.uuid4()}"

            with _capture_rbac_logger() as records:
                resp = await client.get(
                    f"/api/personal-usage/{target_user_id}?range=30d",
                    headers={"Authorization": f"Bearer {token}"},
                )
    finally:
        rbac._persona_resolver = original_persona_resolver

    assert resp.status_code == 403
    assert resp.json() == {"error": {"code": "http_403", "message": "Forbidden", "details": None}}

    events = [r for r in records if r.getMessage() == "individual_view_denied"]
    assert len(events) == 1

    payload = json.loads(JSONFormatter().format(events[0]))
    assert payload["outcome"] == "denied"

    # No PII -- concrete allowlist-by-exclusion, not a vague property.
    for pii_field in (
        "email",
        "name",
        "groups",
        "persona",
        "token",
        "access_token",
        "authorization",
    ):
        assert pii_field not in payload

    # No usage-data field -- concrete allowlist-by-exclusion.
    for usage_field in (
        "cards",
        "daily_tokens",
        "commands",
        "sessions",
        "tokens",
        "duration_seconds",
        "value",
        "count",
        "barStyle",
        "program_id",
    ):
        assert usage_field not in payload

    # Exact allowlist, mirroring test_rbac.py's TC-22 precedent for this same event.
    assert set(payload.keys()) == {
        "timestamp",
        "level",
        "logger",
        "message",
        "user_id",
        "target_user_id",
        "outcome",
    }


# -----------------------------------------------------------------------------
# SHP-02-AC-5 coverage gap -- an omitted `range` query param defaults to 30d
# (`docs/test-cases/SHP-02.json` `coverage_audit`; PRD § Approvals).
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_personal_usage_omitted_range_defaults_to_30d_ac5(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """Closes the disclosed SHP-02-AC-5 coverage gap: a self-view GET with NO
    `range` query parameter at all is computed as if `range=30d` -- proven
    via `daily_tokens.points` having exactly 30 entries (D-02's
    `_range_with_default` wrapper), not just a bare 200."""
    app = _build_personal_usage_app(build_app, test_session)

    async with async_client_for(app) as client:
        token, user_id = await _mint_dev_bypass_token(client, role="developer")
        resp = await client.get(
            f"/api/personal-usage/{user_id}",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["daily_tokens"]["points"]) == 30


# -----------------------------------------------------------------------------
# SHP-02-FR-6 coverage gap -- an out-of-set `range` value 400s with the same
# envelope every other validate_range() consumer produces (D-02).
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_personal_usage_invalid_range_returns_400_fr6(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """Closes the disclosed SHP-02-FR-6 coverage gap: `range=1d` (outside
    `{7d,30d,90d}`) 400s byte-for-byte identically to every other
    `validate_range()` consumer (`test_range_validation.py`'s own
    `EXPECTED_ERROR_BODY`), proving D-02's `_range_with_default` wrapper
    delegates the membership check/rejection body unedited."""
    app = _build_personal_usage_app(build_app, test_session)

    async with async_client_for(app) as client:
        token, user_id = await _mint_dev_bypass_token(client, role="developer")
        resp = await client.get(
            f"/api/personal-usage/{user_id}?range=1d",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp.status_code == 400
    assert resp.json() == {
        "error": {"code": "http_400", "message": "invalid_range", "details": None}
    }


# -----------------------------------------------------------------------------
# SHP-02-FR-3 -- the commands panel is a descending ranking, not grouping order.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_commands_panel_is_ordered_by_count_descending_fr3(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """`commands.items` comes back ranked highest-count-first.

    The mockup renders this panel as a descending bar ranking and `barStyle`
    is already computed against the range's max count, so an unordered list
    puts the longest bar somewhere in the middle. The grouped query carries no
    inherent order, so without an explicit `ORDER BY` the rows arrive in
    whatever order grouping happens to produce.

    Commands are seeded deliberately out of rank order (`alpha` lowest first,
    `delta` highest last) so a response that merely echoed insertion or
    grouping order would fail this assertion.
    """
    app = _build_personal_usage_app(build_app, test_session)

    async with async_client_for(app) as client:
        token, user_id = await _mint_dev_bypass_token(client, role="developer")

        now = datetime.now(UTC)
        in_range_ts = now - timedelta(days=2)
        event_rows: list[dict[str, Any]] = []
        idx = 0
        for command, count in (("alpha", 3), ("bravo", 11), ("charlie", 7), ("delta", 19)):
            for _ in range(count):
                event_rows.append(
                    _usage_event_row(user_id=user_id, command=command, ts=in_range_ts, idx=idx)
                )
                idx += 1
        await test_session.execute(sa.insert(UsageEvent), event_rows)
        await test_session.commit()

        resp = await client.get(
            f"/api/personal-usage/{user_id}?range=30d",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp.status_code == 200, resp.text
    items = resp.json()["commands"]["items"]

    assert [i["command"] for i in items] == ["delta", "bravo", "charlie", "alpha"]
    assert [i["count"] for i in items] == [19, 11, 7, 3]

    counts = [i["count"] for i in items]
    assert counts == sorted(counts, reverse=True)
    # The widest bar is therefore the first row, which is the whole point.
    assert items[0]["barStyle"] == "width: 100%;"
