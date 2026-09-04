import { cookies } from "next/headers";

import { getApiBaseUrl } from "@/lib/apiConfig";

/**
 * Server-only session/token store (AUTH-05).
 *
 * Owns the `dashboard_session` httpOnly cookie (DECISIONS.md D-01/FR-4) and
 * the token-refresh lifecycle. Imports `next/headers`, which Next.js only
 * resolves in a server context (Server Component, Route Handler, Server
 * Action) -- this module must never be imported from a `"use client"`
 * component; there is no client-readable path to a token anywhere here.
 *
 * FR-1 single-flight refresh guard: a single module-level `refreshPromise`
 * ensures at most one `POST /auth/refresh` call is ever in flight. Every
 * caller that needs a fresh token -- the proactive 60s-skew check inside
 * `ensureTokenValid()` and the reactive 401 retry inside `callWithAuth()` --
 * routes through `refreshSession()`; a caller that finds a refresh already
 * in flight awaits that same promise instead of starting its own. This
 * guard is per-Node-process only (DECISIONS.md D-07): a multi-instance /
 * multi-worker deployment dedupes refreshes within each process, not across
 * processes, matching the same documented caveat as FastAPI's own
 * `OAuthStateStore`. That is an accepted tradeoff, not a defect -- the
 * cookie write is the actual serialization point, so a cross-process race
 * costs at most one harmless extra refresh call, never a torn token.
 *
 * FR-5 refresh-failure chain: any non-2xx response from `POST /auth/refresh`,
 * or a throw/timeout while calling it, clears the session cookie and throws
 * `SessionExpiredError` -- the upstream response body/status and any thrown
 * error are never surfaced to a caller or logged. Callers (Route Handlers,
 * `page.tsx`) are expected to catch `SessionExpiredError` and redirect the
 * browser to `/login`.
 *
 * No line in this module logs a token, cookie value, refresh response body,
 * or upstream error body (NFR-security) -- this module deliberately emits no
 * log output at all.
 *
 * Read-only-cookies honesty note (AF-01): `cookies().set()`/`.delete()` only
 * take effect when called from a Route Handler or Server Action -- Next.js
 * seals the jar read-only during a plain Server Component render (e.g.
 * `page.tsx`) and throws if a mutation is attempted there. Because `page.tsx`
 * calls into this module via `callWithAuth()`/`ensureTokenValid()`, a refresh
 * triggered mid-render uses the refreshed token pair for that render but
 * cannot persist it -- the next request simply refreshes again from the
 * still-stored (pre-refresh) refresh token. This is harmless with Keycloak's
 * default (refresh-token rotation/"Revoke Refresh Token" OFF, old refresh
 * token stays reusable). If that Keycloak setting is turned ON, refresh
 * tokens rotate on every use and the unpersisted replacement is lost,
 * ending the session early on the next refresh attempt.
 */

export const SESSION_COOKIE_NAME = "dashboard_session";

/** Milliseconds before `expiresAt` at which `ensureTokenValid()` proactively refreshes (FR-1). */
const PROACTIVE_REFRESH_SKEW_MS = 60_000;

/**
 * `.claude/rules/performance-baseline.md`: every I/O call has an explicit
 * timeout, no silent infinite wait. Matches `programDetailApi.ts`'s
 * `FETCH_TIMEOUT_MS` precedent.
 */
const REFRESH_TIMEOUT_MS = 5000;

/** FastAPI `/auth/*` response shape (AUTH-01), snake_case on the wire. */
export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  expires_in: number;
}

/** Cookie payload (DECISIONS.md D-01), camelCase in the store. */
export interface StoredSession {
  accessToken: string;
  refreshToken: string;
  /** Absolute ms epoch, = Date.now() + expires_in * 1000 at write time (AC-9). */
  expiresAt: number;
}

/**
 * Thrown by `ensureTokenValid()`/`getValidAccessToken()`/`callWithAuth()`
 * when no valid session can be produced -- either no session cookie exists,
 * or refreshing it failed unrecoverably (FR-5). Callers redirect to `/login`.
 */
export class SessionExpiredError extends Error {}

/** Module-level single-flight guard (FR-1, D-07) -- see module docstring. */
let refreshPromise: Promise<StoredSession> | null = null;

function toStoredSession(tokens: TokenResponse): StoredSession {
  return {
    accessToken: tokens.access_token,
    refreshToken: tokens.refresh_token,
    expiresAt: Date.now() + tokens.expires_in * 1000,
  };
}

function isStoredSessionShape(value: unknown): value is StoredSession {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const candidate = value as Record<string, unknown>;
  return (
    typeof candidate.accessToken === "string" &&
    typeof candidate.refreshToken === "string" &&
    typeof candidate.expiresAt === "number"
  );
}

/**
 * Attempts a `cookies()` mutation (`.set()`/`.delete()`) and tolerates
 * exactly one documented failure: Next.js throws when a mutation is
 * attempted during a plain Server Component render (AF-01) because the jar
 * is sealed read-only there (only a Route Handler / Server Action may
 * write). That failure is swallowed here on purpose -- see the module
 * docstring's "Read-only-cookies honesty note" -- so a refresh triggered
 * from `page.tsx` doesn't crash the render; it is NOT a blanket error
 * swallow for unrelated mutation bugs.
 */
function tryMutateCookie(mutate: () => void): void {
  try {
    mutate();
  } catch {
    // Read-only cookies() jar during a Server Component render -- see
    // tryMutateCookie()'s docstring and the module's AF-01 note above.
  }
}

async function persistTokens(tokens: TokenResponse): Promise<StoredSession> {
  const session = toStoredSession(tokens);
  const serialized = JSON.stringify(session);
  const cookieStore = await cookies();
  tryMutateCookie(() =>
    cookieStore.set(SESSION_COOKIE_NAME, serialized, {
      httpOnly: true,
      sameSite: "lax",
      path: "/",
      secure: process.env.NODE_ENV === "production",
    }),
  );
  return session;
}

/** Writes `tokens` into the `dashboard_session` cookie (D-01/FR-4). */
export async function writeSession(tokens: TokenResponse): Promise<void> {
  await persistTokens(tokens);
}

/**
 * Reads and parses the `dashboard_session` cookie. Returns `null` on an
 * absent or unparseable cookie -- never throws (D-01); a corrupt cookie is
 * treated identically to "no session".
 */
export async function readSession(): Promise<StoredSession | null> {
  const cookieStore = await cookies();
  const cookie = cookieStore.get(SESSION_COOKIE_NAME);
  if (cookie === undefined) {
    return null;
  }
  try {
    const parsed: unknown = JSON.parse(cookie.value);
    return isStoredSessionShape(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

/**
 * Clears the `dashboard_session` cookie. Tolerates the read-only-jar case
 * (AF-01, `tryMutateCookie()`) -- callers (notably `doRefresh()`) must still
 * see this resolve normally so their own `SessionExpiredError` throw is not
 * masked by a cookie-mutation error.
 */
export async function clearSession(): Promise<void> {
  const cookieStore = await cookies();
  tryMutateCookie(() => cookieStore.delete(SESSION_COOKIE_NAME));
}

/**
 * `POST /auth/refresh` -- the sole implementation of a refresh attempt.
 * Only ever invoked through `refreshSession()`'s single-flight guard.
 *
 * On 2xx, persists and returns the new session. On any non-2xx response, or
 * a throw/timeout at any step (network failure, abort, malformed body),
 * clears the session and throws `SessionExpiredError` -- the upstream body
 * or error is never surfaced or logged (FR-5/AC-8, TC-04).
 */
async function doRefresh(refreshToken: string): Promise<StoredSession> {
  try {
    const response = await fetch(`${getApiBaseUrl()}/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refreshToken }),
      signal: AbortSignal.timeout(REFRESH_TIMEOUT_MS),
    });
    if (!response.ok) {
      throw new Error("auth_refresh_rejected");
    }
    const tokens = (await response.json()) as TokenResponse;
    return await persistTokens(tokens);
  } catch {
    await clearSession();
    throw new SessionExpiredError("Session refresh failed; sign-in required.");
  }
}

/**
 * Single-flight wrapper around `doRefresh()` (FR-1, D-07). A caller that
 * finds a refresh already in flight awaits that same promise instead of
 * issuing its own `POST /auth/refresh`; the `finally` clears the guard on
 * both the success and failure paths so a failed refresh never wedges later
 * callers on a dead promise.
 */
function refreshSession(refreshToken: string): Promise<StoredSession> {
  if (refreshPromise === null) {
    refreshPromise = doRefresh(refreshToken).finally(() => {
      refreshPromise = null;
    });
  }
  return refreshPromise;
}

/**
 * Proactive 60s-skew check + FR-1 single-flight refresh. Throws
 * `SessionExpiredError` when no session exists or refreshing it fails.
 */
export async function ensureTokenValid(): Promise<StoredSession> {
  const session = await readSession();
  if (session === null) {
    throw new SessionExpiredError("No session cookie present.");
  }
  const msRemaining = session.expiresAt - Date.now();
  if (msRemaining > PROACTIVE_REFRESH_SKEW_MS) {
    return session;
  }
  return refreshSession(session.refreshToken);
}

/** `(await ensureTokenValid()).accessToken` (AC-6). */
export async function getValidAccessToken(): Promise<string> {
  return (await ensureTokenValid()).accessToken;
}

/**
 * D-03/AC-7 reactive-401 retry-once. Resolves a valid token (proactive
 * check via `getValidAccessToken()`), invokes `makeRequest`, and on
 * `isUnauthorized(result)` forces exactly one refresh through the same
 * single-flight guard as the proactive path, then retries `makeRequest`
 * exactly once with the refreshed token. Never loops.
 */
export async function callWithAuth<T>(
  makeRequest: (accessToken: string) => Promise<T>,
  isUnauthorized: (result: T) => boolean,
): Promise<T> {
  const accessToken = await getValidAccessToken();
  const result = await makeRequest(accessToken);
  if (!isUnauthorized(result)) {
    return result;
  }

  const session = await readSession();
  if (session === null) {
    throw new SessionExpiredError("No session cookie present.");
  }
  const refreshed = await refreshSession(session.refreshToken);
  return makeRequest(refreshed.accessToken);
}
