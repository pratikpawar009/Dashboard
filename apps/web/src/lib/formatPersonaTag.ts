/**
 * Persona tag/subtitle/color lookup (D-02 — FR-2).
 *
 * One internal map, one exported function, one `PersonaTagError` throw site
 * — the tag pill, the persona subtitle, and the identity-avatar background
 * color (D-02) are never resolved by four separate lookups.
 */

import {
  VALID_PERSONAS,
  type Persona,
  type ValidPersona,
} from "@/types/persona";

/**
 * Thrown by `formatPersonaTag()` for any value outside the 4 valid personas
 * — this covers `'cio'` and a resolver-error sentinel alike (D-03), never a
 * separate branch for either. The shell never composes the CIO dashboard —
 * the CIO Portfolio mockup has no persona tag/subtitle region at all — so a
 * `cio` value reaching this function is an invariant violation, not a fifth
 * persona to render.
 */
export class PersonaTagError extends Error {}

interface PersonaDisplay {
  tag: string;
  subtitle: string;
  color: string;
  background: string;
}

/**
 * Persona → tag/subtitle/color map, sourced from `docs/design/tokens.md`
 * § Persona colors (D-04). These four literals are byte-exact against the
 * decoded ARC/DEV/PMD/EMD mockups and must never be templated (research
 * condition C-4) — in particular `engineering-manager`'s tag is
 * `"Eng Manager"` (not "Engineering Manager") and its subtitle has a
 * lowercase `m`, `"Engineering manager overview"`. Both are correct as
 * written: a `Title(persona) + " overview"` construction would silently
 * produce the wrong string for this one key.
 */
const PERSONA_DISPLAY: Record<ValidPersona, PersonaDisplay> = {
  architect: {
    tag: "Architect",
    subtitle: "Architect overview",
    color: "#6a4fd0",
    background: "#f0edfb",
  },
  developer: {
    tag: "Developer",
    subtitle: "Developer overview",
    color: "#2a6fdb",
    background: "#e9f1fd",
  },
  "product-manager": {
    tag: "Product Manager",
    subtitle: "Product Manager overview",
    color: "#d97757",
    background: "#fdefe9",
  },
  "engineering-manager": {
    tag: "Eng Manager",
    subtitle: "Engineering manager overview",
    color: "#1f8a5b",
    background: "#eaf6ef",
  },
};

/**
 * Maps a resolved persona to its display tag/subtitle/color pair.
 *
 * `persona` is expected to be one of `VALID_PERSONAS`. `'cio'`, or any other
 * value outside the 4 valid personas, throws `PersonaTagError` rather than
 * rendering a fabricated or blank tag (FR-2).
 */
export function formatPersonaTag(persona: Persona): PersonaDisplay {
  if (!(VALID_PERSONAS as readonly string[]).includes(persona)) {
    throw new PersonaTagError(persona);
  }
  return PERSONA_DISPLAY[persona as ValidPersona];
}
