"""ING-04 · T-06 tests: `workspace_root` resolver + `.harness/program.yaml` parser.

Covers FR-4 (workspace_root resolution table), D-04 (single-source `program.yaml`,
no fallback to `profile.yaml`), and the allowlist wiring for every user-controlled
string parsed out of the file (FR-7 / FR-8 via T-03).

Notes on schema mapping (surfaced as a note in the T-06 return): the task-spec
dataclass names (`type`, `pattern`, `file`, `key`) are stale — carried over from
pre-D-04 planning. The REAL `.harness/program.yaml` (repo root) and the T-01
`tmp_program_yaml` conftest fixture both use `kind` (hyphenated: `glob-count`,
`json-key-count`, `json-field-sum`, `constant`) with fields `path`/`glob`/`exclude`
/`field`/`value`, and `files[]` uses `path`. tasks.json F-16 confirms the
dispatcher looks up `entry['kind']` against `"glob-count"` etc. — so the parser
matches reality, not the stale contract.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from agentrise_mcp.core.profile import (
    ActivityFileSource,
    ArtifactSource,
    Program,
    ProgramYamlError,
    load_program,
    resolve_workspace_root,
)


def _write_program_yaml(root: Path, payload: dict | str) -> Path:
    harness = root / ".harness"
    harness.mkdir(exist_ok=True)
    p = harness / "program.yaml"
    if isinstance(payload, str):
        p.write_text(payload)
    else:
        p.write_text(yaml.safe_dump(payload, sort_keys=False))
    return p


def _valid_payload() -> dict:
    return {
        "programId": "test-prog",
        "team": [{"email": "dev@example.test", "name": "Dev", "role": "dev"}],
        "files": [{"path": "docs/activity/activity.jsonl", "kind": "activity", "mode": "append"}],
        "artifacts": {
            "prd": {"kind": "glob-count", "path": "docs/prd", "glob": "*.md"},
            "user_story": {"kind": "constant", "value": 0},
        },
    }


# ─── resolve_workspace_root ──────────────────────────────────────────────────


def test_resolve_workspace_root_none_uses_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_program_yaml(tmp_path, _valid_payload())
    monkeypatch.chdir(tmp_path)
    resolved = resolve_workspace_root(None)
    assert resolved == tmp_path.resolve()


def test_resolve_workspace_root_nonexistent_raises() -> None:
    with pytest.raises(ProgramYamlError) as exc:
        resolve_workspace_root("/no/such/path/agentrise-test")
    assert "does not exist" in str(exc.value)


def test_resolve_workspace_root_missing_program_yaml_raises(tmp_path: Path) -> None:
    # tmp_path exists but has no `.harness/program.yaml`.
    with pytest.raises(ProgramYamlError) as exc:
        resolve_workspace_root(tmp_path)
    assert "program.yaml not found" in str(exc.value)


def test_resolve_workspace_root_accepts_str_and_path(tmp_path: Path) -> None:
    _write_program_yaml(tmp_path, _valid_payload())
    assert resolve_workspace_root(tmp_path) == tmp_path.resolve()
    assert resolve_workspace_root(str(tmp_path)) == tmp_path.resolve()


# ─── load_program — happy path ───────────────────────────────────────────────


def test_load_program_happy_path(tmp_program_yaml: Path) -> None:
    root = tmp_program_yaml.parent.parent
    program = load_program(root)

    assert isinstance(program, Program)
    assert program.program_id == "test-program"
    assert program.team == ("dev@example.test",)
    assert len(program.activity_files) == 1
    assert isinstance(program.activity_files[0], ActivityFileSource)
    assert program.activity_files[0].path == "docs/activity/activity.jsonl"
    assert "prd" in program.artifacts
    assert isinstance(program.artifacts["prd"], ArtifactSource)
    assert program.artifacts["prd"].kind == "glob-count"
    assert program.workspace_root == root.resolve()


def test_load_program_with_str_workspace_root(tmp_program_yaml: Path) -> None:
    root = tmp_program_yaml.parent.parent
    program = load_program(str(root))
    assert program.program_id == "test-program"


# ─── validation rejections ───────────────────────────────────────────────────


def test_load_program_rejects_unknown_source_kind(tmp_path: Path) -> None:
    payload = _valid_payload()
    payload["artifacts"] = {"prd": {"kind": "wut", "value": 3}}
    _write_program_yaml(tmp_path, payload)
    with pytest.raises(ProgramYamlError) as exc:
        load_program(tmp_path)
    msg = str(exc.value)
    assert "'wut'" in msg
    assert "unknown source kind" in msg


def test_load_program_rejects_unknown_canonical_type(tmp_path: Path) -> None:
    payload = _valid_payload()
    payload["artifacts"] = {"invented_thing": {"kind": "constant", "value": 3}}
    _write_program_yaml(tmp_path, payload)
    with pytest.raises(ProgramYamlError) as exc:
        load_program(tmp_path)
    assert "invented_thing" in str(exc.value)


def test_load_program_rejects_bad_glob_in_files(tmp_path: Path) -> None:
    payload = _valid_payload()
    payload["files"] = [{"path": "../secrets", "kind": "activity", "mode": "append"}]
    _write_program_yaml(tmp_path, payload)
    with pytest.raises(ProgramYamlError) as exc:
        load_program(tmp_path)
    assert "rejected by allowlist" in str(exc.value)


def test_load_program_rejects_bad_glob_in_artifacts(tmp_path: Path) -> None:
    payload = _valid_payload()
    payload["artifacts"] = {
        "prd": {"kind": "glob-count", "path": "docs/prd", "glob": "../*.md"},
    }
    _write_program_yaml(tmp_path, payload)
    with pytest.raises(ProgramYamlError) as exc:
        load_program(tmp_path)
    assert "rejected by allowlist" in str(exc.value)


def test_load_program_rejects_bad_json_field(tmp_path: Path) -> None:
    payload = _valid_payload()
    payload["artifacts"] = {
        "test_case": {
            "kind": "json-field-sum",
            "path": "docs/test-cases",
            "glob": "*.json",
            "field": "$.bad",
        },
    }
    _write_program_yaml(tmp_path, payload)
    with pytest.raises(ProgramYamlError) as exc:
        load_program(tmp_path)
    assert "rejected by allowlist" in str(exc.value)


def test_load_program_rejects_bad_json_exclude_key(tmp_path: Path) -> None:
    payload = _valid_payload()
    payload["artifacts"] = {
        "user_story": {
            "kind": "json-key-count",
            "path": "docs/state/features.json",
            "exclude": ["$.evil"],
        },
    }
    _write_program_yaml(tmp_path, payload)
    with pytest.raises(ProgramYamlError) as exc:
        load_program(tmp_path)
    assert "rejected by allowlist" in str(exc.value)


# ─── partial payload / no-fallback / safe-load ───────────────────────────────


def test_load_program_partial_artifacts_ok(tmp_path: Path) -> None:
    payload = _valid_payload()
    payload["artifacts"] = {
        "prd": {"kind": "glob-count", "path": "docs/prd", "glob": "*.md"},
        "test_case": {"kind": "constant", "value": 0},
    }
    _write_program_yaml(tmp_path, payload)
    program = load_program(tmp_path)
    assert set(program.artifacts.keys()) == {"prd", "test_case"}


def test_load_program_no_fallback_to_profile_yaml(tmp_path: Path) -> None:
    # D-04: a valid `.harness/profile.yaml` MUST NOT satisfy `load_program`.
    harness = tmp_path / ".harness"
    harness.mkdir()
    (harness / "profile.yaml").write_text(
        yaml.safe_dump({"email": "dev@example.test", "name": "Dev", "role": "dev"})
    )
    with pytest.raises(ProgramYamlError) as exc:
        load_program(tmp_path)
    assert "program.yaml not found" in str(exc.value)


def test_load_program_safe_load_rejects_python_object(tmp_path: Path) -> None:
    # `!!python/object/apply:os.system` is blocked by safe_load; wrapped here.
    bad = (
        "programId: test\n"
        "team:\n"
        "  - email: dev@example.test\n"
        "artifacts:\n"
        "  prd: !!python/object/apply:os.system [\"ls\"]\n"
    )
    _write_program_yaml(tmp_path, bad)
    with pytest.raises(ProgramYamlError) as exc:
        load_program(tmp_path)
    assert "failed to parse" in str(exc.value)


# ─── extra required-field rejections (guardrails) ────────────────────────────


def test_load_program_rejects_missing_program_id(tmp_path: Path) -> None:
    payload = _valid_payload()
    del payload["programId"]
    _write_program_yaml(tmp_path, payload)
    with pytest.raises(ProgramYamlError) as exc:
        load_program(tmp_path)
    assert "programId" in str(exc.value)


def test_load_program_rejects_missing_team(tmp_path: Path) -> None:
    payload = _valid_payload()
    del payload["team"]
    _write_program_yaml(tmp_path, payload)
    with pytest.raises(ProgramYamlError) as exc:
        load_program(tmp_path)
    assert "team" in str(exc.value)
