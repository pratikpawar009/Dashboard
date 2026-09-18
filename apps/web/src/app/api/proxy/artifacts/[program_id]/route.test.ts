import { afterEach, describe, expect, it, vi } from "vitest";
import type { Mock } from "vitest";

import type { ArtifactsData, ArtifactsResult } from "@/types/artifacts";

/**
 * `route.ts` (T-11) unit tests -- mirrors
 * `apps/web/src/app/api/proxy/program-detail/[program_id]/team/route.test.ts`
 * exactly: mocking strategy, faithful `callWithAuth` fake, direct `GET()`
 * invocation against a constructed `Request`/`params` Promise.
 *
 * `@/lib/tokenStore` and `@/lib/artifactsApi` are both mocked at their `@/*`
 * alias paths (native `vitest` mocks only, no MSW). `fetchProgramArtifacts`
 * is mocked from its own dedicated `@/lib/artifactsApi` module.
 *
 * `callWithAuth` is mocked with a faithful fake -- it actually invokes the
 * supplied `makeRequest` (so `fetchProgramArtifacts`'s call args are real)
 * and actually evaluates the supplied `isUnauthorized` predicate (so the
 * `(r) => r.status === "unauthorized"` wiring is exercised, not vacuous).
 *
 * `SessionExpiredError` is re-exported from the real `@/lib/tokenStore`
 * module via `vi.importActual` so the route's `error instanceof
 * SessionExpiredError` check matches the same class the test throws.
 *
 * Unlike the `team`/`releases` siblings, this route takes NO query params --
 * no `range` to forward, no `invalid_range` mapping. `buildRequest`/
 * `buildParams` are simplified accordingly: `buildRequest` takes no args.
 */

vi.mock("@/lib/artifactsApi", () => ({
  fetchProgramArtifacts: vi.fn(),
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

import { fetchProgramArtifacts } from "@/lib/artifactsApi";
import { callWithAuth, SessionExpiredError } from "@/lib/tokenStore";

import { GET } from "./route";

const TEST_ACCESS_TOKEN = "test-access-token";
const PROGRAM_ID = "prog-042";

const SAMPLE_DATA: ArtifactsData = {
  items: [
    {
      tag: "PRD",
      name: "Product requirements",
      count: 12,
      bg: "#e6f4ec",
      color: "#1f8a5b",
    },
    {
      tag: "US",
      name: "User stories",
      count: 34,
      bg: "#e6f4ec",
      color: "#1f8a5b",
    },
    {
      tag: "TC",
      name: "Test cases",
      count: 56,
      bg: "#e6f4ec",
      color: "#1f8a5b",
    },
    {
      tag: "AD",
      name: "Architecture diagrams",
      count: 3,
      bg: "#e6f4ec",
      color: "#1f8a5b",
    },
    {
      tag: "API",
      name: "API specs",
      count: 7,
      bg: "#e6f4ec",
      color: "#1f8a5b",
    },
  ],
};

function buildRequest(): Request {
  const url = new URL(
    `http://localhost:3000/api/proxy/artifacts/${PROGRAM_ID}`,
  );
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
      makeRequest: (accessToken: string) => Promise<ArtifactsResult>,
      isUnauthorized: (result: ArtifactsResult) => boolean,
    ) => {
      const result = await makeRequest(TEST_ACCESS_TOKEN);
      if (isUnauthorized(result)) {
        return makeRequest(TEST_ACCESS_TOKEN);
      }
      return result;
    },
  );
}

describe("GET /api/proxy/artifacts/[program_id]", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("awaits params and forwards the resolved program_id plus the resolved access token", async () => {
    installFaithfulCallWithAuth();
    (fetchProgramArtifacts as Mock).mockResolvedValue({
      status: "ok",
      data: SAMPLE_DATA,
    });

    await GET(buildRequest(), buildParams("prog-777"));

    expect(fetchProgramArtifacts).toHaveBeenCalledWith("prog-777", {
      accessToken: TEST_ACCESS_TOKEN,
    });
  });

  it("maps status 'ok' to 200 with the bare ArtifactsData body (no envelope)", async () => {
    installFaithfulCallWithAuth();
    (fetchProgramArtifacts as Mock).mockResolvedValue({
      status: "ok",
      data: SAMPLE_DATA,
    });

    const response = await GET(buildRequest(), buildParams());

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual(SAMPLE_DATA);
  });

  it("maps status 'unauthorized' to 401 {error: 'session_expired'} via the isUnauthorized predicate", async () => {
    installFaithfulCallWithAuth();
    (fetchProgramArtifacts as Mock).mockResolvedValue({
      status: "unauthorized",
    });

    const response = await GET(buildRequest(), buildParams());

    expect(response.status).toBe(401);
    expect(await response.json()).toEqual({ error: "session_expired" });
    // Faithful fake retries once on isUnauthorized -- proves the predicate
    // the route passed in was actually evaluated, not ignored.
    expect(fetchProgramArtifacts).toHaveBeenCalledTimes(2);
  });

  it("maps status 'error' to 502 {error: 'upstream_error'}", async () => {
    installFaithfulCallWithAuth();
    (fetchProgramArtifacts as Mock).mockResolvedValue({ status: "error" });

    const response = await GET(buildRequest(), buildParams());

    expect(response.status).toBe(502);
    expect(await response.json()).toEqual({ error: "upstream_error" });
  });

  it("surfaces a FastAPI 403 governance denial as 502 {error: 'upstream_error'}, not a 403 -- ArtifactsResult has no 'forbidden' variant", async () => {
    // fetchProgramArtifacts() folds any non-401 non-ok response (including a
    // 403 governance_visibility denial) into the generic {status: "error"}
    // branch -- there is no dedicated forbidden/governance-denied variant on
    // ArtifactsResult. This test documents that a legitimate permission
    // denial deliberately reads as an upstream failure here, matching the
    // `team` proxy this route mirrors (route.ts docstring).
    installFaithfulCallWithAuth();
    (fetchProgramArtifacts as Mock).mockResolvedValue({ status: "error" });

    const response = await GET(buildRequest(), buildParams());

    expect(response.status).toBe(502);
    expect(response.status).not.toBe(403);
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
    (fetchProgramArtifacts as Mock).mockResolvedValue({
      status: "ok",
      data: SAMPLE_DATA,
    });

    const response = await GET(buildRequest(), buildParams());

    // Sentinel token flows into the mocked upstream call...
    expect(fetchProgramArtifacts).toHaveBeenCalledWith(PROGRAM_ID, {
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
