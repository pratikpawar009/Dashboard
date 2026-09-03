import type {
  Persona,
  ProgramContextData,
  SignedInUser,
} from "@/types/persona";
import { deriveInitials } from "@/lib/deriveInitials";
import { formatPersonaTag, PersonaTagError } from "@/lib/formatPersonaTag";

import { PersonaHeader } from "./PersonaHeader";
import { ProgramContext } from "./ProgramContext";
import styles from "./PersonaDashboardShell.module.css";

/**
 * Composing shell for the four persona dashboards (ARC-01/DEV-01/PMD-01/
 * EMD-01) — brand bar, signed-in identity block, persona-context header
 * (`PersonaHeader`), and program context (`ProgramContext`), assembled from
 * props alone. No data fetching; no persona-specific branching anywhere in
 * this file beyond the single `isLoading` gate below (research condition
 * C-7 — this file never compares `persona` against a specific value or
 * `VALID_PERSONAS`; `PersonaHeader` owns the valid/invalid split).
 *
 * **No in-repo consumer yet.** ARC-01/DEV-01/PMD-01/EMD-01 are this
 * component's named consumers (`docs/requirements/api.md#persona-shell`)
 * and are not yet planned (PLAN.md § 6 Cross-Feature Dependency Notes) — do
 * not add a page/route/demo to wire this up; that would fabricate scope the
 * PRD explicitly excludes.
 *
 * Props (`docs/requirements/api.md#persona-shell`):
 * - `signedInUser?: SignedInUser` — **PROVISIONAL**, pending the AUTH-01
 *   `session`-contract amendment (SHP-01 Constraints/C-1, DECISIONS.md D-01).
 *   Only this file and `apps/web/src/types/persona.ts` reference
 *   `signedInUser.name`/`.jobTitle` directly. `undefined` — whether because
 *   the amendment hasn't landed yet or the composing page hasn't resolved
 *   it — renders the identity block's neutral fallback (D-05), never a
 *   placeholder name or blank field (FR-1).
 * - `persona?: Persona` — `undefined` means session/persona-resolver output
 *   has not yet resolved. This is the ONLY loading signal this component
 *   reads. Any defined value (one of the 4 valid personas, `'cio'`, or a
 *   resolver-error sentinel) is handed to `PersonaHeader`, which owns the
 *   valid/invalid split and its own neutral-badge rendering (FR-2/FR-5,
 *   D-03).
 * - `program: ProgramContextData` — resolved by the composing page before
 *   render (C-3); this component owns no loading/empty state for it.
 *
 * FR-5 suppression semantics: while `isLoading`, only the brand bar's
 * static left half (logo tile + product name/tagline) renders. The
 * signed-in identity block, the persona tag/subtitle, and the
 * program-context block are all omitted entirely — no skeleton markup.
 * This is NFR-2's flash-prevention rule: none of this persona-gated
 * content may render — even briefly, even as a placeholder — before
 * `persona` resolves, so a user is never shown one persona's (or a stale)
 * view flash before the correct one paints.
 */
export function PersonaDashboardShell({
  signedInUser,
  persona,
  program,
}: {
  signedInUser?: SignedInUser;
  persona?: Persona;
  program: ProgramContextData;
}) {
  const isLoading = persona === undefined;
  // Computed once here rather than inline in the JSX: `persona` is narrowed to
  // `string` only inside the `!isLoading` branches below.
  const personaColor = isLoading ? null : personaAvatarColor(persona);

  return (
    <>
      <div className={styles.brandBar}>
        <div className={styles.logoTile}>
          <div className={styles.logoInner} />
        </div>
        <div className={styles.brandText}>
          <div className={styles.productName}>AgentRise Harness</div>
          <div className={styles.tagline}>AI SDLC Governance</div>
        </div>
        {!isLoading && (
          <div className={styles.identity}>
            {signedInUser ? (
              <>
                <div className={styles.identityText}>
                  <div className={styles.name}>{signedInUser.name}</div>
                  <div className={styles.jobTitle}>
                    {signedInUser.jobTitle}
                  </div>
                </div>
                <div
                  className={
                    personaColor === null
                      ? `${styles.avatar} ${styles.avatarUnknownPersona}`
                      : styles.avatar
                  }
                  style={
                    personaColor === null ? undefined : { background: personaColor }
                  }
                >
                  {deriveInitials(signedInUser.name)}
                </div>
              </>
            ) : (
              /* D-05: neutral fallback for the not-yet-amended/unresolved
               * signedInUser case — a real, asserted render (34x34 neutral
               * circle, no initials, aria-hidden), never a placeholder name
               * and never a suppressed region. Distinct from `isLoading`. */
              <div className={styles.avatarNeutral} aria-hidden="true" />
            )}
          </div>
        )}
      </div>
      {!isLoading && (
        <header className={styles.headerRegion}>
          <PersonaHeader persona={persona} />
          <ProgramContext program={program} />
        </header>
      )}
    </>
  );
}

/**
 * The identity avatar's persona-derived background colour, or `null` when
 * the persona is unresolvable.
 *
 * A non-null result is `formatPersonaTag(persona).color` — the same value
 * `PersonaHeader`'s tag pill uses, so the avatar and the tag can never
 * disagree on a persona's colour (D-02). It is the ONLY value that crosses
 * into a `style` prop (D-06); the avatar's white text and all its geometry
 * are static rules in `PersonaDashboardShell.module.css`.
 *
 * `signedInUser` defined while `persona` is not one of the 4 valid personas
 * is a reachable combination neither PLAN.md nor `SHP-01-TC-02` specify
 * (FLAGS.md AF-03). Resolved by mirroring `PersonaHeader`'s own neutral
 * degradation rather than inventing a new state: only `PersonaTagError` is
 * caught, and `null` selects the `.avatarUnknownPersona` class, which reads
 * the same shared `--neutral-unresolved-*` pair the neutral badge does.
 * Returning `null` rather than a hardcoded pair is what keeps D-02's
 * agreement guarantee structural instead of coincidental (REVIEW.md F-2).
 * Initials still render — the name is known, only the persona is not. Any
 * other error propagates uncaught, staying inside D-03's fail-loud path.
 */
function personaAvatarColor(persona: Persona): string | null {
  try {
    return formatPersonaTag(persona).color;
  } catch (error) {
    if (!(error instanceof PersonaTagError)) {
      throw error;
    }
    return null;
  }
}
