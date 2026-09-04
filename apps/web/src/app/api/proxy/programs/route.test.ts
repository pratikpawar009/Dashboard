import { afterEach, describe, expect, it, vi } from "vitest";

/**
 * `GET /api/proxy/programs` unit test (T-11) -- AUTH-05-AC-10, feeds TC-02
 * (F-18). `@/lib/tokenStore`'s `callWithAuth` is replaced with a faithful
 * fake that actually invokes the supplied `makeRequest` with a test access
 * token, so the assertion that `fetchPrograms` receives that token is not
 * vacuous; `SessionExpiredError` is re-exported from the real module via
 * `importOriginal` so the route's `instanceof` check matches genuinely
 * rather than silently falling through to the 502 branch. `@/lib/
 * programDetailApi`'s `fetchPrograms` is mocked separately. Native vitest
 * mocks only, matching `ProgramDetailView.test.tsx`'s idiom -- no MSW, no
 * `jest-dom` matchers.
 */

const TEST_ACCESS_TOKEN = "test-access-token";

const { callWithAuthMock, fetchProgramsMock } = vi.hoisted(() => ({
  callWithAuthMock: vi.fn(),
  fetchProgramsMock: vi.fn(),
}));

vi.mock("@/lib/tokenStore", async (importOriginal) => {
  const actual = await importOriginal();
  return {
    ...(actual as object),
    callWithAuth: callWithAuthMock,
  };
});

vi.mock("@/lib/programDetailApi", () => ({
  fetchPrograms: fetchProgramsMock,
}));

const { GET } = await import("./route");
const { SessionExpiredError } = await import("@/lib/tokenStore");

const SAMPLE_PROGRAMS = [
  {
    program_id: "p1",
    label: "Program One",
    href: "/programs/p1",
    dotStyle: "background:red",
  },
];

describe("GET /api/proxy/programs (AUTH-05-AC-10)", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("returns the {programs} envelope on a successful upstream call, forwarding the resolved token to fetchPrograms", async () => {
    fetchProgramsMock.mockResolvedValue(SAMPLE_PROGRAMS);
    callWithAuthMock.mockImplementation(
      async (makeRequest: (accessToken: string) => unknown) =>
        makeRequest(TEST_ACCESS_TOKEN),
    );

    const response = await GET();

    expect(response.status).toBe(200);
    const body = await response.json();
    expect(body).toEqual({ programs: SAMPLE_PROGRAMS });

    expect(fetchProgramsMock).toHaveBeenCalledTimes(1);
    expect(fetchProgramsMock).toHaveBeenCalledWith({
      accessToken: TEST_ACCESS_TOKEN,
    });
  });

  it("maps a SessionExpiredError from callWithAuth to 401 {error: session_expired}", async () => {
    callWithAuthMock.mockRejectedValue(new SessionExpiredError("no session"));

    const response = await GET();

    expect(response.status).toBe(401);
    const body = await response.json();
    expect(body).toEqual({ error: "session_expired" });
  });

  it("maps any other throw from callWithAuth to 502 {error: upstream_error}", async () => {
    callWithAuthMock.mockRejectedValue(new Error("boom"));

    const response = await GET();

    expect(response.status).toBe(502);
    const body = await response.json();
    expect(body).toEqual({ error: "upstream_error" });
  });

  it("never leaks the access token to the browser -- no Authorization header, no token value anywhere in the body", async () => {
    fetchProgramsMock.mockResolvedValue(SAMPLE_PROGRAMS);
    callWithAuthMock.mockImplementation(
      async (makeRequest: (accessToken: string) => unknown) =>
        makeRequest(TEST_ACCESS_TOKEN),
    );

    const response = await GET();

    expect(response.headers.get("authorization")).toBeNull();
    const rawBody = await response.text();
    expect(rawBody).not.toContain(TEST_ACCESS_TOKEN);
  });
});
