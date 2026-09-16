import { redirect } from "next/navigation";

import { composeSignedInUser } from "@/lib/composeSignedInUser";
import { fetchMe } from "@/lib/meApi";
import { fetchProgramDetail } from "@/lib/programDetailApi";
import { callWithAuth, SessionExpiredError } from "@/lib/tokenStore";
import { ProgramDetailView } from "@/components/ProgramDetailView";
import type { ProgramDetailResult } from "@/types/programDetail";
import type { Persona, SignedInUser } from "@/types/persona";

interface PageProps {
  // Next.js 15: `params` is a Promise in Server Components (must be awaited).
  params: Promise<{ program_id: string }>;
}

/**
 * Persona-resolution-failure sentinel (OVW-05 DECISIONS.md D-03, reused here
 * per PGD-07 DECISIONS.md D-01 -- not a new symbol). Passed as `persona`
 * whenever the `GET /api/me` call below does not resolve to `"ok"`. Not a
 * real persona value: `PersonaDashboardShell`'s existing `PersonaTagError`
 * catch renders the neutral badge for it, the same as any other unresolvable
 * persona.
 */
const PERSONA_RESOLUTION_ERROR = "persona-resolution-error";

/**
 * `/programs/[program_id]` (T-13) — Server Component entry point.
 *
 * Performs the initial, server-side fetch (DESIGN.md Screen inventory:
 * "server (initial load)") and hands the result to `ProgramDetailView`,
 * which owns every render after that.
 *
 * No route-level `not-found.tsx`/`error.tsx` exists for this segment, and
 * `notFound()` is never called here: DECISIONS.md D-03 makes the 404 an
 * in-page state rendered by `ProgramDetailView`/`ProgramDetailErrorPanel`,
 * not a Next.js route boundary.
 *
 * Switcher reloads (FR-4, D-07) do not re-enter this Server Component: once
 * mounted, `ProgramDetailView` fetches the new program client-side and
 * updates the URL via `next/navigation`'s `router.replace()`, which is a
 * client-side history update, not a navigation back through this page's
 * server render.
 *
 * Auth (AUTH-05-AC-5, FR-2/FR-5): the program-detail fetch is wrapped in
 * `tokenStore.callWithAuth()`, which attaches the session's access token and
 * retries once on a reactive 401. Only a `SessionExpiredError` -- the
 * refresh itself failing -- redirects to `/login`; a `{status:
 * "unauthorized"}` result that survives the retry is not that case and falls
 * through to `ProgramDetailView`'s existing error panel instead, matching
 * D-10. The `redirect()` call is deliberately placed inside the `catch`
 * block, not the `try`: `redirect()` works by throwing its own `NEXT_REDIRECT`
 * control-flow signal, and if it were thrown inside the `try` above, this
 * function's own `catch` would swallow it and turn the redirect into a
 * rendering error instead. Anything that is not a `SessionExpiredError`
 * (including a `NEXT_REDIRECT` bubbling up from elsewhere) is re-thrown, not
 * swallowed.
 *
 * PGD-07 FR-1/FR-3 (Condition C-4): `GET /api/me` (`fetchMe`) is issued
 * concurrently with the program-detail fetch via `Promise.all`, inside this
 * SAME try/catch -- not a second try/catch and not a sequential await chain.
 * This is safe, and deliberately mirrors `app/overview/page.tsx` (OVW-05
 * D-03/D-02): `tokenStore`'s existing single-flight `refreshPromise` guard
 * (FR-1) already dedupes the proactive-refresh race between the two calls,
 * so a `SessionExpiredError` thrown by EITHER fetch -- the program-detail
 * fetch or the `/api/me` fetch -- correctly triggers the exact same
 * `redirect("/login")` below via one coordinated catch, rather than each
 * call racing to redirect independently. On a non-"ok" `/api/me` result
 * (e.g. an isolated 401/403 that survives its own retry), `persona` falls
 * back to the `PERSONA_RESOLUTION_ERROR` sentinel above (D-01) instead of
 * being omitted, and `signedInUser` stays `undefined` -- this does NOT
 * redirect and does NOT affect the program-detail result.
 */
export default async function Page({ params }: PageProps) {
  const { program_id: programId } = await params;

  let result: ProgramDetailResult;
  let persona: Persona;
  let signedInUser: SignedInUser | undefined;
  try {
    const [programDetail, meResult] = await Promise.all([
      callWithAuth(
        (accessToken) => fetchProgramDetail(programId, { accessToken }),
        (r) => r.status === "unauthorized",
      ),
      callWithAuth(
        (accessToken) => fetchMe({ accessToken }),
        (r) => r.status === "unauthorized",
      ),
    ]);
    result = programDetail;
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
    <ProgramDetailView
      initialProgramId={programId}
      initialResult={result}
      persona={persona}
      signedInUser={signedInUser}
    />
  );
}
