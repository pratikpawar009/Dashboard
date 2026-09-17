"""Route-level tests for `GET /api/overview/program-detail/{program_id}/team/
{member_id}/usage` (`app/api/overview.py::get_program_team_member_usage`) --
PGD-05-TC-09, TC-10, TC-11, TC-12, TC-13, TC-18 (`docs/test-cases/PGD-05.json`).

This is the popup's backend sibling route (DECISIONS.md D-03/D-04): the gate is
`member_in_program_visibility` (`app/core/rbac.py`) -- program_visibility first,
then self-or-cio -- distinct from and never delegating to `personal_usage.py`'s
own `individual_usage_visibility` gate on `GET /api/personal-usage/{user_id}`.
On a pass, the route calls SHP-02's own service functions directly
(`fetch_card_totals`/`fetch_daily_token_series`/`fetch_commands_breakdown`) and
returns `PersonalUsageResponse` verbatim -- no PGD-05-specific reshaping.

Mirrors `tests/unit/test_program_team_route.py`'s scaffold (`build_app`/
`async_client_for`/`migrated_db`/`test_session` from `tests/conftest.py`,
`POST /auth/dev-bypass` bearer tokens) and `tests/unit/test_personal_usage.py`'s
dev-bypass-token-then-decode-sub idiom (needed here too, since the self path
requires the path's `member_id` to equal the requester's own `sub`) plus its
`_RecordCapturingHandler`/`_capture_rbac_logger` log-capture idiom, duplicated
locally per each file's own independent-ownership precedent.

Self-witnessing log assertions (per this project's known Alembic
`fileConfig(disable_existing_loggers=True)` trap -- `migrated_db` runs Alembic
migrations before any test body executes, and Alembic's `fileConfig` call can
silently disable every already-configured logger, including `app.core.rbac`'s,
which would make a naive "no log emitted" assertion pass vacuously even when
logging is globally dead). Every test in this file that asserts on captured
`member_view_denied` records also asserts, in the SAME capture window, that a
DIFFERENT known-good rbac event (`rbac_check_org_access`, emitted on both
outcomes by `org_access`) is capturable -- so if logging were dead, the
positive-control assertion would fail first and loudly, rather than the
denial-log assertion silently passing on an empty list. See
`_capture_rbac_logger`/`_assert_logging_alive` below.
"""

from __future__ import annotations

import base64
import json
import logging
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import AbstractAsyncContextManager, contextmanager
from typing import Any, cast

import pytest
from fastapi import FastAPI
from httpx import AsyncClient, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import rbac
from app.core.db import get_db
from app.core.logging import JSONFormatter
from app.core.persona_resolver import PersonaResolver
from tests.conftest import AlembicRunner

AsyncClientFactory = Callable[..., AbstractAsyncContextManager[AsyncClient]]


# -----------------------------------------------------------------------------
# App + DB-override scaffold. Mirrors test_program_team_route.py's
# _build_team_app / _db_override precedent.
# -----------------------------------------------------------------------------


def _db_override(session: AsyncSession) -> Callable[[], AsyncIterator[AsyncSession]]:
    async def _get_db() -> AsyncIterator[AsyncSession]:
        yield session

    return _get_db


def _build_team_usage_app(
    build_app: Callable[..., FastAPI], test_session: AsyncSession, **settings_overrides: Any
) -> FastAPI:
    """Real `create_app()` wired for HTTP-level testing against a live DB. Hermetic
    default settings set `environment="test"`, so `/auth/dev-bypass` is registered and
    its tokens verify with no OIDC config."""
    app = build_app(**settings_overrides)
    app.dependency_overrides[get_db] = _db_override(test_session)
    return app


def _decode_unverified_claims(token: str) -> dict[str, Any]:
    """Read a JWT's payload claims WITHOUT verifying its signature -- mirrors
    `test_personal_usage.py`'s own technique. Needed here because
    `POST /auth/dev-bypass` always mints a fresh `uuid4()` `sub`, and the self
    path requires `member_id == current_user.user_id`."""
    payload_segment = token.split(".")[1]
    padding = "=" * (-len(payload_segment) % 4)
    return json.loads(base64.urlsafe_b64decode(payload_segment + padding))


async def _mint_dev_bypass_token(client: AsyncClient, *, role: str) -> tuple[str, str]:
    """`POST /auth/dev-bypass` and return `(access_token, user_id)`, where
    `user_id` is the token's own `sub` claim."""
    resp = await client.post("/auth/dev-bypass", json={"role": role})
    assert resp.status_code == 200, resp.text
    token = str(resp.json()["access_token"])
    return token, str(_decode_unverified_claims(token)["sub"])


async def _get_team_member_usage(
    client: AsyncClient,
    program_id: str,
    member_id: str,
    *,
    token: str | None,
    range_param: str | None = "__omit__",
) -> Response:
    """Issue the popup GET. `range_param="__omit__"` (default) sends no `range`
    query param at all; any other value (including `""`) sends it."""
    headers = {"Authorization": f"Bearer {token}"} if token is not None else {}
    params: dict[str, Any] = {} if range_param == "__omit__" else {"range": range_param}
    return await client.get(
        f"/api/overview/program-detail/{program_id}/team/{member_id}/usage",
        headers=headers,
        params=params,
    )


# -----------------------------------------------------------------------------
# Stub persona resolver (D-06's `rbac.configure()` seam) -- mirrors
# test_personal_usage.py / test_rbac.py's own stub, duplicated locally per
# each file's independent-ownership precedent.
# -----------------------------------------------------------------------------


class _StubPersonaResolver:
    def __init__(self, *, mapping: dict[str, str]) -> None:
        self._mapping = mapping

    async def resolve(self, role: str) -> str:
        return self._mapping[role]


@pytest.fixture(autouse=True)
def _reset_rbac_state() -> Iterator[None]:
    yield
    rbac._persona_resolver = None


# -----------------------------------------------------------------------------
# Log capture -- mirrors test_rbac.py's / test_personal_usage.py's
# _RecordCapturingHandler / _capture_rbac_logger idiom, duplicated locally.
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


def _events(records: list[logging.LogRecord], message: str) -> list[logging.LogRecord]:
    return [r for r in records if r.getMessage() == message]


async def _assert_logging_alive(records: list[logging.LogRecord]) -> None:
    """Positive control: call `rbac.org_access` directly (bypassing HTTP) inside
    the SAME capture window a test already opened, and assert its
    `rbac_check_org_access` event landed. This makes every denial-log
    assertion in this file self-witnessing -- if Alembic's
    `fileConfig(disable_existing_loggers=True)` (or anything else) silently
    disabled the `app.core.rbac` logger, THIS assertion fails loudly instead
    of the real assertion vacuously passing on an empty record list.
    """
    from dataclasses import dataclass

    @dataclass
    class _ControlUser:
        user_id: str
        email: str
        role: str
        groups: list[str]
        programs: list[str]

    control_user = _ControlUser(
        user_id="control-user",
        email="control@example.com",
        role="developer",
        groups=[],
        programs=[],
    )
    with pytest.raises(Exception):
        await rbac.org_access(cast(Any, control_user))
    control_events = _events(records, "rbac_check_org_access")
    assert control_events, (
        "positive control failed: rbac_check_org_access was not captured -- "
        "the app.core.rbac logger appears to be globally disabled (Alembic "
        "fileConfig trap), so the denial-log assertion above cannot be trusted"
    )


# -----------------------------------------------------------------------------
# Response-shape helpers.
# -----------------------------------------------------------------------------

_PERSONAL_USAGE_KEYS = {"cards", "daily_tokens", "commands"}


def _assert_no_personal_usage_fields(obj: Any, path: str = "$") -> None:
    """Recursively assert none of `cards`/`daily_tokens`/`commands` (nor the
    nested `daily_session_time`) appear anywhere in `obj` -- AC-12 requires
    denial and data to be mutually exclusive, not merely a missing top-level
    key."""
    forbidden = _PERSONAL_USAGE_KEYS | {"daily_session_time"}
    if isinstance(obj, dict):
        for key in forbidden:
            assert key not in obj, f"found forbidden key {key!r} at {path}"
        for key, value in obj.items():
            _assert_no_personal_usage_fields(value, f"{path}.{key}")
    elif isinstance(obj, list):
        for index, item in enumerate(obj):
            _assert_no_personal_usage_fields(item, f"{path}[{index}]")


# -----------------------------------------------------------------------------
# PGD-05-TC-10 -- self allowed.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_self_requester_gets_200_with_own_usage_tc10(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """PGD-05-TC-10 (AC-9): member M requesting their own popup data gets 200
    with a well-formed personal-usage-api envelope (no seeded events -- an
    empty-but-well-shaped envelope is sufficient to prove the gate passed and
    the SHP-02 service functions were actually invoked)."""
    program_id = "prog-001"
    app = _build_team_usage_app(build_app, test_session)

    async with async_client_for(app) as client:
        token, member_id = await _mint_dev_bypass_token(client, role="developer")

        resp = await _get_team_member_usage(client, program_id, member_id, token=token)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body.keys()) == _PERSONAL_USAGE_KEYS


# -----------------------------------------------------------------------------
# PGD-05-TC-10 -- cio allowed for any member.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cio_requester_gets_200_for_any_member_tc10(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """PGD-05-TC-10 (AC-9): a cio persona requesting a DIFFERENT member's popup
    data gets 200. Stubs `rbac.configure()` with an identity `cio` mapping
    (D-06 seam) so `member_in_program_visibility`'s non-self path resolves
    the requester as `cio` and passes."""
    program_id = "prog-001"
    app = _build_team_usage_app(build_app, test_session)

    rbac.configure(cast(PersonaResolver, _StubPersonaResolver(mapping={"cio": "cio"})))

    async with async_client_for(app) as client:
        token, _requester_user_id = await _mint_dev_bypass_token(client, role="cio")
        target_member_id = f"member-{uuid.uuid4()}"

        resp = await _get_team_member_usage(client, program_id, target_member_id, token=token)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body.keys()) == _PERSONAL_USAGE_KEYS


# -----------------------------------------------------------------------------
# PGD-05-TC-11 -- contract: verbatim personal-usage-api shape, no reshaping.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_success_body_is_verbatim_personal_usage_shape_tc11(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """PGD-05-TC-11 (AC-10): the popup route's success body is diffed against
    `GET /api/personal-usage/{user_id}` called directly for the same user_id
    and range -- byte-identical, proving zero PGD-05-specific reshaping.
    Self path used so both calls are gated by different mechanisms
    (`member_in_program_visibility` self-branch vs `individual_usage_
    visibility` self-branch) but hit the same underlying data."""
    program_id = "prog-001"
    app = _build_team_usage_app(build_app, test_session)

    async with async_client_for(app) as client:
        token, member_id = await _mint_dev_bypass_token(client, role="developer")

        popup_resp = await _get_team_member_usage(client, program_id, member_id, token=token)
        direct_resp = await client.get(
            f"/api/personal-usage/{member_id}?range=30d",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert popup_resp.status_code == 200, popup_resp.text
    assert direct_resp.status_code == 200, direct_resp.text
    assert popup_resp.json() == direct_resp.json()
    assert set(popup_resp.json().keys()) == _PERSONAL_USAGE_KEYS


# -----------------------------------------------------------------------------
# PGD-05-TC-12 -- deny non-self, non-cio; logged as member_view_denied, NOT
# individual_view_denied.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_non_self_non_cio_denied_403_logged_member_view_denied_tc12(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """PGD-05-TC-12 (AC-11): a developer persona requesting a DIFFERENT
    member's popup data is denied 403, and the ONLY rbac event emitted for
    this call is `member_view_denied` -- `individual_view_denied` must never
    fire on this route, since `individual_usage_visibility` is never called
    here (D-04)."""
    program_id = "prog-001"
    app = _build_team_usage_app(build_app, test_session)

    rbac.configure(
        cast(PersonaResolver, _StubPersonaResolver(mapping={"developer": "developer"}))
    )

    async with async_client_for(app) as client:
        token, _requester_user_id = await _mint_dev_bypass_token(client, role="developer")
        target_member_id = f"member-{uuid.uuid4()}"

        with _capture_rbac_logger() as records:
            resp = await _get_team_member_usage(
                client, program_id, target_member_id, token=token
            )
            await _assert_logging_alive(records)

    assert resp.status_code == 403

    member_view_denied_events = _events(records, "member_view_denied")
    assert len(member_view_denied_events) == 1

    individual_view_denied_events = _events(records, "individual_view_denied")
    assert individual_view_denied_events == [], (
        "individual_view_denied must never fire on the popup's own sibling "
        "route (D-04) -- member_in_program_visibility is a distinct gate"
    )

    payload = json.loads(JSONFormatter().format(member_view_denied_events[0]))
    assert payload["outcome"] == "denied"
    assert payload["program_id"] == program_id
    assert payload["target_member_id"] == target_member_id


# -----------------------------------------------------------------------------
# PGD-05-TC-13 -- denied response body carries no personal-usage fields.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_denied_response_body_has_no_personal_usage_fields_tc13(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """PGD-05-TC-13 (AC-12): the 403 body is the bare error envelope --
    `{"error": {...}}` -- with no `cards`/`daily_tokens`/`commands`/
    `daily_session_time` anywhere, at any nesting depth. Proves denial and
    data are mutually exclusive by construction (the gate raises before any
    SHP-02 service function is ever called)."""
    program_id = "prog-001"
    app = _build_team_usage_app(build_app, test_session)

    rbac.configure(
        cast(PersonaResolver, _StubPersonaResolver(mapping={"developer": "developer"}))
    )

    async with async_client_for(app) as client:
        token, _requester_user_id = await _mint_dev_bypass_token(client, role="developer")
        target_member_id = f"member-{uuid.uuid4()}"

        resp = await _get_team_member_usage(client, program_id, target_member_id, token=token)

    assert resp.status_code == 403
    body = resp.json()
    assert set(body.keys()) == {"error"}
    _assert_no_personal_usage_fields(body)


# -----------------------------------------------------------------------------
# PGD-05-TC-18 -- gate-matrix: allow self, allow cio, deny other, at the
# route level; and PGD-05-FR-3's spy assertion that member_in_program_
# visibility (not individual_usage_visibility) is the gate in force here.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gate_matrix_self_cio_allowed_other_denied_tc18(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    """PGD-05-TC-18 (FR-3): route-level allow/allow/deny matrix -- self member
    M, a cio persona, and a non-self/non-cio developer, all targeting the
    same member_id. Self and cio both 200; the developer 403s and is the
    only one that logs `member_view_denied`; `individual_view_denied` never
    fires for any of the three."""
    program_id = "prog-001"
    app = _build_team_usage_app(build_app, test_session)

    async with async_client_for(app) as client:
        # Self.
        self_token, member_id = await _mint_dev_bypass_token(client, role="developer")
        self_resp = await _get_team_member_usage(client, program_id, member_id, token=self_token)
        assert self_resp.status_code == 200, self_resp.text

        # CIO.
        rbac.configure(cast(PersonaResolver, _StubPersonaResolver(mapping={"cio": "cio"})))
        cio_token, _cio_user_id = await _mint_dev_bypass_token(client, role="cio")
        cio_resp = await _get_team_member_usage(client, program_id, member_id, token=cio_token)
        assert cio_resp.status_code == 200, cio_resp.text

        # Neither self nor cio.
        rbac.configure(
            cast(PersonaResolver, _StubPersonaResolver(mapping={"developer": "developer"}))
        )
        other_token, _other_user_id = await _mint_dev_bypass_token(client, role="developer")

        with _capture_rbac_logger() as records:
            other_resp = await _get_team_member_usage(
                client, program_id, member_id, token=other_token
            )
            await _assert_logging_alive(records)

    assert other_resp.status_code == 403

    member_view_denied_events = _events(records, "member_view_denied")
    assert len(member_view_denied_events) == 1

    individual_view_denied_events = _events(records, "individual_view_denied")
    assert individual_view_denied_events == []


# -----------------------------------------------------------------------------
# Range handling -- default 30d; 7d/30d/90d valid; anything else -> 400
# invalid_range (not FastAPI's default 422), matching every other
# `_range_with_default` consumer on this router.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_omitted_range_defaults_to_30d(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    program_id = "prog-001"
    app = _build_team_usage_app(build_app, test_session)

    async with async_client_for(app) as client:
        token, member_id = await _mint_dev_bypass_token(client, role="developer")
        resp = await _get_team_member_usage(client, program_id, member_id, token=token)

    assert resp.status_code == 200, resp.text
    assert len(resp.json()["daily_tokens"]["points"]) == 30


@pytest.mark.asyncio
@pytest.mark.parametrize("range_value", ["7d", "30d", "90d"])
async def test_valid_range_values_accepted(
    range_value: str,
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    program_id = "prog-001"
    app = _build_team_usage_app(build_app, test_session)

    async with async_client_for(app) as client:
        token, member_id = await _mint_dev_bypass_token(client, role="developer")
        resp = await _get_team_member_usage(
            client, program_id, member_id, token=token, range_param=range_value
        )

    assert resp.status_code == 200, resp.text
    expected_points = {"7d": 7, "30d": 30, "90d": 90}[range_value]
    assert len(resp.json()["daily_tokens"]["points"]) == expected_points


@pytest.mark.asyncio
async def test_invalid_range_returns_400_not_422(
    migrated_db: AlembicRunner,
    test_session: AsyncSession,
    build_app: Callable[..., FastAPI],
    async_client_for: AsyncClientFactory,
) -> None:
    program_id = "prog-001"
    app = _build_team_usage_app(build_app, test_session)

    async with async_client_for(app) as client:
        token, member_id = await _mint_dev_bypass_token(client, role="developer")
        resp = await _get_team_member_usage(
            client, program_id, member_id, token=token, range_param="1d"
        )

    assert resp.status_code == 400
    assert resp.json() == {
        "error": {"code": "http_400", "message": "invalid_range", "details": None}
    }
