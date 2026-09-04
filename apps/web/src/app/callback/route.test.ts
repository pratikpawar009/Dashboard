import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * `callback/route.ts` tests (T-09) -- AUTH-05-AC-3 (server-to-server relay:
 * a FastAPI 200 writes the session cookie and redirects to `/`; any non-200
 * response or a thrown/aborted fetch clears the session and redirects to
 * `/login`, never surfacing FastAPI's raw status/body) and AUTH-05-AC-4
 * (only the query params Keycloak actually sent -- `code`/`state`/`error` --
 * are forwarded upstream, never an empty/null placeholder for an absent
 * one). Feeds TC-02 (F-18).
 *
 * `next/headers` has no jsdom implementation, so `cookies()` is mocked
 * against an in-memory Map, matching `tokenStore.test.ts`'s idiom -- the
 * real `tokenStore.writeSession`/`clearSession` run against that fake jar,
 * so asserting the jar's contents proves whether a cookie was actually
 * written, not just that a function was invoked. `tokenStore` has
 * module-level single-flight state (unused by this route, but shared code),
 * so each test still `vi.resetModules()`s and re-imports both modules fresh.
 */

const mockCookieStore = vi.hoisted(() => ({ jar: new Map<string, string>() }));

vi.mock("next/headers", () => ({
  cookies: async () => ({
    get: (name: string) => {
      const value = mockCookieStore.jar.get(name);
      return value === undefined ? undefined : { name, value };
    },
    set: (name: string, value: string) => {
      mockCookieStore.jar.set(name, value);
    },
    delete: (name: string) => {
      mockCookieStore.jar.delete(name);
    },
  }),
}));

type RouteModule = typeof import("./route");
type TokenStoreModule = typeof import("@/lib/tokenStore");

const CALLBACK_BASE_URL = "http://localhost:3000/callback";

function callbackRequest(params: Record<string, string>): Request {
  const url = new URL(CALLBACK_BASE_URL);
  for (const [key, value] of Object.entries(params)) {
    url.searchParams.set(key, value);
  }
  return new Request(url);
}

function tokenResponse(overrides?: {
  access_token?: string;
  refresh_token?: string;
  expires_in?: number;
}): Response {
  return new Response(
    JSON.stringify({
      access_token: "issued-access-token",
      refresh_token: "issued-refresh-token",
      expires_in: 900,
      ...overrides,
    }),
    { status: 200 },
  );
}

describe("GET /callback (AUTH-05-AC-3, AUTH-05-AC-4)", () => {
  let route: RouteModule;
  let tokenStore: TokenStoreModule;

  beforeEach(async () => {
    vi.resetModules();
    mockCookieStore.jar.clear();
    global.fetch = vi.fn();
    route = await import("./route");
    tokenStore = await import("@/lib/tokenStore");
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  function getFetchMock(): ReturnType<typeof vi.fn> {
    return global.fetch as ReturnType<typeof vi.fn>;
  }

  it("on a 200 from FastAPI, writes exactly the returned token triple to the session cookie and redirects to /", async () => {
    getFetchMock().mockResolvedValue(tokenResponse());

    const response = await route.GET(
      callbackRequest({ code: "auth-code", state: "abc" }),
    );

    expect(response.status).toBe(307);
    expect(response.headers.get("location")).toBe("http://localhost:3000/");

    const persisted = mockCookieStore.jar.get(tokenStore.SESSION_COOKIE_NAME);
    expect(persisted).not.toBeUndefined();
    const stored = JSON.parse(persisted as string) as {
      accessToken: string;
      refreshToken: string;
      expiresAt: number;
    };
    expect(stored.accessToken).toBe("issued-access-token");
    expect(stored.refreshToken).toBe("issued-refresh-token");

    expect(getFetchMock()).toHaveBeenCalledTimes(1);
    const [calledUrl, init] = getFetchMock().mock.calls[0] as [
      URL,
      RequestInit,
    ];
    expect(new URL(String(calledUrl)).pathname).toBe("/auth/callback");
    expect(init.signal).toBeInstanceOf(AbortSignal);
  });

  it("forwards only code and state when no error param is present on the incoming request -- never an empty/null error", async () => {
    getFetchMock().mockResolvedValue(tokenResponse());

    await route.GET(
      callbackRequest({ code: "auth-code-123", state: "state-abc" }),
    );

    const [calledUrl] = getFetchMock().mock.calls[0] as [URL, RequestInit];
    const upstreamUrl = new URL(String(calledUrl));
    expect(upstreamUrl.searchParams.get("code")).toBe("auth-code-123");
    expect(upstreamUrl.searchParams.get("state")).toBe("state-abc");
    expect(upstreamUrl.searchParams.has("error")).toBe(false);
  });

  it("forwards a Keycloak-reported error param when present, without inventing a code", async () => {
    getFetchMock().mockResolvedValue(
      new Response("invalid_grant", { status: 400 }),
    );

    await route.GET(
      callbackRequest({ state: "state-xyz", error: "access_denied" }),
    );

    const [calledUrl] = getFetchMock().mock.calls[0] as [URL, RequestInit];
    const upstreamUrl = new URL(String(calledUrl));
    expect(upstreamUrl.searchParams.get("state")).toBe("state-xyz");
    expect(upstreamUrl.searchParams.get("error")).toBe("access_denied");
    expect(upstreamUrl.searchParams.has("code")).toBe(false);
  });

  it("FastAPI 400 (invalid_state/missing_code) -- no cookie write, redirects to /login, no raw body surfaced", async () => {
    const upstreamBody = "invalid_state: state token expired or already used";
    getFetchMock().mockResolvedValue(
      new Response(upstreamBody, { status: 400 }),
    );

    const response = await route.GET(
      callbackRequest({ state: "unknown-state" }),
    );

    expect(response.status).toBe(307);
    expect(response.headers.get("location")).toBe(
      "http://localhost:3000/login",
    );
    expect(
      mockCookieStore.jar.get(tokenStore.SESSION_COOKIE_NAME),
    ).toBeUndefined();

    const body = await response.text();
    expect(body).not.toContain(upstreamBody);
    expect(body).not.toContain("400");
  });

  it("FastAPI 401 (failed exchange or IdP-reported error) -- no cookie write, redirects to /login, no raw body surfaced", async () => {
    const upstreamBody = "code exchange failed";
    getFetchMock().mockResolvedValue(
      new Response(upstreamBody, { status: 401 }),
    );

    const response = await route.GET(
      callbackRequest({ code: "auth-code", state: "abc" }),
    );

    expect(response.status).toBe(307);
    expect(response.headers.get("location")).toBe(
      "http://localhost:3000/login",
    );
    expect(
      mockCookieStore.jar.get(tokenStore.SESSION_COOKIE_NAME),
    ).toBeUndefined();

    const body = await response.text();
    expect(body).not.toContain(upstreamBody);
    expect(body).not.toContain("401");
  });

  it("a thrown/aborted fetch -- no cookie write, redirects to /login, no thrown detail surfaced", async () => {
    getFetchMock().mockRejectedValue(
      new DOMException("The operation was aborted.", "AbortError"),
    );

    const response = await route.GET(
      callbackRequest({ code: "auth-code", state: "abc" }),
    );

    expect(response.status).toBe(307);
    expect(response.headers.get("location")).toBe(
      "http://localhost:3000/login",
    );
    expect(
      mockCookieStore.jar.get(tokenStore.SESSION_COOKIE_NAME),
    ).toBeUndefined();

    const body = await response.text();
    expect(body).not.toContain("AbortError");
    expect(body).not.toContain("operation was aborted");
  });

  it("pre-existing session cookie is cleared, not left stale, when a later callback attempt fails", async () => {
    await tokenStore.writeSession({
      access_token: "stale-access-token",
      refresh_token: "stale-refresh-token",
      expires_in: 900,
    });
    expect(
      mockCookieStore.jar.get(tokenStore.SESSION_COOKIE_NAME),
    ).not.toBeUndefined();

    getFetchMock().mockResolvedValue(
      new Response("server_error", { status: 500 }),
    );

    const response = await route.GET(
      callbackRequest({ code: "auth-code", state: "abc" }),
    );

    expect(response.headers.get("location")).toBe(
      "http://localhost:3000/login",
    );
    expect(
      mockCookieStore.jar.get(tokenStore.SESSION_COOKIE_NAME),
    ).toBeUndefined();
  });
});
