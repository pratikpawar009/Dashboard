import { afterEach, describe, expect, it, vi } from "vitest";
import type { Mock } from "vitest";

import type {
  ProgramDetailData,
  ProgramDetailResult,
} from "@/types/programDetail";

/**
 * `route.ts` (T-12) unit tests -- AUTH-05-AC-10. Feeds AUTH-05-TC-02 (F-18);
 * not individually TC-mapped, per `tasks.json` T-13.
 *
 * Direct `GET()` invocation with a constructed `Request`/`params` Promise --
 * `@/lib/tokenStore` and `@/lib/programDetailApi` are both mocked at their
 * `@/*` alias paths (native `vitest` mocks only, no MSW). Unlike
 * `ProgramDetailView.authFlow.test.tsx` (AUTH-05-TC-02), which leaves
 * `tokenStore`/`programDetailApi` real and intercepts only `global.fetch`,
 * this file isolates the route's own wiring: header forwarding, the
 * `isUnauthorized` predicate it hands to `callWithAuth`, and its
 * status-to-HTTP mapping.
 *
 * `callWithAuth` is mocked with a faithful fake -- it actually invokes the
 * supplied `makeRequest` (so `fetchProgramDetail`'s call args are real) and
 * actually evaluates the supplied `isUnauthorized` predicate (so the
 * `(r) => r.status === "unauthorized"` wiring is exercised, not vacuous). A
 * fake that returned a canned value regardless of its arguments would not
 * prove the route wires those callbacks correctly.
 *
 * `SessionExpiredError` is re-exported from the real `@/lib/tokenStore`
 * module via `vi.importActual` so the route's `error instanceof
 * SessionExpiredError` check matches the same class the test throws.
 */

vi.mock("@/lib/programDetailApi", () => ({
  fetchProgramDetail: vi.fn(),
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

import { fetchProgramDetail } from "@/lib/programDetailApi";
import { callWithAuth, SessionExpiredError } from "@/lib/tokenStore";

import { GET } from "./route";

const TEST_ACCESS_TOKEN = "test-access-token";
const PROGRAM_ID = "prog-042";

const SAMPLE_DATA: ProgramDetailData = {
  header: {
    icon: "\u{1F3D7}",
    name: "Platform Modernization",
    type: "Migration",
    description: "Core platform upgrade",
  },
  summary: [{ glyph: "⬡", value: "12", label: "Active workstreams" }],
};

function buildRequest(headers?: Record<string, string>): Request {
  return new Request(
    `http://localhost:3000/api/proxy/program-detail/${PROGRAM_ID}`,
    headers === undefined ? undefined : { headers },
  );
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
      makeRequest: (accessToken: string) => Promise<ProgramDetailResult>,
      isUnauthorized: (result: ProgramDetailResult) => boolean,
    ) => {
      const result = await makeRequest(TEST_ACCESS_TOKEN);
      if (isUnauthorized(result)) {
        return makeRequest(TEST_ACCESS_TOKEN);
      }
      return result;
    },
  );
}

describe("GET /api/proxy/program-detail/[program_id] (AUTH-05-AC-10)", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("forwards a present X-Program-Switch-From header verbatim as opts.switchedFrom", async () => {
    installFaithfulCallWithAuth();
    (fetchProgramDetail as Mock).mockResolvedValue({
      status: "ok",
      data: SAMPLE_DATA,
    });

    await GET(
      buildRequest({ "X-Program-Switch-From": "prog-001" }),
      buildParams(),
    );

    expect(fetchProgramDetail).toHaveBeenCalledWith(PROGRAM_ID, {
      switchedFrom: "prog-001",
      accessToken: TEST_ACCESS_TOKEN,
    });
  });

  it("normalises an absent X-Program-Switch-From header to undefined, not null", async () => {
    installFaithfulCallWithAuth();
    (fetchProgramDetail as Mock).mockResolvedValue({
      status: "ok",
      data: SAMPLE_DATA,
    });

    await GET(buildRequest(), buildParams());

    const [, opts] = (fetchProgramDetail as Mock).mock.calls[0] as [
      string,
      { switchedFrom?: string; accessToken?: string },
    ];
    expect(opts.switchedFrom).toBeUndefined();
    expect(opts.switchedFrom).not.toBeNull();
  });

  it("awaits params and forwards the resolved program_id plus the resolved access token", async () => {
    installFaithfulCallWithAuth();
    (fetchProgramDetail as Mock).mockResolvedValue({
      status: "ok",
      data: SAMPLE_DATA,
    });

    await GET(buildRequest(), buildParams("prog-042"));

    expect(fetchProgramDetail).toHaveBeenCalledWith("prog-042", {
      switchedFrom: undefined,
      accessToken: TEST_ACCESS_TOKEN,
    });
  });

  it("maps status 'ok' to 200 with the bare ProgramDetailData body (no envelope)", async () => {
    installFaithfulCallWithAuth();
    (fetchProgramDetail as Mock).mockResolvedValue({
      status: "ok",
      data: SAMPLE_DATA,
    });

    const response = await GET(buildRequest(), buildParams());

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual(SAMPLE_DATA);
  });

  it("maps status 'not_found' to 404 {error: 'not_found'}", async () => {
    installFaithfulCallWithAuth();
    (fetchProgramDetail as Mock).mockResolvedValue({ status: "not_found" });

    const response = await GET(buildRequest(), buildParams());

    expect(response.status).toBe(404);
    expect(await response.json()).toEqual({ error: "not_found" });
  });

  it("maps status 'unauthorized' to 401 {error: 'session_expired'} via the isUnauthorized predicate", async () => {
    installFaithfulCallWithAuth();
    (fetchProgramDetail as Mock).mockResolvedValue({ status: "unauthorized" });

    const response = await GET(buildRequest(), buildParams());

    expect(response.status).toBe(401);
    expect(await response.json()).toEqual({ error: "session_expired" });
    // Faithful fake retries once on isUnauthorized -- proves the predicate
    // the route passed in was actually evaluated, not ignored.
    expect(fetchProgramDetail).toHaveBeenCalledTimes(2);
  });

  it("maps status 'error' to 502 {error: 'upstream_error'}", async () => {
    installFaithfulCallWithAuth();
    (fetchProgramDetail as Mock).mockResolvedValue({ status: "error" });

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
    (fetchProgramDetail as Mock).mockResolvedValue({
      status: "ok",
      data: SAMPLE_DATA,
    });

    const response = await GET(buildRequest(), buildParams());

    expect(response.headers.get("authorization")).toBeNull();
    const bodyText = JSON.stringify(await response.json());
    expect(bodyText).not.toContain(TEST_ACCESS_TOKEN);
  });
});
