"""Public export surface for `app.utils` — display formatting helpers.

Callers import from `app.utils` without knowing the internal file grouping
(format.py today). `format_number` and `format_duration` are the full public
surface; `format.py` defines no module-level constants to omit, unlike
`app.dependencies` (see that package's `__init__.py` for the precedent on
documenting deliberate omissions per `.claude/rules/reusability-baseline.md`,
"public APIs are intentional").
"""

from app.utils.format import format_duration, format_number

__all__ = [
    "format_duration",
    "format_number",
]
