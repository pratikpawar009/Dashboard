import { afterEach, describe, expect, it, vi } from "vitest";
import type { Mock } from "vitest";

/**
 * `route.ts` (T-12) unit tests -- mirrors
 * `apps/web/src/app/api/proxy/personal-usage/[user_id]/route.test.ts`
 * exactly: mocking strategy, faithful `callWithAuth` fake, direct `GET()`
 * invocation against a constructed `Request`/`params` Promise.
 *
 * Like that sibling (and unlike the artifacts/team proxies), this route has
 * no dedicated `@/lib/*Api.ts` fetcher module in scope (T-12's `files[]` is
 * `route.ts` + `route.test.ts` only) -- the upstream `fetch()` call is
 * inlined in `route.ts` itself, so these tests mock the global `fetch` plus
 * `@/lib/tokenStore` rather than a separate lib module.
 *
 * `callWithAuth` is mocked with a faithful fake -- it actually invokes the
 * supplied `makeRequest` (so the inlined `fetchPersonalSessions`'s call args
 * are real) and actually evaluates the supplied `isUnauthorized` predicate.
 *
 * `SessionExpiredError` is re-exported from the real `@/lib/tokenStore`
 * module via `vi.importActual` so the route's `error instanceof
 * SessionExpiredError` check matches the same class the test throws.
 *
 * Unlike the personal-usage sibling, this route takes `page`/`page_size`
 * query params (not `range`), and has no `missing_program_id` 400 branch --
 * there is no `program_id` on this route at all.
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
const USER_ID = "user-777";

const SAMPLE_PERSONAL_SESSIONS = {
  items: [
    {
      title: "S-1088",
      meta: "S-1088 · Jul 5, 2026",
      duration: "42m",
      tokens: "12.3K",
    },
  ],
  page: 1,
  page_size: 20,
  total: 1,
};

function buildRequest(opts?: { page?: string; pageSize?: string }): Request {
  const url = new URL(
    `http://localhost:3000/api/proxy/personal-sessions/${USER_ID}`,
  );
  if (opts?.page !== undefined) {
    url.searchParams.set("page", opts.page);
  }
  if (opts?.pageSize !== undefined) {
    url.searchParams.set("page_size", opts.pageSize);
  }
  return new Request(url);
}

function buildParams(userId: string = USER_ID): {
  params: Promise<{ user_id: string }>;
} {
  return { params: Promise.resolve({ user_id: userId }) };
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

describe("GET /api/proxy/personal-sessions/[user_id]", () => {
  afterEach(() => {
    vi.clearAllMocks();
    vi.unstubAllGlobals();
  });

  it("awaits params and forwards the resolved user_id plus the resolved access token", async () => {
    installFaithfulCallWithAuth();
    mockFetchOnce(
      new Response(JSON.stringify(SAMPLE_PERSONAL_SESSIONS), { status: 200 }),
    );

    await GET(buildRequest(), buildParams("user-999"));

    const calledUrl = (fetch as unknown as Mock).mock.calls[0][0] as string;
    expect(calledUrl).toContain(`/api/personal-usage/user-999/sessions`);
    const calledInit = (fetch as unknown as Mock).mock.calls[0][1] as {
      headers: Record<string, string>;
    };
    expect(calledInit.headers["Authorization"]).toBe(
      `Bearer ${TEST_ACCESS_TOKEN}`,
    );
  });

  it("forwards page and page_size verbatim when present", async () => {
    installFaithfulCallWithAuth();
    mockFetchOnce(
      new Response(JSON.stringify(SAMPLE_PERSONAL_SESSIONS), { status: 200 }),
    );

    await GET(buildRequest({ page: "3", pageSize: "150" }), buildParams());

    const calledUrl = (fetch as unknown as Mock).mock.calls[0][0] as string;
    expect(calledUrl).toContain("page=3");
    // Pinned: the proxy must NOT clamp page_size itself -- 150 forwards as
    // 150 verbatim, the backend's get_page_params owns clamping.
    expect(calledUrl).toContain("page_size=150");
  });

  it("forwards absent page/page_size as omitted from the query string, not the literal string 'undefined'", async () => {
    installFaithfulCallWithAuth();
    mockFetchOnce(
      new Response(JSON.stringify(SAMPLE_PERSONAL_SESSIONS), { status: 200 }),
    );

    await GET(buildRequest(), buildParams());

    const calledUrl = (fetch as unknown as Mock).mock.calls[0][0] as string;
    expect(calledUrl).not.toContain("page=undefined");
    expect(calledUrl).not.toContain("page_size=undefined");
    expect(calledUrl).not.toContain("page=");
    expect(calledUrl).not.toContain("page_size=");
  });

  it("maps 200 to a verbatim passthrough of the upstream PersonalSessionsData body -- {items, page, page_size, total} with no reshaping", async () => {
    installFaithfulCallWithAuth();
    mockFetchOnce(
      new Response(JSON.stringify(SAMPLE_PERSONAL_SESSIONS), { status: 200 }),
    );

    const response = await GET(buildRequest(), buildParams());

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual(SAMPLE_PERSONAL_SESSIONS);
  });

  it("maps a 403 upstream denial to 403 {error: 'denied'} with no upstream data body leaking through", async () => {
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
    expect(body).not.toHaveProperty("items");
    expect(body).not.toHaveProperty("page");
    expect(body).not.toHaveProperty("page_size");
    expect(body).not.toHaveProperty("total");
  });

  it("maps 'unauthorized' (401 from upstream, retried once via callWithAuth) to 401 {error: 'session_expired'}", async () => {
    installFaithfulCallWithAuth();
    mockFetchOnce(
      new Response(JSON.stringify({ detail: "unauthorized" }), {
        status: 401,
      }),
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

  it("maps a network/timeout failure (fetch throws) to 502 {error: 'upstream_error'}", async () => {
    installFaithfulCallWithAuth();
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("timeout")));

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

  it("maps any other thrown error to the same 502 {error: 'upstream_error'}", async () => {
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
      new Response(JSON.stringify(SAMPLE_PERSONAL_SESSIONS), { status: 200 }),
    );

    const response = await GET(buildRequest(), buildParams());

    expect(response.headers.get("authorization")).toBeNull();
    const bodyText = JSON.stringify(await response.json());
    expect(bodyText).not.toContain(TEST_ACCESS_TOKEN);
  });
});
