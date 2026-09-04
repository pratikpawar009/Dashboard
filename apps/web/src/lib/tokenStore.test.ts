import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * `tokenStore.ts` tests (T-06) -- AUTH-05-TC-01 (single-flight guard,
 * expires_in-derived scheduling, 5s relay timeout) and AUTH-05-TC-04
 * (non-2xx refresh clears the session and signals `SessionExpiredError`).
 *
 * `next/headers` has no jsdom implementation, so `cookies()` is mocked below
 * against an in-memory Map (`mockCookieStore.jar`), declared via
 * `vi.hoisted()` so the hoisted `vi.mock()` factory may reference it.
 * `tokenStore`'s single-flight guard (`refreshPromise`) is module-level
 * state, so every test `vi.resetModules()`s and re-imports the module fresh
 * -- otherwise one test's in-flight refresh would leak into the next.
 *
 * Out of scope here (T-07's `tokenStore.security.test.ts`): log-capture
 * assertions and cookie-attribute (`httpOnly`/`secure`/`sameSite`) assertions.
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

interface Deferred<T> {
  promise: Promise<T>;
  resolve: (value: T) => void;
}

/** Lets a test control exactly when a mocked `fetch` call resolves. */
function createDeferred<T>(): Deferred<T> {
  let resolveFn: (value: T) => void = () => undefined;
  const promise = new Promise<T>((res) => {
    resolveFn = res;
  });
  return { promise, resolve: resolveFn };
}

/** The `POST /auth/refresh` 200 body from the TC-01 fixture (expires_in: 900). */
function refreshResponseBody(overrides?: {
  access_token?: string;
  refresh_token?: string;
  expires_in?: number;
}): string {
  return JSON.stringify({
    access_token: "new-access-token",
    refresh_token: "new-refresh-token",
    expires_in: 900,
    ...overrides,
  });
}

type TokenStoreModule = typeof import("@/lib/tokenStore");

describe("tokenStore.ts (T-06)", () => {
  let tokenStore: TokenStoreModule;

  beforeEach(async () => {
    vi.resetModules();
    mockCookieStore.jar.clear();
    global.fetch = vi.fn();
    tokenStore = await import("@/lib/tokenStore");
  });

  /** `global.fetch` is reassigned fresh in `beforeEach`; cast it where needed. */
  function getFetchMock(): ReturnType<typeof vi.fn> {
    return global.fetch as ReturnType<typeof vi.fn>;
  }

  afterEach(() => {
    vi.clearAllMocks();
    vi.useRealTimers();
  });

  describe("AUTH-05-TC-01 -- single-flight guard, expires_in-derived scheduling, 5s relay timeout", () => {
    const FIXED_NOW = new Date("2026-01-01T00:00:00.000Z").getTime();

    beforeEach(() => {
      vi.useFakeTimers();
      vi.setSystemTime(FIXED_NOW);
    });

    it("collapses two concurrent ensureTokenValid() callers into exactly one POST /auth/refresh, resolving both to the identical refreshed session, with the next deadline derived from expires_in and an AbortSignal on the relay", async () => {
      await tokenStore.writeSession({
        access_token: "initial-access-token",
        refresh_token: "initial-refresh-token",
        expires_in: 45, // inside the 60s proactive-skew window
      });

      const refreshDeferred = createDeferred<Response>();
      getFetchMock().mockReturnValue(refreshDeferred.promise);

      const callerA = tokenStore.ensureTokenValid();
      const callerB = tokenStore.ensureTokenValid();

      // Flush microtasks so both callers reach the single-flight guard while
      // the refresh fetch is still unresolved -- this proves the second
      // caller awaited the first's in-flight refreshPromise instead of
      // racing its own POST /auth/refresh.
      for (let i = 0; i < 10; i++) {
        await Promise.resolve();
      }
      expect(getFetchMock()).toHaveBeenCalledTimes(1);

      refreshDeferred.resolve(
        new Response(refreshResponseBody(), { status: 200 }),
      );

      const [sessionA, sessionB] = await Promise.all([callerA, callerB]);

      expect(getFetchMock()).toHaveBeenCalledTimes(1);
      expect(sessionA).toBe(sessionB);
      expect(sessionA.accessToken).toBe("new-access-token");
      expect(sessionA.refreshToken).toBe("new-refresh-token");

      const [, options] = getFetchMock().mock.calls[0] as [string, RequestInit];
      expect(options.signal).toBeInstanceOf(AbortSignal);

      const persisted = mockCookieStore.jar.get(tokenStore.SESSION_COOKIE_NAME);
      expect(persisted).not.toBeUndefined();
      const persistedSession = JSON.parse(persisted as string) as {
        expiresAt: number;
      };
      expect(persistedSession.expiresAt).toBe(FIXED_NOW + 900_000);
    });

    it("callWithAuth's reactive-401 path issues exactly one refresh and retries makeRequest exactly once with the new access token", async () => {
      await tokenStore.writeSession({
        access_token: "stale-access-token",
        refresh_token: "stale-refresh-token",
        expires_in: 3600, // outside the skew -- getValidAccessToken()'s proactive check is a no-op
      });

      getFetchMock().mockResolvedValueOnce(
        new Response(
          refreshResponseBody({
            access_token: "refreshed-access-token",
            refresh_token: "refreshed-refresh-token",
          }),
          { status: 200 },
        ),
      );

      const makeRequest = vi
        .fn()
        .mockImplementationOnce(async (accessToken: string) => ({
          status: 401,
          accessToken,
        }))
        .mockImplementationOnce(async (accessToken: string) => ({
          status: 200,
          accessToken,
        }));
      const isUnauthorized = (result: { status: number }) =>
        result.status === 401;

      const result = await tokenStore.callWithAuth(makeRequest, isUnauthorized);

      expect(getFetchMock()).toHaveBeenCalledTimes(1);
      expect(makeRequest).toHaveBeenCalledTimes(2);
      expect(makeRequest).toHaveBeenNthCalledWith(1, "stale-access-token");
      expect(makeRequest).toHaveBeenNthCalledWith(2, "refreshed-access-token");
      expect(result).toEqual({
        status: 200,
        accessToken: "refreshed-access-token",
      });
    });
  });

  describe("AUTH-05-TC-04 -- non-2xx refresh clears the session and signals SessionExpiredError", () => {
    it("ensureTokenValid()'s proactive refresh clears the cookie and rejects with SessionExpiredError, never the raw upstream body/status", async () => {
      await tokenStore.writeSession({
        access_token: "expiring-access-token",
        refresh_token: "expired-refresh-token",
        expires_in: 45,
      });
      expect(
        mockCookieStore.jar.get(tokenStore.SESSION_COOKIE_NAME),
      ).not.toBeUndefined();

      const upstreamBody = "invalid_grant: refresh token expired";
      getFetchMock().mockResolvedValueOnce(
        new Response(upstreamBody, { status: 401 }),
      );

      let caught: unknown;
      try {
        await tokenStore.ensureTokenValid();
      } catch (error) {
        caught = error;
      }

      expect(caught).toBeInstanceOf(tokenStore.SessionExpiredError);
      const message = caught instanceof Error ? caught.message : "";
      expect(message).not.toContain(upstreamBody);
      expect(message).not.toContain("401");
      expect(
        mockCookieStore.jar.get(tokenStore.SESSION_COOKIE_NAME),
      ).toBeUndefined();
    });

    it("callWithAuth's reactive refresh clears the cookie and rejects with SessionExpiredError without a second makeRequest attempt", async () => {
      await tokenStore.writeSession({
        access_token: "stale-access-token",
        refresh_token: "stale-refresh-token",
        expires_in: 3600,
      });

      getFetchMock().mockResolvedValueOnce(
        new Response("server_error", { status: 500 }),
      );

      const makeRequest = vi.fn().mockResolvedValueOnce({ status: 401 });
      const isUnauthorized = (result: { status: number }) =>
        result.status === 401;

      await expect(
        tokenStore.callWithAuth(makeRequest, isUnauthorized),
      ).rejects.toBeInstanceOf(tokenStore.SessionExpiredError);

      expect(makeRequest).toHaveBeenCalledTimes(1);
      expect(
        mockCookieStore.jar.get(tokenStore.SESSION_COOKIE_NAME),
      ).toBeUndefined();
    });
  });
});
