# FIX-01 — identity-avatar neutral fallback hardcoded its colour pair, duplicating PersonaHeader's

- Date: 2026-09-03
- Input: `REVIEW.md` F-2 (MEDIUM), raised by the SHP-01 Validate ∥ Review gate and carried forward as `SHP-01-D06-neutral-hex-duplication`
- Branch: `bugfix/FIX-01-session-identity`
- For feature: SHP-01

## Root cause

**`avatarColorStyle()` returning a hardcoded `{ color: "#5b6472", background: "#e4e7ec" }` on its
`PersonaTagError` path produces a latent divergence risk between the persona tag pill and the identity
avatar, because those two literals were the *second* independent copy of a pair already declared in
`PersonaHeader.module.css` `.pillNeutral` — so `DECISIONS.md` D-02's guarantee that "the tag pill and
the avatar can never disagree on a persona's colour" held only by coincidence, not by construction.**

Secondary, same site: D-06 states that static values — "padding, font size, weight, radius, border and
neutral-ramp colors" — belong as literal rules in the component's CSS Module, and that only the
data-driven colour crosses as a `style` prop. The neutral pair is static, and the avatar's white text
was also being passed inline, so the component contradicted the decision it cites.

## Fix

The neutral pair is now declared exactly once, as `--neutral-unresolved-fg` / `--neutral-unresolved-bg`
on `:root` in `app/globals.css`, and read by all three surfaces that stand in for an unresolved value:
`PersonaHeader`'s `.pillNeutral` badge, the identity avatar's D-05 empty circle (`.avatarNeutral`), and
its new unknown-persona variant (`.avatarUnknownPersona`). `avatarColorStyle()` is replaced by
`personaAvatarColor()`, which returns `string | null` — the persona colour, or `null` when
`formatPersonaTag` raises `PersonaTagError`. `null` selects the neutral class instead of supplying
colours; a resolved persona passes only `{ background }` inline. The avatar's white text moved into the
`.avatar` rule.

D-02's agreement is now structural: the badge and the avatar cannot drift because they resolve the same
declaration. No hex literal remains in the component. Behaviour is unchanged — verified visually across
all four personas plus the `cio` neutral case.

Hoisting to `:root` rather than duplicating per CSS Module is a deliberate, narrow departure from
`next-patterns` § Design system ("route-local tokens are scoped inside the route's own CSS Module
class, not hoisted to globals.css"): that rule addresses *route-local* tokens, whereas this pair is
shared across two sibling components, and per-module duplication is the exact defect being fixed.

Files:
- `apps/web/src/app/globals.css`
- `apps/web/src/components/PersonaDashboardShell.tsx`
- `apps/web/src/components/PersonaDashboardShell.module.css`
- `apps/web/src/components/PersonaHeader.module.css`
- `apps/web/src/components/PersonaDashboardShell.test.tsx` (regression)

## Regression test

`apps/web/src/components/PersonaDashboardShell.test.tsx` — two cases tagged
`regression-SHP-01-TC-02`:

1. unknown persona + known name → initials still render, `.avatarUnknownPersona` applied, and
   `style.background` / `style.backgroundColor` / `style.color` are all empty (no inline colour).
2. valid persona → `style.backgroundColor` is `rgb(106, 79, 208)` (architect, `#6a4fd0` from
   `docs/design/tokens.md`), the neutral class is absent, and `style.color` is empty.

Both were confirmed to **fail against the pre-fix component** and pass after — the fix was stashed and
the suite re-run to prove the tests are a real lock rather than a tautology (2 failed / 14 passed
before, 16 passed after).

## Evidence

typecheck ✓ (`tsc --noEmit`, 0 errors) · unit ✓ (16/16 web; backend 431/431 untouched) ·
lint ✓ (`eslint .`, 0 errors) · runtime ✓ (`next dev`, all 5 states rendered and screenshotted) ·
compile ✓ (`next build` — Compiled successfully, 5/5 static pages)

Not covered: the `--neutral-unresolved-*` custom properties are asserted in the served CSS bundle, not
through jsdom — CSS Modules and custom properties do not resolve in the unit environment, so the visual
confirmation is the screenshot plus a grep of the compiled stylesheet.
