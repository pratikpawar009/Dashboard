import { redirect } from "next/navigation";

import { AdoptionOverview } from "@/components/AdoptionOverview";
import { fetchOverviewSummary } from "@/lib/overviewApi";
import { callWithAuth, SessionExpiredError } from "@/lib/tokenStore";
import type { OverviewSummaryResult } from "@/types/overview";

/**
 * `/overview` (OVW-01, T-14) — Server Component entry point for the Adoption
 * Overview page.
 *
 * This route did not exist before this story: the app root redirects here and
 * had been 404ing, because `apps/web/src/app` held only `api`, `callback`,
 * `login` and `programs`. `ADOPTION_OVERVIEW_ROUTE` in `lib/routes.ts` already
 * pointed at `/overview` in anticipation, so nothing there needs changing —
 * the App Router file convention self-registers this segment.
 *
 * Performs the initial, server-side fetch (DESIGN.md Screen inventory:
 * "server (initial load, no client refetch)") and hands the resolved result to
 * `AdoptionOverview`, which owns every render decision from there. Unlike
 * Program Detail there is no client-side refetch path at all — no program
 * switcher, no range toggle — so this Server Component is the only fetch site.
 *
 * Auth mirrors `programs/[program_id]/page.tsx` deliberately (D-03): the fetch
 * is wrapped in `tokenStore.callWithAuth()`, which attaches the session's
 * access token and retries once on a reactive 401. Only a
 * `SessionExpiredError` — the refresh itself failing — redirects to `/login`.
 * A `{status: "unauthorized"}` result that survives the retry is *not* that
 * case and falls through to `AdoptionOverview`, which renders
 * `OverviewErrorPanel` for it exactly as it does for `forbidden` and `error`
 * (D-07 — one message for all three, so the copy never reveals whether the
 * resource exists or whether the session is at fault).
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
  try {
    result = await callWithAuth(
      (accessToken) => fetchOverviewSummary({ accessToken }),
      (r) => r.status === "unauthorized",
    );
  } catch (error) {
    if (error instanceof SessionExpiredError) {
      redirect("/login"); // next/navigation — throws NEXT_REDIRECT, which MUST propagate
    }
    throw error;
  }

  return <AdoptionOverview result={result} />;
}
