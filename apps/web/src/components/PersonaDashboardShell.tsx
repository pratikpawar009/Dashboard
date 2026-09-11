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
 * EMD-01) and the org-wide `/overview` page (OVW-05) — brand bar,
 * signed-in identity block, either the persona-context header
 * (`PersonaHeader`, program variant) or the org page-title header
 * (`pageTitle` variant), and program context (`ProgramContext`), assembled
 * from props alone. No data fetching; no persona-specific branching
 * anywhere in this file beyond the single `isLoading` gate below (research
 * condition C-7 — this file never compares `persona` against a specific
 * value or `VALID_PERSONAS`; `PersonaHeader` owns the valid/invalid split
 * for the program variant, and the org variant duplicates that same catch
 * inline, D-04).
 *
 * **No in-repo consumer yet** for the four persona dashboards.
 * ARC-01/DEV-01/PMD-01/EMD-01 are this component's named consumers
 * (`docs/requirements/api.md#persona-shell`) and are not yet planned
 * (PLAN.md § 6 Cross-Feature Dependency Notes) — do not add a
 * page/route/demo to wire those up; that would fabricate scope the PRD
 * explicitly excludes. `AdoptionOverview` (OVW-05) is the first live
 * consumer, via the `pageTitle` variant below.
 *
 * Props (`docs/requirements/api.md#persona-shell`):
 * - `signedInUser?: SignedInUser` — resolved without a rename: `name`
 *   arrives from `session-identity-api` (`GET /api/me`) under that exact
 *   field name; `jobTitle` is composed frontend-side from
 *   `PERSONA_DISPLAY[persona].jobTitle`, never read off the wire (OVW-05
 *   AC-11). The SHP-01 D-01 field-name isolation adapter
 *   (`apps/web/src/types/persona.ts`) is left intact, not exercised.
 *   `undefined` renders the identity block's neutral fallback (D-05),
 *   never a placeholder name or blank field (FR-1).
 * - `persona?: Persona` — `undefined` means session/persona-resolver output
 *   has not yet resolved. This is the ONLY loading signal this component
 *   reads. Any defined value (one of the 5 valid personas, or a
 *   resolver-error sentinel) is resolved by whichever header variant is
 *   selected, each owning its own valid/invalid split and neutral-badge
 *   rendering (FR-2/FR-5, D-03).
 * - `program?: ProgramContextData` — **OVW-01 D-04**: optional, for callers
 *   with a single-program concept. When defined, resolved by the composing
 *   page before render (C-3); this component owns no loading/empty state
 *   for it. `undefined` never reaches `ProgramContext` (which still
 *   requires a defined `program` itself, unchanged) — the header region's
 *   render guard checks `program !== undefined` alongside `!isLoading`.
 * - `pageTitle?: string` — **OVW-05 AC-8**: the composing page's title
 *   (e.g. `"Adoption Overview"`). Together with a resolved `persona` and
 *   `program === undefined`, selects the org-header variant instead of the
 *   program-header variant: the title plus the persona pill on one line,
 *   then the persona subtitle beneath. Selection is by prop presence only
 *   — never a `persona === 'cio'` (or any persona-literal) conditional in
 *   this file (research condition C-7). Mutually exclusive with
 *   `program !== undefined` by construction; passing both is a caller
 *   error this component does not otherwise resolve.
 * - `children?: React.ReactNode` — **OVW-01 D-04**: rendered as the shell's
 *   last element, always, regardless of `isLoading`. Lets a composing page
 *   place its own content beneath the shared brand-bar chrome (e.g.
 *   `AdoptionOverview`).
 *
 * FR-5 suppression semantics: while `isLoading`, only the brand bar's
 * static left half (logo tile + product name/tagline) renders. The
 * signed-in identity block, both header variants, and the program-context
 * block are all omitted entirely — no skeleton markup. This is NFR-2's
 * flash-prevention rule: none of this persona-gated content may render —
 * even briefly, even as a placeholder — before `persona` resolves, so a
 * user is never shown one persona's (or a stale) view flash before the
 * correct one paints.
 */
export function PersonaDashboardShell({
  signedInUser,
  persona,
  program,
  pageTitle,
  children,
}: {
  signedInUser?: SignedInUser;
  persona?: Persona;
  program?: ProgramContextData;
  pageTitle?: string;
  children?: React.ReactNode;
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
            {/* Sign-out control (AC-12..15/19): a SIBLING of the ternary
             * above, outside it, gated only by the enclosing `!isLoading` —
             * it must render in BOTH the populated and the D-05
             * neutral-fallback branch. Nesting it inside either branch
             * drops it in the other (the defect the story flags as
             * shipping untested today). Zero-JS GET form: a `<button
             * onClick>` would force "use client" on this Server Component. */}
            <form action="/logout" method="get">
              <button
                type="submit"
                className={styles.signOutButton}
                aria-label="Sign out"
              >
                Sign out
              </button>
            </form>
          </div>
        )}
      </div>
      {!isLoading && program !== undefined && (
        <header className={styles.headerRegion}>
          <PersonaHeader persona={persona} />
          <ProgramContext program={program} />
        </header>
      )}
      {!isLoading && pageTitle !== undefined && program === undefined && (
        <header className={`${styles.headerRegion} ${styles.headerRegionOrg}`}>
          <div style={{ flex: 1 }}>
            {renderOrgHeaderContent(pageTitle, persona)}
          </div>
        </header>
      )}
      {children}
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

/**
 * Org-header variant content: title row (page title + persona pill) plus
 * the persona subtitle beneath (AC-8/AC-9). Duplicates `PersonaHeader`'s
 * try/catch + neutral-badge JSX inline rather than sharing a helper with it
 * (D-04) — this is only the org variant's own composition (title+pill on
 * one line, subtitle on the next), which differs from `PersonaHeader`'s
 * single-line layout, and is the second occurrence of this catch shape,
 * not the third that would justify extraction
 * (`.claude/rules/reusability-baseline.md`). `PersonaTagError` degrades the
 * pill to the shared neutral badge plus a visually-hidden `aria-live`
 * announcement; the page title still renders either way. Any other error
 * propagates uncaught, mirroring `PersonaHeader`'s exact guard shape.
 */
function renderOrgHeaderContent(pageTitle: string, persona: Persona) {
  try {
    const { tag, subtitle, color, background } = formatPersonaTag(persona);
    return (
      <>
        <div className={styles.orgTitleRow}>
          <span className={styles.pageTitle}>{pageTitle}</span>
          <span className={styles.orgPill} style={{ color, background }}>
            {tag}
          </span>
        </div>
        <div className={styles.orgSubtitle}>{subtitle}</div>
      </>
    );
  } catch (error) {
    if (!(error instanceof PersonaTagError)) {
      throw error;
    }
    return (
      <>
        <div className={styles.orgTitleRow}>
          <span className={styles.pageTitle}>{pageTitle}</span>
          <span className={`${styles.orgPill} ${styles.orgPillNeutral}`}>
            Persona unavailable
          </span>
        </div>
        <span aria-live="assertive" className={styles.visuallyHidden}>
          Unable to load your dashboard view.
        </span>
      </>
    );
  }
}
