import { redirect } from "next/navigation";

import { fetchProgramDetail } from "@/lib/programDetailApi";
import { callWithAuth, SessionExpiredError } from "@/lib/tokenStore";
import { ProgramDetailView } from "@/components/ProgramDetailView";
import type { ProgramDetailResult } from "@/types/programDetail";

interface PageProps {
  // Next.js 15: `params` is a Promise in Server Components (must be awaited).
  params: Promise<{ program_id: string }>;
}

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
 * Auth (AUTH-05-AC-5, FR-2/FR-5): the fetch is wrapped in
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
 */
export default async function Page({ params }: PageProps) {
  const { program_id: programId } = await params;

  let result: ProgramDetailResult;
  try {
    result = await callWithAuth(
      (accessToken) => fetchProgramDetail(programId, { accessToken }),
      (r) => r.status === "unauthorized",
    );
  } catch (error) {
    if (error instanceof SessionExpiredError) {
      redirect("/login"); // next/navigation — throws NEXT_REDIRECT, which MUST propagate
    }
    throw error;
  }

  return (
    <ProgramDetailView initialProgramId={programId} initialResult={result} />
  );
}
