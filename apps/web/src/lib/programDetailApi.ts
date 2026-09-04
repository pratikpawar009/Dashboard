import { getApiBaseUrl } from "@/lib/apiConfig";
import type {
  ProgramDetailData,
  ProgramSwitcherEntry,
} from "@/types/programDetail";

/**
 * `.claude/rules/performance-baseline.md`: every I/O call has an explicit
 * timeout, no silent infinite wait.
 */
const FETCH_TIMEOUT_MS = 5000;

/**
 * Additive on purpose (DECISIONS.md D-08) -- a future `accessToken` field
 * extends this object rather than renaming either call's signature.
 */
export interface FetchProgramDetailOptions {
  switchedFrom?: string;
}

/**
 * `fetchProgramDetail()`'s result (T-07). Both `ProgramDetailView` and
 * `page.tsx` consume this discriminated union.
 */
export type ProgramDetailResult =
  | { status: "ok"; data: ProgramDetailData }
  | { status: "not_found" }
  | { status: "error" };

/**
 * `GET /api/overview/program-detail/{programId}` (ADR-0007).
 *
 * Sets `X-Program-Switch-From` only when `opts.switchedFrom` is provided --
 * absent means an initial page load, present means a switcher-triggered
 * reload (DECISIONS.md D-07). A 404 maps to `not_found`; any other non-ok
 * response or a network/timeout throw maps to `error`.
 */
export async function fetchProgramDetail(
  programId: string,
  opts?: FetchProgramDetailOptions,
): Promise<ProgramDetailResult> {
  const headers: HeadersInit = {};
  if (opts?.switchedFrom) {
    headers["X-Program-Switch-From"] = opts.switchedFrom;
  }

  try {
    // D-08: no Authorization header -- no frontend token-acquisition
    // mechanism exists yet (accepted, disclosed gap; carried forward as
    // `frontend-auth-token-gap`).
    const response = await fetch(
      `${getApiBaseUrl()}/api/overview/program-detail/${programId}`,
      { headers, signal: AbortSignal.timeout(FETCH_TIMEOUT_MS) },
    );

    if (response.status === 404) {
      return { status: "not_found" };
    }
    if (!response.ok) {
      return { status: "error" };
    }

    const data = (await response.json()) as ProgramDetailData;
    return { status: "ok", data };
  } catch {
    return { status: "error" };
  }
}

/**
 * `GET /api/programs` (ADR-0005), for the switch-program selector's option
 * list. Returns `[]` on ANY failure -- a degraded switcher must never block
 * the rest of the page from rendering.
 */
export async function fetchPrograms(): Promise<ProgramSwitcherEntry[]> {
  try {
    // D-08: no Authorization header -- see fetchProgramDetail() above.
    const response = await fetch(`${getApiBaseUrl()}/api/programs`, {
      signal: AbortSignal.timeout(FETCH_TIMEOUT_MS),
    });
    if (!response.ok) {
      return [];
    }
    const body = (await response.json()) as {
      programs: ProgramSwitcherEntry[];
    };
    return body.programs;
  } catch {
    return [];
  }
}
