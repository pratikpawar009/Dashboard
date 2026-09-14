"""Static-code guard for `app/services/ingest_artifacts.py` -- D-03 /
ADR-0012 non-applicability (ING-03 T-10 / F-16).

ADR-0012 (`rebuild_org_rollups()` runs out-of-band via
`BackgroundTasks`) applies ONLY to `kind="activity"`. `program_artifacts`
is a leaf counts table with no rollup source relationship -- nothing
under `services/api/app/services/rollup_rebuild.py` reads it. A
well-meaning future contributor copying `activity_ingest.py`'s signature
(which takes `on_org_rebuild: Callable[[], None]`) into
`ingest_artifacts.py` would silently break the D-03 contract; a runtime
assertion is unreliable because the copied code compiles and runs.

This module makes the D-03 structural contract explicit at test-collect
time via two static checks:

  1. `ast.parse(...)` walks `ingest_artifacts.py` for `ImportFrom` nodes
     and asserts NO import of `rebuild_program_rollups` or
     `rebuild_org_rollups` from `app.services.rollup_rebuild`.
  2. `inspect.signature(ingest_artifacts)` has no parameter named
     `on_org_rebuild`.

Both checks catch copy-paste from `activity_ingest.py` at the earliest
possible check -- before any request touches the code path.
"""

import ast
import inspect
from pathlib import Path

import app.services.ingest_artifacts as ingest_artifacts_module
from app.services.ingest_artifacts import ingest_artifacts

_MODULE_PATH = Path(ingest_artifacts_module.__file__)
_FORBIDDEN_ROLLUP_NAMES = frozenset({"rebuild_program_rollups", "rebuild_org_rollups"})


def _import_from_nodes(module_path: Path) -> list[ast.ImportFrom]:
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    return [node for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]


def test_module_does_not_import_rollup_rebuild_functions() -> None:
    """D-03 structural guard: `ingest_artifacts.py` MUST NOT import
    `rebuild_program_rollups` or `rebuild_org_rollups` from
    `app.services.rollup_rebuild`. A copy-paste from `activity_ingest.py`
    fails here immediately."""
    for node in _import_from_nodes(_MODULE_PATH):
        imported_names = {alias.name for alias in node.names}
        forbidden_hit = imported_names & _FORBIDDEN_ROLLUP_NAMES
        assert not forbidden_hit, (
            f"D-03 violated: ingest_artifacts.py imports {sorted(forbidden_hit)} "
            f"from {node.module!r}; the artifacts service MUST NOT dispatch "
            "rollup rebuilds (ADR-0012 non-applicability)."
        )


def test_module_does_not_import_from_rollup_rebuild_module() -> None:
    """Defence-in-depth: even a `from app.services.rollup_rebuild import *`
    is refused. The named check above catches the two current forbidden
    symbols; this catches the whole module by name."""
    for node in _import_from_nodes(_MODULE_PATH):
        assert node.module != "app.services.rollup_rebuild", (
            "D-03 violated: ingest_artifacts.py imports from "
            "'app.services.rollup_rebuild' -- the artifacts service must "
            "not depend on the rollup module at all."
        )


def test_ingest_artifacts_signature_has_no_on_org_rebuild_parameter() -> None:
    """D-03 structural guard (2/2): `ingest_artifacts()`'s public signature
    MUST NOT accept an `on_org_rebuild` parameter. A copy-paste of
    `activity_ingest.ingest_files`'s signature fails here immediately."""
    parameters = inspect.signature(ingest_artifacts).parameters
    assert "on_org_rebuild" not in parameters, (
        f"D-03 violated: ingest_artifacts() accepts an 'on_org_rebuild' "
        f"parameter (parameters: {list(parameters)}); the artifacts service "
        "MUST NOT dispatch rollup rebuilds."
    )
