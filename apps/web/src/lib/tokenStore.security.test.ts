import {
  afterEach,
  beforeEach,
  describe,
  expect,
  it,
  vi,
  type MockInstance,
} from "vitest";

/**
 * AUTH-05-TC-03 -- the dedicated security run for the story's core no-token-
 * leak invariant (NFR-security primary, NFR-observability rider, AC-4
 * primary). Scoped to exactly the three files TC-03 names: `tokenStore.ts`,
 * `login/route.ts`, `callback/route.ts`.
 *
 * `next/headers` has no jsdom implementation, so it is mocked with a fake
 * cookie jar that records the exact options object every `.set()` call
 * receives -- assertions 3/4 below run against that real recorded call, not
 * a hand-written cookie string. The factory only creates closures over
 * `cookieStorage`/`recordedSetCalls` at call time (never reads them at
 * factory-definition time), matching this repo's existing deferred-closure
 * mock idiom (see `ProgramDetailView.test.tsx`'s `fetchProgramDetail`/
 * `fetchPrograms` mocks) so no `vi.hoisted()` wrapper is needed.
 */

interface RecordedCookieSet {
  name: string;
  value: string;
  options: Record<string, unknown>;
}

let cookieStorage = new Map<string, string>();
let recordedSetCalls: RecordedCookieSet[] = [];

function makeFakeCookieJar() {
  return {
    get(name: string) {
      const value = cookieStorage.get(name);
      return value === undefined ? undefined : { name, value };
    },
    set(name: string, value: string, options: Record<string, unknown>) {
      cookieStorage.set(name, value);
      recordedSetCalls.push({ name, value, options });
    },
    delete(name: string) {
      cookieStorage.delete(name);
    },
  };
}

vi.mock("next/headers", () => ({
  cookies: async () => makeFakeCookieJar(),
}));

const CONSOLE_METHODS = [
  "log",
  "info",
  "warn",
  "error",
  "debug",
  "trace",
] as const;

/** Serialises a logged argument -- including objects, via `JSON.stringify` --
 * so a token hidden inside a logged object is caught, not just plain string
 * arguments (a string-only grep would pass vacuously). */
function serializeArg(arg: unknown): string {
  if (typeof arg === "string") {
    return arg;
  }
  if (arg instanceof Error) {
    return `${arg.name}: ${arg.message}\n${arg.stack ?? ""}`;
  }
  try {
    return JSON.stringify(arg) ?? String(arg);
  } catch {
    return String(arg);
  }
}

function serializeCapturedLogs(calls: unknown[][]): string {
  return calls.flat().map(serializeArg).join("\n");
}

function makeTokenResponse(
  accessToken: string,
  refreshToken: string,
  expiresIn = 900,
): Response {
  return new Response(
    JSON.stringify({
      access_token: accessToken,
      refresh_token: refreshToken,
      expires_in: expiresIn,
    }),
    { status: 200, headers: { "Content-Type": "application/json" } },
  );
}

const JWT_MARKER = "eyJ";
const KEYCLOAK_URL =
  "https://lab.apexonlab.com/apexonlogin/realms/Apexon/protocol/openid-connect/auth?client_id=dashboard&response_type=code";

const ACCESS_TOKEN =
  "eyJhbGciOiJIUzI1NiJ9.dev-bypass-access-fixture.sig-access-one";
const REFRESH_TOKEN =
  "eyJhbGciOiJIUzI1NiJ9.dev-bypass-refresh-fixture.sig-refresh-one";
const PROACTIVE_ACCESS_TOKEN =
  "eyJhbGciOiJIUzI1NiJ9.proactive-access-fixture.sig-access-two";
const PROACTIVE_REFRESH_TOKEN =
  "eyJhbGciOiJIUzI1NiJ9.proactive-refresh-fixture.sig-refresh-two";
const REACTIVE_ACCESS_TOKEN =
  "eyJhbGciOiJIUzI1NiJ9.reactive-access-fixture.sig-access-three";
const REACTIVE_REFRESH_TOKEN =
  "eyJhbGciOiJIUzI1NiJ9.reactive-refresh-fixture.sig-refresh-three";
/** Simulates an upstream error body/thrown error that happens to embed a
 * token-shaped string, so failure branches are proven not to log it either. */
const FAKE_UPSTREAM_LEAK =
  "eyJhbGciOiJIUzI1NiJ9.hypothetical-upstream-body-leak.sig-leak-one";
const FAKE_THROWN_ERROR_LEAK =
  "eyJhbGciOiJIUzI1NiJ9.hypothetical-thrown-error-leak.sig-leak-two";

const ALL_TOKEN_FIXTURES = [
  ACCESS_TOKEN,
  REFRESH_TOKEN,
  PROACTIVE_ACCESS_TOKEN,
  PROACTIVE_REFRESH_TOKEN,
  REACTIVE_ACCESS_TOKEN,
  REACTIVE_REFRESH_TOKEN,
  FAKE_UPSTREAM_LEAK,
  FAKE_THROWN_ERROR_LEAK,
];

describe("AUTH-05-TC-03: no token leak in logs; dashboard_session cookie is HttpOnly/SameSite=Lax(+Secure outside dev)/never client-readable", () => {
  let capturedLogCalls: unknown[][];
  let setItemSpy: MockInstance;

  beforeEach(() => {
    vi.resetModules();
    cookieStorage = new Map<string, string>();
    recordedSetCalls = [];
    capturedLogCalls = [];
    for (const method of CONSOLE_METHODS) {
      vi.spyOn(console, method).mockImplementation((...args: unknown[]) => {
        capturedLogCalls.push(args);
      });
    }
    setItemSpy = vi.spyOn(Storage.prototype, "setItem");
    global.fetch = vi.fn();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllEnvs();
    vi.clearAllMocks();
  });

  it("sanity check: the log-capture harness catches a plain-string leak and one embedded inside a logged object (proves assertion 1 below is not vacuous)", () => {
    console.log("plain string leak", ACCESS_TOKEN);
    console.error({ tokens: { access_token: ACCESS_TOKEN }, note: "nested" });

    const text = serializeCapturedLogs(capturedLogCalls);
    expect(text).toContain(JWT_MARKER);
    expect(text).toContain(ACCESS_TOKEN);
  });

  it("zero token leakage across a full dev-bypass login, a proactive (60s-skew) refresh, a reactive-401 refresh, and every failure branch of login/route.ts and callback/route.ts", async () => {
    const { GET: loginGet } = await import("@/app/login/route");
    const { GET: callbackGet } = await import("@/app/callback/route");
    const tokenStore = await import("@/lib/tokenStore");

    const fetchMock = global.fetch as ReturnType<typeof vi.fn>;
    fetchMock
      // 1. /login happy path
      .mockResolvedValueOnce(
        new Response(null, {
          status: 302,
          headers: { location: KEYCLOAK_URL },
        }),
      )
      // 2. /login failure: 3xx with no Location header
      .mockResolvedValueOnce(new Response(null, { status: 302 }))
      // 3. /login failure: FastAPI's documented 501 (OIDC config incomplete)
      .mockResolvedValueOnce(new Response("Not Implemented", { status: 501 }))
      // 4. /login failure: outbound fetch throws
      .mockRejectedValueOnce(
        new DOMException("The operation was aborted.", "AbortError"),
      )
      // 5. /callback happy path (dev-bypass-shaped token)
      .mockResolvedValueOnce(makeTokenResponse(ACCESS_TOKEN, REFRESH_TOKEN))
      // 6. /callback failure: non-200 whose body happens to embed a token-shaped leak
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({ error: "invalid_grant", hint: FAKE_UPSTREAM_LEAK }),
          { status: 400 },
        ),
      )
      // 7. /callback failure: outbound fetch throws with a token-shaped leak in the error message
      .mockRejectedValueOnce(
        new Error(`upstream failure: ${FAKE_THROWN_ERROR_LEAK}`),
      )
      // 8. proactive 60s-skew refresh
      .mockResolvedValueOnce(
        makeTokenResponse(PROACTIVE_ACCESS_TOKEN, PROACTIVE_REFRESH_TOKEN),
      )
      // 9. reactive-401 forced refresh
      .mockResolvedValueOnce(
        makeTokenResponse(REACTIVE_ACCESS_TOKEN, REACTIVE_REFRESH_TOKEN),
      );

    // 1
    const loginOk = await loginGet();
    expect(loginOk.headers.get("location")).toBe(KEYCLOAK_URL);
    // 2
    const loginNoLocation = await loginGet();
    expect(loginNoLocation.status).toBe(502);
    // 3
    const login501 = await loginGet();
    expect(login501.status).toBe(502);
    // 4
    const loginThrew = await loginGet();
    expect(loginThrew.status).toBe(502);

    // 5
    const callbackOk = await callbackGet(
      new Request(
        "http://localhost:3000/callback?code=test-code&state=test-state",
      ),
    );
    expect(callbackOk.headers.get("location")).toBe("http://localhost:3000/");
    expect(cookieStorage.get(tokenStore.SESSION_COOKIE_NAME)).toBeDefined();

    // 6
    const callbackBadBody = await callbackGet(
      new Request(
        "http://localhost:3000/callback?code=bad-code&state=test-state",
      ),
    );
    expect(callbackBadBody.headers.get("location")).toBe(
      "http://localhost:3000/login",
    );
    // 7
    const callbackThrew = await callbackGet(
      new Request(
        "http://localhost:3000/callback?code=throws&state=test-state",
      ),
    );
    expect(callbackThrew.headers.get("location")).toBe(
      "http://localhost:3000/login",
    );

    // 8. proactive refresh: seed a session 45s from expiry (inside the 60s skew window)
    cookieStorage.set(
      tokenStore.SESSION_COOKIE_NAME,
      JSON.stringify({
        accessToken: ACCESS_TOKEN,
        refreshToken: REFRESH_TOKEN,
        expiresAt: Date.now() + 45_000,
      }),
    );
    const proactive = await tokenStore.ensureTokenValid();
    expect(proactive.accessToken).toBe(PROACTIVE_ACCESS_TOKEN);

    // 9. reactive-401: seed a session with plenty of time left, force one 401-triggered refresh + retry
    cookieStorage.set(
      tokenStore.SESSION_COOKIE_NAME,
      JSON.stringify({
        accessToken: PROACTIVE_ACCESS_TOKEN,
        refreshToken: PROACTIVE_REFRESH_TOKEN,
        expiresAt: Date.now() + 900_000,
      }),
    );
    let makeRequestCalls = 0;
    const reactiveResult = await tokenStore.callWithAuth(
      async (accessToken: string) => {
        makeRequestCalls += 1;
        return { accessToken, unauthorized: makeRequestCalls === 1 };
      },
      (result) => result.unauthorized,
    );
    expect(reactiveResult.accessToken).toBe(REACTIVE_ACCESS_TOKEN);

    // Expected result 1: zero captured log records contain the JWT marker or any raw token value.
    const allLogText = serializeCapturedLogs(capturedLogCalls);
    expect(allLogText).not.toContain(JWT_MARKER);
    for (const token of ALL_TOKEN_FIXTURES) {
      expect(allLogText).not.toContain(token);
    }

    // Expected result 2: any record referencing the session carries at most a
    // non-token identifier, never token content.
    const sessionReferencingCalls = capturedLogCalls.filter((args) =>
      args.some((arg) => serializeArg(arg).toLowerCase().includes("session")),
    );
    for (const call of sessionReferencingCalls) {
      const text = call.map(serializeArg).join(" ");
      expect(text).not.toContain(JWT_MARKER);
      for (const token of ALL_TOKEN_FIXTURES) {
        expect(text).not.toContain(token);
      }
    }
  });

  it("dashboard_session cookie is set with HttpOnly and SameSite=Lax, and Secure only outside local/development", async () => {
    const tokenStore = await import("@/lib/tokenStore");

    await tokenStore.writeSession({
      access_token: ACCESS_TOKEN,
      refresh_token: REFRESH_TOKEN,
      expires_in: 900,
    });

    expect(recordedSetCalls).toHaveLength(1);
    const [localCall] = recordedSetCalls;
    expect(localCall.name).toBe(tokenStore.SESSION_COOKIE_NAME);
    expect(localCall.options.httpOnly).toBe(true);
    expect(localCall.options.sameSite).toBe("lax");
    // Default vitest env is not "production" -- Secure must not be forced on locally.
    expect(localCall.options.secure).toBe(false);

    recordedSetCalls = [];
    vi.stubEnv("NODE_ENV", "production");

    await tokenStore.writeSession({
      access_token: ACCESS_TOKEN,
      refresh_token: REFRESH_TOKEN,
      expires_in: 900,
    });

    expect(recordedSetCalls).toHaveLength(1);
    expect(recordedSetCalls[0].options.secure).toBe(true);
  });

  it("document.cookie never exposes dashboard_session or any token value after a stored login", async () => {
    const { GET: callbackGet } = await import("@/app/callback/route");
    const tokenStore = await import("@/lib/tokenStore");

    const fetchMock = global.fetch as ReturnType<typeof vi.fn>;
    fetchMock.mockResolvedValueOnce(
      makeTokenResponse(ACCESS_TOKEN, REFRESH_TOKEN),
    );

    await callbackGet(
      new Request(
        "http://localhost:3000/callback?code=test-code&state=test-state",
      ),
    );

    expect(document.cookie).not.toContain(tokenStore.SESSION_COOKIE_NAME);
    expect(document.cookie).not.toContain(ACCESS_TOKEN);
    expect(document.cookie).not.toContain(REFRESH_TOKEN);
  });

  it("no token value is ever written to localStorage or sessionStorage across login, callback, and a proactive refresh", async () => {
    const { GET: loginGet } = await import("@/app/login/route");
    const { GET: callbackGet } = await import("@/app/callback/route");
    const tokenStore = await import("@/lib/tokenStore");

    const fetchMock = global.fetch as ReturnType<typeof vi.fn>;
    fetchMock
      .mockResolvedValueOnce(
        new Response(null, {
          status: 302,
          headers: { location: KEYCLOAK_URL },
        }),
      )
      .mockResolvedValueOnce(makeTokenResponse(ACCESS_TOKEN, REFRESH_TOKEN))
      .mockResolvedValueOnce(
        makeTokenResponse(PROACTIVE_ACCESS_TOKEN, PROACTIVE_REFRESH_TOKEN),
      );

    await loginGet();
    await callbackGet(
      new Request(
        "http://localhost:3000/callback?code=test-code&state=test-state",
      ),
    );

    cookieStorage.set(
      tokenStore.SESSION_COOKIE_NAME,
      JSON.stringify({
        accessToken: ACCESS_TOKEN,
        refreshToken: REFRESH_TOKEN,
        expiresAt: Date.now() + 45_000,
      }),
    );
    await tokenStore.ensureTokenValid();

    for (const [, value] of setItemSpy.mock.calls as Array<[string, string]>) {
      expect(value).not.toContain(JWT_MARKER);
      for (const token of ALL_TOKEN_FIXTURES) {
        expect(value).not.toContain(token);
      }
    }
  });
});
