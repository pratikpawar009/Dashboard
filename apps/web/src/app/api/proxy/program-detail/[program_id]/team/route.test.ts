import { afterEach, describe, expect, it, vi } from "vitest";
import type { Mock } from "vitest";

import type { ProgramTeamData, ProgramTeamResult } from "@/types/programTeam";

/**
 * `route.ts` (T-13) unit tests -- mirrors
 * `apps/web/src/app/api/proxy/program-detail/[program_id]/commands/route.test.ts`
 * exactly: mocking strategy, faithful `callWithAuth` fake, direct `GET()`
 * invocation against a constructed `Request`/`params` Promise.
 *
 * `@/lib/tokenStore` and `@/lib/programTeamApi` are both mocked at their
 * `@/*` alias paths (native `vitest` mocks only, no MSW). `fetchProgramTeam`
 * is mocked from its own dedicated `@/lib/programTeamApi` module.
 *
 * `callWithAuth` is mocked with a faithful fake -- it actually invokes the
 * supplied `makeRequest` (so `fetchProgramTeam`'s call args are real) and
 * actually evaluates the supplied `isUnauthorized` predicate (so the
 * `(r) => r.status === "unauthorized"` wiring is exercised, not vacuous).
 *
 * `SessionExpiredError` is re-exported from the real `@/lib/tokenStore`
 * module via `vi.importActual` so the route's `error instanceof
 * SessionExpiredError` check matches the same class the test throws.
 */

vi.mock("@/lib/programTeamApi", () => ({
  fetchProgramTeam: vi.fn(),
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

import { fetchProgramTeam } from "@/lib/programTeamApi";
import { callWithAuth, SessionExpiredError } from "@/lib/tokenStore";

import { GET } from "./route";

const TEST_ACCESS_TOKEN = "test-access-token";
const PROGRAM_ID = "prog-042";

const SAMPLE_DATA: ProgramTeamData = {
  items: [
    {
      member_id: "user-ada-lovelace",
      member_name: "Ada Lovelace",
      role: "Engineer",
      sessions: 12,
      tokens: 48000,
      avg_tokens_per_session: 4000,
    },
  ],
};

function buildRequest(range?: string): Request {
  const url = new URL(
    `http://localhost:3000/api/proxy/program-detail/${PROGRAM_ID}/team`,
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
      makeRequest: (accessToken: string) => Promise<ProgramTeamResult>,
      isUnauthorized: (result: ProgramTeamResult) => boolean,
    ) => {
      const result = await makeRequest(TEST_ACCESS_TOKEN);
      if (isUnauthorized(result)) {
        return makeRequest(TEST_ACCESS_TOKEN);
      }
      return result;
    },
  );
}

describe("GET /api/proxy/program-detail/[program_id]/team", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("forwards an absent range as undefined, not the literal string 'undefined'", async () => {
    installFaithfulCallWithAuth();
    (fetchProgramTeam as Mock).mockResolvedValue({
      status: "ok",
      data: SAMPLE_DATA,
    });

    await GET(buildRequest(), buildParams());

    expect(fetchProgramTeam).toHaveBeenCalledWith(PROGRAM_ID, {
      range: undefined,
      accessToken: TEST_ACCESS_TOKEN,
    });
    const [, opts] = (fetchProgramTeam as Mock).mock.calls[0] as [
      string,
      { range?: string },
    ];
    expect(opts.range).not.toBe("undefined");
  });

  it("forwards a present range unchanged", async () => {
    installFaithfulCallWithAuth();
    (fetchProgramTeam as Mock).mockResolvedValue({
      status: "ok",
      data: SAMPLE_DATA,
    });

    await GET(buildRequest("7d"), buildParams());

    expect(fetchProgramTeam).toHaveBeenCalledWith(PROGRAM_ID, {
      range: "7d",
      accessToken: TEST_ACCESS_TOKEN,
    });
  });

  it("awaits params and forwards the resolved program_id plus the resolved access token", async () => {
    installFaithfulCallWithAuth();
    (fetchProgramTeam as Mock).mockResolvedValue({
      status: "ok",
      data: SAMPLE_DATA,
    });

    await GET(buildRequest(), buildParams("prog-777"));

    expect(fetchProgramTeam).toHaveBeenCalledWith("prog-777", {
      range: undefined,
      accessToken: TEST_ACCESS_TOKEN,
    });
  });

  it("maps status 'ok' to 200 with the bare ProgramTeamData body (no envelope)", async () => {
    installFaithfulCallWithAuth();
    (fetchProgramTeam as Mock).mockResolvedValue({
      status: "ok",
      data: SAMPLE_DATA,
    });

    const response = await GET(buildRequest(), buildParams());

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual(SAMPLE_DATA);
  });

  it("maps status 'invalid_range' to 400 {error: 'invalid_range'} -- a caller mistake, never a 502", async () => {
    installFaithfulCallWithAuth();
    (fetchProgramTeam as Mock).mockResolvedValue({ status: "invalid_range" });

    const response = await GET(buildRequest("bogus"), buildParams());

    expect(response.status).toBe(400);
    expect(await response.json()).toEqual({ error: "invalid_range" });
    // AF-05: the API's explicit 400 invalid_range must not be collapsed into the
    // generic 502 upstream_error, which would report a caller mistake as an outage.
    expect(response.status).not.toBe(502);
  });

  it("maps status 'unauthorized' to 401 {error: 'session_expired'} via the isUnauthorized predicate", async () => {
    installFaithfulCallWithAuth();
    (fetchProgramTeam as Mock).mockResolvedValue({
      status: "unauthorized",
    });

    const response = await GET(buildRequest(), buildParams());

    expect(response.status).toBe(401);
    expect(await response.json()).toEqual({ error: "session_expired" });
    // Faithful fake retries once on isUnauthorized -- proves the predicate
    // the route passed in was actually evaluated, not ignored.
    expect(fetchProgramTeam).toHaveBeenCalledTimes(2);
  });

  it("maps status 'error' to 502 {error: 'upstream_error'}", async () => {
    installFaithfulCallWithAuth();
    (fetchProgramTeam as Mock).mockResolvedValue({ status: "error" });

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
    (fetchProgramTeam as Mock).mockResolvedValue({
      status: "ok",
      data: SAMPLE_DATA,
    });

    const response = await GET(buildRequest(), buildParams());

    // Sentinel token flows into the mocked upstream call...
    expect(fetchProgramTeam).toHaveBeenCalledWith(PROGRAM_ID, {
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
