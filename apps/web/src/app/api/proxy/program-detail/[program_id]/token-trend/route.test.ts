import { afterEach, describe, expect, it, vi } from "vitest";
import type { Mock } from "vitest";

import type {
  ProgramTokenTrendData,
  ProgramTokenTrendResult,
} from "@/types/programTokenTrend";

/**
 * `route.ts` (T-10) unit tests -- mirrors
 * `apps/web/src/app/api/proxy/program-detail/[program_id]/route.test.ts`
 * (T-13/AUTH-05-AC-10) exactly: mocking strategy, faithful `callWithAuth`
 * fake, direct `GET()` invocation against a constructed `Request`/`params`
 * Promise.
 *
 * `@/lib/tokenStore` and `@/lib/programTokenTrendApi` are both mocked at
 * their `@/*` alias paths (native `vitest` mocks only, no MSW).
 *
 * `callWithAuth` is mocked with a faithful fake -- it actually invokes the
 * supplied `makeRequest` (so `fetchProgramTokenTrend`'s call args are real)
 * and actually evaluates the supplied `isUnauthorized` predicate (so the
 * `(r) => r.status === "unauthorized"` wiring is exercised, not vacuous).
 *
 * `SessionExpiredError` is re-exported from the real `@/lib/tokenStore`
 * module via `vi.importActual` so the route's `error instanceof
 * SessionExpiredError` check matches the same class the test throws.
 *
 * F-01 (FLAGS.md): the 400->502 collapse (`fetchProgramTokenTrend`'s
 * `{status:"error"}` on any non-404/401 non-2xx response, rendered here as
 * 502 `upstream_error`) is a KNOWN, ACCEPTED behaviour for this endpoint --
 * tests below assert `error` -> 502 as shipped, not a wished-for 400
 * passthrough.
 */

vi.mock("@/lib/programTokenTrendApi", () => ({
  fetchProgramTokenTrend: vi.fn(),
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

import { fetchProgramTokenTrend } from "@/lib/programTokenTrendApi";
import { callWithAuth, SessionExpiredError } from "@/lib/tokenStore";

import { GET } from "./route";

const TEST_ACCESS_TOKEN = "test-access-token";
const PROGRAM_ID = "prog-042";

const SAMPLE_DATA: ProgramTokenTrendData = {
  points: [{ date: "2026-09-01", tokens: 842 }],
  period_total: 842,
  avg_per_day: 121,
};

function buildRequest(range?: string): Request {
  const url = new URL(
    `http://localhost:3000/api/proxy/program-detail/${PROGRAM_ID}/token-trend`,
  );
  if (range !== undefined) {
    url.searchParams.set("range", range);
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
      makeRequest: (accessToken: string) => Promise<ProgramTokenTrendResult>,
      isUnauthorized: (result: ProgramTokenTrendResult) => boolean,
    ) => {
      const result = await makeRequest(TEST_ACCESS_TOKEN);
      if (isUnauthorized(result)) {
        return makeRequest(TEST_ACCESS_TOKEN);
      }
      return result;
    },
  );
}

describe("GET /api/proxy/program-detail/[program_id]/token-trend", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("forwards an absent range as undefined, not the literal string 'undefined' (AC-1)", async () => {
    installFaithfulCallWithAuth();
    (fetchProgramTokenTrend as Mock).mockResolvedValue({
      status: "ok",
      data: SAMPLE_DATA,
    });

    await GET(buildRequest(), buildParams());

    expect(fetchProgramTokenTrend).toHaveBeenCalledWith(PROGRAM_ID, undefined, {
      accessToken: TEST_ACCESS_TOKEN,
    });
    const [, range] = (fetchProgramTokenTrend as Mock).mock.calls[0] as [
      string,
      string | undefined,
    ];
    expect(range).not.toBe("undefined");
  });

  it("forwards a present range unchanged", async () => {
    installFaithfulCallWithAuth();
    (fetchProgramTokenTrend as Mock).mockResolvedValue({
      status: "ok",
      data: SAMPLE_DATA,
    });

    await GET(buildRequest("90d"), buildParams());

    expect(fetchProgramTokenTrend).toHaveBeenCalledWith(PROGRAM_ID, "90d", {
      accessToken: TEST_ACCESS_TOKEN,
    });
  });

  it("awaits params and forwards the resolved program_id plus the resolved access token", async () => {
    installFaithfulCallWithAuth();
    (fetchProgramTokenTrend as Mock).mockResolvedValue({
      status: "ok",
      data: SAMPLE_DATA,
    });

    await GET(buildRequest(), buildParams("prog-777"));

    expect(fetchProgramTokenTrend).toHaveBeenCalledWith("prog-777", undefined, {
      accessToken: TEST_ACCESS_TOKEN,
    });
  });

  it("maps status 'ok' to 200 with the bare ProgramTokenTrendData body (no envelope)", async () => {
    installFaithfulCallWithAuth();
    (fetchProgramTokenTrend as Mock).mockResolvedValue({
      status: "ok",
      data: SAMPLE_DATA,
    });

    const response = await GET(buildRequest(), buildParams());

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual(SAMPLE_DATA);
  });

  it("maps status 'not_found' to 404 {error: 'not_found'}", async () => {
    installFaithfulCallWithAuth();
    (fetchProgramTokenTrend as Mock).mockResolvedValue({
      status: "not_found",
    });

    const response = await GET(buildRequest(), buildParams());

    expect(response.status).toBe(404);
    expect(await response.json()).toEqual({ error: "not_found" });
  });

  it("maps status 'unauthorized' to 401 {error: 'session_expired'} via the isUnauthorized predicate", async () => {
    installFaithfulCallWithAuth();
    (fetchProgramTokenTrend as Mock).mockResolvedValue({
      status: "unauthorized",
    });

    const response = await GET(buildRequest(), buildParams());

    expect(response.status).toBe(401);
    expect(await response.json()).toEqual({ error: "session_expired" });
    // Faithful fake retries once on isUnauthorized -- proves the predicate
    // the route passed in was actually evaluated, not ignored.
    expect(fetchProgramTokenTrend).toHaveBeenCalledTimes(2);
  });

  it("maps status 'error' to 502 {error: 'upstream_error'} -- includes the F-01 400-collapse case as shipped", async () => {
    installFaithfulCallWithAuth();
    (fetchProgramTokenTrend as Mock).mockResolvedValue({ status: "error" });

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
    (fetchProgramTokenTrend as Mock).mockResolvedValue({
      status: "ok",
      data: SAMPLE_DATA,
    });

    const response = await GET(buildRequest(), buildParams());

    // Sentinel token flows into the mocked upstream call...
    expect(fetchProgramTokenTrend).toHaveBeenCalledWith(PROGRAM_ID, undefined, {
      accessToken: TEST_ACCESS_TOKEN,
    });
    // ...but never into any response header or body. If route.ts ever
    // echoed the token (e.g. into a header or the JSON body), this
    // assertion would fail.
    expect(response.headers.get("authorization")).toBeNull();
    const bodyText = JSON.stringify(await response.json());
    expect(bodyText).not.toContain(TEST_ACCESS_TOKEN);
  });
});
