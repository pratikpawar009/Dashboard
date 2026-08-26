---
name: typescript-patterns
description: typescript patterns for this project — fill body with team conventions. Used by implementation/validation/arh-review agents.
when_to_use: Writing or reviewing typescript code.
user-invocable: false
allowed-tools: Read Write Edit Bash Grep Glob
---
# typescript Patterns

<!-- Harness scaffold: stack=typescript — STRUCTURE only; -->
<!-- Fill every CORE section below. Under OPTIONAL, keep only the sections that apply to -->
<!-- this stack and DELETE the heading+slot of the rest BEFORE filling. Keep ≤ 200 lines. -->
<!-- Deletion is safe: OPTIONAL slots use the word OPTIONAL (not TODO) so the lint does not -->
<!-- nag for them; CORE TODO slots are nagged until filled — that is intentional. -->
<!-- Loaded by implementation-, impl-planning-, validation-, code-review-, security-review-, -->
<!-- scaffold-, and cicd-agents when this stack is active. -->

## Verified facts

<!-- BEGIN VERIFIED FACTS -->
<!-- Owned by skill `deep-scan-verification` (/arh-init Phase 6) — `harness fill` never -->
<!-- edits between these markers. Empty until a brownfield deep scan approves facts here. -->
<!-- Each bullet ends in (see file:line); the file it cites is this fact's proof. -->
<!-- END VERIFIED FACTS -->

## Idioms

- `strict: true` in `apps/web/tsconfig.json` — no implicit any, strict null checks apply repo-wide.
- Path alias `@/*` → `./src/*` (`apps/web/tsconfig.json`). Import via `@/...`, not relative `../../` chains, once code moves below `src/app/`.
- `moduleResolution: "bundler"`, `module: "esnext"`, `target: "ES2017"`, `jsx: "preserve"` (Next.js compiles JSX) — do not hand-roll a different target/module setting per file.
- `isolatedModules: true` — every file must be independently transpilable; no cross-file `const enum`, no ambient-only files without `export {}`.
- No `type` vs `interface` convention is evidenced yet — the only typed shape in the codebase is `RootLayout`'s inferred `Readonly<{ children: React.ReactNode }>` prop (`apps/web/src/app/layout.tsx:20`) and the ambient `next.config.ts: NextConfig` type. Follow TypeScript's own default (`interface` for extensible object shapes, `type` for unions/aliases) until a real pattern emerges — do not invent a rule and present it as team convention.

## Project structure

- Single TS project at `apps/web/` (see `apps/web/tsconfig.json`), no separate `tsconfig.base.json` or monorepo project references yet — nothing under `services/api` participates in this TS project.
- `include`: `next-env.d.ts`, `**/*.ts`, `**/*.tsx`, `.next/types/**/*.ts`; `exclude`: `node_modules` (`apps/web/tsconfig.json:25-26`).
- All hand-written source lives under `apps/web/src/`; `next-env.d.ts` at the app root is generated, do not edit it.

## Layering & dependency rules

- No internal module boundaries exist yet (only `src/app/layout.tsx` + `src/app/page.tsx`). When new modules are added, import through `@/*`, never deep-relative paths that cross `src/app` into a future `src/lib`/`src/components`.
- No dependency-direction rule is evidenced beyond the Next.js App Router convention (pages/layouts import shared code, shared code must not import from `src/app/**`) — treat this as the working default, not a verified fact.

## Error handling

- No custom error types or try/catch idioms exist in the codebase yet (`layout.tsx`, `page.tsx` are pure render, no fallible logic). No pattern to follow — when introducing fallible code (e.g. a fetch to the FastAPI backend per ADR-0002), do not invent a bespoke error-wrapping scheme without checking back with an existing example first.

## Anti-patterns

- Do not bypass `strict` mode with `// @ts-ignore` / `any` to silence errors — `tsconfig.json` sets `strict: true` deliberately; suppressing it violates the project's own compiler contract.
- Do not add relative-path imports that could use the `@/*` alias instead (`apps/web/tsconfig.json:21-23`).
- Do not hand-write a second `tsconfig.json` under `src/` — one project config governs `apps/web/`.

## Examples

BAD — bypasses strict mode:
```ts
// @ts-ignore
const value: any = fetchSomething();
```

GOOD — typed, no suppression:
```ts
const value: unknown = fetchSomething();
if (typeof value === "string") {
  // narrowed
}
```

## References

- `apps/web/tsconfig.json` — compiler options, path alias.
- `docs/adr/0001-tech-stack.md` — TypeScript pinned as part of the declared stack.
- `docs/config/project-commands.yaml` — `typecheck_for_ts: "pnpm -C apps/web exec tsc --noEmit"`.

<!-- ============================================================================ -->
<!-- OPTIONAL sections — keep only what applies to typescript; DELETE the rest    -->
<!-- (heading + slot). OPTIONAL markers are NOT lint-nagged; once you keep one,    -->
<!-- change its OPTIONAL marker to a real convention. Do not leave empty OPTIONALs.-->
<!-- ============================================================================ -->

## Dependency, build & CI

- Package manager: pnpm (`apps/web/pnpm-lock.yaml` is committed; `Dockerfile` runs `corepack enable` then `pnpm install --frozen-lockfile=false`). Always install/add deps via `pnpm`, not `npm`/`yarn`, and keep the lockfile in sync.
- `tsc --noEmit` is the typecheck gate — wired as `typecheck_for_ts` in `docs/config/project-commands.yaml`, run standalone (`pnpm -C apps/web exec tsc --noEmit`), not bundled into `next build`.
- No formatter config file exists (`prettier` is a devDependency in `apps/web/package.json` but there is no `.prettierrc*`) — formatting runs on Prettier's own defaults via `docs/config/project-commands.yaml`'s `format_for_ts` (`pnpm -C apps/web exec prettier --write $FILE`). Do not invent custom Prettier options.
- CI: `none` per `CLAUDE.md` Integrations — these checks currently run only locally / via `docs/config/project-commands.yaml`, not an automated pipeline.
