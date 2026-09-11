import { afterEach, describe, expect, it, vi } from "vitest";

import { GET } from "./route";

/**
 * AUTH-05-AC-2: the browser must land on Keycloak's own authorization URL,
 * never on a FastAPI origin. Covers T-08's happy path (manual-redirect relay)
 * and the uniform generic-error fallback (missing Location, non-3xx status
 * incl. the documented 501, and a thrown/aborted fetch) -- feeds TC-02
 * (F-18). Native `vitest` mocks only, matching
 * `ProgramDetailView.test.tsx`'s idiom -- no MSW, no `jest-dom` matchers.
 */

const KEYCLOAK_URL =
  "https://lab.apexonlab.com/apexonlogin/realms/Apexon/protocol/openid-connect/auth?client_id=dashboard&state=abc";

function manualRedirectResponse(location: string | null, status = 302) {
  const headers = new Headers();
  if (location !== null) {
    headers.set("location", location);
  }
  return new Response(null, { status, headers });
}

describe("GET /login (AUTH-05-AC-2)", () => {
  afterEach(() => {
    vi.clearAllMocks();
    vi.unstubAllGlobals();
  });

  it("relays FastAPI's manual-redirect Location header as the returned redirect", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(manualRedirectResponse(KEYCLOAK_URL));
    vi.stubGlobal("fetch", fetchMock);

    const response = await GET();

    // `NextResponse.redirect(location)` defaults to 307 when no explicit
    // status is passed -- route.ts never sets one, so 307 is what it
    // actually returns; the load-bearing assertion is the target URL.
    expect(response.status).toBe(307);
    expect(response.headers.get("location")).toBe(KEYCLOAK_URL);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(init.redirect).toBe("manual");
    expect(init.signal).toBeInstanceOf(AbortSignal);
  });

  it("never returns a redirect to a FastAPI origin -- only the Keycloak URL relayed in Location", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(manualRedirectResponse(KEYCLOAK_URL));
    vi.stubGlobal("fetch", fetchMock);

    const response = await GET();

    const location = response.headers.get("location");
    expect(location).toBe(KEYCLOAK_URL);
    expect(location).not.toContain("localhost:8000");
    expect(location).not.toContain("/auth/login");
  });

  it("a missing Location header on an otherwise-3xx response produces the generic error, not a crash", async () => {
    const fetchMock = vi.fn().mockResolvedValue(manualRedirectResponse(null));
    vi.stubGlobal("fetch", fetchMock);

    const response = await GET();

    expect(response.status).toBe(502);
    expect(response.headers.get("location")).toBeNull();
    const body = await response.text();
    expect(body).toBe("Sign-in is unavailable.");
  });

  it("a non-3xx status -- the documented 501 for an incomplete OIDC config -- produces the generic error", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response("OIDC configuration incomplete", {
        status: 501,
        headers: { "content-type": "text/plain" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const response = await GET();

    expect(response.status).toBe(502);
    const body = await response.text();
    expect(body).toBe("Sign-in is unavailable.");
    expect(body).not.toContain("501");
    expect(body).not.toContain("OIDC configuration incomplete");
  });

  it("a thrown/aborted fetch produces the same generic error, with no upstream detail surfaced", async () => {
    const fetchMock = vi
      .fn()
      .mockRejectedValue(
        new DOMException("The operation was aborted.", "AbortError"),
      );
    vi.stubGlobal("fetch", fetchMock);

    const response = await GET();

    expect(response.status).toBe(502);
    const body = await response.text();
    expect(body).toBe("Sign-in is unavailable.");
    expect(body).not.toContain("AbortError");
    expect(body).not.toContain("operation was aborted");
  });
});
