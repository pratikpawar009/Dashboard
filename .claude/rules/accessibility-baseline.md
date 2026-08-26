---
paths:
  - "**/*.tsx"
  - "**/*.jsx"
  - "**/*.vue"
  - "**/*.svelte"
  - "**/*.html"
---
# Accessibility baseline

WCAG 2.2 Level AA is the minimum bar for every UI surface. This rule is the canonical source — PRDs reference this file via `Per `.claude/rules/accessibility-baseline.md`:` instead of inlining the bullets below.

## Core

- Conform to WCAG 2.2 Level AA at minimum.
- Every interactive element is keyboard reachable and has a visible focus state.
- Every image, icon button, and form control has an accessible name (`aria-label`, `aria-labelledby`, or associated `<label>`).
- Color is not the sole indicator of state. Pair color with text or icon.
- Minimum text contrast 4.5:1 for body, 3:1 for large text and UI components.
- Touch targets are at least 44×44 device-independent pixels on mobile and pointer interfaces.
- Content reflows at 320px viewport width without horizontal scrolling.
- Animations respect `prefers-reduced-motion`.

## Modals and dialogs

- Root element carries `role="dialog"` (or `role="alertdialog"` for destructive confirmations) and `aria-modal="true"`.
- Focus is trapped while the dialog is open: Tab cycles last → first, Shift+Tab cycles first → last.
- ESC closes the dialog without persisting changes; clicks on backdrop close the dialog (configurable; same behaviour as ESC by default).
- Focus is restored to the triggering element when the dialog closes for any reason.
- Default focus on open lands on the first focusable interactive element, EXCEPT in destructive contexts (delete confirm, irreversible action) where default focus is on the Cancel button.
- Validation errors are surfaced in `aria-live="assertive"` regions so screen readers announce them immediately.
- The dialog has an associated `aria-labelledby` pointing to the title element.

## Forms

- Every input has an associated `<label>` with explicit `for` / `htmlFor` linkage.
- Inline validation errors are surfaced in `aria-live="polite"` or `aria-live="assertive"` regions per error severity.
- Required fields are marked with `aria-required="true"` AND a visual indicator (asterisk or "required" text).
- Field-level help text is associated via `aria-describedby`.
- Error messages are tied to fields via `aria-describedby` so screen readers read field + error together.

## Lists and tables

- Headers use semantic elements (`<thead>`, `<th>`, `scope="col"` / `scope="row"`).
- Sortable columns carry `aria-sort` reflecting current direction.
- Pagination announces page changes via a live region.
- Toggle / filter chips (e.g. tag filters) carry `aria-pressed` reflecting selection state.

## Motion + animation

- All non-essential animation respects `prefers-reduced-motion: reduce`.
- Auto-playing content (carousels, video) provides a pause control.
- Flashing content stays below the 3-flashes-per-second threshold.

## What PRDs do

PRDs reference this rule in NFR-a11y with one bullet:

```
- Accessibility: Per `.claude/rules/accessibility-baseline.md`: applies to all new UI surfaces in this story (<list the new screens/components in scope>). <feature-specific additions only>
```

The rule body above is canonical. Do NOT re-paste these bullets in the PRD — every PRD doing so creates 15+ lines of drift and a 3rd copy of the same content that downstream readers must reconcile.
