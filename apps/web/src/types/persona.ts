/**
 * Persona-shell prop shapes (D-01 — FR-1 field-name isolation adapter).
 *
 * Single source of `SignedInUser`, `ProgramContextData`, and `Persona`/
 * `VALID_PERSONAS`. Only this file and `PersonaDashboardShell.tsx` reference
 * `signedInUser.name`/`.jobTitle` directly, so a field rename is a two-file
 * change, not a wide refactor.
 */

/**
 * PROVISIONAL — pending the AUTH-01 session-contract amendment (SHP-01
 * Constraints/C-1); only this file and PersonaDashboardShell.tsx reference
 * these field names directly.
 */
export interface SignedInUser {
  name: string;
  jobTitle: string;
}

/** `docs/requirements/api.md#persona-shell` `program` prop — data only, no style fields. */
export interface ProgramContextData {
  icon: string;
  name: string;
  type: string;
  description: string;
}

/** Runtime allow-list `formatPersonaTag()` validates against (FR-2). */
export const VALID_PERSONAS = [
  "architect",
  "developer",
  "product-manager",
  "engineering-manager",
] as const;

export type ValidPersona = (typeof VALID_PERSONAS)[number];

/**
 * Loose `string` on purpose: AUTH-02's `resolve()` is fully data-driven
 * (`docs/requirements/auth.md#persona-resolver`) — no hardcoded enum on the
 * wire. `VALID_PERSONAS` is the runtime allow-list `formatPersonaTag()`
 * validates against.
 */
export type Persona = string;
