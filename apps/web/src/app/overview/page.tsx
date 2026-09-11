import { redirect } from "next/navigation";

import { AdoptionOverview } from "@/components/AdoptionOverview";
import { composeSignedInUser } from "@/lib/composeSignedInUser";
import { fetchMe } from "@/lib/meApi";
import { fetchOverviewSummary } from "@/lib/overviewApi";
import { callWithAuth, SessionExpiredError } from "@/lib/tokenStore";
import type { OverviewSummaryResult } from "@/types/overview";
import type { Persona, SignedInUser } from "@/types/persona";

/**
 * Persona-resolution-failure sentinel (OVW-05 DECISIONS.md D-03) — passed as
 * `persona` whenever the `GET /api/me` call below does not resolve to
 * `"ok"`. Not a real persona value: `PersonaDashboardShell`'s existing
 * `PersonaTagError` catch renders the neutral badge for it, the same as any
 * other unresolvable persona, so no new error UI is introduced. This is the
 * exact literal `PersonaDashboardShell.test.tsx` already exercises for this
 * scenario.
 */
const PERSONA_RESOLUTION_ERROR = "persona-resolution-error";

/**
 * `/overview` (OVW-01, T-14; OVW-05, T-08) — Server Component entry point
 * for the Adoption Overview page.
 *
 * This route did not exist before OVW-01: the app root redirects here and
 * had been 404ing, because `apps/web/src/app` held only `api`, `callback`,
 * `login` and `programs`. `ADOPTION_OVERVIEW_ROUTE` in `lib/routes.ts` already
 * pointed at `/overview` in anticipation, so nothing there needs changing —
 * the App Router file convention self-registers this segment.
 *
 * Performs two concurrent, server-side fetches (DESIGN.md Screen inventory:
 * "server (initial load, no client refetch)") — `GET /api/overview/summary`
 * (org summary data) and `GET /api/me` (`session-identity-api`, brand-bar
 * identity, OVW-05 DECISIONS.md D-02) — and hands the resolved results to
 * `AdoptionOverview`, which owns every render decision from there. Unlike
 * Program Detail there is no client-side refetch path at all — no program
 * switcher, no range toggle — so this Server Component is still the only
 * fetch site, now issuing two calls instead of one.
 *
 * Auth mirrors `programs/[program_id]/page.tsx` deliberately (D-03): each
 * fetch is wrapped in its own `tokenStore.callWithAuth()` call, which
 * attaches the session's access token and retries once on a reactive 401;
 * both calls are issued concurrently via `Promise.all` inside the SAME
 * try/catch below rather than sequentially — safe because `tokenStore`'s
 * existing single-flight `refreshPromise` guard (FR-1) already dedupes the
 * proactive-refresh race between them, so no new concurrency primitive is
 * added (D-02). Only a `SessionExpiredError` from either call — the refresh
 * itself failing — redirects to `/login`.
 *
 * The two calls' non-`SessionExpiredError` failure modes are deliberately
 * asymmetric and must not be merged into one error path: a
 * `{status: "unauthorized"}` overview-summary result that survives the retry
 * falls through to `AdoptionOverview`, which renders `OverviewErrorPanel` for
 * it exactly as it does for `forbidden` and `error` (D-07 — one message for
 * all three, so the copy never reveals whether the resource exists or
 * whether the session is at fault). A non-`"ok"` `/api/me` result does
 * **not** render an error panel — it only degrades the shell's persona
 * display via the `PERSONA_RESOLUTION_ERROR` sentinel above, leaving the
 * summary content unaffected.
 *
 * The `redirect()` call sits inside the `catch`, not the `try`, and this
 * placement is load-bearing rather than stylistic: `redirect()` works by
 * throwing its own `NEXT_REDIRECT` control-flow signal, so calling it inside
 * the `try` would let this function's own `catch` swallow it and convert a
 * redirect into a rendering error. Anything that is not a
 * `SessionExpiredError` — including a `NEXT_REDIRECT` bubbling up from
 * elsewhere — is re-thrown rather than swallowed.
 *
 * No `not-found.tsx` or `error.tsx` exists for this segment and `notFound()`
 * is never called: every non-ok outcome is an in-page state rendered by
 * `AdoptionOverview`, not a Next.js route boundary — the same choice
 * Program Detail made in its own D-03.
 */
export default async function Page() {
  let result: OverviewSummaryResult;
  let persona: Persona;
  let signedInUser: SignedInUser | undefined;
  try {
    const [overviewSummary, meResult] = await Promise.all([
      callWithAuth(
        (accessToken) => fetchOverviewSummary({ accessToken }),
        (r) => r.status === "unauthorized",
      ),
      callWithAuth(
        (accessToken) => fetchMe({ accessToken }),
        (r) => r.status === "unauthorized",
      ),
    ]);
    result = overviewSummary;
    if (meResult.status === "ok") {
      persona = meResult.data.persona;
      signedInUser = composeSignedInUser(meResult.data);
    } else {
      persona = PERSONA_RESOLUTION_ERROR;
      signedInUser = undefined;
    }
  } catch (error) {
    if (error instanceof SessionExpiredError) {
      redirect("/login"); // next/navigation — throws NEXT_REDIRECT, which MUST propagate
    }
    throw error;
  }

  return (
    <AdoptionOverview
      result={result}
      persona={persona}
      signedInUser={signedInUser}
      pageTitle="Adoption Overview"
    />
  );
}
