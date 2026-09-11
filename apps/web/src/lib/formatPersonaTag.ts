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
 * Thrown by `formatPersonaTag()` for any value outside the 5 valid personas
 * — this covers a resolver-error sentinel (D-03) and any other unrecognized
 * value, never a separate branch for either. `cio` is a valid, renderable
 * persona (OVW-05 AC-2/AC-4): its brand-bar pill/avatar and header subtitle
 * render exactly like the other four, so it does not throw here.
 */
export class PersonaTagError extends Error {}

interface PersonaDisplay {
  tag: string;
  subtitle: string;
  color: string;
  background: string;
  jobTitle: string;
}

/**
 * Persona → tag/subtitle/color/jobTitle map, sourced from
 * `docs/design/tokens.md` § Persona colors (D-04) plus this story's
 * `jobTitle` field (OVW-05 AC-3) — a plain role name on all five entries,
 * never the mockups' seniority literals. The tag/subtitle/color literals are
 * byte-exact against the decoded ARC/DEV/PMD/EMD/CIO mockups and must never
 * be templated (research condition C-4) — in particular
 * `engineering-manager`'s tag is `"Eng Manager"` (not "Engineering
 * Manager") and its subtitle has a lowercase `m`,
 * `"Engineering manager overview"`. Both are correct as written: a
 * `Title(persona) + " overview"` construction would silently produce the
 * wrong string for this one key.
 *
 * Sync obligation (research condition C-3): these keys must stay in sync
 * with `services/api/app/core/persona_resolver.py`'s persona set — adding a
 * persona to the backend resolver obliges adding it here (and to
 * `VALID_PERSONAS`), never one without the other.
 */
const PERSONA_DISPLAY: Record<ValidPersona, PersonaDisplay> = {
  architect: {
    tag: "Architect",
    subtitle: "Architect overview",
    color: "#6a4fd0",
    background: "#f0edfb",
    jobTitle: "Architect",
  },
  developer: {
    tag: "Developer",
    subtitle: "Developer overview",
    color: "#2a6fdb",
    background: "#e9f1fd",
    jobTitle: "Developer",
  },
  "product-manager": {
    tag: "Product Manager",
    subtitle: "Product Manager overview",
    color: "#d97757",
    background: "#fdefe9",
    jobTitle: "Product Manager",
  },
  "engineering-manager": {
    tag: "Eng Manager",
    subtitle: "Engineering manager overview",
    color: "#1f8a5b",
    background: "#eaf6ef",
    jobTitle: "Engineering Manager",
  },
  cio: {
    tag: "CIO / CXO",
    subtitle: "Organization-wide AI-in-SDLC adoption, spend & impact",
    color: "#0f1a2e",
    background: "#e6e9ef",
    jobTitle: "Chief Information Officer",
  },
};

/**
 * Maps a resolved persona to its display tag/subtitle/color pair.
 *
 * `persona` is expected to be one of `VALID_PERSONAS` — now five entries,
 * `cio` included (OVW-05 AC-1/AC-2). Any other value throws
 * `PersonaTagError` rather than rendering a fabricated or blank tag (FR-2).
 */
export function formatPersonaTag(persona: Persona): PersonaDisplay {
  if (!(VALID_PERSONAS as readonly string[]).includes(persona)) {
    throw new PersonaTagError(persona);
  }
  return PERSONA_DISPLAY[persona as ValidPersona];
}
