import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * `logout/route.ts` tests (T-09) -- DECISIONS.md D-08's fixed call order
 * (`readSession()` -> `clearSession()` -> fetch-with-bearer -> relay,
 * AUTH-07-AC-8/AC-9/AC-14/AC-15/AUTH-07-FR-5). Feeds this story's own test
 * mapping (D-07).
 *
 * `next/headers` has no jsdom implementation, so `cookies()` is mocked
 * against an in-memory Map, matching `callback/route.test.ts`'s idiom -- the
 * real `tokenStore.readSession`/`clearSession` run against that fake jar, so
 * asserting the jar's contents proves whether a cookie was actually cleared,
 * not just that a function was invoked. The mock's `get`/`delete` also push
 * into a shared `callOrder` array (only for the session cookie name), and
 * the fetch mock pushes its own entry, so D-08's ordering is asserted
 * directly rather than inferred from side effects alone. `tokenStore` has
 * module-level single-flight state (unused by this route, but shared code),
 * so each test still `vi.resetModules()`s and re-imports both modules fresh.
 */

const state = vi.hoisted(() => ({
  jar: new Map<string, string>(),
  callOrder: [] as string[],
}));

const SESSION_COOKIE_NAME = "dashboard_session";

vi.mock("next/headers", () => ({
  cookies: async () => ({
    get: (name: string) => {
      if (name === SESSION_COOKIE_NAME) {
        state.callOrder.push("read");
      }
      const value = state.jar.get(name);
      return value === undefined ? undefined : { name, value };
    },
    set: (name: string, value: string) => {
      state.jar.set(name, value);
    },
    delete: (name: string) => {
      if (name === SESSION_COOKIE_NAME) {
        state.callOrder.push("clear");
      }
      state.jar.delete(name);
    },
  }),
}));

type RouteModule = typeof import("./route");
type TokenStoreModule = typeof import("@/lib/tokenStore");

const KEYCLOAK_LOGOUT_URL =
  "https://lab.apexonlab.com/apexonlogin/realms/Apexon/protocol/openid-connect/logout?client_id=dashboard&post_logout_redirect_uri=http%3A%2F%2Flocalhost%3A3000%2Flogin";

function manualRedirectResponse(location: string | null, status = 302) {
  const headers = new Headers();
  if (location !== null) {
    headers.set("location", location);
  }
  return new Response(null, { status, headers });
}

/** Records a "fetch" entry in `state.callOrder` before resolving `response`. */
function mockFetchTrackingOrder(response: Response) {
  return vi.fn().mockImplementation(async () => {
    state.callOrder.push("fetch");
    return response;
  });
}

describe("GET /logout (AUTH-07-AC-8, AC-9, AC-14, AC-15, D-08)", () => {
  let route: RouteModule;
  let tokenStore: TokenStoreModule;

  beforeEach(async () => {
    vi.resetModules();
    state.jar.clear();
    state.callOrder.length = 0;
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

  it("D-08 order: reads the session, clears the cookie, forwards the pre-clear token as bearer, then relays the 302 Location verbatim", async () => {
    await tokenStore.writeSession({
      access_token: "pre-clear-access-token",
      refresh_token: "pre-clear-refresh-token",
      expires_in: 900,
    });
    expect(state.jar.get(SESSION_COOKIE_NAME)).not.toBeUndefined();

    global.fetch = mockFetchTrackingOrder(
      manualRedirectResponse(KEYCLOAK_LOGOUT_URL),
    );

    const response = await route.GET();

    // NextResponse.redirect(location) defaults to 307 when no explicit
    // status is passed, matching login/route.test.ts's precedent.
    expect(response.status).toBe(307);
    expect(response.headers.get("location")).toBe(KEYCLOAK_LOGOUT_URL);

    // AC-8: the cookie is cleared before the redirect is relayed.
    expect(state.jar.get(SESSION_COOKIE_NAME)).toBeUndefined();

    // D-08: read -> clear -> fetch, in that exact order.
    expect(state.callOrder).toEqual(["read", "clear", "fetch"]);

    expect(getFetchMock()).toHaveBeenCalledTimes(1);
    const [, init] = getFetchMock().mock.calls[0] as [string, RequestInit];
    expect(init.redirect).toBe("manual");
    expect(init.signal).toBeInstanceOf(AbortSignal);
    expect((init.headers as Record<string, string>).Authorization).toBe(
      "Bearer pre-clear-access-token",
    );
  });

  it("clearSession() runs unconditionally even with no prior session (idempotent), and the relay still proceeds with no Authorization header", async () => {
    expect(state.jar.get(SESSION_COOKIE_NAME)).toBeUndefined();

    global.fetch = mockFetchTrackingOrder(
      manualRedirectResponse(KEYCLOAK_LOGOUT_URL),
    );

    const response = await route.GET();

    expect(response.status).toBe(307);
    expect(response.headers.get("location")).toBe(KEYCLOAK_LOGOUT_URL);
    expect(state.jar.get(SESSION_COOKIE_NAME)).toBeUndefined();
    expect(state.callOrder).toEqual(["read", "clear", "fetch"]);

    const [, init] = getFetchMock().mock.calls[0] as [string, RequestInit];
    expect(
      (init.headers as Record<string, string>).Authorization,
    ).toBeUndefined();
  });

  it("never returns a redirect to a FastAPI origin -- only the Keycloak logout URL relayed in Location", async () => {
    await tokenStore.writeSession({
      access_token: "pre-clear-access-token",
      refresh_token: "pre-clear-refresh-token",
      expires_in: 900,
    });
    global.fetch = mockFetchTrackingOrder(
      manualRedirectResponse(KEYCLOAK_LOGOUT_URL),
    );

    const response = await route.GET();

    const location = response.headers.get("location");
    expect(location).toBe(KEYCLOAK_LOGOUT_URL);
    expect(location).not.toContain("localhost:8000");
    expect(location).not.toContain("/auth/logout");
  });

  it("a missing Location header on an otherwise-3xx response produces the generic error, not a crash -- cookie stays cleared", async () => {
    await tokenStore.writeSession({
      access_token: "pre-clear-access-token",
      refresh_token: "pre-clear-refresh-token",
      expires_in: 900,
    });
    global.fetch = mockFetchTrackingOrder(manualRedirectResponse(null));

    const response = await route.GET();

    expect(response.status).toBe(502);
    expect(response.headers.get("location")).toBeNull();
    expect(state.jar.get(SESSION_COOKIE_NAME)).toBeUndefined();
    const body = await response.text();
    expect(body).toBe("Sign-out is unavailable.");
  });

  it("a non-3xx status -- the documented 501 for an incomplete OIDC/frontend_login_url config -- produces the generic error", async () => {
    global.fetch = mockFetchTrackingOrder(
      new Response("OIDC configuration incomplete", {
        status: 501,
        headers: { "content-type": "text/plain" },
      }),
    );

    const response = await route.GET();

    expect(response.status).toBe(502);
    const body = await response.text();
    expect(body).toBe("Sign-out is unavailable.");
    expect(body).not.toContain("501");
    expect(body).not.toContain("OIDC configuration incomplete");
  });

  it("a thrown/aborted fetch produces the same generic error, with no upstream detail surfaced -- cookie stays cleared", async () => {
    await tokenStore.writeSession({
      access_token: "pre-clear-access-token",
      refresh_token: "pre-clear-refresh-token",
      expires_in: 900,
    });
    global.fetch = vi.fn().mockImplementation(async () => {
      state.callOrder.push("fetch");
      throw new DOMException("The operation was aborted.", "AbortError");
    });

    const response = await route.GET();

    expect(response.status).toBe(502);
    const body = await response.text();
    expect(body).toBe("Sign-out is unavailable.");
    expect(body).not.toContain("AbortError");
    expect(body).not.toContain("operation was aborted");
    expect(state.jar.get(SESSION_COOKIE_NAME)).toBeUndefined();
    expect(state.callOrder).toEqual(["read", "clear", "fetch"]);
  });
});
