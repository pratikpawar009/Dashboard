---
name: next-patterns
description: next patterns for this project — fill body with team conventions. Used by implementation/validation/arh-review agents.
when_to_use: Writing or reviewing next code.
user-invocable: false
allowed-tools: Read Write Edit Bash Grep Glob
---
# next Patterns

<!-- Harness scaffold: stack=next — STRUCTURE only; -->
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

- App Router only — routes live under `src/app/`, no `pages/` directory exists (`apps/web/src/app/layout.tsx`, `apps/web/src/app/page.tsx`).
- Root layout (`src/app/layout.tsx`) defines `<html>`/`<body>` once and exports `metadata: Metadata`; page components (`src/app/page.tsx`) render inside it — do not re-declare `<html>`/`<body>` in a page.
- Components are Server Components by default — neither `layout.tsx` nor `page.tsx` declares `"use client"`. No client component exists yet in the codebase; add `"use client"` only when a component genuinely needs interactivity/browser APIs.
- Per-route CSS Modules co-located with the route (`src/app/page.module.css` next to `src/app/page.tsx`), imported as `styles` and applied via `className={styles.x}` (`apps/web/src/app/page.tsx:2,6`).
- Fonts loaded via `next/font/google`, exposed as CSS custom properties set on `<body className>` (`apps/web/src/app/layout.tsx:5-13,27`), not linked via `<link>` tags or `@import`.
- Images via `next/image`, always with explicit `width`/`height` (or `fill`) and `alt` (`apps/web/src/app/page.tsx:8-15`) — do not use a bare `<img>`.

## Project structure

- `apps/web/src/app/` — route segments, layouts, route-local styles.
- `apps/web/public/` — static assets served from `/` (svgs currently).
- `apps/web/next.config.ts` — currently an empty `NextConfig` (`apps/web/next.config.ts:3-5`); no rewrites, redirects, or image domains configured yet.
- No `src/components/`, `src/lib/`, or `src/app/api/` exist yet — this is the scaffold-default layout, not a deliberately minimal one; add these directories as real code lands.

## Layering & dependency rules

- Route segment files (`page.tsx`, `layout.tsx`) are entry points — shared logic should live outside `src/app/` (e.g. a future `src/lib/` or `src/components/`) and be imported into routes via the `@/*` alias, not the reverse.
- No route currently reads from or writes to the FastAPI backend — when that lands, keep the REST call in a shared module under `src/lib/` (or a route handler under `src/app/api/`), not inlined ad hoc in every page component, so the fetch layer stays swappable.

## Error handling

- No `error.tsx`, `not-found.tsx`, or `loading.tsx` exist yet in `src/app/` — App Router error/loading boundaries are an available but unused convention. When added, follow Next's file convention (`error.tsx` per segment) rather than manual try/catch UI state in the page component.

## Anti-patterns

- Do not add a `pages/` directory — this project committed to App Router only; mixing routers is unsupported drift.
- Do not fetch data with client-side `useEffect` + `fetch` in a Server Component context — Server Components can `fetch` directly; only mark `"use client"` when interactivity requires it.
- Do not bypass `next/image` for content images (raster/vector assets meant to be optimized) — breaks the optimization/`alt`-enforcement this codebase already relies on.

## Examples

BAD — client-only fetch pattern in what should be a Server Component:
```tsx
"use client";
export default function Page() {
  const [data, setData] = useState(null);
  useEffect(() => { fetch("/api/x").then(r => r.json()).then(setData); }, []);
  return <div>{data}</div>;
}
```

GOOD — Server Component, direct async fetch (App Router default):
```tsx
export default async function Page() {
  const data = await fetch("http://api:8000/x").then(r => r.json());
  return <div>{data}</div>;
}
```

## References

- `apps/web/src/app/layout.tsx`, `apps/web/src/app/page.tsx` — canonical current examples.
- `docs/adr/0002-system-architecture.md` — REST/OpenAPI contract with the FastAPI backend, event-driven ingest, OIDC/SSO seam (not yet implemented in `apps/web`).
- `docs/config/stack-smoke.md` § `next` / `nextjs` — run/check commands.

<!-- ============================================================================ -->
<!-- OPTIONAL sections — keep only what applies to next; DELETE the rest    -->
<!-- (heading + slot). OPTIONAL markers are NOT lint-nagged; once you keep one,    -->
<!-- change its OPTIONAL marker to a real convention. Do not leave empty OPTIONALs.-->
<!-- ============================================================================ -->

## Design system + visual conventions

- No CSS/component framework (no Tailwind, no MUI, no styled-components) — plain CSS Modules per route plus one global stylesheet (`apps/web/src/app/globals.css`).
- Design tokens are two CSS custom properties on `:root`: `--background`, `--foreground` (`apps/web/src/app/globals.css:1-4`), redefined under `@media (prefers-color-scheme: dark)` (`globals.css:6-11`) — dark mode is OS-preference-driven, no manual theme toggle exists.
- Route-local tokens (e.g. `--gray-rgb`, `--button-primary-hover`) are scoped inside the route's own CSS Module class, not hoisted to `globals.css` (`apps/web/src/app/page.module.css:1-17`).
- No spacing scale or breakpoint system is declared beyond ad hoc values in `page.module.css` (e.g. `@media (max-width: 600px)`) — treat as scaffold placeholder, not a real token system, until deliberately designed.

## State management

- No state management library is installed (no Redux/Zustand/Jotai/TanStack Query/SWR in `apps/web/package.json`). No client state exists yet — every component today is a Server Component. Decide a client-state approach only when the first `"use client"` component needs one; do not add a store pre-emptively.

## API / interface contracts

- No API-calling code exists yet in `apps/web` (no `fetch` calls, no `src/app/api/`, no generated OpenAPI client). Per `docs/adr/0002-system-architecture.md`: the backend is REST with Pydantic-validated schemas, and FastAPI's auto-generated OpenAPI docs are the contract source of truth — when wiring the first call, consume that OpenAPI contract rather than hand-guessing response shapes.
- Auth: OIDC/SSO is decided at the architecture level (ADR-0002) but the identity provider is unspecified (`[NEEDS CLARIFICATION]`) and no auth code exists in `apps/web` yet.

## Dependency, build & CI

- Package manager: pnpm (`apps/web/pnpm-lock.yaml`); install via `pnpm -C apps/web install` (`docs/config/project-commands.yaml` preflight).
- Scripts (`apps/web/package.json`): `dev` = `next dev --turbopack`, `build` = `next build --turbopack`, `start` = `next start`, `lint` = `eslint`, `test` = `vitest run`.
- Lint: flat config `apps/web/eslint.config.mjs`, extends `next/core-web-vitals` + `next/typescript` via `FlatCompat` — this is the framework default, not a custom rule set; no rules are overridden.
- CI: `none` (`CLAUDE.md` Integrations) — these commands run locally / via `docs/config/project-commands.yaml` only.
