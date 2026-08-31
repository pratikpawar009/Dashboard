"""Performance tests for `app/core/rbac.py`'s five RBAC checks --
AUTH-03-TC-26 (`AUTH-03-NFR-performance`): each check adds < 5ms p95
latency, in-process, no I/O (`docs/features/AUTH-03/REQUIREMENTS.md` §
Non-functional requirements; story Decision log, 2026-08-26 assumption;
`DATA-DESIGN.md` § 8 -- budget is for the in-process check itself, a cold
Tier-3 resolve is explicitly out of scope by design).

Structure mirrors `tests/perf/test_persona_resolver_perf.py`: plain
`time.perf_counter()`, no dedicated benchmark tool. `_percentile` below is
copied from `test_range_pagination_perf.py::_percentile` /
`test_persona_resolver_perf.py::_percentile` rather than imported -- this
repo's existing perf files each keep their own small copy instead of a
shared `perf_utils` module (reusability-baseline.md: "extract on the third
repetition, not the first" -- that principle is scoped to a module's own
repeated code, not cross-file duplication of a five-line, dependency-free
helper); this file follows that established precedent rather than
introducing the first shared module unilaterally.

Stub persona resolver: a minimal, local `_StubPersonaResolver` (`resolve()`
returns a fixed persona immediately, no I/O) -- NOT imported from
`tests/unit/test_rbac.py::_StubPersonaResolver`, a sibling file under
concurrent edit by another task in this same session. `rbac.configure()`
declares its parameter as the concrete `PersonaResolver` class, so the stub
is passed via `cast(PersonaResolver, stub)` -- structurally compatible (a
single async `resolve(role) -> str` method), the same idiom
`tests/unit/test_rbac.py::_configure` and `test_persona_resolver.py` already
use. `app.core.rbac._persona_resolver` is process-lifetime, set-once module
state (D-06) -- the autouse `_reset_rbac_state` fixture resets it to `None`
after every test in this file, so a leaked stub can't corrupt whichever test
module pytest runs next.

Passing-path choice per check (all five stay on the fast, non-raising
branch for all `ITERATIONS` calls):
- `org_access` -- persona `"cio"`.
- `program_visibility` -- passes unconditionally (open-aggregate, D-03); no
  resolver involved, `rbac.configure()` is not even called for this test.
- `individual_usage_visibility` -- the NON-self, persona=`"cio"` path,
  deliberately, not the self path. The self path
  (`target_user_id == current_user.user_id`) returns before any persona
  resolution runs at all (see `rbac.py`'s own docstring), so timing it would
  measure almost nothing and hide the persona-resolution cost the 5ms
  budget is actually about -- a vacuous pass. TC-26's own `steps`/
  `preconditions` do not name a specific requester/target relationship,
  only that "a stub persona resolver returns immediately ... for checks
  that resolve persona", which this path honors -- no discrepancy with the
  TC's literal wording.
- `member_in_program_visibility` -- non-self, persona `"cio"`, so both the
  `program_visibility` cascade (FR-4, always runs first) and persona
  resolution are inside the timed window.
- `governance_visibility` -- persona `"architect"` (in `_GOVERNANCE_
  PERSONAS`) WITH a `program_id` supplied, so the persona gate and the
  `program_visibility` cascade are both timed.

Logging cost is part of the timed window, not excluded: `org_access` and
`governance_visibility` emit an `authorized`-outcome log record on every
passing call (D-02); `individual_usage_visibility` and `member_in_program_
visibility`'s `*_view_denied` events are denial-only and so do NOT fire on
the passing paths measured here; `program_visibility` emits no event at
all (FR-2 closing note, TC-28). Where a log call does fire, the
`production_logging` fixture (copied from `test_persona_resolver_perf.py::
production_logging` -- same rationale, restore mechanics, and JSON-stdout
`configure_logging()` setup) ensures it actually formats and writes rather
than short-circuiting at `Logger.isEnabledFor(INFO)` with no handler
attached, so the measured numbers include the real cost a deployed process
pays per check.

No I/O occurs during any measured call: every persona resolution here is
served by the local stub (no DB session, no HTTP client is imported by this
file at all), satisfying TC-26's own "No I/O or external call occurs during
any measured call" expected result structurally, not by mock/spy assertion.

No warm-up prefix: TC-26's own `steps` specify exactly `ITERATIONS`
consecutive *measured* calls, with no separate warmup phase (unlike
`test_range_pagination_perf.py`'s 5-request warmup -- legitimate precedent
only where a test's own steps call for one).

Honest measurement: if any budget breaches, that is reported as a finding
with the measured number -- not hidden by loosening the budget, adding
unrequested warm-up iterations, stubbing out the logger, or reducing the
iteration count.
"""

from __future__ import annotations

import logging
import math
import time
from collections.abc import Awaitable, Callable, Iterator
from typing import cast

import pytest

from app.core import rbac
from app.core.auth import CurrentUser
from app.core.logging import configure_logging
from app.core.persona_resolver import PersonaResolver

# AUTH-03-TC-26 test_data -- do not relax.
ITERATIONS = 100
P95_BUDGET_MS = 5.0


@pytest.fixture
def production_logging() -> Iterator[None]:
    """Configure the same JSON-stdout logging `create_app()` sets up at
    import time (`app/core/logging.py::configure_logging`), then restore the
    previous root-logger state so this doesn't leak into other test files
    sharing this pytest session.

    Copied from `test_persona_resolver_perf.py::production_logging` --
    identical rationale: without a real handler attached, an INFO-level
    call short-circuits at `Logger.isEnabledFor(INFO)` before any
    formatting or I/O, understating what a deployed process actually pays.
    Level is forced to INFO explicitly (not left to `settings.log_level`)
    so the measurement is deterministic regardless of a local `.env`'s
    `LOG_LEVEL` override.
    """
    root = logging.getLogger()
    original_handlers = root.handlers[:]
    original_level = root.level
    configure_logging()
    root.setLevel(logging.INFO)
    try:
        yield
    finally:
        root.handlers = original_handlers
        root.setLevel(original_level)


@pytest.fixture(autouse=True)
def _reset_rbac_state() -> Iterator[None]:
    """`app.core.rbac._persona_resolver` is process-lifetime, set-once
    module state (D-06) -- reset to `None` after every test in this file so
    a leaked stub can't corrupt whichever test module pytest runs next.
    """
    yield
    rbac._persona_resolver = None


def _percentile(sorted_values_ms: list[float], pct: float) -> float:
    """Nearest-rank percentile over an already-sorted list, in milliseconds.

    index = ceil(pct * N) - 1 -- copied from
    `test_persona_resolver_perf.py::_percentile` /
    `test_range_pagination_perf.py::_percentile` (same deterministic,
    dependency-free method; no numpy/statistics.quantiles interpolation
    ambiguity to document).
    """
    n = len(sorted_values_ms)
    rank = math.ceil(pct * n)
    return sorted_values_ms[rank - 1]


class _StubPersonaResolver:
    """Minimal local stub -- returns a fixed persona immediately, no I/O.

    Not imported from `tests/unit/test_rbac.py`, a sibling file under
    concurrent edit (see module docstring).
    """

    def __init__(self, persona: str) -> None:
        self._persona = persona

    async def resolve(self, role: str) -> str:
        return self._persona


def _build_current_user(*, user_id: str = "u-1", role: str = "developer") -> CurrentUser:
    return CurrentUser(user_id=user_id, email="user@example.com", role=role, groups=[], programs=[])


async def _measure_p95_ms(run_once: Callable[[], Awaitable[None]]) -> float:
    """Run `run_once` `ITERATIONS` times, return the p95 latency in ms.

    Shared by all five tests below -- each measured loop is structurally
    identical (time a no-arg async call, ITERATIONS times, take p95); only
    the check-specific setup (stub persona, CurrentUser, arguments) differs
    per test, which stays inline in each test function.
    """
    latencies_ms: list[float] = []
    for _ in range(ITERATIONS):
        started = time.perf_counter()
        await run_once()
        elapsed_ms = (time.perf_counter() - started) * 1000
        latencies_ms.append(elapsed_ms)
    latencies_ms.sort()
    return _percentile(latencies_ms, 0.95)


def _budget_message(check_name: str, p95: float) -> str:
    return (
        f"{check_name} p95 latency {p95:.4f}ms exceeded the AUTH-03-TC-26 / "
        f"NFR-performance budget of {P95_BUDGET_MS}ms across {ITERATIONS} calls "
        "on a passing, in-process, no-I/O path. Do not relax this budget or "
        "exclude the log call to get under the line; investigate a real "
        "regression."
    )


@pytest.mark.asyncio
@pytest.mark.usefixtures("production_logging")
async def test_org_access_p95_under_5ms_tc26() -> None:
    """AUTH-03-TC-26: `org_access`, persona `"cio"` (passing path).

    Persona resolution and the `rbac_check_org_access` authorized-outcome
    log call are both inside the timed window.
    """
    stub = _StubPersonaResolver(persona="cio")
    rbac.configure(cast(PersonaResolver, stub))
    current_user = _build_current_user(user_id="u-cio-1", role="cio")

    p95 = await _measure_p95_ms(lambda: rbac.org_access(current_user))

    assert p95 < P95_BUDGET_MS, _budget_message("org_access", p95)


@pytest.mark.asyncio
@pytest.mark.usefixtures("production_logging")
async def test_program_visibility_p95_under_5ms_tc26() -> None:
    """AUTH-03-TC-26: `program_visibility` passes unconditionally (D-03) --
    no resolver involved, `rbac.configure()` is not called for this test.
    """
    current_user = _build_current_user(user_id="u-100")

    p95 = await _measure_p95_ms(lambda: rbac.program_visibility(current_user, "prog-1"))

    assert p95 < P95_BUDGET_MS, _budget_message("program_visibility", p95)


@pytest.mark.asyncio
@pytest.mark.usefixtures("production_logging")
async def test_individual_usage_visibility_p95_under_5ms_tc26() -> None:
    """AUTH-03-TC-26: `individual_usage_visibility`, NON-self, persona
    `"cio"` -- see module docstring for why the self path is not measured
    here (it would short-circuit before persona resolution and understate
    the real cost).
    """
    stub = _StubPersonaResolver(persona="cio")
    rbac.configure(cast(PersonaResolver, stub))
    current_user = _build_current_user(user_id="u-cio-2", role="cio")

    p95 = await _measure_p95_ms(
        lambda: rbac.individual_usage_visibility(current_user, "u-target-1")
    )

    assert p95 < P95_BUDGET_MS, _budget_message("individual_usage_visibility", p95)


@pytest.mark.asyncio
@pytest.mark.usefixtures("production_logging")
async def test_member_in_program_visibility_p95_under_5ms_tc26() -> None:
    """AUTH-03-TC-26: `member_in_program_visibility`, non-self, persona
    `"cio"` -- both the `program_visibility` cascade (FR-4) and persona
    resolution are inside the timed window.
    """
    stub = _StubPersonaResolver(persona="cio")
    rbac.configure(cast(PersonaResolver, stub))
    current_user = _build_current_user(user_id="u-cio-3", role="cio")

    p95 = await _measure_p95_ms(
        lambda: rbac.member_in_program_visibility(current_user, "prog-1", "u-target-2")
    )

    assert p95 < P95_BUDGET_MS, _budget_message("member_in_program_visibility", p95)


@pytest.mark.asyncio
@pytest.mark.usefixtures("production_logging")
async def test_governance_visibility_p95_under_5ms_tc26() -> None:
    """AUTH-03-TC-26: `governance_visibility`, persona `"architect"` (in
    `_GOVERNANCE_PERSONAS`) WITH a `program_id`, so both the persona gate
    and the `program_visibility` cascade are inside the timed window.
    """
    stub = _StubPersonaResolver(persona="architect")
    rbac.configure(cast(PersonaResolver, stub))
    current_user = _build_current_user(user_id="u-arch-1", role="architect")

    p95 = await _measure_p95_ms(lambda: rbac.governance_visibility(current_user, "prog-1"))

    assert p95 < P95_BUDGET_MS, _budget_message("governance_visibility", p95)
