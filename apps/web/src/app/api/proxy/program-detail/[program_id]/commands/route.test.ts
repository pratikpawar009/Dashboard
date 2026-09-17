import { afterEach, describe, expect, it, vi } from "vitest";
import type { Mock } from "vitest";

import type {
  ProgramCommandsData,
  ProgramCommandsResult,
} from "@/types/programCommands";

/**
 * `route.ts` (T-12) unit tests -- mirrors
 * `apps/web/src/app/api/proxy/program-detail/[program_id]/token-trend/route.test.ts`
 * and
 * `apps/web/src/app/api/proxy/program-detail/[program_id]/releases/route.test.ts`
 * exactly: mocking strategy, faithful `callWithAuth` fake, direct `GET()`
 * invocation against a constructed `Request`/`params` Promise.
 *
 * `@/lib/tokenStore` and `@/lib/programCommandsApi` are both mocked at their
 * `@/*` alias paths (native `vitest` mocks only, no MSW). `fetchProgramCommands`
 * is mocked from its own dedicated `@/lib/programCommandsApi` module (PLAN.md
 * F-10), mirroring `programTokenTrendApi.ts`'s dedicated-module precedent.
 *
 * `callWithAuth` is mocked with a faithful fake -- it actually invokes the
 * supplied `makeRequest` (so `fetchProgramCommands`'s call args are real) and
 * actually evaluates the supplied `isUnauthorized` predicate (so the
 * `(r) => r.status === "unauthorized"` wiring is exercised, not vacuous).
 *
 * `SessionExpiredError` is re-exported from the real `@/lib/tokenStore`
 * module via `vi.importActual` so the route's `error instanceof
 * SessionExpiredError` check matches the same class the test throws.
 */

vi.mock("@/lib/programCommandsApi", () => ({
  fetchProgramCommands: vi.fn(),
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

import { fetchProgramCommands } from "@/lib/programCommandsApi";
import { callWithAuth, SessionExpiredError } from "@/lib/tokenStore";

import { GET } from "./route";

const TEST_ACCESS_TOKEN = "test-access-token";
const PROGRAM_ID = "prog-042";

const SAMPLE_DATA: ProgramCommandsData = {
  total_runs: "128",
  items: [{ command: "/deploy", count: 42, barStyle: "width: 100%" }],
};

function buildRequest(range?: string): Request {
  const url = new URL(
    `http://localhost:3000/api/proxy/program-detail/${PROGRAM_ID}/commands`,
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
      makeRequest: (accessToken: string) => Promise<ProgramCommandsResult>,
      isUnauthorized: (result: ProgramCommandsResult) => boolean,
    ) => {
      const result = await makeRequest(TEST_ACCESS_TOKEN);
      if (isUnauthorized(result)) {
        return makeRequest(TEST_ACCESS_TOKEN);
      }
      return result;
    },
  );
}

describe("GET /api/proxy/program-detail/[program_id]/commands", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("forwards an absent range as undefined, not the literal string 'undefined' (AC-1)", async () => {
    installFaithfulCallWithAuth();
    (fetchProgramCommands as Mock).mockResolvedValue({
      status: "ok",
      data: SAMPLE_DATA,
    });

    await GET(buildRequest(), buildParams());

    expect(fetchProgramCommands).toHaveBeenCalledWith(PROGRAM_ID, {
      range: undefined,
      accessToken: TEST_ACCESS_TOKEN,
    });
    const [, opts] = (fetchProgramCommands as Mock).mock.calls[0] as [
      string,
      { range?: string },
    ];
    expect(opts.range).not.toBe("undefined");
  });

  it("forwards a present range unchanged", async () => {
    installFaithfulCallWithAuth();
    (fetchProgramCommands as Mock).mockResolvedValue({
      status: "ok",
      data: SAMPLE_DATA,
    });

    await GET(buildRequest("7d"), buildParams());

    expect(fetchProgramCommands).toHaveBeenCalledWith(PROGRAM_ID, {
      range: "7d",
      accessToken: TEST_ACCESS_TOKEN,
    });
  });

  it("awaits params and forwards the resolved program_id plus the resolved access token", async () => {
    installFaithfulCallWithAuth();
    (fetchProgramCommands as Mock).mockResolvedValue({
      status: "ok",
      data: SAMPLE_DATA,
    });

    await GET(buildRequest(), buildParams("prog-777"));

    expect(fetchProgramCommands).toHaveBeenCalledWith("prog-777", {
      range: undefined,
      accessToken: TEST_ACCESS_TOKEN,
    });
  });

  it("maps status 'ok' to 200 with the bare ProgramCommandsData body (no envelope)", async () => {
    installFaithfulCallWithAuth();
    (fetchProgramCommands as Mock).mockResolvedValue({
      status: "ok",
      data: SAMPLE_DATA,
    });

    const response = await GET(buildRequest(), buildParams());

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual(SAMPLE_DATA);
  });

  // Per D-02 the backend never actually returns `not_found` for this route --
  // an unknown or quiet program_id yields 200 {total_runs: "0", items: []}
  // instead. This branch exists only for ProgramCommandsResult
  // union-exhaustiveness / defensive handling; it is not an expected outcome.
  it("maps status 'not_found' to 404 {error: 'not_found'} (defensive only -- D-02, never hit in production)", async () => {
    installFaithfulCallWithAuth();
    (fetchProgramCommands as Mock).mockResolvedValue({
      status: "not_found",
    });

    const response = await GET(buildRequest(), buildParams());

    expect(response.status).toBe(404);
    expect(await response.json()).toEqual({ error: "not_found" });
  });

  it("maps status 'invalid_range' to 400 {error: 'invalid_range'} -- a caller mistake, never a 502", async () => {
    installFaithfulCallWithAuth();
    (fetchProgramCommands as Mock).mockResolvedValue({ status: "invalid_range" });

    const response = await GET(buildRequest("bogus"), buildParams());

    expect(response.status).toBe(400);
    expect(await response.json()).toEqual({ error: "invalid_range" });
    // AF-05: the API's explicit 400 invalid_range must not be collapsed into the
    // generic 502 upstream_error, which would report a caller mistake as an outage.
    expect(response.status).not.toBe(502);
  });

  it("maps status 'unauthorized' to 401 {error: 'session_expired'} via the isUnauthorized predicate", async () => {
    installFaithfulCallWithAuth();
    (fetchProgramCommands as Mock).mockResolvedValue({
      status: "unauthorized",
    });

    const response = await GET(buildRequest(), buildParams());

    expect(response.status).toBe(401);
    expect(await response.json()).toEqual({ error: "session_expired" });
    // Faithful fake retries once on isUnauthorized -- proves the predicate
    // the route passed in was actually evaluated, not ignored.
    expect(fetchProgramCommands).toHaveBeenCalledTimes(2);
  });

  it("maps status 'error' to 502 {error: 'upstream_error'}", async () => {
    installFaithfulCallWithAuth();
    (fetchProgramCommands as Mock).mockResolvedValue({ status: "error" });

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
    (fetchProgramCommands as Mock).mockResolvedValue({
      status: "ok",
      data: SAMPLE_DATA,
    });

    const response = await GET(buildRequest(), buildParams());

    // Sentinel token flows into the mocked upstream call...
    expect(fetchProgramCommands).toHaveBeenCalledWith(PROGRAM_ID, {
      range: undefined,
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
