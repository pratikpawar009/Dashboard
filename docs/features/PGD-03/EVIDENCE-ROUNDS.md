| Round | FAILing dims | Action                                                                 | Result       |
|-------|--------------|-------------------------------------------------------------------------|--------------|
| 1     | typecheck    | Widened `_release_row`'s `day_offset` param from `int` to `int \| float` in `services/api/tests/unit/test_program_releases_service.py` (TC-04 packs 40 releases across a fractional day-offset spread; `timedelta(days=...)` already accepts float — the test's own data intent needed the wider type, not a narrowed test) | typecheck ✓ |
