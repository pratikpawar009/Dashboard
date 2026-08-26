---
name: scaffold-verification
description: Verify a freshly scaffolded project — 5 gates (install, typecheck, lint, test smoke, run smoke), manifest-driven entrypoint detection, evidence-quoting report. Used by scaffold-agent.
user-invocable: false
---
# Scaffold verification

Goal: prove the scaffold actually compiles and runs before declaring it done. Green init means files exist; only this verify proves the project is alive.

## Discipline (read first)

- **No tech-specific hardcoding.** Detect entrypoints from the manifest the framework wrote (package.json scripts, pyproject.toml `[project.scripts]`, Cargo.toml `[[bin]]`, go main package).
- **Every PASS must quote the exact command and output.** No "PASS (done by agent)" — that is a fake pass and forbidden.
- **SKIP requires a concrete reason.** Only valid for: mobile native bundles (device required), IaC plan/apply (cloud account required). Web, server, CLI MUST run.
- **A failing entrypoint command is a failure**, not a SKIP. If `npm run web` exits non-zero, Run smoke = FAIL — even if the failure is a missing peer-dep. The error message is the user's actionable fix.

## Per-stack gate

For every framework in `docs/adr/0001-tech-stack.md` § Decision (Frameworks list), run these gates in order. **Stop on first failure.** Surface the exact command, exit code, and last 50 lines of output. If the ADR is missing, run `/arh-init` first.

### Gate 1 — Install

| package_manager | Command |
|---|---|
| pnpm | `pnpm install --frozen-lockfile=false` |
| npm | `npm install --no-audit --no-fund` |
| yarn | `yarn install --immutable=false` |
| bun | `bun install` |
| uv | `uv sync` |
| pip | `python -m venv .venv && .venv/bin/pip install -e .` |
| poetry | `poetry install` |
| go | `go mod download` |
| cargo | `cargo fetch` |
| gradle | `./gradlew --no-daemon dependencies` |
| maven | `mvn -B -q dependency:resolve` |
| dotnet | `dotnet restore` |

Time-box: 10 min per stack. Beyond that → fail with `INSTALL_TIMEOUT`.

### Gate 2 — Typecheck / compile

Read `docs/config/project-commands.yaml` and run `typecheck` for the stack. Examples:

| Stack family | Command |
|---|---|
| typescript | `pnpm tsc --noEmit` |
| python | `uv run mypy <pkg>` (or skip if no mypy and use `python -c "import <pkg>"`) |
| go | `go vet ./...` |
| rust | `cargo check` |
| java | `./gradlew --no-daemon compileJava` |
| dotnet | `dotnet build --no-restore` |

### Gate 3 — Lint

Run the stack's `lint` command. Pass when exit 0. With `--lint-strict`, also fail on any warning.

### Gate 4 — Test smoke

When `test_runner` is set, the scaffold-agent's playbook should have generated ONE placeholder test that proves the runner is wired:

| Test runner | Smoke test path | Expected output |
|---|---|---|
| jest / vitest | `<src>/smoke.test.ts` with `expect(1+1).toBe(2)` | 1 passed |
| pytest | `tests/test_smoke.py` with `assert 1+1 == 2` | 1 passed |
| go-test | `<pkg>/smoke_test.go` with `if 1+1 != 2 { t.Fatal() }` | PASS |
| junit | `src/test/.../SmokeTest.java` | 1 test passed |
| playwright | `tests/e2e/smoke.spec.ts` (just `expect(true).toBe(true)`, no browser yet) | 1 passed |

If no test runner declared → skip with `Test smoke: SKIP (no test_runner)`.

### Gate 5 — Run smoke (manifest-driven, no per-stack hardcoding)

Detect runtime entrypoints from the manifest the framework wrote. Try each detected entrypoint. Gate FAILS the moment any detected entrypoint exits non-zero.

#### Detection (in this order; first match wins, but try ALL declared entries)

| Manifest | Detection rule |
|---|---|
| `package.json` | Read `scripts` keys. Any of: `dev`, `start`, `serve`, `web`, `run`, `preview`. Try each via `<pm> run <key>`. |
| `pyproject.toml` | Read `[project.scripts]`. Try each entry as a CLI command. If `uvicorn`/`gunicorn` declared as dep, also try `uv run uvicorn $module:app` when an `app.main` / `main:app` module exists. |
| `Cargo.toml` | Read `[[bin]]`. Try `cargo run --bin <name>`. |
| `go.mod` | Try `go run .` if `main.go` or `cmd/*/main.go` exists. |
| `Dockerfile` | Try `docker build -t scaffold-smoke .` only (do NOT run a container blindly). |

Multiple entrypoints (e.g. `dev` AND `web`) → run each in turn. PASS only when ALL declared entrypoints boot.

#### Procedure (per entrypoint)

1. Allocate a free port (read from `--port` flag or pick ephemeral).
2. Spawn the command in a child process; capture stdout+stderr.
3. **5-second exit check**: if process exits within 5s with non-zero → **FAIL**. Capture the full stderr; surface the error message verbatim.
4. **Ready-signal poll**: tail logs up to 30s for any of: `Ready`, `Listening`, `Started`, `Application startup complete`, `running at`, `localhost:<port>`, port `LISTEN` via `lsof`. On match → continue.
5. **Health probe** (when port detected): `curl -fsS http://localhost:<port>/` — accept any HTTP status as proof the server bound. Connection refused → continue waiting up to 30s total.
6. **SIGTERM**, wait ≤5s, SIGKILL if needed.
7. Record `started_in_ms`, `final_log_line`, and either `http_status` or `not_probed`.

Time-box: 60s per entrypoint. Exceeds → `RUN_TIMEOUT` FAIL.

#### When SKIP is the only valid outcome

| Skip cause | Detection |
|---|---|
| Mobile native build (device required) | manifest declares `expo` / `react-native` AND no `web` script in `package.json scripts`. SKIP with `mobile-native (no web entry)`. |
| IaC plan/apply (cloud account required) | manifest is `*.tf` only, no other runtime entry. SKIP with `iac (cloud account required)`. |
| Test-runner-only stack | only entry is the test runner CLI (jest/playwright/maestro/cypress/pytest); already exercised by Gate 4. SKIP with `test-runner-only`. |

Crucially: if the manifest declares a runnable entry like `expo start --web`, IT IS NOT SKIPPABLE. Try it. If it fails (e.g. missing `react-dom` peer dep), report the error verbatim. The user's fix comes from the error message.

#### Anti-pattern to avoid

Reporting `Run smoke: SKIP` when the manifest has `scripts.web` or `scripts.dev` is **fake PASS**. The agent must run those entries. If the agent did not run them, the gate is FAIL with `not-attempted`.

#### Reporting discipline

Every line in the verify report MUST quote the actual command + outcome:

```
✓ [web] install   PASS   `pnpm install`            (412 packages, 38.2s)
✓ [web] typecheck PASS   `pnpm tsc --noEmit`       (0 errors)
✓ [web] lint      PASS   `pnpm eslint .`           (3 warnings)
✓ [web] test      PASS   `pnpm vitest run`         (1/1, 0.9s)
⨯ [web] run       FAIL   `pnpm next dev -p 3001`   exit=1
        stderr last 5 lines:
          CommandError: missing peer deps react-dom@19.2.0, react-native-web@^0.21.0
          Suggested fix: npx expo install react-dom react-native-web
```

A bare `PASS  (done by scaffold-agent)` is NOT acceptable output.

## Idempotency

Re-runnable. Subsequent invocations are faster because installs are cached.

## On failure

- Surface: `[<stack-id>] <gate>: FAIL exit=<code>`
- Last 50 lines of stdout/stderr.
- 1-line diagnosis when known:
  - `EADDRINUSE` → "Port collision; pass --skip-run-smoke or change <port>."
  - `command not found` → "Tool <X> not on PATH. Install it then retry."
  - `mypy: cannot find module` → "Run install gate first; missing site-packages."
- Do NOT auto-rollback. Leave files in place; user inspects.

## Flags

- `--skip-install` — assume deps already installed (CI cache).
- `--skip-run-smoke` — only Gates 1–4.
- `--lint-strict` — fail Gate 3 on warnings.
- `--port <N>` — pin the run-smoke port (default: ephemeral).

## Output

```
SCAFFOLD VERIFY
──────────────────────────────
[web]      install   PASS   (412 packages, 38.2s)
[web]      typecheck PASS
[web]      lint      PASS   (3 warnings)
[web]      test      PASS   (1/1)
[web]      run       PASS   (Ready in 1.4s, GET / 200)
[api]      install   PASS   (87 packages, 4.1s)
[api]      typecheck PASS
[api]      lint      PASS
[api]      test      PASS   (1/1)
[api]      run       PASS   (startup 0.9s, GET /docs 200)
[e2e]      install   PASS   (playwright bundled)
[e2e]      typecheck PASS
[e2e]      lint      SKIP   (no lint command for stack)
[e2e]      test      PASS   (1/1)
[e2e]      run       SKIP   (test-automation stack)

ALL GATES GREEN
```
