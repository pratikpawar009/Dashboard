import { NextResponse } from "next/server";

import { getApiBaseUrl } from "@/lib/apiConfig";
import {
  clearSession,
  writeSession,
  type TokenResponse,
} from "@/lib/tokenStore";

/**
 * `.claude/rules/performance-baseline.md`: every I/O call has an explicit
 * timeout, no silent infinite wait. Matches `login/route.ts`'s
 * `FETCH_TIMEOUT_MS` precedent.
 */
const FETCH_TIMEOUT_MS = 5000;

/**
 * `GET /callback` -- server-to-server relay to FastAPI `GET /auth/callback`
 * (AUTH-05-AC-3/AC-4, DATA-DESIGN.md § 9).
 *
 * This handler is the only place a `Set-Cookie` for this feature can
 * originate: FastAPI's `/auth/callback` returns a JSON token body, never a
 * `Set-Cookie` (REQUIREMENTS.md § Constraints) -- no client-side page ever
 * receives or parses that JSON (AC-3), it only ever reaches this
 * server-to-server relay.
 *
 * Only the query params Keycloak actually sent (`code`, `state`, `error`)
 * are forwarded -- never an empty/`null` value for an absent one, since
 * FastAPI treats `state` as required (`400 invalid_state` if absent, unknown,
 * already used, or expired) and `missing_code` when neither `code` nor
 * `error` is present.
 *
 * On FastAPI `200`, the token JSON is handed straight to
 * `tokenStore.writeSession()` and the browser is redirected to `/`
 * (DECISIONS.md D-04). On any non-200 response, or a thrown/timed-out
 * fetch, the session cookie is cleared and the browser is redirected to
 * `/login` -- FastAPI's status, body, or a thrown error is never surfaced
 * (AC-3/D-04).
 *
 * No line in this file logs the code, the state, the token response, or the
 * upstream error body (NFR-security).
 */
export async function GET(request: Request): Promise<NextResponse> {
  const incoming = new URL(request.url);
  const upstream = new URL(`${getApiBaseUrl()}/auth/callback`);
  for (const key of ["code", "state", "error"]) {
    const value = incoming.searchParams.get(key);
    if (value !== null) {
      upstream.searchParams.set(key, value);
    }
  }

  try {
    const response = await fetch(upstream, {
      signal: AbortSignal.timeout(FETCH_TIMEOUT_MS),
    });

    if (!response.ok) {
      await clearSession();
      return NextResponse.redirect(new URL("/login", request.url));
    }

    const tokens = (await response.json()) as TokenResponse;
    await writeSession(tokens);
    return NextResponse.redirect(new URL("/", request.url));
  } catch {
    await clearSession();
    return NextResponse.redirect(new URL("/login", request.url));
  }
}
