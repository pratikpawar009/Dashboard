# Phase 0 — Brownfield check

Goal: refuse to overwrite an existing project unless the user passes `--force`.

## Detection

A repo is **brownfield** if any of:

- Manifest exists for any declared stack (`package.json`, `pyproject.toml`, `go.mod`, `Cargo.toml`, `pom.xml`, `build.gradle`, `*.csproj`).
- `.git` exists with commit count > 5.
- A source directory matching the stack's `paths` glob has >10 files.

## Behaviour

| State | Without `--force` | With `--force` |
|---|---|---|
| Greenfield (no manifests, fresh repo) | Proceed | Proceed |
| Brownfield | **Stop**: print detected manifests + suggest `/arh-init` instead. | Proceed; show diff per file before overwrite, ask per-file confirmation. |

## Output

```
SCAFFOLD PRECHECK
─────────────────
Manifests detected: <list> | none
Existing source dirs: <list>
Mode: greenfield | brownfield
```

If brownfield without `--force`, exit with: `Use /arh-init to initialise harness state for an existing project. /arh-scaffold is for empty projects.`
