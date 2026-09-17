import { afterEach, describe, expect, it, vi } from "vitest";
import type { Mock } from "vitest";

/**
 * `route.ts` (T-14) unit tests -- mirrors
 * `apps/web/src/app/api/proxy/program-detail/[program_id]/commands/route.test.ts`
 * exactly: mocking strategy, faithful `callWithAuth` fake, direct `GET()`
 * invocation against a constructed `Request`/`params` Promise.
 *
 * Unlike the commands proxy, this route has no dedicated `@/lib/*Api.ts`
 * fetcher module in scope (T-14's `files[]` is `route.ts` + `route.test.ts`
 * only) -- the upstream `fetch()` call is inlined in `route.ts` itself, so
 * these tests mock the global `fetch` plus `@/lib/tokenStore` rather than a
 * separate lib module.
 *
 * `callWithAuth` is mocked with a faithful fake -- it actually invokes the
 * supplied `makeRequest` (so the inlined `fetchMemberUsage`'s call args are
 * real) and actually evaluates the supplied `isUnauthorized` predicate.
 *
 * `SessionExpiredError` is re-exported from the real `@/lib/tokenStore`
 * module via `vi.importActual` so the route's `error instanceof
 * SessionExpiredError` check matches the same class the test throws.
 */

vi.mock("@/lib/tokenStore", async () => {
  const actual =
    await vi.importActual<typeof import("@/lib/tokenStore")>(
      "@/lib/tokenStore",
    );
  return {
    ...actual,
    callWithAuth: vi.fn(),
  };
});

import { callWithAuth, SessionExpiredError } from "@/lib/tokenStore";

import { GET } from "./route";

const TEST_ACCESS_TOKEN = "test-access-token";
const PROGRAM_ID = "prog-042";
const MEMBER_ID = "user-777";

const SAMPLE_PERSONAL_USAGE = {
  cards: [
    {
      glyph: "sessions",
      value: "12",
      label: "Sessions",
      iconBg: "#eee",
      iconColor: "#333",
    },
  ],
  daily_tokens: { points: [], period_total: "0", avg_per_day: "0" },
  commands: { total_runs: "0", items: [] },
};

function buildRequest(opts?: {
  programId?: string;
  range?: string;
  omitProgramId?: boolean;
}): Request {
  const url = new URL(
    `http://localhost:3000/api/proxy/personal-usage/${MEMBER_ID}`,
  );
  if (!opts?.omitProgramId) {
    url.searchParams.set("program_id", opts?.programId ?? PROGRAM_ID);
  }
  if (opts?.range !== undefined) {
    url.searchParams.set("range", opts.range);
  }
  return new Request(url);
}

function buildParams(memberId: string = MEMBER_ID): {
  params: Promise<{ user_id: string }>;
} {
  return { params: Promise.resolve({ user_id: memberId }) };
}

/**
 * Faithful `callWithAuth` fake (see file docstring): calls `makeRequest`
 * with a fixed test token, and on `isUnauthorized(result)` retries exactly
 * once more with the same token.
 */
function installFaithfulCallWithAuth(): void {
  (callWithAuth as unknown as Mock).mockImplementation(
    async (
      makeRequest: (accessToken: string) => Promise<unknown>,
      isUnauthorized: (result: unknown) => boolean,
    ) => {
      const result = await makeRequest(TEST_ACCESS_TOKEN);
      if (isUnauthorized(result)) {
        return makeRequest(TEST_ACCESS_TOKEN);
      }
      return result;
    },
  );
}

function mockFetchOnce(response: Response): void {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response));
}

describe("GET /api/proxy/personal-usage/[user_id]", () => {
  afterEach(() => {
    vi.clearAllMocks();
    vi.unstubAllGlobals();
  });

  it("400s with missing_program_id and never calls upstream when program_id is absent", async () => {
    installFaithfulCallWithAuth();
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);

    const response = await GET(
      buildRequest({ omitProgramId: true }),
      buildParams(),
    );

    expect(response.status).toBe(400);
    expect(await response.json()).toEqual({ error: "missing_program_id" });
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(callWithAuth).not.toHaveBeenCalled();
  });

  it("calls the PGD-05 sibling route (team/{member_id}/usage), not SHP-02's own /api/personal-usage/{user_id} (D-03/D-04)", async () => {
    installFaithfulCallWithAuth();
    mockFetchOnce(
      new Response(JSON.stringify(SAMPLE_PERSONAL_USAGE), { status: 200 }),
    );

    await GET(buildRequest(), buildParams());

    const calledUrl = (fetch as unknown as Mock).mock.calls[0][0] as string;
    expect(calledUrl).toContain(
      `/api/overview/program-detail/${PROGRAM_ID}/team/${MEMBER_ID}/usage`,
    );
    expect(calledUrl).not.toContain(`/api/personal-usage/${MEMBER_ID}`);
  });

  it("forwards an absent range as omitted from the query string, not the literal string 'undefined'", async () => {
    installFaithfulCallWithAuth();
    mockFetchOnce(
      new Response(JSON.stringify(SAMPLE_PERSONAL_USAGE), { status: 200 }),
    );

    await GET(buildRequest(), buildParams());

    const calledUrl = (fetch as unknown as Mock).mock.calls[0][0] as string;
    expect(calledUrl).not.toContain("range=undefined");
    expect(calledUrl).not.toContain("range=");
  });

  it("forwards a present range unchanged", async () => {
    installFaithfulCallWithAuth();
    mockFetchOnce(
      new Response(JSON.stringify(SAMPLE_PERSONAL_USAGE), { status: 200 }),
    );

    await GET(buildRequest({ range: "7d" }), buildParams());

    const calledUrl = (fetch as unknown as Mock).mock.calls[0][0] as string;
    expect(calledUrl).toContain("range=7d");
  });

  it("awaits params and forwards the resolved member_id plus the resolved access token", async () => {
    installFaithfulCallWithAuth();
    mockFetchOnce(
      new Response(JSON.stringify(SAMPLE_PERSONAL_USAGE), { status: 200 }),
    );

    await GET(buildRequest(), buildParams("user-999"));

    const calledUrl = (fetch as unknown as Mock).mock.calls[0][0] as string;
    expect(calledUrl).toContain(`/team/user-999/usage`);
    const calledInit = (fetch as unknown as Mock).mock.calls[0][1] as {
      headers: Record<string, string>;
    };
    expect(calledInit.headers["Authorization"]).toBe(
      `Bearer ${TEST_ACCESS_TOKEN}`,
    );
  });

  it("maps 200 to a verbatim passthrough of the upstream PersonalUsageResponse body (AC-10, AC-11 -- no reshaping)", async () => {
    installFaithfulCallWithAuth();
    mockFetchOnce(
      new Response(JSON.stringify(SAMPLE_PERSONAL_USAGE), { status: 200 }),
    );

    const response = await GET(buildRequest(), buildParams());

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual(SAMPLE_PERSONAL_USAGE);
  });

  it("maps a 403 upstream denial to 403 {error: 'denied'} with no personal-usage fields in the body (AC-12)", async () => {
    installFaithfulCallWithAuth();
    mockFetchOnce(
      new Response(JSON.stringify({ detail: "Access denied" }), {
        status: 403,
      }),
    );

    const response = await GET(buildRequest(), buildParams());

    expect(response.status).toBe(403);
    const body = await response.json();
    expect(body).toEqual({ error: "denied" });
    expect(body).not.toHaveProperty("cards");
    expect(body).not.toHaveProperty("daily_tokens");
    expect(body).not.toHaveProperty("commands");
  });

  it("maps 'unauthorized' (401 from upstream, retried once via callWithAuth) to 401 {error: 'session_expired'}", async () => {
    installFaithfulCallWithAuth();
    mockFetchOnce(
      new Response(JSON.stringify({ detail: "unauthorized" }), { status: 401 }),
    );

    const response = await GET(buildRequest(), buildParams());

    expect(response.status).toBe(401);
    expect(await response.json()).toEqual({ error: "session_expired" });
    // Faithful fake retries once on isUnauthorized -- proves the predicate
    // the route passed in was actually evaluated, not ignored.
    expect(fetch as unknown as Mock).toHaveBeenCalledTimes(2);
  });

  it("maps any other non-ok upstream response to 502 {error: 'upstream_error'}", async () => {
    installFaithfulCallWithAuth();
    mockFetchOnce(
      new Response(JSON.stringify({ detail: "boom" }), { status: 500 }),
    );

    const response = await GET(buildRequest(), buildParams());

    expect(response.status).toBe(502);
    expect(await response.json()).toEqual({ error: "upstream_error" });
  });

  it("maps a caught SessionExpiredError to the same 401 {error: 'session_expired'}", async () => {
    (callWithAuth as unknown as Mock).mockImplementation(async () => {
      throw new SessionExpiredError("no session");
    });

    const response = await GET(buildRequest(), buildParams());

    expect(response.status).toBe(401);
    expect(await response.json()).toEqual({ error: "session_expired" });
  });

  it("maps any other thrown error (e.g. network failure) to the same 502 {error: 'upstream_error'}", async () => {
    (callWithAuth as unknown as Mock).mockImplementation(async () => {
      throw new Error("boom");
    });

    const response = await GET(buildRequest(), buildParams());

    expect(response.status).toBe(502);
    expect(await response.json()).toEqual({ error: "upstream_error" });
  });

  it("never lets the access token reach the browser -- no Authorization response header, no token in the body", async () => {
    installFaithfulCallWithAuth();
    mockFetchOnce(
      new Response(JSON.stringify(SAMPLE_PERSONAL_USAGE), { status: 200 }),
    );

    const response = await GET(buildRequest(), buildParams());

    expect(response.headers.get("authorization")).toBeNull();
    const bodyText = JSON.stringify(await response.json());
    expect(bodyText).not.toContain(TEST_ACCESS_TOKEN);
  });
});
