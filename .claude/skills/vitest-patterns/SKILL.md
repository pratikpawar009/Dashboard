---
name: vitest-patterns
description: vitest test patterns for this project — fill body with team test conventions. Used by validation/arh-implementation agents.
when_to_use: Writing or reviewing vitest tests.
user-invocable: false
allowed-tools: Read Write Edit Bash Grep Glob
---
# vitest Test Patterns

<!-- Harness scaffold: test-runner=vitest — STRUCTURE only; -->
<!-- Fill every CORE section. Under OPTIONAL, keep only what applies and DELETE the rest -->
<!-- (heading+slot) before filling. OPTIONAL slots are not lint-nagged; CORE TODO slots are. -->
<!-- Loaded by validation-agent (and implementation-agent for test code) when this runner is active. -->

## Verified facts

<!-- BEGIN VERIFIED FACTS -->
<!-- Owned by skill `deep-scan-verification` (/arh-init Phase 6) — `harness fill` never -->
<!-- edits between these markers. Empty until a brownfield deep scan approves facts here. -->
<!-- Each bullet ends in (see file:line); the file it cites is this fact's proof. -->
<!-- END VERIFIED FACTS -->

## Idioms

- Test files match `src/**/*.test.{ts,tsx}` (`apps/web/vitest.config.ts:14`) and import from `"vitest"` (`describe`, `expect`, `it`), not Jest globals (`apps/web/src/smoke.test.ts:1`).
- `describe` / `it` / `expect` structure, one `describe` block per unit under test (`apps/web/src/smoke.test.ts:3-7`) — no BDD alias usage (`context`/`suite`) evidenced.
- The `@` alias resolves the same in tests as in app code: `path.resolve(__dirname, "./src")` (`apps/web/vitest.config.ts:7-10`), matching `tsconfig.json`'s `@/* -> ./src/*`. Use `@/...` imports in tests, not deep relative paths.
- Only one test exists today (`apps/web/src/smoke.test.ts`) and it is a runner-wiring smoke test, not a component/unit test — there is no established colocation pattern (e.g. `Component.test.tsx` next to `Component.tsx`) yet since no components beyond `page.tsx`/`layout.tsx` exist. Follow Vitest's own default of colocating `*.test.tsx` beside the file it tests once real components land; do not invent a separate `__tests__/` convention without evidence.

## Test layering

- Environment is `jsdom` for all tests (`apps/web/vitest.config.ts:13`) — this is a single-tier unit/component config, no separate integration or E2E project is defined in `vitest.config.ts`.
- `docs/config/project-commands.yaml`: `test_integration` and `test_e2e` are explicitly empty — "not yet scaffolded" / "no e2e framework (Playwright/Cypress) declared in ADR-0001". Do not write integration/E2E-style tests against `vitest.config.ts` as it stands; it is wired for unit/component tests only.
- `test` / `test_unit` in `docs/config/project-commands.yaml` both resolve to `pnpm -C apps/web test` (i.e. `vitest run`) — there is currently no distinct unit vs. component test split.

## Mocking & test data

- `@testing-library/react` and `@testing-library/dom` are installed (`apps/web/package.json` devDependencies) but unused so far — no `render()`/`screen` call exists anywhere in the codebase. When writing the first component test, use Testing Library's `render`/`screen` queries (they're already on the dependency graph for this reason) rather than adding a different testing library.
- No `vi.mock()` usage, no MSW, no fixtures directory exist yet — no mocking convention is evidenced. Do not invent one; the only real example (`apps/web/src/smoke.test.ts`) has no dependencies to mock.
- No `setupFiles` is configured in `apps/web/vitest.config.ts` — e.g. no jest-dom matcher extension (`@testing-library/jest-dom`) is wired in yet, despite Testing Library being installed. Note this gap plainly rather than assuming matchers like `toBeInTheDocument` are available.

## Examples

BAD — Jest-style globals, no import (won't resolve under this Vitest config):
```ts
describe("smoke", () => {
  it("adds", () => {
    expect(1 + 1).toBe(2); // describe/it/expect not global here
  });
});
```

GOOD — matches the real scaffolded test:
```ts
import { describe, expect, it } from "vitest";

describe("smoke", () => {
  it("proves the vitest runner is wired", () => {
    expect(1 + 1).toBe(2);
  });
});
```

## References

- `apps/web/vitest.config.ts` — runner config (jsdom, `@` alias, include glob).
- `apps/web/src/smoke.test.ts` — only test in the codebase today.
- `docs/config/project-commands.yaml` — `test`, `test_unit` commands; `test_integration`/`test_e2e` intentionally blank.

<!-- ============================================================================ -->
<!-- OPTIONAL — keep only what applies to vitest; DELETE the rest.            -->
<!-- ============================================================================ -->

## Dependency, build & CI

- Test script: `"test": "vitest run"` (`apps/web/package.json:10`) — CI-style single run, not watch mode; use `pnpm -C apps/web exec vitest` locally for watch mode.
- React plugin required for JSX/TSX transform in tests: `@vitejs/plugin-react` wired in `apps/web/vitest.config.ts:2,6`.
- Wired command: `docs/config/project-commands.yaml` `test: "pnpm -C apps/web test && ..."` — always run through this, not a bare `vitest` invocation, so the FastAPI `pytest` half also runs where the harness expects a combined result.
- CI: `none` (`CLAUDE.md` Integrations) — `vitest run` currently executes locally / via `docs/config/project-commands.yaml` only, no pipeline runs it automatically.
