"""Unit/security/contract tests for `app/core/rbac.py` -- AUTH-03-TC-01..28
(`docs/test-cases/AUTH-03.json`).

Bundles every layer (unit, security/PII-audit, contract) into one topic
file, matching `test_persona_resolver.py`'s precedent (AUTH-02). Perf
(TC-26) belongs to `tests/perf/test_rbac_perf.py` (T-06), not here.

T-01 owns this file's scaffold and implements only `org_access` and
`program_visibility`; it covers TC-01, TC-02, TC-03, TC-04, TC-17, TC-18,
TC-20, TC-24, TC-27, TC-28, plus a decision-guard test for D-06 (not a
numbered TC). T-02 adds `individual_usage_visibility` and covers TC-05,
TC-06, TC-07, TC-22, plus a decision-guard test proving the self path
short-circuits before persona resolution (not a numbered TC). T-03 adds
`member_in_program_visibility` and covers TC-08, TC-09, TC-10, TC-23, plus
the `_ProgramVisibilitySpy`/`_patch_program_visibility` call-order/deny spy.
T-04 adds `governance_visibility` -- the last of the five checks -- and
covers TC-11, TC-12 (parametrized over all five personas, not
hand-duplicated), TC-13, TC-14, TC-15, TC-16, TC-19, TC-21, reusing the T-03
spy unchanged for its own persona-then-program_visibility call-order
assertions. T-05 adds the contract layer -- TC-25, a tripwire asserting all
five checks' names/parameter order/count against the locked `rbac-checks`
contract -- without altering the scaffold: `_build_current_user`,
`_StubPersonaResolver`, `_capture_logger`, `_events`, and the autouse
`_reset_rbac_state` fixture were all kept deliberately general so every
check's tests, through T-05, could reuse them unchanged.

Log-capture idiom: a `_RecordCapturingHandler` attached directly to the
real `app.core.rbac` logger, force-enabled and depropagated --
`tests/unit/test_persona_resolver.py`'s documented idiom, immune to both
the `configure_logging()`+stdout trap and Alembic's
`fileConfig(disable_existing_loggers=True)` sweep.

Module-state hygiene (D-06/DATA-DESIGN.md §7): `app.core.rbac._persona_
resolver` is process-lifetime, set-once state -- every test that needs a
resolver calls `rbac.configure(...)` itself at the start; the autouse
`_reset_rbac_state` fixture resets it to `None` on teardown so no test can
leak its stub into the next one.
"""

from __future__ import annotations

import inspect
import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import cast

import pytest
from fastapi import HTTPException

from app.core import rbac
from app.core.auth import CurrentUser
from app.core.logging import JSONFormatter
from app.core.persona_resolver import (
    PersonaNotFoundError,
    PersonaResolutionError,
    PersonaResolver,
)

# -----------------------------------------------------------------------------
# CurrentUser fixture builder.
# -----------------------------------------------------------------------------


def _build_current_user(
    *,
    user_id: str = "u-1",
    role: str = "developer",
    email: str = "user@example.com",
    groups: list[str] | None = None,
    programs: list[str] | None = None,
) -> CurrentUser:
    return CurrentUser(
        user_id=user_id,
        email=email,
        role=role,
        groups=groups if groups is not None else [],
        programs=programs if programs is not None else [],
    )


# -----------------------------------------------------------------------------
# Stub persona-resolver test double (D-06's `configure()` seam). Configurable
# to return a persona (directly, or via a role->persona mapping) or raise
# PersonaResolutionError/PersonaNotFoundError; records every role it was
# asked to resolve for later call-order spies.
# -----------------------------------------------------------------------------


class _StubPersonaResolver:
    def __init__(
        self,
        *,
        persona: str | None = None,
        mapping: dict[str, str] | None = None,
        raises: type[PersonaResolutionError] | None = None,
        order: list[str] | None = None,
        label: str = "persona-check",
    ) -> None:
        self.persona = persona
        self.mapping = mapping or {}
        self.raises = raises
        # `order`/`label` mirror `_ProgramVisibilitySpy`'s own fields below --
        # when a test shares one list between both, it can assert call ORDER
        # across a persona-resolution step and a program_visibility call
        # (AUTH-03-TC-16), not just the end result.
        self.order = order
        self.label = label
        self.calls: list[str] = []

    async def resolve(self, role: str) -> str:
        self.calls.append(role)
        if self.order is not None:
            self.order.append(self.label)
        if self.raises is not None:
            if self.raises is PersonaNotFoundError:
                raise PersonaNotFoundError(role)
            raise PersonaResolutionError(role, "stub: Tier-3 timeout")
        if role in self.mapping:
            return self.mapping[role]
        if self.persona is not None:
            return self.persona
        raise PersonaNotFoundError(role)


def _configure(stub: _StubPersonaResolver) -> None:
    """`cast` is safe here: structurally compatible (a single async
    `resolve(role) -> str` method) without literally subclassing
    `PersonaResolver` -- same idiom as `test_persona_resolver.py`'s
    `_pure_mock_resolver` casting `FakeSessionFactory`."""
    rbac.configure(cast(PersonaResolver, stub))


@pytest.fixture(autouse=True)
def _reset_rbac_state() -> Iterator[None]:
    yield
    rbac._persona_resolver = None


# -----------------------------------------------------------------------------
# Log capture -- mirrors test_persona_resolver.py's documented idiom.
# -----------------------------------------------------------------------------


class _RecordCapturingHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@contextmanager
def _capture_logger(name: str, level: int = logging.INFO) -> Iterator[list[logging.LogRecord]]:
    logger = logging.getLogger(name)
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


# -----------------------------------------------------------------------------
# TC-27 support -- a CurrentUser look-alike whose `.programs` raises if ever
# read. Not a `CurrentUser` subclass: `CurrentUser`'s dataclass `__init__`
# would assign a plain instance attribute over any same-named property,
# defeating the guard.
# -----------------------------------------------------------------------------


class _ProgramsAccessGuard:
    user_id = "u-guard"
    email = "guard@example.com"
    role = "developer"
    groups: list[str] = []

    @property
    def programs(self) -> list[str]:
        raise AssertionError("program_visibility must never read current_user.programs (R-003)")


# -----------------------------------------------------------------------------
# AUTH-03-TC-01 (AC-1) -- org_access denies a non-CIO session.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_org_access_denies_non_cio_session_tc01() -> None:
    _configure(_StubPersonaResolver(mapping={"developer": "developer"}))
    current_user = _build_current_user(user_id="u-dev-1", role="developer")

    with _capture_logger("app.core.rbac") as records:
        with pytest.raises(HTTPException) as exc_info:
            await rbac.org_access(current_user)

    assert exc_info.value.status_code == 403
    events = _events(records, "rbac_check_org_access")
    assert len(events) == 1
    assert events[0].outcome == "denied"  # type: ignore[attr-defined]


# -----------------------------------------------------------------------------
# AUTH-03-TC-02 (AC-2) -- org_access passes a CIO session.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_org_access_passes_cio_session_tc02() -> None:
    _configure(_StubPersonaResolver(mapping={"cio": "cio"}))
    current_user = _build_current_user(user_id="u-cio-1", role="cio")

    with _capture_logger("app.core.rbac") as records:
        await rbac.org_access(current_user)  # returns normally -- no exception

    events = _events(records, "rbac_check_org_access")
    assert len(events) == 1
    assert events[0].outcome == "authorized"  # type: ignore[attr-defined]


# -----------------------------------------------------------------------------
# AUTH-03-TC-03 (AC-3) -- program_visibility passes for any authenticated
# session and program id, including one absent from current_user.programs.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_program_visibility_passes_for_any_authenticated_session_tc03() -> None:
    current_user = _build_current_user(user_id="u-100", programs=["prog-1"])

    await rbac.program_visibility(current_user, program_id="prog-99")  # no exception


# -----------------------------------------------------------------------------
# AUTH-03-TC-04 (AC-3) -- program_visibility's outcome is invariant across
# arbitrary program_id values (R-003, open-aggregate model).
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_program_visibility_outcome_invariant_across_program_ids_tc04() -> None:
    current_user = _build_current_user(user_id="u-100", programs=["prog-1", "prog-2"])
    program_ids = [
        "prog-1",
        "prog-99",
        "",
        "not-a-real-program",
        "00000000-0000-0000-0000-000000000000",
    ]

    for program_id in program_ids:
        await rbac.program_visibility(current_user, program_id=program_id)  # no exception


# -----------------------------------------------------------------------------
# AUTH-03-TC-05 (AC-4) -- individual_usage_visibility passes for self.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_individual_usage_visibility_passes_for_self_tc05() -> None:
    _configure(_StubPersonaResolver(mapping={"developer": "developer"}))
    current_user = _build_current_user(user_id="u-200", role="developer")

    await rbac.individual_usage_visibility(current_user, target_user_id="u-200")  # no exception


# -----------------------------------------------------------------------------
# AUTH-03-TC-06 (AC-4) -- individual_usage_visibility passes for CIO viewing
# another user's data.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_individual_usage_visibility_passes_for_cio_tc06() -> None:
    _configure(_StubPersonaResolver(mapping={"cio": "cio"}))
    current_user = _build_current_user(user_id="u-cio-1", role="cio")

    await rbac.individual_usage_visibility(current_user, target_user_id="u-300")  # no exception


# -----------------------------------------------------------------------------
# AUTH-03-TC-07 (AC-4) -- denies every combination that is neither self nor
# CIO.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_individual_usage_visibility_denies_non_self_non_cio_tc07() -> None:
    combinations = [
        ("u-arch-1", "architect", "u-300"),
        ("u-dev-1", "developer", "u-301"),
        ("u-pm-1", "product-manager", "u-302"),
        ("u-em-1", "engineering-manager", "u-303"),
    ]
    for user_id, role, target_user_id in combinations:
        _configure(_StubPersonaResolver(mapping={role: role}))
        current_user = _build_current_user(user_id=user_id, role=role)

        with _capture_logger("app.core.rbac") as records:
            with pytest.raises(HTTPException) as exc_info:
                await rbac.individual_usage_visibility(current_user, target_user_id=target_user_id)

        assert exc_info.value.status_code == 403
        events = _events(records, "individual_view_denied")
        assert len(events) == 1
        assert events[0].outcome == "denied"  # type: ignore[attr-defined]


# -----------------------------------------------------------------------------
# Decision guard (task note, not a numbered TC) -- the self path short-
# circuits before persona resolution; proven with a stub that would raise if
# ever consulted.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_individual_usage_visibility_self_path_skips_persona_resolution() -> None:
    stub = _StubPersonaResolver(raises=PersonaResolutionError)
    _configure(stub)
    current_user = _build_current_user(user_id="u-200", role="developer")

    await rbac.individual_usage_visibility(current_user, target_user_id="u-200")  # no exception

    assert stub.calls == []


# -----------------------------------------------------------------------------
# program_visibility call-order/deny spy (T-03) -- reused unchanged by T-04's
# TC-15/TC-16 ordered persona-then-program_visibility call-order tests.
# -----------------------------------------------------------------------------


class _ProgramVisibilitySpy:
    """Callable stand-in for `program_visibility`. Records every
    `(current_user, program_id)` call in `self.calls`; optionally raises
    `HTTPException(403)` unconditionally to simulate `program_visibility`
    DENYING (TC-10, and T-04's TC-14). When `order` is given, also appends
    `label` to it -- the same shared list a persona-resolution step can
    append to, so a test can assert call ORDER across both steps (T-04's
    TC-15/TC-16), not just the end result."""

    def __init__(
        self,
        *,
        deny: bool = False,
        order: list[str] | None = None,
        label: str = "program-visibility",
    ) -> None:
        self.deny = deny
        self.order = order
        self.label = label
        self.calls: list[tuple[CurrentUser, str]] = []

    async def __call__(self, current_user: CurrentUser, program_id: str) -> None:
        self.calls.append((current_user, program_id))
        if self.order is not None:
            self.order.append(self.label)
        if self.deny:
            raise HTTPException(status_code=403)


def _patch_program_visibility(
    monkeypatch: pytest.MonkeyPatch,
    *,
    deny: bool = False,
    order: list[str] | None = None,
) -> _ProgramVisibilitySpy:
    """Installs the spy onto `app.core.rbac.program_visibility`. Calling it
    UNQUALIFIED from inside `rbac.py` resolves through the module's own
    globals at call time (see `member_in_program_visibility`'s docstring),
    so every in-module caller sees the patched version. `monkeypatch`
    restores the real function automatically at test teardown -- no manual
    restore needed, so a leaked patch can never corrupt a later test (T-04,
    T-06's perf test)."""
    spy = _ProgramVisibilitySpy(deny=deny, order=order)
    monkeypatch.setattr(rbac, "program_visibility", spy)
    return spy


# -----------------------------------------------------------------------------
# AUTH-03-TC-08 (AC-5) -- member_in_program_visibility passes when
# program_visibility passes and the requester is that member (self).
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_member_in_program_visibility_passes_for_self_tc08() -> None:
    current_user = _build_current_user(user_id="u-400", role="developer")

    await rbac.member_in_program_visibility(
        current_user, program_id="prog-1", target_member_id="u-400"
    )  # no exception


# -----------------------------------------------------------------------------
# AUTH-03-TC-09 (AC-5) -- denies when program_visibility passes but the
# requester is neither the member nor CIO.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_member_in_program_visibility_denies_non_member_non_cio_tc09() -> None:
    _configure(_StubPersonaResolver(mapping={"developer": "developer"}))
    current_user = _build_current_user(user_id="u-401", role="developer")

    with _capture_logger("app.core.rbac") as records:
        with pytest.raises(HTTPException) as exc_info:
            await rbac.member_in_program_visibility(
                current_user, program_id="prog-1", target_member_id="u-402"
            )

    assert exc_info.value.status_code == 403
    events = _events(records, "member_view_denied")
    assert len(events) == 1
    assert events[0].outcome == "denied"  # type: ignore[attr-defined]


# -----------------------------------------------------------------------------
# AUTH-03-TC-10 (FR-4) -- program_visibility's denial cascades without ever
# evaluating self-or-cio, even when target_member_id == current_user.user_id.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_member_in_program_visibility_program_denial_short_circuits_tc10(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spy = _patch_program_visibility(monkeypatch, deny=True)
    # user_id == target_member_id: would pass self-or-cio if that branch
    # were ever reached -- it must not be, since program_visibility denies
    # first. No persona resolver is configured; if the self-or-cio branch
    # (or a fallback persona-resolution path) ran anyway, `_resolver()`
    # would raise `RuntimeError`, not `HTTPException`, making that bug loud
    # too.
    current_user = _build_current_user(user_id="u-500", role="developer")

    with pytest.raises(HTTPException) as exc_info:
        await rbac.member_in_program_visibility(
            current_user, program_id="prog-9", target_member_id="u-500"
        )

    assert exc_info.value.status_code == 403
    assert spy.calls == [(current_user, "prog-9")]


# -----------------------------------------------------------------------------
# AUTH-03-TC-11/TC-12 (AC-6) -- governance_visibility enumerates the full
# five-persona set: passes for architect/product-manager/developer, denies
# for cio/engineering-manager. Parametrized (task note) rather than five
# near-duplicate tests, so adding a persona to the tuple later cannot
# silently pass an unchanged suite.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("persona", "expect_authorized"),
    [
        ("architect", True),
        ("product-manager", True),
        ("developer", True),
        ("cio", False),
        ("engineering-manager", False),
    ],
)
async def test_governance_visibility_enumerates_persona_set_tc11_tc12(
    persona: str, expect_authorized: bool
) -> None:
    _configure(_StubPersonaResolver(mapping={persona: persona}))
    current_user = _build_current_user(user_id=f"u-{persona}", role=persona)

    with _capture_logger("app.core.rbac") as records:
        if expect_authorized:
            await rbac.governance_visibility(current_user)  # no exception
        else:
            with pytest.raises(HTTPException) as exc_info:
                await rbac.governance_visibility(current_user)
            assert exc_info.value.status_code == 403

    events = _events(records, "rbac_check_governance_visibility")
    assert len(events) == 1
    assert events[0].outcome == ("authorized" if expect_authorized else "denied")  # type: ignore[attr-defined]


# -----------------------------------------------------------------------------
# AUTH-03-TC-13 (AC-7) -- with a program_id, passes only once BOTH the
# persona gate and program_visibility pass.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_governance_visibility_with_program_id_passes_when_both_pass_tc13(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spy = _patch_program_visibility(monkeypatch)  # deny=False -- still executes normally
    _configure(_StubPersonaResolver(mapping={"architect": "architect"}))
    current_user = _build_current_user(user_id="u-600", role="architect")

    with _capture_logger("app.core.rbac") as records:
        await rbac.governance_visibility(current_user, program_id="prog-5")  # no exception

    assert spy.calls == [(current_user, "prog-5")]
    events = _events(records, "rbac_check_governance_visibility")
    assert len(events) == 1
    assert events[0].outcome == "authorized"  # type: ignore[attr-defined]


# -----------------------------------------------------------------------------
# AUTH-03-TC-14 (AC-7) -- denies when program_visibility denies, even though
# the persona gate passed.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_governance_visibility_with_program_id_denies_when_program_denies_tc14(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spy = _patch_program_visibility(monkeypatch, deny=True)
    _configure(_StubPersonaResolver(mapping={"developer": "developer"}))
    current_user = _build_current_user(user_id="u-601", role="developer")

    with pytest.raises(HTTPException) as exc_info:
        await rbac.governance_visibility(current_user, program_id="prog-6")

    assert exc_info.value.status_code == 403
    assert spy.calls == [(current_user, "prog-6")]


# -----------------------------------------------------------------------------
# AUTH-03-TC-15 (AC-7) -- a persona-gate denial short-circuits before
# program_visibility is ever called.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_governance_visibility_persona_denial_short_circuits_before_program_tc15(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spy = _patch_program_visibility(monkeypatch)
    _configure(_StubPersonaResolver(mapping={"cio": "cio"}))
    current_user = _build_current_user(user_id="u-602", role="cio")

    with _capture_logger("app.core.rbac") as records:
        with pytest.raises(HTTPException) as exc_info:
            await rbac.governance_visibility(current_user, program_id="prog-7")

    assert exc_info.value.status_code == 403
    assert spy.calls == []
    events = _events(records, "rbac_check_governance_visibility")
    assert len(events) == 1
    assert events[0].outcome == "denied"  # type: ignore[attr-defined]


# -----------------------------------------------------------------------------
# AUTH-03-TC-16 (FR-4) -- call order is persona gate FIRST, then
# program_visibility -- proven with a single ordered call-recorder shared by
# both steps.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_governance_visibility_call_order_persona_then_program_tc16(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order: list[str] = []
    _configure(_StubPersonaResolver(mapping={"product-manager": "product-manager"}, order=order))
    spy = _patch_program_visibility(monkeypatch, order=order)
    current_user = _build_current_user(user_id="u-603", role="product-manager")

    await rbac.governance_visibility(current_user, program_id="prog-8")  # no exception

    assert order == ["persona-check", "program-visibility"]
    assert spy.calls == [(current_user, "prog-8")]


# -----------------------------------------------------------------------------
# AUTH-03-TC-17 (FR-1/C-1) -- PersonaResolutionError denies with 403, logged
# at ERROR level.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_org_access_persona_resolution_error_denies_and_logs_at_error_tc17() -> None:
    _configure(_StubPersonaResolver(raises=PersonaResolutionError))
    current_user = _build_current_user(user_id="u-700", role="cio")

    with _capture_logger("app.core.rbac") as records:
        with pytest.raises(HTTPException) as exc_info:
            await rbac.org_access(current_user)

    assert exc_info.value.status_code == 403
    events = _events(records, "rbac_check_org_access")
    assert len(events) == 1
    assert events[0].levelno == logging.ERROR
    assert events[0].outcome == "denied"  # type: ignore[attr-defined]


# -----------------------------------------------------------------------------
# AUTH-03-TC-18 (FR-1/C-1) -- PersonaNotFoundError denies with 403, logged
# at the check's normal INFO level (distinct from TC-17's ERROR).
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_org_access_persona_not_found_error_denies_and_logs_at_info_tc18() -> None:
    _configure(_StubPersonaResolver(raises=PersonaNotFoundError))
    current_user = _build_current_user(user_id="u-701", role="unmapped-role")

    with _capture_logger("app.core.rbac") as records:
        with pytest.raises(HTTPException) as exc_info:
            await rbac.org_access(current_user)

    assert exc_info.value.status_code == 403
    events = _events(records, "rbac_check_org_access")
    assert len(events) == 1
    assert events[0].levelno == logging.INFO
    assert events[0].outcome == "denied"  # type: ignore[attr-defined]


# -----------------------------------------------------------------------------
# AUTH-03-TC-19 (FR-1) -- PersonaResolutionError fails closed at
# governance_visibility too, not only org_access.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_governance_visibility_persona_resolution_error_denies_tc19() -> None:
    _configure(_StubPersonaResolver(raises=PersonaResolutionError))
    current_user = _build_current_user(user_id="u-702", role="architect")

    with _capture_logger("app.core.rbac") as records:
        with pytest.raises(HTTPException) as exc_info:
            await rbac.governance_visibility(current_user)

    assert exc_info.value.status_code == 403
    events = _events(records, "rbac_check_governance_visibility")
    assert len(events) == 1
    assert events[0].levelno == logging.ERROR
    assert events[0].outcome == "denied"  # type: ignore[attr-defined]


# -----------------------------------------------------------------------------
# AUTH-03-TC-20 (FR-2/C-2) -- rbac_check_org_access payload contains exactly
# its allowlisted fields (pattern: AUTH-02 TC-15).
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rbac_check_org_access_payload_allowlist_tc20() -> None:
    _configure(_StubPersonaResolver(mapping={"cio": "cio"}))
    current_user = _build_current_user(
        user_id="u-800", role="cio", email="cio@example.com", groups=["program-alpha"]
    )

    with _capture_logger("app.core.rbac") as records:
        await rbac.org_access(current_user)

    events = _events(records, "rbac_check_org_access")
    assert len(events) == 1
    payload = json.loads(JSONFormatter().format(events[0]))

    assert set(payload.keys()) == {
        "timestamp",
        "level",
        "logger",
        "message",
        "user_id",
        "persona",
        "outcome",
    }
    assert "email" not in payload
    assert "groups" not in payload
    assert payload["outcome"] == "authorized"


# -----------------------------------------------------------------------------
# AUTH-03-TC-21 (FR-2/C-2) -- rbac_check_governance_visibility payload
# contains exactly its allowlisted fields.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rbac_check_governance_visibility_payload_allowlist_tc21() -> None:
    _configure(_StubPersonaResolver(mapping={"developer": "developer"}))
    current_user = _build_current_user(
        user_id="u-801", role="developer", email="dev@example.com", groups=["program-beta"]
    )

    with _capture_logger("app.core.rbac") as records:
        await rbac.governance_visibility(current_user)  # no exception

    events = _events(records, "rbac_check_governance_visibility")
    assert len(events) == 1
    payload = json.loads(JSONFormatter().format(events[0]))

    assert set(payload.keys()) == {
        "timestamp",
        "level",
        "logger",
        "message",
        "user_id",
        "persona",
        "outcome",
    }
    assert "email" not in payload
    assert "groups" not in payload
    assert payload["outcome"] == "authorized"


# -----------------------------------------------------------------------------
# AUTH-03-TC-22 (FR-2/C-2) -- individual_view_denied payload contains
# exactly its allowlisted fields.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_individual_view_denied_payload_allowlist_tc22() -> None:
    _configure(_StubPersonaResolver(mapping={"developer": "developer"}))
    current_user = _build_current_user(
        user_id="u-802", role="developer", email="dev2@example.com", groups=["program-gamma"]
    )

    with _capture_logger("app.core.rbac") as records:
        with pytest.raises(HTTPException):
            await rbac.individual_usage_visibility(current_user, target_user_id="u-900")

    events = _events(records, "individual_view_denied")
    assert len(events) == 1
    payload = json.loads(JSONFormatter().format(events[0]))

    assert set(payload.keys()) == {
        "timestamp",
        "level",
        "logger",
        "message",
        "user_id",
        "target_user_id",
        "outcome",
    }
    assert "email" not in payload
    assert "groups" not in payload
    assert "persona" not in payload
    assert payload["outcome"] == "denied"


# -----------------------------------------------------------------------------
# AUTH-03-TC-23 (FR-2/C-2) -- member_view_denied payload contains exactly
# its allowlisted fields.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_member_view_denied_payload_allowlist_tc23() -> None:
    _configure(_StubPersonaResolver(mapping={"product-manager": "product-manager"}))
    current_user = _build_current_user(
        user_id="u-803",
        role="product-manager",
        email="pm@example.com",
        groups=["program-delta"],
    )

    with _capture_logger("app.core.rbac") as records:
        with pytest.raises(HTTPException):
            await rbac.member_in_program_visibility(
                current_user, program_id="prog-11", target_member_id="u-901"
            )

    events = _events(records, "member_view_denied")
    assert len(events) == 1
    payload = json.loads(JSONFormatter().format(events[0]))

    assert set(payload.keys()) == {
        "timestamp",
        "level",
        "logger",
        "message",
        "user_id",
        "program_id",
        "target_member_id",
        "outcome",
    }
    assert "email" not in payload
    assert "groups" not in payload
    assert "persona" not in payload
    assert payload["outcome"] == "denied"


# -----------------------------------------------------------------------------
# AUTH-03-TC-24 (FR-3) -- _GOVERNANCE_PERSONAS is a hardcoded module
# constant, no config/DB lookup backing it.
# -----------------------------------------------------------------------------


def test_governance_personas_is_hardcoded_constant_tc24() -> None:
    assert set(rbac._GOVERNANCE_PERSONAS) == {"architect", "product-manager", "developer"}
    assert "cio" not in rbac._GOVERNANCE_PERSONAS
    assert "engineering-manager" not in rbac._GOVERNANCE_PERSONAS

    source = Path(rbac.__file__).read_text(encoding="utf-8")
    definition_line = next(
        line for line in source.splitlines() if line.strip().startswith("_GOVERNANCE_PERSONAS")
    )
    assert "architect" in definition_line
    assert "settings" not in definition_line.lower()
    assert "environ" not in definition_line.lower()


# -----------------------------------------------------------------------------
# AUTH-03-TC-27 (NFR-security/R-003) -- program_visibility never reads
# current_user.programs; the open-aggregate model is structural.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_program_visibility_never_reads_programs_tc27() -> None:
    guard = cast(CurrentUser, _ProgramsAccessGuard())

    await rbac.program_visibility(guard, program_id="prog-20")  # no exception -> no AssertionError


# -----------------------------------------------------------------------------
# AUTH-03-TC-28 (NFR-observability/FR-2) -- program_visibility emits no log
# event of its own.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_program_visibility_emits_no_log_event_tc28() -> None:
    current_user = _build_current_user(programs=["prog-1"])

    with _capture_logger("app.core.rbac") as records:
        await rbac.program_visibility(current_user, program_id="prog-1")
        await rbac.program_visibility(current_user, program_id="prog-99")

    assert records == []


# -----------------------------------------------------------------------------
# Decision guard (D-06, not a numbered TC) -- _resolver() fails loudly, never
# silently default-permits, when configure() was never called.
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolver_raises_runtime_error_when_never_configured() -> None:
    current_user = _build_current_user()

    with pytest.raises(RuntimeError, match=r"rbac\.configure\(\) was never called"):
        await rbac.org_access(current_user)


# -----------------------------------------------------------------------------
# AUTH-03-TC-25 (FR-5) -- the five rbac check functions match the locked
# `rbac-checks` contract (`docs/requirements/auth.md#rbac-checks`): coroutine
# functions, `current_user` first, and the FULL parameter name list/order/
# count exactly as published -- the contract's own words are "names,
# parameter order, and count are locked", so this asserts all three, not
# just the first-parameter rule. Plain-introspection pattern, same as
# `tests/unit/test_rollup_rebuild_contract.py`'s TC-09 -- no dedicated
# contract-testing framework.
#
# This is a tripwire for the 16 downstream consumers (AUTH-04, OVW-01..04,
# PGD-01..06, SHP-02..06). A failure here means "you just broke a published
# contract" -- the fix is reverting the signature change (or, if the rename
# is deliberate, a coordinated migration across all 16 consumers plus an
# update to docs/requirements/auth.md), never "update this assertion to
# match".
# -----------------------------------------------------------------------------

_CONTRACT_PARAMS: dict[str, list[str]] = {
    "org_access": ["current_user"],
    "program_visibility": ["current_user", "program_id"],
    "individual_usage_visibility": ["current_user", "target_user_id"],
    "member_in_program_visibility": ["current_user", "program_id", "target_member_id"],
    "governance_visibility": ["current_user", "program_id"],
}


@pytest.mark.parametrize(("name", "expected_params"), list(_CONTRACT_PARAMS.items()))
def test_rbac_check_signatures_match_locked_contract_tc25(
    name: str, expected_params: list[str]
) -> None:
    fn = getattr(rbac, name)
    assert inspect.iscoroutinefunction(fn)

    sig = inspect.signature(fn)
    param_names = list(sig.parameters)
    assert param_names[0] == "current_user"
    assert param_names == expected_params  # full name list, order, AND count


def test_governance_visibility_program_id_defaults_to_none_tc25() -> None:
    """The contract's only optional parameter: `governance_visibility`'s
    `program_id` must default to `None`, so a consumer calling
    `governance_visibility(user)` with no program (AC6, the persona-only
    gate) does not have to pass one explicitly."""
    sig = inspect.signature(rbac.governance_visibility)
    assert sig.parameters["program_id"].default is None
