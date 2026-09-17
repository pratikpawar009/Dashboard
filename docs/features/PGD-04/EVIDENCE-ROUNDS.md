# PGD-04 — Evidence pass rounds

| Round | FAILing dims | Action | Result |
|-------|--------------|--------|--------|
| 1 | typecheck (api) | `_usage_event_row`'s `idx` param in `tests/unit/test_program_commands_service.py` was typed `int`, but every call site passes an f-string label (`f"recent-{days_ago}"`, etc.) used only to build a unique `session_id` — mypy correctly flagged the annotation/usage mismatch. Root cause: annotation too narrow for its only real use. Fix: widened `idx: int` → `idx: int | str` (matches every actual call site; no call site or assertion changed). | typecheck (api) ✓ — 0 errors, 168 files |

Full six-dimension packet reached PASS/accepted-N/A on round 1's re-run — no round 2 needed.
