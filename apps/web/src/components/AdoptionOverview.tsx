import { AdoptionIndicator } from "./AdoptionIndicator";
import styles from "./AdoptionOverview.module.css";
import { OrgSummaryCards } from "./OrgSummaryCards";
import { OverviewErrorPanel } from "./OverviewErrorPanel";
import { PersonaDashboardShell } from "./PersonaDashboardShell";
import { ProgramLeaderboard } from "./ProgramLeaderboard";
import type { OverviewSummaryResult } from "@/types/overview";
import type { Persona, SignedInUser } from "@/types/persona";
import type { ProgramBoardResult } from "@/types/programBoard";

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
 *
 * `programBoardResult` (OVW-04, T-12) is a separate server-side fetch from
 * `result` — its own status is branched independently, the same
 * ok/forbidden/unauthorized/error handling `OrgSummaryCards` above already
 * uses, rendering `OverviewErrorPanel` on any non-ok status (D-07's "one
 * message for all three" precedent applies per-region, not just page-wide).
 * `ProgramLeaderboard` renders beneath `AdoptionIndicator` per DESIGN.md's
 * region ordering (`PROGRAM LEADERBOARD` follows `PROGRAM ADOPTION HEALTH`
 * on the mockup). `programBoardResult` stays `undefined` when the caller
 * omits it (OVW-01's own test suite, which predates this story and knows
 * nothing about a board) — an *absent* prop renders neither the board region
 * nor an error panel, distinct from a *supplied* non-ok status, which is a
 * real fetch failure worth showing. The composing page (`overview/page.tsx`)
 * always supplies the real fetch result.
 */
export function AdoptionOverview({
  result,
  programBoardResult,
  persona,
  signedInUser,
  pageTitle,
}: {
  result: OverviewSummaryResult;
  programBoardResult?: ProgramBoardResult;
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
        {programBoardResult === undefined ? null : programBoardResult.status ===
          "ok" ? (
          <ProgramLeaderboard
            state="populated"
            items={programBoardResult.data.items}
          />
        ) : (
          <OverviewErrorPanel status={programBoardResult.status} />
        )}
      </div>
    </PersonaDashboardShell>
  );
}
