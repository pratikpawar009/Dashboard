import { afterEach, describe, expect, it, vi } from "vitest";
import type { Mock } from "vitest";

import type {
  SessionSeriesData,
  SessionSeriesResult,
} from "@/types/programSessionSeries";

/**
 * `route.ts` (T-10) unit tests -- mirrors
 * `apps/web/src/app/api/proxy/program-detail/[program_id]/token-trend/route.test.ts`
 * exactly: mocking strategy, faithful `callWithAuth` fake, direct `GET()`
 * invocation against a constructed `Request`/`params` Promise.
 *
 * `@/lib/tokenStore` and `@/lib/programSessionSeriesApi` are both mocked at
 * their `@/*` alias paths (native `vitest` mocks only, no MSW).
 *
 * `callWithAuth` is mocked with a faithful fake -- it actually invokes the
 * supplied `makeRequest` (so `fetchProgramSessionSeries`'s call args are
 * real) and actually evaluates the supplied `isUnauthorized` predicate (so
 * the `(r) => r.status === "unauthorized"` wiring is exercised, not
 * vacuous).
 *
 * `SessionExpiredError` is re-exported from the real `@/lib/tokenStore`
 * module via `vi.importActual` so the route's `error instanceof
 * SessionExpiredError` check matches the same class the test throws.
 *
 * The upstream route 403s when `member_in_program_visibility` denies a non-self
 * `member_id`. That maps to `SessionSeriesResult`'s `denied` and is passed
 * through as `403 {error:"denied"}` (AF-01, story AC-5) -- deliberately NOT
 * collapsed into the generic `502 upstream_error`, so a consumer can tell a
 * permission decision from an upstream outage. Covered below by its own case.
 */

vi.mock("@/lib/programSessionSeriesApi", () => ({
  fetchProgramSessionSeries: vi.fn(),
}));

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

import { fetchProgramSessionSeries } from "@/lib/programSessionSeriesApi";
import { callWithAuth, SessionExpiredError } from "@/lib/tokenStore";

import { GET } from "./route";

const TEST_ACCESS_TOKEN = "test-access-token";
const PROGRAM_ID = "prog-042";

const SAMPLE_DATA: SessionSeriesData = {
  points: [{ date: "2026-09-01", session_time_seconds: 3600 }],
  period_total_seconds: 3600,
  avg_seconds_per_day: 120,
};

function buildRequest(range?: string, memberId?: string): Request {
  const url = new URL(
    `http://localhost:3000/api/proxy/program-detail/${PROGRAM_ID}/session-time-series`,
  );
  if (range !== undefined) {
    url.searchParams.set("range", range);
  }
  if (memberId !== undefined) {
    url.searchParams.set("member_id", memberId);
  }
  return new Request(url);
}

function buildParams(programId: string = PROGRAM_ID): {
  params: Promise<{ program_id: string }>;
} {
  return { params: Promise.resolve({ program_id: programId }) };
}

/**
 * Faithful `callWithAuth` fake (see file docstring): calls `makeRequest`
 * with a fixed test token, and on `isUnauthorized(result)` retries exactly
 * once more with the same token -- mirroring the real retry-once contract
 * closely enough to exercise the route's predicate wiring honestly.
 */
function installFaithfulCallWithAuth(): void {
  (callWithAuth as unknown as Mock).mockImplementation(
    async (
      makeRequest: (accessToken: string) => Promise<SessionSeriesResult>,
      isUnauthorized: (result: SessionSeriesResult) => boolean,
    ) => {
      const result = await makeRequest(TEST_ACCESS_TOKEN);
      if (isUnauthorized(result)) {
        return makeRequest(TEST_ACCESS_TOKEN);
      }
      return result;
    },
  );
}

describe("GET /api/proxy/program-detail/[program_id]/session-time-series", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("forwards an absent range as undefined, not the literal string 'undefined' (AC-1)", async () => {
    installFaithfulCallWithAuth();
    (fetchProgramSessionSeries as Mock).mockResolvedValue({
      status: "ok",
      data: SAMPLE_DATA,
    });

    await GET(buildRequest(), buildParams());

    expect(fetchProgramSessionSeries).toHaveBeenCalledWith(
      PROGRAM_ID,
      undefined,
      undefined,
      { accessToken: TEST_ACCESS_TOKEN },
    );
    const [, range] = (fetchProgramSessionSeries as Mock).mock.calls[0] as [
      string,
      string | undefined,
    ];
    expect(range).not.toBe("undefined");
  });

  it("forwards a present range unchanged", async () => {
    installFaithfulCallWithAuth();
    (fetchProgramSessionSeries as Mock).mockResolvedValue({
      status: "ok",
      data: SAMPLE_DATA,
    });

    await GET(buildRequest("90d"), buildParams());

    expect(fetchProgramSessionSeries).toHaveBeenCalledWith(
      PROGRAM_ID,
      "90d",
      undefined,
      { accessToken: TEST_ACCESS_TOKEN },
    );
  });

  it("omits member_id upstream when absent, not as an empty/undefined string", async () => {
    installFaithfulCallWithAuth();
    (fetchProgramSessionSeries as Mock).mockResolvedValue({
      status: "ok",
      data: SAMPLE_DATA,
    });

    await GET(buildRequest("30d"), buildParams());

    const [, , memberId] = (fetchProgramSessionSeries as Mock).mock
      .calls[0] as [string, string | undefined, string | undefined];
    expect(memberId).toBeUndefined();
    expect(memberId).not.toBe("undefined");
  });

  it("forwards a present member_id unchanged", async () => {
    installFaithfulCallWithAuth();
    (fetchProgramSessionSeries as Mock).mockResolvedValue({
      status: "ok",
      data: SAMPLE_DATA,
    });

    await GET(buildRequest("30d", "user-9"), buildParams());

    expect(fetchProgramSessionSeries).toHaveBeenCalledWith(
      PROGRAM_ID,
      "30d",
      "user-9",
      { accessToken: TEST_ACCESS_TOKEN },
    );
  });

  it("awaits params and forwards the resolved program_id plus the resolved access token", async () => {
    installFaithfulCallWithAuth();
    (fetchProgramSessionSeries as Mock).mockResolvedValue({
      status: "ok",
      data: SAMPLE_DATA,
    });

    await GET(buildRequest(), buildParams("prog-777"));

    expect(fetchProgramSessionSeries).toHaveBeenCalledWith(
      "prog-777",
      undefined,
      undefined,
      { accessToken: TEST_ACCESS_TOKEN },
    );
  });

  it("maps status 'ok' to 200 with the bare SessionSeriesData body (no envelope)", async () => {
    installFaithfulCallWithAuth();
    (fetchProgramSessionSeries as Mock).mockResolvedValue({
      status: "ok",
      data: SAMPLE_DATA,
    });

    const response = await GET(buildRequest(), buildParams());

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual(SAMPLE_DATA);
  });

  it("maps status 'denied' to 403 {error: 'denied'} -- a denied non-self member_id stays a denial, never a 502", async () => {
    installFaithfulCallWithAuth();
    (fetchProgramSessionSeries as Mock).mockResolvedValue({
      status: "denied",
    });

    const response = await GET(buildRequest("30d", "user-9"), buildParams());

    expect(response.status).toBe(403);
    expect(await response.json()).toEqual({ error: "denied" });
    // AF-01/AC-5: the denial must be distinguishable from an upstream outage,
    // so it must NOT surface as the 502 the generic "error" branch returns.
    expect(response.status).not.toBe(502);
    // A denial is terminal, not a refresh-and-retry case: the isUnauthorized
    // predicate is false for "denied", so callWithAuth must not retry.
    expect(fetchProgramSessionSeries).toHaveBeenCalledTimes(1);
  });

  it("maps status 'unauthorized' to 401 {error: 'session_expired'} via the isUnauthorized predicate", async () => {
    installFaithfulCallWithAuth();
    (fetchProgramSessionSeries as Mock).mockResolvedValue({
      status: "unauthorized",
    });

    const response = await GET(buildRequest(), buildParams());

    expect(response.status).toBe(401);
    expect(await response.json()).toEqual({ error: "session_expired" });
    // Faithful fake retries once on isUnauthorized -- proves the predicate
    // the route passed in was actually evaluated, not ignored.
    expect(fetchProgramSessionSeries).toHaveBeenCalledTimes(2);
  });

  it("maps status 'error' to 502 {error: 'upstream_error'} -- a genuine upstream failure, distinct from the 403 denial case above", async () => {
    installFaithfulCallWithAuth();
    (fetchProgramSessionSeries as Mock).mockResolvedValue({ status: "error" });

    const response = await GET(buildRequest("30d", "user-9"), buildParams());

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
    (fetchProgramSessionSeries as Mock).mockResolvedValue({
      status: "ok",
      data: SAMPLE_DATA,
    });

    const response = await GET(buildRequest(), buildParams());

    // Sentinel token flows into the mocked upstream call...
    expect(fetchProgramSessionSeries).toHaveBeenCalledWith(
      PROGRAM_ID,
      undefined,
      undefined,
      { accessToken: TEST_ACCESS_TOKEN },
    );
    // ...but never into any response header or body. If route.ts ever
    // echoed the token (e.g. into a header or the JSON body), this
    // assertion would fail.
    expect(response.headers.get("authorization")).toBeNull();
    const bodyText = JSON.stringify(await response.json());
    expect(bodyText).not.toContain(TEST_ACCESS_TOKEN);
  });
});
