"""`.harness/program.yaml` parser + `workspace_root` resolver (ING-04 · T-06).

Per D-04, `.harness/program.yaml` is the ONLY source for `files[]` and
`artifacts{}`. `.harness/profile.yaml` is IDENTITY ONLY and MUST NOT be read
here — there is no fallback branch. The path is hard-coded to
`<workspace_root>/.harness/program.yaml`; a missing file raises
`ProgramYamlError` before any HTTP attempt (FR-4).

YAML is loaded via `yaml.safe_load` (NEVER `yaml.load`) per NFR-Security — no
arbitrary Python object construction. Every user-controlled string parsed out
of the YAML (glob patterns and JSON key/field names) is passed through the
FR-7 / FR-8 allowlist BEFORE it can reach filesystem or JSON traversal code.

Non-goals kept intentionally: this module does NOT walk `files[]`, does NOT
open any file referenced by `path`/`glob`/`field`, and does NOT log. Source
resolution + counting is T-07's job.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml

from agentrise_mcp.core.allowlist import AllowlistError, validate_glob, validate_json_key

__all__ = [
    "ActivityFileSource",
    "ArtifactSource",
    "Program",
    "ProgramYamlError",
    "load_program",
    "resolve_workspace_root",
]

# The 5 canonical `ProgramArtifact.type` slugs (REQUIREMENTS.md FR-3 · api.md).
_CANONICAL_ARTIFACT_TYPES: frozenset[str] = frozenset(
    {"prd", "user_story", "test_case", "arch_diagram", "api_spec"}
)

# The 4 source-kind vocabulary values documented in `.harness/program.yaml`.
_ALLOWED_SOURCE_KINDS: frozenset[str] = frozenset(
    {"glob-count", "json-key-count", "json-field-sum", "constant"}
)

_ProgramYamlPath = ".harness/program.yaml"


class ProgramYamlError(Exception):
    """Raised on any failure to resolve `workspace_root` or parse `program.yaml`."""


@dataclass(frozen=True)
class ActivityFileSource:
    """One entry from `program.yaml::files[]` — a path pattern under workspace_root."""

    path: str
    kind: str = "activity"
    mode: str = "append"


@dataclass(frozen=True)
class ArtifactSource:
    """One entry from `program.yaml::artifacts.<canonical_type>` — how to count it."""

    kind: Literal["glob-count", "json-key-count", "json-field-sum", "constant"]
    path: str | None = None
    glob: str | None = None
    exclude: tuple[str, ...] = ()
    field: str | None = None
    value: int | None = None


@dataclass(frozen=True)
class Program:
    program_id: str
    team: tuple[str, ...]
    activity_files: tuple[ActivityFileSource, ...]
    artifacts: dict[str, ArtifactSource] = field(default_factory=dict)
    workspace_root: Path = field(default_factory=Path)


def resolve_workspace_root(workspace_root: str | Path | None) -> Path:
    """Resolve the caller-supplied `workspace_root` (FR-4).

    - `None` → process CWD.
    - `.resolve(strict=True)` — must exist on disk.
    - Must contain a `.harness/program.yaml` regular file.

    Raises `ProgramYamlError` on any failure. Returns an absolute `Path`.
    """
    raw = Path(workspace_root) if workspace_root is not None else Path.cwd()
    try:
        resolved = raw.resolve(strict=True)
    except FileNotFoundError as exc:
        raise ProgramYamlError(
            f"workspace_root does not exist: {os.fspath(raw)!r}"
        ) from exc

    program_yaml = resolved / _ProgramYamlPath
    if not program_yaml.is_file():
        raise ProgramYamlError(
            f"program.yaml not found at {os.fspath(program_yaml)!r} — "
            "expected .harness/program.yaml under workspace_root (D-04)."
        )

    return resolved


def load_program(workspace_root: str | Path | None = None) -> Program:
    """Resolve `workspace_root`, read `<workspace_root>/.harness/program.yaml`, validate.

    Raises `ProgramYamlError` on: missing file, unparseable YAML, missing
    `programId`, missing `team`, unknown top-level artifact key (must be one
    of the 5 canonical `ProgramArtifact.type` slugs), unknown source `kind`,
    or any allowlist rejection of a glob / JSON key parsed out of the file.
    """
    resolved_root = resolve_workspace_root(workspace_root)
    program_yaml_path = resolved_root / _ProgramYamlPath

    try:
        raw_text = program_yaml_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ProgramYamlError(
            f"failed to read program.yaml at {os.fspath(program_yaml_path)!r}: {exc}"
        ) from exc

    try:
        doc = yaml.safe_load(raw_text)
    except yaml.YAMLError as exc:
        # Covers yaml.constructor.ConstructorError (blocked tags) + parse errors.
        raise ProgramYamlError(
            f"failed to parse program.yaml at {os.fspath(program_yaml_path)!r}: {exc}"
        ) from exc

    if not isinstance(doc, dict):
        raise ProgramYamlError(
            f"program.yaml root must be a mapping, got {type(doc).__name__}"
        )

    program_id = doc.get("programId")
    if not isinstance(program_id, str) or not program_id:
        raise ProgramYamlError("program.yaml is missing required 'programId' (string)")

    raw_team = doc.get("team")
    if not isinstance(raw_team, list) or not raw_team:
        raise ProgramYamlError(
            "program.yaml is missing required 'team' (non-empty list)"
        )
    team = tuple(_extract_team_emails(raw_team))

    activity_files = tuple(_parse_files(doc.get("files")))
    artifacts = _parse_artifacts(doc.get("artifacts"))

    return Program(
        program_id=program_id,
        team=team,
        activity_files=activity_files,
        artifacts=artifacts,
        workspace_root=resolved_root,
    )


def _extract_team_emails(raw_team: list[Any]) -> list[str]:
    emails: list[str] = []
    for idx, entry in enumerate(raw_team):
        if not isinstance(entry, dict):
            raise ProgramYamlError(
                f"program.yaml::team[{idx}] must be a mapping, got {type(entry).__name__}"
            )
        email = entry.get("email")
        if not isinstance(email, str) or not email:
            raise ProgramYamlError(
                f"program.yaml::team[{idx}] is missing required 'email' (string)"
            )
        emails.append(email)
    return emails


def _parse_files(raw_files: Any) -> list[ActivityFileSource]:
    if raw_files is None:
        return []
    if not isinstance(raw_files, list):
        raise ProgramYamlError(
            f"program.yaml::files must be a list, got {type(raw_files).__name__}"
        )
    out: list[ActivityFileSource] = []
    for idx, entry in enumerate(raw_files):
        if not isinstance(entry, dict):
            raise ProgramYamlError(
                f"program.yaml::files[{idx}] must be a mapping, got {type(entry).__name__}"
            )
        path = entry.get("path")
        if not isinstance(path, str) or not path:
            raise ProgramYamlError(
                f"program.yaml::files[{idx}] is missing required 'path' (string)"
            )
        try:
            validate_glob(path)
        except AllowlistError as exc:
            raise ProgramYamlError(
                f"program.yaml::files[{idx}].path rejected by allowlist: {exc}"
            ) from exc
        kind = entry.get("kind", "activity")
        mode = entry.get("mode", "append")
        if not isinstance(kind, str) or not isinstance(mode, str):
            raise ProgramYamlError(
                f"program.yaml::files[{idx}] 'kind' and 'mode' must be strings"
            )
        out.append(ActivityFileSource(path=path, kind=kind, mode=mode))
    return out


def _parse_artifacts(raw_artifacts: Any) -> dict[str, ArtifactSource]:
    if raw_artifacts is None:
        return {}
    if not isinstance(raw_artifacts, dict):
        raise ProgramYamlError(
            f"program.yaml::artifacts must be a mapping, got {type(raw_artifacts).__name__}"
        )
    out: dict[str, ArtifactSource] = {}
    for canonical_type, entry in raw_artifacts.items():
        if canonical_type not in _CANONICAL_ARTIFACT_TYPES:
            raise ProgramYamlError(
                f"program.yaml::artifacts contains unknown canonical type "
                f"{canonical_type!r} — must be one of {sorted(_CANONICAL_ARTIFACT_TYPES)}"
            )
        if not isinstance(entry, dict):
            raise ProgramYamlError(
                f"program.yaml::artifacts.{canonical_type} must be a mapping, "
                f"got {type(entry).__name__}"
            )
        out[canonical_type] = _parse_artifact_source(canonical_type, entry)
    return out


def _parse_artifact_source(canonical_type: str, entry: dict[str, Any]) -> ArtifactSource:
    kind = entry.get("kind")
    if kind not in _ALLOWED_SOURCE_KINDS:
        raise ProgramYamlError(
            f"program.yaml::artifacts.{canonical_type} has unknown source kind "
            f"{kind!r} — must be one of {sorted(_ALLOWED_SOURCE_KINDS)}"
        )

    path = entry.get("path")
    glob = entry.get("glob")
    field_name = entry.get("field")
    value = entry.get("value")
    raw_exclude = entry.get("exclude")

    if path is not None:
        if not isinstance(path, str):
            raise ProgramYamlError(
                f"program.yaml::artifacts.{canonical_type}.path must be a string"
            )
        try:
            validate_glob(path)
        except AllowlistError as exc:
            raise ProgramYamlError(
                f"program.yaml::artifacts.{canonical_type}.path rejected by allowlist: {exc}"
            ) from exc

    if glob is not None:
        if not isinstance(glob, str):
            raise ProgramYamlError(
                f"program.yaml::artifacts.{canonical_type}.glob must be a string"
            )
        try:
            validate_glob(glob)
        except AllowlistError as exc:
            raise ProgramYamlError(
                f"program.yaml::artifacts.{canonical_type}.glob rejected by allowlist: {exc}"
            ) from exc

    if field_name is not None:
        if not isinstance(field_name, str):
            raise ProgramYamlError(
                f"program.yaml::artifacts.{canonical_type}.field must be a string"
            )
        try:
            validate_json_key(field_name)
        except AllowlistError as exc:
            raise ProgramYamlError(
                f"program.yaml::artifacts.{canonical_type}.field rejected by allowlist: {exc}"
            ) from exc

    exclude_tuple: tuple[str, ...] = ()
    if raw_exclude is not None:
        if not isinstance(raw_exclude, list):
            raise ProgramYamlError(
                f"program.yaml::artifacts.{canonical_type}.exclude must be a list"
            )
        for i, item in enumerate(raw_exclude):
            if not isinstance(item, str):
                raise ProgramYamlError(
                    f"program.yaml::artifacts.{canonical_type}.exclude[{i}] must be a string"
                )
            # `exclude` on glob-count / json-field-sum holds glob patterns; on
            # json-key-count it holds JSON key names. Validate against the
            # kind's own allowlist.
            try:
                if kind == "json-key-count":
                    validate_json_key(item)
                else:
                    validate_glob(item)
            except AllowlistError as exc:
                raise ProgramYamlError(
                    f"program.yaml::artifacts.{canonical_type}.exclude[{i}] "
                    f"rejected by allowlist: {exc}"
                ) from exc
        exclude_tuple = tuple(raw_exclude)

    if value is not None and not isinstance(value, int):
        raise ProgramYamlError(
            f"program.yaml::artifacts.{canonical_type}.value must be an integer"
        )

    return ArtifactSource(
        kind=kind,  # type: ignore[arg-type]
        path=path,
        glob=glob,
        exclude=exclude_tuple,
        field=field_name,
        value=value,
    )
