import type {
  PersonalSessionsData,
  PersonalSessionsResult,
} from "@/types/personalSessions";

/**
 * `.claude/rules/performance-baseline.md`: every I/O call has an explicit
 * timeout, no silent infinite wait.
 */
const FETCH_TIMEOUT_MS = 5000;

/**
 * Client-only fetcher for `SessionsTable` (SHP-03 T-15), mirroring
 * `memberUsageApi.client.ts`'s shape: targets the frontend's own same-origin
 * `/api/proxy/personal-sessions/[user_id]` Route Handler (T-12), never
 * FastAPI directly -- no `getApiBaseUrl()`, no `Authorization` header, no
 * token concept here (ADR-0008; the proxy resolves and attaches the token
 * server-side).
 *
 * `page`/`page_size` are forwarded verbatim as query params -- this module
 * does not re-clamp them; the backend (`get_page_params`) owns that.
 *
 * Status mapping: `403` -> `denied` (this route sits behind the same
 * `individual_usage_visibility` self-or-cio gate family the personal-usage
 * routes use -- a denial, not a transient failure, checked before the
 * generic non-ok branch); `401` -> `unauthorized` (terminal -- this module
 * never retries it); any other non-ok response (incl. `502`) or a
 * network/timeout throw -> `error`.
 */
export async function fetchPersonalSessions(
  userId: string,
  page: number,
  pageSize: number,
): Promise<PersonalSessionsResult> {
  const query = new URLSearchParams({
    page: String(page),
    page_size: String(pageSize),
  });

  try {
    const response = await fetch(
      `/api/proxy/personal-sessions/${userId}?${query.toString()}`,
      { signal: AbortSignal.timeout(FETCH_TIMEOUT_MS) },
    );

    if (response.status === 403) {
      return { status: "denied" };
    }
    if (response.status === 401) {
      return { status: "unauthorized" };
    }
    if (!response.ok) {
      return { status: "error" };
    }

    const data = (await response.json()) as PersonalSessionsData;
    return { status: "ok", data };
  } catch {
    return { status: "error" };
  }
}
