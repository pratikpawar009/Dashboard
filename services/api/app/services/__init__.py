"""Public export surface for `app.services` — rollup + guardrail compute
functions.

Callers (routers, later stories) import from `app.services` without knowing
the internal file grouping (rollup_compute.py / guardrail_compute.py, split
per D-03 — see docs/features/BED-02/DECISIONS.md). `guardrail_compute.
PASSING_STATUS` is deliberately NOT re-exported here: it is an internal
formula detail of `compute_guardrail_summary` (which status counts toward
the numerator, per D-05), has no caller outside that function today, and no
name collision forced the decision either way — per
`.claude/rules/reusability-baseline.md` ("public APIs are intentional;
implementation details stay private"), it stays module-private until a
second caller actually needs it. Callers that need it can still import it
directly from `app.services.guardrail_compute`.
"""

from app.services.guardrail_compute import compute_guardrail_summary
from app.services.rollup_compute import (
    compute_adoption_percent,
    compute_average,
    compute_period_delta,
)

__all__ = [
    "compute_adoption_percent",
    "compute_average",
    "compute_guardrail_summary",
    "compute_period_delta",
]
