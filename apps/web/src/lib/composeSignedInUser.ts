/**
 * `signedInUser` composition for the brand-bar identity block (OVW-05
 * AC-6/AC-7, DECISIONS.md D-03, DATA-DESIGN.md § 9 Contract).
 *
 * Pure function, no I/O, no logging — `name` is PII and this story adds no
 * new logging event (DATA-DESIGN.md § 4). `jobTitle` is NEVER read off the
 * `me` argument itself; it is always derived via `formatPersonaTag()`. The
 * real `GET /api/me` response model is `extra="forbid"` and carries exactly
 * `{name, persona}` (README.md), so a `jobTitle` field on the wire would
 * already be a bug — this function is structurally incapable of passing one
 * through even if that bug existed (research risk #2, the sole HIGH; PRD
 * condition C-1).
 */

import type { MeData } from "@/types/me";
import type { SignedInUser } from "@/types/persona";
import { formatPersonaTag, PersonaTagError } from "@/lib/formatPersonaTag";

/**
 * `me.name === null` (e.g. a `/auth/dev-bypass` token with no profile
 * claims) → `undefined`, never a fabricated name (AC-7); the composing page
 * then renders the shell's existing neutral fallback. Otherwise →
 * `{ name, jobTitle: formatPersonaTag(me.persona).jobTitle }` (AC-6).
 *
 * `PersonaTagError` (persona unresolvable) is caught back to `undefined` —
 * mirrors the guard shape in `PersonaDashboardShell.tsx`'s
 * `personaAvatarColor()` / `PersonaHeader.tsx` (D-03: do not throw). Any
 * other error propagates uncaught.
 */
export function composeSignedInUser(me: MeData): SignedInUser | undefined {
  if (me.name === null) {
    return undefined;
  }

  try {
    return { name: me.name, jobTitle: formatPersonaTag(me.persona).jobTitle };
  } catch (error) {
    if (!(error instanceof PersonaTagError)) {
      throw error;
    }
    return undefined;
  }
}
