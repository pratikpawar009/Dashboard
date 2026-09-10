import { AdoptionIndicator } from "./AdoptionIndicator";
import styles from "./AdoptionOverview.module.css";
import { OrgSummaryCards } from "./OrgSummaryCards";
import { OverviewErrorPanel } from "./OverviewErrorPanel";
import { PersonaDashboardShell } from "./PersonaDashboardShell";
import type { OverviewSummaryResult } from "@/types/overview";

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
 * `PersonaDashboardShell` is rendered with `signedInUser`/`persona`/`program`
 * **all omitted** (D-04). That is intentional, not an oversight: the shell
 * derives `isLoading` from `persona === undefined`, so omitting it keeps the
 * shell in its brand-bar-only branch and neither `PersonaHeader` nor
 * `ProgramContext` is invoked. This is an org-wide view — there is no single
 * program to name, which is exactly why T-08 widened `program` to optional.
 *
 * Every non-`ok` status renders the same `OverviewErrorPanel` (D-07) — one
 * message for `forbidden`, `unauthorized` and `error` alike, so the copy
 * never reveals whether the resource exists or whether the session is at
 * fault.
 */
export function AdoptionOverview({ result }: { result: OverviewSummaryResult }) {
  return (
    <PersonaDashboardShell>
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
