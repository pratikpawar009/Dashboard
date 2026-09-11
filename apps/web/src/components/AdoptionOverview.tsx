import { AdoptionIndicator } from "./AdoptionIndicator";
import styles from "./AdoptionOverview.module.css";
import { OrgSummaryCards } from "./OrgSummaryCards";
import { OverviewErrorPanel } from "./OverviewErrorPanel";
import { PersonaDashboardShell } from "./PersonaDashboardShell";
import type { OverviewSummaryResult } from "@/types/overview";
import type { Persona, SignedInUser } from "@/types/persona";

/**
 * Adoption Overview page body (OVW-01, AC-3/AC-4/AC-5) — composes the two
 * in-scope regions of the CIO Portfolio Dashboard mockup beneath the shared
 * brand-bar chrome.
 *
 * Deliberately a plain component with **no `"use client"`** (DECISIONS.md
 * D-03): it takes an already-resolved `OverviewSummaryResult` as a prop and
 * never fetches. The server-side fetch lives in `lib/overviewApi.ts` and is
 * invoked by the route (T-14) inside `tokenStore.callWithAuth()`, mirroring
 * how `programs/[program_id]/page.tsx` drives `fetchProgramDetail`. That is
 * what keeps the access token off the client per
 * `docs/adr/0008-client-side-auth-route-handler-proxy.md`.
 *
 * `persona`/`signedInUser`/`pageTitle` arrive from the composing page
 * (`overview/page.tsx`, OVW-05) fully resolved and are forwarded to
 * `PersonaDashboardShell` unchanged — this component performs no fetching
 * and no composition of its own (`GET /api/me` is called server-side by the
 * page, not here). `program` stays omitted, unchanged from before this
 * story: this is an org-wide view — there is no single program to name,
 * which is exactly why T-08 widened `program` to optional.
 *
 * Every non-`ok` status renders the same `OverviewErrorPanel` (D-07) — one
 * message for `forbidden`, `unauthorized` and `error` alike, so the copy
 * never reveals whether the resource exists or whether the session is at
 * fault.
 */
export function AdoptionOverview({
  result,
  persona,
  signedInUser,
  pageTitle,
}: {
  result: OverviewSummaryResult;
  persona?: Persona;
  signedInUser?: SignedInUser;
  pageTitle?: string;
}) {
  return (
    <PersonaDashboardShell
      persona={persona}
      signedInUser={signedInUser}
      pageTitle={pageTitle}
    >
      <div className={styles.content}>
        {result.status === "ok" ? (
          <>
            <OrgSummaryCards state="populated" cards={result.data.cards} />
            <AdoptionIndicator
              state="populated"
              data={result.data.programs_using_ai}
            />
          </>
        ) : (
          <OverviewErrorPanel status={result.status} />
        )}
      </div>
    </PersonaDashboardShell>
  );
}
