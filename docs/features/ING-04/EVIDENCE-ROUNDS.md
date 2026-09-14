# Evidence rounds — ING-04

| Round | FAILing dims                     | Action                                                                                                                                                                                                                                                                          | Result                                      |
|-------|----------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|---------------------------------------------|
| 1     | typecheck, unit_tests, lint      | Baseline pass on a fresh `services/mcp-server/.venv` (D-01 venv isolation) — captured raw failures for full-picture triage before any fix.                                                                                                                                        | typecheck 2 errs, 1 unit fail, 8 lint errs |
| 2     | typecheck, unit_tests, lint      | `ruff --fix` autofix (11 issues); manual: add `import logging` in test_logging_no_token_leak.py (F821); wrap long signature in test_workspace_root_resolution.py (E501); fix http_client test to compare parsed JSON (httpx 0.28 dropped space-after-colon); refactor push_artifacts.py `except (AllowlistError, *_SOURCE_ERRORS)` to a pre-combined `_RESOLVER_EXCEPTIONS` tuple; annotate `body: dict[str, object]` for post_json's invariant dict type. | typecheck still FAIL (yaml stubs missing), unit/lint PASS |
| 3     | typecheck                        | Add `types-PyYAML>=6.0` to `services/mcp-server/pyproject.toml [project.optional-dependencies].dev`, install into the mcp-server venv. Real stubs, not a suppression.                                                                                                             | ALL PASS                                    |

## Root-cause summary (per fix)

- **`test_http_client_timeout_retry.py::test_post_json_success_first_attempt`** — cause: assertion compared raw JSON bytes (`b'{"hello": "world"}'`) which pinned httpx's serializer whitespace; symptom: httpx 0.28.1 (installed here) writes compact `b'{"hello":"world"}'`; mechanism: test over-specified serialization instead of the "sent as JSON" contract. Fix: `json.loads(sent.read()) == {"hello": "world"}`. Assertion is stronger — semantic equality, not whitespace-dependent.
- **mypy `push_artifacts.py:130` "Exception type must be derived from BaseException"** — cause: `except (AllowlistError, *_SOURCE_ERRORS)` starred-unpack in an `except` clause; symptom: mypy can't statically verify the runtime type of the flattened tuple; mechanism: PEP 646-style unpack in `except` is legal at runtime but not inferred; Fix: pre-combine `_RESOLVER_EXCEPTIONS: tuple[type[Exception], ...] = (AllowlistError, *_SOURCE_ERRORS)` at module scope and reference the concrete tuple in the except.
- **mypy `push_artifacts.py:168` "incompatible dict type"** — cause: unannotated dict literal `body = {...}` where values are `str | dict[str, int]`; symptom: mypy narrows to `dict[str, Collection[str]]` (invariant); mechanism: `dict` is invariant in its value type, and `post_json` expects `dict[str, object]`; Fix: annotate `body: dict[str, object] = {...}` at the assignment.
- **mypy `import-untyped` on `yaml`** — cause: PyYAML ships no runtime type stubs; symptom: mypy 2.3 flags `import-untyped` even with `ignore_missing_imports = true` (they are separate error codes); Fix: add real stubs via `types-PyYAML>=6.0`. Legitimate config, no suppression.
- **lint `F821 logging` in test_logging_no_token_leak.py** — cause: annotation `tuple[logging.Logger, io.StringIO]` referenced `logging` without importing it. Fix: `import logging`.
- **lint `E501` in test_workspace_root_resolution.py** — cause: single-line function signature 103 > 100 chars. Fix: wrap params onto multiple lines.
- **lint autofix (11 issues)** — UP037 (quoted `HttpClient` annotation → bare), UP017 (`timezone.utc` → `UTC`), UP035 (`typing.Callable` → `collections.abc.Callable`), F401 (unused `pytest` / `os` imports).

## Anti-suppression audit

- No `# noqa`, `# type: ignore`, `pytest.skip`, or `xfail` added.
- No assertion weakened. The `json.loads(...)` change is stronger (whitespace-invariant semantic comparison).
- No `except Exception` broadened. The refactor consolidates the same exception tuple at module scope.
- No test disabled. 126/126 unit tests pass in round 3 (round 1 was 125/126).
